# -*- coding: utf-8 -*-
"""check_grant rule-by-rule: every rule has a positive and a still-catches pair.

The pattern each class follows: a legitimate packet must PASS (that is the
still-catches half — a rule that fires on a correct fill is worse than no rule),
and a one-key mutation of the same fixture must produce exactly the finding the
rule names.

Two properties get more attention than the rest, because they are what makes this
module different from minwon and hr:

* ``TestExtendableTables`` — adding rows is legitimate here, so the geometry rule
  compares COLUMN structure and the header row. Added rows pass and are reported
  as an extension; a changed column count is HARD.
* ``TestPacketIntegrity`` — a 붙임/별첨 citation resolving against a section of
  this same document needs no baseline, and a marker class the document carries
  no header for is EXTERNAL rather than dangling.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MODULE_ROOT = _HERE.parent
_REPO_ROOT = _MODULE_ROOT.parents[1]
for _dir in (_REPO_ROOT / "pipeline" / "scripts",
             _REPO_ROOT / "engine" / "scripts", _MODULE_ROOT / "scripts",
             _HERE):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import check_grant as cg  # noqa: E402
import grant_fixtures as fx  # noqa: E402


def codes(verdict: dict, bucket: str = "hard") -> list:
    return [row["code"] for row in verdict[bucket]]


def skipped_rules(verdict: dict, reason: str | None = None) -> set:
    return {row["rule"] for row in verdict["skipped"]
            if reason is None or row["reason"] == reason}


def seats(verdict: dict, name: str) -> list:
    return [row for row in verdict["seats"] if row["seat"] == name]


@pytest.fixture()
def blank(tmp_path) -> Path:
    return fx.write_grant(tmp_path / "blank.hwpx", fx.BLANK)


@pytest.fixture()
def filled(tmp_path) -> Path:
    return fx.write_grant(tmp_path / "filled.hwpx", fx.FILLED)


def mutate(tmp_path, name: str, **overrides) -> Path:
    """A FILLED packet with one thing changed."""
    return fx.write_grant(tmp_path / f"{name}.hwpx", fx.FILLED, **overrides)


# --------------------------------------------------------------------------- #
# R0 — the loud-failure contract
# --------------------------------------------------------------------------- #
class TestArtifactLevel:
    def test_a_missing_artifact_is_hard_never_a_silent_pass(self, tmp_path):
        verdict, code = cg.check(tmp_path / "nope.hwpx")
        assert code == 3
        assert codes(verdict) == ["artifact_missing"]

    def test_a_malformed_section_stops_structure_checks(self, tmp_path):
        path = fx.write_grant(tmp_path / "bad.hwpx", fx.BLANK, malformed=True)
        verdict, code = cg.check(path)
        assert code == 3
        assert codes(verdict) == ["artifact_malformed"]
        assert verdict["document"] is None

    def test_a_non_zip_is_a_usage_refusal(self, tmp_path):
        path = tmp_path / "plain.txt"
        path.write_text("not a packet", encoding="utf-8")
        _verdict, code = cg.check(path)
        assert code == 2

    def test_a_document_that_is_not_a_packet_is_refused(self, tmp_path):
        path = fx.write_not_a_packet(tmp_path / "report.hwpx")
        verdict, code = cg.check(path)
        assert code == 3
        assert codes(verdict) == ["grant_structure_absent"]
        assert verdict["document"]["families"] == []

    def test_a_bad_mode_is_a_usage_refusal(self, blank):
        _verdict, code = cg.check(blank, mode="whenever")
        assert code == 2


# --------------------------------------------------------------------------- #
# the still-catches baseline: correct packets pass
# --------------------------------------------------------------------------- #
class TestLegitimatePacketsPass:
    def test_the_pristine_packet_is_clean_and_reads_blank(self, blank):
        verdict, code = cg.check(blank)
        assert code == 0
        assert verdict["hard"] == [] and verdict["warn"] == []
        assert verdict["document"]["state"] == "blank"
        assert len(verdict["document"]["families"]) == 6

    def test_a_document_is_never_its_own_baseline_but_it_may_be_checked(
            self, blank):
        """Passing the blank form as its own baseline must be clean — this is the
        shape the eval harness uses when it profiles the form itself."""
        verdict, code = cg.check(blank, baseline=blank)
        assert code == 0
        assert verdict["document"]["state_basis"] == "baseline_diff"
        assert verdict["document"]["seats_changed"] == 0

    def test_a_correctly_completed_packet_is_clean(self, filled, blank):
        verdict, code = cg.check(filled, baseline=blank)
        assert code == 0
        assert verdict["hard"] == [] and verdict["warn"] == []
        assert verdict["document"]["state"] == "final"

    def test_exactly_six_rules_need_the_blank_form(self, filled):
        """``wants: [baseline]`` is only honest if it tracks behaviour."""
        verdict, _code = cg.check(filled)
        assert skipped_rules(verdict, "no_baseline") == {
            "packet_section_lost", "table_structure_lost",
            "table_column_changed", "consent_block_lost",
            "consent_option_lost", "signature_seat_lost"}

    def test_supplying_the_baseline_decides_all_six(self, filled, blank):
        verdict, _code = cg.check(filled, baseline=blank)
        assert skipped_rules(verdict, "no_baseline") == set()


# --------------------------------------------------------------------------- #
# R1 — packet integrity
# --------------------------------------------------------------------------- #
class TestPacketIntegrity:
    def test_a_resolving_reference_is_reported_not_flagged(self, filled):
        verdict, code = cg.check(filled)
        assert code == 0
        resolved = [row for row in seats(verdict, "packet_reference")
                    if row["state"] == "resolved"]
        assert resolved and all(row["number"] == "2-1" for row in resolved)

    def test_a_marker_class_with_no_header_is_external_not_dangling(self,
                                                                   filled):
        """The corpus fact this rule is calibrated on: kstartup cites 붙임3 and
        붙임5, which live in the 공고문. Demanding them inside the file would
        fail every pristine form of this family."""
        verdict, code = cg.check(filled)
        assert code == 0
        external = [row for row in seats(verdict, "packet_reference")
                    if row["state"] == "external"]
        assert external == [{"seat": "packet_reference", "state": "external",
                             "marker": "붙임", "numbers": ["3", "5"]}]

    def test_a_reference_whose_section_vanished_is_hard_without_a_baseline(
            self, tmp_path):
        keep = [row for row in fx.FILLED["sections"] if row["number"] != "2-1"]
        path = mutate(tmp_path, "dangling", sections=keep)
        verdict, code = cg.check(path)
        assert code == 3
        assert "packet_reference_dangling" in codes(verdict)
        row = next(item for item in verdict["hard"]
                   if item["code"] == "packet_reference_dangling")
        assert row["number"] == "2-1" and row["marker"] == "별첨"

    def test_a_section_the_blank_form_carries_is_hard_when_gone(self, tmp_path,
                                                               blank):
        path = mutate(tmp_path, "nosection",
                      sections=fx.FILLED["sections"][:1])
        verdict, code = cg.check(path, baseline=blank)
        assert code == 3
        lost = [row for row in verdict["hard"]
                if row["code"] == "packet_section_lost"]
        assert [row["number"] for row in lost] == ["2-1"]

    def test_a_section_the_form_says_may_be_deleted_is_warn_not_hard(
            self, tmp_path, blank):
        """kstartup licenses dropping two of its parts ('※ 해당자에 한함 (없을
        시 삭제)'). Deleting one is following the form, so it cannot be HARD."""
        path = mutate(tmp_path, "optional",
                      sections=fx.FILLED["sections"][:2])
        verdict, code = cg.check(path, baseline=blank)
        assert code == 0
        assert codes(verdict) == []
        row = next(item for item in verdict["warn"]
                   if item["code"] == "packet_section_lost")
        assert row["optional"] is True and row["number"] == "3"

    def test_a_packet_with_no_internal_marker_class_says_so(self, tmp_path):
        path = mutate(tmp_path, "noparts", sections=[],
                      guide_rows=[row for row in fx.FILLED["guide_rows"]
                                  if "별첨" not in row and "붙임" not in row])
        verdict, _code = cg.check(path)
        assert {"rule": "packet_reference_dangling",
                "reason": "no_internal_marker_class"} in verdict["skipped"]


