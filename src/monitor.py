"""主监控循环 — 启动服务监控 + Windows 看门狗 + 可视化仪表板."""

import signal
import sys
import time
from pathlib import Path

import yaml

from .watcher import ServiceWatcher
from .alerter import Alerter
from .logger import get_logger

log = get_logger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    """加载配置文件."""
    config_path = Path(path)
    if not config_path.exists():
        log.error(f"配置文件不存在: {config_path.absolute()}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    """主入口."""
    config = load_config()

    alerter = Alerter(config.get("alerts", {}))
    watchers: list[ServiceWatcher] = []

    # ── 1. 创建进程 watchers ──
    for mc in config.get("monitors", []):
        w = ServiceWatcher(mc, alerter)
        watchers.append(w)
        log.info(f"已注册进程监控: {mc['name']}")

    # ── 2. 启动 Windows 服务看门狗 ──
    watchdog = None
    watchdog_cfg = config.get("windows_service_watchdog", {})
    if watchdog_cfg.get("enabled", True):
        try:
            from .service_watchdog import WindowsServiceWatchdog
            watchdog = WindowsServiceWatchdog(config, alerter)
            watchdog.start_thread()
            log.info("🔍 Windows 服务看门狗已启动")
        except ImportError as e:
            log.warning(f"看门狗模块加载失败 (非 Windows 环境?): {e}")
        except Exception as e:
            log.error(f"看门狗启动失败: {e}")

    # ── 3. 启动可视化仪表板 ──
    dashboard = None
    dashboard_enabled = config.get("dashboard", {}).get("enabled", True)
    if dashboard_enabled:
        try:
            from .dashboard import DashboardServer
            dashboard_port = config.get("dashboard", {}).get("port", 19998)
            dashboard = DashboardServer(config)
            dashboard.start(port=dashboard_port)
        except Exception as e:
            log.error(f"仪表板启动失败: {e}")

    if not watchers and not watchdog:
        log.warning("没有配置任何监控目标，退出")
        return

    # 启动所有进程 watcher
    for w in watchers:
        w.start()

    total = len(watchers) + (1 if watchdog else 0)
    log.info(f"━━━ Crash Monitor 已启动 ━━━")
    log.info(f"  进程监控: {len(watchers)} 个")
    log.info(f"  服务看门狗: {'✅' if watchdog else '❌'}")
    log.info(f"  仪表板: {'✅' if dashboard else '❌'}")

    # ── 优雅退出 ──
    def shutdown(sig, frame):
        log.info("收到退出信号，关闭所有监控...")
        for w in watchers:
            w.stop()
        if watchdog:
            watchdog.stop()
        if dashboard:
            dashboard.stop()
        log.info("Crash Monitor 已退出")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # ── 主循环 ──
    try:
        while True:
            for w in watchers:
                w.check()
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
