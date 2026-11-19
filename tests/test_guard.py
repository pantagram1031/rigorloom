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


def test_a_version_glued_to_a_latin_letter_is_left_alone(tmp_path):
    # The boundary on the other side: digits right after an ASCII letter (v2,
    # x86, A4) stay outside the guard, even when they change.
    b = _write(tmp_path / "b.md", "내부 초안 표시는 v2다.")
    a = _write(tmp_path / "a.md", "내부 초안 표시는 v3다.")
    proc = _guard(b, a)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["edited"] == 1 and result["changed"] == []


def test_the_same_number_spelled_another_way_is_not_a_change(tmp_path):
    # Reading numbers after Hangul (T180) must not start flagging digit width,
    # thousands commas or the space before a unit.
    b = _write(tmp_path / "b.md", "제１７조를 따른다.", "금1,000만원을 지급한다.", "온도는 약20 ℃이다.")
    a = _write(tmp_path / "a.md", "제17조를 따른다.", "금1000만원을 지급한다.", "온도는 약20℃이다.")
    proc = _guard(b, a)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["result"]["changed"] == []


def test_a_korean_magnitude_or_unit_is_part_of_the_number(tmp_path):
    # 500만원 and 500원 share their digits; the magnitude and the unit are the fact.
    b = _write(tmp_path / "b.md", "금500만원을 지급한다.", "사업비는 2천만원이다.",
               "3일 이내에 제출한다.", "면적은 10 m²이다.")
    a = _write(tmp_path / "a.md", "금500원을 지급한다.", "사업비는 2백만원이다.",
               "3개월 이내에 제출한다.", "면적은 10 m³이다.")
    proc = _guard(b, a)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    changed = json.loads(proc.stdout)["result"]["changed"]
    assert [(c["paragraph"], c["kinds"]) for c in changed] == [
        (1, ["numbers"]), (2, ["numbers"]), (3, ["numbers"]), (4, ["numbers"])]


def test_the_same_amount_written_with_or_without_a_magnitude_is_not_a_change(tmp_path):
    b = _write(tmp_path / "b.md", "금500만원을 지급한다.", "총 1억 2천만원이다.", "총 2천3백만 원이다.",
               "면적은 10㎡이다.", "기간은 1달이다.", "제1조 2항을 따른다.")
    a = _write(tmp_path / "a.md", "금5,000,000원을 지급한다.", "총 120,000,000원이다.",
               "총 23,000,000원이다.", "면적은 10 m²이다.", "기간은 1개월이다.", "제1조 제2항을 따른다.")
    proc = _guard(b, a)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["result"]["changed"] == []


def test_numbers_that_trade_places_are_a_change(tmp_path):
    # Every number is still there, so counting them saw nothing.
    b = _write(tmp_path / "b.md", "기본급은 300만원, 수당은 50만원이다.")
    a = _write(tmp_path / "a.md", "기본급은 50만원, 수당은 300만원이다.")
    proc = _guard(b, a)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    (change,) = json.loads(proc.stdout)["result"]["changed"]
    assert change["kinds"] == ["numbers"]
    assert change["changes"] == [{"kind": "numbers", "order": True,
                                  "before": ["기본급은 300만원", "수당은 50만원"],
                                  "after": ["기본급은 50만원", "수당은 300만원"]}]
    text = _guard(b, a, "--format", "text").stdout
    assert "swapped numbers" in text and "기본급은 300만원, 수당은 50만원  ->  기본급은 50만원, 수당은 300만원" in text


def test_a_reordered_sentence_keeps_its_numbers_with_their_words(tmp_path):
    b = _write(tmp_path / "b.md", "기본급은 300만원, 수당은 50만원이다.", "제17조 및 제18조를 따른다.",
               "응답률은 18.6%였고 참가자는 30명이었다.")
    a = _write(tmp_path / "a.md", "수당은 50만원, 기본급은 300만원이다.", "제18조 및 제17조를 따른다.",
               "참가자는 30명, 응답률은 18.6%였다.")
    proc = _guard(b, a)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["result"]["changed"] == []


def _changed(b_paras, a_paras, tmp_path) -> list[int]:
    proc = _guard(_write(tmp_path / "b.md", *b_paras), _write(tmp_path / "a.md", *a_paras))
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr
    return [c["paragraph"] for c in json.loads(proc.stdout)["result"]["changed"]]


