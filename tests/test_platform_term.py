# -*- coding: utf-8 -*-
"""Terminal output: Korean width, control stripping, and who counts as a person."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime" / "scripts"))

from rt_term import (  # noqa: E402
    Term,
    confirm,
    is_console,
    one_line,
    pad,
    safe_text,
    truncate,
    width,
)
import rt_term  # noqa: E402


def test_korean_is_two_columns():
    assert width("보고서") == 6
    assert width("ab") == 2
    assert width("가́") == 2          # a combining mark takes no column
    assert width("각") == 2  # conjoining jamo: one syllable


def test_truncate_and_pad_count_columns():
    assert truncate("출장신청서", 7) == "출장신…"
    assert width(truncate("출장신청서", 7)) <= 7
    assert pad("가", 4) == "가  " and pad("가", 4, "right") == "  가"


def test_table_aligns_korean_columns():
    term = Term(stream=io.StringIO(), color=False, columns=80, interactive=False)
    rows = term.table([["p1", "제목"], ["t12/r3/c1", "금액 450,000원"]], header=["주소", "글"])
    second = [width(r[: r.index(cell)]) for r, cell in zip(rows, ["글", "제목", "금액"])]
    assert len(set(second)) == 1, rows  # the second column starts at one column


def test_table_shrinks_the_free_text_column():
    term = Term(stream=io.StringIO(), color=False, columns=40, interactive=False)
    rows = term.table([["p1", "가" * 60]], shrink=1)
    assert all(width(r) <= 40 for r in rows)
    assert rows[0].endswith("…")


def test_escape_bidi_and_controls_are_removed():
    dirty = "앞\x1b[31m빨강\x1b[0m‮뒤집힘⁦격리⁩\x07\x9b끝\r\n다음"
    clean = safe_text(dirty)
    for bad in ("\x1b", "‮", "⁦", "⁩", "\x07", "\x9b", "\r"):
        assert bad not in clean
    assert "\t" in safe_text("a\tb") and "\n" in clean
    assert one_line("가\n나\t다") == "가 나 다"


def test_color_off_when_piped_or_no_color(monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert Term.detect("auto", io.StringIO()).color is False
    assert Term.detect("always", io.StringIO()).color is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert Term.detect("never", io.StringIO()).color is False


def test_redirected_input_is_not_a_person():
    # On Windows `< NUL` reports isatty() True; GetConsoleMode must fail too.
    with open(os.devnull, "r", encoding="utf-8") as null:
        assert is_console(null) is False
        assert confirm("지울까요?", stdin=null, stdout=io.StringIO()) is None
    assert is_console(io.StringIO()) is False


def test_confirm_reads_a_yes_only_from_a_console(monkeypatch):
    class FakeTty(io.StringIO):
        def isatty(self):
            return True

    if os.name == "nt":
        # A StringIO has no console handle; Windows must not take it for one.
        assert confirm("?", stdin=FakeTty("y\n"), stdout=FakeTty()) is None
        return
    assert confirm("?", stdin=FakeTty("예\n"), stdout=FakeTty()) is True
    assert confirm("?", stdin=FakeTty("\n"), stdout=FakeTty()) is False



def test_help_descriptions_start_at_one_column():
    from rt_cli_product import HELP_SECTIONS, HELP_USAGE_COLUMNS, help_text

    text = help_text().splitlines()
    for _, rows in HELP_SECTIONS:
        for usage, what in rows:
            assert what, usage  # every verb says what it does
            line = next(x for x in text if x.startswith("  " + usage + " "))
            assert width(line[: line.index(what)]) == HELP_USAGE_COLUMNS + 4, line


@pytest.mark.parametrize("name,posix,windows", [
    ("보고서.hwpx", '"보고서.hwpx"', '"보고서.hwpx"'),
    ("C:\\문서\\보고서.hwpx", "'C:\\문서\\보고서.hwpx'", '"C:\\문서\\보고서.hwpx"'),
    ('report"quoted".hwpx', "'report\"quoted\".hwpx'", None),
    ("a$HOME.hwpx", "'a$HOME.hwpx'", None),
    ("it's $x.hwpx", "'it'\"'\"'s $x.hwpx'", None),
    ("100%.hwpx", '"100%.hwpx"', None),
    ("a\u202eb.hwpx", None, None),
    ("a\nb.hwpx", None, None),
])
def test_shell_arg_is_copyable_or_absent(name, posix, windows):
    import shlex
    assert rt_term.shell_arg(name, windows=False) == posix
    assert rt_term.shell_arg(name, windows=True) == windows
    if posix is not None:
        assert shlex.split(posix) == [name]


def test_the_undo_line_names_no_command_for_an_invisible_character():
    assert rt_term.undo_line("/x/a\u200b.hwpx") == \
        "되돌리려면 rigorloom undo 뒤에 실제 파일 경로를 입력해 실행하세요."
    assert rt_term.undo_line("/x/a.hwpx", shown=rt_term.path_text) == \
        '되돌리기: rigorloom undo "/x/a.hwpx"'
