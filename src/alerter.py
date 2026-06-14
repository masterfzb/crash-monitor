"""告警通知 — 通过 Webhook 发送崩溃告警."""

import json
import urllib.request
from datetime import datetime

from .logger import get_logger

log = get_logger(__name__)

# 企业微信 Markdown 消息模板
WECOM_TEMPLATE = """## 💥 服务崩溃告警
> 服务: <font color="warning">{name}</font>
> 时间: {time}
> 退出码: {exit_code}
> 重启次数: {restart_count}
> {exhausted_note}"""

FEISHU_TEMPLATE = {
    "msg_type": "interactive",
    "card": {
        "header": {
            "title": {"tag": "plain_text", "content": "💥 服务崩溃告警"},
            "template": "red",
        },
        "elements": [],  # 动态填充
    },
}


class Alerter:
    """告警通知发送器."""

    def __init__(self, alert_config: dict):
        self.config = alert_config
        self.webhook_url = alert_config.get("webhook", {}).get("url", "")
        self.webhook_type = alert_config.get("webhook", {}).get("type", "wecom")

    def send_crash_alert(self, record, exhausted: bool = False):
        """发送崩溃告警."""
        if not self.webhook_url:
            log.warning("未配置告警 Webhook，跳过通知")
            return

        exhausted_note = (
            "⚠️ **已达最大重启次数，请人工介入！**" if exhausted else ""
        )

        if self.webhook_type == "wecom":
            self._send_wecom(record, exhausted_note)
        elif self.webhook_type == "feishu":
            self._send_feishu(record, exhausted_note)
        elif self.webhook_type == "discord":
            self._send_discord(record, exhausted_note)

    def _send_wecom(self, record, exhausted_note: str):
        """企业微信 Webhook."""
        content = WECOM_TEMPLATE.format(
            name=record.service_name,
            time=record.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            exit_code=record.exit_code,
            restart_count=record.restart_count,
            exhausted_note=exhausted_note,
        )
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }
        self._post(payload)

    def _send_feishu(self, record, exhausted_note: str):
        """飞书 Webhook."""
        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**服务**: {record.service_name}\n"
                    f"**时间**: {record.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"**退出码**: {record.exit_code}\n"
                    f"**重启**: {record.restart_count} 次\n{exhausted_note}",
                },
            }
        ]
        card = FEISHU_TEMPLATE.copy()
        card["card"]["elements"] = elements
        self._post(card)

    def _send_discord(self, record, exhausted_note: str):
        """Discord Webhook."""
        payload = {
            "embeds": [
                {
                    "title": "💥 服务崩溃告警",
                    "color": 0xFF0000,
                    "fields": [
                        {"name": "服务", "value": record.service_name, "inline": True},
                        {
                            "name": "时间",
                            "value": record.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                            "inline": True,
                        },
                        {
                            "name": "退出码",
                            "value": str(record.exit_code),
                            "inline": True,
                        },
                        {
                            "name": "重启次数",
                            "value": str(record.restart_count),
                            "inline": True,
                        },
                    ],
                    "footer": {"text": exhausted_note} if exhausted_note else None,
                }
            ]
        }
        self._post(payload)

    def _post(self, payload: dict):
        """发送 HTTP POST."""
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            log.info("告警已发送")
        except Exception as e:
            log.error(f"发送告警失败: {e}")