def test_the_sign_scale_and_spelling_of_an_amount(tmp_path):
    # From Sol's T183 review: the sign covers the whole amount, the won after
    # the last group belongs to it, and spacing, a trailing zero or a plus
    # sign change nothing.
    same = [("-1억 4천만원", "-140,000,000원"), ("1억 2,000만 3,500원", "120,003,500원"),
            ("2억  7천만원", "270,000,000원"), ("연 1.20%", "연 1.2%"), ("+3,000원", "3,000원"),
            ("7명", "7인"), ("36 m²", "36 m2"), ("10㎡", "10제곱미터")]
    assert _changed([f"금액은 {x}이다." for x, _ in same], [f"금액은 {y}이다." for _, y in same],
                    tmp_path) == []
    changed = [("-1억 2천만원", "-80,000,000원"), ("4%", "4%p"), ("45평", "45제곱미터"),
               ("4차", "4분기"), ("3일", "3년"), ("2개월", "2년")]
    assert _changed([f"기준은 {x}이다." for x, _ in changed], [f"기준은 {y}이다." for _, y in changed],
                    tmp_path) == list(range(1, len(changed) + 1))


def test_a_unit_declared_in_the_header_applies_to_the_bare_amounts(tmp_path):
    b = ["| 비목 | 금액 |\n|---|---|\n| 재료비 | 7,000천원 |",
         "| 비목 | 금액(천원) |\n|---|---|\n| 외주비 | 7,000 |",
         "| 비목 | 금액(천원) |\n|---|---|\n| 재료비 | 7,000 |"]
    a = ["| 비목 | 금액(천원) |\n|---|---|\n| 재료비 | 7,000 |",
         "| 비목 | 금액(원) |\n|---|---|\n| 외주비 | 7,000,000 |",
         "| 비목 | 금액(백만원) |\n|---|---|\n| 재료비 | 7,000 |"]
    assert _changed(b, a, tmp_path) == [3]


def test_which_words_a_number_belongs_to(tmp_path):
    b = ["안건은 3건 승인, 5건 보류, 7건 반려로 집계했다.",
         "안건은 3건 승인, 5건 보류로 집계했다.",
         "서부권 지원금은 6천만원, 동부권 지원금은 9천만원이다.",
         "1. 재료비 30만원을 청구한다.\n2. 인쇄비 70만원을 청구한다.",
         "A반 학생은 20명, B반 학생은 25명이다."]
    a = ["안건은 5건 보류, 3건 승인, 7건 반려로 집계했다.",   # reordered: same
         "안건은 5건 승인, 3건 보류로 집계했다.",             # swapped
         "서부권 지원금은 9천만원, 동부권 지원금은 6천만원이다.",
         "1. 재료비 70만원을 청구한다.\n2. 인쇄비 30만원을 청구한다.",
         "A반 학생은 25명, B반 학생은 20명이다."]
    assert _changed(b, a, tmp_path) == [2, 3, 4, 5]


def test_a_swap_is_shown_in_each_sides_own_words_and_spelling(tmp_path):
    b = _write(tmp_path / "b.md", "평가 2회, 조사 4회, 시설비 3천만원, 재료비 7천만원을 확정했다.")
    a = _write(tmp_path / "a.md", "평가 4회, 조사 2회, 시설비 70,000,000원, 재료비 30,000,000원을 확정했다.")
    (change,) = json.loads(_guard(b, a).stdout)["result"]["changed"][0]["changes"]
    assert change == {"kind": "numbers", "order": True,
                      "before": ["평가 2회", "조사 4회", "시설비 3천만원", "재료비 7천만원"],
                      "after": ["평가 4회", "조사 2회", "시설비 70,000,000원", "재료비 30,000,000원"]}


def test_changed_numbers_are_shown_as_the_document_writes_them(tmp_path):
    # Compared in one spelling, shown in the document's: 1,000만원 stays 1,000만원
    # on both sides instead of turning into 10000000원, and is not reported as
    # lost and added just because the edit dropped its comma.
    b = _write(tmp_path / "b.md", "금1,000만원과 금5만원을 지급한다.")
    a = _write(tmp_path / "a.md", "금1000만원과 금6만원을 지급한다.")
    proc = _guard(b, a)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    (change,) = json.loads(proc.stdout)["result"]["changed"][0]["changes"]
    assert change == {"kind": "numbers", "before": {"1,000만원": 1, "5만원": 1},
                      "after": {"1,000만원": 1, "6만원": 1}}


def test_a_full_width_latin_letter_glues_like_an_ascii_one(tmp_path):
    b = _write(tmp_path / "b.md", "내부 초안 표시는 ｖ２다.")
    a = _write(tmp_path / "a.md", "내부 초안 표시는 ｖ３다.")
    proc = _guard(b, a)
    assert proc.returncode == 0, proc.stdout + proc.stderr


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
