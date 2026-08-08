# -*- coding: utf-8 -*-
"""Corpus-backed regression for check_minwon over all four family-① forms.

Three claims the synthetic fixtures cannot make:

1. Running the checker over the REAL blank 별지서식 — all four corpus forms, in
   their untouched blank state, with and without a baseline — reports the
   expected *unfilled* shape and exits 0. It must not crash, and it must not
   fail a form nobody has filled.
2. Each form's own declarations are actually read off the document: the shading
   sentence only exists in 정보공개 청구서, the `[ ]에 √표` instruction only in
   주민등록 등초본 신청서 and 사업자등록 신청서, and the checker's behaviour
   differs accordingly.
3. A copy filled with the engine's own operations (``preedit replace`` +
   ``preedit fill-cells``) passes every rule, and the still-catches variants —
   an invented 주민등록번호, a wiped 접수번호, a deleted option, a lost signature
   marker, a stripped footer — are all caught. The fill is produced here rather
   than committed, so the two halves of the pipeline (engine fill → module gate)
   are exercised together.

The corpus originals are never written to: every step works on a copy under
``tmp_path`` and the tests assert the originals are byte-identical afterwards.
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
             _REPO_ROOT / "pipeline" / "scripts", _HERE):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import check_minwon as cm  # noqa: E402
import preedit  # noqa: E402

#: The four family-① forms (docs/research/hwp-usage-landscape.md family ①;
#: tests/corpus/forms/manifest.json family "petition").
MINWON_FORMS = (
    "jumin-deungchobon-sinchengseo",
    "jeongbo-gonggae-cheongguseo",
    "saeopja-deungnok-sinchengseo",
    "admrul-gajokdolbom-hyuga-sinchengseo",
)

#: What an agent filling 주민등록법 별지 제7호서식 writes. Keys are exact run texts
#: from the form: 주민등록 등초본 신청서 splits '[  ]' across two runs in some
#: cells, so the fill keys deliberately target runs that hold a whole group.
#: 주민등록번호 is ABSENT on purpose — the operator supplied no identity number,
#: so the seat stays empty and check_minwon must not complain about that.
FILL_MAP = {
    "성명 ": "성명 김도현 ",
    "                (시ㆍ도)                   (시ㆍ군ㆍ구)":
        "                서울특별시                   강남구",
    "연락처": "연락처 010-0000-0000",
    " [  ]등본 사항 전부 포함                  [  ]초본 사항 전부 포함":
        " [√]등본 사항 전부 포함                  [  ]초본 사항 전부 포함",
    "[  ]통": "[1]통",
    "     년      월      일": "     2026년      8월      20일",
}

#: The 용도 및 목적 value cell of 주민등록 등초본 신청서: empty in the blank form,
#: so it has no ``hp:t`` and only ``fill-cells`` can reach it.
PURPOSE_CELL = (1, 21, 1, "은행 제출용")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_form(slug: str) -> Path:
    path = _CORPUS / "converted" / f"{slug}.hwpx"
    if not path.is_file():
        pytest.skip(f"blank-form corpus is not available: {path}")
    return path


@pytest.fixture()
def blank_jumin(tmp_path):
    """A working COPY of 별지 제7호서식 (originals are never edited in place)."""
    source = corpus_form("jumin-deungchobon-sinchengseo")
    target = tmp_path / source.name
    shutil.copy2(source, target)
    return target


class TestBlankCorpusForms:
    @pytest.mark.parametrize("slug", MINWON_FORMS)
    def test_blank_form_passes_and_reports_the_unfilled_shape(self, slug):
        form = corpus_form(slug)
        before = _sha256(form)
        verdict, code = cm.check(form)
        assert code == 0, verdict["hard"]
        assert verdict["document"]["state"] == "blank"
        assert verdict["document"]["marked_checkboxes"] == 0
        assert verdict["document"]["unfilled_date_seats"] >= 1
        assert verdict["counts"]["seats"] >= 1
        # the finishing rules cannot apply to an unfilled 서식, and the checker
        # says so instead of passing them silently
        reasons = {row["rule"]: row["reason"] for row in verdict["skipped"]}
        assert reasons["checkbox_selection_absent"] == "document_state_blank"
        assert reasons["placeholder_glyphs_retained"] == "document_state_blank"
        assert _sha256(form) == before, "the checker must not touch its input"

    @pytest.mark.parametrize("slug", MINWON_FORMS)
    def test_blank_form_is_still_blank_under_a_baseline_of_itself(self, slug):
        form = corpus_form(slug)
        verdict, code = cm.check(form, baseline=form)
        assert code == 0, verdict["hard"]
        assert verdict["document"]["cells_changed"] == 0

    @pytest.mark.parametrize("slug", MINWON_FORMS)
    def test_every_form_carries_the_byeolji_header_and_an_addressee(self, slug):
        """The two frame facts all four forms share — 210mm×297mm is NOT one of
        them (행정규칙 서식 has no paper-spec footer)."""
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(corpus_form(slug))
        assert cm.header_lines(model, vocabulary)
        assert cm.addressee_count(model, vocabulary) >= 1

    def test_the_dense_grid_form_carries_every_seat_family(self):
        verdict, _code = cm.check(corpus_form("jumin-deungchobon-sinchengseo"))
        assert set(verdict["document"]["families"]) == {
            "furniture", "guide", "human", "identity", "select"}

    def test_the_sparse_admrul_form_reports_absent_seats_rather_than_failing(
            self):
        """행정규칙 별지 제13호 has no 접수 block, no 유의사항 and no paper-spec
        footer — absence is not failure."""
        form = corpus_form("admrul-gajokdolbom-hyuga-sinchengseo")
        verdict, code = cm.check(form, baseline=form)
        assert code == 0
        reasons = {row["rule"]: row["reason"] for row in verdict["skipped"]}
        assert reasons["staff_seat_filled"] == "seat_absent"
        assert reasons["guide_block_lost"] == "seat_absent"
        assert any(row.get("seat") == "paper_spec_footer"
                   and row["state"] == "none_in_baseline"
                   for row in verdict["seats"])
        # its signature seats live in top-level paragraphs, not cells
        assert any(row.get("basis") == "paragraph_count"
                   for row in verdict["seats"])

    def test_only_the_information_disclosure_form_declares_the_shading_rule(
            self):
        """The gate that keeps 주민등록 등초본 신청서's #B2B2B2 instruction blocks
        from being mistaken for staff-only cells."""
        vocabulary = cm.load_vocabulary()
        declared = {
            slug: cm.declares_shading_rule(
                cm.document_model(corpus_form(slug)), vocabulary)
            for slug in MINWON_FORMS}
        assert declared == {
            "jumin-deungchobon-sinchengseo": False,
            "jeongbo-gonggae-cheongguseo": True,
            "saeopja-deungnok-sinchengseo": False,
            "admrul-gajokdolbom-hyuga-sinchengseo": False,
        }

    def test_the_shaded_staff_block_of_the_real_form_is_recognized(self):
        """정보공개 청구서: 접수번호/접수일/처리기간 are #B2B2B2 (0.698) and the
        form says dark cells are not the applicant's."""
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(corpus_form("jeongbo-gonggae-cheongguseo"))
        seats = cm.staff_seats(model, vocabulary)
        assert len(seats) >= 7
        shaded = [seat for seat in seats
                  if seat["face_brightness"] is not None
                  and seat["face_brightness"] <= 0.75]
        assert shaded, "the #B2B2B2 접수 block must be recognized"
        labels = {label for seat in seats for label in seat["labels"]}
        assert {"접수번호", "접수일", "처리기간", "접수부서", "접수자"} <= labels

    def test_the_label_recognizer_covers_the_undeclared_shaded_form(self):
        """사업자등록 신청서 shades its 접수번호 row #BBBBBB but declares no
        shading rule, so the label-anchored recognizer is what covers it."""
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(corpus_form("saeopja-deungnok-sinchengseo"))
        seats = cm.staff_seats(model, vocabulary)
        assert seats
        assert all("label" in seat["basis"] for seat in seats)
        labels = {label for seat in seats for label in seat["labels"]}
        assert {"접수번호", "처리기간"} <= labels

    def test_the_addressee_line_is_not_mistaken_for_a_staff_seat(self):
        """'(접수 기관의 장) 귀하' is the ADDRESSEE, and replacing the guide term
        is what an agent is supposed to do."""
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(corpus_form("jeongbo-gonggae-cheongguseo"))
        for seat in cm.staff_seats(model, vocabulary):
            assert not cm._contains(seat["text"], "귀하")

    @pytest.mark.parametrize("slug,declared", [
        ("jumin-deungchobon-sinchengseo", True),
        ("saeopja-deungnok-sinchengseo", True),
        ("jeongbo-gonggae-cheongguseo", False),
        ("admrul-gajokdolbom-hyuga-sinchengseo", False),
    ])
    def test_the_check_instruction_is_read_off_each_form(self, slug, declared):
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(corpus_form(slug))
        found = bool(cm._findall(vocabulary["select_instruction_re"],
                                cm.haystack(model)))
        assert found is declared

    @pytest.mark.parametrize("slug", MINWON_FORMS)
    def test_no_blank_form_contains_an_identity_number(self, slug):
        """The corpus privacy ruling says these are blank templates; the RRN rule
        agrees, and that is what makes 'invented' meaningful."""
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(corpus_form(slug))
        assert cm._findall(vocabulary["rrn_re"], cm.haystack(model)) == []

    @pytest.mark.parametrize("slug", MINWON_FORMS)
    def test_no_blank_form_reads_as_having_a_marked_checkbox(self, slug):
        """A bare ■ is the 별지서식 header's bullet, not a mark. Every form uses
        it, so the marked-glyph class has to exclude it."""
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(corpus_form(slug))
        text = cm.haystack(model)
        assert cm._findall(vocabulary["marked_glyph_re"], text) == []
        assert cm._findall(vocabulary["unmarked_glyph_re"], text)


