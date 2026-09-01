<#
  Scripted end-to-end smoke against the BUILT app and a real corpus HWPX.

  Two launches of the same executable, because close/reopen has to be a real
  process boundary to mean anything:

    run 1 (phase "open")     opens tests/corpus/forms/converted/<form>.hwpx,
                             checks the tree against the runtime's own counts,
                             switches views both ways and asserts the shared
                             state is byte-identical, then exits.
    run 2 (phase "reattach") starts cold, finds the session run 1 left on disk
                             under --root, re-reads it, and asserts the same
                             source hash — with no terminal involved.

  The assertions live in the app (src/smoke.ts) and run through the same
  actions.ts functions a click calls. This script owns process lifecycle,
  timeouts, orphan checks and exit codes.

    powershell -ExecutionPolicy Bypass -File desktop/scripts/smoke.ps1

  Exit codes: 0 all checks passed · 3 a check failed · 2 could not run.
#>
param(
    [string]$Corpus = "",
    [int]$TimeoutSec = 240,
    [switch]$KeepRoot
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $ScriptDir
$RepoRoot   = Split-Path -Parent $DesktopDir
$RunDir     = Join-Path $ScriptDir '_run'
$Exe        = Join-Path $DesktopDir 'src-tauri\target\release\rigorloom-desktop.exe'

if (-not $Corpus) {
    $Corpus = Join-Path $RepoRoot 'tests\corpus\forms\converted\gianmun-byeolji-1ho.hwpx'
}
if (-not (Test-Path $Exe))    { Write-Error "not built: $Exe`nRun desktop/scripts/build-clean.ps1 first."; exit 2 }
if (-not (Test-Path $Corpus)) { Write-Error "corpus form not found: $Corpus"; exit 2 }

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$SmokeRoot = Join-Path $RunDir 'smoke-root'
$AppData   = Join-Path $RunDir 'appdata'
# A clean user: the shell has never run, remembers nothing, and the runtime
# root is empty. Objective: "a clean user can open a supported document".
Remove-Item -Recurse -Force $SmokeRoot, $AppData -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $SmokeRoot, $AppData | Out-Null

function Invoke-Phase {
    param([string]$Phase, [string]$ReportPath)

    Remove-Item -Force $ReportPath -ErrorAction SilentlyContinue
    $env:RIGORLOOM_SMOKE = $Phase
    $env:RIGORLOOM_SMOKE_CORPUS = $Corpus
    $env:RIGORLOOM_SMOKE_REPORT = $ReportPath
    # Redirect the app's own data dir so a developer's real prefs and sessions
    # are never read or written by the smoke.
    $env:LOCALAPPDATA = $AppData

    # Not minimised: WebView2 throttles a minimised window's timers and
    # withholds rAF entirely, which is a good way to make a harness hang.
    $proc = Start-Process -FilePath $Exe -PassThru
    $exited = $proc.WaitForExit($TimeoutSec * 1000)
    if (-not $exited) {
        Write-Warning "phase '$Phase' did not exit within ${TimeoutSec}s; killing"
        try { $proc.Kill() } catch {}
        return @{ phase = $Phase; timedOut = $true; exit = -1; report = $null }
    }
    $report = $null
    if (Test-Path $ReportPath) {
        # -Encoding UTF8 is required, not cosmetic: the report contains Korean
        # document text, Get-Content defaults to the ANSI codepage (cp949 here),
        # and the mangled bytes break ConvertFrom-Json with an error that points
        # at a character offset rather than at the encoding.
        $raw = Get-Content $ReportPath -Raw -Encoding UTF8
        if ($raw -and $raw.Trim()) {
            try { $report = $raw | ConvertFrom-Json }
            catch { Write-Warning "phase '$Phase' wrote an unreadable report: $_" }
        }
    }
    return @{ phase = $Phase; timedOut = $false; exit = $proc.ExitCode; report = $report }
}

function Show-Report {
    param($Result)
    Write-Host ""
    Write-Host ("── phase {0} ── exit {1}" -f $Result.phase, $Result.exit)
    if (-not $Result.report) {
        Write-Host "  (no report written)"
        return $false
    }
    foreach ($c in $Result.report.checks) {
        $mark = if ($c.ok) { "PASS" } else { "FAIL" }
        $line = "  [{0}] {1}" -f $mark, $c.name
        if ($c.detail) { $line += "  — $($c.detail)" }
        Write-Host $line
    }
    Write-Host ("  {0} passed, {1} failed" -f $Result.report.passed, $Result.report.failed)
    return ($Result.report.failed -eq 0)
}

$origLocalAppData = $env:LOCALAPPDATA
try {
    $openResult = Invoke-Phase -Phase 'open' -ReportPath (Join-Path $RunDir 'report-open.json')
    $openOk = Show-Report $openResult

    # M10/M11: nothing may outlive the shell. The job object is the mechanism;
    # this is the check that it worked.
    Start-Sleep -Seconds 3
    $orphans = @(Get-Process rigorloomd -ErrorAction SilentlyContinue)
    if ($orphans.Count -gt 0) {
        Write-Host ("  [FAIL] no orphaned sidecar after the shell exits — found {0}" -f $orphans.Count)
        $orphans | Stop-Process -Force -ErrorAction SilentlyContinue
        $openOk = $false
    } else {
        Write-Host "  [PASS] no orphaned sidecar after the shell exits"
    }

    $reattachResult = Invoke-Phase -Phase 'reattach' -ReportPath (Join-Path $RunDir 'report-reattach.json')
    $reattachOk = Show-Report $reattachResult
}
finally {
    $env:LOCALAPPDATA = $origLocalAppData
    Remove-Item Env:RIGORLOOM_SMOKE, Env:RIGORLOOM_SMOKE_CORPUS, Env:RIGORLOOM_SMOKE_REPORT -ErrorAction SilentlyContinue
    Get-Process rigorloomd -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if (-not $KeepRoot) { Remove-Item -Recurse -Force $SmokeRoot -ErrorAction SilentlyContinue }
}

Write-Host ""
if ($openOk -and $reattachOk) {
    Write-Host "SMOKE PASS"
    exit 0
}
Write-Host "SMOKE FAIL"
exit 3
