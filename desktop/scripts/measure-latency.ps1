<#
  F6 latency harness against the BUILT exe and the packaged sidecar.

  Three fresh --root launches each for Home, 소논문 open, and click→hunk;
  three sidecar-alone spawn→capabilities measurements. Prints medians.

    powershell -ExecutionPolicy Bypass -File desktop/scripts/measure-latency.ps1
#>
param(
    [string]$Executable = "",
    [string]$Sidecar = "",
    [string]$Form = "",
    [string]$HunkForm = "",
    [int]$TimeoutSec = 120,
    [string]$Label = "measure"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $ScriptDir
$RunDir     = Join-Path $ScriptDir '_run'
$Exe = if ($Executable) { (Resolve-Path -LiteralPath $Executable).Path } else {
    $local = Join-Path $DesktopDir 'src-tauri\target\release\rigorloom-desktop.exe'
    $fromCargo = if ($env:CARGO_TARGET_DIR) {
        Join-Path $env:CARGO_TARGET_DIR 'release\rigorloom-desktop.exe'
    } else { '' }
    if ($fromCargo -and (Test-Path -LiteralPath $fromCargo)) {
        (Resolve-Path -LiteralPath $fromCargo).Path
    } elseif (Test-Path -LiteralPath $local) {
        (Resolve-Path -LiteralPath $local).Path
    } else { $local }
}
$SidecarExe = if ($Sidecar) { (Resolve-Path -LiteralPath $Sidecar).Path } else {
    $nextToExe = Join-Path (Split-Path -Parent $Exe) 'resources\rigorloomd\rigorloomd.exe'
    $resources = Join-Path $DesktopDir 'src-tauri\resources\rigorloomd\rigorloomd.exe'
    if (Test-Path -LiteralPath $nextToExe) { (Resolve-Path -LiteralPath $nextToExe).Path }
    elseif (Test-Path -LiteralPath $resources) { (Resolve-Path -LiteralPath $resources).Path }
    else { $resources }
}

if (-not $Form) {
    $templates = Join-Path $env:USERPROFILE 'Downloads\agenthwpx\templates'
    $found = Get-ChildItem -LiteralPath $templates -Filter '*.hwpx' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch 'verify' } |
        Select-Object -First 1
    if ($found) { $Form = $found.FullName }
}
$HunkPath = if ($HunkForm) { $HunkForm } else {
    Join-Path (Split-Path -Parent $DesktopDir) 'tests\corpus\forms\converted\kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx'
}

if (-not (Test-Path -LiteralPath $Exe)) { Write-Error "not built: $Exe"; exit 2 }
if (-not (Test-Path -LiteralPath $Form)) { Write-Error "form not found: $Form"; exit 2 }
if (-not (Test-Path -LiteralPath $SidecarExe)) { Write-Error "sidecar not found: $SidecarExe"; exit 2 }
if (-not (Test-Path -LiteralPath $HunkPath)) { Write-Error "hunk form not found: $HunkPath"; exit 2 }

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Median([double[]]$Values) {
    $sorted = @($Values | Sort-Object)
    $n = $sorted.Count
    if ($n -eq 0) { return $null }
    if ($n % 2 -eq 1) { return $sorted[($n - 1) / 2] }
    return ($sorted[$n / 2 - 1] + $sorted[$n / 2]) / 2
}