# --------------------------------------------------------------------------- #
# R2 — the extendable-table geometry rule (this module's sharpest difference)
# --------------------------------------------------------------------------- #
class TestExtendableTables:
    def test_added_rows_pass_and_are_reported_as_an_extension(self, filled,
                                                              blank):
        """The property that separates this family from every other one: the
        applicant adds budget line items and roster rows, so a row count that
        moved is an extension, not damage. FILLED's roster carries one more row
        than the blank form's."""
        verdict, code = cg.check(filled, baseline=blank)
        assert code == 0
        added = [row for row in seats(verdict, "grid") if row["rows_added"]]
        assert [row["rows_added"] for row in added] == [1]
        assert all(row["state"] == "extendable"
                   for row in seats(verdict, "grid"))

    def test_many_added_rows_still_pass(self, tmp_path, blank):
        roster = fx.FILLED["roster_grid"] + [
            [f"2027.{month:02d}", "광주테크노파크", "1,000", "추가 활동"]
            for month in range(7, 12)]
        path = mutate(tmp_path, "grown", roster_grid=roster)
        verdict, code = cg.check(path, baseline=blank)
        assert code == 0
        added = [row for row in seats(verdict, "grid") if row["rows_added"]]
        assert [row["rows_added"] for row in added] == [6]

    def test_a_changed_column_count_is_hard(self, tmp_path, blank):
        path = mutate(tmp_path, "widened", roster_cols=6)
        verdict, code = cg.check(path, baseline=blank)
        assert code == 3
        row = next(item for item in verdict["hard"]
                   if item["code"] == "table_column_changed")
        assert (row["baseline"], row["artifact"]) == (4, 6)

    def test_a_deleted_table_is_hard(self, tmp_path, blank):
        path = mutate(tmp_path, "notable", roster_grid=None)
        verdict, code = cg.check(path, baseline=blank)
        assert code == 3
        assert "table_structure_lost" in codes(verdict)

    def test_the_rule_never_compares_a_cell_count(self):
        """Stated as source, because it is the one comparison this family
        forbids: adding a row adds cells, and a cell-count rule would fire on
        every legitimate extension. minwon and hr can afford that rule; this
        module may not."""
        source = (_MODULE_ROOT / "scripts" / "check_grant.py").read_text(
            encoding="utf-8")
        body = source.split('def _check_tables', 1)[1].split("\ndef ", 1)[0]
        assert "colCnt" in body
        assert "rows_added" in body
        assert "cells" not in body

    def test_two_tables_sharing_a_header_pair_one_to_one(self, filled, blank):
        """The consent rows ship twice with identical headers. Both must pair
        with their own partner rather than both onto the first."""
        verdict, _code = cg.check(filled, baseline=blank)
        paired = {row["at"]["table"] for row in seats(verdict, "grid")}
        assert len(paired) == len(seats(verdict, "grid"))


