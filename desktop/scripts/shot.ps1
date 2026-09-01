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
    'using System.Collections.Generic;',
    'using System.Runtime.InteropServices;',
    'public class W {',
    '  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);',
    '  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);',
    '  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);',
    '  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr ctx);',
    '  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool repaint);',
    '  [DllImport("user32.dll")] public static extern bool SystemParametersInfo(uint a, uint b, ref R r, uint c);',
    '  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);',
    '  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);',
    '  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);',
    '  public delegate bool EnumProc(IntPtr h, IntPtr p);',
    '  [StructLayout(LayoutKind.Sequential)] public struct R { public int L, T, Rt, B; }',
    # The biggest visible top-level window this process owns.
    #
    # MainWindowHandle is "the first top-level window Windows happened to
    # associate with the process", and this process owns four: the editor, a
    # 26x26 something, and two invisible zero-size ones. Picking by area is a
    # cheap way not to depend on which one Windows named first.
    #
    # It is NOT a size test. Measured on this machine: the editor's window rect
    # is 314x50 until `MoveWindow` below fits it to the work area, even while
    # the WebView inside it already reports a 2880x1759 CSS viewport. Requiring
    # a plausible size at SELECTION time therefore rejects the real window and
    # the capture never happens — which is how the first version of this fix
    # failed. The size test belongs after the move, and that is where it is.
    '  public static IntPtr Largest(uint want) {',
    '    IntPtr best = IntPtr.Zero; long bestArea = 0;',
    '    EnumWindows(delegate(IntPtr h, IntPtr p) {',
    '      uint pid; GetWindowThreadProcessId(h, out pid);',
    '      if (pid != want || !IsWindowVisible(h)) return true;',
    '      R r; GetWindowRect(h, out r);',
    '      long area = (long)(r.Rt - r.L) * (r.B - r.T);',
    '      if (area > bestArea) { bestArea = area; best = h; }',
    '      return true;',
    '    }, IntPtr.Zero);',
    '    return best;',
    '  }',
    '}'
) -join "`n"
Add-Type -TypeDefinition $source

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
try { [void][W]::SetProcessDpiAwarenessContext([IntPtr](-4)) } catch {}

# The editor's own minimum, enforced AFTER the window has been fitted to the
# work area. See the size check further down for why it cannot be enforced
# before.
$MIN_W = 1000
$MIN_H = 600

$deadline = (Get-Date).AddSeconds(40)
$hwnd = [IntPtr]::Zero
while ((Get-Date) -lt $deadline) {
    $proc = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne 0 } |
            Select-Object -First 1
    if ($proc) {
        # Largest first, MainWindowHandle as the fallback: enumeration can
        # legitimately come back empty for a heartbeat while windows are being
        # created, and the handle the OS already named is better than nothing.
        $hwnd = [W]::Largest([uint32]$proc.Id)
        if ($hwnd -eq [IntPtr]::Zero) { $hwnd = $proc.MainWindowHandle }
        if ($hwnd -ne [IntPtr]::Zero) { break }
    }
    Start-Sleep -Milliseconds 400
}
if ($hwnd -eq [IntPtr]::Zero) { throw "no window for process '$ProcessName'" }

if ($FitToWorkArea) {
    # SPI_GETWORKAREA = 0x0030 - the desktop minus the taskbar, in device px
    # now that this process is per-monitor DPI aware.
    $work = New-Object W+R
    [void][W]::SystemParametersInfo(0x0030, 0, [ref]$work, 0)
    $ww = $work.Rt - $work.L
    $wh = $work.B - $work.T
    [void][W]::MoveWindow($hwnd, $work.L, $work.T, $ww, $wh, $true)
    Start-Sleep -Milliseconds 800
}

[void][W]::SetForegroundWindow($hwnd)
Start-Sleep -Milliseconds $SettleMs

# THE SIZE CHECK, and it has to be here rather than at selection time.
#
# `$w -gt 0` was the whole check, and it let a 314x50 rect through: `MoveWindow`
# above had not taken effect yet, so the harness photographed the window at the
# size it has BEFORE being fitted to the work area and filed the title-bar
# sliver under a panel's name. A fragment saved under the right name is worse
# than a failed capture, because the failure is visible and the fragment is not.
#
# 314x50 is the editor's own pre-move rect on this machine, not a helper's —
# which is why this poll cannot be moved up into the selection loop. It waits
# for the move to land and refuses if it never does.
$r = New-Object W+R
$settleDeadline = (Get-Date).AddSeconds(15)
do {
    [void][W]::GetWindowRect($hwnd, [ref]$r)
    $w = $r.Rt - $r.L
    $h = $r.B - $r.T
    if ($w -ge $MIN_W -and $h -ge $MIN_H) { break }
    Start-Sleep -Milliseconds 400
} while ((Get-Date) -lt $settleDeadline)
if ($w -le 0 -or $h -le 0) { throw "bad window rect" }
if ($w -lt $MIN_W -or $h -lt $MIN_H) {
    throw ("window is ${w}x${h}, below the editor's own ${MIN_W}x${MIN_H} minimum; " +
           "refusing to save a capture that would show a fragment of the app")
}

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
$ok = [W]::PrintWindow($hwnd, $hdc, 2)
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
