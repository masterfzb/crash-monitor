@echo off
:: Crash Monitor v2 — double-click to start (30s interval, runs until closed)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "monitor.ps1" -IntervalSec 30
pause
