"""服务监控器 — 监控单个服务的运行状态."""

import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .logger import get_logger

log = get_logger(__name__)

# 设置本地时区
TZ = datetime.now().astimezone().tzinfo or timezone.utc


@dataclass
class CrashRecord:
    """崩溃记录."""
    service_name: str
    timestamp: datetime
    exit_code: Optional[int] = None
    signal_num: Optional[int] = None
    restart_count: int = 0
    note: str = ""


@dataclass
class ServiceWatcher:
    """单个服务的监控器."""

    config: dict
    alerter: object  # Alerter
    process: Optional[subprocess.Popen] = None
    crash_history: list[CrashRecord] = field(default_factory=list)
    restart_count: int = 0
    _running: bool = False

    @property
    def name(self) -> str:
        return self.config["name"]

    def start(self):
        """启动被监控的服务进程."""
        command = self.config["command"]
        cwd = self.config.get("working_dir")

        log.info(f"[{self.name}] 启动进程: {command}")

        self.process = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid if os.name != "nt" else None,
        )

        # 写 PID 文件
        pid_file = self.config.get("pid_file")
        if pid_file:
            with open(pid_file, "w") as f:
                f.write(str(self.process.pid))

        self._running = True
        log.info(f"[{self.name}] 进程已启动, PID={self.process.pid}")

    def stop(self):
        """停止被监控的服务."""
        self._running = False
        if self.process and self.process.poll() is None:
            log.info(f"[{self.name}] 停止进程 PID={self.process.pid}")
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def check(self):
        """检查服务状态，处理崩溃."""
        if not self._running or self.process is None:
            return

        # 检查进程是否还在运行
        returncode = self.process.poll()
        if returncode is not None:
            # 进程已退出 → 崩溃
            self._handle_crash(returncode)

        # 健康检查（如果配置了）
        self._health_check()

    def _handle_crash(self, exit_code: int):
        """处理崩溃事件."""
        now = datetime.now(TZ)
        record = CrashRecord(
            service_name=self.name,
            timestamp=now,
            exit_code=exit_code,
            restart_count=self.restart_count + 1,
        )
        self.crash_history.append(record)

        log.error(
            f"[{self.name}] 💥 崩溃! exit_code={exit_code}, "
            f"这是第 {record.restart_count} 次崩溃"
        )

        # 发送告警
        self.alerter.send_crash_alert(record)

        # 自动重启
        restart_cfg = self.config.get("restart", {})
        if restart_cfg.get("enabled", True):
            max_restarts = restart_cfg.get("max_restarts", 5)
            cooldown = restart_cfg.get("cooldown_seconds", 10)

            if self.restart_count < max_restarts:
                log.info(
                    f"[{self.name}] {cooldown}s 后重启 "
                    f"({self.restart_count + 1}/{max_restarts})"
                )
                time.sleep(cooldown)
                self.restart_count += 1
                self.start()
            else:
                log.error(
                    f"[{self.name}] 已达最大重启次数 ({max_restarts})，停止自动恢复"
                )
                self._running = False
                self.alerter.send_crash_alert(record, exhausted=True)

    def _health_check(self):
        """HTTP 健康检查."""
        hc = self.config.get("health_check", {})
        if hc.get("type") != "http":
            return

        url = hc.get("url")
        if not url:
            return

        try:
            import urllib.request

            req = urllib.request.Request(url)
            timeout = hc.get("timeout_seconds", 5)
            urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            log.warning(f"[{self.name}] 健康检查失败: {url} → {e}")
