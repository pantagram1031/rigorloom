<#
  Visual evidence: both views, at two display scales, with a real Korean
  document loaded from tests/corpus/forms/.

  The machine this runs on is a single 200%-scaled display, so 100% and 150%
  are forced on the WebView through --force-device-scale-factor, the same
  method the shell spike used for its DPI matrix. State that limitation with
  the screenshots: this exercises web-content re-layout and re-rasterisation,
  which is where the risk lives, but not the native frame's own DPI handling
  and not a live scale change while running.

    powershell -ExecutionPolicy Bypass -File desktop/scripts/screenshots.ps1

  Exit codes: 0 all four captured - 2 could not run - 3 a capture failed.
#>
param(
    [string]$Corpus = "",
    # The form the runtime actually seats. `cell_borders` places 55 of the
    # corpus's 73 seats here and 0 on $Corpus, so the seat-editing shot — the
    # marquee one — has to be taken against this document or it photographs an
    # empty page and calls it the feature.
    [string]$SeatedCorpus = "",
    [double[]]$Scales = @(1.0, 1.5),
    # Re-take a subset by output name. The captures are independent — each is
    # its own process against its own arranged state — and a window that came
    # back from a restore mid-capture has produced a title-bar sliver more than
    # once. Retaking one shot beats retaking twenty.
    [string[]]$Only = @()
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $ScriptDir
$RepoRoot   = Split-Path -Parent $DesktopDir
$OutDir     = Join-Path $DesktopDir 'screenshots'
$RunDir     = Join-Path $ScriptDir '_run'
$AppData    = Join-Path $RunDir 'shot-appdata'
$Exe        = Join-Path $DesktopDir 'src-tauri\target\release\rigorloom-desktop.exe'

if (-not $Corpus) {
    $Corpus = Join-Path $RepoRoot 'tests\corpus\forms\converted\gianmun-byeolji-1ho.hwpx'
}
if (-not $SeatedCorpus) {
    $SeatedCorpus = Join-Path $RepoRoot 'tests\corpus\forms\converted\kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx'
}
if (-not (Test-Path $Exe))    { Write-Error "not built: $Exe"; exit 2 }
if (-not (Test-Path $Corpus)) { Write-Error "corpus form not found: $Corpus"; exit 2 }
if (-not (Test-Path $SeatedCorpus)) { Write-Error "seated corpus form not found: $SeatedCorpus"; exit 2 }

New-Item -ItemType Directory -Force -Path $OutDir, $RunDir | Out-Null
Remove-Item -Recurse -Force $AppData -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $AppData | Out-Null

$origAppData = $env:RIGORLOOM_APPDATA
$captured = @()
$failed = 0

try {
    $env:RIGORLOOM_APPDATA = $AppData
    $env:RIGORLOOM_SMOKE_CORPUS = $Corpus

    # The overlay shot needs a page with real geometry on it. This machine
    # cannot make one on demand — a Hancom instance is open and
    # `document/renderPrepare` refuses `com_busy` rather than terminating it —
    # so the corpus's OWN Hancom render of this same form is staged into the
    # runtime root the way renderPrepare would have staged it. Provenance and
    # the exact limits of that substitution: scripts/stage-rendered-session.py.
    #
    # `overlay-live` is captured too, and it is a REFUSAL. Both go in the
    # directory, because a screenshot set that only showed the working case
    # would be advertising a capability this machine does not have.
    $Stager = Join-Path $ScriptDir 'stage-rendered-session.py'
    $RenderedPdf = Join-Path $RepoRoot ('tests\corpus\forms\render\' +
        [IO.Path]::GetFileNameWithoutExtension($SeatedCorpus) + '.pdf')
    if (Test-Path $RenderedPdf) {
        $stageRoot = Join-Path $AppData 'runtime-root'
        New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
        $staged = (& python $Stager --root $stageRoot --hwpx $SeatedCorpus --pdf $RenderedPdf 2>&1 |
                   Select-Object -Last 1)
        if ($LASTEXITCODE -eq 0 -and $staged) {
            $env:RIGORLOOM_SMOKE_STAGED = $staged.ToString().Trim()
            Write-Host ("staged a rendered session for the overlay shot: {0}" -f $env:RIGORLOOM_SMOKE_STAGED)
        } else {
            Write-Warning "could not stage a rendered session; the overlay shot will photograph the unavailable state: $staged"
        }
    }

    $MockAgent = Join-Path $RepoRoot 'runtime\scripts\mock_agent.py'
    if (Test-Path $MockAgent) { $env:RIGORLOOM_MOCK_AGENT = $MockAgent }
    $AgentHost = Join-Path $RepoRoot 'agenthost\scripts\host.py'
    if (Test-Path $AgentHost) { $env:RIGORLOOM_AGENT_HOST = $AgentHost }
    $ModulesRoot = Join-Path $RepoRoot 'modules'
    if (Test-Path $ModulesRoot) { $env:RIGORLOOM_MODULES_ROOT = $ModulesRoot }
    # An enablement, written outside the checkout and pointed at by the same
    # variable both readers honour. Without it `packs-result` would photograph a
    # disabled button, which is a true picture of a fresh checkout but not of
    # the feature. The checkout's own modules/ is never written to.
    $EnabledFile = Join-Path $RunDir 'shot-enabled.yaml'
    [IO.File]::WriteAllText($EnabledFile,
        "schema: rigorloom-enabled-modules/v1`nenabled: [grant, report, style]`n")
    $env:RIGORLOOM_MODULES_ENABLED = $EnabledFile
    Remove-Item Env:RIGORLOOM_SMOKE_REPORT -ErrorAction SilentlyContinue

    # Document view at 100% runs first on purpose: it opens the corpus form,
    # which is what puts an entry in 최근 문서 for the welcome shot and a
    # session on disk for the entrance shot to reattach to. Everything after it
    # is photographing a state the app genuinely reached.
    # Phase 4 states are reached by RUNNING the loop, not by staging: the
    # approval in `approval.png` is an approval record the Runtime issued, and
    # the hash on the bar in `candidate.png` belongs to a candidate on disk.
    # `page.png` is whatever this machine can honestly do — on this one, the
    # Hancom COM server is broken, so it photographs the convert_failed state.
    $shots = @(
        @{ phase = 'hold';                    name = 'document-view-100pct'; scale = 1.0 },
        @{ phase = 'hold-entrance';           name = 'entrance';             scale = 1.0 },
        @{ phase = 'hold-welcome';            name = 'welcome';              scale = 1.0 },
        @{ phase = 'hold-agent';              name = 'agent-view-100pct';    scale = 1.0 },
        @{ phase = 'hold-shot-inline-edit';   name = 'inline-edit';          scale = 1.0 },
        @{ phase = 'hold-shot-queue';         name = 'review-queue';         scale = 1.0 },
        @{ phase = 'hold-shot-approval';      name = 'approval';             scale = 1.0 },
        @{ phase = 'hold-shot-verified';      name = 'candidate-verified';   scale = 1.0 },
        @{ phase = 'hold-shot-receipt';       name = 'receipt';              scale = 1.0 },
        @{ phase = 'hold-shot-page';          name = 'page-view';            scale = 1.0 },
        # 한글 오버레이. The first is a real raster with the runtime's own rects
        # on it and the candidate chooser open over a real ambiguity; the second
        # is this machine with nothing substituted, which is a refusal.
        @{ phase = 'hold-shot-overlay';       name = 'page-overlay';         scale = 1.0 },
        @{ phase = 'hold-shot-overlay-live';  name = 'page-overlay-unavailable'; scale = 1.0 },
        # THE MARQUEE SHOT: a real cell_borders seat on the page the runtime
        # seated, open in the same inline editor a tree click opens, with a
        # value part-typed. Nothing about it is arranged — the page is found by
        # asking the runtime which one carries seats.
        @{ phase = 'hold-shot-overlay-seat';  name = 'page-seat-edit';       scale = 1.0 },
        @{ phase = 'hold-shot-agent-proposal';name = 'agent-proposal';       scale = 1.0 },
        # Phase 5. Each one is reached by running the real thing: the composer
        # shot photographs a plan a real Agent Host process proposed, and the
        # settings shot photographs a real --capabilities answer with NO
        # credential stored, which is the state a new user meets.
        @{ phase = 'hold-shot-composer';      name = 'composer';             scale = 1.0 },
        @{ phase = 'hold-shot-settings';      name = 'provider-settings';    scale = 1.0 },
        @{ phase = 'hold-shot-toolbar-text';  name = 'toolbar-text';         scale = 1.0 },
        @{ phase = 'hold-shot-toolbar-page';  name = 'toolbar-page';         scale = 1.0 },
        @{ phase = 'hold-shot-packs';         name = 'task-packs';           scale = 1.0 },
        # A real module/check answer: per-checker verdicts, findings with their
        # own severities, and the runtime's own counts. Falls back to the
        # disabled state if this machine has no enablement, and the capture is
        # named for the panel rather than for a result so it cannot be mistaken
        # for a promise about what it shows.
        # `corpus` overrides which document this shot opens. The seated form is
        # the one whose grant checker returns a finding the Runtime could
        # translate into an address, which is the row the capture is FOR.
        @{ phase = 'hold-shot-packs-result';  name = 'task-pack-check';      scale = 1.0;
           corpus = $SeatedCorpus }
    )
    foreach ($scale in $Scales) {
        if ([math]::Abs($scale - 1.0) -lt 0.001) { continue }
        $pct = [int]($scale * 100)
        $shots += @{ phase = 'hold';       name = "document-view-${pct}pct"; scale = $scale }
        $shots += @{ phase = 'hold-agent'; name = "agent-view-${pct}pct";    scale = $scale }
    }

    if ($Only.Count -gt 0) { $shots = $shots | Where-Object { $Only -contains $_.name } }

    # ONE RETRY PER SHOT, and only because the failure it covers is a relaunch
    # away from being fixed. `shot.ps1` now refuses a window smaller than the
    # editor's own minimum instead of saving a title-bar sliver, and the window
    # that provokes it is one that never finished coming back from a restore —
    # a fresh process gets a fresh window. Nothing about the app's STATE is
    # retried: each attempt arranges itself from scratch through the same
    # `hold-*` phase, so a retry cannot accumulate anything a first run did.
    $attempts = @{}
    $queue = [System.Collections.Generic.Queue[object]]::new()
    foreach ($s in $shots) { $queue.Enqueue($s) }

    while ($queue.Count -gt 0) {
        $shot = $queue.Dequeue()
        $name = $shot.name
        $out = Join-Path $OutDir ("{0}.png" -f $name)
        $marker = Join-Path $RunDir ("ready-{0}.json" -f $name)
        Remove-Item -Force $marker -ErrorAction SilentlyContinue

        $env:RIGORLOOM_SMOKE = $shot.phase
        $env:RIGORLOOM_SMOKE_REPORT = $marker
        $env:RIGORLOOM_SMOKE_CORPUS =
            $(if ($shot.ContainsKey('corpus')) { $shot.corpus } else { $Corpus })
        $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--force-device-scale-factor=$($shot.scale)"

        $proc = Start-Process -FilePath $Exe -PassThru
        try {
            # Wait for the app to say it is arranged. A fixed sleep here
            # captured the loading screen instead of the app.
            # The Phase 4 stops run a real apply (preedit children) and, for
            # the page shot, a real Hancom attempt with its own 300 s bound.
            $deadline = (Get-Date).AddSeconds(
                $(if ($shot.phase -like 'hold-shot-*') { 420 } else { 150 }))
            while (-not (Test-Path $marker) -and (Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 500
            }
            if (-not (Test-Path $marker)) { throw "app never reported ready" }
            $detail = (Get-Content $marker -Raw -Encoding UTF8 | ConvertFrom-Json).detail
            Write-Host ("  dpr={0} css={1} selection={2}" -f `
                $detail.devicePixelRatio, $detail.cssViewport, $detail.selection)

            # The entrance is mid-animation by design; do not let the capture
            # settle for so long that it looks static. The approval gate
            # breathes on a 2.4 s cycle, so its capture waits long enough to
            # land somewhere legible rather than at the trough.
            $settle = switch ($shot.phase) {
                'hold-entrance'          { 400 }
                'hold-shot-approval'     { 2200 }
                default                  { 1500 }
            }
            & powershell -ExecutionPolicy Bypass -NoProfile `
                -File (Join-Path $ScriptDir 'shot.ps1') -Out $out -SettleMs $settle -FitToWorkArea
            if ($LASTEXITCODE -ne 0) { throw "shot.ps1 exit $LASTEXITCODE" }
            $captured += $out
            Write-Host ("captured {0}" -f $name)
        }
        catch {
            $tries = 1 + [int]$attempts[$name]
            $attempts[$name] = $tries
            if ($tries -lt 2) {
                Write-Warning ("retrying {0} after: {1}" -f $name, $_)
                $queue.Enqueue($shot)
            } else {
                Write-Warning ("failed {0}: {1}" -f $name, $_)
                $failed++
            }
        }
        finally {
            try { $proc.Kill(); $proc.WaitForExit(5000) | Out-Null } catch {}
            Get-Process rigorloomd -ErrorAction SilentlyContinue |
                Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 700
        }
    }
}
finally {
    if ($origAppData) { $env:RIGORLOOM_APPDATA = $origAppData }
    else { Remove-Item Env:RIGORLOOM_APPDATA -ErrorAction SilentlyContinue }
    Remove-Item Env:RIGORLOOM_SMOKE, Env:RIGORLOOM_SMOKE_CORPUS, Env:RIGORLOOM_SMOKE_REPORT, `
        Env:RIGORLOOM_MOCK_AGENT, Env:RIGORLOOM_AGENT_HOST, Env:RIGORLOOM_MODULES_ROOT, `
        Env:RIGORLOOM_SMOKE_STAGED, Env:RIGORLOOM_MODULES_ENABLED, `
        Env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ErrorAction SilentlyContinue
    Get-Process rigorloomd -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

Write-Host ""
foreach ($f in $captured) {
    $item = Get-Item $f
    Write-Host ("  {0}  ({1:N0} KiB)" -f $item.Name, ($item.Length / 1KB))
}
if ($failed -gt 0) { Write-Host "$failed capture(s) failed"; exit 3 }
Write-Host "screenshots written to $OutDir"
exit 0
