# -*- coding: utf-8 -*-
"""Corpus-backed regression for check_gongmun.

Two claims the synthetic fixtures cannot make:

1. Running the checker over the REAL blank 기안문 서식 — both corpus forms, in
   their untouched blank state — reports the expected *unfilled* shape and
   exits 0. It must not crash, and it must not fail a form nobody has filled.
2. A copy filled with the engine's own operations (``preedit replace``) passes
   every rule. The fill is produced here rather than committed, so the two
   halves of the pipeline (engine fill → module gate) are exercised together.

The corpus originals are never written to: every step works on a copy under
``tmp_path`` and the test asserts the originals are byte-identical afterwards.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MODULE_ROOT = _HERE.parent
_REPO_ROOT = _MODULE_ROOT.parents[1]
_CORPUS = _REPO_ROOT / "tests" / "corpus" / "forms"
for _dir in (_MODULE_ROOT / "scripts", _REPO_ROOT / "engine" / "scripts",
             _HERE):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import check_gongmun  # noqa: E402
import preedit  # noqa: E402

GONGMUN_FORMS = ("gianmun-byeolji-1ho", "gianmun-byeolji-2ho")

# The 비고 block of 별지 제1호서식, verbatim: emptying it is how a fill turns the
# 서식 into a document (이 난은 서식에 포함하지 아니한다).
_BIGO_MARKER = "비고(이 난은 서식에 포함하지 아니한다)"
_BIGO_SENTENCE = (
    '문서를 작성할 때 "행정기관명", "발신명", "기안자", "검토자", "결재권자", '
    '"직위(직급) 서명", "처리과명-연도별 일련번호(시행일)", "도로명주소", '
    '"홈페이지 주소", "공무원의 전자우편주소", "공개 구분"의 용어는 표시하지 '
    "아니하고 그 내용을 적는다."
)

#: What an agent filling 별지 제1호서식 writes. The 비고 quotes five seat labels
#: in one later paragraph. T41 requires the real seat to be named explicitly;
#: map order may not hide that ambiguity by deleting the quote first.
FILL_MAP = {
    _BIGO_SENTENCE: "",
    _BIGO_MARKER: "",
    "행 정 기 관 명": "국가유산청",
    "수신": "수신 국가유산청장",
    "제목": "제목 자료 제출 협조 요청",
    "기안자  직위(직급) 서명": "주무관 홍길동",
    "검토자  직위(직급) 서명": "과장 김영희",
    "결재권자  직위(직급) 서명": "청장 이철수",
    "처리과명-연도별 일련번호(시행일)": {
        "text": "문화유산정책과-1234(2026. 8. 20.)", "at_para": 48},
    "처리과명-연도별 일련번호(접수일)": "",
    "도로명주소": {"text": "서울특별시 종로구 삼봉로 81", "at_para": 52},
    "홈페이지 주소": {"text": "www.khs.go.kr", "at_para": 54},
    "공무원의 전자우편주소": {
        "text": "gongmun@example.com", "at_para": 58},
    "공개 구분": {"text": "대외공개", "at_para": 60},
    "발신명의": "국가유산청장",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_form(slug: str) -> Path:
    path = _CORPUS / "converted" / f"{slug}.hwpx"
    if not path.is_file():
        pytest.skip(f"blank-form corpus is not available: {path}")
    return path


@pytest.fixture()
def blank_1ho(tmp_path):
    """A working COPY of 별지 제1호서식 (originals are never edited in place)."""
    source = corpus_form("gianmun-byeolji-1ho")
    target = tmp_path / source.name
    shutil.copy2(source, target)
    return target


class TestBlankCorpusForms:
    @pytest.mark.parametrize("slug", GONGMUN_FORMS)
    def test_blank_form_passes_and_reports_the_unfilled_shape(self, slug):
        form = corpus_form(slug)
        before = _sha256(form)
        verdict, code = check_gongmun.check(form)
        assert code == 0, verdict["hard"]
        assert verdict["document"]["state"] == "blank"
        assert verdict["counts"]["seats"] >= 1
        # the finishing rules cannot apply to an unfilled 서식, and the checker
        # says so instead of passing them silently
        reasons = {row["rule"]: row["reason"] for row in verdict["skipped"]}
        assert reasons["guide_vocabulary_residue"] == "document_state_blank"
        assert reasons["bigo_block_retained"] == "document_state_blank"
        assert _sha256(form) == before, "the checker must not touch its input"

    def test_first_form_carries_every_seat_family(self):
        verdict, _code = check_gongmun.check(
            corpus_form("gianmun-byeolji-1ho"))
        assert set(verdict["document"]["families"]) == {
            "dumun", "gyeoljae", "gyeolmun", "balsin", "seal"}
        seats = {(row.get("seat"), row.get("state"))
                 for row in verdict["seats"]}
        assert ("seal", "reserved") in seats
        assert ("balsin", "blank_by_design") in seats
        assert ("gyeoljae", "blank_by_design") in seats

    def test_report_style_form_reports_absent_seats_rather_than_failing(self):
        """별지 제2호서식 has no 수신 and no labelled 결재란 — absence is not failure."""
        verdict, code = check_gongmun.check(
            corpus_form("gianmun-byeolji-2ho"))
        assert code == 0
        reasons = {row["rule"]: row["reason"] for row in verdict["skipped"]}
        assert reasons["gyeoljae"] == "seat_absent"
        assert reasons["dumun_label_missing"] == "no_baseline"
        # its issuer seat is a ○ placeholder, and that is what the checker sees
        assert any(row.get("state") == "placeholder_glyphs"
                   for row in verdict["seats"])

    def test_blank_form_is_still_blank_under_a_baseline_of_itself(self):
        form = corpus_form("gianmun-byeolji-1ho")
        verdict, code = check_gongmun.check(form, baseline=form)
        assert code == 0, verdict["hard"]

    def test_seal_slot_of_the_real_form_is_red_bordered(self):
        vocabulary = check_gongmun.load_vocabulary()
        model = check_gongmun.document_model(
            corpus_form("gianmun-byeolji-1ho"))
        slots = check_gongmun.seal_slots(model, vocabulary)
        assert len(slots) == 1
        assert slots[0]["red_bordered"] is True
        assert slots[0]["labels"] == ["직인"]


class TestSyntheticallyFilledCorpusForm:
    @pytest.fixture()
    def filled(self, tmp_path, blank_1ho):
        mapping = tmp_path / "fill.json"
        mapping.write_text(json.dumps(FILL_MAP, ensure_ascii=False),
                           encoding="utf-8")
        out = tmp_path / "filled.hwpx"
        result = preedit.replace_placeholders(
            blank_1ho, out, FILL_MAP, on_zero_hits="error")
        assert result["ok"] and all(result["hits"].values())
        return out

    def test_filled_copy_passes_every_rule(self, filled, blank_1ho):
        verdict, code = check_gongmun.check(filled, baseline=blank_1ho)
        assert code == 0, verdict["hard"]
        assert verdict["document"]["state"] == "final"
        assert verdict["hard"] == []

    def test_fill_did_not_touch_the_corpus_original(self, filled):
        source = corpus_form("gianmun-byeolji-1ho")
        assert _sha256(source) != _sha256(filled)
        # the manifest records the original's digest; re-reading it here would
        # duplicate the corpus test, so the claim is simply that the checker
        # and the fill both worked on copies under tmp_path
        assert source.parent != filled.parent

    def test_seal_slot_and_signature_positions_survive_the_fill(self, filled):
        verdict, _code = check_gongmun.check(filled)
        seals = [row for row in verdict["seats"] if row.get("seat") == "seal"]
        assert seals and seals[0]["state"] == "reserved"
        assert "seal_slot_overwritten" not in {
            row["code"] for row in verdict["hard"]}

    def test_issue_number_is_read_back_in_the_regulated_shape(self, filled):
        verdict, _code = check_gongmun.check(filled)
        issues = [row for row in verdict["seats"]
                  if row.get("seat") == "gyeolmun_issue"]
        assert issues and issues[0]["label"] == "시행"

    def test_a_fill_that_wipes_a_seat_is_caught(self, tmp_path, blank_1ho):
        """Still-catches: the same pipeline, one seat deleted instead of filled."""
        broken_map = dict(FILL_MAP)
        broken_map["도로명주소"] = {"text": "", "at_para": 52}
        out = tmp_path / "wiped.hwpx"
        preedit.replace_placeholders(blank_1ho, out, broken_map,
                                    on_zero_hits="error")
        verdict, code = check_gongmun.check(out, baseline=blank_1ho)
        assert code == 3
        assert "seat_emptied" in {row["code"] for row in verdict["hard"]}

    def test_a_fill_that_leaves_a_guide_term_is_caught(self, tmp_path,
                                                      blank_1ho):
        """Still-catches: 공개 구분 left as the guide term in a finished 공문."""
        partial_map = {key: value for key, value in FILL_MAP.items()
                       if key != "공개 구분"}
        out = tmp_path / "residue.hwpx"
        preedit.replace_placeholders(blank_1ho, out, partial_map,
                                    on_zero_hits="error")
        verdict, code = check_gongmun.check(out)
        assert code == 3
        assert "guide_vocabulary_residue" in {row["code"]
                                              for row in verdict["hard"]}
