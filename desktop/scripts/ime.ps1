<#
  M13/M14 against the SHIPPED inline editor: does Hangul actually compose in
  the field a person types a form value into?

  The spike answered this for a bare test page. This answers it for the real
  application, and the difference matters: the spike's field was a plain
  input on a plain page, and this one lives inside a React-controlled table
  cell with a composition handler, an Enter binding that must ignore the
  IME's own Enter, and an app-level keyboard shortcut layer above it. Every
  one of those is a way to break composition that the spike could not have
  caught.

  How it works: the app is launched into `hold-shot-inline-edit`, which opens
  a real 채움 자리 for typing and then waits. `ime_type.py` finds the window,
  brings it forward, switches the IME to Hangul, sends 두벌식 SCAN CODES —
  not Unicode injection, which would bypass the IME entirely and prove
  nothing — then Enter. The app commits the edit into the queue, and the
  queue is read back out of the app's own report.

  This one is NOT headless and cannot be: SendInput goes to the foreground
  window, and Windows refuses focus changes from a process that is not
  already in front. Run it with this console in the foreground and do not
  touch the mouse while it types.

    powershell -ExecutionPolicy Bypass -File desktop/scripts/ime.ps1

  Exit codes: 0 composed correctly · 2 could not run · 3 the field got
  something other than what was typed.
#>
param(
    [string]$Corpus = "",
    [string]$Text = "안녕하세요 서울특별시",
    [int]$TimeoutSec = 240
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $ScriptDir
$RepoRoot   = Split-Path -Parent $DesktopDir
$RunDir     = Join-Path $ScriptDir '_run'
$AppData    = Join-Path $RunDir 'ime-appdata'
$Exe        = Join-Path $DesktopDir 'src-tauri\target\release\rigorloom-desktop.exe'
$Typer      = Join-Path $ScriptDir 'ime_type.py'

if (-not $Corpus) {
    $Corpus = Join-Path $RepoRoot 'tests\corpus\forms\converted\gianmun-byeolji-1ho.hwpx'
}
if (-not (Test-Path $Exe))    { Write-Error "not built: $Exe"; exit 2 }
if (-not (Test-Path $Typer))  { Write-Error "missing: $Typer"; exit 2 }
if (-not (Test-Path $Corpus)) { Write-Error "corpus form not found: $Corpus"; exit 2 }

$Python = if ($env:RIGORLOOM_PYTHON) { $env:RIGORLOOM_PYTHON } else { "python" }

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
Remove-Item -Recurse -Force $AppData -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $AppData | Out-Null

$marker = Join-Path $RunDir 'ime-ready.json'
$final  = Join-Path $RunDir 'ime-final.json'
Remove-Item -Force $marker, $final -ErrorAction SilentlyContinue

$origAppData = $env:RIGORLOOM_APPDATA
$failed = 0
$proc = $null
try {
    $env:RIGORLOOM_APPDATA = $AppData
    $env:RIGORLOOM_SMOKE = 'hold-shot-inline-edit'
    $env:RIGORLOOM_SMOKE_CORPUS = $Corpus
    $env:RIGORLOOM_SMOKE_REPORT = $marker
    $env:RIGORLOOM_SMOKE_FINAL = $final
    # The hold phase pre-fills a value for the screenshot; for this run the
    # field must start empty so what lands in it is only what was typed.
    $env:RIGORLOOM_IME_EMPTY = '1'

    $proc = Start-Process -FilePath $Exe -PassThru
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while (-not (Test-Path $marker) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Path $marker)) { throw "app never reported ready" }
    $ready = (Get-Content $marker -Raw -Encoding UTF8 | ConvertFrom-Json).detail
    Write-Host ("  editor open at {0}" -f $ready.selection)
    if (-not $ready.editorOpen) { throw "the app did not open a seat for typing" }

    Start-Sleep -Milliseconds 800
    Write-Host "  typing 두벌식 scan codes — do not touch the keyboard or mouse"
    & $Python $Typer --text $Text --enter
    if ($LASTEXITCODE -ne 0) { throw "ime_type.py exit $LASTEXITCODE" }

    # The app writes what its queue ended up holding once the edit commits.
    $deadline = (Get-Date).AddSeconds(30)
    while (-not (Test-Path $final) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
    }
    if (-not (Test-Path $final)) { throw "the app never reported the committed value" }
    $got = (Get-Content $final -Raw -Encoding UTF8 | ConvertFrom-Json).detail

    Write-Host ""
    Write-Host ("  typed:    {0}" -f $Text)
    Write-Host ("  received: {0}" -f $got.value)
    Write-Host ("  queued:   {0}" -f $got.queued)

    if ($got.value -ceq $Text) {
        Write-Host "  [PASS] the IME composed into the shipped inline editor"
    } else {
        Write-Host "  [FAIL] the field received something else"
        $failed++
    }
    if ($got.queued -ceq $Text) {
        Write-Host "  [PASS] Enter committed the composed value into the plan queue"
    } else {
        Write-Host ("  [FAIL] the queue holds {0}" -f $got.queued)
        $failed++
    }
    if ($got.composed -eq $true) {
        Write-Host "  [PASS] the field saw real composition events, not injected characters"
    } else {
        Write-Host "  [FAIL] no compositionend fired — the IME was bypassed, so this proved nothing"
        $failed++
    }
}
catch {
    Write-Warning $_
    $failed++
}
finally {
    if ($proc) { try { $proc.Kill(); $proc.WaitForExit(5000) | Out-Null } catch {} }
    Get-Process rigorloomd -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    if ($origAppData) { $env:RIGORLOOM_APPDATA = $origAppData }
    else { Remove-Item Env:RIGORLOOM_APPDATA -ErrorAction SilentlyContinue }
    Remove-Item Env:RIGORLOOM_SMOKE, Env:RIGORLOOM_SMOKE_CORPUS, `
        Env:RIGORLOOM_SMOKE_REPORT, Env:RIGORLOOM_SMOKE_FINAL, Env:RIGORLOOM_IME_EMPTY `
        -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $AppData -ErrorAction SilentlyContinue
}

Write-Host ""
if ($failed -gt 0) { Write-Host "IME FAIL"; exit 3 }
Write-Host "IME PASS"
exit 0
