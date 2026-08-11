# -*- coding: utf-8 -*-
"""Rule-by-rule tests for check_gongmun.

Every rule gets BOTH halves of the pair the calibration policy demands:

* a **positive fixture** — the violation is present and the rule catches it;
* a **still-catches negative** — a legitimately finished 공문 that must NOT be
  flagged, so a future loosening of the rule cannot pass by silently accepting
  everything.

Fixtures are synthetic 기안문 documents shaped like the corpus 별지 제1호서식
(see ``gongmun_fixtures.py``); the corpus forms themselves are exercised by
``test_corpus_gongmun.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MODULE_ROOT = _HERE.parent
for _dir in (_MODULE_ROOT / "scripts", _HERE):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import check_gongmun  # noqa: E402
import gongmun_fixtures as fx  # noqa: E402


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def codes(verdict: dict, bucket: str = "hard") -> set[str]:
    return {row["code"] for row in verdict[bucket]}


def skipped_rules(verdict: dict) -> dict[str, str]:
    return {row["rule"]: row["reason"] for row in verdict["skipped"]}


def run(path: Path, **kwargs):
    return check_gongmun.check(path, **kwargs)


@pytest.fixture()
def blank(tmp_path):
    return fx.write_gongmun(tmp_path / "blank.hwpx", fx.BLANK)


@pytest.fixture()
def finished(tmp_path):
    return fx.write_gongmun(tmp_path / "finished.hwpx", fx.FINISHED)


# --------------------------------------------------------------------------- #
# the two anchors: a blank form is not a failed 공문; a finished one is clean
# --------------------------------------------------------------------------- #
class TestDocumentState:
    def test_blank_form_reports_the_unfilled_shape_and_passes(self, blank):
        verdict, code = run(blank)
        assert code == 0 and verdict["ok"] is True
        assert verdict["document"]["state"] == "blank"
        states = {row.get("state") for row in verdict["seats"]}
        assert "blank_by_design" in states
        assert "unfilled" in states
        # finishing rules cannot apply to a form nobody has filled yet
        assert skipped_rules(verdict)["guide_vocabulary_residue"] == \
            "document_state_blank"

    def test_finished_gongmun_is_clean(self, finished):
        verdict, code = run(finished)
        assert code == 0, verdict["hard"]
        assert verdict["document"]["state"] == "final"
        assert verdict["hard"] == []

    def test_partially_filled_form_is_a_draft(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "draft.hwpx", fx.FINISHED,
                                bigo=True)
        verdict, _code = run(path)
        assert verdict["document"]["state"] == "draft"

    def test_mode_forces_the_state(self, blank):
        verdict, code = run(blank, mode="final")
        assert verdict["document"]["state_used"] == "final"
        assert code == 3
        assert "guide_vocabulary_residue" in codes(verdict)

    def test_unknown_mode_is_a_usage_error(self, blank):
        verdict, code = run(blank, mode="whatever")
        assert code == 2 and verdict["verdict"] == "usage_error"


# --------------------------------------------------------------------------- #
# R0 — preconditions
# --------------------------------------------------------------------------- #
class TestPreconditions:
    def test_missing_artifact_is_hard_never_a_silent_pass(self, tmp_path):
        verdict, code = run(tmp_path / "absent.hwpx")
        assert code == 3
        assert codes(verdict) == {"artifact_missing"}

    def test_present_artifact_does_not_trip_the_missing_rule(self, finished):
        verdict, _code = run(finished)
        assert "artifact_missing" not in codes(verdict)

    def test_malformed_section_is_hard_and_skips_the_text_rules(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "broken.hwpx", fx.FINISHED,
                                malformed=True)
        verdict, code = run(path)
        assert code == 3
        assert codes(verdict) == {"artifact_malformed"}

    def test_wellformed_section_is_not_reported_malformed(self, finished):
        verdict, _code = run(finished)
        assert "artifact_malformed" not in codes(verdict)

    def test_non_gongmun_document_is_refused(self, tmp_path):
        path = fx.write_not_a_gongmun(tmp_path / "report.hwpx")
        verdict, code = run(path)
        assert code == 3
        assert codes(verdict) == {"gongmun_structure_absent"}

    def test_gongmun_document_is_recognized(self, blank):
        verdict, _code = run(blank)
        assert "gongmun_structure_absent" not in codes(verdict)
        assert set(verdict["document"]["families"]) == {
            "dumun", "gyeoljae", "gyeolmun", "balsin", "seal"}

    def test_non_hwpx_input_is_a_usage_error(self, tmp_path):
        path = tmp_path / "plain.txt"
        path.write_text("수신 제목", encoding="utf-8")
        verdict, code = run(path)
        assert code == 2 and verdict["verdict"] == "usage_error"


# --------------------------------------------------------------------------- #
# R1 — 두문
# --------------------------------------------------------------------------- #
class TestDumun:
    def test_deleted_label_is_caught_against_the_blank_form(self, tmp_path,
                                                            blank):
        path = fx.write_gongmun(tmp_path / "no_susin.hwpx", fx.FINISHED,
                                susin=None)
        verdict, code = run(path, baseline=blank)
        assert code == 3
        assert "dumun_label_missing" in codes(verdict)

    def test_intact_frame_is_not_flagged(self, finished, blank):
        verdict, _code = run(finished, baseline=blank)
        assert "dumun_label_missing" not in codes(verdict)

    def test_label_absence_without_a_baseline_is_skipped_not_guessed(
            self, tmp_path):
        # 별지 제2호서식 legitimately has no 수신 seat: absence alone is not
        # destruction, so the rule refuses to decide without the blank form.
        path = fx.write_gongmun(tmp_path / "no_susin.hwpx", fx.FINISHED,
                                susin=None)
        verdict, _code = run(path)
        assert skipped_rules(verdict)["dumun_label_missing"] == "no_baseline"
        assert "dumun_label_missing" not in codes(verdict)

    def test_required_label_without_a_value_is_hard_in_a_final_document(
            self, tmp_path):
        path = fx.write_gongmun(tmp_path / "empty_susin.hwpx", fx.FINISHED,
                                susin="수신")
        verdict, code = run(path)
        assert code == 3
        assert "dumun_seat_unfilled" in codes(verdict)

    def test_filled_labels_are_not_flagged(self, finished):
        verdict, _code = run(finished)
        assert "dumun_seat_unfilled" not in codes(verdict)

    def test_agency_term_beside_the_value_is_half_filled(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "half.hwpx", fx.FINISHED,
                                agency="행 정 기 관 명 국가유산청")
        verdict, code = run(path)
        assert code == 3
        assert "dumun_seat_half_filled" in codes(verdict)

    def test_replaced_agency_name_is_not_half_filled(self, finished):
        verdict, _code = run(finished)
        assert "dumun_seat_half_filled" not in codes(verdict)


# --------------------------------------------------------------------------- #
# R2 — 결재란
# --------------------------------------------------------------------------- #
class TestGyeoljae:
    def test_partly_consumed_seat_is_half_filled(self, tmp_path):
        path = fx.write_gongmun(
            tmp_path / "half_seat.hwpx", fx.FINISHED,
            approvers=["기안자 주무관 홍길동", "검토자  직위(직급) 서명",
                       "결재권자  직위(직급) 서명"])
        verdict, code = run(path)
        assert code == 3
        assert "gyeoljae_seat_half_filled" in codes(verdict)

    def test_row_mixing_filled_and_blank_seats_is_caught(self, tmp_path):
        path = fx.write_gongmun(
            tmp_path / "half_row.hwpx", fx.FINISHED,
            approvers=["주무관 홍길동", "검토자  직위(직급) 서명",
                       "결재권자  직위(직급) 서명"])
        verdict, code = run(path)
        assert code == 3
        assert "gyeoljae_row_half_filled" in codes(verdict)
        assert "gyeoljae_seat_half_filled" not in codes(verdict)

    def test_fully_blank_row_is_blank_by_design(self, blank):
        verdict, code = run(blank)
        assert code == 0
        assert "gyeoljae_row_half_filled" not in codes(verdict)
        assert "gyeoljae_seat_half_filled" not in codes(verdict)

    def test_fully_filled_row_is_clean(self, finished):
        verdict, _code = run(finished)
        assert not codes(verdict) & {"gyeoljae_row_half_filled",
                                     "gyeoljae_seat_half_filled"}

    def test_absent_gyeoljae_is_skipped_not_passed(self, finished):
        # a finished 결재란 carries no role term, so the per-seat rule cannot
        # locate it — that must be visible, not silent.
        verdict, _code = run(finished)
        assert skipped_rules(verdict)["gyeoljae"] == "seat_absent"


# --------------------------------------------------------------------------- #
# R3 — 결문
# --------------------------------------------------------------------------- #
class TestGyeolmun:
    def test_guide_term_beside_a_value_is_half_filled(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "half_doro.hwpx", fx.FINISHED,
                                doro="도로명주소 서울특별시 종로구 삼봉로 81")
        verdict, code = run(path)
        assert code == 3
        assert "gyeolmun_seat_half_filled" in codes(verdict)

    def test_replaced_address_is_clean(self, finished):
        verdict, _code = run(finished)
        assert "gyeolmun_seat_half_filled" not in codes(verdict)

    def test_issue_number_off_the_regulated_shape_is_caught(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "bad_number.hwpx", fx.FINISHED,
                                siheng_value="2026년 8월 20일 발송")
        verdict, code = run(path)
        assert code == 3
        assert "gyeolmun_issue_number_malformed" in codes(verdict)

    def test_regulated_issue_number_is_accepted(self, finished):
        verdict, _code = run(finished)
        assert "gyeolmun_issue_number_malformed" not in codes(verdict)
        values = [row for row in verdict["seats"]
                  if row.get("seat") == "gyeolmun_issue"]
        assert values and values[0]["value"].startswith("문화유산정책과-1234")

    def test_unconsumed_gyeolmun_seat_is_a_warning_not_a_block(self, tmp_path):
        # a 공문 may legitimately ship with no 접수 numbering
        path = fx.write_gongmun(tmp_path / "gonggae.hwpx", fx.FINISHED,
                                jeopsu_value="처리과명-연도별 일련번호(접수일)")
        verdict, _code = run(path)
        assert "gyeolmun_seat_unfilled" in codes(verdict, "warn")


# --------------------------------------------------------------------------- #
# R4 — 발신명의
# --------------------------------------------------------------------------- #
class TestBalsinMyeongui:
    def test_unreplaced_term_is_hard_in_a_final_document(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "balsin.hwpx", fx.FINISHED,
                                balsin="발신명의")
        verdict, code = run(path)
        assert code == 3
        assert "balsin_myeongui_unfilled" in codes(verdict)

    def test_glyph_placeholder_issuer_is_unfilled(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "glyphs.hwpx", fx.FINISHED,
                                balsin="○○○○부(처ㆍ청 또는 위원회 등)")
        verdict, code = run(path)
        assert code == 3
        assert "balsin_myeongui_unfilled" in codes(verdict)

    def test_missing_issuer_line_is_hard(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "no_balsin.hwpx", fx.FINISHED,
                                balsin=None)
        verdict, code = run(path)
        assert code == 3
        assert "balsin_myeongui_missing" in codes(verdict)

    def test_named_issuer_is_clean(self, finished):
        verdict, _code = run(finished)
        assert not codes(verdict) & {"balsin_myeongui_unfilled",
                                     "balsin_myeongui_missing"}
        assert any(row.get("seat") == "balsin" and row.get("state") == "filled"
                   for row in verdict["seats"])

    def test_blank_form_issuer_seat_is_not_a_failure(self, blank):
        verdict, code = run(blank)
        assert code == 0
        assert not codes(verdict) & {"balsin_myeongui_unfilled",
                                     "balsin_myeongui_missing"}


# --------------------------------------------------------------------------- #
# R5 — 직인
# --------------------------------------------------------------------------- #
class TestSealSlot:
    def test_text_written_into_the_seal_box_is_caught(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "stamped.hwpx", fx.FINISHED,
                                seal="직인 국가유산청장")
        verdict, code = run(path)
        assert code == 3
        assert "seal_slot_overwritten" in codes(verdict)

    def test_reserved_seal_box_survives_untouched(self, finished):
        verdict, _code = run(finished)
        assert "seal_slot_overwritten" not in codes(verdict)
        seals = [row for row in verdict["seats"] if row.get("seat") == "seal"]
        assert seals and seals[0]["red_bordered"] is True

    def test_balsin_box_is_not_mistaken_for_the_seal_box(self, finished):
        """The corpus 발신명의 box declares color=#FF0000 on a type=NONE border."""
        verdict, _code = run(finished)
        seals = [row for row in verdict["seats"] if row.get("seat") == "seal"]
        assert len(seals) == 1

    def test_removed_seal_slot_is_caught_against_the_blank_form(self, tmp_path,
                                                                blank):
        path = fx.write_gongmun(tmp_path / "no_seal.hwpx", fx.FINISHED,
                                seal=None)
        verdict, code = run(path, baseline=blank)
        assert code == 3
        assert "seal_slot_removed" in codes(verdict)

    def test_surviving_seal_slot_is_not_reported_removed(self, finished, blank):
        verdict, _code = run(finished, baseline=blank)
        assert "seal_slot_removed" not in codes(verdict)



    # ----------------------------------------------------------------- #
    # T105 — the baseline excuses, and only that direction
    # ----------------------------------------------------------------- #
    def test_seal_residue_the_blank_form_also_prints_is_not_a_defect(
            self, tmp_path):
        """The T105 defect. A blank form may print something inside its own
        직인 box — a size hint, a bracketed instruction — and that text is the
        form's, not the fill's. The sibling rule `seal_slot_removed` two lines
        up already read `baseline_model` from the same scope; this one did not,
        so the pristine form read as overwritten."""
        printed = "직인 (35mm)"
        blank = fx.write_gongmun(tmp_path / "blank.hwpx", fx.BLANK,
                                 seal=printed)
        artifact = fx.write_gongmun(tmp_path / "filled.hwpx", fx.FINISHED,
                                    seal=printed)
        verdict, code = run(artifact, baseline=blank)
        assert "seal_slot_overwritten" not in codes(verdict)
        assert code == 0
        seals = [row for row in verdict["seats"] if row.get("seat") == "seal"]
        # residual_text strips the label and the vocabulary noise, so the
        # recorded value is the residue itself, not the printed cell text.
        assert seals and seals[0]["inherited_residue"]

    def test_seal_residue_the_fill_added_is_still_hard_with_a_baseline(
            self, tmp_path):
        """The still-catches. Inheriting the form's own hint must not excuse a
        name typed into the slot on top of it."""
        blank = fx.write_gongmun(tmp_path / "blank.hwpx", fx.BLANK,
                                 seal="직인 (35mm)")
        artifact = fx.write_gongmun(tmp_path / "filled.hwpx", fx.FINISHED,
                                    seal="직인 (35mm) 국가유산청장")
        verdict, code = run(artifact, baseline=blank)
        assert "seal_slot_overwritten" in codes(verdict)
        assert code == 3

    def test_a_blank_form_without_that_residue_does_not_excuse_it(
            self, tmp_path):
        """The baseline must match THIS slot, not merely exist.

        A blank form whose seal box prints nothing extra cannot excuse residue
        in the artifact's box — otherwise passing any baseline at all would
        launder the finding.
        """
        blank = fx.write_gongmun(tmp_path / "blank.hwpx", fx.BLANK,
                                 seal="직인")
        artifact = fx.write_gongmun(tmp_path / "filled.hwpx", fx.FINISHED,
                                    seal="직인 국가유산청장")
        verdict, code = run(artifact, baseline=blank)
        assert "seal_slot_overwritten" in codes(verdict)
        assert code == 3

    def test_no_baseline_still_hards_exactly_as_before(self, tmp_path):
        """Deliberately unchanged, and this is a correction to my own first cut.

        That version downgraded the no-baseline case to a WARN so it could
        report "cannot attribute". An existing test disproved it: a name in the
        seal box is caught with no baseline at all, that is the common case,
        and trading a working true positive for a false positive the corpus
        never exhibits is the wrong way round. The baseline EXCUSES; it never
        becomes a precondition for accusing.
        """
        artifact = fx.write_gongmun(tmp_path / "filled.hwpx", fx.FINISHED,
                                    seal="직인 (35mm)")
        verdict, code = run(artifact)
        assert "seal_slot_overwritten" in codes(verdict)
        assert code == 3

