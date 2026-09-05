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

# The rasterizer, and why it is no longer left out.
#
# `rt_render` and `rt_geometry` treat PyMuPDF as an OPTIONAL dependency and both
# report `rasterizer_missing` honestly when it is absent — which is correct for a
# bare interpreter and was wrong for the shipped bundle. The frozen sidecar had
# no PyMuPDF, so a packaged install answered `rasterizer_missing` for every PDF
# it was ever handed: 페이지 보기 could not draw a page, and `document/pageGeometry`
# could not return a single rect, on any machine, ever. Shipping a page mode
# inside a bundle that structurally cannot produce a page is the same class of
# defect as Phase 4's pre-merge sidecar — the app says a thing is possible and
# the payload makes it impossible.
#
# Pinned to the version the dev interpreter carries, so a packaged run and a
# `--dev` run cannot disagree about what the renderer read off a page. Costs
# roughly 20 MiB against a 23 MiB payload; the role checks below prove it landed.
& $VenvPy -m pip install --disable-pip-version-check --quiet 'pymupdf==1.27.2.3'
if ($LASTEXITCODE -ne 0) { exit 3 }

# --- freeze ------------------------------------------------------------------
# The Runtime is stdlib-only and resolves its siblings through sys.path the way
# every repo script does, so the runtime modules go in as hidden imports and the
# engine/pipeline scripts go in as DATA: rigorloomd.py executes them from source
# with runpy when the Runtime spawns them as children.
foreach ($ownedBuildPath in @($Work, $Dist)) {
    if (Test-Path -LiteralPath $ownedBuildPath) {
        Remove-Item -LiteralPath $ownedBuildPath -Recurse -Force -ErrorAction Stop
    }
}

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

# Both spellings. `rt_render.RASTERIZER_MODULES` imports by name at CALL time
# ("pymupdf" first, "fitz" second), so PyInstaller's static analysis never sees
# either one and would leave the wheel out of a bundle that pip had installed
# into the build venv. Naming them here is what pulls in the hook that collects
# the native libraries alongside.
$hidden += '--hidden-import'; $hidden += 'pymupdf'
$hidden += '--hidden-import'; $hidden += 'fitz'
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
# Build output is copied into a unique sibling first and compared file-for-file
# before the previous resource tree is touched. A locked/stale OutDir is a hard
# build failure: copying on top of it can silently combine two sidecar versions.
function Get-TreeManifest([string]$Root) {
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $rootPrefix = $rootFull.TrimEnd('\') + '\'
    return @(
        Get-ChildItem -LiteralPath $rootFull -Recurse -File | ForEach-Object {
            [pscustomobject]@{
                path = $_.FullName.Substring($rootPrefix.Length).Replace('\', '/')
                bytes = $_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            }
        } | Sort-Object path
    )
}

$resourceParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $OutDir))
$outFull = [System.IO.Path]::GetFullPath($OutDir)
if ([System.IO.Path]::GetDirectoryName($outFull) -ne $resourceParent) {
    Write-Error "refusing an unexpected sidecar output path: $outFull"
    exit 3
}
New-Item -ItemType Directory -Force -Path $resourceParent | Out-Null
$publishStage = Join-Path $resourceParent ("rigorloomd.stage." + [guid]::NewGuid().ToString('N'))

try {
    Copy-Item -LiteralPath $built -Destination $publishStage -Recurse -ErrorAction Stop
    $builtManifest = Get-TreeManifest $built
    $stageManifest = Get-TreeManifest $publishStage
    $builtJson = $builtManifest | ConvertTo-Json -Depth 4 -Compress
    $stageJson = $stageManifest | ConvertTo-Json -Depth 4 -Compress
    if ($builtJson -cne $stageJson) {
        throw 'sidecar staging tree does not match the PyInstaller output'
    }

    if (Test-Path -LiteralPath $outFull) {
        Remove-Item -LiteralPath $outFull -Recurse -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $outFull) {
            throw 'the previous sidecar output still exists after checked removal'
        }
    }
    Move-Item -LiteralPath $publishStage -Destination $outFull -ErrorAction Stop
    $publishedManifest = Get-TreeManifest $outFull
    $publishedJson = $publishedManifest | ConvertTo-Json -Depth 4 -Compress
    if ($publishedJson -cne $builtJson) {
        throw 'published sidecar tree does not match the verified staging tree'
    }
    Write-Host ("sidecar manifest: {0} files, {1:N1} MiB" -f `
        $publishedManifest.Count, (($publishedManifest | Measure-Object bytes -Sum).Sum / 1MB))
} catch {
    $failure = $_
    if (Test-Path -LiteralPath $publishStage) {
        try {
            Remove-Item -LiteralPath $publishStage -Recurse -Force -ErrorAction Stop
        } catch {
            Write-Error "sidecar staging cleanup failed at $publishStage`: $($_.Exception.Message)"
            exit 3
        }
    }
    Write-Error "sidecar publish failed: $($failure.Exception.Message)"
    exit 3
}

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

