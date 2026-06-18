# 💥 Crash Monitor

轻量级服务崩溃监控与自动恢复系统。支持进程监控 + **Windows 系统服务看门狗** + 可视化仪表板。

## v0.3.0 新增

- 🔍 **Windows 服务看门狗** — 监控关键系统服务/进程，检测"电脑活着但服务死了"的静默故障
- 📸 **故障快照** — 异常时自动捕获系统状态完整快照（进程列表+服务状态+事件时间线）
- 📊 **可视化仪表板** — 浏览器实时查看系统健康状态，自动刷新
- 💓 **心跳文件** — 独立于日志的存活证明，写入非 C 盘
- 🚨 **服务异常告警** — 核心服务/进程挂了立即 Webhook 通知

## 功能

- **进程监控** — 监控目标进程，崩溃自动重启
- **服务看门狗** — 监控 Windows 系统服务 (sc query) + 关键进程 (tasklist)
- **系统功能检查** — 检测关机命令可用性、任务栏响应性
- **崩溃快照** — 故障时刻全系统状态 dump
- **自动恢复** — 进程崩溃后自动重启（可配置最大次数）
- **告警通知** — Webhook（企业微信/飞书/Discord）
- **可视化仪表板** — HTTP 仪表板，浏览器直接看
- **非 C 盘日志** — 所有日志/快照/心跳写 D: 盘，防磁盘锁丢证据

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 复制配置
cp config.example.yaml config.yaml

# 3. 编辑配置
#    - 如需进程监控: 修改 monitors 段
#    - 如需服务看门狗: 确认 windows_service_watchdog.enabled = true
#    - 日志目录改成非 C 盘路径 (默认 D:\ 下)
#    - 告警 Webhook: 修改 alerts 段

# 4. 启动
python -m src.monitor

# 5. 打开仪表板
# 浏览器访问 http://localhost:19998
```

## 服务看门狗使用

```
启动后自动监控:
  ✅ 10 个关键 Windows 服务 (DcomLaunch, RpcSs, EventLog, ShellHWDetection...)
  ✅ 5 个关键系统进程 (explorer.exe, StartMenuExperienceHost.exe...)
  ✅ 关机功能可用性
  ✅ 任务栏/Shell 响应性

每 N 秒:
  → 检查所有服务状态
  → 检查所有进程存活
  → 写入心跳文件到 D:\ 盘
  → 更新仪表板状态 JSON

发现异常:
  → 记录 ERROR 级别事件
  → 捕获完整系统快照 (D:\crash-monitor\snapshots\)
  → 发送 Webhook 告警

恢复正常:
  → 发送恢复通知
```

## 仪表板

访问 `http://localhost:19998` 查看:

- 服务状态卡片（绿色=运行 / 红色=挂了）
- 进程存活列表（含 PID）
- 系统功能检查结果
- 实时事件流

## 项目结构

```
crash-monitor/
├── src/
│   ├── __init__.py
│   ├── monitor.py            # 主监控循环
│   ├── watcher.py            # 进程监控器
│   ├── service_watchdog.py   # 🆕 Windows 服务看门狗
│   ├── dashboard.py          # 🆕 可视化仪表板
│   ├── alerter.py            # 告警通知
│   └── logger.py             # 日志
├── config.example.yaml
├── requirements.txt
└── README.md
```

## License

MIT
