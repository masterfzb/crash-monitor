# Crash Monitor v2.2

Minimal-impact, crash-safe system heartbeat. **Dual-disk output** — writes to both C: (NVMe, Desktop) and D: (SATA HDD). If one copy stops, the other reveals which drive failed.

## Design

- **Dual-disk mirroring** — `Desktop\crash-monitor-logs\` (C: NVMe) + `D:\crash-monitor-logs\` (SATA)
- **Atomic round files** — per-heartbeat `YYYY-MM-DD/HH-MM-SS.txt` on both disks
- **LATEST.txt** — fixed single-line snapshot on both disks for post-crash glance
- **60-second heartbeat** — minimal system impact, catches crash progression
- **Performance impact** — ~1 nvidia-smi call + ~2 WMI queries + ~2 event log queries per minute. Negligible CPU/IO load.
- **No Get-Counter** — avoids Windows Performance Counter hangs (known crash vector)
- **Crash-diagnostic metrics** — GPU state, RAM, NVMe controller resets (stornvme 129), Kernel-Power 41 count

## Usage

```powershell
# Double-click run_monitor.bat, or:
powershell -NoProfile -ExecutionPolicy Bypass -File monitor.ps1

# Custom interval:
powershell -NoProfile -ExecutionPolicy Bypass -File monitor.ps1 -IntervalSec 30 -MaxRounds 120
```

## Post-Crash Diagnosis

1. Open `D:\crash-monitor-logs\LATEST.txt` (survives NVMe failure)
2. Compare with `Desktop\crash-monitor-logs\LATEST.txt`
3. If D: has more recent data than C: → NVMe was the problem
4. If both have same last timestamp → system-level hang (not disk-specific)

## Log Format

```
[2026-06-15 00:23:45] R42 GPU:38°C|0%|252MiB|22W|210MHz/405MHz RAM:5.1/31.8G U:0d0h26m nvme:0r5m kp41:0 edge:16p top:msedge
```

| Field | Meaning |
|-------|---------|
| GPU:temp\|usage\|vram\|power\|core/mem | NVIDIA GPU state |
| RAM:used/total | Memory pressure |
| U:days/hours/minutes | System uptime |
| nvme:Nr5m | stornvme 129 resets in last 5 min (≤1 is concerning) |
| kp41:N | Kernel-Power 41 events since boot |
| edge:Np | Edge browser process count |
| top:name | Highest-CPU process |
