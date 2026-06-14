# Crash Monitor v2.1

Minimal-impact, crash-safe system heartbeat. **Survives NVMe failure** — writes to independent SATA disk.

## Design

- **D: drive output** — separate SATA HDD, immune to NVMe controller hangs
- **Atomic round files** — `D:\crash-monitor-logs\YYYY-MM-DD\HH-MM-SS.txt` each heartbeat
- **LATEST.txt** — `D:\crash-monitor-logs\LATEST.txt` always contains the most recent snapshot; quick post-crash glance
- **No performance counters** — avoids `Get-Counter` (known to cause Windows hangs)
- **15-second heartbeat** — catches crashes, near-zero system impact
- **Minimal system calls** — single `nvidia-smi`, one WMI, one process list

## Usage

```powershell
# Double-click run_monitor.bat, or:
powershell -NoProfile -ExecutionPolicy Bypass -File monitor.ps1

# Custom interval + path:
powershell -NoProfile -ExecutionPolicy Bypass -File monitor.ps1 -IntervalSec 30 -LogRoot "E:\monitor"
```

## Post-Crash

After reboot, open `D:\crash-monitor-logs\LATEST.txt` — the last recorded heartbeat before the system froze.

## Log Format

```
[2026-06-15 00:23:45] R42 GPU:38°C|0%|252MiB|22W|210MHz/405MHz RAM:5.1/31.8G U:0d0h26m edge:16p top:msedge
```