function Invoke-AppPhase {
    param([string]$Phase, [string]$Corpus = "")
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
    $appdata = Join-Path $RunDir "appdata-$Phase-$stamp"
    $report = Join-Path $RunDir "report-$Phase-$stamp.json"
    Remove-Item -Recurse -Force $appdata -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $appdata | Out-Null
    $env:RIGORLOOM_TIMING = '1'
    $env:RIGORLOOM_SMOKE = $Phase
    $env:RIGORLOOM_SMOKE_REPORT = $report
    $env:RIGORLOOM_APPDATA = $appdata
    if ($Corpus) { $env:RIGORLOOM_SMOKE_CORPUS = $Corpus }
    else { Remove-Item Env:RIGORLOOM_SMOKE_CORPUS -ErrorAction SilentlyContinue }
    $proc = Start-Process -FilePath $Exe -WindowStyle Hidden -PassThru
    $exited = $proc.WaitForExit($TimeoutSec * 1000)
    if (-not $exited) {
        try { $proc.Kill() } catch {}
        throw "phase $Phase timed out"
    }
    Remove-Item Env:RIGORLOOM_TIMING, Env:RIGORLOOM_SMOKE, Env:RIGORLOOM_SMOKE_REPORT, `
        Env:RIGORLOOM_APPDATA, Env:RIGORLOOM_SMOKE_CORPUS -ErrorAction SilentlyContinue
    Get-Process rigorloomd -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $report)) {
        throw "phase $Phase wrote no report"
    }
    $raw = Get-Content $report -Raw -Encoding UTF8
    $parsed = $raw | ConvertFrom-Json
    Remove-Item -Recurse -Force $appdata -ErrorAction SilentlyContinue
    return $parsed
}

function Measure-Sidecar {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
    $root = Join-Path $RunDir "sidecar-$stamp"
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $py = @"
import json, os, subprocess, sys, time
from pathlib import Path
exe = Path(r'''$SidecarExe''')
root = Path(r'''$root''')
init = json.dumps({
    'kind': 'request', 'id': '1', 'method': 'initialize',
    'params': {'protocolVersion': '0',
               'client': {'name': 'measure-latency', 'version': '0'},
               'unknownFieldPolicy': 'reject'}
}, separators=(',', ':')) + '\n'
caps = json.dumps({
    'kind': 'request', 'id': '2', 'method': 'capabilities/list'
}, separators=(',', ':')) + '\n'
creation = 0x08000000 if os.name == 'nt' else 0
t0 = time.perf_counter()
proc = subprocess.Popen(
    [str(exe), '--entry', 'host', '--root', str(root)],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    creationflags=creation)
proc.stdin.write(init.encode('utf-8'))
proc.stdin.write(caps.encode('utf-8'))
proc.stdin.flush()
first = proc.stdout.readline()
t_first = (time.perf_counter() - t0) * 1000
second = proc.stdout.readline()
t_caps = (time.perf_counter() - t0) * 1000
rss_mb = None
if os.name == 'nt':
    try:
        import ctypes
        from ctypes import wintypes
        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ('cb', wintypes.DWORD),
                ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t),
                ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t),
                ('PeakPagefileUsage', ctypes.c_size_t),
                ('PrivateUsage', ctypes.c_size_t),
            ]
        GetCurrentProcess = None
        psapi = ctypes.WinDLL('psapi')
        kernel = ctypes.WinDLL('kernel32')
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(counters)
        handle = kernel.OpenProcess(0x0410, False, proc.pid)
        if handle:
            ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            kernel.CloseHandle(handle)
            if ok:
                rss_mb = counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        rss_mb = None
try:
    proc.stdin.close()
except Exception:
    pass
try:
    proc.kill()
except Exception:
    pass
proc.wait(timeout=8)
first_ok = b'"kind":"response"' in first or b'"kind": "response"' in first
caps_ok = b'capabilities' in second or b'"kind":"response"' in second
print(json.dumps({
    't_first_ms': round(t_first, 1),
    't_capabilities_ms': round(t_caps, 1),
    'rss_mb': None if rss_mb is None else round(rss_mb, 1),
    'first_ok': bool(first_ok),
    'caps_ok': bool(caps_ok),
}))
"@
    $out = & python -c $py
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
    Get-Process rigorloomd -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    return ($out | ConvertFrom-Json)
}

Write-Host ("exe     {0}" -f $Exe)
Write-Host ("sidecar {0}" -f $SidecarExe)
Write-Host ("form    {0}" -f $Form)
Write-Host ("hunk    {0}" -f $HunkPath)
Write-Host ("label   {0}" -f $Label)

$homeRuns = @()
$openRuns = @()
$hunkRuns = @()
$sideRuns = @()

foreach ($i in 1..3) {
    Write-Host ("-- timing-home {0}" -f $i)
    $r = Invoke-AppPhase -Phase 'timing-home'
    $ms = [double]$r.timing.t_home_ms
    $homeRuns += $ms
    Write-Host ("   t_home_ms={0}  passed={1} failed={2}" -f $ms, $r.passed, $r.failed)
}
foreach ($i in 1..3) {
    Write-Host ("-- timing-open {0}" -f $i)
    $r = Invoke-AppPhase -Phase 'timing-open' -Corpus $Form
    $ms = [double]$r.timing.t_open_ms
    $openRuns += $ms
    Write-Host ("   t_open_ms={0}  passed={1} failed={2}" -f $ms, $r.passed, $r.failed)
}
foreach ($i in 1..3) {
    Write-Host ("-- timing-hunk {0}" -f $i)
    $r = Invoke-AppPhase -Phase 'timing-hunk' -Corpus $HunkPath
    $ms = [double]$r.timing.t_hunk_ms
    $hunkRuns += $ms
    Write-Host ("   t_hunk_ms={0}  passed={1} failed={2}" -f $ms, $r.passed, $r.failed)
}
foreach ($i in 1..3) {
    Write-Host ("-- sidecar {0}" -f $i)
    $r = Measure-Sidecar
    $sideRuns += $r
    Write-Host ("   t_first_ms={0} t_capabilities_ms={1} rss_mb={2}" -f `
        $r.t_first_ms, $r.t_capabilities_ms, $r.rss_mb)
}