# --------------------------------------------------------------------------- #
# R3 — budget arithmetic
# --------------------------------------------------------------------------- #
class TestBudgetArithmetic:
    def test_a_balanced_total_is_reported(self, filled):
        verdict, code = cg.check(filled)
        assert code == 0
        balanced = seats(verdict, "budget_total")
        assert len(balanced) == 3
        assert all(row["state"] == "balanced" for row in balanced)

    def test_a_total_that_does_not_add_up_is_hard_with_no_baseline(self,
                                                                  tmp_path):
        grid = [row[:] for row in fx.FILLED["budget_grid"]]
        grid[-1] = ["합        계(천원)", "21,000", "5,000", "25,000"]
        path = mutate(tmp_path, "unbalanced", budget_grid=grid)
        verdict, code = cg.check(path)
        assert code == 3
        row = next(item for item in verdict["hard"]
                   if item["code"] == "budget_total_mismatch")
        assert (row["total"], row["column_sum"]) == (21000, 20000)

    def test_adding_a_line_item_and_updating_the_total_passes(self, tmp_path,
                                                             blank):
        """The two rules together: an extended budget table with a corrected
        total is a legitimate packet, and nothing may fire on it."""
        grid = [row[:] for row in fx.FILLED["budget_grid"]]
        grid.insert(-1, ["홈페이지 개발", "4,000", "-", "4,000"])
        grid[-1] = ["합        계(천원)", "24,000", "5,000", "29,000"]
        path = mutate(tmp_path, "extended_budget", budget_grid=grid)
        verdict, code = cg.check(path, baseline=blank)
        assert code == 0
        assert verdict["warn"] == []
        added = [row for row in seats(verdict, "grid")
                 if row["at"]["table"] == 1]
        assert added[0]["rows_added"] == 1

    def test_a_total_with_no_addends_is_skipped_not_asserted(self, tmp_path):
        grid = [["지원분야", "지원신청액", "자부담금", "합계"],
                ["시제품 제작", "11,000", "-", "11,000"],
                ["합        계(천원)", "11,000", "0", "11,000"]]
        path = mutate(tmp_path, "noaddends", budget_grid=grid)
        verdict, code = cg.check(path)
        assert code == 0
        assert "budget_total_mismatch" in skipped_rules(verdict, "no_addends")

    def test_a_packet_with_no_budget_table_skips_the_rule(self, tmp_path):
        path = mutate(tmp_path, "nobudget", budget_grid=None)
        verdict, code = cg.check(path)
        assert code == 0
        assert "budget_total_mismatch" in skipped_rules(verdict, "seat_absent")

    def test_declared_money_caps_are_reported_and_never_gated(self, filled):
        """The honest residue of the cap idea: the form states three, and
        binding one to a figure would be a guess (two share the noun
        지원신청액 with different scopes)."""
        verdict, code = cg.check(filled)
        assert code == 0
        caps = seats(verdict, "budget_cap")
        assert caps and set(caps[0]["caps"]) == {"30,000천원", "1백만원"}
        source = (_MODULE_ROOT / "scripts" / "check_grant.py").read_text(
            encoding="utf-8")
        assert "budget_cap_exceeded" not in source