# --------------------------------------------------------------------------- #
# R6/R7/R8 — finishing rules
# --------------------------------------------------------------------------- #
class TestFinishingRules:
    def test_surviving_guide_term_is_residue(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "residue.hwpx", fx.FINISHED,
                                gonggae="공개 구분")
        verdict, code = run(path)
        assert code == 3
        assert "guide_vocabulary_residue" in codes(verdict)

    def test_section_labels_are_on_the_keep_list(self, finished):
        verdict, _code = run(finished)
        assert "guide_vocabulary_residue" not in codes(verdict)
        # the labels really are still in the document — they are kept, not gone
        assert check_gongmun.keep_labels(
            check_gongmun.load_vocabulary()).count("수신") == 1

    def test_bigo_block_must_not_ship(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "with_bigo.hwpx", fx.FINISHED,
                                bigo=True)
        verdict, code = run(path, mode="final")
        assert code == 3
        assert "bigo_block_retained" in codes(verdict)

    def test_bigo_block_removed_is_clean(self, finished):
        verdict, _code = run(finished)
        assert "bigo_block_retained" not in codes(verdict)

    def test_bigo_in_a_draft_is_a_warning(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "draft.hwpx", fx.FINISHED,
                                bigo=True)
        verdict, code = run(path)
        assert code == 0
        assert "bigo_block_retained" in codes(verdict, "warn")

    def test_placeholder_glyphs_must_not_survive(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "glyphs.hwpx", fx.FINISHED,
                                jemok="제목 ○○○○ 협조 요청")
        verdict, code = run(path)
        assert code == 3
        assert "placeholder_glyphs_retained" in codes(verdict)

    def test_no_glyphs_no_finding(self, finished):
        verdict, _code = run(finished)
        assert "placeholder_glyphs_retained" not in codes(verdict)

    def test_bigo_quoted_terms_widen_the_residue_class(self, tmp_path):
        """A term only the form's own 비고 names is still residue."""
        vocabulary = check_gongmun.load_vocabulary()
        path = fx.write_gongmun(tmp_path / "bigo.hwpx", fx.BLANK)
        model = check_gongmun.document_model(path)
        terms = check_gongmun.bigo_terms(model, vocabulary)
        assert "발신명" in terms
        assert "행정기관명" in terms


