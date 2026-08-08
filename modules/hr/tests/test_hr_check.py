# -*- coding: utf-8 -*-
"""Rule-by-rule tests for check_hr over synthetic 표준근로계약서 packs.

Every rule gets both halves: a positive fixture where the violation is present,
and a still-catches negative where a legitimate document must NOT be failed.
Several fixtures cascade (deleting a whole sheet loses its clauses, its option
slots and its text at once), so each test asserts on the CODE it is about rather
than on an exact finding list.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MODULE_ROOT = _HERE.parent
_REPO_ROOT = _MODULE_ROOT.parents[1]
for _dir in (_MODULE_ROOT / "scripts", _REPO_ROOT / "engine" / "scripts",
             _REPO_ROOT / "pipeline" / "scripts", _HERE):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import check_hr as ch  # noqa: E402
import hr_fixtures as fx  # noqa: E402


def codes(verdict, key="hard"):
    return [row["code"] for row in verdict[key]]


@pytest.fixture()
def blank(tmp_path):
    return fx.write_hr(tmp_path / "blank.hwpx", fx.BLANK)


@pytest.fixture()
def blank2013(tmp_path):
    return fx.write_hr(tmp_path / "blank2013.hwpx", fx.BLANK_2013)


@pytest.fixture()
def filled(tmp_path):
    return fx.write_hr(tmp_path / "filled.hwpx", fx.FILLED)


@pytest.fixture()
def fill_map_file(tmp_path):
    """What the operator declared: the two phone numbers the prompt supplied."""
    return fx.write_fill_map(tmp_path / "fill.json", {
        "employer_phone": "031-000-0000",
        "worker_phone": "010-0000-0000",
    })


# --------------------------------------------------------------------------- #
# R0 — inputs
# --------------------------------------------------------------------------- #
class TestInputs:
    def test_missing_artifact_is_hard_not_a_silent_pass(self, tmp_path):
        verdict, code = ch.check(tmp_path / "nope.hwpx")
        assert code == 3
        assert codes(verdict) == ["artifact_missing"]

    def test_non_zip_is_a_usage_refusal(self, tmp_path):
        path = tmp_path / "plain.hwpx"
        path.write_text("not a zip", encoding="utf-8")
        _verdict, code = ch.check(path)
        assert code == 2

    def test_malformed_section_is_hard_and_stops_structure_checks(self, tmp_path):
        broken = fx.write_hr(tmp_path / "broken.hwpx", fx.BLANK, malformed=True)
        verdict, code = ch.check(broken)
        assert code == 3
        assert codes(verdict) == ["artifact_malformed"]

    def test_a_document_that_is_not_a_contract_is_refused(self, tmp_path):
        other = fx.write_not_a_contract(tmp_path / "report.hwpx")
        verdict, code = ch.check(other)
        assert code == 3
        assert codes(verdict) == ["hr_structure_absent"]

    def test_bad_mode_is_a_usage_refusal(self, blank):
        _verdict, code = ch.check(blank, mode="nonsense")
        assert code == 2

    def test_unreadable_vocabulary_is_a_usage_refusal(self, blank, tmp_path):
        _verdict, code = ch.check(blank, vocabulary=tmp_path / "absent.json")
        assert code == 2

    def test_the_checker_never_writes_to_its_input(self, filled, blank):
        before = (filled.read_bytes(), blank.read_bytes())
        ch.check(filled, baseline=blank)
        assert (filled.read_bytes(), blank.read_bytes()) == before


# --------------------------------------------------------------------------- #
# document state
# --------------------------------------------------------------------------- #
class TestDocumentState:
    def test_pristine_pack_is_blank_and_is_reported_not_failed(self, blank):
        verdict, code = ch.check(blank, baseline=blank)
        assert code == 0
        assert verdict["document"]["state"] == "blank"
        assert verdict["document"]["marked_slots"] == 0
        assert verdict["document"]["party_seats_filled"] == 0
        assert verdict["document"]["unfilled_date_seats"] >= 1

    def test_printed_parentheticals_do_not_make_a_blank_form_a_draft(self,
                                                                    blank):
        """The trap this pair taught: the broad slot class matches '(서명)',
        '(전화 :' and friends, so classifying state by it reported every blank
        form as a draft. State uses the narrow mark-glyph class instead."""
        vocabulary = ch.load_vocabulary()
        model = ch.document_model(blank)
        slots = ch.slot_counts(model, vocabulary)
        assert slots["occupied"] >= 1, "the broad class must see them"
        assert slots["glyph_marks"] == 0, "the narrow class must not"

    def test_a_dated_filled_contract_is_final(self, filled, blank):
        verdict, _code = ch.check(filled, baseline=blank)
        assert verdict["document"]["state"] == "final"

    def test_written_but_undated_is_draft(self, tmp_path, blank):
        draft = fx.write_hr(tmp_path / "draft.hwpx", fx.FILLED,
                            date_row=fx.BLANK["date_row"])
        verdict, _code = ch.check(draft, baseline=blank)
        assert verdict["document"]["state"] == "draft"

    def test_a_filled_contract_is_not_blank_even_without_a_baseline(self,
                                                                   filled):
        """The party-seat term. Without it the no-baseline path had no evidence
        of writing at all in a family with no checkbox culture, and a completed
        contract read as blank-by-design."""
        verdict, _code = ch.check(filled)
        assert verdict["document"]["state"] != "blank"
        assert verdict["document"]["party_seats_filled"] >= 4

    def test_생년월일_is_not_mistaken_for_an_unfilled_date_seat(self, blank):
        """'생년월일' is contiguous; the seat is '  년   월   일'."""
        vocabulary = ch.load_vocabulary()
        assert ch._findall_raw(vocabulary["unfilled_date_seat_re"],
                               "   생년월일 :") == []
        assert ch._findall_raw(vocabulary["unfilled_date_seat_re"],
                               "      년      월      일")

    def test_a_written_date_is_not_an_unfilled_date_seat(self):
        vocabulary = ch.load_vocabulary()
        assert ch._findall_raw(vocabulary["unfilled_date_seat_re"],
                               "     2026년   8월   20일") == []

    def test_a_written_time_is_not_an_unfilled_time_seat(self):
        vocabulary = ch.load_vocabulary()
        assert ch._findall_raw(vocabulary["unfilled_time_seat_re"],
                               "09시 00분 ~ 18시 00분") == []
        assert ch._findall_raw(vocabulary["unfilled_time_seat_re"],
                               "  시  분 ~   시  분")

    def test_mode_forces_the_state(self, blank):
        verdict, _code = ch.check(blank, baseline=blank, mode="final")
        assert verdict["document"]["state"] == "blank"
        assert verdict["document"]["state_used"] == "final"


# --------------------------------------------------------------------------- #
# R1 — numbered-clause skeleton
# --------------------------------------------------------------------------- #
class TestClauseSkeleton:
    def test_a_correct_fill_keeps_the_whole_skeleton(self, filled, blank,
                                                    fill_map_file):
        verdict, code = ch.check(filled, baseline=blank,
                                 fill_map=fill_map_file)
        assert code == 0, verdict["hard"]
        assert any(row.get("seat") == "clause_block"
                   and row["state"] == "intact" for row in verdict["seats"])

    def test_a_deleted_clause_is_hard(self, tmp_path, blank):
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK,
                             clauses=fx.BLANK["clauses"][:-1])
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "clause_lost" in codes(verdict)

    def test_a_renumbered_clause_is_hard(self, tmp_path, blank):
        shifted = [text.replace("5.", "6.", 1) if text.startswith("5.")
                   else text for text in fx.BLANK["clauses"]]
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, clauses=shifted)
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "clause_renumbered" in codes(verdict)

    def test_a_deleted_contract_block_is_hard(self, tmp_path, blank):
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, clauses=[],
                             wage_rows=[])
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "clause_block_lost" in codes(verdict)

    def test_a_non_contiguous_baseline_is_not_failed_for_being_non_contiguous(
            self, tmp_path):
        """The 2013 단시간 sheet runs 1,2,3,4,5,6,8,9 on the PRISTINE form — its
        clause 7 is written mid-paragraph. 'Numbers must run 1..N' would fail
        the blank form, so the inventory comes from the baseline instead."""
        gapped = [text for text in fx.BLANK["clauses"]
                  if not text.startswith("7.")]
        form = fx.write_hr(tmp_path / "gapped.hwpx", fx.BLANK, clauses=gapped)
        verdict, code = ch.check(form, baseline=form)
        assert code == 0, verdict["hard"]
        blocks = ch.clause_blocks(ch.document_model(form), ch.load_vocabulary())
        assert [row["number"] for row in blocks[0]] == [1, 2, 3, 4, 5, 6, 8,
                                                        9, 10, 11]

    def test_a_letter_spaced_clause_label_is_matched(self, blank):
        """'2. 근 무 장 소 :' — the form letter-spaces its own labels."""
        blocks = ch.clause_blocks(ch.document_model(blank),
                                  ch.load_vocabulary())
        labels = [row["label"] for row in blocks[0]]
        assert labels[1] and " " not in labels[1]

    def test_without_a_baseline_the_skeleton_rules_say_so(self, filled):
        verdict, _code = ch.check(filled)
        undecided = {row["rule"] for row in verdict["skipped"]
                     if row["reason"] == "no_baseline"}
        assert {"clause_lost", "clause_renumbered",
                "clause_block_lost"} <= undecided
        assert any(row.get("seat") == "clause_inventory"
                   for row in verdict["seats"])


# --------------------------------------------------------------------------- #
# R2 — contract variants
# --------------------------------------------------------------------------- #
class TestContractVariants:
    def test_a_correct_fill_keeps_every_variant(self, filled, blank,
                                                fill_map_file):
        verdict, _code = ch.check(filled, baseline=blank,
                                  fill_map=fill_map_file)
        titles = {row["title"] for row in verdict["seats"]
                  if row.get("seat") == "contract_variant"}
        assert len(titles) == 2

    def test_deleting_a_variant_banner_is_hard(self, tmp_path, blank):
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK,
                             banner_consent=None)
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "contract_variant_lost" in codes(verdict)

    def test_a_numbered_clause_naming_a_consent_form_is_not_a_variant(
            self, tmp_path):
        """'8. 가족관계증명서 및 동의서' is a CLAUSE in a top-level paragraph.
        Counting it as a variant banner made one sheet look like two, which is
        why the recognizer reads table cells only."""
        form = fx.write_hr(
            tmp_path / "x.hwpx", fx.BLANK,
            clauses=fx.BLANK["clauses"] + ["12. 가족관계증명서 및 동의서"])
        titles = ch.contract_titles(ch.document_model(form),
                                    ch.load_vocabulary())
        assert len(titles) == 2

    def test_without_a_baseline_the_variant_rule_says_so(self, filled):
        verdict, _code = ch.check(filled)
        assert "contract_variant_lost" in {
            row["rule"] for row in verdict["skipped"]
            if row["reason"] == "no_baseline"}


# --------------------------------------------------------------------------- #
# R3 — the seats, and the text around them
# --------------------------------------------------------------------------- #
class TestSeats:
    def test_a_correct_fill_keeps_every_stencil_fragment(self, filled, blank,
                                                         fill_map_file):
        verdict, code = ch.check(filled, baseline=blank,
                                 fill_map=fill_map_file)
        assert code == 0, verdict["hard"]
        assert any(row.get("seat") == "clause_text"
                   and row["state"] == "intact" for row in verdict["seats"])

    def test_consuming_a_legal_sentence_is_hard(self, tmp_path, blank):
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK,
                             legal_rows=fx.BLANK["legal_rows"][1:])
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "clause_text_consumed" in codes(verdict)

    def test_filling_a_letter_spaced_party_seat_is_not_consumed_text(
            self, tmp_path, blank, fill_map_file):
        """The reason the stencil splits on colons as well as blank runs:
        '주    소 :' carries a four-space run of its own, so a blank-run-only
        split fused it with the '대 표 자 :' below and filling 주소 separated
        them — a HARD finding on a correct fill."""
        form = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK,
                           employer_rows=fx.FILLED["employer_rows"])
        verdict, _code = ch.check(form, baseline=blank, fill_map=fill_map_file)
        assert "clause_text_consumed" not in codes(verdict)

    def test_deleting_an_option_is_hard(self, tmp_path, blank):
        thinned = [text.replace(",   없음 [    ]", "")
                   for text in fx.BLANK["wage_rows"]]
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, wage_rows=thinned)
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "option_slot_lost" in codes(verdict)

    def test_marking_an_option_keeps_the_slot_count(self, filled, blank):
        vocabulary = ch.load_vocabulary()
        before = ch.slot_counts(ch.document_model(blank), vocabulary)
        after = ch.slot_counts(ch.document_model(filled), vocabulary)
        assert after["total"] >= before["total"]
        assert after["glyph_marks"] > before["glyph_marks"]

    def test_an_unfilled_seat_is_reported_and_never_hard(self, tmp_path, blank,
                                                         fill_map_file):
        """The family's own asymmetry. Failing a document for an empty
        임금지급일 is how a tool learns to invent one."""
        partial = fx.write_hr(tmp_path / "x.hwpx", fx.FILLED,
                              wage_rows=fx.BLANK["wage_rows"])
        verdict, code = ch.check(partial, baseline=blank, mode="final",
                                 fill_map=fill_map_file)
        assert code == 0, verdict["hard"]
        assert "seat_unfilled" in codes(verdict, "warn")

    def test_a_blank_pack_is_not_warned_for_being_unfilled(self, blank):
        verdict, _code = ch.check(blank, baseline=blank)
        assert codes(verdict, "warn") == []
        assert {row["rule"]: row["reason"] for row in verdict["skipped"]}[
            "seat_unfilled"] == "document_state_blank"

    def test_without_a_baseline_the_preservation_seat_rules_say_so(self,
                                                                  filled):
        verdict, _code = ch.check(filled)
        undecided = {row["rule"] for row in verdict["skipped"]
                     if row["reason"] == "no_baseline"}
        assert {"clause_text_consumed", "option_slot_lost"} <= undecided


# --------------------------------------------------------------------------- #
# R4 — the two-party signature block
# --------------------------------------------------------------------------- #
class TestParties:
    def test_a_pristine_pack_reads_both_parties_blank_by_design(self, blank):
        verdict, code = ch.check(blank, baseline=blank)
        assert code == 0
        pairs = [row for row in verdict["seats"]
                 if row.get("seat") == "party_pair"]
        assert pairs and all(row["state"] == "both_blank" for row in pairs)

    def test_a_correct_fill_reads_both_parties_filled(self, filled, blank,
                                                      fill_map_file):
        verdict, code = ch.check(filled, baseline=blank,
                                 fill_map=fill_map_file)
        assert code == 0, verdict["hard"]
        assert any(row.get("seat") == "party_pair"
                   and row["state"] == "both_filled"
                   for row in verdict["seats"])

    def test_half_a_party_is_hard_in_a_final_document(self, tmp_path, blank,
                                                      fill_map_file):
        half = fx.write_hr(tmp_path / "x.hwpx", fx.FILLED,
                           worker_rows=fx.BLANK["worker_rows"])
        verdict, code = ch.check(half, baseline=blank, mode="final",
                                 fill_map=fill_map_file)
        assert code == 3
        assert "party_half_filled" in codes(verdict)

    def test_half_a_party_only_warns_in_a_draft(self, tmp_path, blank,
                                                fill_map_file):
        half = fx.write_hr(tmp_path / "x.hwpx", fx.FILLED,
                           worker_rows=fx.BLANK["worker_rows"],
                           date_row=fx.BLANK["date_row"])
        verdict, code = ch.check(half, baseline=blank, fill_map=fill_map_file)
        assert code == 0, verdict["hard"]
        assert "party_half_filled" in codes(verdict, "warn")

    def test_half_a_party_is_decidable_without_a_baseline(self, tmp_path,
                                                          fill_map_file):
        """A value in one party's seats and nothing in the other's is a defect
        on the artifact's own evidence — no blank form needed."""
        half = fx.write_hr(tmp_path / "x.hwpx", fx.FILLED,
                           worker_rows=fx.BLANK["worker_rows"])
        verdict, code = ch.check(half, mode="final", fill_map=fill_map_file)
        assert code == 3
        assert "party_half_filled" in codes(verdict)
        assert "party_half_filled" not in {row["rule"]
                                           for row in verdict["skipped"]}

    def test_deleting_a_signature_marker_is_hard(self, tmp_path, blank):
        stripped = [text.replace("(서명)", "") for text in fx.BLANK["worker_rows"]]
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK,
                             worker_rows=stripped)
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "signature_marker_lost" in codes(verdict)

    def test_writing_the_partys_name_beside_the_marker_is_allowed(
            self, filled, blank, fill_map_file):
        verdict, _code = ch.check(filled, baseline=blank,
                                  fill_map=fill_map_file)
        assert "signature_marker_lost" not in codes(verdict)
        assert any(row.get("seat") == "signature"
                   and row["state"] == "reserved" for row in verdict["seats"])

    def test_deleting_a_party_block_is_hard(self, tmp_path, blank):
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, worker_rows=[])
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "party_block_lost" in codes(verdict)

    def test_the_opening_sentence_is_not_a_party_block(self, blank):
        """'(이하 “사업주”라 함)과(와)' names 사업주 but carries no marker and no
        seat label; treating it as a block made the pristine form read filled."""
        blocks = ch.party_blocks(ch.document_model(blank), ch.load_vocabulary())
        assert len(blocks) == 2
        assert [row["party"] for row in blocks] == ["employer", "worker"]

    def test_a_party_block_spread_over_three_paragraphs_is_one_block(self,
                                                                     blank):
        blocks = ch.party_blocks(ch.document_model(blank), ch.load_vocabulary())
        assert all(len(row["texts"]) == 3 for row in blocks)

    def test_a_party_block_collapsed_into_one_paragraph_is_one_block(
            self, tmp_path):
        """The 2025 revision writes all three seats in a single paragraph with
        line breaks, which extract to one string."""
        collapsed = fx.write_hr(
            tmp_path / "x.hwpx", fx.BLANK,
            employer_rows=["".join(fx.BLANK["employer_rows"])],
            worker_rows=["".join(fx.BLANK["worker_rows"])])
        blocks = ch.party_blocks(ch.document_model(collapsed),
                                 ch.load_vocabulary())
        assert [row["party"] for row in blocks] == ["employer", "worker"]
        values = ch.party_seat_values(blocks[0], ch.load_vocabulary())
        assert len(values) >= 3
        assert all(not row["value"] for row in values)


