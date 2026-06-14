"""主监控循环 — 启动所有 watcher 并持续运行."""

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

    # 创建 watchers
    for mc in config.get("monitors", []):
        w = ServiceWatcher(mc, alerter)
        watchers.append(w)
        log.info(f"已注册监控: {mc['name']}")

    if not watchers:
        log.warning("没有配置任何监控目标，退出")
        return

    # 启动所有 watcher
    for w in watchers:
        w.start()

    log.info(f"Crash Monitor 已启动，监控 {len(watchers)} 个服务")

    # 优雅退出
    def shutdown(sig, frame):
        log.info("收到退出信号，关闭所有 watcher...")
        for w in watchers:
            w.stop()
        log.info("Crash Monitor 已退出")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 主循环
    try:
        while True:
            for w in watchers:
                w.check()
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