# --------------------------------------------------------------------------- #
# R10 — seat_emptied (baseline)
# --------------------------------------------------------------------------- #
class TestSeatEmptied:
    def test_wiped_seat_is_caught_against_the_blank_form(self, tmp_path, blank):
        path = fx.write_gongmun(tmp_path / "wiped.hwpx", fx.FINISHED, doro="")
        verdict, code = run(path, baseline=blank)
        assert code == 3
        assert "seat_emptied" in codes(verdict)

    def test_filled_seats_are_not_reported_emptied(self, finished, blank):
        verdict, code = run(finished, baseline=blank)
        assert code == 0, verdict["hard"]
        assert "seat_emptied" not in codes(verdict)

    def test_receiver_completed_seat_is_exempt(self, finished, blank):
        """접수 numbering is written by the RECEIVING agency: blank is correct."""
        verdict, _code = run(finished, baseline=blank)
        assert any(row.get("state") == "human_completed"
                   for row in verdict["seats"])

    def test_without_a_baseline_the_rule_is_skipped(self, finished):
        verdict, _code = run(finished)
        assert skipped_rules(verdict)["seat_emptied"] == "no_baseline"


# --------------------------------------------------------------------------- #
# R9 — the gongmun_org pack
# --------------------------------------------------------------------------- #
class TestIssuingOrganizationPack:
    def test_undeclared_issuer_is_hard(self, tmp_path, finished):
        pack = fx.write_pack(tmp_path / "pack.json",
                             organizations=["문화체육관광부"])
        verdict, code = run(finished, pack=pack)
        assert code == 3
        assert "issuer_not_in_pack" in codes(verdict)

    def test_declared_issuer_is_accepted(self, tmp_path, finished):
        pack = fx.write_pack(tmp_path / "pack.json",
                             organizations=["국가유산청"])
        verdict, code = run(finished, pack=pack)
        assert code == 0, verdict["hard"]
        assert "issuer_not_in_pack" not in codes(verdict)

    def test_undeclared_rank_is_a_warning(self, tmp_path, finished, blank):
        pack = fx.write_pack(tmp_path / "pack.json",
                             organizations=["국가유산청"], ranks=["사무관"])
        verdict, _code = run(finished, pack=pack, baseline=blank)
        assert "rank_not_in_pack" in codes(verdict, "warn")

    def test_declared_ranks_are_accepted(self, tmp_path, finished, blank):
        pack = fx.write_pack(tmp_path / "pack.json",
                             organizations=["국가유산청"],
                             ranks=["주무관", "과장", "청장"])
        verdict, _code = run(finished, pack=pack, baseline=blank)
        assert "rank_not_in_pack" not in codes(verdict, "warn")

    def test_no_pack_means_skipped_not_passed(self, finished):
        verdict, _code = run(finished)
        assert skipped_rules(verdict)["issuing_organization_pack"] == "no_pack"

    def test_shipped_default_pack_is_empty_and_says_so(self, finished):
        verdict, code = run(finished, pack=check_gongmun.DEFAULT_PACK)
        assert code == 0
        assert skipped_rules(verdict)["issuing_organization_pack"] == \
            "pack_vocabulary_empty"

    def test_wrong_pack_type_is_a_usage_error(self, tmp_path, finished):
        bad = tmp_path / "bad.json"
        bad.write_text('{"pack_type": "saeteuk"}', encoding="utf-8")
        verdict, code = run(finished, pack=bad)
        assert code == 2 and verdict["verdict"] == "usage_error"


