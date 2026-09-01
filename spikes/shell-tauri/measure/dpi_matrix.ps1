<#
  M15 DPI matrix.

  IMPORTANT / honest limitation: this does NOT change the machine's display
  scaling. Changing a user's display settings is out of scope for the spike, so
  the scale factors below are forced on the WebView via Chromium's
  --force-device-scale-factor, delivered through
  WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS. That exercises the half of M15 where
  the risk actually lives (does web content re-layout and re-rasterise at the
  new scale, or does it get bitmap-upscaled and go soft?) but leaves the native
  window frame at the OS scale factor. The 200% row is the machine's REAL
  display scaling and needs no forcing.
#>
param(
  [Parameter(Mandatory = $true)][string]$Exe,
  [Parameter(Mandatory = $true)][string]$OutDir,
  [double[]]$Scales = @(1.0, 1.25, 1.5, 2.0)
)
$ErrorActionPreference = "Stop"
$shot = Join-Path $PSScriptRoot "shot.ps1"

foreach ($s in $Scales) {
  Get-Process rigorloom-shell-spike -ErrorAction SilentlyContinue | Stop-Process -Force
  Get-Process rigorloomd -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 2

  $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--force-device-scale-factor=$s"
  Write-Output ("--- forcing device scale factor {0} ---" -f $s)
  Start-Process -FilePath $Exe
  Start-Sleep -Seconds 9

  $pct = [int]($s * 100)
  $out = Join-Path $OutDir ("dpi-{0}pct.png" -f $pct)
  & powershell -NoProfile -ExecutionPolicy Bypass -File $shot -Out $out
}

Get-Process rigorloom-shell-spike -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process rigorloomd -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item Env:\WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ErrorAction SilentlyContinue
Write-Output "done"
