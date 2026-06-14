# Crash Monitor v2.2 — Dual-disk, crash-safe heartbeat
# Writes to BOTH C:\ (NVMe, Desktop) and D:\ (SATA HDD). If one copy stops while
# the other continues → the stopped drive is the crash locus.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File monitor.ps1 [-IntervalSec 60] [-MaxRounds 0]
param(
    [int]$IntervalSec = 60,
    [int]$MaxRounds = 0
)

$ErrorActionPreference = 'SilentlyContinue'
$script:Hostname = $env:COMPUTERNAME

# Dual output roots — same data, two physical disks
$script:RootC = "$env:USERPROFILE\Desktop\crash-monitor-logs"  # NVMe SSD
$script:RootD = 'D:\crash-monitor-logs'                        # SATA HDD (survives NVMe failure)

# ---- helpers ----

function atomic-write($path, $text) {
    $dir = Split-Path $path -Parent
    [void](New-Item $dir -ItemType Directory -Force)
    [System.IO.File]::WriteAllText($path, $text, [System.Text.Encoding]::UTF8)
}

function write-round($text) {
    $now = [DateTime]::Now
    $dateDir = $now.ToString('yyyy-MM-dd')
    $timeFile = $now.ToString('HH-mm-ss') + '.txt'

    # D: first (more likely to survive)
    $dPath = Join-Path $script:RootD "$dateDir\$timeFile"
    atomic-write $dPath $text
    atomic-write (Join-Path $script:RootD 'LATEST.txt') $text

    # C: Desktop (NVMe — stopped = NVMe issue)
    $cPath = Join-Path $script:RootC "$dateDir\$timeFile"
    atomic-write $cPath $text
    atomic-write (Join-Path $script:RootC 'LATEST.txt') $text
}

function get-gpu-snapshot {
    $raw = & 'nvidia-smi' --query-gpu=timestamp,temperature.gpu,utilization.gpu,utilization.memory,memory.used,power.draw,clocks.current.sm,clocks.current.memory --format=csv,noheader 2>&1 | Out-String
    if (-not $raw -or $raw.Trim().Length -eq 0) { return 'GPU:n/a' }
    $raw = ($raw.Trim() -split "`n")[0]
    $f = $raw -split ','
    if ($f.Count -lt 8) { return "GPU:fmt$($f.Count) $raw" }
    "GPU:$($f[1].Trim())C|$($f[2].Trim())|$($f[4].Trim())|$($f[5].Trim())|$($f[6].Trim())/$($f[7].Trim())"
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

function get-nvme-errors {
    # Check for recent NVMe controller resets (stornvme 129)
    # This is THE key metric for the current crash scenario
    $c = @(Get-WinEvent -FilterHashtable @{
        LogName='System'; Id=129; ProviderName='stornvme'
        StartTime=(Get-Date).AddMinutes(-5)
    } -MaxEvents 5 -ErrorAction SilentlyContinue).Count
    "nvme:${c}r5m"
}

function get-kernel-errors {
    # Kernel-Power 41 count since boot — unexpected reboots
    $os = Get-CimInstance Win32_OperatingSystem -Property LastBootUpTime -ErrorAction SilentlyContinue
    if ($os -and $os.LastBootUpTime) {
        $c = @(Get-WinEvent -FilterHashtable @{
            LogName='System'; Id=41; ProviderName='Microsoft-Windows-Kernel-Power'
            StartTime=$os.LastBootUpTime
        } -MaxEvents 20 -ErrorAction SilentlyContinue).Count
        "kp41:${c}"
    } else { 'kp41:n/a' }
}

# ---- main loop ----

$header = "monitor_v2.2 host=$script:Hostname interval=${IntervalSec}s pid=$PID"
write-round "START $header at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

$round = 0
$lastCleanup = [DateTime]::MinValue
$cleanupAgeMin = 30  # keep last 30 min of round files

while ($MaxRounds -eq 0 -or $round -lt $MaxRounds) {
    $round++
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

    $gpu   = get-gpu-snapshot
    $ram   = get-cpu-ram
    $edge  = get-edge-count
    $upt   = get-uptime
    $top   = get-top-cpu-proc
    $nvme  = get-nvme-errors
    $kp41  = get-kernel-errors

    $line = "[$ts] R$round $gpu $ram $upt $nvme $kp41 $edge $top"
    write-round $line

    # Cleanup old round files every ~30 min (keeps last 30 min)
    if (([DateTime]::Now - $lastCleanup).TotalMinutes -ge 30) {
        $lastCleanup = [DateTime]::Now
        foreach ($root in @($script:RootC, $script:RootD)) {
            Get-ChildItem $root -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -ne 'LATEST.txt' -and $_.LastWriteTime -lt [DateTime]::Now.AddMinutes(-$cleanupAgeMin) } |
                Remove-Item -Force -ErrorAction SilentlyContinue
        }
    }

    Start-Sleep -Seconds $IntervalSec
}

write-round "STOP $header at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') rounds=$round"