# --------------------------------------------------------------------------- #
# R4 — consent
# --------------------------------------------------------------------------- #
class TestConsent:
    def test_a_marked_consent_passes(self, filled):
        verdict, code = cg.check(filled)
        assert code == 0
        marked = seats(verdict, "consent")
        assert len(marked) == 2
        assert all(row["state"] == "marked" and row["required"]
                   for row in marked)

    def test_an_unmarked_required_consent_is_hard_in_a_final_packet(self,
                                                                   tmp_path):
        rows = [["개인정보", "필수항목 : 개인 식별정보",
                 "( □동의함    □동의하지 않음 )"],
                fx.FILLED["consent_rows"][1]]
        path = mutate(tmp_path, "unmarked", consent_rows=rows)
        verdict, code = cg.check(path)
        assert code == 3
        row = next(item for item in verdict["hard"]
                   if item["code"] == "consent_unmarked")
        assert row["required"] is True and row["options"] == 2

    def test_an_unmarked_consent_is_only_a_warn_before_the_packet_is_dated(
            self, tmp_path, blank):
        """``draft`` needs the baseline: without it there is no evidence anyone
        wrote in the packet (the form ships pre-filled with examples), so state
        falls back to the date seat and reads ``blank``. That is the
        ``state_basis`` distinction, exercised."""
        rows = [["개인정보", "필수항목 : 개인 식별정보",
                 "( □동의함    □동의하지 않음 )"],
                fx.FILLED["consent_rows"][1]]
        path = mutate(tmp_path, "draft_unmarked", consent_rows=rows,
                      date_row=fx.BLANK["date_row"])
        verdict, code = cg.check(path, baseline=blank)
        assert code == 0
        assert verdict["document"]["state"] == "draft"
        assert "consent_unmarked" in codes(verdict, "warn")

    def test_an_unmarked_consent_the_form_does_not_call_required_is_warn(
            self, tmp_path):
        rows = [["개인정보", "선택항목 : 마케팅 정보",
                 "( □동의함    □동의하지 않음 )"]]
        path = mutate(tmp_path, "optional_consent", consent_rows=rows)
        verdict, code = cg.check(path)
        assert code == 0
        row = next(item for item in verdict["warn"]
                   if item["code"] == "consent_unmarked")
        assert row["required"] is False

    def test_a_glyphless_choice_is_skipped_with_a_reason_not_guessed(
            self, tmp_path):
        """pps-jeongbogonggae's own shape: '동의하십니까? (예,  아니오)'. There is
        no mark to read, so the rule says so instead of inventing a verdict."""
        rows = [["개인정보", "수집ㆍ이용 내역",
                 "위와 같이 수집ㆍ이용하는데 동의하십니까? (예,  아니오)"]]
        path = mutate(tmp_path, "glyphless", consent_rows=rows)
        verdict, code = cg.check(path)
        assert code == 0
        row = next(item for item in verdict["skipped"]
                   if item["rule"] == "consent_unmarked")
        assert row["reason"] == "no_mark_glyphs" and row["groups"] == 1

    def test_a_section_bullet_is_not_a_consent_choice(self, tmp_path):
        """Thirty of kstartup's 32 box glyphs are bullets ('□ 수집·이용 목적').
        A rule that demanded marking a heading would fire on every form."""
        path = mutate(tmp_path, "bullets", consent_rows=None,
                      guide_rows=fx.FILLED["guide_rows"]
                      + ["□ 수집·이용 목적", "□ 동의를 거부할 권리"])
        verdict, code = cg.check(path)
        assert code == 0
        assert "consent_unmarked" in skipped_rules(verdict, "seat_absent")

    def test_a_parenthetical_that_merely_contains_예_is_not_a_choice(self,
                                                                    tmp_path):
        path = mutate(tmp_path, "yebi", consent_rows=None,
                      guide_rows=fx.FILLED["guide_rows"]
                      + ["  ① (예비)창업자 부담금율(%) 산정 시 동의 사항 참고"])
        verdict, code = cg.check(path)
        assert code == 0
        assert "consent_unmarked" in skipped_rules(verdict, "seat_absent")

    def test_a_dropped_consent_block_is_hard(self, tmp_path, blank):
        path = mutate(tmp_path, "oneconsent",
                      consent_rows=fx.FILLED["consent_rows"][:1])
        verdict, code = cg.check(path, baseline=blank)
        assert code == 3
        row = next(item for item in verdict["hard"]
                   if item["code"] == "consent_block_lost")
        assert (row["baseline"], row["artifact"]) == (2, 1)

    def test_deleting_the_refuse_option_is_hard(self, tmp_path):
        """Manufacturing a consent by removing the way to decline it. Needs a
        three-option baseline so the block count is untouched and only the
        option count moves."""
        wide = [["개인정보", "필수항목 : 개인 식별정보",
                 "( □동의함    □일부 동의함    □동의하지 않음 )"]]
        narrowed = [["개인정보", "필수항목 : 개인 식별정보",
                     "( ■동의함    □일부 동의함 )"]]
        base = fx.write_grant(tmp_path / "wide.hwpx", fx.BLANK,
                              consent_rows=wide)
        path = fx.write_grant(tmp_path / "narrowed.hwpx", fx.FILLED,
                              consent_rows=narrowed)
        verdict, code = cg.check(path, baseline=base)
        assert code == 3
        row = next(item for item in verdict["hard"]
                   if item["code"] == "consent_option_lost")
        assert (row["baseline"], row["artifact"]) == (3, 2)
        assert "consent_block_lost" not in codes(verdict)


