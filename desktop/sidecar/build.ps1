# Freeze the Runtime as a one-dir PyInstaller bundle.
#
# Spike finding 3: one-dir reaches ready in 264 ms standalone, one-file in
# 1394 ms, because one-file self-extracts on every launch — a 5.3x gap that
# also doubles the process count. So: one-dir, shipped under
# `bundle.resources`, NOT one-file under `externalBin`.
#
# Spike finding 4 / obligation 4: `--noconsole`, so no conhost.exe joins the
# process tree and there is no console flash. That is exactly the configuration
# that orphans on a hard kill without a job object, which is why
# src-tauri/src/jobkill.rs is not optional.
#
# The interpreter is pinned. The audit's `C:\Python313` is a partial install
# with no Lib/ and cannot create a venv, and the PATH default is a Microsoft
# Store build that PyInstaller cannot freeze from. CPython 3.12.10 under
# %LOCALAPPDATA%\Programs\Python\Python312 is the one that works.
#
#   powershell -ExecutionPolicy Bypass -File desktop/sidecar/build.ps1
#
# Exit codes: 0 built · 2 prerequisite missing · 3 build failed.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$SidecarDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $SidecarDir
$RepoRoot   = Split-Path -Parent $DesktopDir
$OutDir     = Join-Path $DesktopDir 'src-tauri\resources\rigorloomd'
$Venv       = Join-Path $SidecarDir '.venv'
$Work       = Join-Path $SidecarDir 'build'
$Dist       = Join-Path $SidecarDir 'dist'

$Pinned = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
if ($env:RIGORLOOM_SIDECAR_PYTHON) { $Pinned = $env:RIGORLOOM_SIDECAR_PYTHON }

if (-not (Test-Path $Pinned)) {
    Write-Error "pinned interpreter not found: $Pinned`nSet RIGORLOOM_SIDECAR_PYTHON to a non-Store CPython 3.12."
    exit 2
}
$version = & $Pinned -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
Write-Host "interpreter: $Pinned ($version)"
if ($version -notlike '3.12.*') {
    Write-Error "expected CPython 3.12.x, got $version"
    exit 2
}

# --- project-local build venv ------------------------------------------------
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    Write-Host 'creating the sidecar build venv'
    & $Pinned -m venv $Venv
    if ($LASTEXITCODE -ne 0) { exit 3 }
}
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
& $VenvPy -m pip install --disable-pip-version-check --quiet 'pyinstaller==6.22.2'
if ($LASTEXITCODE -ne 0) { exit 3 }

# --- freeze ------------------------------------------------------------------
# The Runtime is stdlib-only and resolves its siblings through sys.path the way
# every repo script does, so the runtime modules go in as hidden imports and the
# engine/pipeline scripts go in as DATA: rigorloomd.py executes them from source
# with runpy when the Runtime spawns them as children.
Remove-Item -Recurse -Force $Work, $Dist -ErrorAction SilentlyContinue

$runtimeScripts = Join-Path $RepoRoot 'runtime\scripts'
$hidden = @()
Get-ChildItem -Path $runtimeScripts -Filter '*.py' | ForEach-Object {
    $hidden += '--hidden-import'
    $hidden += $_.BaseName
}

