<#
  Scripted end-to-end smoke against the BUILT app and a real corpus HWPX.

  Five launches of the same executable. Separate processes, because close and
  reopen has to be a real process boundary to mean anything, and because a
  phase that inherited another phase's in-memory state would be proving less
  than it looks like it proves:

    run 1 (phase "open")     opens tests/corpus/forms/converted/<form>.hwpx,
                             checks the tree against the runtime's own counts,
                             switches views both ways and asserts the shared
                             state is byte-identical, then exits.
    run 2 (phase "reattach") starts cold, finds the session run 1 left on disk
                             under --root, re-reads it, and asserts the same
                             source hash — with no terminal involved.
    run 3 (phase "edit")     THE EDITING LOOP, headless and complete: click a
                             fill seat, type, queue, watch the T30 preflight
                             refuse and be resolved with the engine's own
                             suggestion, prove a queue bound to another
                             document cannot be approved, approve, apply,
                             assert the candidate sha256 AND that the source
                             sha256 did not move, read the receipt, export,
                             and reopen the exported file to prove it loads.
    run 4 (phase "agent")    the mock agent proposes through the AGENT door,
                             its plan lands in the same queue, and it cannot
                             approve — the host does, exactly as for a manual
                             edit.
    run 5 (phase "page")     페이지 보기 against what this machine can really
                             do. The Hancom COM server here is broken, so
                             renderPrepare returns convert_failed; the
                             assertion is that the refusal is drawn as a
                             designed state carrying the runtime's own detail,
                             not that it succeeds.

  The assertions live in the app (src/smoke.ts) and run through the same
  actions.ts functions a click calls. This script owns process lifecycle,
  timeouts, orphan checks and exit codes.

  STALENESS IS NEVER EXERCISED BY MUTATING A SESSION COPY. Run 3 opens a
  second, genuinely different corpus form while a queue is pending. The
  session copies are read-only for the whole run and nothing here writes into
  the runtime root by hand.

    powershell -ExecutionPolicy Bypass -File desktop/scripts/smoke.ps1
    powershell -ExecutionPolicy Bypass -File desktop/scripts/smoke.ps1 -Only edit

  Exit codes: 0 all checks passed · 3 a check failed · 2 could not run.