# --------------------------------------------------------------------------- #
# R5 — statutory floor references
# --------------------------------------------------------------------------- #
class TestStatute:
    def test_a_correct_fill_keeps_every_citation_verbatim(self, filled, blank,
                                                          fill_map_file):
        verdict, _code = ch.check(filled, baseline=blank,
                                  fill_map=fill_map_file)
        row = next(entry for entry in verdict["seats"]
                   if entry.get("seat") == "statute")
        assert row["state"] == "verbatim"
        assert "제17조" in row["articles"]

    def test_losing_an_article_citation_is_hard(self, tmp_path, blank):
        stripped = [text.replace("(근로기준법 제17조 이행)", "")
                    for text in fx.BLANK["legal_rows"]]
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK,
                             legal_rows=stripped)
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "statute_reference_lost" in codes(verdict)

    def test_thinning_a_law_name_is_hard(self, tmp_path, blank):
        thinned = [text.replace("근로관계법령", "관계 규정")
                   for text in fx.BLANK["legal_rows"]]
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK,
                             legal_rows=thinned)
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "statute_reference_lost" in codes(verdict)

    def test_inventing_an_article_citation_is_hard(self, tmp_path, blank):
        """A citation nobody put in the form is a fabricated legal claim."""
        rewritten = [text.replace("제17조", "제19조")
                     for text in fx.BLANK["legal_rows"]]
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK,
                             legal_rows=rewritten)
        verdict, code = ch.check(broken, baseline=blank)
        assert code == 3
        assert "statute_reference_invented" in codes(verdict)

    def test_without_a_baseline_the_statute_rules_say_so(self, filled):
        verdict, _code = ch.check(filled)
        undecided = {row["rule"] for row in verdict["skipped"]
                     if row["reason"] == "no_baseline"}
        assert {"statute_reference_lost",
                "statute_reference_invented"} <= undecided
        assert any(row.get("seat") == "statute" and row["state"] == "reported"
                   for row in verdict["seats"])


