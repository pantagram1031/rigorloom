"""``rigorloom guard``: per-paragraph protected-fact check on .txt/.md/.hwpx."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "runtime" / "scripts" / "cli.py"
FORM = REPO / "tests" / "corpus" / "forms" / "converted" / "moel-pyojun-geunrogyeyakseo-2013.hwpx"


def _guard(before: Path, after: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), "guard", str(before), str(after), *extra],
                          capture_output=True, text=True, encoding="utf-8")


def _write(path: Path, *paras: str) -> Path:
    path.write_text("\n\n".join(paras) + "\n", encoding="utf-8")
    return path


def _edit_hwpx(src: Path, dst: Path, old: str, new: str) -> Path:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        hit = False
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("Contents/section") and old.encode() in data:
                data, hit = data.replace(old.encode(), new.encode(), 1), True
            zout.writestr(item, data)
    assert hit, f"{old!r} not found in {src.name}"
    return dst


def test_rewording_that_keeps_every_fact_exits_zero(tmp_path):
    b = _write(tmp_path / "b.txt", "참가자는 30명이었고 응답률은 18.6%였다.", "결론은 다음 절에서 다룬다.")
    a = _write(tmp_path / "a.txt", "응답률은 18.6%였고 참가자는 30명이었다.", "결론은 다음 절에서 이야기한다.")
    proc = _guard(b, a)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["pass"] is True and result["edited"] == 2 and result["changed"] == []


def test_a_changed_number_or_dropped_negation_is_named_by_paragraph(tmp_path):
    b = _write(tmp_path / "b.md", "응답률은 18.6%였다.", "표본이 작아 일반화할 수 없다.")
    a = _write(tmp_path / "a.md", "응답률은 19%였다.", "표본이 작지만 일반화할 수 있다.")
    proc = _guard(b, a)
    assert proc.returncode == 3
    changed = json.loads(proc.stdout)["result"]["changed"]
    assert [(c["paragraph"], c["kinds"]) for c in changed] == [(1, ["numbers"]), (2, ["qualifiers"])]


def test_a_number_right_after_hangul_is_still_a_number(tmp_path):
    # Python's \w includes Hangul, so a lookbehind on \w hid 17 in 제17조.
    b = _write(tmp_path / "b.md", "근로기준법 제17조를 따른다.", "금500만원을 지급한다.",
               "2025년 1월부터 시행한다.", "버전 v2와 x86은 그대로다.")
    a = _write(tmp_path / "a.md", "근로기준법 제18조를 따른다.", "금50만원을 지급한다.",
               "2026년 1월부터 시행한다.", "버전 v2와 x86은 그대로다.")
    proc = _guard(b, a)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    changed = json.loads(proc.stdout)["result"]["changed"]
    assert [(c["paragraph"], c["kinds"]) for c in changed] == [
        (1, ["numbers"]), (2, ["numbers"]), (3, ["numbers"])]



def test_the_same_number_spelled_another_way_is_not_a_change(tmp_path):
    # Reading numbers after Hangul (T180) must not start flagging digit width,
    # thousands commas or the space before a unit.
    b = _write(tmp_path / "b.md", "제１７조를 따른다.", "금1,000만원을 지급한다.", "온도는 약20 ℃이다.")
    a = _write(tmp_path / "a.md", "제17조를 따른다.", "금1000만원을 지급한다.", "온도는 약20℃이다.")
    proc = _guard(b, a)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["result"]["changed"] == []

def test_added_or_removed_paragraphs_are_refused_not_guessed(tmp_path):
    b = _write(tmp_path / "b.txt", "하나.", "둘.")
    a = _write(tmp_path / "a.txt", "하나.")
    proc = _guard(b, a)
    assert proc.returncode == 3
    assert json.loads(proc.stdout)["result"]["reason"] == "paragraph_count_changed"


def test_hwpx_paragraphs_are_compared_without_hancom(tmp_path):
    same = _edit_hwpx(FORM, tmp_path / "same.hwpx", "체결한다", "맺는다")
    proc = _guard(FORM, same)
    assert proc.returncode == 0, proc.stdout
    assert json.loads(proc.stdout)["result"]["edited"] == 1

    moved = _edit_hwpx(FORM, tmp_path / "moved.hwpx", "매주", "매월")
    moved = _edit_hwpx(moved, tmp_path / "moved2.hwpx", "1. 근로계약기간", "2. 근로계약기간")
    proc = _guard(FORM, moved, "--format", "text")
    assert proc.returncode == 3
    assert "number/unit" in proc.stdout and "CHANGED" in proc.stdout


def test_inputs_that_cannot_be_compared_are_usage_errors(tmp_path):
    b = _write(tmp_path / "b.txt", "x")
    other = tmp_path / "a.docx"
    other.write_bytes(b"not really")
    assert _guard(b, other).returncode == 2
    assert _guard(b, tmp_path / "missing.txt").returncode == 2
    fake = tmp_path / "fake.hwpx"
    fake.write_bytes(b"not a zip")
    assert _guard(fake, fake).returncode == 2


def test_runtime_copy_of_the_checker_matches_the_module():
    """The wheel ships rt_fidelity.py; it must be the module's checker, not a fork."""
    module = REPO / "modules" / "style" / "scripts" / "prose_fidelity.py"
    runtime = REPO / "runtime" / "scripts" / "rt_fidelity.py"
    assert runtime.read_bytes() == module.read_bytes(), (
        "copy modules/style/scripts/prose_fidelity.py to runtime/scripts/rt_fidelity.py")


