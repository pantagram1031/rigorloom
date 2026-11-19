"""``rigorloom guard``: per-paragraph protected-fact check on .txt/.md/.hwpx."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
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


def test_a_minus_written_as_a_word_or_a_math_sign_and_every_digit_count(tmp_path):
    # Sol's re-check of the T183 fixes: 마이너스 and − (U+2212) are minus
    # signs, groups may be several spaces apart, and a long decimal is
    # compared digit by digit, not rounded to 28 places.
    same = [("마이너스 3천 200원", "-3,200원"), ("-3억   6,200만 410원", "-362,000,410원"),
            ("−52,800원", "-52,800원")]
    assert _changed([f"잔액은 {x}이다." for x, _ in same], [f"잔액은 {y}이다." for _, y in same],
                    tmp_path) == []
    changed = [("마이너스 8,500원", "8,500원"), ("−52,800원", "52,800원"),
               ("0.12345678901234567890123456781", "0.12345678901234567890123456782")]
    assert _changed([f"잔액은 {x}이다." for x, _ in changed], [f"잔액은 {y}이다." for _, y in changed],
                    tmp_path) == [1, 2, 3]


def test_a_long_run_of_digits_is_read_in_one_pass():
    # The guard, check, the MCP check tool and the review screen read untrusted
    # text. The number key once tried every digit of a run as the start of a
    # group: 20,000 digits took 13 s, 100,000 several minutes.
    sys.path.insert(0, str(REPO / "runtime" / "scripts"))
    import rt_fidelity

    amounts = [("7" * 100_000 + "원", "7" * 99_999 + "8원"),
               ("1" + ",234" * 3_000 + "원", "1" + ",234" * 2_999 + ",235원"),
               ("1억 " * 3_000 + "원", "1억 " * 2_999 + "2억 원")]
    started = time.perf_counter()
    for x, y in amounts:
        result = rt_fidelity.audit_text(f"금액은 {x}이다.", f"금액은 {y}이다.")
        assert [c["kind"] for c in result["changes"]] == ["numbers"]
        assert len(rt_fidelity.number_keys(f"금액은 {x}이다.")) == 1
    assert time.perf_counter() - started < 5


def test_a_unit_is_not_the_first_letter_of_another_word(tmp_path):
    # 24인치 is not 24인, 제12차량 holds no 차, and after a space a unit has
    # to end the word: 18 인원, 38 평가 and 68 분기점 are bare numbers.
    b = ["최소 사양은 화면 폭 24인치다.", "제12차량 정비 이력을 첨부했다.",
         "명부의 항목 18 인원 확인을 끝냈다.", "과제 38 평가 결과를 첨부했다.",
         "노선 68 분기점 주변을 조사했다.", "정산율 12%project라는 표기를 확인했다.",
         "목록은 8차분 납품서다.", "참석자는 5 명이다."]
    a = ["최소 사양은 운영 인력 24명이다.", "차량 제12호의 정비 이력을 첨부했다.",
         "명부의 항목 18에 대한 인원 확인을 끝냈다.", "과제 38의 평가 결과를 첨부했다.",
         "노선 68의 분기점 주변을 조사했다.", "정산율 12% project라는 표기를 확인했다.",
         "목록은 8 차분 납품서다.", "참석자는 5명이다."]
    assert _changed(b, a, tmp_path) == [1]


def test_an_article_before_a_word_that_starts_with_won_is_not_trillions(tmp_path):
    # Fable's review of T183: 조 is a trillion only before a won that stands
    # alone (1조원이다, 1조 원으로); in 제12조 원장은 and 제5조 원칙 it is an
    # article, so respacing or rewording around it changes nothing.
    b = ["제12조 원장은 회의를 소집한다.", "제5조 원칙에 따라 처리한다.", "예산은 1조원이다.",
         "예산은 1조원이다.", "제3조 원인 분석을 첨부했다."]
    a = ["제12조 위원장은 회의를 소집한다.", "제5조원칙에 따라 처리한다.", "예산은 1조 원이다.",
         "예산은 1조 2천억원이다.", "제4조 원인 분석을 첨부했다."]
    assert _changed(b, a, tmp_path) == [4, 5]


def test_an_amount_in_the_range_of_trillions_keeps_its_won(tmp_path):
    # Fable's review of #396: 대 after 원 (1조원대, 3억 원대) is a counting
    # suffix, so the 조 is a trillion and a space before 원대 changes nothing.
    b = ["1조원대 사업을 맡았다.", "3억원대 아파트를 샀다.", "1조원대 사업을 맡았다."]
    a = ["1조 원대 사업을 맡았다.", "3억 원대 아파트를 샀다.", "2조원대 사업을 맡았다."]
    assert _changed(b, a, tmp_path) == [3]
    sys.path.insert(0, str(REPO / "runtime" / "scripts"))
    import rt_fidelity
    assert rt_fidelity._number_change(b[2], a[2]) == {
        "kind": "numbers", "before": {"1조원": 1}, "after": {"2조원": 1}}


def test_a_number_and_its_unit_on_a_line_of_their_own_are_not_a_heading(tmp_path):
    assert _changed(["3,500원"], ["3500 원"], tmp_path) == []


def test_a_unit_declared_in_the_header_applies_to_the_bare_amounts(tmp_path):
    b = ["| 비목 | 금액 |\n|---|---|\n| 재료비 | 7,000천원 |",
         "| 비목 | 금액(천원) |\n|---|---|\n| 외주비 | 7,000 |",
         "| 비목 | 금액(천원) |\n|---|---|\n| 재료비 | 7,000 |"]
    a = ["| 비목 | 금액(천원) |\n|---|---|\n| 재료비 | 7,000 |",
         "| 비목 | 금액(원) |\n|---|---|\n| 외주비 | 7,000,000 |",
         "| 비목 | 금액(백만원) |\n|---|---|\n| 재료비 | 7,000 |"]
    assert _changed(b, a, tmp_path) == [3]


def test_a_declared_unit_holds_only_where_it_is_declared(tmp_path):
    # A header cell's unit is that column's, a field's unit is the next
    # number's, 단위: and 천원 단위 cover the amounts after them, and a word
    # that merely contains 원 declares nothing.
    b = ["| 순번 | 지출(천원) |\n|---|---|\n| 17 | 84 |",
         "| 순번 | 지출(천원) |\n|---|---|\n| 2 | 84 |",
         "참가 규모는 19로 유지하며 식비(천원)는 62로 책정했다.",
         "연구비(천원)는 75, 시설비(백만원)는 6으로 책정했다.",
         "연구비(천원)는 75, 시설비(백만원)는 6으로 책정했다.",
         "예산은 천원 단위로 표기하여 84로 확정했다.",
         "정산액(원가) 항목의 코드 48을 복사했다.",
         "국내 예산(천원)은 47로 잡았다. 해외 지출 81은 달러 기준이다."]
    a = ["| 순번 | 지출(원) |\n|---|---|\n| 17 | 84,000 |",
         "| 순번 | 지출(원) |\n|---|---|\n| 2,000 | 84,000 |",      # the row number changed
         "참가 규모는 19로 유지하며 식비는 62,000원으로 책정했다.",
         "연구비는 75,000원, 시설비는 6,000,000원으로 책정했다.",
         "연구비(원)는 75, 시설비(백만원)는 6으로 책정했다.",         # 75천원 became 75원
         "예산은 84,000원으로 확정했다.",
         "정산액의 원가 항목 코드는 48이다.",
         "국내 예산은 47,000원으로 잡았다. 해외 지출 81은 달러 기준이다."]
    assert _changed(b, a, tmp_path) == [2, 5]


def test_a_bare_amount_is_shown_with_the_unit_it_inherits(tmp_path):
    b = _write(tmp_path / "b.md", "검수비(천원)는 93으로 확정했다.")
    a = _write(tmp_path / "a.md", "검수비(백만원)는 93으로 확정했다.")
    (change,) = json.loads(_guard(b, a).stdout)["result"]["changed"][0]["changes"]
    assert change == {"kind": "numbers", "before": {"93(천원)": 1}, "after": {"93(백만원)": 1}}


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


def test_a_swap_is_found_past_edited_words_and_repeated_predicates(tmp_path):
    # Sol's re-check: a word edited next to an untouched number does not hide
    # a swap; a predicate every number shares does not veto one; a sentence
    # that gained words at its start still names its number; words after a
    # list end at the noun they mark, so a reordered list stays quiet.
    b = ["북관 조명은 12개, 남관 진열장은 28개, 별관 공용 창고는 36개로 계획했다.",
         "설계비는 38만원을 심사 후 확정했다. 감리비는 47만원을 심사 후 확정했다.",
         "총무팀은 32건을 심사했다. 운영팀은 47건을 심사했다.",
         "명단은 19명, 27건 승인 확인, 44건 보류 확인, 68건 승인 확인을 기록했다.",
         "신청 14건을 승인하고 6건을 반려했다.",
         "지원금 35만원을 반환하고 60만원을 집행했다."]
    a = ["북관 조명은 28개, 남관 진열장은 12개, 별관 공동 창고는 36개로 계획했다.",
         "설계비는 47만원을 심사 후 확정했다. 감리비는 38만원을 심사 후 확정했다.",
         "지난 회의에서 총무팀은 47건을 심사했다. 운영팀은 32건을 심사했다.",
         "명단은 19명, 68건 승인 확인, 44건 보류 확인, 27건 승인 확인을 기록했다.",  # reordered
         "신청 14건을 반려하고 6건을 승인했다.",
         "지원금 60만원을 집행하고 35만원을 반환했다."]                              # reordered
    assert _changed(b, a, tmp_path) == [1, 2, 3, 5]


def test_a_swap_is_shown_with_the_words_that_name_each_number(tmp_path):
    b = _write(tmp_path / "b.md", "기획팀은 11명, 집행팀은 17명으로 편성했다.",
               "동관에서 근무하는 야간 순찰 담당 직원은 8명, 서관에서 근무하는 야간 순찰 담당 직원은 24명이다.")
    a = _write(tmp_path / "a.md", "기획 부서는 17명, 집행팀은 11명으로 편성했다.",
               "동관에서 근무하는 야간 순찰 담당 직원은 24명, 서관에서 근무하는 야간 순찰 담당 직원은 8명이다.")
    rows = json.loads(_guard(b, a).stdout)["result"]["changed"]
    assert [r["changes"] for r in rows] == [
        [{"kind": "numbers", "order": True,
          "before": ["기획팀은 11명", "집행팀은 17명"], "after": ["기획 부서는 17명", "집행팀은 11명"]}],
        [{"kind": "numbers", "order": True,
          "before": ["동관에서 근무하는 야간 순찰 담당 직원은 8명", "서관에서 근무하는 야간 순찰 담당 직원은 24명"],
          "after": ["동관에서 근무하는 야간 순찰 담당 직원은 24명", "서관에서 근무하는 야간 순찰 담당 직원은 8명"]}]]


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
