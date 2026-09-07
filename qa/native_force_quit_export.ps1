# Card1 native force-quit Run-Card (Windows entry point).
#
# From the repo root on a Windows tip checkout:
#   powershell -ExecutionPolicy Bypass -File qa\native_force_quit_export.ps1
#
# Evidence:
#   qa\_artifacts\card1-force-quit.json
#
# Then flip the matrix row:
#   python qa\export_safety_card1_matrix.py --json-out qa\_artifacts\card1-matrix.json
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$Script = Join-Path $PSScriptRoot "native_force_quit_export.py"
$Out = Join-Path $PSScriptRoot "_artifacts\card1-force-quit.json"
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    if (-not $Python) {
        Write-Error "python or py is required"
        exit 2
    }
    $PyArgs = @("-3", $Script, "--json-out", $Out)
    & py @PyArgs
    exit $LASTEXITCODE
}
& python $Script --json-out $Out
exit $LASTEXITCODE