# --------------------------------------------------------------------------- #
# R5 — signature seats
# --------------------------------------------------------------------------- #
class TestSignatureSeats:
    def test_the_seats_survive_a_correct_fill(self, filled, blank):
        verdict, code = cg.check(filled, baseline=blank)
        assert code == 0
        row = next(item for item in seats(verdict, "signature"))
        assert row["state"] == "reserved" and row["count"] == 3

    def test_a_removed_seat_is_hard(self, tmp_path, blank):
        path = mutate(tmp_path, "nosig",
                      signature_rows=fx.FILLED["signature_rows"][:1])
        verdict, code = cg.check(path, baseline=blank)
        assert code == 3
        row = next(item for item in verdict["hard"]
                   if item["code"] == "signature_seat_lost")
        assert (row["baseline"], row["artifact"]) == (3, 2)

    def test_writing_a_name_beside_the_seat_is_not_removing_it(self, tmp_path,
                                                              blank):
        path = mutate(tmp_path, "named", signature_rows=[
            "                     신 청 자 : 이서준          (인)",
            "                     대 표 자 : 김도현          (인)"])
        verdict, code = cg.check(path, baseline=blank)
        assert code == 0


# --------------------------------------------------------------------------- #
# R6 — the privacy rule, never gated behind the baseline
# --------------------------------------------------------------------------- #
class TestNeverInventAPersonalNumber:
    def test_an_undeclared_rrn_is_hard_with_no_baseline(self, tmp_path):
        grid = [["구    분", "성    명", "생년월일"],
                ["지원 신청자", "이서준", "900101-1234567"],
                ["소    속", "한빛정밀 주식회사", ""]]
        path = mutate(tmp_path, "rrn", applicant_grid=grid)
        verdict, code = cg.check(path)
        assert code == 3
        assert "identity_value_invented" in codes(verdict)
        assert "identity_value_invented" not in skipped_rules(verdict)

    def test_an_undeclared_account_shape_is_hard_with_no_baseline(self,
                                                                 tmp_path):
        grid = [["구    분", "성    명", "생년월일"],
                ["지원 신청자", "이서준", "110-234-567890"],
                ["소    속", "한빛정밀 주식회사", ""]]
        path = mutate(tmp_path, "acct", applicant_grid=grid)
        verdict, code = cg.check(path)
        assert code == 3
        assert "account_number_invented" in codes(verdict)

    def test_a_declared_value_passes(self, tmp_path, blank):
        grid = [["구    분", "성    명", "생년월일"],
                ["지원 신청자", "이서준", "900101-1234567"],
                ["소    속", "한빛정밀 주식회사", ""]]
        path = mutate(tmp_path, "declared", applicant_grid=grid)
        fill_map = fx.write_fill_map(tmp_path / "fill.json",
                                     {"생년월일": "900101-1234567"})
        verdict, code = cg.check(path, baseline=blank, fill_map=fill_map)
        assert code == 0
        assert verdict["document"]["fill_map_declared"] == 1

    def test_this_family_s_money_is_not_an_account_number(self, filled):
        """The comma guards, tested where they matter: this family prints
        16,000,000 and 35,000 in its budget tables."""
        grid = [["지원분야", "지원신청액", "자부담금", "합계"],
                ["기술료 이전", "20,000,000", "-", "20,000,000"],
                ["합        계(천원)", "20,000,000", "0", "20,000,000"]]
        path = fx.write_grant(Path(filled).parent / "money.hwpx", fx.FILLED,
                              budget_grid=grid)
        verdict, code = cg.check(path)
        assert code == 0
        assert "account_number_invented" not in codes(verdict)

    def test_a_part_number_is_not_an_account_number(self, filled):
        verdict, code = cg.check(filled)
        assert code == 0
        assert "account_number_invented" not in codes(verdict)

    def test_the_identity_seats_the_packet_asks_for_are_reported(self, filled):
        verdict, _code = cg.check(filled)
        row = next(item for item in seats(verdict, "identity_seat"))
        assert "생년월일" in row["labels"]


