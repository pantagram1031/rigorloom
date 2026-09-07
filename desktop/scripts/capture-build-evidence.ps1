[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [string]$Executable,

    [Parameter(Mandatory = $true)]
    [string]$Sidecar,

    [Parameter(Mandatory = $true)]
    [string]$Installer,

    [Parameter(Mandatory = $true)]
    [string]$EvidenceDirectory,

    [string]$InstalledRoot,

    [string]$BuildLogDirectory,

    [switch]$AllowInstallerPatchedExecutable
)

<#
Fresh-build example (PowerShell):

  .\desktop\scripts\capture-build-evidence.ps1 `
    -Repository . `
    -Executable F:\RigorloomQA\build\rigorloom-desktop.exe `
    -Sidecar F:\RigorloomQA\build\rigorloomd.exe `
    -Installer F:\RigorloomQA\build\Rigorloom_0.1.0_x64-setup.exe `
    -EvidenceDirectory F:\RigorloomQA\card5-<sha>\evidence `
    -InstalledRoot F:\RigorloomQA\card5-<sha>\installed `
    -BuildLogDirectory F:\RigorloomQA\card5-<sha>\logs `
    -AllowInstallerPatchedExecutable

The collector proves source and copied artifact hash linkage. Even with an
installed root it deliberately does not claim GUI, IME, user-flow, uninstall,
or Card 5 acceptance.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-ExistingFile {
    param([string]$Path, [string]$Role)
    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($item.PSIsContainer) {
        throw "$Role is not a file: $Path"
    }
    return $item
}

function Get-FileRecord {
    param([System.IO.FileInfo]$File, [string]$Role)
    $hash = Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256
    return [pscustomobject][ordered]@{
        role = $Role
        path = $File.FullName
        bytes = [int64]$File.Length
        sha256 = $hash.Hash.ToLowerInvariant()
    }
}

function Invoke-CapturedText {
    param([string]$Program, [string[]]$Arguments)
    $lines = @(& $Program @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed with exit $LASTEXITCODE"
    }
    return ($lines -join [Environment]::NewLine).Trim()
}

