# Crash Monitor v2

Minimal-impact system heartbeat monitor. Designed to survive system hangs and crashes.

## Design

- **Atomic round files**: each heartbeat is a separate file (`logs/YYYY-MM-DD/HH-MM-SS.txt`). If the system crashes mid-write, only the current file is lost — all previous rounds are intact.
- **No performance counters**: avoids `Get-Counter` and disk I/O counters, which are known to cause Windows hangs when the counter subsystem is corrupted.
- **Minimal system calls**: one `nvidia-smi` query, one WMI call, one process list — fast and stable.
- **30-second heartbeat**: frequent enough to catch crashes, sparse enough to have near-zero system impact.

## Usage

```powershell
# Run with default 30-second interval, until killed
powershell -NoProfile -ExecutionPolicy Bypass -File monitor.ps1

# Custom interval, fixed number of rounds
powershell -NoProfile -ExecutionPolicy Bypass -File monitor.ps1 -IntervalSec 60 -MaxRounds 120
```

## Log Format

Each round file contains a single line:

```
[2026-06-15 00:23:45] R42 GPU:38°C|0%|252MiB|22W|210MHz/405MHz RAM:5.1/31.8G U:0d0h26m edge:16p top:msedge
```

## Why v2 Exists

v1 ran at 4-second intervals with full disk performance counters and two parallel instances. At 00:12:57 the disk I/O hit 1486% and the system hung. v2 exists so that never happens again.
