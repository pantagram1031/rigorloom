<#
  M10/M11 focused: identify OUR processes only (sidecar by image name, WebView2
  by the user-data-folder argument carrying our bundle identifier), hard-kill
  the shell, then poll for 30 s.

  -Graceful  closes the window politely instead (M10).
#>
param(
  [Parameter(Mandatory = $true)][string]$Exe,
  [string]$Identifier = "dev.rigorloom.shellspike",
  [int]$Settle = 18,
  [int]$PollSeconds = 30,
  [switch]$Graceful
)
$ErrorActionPreference = "Stop"

function Ours() {
  $rows = Get-CimInstance Win32_Process |
    Select-Object ProcessId, Name, CommandLine
  $side = $rows | Where-Object { $_.Name -like "rigorloomd*" }
  $web = $rows | Where-Object {
    $_.Name -like "msedgewebview2*" -and $_.CommandLine -and
    $_.CommandLine -like "*$Identifier*"
  }
  return @{ sidecar = @($side); webview = @($web) }
}

$p = Start-Process -FilePath $Exe -PassThru
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.ElapsedMilliseconds -lt 60000) {
  $p.Refresh(); if ($p.MainWindowHandle -ne 0) { break }; Start-Sleep -Milliseconds 5
}
Write-Output ("window at {0} ms, shell pid {1}" -f $sw.ElapsedMilliseconds, $p.Id)
Start-Sleep -Seconds $Settle

$before = Ours
Write-Output ("before: sidecar pids [{0}]  webview pids [{1}]" -f `
  (($before.sidecar | ForEach-Object { $_.ProcessId }) -join ","), `
  (($before.webview | ForEach-Object { $_.ProcessId }) -join ","))

if ($Graceful) {
  Write-Output "GRACEFUL: CloseMainWindow()"
  [void]$p.CloseMainWindow()
} else {
  Write-Output "HARD KILL: Stop-Process -Force on the shell only"
  Stop-Process -Id $p.Id -Force
}

for ($t = 1; $t -le $PollSeconds; $t++) {
  Start-Sleep -Seconds 1
  $now = Ours
  $s = @($now.sidecar | Where-Object { $before.sidecar.ProcessId -contains $_.ProcessId })
  $w = @($now.webview | Where-Object { $before.webview.ProcessId -contains $_.ProcessId })
  if ($s.Count -eq 0 -and $w.Count -eq 0) {
    Write-Output ("CLEAN after {0}s: no sidecar, no webview survivors" -f $t)
    exit 0
  }
  if ($t -in 1, 2, 3, 5, 10, 15, 20, 30) {
    Write-Output ("  t+{0,-3}s sidecar alive {1}  webview alive {2}" -f $t, $s.Count, $w.Count)
  }
}
$now = Ours
Write-Output ("ORPHANS after {0}s: sidecar [{1}] webview [{2}]" -f $PollSeconds, `
  (($now.sidecar | ForEach-Object { $_.ProcessId }) -join ","), `
  (($now.webview | ForEach-Object { $_.ProcessId }) -join ","))
foreach ($x in @($now.sidecar) + @($now.webview)) {
  Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue
}
exit 1
