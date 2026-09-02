<#
  M13/M14 against the SHIPPED inline editor: does Hangul actually compose in
  the field a person types into?

  The spike answered this for a bare test page. This answers it for the real
  application, and the difference matters: the spike's field was a plain
  input on a plain page, and this one lives inside a React-controlled surface
  with a composition handler, an Enter binding that must ignore the IME's own
  Enter, and an app-level keyboard shortcut layer above it. Every one of those
  is a way to break composition that the spike could not have caught.

  TWO SURFACES, AND THAT IS THE POINT OF THE SECOND RUN.

    -Surface seat  (default)  a 채움 자리 in the tree: `hold-shot-inline-edit`
    -Surface page             a CARET standing in a paragraph line on the
                              rendered page: `hold-shot-overlay-caret`

  The seat run and the page run mount the same `SeatEditor` component, so it
  was tempting to call the page surface covered by construction. It is not:
  the page field is mounted inside an absolutely-positioned overlay over a
  raster, sized from the runtime's own rect, with a caret placed by
  `setSelectionRange` rather than by `select()`. Composition inside a field
  whose selection was set programmatically is exactly the kind of thing that
  works everywhere until it does not, and "shared by construction" is not
  evidence. So the page surface is now driven by real scan codes too, and it
  asserts one thing the seat run cannot: the composed value has to arrive in
  the queue as a `set_run` op, which is the operation a paragraph line takes.

  How it works: the app is launched into the hold phase, which opens a real
  editor and then waits. `ime_type.py` finds the window, brings it forward,
  switches the IME to Hangul, sends 두벌식 SCAN CODES — not Unicode injection,
  which would bypass the IME entirely and prove nothing — then Enter. The app
  commits the edit into the queue, and the queue is read back out of the app's
  own report.

  The page run needs a page, and this machine cannot make one on demand:
  `document/renderPrepare` refuses `com_busy` whenever a Hancom is open and
  the Runtime does not terminate somebody else's session to get one. So it
  stages the corpus's OWN Hancom render exactly as smoke.ps1's overlay phase
  does — same script, same provenance, same limits.

  This one is NOT headless and cannot be: SendInput goes to the foreground
  window, and Windows refuses focus changes from a process that is not
  already in front. Run it with this console in the foreground and do not
  touch the mouse while it types.

    powershell -ExecutionPolicy Bypass -File desktop/scripts/ime.ps1
    powershell -ExecutionPolicy Bypass -File desktop/scripts/ime.ps1 -Surface page
    powershell -ExecutionPolicy Bypass -File desktop/scripts/ime.ps1 -Surface both

  Exit codes: 0 composed correctly · 2 could not run · 3 the field got
  something other than what was typed.