# --------------------------------------------------------------------------- #
# R7 — what the form told the applicant to remove
# --------------------------------------------------------------------------- #
class TestSubmissionResidue:
    def test_a_clean_packet_reports_both_rules_clean(self, filled):
        verdict, code = cg.check(filled)
        assert code == 0
        assert {row["seat"] for row in verdict["seats"]} >= {
            "self_deleting_guide_retained", "example_placeholder_retained"}

    def test_the_self_deleting_guidance_surviving_a_final_packet_is_hard(
            self, tmp_path):
        path = mutate(tmp_path, "guide", guide_rows=fx.FILLED["guide_rows"] + [
            "  ※ 해당 안내를 포함한, 아래 파란색 안내 문구는 참고하여 작성 후 삭제"])
        verdict, code = cg.check(path)
        assert code == 3
        assert "self_deleting_guide_retained" in codes(verdict)

    def test_a_worked_example_stand_in_surviving_is_hard(self, tmp_path):
        path = mutate(tmp_path, "placeholder",
                      closing_placeholder="   지원자      ㅇㅇㅇ  (인)")
        verdict, code = cg.check(path)
        assert code == 3
        assert "example_placeholder_retained" in codes(verdict)

    def test_a_single_bullet_circle_is_not_a_placeholder(self, tmp_path):
        """This family writes 40+ '○ …' bullets. A rule keyed on a single ○
        would fire on every packet."""
        path = mutate(tmp_path, "bullet", guide_rows=fx.FILLED["guide_rows"]
                      + ["  ○ 제품 개발 계획", "  ○ 사업화 계획"])
        verdict, code = cg.check(path)
        assert code == 0

    def test_both_rules_are_reported_not_failed_on_a_blank_form(self, blank):
        verdict, code = cg.check(blank)
        assert code == 0
        assert {"self_deleting_guide_retained",
                "example_placeholder_retained"} <= skipped_rules(
                    verdict, "document_state_blank")