def test_committed_example_verdict_is_reproduced_byte_for_byte():
    example = REPO / "examples" / "guard"
    proc = subprocess.run([sys.executable, str(CLI), "guard", "before.hwpx", "after.hwpx"],
                          cwd=example, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 3
    assert proc.stdout == (example / "verdict.json").read_text(encoding="utf-8")


def test_readme_quick_start_output_is_real(tmp_path):
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    block = readme.split("## Try it in one minute", 1)[1]
    sh, out = block.split("```sh\n", 1)[1].split("```", 1)[0], block.split("```text\n", 1)[1].split("```", 1)[0]
    texts = [line.split("'")[1].replace("%%", "%").replace("\\n", "\n")
             for line in sh.splitlines() if line.startswith("printf")]
    (tmp_path / "before.txt").write_text(texts[0], encoding="utf-8")
    (tmp_path / "after.txt").write_text(texts[1], encoding="utf-8")
    proc = _guard(tmp_path / "before.txt", tmp_path / "after.txt", "--format", "text")
    assert proc.returncode == 3
    assert proc.stdout == out


def test_reflow_that_starts_a_line_with_a_number_is_a_heading_change(tmp_path):
    """Deliberate strictness, as in test_known_strictness_is_deliberate: a hard
    wrap that puts "3. ..." at a line start makes a short numbered line, which
    counts as a heading, so the paragraph is reported."""
    b = _write(tmp_path / "b.md", "조건은 세 가지다. 3. 반복 측정은 하지 않았다")
    a = _write(tmp_path / "a.md", "조건은 세 가지다.\n3. 반복 측정은 하지 않았다")
    proc = _guard(b, a)
    assert proc.returncode == 3
    assert json.loads(proc.stdout)["result"]["changed"][0]["kinds"] == ["headings"]


def test_paths_are_reported_as_names_and_zip_bombs_are_refused(tmp_path):
    b = _write(tmp_path / "b.txt", "x")
    proc = _guard(b.resolve(), b.resolve())
    assert json.loads(proc.stdout)["result"]["before"] == "b.txt"
    bomb = tmp_path / "bomb.hwpx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Contents/section0.xml", b"<a>" + b" " * (20 * 1024 * 1024) + b"</a>")
    proc = _guard(bomb, bomb)
    assert proc.returncode == 2 and "compression ratio" in proc.stdout