#>
param(
    [string]$Corpus = "",
    # The form the PAGE surface uses. Not the same as $Corpus, for the same
    # reason smoke.ps1 keeps them apart: the caret needs a form whose render
    # this repo actually has, and whose paragraphs the form scan maps.
    [string]$SeatedCorpus = "",
    [string]$Text = "안녕하세요 서울특별시",
    [ValidateSet("seat", "page", "both")]
    [string]$Surface = "seat",
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
$Stager     = Join-Path $ScriptDir 'stage-rendered-session.py'

if (-not $Corpus) {
    $Corpus = Join-Path $RepoRoot 'tests\corpus\forms\converted\gianmun-byeolji-1ho.hwpx'
}
if (-not $SeatedCorpus) {
    $SeatedCorpus = Join-Path $RepoRoot 'tests\corpus\forms\converted\kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx'
}
if (-not (Test-Path $Exe))    { Write-Error "not built: $Exe"; exit 2 }
if (-not (Test-Path $Typer))  { Write-Error "missing: $Typer"; exit 2 }
if (-not (Test-Path $Corpus)) { Write-Error "corpus form not found: $Corpus"; exit 2 }

$Python = if ($env:RIGORLOOM_PYTHON) { $env:RIGORLOOM_PYTHON } else { "python" }
$RenderedPdf = Join-Path $RepoRoot ('tests\corpus\forms\render\' +
    [IO.Path]::GetFileNameWithoutExtension($SeatedCorpus) + '.pdf')

$failed = 0
$ran = 0

# THE COUNTER IS SCRIPT-SCOPED, NOT A RETURN VALUE.
#
# A PowerShell function emits everything it does not consume, so
# `$failed += Invoke-Surface $which` collected every stray object the body
# produced and then tried to add an array to an integer. build-clean.ps1
# carries the same note about the same trap; this file learned it the same
# way, by watching a passing IME run die on the line after it printed [PASS].
$script:failedChecks = 0

function Invoke-Surface {
    param([string]$Which)

    Write-Host ""
    Write-Host ("== IME on the {0} surface" -f $Which)

    $phase   = if ($Which -eq 'page') { 'hold-shot-overlay-caret' } else { 'hold-shot-inline-edit' }
    $useForm = if ($Which -eq 'page') { $SeatedCorpus } else { $Corpus }

    Remove-Item -Recurse -Force $AppData -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $AppData | Out-Null

    $marker = Join-Path $RunDir ("ime-ready-{0}.json" -f $Which)
    $final  = Join-Path $RunDir ("ime-final-{0}.json" -f $Which)
    Remove-Item -Force $marker, $final -ErrorAction SilentlyContinue

    # The page surface needs a rendered session under the app's own runtime
    # root. Staged the way renderPrepare would have staged it; provenance and
    # limits are in stage-rendered-session.py.
    $staged = ''
    if ($Which -eq 'page') {
        if (-not (Test-Path $RenderedPdf)) {
            Write-Host ("  [FAIL] no corpus render at {0}; the page surface has no page to type on" -f $RenderedPdf)
            $script:failedChecks++
            return
        }
        $stageRoot = Join-Path $AppData 'runtime-root'
        New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
        $out = (& $Python $Stager --root $stageRoot --hwpx $SeatedCorpus --pdf $RenderedPdf 2>&1 |
                Select-Object -Last 1)
        if ($LASTEXITCODE -ne 0 -or -not $out) {
            Write-Host ("  [FAIL] could not stage a rendered session: {0}" -f $out)
            $script:failedChecks++
            return
        }
        $staged = $out.ToString().Trim()
        Write-Host ("  staged a rendered session: {0}" -f $staged)
    }

    $origAppData = $env:RIGORLOOM_APPDATA
    $proc = $null
    try {
        $env:RIGORLOOM_APPDATA = $AppData
        $env:RIGORLOOM_SMOKE = $phase
        $env:RIGORLOOM_SMOKE_CORPUS = $useForm
        $env:RIGORLOOM_SMOKE_REPORT = $marker
        $env:RIGORLOOM_SMOKE_FINAL = $final
        if ($staged) { $env:RIGORLOOM_SMOKE_STAGED = $staged }
        else { Remove-Item Env:RIGORLOOM_SMOKE_STAGED -ErrorAction SilentlyContinue }
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
        if (-not $ready.editorOpen) {
            throw "the app did not open an editor on the $Which surface"
        }
        if ($Which -eq 'page') {
            # The caret's offset is reported so this run says whether it typed
            # into a MEASURED position or into a line that snapped to its front
            # — the same distinction the status bar draws, in the evidence.
            $at = if ($null -eq $ready.caret) { 'line start (no per-character boxes)' }
                  else { "character $($ready.caret)" }
            Write-Host ("  caret at {0}, page {1}" -f $at, $ready.page)
        }

        Start-Sleep -Milliseconds 800
        Write-Host "  typing 두벌식 scan codes — do not touch the keyboard or mouse"
        & $Python $Typer --text $Text --enter
        if ($LASTEXITCODE -ne 0) { throw "ime_type.py exit $LASTEXITCODE" }

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
            Write-Host "  [PASS] the IME composed into the shipped editor"
        } else {
            Write-Host "  [FAIL] the field received something else"
            $script:failedChecks++
        }
        if ($got.queued -ceq $Text) {
            Write-Host "  [PASS] Enter committed the composed value into the plan queue"
        } else {
            Write-Host ("  [FAIL] the queue holds {0}" -f $got.queued)
            $script:failedChecks++
        }
        if ($got.composed -eq $true) {
            Write-Host "  [PASS] the field saw real composition events, not injected characters"
        } else {
            Write-Host "  [FAIL] no compositionend fired — the IME was bypassed, so this proved nothing"
            $script:failedChecks++
        }
        if ($Which -eq 'page') {
            # The assertion the seat run cannot make: a paragraph line is
            # written by `set_run`, and a composed value that arrived as a
            # `fill_cell` would mean the page surface had quietly reached the
            # wrong operation.
            if ($got.kind -ceq 'set_run') {
                Write-Host "  [PASS] the composed value queued a set_run op — the operation a paragraph line takes"
            } else {
                Write-Host ("  [FAIL] the page surface queued a {0} op" -f $got.kind)
                $script:failedChecks++
            }
        }
    }
    catch {
        Write-Warning $_
        $script:failedChecks++
    }
    finally {
        if ($proc) { try { $proc.Kill(); $proc.WaitForExit(5000) | Out-Null } catch {} }
        Get-Process rigorloomd -ErrorAction SilentlyContinue |
            Stop-Process -Force -ErrorAction SilentlyContinue
        if ($origAppData) { $env:RIGORLOOM_APPDATA = $origAppData }
        else { Remove-Item Env:RIGORLOOM_APPDATA -ErrorAction SilentlyContinue }
        Remove-Item Env:RIGORLOOM_SMOKE, Env:RIGORLOOM_SMOKE_CORPUS, `
            Env:RIGORLOOM_SMOKE_REPORT, Env:RIGORLOOM_SMOKE_FINAL, `
            Env:RIGORLOOM_SMOKE_STAGED, Env:RIGORLOOM_IME_EMPTY `
            -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $AppData -ErrorAction SilentlyContinue
    }
}

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

$surfaces = if ($Surface -eq 'both') { @('seat', 'page') } else { @($Surface) }
foreach ($which in $surfaces) {
    Invoke-Surface $which | Out-Null
    $ran++
}
$failed = $script:failedChecks

Write-Host ""
Write-Host ("{0} surface(s) driven with real scan codes" -f $ran)
if ($failed -gt 0) { Write-Host "IME FAIL"; exit 3 }
Write-Host "IME PASS"
exit 0