# --------------------------------------------------------------------------- #
# R6 — the versioned pair
# --------------------------------------------------------------------------- #
class TestTemplateVersion:
    def test_each_revision_is_detected_on_its_own_evidence(self, blank,
                                                            blank2013):
        vocabulary = ch.load_vocabulary()
        assert ch.template_version(ch.document_model(blank),
                                   vocabulary)["version"] == "v2025"
        assert ch.template_version(ch.document_model(blank2013),
                                   vocabulary)["version"] == "v2013"

    def test_mixing_two_revisions_vocabulary_is_hard_without_a_baseline(
            self, tmp_path):
        spliced = fx.write_hr(
            tmp_path / "x.hwpx", fx.BLANK,
            wage_rows=fx.BLANK["wage_rows"] + fx.BLANK_2013["wage_rows"])
        verdict, code = ch.check(spliced)
        assert code == 3
        assert "template_version_mixed" in codes(verdict)
        assert "template_version_mixed" not in {row["rule"]
                                               for row in verdict["skipped"]}

    def test_migrating_a_contract_to_another_revision_is_hard(self, blank,
                                                               blank2013):
        verdict, code = ch.check(blank2013, baseline=blank)
        assert code == 3
        assert "template_version_changed" in codes(verdict)

    def test_a_correct_fill_stays_on_its_revision(self, filled, blank,
                                                  fill_map_file):
        verdict, _code = ch.check(filled, baseline=blank,
                                  fill_map=fill_map_file)
        assert "template_version_changed" not in codes(verdict)
        assert "template_version_mixed" not in codes(verdict)

    def test_without_a_baseline_only_the_drift_rule_says_so(self, filled):
        verdict, _code = ch.check(filled)
        undecided = {row["rule"] for row in verdict["skipped"]
                     if row["reason"] == "no_baseline"}
        assert "template_version_changed" in undecided
        assert "template_version_mixed" not in undecided


