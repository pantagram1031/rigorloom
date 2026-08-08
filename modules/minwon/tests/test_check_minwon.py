# -*- coding: utf-8 -*-
"""Per-rule tests for check_minwon over the synthetic 민원 서식 fixture.

Every rule gets both halves: a positive fixture where the violation is present,
and a still-catches negative proving the rule is not a tautology — the same
document with the violation removed passes. The fixture spec makes those two
differ by exactly one key, so a test that stops discriminating is visible as a
one-line diff rather than as a green suite.

The corpus regression lives in ``test_corpus_minwon.py``; this file is about
mechanism.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MODULE_ROOT = _HERE.parent
_REPO_ROOT = _MODULE_ROOT.parents[1]
for _dir in (_MODULE_ROOT / "scripts", _REPO_ROOT / "pipeline" / "scripts",
             _REPO_ROOT / "engine" / "scripts", _HERE):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import check_minwon as cm  # noqa: E402
import minwon_fixtures as fx  # noqa: E402

EXIT_PASS, EXIT_USAGE, EXIT_HARD = 0, 2, 3


def codes(verdict, bucket="hard") -> set:
    return {row["code"] for row in verdict[bucket]}


def reasons(verdict) -> dict:
    return {row["rule"]: row["reason"] for row in verdict["skipped"]}


@pytest.fixture()
def blank(tmp_path):
    """The pristine 별지서식 — also the baseline every preservation rule needs."""
    return fx.write_minwon(tmp_path / "blank.hwpx", fx.BLANK)


@pytest.fixture()
def filled(tmp_path):
    """A correctly completed 신청서."""
    return fx.write_minwon(tmp_path / "filled.hwpx", fx.FILLED)


def broken(tmp_path, name, **overrides):
    """``FILLED`` with one thing wrong."""
    return fx.write_minwon(tmp_path / f"{name}.hwpx", fx.FILLED, **overrides)


# --------------------------------------------------------------------------- #
# R0 — inputs and structure
# --------------------------------------------------------------------------- #
class TestInputs:
    def test_missing_artifact_is_hard_not_a_silent_pass(self, tmp_path):
        verdict, code = cm.check(tmp_path / "nope.hwpx")
        assert code == EXIT_HARD
        assert "artifact_missing" in codes(verdict)

    def test_non_zip_is_a_usage_refusal(self, tmp_path):
        path = tmp_path / "plain.hwpx"
        path.write_text("not a zip", encoding="utf-8")
        _verdict, code = cm.check(path)
        assert code == EXIT_USAGE

    def test_malformed_section_is_hard_and_stops_structure_checks(self, tmp_path):
        path = fx.write_minwon(tmp_path / "bad.hwpx", fx.FILLED, malformed=True)
        verdict, code = cm.check(path)
        assert code == EXIT_HARD
        assert codes(verdict) == {"artifact_malformed"}

    def test_a_document_that_is_not_a_minwon_form_is_refused(self, tmp_path):
        path = fx.write_not_a_minwon(tmp_path / "report.hwpx")
        verdict, code = cm.check(path)
        assert code == EXIT_HARD
        assert "minwon_structure_absent" in codes(verdict)

    def test_bad_mode_is_a_usage_refusal(self, blank):
        _verdict, code = cm.check(blank, mode="whenever")
        assert code == EXIT_USAGE

    def test_unreadable_vocabulary_is_a_usage_refusal(self, blank, tmp_path):
        bad = tmp_path / "vocab.json"
        bad.write_text('{"schema": "wrong/v9"}', encoding="utf-8")
        _verdict, code = cm.check(blank, vocabulary=bad)
        assert code == EXIT_USAGE

    def test_the_checker_never_writes_to_its_input(self, filled, blank):
        before = filled.read_bytes()
        cm.check(filled, baseline=blank)
        assert filled.read_bytes() == before


# --------------------------------------------------------------------------- #
# document state
# --------------------------------------------------------------------------- #
class TestDocumentState:
    def test_pristine_form_is_blank_and_is_reported_not_failed(self, blank):
        verdict, code = cm.check(blank)
        assert code == EXIT_PASS
        assert verdict["document"]["state"] == "blank"
        assert verdict["document"]["marked_checkboxes"] == 0
        assert verdict["document"]["unfilled_date_seats"] >= 1
        assert reasons(verdict)["checkbox_selection_absent"] == \
            "document_state_blank"

    def test_a_dated_filled_form_is_final(self, filled):
        verdict, _code = cm.check(filled)
        assert verdict["document"]["state"] == "final"
        assert verdict["document"]["unfilled_date_seats"] == 0

    def test_written_but_undated_is_draft(self, tmp_path, blank):
        path = broken(tmp_path, "undated", date_row=fx.BLANK["date_row"])
        verdict, _code = cm.check(path, baseline=blank)
        assert verdict["document"]["state"] == "draft"

    def test_생년월일_is_not_mistaken_for_an_unfilled_date_seat(self, filled):
        """'생년월일' contains '년월일'. Without the lookbehind every form with a
        birthdate label would read as undated forever."""
        verdict, _code = cm.check(filled)
        assert verdict["document"]["unfilled_date_seats"] == 0
        assert cm._contains(cm.haystack(cm.document_model(filled)), "생년월일")

    def test_mode_forces_the_state(self, blank):
        verdict, _code = cm.check(blank, mode="final")
        assert verdict["document"]["state"] == "blank"
        assert verdict["document"]["state_used"] == "final"


# --------------------------------------------------------------------------- #
# R1 — the 별지서식's own frame
# --------------------------------------------------------------------------- #
class TestFurniture:
    def test_correct_fill_keeps_the_whole_frame(self, filled, blank):
        verdict, code = cm.check(filled, baseline=blank)
        assert code == EXIT_PASS, verdict["hard"]
        seats = {(row.get("seat"), row.get("state")) for row in verdict["seats"]}
        assert ("byeolji_header", "present") in seats
        assert ("paper_spec_footer", "present") in seats
        assert ("addressee_line", "present") in seats

    def test_lost_byeolji_header_is_hard(self, tmp_path, blank):
        path = broken(tmp_path, "noheader", form_header="민원 신청")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        assert "byeolji_header_lost" in codes(verdict)

    def test_lost_paper_spec_footer_is_hard(self, tmp_path, blank):
        path = broken(tmp_path, "nofooter", paper_spec="")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        assert "paper_spec_footer_lost" in codes(verdict)

    def test_lost_addressee_line_is_hard(self, tmp_path, blank):
        path = broken(tmp_path, "noaddr", addressee="(접수 기관의 장)")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        assert "addressee_line_lost" in codes(verdict)

    def test_replacing_the_addressee_guide_term_is_correct_not_a_defect(
            self, tmp_path, blank):
        """Still-catches boundary: '(접수 기관의 장) 귀하' → '국가유산청장 귀하' is
        exactly what an agent SHOULD do, and it must not read as destruction."""
        path = broken(tmp_path, "addrok", addressee="국가유산청장 귀하")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_PASS, verdict["hard"]

    def test_without_a_baseline_the_frame_rules_say_so(self, filled):
        verdict, code = cm.check(filled)
        assert code == EXIT_PASS
        assert reasons(verdict)["byeolji_header_lost"] == "no_baseline"
        assert reasons(verdict)["paper_spec_footer_lost"] == "no_baseline"
        assert reasons(verdict)["addressee_line_lost"] == "no_baseline"

    def test_a_document_with_no_header_at_all_warns_without_a_baseline(
            self, tmp_path):
        path = broken(tmp_path, "headerless", form_header="민원 신청")
        verdict, code = cm.check(path)
        assert code == EXIT_PASS
        assert "byeolji_header_lost" in codes(verdict, "warn")
        assert verdict["warn"][0]["basis"] == "artifact_only"


# --------------------------------------------------------------------------- #
# R2 — 접수(처리) 기관 seats
# --------------------------------------------------------------------------- #
class TestStaffSeats:
    def test_correct_fill_leaves_the_staff_block_untouched(self, filled, blank):
        verdict, code = cm.check(filled, baseline=blank)
        assert code == EXIT_PASS, verdict["hard"]
        untouched = [row for row in verdict["seats"]
                     if row.get("seat") == "staff"]
        assert len(untouched) >= 3
        assert all(row["state"] == "untouched" for row in untouched)

    def test_writing_into_a_staff_seat_is_hard(self, tmp_path, blank):
        path = broken(tmp_path, "staff", jeopsu_number="접수번호 2026-1234")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        finding = next(row for row in verdict["hard"]
                       if row["code"] == "staff_seat_filled")
        assert "label" in finding["basis"]
        assert finding["labels"] == ["접수번호"]

    def test_deleting_a_staff_seat_is_hard(self, tmp_path, blank):
        path = broken(tmp_path, "staffgone", drop_chori_period=True)
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        assert "staff_seat_removed" in codes(verdict)

    def test_the_shaded_recognizer_needs_the_forms_own_declaration(
            self, tmp_path):
        """A shaded cell only means staff-only where the form says so. Drop the
        declaration and the shading-only seats stop being staff seats."""
        vocabulary = cm.load_vocabulary()
        with_declaration = cm.document_model(
            fx.write_minwon(tmp_path / "decl.hwpx", fx.BLANK))
        without = cm.document_model(fx.write_minwon(
            tmp_path / "nodecl.hwpx", fx.BLANK, shading_declaration=""))
        assert cm.declares_shading_rule(with_declaration, vocabulary) is True
        assert cm.declares_shading_rule(without, vocabulary) is False
        # the label-anchored seats survive either way — that is the point of
        # having two independent recognizers
        assert cm.staff_seats(without, vocabulary)

    def test_a_light_tint_is_not_a_staff_seat(self, tmp_path):
        """#F2F2F2 (0.949) sits above the declared threshold: the 수수료 row is
        shaded and the applicant fills it."""
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(fx.write_minwon(tmp_path / "tint.hwpx"))
        shaded_only = [seat for seat in cm.staff_seats(model, vocabulary)
                       if seat["basis"] == ["shaded"]]
        for seat in shaded_only:
            assert seat["face_brightness"] <= \
                vocabulary["shaded_face_max_brightness"]
        assert not any(cm._contains(seat["text"], "수수료")
                       for seat in cm.staff_seats(model, vocabulary))

    def test_marking_a_checkbox_in_a_shaded_cell_is_not_a_staff_write(
            self, tmp_path, blank):
        """The trap 주민등록 등초본 신청서 sets: a #B2B2B2 instruction block that
        CARRIES the boxes the applicant must mark."""
        vocabulary = cm.load_vocabulary()
        model = cm.document_model(blank)
        for seat in cm.staff_seats(model, vocabulary):
            if "label" in seat["basis"]:
                continue
            assert not cm._findall(vocabulary["unmarked_glyph_re"],
                                   seat["text"])

    def test_without_a_baseline_the_staff_rules_say_so(self, filled):
        verdict, _code = cm.check(filled)
        assert reasons(verdict)["staff_seat_filled"] == "no_baseline"


# --------------------------------------------------------------------------- #
# R3 — 선택 항목
# --------------------------------------------------------------------------- #
class TestSelect:
    def test_a_final_document_with_no_selection_is_hard(self, tmp_path, blank):
        path = broken(tmp_path, "nosel", select_row=fx.BLANK["select_row"],
                      copies_row=fx.BLANK["copies_row"])
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        finding = next(row for row in verdict["hard"]
                       if row["code"] == "checkbox_selection_absent")
        assert finding["instruction_declared"] is True

    def test_without_the_forms_instruction_an_unmarked_final_only_warns(
            self, tmp_path):
        """Severity comes from the form's own words. No '√표를 합니다' line, no
        HARD — some groups are conditional and the form never said otherwise."""
        blank = fx.write_minwon(tmp_path / "b.hwpx", fx.BLANK,
                                select_instruction="")
        path = fx.write_minwon(tmp_path / "a.hwpx", fx.FILLED,
                               select_instruction="",
                               select_row=fx.BLANK["select_row"],
                               copies_row=fx.BLANK["copies_row"])
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_PASS
        assert "checkbox_selection_absent" in codes(verdict, "warn")

    def test_a_blank_form_is_not_failed_for_having_no_selection(self, blank):
        verdict, code = cm.check(blank, baseline=blank)
        assert code == EXIT_PASS
        assert reasons(verdict)["checkbox_selection_absent"] == \
            "document_state_blank"

    def test_deleting_an_option_is_hard(self, tmp_path, blank):
        path = broken(tmp_path, "optgone",
                      select_row="[√]열람ㆍ시청 [ ]사본ㆍ출력물")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        finding = next(row for row in verdict["hard"]
                       if row["code"] == "checkbox_option_lost")
        assert finding["artifact"] < finding["baseline"]

    def test_marking_a_box_keeps_the_slot_count(self, filled, blank):
        """[ ] → [√] must not read as a deleted option; that is the whole reason
        the rule counts slots instead of unmarked glyphs."""
        verdict, code = cm.check(filled, baseline=blank)
        assert code == EXIT_PASS, verdict["hard"]
        assert "checkbox_option_lost" not in codes(verdict)

    def test_deleting_every_option_is_still_caught(self, tmp_path, blank):
        """The gap the rule ordering has to avoid: with no boxes left in the
        artifact there is nothing to iterate, and that is the WORST case of
        option loss, not a reason to skip."""
        path = broken(tmp_path, "allgone", select_row="열람ㆍ시청 사본ㆍ출력물",
                      copies_row="교부 1통",
                      fee_row="수수료 감면 대상 아님",
                      select_instruction="")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        assert "checkbox_option_lost" in codes(verdict)
        # nothing left to iterate in the artifact, and the rule still bit
        assert reasons(verdict).get("checkbox_selection_absent") == \
            "seat_absent"
        assert len([row for row in verdict["hard"]
                    if row["code"] == "checkbox_option_lost"]) >= 3

    def test_a_form_with_no_selection_at_all_reports_seat_absent(self, tmp_path):
        blank = fx.write_minwon(
            tmp_path / "b.hwpx", fx.BLANK, select_row="열람ㆍ시청",
            copies_row="교부 1통", fee_row="수수료 감면 대상 아님",
            select_instruction="")
        verdict, code = cm.check(blank, baseline=blank)
        assert code == EXIT_PASS
        assert reasons(verdict)["checkbox_option_lost"] == "seat_absent"

    def test_a_numeric_slot_fill_keeps_the_slot_count(self, tmp_path, blank):
        """'교부 [ ]통' is a numeric field wearing the checkbox glyph; '[1]통' is
        a consumed slot, not a deleted option."""
        path = broken(tmp_path, "num", copies_row="교부 [12]통")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_PASS, verdict["hard"]


# --------------------------------------------------------------------------- #
# R4 — the seats a person completes by hand
# --------------------------------------------------------------------------- #
class TestHumanSeats:
    def test_correct_fill_reserves_signature_and_seal(self, filled, blank):
        verdict, code = cm.check(filled, baseline=blank)
        assert code == EXIT_PASS, verdict["hard"]
        seats = {(row.get("seat"), row.get("state")) for row in verdict["seats"]}
        assert ("signature", "reserved") in seats
        assert ("seal", "reserved") in seats

    def test_deleting_a_signature_marker_in_a_cell_is_hard(self, tmp_path,
                                                          blank):
        path = broken(tmp_path, "nosig", name_value="")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        finding = next(row for row in verdict["hard"]
                       if row["code"] == "signature_marker_lost")
        assert finding["at"]["addr"] == [4, 3]

    def test_deleting_a_signature_marker_in_a_paragraph_is_hard(self, tmp_path,
                                                               blank):
        """행정규칙 서식 keeps its signature seats in top-level paragraphs, which
        have no stable address — so that domain is compared by COUNT."""
        path = broken(tmp_path, "noparasig",
                      paragraph_confirmer="확인자 : 부서장")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        finding = next(row for row in verdict["hard"]
                       if row["code"] == "signature_marker_lost")
        assert finding["basis"] == "paragraph_count"

    def test_writing_the_applicants_name_beside_the_marker_is_allowed(
            self, tmp_path, blank):
        """Still-catches boundary: in 주민등록 등초본 신청서 the 성명 value shares
        the cell with '(서명 또는 인)'. The MARKER must survive, not the cell."""
        path = broken(tmp_path, "signame", name_value="김도현 (서명 또는 인)")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_PASS, verdict["hard"]

    def test_writing_into_the_seal_slot_is_hard(self, tmp_path, blank):
        path = broken(tmp_path, "seal", seal="직인 김도현")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        assert "seal_seat_overwritten" in codes(verdict)

    def test_deleting_the_seal_slot_is_hard(self, tmp_path, blank):
        path = broken(tmp_path, "sealgone", seal=None)
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        assert "seal_seat_overwritten" in codes(verdict)


# --------------------------------------------------------------------------- #
# R5 — the printed guide blocks
# --------------------------------------------------------------------------- #
class TestGuideBlocks:
    def test_correct_fill_keeps_every_guide_block(self, filled, blank):
        verdict, code = cm.check(filled, baseline=blank)
        assert code == EXIT_PASS, verdict["hard"]
        kept = {row["label"] for row in verdict["seats"]
                if row.get("seat") == "guide_block"}
        assert {"유의사항", "수수료", "제출서류", "작성방법"} <= kept

    @pytest.mark.parametrize("overrides,label", [
        ({"guide_header": "", "guide_body": "1. 서류를 준비하세요."}, "유의사항"),
        ({"fee_row": "[ ]감면 대상임 [ ]감면 대상 아님"}, "수수료"),
        ({"guide_body": "1. 3쪽의 안내를 읽으세요."}, "제출서류"),
    ])
    def test_deleting_a_guide_block_is_hard(self, tmp_path, blank, overrides,
                                           label):
        path = broken(tmp_path, "guide", **overrides)
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        lost = {row["at"] for row in verdict["hard"]
                if row["code"] == "guide_block_lost"}
        assert label in lost

    def test_this_is_the_inverse_of_the_gongmun_residue_rule(self, filled,
                                                            blank):
        """A 민원 서식 has no guide vocabulary to CONSUME. The finished document
        still contains its printed instruction lines, and that is correct."""
        verdict, code = cm.check(filled, baseline=blank)
        assert code == EXIT_PASS
        text = cm.haystack(cm.document_model(filled))
        assert cm._contains(text, fx.SELECT_INSTRUCTION)
        assert cm._contains(text, fx.SHADING_DECLARATION)

    def test_without_a_baseline_the_guide_rule_says_so(self, filled):
        verdict, _code = cm.check(filled)
        assert reasons(verdict)["guide_block_lost"] == "no_baseline"


# --------------------------------------------------------------------------- #
# R6 — the privacy rule
# --------------------------------------------------------------------------- #
class TestIdentity:
    def test_an_undeclared_rrn_is_hard_without_any_baseline(self, tmp_path):
        """The one rule that must never be gated behind an input the caller can
        forget: if nothing declared the number, its presence IS the finding."""
        path = broken(tmp_path, "rrn", rrn_value="900101-1234567")
        verdict, code = cm.check(path)
        assert code == EXIT_HARD
        finding = next(row for row in verdict["hard"]
                       if row["code"] == "identity_value_invented")
        assert finding["shape"] == "rrn"
        assert finding["declared_values"] == 0

    def test_a_declared_rrn_passes(self, tmp_path, blank):
        path = broken(tmp_path, "rrnok", rrn_value="900101-1234567")
        fill_map = fx.write_fill_map(
            tmp_path / "fill.json", {"주민등록번호": "주민등록번호 900101-1234567"})
        verdict, code = cm.check(path, baseline=blank, fill_map=fill_map)
        assert code == EXIT_PASS, verdict["hard"]
        assert any(row.get("seat") == "identity_value"
                   and row["state"] == "declared" for row in verdict["seats"])

    def test_a_blank_form_reports_no_identity_value_present(self, blank):
        verdict, code = cm.check(blank, baseline=blank)
        assert code == EXIT_PASS
        assert any(row.get("seat") == "identity_value"
                   and row["state"] == "none_present" for row in verdict["seats"])

    def test_filling_an_in_cell_identity_seat_undeclared_is_hard(self, tmp_path,
                                                                blank):
        path = broken(tmp_path, "idcell", rrn_value="900101-1234567")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        finding = next(row for row in verdict["hard"]
                       if row["code"] == "identity_seat_autofilled")
        assert finding["slot"] == "own_cell"

    def test_filling_a_neighbouring_identity_seat_undeclared_is_hard(
            self, tmp_path, blank):
        """행정규칙 가족돌봄 서식's topology: '생년월일' label, value in the cell
        to its right."""
        path = broken(tmp_path, "idright", birth_value="1990. 1. 1.")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        finding = next(row for row in verdict["hard"]
                       if row["code"] == "identity_seat_autofilled")
        assert finding["slot"] == "right"
        assert finding["labels"] == ["생년월일"]

    def test_a_declared_birthdate_passes(self, tmp_path, blank):
        path = broken(tmp_path, "idrightok", birth_value="1990. 1. 1.")
        fill_map = fx.write_fill_map(tmp_path / "fill.json",
                                     {"생년월일": "1990. 1. 1."})
        verdict, code = cm.check(path, baseline=blank, fill_map=fill_map)
        assert code == EXIT_PASS, verdict["hard"]

    def test_prose_mentioning_an_identity_label_is_not_a_seat(self, tmp_path):
        """The false positive this discriminator exists for: a long instruction
        block that MENTIONS 생년월일 and carries the boxes the applicant marks."""
        vocabulary = cm.load_vocabulary()
        prose = ("※ 포함 여부를 선택하지 않을 경우 신청인 또는 교부 대상자의 성명, "
                 "생년월일, 주소 등 기본적인 사항만 제공됩니다. [ ]등본 사항 전부 "
                 "포함 [ ]초본 사항 전부 포함")
        blank = fx.write_minwon(tmp_path / "b.hwpx", fx.BLANK, guide_body=prose)
        seats = cm.identity_seats(cm.document_model(blank), vocabulary)
        assert not any(cm._contains(seat["text"], "기본적인")
                       for seat in seats)

    def test_marking_a_checkbox_in_such_prose_is_not_an_identity_autofill(
            self, tmp_path):
        prose_blank = ("※ 대상자의 성명, 생년월일, 주소 등 기본적인 사항만 "
                       "제공됩니다. [ ]등본 사항 전부 포함")
        prose_filled = prose_blank.replace("[ ]등본", "[√]등본")
        blank = fx.write_minwon(tmp_path / "b.hwpx", fx.BLANK,
                                guide_body=prose_blank)
        path = fx.write_minwon(tmp_path / "a.hwpx", fx.FILLED,
                               guide_body=prose_filled)
        verdict, code = cm.check(path, baseline=blank)
        assert "identity_seat_autofilled" not in codes(verdict), verdict["hard"]
        assert code == EXIT_PASS, verdict["hard"]

    def test_without_a_baseline_the_seat_rule_says_so_but_the_shape_rule_runs(
            self, filled):
        verdict, code = cm.check(filled)
        assert code == EXIT_PASS
        assert reasons(verdict)["identity_seat_autofilled"] == "no_baseline"
        assert "identity_value_invented" not in reasons(verdict)

    def test_a_malformed_fill_map_is_a_usage_refusal(self, filled, tmp_path):
        bad = tmp_path / "fill.json"
        bad.write_text('{"a": ["list"]}', encoding="utf-8")
        _verdict, code = cm.check(filled, fill_map=bad)
        assert code == EXIT_USAGE


# --------------------------------------------------------------------------- #
# R7 — ○ placeholder runs
# --------------------------------------------------------------------------- #
class TestPlaceholderGlyphs:
    def test_surviving_glyph_run_in_a_final_document_is_hard(self, tmp_path,
                                                            blank):
        path = broken(tmp_path, "glyph",
                      paragraph_applicant="신청인 : ○○○ (인)")
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_HARD
        assert "placeholder_glyphs_retained" in codes(verdict)

    def test_a_draft_only_warns(self, tmp_path, blank):
        path = broken(tmp_path, "glyphdraft",
                      paragraph_applicant="신청인 : ○○○ (인)",
                      date_row=fx.BLANK["date_row"])
        verdict, code = cm.check(path, baseline=blank)
        assert code == EXIT_PASS
        assert "placeholder_glyphs_retained" in codes(verdict, "warn")

    def test_a_blank_form_is_not_failed_for_carrying_its_own_placeholder(
            self, blank):
        verdict, code = cm.check(blank, baseline=blank)
        assert code == EXIT_PASS
        assert reasons(verdict)["placeholder_glyphs_retained"] == \
            "document_state_blank"


# --------------------------------------------------------------------------- #
# the verdict shape and the baseline declaration
# --------------------------------------------------------------------------- #
class TestVerdictShape:
    def test_a_baseline_leaves_nothing_undecided(self, filled, blank):
        """``wants: [baseline]`` is only honest if supplying one removes every
        no_baseline skip. If it stopped doing that, the declaration is a lie."""
        without, _code = cm.check(filled)
        undecided = {row["rule"] for row in without["skipped"]
                     if row["reason"] == "no_baseline"}
        assert len(undecided) >= 9, undecided
        with_baseline, _code = cm.check(filled, baseline=blank)
        assert {row["rule"] for row in with_baseline["skipped"]
                if row["reason"] == "no_baseline"} == set()

    def test_counts_agree_with_the_lists(self, filled, blank):
        verdict, _code = cm.check(filled, baseline=blank)
        assert verdict["counts"]["hard"] == len(verdict["hard"])
        assert verdict["counts"]["warn"] == len(verdict["warn"])
        assert verdict["counts"]["seats"] == len(verdict["seats"])
        assert verdict["counts"]["skipped"] == len(verdict["skipped"])

    def test_the_verdict_is_strict_json_over_the_cli(self, filled, blank,
                                                    tmp_path, capsys):
        out = tmp_path / "verdict.json"
        code = cm.main([str(filled), "--baseline", str(blank),
                        "--out", str(out)])
        assert code == EXIT_PASS
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["checker"] == "check_minwon"
        assert payload["verdict"] == "pass"
        capsys.readouterr()

    def test_the_cli_reports_a_hard_finding_with_exit_3(self, tmp_path, blank,
                                                       capsys):
        path = broken(tmp_path, "cli", jeopsu_number="접수번호 9")
        code = cm.main([str(path), "--baseline", str(blank)])
        assert code == EXIT_HARD
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False


# --------------------------------------------------------------------------- #
# the document model itself
# --------------------------------------------------------------------------- #
class TestDocumentModel:
    def test_xml_entities_are_unescaped(self, blank):
        """The 별지서식 header is stored as '&lt;개정 2026. 1. 1.&gt;'. A rule that
        reads it must see the characters."""
        text = cm.haystack(cm.document_model(blank))
        assert "<개정" in text
        assert "&lt;" not in text

    def test_nested_box_text_is_not_absorbed_by_its_holder(self, blank):
        model = cm.document_model(blank)
        holders = [cell for _at, cell, table in cm.iter_cells(model)
                   if table["depth"] == 0 and cell["addr"] == [9, 5]]
        assert holders and "직인" not in holders[0]["text"]
        nested = [cell for _at, cell, table in cm.iter_cells(model)
                  if table["depth"] >= 1]
        assert any("직인" in cell["text"] for cell in nested)

    def test_shading_is_read_from_the_header_borderfills(self, blank):
        model = cm.document_model(blank)
        by_addr = cm.addressed_cells(model)
        assert by_addr[(0, (3, 0))]["face_brightness"] == pytest.approx(
            178 / 255, abs=1e-6)
        assert by_addr[(0, (7, 0))]["face_brightness"] == pytest.approx(
            242 / 255, abs=1e-6)
        assert by_addr[(0, (4, 0))]["face_brightness"] is None

    def test_letter_spaced_labels_still_match(self, tmp_path):
        """The 서식 letter-spaces its own headings ('유 의 사 항')."""
        blank = fx.write_minwon(tmp_path / "b.hwpx", fx.BLANK)
        text = cm.haystack(cm.document_model(blank))
        assert cm._contains(text, "유의사항")

    def test_brightness_parses_both_hex_widths_and_rejects_none(self):
        assert cm._brightness("#000000") == 0.0
        assert cm._brightness("#FFFFFF") == 1.0
        assert cm._brightness("#FF000000") == 0.0
        assert cm._brightness("none") is None
        assert cm._brightness(None) is None
        assert cm._brightness("#12") is None

    def test_the_model_reads_every_section_member(self, tmp_path):
        path = fx.write_minwon(tmp_path / "two.hwpx", fx.BLANK)
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("Contents/section1.xml",
                             archive.read("Contents/section0.xml"))
        model = cm.document_model(path)
        assert len({table["section"] for table in model["tables"]}) == 2
