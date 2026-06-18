"""
可视化仪表板 — 轻量级 HTTP 服务，展示系统监控状态。

单文件实现，零外部依赖。服务端渲染 HTML + 内嵌
CSS/JS，浏览器直接访问即可看到实时状态面板。
"""

import json
import os
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from typing import Optional

from .logger import get_logger

log = get_logger(__name__, "crash-monitor-dashboard.log")

# ── 仪表板 HTML ────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>💥 Crash Monitor · 系统监控仪表板</title>
<style>
  :root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --yellow: #d29922; --red: #f85149;
    --purple: #a371f7;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; padding:20px; }
  h1 { font-size:1.4em; font-weight:600; margin-bottom:4px; }
  .subtitle { color:var(--muted); font-size:0.85em; margin-bottom:20px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:12px; margin-bottom:20px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:14px; }
  .card h3 { font-size:0.8em; color:var(--muted); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:10px; }
  .row { display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid var(--border); }
  .row:last-child { border-bottom:none; }
  .label { font-size:0.9em; }
  .badge { font-size:0.75em; padding:3px 8px; border-radius:12px; font-weight:600; }
  .badge.ok { background:#1a3a1a; color:var(--green); }
  .badge.warn { background:#3a2e0a; color:var(--yellow); }
  .badge.dead { background:#3a1a1a; color:var(--red); }
  .badge.unknown { background:#1a1a2e; color:var(--muted); }
  .timeline { max-height:300px; overflow-y:auto; }
  .event { padding:5px 0; border-left:2px solid var(--border); padding-left:10px; margin-bottom:6px; font-size:0.82em; font-family:'Cascadia Code',Consolas,monospace; }
  .event.INFO { border-left-color:var(--accent); }
  .event.WARN { border-left-color:var(--yellow); }
  .event.ERROR { border-left-color:var(--red); }
  .event .time { color:var(--muted); }
  .health-dot { width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:6px; }
  .health-dot.green { background:var(--green); box-shadow:0 0 8px var(--green); }
  .health-dot.red { background:var(--red); box-shadow:0 0 8px var(--red); animation:pulse 1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  .status-bar { display:flex; gap:16px; margin-bottom:16px; align-items:center; }
  .stat { font-size:1.2em; font-weight:700; }
  .stat-label { font-size:0.7em; color:var(--muted); }
  .refresh { color:var(--muted); font-size:0.75em; }
  .no-data { text-align:center; padding:40px; color:var(--muted); }
  .section { margin-top:8px; }
</style>
</head>
<body>
<h1>💥 Crash Monitor</h1>
<div class="subtitle">系统服务 &amp; 进程看门狗 · <span id="updateTime">--</span></div>

<div class="status-bar">
  <div class="stat" id="svcOk">-</div><div class="stat-label">服务正常</div>
  <div class="stat" id="svcBad" style="color:var(--red)">-</div><div class="stat-label">服务异常</div>
  <div class="stat" id="procOk">-</div><div class="stat-label">进程存活</div>
  <div class="stat" id="procBad" style="color:var(--red)">-</div><div class="stat-label">进程死亡</div>
  <span class="refresh" id="refresh">自动刷新: 3s</span>
</div>

<div class="grid">
  <div class="card">
    <h3>🔧 Windows 服务</h3>
    <div id="services"></div>
  </div>
  <div class="card">
    <h3>📦 关键进程</h3>
    <div id="processes"></div>
  </div>
  <div class="card">
    <h3>🧪 系统功能</h3>
    <div id="checks"></div>
  </div>
  <div class="card">
    <h3>📋 最近事件</h3>
    <div class="timeline" id="events"></div>
  </div>
</div>

<script>
const STATUS_URL = window.location.origin + '/api/status';

function badge(status, isProcess) {
  if (isProcess) {
    if (status === true || status === 'running') return 'ok';
    return 'dead';
  }
  if (status === 'running') return 'ok';
  if (status === 'stopped') return 'warn';
  return 'dead';
}

function badgeLabel(status, isProcess) {
  if (isProcess) return status ? '存活' : '死亡';
  const map = {running:'运行中', stopped:'已停止', dead:'不存在', unknown:'未知'};
  return map[status] || status;
}

function render() {
  fetch(STATUS_URL).then(r=>r.json()).then(data=>{
    document.getElementById('updateTime').textContent = '更新于 ' + data.timestamp;

    // 服务
    let svcHtml = '', svcOk=0, svcBad=0;
    data.services.forEach(s=>{
      const b = badge(s.status, false);
      svcHtml += `<div class="row"><span class="label">${s.critical?'⚠️':''} ${s.display}</span><span class="badge ${b}">${badgeLabel(s.status,false)}</span></div>`;
      if (s.status==='running') svcOk++; else svcBad++;
    });
    document.getElementById('services').innerHTML = svcHtml || '<div class="no-data">无数据</div>';
    document.getElementById('svcOk').textContent = svcOk;
    document.getElementById('svcBad').textContent = svcBad;

    // 进程
    let procHtml = '', procOk=0, procBad=0;
    data.processes.forEach(p=>{
      const b = badge(p.running, true);
      procHtml += `<div class="row"><span class="label">${p.critical?'⚠️':''} ${p.display}</span><span class="badge ${b}">${badgeLabel(p.running,true)}${p.pid?' (PID:'+p.pid+')':''}</span></div>`;
      if (p.running) procOk++; else procBad++;
    });
    document.getElementById('processes').innerHTML = procHtml || '<div class="no-data">无数据</div>';
    document.getElementById('procOk').textContent = procOk;
    document.getElementById('procBad').textContent = procBad;

    // 系统功能
    let checkHtml = '';
    data.system_checks.forEach(c=>{
      const b = c.passed ? 'ok' : 'dead';
      checkHtml += `<div class="row"><span class="label">${c.display}</span><span class="badge ${b}">${c.passed?'正常':'异常'}</span></div>`;
      if (!c.passed) checkHtml += `<div style="font-size:0.75em;color:var(--red);padding:2px 0">${c.error||''}</div>`;
    });
    document.getElementById('checks').innerHTML = checkHtml || '<div class="no-data">无数据</div>';

    // 事件
    let evtHtml = '';
    (data.events||[]).slice(-40).reverse().forEach(e=>{
      evtHtml += `<div class="event ${e.level}"><span class="time">${(e.time||'').slice(-8)}</span> ${e.message}</div>`;
    });
    document.getElementById('events').innerHTML = evtHtml || '<div class="no-data">暂无事件</div>';
  }).catch(e=>{
    document.getElementById('updateTime').textContent = '⚠️ 无法连接';
  });
}

render();
setInterval(render, 3000);
</script>
</body>
</html>"""

# ── HTTP 处理器 ─────────────────────────────────────────


class DashboardHandler(BaseHTTPRequestHandler):
    """仪表板 HTTP 请求处理器."""

    # 类变量: 由外部设置
    status_dir: str = "D:\\crash-monitor\\status"
    dashboard_port: int = 0

    def log_message(self, format, *args):
        """抑制默认访问日志."""
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/status":
            self._serve_status()
        elif self.path == "/api/health":
            self._serve_health()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(DASHBOARD_HTML.encode("utf-8"))

    def _serve_status(self):
        """返回最新的状态 JSON."""
        status_file = Path(self.status_dir) / "status.json"
        data = {"timestamp": "--", "services": [], "processes": [],
                "system_checks": [], "events": []}

        if status_file.exists():
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _serve_health(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")


# ── 仪表板启动器 ───────────────────────────────────────


class DashboardServer:
    """轻量级仪表板 HTTP 服务."""

    def __init__(self, config: dict):
        self.config = config
        self.httpd: Optional[HTTPServer] = None

    def start(self, port: int = 19998) -> Thread:
        """启动仪表板 HTTP 服务."""
        watchdog_cfg = self.config.get("windows_service_watchdog", {})
        status_dir = watchdog_cfg.get(
            "status_dir", "D:\\crash-monitor\\status"
        )

        # 注入配置到处理器
        DashboardHandler.status_dir = status_dir
        DashboardHandler.dashboard_port = port

        def _run():
            try:
                self.httpd = HTTPServer(("0.0.0.0", port), DashboardHandler)
                log.info(f"📊 仪表板已启动: http://localhost:{port}")
                self.httpd.serve_forever()
            except OSError as e:
                log.warning(f"仪表板启动失败 (端口 {port} 被占用?): {e}")
            except Exception as e:
                log.error(f"仪表板异常: {e}")

        t = Thread(target=_run, daemon=True, name="DashboardHTTP")
        t.start()
        return t

    def stop(self):
        """停止仪表板."""
        if self.httpd:
            self.httpd.shutdown()
            log.info("仪表板已停止")