# --------------------------------------------------------------------------- #
# R7 — the privacy rule
# --------------------------------------------------------------------------- #
class TestIdentity:
    def test_an_undeclared_rrn_is_hard_without_any_baseline(self, tmp_path):
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, consent_rows=[
            "○ 친권자(후견인) 인적사항", "   성    명 :",
            "   생년월일 : 900101-1234567", "   연 락 처 :"])
        verdict, code = ch.check(broken)
        assert code == 3
        assert "identity_value_invented" in codes(verdict)
        assert "identity_value_invented" not in {row["rule"]
                                                for row in verdict["skipped"]}

    @pytest.mark.parametrize("wrap", [False, True])
    def test_either_fill_map_shape_declares_the_same_values(
            self, tmp_path, blank, wrap):
        """T35: ONE file must serve this checker and visual_verify alike.

        ``--fill-map`` is one flag name, so both shapes it is documented to
        accept must work here too — a bare ``{key: value}`` map and a wrapper
        object carrying a ``fill_map`` member (a visual_verify expectations
        file). Shape handling is core's ``check_residue.load_fill_map``.
        """
        mapping = {"guardian_rrn": "900101-1234567"}
        declared = fx.write_fill_map(
            tmp_path / f"fill{int(wrap)}.json",
            {"fill_map": mapping, "base_pt": 10} if wrap else mapping)
        form = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, consent_rows=[
            "○ 친권자(후견인) 인적사항", "   성    명 :",
            "   생년월일 : 900101-1234567", "   연 락 처 :"])
        verdict, code = ch.check(form, baseline=blank, fill_map=declared)
        assert code == 0, verdict["hard"]

    def test_a_wrapper_with_a_non_object_fill_map_is_a_usage_refusal(
            self, tmp_path, filled):
        """The wrapper must not degrade into "the wrapper IS the map"."""
        path = fx.write_fill_map(tmp_path / "nullmap.json",
                                 {"fill_map": None, "base_pt": 10})
        verdict, code = ch.check(filled, fill_map=path)
        assert code == 2
        assert "'fill_map' member" in verdict["error"]
        assert "BARE" in verdict["error"] and "WRAPPER" in verdict["error"]

    def test_a_declared_rrn_passes(self, tmp_path, blank):
        declared = fx.write_fill_map(tmp_path / "fill.json",
                                     {"guardian_rrn": "900101-1234567"})
        form = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, consent_rows=[
            "○ 친권자(후견인) 인적사항", "   성    명 :",
            "   생년월일 : 900101-1234567", "   연 락 처 :"])
        verdict, code = ch.check(form, baseline=blank, fill_map=declared)
        assert code == 0, verdict["hard"]

    def test_an_undeclared_account_shape_is_hard_without_any_baseline(
            self, tmp_path):
        """The 계좌번호 half. This family has no 계좌번호 SEAT at all — only the
        지급방법 clause naming an account — so the rule is a value-shape rule."""
        broken = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, worker_rows=[
            "(근로자) 주    소 :", "        연 락 처 : 110-234-567890",
            "        성    명 :                   (서명)"])
        verdict, code = ch.check(broken)
        assert code == 3
        assert "personal_number_invented" in codes(verdict)

    def test_a_declared_account_shape_passes(self, tmp_path, blank):
        declared = fx.write_fill_map(tmp_path / "fill.json",
                                     {"account": "110-234-567890"})
        form = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, worker_rows=[
            "(근로자) 주    소 :", "        연 락 처 : 110-234-567890",
            "        성    명 :                   (서명)"])
        verdict, code = ch.check(form, baseline=blank, fill_map=declared)
        assert code == 0, verdict["hard"]

    def test_a_money_amount_is_not_an_account_number(self, filled, blank,
                                                     fill_map_file):
        """'2,800,000원' is comma-grouped and has no run of ten contiguous
        digits; treating it as an account number would fail every wage fill."""
        verdict, code = ch.check(filled, baseline=blank,
                                 fill_map=fill_map_file)
        assert code == 0, verdict["hard"]
        assert "personal_number_invented" not in codes(verdict)

    def test_a_short_date_shape_stays_below_the_floor(self):
        vocabulary = ch.load_vocabulary()
        hits = ch._findall_raw(vocabulary["personal_number_re"], "2026-09-01")
        digits = [sum(c.isdigit() for c in hit) for hit in hits]
        assert all(count < vocabulary["personal_number_min_digits"]
                   for count in digits)

    def test_an_undeclared_phone_number_is_a_finding(self, tmp_path):
        """A phone number the operator DID supply is declared and passes; one the
        tool made up is exactly what the rule is for."""
        form = fx.write_hr(tmp_path / "x.hwpx", fx.FILLED)
        verdict, code = ch.check(form)
        assert code == 3
        assert "personal_number_invented" in codes(verdict)

    def test_a_value_written_into_an_empty_identity_seat_is_hard(self,
                                                                 tmp_path,
                                                                 blank):
        form = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, consent_rows=[
            "○ 친권자(후견인) 인적사항", "   성    명 :",
            "   생년월일 : 1990. 1. 1.", "   연 락 처 :"])
        verdict, code = ch.check(form, baseline=blank)
        assert code == 3
        assert "identity_seat_autofilled" in codes(verdict)

    def test_a_correct_fill_leaves_the_identity_seats_empty(self, filled,
                                                            blank,
                                                            fill_map_file):
        verdict, code = ch.check(filled, baseline=blank,
                                 fill_map=fill_map_file)
        assert code == 0, verdict["hard"]
        assert "identity_seat_autofilled" not in codes(verdict)

    def test_prose_naming_an_account_is_not_an_identity_seat(self, tmp_path):
        """The 지급방법 sentence mentions 예금통장 inside a hundred characters and
        is not a place a number goes."""
        form = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, legal_rows=[
            *fx.BLANK["legal_rows"],
            "  - 임금 및 수당은 “근로자”에게 직접 지불하거나 “근로자”의 명의로 된 "
            "예금통장에 입금한다. “사업주”는 근로자의 명의로 된 예금통장, 도장을 "
            "관리해서는 안 된다."])
        seats = ch.identity_seats(ch.document_model(form), ch.load_vocabulary())
        assert "예금통장" not in seats

    def test_a_seat_count_change_is_reported_not_guessed(self, tmp_path, blank):
        form = fx.write_hr(tmp_path / "x.hwpx", fx.BLANK, consent_rows=[
            "○ 친권자(후견인) 인적사항", "   성    명 :", "   연 락 처 :"])
        verdict, _code = ch.check(form, baseline=blank)
        reasons = [row for row in verdict["skipped"]
                   if row["rule"] == "identity_seat_autofilled"]
        assert reasons and reasons[0]["reason"] == "seat_count_drift"


