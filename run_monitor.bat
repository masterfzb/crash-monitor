@echo off
:: Crash Monitor v2.2 — double-click to start (60s interval, writes to C:\Desktop + D:\)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "monitor.ps1" -IntervalSec 60
pause
