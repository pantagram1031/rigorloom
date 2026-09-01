<#
  Capture the app window to a PNG.

  Adapted from spikes/shell-tauri/measure/shot.ps1. The DPI-awareness call is
  the load-bearing part: without it PowerShell is DPI-unaware, GetWindowRect
  returns virtualised 96-DPI coordinates, and CopyFromScreen captures a
  rescaled region — the PNG would then misrepresent exactly the thing a DPI
  screenshot is evidence for.
#>
param(
    [Parameter(Mandatory = $true)][string]$Out,
    # Matched by process name, not by window title: the title is Korean, and a
    # Korean literal in a .ps1 only survives if the file carries a UTF-8 BOM
    # (Windows PowerShell 5.1 otherwise decodes the file as ANSI/cp949).
    # Process name has no such hazard.
    [string]$ProcessName = "rigorloom-desktop",
    [int]$SettleMs = 1200,
    # The app's configured 1440x900 fills a 200%-scaled 1440x900 display
    # exactly, which puts the verification bar behind the taskbar. Fitting the
    # window to the work area first is what makes the bottom bar appear in the
    # evidence at all.
    [switch]$FitToWorkArea
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

# Joined lines rather than a here-string: Windows PowerShell 5.1 only
# terminates `@"` ... `"@` when the file has CRLF endings, and this repo checks
# out LF. A here-string here fails with a C#-shaped parser error that looks
# nothing like a line-ending problem.
$source = @(
    'using System;',
    'using System.Runtime.InteropServices;',
    'public class W {',
    '  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);',
    '  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);',
    '  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);',
    '  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr ctx);',
    '  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool repaint);',
    '  [DllImport("user32.dll")] public static extern bool SystemParametersInfo(uint a, uint b, ref R r, uint c);',
    '  [StructLayout(LayoutKind.Sequential)] public struct R { public int L, T, Rt, B; }',
    '}'
) -join "`n"
Add-Type -TypeDefinition $source

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
try { [void][W]::SetProcessDpiAwarenessContext([IntPtr](-4)) } catch {}

$deadline = (Get-Date).AddSeconds(40)
$p = $null
while ((Get-Date) -lt $deadline) {
    $p = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
         Where-Object { $_.MainWindowHandle -ne 0 } |
         Select-Object -First 1
    if ($p) { break }
    Start-Sleep -Milliseconds 400
}
if (-not $p) { throw "no window for process '$ProcessName'" }

if ($FitToWorkArea) {
    # SPI_GETWORKAREA = 0x0030 - the desktop minus the taskbar, in device px
    # now that this process is per-monitor DPI aware.
    $work = New-Object W+R
    [void][W]::SystemParametersInfo(0x0030, 0, [ref]$work, 0)
    $ww = $work.Rt - $work.L
    $wh = $work.B - $work.T
    [void][W]::MoveWindow($p.MainWindowHandle, $work.L, $work.T, $ww, $wh, $true)
    Start-Sleep -Milliseconds 800
}

[void][W]::SetForegroundWindow($p.MainWindowHandle)
Start-Sleep -Milliseconds $SettleMs

$r = New-Object W+R
[void][W]::GetWindowRect($p.MainWindowHandle, [ref]$r)
$w = $r.Rt - $r.L
$h = $r.B - $r.T
if ($w -le 0 -or $h -le 0) { throw "bad window rect" }

$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)

# PrintWindow, not CopyFromScreen. CopyFromScreen copies whatever pixels are on
# the screen inside the window's rectangle, so any window sitting on top is
# captured too — and SetForegroundWindow above cannot be relied on to prevent
# that, because Windows refuses focus changes requested by a process that is
# not itself in the foreground. A run on a busy desktop produced "screenshots"
# of the app with somebody's chat window composited over the middle of it.
#
# PW_RENDERFULLCONTENT (2) asks the window to draw itself into our DC, which
# reaches the WebView2 content and is unaffected by occlusion.
$hdc = $g.GetHdc()
$ok = [W]::PrintWindow($p.MainWindowHandle, $hdc, 2)
$g.ReleaseHdc($hdc)
if (-not $ok) {
    $g.Dispose(); $bmp.Dispose()
    throw "PrintWindow failed for '$ProcessName'; refusing to fall back to a screen grab that may capture other windows"
}

$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output ("saved {0}  ({1}x{2} device px)" -f $Out, $w, $h)
