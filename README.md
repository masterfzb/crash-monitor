# 💥 Crash Monitor

轻量级服务崩溃监控与自动恢复系统。监控目标进程/服务状态，崩溃时自动重启、记录日志、发送告警通知。

## 功能

- **进程监控** — 通过 PID 文件或进程名监控目标服务
- **崩溃检测** — 进程退出、无响应、资源异常（CPU/内存）
- **自动恢复** — 检测到崩溃后自动重启服务
- **日志记录** — 完整崩溃堆栈、时间线、重启记录
- **告警通知** — 支持 Webhook（企业微信/飞书/Discord）
- **轻量无侵入** — 纯 Python，不依赖外部 agent

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置
cp config.example.yaml config.yaml

# 编辑配置，添加要监控的服务
vim config.yaml

# 启动监控
python -m src.monitor
```

## 配置示例

```yaml
# config.yaml
monitors:
  - name: "my-web-service"
    command: "python -m http.server 8080"
    working_dir: "/path/to/project"
    pid_file: "/tmp/my-service.pid"
    restart:
      enabled: true
      max_restarts: 5
      cooldown_seconds: 10
    health_check:
      type: http
      url: "http://localhost:8080/health"
      interval_seconds: 30
      timeout_seconds: 5

alerts:
  webhook:
    url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
    type: wecom  # wecom | feishu | discord
```

## 项目结构

```
crash-monitor/
├── src/
│   ├── __init__.py
│   ├── monitor.py      # 主监控循环
│   ├── watcher.py       # 进程监控器
│   ├── alerter.py       # 告警通知
│   └── logger.py        # 日志记录
├── config.example.yaml
├── requirements.txt
├── .gitignore
└── README.md
```

## License

MIT
