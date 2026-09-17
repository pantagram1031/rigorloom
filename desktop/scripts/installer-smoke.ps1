<#
  Silent-install the NSIS bundle into a scratch prefix, drive one xml edit
  through the installed exe (queue → approve → apply → receipt), then
  uninstall. Never touches the machine's existing per-user install beyond
  whatever Start Menu / uninstall-registry entries THIS installer writes.

    powershell -ExecutionPolicy Bypass -File desktop/scripts/installer-smoke.ps1
#>
param(
    [string]$Installer = "",
    [string]$Prefix = ""
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = Split-Path -Parent $ScriptDir
$RepoRoot   = Split-Path -Parent $DesktopDir
$steps = @()

function Step {
    param([string]$Name, [string]$Result, [string]$Detail = "")
    $script:steps += [pscustomobject]@{ step = $Name; result = $Result; detail = $Detail }
    Write-Host ("  [{0}] {1}{2}" -f $Result, $Name, $(if ($Detail) { " — $Detail" } else { "" }))
}

function Find-Nsis {
    $dirs = @()
    if ($env:CARGO_TARGET_DIR) {
        $dirs += (Join-Path $env:CARGO_TARGET_DIR 'release\bundle\nsis')
    }
    $dirs += (Join-Path $DesktopDir 'src-tauri\target\release\bundle\nsis')
    foreach ($dir in $dirs) {
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        $found = Get-ChildItem -LiteralPath $dir -Filter '*setup.exe' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

$setup = if ($Installer) { (Resolve-Path -LiteralPath $Installer).Path } else { Find-Nsis }
if (-not $setup) {
    Write-Error "no NSIS setup.exe under release/bundle/nsis; run npx tauri build first"
    exit 2
}
$setupItem = Get-Item -LiteralPath $setup
Step 'locate NSIS bundle' 'PASS' ("{0} ({1:N1} MiB)" -f $setupItem.FullName, ($setupItem.Length / 1MB))

if (-not $Prefix) {
    $Prefix = Join-Path $env:TEMP ('rigorloom-nsis-smoke-' + [guid]::NewGuid().ToString('N'))
}
New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
$Prefix = (Resolve-Path -LiteralPath $Prefix).Path

$startMenuBefore = @(Get-ChildItem -LiteralPath (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs') -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'Rigorloom|rigorloom' })
$uninstBefore = @()
foreach ($hive in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')) {
    if (-not (Test-Path $hive)) { continue }
    foreach ($key in @(Get-ChildItem $hive -ErrorAction SilentlyContinue)) {
        $display = $null
        try { $display = $key.GetValue('DisplayName') } catch { continue }
        if ($display -match 'Rigorloom') { $uninstBefore += [string]$key.PSPath }
    }
}

# NSIS: /S silent. /D= must be last, unquoted, and names the install directory.
$installArgs = "/S /D=$Prefix"
Write-Host ("  installing with: {0} {1}" -f $setup, $installArgs)
$inst = Start-Process -FilePath $setup -ArgumentList $installArgs -Wait -PassThru
if ($inst.ExitCode -ne 0) {
    Step 'silent install' 'FAIL' ("exit $($inst.ExitCode); /S /D= prefix")
    $steps | Format-Table -AutoSize | Out-String | Write-Host
    exit 3
}
$exe = @(
    (Join-Path $Prefix 'rigorloom-desktop.exe'),
    (Join-Path $Prefix 'Rigorloom.exe')
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $exe) {
    $exe = Get-ChildItem -LiteralPath $Prefix -Filter '*.exe' -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch 'uninstall' } |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $exe) {
    Step 'silent install' 'FAIL' ("installer exit 0 but no exe under $Prefix")
    Get-ChildItem -LiteralPath $Prefix -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 40 FullName | ForEach-Object { Write-Host "    $_" }
    exit 3
}
Step 'silent install' 'PASS' ("exe $exe")

$outside = @()
$startMenuAfter = @(Get-ChildItem -LiteralPath (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs') -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'Rigorloom|rigorloom' })
foreach ($item in $startMenuAfter) {
    $beforeNames = @($startMenuBefore | ForEach-Object { $_.FullName })
    if ($beforeNames -notcontains $item.FullName) {
        $outside += "Start Menu: $($item.FullName)"
    }
}
foreach ($hive in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')) {
    if (-not (Test-Path $hive)) { continue }
    foreach ($key in @(Get-ChildItem $hive -ErrorAction SilentlyContinue |
            Where-Object { $_.GetValue('DisplayName') -match 'Rigorloom' })) {
        if ($uninstBefore -notcontains $key.PSPath) {
            $outside += "uninstall registry: $($key.PSPath) DisplayName=$($key.GetValue('DisplayName')) InstallLocation=$($key.GetValue('InstallLocation'))"
        }
    }
}
if ($outside.Count -eq 0) {
    Step 'outside-prefix writes' 'PASS' 'none observed (Start Menu / uninstall key)'
} else {
    Step 'outside-prefix writes' 'NOTE' ($outside -join ' | ')
}

$smoke = Join-Path $ScriptDir 'smoke.ps1'
Write-Host "  launching installed exe through smoke.ps1 -Only edit (fresh --root via RIGORLOOM_APPDATA)"
& powershell -ExecutionPolicy Bypass -NoProfile -File $smoke -Executable $exe -Only edit
$editCode = $LASTEXITCODE
if ($editCode -eq 0) {
    Step 'xml edit via GUI (queue → approve → apply → receipt)' 'PASS' 'smoke.ps1 -Only edit'
} else {
    Step 'xml edit via GUI (queue → approve → apply → receipt)' 'FAIL' "smoke.ps1 -Only edit exit $editCode"
}

$uninst = @(
    (Join-Path $Prefix 'uninstall.exe'),
    (Join-Path $Prefix 'Uninstall.exe')
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $uninst) {
    $uninst = Get-ChildItem -LiteralPath $Prefix -Filter '*uninstall*.exe' -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if ($uninst) {
    $u = Start-Process -FilePath $uninst -ArgumentList '/S' -Wait -PassThru
    if ($u.ExitCode -eq 0) {
        Step 'silent uninstall' 'PASS' $uninst
    } else {
        Step 'silent uninstall' 'FAIL' ("exit $($u.ExitCode) from $uninst")
    }
} else {
    Step 'silent uninstall' 'FAIL' "no Uninstall.exe under $Prefix"
}

Write-Host ""
Write-Host "── installer smoke ──"
$steps | ForEach-Object {
    Write-Host ("  {0,-55} {1}  {2}" -f $_.step, $_.result, $_.detail)
}
$failed = @($steps | Where-Object { $_.result -eq 'FAIL' }).Count
if ($failed -gt 0) { exit 3 }
exit 0
