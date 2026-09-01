<#
  M8/M9 memory. Identifies OUR processes by identity rather than by walking
  ParentProcessId (WebView2 host processes do not always stay descendants of
  the shell in the CIM snapshot, which silently under-counted an earlier run).
    - shell    : image name
    - sidecar  : image name rigorloomd*
    - webview  : msedgewebview2 whose command line carries the bundle identifier
#>
param(
  [Parameter(Mandatory = $true)][string]$Exe,
  [string]$Identifier = "dev.rigorloom.shellspike",
  [string]$ShellName = "rigorloom-shell-spike",
  [int]$Settle = 25
)
$ErrorActionPreference = "Stop"

function Snapshot() {
  $rows = Get-CimInstance Win32_Process | Select-Object ProcessId, Name, CommandLine
  $ours = $rows | Where-Object {
    $_.Name -like "$ShellName*" -or
    $_.Name -like "rigorloomd*" -or
    ($_.Name -like "msedgewebview2*" -and $_.CommandLine -and $_.CommandLine -like "*$Identifier*") -or
    ($_.Name -like "conhost*" -and $_.CommandLine -and $_.CommandLine -like "*rigorloomd*")
  }
  $out = @()
  foreach ($r in $ours) {
    try { $out += Get-Process -Id $r.ProcessId -ErrorAction Stop } catch {}
  }
  return $out
}

function Report([string]$Label, $procs) {
  $ws = 0; $pv = 0
  foreach ($q in $procs) {
    Write-Output ("  {0,-26} pid {1,-7} ws {2,8:N1} MiB  private {3,8:N1} MiB" -f `
        $q.ProcessName, $q.Id, ($q.WorkingSet64 / 1MB), ($q.PrivateMemorySize64 / 1MB))
    $ws += $q.WorkingSet64; $pv += $q.PrivateMemorySize64
  }
  Write-Output ("{0}: {1} processes  workingset {2:N1} MiB  private {3:N1} MiB" -f `
      $Label, $procs.Count, ($ws / 1MB), ($pv / 1MB))
}

$p = Start-Process -FilePath $Exe -PassThru
$sw = [Diagnostics.Stopwatch]::StartNew()
while ($sw.ElapsedMilliseconds -lt 60000) {
  $p.Refresh(); if ($p.MainWindowHandle -ne 0) { break }; Start-Sleep -Milliseconds 5
}
Write-Output ("window at {0} ms, shell pid {1}; settling {2}s" -f $sw.ElapsedMilliseconds, $p.Id, $Settle)
Start-Sleep -Seconds $Settle
Report "M8 at rest" (Snapshot)

Write-Output ""
Write-Output "leaving app running for interactive measurement; shell pid $($p.Id)"