class TestSyntheticallyFilledCorpusForm:
    @pytest.fixture()
    def filled(self, tmp_path, blank_jumin):
        replaced = tmp_path / "replaced.hwpx"
        result = preedit.replace_placeholders(
            blank_jumin, replaced, FILL_MAP, on_zero_hits="error")
        assert result["ok"] and all(result["hits"].values())
        out = tmp_path / "filled.hwpx"
        table, row, col, text = PURPOSE_CELL
        cells = preedit.fill_cells(replaced, out, [(row, col, text)],
                                  table=table)
        assert cells["filled"] == 1
        return out

    @pytest.fixture()
    def fill_map_file(self, tmp_path):
        path = tmp_path / "fill.json"
        path.write_text(json.dumps(FILL_MAP, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def test_filled_copy_passes_every_rule(self, filled, blank_jumin,
                                           fill_map_file):
        verdict, code = cm.check(filled, baseline=blank_jumin,
                                 fill_map=fill_map_file)
        assert code == 0, verdict["hard"]
        assert verdict["document"]["state"] == "final"
        assert verdict["hard"] == []
        assert verdict["warn"] == []

    def test_a_baseline_leaves_nothing_undecided_on_the_real_form(
            self, filled, blank_jumin):
        without, _code = cm.check(filled)
        undecided = {row["rule"] for row in without["skipped"]
                     if row["reason"] == "no_baseline"}
        assert len(undecided) >= 9, undecided
        with_baseline, _code = cm.check(filled, baseline=blank_jumin)
        assert {row["rule"] for row in with_baseline["skipped"]
                if row["reason"] == "no_baseline"} == set()

    def test_the_fill_left_the_identity_seats_empty(self, filled, blank_jumin):
        """FILL_MAP supplies no 주민등록번호 and the checker is content: an empty
        identity seat is the correct output, not a finding."""
        verdict, _code = cm.check(filled, baseline=blank_jumin)
        assert "identity_seat_autofilled" not in {row["code"]
                                                 for row in verdict["hard"]}
        assert any(row.get("seat") == "identity_value"
                   and row["state"] == "none_present"
                   for row in verdict["seats"])

    def test_the_guide_pages_and_signature_seats_survived(self, filled,
                                                         blank_jumin):
        verdict, _code = cm.check(filled, baseline=blank_jumin)
        kept = {row["label"] for row in verdict["seats"]
                if row.get("seat") == "guide_block"}
        assert {"유의사항", "수수료"} <= kept
        signatures = [row for row in verdict["seats"]
                      if row.get("seat") == "signature"]
        assert len(signatures) >= 4
        assert all(row["state"] == "reserved" for row in signatures)

    def test_marking_a_box_kept_the_slot_count(self, filled, blank_jumin):
        vocabulary = cm.load_vocabulary()
        before = cm.checkbox_slots_by_cell(
            cm.document_model(blank_jumin), vocabulary)
        after = cm.checkbox_slots_by_cell(
            cm.document_model(filled), vocabulary)
        assert sum(after.values()) >= sum(before.values())
        verdict, _code = cm.check(filled, baseline=blank_jumin)
        assert verdict["document"]["marked_checkboxes"] >= 1

    def test_fill_did_not_touch_the_corpus_original(self, filled):
        source = corpus_form("jumin-deungchobon-sinchengseo")
        assert _sha256(source) != _sha256(filled)
        assert source.parent != filled.parent

    # ── still-catches: the same pipeline, one thing wrong ──────────────────
    def _variant(self, tmp_path, blank, name, mapping):
        out = tmp_path / f"{name}.hwpx"
        preedit.replace_placeholders(blank, out, mapping, on_zero_hits="error")
        return cm.check(out, baseline=blank)

    def test_an_invented_rrn_is_caught(self, tmp_path, blank_jumin):
        verdict, code = self._variant(
            tmp_path, blank_jumin, "rrn",
            {**FILL_MAP, "주민등록번호": "주민등록번호 900101-1234567"})
        assert code == 3
        assert {"identity_value_invented", "identity_seat_autofilled"} <= {
            row["code"] for row in verdict["hard"]}

    def test_the_same_rrn_passes_once_the_operator_declares_it(
            self, tmp_path, blank_jumin):
        mapping = {**FILL_MAP, "주민등록번호": "주민등록번호 900101-1234567"}
        out = tmp_path / "rrn-ok.hwpx"
        preedit.replace_placeholders(blank_jumin, out, mapping,
                                    on_zero_hits="error")
        declared = tmp_path / "declared.json"
        declared.write_text(json.dumps(mapping, ensure_ascii=False),
                            encoding="utf-8")
        verdict, code = cm.check(out, baseline=blank_jumin, fill_map=declared)
        assert code == 0, verdict["hard"]

    def test_a_deleted_signature_marker_is_caught(self, tmp_path, blank_jumin):
        verdict, code = self._variant(tmp_path, blank_jumin, "sig",
                                      {**FILL_MAP, "(서명 또는 인)": ""})
        assert code == 3
        assert "signature_marker_lost" in {row["code"]
                                          for row in verdict["hard"]}

    def test_a_stripped_paper_spec_footer_is_caught(self, tmp_path,
                                                   blank_jumin):
        verdict, code = self._variant(
            tmp_path, blank_jumin, "footer",
            {**FILL_MAP, "210㎜×297㎜[백상지(80g/㎡) 또는 중질지(80g/㎡)]": ""})
        assert code == 3
        assert "paper_spec_footer_lost" in {row["code"]
                                           for row in verdict["hard"]}

    def test_a_stripped_byeolji_header_is_caught(self, tmp_path, blank_jumin):
        verdict, code = self._variant(tmp_path, blank_jumin, "header",
                                      {**FILL_MAP, "[별지 제7호서식]": ""})
        assert code == 3
        assert "byeolji_header_lost" in {row["code"] for row in verdict["hard"]}

    def test_a_lost_addressee_line_is_caught(self, tmp_path, blank_jumin):
        verdict, code = self._variant(tmp_path, blank_jumin, "addr",
                                      {**FILL_MAP, "귀하": ""})
        assert code == 3
        assert "addressee_line_lost" in {row["code"] for row in verdict["hard"]}

    def test_a_deleted_option_is_caught(self, tmp_path, blank_jumin):
        verdict, code = self._variant(
            tmp_path, blank_jumin, "option",
            {**FILL_MAP,
             " [  ]등본 사항 전부 포함                  [  ]초본 사항 전부 포함":
                 " 등본 사항 전부 포함                  초본 사항 전부 포함"})
        assert code == 3
        assert "checkbox_option_lost" in {row["code"] for row in verdict["hard"]}

    def test_a_finished_document_with_no_selection_is_caught(self, tmp_path,
                                                            blank_jumin):
        """주민등록 등초본 신청서 declares '[ ]에 √표를 합니다', so an unmarked
        final document is HARD on the form's own authority."""
        verdict, code = self._variant(
            tmp_path, blank_jumin, "nosel",
            {"성명 ": "성명 김도현 ",
             "     년      월      일": "     2026년      8월      20일"})
        assert code == 3
        finding = next(row for row in verdict["hard"]
                       if row["code"] == "checkbox_selection_absent")
        assert finding["instruction_declared"] is True


class TestStaffSeatsOnTheRealForm:
    @pytest.fixture()
    def blank_jeongbo(self, tmp_path):
        source = corpus_form("jeongbo-gonggae-cheongguseo")
        target = tmp_path / source.name
        shutil.copy2(source, target)
        return target

    def test_writing_into_the_real_shaded_staff_block_is_caught(
            self, tmp_path, blank_jeongbo):
        out = tmp_path / "staff.hwpx"
        preedit.replace_placeholders(blank_jeongbo, out,
                                    {"접수번호": "접수번호 2026-1234"},
                                    on_zero_hits="error")
        verdict, code = cm.check(out, baseline=blank_jeongbo)
        assert code == 3
        findings = [row for row in verdict["hard"]
                    if row["code"] == "staff_seat_filled"]
        assert findings
        assert all("접수번호" in row["labels"] for row in findings)

    def test_the_real_seal_slot_is_recognized_and_reserved(self,
                                                          blank_jeongbo):
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(blank_jeongbo)
        seals = cm.seal_cells(model, vocabulary)
        assert seals and any(seal["labels"] == ["직인"] for seal in seals)
        verdict, code = cm.check(blank_jeongbo, baseline=blank_jeongbo)
        assert code == 0
        assert any(row.get("seat") == "seal" and row["state"] == "reserved"
                   for row in verdict["seats"])

    def test_deleting_the_guide_block_is_caught(self, tmp_path, blank_jeongbo):
        out = tmp_path / "guide.hwpx"
        preedit.replace_placeholders(blank_jeongbo, out, {"유 의 사 항": ""},
                                    on_zero_hits="error")
        verdict, code = cm.check(out, baseline=blank_jeongbo)
        assert code == 3
        lost = {row["at"] for row in verdict["hard"]
                if row["code"] == "guide_block_lost"}
        assert "유의사항" in lost

    def test_the_second_date_seat_keeps_auto_out_of_final(self, blank_jeongbo):
        """Documented boundary: 정보공개 청구서's 접수증 block carries its own
        년 월 일 that the applicant must not fill, so auto stays at draft."""
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(blank_jeongbo)
        seats = sum(cm._count(vocabulary["unfilled_date_seat_re"], text)
                    for _at, text in cm.iter_seats(model))
        assert seats == 2