# The engine scripts ship as data and run through runpy, so PyInstaller's
# analysis never sees their imports. deps.py derives the closure statically so
# a new engine import cannot silently produce a build that answers initialize
# and then dies on document/inspect. See desktop/sidecar/deps.py.
$engineDeps = & $VenvPy (Join-Path $SidecarDir 'deps.py') $RepoRoot
if ($LASTEXITCODE -ne 0) {
    Write-Error 'deps.py could not compute the engine import closure'
    exit 3
}
foreach ($module in $engineDeps) {
    if ($module) { $hidden += '--hidden-import'; $hidden += $module }
}
Write-Host ("hidden imports: {0} runtime modules + {1} engine dependencies" -f `
    (Get-ChildItem -Path $runtimeScripts -Filter '*.py').Count, $engineDeps.Count)

# Phase 5 adds three payloads, all of them run through the same interpreter
# role as the engine scripts:
#
#   agenthost\scripts  the Agent Host CLI. host.py resolves runtime/scripts as
#                      parents[2]/runtime/scripts, which is exactly this layout,
#                      so a packaged install can talk to a provider with no
#                      Python on the machine.
#   modules            the distribution-module DECLARATIONS the 작업 팩 list
#                      reads through pipeline\scripts\module_registry.py. 2.0
#                      MiB against a 23 MiB payload, and without it a shipped
#                      build can only say it has no packs.
#   pyproject.toml     module_registry gates each manifest's `requires.rigorloom`
#                      against the project version, which it reads from here.
$addData = @(
    "$RepoRoot\engine\scripts;repo\engine\scripts",
    "$RepoRoot\pipeline\scripts;repo\pipeline\scripts",
    "$RepoRoot\runtime\scripts;repo\runtime\scripts",
    "$RepoRoot\agenthost\scripts;repo\agenthost\scripts",
    "$RepoRoot\modules;repo\modules",
    "$RepoRoot\pyproject.toml;repo"
)
$dataArgs = @()
foreach ($entry in $addData) { $dataArgs += '--add-data'; $dataArgs += $entry }

Push-Location $SidecarDir
try {
    & $VenvPy -m PyInstaller `
        --name rigorloomd `
        --onedir `
        --noconsole `
        --noconfirm `
        --clean `
        --distpath $Dist `
        --workpath $Work `
        --specpath $SidecarDir `
        --paths $runtimeScripts `
        @hidden `
        @dataArgs `
        (Join-Path $SidecarDir 'rigorloomd.py')
    if ($LASTEXITCODE -ne 0) { exit 3 }
} finally {
    Pop-Location
}

$built = Join-Path $Dist 'rigorloomd'
if (-not (Test-Path (Join-Path $built 'rigorloomd.exe'))) {
    Write-Error 'PyInstaller produced no rigorloomd.exe'
    exit 3
}

# --- publish into the Tauri resource tree ------------------------------------
Remove-Item -Recurse -Force $OutDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutDir) | Out-Null
Copy-Item -Recurse -Force $built $OutDir

$size = (Get-ChildItem -Recurse $OutDir | Measure-Object -Property Length -Sum).Sum
Write-Host ("sidecar published: {0} ({1:N1} MiB)" -f $OutDir, ($size / 1MB))

# --- smoke the frozen binary in both of its roles ----------------------------
# PyInstaller 6 puts --add-data payloads under _internal/, which is also what
# sys._MEIPASS resolves to in a one-dir build; rigorloomd.bundled_engine_root()
# looks there. Assert the layout rather than trusting it.
$exe = Join-Path $OutDir 'rigorloomd.exe'
$formInspect = Join-Path $OutDir '_internal\repo\engine\scripts\form_inspect.py'
if (-not (Test-Path $formInspect)) {
    Write-Error "bundled engine scripts missing at $formInspect"
    exit 3
}

# Role 2 first, because it is the one that is easy to get wrong: under
# PyInstaller sys.executable IS this exe, and rt_engine spawns its children as
# [sys.executable, "<...>/form_inspect.py", ...]. If this does not work,
# document/inspect recursively launches a second server and hangs.
& $exe $formInspect '--help' > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "the frozen binary cannot run form_inspect.py as a child (exit $LASTEXITCODE). document/inspect would hang."
    exit 3
}
Write-Host 'interpreter role: form_inspect.py --help ok'

# The two Phase 5 payloads, exercised rather than assumed present. Both run
# through the interpreter role, and both were silently absent before this
# slice — which is exactly the class of failure the Phase 4 evidence caught
# when the packaged sidecar turned out to predate the branch it was shipping.
$hostScript = Join-Path $OutDir '_internal\repo\agenthost\scripts\host.py'
if (-not (Test-Path $hostScript)) {
    Write-Error "bundled agent host missing at $hostScript"
    exit 3
}
& $exe $hostScript '--capabilities' '--provider' 'mock' > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "the frozen binary cannot run the agent host (exit $LASTEXITCODE). The composer would have nowhere to send."
    exit 3
}
Write-Host 'interpreter role: agent host --capabilities ok'

$registry = Join-Path $OutDir '_internal\repo\pipeline\scripts\module_registry.py'
$bundledModules = Join-Path $OutDir '_internal\repo\modules'
& $exe $registry '--modules-root' $bundledModules `
    '--pyproject' (Join-Path $OutDir '_internal\repo\pyproject.toml') 'list' > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "the frozen binary cannot list the bundled task packs (exit $LASTEXITCODE)."
    exit 3
}
Write-Host 'interpreter role: module registry list ok'

# Role 1: a real initialize handshake over stdio against the frozen server.
$probeRoot = Join-Path $env:TEMP ('rigorloomd-probe-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $probeRoot | Out-Null
$frame = '{"kind":"request","id":"1","method":"initialize","params":{"protocolVersion":"0","client":{"name":"build.ps1","version":"0"},"unknownFieldPolicy":"reject"}}'
$framePath = Join-Path $probeRoot 'in.jsonl'
$outPath = Join-Path $probeRoot 'out.jsonl'
[IO.File]::WriteAllText($framePath, $frame + "`n")
# The sidecar logs its readiness line to stderr, and PowerShell turns native
# stderr into a terminating NativeCommandError under $ErrorActionPreference =
# 'Stop'. Start-Process keeps the two streams apart without that.
$proc = Start-Process -FilePath $exe `
    -ArgumentList @('--entry', 'host', '--root', $probeRoot) `
    -RedirectStandardInput $framePath `
    -RedirectStandardOutput $outPath `
    -RedirectStandardError (Join-Path $probeRoot 'err.log') `
    -NoNewWindow -PassThru -Wait
$reply = if (Test-Path $outPath) { Get-Content $outPath -First 1 } else { $null }
$serveExit = $proc.ExitCode
# The probe is `--noconsole`, and this script does not job-confine it — that is
# jobkill.rs's job inside the app, and it does not apply here. Start-Process
# -Wait can return while the process is still winding down, and the survivor
# then keeps the build script's process tree open: a caller that waits on the
# tree (a CI runner, or a background shell) sees a build that printed "exit 0"
# and then hung for a quarter of an hour. Reap it explicitly.
Get-Process -Id $proc.Id -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $probeRoot -ErrorAction SilentlyContinue
if ($serveExit -ne 0) {
    Write-Error "the frozen server exited $serveExit on a clean EOF shutdown"
    exit 3
}
if (-not $reply -or $reply -notmatch '"kind"\s*:\s*"response"') {
    Write-Error "the frozen server did not answer initialize. Got: $reply"
    exit 3
}
Write-Host 'serve role: initialize answered'
exit 0
