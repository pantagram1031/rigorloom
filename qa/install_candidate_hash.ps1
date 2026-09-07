# Card5 install-candidate hash Run-Card (Windows entry point).
#
# From the repo root on a Windows machine that already copied EXE / sidecar /
# installer bytes into an *external* evidence directory:
#
#   $env:RIGORLOOM_CARD5_EVIDENCE_DIR = 'D:\rigorloom-card5-evidence'
#   powershell -ExecutionPolicy Bypass -File qa\install_candidate_hash.ps1
#
# Optional collect (still NOT an install PASS; run verify afterwards):
#
#   powershell -ExecutionPolicy Bypass -File qa\install_candidate_hash.ps1 `
#     -Mode collect -EvidenceDir 'D:\rigorloom-card5-evidence' `
#     -Exe 'D:\rigorloom-card5-evidence\files\Rigorloom.exe' `
#     -Sidecar 'D:\rigorloom-card5-evidence\files\rigorloomd.exe' `
#     -Installer 'D:\rigorloom-card5-evidence\files\Rigorloom_0.1.0_x64-setup.exe' `
#     -OutsideCheckout -CopyIntoEvidence
#
# Do not hardcode a user-profile path. This script never claims GUI / IME /
# install PASS.
param(
    [ValidateSet("verify", "collect")]
    [string]$Mode = "verify",
    [string]$EvidenceDir = $env:RIGORLOOM_CARD5_EVIDENCE_DIR,
    [string]$Exe,
    [string]$Sidecar,
    [string]$Installer,
    [switch]$OutsideCheckout,
    [switch]$CopyIntoEvidence,
    [string]$JsonOut
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$Script = Join-Path $PSScriptRoot "install_candidate_hash.py"
if (-not $JsonOut) {
    $JsonOut = Join-Path $PSScriptRoot "_artifacts\card5-hashes.json"
}
$Py = Get-Command python -ErrorAction SilentlyContinue
$PyLauncher = $null
if (-not $Py) {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $PyLauncher) {
        Write-Error "python or py is required"
        exit 2
    }
}
$ArgList = @($Script, $Mode, "--json-out", $JsonOut)
if ($EvidenceDir) {
    $ArgList += @("--evidence-dir", $EvidenceDir)
}
if ($Exe) { $ArgList += @("--exe", $Exe) }
if ($Sidecar) { $ArgList += @("--sidecar", $Sidecar) }
if ($Installer) { $ArgList += @("--installer", $Installer) }
if ($OutsideCheckout) { $ArgList += "--outside-checkout" }
if ($CopyIntoEvidence) { $ArgList += "--copy-into-evidence" }

if ($Py) {
    & python @ArgList
    exit $LASTEXITCODE
}
$PyArgs = @("-3") + $ArgList
& py @PyArgs
exit $LASTEXITCODE
