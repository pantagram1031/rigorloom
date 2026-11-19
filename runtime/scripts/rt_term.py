#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Terminal output for people: width-aware text, quiet color, plain when piped.

Machines get ``--json``. Everything here is for a person looking at a
terminal, and it follows three rules:

* Korean is two columns wide. Alignment uses East Asian Width, so a table of
  Korean headings lines up the way it does in Hancom, not the way ``len`` says.
* Color is a hint, never the message. It is off when stdout is not a terminal,
  when ``NO_COLOR`` is set, or when ``--color never`` is given; the text reads
  the same without it.
* Windows consoles get UTF-8 and VT sequences turned on once, at startup, so
  the same bytes render on Windows Terminal, conhost and Linux terminals.

Stdlib only, like the rest of the runtime.
"""
from __future__ import annotations

import os
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence, TextIO

COLOR_CHOICES = ("auto", "always", "never")

_SGR = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "cyan": "36",
}


def prepare_stdio() -> None:
    """UTF-8 on every platform, and VT processing on Windows consoles.

    Called once before anything is printed. A Korean Windows console defaults
    to cp949, which cannot encode every character a document holds (``⋅``,
    ``㉮``, ``∑``); writing one would raise mid-output. Reconfiguring keeps the
    bytes UTF-8, and Windows Terminal and conhost on Windows 10+ display them.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    if os.name == "nt":
        _enable_windows_vt()