# The overlay slice's own payload. Asserted by NAME rather than trusted to the
# runtime-scripts glob above, because "the packaged sidecar was the pre-merge
# runtime" is a defect this project has already shipped once.
$geometryScript = Join-Path $OutDir '_internal\repo\runtime\scripts\rt_geometry.py'
if (-not (Test-Path $geometryScript)) {
    Write-Error "bundled runtime is missing rt_geometry.py at $geometryScript — the overlay would have no method to call."
    exit 3
}

# The 작업 팩 run button's own payload, asserted by NAME for the same reason.
# `module/check` runs a module's checker as a child of this exe; a bundle that
# froze a runtime/scripts predating rt_module.py would answer method_not_found
# to a button the shell draws as enabled. Same defect class, third outfit.
$moduleScript = Join-Path $OutDir '_internal\repo\runtime\scripts\rt_module.py'
if (-not (Test-Path $moduleScript)) {
    Write-Error "bundled runtime is missing rt_module.py at $moduleScript — the 작업 팩 실행 button would call a method the shipped runtime does not have."
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
# Two frames, not one. `initialize` proves the server answers; `capabilities/list`
# proves WHAT it answers — which is the only way to catch a bundle that froze an
# older runtime/scripts than the branch being shipped, and the only way to catch
# a rasterizer that pip installed and PyInstaller then left behind.
$frames = @(
    '{"kind":"request","id":"1","method":"initialize","params":{"protocolVersion":"0","client":{"name":"build.ps1","version":"0"},"unknownFieldPolicy":"reject"}}'
    '{"kind":"request","id":"2","method":"capabilities/list"}'
)
$framePath = Join-Path $probeRoot 'in.jsonl'
$outPath = Join-Path $probeRoot 'out.jsonl'
[IO.File]::WriteAllText($framePath, ($frames -join "`n") + "`n")
# The sidecar logs its readiness line to stderr, and PowerShell turns native
# stderr into a terminating NativeCommandError under $ErrorActionPreference =
# 'Stop'. Start-Process keeps the two streams apart without that.
$proc = Start-Process -FilePath $exe `
    -ArgumentList @('--entry', 'host', '--root', $probeRoot) `
    -RedirectStandardInput $framePath `
    -RedirectStandardOutput $outPath `
    -RedirectStandardError (Join-Path $probeRoot 'err.log') `
    -NoNewWindow -PassThru -Wait
$replies = if (Test-Path $outPath) { @(Get-Content $outPath) } else { @() }
$reply = if ($replies.Count -gt 0) { $replies[0] } else { $null }
$capsLine = if ($replies.Count -gt 1) { $replies[1] } else { $null }
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

if (-not $capsLine) {
    Write-Error 'the frozen server answered initialize but not capabilities/list'
    exit 3
}
$caps = ($capsLine | ConvertFrom-Json).result
if ($caps.methods -notcontains 'document/pageGeometry') {
    Write-Error ("the frozen server does not advertise document/pageGeometry. " +
        "This bundle predates the page-geometry merge; the overlay would call a method " +
        "the shipped runtime does not have. Methods: " + ($caps.methods -join ', '))
    exit 3
}
Write-Host 'serve role: document/pageGeometry advertised'

# The rasterizer, from the frozen interpreter's own mouth. `state: yes` means it
# imported PyMuPDF; anything else means this bundle would answer
# `rasterizer_missing` to every page request a user ever makes.
if ($caps.geometry.state -ne 'yes') {
    Write-Error ("the frozen server reports geometry state '" + $caps.geometry.state +
        "' (" + $caps.geometry.reason + "). PyMuPDF did not make it into the bundle, " +
        "so no packaged install could draw a page or place a single overlay.")
    exit 3
}
Write-Host ("serve role: rasterizer present (module {0}, geometry state {1})" -f `
    $caps.render.rasterizer.module, $caps.geometry.state)

