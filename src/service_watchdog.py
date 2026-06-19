"""
Windows 服务看门狗 — 监控关键系统服务 & 进程存活状态。

针对"电脑活着但开始菜单和关机废了"这种内核级静默故障。
所有日志 / 状态文件强制写入非 C 盘，防止磁盘通路被锁时丢证据。

设计原则:
- 零外部依赖，仅 Python 标准库
- 多通道检测：Windows 服务 API + 进程存活 + 功能可用性
- 故障快照：出问题时自动捕获系统状态完整快照
- 心跳文件：独立于日志的存活证明，写入指定盘符
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import Thread, Event
from typing import Optional

from .logger import get_logger

log = get_logger(__name__, "crash-monitor-service-watchdog.log")

# ── 数据模型 ───────────────────────────────────────────


@dataclass
class ServiceState:
    """单个 Windows 服务的当前状态."""
    name: str
    display: str
    status: str = "unknown"       # running | stopped | dead
    critical: bool = False
    last_checked: str = ""
    error: str = ""


@dataclass
class ProcessState:
    """关键进程的存活状态."""
    name: str
    display: str
    running: bool = False
    pid: int = 0
    critical: bool = False
    last_checked: str = ""


@dataclass
class SystemCheck:
    """系统功能可用性检查."""
    name: str
    display: str
    passed: bool = False
    error: str = ""
    last_checked: str = ""


@dataclass
class WatchdogSnapshot:
    """故障时刻的系统快照."""
    timestamp: str
    trigger: str                    # 触发原因
    services: list[dict] = field(default_factory=list)
    processes: list[dict] = field(default_factory=list)
    system_checks: list[dict] = field(default_factory=list)
    running_processes: list[str] = field(default_factory=list)
    recent_events: list[dict] = field(default_factory=list)


# ── 看门狗核心 ──────────────────────────────────────────


class WindowsServiceWatchdog:
    """Windows 关键服务 & 进程看门狗."""

    # 默认监控的关键 Windows 服务
    DEFAULT_SERVICES = [
        ("DcomLaunch", "DCOM 服务启动器", True),
        ("RpcSs", "RPC 远程调用", True),
        ("EventLog", "Windows 事件日志", True),
        ("ShellHWDetection", "Shell 硬件检测", True),
        ("UserManager", "用户管理器", True),
        ("BFE", "基础过滤引擎", True),
        ("Power", "电源服务", True),
        ("CoreMessagingRegistrar", "核心消息注册", True),
        ("StateRepository", "状态存储库", True),
        ("WpnUserService", "通知推送服务", False),
    ]

    # 默认监控的关键进程
    DEFAULT_PROCESSES = [
        ("explorer.exe", "资源管理器 (Shell)", True),
        ("StartMenuExperienceHost.exe", "开始菜单宿主", True),
        ("SearchHost.exe", "搜索服务", False),
        ("ShellExperienceHost.exe", "Shell 体验宿主", True),
        ("SystemSettings.exe", "系统设置", False),
    ]

    # 系统功能可用性检查
    DEFAULT_SYSTEM_CHECKS = [
        ("shutdown_accessible", "关机命令可用",
         "shutdown /? >nul 2>&1" if os.name == "nt" else "true"),
        ("taskbar_responding", "任务栏响应",
         # 通过检查 explorer 托盘窗口句柄间接判断
         None),
    ]

    def __init__(self, config: dict, alerter=None):
        self.config = config
        self.alerter = alerter
        self._stop_event = Event()

        # 心跳 & 日志路径（强制非 C 盘）
        watchdog_cfg = config.get("windows_service_watchdog", {})
        self.heartbeat_interval = int(watchdog_cfg.get("heartbeat_interval", 5))
        self.log_dir = Path(watchdog_cfg.get("log_dir", "D:\\crash-monitor\\logs"))
        self.status_dir = Path(watchdog_cfg.get("status_dir", "D:\\crash-monitor\\status"))
        self.snapshot_dir = Path(watchdog_cfg.get("snapshot_dir", "D:\\crash-monitor\\snapshots"))

        # 确保目录存在
        for d in [self.log_dir, self.status_dir, self.snapshot_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # 加载监控目标
        self.services = self._load_services(watchdog_cfg)
        self.processes = self._load_processes(watchdog_cfg)
        self.system_checks = self._load_system_checks(watchdog_cfg)

        # 状态跟踪
        self.events: list[dict] = []      # 最近事件
        self.max_events = 200
        self._last_all_healthy = True     # 用于检测从健康→故障的转换

        # 聚合日志文件
        self.watchdog_log = self.log_dir / "watchdog_events.log"

        log.info(
            f"看门狗已初始化 | 服务:{len(self.services)} "
            f"进程:{len(self.processes)} 系统检查:{len(self.system_checks)}"
        )
        log.info(f"日志目录: {self.log_dir}")
        self._log_event("INIT", f"看门狗启动, 监控 {len(self.services)} 服务 + {len(self.processes)} 进程")

    # ── 配置加载 ─────────────────────────────────

    def _load_services(self, cfg: dict) -> list[ServiceState]:
        items = cfg.get("services", [])
        if not items:
            items = [
                {"name": n, "display": d, "critical": c}
                for n, d, c in self.DEFAULT_SERVICES
            ]
        return [
            ServiceState(
                name=s["name"], display=s.get("display", s["name"]),
                critical=s.get("critical", False)
            )
            for s in items
        ]

    def _load_processes(self, cfg: dict) -> list[ProcessState]:
        items = cfg.get("processes", [])
        if not items:
            items = [
                {"name": n, "display": d, "critical": c}
                for n, d, c in self.DEFAULT_PROCESSES
            ]
        return [
            ProcessState(
                name=p["name"], display=p.get("display", p["name"]),
                critical=p.get("critical", False)
            )
            for p in items
        ]

    def _load_system_checks(self, cfg: dict) -> list[SystemCheck]:
        items = cfg.get("system_checks", [])
        if not items:
            items = [
                {"name": n, "display": d}
                for n, d, *_ in self.DEFAULT_SYSTEM_CHECKS
            ]
        return [
            SystemCheck(name=c["name"], display=c.get("display", c["name"]))
            for c in items
        ]

    # ── 检测逻辑 ─────────────────────────────────

    def _query_service(self, service_name: str) -> tuple[str, str]:
        """查询 Windows 服务状态.

        Returns:
            (status, error) — status 为 running/stopped/unknown
        """
        try:
            result = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            output = result.stdout + result.stderr
            # "RUNNING" / "STOPPED" / "STOP_PENDING" 等
            if "RUNNING" in output.upper():
                return ("running", "")
            elif "STOP" in output.upper():
                return ("stopped", "")
            elif "1060" in output:
                return ("dead", f"服务 {service_name} 不存在 (1060)")
            else:
                return ("unknown", output.strip()[:200])
        except subprocess.TimeoutExpired:
            return ("unknown", "查询超时")
        except Exception as e:
            return ("unknown", str(e))

    def _check_process(self, process_name: str) -> tuple[bool, int]:
        """检查进程是否在运行.

        Returns:
            (running, pid)
        """
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {process_name}",
                     "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if process_name.lower() in result.stdout.lower():
                    # 解析 PID
                    for line in result.stdout.strip().split("\n"):
                        if process_name.lower() in line.lower():
                            parts = line.replace('"', "").split(",")
                            if len(parts) >= 2:
                                try:
                                    return (True, int(parts[1].strip()))
                                except ValueError:
                                    return (True, 0)
                    return (True, 0)
                return (False, 0)
            else:
                # 非 Windows: 用 pgrep
                result = subprocess.run(
                    ["pgrep", "-f", process_name],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    pids = result.stdout.strip().split("\n")
                    return (True, int(pids[0]) if pids[0] else 0)
                return (False, 0)
        except Exception as e:
            log.debug(f"检查进程 {process_name} 失败: {e}")
            return (False, 0)

    def _check_shutdown_accessible(self) -> tuple[bool, str]:
        """测试 shutdown 命令是否可用 — 检查 shutdown.exe 文件是否存在."""
        try:
            import shutil
            shutdown_path = shutil.which("shutdown") or (
                r"C:\Windows\System32\shutdown.exe" if os.name == "nt" else "/sbin/shutdown"
            )
            if os.path.exists(shutdown_path):
                return (True, f"shutdown.exe 存在 ({shutdown_path})")
            return (False, f"shutdown.exe 未找到")
        except Exception as e:
            return (False, str(e))

    def _check_taskbar(self) -> tuple[bool, str]:
        """检查任务栏/开始菜单进程是否存活（间接判断响应性）."""
        # 检查开始菜单是否至少进程还在
        running, pid = self._check_process("StartMenuExperienceHost.exe")
        if not running:
            running, pid = self._check_process("explorer.exe")
        if running:
            return (True, f"Shell 进程存活 (PID:{pid})")
        return (False, "Shell 宿主进程全部死亡")

    def _capture_running_processes(self) -> list[str]:
        """获取当前运行的进程列表（故障快照用）."""
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["tasklist", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                # 只取进程名
                procs = []
                for line in result.stdout.strip().split("\n"):
                    parts = line.replace('"', "").split(",")
                    if parts:
                        procs.append(parts[0].strip())
                return procs[:500]  # 限制数量
            else:
                result = subprocess.run(
                    ["ps", "aux", "--no-headers"],
                    capture_output=True, text=True, timeout=15,
                )
                return result.stdout.strip().split("\n")[:500]
        except Exception:
            return []

    # ── 心跳 & 日志 ─────────────────────────────────

    def _write_heartbeat(self):
        """写入心跳文件（独立于普通日志的存在证明）."""
        hb_file = self.status_dir / "heartbeat.txt"
        try:
            now = datetime.now(timezone.utc).astimezone()
            hb_file.write_text(
                f"{now.isoformat(timespec='seconds')} | alive | "
                f"pid={os.getpid()}\n",
                encoding="utf-8",
            )
        except Exception as e:
            log.error(f"心跳写入失败! 磁盘可能已锁: {e}")

    def _write_status_json(self, services, processes, checks):
        """写入状态 JSON 供仪表板消费."""
        status_file = self.status_dir / "status.json"
        try:
            status_file.write_text(json.dumps({
                "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
                "services": [asdict(s) for s in services],
                "processes": [asdict(p) for p in processes],
                "system_checks": [asdict(c) for c in checks],
                "events": self.events[-50:],  # 最近 50 条事件
            }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except Exception as e:
            log.error(f"状态 JSON 写入失败: {e}")

    def _log_event(self, level: str, message: str):
        """记录结构化事件."""
        entry = {
            "time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "level": level,
            "message": message,
        }
        self.events.append(entry)
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

        # 写入聚合日志
        try:
            with open(self.watchdog_log, "a", encoding="utf-8") as f:
                f.write(f"[{entry['time']}] [{level}] {message}\n")
        except Exception:
            pass  # 日志写不进去时静默，不级联故障

        # 同时打到标准 logger
        log_fn = {"INFO": log.info, "WARN": log.warning, "ERROR": log.error}
        log_fn.get(level, log.info)(message)

    # ── 故障快照 ─────────────────────────────────

    def _take_snapshot(self, trigger: str, services, processes, checks):
        """捕获故障时刻完整快照."""
        snap = WatchdogSnapshot(
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            trigger=trigger,
            services=[asdict(s) for s in services],
            processes=[asdict(p) for p in processes],
            system_checks=[asdict(c) for c in checks],
            running_processes=self._capture_running_processes(),
            recent_events=self.events[-30:],
        )

        snap_file = self.snapshot_dir / (
            f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{trigger.replace(' ', '_')[:60]}.json"
        )
        try:
            snap_file.write_text(
                json.dumps(asdict(snap), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            log.warning(f"📸 故障快照已保存: {snap_file}")
        except Exception as e:
            log.error(f"快照写入失败: {e}")

    # ── 主检测循环 ─────────────────────────────────

    def _check_all(self) -> tuple[list, list, list, list[str]]:
        """执行全部检测.

        Returns:
            (services, processes, checks, failures)
        """
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        failures = []

        # 1. 检查 Windows 服务
        for svc in self.services:
            status, error = self._query_service(svc.name)
            svc.last_checked = now
            if status != svc.status:
                svc.status = status
                svc.error = error
                self._log_event(
                    "INFO" if status == "running" else "WARN",
                    f"服务 {svc.display}({svc.name}) → {status}",
                )
            if status != "running" and svc.critical:
                failures.append(f"[服务] {svc.display} 状态={status}")

        # 2. 检查关键进程
        for proc in self.processes:
            running, pid = self._check_process(proc.name)
            proc.last_checked = now
            if running != proc.running:
                proc.running = running
                proc.pid = pid
                level = "WARN" if (proc.critical and not running) else "INFO"
                self._log_event(level, f"进程 {proc.display}({proc.name}) → {'存活' if running else '死亡'}")
            if not running and proc.critical:
                failures.append(f"[进程] {proc.display} 已终止")

        # 3. 系统功能检查
        for check in self.system_checks:
            check.last_checked = now
            if check.name == "shutdown_accessible":
                passed, error = self._check_shutdown_accessible()
            elif check.name == "taskbar_responding":
                passed, error = self._check_taskbar()
            else:
                passed, error = (True, "")

            if passed != check.passed:
                check.passed = passed
                check.error = error
                level = "WARN" if (not passed) else "INFO"
                self._log_event(level, f"系统功能 {check.display} → {'正常' if passed else '异常'}")
            if not passed:
                failures.append(f"[系统] {check.display}: {error}")

        return (self.services, self.processes, self.system_checks, failures)

    # ── 公开接口 ───────────────────────────────────

    def check_once(self) -> list[str]:
        """执行一次完整检测，返回故障列表."""
        services, processes, checks, failures = self._check_all()
        self._write_status_json(services, processes, checks)
        return failures

    def run(self):
        """后台运行主循环."""
        log.info("━━━ 看门狗后台监控已启动 ━━━")

        while not self._stop_event.is_set():
            try:
                services, processes, checks, failures = self._check_all()

                # 写心跳 & 状态
                self._write_heartbeat()
                self._write_status_json(services, processes, checks)

                # 判断健康状态变化
                critical_failures = [f for f in failures if "[进程]" in f or
                                     ("[服务]" in f and "dead" in f.lower())]
                currently_healthy = len(critical_failures) == 0

                if not currently_healthy and self._last_all_healthy:
                    # 从健康 → 故障：捕获快照
                    self._log_event("ERROR", f"🚨 系统进入异常状态! 故障数: {len(failures)}")
                    for f in failures:
                        self._log_event("ERROR", f"  └ {f}")
                    self._take_snapshot("CRITICAL_FAILURES", services, processes, checks)

                    # 触发告警
                    if self.alerter:
                        self.alerter.send_service_alert(
                            failures=failures,
                            service_states=[asdict(s) for s in services],
                            process_states=[asdict(p) for p in processes],
                        )

                elif currently_healthy and not self._last_all_healthy:
                    self._log_event("INFO", "✅ 系统恢复正常")
                    if self.alerter:
                        self.alerter.send_service_alert(
                            failures=[], recovered=True,
                        )

                self._last_all_healthy = currently_healthy

            except Exception as e:
                log.error(f"检测循环异常: {e}")
                # 即使异常也尝试写心跳（帮助判断是不是磁盘锁了）
                try:
                    self._write_heartbeat()
                except Exception:
                    pass

            self._stop_event.wait(self.heartbeat_interval)

        log.info("看门狗已停止")

    def start_thread(self) -> Thread:
        """在新线程中启动看门狗."""
        t = Thread(target=self.run, daemon=True, name="ServiceWatchdog")
        t.start()
        return t

    def stop(self):
        """停止看门狗."""
        self._stop_event.set()
        self._log_event("INFO", "看门狗收到停止信号")