#>
param(
    [string]$Corpus = "",
    [string]$Corpus2 = "",
    [int]$TimeoutSec = 300,
    [switch]$KeepRoot,
    # Run a subset. Handy while iterating; the evidence run passes nothing.
    [string[]]$Only = @()
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
if (-not $Corpus2) {
    # A DIFFERENT form, not a copy: the staleness check is only worth anything
    # if the two sessions really are bound to different bytes.
    $Corpus2 = Join-Path $RepoRoot 'tests\corpus\forms\converted\gianmun-byeolji-2ho.hwpx'
}
if (-not (Test-Path $Exe))    { Write-Error "not built: $Exe`nRun desktop/scripts/build-clean.ps1 first."; exit 2 }
if (-not (Test-Path $Corpus)) { Write-Error "corpus form not found: $Corpus"; exit 2 }
if (-not (Test-Path $Corpus2)) { Write-Error "second corpus form not found: $Corpus2"; exit 2 }

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$AppData = Join-Path $RunDir 'appdata'
$ExportDir = Join-Path $RunDir 'export'
# A clean user: the shell has never run, remembers nothing, and the runtime
# root is empty. Objective: "a clean user can open a supported document".
#
# One directory, not two. There used to be a separate $SmokeRoot here that was
# created and deleted but never handed to the app, which made the isolation
# look more thorough than it was. The runtime root lives under $AppData, so
# wiping that wipes both prefs and sessions.
Remove-Item -Recurse -Force $AppData, $ExportDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $AppData, $ExportDir | Out-Null

# The mock agent runs as a child of the app, so the app has to be told where
# its script is. A packaged build has no repo inside it; this is what lets the
# RELEASE executable — the only one this script ever launches — reach the
# agent door without the button pretending to exist in a shipped install.
$MockAgent = Join-Path $RepoRoot 'runtime\scripts\mock_agent.py'

function Invoke-Phase {
    param([string]$Phase, [string]$ReportPath)

    Remove-Item -Force $ReportPath -ErrorAction SilentlyContinue
    $env:RIGORLOOM_SMOKE = $Phase
    $env:RIGORLOOM_SMOKE_CORPUS = $Corpus
    $env:RIGORLOOM_SMOKE_CORPUS2 = $Corpus2
    $env:RIGORLOOM_SMOKE_REPORT = $ReportPath
    $env:RIGORLOOM_SMOKE_EXPORT = Join-Path $ExportDir 'candidate.hwpx'
    if (Test-Path $MockAgent) { $env:RIGORLOOM_MOCK_AGENT = $MockAgent }
    # Redirect the app's own data dir so a developer's real prefs and sessions
    # are never read or written by the smoke.
    #
    # This MUST be RIGORLOOM_APPDATA and not $env:LOCALAPPDATA. Tauri resolves
    # app_local_data_dir() through SHGetKnownFolderPath, which reads the user
    # profile from the OS and ignores the environment variable, so the old
    # redirect silently did nothing: the smoke ran against the developer's real
    # prefs, inherited lastSessionId from the previous run, and booted straight
    # into a document — which is why the welcome-screen checks failed.
    $env:RIGORLOOM_APPDATA = $AppData

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

$origAppData = $env:RIGORLOOM_APPDATA
$allOk = $true
$totals = @{ passed = 0; failed = 0 }
$ran = @()

# Ordered, because run 2 depends on what run 1 left on disk. Everything after
# that opens its own session and is order-independent.
$phases = @('open', 'reattach', 'edit', 'agent', 'page')
if ($Only.Count -gt 0) { $phases = $phases | Where-Object { $Only -contains $_ } }

try {
    foreach ($phase in $phases) {
        $result = Invoke-Phase -Phase $phase -ReportPath (Join-Path $RunDir "report-$phase.json")
        $ok = Show-Report $result
        if (-not $ok) { $allOk = $false }
        if ($result.report) {
            $totals.passed += [int]$result.report.passed
            $totals.failed += [int]$result.report.failed
        }
        $ran += $phase

        # M10/M11 after the FIRST phase: nothing may outlive the shell. The job
        # object is the mechanism; this is the check that it worked. Once is
        # enough — the mechanism does not vary by phase — but it has to be
        # between two real process boundaries to mean anything.
        if ($phase -eq 'open') {
            Start-Sleep -Seconds 3
            $orphans = @(Get-Process rigorloomd -ErrorAction SilentlyContinue)
            if ($orphans.Count -gt 0) {
                Write-Host ("  [FAIL] no orphaned sidecar after the shell exits — found {0}" -f $orphans.Count)
                $orphans | Stop-Process -Force -ErrorAction SilentlyContinue
                $allOk = $false
            } else {
                Write-Host "  [PASS] no orphaned sidecar after the shell exits"
            }
        }
    }

    # The export is a file that left the application. Check it from OUT HERE,
    # not only from inside the app that wrote it: the in-app check compares
    # hashes the app computed, and this one compares against the receipt on
    # disk with a hasher the app had nothing to do with.
    if ($ran -contains 'edit') {
        $exported = Join-Path $ExportDir 'candidate.hwpx'
        $exportedReceipt = "$exported.receipt.json"
        if ((Test-Path $exported) -and (Test-Path $exportedReceipt)) {
            $actual = (Get-FileHash -Algorithm SHA256 -Path $exported).Hash.ToLowerInvariant()
            $bound  = (Get-Content $exportedReceipt -Raw -Encoding UTF8 |
                       ConvertFrom-Json).candidate.sha256
            if ($actual -eq $bound) {
                Write-Host ("  [PASS] the exported file matches the digest its receipt binds — {0}" -f $actual.Substring(0, 16))
            } else {
                Write-Host ("  [FAIL] exported file hashes {0}, receipt binds {1}" -f $actual, $bound)
                $allOk = $false
            }
        } else {
            Write-Host ("  [FAIL] the export phase left no file pair at {0}" -f $exported)
            $allOk = $false
        }
    }
}
finally {
    if ($origAppData) { $env:RIGORLOOM_APPDATA = $origAppData }
    else { Remove-Item Env:RIGORLOOM_APPDATA -ErrorAction SilentlyContinue }
    Remove-Item Env:RIGORLOOM_SMOKE, Env:RIGORLOOM_SMOKE_CORPUS, Env:RIGORLOOM_SMOKE_CORPUS2, `
        Env:RIGORLOOM_SMOKE_REPORT, Env:RIGORLOOM_SMOKE_EXPORT, Env:RIGORLOOM_MOCK_AGENT `
        -ErrorAction SilentlyContinue
    Get-Process rigorloomd -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if (-not $KeepRoot) { Remove-Item -Recurse -Force $AppData -ErrorAction SilentlyContinue }
}

Write-Host ""
Write-Host ("── total ── {0} passed, {1} failed across {2}" -f $totals.passed, $totals.failed, ($ran -join ', '))
if ($allOk) {
    Write-Host "SMOKE PASS"
    exit 0
}
Write-Host "SMOKE FAIL"
exit 3
