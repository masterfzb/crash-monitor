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

    # ── 服务看门狗告警 ──────────────────────────────

    def send_service_alert(
        self,
        failures: list[str],
        service_states: list[dict] = None,
        process_states: list[dict] = None,
        recovered: bool = False,
    ):
        """发送服务/进程异常告警."""
        if not self.webhook_url:
            return

        if recovered:
            self._send_generic(
                title="✅ 系统恢复正常",
                color=0x00FF00,
                fields=[{"name": "状态", "value": "所有关键服务和进程已恢复"}],
            )
            return

        # 构建告警内容
        failure_text = "\n".join(f"- {f}" for f in failures[:10])

        fields = [
            {"name": "异常项", "value": failure_text, "inline": False},
        ]

        # 附加服务状态摘要
        if service_states:
            bad_svcs = [s for s in service_states if s.get("status") != "running"]
            if bad_svcs:
                fields.append({
                    "name": "异常服务",
                    "value": ", ".join(f"{s['display']}({s['status']})" for s in bad_svcs[:5]),
                    "inline": False,
                })

        # 附加进程状态
        if process_states:
            dead_procs = [p for p in process_states if not p.get("running")]
            if dead_procs:
                fields.append({
                    "name": "死亡进程",
                    "value": ", ".join(p["display"] for p in dead_procs[:5]),
                    "inline": False,
                })

        self._send_generic(
            title="🚨 Windows 系统服务异常",
            color=0xFF0000,
            fields=fields,
        )

    def _send_generic(self, title: str, color: int, fields: list[dict]):
        """通用告警发送（自动选择平台）."""
        if self.webhook_type == "wecom":
            lines = [f"## {title}"]
            for f in fields:
                lines.append(f"> {f['name']}: {f['value']}")
            self._post({"msgtype": "markdown", "markdown": {"content": "\n".join(lines)}})
        elif self.webhook_type == "discord":
            self._post({"embeds": [{"title": title, "color": color, "fields": fields}]})
        elif self.webhook_type == "feishu":
            content = "\n".join(f"**{f['name']}**: {f['value']}" for f in fields)
            self._post({"msg_type": "text", "content": {"text": f"{title}\n{content}"}})

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
