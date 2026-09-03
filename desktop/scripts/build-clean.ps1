<#
  From-clean build, with every exit code recorded.

  Four steps, in the only order that works:

    1. npm install          — project-local, no global installs
    2. sidecar/build.ps1    — PyInstaller one-dir into src-tauri/resources
    3. npm run build        — tsc --noEmit && vite build
    4. npx tauri build      — cargo release + NSIS

  Step 2 must precede step 4: tauri.conf.json declares
  `bundle.resources: ["resources/rigorloomd/**/*"]`, and the Tauri build script
  fails outright when a resource glob matches nothing. That is the desired
  behaviour — a bundle with no sidecar would install and then never start — but
  it means the order is a real dependency, not a preference.

    powershell -ExecutionPolicy Bypass -File desktop/scripts/build-clean.ps1
    powershell -ExecutionPolicy Bypass -File desktop/scripts/build-clean.ps1 -Fresh

  -Fresh removes node_modules, the cargo target dir, dist and the sidecar venv
  first, which is what "from clean" means on a machine that has built before.

  Exit codes: 0 all four steps succeeded · 3 a step failed.
#>
param([switch]$Fresh)
$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $ScriptDir
$RunDir     = Join-Path $ScriptDir '_run'
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$Log = Join-Path $RunDir 'build-exit-codes.txt'

if ($Fresh) {
    Write-Host "-Fresh: removing node_modules, target, dist, sidecar venv"
    Remove-Item -Recurse -Force `
        (Join-Path $DesktopDir 'node_modules'), `
        (Join-Path $DesktopDir 'dist'), `
        (Join-Path $DesktopDir 'src-tauri\target'), `
        (Join-Path $DesktopDir 'src-tauri\resources'), `
        (Join-Path $DesktopDir 'sidecar\.venv'), `
        (Join-Path $DesktopDir 'sidecar\build'), `
        (Join-Path $DesktopDir 'sidecar\dist') `
        -ErrorAction SilentlyContinue
}

$steps = @()

# The step's own stdout must go to the console, NOT into this function's
# return value — otherwise `$code = Step ...` captures every line npm printed
# and the exit-code check compares an array to 0.
$script:lastStepExit = 0
function Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ""
    Write-Host "== $Name"
    $started = Get-Date
    & $Body | Out-Host
    $code = $LASTEXITCODE
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    $script:steps += [pscustomobject]@{ step = $Name; exit = $code; seconds = $elapsed }
    $script:lastStepExit = $code
    Write-Host ("-- $Name exit={0} ({1}s)" -f $code, $elapsed)
}

Push-Location $DesktopDir
try {
    Step 'npm install' { & npm install }
    if ($script:lastStepExit -ne 0) { throw "npm install failed" }

    Step 'sidecar build (PyInstaller one-dir)' {
        & powershell -ExecutionPolicy Bypass -NoProfile -File (Join-Path $DesktopDir 'sidecar\build.ps1')
    }
    if ($script:lastStepExit -ne 0) { throw "sidecar build failed" }

    Step 'npm run build (tsc + vite)' { & npm run build }
    if ($script:lastStepExit -ne 0) { throw "frontend build failed" }

    Step 'npx tauri build' { & npx tauri build }
    if ($script:lastStepExit -ne 0) { throw "tauri build failed" }
}
catch {
    Write-Host ""
    Write-Host "BUILD FAILED: $_"
}
finally {
    Pop-Location
}

$lines = $steps | ForEach-Object { "{0,-40} exit={1} {2}s" -f $_.step, $_.exit, $_.seconds }
$lines | Tee-Object -FilePath $Log
Write-Host ""
Write-Host "exit codes recorded in $Log"

# Artefact inventory: the build is only real if these exist.
$exe = Join-Path $DesktopDir 'src-tauri\target\release\rigorloom-desktop.exe'
$nsisDir = Join-Path $DesktopDir 'src-tauri\target\release\bundle\nsis'
if (Test-Path $exe) {
    Write-Host ("shell exe: {0:N2} MiB" -f ((Get-Item $exe).Length / 1MB))
}
if (Test-Path $nsisDir) {
    Get-ChildItem $nsisDir -Filter '*.exe' | ForEach-Object {
        Write-Host ("installer: {0} ({1:N2} MiB)" -f $_.Name, ($_.Length / 1MB))
    }
}

$failed = @($steps | Where-Object { $_.exit -ne 0 })
if ($failed.Count -gt 0 -or @($steps).Count -lt 4) { exit 3 }
exit 0