def _enable_windows_vt() -> bool:
    """Turn on ENABLE_VIRTUAL_TERMINAL_PROCESSING for stdout and stderr."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        enabled = False
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            mode = wintypes.DWORD()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                continue
            if kernel32.SetConsoleMode(handle, mode.value | 0x0004):
                enabled = True
        try:
            kernel32.SetConsoleOutputCP(65001)
        except Exception:  # noqa: BLE001 - best effort, never fatal
            pass
        return enabled
    except Exception:  # noqa: BLE001 - no console, or not Windows after all
        return False


def is_console(stream) -> bool:
    """True only for an interactive console a person can type into.

    ``isatty()`` alone is not enough: on Windows it is true for ``< NUL``
    (the NUL device is a character device), which would let a script's
    redirected input pass for a person. There the console mode query must
    succeed too.
    """
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError, OSError):
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = wintypes.DWORD()
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except Exception:  # noqa: BLE001 - unknown means not a person
        return False


def confirm(question: str, *, stdin=None, stdout=None, prompt: str = " [y/N] ") -> bool | None:
    """Ask a person y/N on the console. ``None`` when no person can answer.

    ``prompt`` follows the question; a caller that already printed the
    question and its details passes an empty question and ``"> "``.
    """
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stderr
    if not (is_console(stdin) and is_console(stdout)):
        return None
    stdout.write(f"{safe_text(question)}{prompt}")
    stdout.flush()
    try:
        answer = stdin.readline()
    except (OSError, ValueError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in ("y", "yes", "예", "네", "ㅇ")


def char_width(ch: str) -> int:
    """Columns one code point takes in a monospace terminal."""
    if not ch:
        return 0
    code = ord(ch)
    if code == 0 or code == 0x200B or code == 0x200D or code == 0xFEFF:
        return 0
    if code < 32 or 0x7F <= code < 0xA0:
        return 0
    if unicodedata.combining(ch):
        return 0
    category = unicodedata.category(ch)
    if category in ("Mn", "Me", "Cf"):
        return 0
    # Hangul jungseong/jongseong jamo combine with the preceding choseong.
    if 0x1160 <= code <= 0x11FF or 0xD7B0 <= code <= 0xD7FF:
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def width(text: str) -> int:
    """Display width of ``text`` (no escape sequences expected)."""
    return sum(char_width(ch) for ch in text)


def truncate(text: str, limit: int, ellipsis: str = "…") -> str:
    """Cut ``text`` to at most ``limit`` columns, marking the cut."""
    if limit <= 0:
        return ""
    if width(text) <= limit:
        return text
    budget = limit - width(ellipsis)
    out: list[str] = []
    used = 0
    for ch in text:
        w = char_width(ch)
        if used + w > budget:
            break
        out.append(ch)
        used += w
    return "".join(out) + ellipsis


def pad(text: str, size: int, align: str = "left") -> str:
    """Pad ``text`` with spaces to ``size`` columns (never truncates)."""
    gap = size - width(text)
    if gap <= 0:
        return text
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


#: Characters a document may contain that must never reach a terminal or an
#: agent verbatim: C0 controls except tab/newline, DEL, C1 controls (ESC and
#: CSI start sequences live here), and the bidi overrides/isolates that can
#: make displayed text differ from the bytes (CVE-2021-42574 style).
_UNSAFE = {c: None for c in list(range(0x00, 0x09)) + [0x0B, 0x0C]
           + list(range(0x0E, 0x20)) + [0x7F] + list(range(0x80, 0xA0))
           + [0x061C, 0x200E, 0x200F] + list(range(0x202A, 0x202F))
           + list(range(0x2066, 0x206A))}


def safe_text(text: str) -> str:
    """Document text with escape, control and bidi-override characters removed.

    Applied to every piece of document content before it is printed or handed
    to an agent as text. Carriage returns become newlines.
    """
    if not text:
        return text
    return text.replace("\r\n", "\n").replace("\r", "\n").translate(_UNSAFE)


def _invisible(ch: str) -> bool:
    """Not drawn, or drawn like a plain space: control, format (zero-width,
    bidi), separators other than ASCII space, private use, unassigned."""
    if ch == " ":
        return False
    return (ch.isspace() or not ch.translate(_UNSAFE)
            or unicodedata.category(ch) in ("Cc", "Cf", "Zs", "Zl", "Zp", "Co", "Cs", "Cn"))


def path_text(path: str) -> str:
    """A path for a person to read: exact, with invisible characters escaped.

    Unlike one_line, runs of spaces stay as they are, so two names that differ
    only in spacing never look alike in a question the person answers. A name
    with escapes also gets an ``invisible_in`` line, so a name that really
    contains the text ``\\u0009`` is not mistaken for one with a tab.
    """
    return "".join(f"\\u{ord(ch):04x}" if _invisible(ch) else ch for ch in str(path))


def invisible_in(path: str) -> list[str]:
    """The invisible characters ``path_text`` escaped, as U+XXXX, in order."""
    seen: list[str] = []
    for ch in str(path):
        code = f"U+{ord(ch):04X}"
        if _invisible(ch) and code not in seen:
            seen.append(code)
    return seen


def one_line(text: str) -> str:
    """Collapse line breaks and tabs so a preview stays on one row."""
    return " ".join(safe_text(text).replace("\t", " ").split())


@dataclass
class Term:
    """Where human output goes, and how it may look there."""

    stream: TextIO
    color: bool
    columns: int
    interactive: bool

    @classmethod
    def detect(cls, choice: str = "auto", stream: TextIO | None = None) -> "Term":
        stream = stream if stream is not None else sys.stdout
        try:
            tty = bool(stream.isatty())
        except (AttributeError, ValueError, OSError):
            tty = False
        if choice == "always":
            color = True
        elif choice == "never":
            color = False
        else:
            color = tty and "NO_COLOR" not in os.environ and \
                os.environ.get("TERM") != "dumb"
            if os.environ.get("FORCE_COLOR"):
                color = True
        columns = shutil.get_terminal_size((100, 24)).columns if tty else 100
        return cls(stream=stream, color=color, columns=max(40, columns),
                   interactive=tty)

    # -- styling ---------------------------------------------------------
    def style(self, text: str, *names: str) -> str:
        if not self.color or not names or not text:
            return text
        codes = ";".join(_SGR[name] for name in names if name in _SGR)
        return f"\x1b[{codes}m{text}\x1b[0m" if codes else text

    def bold(self, text: str) -> str:
        return self.style(text, "bold")

    def dim(self, text: str) -> str:
        return self.style(text, "dim")

    # -- writing ---------------------------------------------------------
    def line(self, text: str = "") -> None:
        self.stream.write(text + "\n")

    def lines(self, rows: Iterable[str]) -> None:
        for row in rows:
            self.line(row)

    def flush(self) -> None:
        try:
            self.stream.flush()
        except (AttributeError, ValueError, OSError):
            pass

    # -- layouts ---------------------------------------------------------
    def table(self, rows: Sequence[Sequence[str]], *,
              header: Sequence[str] | None = None,
              align: Sequence[str] | None = None,
              shrink: int | None = None,
              gap: int = 2) -> list[str]:
        """Rows of aligned columns with no borders, the way ``gh`` prints lists.

        ``shrink`` names the one column that gives up width when the terminal
        is too narrow (usually the free-text column); the others keep theirs.
        Returns the rendered lines so callers can test them; also writes them.
        """
        body = [[one_line(str(cell)) for cell in row] for row in rows]
        head = [str(cell) for cell in header] if header else None
        count = max([len(r) for r in body] + [len(head) if head else 0] + [0])
        if count == 0:
            return []
        sizes = [0] * count
        for row in ([head] if head else []) + body:
            for index, cell in enumerate(row):
                sizes[index] = max(sizes[index], width(cell))
        total = sum(sizes) + gap * (count - 1)
        if shrink is not None and total > self.columns:
            over = total - self.columns
            sizes[shrink] = max(8, sizes[shrink] - over)
        aligns = list(align or []) + ["left"] * count
        out: list[str] = []
        sep = " " * gap
        if head:
            cells = [pad(truncate(head[i], sizes[i]), sizes[i], aligns[i])
                     for i in range(len(head))]
            out.append(self.dim(sep.join(cells).rstrip()))
        for row in body:
            cells = []
            for index in range(count):
                cell = row[index] if index < len(row) else ""
                cells.append(pad(truncate(cell, sizes[index]), sizes[index],
                                 aligns[index]))
            out.append(sep.join(cells).rstrip())
        self.lines(out)
        return out

    def kv(self, pairs: Sequence[tuple[str, str]], *, indent: int = 0) -> list[str]:
        """``label  value`` pairs with labels aligned (Korean-width aware)."""
        if not pairs:
            return []
        size = max(width(label) for label, _ in pairs)
        out = [" " * indent + self.dim(pad(label, size)) + "  " + value
               for label, value in pairs]
        self.lines(out)
        return out


def plural_ko(count: int, unit: str) -> str:
    """``3개``, ``12쪽`` — Korean counters do not change with number."""
    return f"{count:,}{unit}"
