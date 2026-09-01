#!/usr/bin/env python3
"""Send REAL keyboard scan codes so the Windows IME actually composes (M13).

Why this exists: the desktop-automation tooling available in this environment
types by injecting Unicode characters (SendInput with KEYEVENTF_UNICODE) or by
pasting. That bypasses the IME entirely — the field receives 'dkssudgktpdy'
literally and nothing about Hangul composition is exercised. Scan-code events
go through the keyboard layout and therefore through the IME, which is the
thing under test.

Usage (the target window must already be focused, IME already in Hangul mode):
    python measure/ime_keys.py 안녕하세요        # types the 두벌식 key sequence
    python measure/ime_keys.py --raw dkssudgktpdy
    python measure/ime_keys.py --key backspace
"""
import ctypes
import sys
import time
from ctypes import wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001

# US-layout scan codes for the letters the 두벌식 layout maps onto.
SCAN = {
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12, "f": 0x21,
    "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24, "k": 0x25, "l": 0x26,
    "m": 0x32, "n": 0x31, "o": 0x18, "p": 0x19, "q": 0x10, "r": 0x13,
    "s": 0x1F, "t": 0x14, "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D,
    "y": 0x15, "z": 0x2C, " ": 0x39,
}
NAMED = {"backspace": 0x0E, "enter": 0x1C, "space": 0x39, "tab": 0x0F}

# 두벌식: Hangul syllable -> the US letters you press to compose it.
JAMO_KEYS = {
    "ㄱ": "r", "ㄲ": "R", "ㄴ": "s", "ㄷ": "e", "ㄸ": "E", "ㄹ": "f",
    "ㅁ": "a", "ㅂ": "q", "ㅃ": "Q", "ㅅ": "t", "ㅆ": "T", "ㅇ": "d",
    "ㅈ": "w", "ㅉ": "W", "ㅊ": "c", "ㅋ": "z", "ㅌ": "x", "ㅍ": "v",
    "ㅎ": "g",
    "ㅏ": "k", "ㅐ": "o", "ㅑ": "i", "ㅒ": "O", "ㅓ": "j", "ㅔ": "p",
    "ㅕ": "u", "ㅖ": "P", "ㅗ": "h", "ㅛ": "y", "ㅜ": "n", "ㅠ": "b",
    "ㅡ": "m", "ㅣ": "l",
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


def _send(scan, up=False):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    inp = INPUT(type=INPUT_KEYBOARD,
                u=_U(ki=KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags,
                                   time=0, dwExtraInfo=None)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def tap(scan, hold=0.012, gap=0.045):
    _send(scan, False)
    time.sleep(hold)
    _send(scan, True)
    time.sleep(gap)


def press_letter(ch):
    shift = ch.isupper()
    low = ch.lower()
    if low not in SCAN:
        raise SystemExit(f"no scan code for {ch!r}")
    if shift:
        _send(0x2A, False)  # left shift down
        time.sleep(0.01)
    tap(SCAN[low])
    if shift:
        _send(0x2A, True)
        time.sleep(0.01)


def decompose(text):
    """Hangul syllables -> the 두벌식 key string that composes them."""
    keys = []
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            off = code - 0xAC00
            lead = LEAD[off // 588]
            vowel = VOWEL[(off % 588) // 28]
            tail = TAIL[off % 28]
            for jamo in (lead, vowel, tail):
                if not jamo:
                    continue
                if jamo not in JAMO_KEYS:
                    raise SystemExit(f"compound jamo {jamo!r} not in table; use --raw")
                keys.append(JAMO_KEYS[jamo])
        elif ch in JAMO_KEYS:
            keys.append(JAMO_KEYS[ch])
        else:
            keys.append(ch)
    return "".join(keys)


def main(argv):
    if len(argv) >= 2 and argv[0] == "--key":
        name = argv[1].lower()
        if name not in NAMED:
            raise SystemExit(f"unknown key {name}")
        tap(NAMED[name])
        print(f"tapped {name}")
        return
    if argv and argv[0] == "--raw":
        seq = argv[1]
    else:
        seq = decompose(" ".join(argv))
        print(f"두벌식 key sequence: {seq}")
    time.sleep(0.4)
    for ch in seq:
        press_letter(ch)
    print(f"sent {len(seq)} scan-code key events")


if __name__ == "__main__":
    main(sys.argv[1:])