# --------------------------------------------------------------------------- #
# the seat-state mechanism itself
# --------------------------------------------------------------------------- #
class TestSeatStateMechanism:
    @pytest.fixture()
    def vocabulary(self):
        return check_gongmun.load_vocabulary()

    @pytest.mark.parametrize("text, terms, expected", [
        ("도로명주소", ["도로명주소"], "blank_by_design"),
        ("서울특별시 종로구 삼봉로 81", ["도로명주소"], "filled"),
        ("", ["도로명주소"], "emptied"),
        ("도로명주소 서울특별시", ["도로명주소"], "half_filled"),
        ("기안자  직위(직급) 서명", ["기안자", "직위(직급)", "서명"],
         "blank_by_design"),
        ("기안자 주무관 홍길동", ["기안자", "직위(직급)", "서명"], "half_filled"),
        ("주무관 홍길동", ["기안자", "직위(직급)", "서명"], "filled"),
        # a seat holding nothing but ○ runs is unfilled, not filled …
        ("○○○○", ["발신명의"], "emptied"),
        # … but 별지 제2호서식's issuer placeholder carries real characters too,
        # so the ○-run rule (not seat_state) is what catches that one.
        ("○○○○부", ["발신명의"], "filled"),
    ])
    def test_tri_state(self, vocabulary, text, terms, expected):
        assert check_gongmun.seat_state(
            text, terms, vocabulary)["state"] == expected

    def test_matching_is_whitespace_insensitive(self, vocabulary):
        """The 서식 letter-spaces its own labels: 행 정 기 관 명."""
        judged = check_gongmun.seat_state("행 정 기 관 명", ["행정기관명"],
                                          vocabulary)
        assert judged["state"] == "blank_by_design"

    def test_vocabulary_schema_is_validated(self, tmp_path):
        bad = tmp_path / "vocab.json"
        bad.write_text('{"schema": "nope/v1"}', encoding="utf-8")
        with pytest.raises(check_gongmun.GongmunError, match="schema must be"):
            check_gongmun.load_vocabulary(bad)

    def test_approver_roles_are_not_on_the_keep_list(self, vocabulary):
        """The 비고 names 기안자/검토자/결재권자 as terms to REPLACE."""
        keep = check_gongmun.keep_labels(vocabulary)
        assert "기안자" not in keep
        assert "수신" in keep and "협조자" in keep


# --------------------------------------------------------------------------- #
# CLI + verdict contract
# --------------------------------------------------------------------------- #
class TestCliContract:
    def test_cli_emits_one_json_verdict_and_the_exit_code(self, finished,
                                                          tmp_path, capsys):
        import json
        out = tmp_path / "verdict.json"
        code = check_gongmun.main([str(finished), "--out", str(out)])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["checker"] == "check_gongmun"
        assert payload["verdict"] == "pass"
        assert set(payload) >= {"ok", "workspace", "checker", "hard", "warn",
                                "counts", "verdict", "document", "seats",
                                "skipped"}
        assert json.loads(out.read_text(encoding="utf-8")) == payload

    def test_cli_returns_three_on_a_hard_finding(self, tmp_path):
        path = fx.write_gongmun(tmp_path / "bad.hwpx", fx.FINISHED,
                                seal="직인 국가유산청장")
        assert check_gongmun.main([str(path)]) == 3
