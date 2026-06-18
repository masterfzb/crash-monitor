"""
崩溃现场报告器 — 独立工具，不依赖 crash-monitor 运行。

用途: 神授重启/恢复后，跑这个脚本立刻生成结构化状态报告。
零依赖，仅标准库。PowerShell 环境也可用。

用法:
  python crash_report.py              # 文本报告（适合聊天发送）
  python crash_report.py --json       # JSON 输出
  python crash_report.py --live       # 附加实时系统检查（sc query + tasklist）
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── 配置（可改）──
DATA_DIR = Path(os.environ.get("CRASH_MONITOR_DATA", "D:\\crash-monitor"))
LOG_DIR = DATA_DIR / "logs"
STATUS_DIR = DATA_DIR / "status"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
WATCHDOG_LOG = LOG_DIR / "watchdog_events.log"
HEARTBEAT_FILE = STATUS_DIR / "heartbeat.txt"
STATUS_FILE = STATUS_DIR / "status.json"


def now():
    return datetime.now(timezone.utc).astimezone()


def read_heartbeat() -> dict:
    """读取最后一次心跳."""
    result = {"heartbeat_file_exists": False, "last_heartbeat": None, "seconds_ago": None}
    if not HEARTBEAT_FILE.exists():
        result["error"] = f"心跳文件不存在: {HEARTBEAT_FILE}"
        return result

    result["heartbeat_file_exists"] = True
    try:
        lines = HEARTBEAT_FILE.read_text(encoding="utf-8").strip().split("\n")
        if lines:
            last_line = lines[-1]
            parts = last_line.split("|")
            if parts:
                result["last_heartbeat"] = parts[0].strip()
                try:
                    hb_time = datetime.fromisoformat(result["last_heartbeat"])
                    delta = now() - hb_time
                    result["seconds_ago"] = int(delta.total_seconds())
                    result["minutes_ago"] = round(delta.total_seconds() / 60, 1)
                    if delta.total_seconds() > 300:
                        result["warning"] = (
                            f"⚠️ 最后心跳是 {result['minutes_ago']} 分钟前，"
                            f"看门狗可能已经死了"
                        )
                except Exception:
                    pass
    except Exception as e:
        result["error"] = str(e)
    return result


def list_snapshots() -> dict:
    """列出最近的故障快照."""
    result = {"snapshots": [], "count": 0, "latest": None}
    if not SNAPSHOT_DIR.exists():
        result["error"] = f"快照目录不存在: {SNAPSHOT_DIR}"
        return result

    try:
        files = sorted(SNAPSHOT_DIR.glob("snapshot_*.json"), reverse=True)
        result["count"] = len(files)
        for f in files[:5]:
            info = {"file": f.name, "size": f.stat().st_size, "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
            # 提取触发原因
            parts = f.stem.split("_", 2)
            info["trigger"] = parts[-1] if len(parts) > 2 else f.stem
            result["snapshots"].append(info)

        if result["snapshots"]:
            result["latest"] = result["snapshots"][0]
            # 读取最新快照的关键信息
            latest_file = SNAPSHOT_DIR / result["snapshots"][0]["file"]
            try:
                data = json.loads(latest_file.read_text(encoding="utf-8"))
                result["latest_summary"] = {
                    "timestamp": data.get("timestamp", ""),
                    "trigger": data.get("trigger", ""),
                    "service_count": len(data.get("services", [])),
                    "process_count": len(data.get("processes", [])),
                    "running_proc_count": len(data.get("running_processes", [])),
                }
                # 提取挂掉的服务和进程
                dead_services = [s for s in data.get("services", []) if s.get("status") != "running"]
                dead_processes = [p for p in data.get("processes", []) if not p.get("running")]
                result["latest_summary"]["dead_services"] = [
                    {"name": s["name"], "display": s.get("display", s["name"]), "status": s["status"]}
                    for s in dead_services
                ]
                result["latest_summary"]["dead_processes"] = [
                    {"name": p["name"], "display": p.get("display", p["name"])}
                    for p in dead_processes
                ]
            except Exception as e:
                result["latest_summary"] = {"error": str(e)}

    except Exception as e:
        result["error"] = str(e)
    return result


def read_recent_events(n: int = 30) -> dict:
    """读取最近的事件."""
    result = {"events": [], "count": 0, "errors": 0, "warns": 0}
    if not WATCHDOG_LOG.exists():
        result["error"] = f"事件日志不存在: {WATCHDOG_LOG}"
        return result

    try:
        lines = WATCHDOG_LOG.read_text(encoding="utf-8").strip().split("\n")
        result["total_lines"] = len(lines)
        recent = lines[-n:]

        for line in recent:
            level = "INFO"
            if "[ERROR]" in line:
                level = "ERROR"
                result["errors"] += 1
            elif "[WARN]" in line:
                level = "WARN"
                result["warns"] += 1

            # 提取时间和内容
            time_str = ""
            msg = line
            if line.startswith("[") and "]" in line:
                bracket_end = line.index("]", 1)
                time_str = line[1:bracket_end]
                rest = line[bracket_end + 1:]
                if "] " in rest:
                    msg = rest[rest.index("] ") + 2:]
                else:
                    msg = rest

            result["events"].append({"time": time_str, "level": level, "message": msg[:200]})
        result["count"] = len(result["events"])
    except Exception as e:
        result["error"] = str(e)
    return result


def read_status_json() -> dict:
    """读取最新状态 JSON."""
    if not STATUS_FILE.exists():
        return {"error": f"状态文件不存在: {STATUS_FILE}"}

    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": str(e)}


def live_check() -> dict:
    """实时执行系统检查（仅 Windows）."""
    result = {"services": {}, "processes": {}}
    if os.name != "nt":
        result["error"] = "live_check 仅支持 Windows"
        return result

    import subprocess
    # 关键服务
    key_services = ["DcomLaunch", "RpcSs", "EventLog", "ShellHWDetection", "Power", "BFE"]
    for svc in key_services:
        try:
            r = subprocess.run(
                ["sc", "query", svc],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            out = r.stdout + r.stderr
            if "RUNNING" in out.upper():
                result["services"][svc] = "running"
            elif "STOP" in out.upper():
                result["services"][svc] = "stopped"
            else:
                result["services"][svc] = "unknown"
        except Exception as e:
            result["services"][svc] = f"error:{e}"

    # 关键进程
    key_procs = ["explorer.exe", "StartMenuExperienceHost.exe", "ShellExperienceHost.exe"]
    try:
        r = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for proc in key_procs:
            result["processes"][proc] = proc.lower() in r.stdout.lower()
    except Exception as e:
        result["processes"]["error"] = str(e)

    return result


def build_report(json_output: bool = False, with_live: bool = False) -> str | dict:
    """构建完整报告."""
    hb = read_heartbeat()
    snap = list_snapshots()
    events = read_recent_events(40)
    status = read_status_json()

    live = None
    if with_live:
        live = live_check()

    if json_output:
        return {
            "report_time": now().isoformat(),
            "heartbeat": hb,
            "snapshots": snap,
            "events": events,
            **({"live_check": live} if live else {}),
        }

    # ── 文本报告 ──
    lines = []
    lines.append("=" * 50)
    lines.append("💥 Crash Monitor 现场报告")
    lines.append(f"   生成时间: {now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 50)

    # 1. 心跳
    lines.append("\n── 存活心跳 ──")
    if hb.get("last_heartbeat"):
        lines.append(f"   最后心跳: {hb['last_heartbeat']}")
        if hb.get("seconds_ago") is not None:
            if hb["seconds_ago"] < 60:
                lines.append(f"   距现在: {hb['seconds_ago']} 秒 → 🟢 看门狗活着")
            elif hb["seconds_ago"] < 300:
                lines.append(f"   距现在: {hb['minutes_ago']} 分钟 → 🟡 有点久了")
            else:
                lines.append(f"   距现在: {hb['minutes_ago']} 分钟 → 🔴 看门狗可能已死")
    else:
        lines.append(f"   ❌ 没有心跳数据 ({hb.get('error', '未知')})")

    # 2. 最近快照
    lines.append("\n── 故障快照 ──")
    if snap.get("count", 0) > 0:
        lines.append(f"   共 {snap['count']} 个快照")
        if snap.get("latest_summary"):
            s = snap["latest_summary"]
            lines.append(f"   最新: {s.get('timestamp', '?')}")
            lines.append(f"   触发: {s.get('trigger', '?')}")
            dead_svcs = s.get("dead_services", [])
            dead_procs = s.get("dead_processes", [])
            if dead_svcs:
                lines.append(f"   💀 异常服务: {len(dead_svcs)} 个")
                for ds in dead_svcs:
                    lines.append(f"      - {ds['display']} ({ds['name']}) → {ds['status']}")
            if dead_procs:
                lines.append(f"   💀 死亡进程: {len(dead_procs)} 个")
                for dp in dead_procs:
                    lines.append(f"      - {dp['display']} ({dp['name']})")
    else:
        lines.append("   ✅ 没有故障快照（系统尚未触发过异常）")

    # 3. 最近事件
    lines.append(f"\n── 最近事件 (最近 {events.get('count', 0)} 条) ──")
    lines.append(f"   ERROR: {events.get('errors', 0)} | WARN: {events.get('warns', 0)}")
    for e in events.get("events", []):
        marker = {"ERROR": "🔴", "WARN": "🟡", "INFO": "Ⓜ️"}.get(e["level"], "  ")
        lines.append(f"   {marker} [{e['time']}] {e['message']}")

    # 4. 实时检查
    if live:
        lines.append("\n── 实时系统检查 ──")
        if live.get("services"):
            lines.append("   Windows 服务:")
            for k, v in live["services"].items():
                icon = {"running": "🟢", "stopped": "🔴"}.get(v, "❓")
                lines.append(f"     {icon} {k}: {v}")
        if live.get("processes"):
            lines.append("   关键进程:")
            for k, v in live["processes"].items():
                icon = "🟢" if v else "🔴"
                lines.append(f"     {icon} {k}: {'存活' if v else '死亡'}")

    lines.append("\n" + "=" * 50)
    return "\n".join(lines)


def main():
    json_output = "--json" in sys.argv
    with_live = "--live" in sys.argv

    report = build_report(json_output=json_output, with_live=with_live)
    if json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(report)


if __name__ == "__main__":
    main()
