# Crash Monitor v2.1 — Minimal-impact, crash-safe system heartbeat
# Design: atomic round files on D:\ (independent SATA disk) + LATEST.txt marker
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File monitor.ps1 [-IntervalSec 15] [-LogRoot "D:\..."] [-MaxRounds 0]
param(
    [int]$IntervalSec = 15,
    [int]$MaxRounds = 0,  # 0 = run until killed or crash
    [string]$LogRoot = 'D:\crash-monitor-logs'
)

$ErrorActionPreference = 'SilentlyContinue'
$script:LogRoot = $LogRoot
$script:Hostname = $env:COMPUTERNAME
$script:LatestFile = Join-Path $script:LogRoot 'LATEST.txt'

# ---- helpers ----

function atomic-write($path, $text) {
    # WriteAllText is atomic: file appears complete or not at all
    # Writes to D:\ (independent SATA controller, survives NVMe failure)
    $dir = Split-Path $path -Parent
    [void](New-Item $dir -ItemType Directory -Force)
    [System.IO.File]::WriteAllText($path, $text, [System.Text.Encoding]::UTF8)
}

function write-round($text) {
    # 1. Per-round archive file: D:\crash-monitor-logs\YYYY-MM-DD\HH-MM-SS.txt
    $now = [DateTime]::Now
    $roundPath = Join-Path $script:LogRoot "$($now.ToString('yyyy-MM-dd'))\$($now.ToString('HH-mm-ss')).txt"
    atomic-write $roundPath $text

    # 2. LATEST.txt: fixed single-line marker for post-crash quick glance
    atomic-write $script:LatestFile $text
}

function get-gpu-snapshot {
    # Single nvidia-smi call — fast, stable, no WMI perf counters
    $lines = & 'nvidia-smi' --query-gpu=timestamp,temperature.gpu,utilization.gpu,utilization.memory,memory.used,power.draw,clocks.current.sm,clocks.current.memory --format=csv,noheader 2>$null
    if (-not $lines) { return 'GPU:n/a' }
    $f = ($lines[0] -split ', ').Trim()
    "GPU:${f[1]}°C|${f[2]}|${f[4]}|${f[5]}|${f[6]}MHz/${f[7]}MHz"
}

function get-cpu-ram {
    $os = Get-CimInstance Win32_OperatingSystem -Property TotalVisibleMemorySize,FreePhysicalMemory -ErrorAction SilentlyContinue
    if ($os) {
        $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
        $freeGB  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
        $usedGB  = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 1)
        "RAM:${usedGB}/${totalGB}G"
    } else { 'RAM:n/a' }
}

function get-edge-count {
    $c = @(Get-Process msedge -ErrorAction SilentlyContinue).Count
    "edge:${c}p"
}

function get-uptime {
    $os = Get-CimInstance Win32_OperatingSystem -Property LastBootUpTime -ErrorAction SilentlyContinue
    if ($os -and $os.LastBootUpTime) {
        $span = [DateTime]::Now - $os.LastBootUpTime
        "U:$($span.Days)d$($span.Hours)h$($span.Minutes)m"
    } else { 'U:n/a' }
}

function get-top-cpu-proc {
    $top = Get-Process -ErrorAction SilentlyContinue |
        Sort-Object CPU -Descending |
        Select-Object -First 1
    if ($top) { "top:$($top.ProcessName)" } else { 'top:n/a' }
}

# ---- main loop ----

$header = "monitor_v2.1 host=$script:Hostname interval=${IntervalSec}s pid=$PID logroot=$script:LogRoot"
write-round "START $header at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

$round = 0
while ($MaxRounds -eq 0 -or $round -lt $MaxRounds) {
    $round++
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

    $gpu  = get-gpu-snapshot
    $ram  = get-cpu-ram
    $edge = get-edge-count
    $upt  = get-uptime
    $top  = get-top-cpu-proc

    $line = "[$ts] R$round $gpu $ram $upt $edge $top"
    write-round $line

    Start-Sleep -Seconds $IntervalSec
}

write-round "STOP $header at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') rounds=$round"