$summary = [ordered]@{
    label = $Label
    t_home_ms = @{ runs = $homeRuns; median = [math]::Round((Median $homeRuns), 1); target = 2000 }
    t_open_ms = @{ runs = $openRuns; median = [math]::Round((Median $openRuns), 1); target = 1500 }
    t_hunk_ms = @{ runs = $hunkRuns; median = [math]::Round((Median $hunkRuns), 1); target = 100 }
    sidecar = @{
        t_first_ms = @($sideRuns | ForEach-Object { $_.t_first_ms })
        t_capabilities_ms = @($sideRuns | ForEach-Object { $_.t_capabilities_ms })
        rss_mb = @($sideRuns | ForEach-Object { $_.rss_mb })
        median_first_ms = [math]::Round((Median (@($sideRuns | ForEach-Object { [double]$_.t_first_ms }))), 1)
        median_caps_ms = [math]::Round((Median (@($sideRuns | ForEach-Object { [double]$_.t_capabilities_ms }))), 1)
        median_rss_mb = [math]::Round((Median (@($sideRuns | ForEach-Object { [double]$_.rss_mb }))), 1)
        target_ms = 1000
    }
}
$outPath = Join-Path $RunDir "latency-$Label.json"
($summary | ConvertTo-Json -Depth 6) | Set-Content -Encoding UTF8 $outPath
Write-Host ""
Write-Host ("Home     median {0} ms  (target 2000)  runs {1}" -f $summary.t_home_ms.median, ($homeRuns -join ', '))
Write-Host ("Open     median {0} ms  (target 1500)  runs {1}" -f $summary.t_open_ms.median, ($openRuns -join ', '))
Write-Host ("Hunk     median {0} ms  (target 100)   runs {1}" -f $summary.t_hunk_ms.median, ($hunkRuns -join ', '))
Write-Host ("Sidecar  median {0} ms to first JSONL / {1} ms to capabilities, RSS {2} MiB  (target 1000)" -f `
    $summary.sidecar.median_first_ms, $summary.sidecar.median_caps_ms, $summary.sidecar.median_rss_mb)
Write-Host ("wrote {0}" -f $outPath)