function Get-DirectoryManifest {
    param([string]$Root)
    $resolved = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
    $files = @(
        Get-ChildItem -LiteralPath $resolved -Recurse -File | Sort-Object FullName |
            ForEach-Object {
                $relative = $_.FullName.Substring($resolved.Length).TrimStart('\').Replace('\', '/')
                $record = Get-FileRecord -File $_ -Role 'installed-file'
                [pscustomobject][ordered]@{
                    path = $relative
                    bytes = $record.bytes
                    sha256 = $record.sha256
                }
            }
    )
    $bytes = [int64](($files | Measure-Object -Property bytes -Sum).Sum)
    return [pscustomobject][ordered]@{
        root = $resolved
        fileCount = $files.Count
        bytes = $bytes
        cacheFileCount = @($files | Where-Object {
            $_.path -match '(^|/)__pycache__(/|$)' -or $_.path -match '\.pyc$'
        }).Count
        files = $files
    }
}

$repo = (Resolve-Path -LiteralPath $Repository).Path.TrimEnd('\')
$head = Invoke-CapturedText -Program 'git' -Arguments @('-C', $repo, 'rev-parse', 'HEAD')
$tree = Invoke-CapturedText -Program 'git' -Arguments @('-C', $repo, 'rev-parse', 'HEAD^{tree}')
$branch = Invoke-CapturedText -Program 'git' -Arguments @('-C', $repo, 'branch', '--show-current')
$dirty = Invoke-CapturedText -Program 'git' -Arguments @(
    '-C', $repo, 'status', '--porcelain=v1', '--untracked-files=no'
)
if ($dirty) {
    throw 'Tracked source is dirty; refusing to bind artifacts to an ambiguous tree.'
}

$sourceFiles = [ordered]@{
    packageLock = Resolve-ExistingFile -Path (Join-Path $repo 'desktop\package-lock.json') -Role 'npm-lock'
    cargoLock = Resolve-ExistingFile -Path (Join-Path $repo 'desktop\src-tauri\Cargo.lock') -Role 'cargo-lock'
}
$sourceExecutable = Resolve-ExistingFile -Path $Executable -Role 'executable'
$sourceSidecar = Resolve-ExistingFile -Path $Sidecar -Role 'sidecar'
$sourceInstaller = Resolve-ExistingFile -Path $Installer -Role 'installer'

if (Test-Path -LiteralPath $EvidenceDirectory) {
    if (@(Get-ChildItem -LiteralPath $EvidenceDirectory -Force).Count -ne 0) {
        throw "Evidence directory is not empty: $EvidenceDirectory"
    }
} else {
    New-Item -ItemType Directory -Path $EvidenceDirectory | Out-Null
}
$evidence = (Resolve-Path -LiteralPath $EvidenceDirectory).Path.TrimEnd('\')
$filesDirectory = Join-Path $evidence 'files'
New-Item -ItemType Directory -Path $filesDirectory | Out-Null

$sourceRecords = [ordered]@{
    executable = Get-FileRecord -File $sourceExecutable -Role 'executable'
    sidecar = Get-FileRecord -File $sourceSidecar -Role 'sidecar'
    installer = Get-FileRecord -File $sourceInstaller -Role 'installer'
}
$copiedRecords = [ordered]@{}
foreach ($role in @('executable', 'sidecar', 'installer')) {
    $sourceRecord = $sourceRecords[$role]
    $destination = Join-Path $filesDirectory ([System.IO.Path]::GetFileName($sourceRecord.path))
    Copy-Item -LiteralPath $sourceRecord.path -Destination $destination
    $copied = Get-FileRecord -File (Get-Item -LiteralPath $destination) -Role $role
    if ($copied.sha256 -ne $sourceRecord.sha256 -or $copied.bytes -ne $sourceRecord.bytes) {
        throw "$role changed while copying into the evidence directory"
    }
    $copiedRecords[$role] = $copied
}

$installed = $null
if ($InstalledRoot) {
    $installedManifest = Get-DirectoryManifest -Root $InstalledRoot
    $installedExe = Resolve-ExistingFile -Path (
        Join-Path $installedManifest.root 'rigorloom-desktop.exe'
    ) -Role 'installed-executable'
    $installedSidecar = Resolve-ExistingFile -Path (
        Join-Path $installedManifest.root 'resources\rigorloomd\rigorloomd.exe'
    ) -Role 'installed-sidecar'
    $installedExeRecord = Get-FileRecord -File $installedExe -Role 'installed-executable'
    $installedSidecarRecord = Get-FileRecord -File $installedSidecar -Role 'installed-sidecar'
    $executableMatchesRelease = (
        $installedExeRecord.sha256 -eq $sourceRecords.executable.sha256
    )
    if (-not $executableMatchesRelease -and -not $AllowInstallerPatchedExecutable) {
        throw 'Installed executable does not match the freshly built executable. Use the explicit installer-patch switch only when the bundler log proves that transformation.'
    }
    if (-not $executableMatchesRelease -and
        $installedExeRecord.bytes -ne $sourceRecords.executable.bytes) {
        throw 'Installer-patched executable has a different length; refusing the narrow metadata-patch exception.'
    }
    if ($installedSidecarRecord.sha256 -ne $sourceRecords.sidecar.sha256) {
        throw 'Installed sidecar does not match the freshly built sidecar.'
    }
    $installed = [pscustomobject][ordered]@{
        status = 'HASHED_NOT_UI_ACCEPTED'
        executable = $installedExeRecord
        executableMatchesRelease = $executableMatchesRelease
        executableRelationship = if ($executableMatchesRelease) {
            'byte_identical'
        } else {
            'installer_patch_explicitly_recorded'
        }
        sidecar = $installedSidecarRecord
        manifest = $installedManifest
    }
}

$buildLogs = @()
if ($BuildLogDirectory) {
    $logRoot = (Resolve-Path -LiteralPath $BuildLogDirectory).Path
    $buildLogs = @(
        Get-ChildItem -LiteralPath $logRoot -File | Sort-Object Name |
            ForEach-Object { Get-FileRecord -File $_ -Role 'build-log' }
    )
}

$signature = Get-AuthenticodeSignature -LiteralPath $sourceInstaller.FullName
$outsideCheckout = -not $evidence.StartsWith(
    $repo + '\', [System.StringComparison]::OrdinalIgnoreCase
)
$manifest = [pscustomobject][ordered]@{
    schema = 'rigorloom/build-evidence-manifest/v1'
    generatedUtc = [DateTime]::UtcNow.ToString('o')
    status = if ($installed) { 'HASHED_INSTALL_PAYLOAD' } else { 'HASHED_BUILD_ARTIFACTS' }
    card5Pass = $false
    guiImeClaimed = $false
    reason = 'Hash linkage is not GUI, IME, user-flow, or uninstall acceptance.'
    evidenceOutsideCheckout = $outsideCheckout
    source = [pscustomobject][ordered]@{
        repository = $repo
        branch = $branch
        commit = $head
        tree = $tree
        trackedDirty = $false
        locks = [pscustomobject][ordered]@{
            npm = Get-FileRecord -File $sourceFiles.packageLock -Role 'npm-lock'
            cargo = Get-FileRecord -File $sourceFiles.cargoLock -Role 'cargo-lock'
        }
    }
    environment = [pscustomobject][ordered]@{
        powershell = $PSVersionTable.PSVersion.ToString()
        node = Invoke-CapturedText -Program 'node' -Arguments @('--version')
        npm = Invoke-CapturedText -Program 'npm' -Arguments @('--version')
        rustc = Invoke-CapturedText -Program 'rustc' -Arguments @('--version')
        cargo = Invoke-CapturedText -Program 'cargo' -Arguments @('--version')
        os = (Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture)
    }
    artifacts = [pscustomobject][ordered]@{
        source = [pscustomobject]$sourceRecords
        copied = [pscustomobject]$copiedRecords
        installerSignatureStatus = $signature.Status.ToString()
        installerPatchedExecutableAllowed = [bool]$AllowInstallerPatchedExecutable
    }
    installedPayload = $installed
    buildLogs = $buildLogs
}

$manifestPath = Join-Path $evidence 'BuildEvidenceManifest.json'
$json = $manifest | ConvertTo-Json -Depth 8
$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($manifestPath, $json + [Environment]::NewLine, $utf8)
$manifestHash = Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256
[pscustomobject][ordered]@{
    manifest = $manifestPath
    sha256 = $manifestHash.Hash.ToLowerInvariant()
    sourceCommit = $head
    status = $manifest.status
    card5Pass = $false
    evidenceOutsideCheckout = $outsideCheckout
} | ConvertTo-Json -Compress
