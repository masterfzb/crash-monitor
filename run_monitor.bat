@echo off
:: Crash Monitor v2.1 — double-click to start (15s interval, writes to D:\)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "monitor.ps1" -IntervalSec 15 -LogRoot "D:\crash-monitor-logs"
pause
