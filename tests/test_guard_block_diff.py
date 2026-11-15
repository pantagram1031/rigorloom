"""``rigorloom guard --mode block-diff``, as defined in docs/guard-block-diff.md."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "runtime" / "scripts" / "cli.py"
EXAMPLE = REPO / "examples" / "guard"


def _run(before, after, *extra, cwd=None):
    return subprocess.run([sys.executable, str(CLI), "guard", str(before), str(after), *extra],
                          cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def _write(path: Path, *paras: str) -> Path:
    path.write_text("\n\n".join(paras) + "\n", encoding="utf-8")
    return path


def test_committed_block_diff_is_reproduced_byte_for_byte():
    proc = _run("before.hwpx", "after.hwpx", "--mode", "block-diff", cwd=EXAMPLE)
    assert proc.returncode == 3
    assert proc.stdout == (EXAMPLE / "block-diff.txt").read_text(encoding="utf-8")


def test_block_diff_shows_kept_edits_and_lost_or_added_expressions():
    text = (EXAMPLE / "block-diff.txt").read_text(encoding="utf-8")
    blocks = text.split("\n\n")
    assert blocks[0] == "paragraphs: 295, edited: 3, changed a protected fact: 2"
    assert blocks[1].startswith("¶3 kept\n- ")
    assert "lost" not in blocks[1]
    assert blocks[2].splitlines()[0] == "¶4 CHANGED: number/unit"
    assert "  lost   number/unit  1" in blocks[2] and "  added  number/unit  2" in blocks[2]
    assert blocks[3].splitlines()[-1] == "  lost   negation/hedge/bound  않"
    assert blocks[-1] == "CHANGED: restore or review the paragraphs above.\n"


def test_only_kept_edits_exit_zero(tmp_path):
    b = _write(tmp_path / "b.txt", "참가자는 30명이었다.", "결론은 다음 절에서 다룬다.")
    a = _write(tmp_path / "a.txt", "참가자는 30명이었다.", "결론은 다음 절에서 이야기한다.")
    proc = _run(b, a, "--mode", "block-diff")
    assert proc.returncode == 0
    assert proc.stdout == ("paragraphs: 2, edited: 1, changed a protected fact: 0\n\n"
                           "¶2 kept\n- 결론은 다음 절에서 다룬다.\n+ 결론은 다음 절에서 이야기한다.\n\n"
                           "OK: every protected fact is unchanged.\n")


def test_paragraph_count_change_prints_the_refusal(tmp_path):
    b = _write(tmp_path / "b.txt", "하나.", "둘.")
    a = _write(tmp_path / "a.txt", "하나.")
    proc = _run(b, a, "--mode", "block-diff")
    assert proc.returncode == 3
    assert proc.stdout.startswith("paragraphs: 2 before, 1 after\nREFUSED:")
    assert "¶" not in proc.stdout


def test_multiline_paragraph_stays_one_line_per_side(tmp_path):
    b = _write(tmp_path / "b.md", "첫 줄은 18.6%였다.\n둘째 줄.")
    a = _write(tmp_path / "a.md", "첫 줄은 19%였다.\n둘째 줄.")
    lines = _run(b, a, "--mode", "block-diff").stdout.splitlines()
    assert "- 첫 줄은 18.6%였다.⏎둘째 줄." in lines
    assert "+ 첫 줄은 19%였다.⏎둘째 줄." in lines


def test_default_mode_output_is_unchanged():
    proc = _run("before.hwpx", "after.hwpx", cwd=EXAMPLE)
    assert proc.stdout == (EXAMPLE / "verdict.json").read_text(encoding="utf-8")
    assert json.loads(proc.stdout)["command"] == "guard"


def test_unreadable_input_is_a_usage_error(tmp_path):
    proc = _run(tmp_path / "missing.txt", tmp_path / "also.txt", "--mode", "block-diff")
    assert proc.returncode == 2