# --------------------------------------------------------------------------- #
# R8 — the declared dependency
# --------------------------------------------------------------------------- #
class TestLengthBudgetIsADeclaredDependency:
    def test_no_declared_budget_reports_not_declared(self, filled):
        verdict, _code = cg.check(filled)
        row = next(item for item in verdict["skipped"]
                   if item["rule"] == "length_budget_unverified")
        assert row["reason"] == "not_declared"

    def test_a_declared_page_budget_reports_the_render_dependency(self,
                                                                  tmp_path):
        """The honest answer, not a guess: a page count is not derivable from
        Contents/section*.xml, so the rule names the tool that owns it."""
        path = mutate(tmp_path, "paged", guide_rows=fx.FILLED["guide_rows"]
                      + ["  ○ 사업계획서 본문은 5쪽 이내로 작성"])
        verdict, code = cg.check(path)
        assert code == 0
        row = next(item for item in verdict["skipped"]
                   if item["reason"] == "needs_render")
        assert row["pages"] == ["5"]
        assert "visual_verify" in row["dependency"]
        declared = next(item for item in seats(verdict, "length_budget"))
        assert declared["pages"] == ["5"]

    def test_a_declared_character_budget_reports_the_scoping_gap(self,
                                                                 tmp_path):
        path = mutate(tmp_path, "chars", guide_rows=fx.FILLED["guide_rows"]
                      + ["  ○ 요약은 500자 이내로 작성"])
        verdict, code = cg.check(path)
        assert code == 0
        row = next(item for item in verdict["skipped"]
                   if item["reason"] == "needs_section_scoping")
        assert row["chars"] == ["500"]

    def test_the_rule_never_reaches_hard_or_pass(self):
        source = (_MODULE_ROOT / "scripts" / "check_grant.py").read_text(
            encoding="utf-8")
        body = source.split("def _check_length_budget", 1)[1]
        body = body.split("\ndef ", 1)[0]
        assert "hard" not in body


