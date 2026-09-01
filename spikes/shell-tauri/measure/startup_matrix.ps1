<#
  M1 (first paint) and M2 (sidecar ready) end to end, repeated, for both
  PyInstaller packaging modes from the SAME shell binary
  (RIGORLOOM_SPIKE_SIDECAR selects the sidecar at runtime).

  Both numbers come from the app itself, appended to
  %TEMP%\rigorloom-spike-timings.txt, so nothing is read off a screenshot.
#>
param(
  [Parameter(Mandatory = $true)][string]$Exe,
  [Parameter(Mandatory = $true)][string]$OneFile,
  [Parameter(Mandatory = $true)][string]$OneDir,
  [int]$N = 5
)
$ErrorActionPreference = "Stop"
$timings = Join-Path $env:TEMP "rigorloom-spike-timings.txt"

function Run-Arm([string]$Label, [string]$Sidecar) {
  Remove-Item $timings -ErrorAction SilentlyContinue
  $env:RIGORLOOM_SPIKE_SIDECAR = $Sidecar
  Write-Output "===== $Label ====="
  for ($i = 1; $i -le $N; $i++) {
    $p = Start-Process -FilePath $Exe -PassThru
    Start-Sleep -Seconds 11
    Get-Process -Id $p.Id -ErrorAction SilentlyContinue | Stop-Process -Force
    Get-Process rigorloomd, rigorloomd-onefile, rigorloomd-onedir -ErrorAction SilentlyContinue |
      Stop-Process -Force
    Start-Sleep -Seconds 3
  }
  if (-not (Test-Path $timings)) { Write-Output "  no timings recorded"; return }
  foreach ($kind in @("first_paint_ms", "sidecar_ready_ms")) {
    $vals = @(Select-String -Path $timings -Pattern "$kind=(\d+)" -AllMatches |
      ForEach-Object { $_.Matches } | ForEach-Object { [int]$_.Groups[1].Value })
    if ($vals.Count -eq 0) { Write-Output ("  {0}: none" -f $kind); continue }
    $s = $vals | Sort-Object
    Write-Output ("  {0,-18} runs [{1}]  median {2} ms  min {3}  max {4}" -f `
        $kind, ($vals -join ", "), $s[[math]::Floor($s.Count / 2)], $s[0], $s[-1])
  }
}

Run-Arm "one-file sidecar (bundled externalBin shape)" $OneFile
Run-Arm "one-dir sidecar (bundle.resources shape)" $OneDir
Remove-Item Env:\RIGORLOOM_SPIKE_SIDECAR -ErrorAction SilentlyContinue
Write-Output "done"