# The SEAT derivation, from the frozen runtime's own mouth. `document/pageGeometry`
# existed before cell_borders did and answered without placing a single seat on
# any corpus form — so "the method is advertised" is no longer enough to prove
# the bundle can reach the marquee interaction. `derivationMethods` is
# rt_geometry's own list; cell_borders in it means the border scan shipped.
if ($caps.geometry.derivationMethods -notcontains 'cell_borders') {
    Write-Error ("the frozen server does not list cell_borders among its seat " +
        "derivations. This bundle predates the cell-border seat merge; the overlay " +
        "would draw a page with nothing clickable on it. Derivations: " +
        ($caps.geometry.derivationMethods -join ', '))
    exit 3
}
Write-Host ("serve role: seat derivations {0}" -f ($caps.geometry.derivationMethods -join ', '))

# SUB-LINE OFFSETS, from the frozen runtime's own mouth for the same reason.
# The caret places itself from `spans[].charX`; a bundle that does not extract
# per-character boxes answers every click by snapping to the front of the line,
# and it would do that silently — the field would open, the caret would be at
# offset 0, and nothing on screen would be wrong except the position. So the
# build refuses to ship a bundle whose runtime does not advertise them, rather
# than letting a user find out one line at a time.
if ($caps.geometry.charOffsets.emitted -ne $true) {
    Write-Error ("the frozen server does not emit sub-line character offsets " +
        "(geometry.charOffsets.emitted = " + $caps.geometry.charOffsets.emitted + "). " +
        "This bundle predates the caret merge; every click on a page line would " +
        "snap to the start of the line without saying so.")
    exit 3
}
if ($caps.geometry.charOffsets.field -ne 'spans[].charX') {
    Write-Error ("the frozen server names its offset field '" +
        $caps.geometry.charOffsets.field + "'; the shell reads spans[].charX.")
    exit 3
}
Write-Host ("serve role: sub-line offsets on {0}, unit {1}" -f `
    $caps.geometry.charOffsets.field, $caps.geometry.charOffsets.unit)

# module/check, the 작업 팩 run button's method. Advertised by NAME, because
# the shell now draws an enabled 실행 control off the back of it.
foreach ($method in @('module/list', 'module/check')) {
    if ($caps.methods -notcontains $method) {
        Write-Error ("the frozen server does not advertise $method. This bundle " +
            "predates the module/check merge; the 작업 팩 panel would offer a button " +
            "with nothing behind it. Methods: " + ($caps.methods -join ', '))
        exit 3
    }
}
Write-Host 'serve role: module/list and module/check advertised'

# And the bundled DECLARATIONS are readable through the runtime's own registry,
# not merely present on disk. `capabilities.modules` computes this without
# running anything; `state` is `unavailable` when the registry could not be
# loaded at all, which is what a bundle with modules/ but no readable manifest
# looks like. Enablement is NOT asserted — a shipped bundle enables nothing
# until an operator does, and that is the correct empty state.
if ($caps.modules.state -ne 'ready') {
    Write-Error ("the frozen server reports module capability '" + $caps.modules.state +
        "' (" + $caps.modules.reason + "). The bundled module declarations are not " +
        "readable through the runtime's own registry.")
    exit 3
}
if (@($caps.modules.discovered).Count -lt 1) {
    Write-Error ("the frozen server discovered no distribution module under " +
        $caps.modules.modulesRoot + ". The 작업 팩 panel would be empty in every " +
        "shipped install.")
    exit 3
}
Write-Host ("serve role: {0} module declarations discovered, {1} enabled ({2})" -f `
    @($caps.modules.discovered).Count, @($caps.modules.enabled).Count,
    $(if (@($caps.modules.enabled).Count -eq 0) { 'none, which is the shipped default' }
      else { ($caps.modules.enabled -join ', ') }))

# candidate/compare, the method an undo is PROVEN with (E1.4, protocol §15.4).
# Asserted by name for the reason module/check is: the 기록 panel prints a
# 되돌리기 확인됨 verdict, and a bundle predating this merge would leave that
# verdict permanently unobtainable while the button that asks for it still shows.
if ($caps.methods -notcontains 'candidate/compare') {
    Write-Error ("the frozen server does not advertise candidate/compare. This bundle " +
        "predates the lineage merge; a reversal could be proposed and applied but " +
        "never proven. Methods: " + ($caps.methods -join ', '))
    exit 3
}
Write-Host 'serve role: candidate/compare advertised'
exit 0
