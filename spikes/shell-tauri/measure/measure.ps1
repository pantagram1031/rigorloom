<#
  Spike measurement harness (throwaway). Every number in
  docs/desktop-shell-spike.md ## Decision comes from one of these modes.

  Usage:  powershell -NoProfile -File measure/measure.ps1 -Mode <mode> -Exe <path>
  Modes:
    startup   spawn -> MainWindowHandle != 0, wall ms (repeat -N times)
    memory    launch, wait -Settle s, sum working set / private bytes over the
              whole process tree (shell + WebView2 children + sidecar)
    orphan    launch, wait, Stop-Process -Force the SHELL ONLY, then report
              whether the sidecar is still alive after 5 s   (M10/M11)
    tree      launch, wait, print the process tree, leave it running
#>
param(
  [Parameter(Mandatory = $true)][string]$Mode,
  [Parameter(Mandatory = $true)][string]$Exe,
  [int]$N = 5,
  [int]$Settle = 20
)

$ErrorActionPreference = "Stop"

function Get-Descendants([int]$RootPid) {
  $all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name
  $out = @()
  $frontier = @($RootPid)
  while ($frontier.Count -gt 0) {
    $next = @()
    foreach ($p in $frontier) {
      foreach ($c in $all | Where-Object { $_.ParentProcessId -eq $p }) {
        $out += $c
        $next += $c.ProcessId
      }
    }
    $frontier = $next
  }
  return $out
}

function Wait-Window([System.Diagnostics.Process]$Proc, [int]$TimeoutMs = 60000) {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  while ($sw.ElapsedMilliseconds -lt $TimeoutMs) {
    try { $Proc.Refresh() } catch { break }
    if ($Proc.HasExited) { return -1 }
    if ($Proc.MainWindowHandle -ne 0) { return $sw.ElapsedMilliseconds }
    Start-Sleep -Milliseconds 2
  }
  return -1
}

function Kill-Tree([int]$RootPid) {
  foreach ($d in (Get-Descendants $RootPid)) {
    try { Stop-Process -Id $d.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
  }
  try { Stop-Process -Id $RootPid -Force -ErrorAction SilentlyContinue } catch {}
  Start-Sleep -Milliseconds 800
}

switch ($Mode) {

  "startup" {
    $results = @()
    for ($i = 1; $i -le $N; $i++) {
      $p = Start-Process -FilePath $Exe -PassThru
      $ms = Wait-Window $p
      $results += $ms
      Write-Output ("run {0}: {1} ms to first window" -f $i, $ms)
      Start-Sleep -Seconds 2
      Kill-Tree $p.Id
      Start-Sleep -Seconds 2
    }
    $ok = $results | Where-Object { $_ -ge 0 } | Sort-Object
    if ($ok.Count -gt 0) {
      Write-Output ("median {0} ms  min {1}  max {2}  n={3}" -f `
          $ok[[math]::Floor($ok.Count / 2)], $ok[0], $ok[$ok.Count - 1], $ok.Count)
    }
  }

  "memory" {
    $p = Start-Process -FilePath $Exe -PassThru
    $ms = Wait-Window $p
    Write-Output ("window at {0} ms; settling {1}s" -f $ms, $Settle)
    Start-Sleep -Seconds $Settle
    $procs = @(Get-Process -Id $p.Id) + @(
      Get-Descendants $p.Id | ForEach-Object {
        try { Get-Process -Id $_.ProcessId -ErrorAction Stop } catch {} }
    )
    $ws = 0; $pv = 0
    foreach ($q in $procs) {
      Write-Output ("  {0,-28} pid {1,-7} ws {2,8:N1} MiB  private {3,8:N1} MiB" -f `
          $q.ProcessName, $q.Id, ($q.WorkingSet64 / 1MB), ($q.PrivateMemorySize64 / 1MB))
      $ws += $q.WorkingSet64; $pv += $q.PrivateMemorySize64
    }
    Write-Output ("TOTAL processes {0}  workingset {1:N1} MiB  private {2:N1} MiB" -f `
        $procs.Count, ($ws / 1MB), ($pv / 1MB))
    Kill-Tree $p.Id
  }

  "orphan" {
    $p = Start-Process -FilePath $Exe -PassThru
    $ms = Wait-Window $p
    Write-Output ("window at {0} ms" -f $ms)
    Start-Sleep -Seconds $Settle
    $kids = Get-Descendants $p.Id
    $side = $kids | Where-Object { $_.Name -like "rigorloomd*" }
    Write-Output ("before kill: {0} descendants, sidecar pids: {1}" -f `
        $kids.Count, (($side | ForEach-Object { $_.ProcessId }) -join ","))
    Write-Output "HARD-KILLING SHELL ONLY (Stop-Process -Force, no cleanup handler runs)"
    Stop-Process -Id $p.Id -Force
    Start-Sleep -Seconds 5
    $still = @()
    foreach ($s in $side) {
      if (Get-Process -Id $s.ProcessId -ErrorAction SilentlyContinue) { $still += $s.ProcessId }
    }
    $webleft = @()
    foreach ($k in ($kids | Where-Object { $_.Name -like "msedgewebview2*" })) {
      if (Get-Process -Id $k.ProcessId -ErrorAction SilentlyContinue) { $webleft += $k.ProcessId }
    }
    Write-Output ("after 5s: orphaned sidecars = {0}  orphaned webview procs = {1}" -f `
      ($(if ($still.Count) { $still -join "," } else { "NONE" })), `
      ($(if ($webleft.Count) { $webleft -join "," } else { "NONE" })))
    foreach ($x in ($still + $webleft)) { Stop-Process -Id $x -Force -ErrorAction SilentlyContinue }
  }

  "tree" {
    $p = Start-Process -FilePath $Exe -PassThru
    $ms = Wait-Window $p
    Write-Output ("window at {0} ms; shell pid {1}" -f $ms, $p.Id)
    Start-Sleep -Seconds $Settle
    foreach ($d in (Get-Descendants $p.Id)) {
      Write-Output ("  {0,-26} pid {1,-7} parent {2}" -f $d.Name, $d.ProcessId, $d.ParentProcessId)
    }
    Write-Output "left running"
  }

  default { throw "unknown mode $Mode" }
}
