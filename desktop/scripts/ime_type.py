#!/usr/bin/env python3
"""Send REAL keyboard scan codes at the Desktop's inline seat editor (M13/M14).

Adapted from ``spikes/shell-tauri/measure/ime_keys.py``, which established why
this has to exist: the desktop-automation tooling available here types by
injecting Unicode characters (``SendInput`` with ``KEYEVENTF_UNICODE``) or by
pasting, and both bypass the IME completely. The field would receive
``dkssudgktpdy`` literally and nothing about Hangul composition would be
exercised. Scan-code events go through the keyboard layout, therefore through
the IME, which is the thing under test.

WHAT IS DIFFERENT FROM THE SPIKE VERSION. The spike typed into a bare test
page and a human read the result. This types into the shipped application's
inline editor and the APPLICATION reports what it received, so the check is
machine-readable:

  * it finds the Rigorloom window itself and brings it forward, rather than
    assuming whatever is focused is the right thing;
  * it toggles the IME into Hangul mode with VK_HANGUL rather than assuming
    the mode, and puts it back afterwards;
  * it types, then presses Enter, and the app writes what it ended up with
    into its own report file. Comparing that to the expected string is the
    assertion.

WHAT IT STILL CANNOT PROVE. Composition is the IME's business and this only
proves the field receives it correctly on THIS machine with THIS layout
(Microsoft IME, 두벌식). A different IME is a different code path.

    python desktop/scripts/ime_type.py --text 안녕하세요 [--enter] [--backspace 2]
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

VK_HANGUL = 0x15

#: US-layout scan codes for the letters the 두벌식 layout maps onto.
SCAN = {
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12, "f": 0x21,
    "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24, "k": 0x25, "l": 0x26,
    "m": 0x32, "n": 0x31, "o": 0x18, "p": 0x19, "q": 0x10, "r": 0x13,
    "s": 0x1F, "t": 0x14, "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D,
    "y": 0x15, "z": 0x2C, " ": 0x39,
    "0": 0x0B, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05,
    "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A,
    "-": 0x0C, ".": 0x34,
}
NAMED = {"backspace": 0x0E, "enter": 0x1C, "space": 0x39, "tab": 0x0F,
         "escape": 0x01}

#: 두벌식: jamo -> the US letters you press to compose it.
JAMO_KEYS = {
    "ㄱ": "r", "ㄲ": "R", "ㄴ": "s", "ㄷ": "e", "ㄸ": "E", "ㄹ": "f",
    "ㅁ": "a", "ㅂ": "q", "ㅃ": "Q", "ㅅ": "t", "ㅆ": "T", "ㅇ": "d",
    "ㅈ": "w", "ㅉ": "W", "ㅊ": "c", "ㅋ": "z", "ㅌ": "x", "ㅍ": "v",
    "ㅎ": "g",
    "ㅏ": "k", "ㅐ": "o", "ㅑ": "i", "ㅒ": "O", "ㅓ": "j", "ㅔ": "p",
    "ㅕ": "u", "ㅖ": "P", "ㅗ": "h", "ㅛ": "y", "ㅜ": "n", "ㅠ": "b",
    "ㅡ": "m", "ㅣ": "l",
}
#: Compound jamo the layout composes from two keys, so a syllable carrying one
#: is typable rather than a refusal. Same table shape as the spike, extended
#: with the pairs the corpus forms actually need.
COMPOUND_VOWEL = {
    "ㅘ": "ㅗㅏ", "ㅙ": "ㅗㅐ", "ㅚ": "ㅗㅣ", "ㅝ": "ㅜㅓ",
    "ㅞ": "ㅜㅔ", "ㅟ": "ㅜㅣ", "ㅢ": "ㅡㅣ",
}
COMPOUND_TAIL = {
    "ㄳ": "ㄱㅅ", "ㄵ": "ㄴㅈ", "ㄶ": "ㄴㅎ", "ㄺ": "ㄹㄱ", "ㄻ": "ㄹㅁ",
    "ㄼ": "ㄹㅂ", "ㄽ": "ㄹㅅ", "ㄾ": "ㄹㅌ", "ㄿ": "ㄹㅍ", "ㅀ": "ㄹㅎ",
    "ㅄ": "ㅂㅅ",
}

LEAD = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
VOWEL = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
TAIL = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send_scan(scan: int, up: bool = False) -> None:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    inp = INPUT(type=INPUT_KEYBOARD,
                u=_U(ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags,
                                   time=0, dwExtraInfo=None)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _send_vk(vk: int, up: bool = False) -> None:
    inp = INPUT(type=INPUT_KEYBOARD,
                u=_U(ki=KEYBDINPUT(wVk=vk, wScan=0,
                                   dwFlags=KEYEVENTF_KEYUP if up else 0,
                                   time=0, dwExtraInfo=None)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def tap(scan: int, hold: float = 0.012, gap: float = 0.045) -> None:
    _send_scan(scan, False)
    time.sleep(hold)
    _send_scan(scan, True)
    time.sleep(gap)


def press_letter(ch: str) -> None:
    shift = ch.isupper()
    low = ch.lower()
    if low not in SCAN:
        raise SystemExit(f"no scan code for {ch!r}")
    if shift:
        _send_scan(0x2A, False)
        time.sleep(0.01)
    tap(SCAN[low])
    if shift:
        _send_scan(0x2A, True)
        time.sleep(0.01)


def decompose(text: str) -> str:
    """Hangul syllables -> the 두벌식 key string that composes them."""
    keys: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            off = code - 0xAC00
            parts = [LEAD[off // 588], VOWEL[(off % 588) // 28], TAIL[off % 28]]
            for jamo in parts:
                if not jamo:
                    continue
                expanded = COMPOUND_VOWEL.get(jamo) or COMPOUND_TAIL.get(jamo) or jamo
                for piece in expanded:
                    if piece not in JAMO_KEYS:
                        raise SystemExit(f"jamo {piece!r} is not in the 두벌식 table")
                    keys.append(JAMO_KEYS[piece])
        elif ch in JAMO_KEYS:
            keys.append(JAMO_KEYS[ch])
        else:
            keys.append(ch)
    return "".join(keys)


def find_window(title_fragment: str) -> int:
    """The Rigorloom window, by title. Never "whatever is focused"."""
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum(hwnd, _param):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title_fragment.lower() in buffer.value.lower():
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum, 0)
    return found[0] if found else 0


def focus(hwnd: int) -> bool:
    """Bring the window forward.

    ``SetForegroundWindow`` is refused for a process that is not already in the
    foreground, which is the same Windows rule that made the screenshot
    harness capture other applications. So this asks, then VERIFIES, and says
    plainly whether it worked instead of typing into whatever happened to be
    in front.
    """
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    return user32.GetForegroundWindow() == hwnd


def set_hangul(on: bool) -> None:
    """Toggle the IME. VK_HANGUL is a toggle, so read the state first."""
    user32 = ctypes.windll.user32
    imm32 = ctypes.windll.imm32
    hwnd = user32.GetForegroundWindow()
    context = imm32.ImmGetDefaultIMEWnd(hwnd)
    # WM_IME_CONTROL / IMC_GETCONVERSIONMODE = 0x0001
    mode = user32.SendMessageW(context, 0x0283, 0x0001, 0)
    native = bool(mode & 0x0001)
    if native != on:
        _send_vk(VK_HANGUL, False)
        time.sleep(0.02)
        _send_vk(VK_HANGUL, True)
        time.sleep(0.25)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desktop/scripts/ime_type.py")
    parser.add_argument("--text", required=True,
                        help="the Hangul to compose through the IME")
    parser.add_argument("--window", default="Rigorloom",
                        help="window title fragment to focus")
    parser.add_argument("--enter", action="store_true",
                        help="press Enter afterwards, committing the edit")
    parser.add_argument("--backspace", type=int, default=0,
                        help="press Backspace N times before Enter (M14: a "
                             "syllable must DECOMPOSE, not vanish)")
    parser.add_argument("--no-ime", action="store_true",
                        help="do not touch the IME mode (for ASCII text)")
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print("this harness is Windows-only", file=sys.stderr)
        return 2

    hwnd = find_window(args.window)
    if not hwnd:
        print(f"no visible window matching {args.window!r}", file=sys.stderr)
        return 2
    if not focus(hwnd):
        print("could not bring the window to the foreground; Windows refuses "
              "focus changes from a process that is not already in front. "
              "Run this from a foreground console, or click the window first.",
              file=sys.stderr)
        return 2

    if not args.no_ime:
        set_hangul(True)
    try:
        sequence = args.text if args.no_ime else decompose(args.text)
        print(f"두벌식 key sequence: {sequence}")
        time.sleep(0.3)
        for ch in sequence:
            press_letter(ch)
        for _ in range(args.backspace):
            tap(NAMED["backspace"])
        if args.enter:
            time.sleep(0.2)
            tap(NAMED["enter"])
        time.sleep(0.3)
        print(f"sent {len(sequence)} scan-code key events")
    finally:
        if not args.no_ime:
            set_hangul(False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