# --------------------------------------------------------------------------- #
# verdict shape
# --------------------------------------------------------------------------- #
class TestVerdictShape:
    def test_the_verdict_is_json_serializable_and_counts_agree(self, filled,
                                                                blank):
        verdict, _code = ch.check(filled, baseline=blank)
        json.dumps(verdict, ensure_ascii=False)
        assert verdict["counts"]["hard"] == len(verdict["hard"])
        assert verdict["counts"]["warn"] == len(verdict["warn"])
        assert verdict["counts"]["seats"] == len(verdict["seats"])
        assert verdict["counts"]["skipped"] == len(verdict["skipped"])
        assert verdict["checker"] == "check_hr"

    def test_a_baseline_leaves_nothing_undecided(self, filled, blank):
        without, _code = ch.check(filled)
        undecided = {row["rule"] for row in without["skipped"]
                     if row["reason"] == "no_baseline"}
        assert len(undecided) == 12, sorted(undecided)
        with_baseline, _code = ch.check(filled, baseline=blank)
        assert {row["rule"] for row in with_baseline["skipped"]
                if row["reason"] == "no_baseline"} == set()

    def test_the_cli_writes_the_verdict_and_returns_the_checker_code(
            self, filled, blank, tmp_path, capsys):
        out = tmp_path / "verdict.json"
        code = ch.main([str(filled), "--baseline", str(blank),
                        "--out", str(out)])
        capsys.readouterr()
        assert code in (0, 3)
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["checker"] == "check_hr"
