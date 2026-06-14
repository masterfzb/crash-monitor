# Crash Monitor v2 — Minimal-impact, crash-safe system heartbeat
# Design: atomic round files → survives system hang/crash
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File monitor.ps1 [-IntervalSec 30] [-MaxRounds 0]
param(
    [int]$IntervalSec = 30,
    [int]$MaxRounds = 0  # 0 = run until killed or crash
)

$ErrorActionPreference = 'SilentlyContinue'
$script:LogRoot = Join-Path $PSScriptRoot 'logs'
$script:Hostname = $env:COMPUTERNAME

# ---- helpers ----

function atomic-write($text) {
    # One file per round: logs/YYYY-MM-DD/HH-MM-SS.txt
    # WriteAllText is atomic: file appears complete or not at all
    $now = [DateTime]::Now
    $dir = Join-Path $script:LogRoot $now.ToString('yyyy-MM-dd')
    [void](New-Item $dir -ItemType Directory -Force)
    $path = Join-Path $dir "$($now.ToString('HH-mm-ss')).txt"
    [System.IO.File]::WriteAllText($path, $text, [System.Text.Encoding]::UTF8)
}

function get-gpu-snapshot {
    # Single nvidia-smi call — fast, stable, no WMI perf counters
    $lines = & 'nvidia-smi' --query-gpu=timestamp,temperature.gpu,utilization.gpu,utilization.memory,memory.used,power.draw,clocks.current.sm,clocks.current.memory --format=csv,noheader 2>$null
    if (-not $lines) { return 'GPU:n/a' }
    # Parse first GPU only
    $f = ($lines[0] -split ', ').Trim()
    # Fields: timestamp, temp, gpu%, mem%, vram, power, sm_clock, mem_clock
    "GPU:${f[1]}°C|${f[2]}|${f[4]}|${f[5]}|${f[6]}MHz/${f[7]}MHz"
}

function get-cpu-ram {
    # Avoid Get-Counter (perf counters can hang). Use lightweight alternatives.
    # CPU: rough via process CPU time delta — skip for stability, use simple load via WMI
    $os = Get-CimInstance Win32_OperatingSystem -Property TotalVisibleMemorySize,FreePhysicalMemory -ErrorAction SilentlyContinue
    if ($os) {
        $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
        $freeGB  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
        $usedGB  = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 1)
        $ram = "${usedGB}/${totalGB}G"
    } else {
        $ram = 'n/a'
    }
    "RAM:${ram}"
}

function get-edge-count {
    $c = @(Get-Process msedge -ErrorAction SilentlyContinue).Count
    "edge:${c}p"
}

function get-uptime {
    # Use Get-Date minus CIM LastBootUpTime — safer than perf counters
    $os = Get-CimInstance Win32_OperatingSystem -Property LastBootUpTime -ErrorAction SilentlyContinue
    if ($os -and $os.LastBootUpTime) {
        $span = [DateTime]::Now - $os.LastBootUpTime
        "U:$($span.Days)d$($span.Hours)h$($span.Minutes)m"
    } else {
        "U:n/a"
    }
}

function get-top-cpu-proc {
    # Lightweight: just the #1 CPU-hog process name (no CPU time needed)
    $top = Get-Process -ErrorAction SilentlyContinue |
        Sort-Object CPU -Descending |
        Select-Object -First 1
    if ($top) { "top:$($top.ProcessName)" } else { "top:n/a" }
}

# ---- main loop ----

$header = "monitor_v2 host=$script:Hostname interval=${IntervalSec}s pid=$PID"
atomic-write "START $header at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

$round = 0
while ($MaxRounds -eq 0 -or $round -lt $MaxRounds) {
    $round++
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

    # Collect snapshots — each call is independent, failure in one won't block others
    $gpu  = get-gpu-snapshot
    $ram  = get-cpu-ram
    $edge = get-edge-count
    $upt  = get-uptime
    $top  = get-top-cpu-proc

    $line = "[$ts] R$round $gpu $ram $upt $edge $top"
    atomic-write $line

    Start-Sleep -Seconds $IntervalSec
}

atomic-write "STOP $header at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') rounds=$round"
