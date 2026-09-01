<#
  Capture the spike window to a PNG (visual evidence for the DPI matrix).
  Grabs the window's screen rectangle, so what lands in the file is exactly
  what the display showed at that scale factor.
#>
param(
  [Parameter(Mandatory = $true)][string]$Out,
  [string]$WindowTitle = "Rigorloom Shell Spike"
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  // Without this, PowerShell is DPI-unaware: GetWindowRect returns virtualised
  // 96-DPI coordinates and CopyFromScreen captures a rescaled region, so the
  // PNG would misrepresent exactly the thing the DPI matrix is testing.
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr ctx);
  [StructLayout(LayoutKind.Sequential)] public struct R { public int L, T, Rt, B; }
}
"@

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
try { [void][W]::SetProcessDpiAwarenessContext([IntPtr](-4)) } catch {}

$p = Get-Process | Where-Object { $_.MainWindowTitle -eq $WindowTitle } | Select-Object -First 1
if (-not $p) { throw "window '$WindowTitle' not found" }
[void][W]::SetForegroundWindow($p.MainWindowHandle)
Start-Sleep -Milliseconds 900

$r = New-Object W+R
[void][W]::GetWindowRect($p.MainWindowHandle, [ref]$r)
$w = $r.Rt - $r.L
$h = $r.B - $r.T
if ($w -le 0 -or $h -le 0) { throw "bad window rect" }

$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, (New-Object System.Drawing.Size($w, $h)))
$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output ("saved {0}  ({1}x{2} device px)" -f $Out, $w, $h)