# --------------------------------------------------------------------------- #
# state machine
# --------------------------------------------------------------------------- #
class TestStateMachine:
    def test_mode_forces_the_state(self, blank):
        verdict, _code = cg.check(blank, mode="final")
        assert verdict["document"]["state"] == "blank"
        assert verdict["document"]["state_used"] == "final"

    def test_forcing_final_on_a_blank_form_makes_the_residue_rules_bite(
            self, blank):
        """The blank fixture carries the form's own guidance and stand-ins. In
        ``auto`` they are reported; forcing ``final`` says 'this is what you are
        submitting' and they become findings."""
        verdict, code = cg.check(blank, mode="final")
        assert code == 3
        assert {"self_deleting_guide_retained",
                "example_placeholder_retained"} <= set(codes(verdict))

    def test_the_state_basis_is_recorded_both_ways(self, filled, blank):
        without, _c1 = cg.check(filled)
        with_form, _c2 = cg.check(filled, baseline=blank)
        assert without["document"]["state_basis"] == "date_seat_only"
        assert with_form["document"]["state_basis"] == "baseline_diff"
        assert with_form["document"]["seats_changed"] > 0

    def test_a_pre_marked_consent_is_not_evidence_of_writing(self, tmp_path):
        """The kstartup form ships with ■동의함 already marked. A state machine
        that read a marked box as 'someone wrote here' would call every pristine
        form of this family a draft."""
        path = fx.write_grant(tmp_path / "premarked.hwpx", fx.BLANK,
                              consent_rows=fx.FILLED["consent_rows"])
        verdict, code = cg.check(path)
        assert code == 0
        assert verdict["document"]["marked_consent_options"] == 2
        assert verdict["document"]["state"] == "blank"


# --------------------------------------------------------------------------- #
# CLI + verdict shape
# --------------------------------------------------------------------------- #
class TestCli:
    def test_the_cli_writes_a_verdict_and_exits_zero_on_a_clean_packet(
            self, tmp_path, filled, blank):
        out = tmp_path / "verdict.json"
        code = cg.main([str(filled), "--baseline", str(blank),
                        "--out", str(out)])
        assert code == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["checker"] == "check_grant"
        assert payload["counts"]["hard"] == 0

    def test_the_cli_exits_three_on_a_hard_finding(self, tmp_path, blank):
        path = mutate(tmp_path, "cli_bad", roster_cols=6)
        code = cg.main([str(path), "--baseline", str(blank),
                        "--out", str(tmp_path / "v.json")])
        assert code == 3

    def test_a_broken_vocabulary_is_a_usage_refusal(self, tmp_path, filled):
        broken = dict(cg.load_vocabulary())
        broken["schema"] = "nope/v9"
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        _verdict, code = cg.check(filled, vocabulary=path)
        assert code == 2

    def test_a_non_scalar_fill_map_is_a_usage_refusal(self, tmp_path, filled):
        path = tmp_path / "fill.json"
        path.write_text(json.dumps({"a": ["list"]}), encoding="utf-8")
        _verdict, code = cg.check(filled, fill_map=path)
        assert code == 2
