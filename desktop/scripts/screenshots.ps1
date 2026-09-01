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
    [double[]]$Scales = @(1.0, 1.5)
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
if (-not (Test-Path $Exe))    { Write-Error "not built: $Exe"; exit 2 }
if (-not (Test-Path $Corpus)) { Write-Error "corpus form not found: $Corpus"; exit 2 }

New-Item -ItemType Directory -Force -Path $OutDir, $RunDir | Out-Null
Remove-Item -Recurse -Force $AppData -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $AppData | Out-Null

$origLocalAppData = $env:LOCALAPPDATA
$captured = @()
$failed = 0

try {
    $env:LOCALAPPDATA = $AppData
    $env:RIGORLOOM_SMOKE_CORPUS = $Corpus
    Remove-Item Env:RIGORLOOM_SMOKE_REPORT -ErrorAction SilentlyContinue

    foreach ($scale in $Scales) {
        $pct = [int]($scale * 100)
        foreach ($pair in @(@('hold', 'document'), @('hold-agent', 'agent'))) {
            $phase = $pair[0]
            $view = $pair[1]
            $out = Join-Path $OutDir ("{0}-view-{1}pct.png" -f $view, $pct)

            $marker = Join-Path $RunDir ("ready-{0}-{1}.json" -f $view, $pct)
            Remove-Item -Force $marker -ErrorAction SilentlyContinue

            $env:RIGORLOOM_SMOKE = $phase
            $env:RIGORLOOM_SMOKE_REPORT = $marker
            $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--force-device-scale-factor=$scale"

            $proc = Start-Process -FilePath $Exe -PassThru
            try {
                # Wait for the app to say it is arranged. A fixed sleep here
                # captured the loading screen instead of the app.
                $deadline = (Get-Date).AddSeconds(120)
                while (-not (Test-Path $marker) -and (Get-Date) -lt $deadline) {
                    Start-Sleep -Milliseconds 500
                }
                if (-not (Test-Path $marker)) { throw "app never reported ready" }
                $detail = (Get-Content $marker -Raw -Encoding UTF8 | ConvertFrom-Json).detail
                Write-Host ("  dpr={0} css={1} selection={2}" -f `
                    $detail.devicePixelRatio, $detail.cssViewport, $detail.selection)

                & powershell -ExecutionPolicy Bypass -NoProfile `
                    -File (Join-Path $ScriptDir 'shot.ps1') -Out $out -SettleMs 1500 -FitToWorkArea
                if ($LASTEXITCODE -ne 0) { throw "shot.ps1 exit $LASTEXITCODE" }
                $captured += $out
                Write-Host ("captured {0} view at {1}%" -f $view, $pct)
            }
            catch {
                Write-Warning ("failed {0} view at {1}%: {2}" -f $view, $pct, $_)
                $failed++
            }
            finally {
                try { $proc.Kill(); $proc.WaitForExit(5000) | Out-Null } catch {}
                Get-Process rigorloomd -ErrorAction SilentlyContinue |
                    Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 700
            }
        }
    }
}
finally {
    $env:LOCALAPPDATA = $origLocalAppData
    Remove-Item Env:RIGORLOOM_SMOKE, Env:RIGORLOOM_SMOKE_CORPUS, Env:RIGORLOOM_SMOKE_REPORT, `
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
