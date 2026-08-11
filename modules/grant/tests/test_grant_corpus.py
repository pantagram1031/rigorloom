# -*- coding: utf-8 -*-
"""check_grant against the real blank-form corpus (family ⑥).

``tests/test_grant_check.py`` proves the rules on synthetic fixtures. This file
proves they were derived from the actual documents, and it does the two things a
synthetic suite cannot:

1. **Every pristine corpus form comes back clean.** A family module whose rules
   fire on the official blank template has mis-measured the family, and no
   fixture can tell you that.
2. **Every number this module's design rests on is re-derived here**, so the
   design notes in ``references/grant_vocabulary.json`` and
   ``skill/references/grant_flow.md`` cannot rot silently — including the
   *dropped* premises, which are recorded as assertions about the corpus rather
   than as prose nobody re-checks.

The corpus members (``tests/corpus/forms/manifest.json``, family ``grant``):

| slug | what it contributes |
|---|---|
| ``kstartup-jiwon-sincheongseo-saeopgyehoekseo`` | the hybrid: 42 tables / 366 cells, 3 ``【별첨 N】`` sections, 2 external ``붙임`` citations, 3 budget tables with Hancom ``=SUM()`` 합계 rows, 2 pre-marked required consents, 6 signature seats |
| ``pps-hyeopeop-seungin-sinchengseo`` | native .hwpx; one 9-column 19-row grid with a 참여기업 roster and a 첨부서류 list citing a SEPARATE 별지서식 |
| ``pps-jeongbogonggae-donguiseo`` | native .hwpx; the consent form — two glyph-less ``(예, 아니오)`` choices and two ``□`` SECTION BULLETS |
"""
from __future__ import annotations

import re
import sys
import zipfile
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

CORPUS = _REPO_ROOT / "tests" / "corpus" / "forms"
KSTARTUP = (CORPUS / "converted"
            / "kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx")
HYEOPEOP = CORPUS / "grant" / "pps-hyeopeop-seungin-sinchengseo.hwpx"
DONGUISEO = CORPUS / "grant" / "pps-jeongbogonggae-donguiseo.hwpx"
GRANT_FORMS = (KSTARTUP, HYEOPEOP, DONGUISEO)

#: Other families, converted to .hwpx by XC-1. Used for the boundary test.
OTHER = {
    "gongmun-1": CORPUS / "converted" / "gianmun-byeolji-1ho.hwpx",
    "gongmun-2": CORPUS / "converted" / "gianmun-byeolji-2ho.hwpx",
    "hr-2013": CORPUS / "converted" / "moel-pyojun-geunrogyeyakseo-2013.hwpx",
    "hr-2025": CORPUS / "converted" / "moel-pyojun-geunrogyeyakseo-2025.hwpx",
    "research": CORPUS / "converted" / "nrf-gyeolgwa-bogoseo-yangsik.hwpx",
}
#: The 민원 별지서식. These DO clear the structure gate, deliberately — see
#: ``family_minimum_note`` in the vocabulary.
PETITION = {
    "jumin": CORPUS / "converted" / "jumin-deungchobon-sinchengseo.hwpx",
    "jeongbo": CORPUS / "converted" / "jeongbo-gonggae-cheongguseo.hwpx",
    "saeopja": CORPUS / "converted" / "saeopja-deungnok-sinchengseo.hwpx",
    "admrul": CORPUS / "converted"
              / "admrul-gajokdolbom-hyuga-sinchengseo.hwpx",
}

pytestmark = pytest.mark.skipif(
    not all(path.is_file() for path in GRANT_FORMS),
    reason="blank-form corpus (family grant) is not present in this checkout")

_TR_RE = re.compile(r"<hp:tr>(?:(?!<hp:tr>).)*?</hp:tr>", re.S)
_SECTION_RE = re.compile(r"^Contents/section\d*\.xml$", re.IGNORECASE)


@pytest.fixture(scope="module")
def vocabulary() -> dict:
    return cg.load_vocabulary()


@pytest.fixture(scope="module")
def models(vocabulary) -> dict:
    return {path.stem: cg.document_model(path) for path in GRANT_FORMS}


def rewrite(source: Path, target: Path, transform) -> Path:
    """A copy of ``source`` with every section XML passed through ``transform``."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive, \
            zipfile.ZipFile(target, "w") as out:
        for item in archive.infolist():
            data = archive.read(item.filename)
            if _SECTION_RE.match(item.filename.replace("\\", "/")):
                data = transform(data.decode("utf-8")).encode("utf-8")
            out.writestr(item, data)
    return target


def codes(verdict: dict, bucket: str = "hard") -> list:
    return [row["code"] for row in verdict[bucket]]


# --------------------------------------------------------------------------- #
# 1. every pristine form is clean
# --------------------------------------------------------------------------- #
class TestPristineFormsAreClean:
    @pytest.mark.parametrize("path", GRANT_FORMS, ids=lambda p: p.stem[:24])
    def test_no_rule_fires_on_the_official_blank_form(self, path):
        verdict, code = cg.check(path)
        assert code == 0, verdict["hard"]
        assert verdict["hard"] == []
        assert verdict["warn"] == []

    @pytest.mark.parametrize("path", GRANT_FORMS, ids=lambda p: p.stem[:24])
    def test_no_rule_fires_with_the_form_as_its_own_baseline(self, path):
        """The shape the eval harness uses when it checks the blank form: every
        preservation rule becomes decidable and every one of them must pass."""
        verdict, code = cg.check(path, baseline=path)
        assert code == 0, verdict["hard"]
        assert verdict["warn"] == []
        assert {row["rule"] for row in verdict["skipped"]
                if row["reason"] == "no_baseline"} == set()
        assert verdict["document"]["state_basis"] == "baseline_diff"
        assert verdict["document"]["seats_changed"] == 0

    @pytest.mark.parametrize("path", GRANT_FORMS, ids=lambda p: p.stem[:24])
    def test_a_pristine_form_classifies_blank_not_draft(self, path):
        """All three carry an unfilled date seat and none has been written in."""
        verdict, _code = cg.check(path)
        assert verdict["document"]["state"] == "blank"
        assert verdict["document"]["unfilled_date_seats"] >= 2


# --------------------------------------------------------------------------- #
# 2. the measured numbers the design rests on
# --------------------------------------------------------------------------- #
class TestMeasuredKstartup:
    """The largest and most heterogeneous corpus document, re-derived."""

    def test_the_probe_shape_still_holds(self, models):
        model = models[KSTARTUP.stem]
        assert len(model["tables"]) == 42
        assert sum(len(table["cells"]) for table in model["tables"]) == 366

    def test_all_six_seat_families_are_present(self, models, vocabulary):
        assert cg.rule_families(models[KSTARTUP.stem], vocabulary) == [
            "packet", "budget", "consent", "signature", "addressee", "grid"]

    def test_the_packet_marker_classes_split_internal_from_external(
            self, models, vocabulary):
        classes = cg.packet_marker_classes(models[KSTARTUP.stem], vocabulary)
        assert classes["별첨"]["internal"] is True
        assert {row["number"] for row in classes["별첨"]["headers"]} == {
            "1", "2-1", "2-2"}
        assert {row["number"] for row in classes["별첨"]["references"]} == {"2-1"}
        # 붙임3 and 붙임5 live in the 공고문, not in this file. This is the fact
        # that killed "every 붙임/별첨 reference must resolve" as stated.
        assert classes["붙임"]["internal"] is False
        assert {row["number"] for row in classes["붙임"]["references"]} == {
            "3", "5"}
        assert classes["첨부"]["references"] == []

    def test_별지_is_not_a_packet_marker(self, vocabulary):
        """pps-hyeopeop's 첨부서류 cites '[별지 제2호의 8서식] … 1부' — a separately
        published form, not a section of this document. Admitting 별지 would fail
        that pristine form."""
        assert "별지" not in cg._terms(vocabulary, "packet", "markers")

    def test_thirteen_grids_and_none_of_them_is_a_prose_container(
            self, models, vocabulary):
        grids = cg.grid_tables(models[KSTARTUP.stem], vocabulary)
        assert len(grids) == 13
        assert all(grid["colCnt"] >= 3 for grid in grids)
        # every header label is a LABEL, not a paragraph of guidance
        longest = max(len(label) for grid in grids
                      for label in grid["signature"])
        assert longest <= 31, longest

    def test_the_extendable_tables_are_the_ones_with_records(self, models,
                                                            vocabulary):
        grids = {grid["index"]: grid
                 for grid in cg.grid_tables(models[KSTARTUP.stem], vocabulary)}
        # 신청서 예산표 (7 cols), the two 사업비 편성표 (7), 추진일정 (14),
        # 성과목표 (5), 전문가 프로필 (12), 기술이전 의향서 (5)
        assert grids[1]["colCnt"] == 7
        assert grids[11]["colCnt"] == grids[12]["colCnt"] == 7
        assert grids[10]["colCnt"] == 14
        assert grids[31]["colCnt"] == 12

    def test_every_budget_total_balances_on_the_pristine_form(self, models,
                                                             vocabulary):
        """Nine 합계 cells across three tables. The corpus form computes them
        with Hancom ``=SUM()`` fields, which is exactly why an agent that edits
        a budget row without recalculating produces a mismatch — and why this
        rule is worth having."""
        totals = cg.budget_totals(models[KSTARTUP.stem], vocabulary)
        assert len(totals) == 9
        decidable = [row for row in totals if row["decidable"]]
        assert len(decidable) == 8
        assert all(row["total"] == row["sum"] for row in decidable)
        assert {row["total"] for row in decidable} == {
            35000, 30000, 5000, 16000000, 14000000, 5000000, 19000000}

    def test_the_consent_choices_are_two_and_both_are_required(self, models,
                                                              vocabulary):
        groups = cg.consent_groups(models[KSTARTUP.stem], vocabulary)
        assert len(groups) == 2
        assert all(row["glyph_bearing"] and row["required"] and row["marked"]
                   for row in groups)

    def test_thirty_of_the_thirty_two_box_glyphs_are_not_consent_slots(
            self, models, vocabulary):
        """The calibration that keeps this module from demanding that a heading
        be ticked."""
        model = models[KSTARTUP.stem]
        glyphs = (cg._count_sq(vocabulary["box_unmarked_re"], model)
                  + cg._count_sq(vocabulary["box_marked_re"], model))
        assert glyphs == 32
        in_consent = sum(row["options"]
                         for row in cg.consent_groups(model, vocabulary))
        assert in_consent == 4  # two groups × two options
        assert glyphs - in_consent == 28

    def test_six_signature_seats(self, models, vocabulary):
        assert cg.signature_marker_count(models[KSTARTUP.stem],
                                         vocabulary) == 6

    def test_the_three_money_caps_are_extracted(self, models, vocabulary):
        caps = cg.declared_caps(models[KSTARTUP.stem], vocabulary)
        assert set(caps) == {"30,000천원", "1백만원", "2천만원"}

    def test_the_self_deleting_guidance_and_the_stand_ins_are_found(
            self, models, vocabulary):
        model = models[KSTARTUP.stem]
        assert sum(1 for _at, text in cg.iter_seats(model)
                   if cg._findall_sq(vocabulary["self_deleting_guide_re"],
                                     text)) == 1
        assert sum(1 for _at, text in cg.iter_seats(model)
                   if cg._findall_sq(vocabulary["example_placeholder_re"],
                                     text)) == 3


class TestMeasuredPps:
    def test_hyeopeop_is_one_nine_column_grid_with_a_roster(self, models,
                                                            vocabulary):
        grids = cg.grid_tables(models[HYEOPEOP.stem], vocabulary)
        assert len(grids) == 1
        assert grids[0]["colCnt"] == 9
        assert grids[0]["rows"] == 19

    def test_hyeopeop_has_a_packet_family_but_no_internal_sections(
            self, models, vocabulary):
        model = models[HYEOPEOP.stem]
        assert "packet" in cg.rule_families(model, vocabulary)
        assert cg.packet_headers(model, vocabulary) == []
        verdict, _code = cg.check(HYEOPEOP)
        assert {"rule": "packet_reference_dangling",
                "reason": "no_internal_marker_class"} in verdict["skipped"]

    def test_donguiseo_offers_two_glyphless_choices(self, models, vocabulary):
        groups = cg.consent_groups(models[DONGUISEO.stem], vocabulary)
        assert len(groups) == 2
        assert all(not row["glyph_bearing"] and row["basis"] == "tokens"
                   for row in groups)

    def test_donguiseos_two_box_glyphs_are_section_bullets(self, models,
                                                          vocabulary):
        """'□ 개인정보 수집ㆍ이용 내역' is a heading, and A2's judgment criteria
        say so out loud. The checker must agree."""
        model = models[DONGUISEO.stem]
        assert cg._count_sq(vocabulary["box_unmarked_re"], model) == 2
        assert all(not row["glyph_bearing"]
                   for row in cg.consent_groups(model, vocabulary))

    def test_the_glyphless_choices_are_skipped_with_a_reason(self):
        verdict, code = cg.check(DONGUISEO)
        assert code == 0
        row = next(item for item in verdict["skipped"]
                   if item["rule"] == "consent_unmarked")
        assert row["reason"] == "no_mark_glyphs"


# --------------------------------------------------------------------------- #
# 3. the DROPPED premises, as assertions about the corpus
# --------------------------------------------------------------------------- #
class TestDroppedPremises:
    def test_no_corpus_form_declares_a_page_or_character_budget(self, models,
                                                               vocabulary):
        """The landscape write-up predicts '5쪽 이내' for this family
        (docs/research/hwp-usage-landscape.md family ⑥). The corpus — after the
        표준사업계획서 proper turned out to be unreachable and a same-domain 공고
        attachment was substituted — declares none. That is why
        length_budget_unverified is a declared dependency instead of a rule, and
        why references/visual_expectations/grant.json carries no page_budget."""
        for name, model in models.items():
            budgets = cg.length_budgets(model, vocabulary)
            assert budgets == {"pages": [], "chars": []}, name

    def test_the_page_budget_rule_is_permanently_a_skip_on_this_corpus(self):
        for path in GRANT_FORMS:
            verdict, _code = cg.check(path)
            row = next(item for item in verdict["skipped"]
                       if item["rule"] == "length_budget_unverified")
            assert row["reason"] == "not_declared"

    def test_no_pristine_form_carries_a_personal_number_shaped_value(
            self, models, vocabulary):
        """The privacy rule cannot false-positive on the corpus, which is the
        precondition for it being un-gated by the baseline."""
        floor = int(vocabulary["account_number_min_digits"])
        for name, model in models.items():
            rrn = [value for _at, text in cg.iter_seats(model)
                   for value in cg._findall_raw(vocabulary["rrn_re"], text)]
            account = [value for _at, text in cg.iter_seats(model)
                       for value in cg._findall_raw(
                           vocabulary["account_number_re"], text)
                       if sum(char.isdigit() for char in value) >= floor]
            assert rrn == [], (name, rrn)
            assert account == [], (name, account)

    def test_the_family_asks_for_identity_numbers_and_supplies_none(
            self, models, vocabulary):
        """Both halves matter: the seats exist (so the rule has a subject) and
        no value is printed (so any value is the tool's)."""
        labels = {name: cg.identity_labels_present(model, vocabulary)
                  for name, model in models.items()}
        assert "주민등록번호" in labels[KSTARTUP.stem]
        assert "생년월일" in labels[KSTARTUP.stem]
        assert "법인등록번호" in labels[HYEOPEOP.stem]
        assert "사업자등록번호" in labels[HYEOPEOP.stem]

    def test_no_corpus_form_carries_a_소계_subtotal(self, models):
        """Why 소계 is not a total label: a whole-column sum would double-count a
        nested subtotal. The corpus has none, so the rule stays simple."""
        for name, model in models.items():
            assert "소계" not in cg._squeeze(cg.haystack(model)), name


# --------------------------------------------------------------------------- #
# 4. the family boundary, both directions
# --------------------------------------------------------------------------- #
class TestFamilyBoundary:
    @pytest.mark.parametrize("name", sorted(OTHER))
    def test_another_familys_form_is_refused(self, name):
        path = OTHER[name]
        if not path.is_file():
            pytest.skip(f"{name} not converted in this checkout")
        verdict, code = cg.check(path)
        assert code == 3
        assert codes(verdict) == ["grant_structure_absent"]

    @pytest.mark.parametrize("name", sorted(PETITION))
    def test_a_민원_별지서식_clears_the_gate_and_that_is_deliberate(self, name):
        """The overlap is measured, not accidental: pps-hyeopeop IS a 신청서 with
        a 첨부서류 block and is structurally indistinguishable from a 민원 신청서,
        so a threshold that refused these would refuse a corpus member of this
        family. What a 민원 서식 gets from check_grant is a verdict whose
        family-specific rules all skip with a reason — never a false HARD."""
        path = PETITION[name]
        if not path.is_file():
            pytest.skip(f"{name} not converted in this checkout")
        verdict, code = cg.check(path)
        assert code == 0
        assert verdict["hard"] == []
        rules = {row["rule"] for row in verdict["skipped"]}
        assert {"packet_reference_dangling", "budget_total_mismatch",
                "consent_unmarked"} <= rules

    def test_the_gate_is_calibrated_where_the_corpus_puts_it(self, models,
                                                            vocabulary):
        minimum = int(vocabulary["family_minimum"])
        assert minimum == 3
        for name, model in models.items():
            assert len(cg.rule_families(model, vocabulary)) >= minimum, name


# --------------------------------------------------------------------------- #
# 5. every rule bites on the real document, not just on a fixture
# --------------------------------------------------------------------------- #
class TestRulesBiteOnTheRealPacket:
    def test_deleting_a_별첨_header_dangles_its_citations(self, tmp_path):
        path = rewrite(KSTARTUP, tmp_path / "noheader.hwpx",
                       lambda xml: xml.replace("별첨 2-1】", "삭제됨】"))
        verdict, code = cg.check(path, baseline=KSTARTUP)
        assert code == 3
        found = codes(verdict)
        assert "packet_reference_dangling" in found
        assert "packet_section_lost" in found
        dangling = [row for row in verdict["hard"]
                    if row["code"] == "packet_reference_dangling"]
        assert len(dangling) == 3  # the three places 별첨 2-1 is cited

    def test_breaking_a_합계_is_caught_without_a_baseline(self, tmp_path):
        path = rewrite(
            KSTARTUP, tmp_path / "badtotal.hwpx",
            lambda xml: xml.replace("<hp:t>35,000</hp:t>",
                                    "<hp:t>39,000</hp:t>"))
        verdict, code = cg.check(path)
        assert code == 3
        row = next(item for item in verdict["hard"]
                   if item["code"] == "budget_total_mismatch")
        assert (row["total"], row["column_sum"]) == (39000, 35000)

    def test_changing_a_column_count_is_caught(self, tmp_path):
        path = rewrite(KSTARTUP, tmp_path / "dropcol.hwpx",
                       lambda xml: xml.replace('colCnt="7"', 'colCnt="6"', 1))
        verdict, code = cg.check(path, baseline=KSTARTUP)
        assert code == 3
        row = next(item for item in verdict["hard"]
                   if item["code"] == "table_column_changed")
        assert (row["baseline"], row["artifact"]) == (7, 6)

    def test_adding_a_row_to_a_real_roster_passes(self, tmp_path):
        """The property, on the real 42-table document: the artifact is the
        pristine form and the BASELINE is a copy with one roster row removed, so
        the artifact legitimately carries one more row than the form it came
        from. Nothing may fire, and the extension must be reported."""
        def shorten(xml: str) -> str:
            start = xml.index('rowCnt="16"')
            table_start = xml.rindex("<hp:tbl", 0, start)
            table_end = xml.index("</hp:tbl>", start)
            body = xml[table_start:table_end]
            for match in _TR_RE.finditer(body):
                if "<hp:t>" in match.group(0):
                    continue
                trimmed = (body[:match.start()] + body[match.end():]).replace(
                    'rowCnt="16"', 'rowCnt="15"', 1)
                return xml[:table_start] + trimmed + xml[table_end:]
            raise AssertionError("no all-empty roster row to remove")

        shorter = rewrite(KSTARTUP, tmp_path / "shorter.hwpx", shorten)
        verdict, code = cg.check(KSTARTUP, baseline=shorter)
        assert code == 0, verdict["hard"]
        assert verdict["warn"] == []
        added = [row for row in verdict["seats"]
                 if row["seat"] == "grid" and row["rows_added"]]
        assert [row["rows_added"] for row in added] == [1]

    def test_removing_the_consent_options_is_caught(self, tmp_path):
        path = rewrite(
            KSTARTUP, tmp_path / "noconsent.hwpx",
            lambda xml: xml.replace("■동의함    □동의하지 않음", "■동의함"))
        verdict, code = cg.check(path, baseline=KSTARTUP)
        assert code == 3
        assert {"consent_block_lost", "consent_option_lost"} <= set(
            codes(verdict))

    def test_removing_signature_seats_is_caught(self, tmp_path):
        path = rewrite(KSTARTUP, tmp_path / "nosig.hwpx",
                       lambda xml: xml.replace("(인)", "", 2))
        verdict, code = cg.check(path, baseline=KSTARTUP)
        assert code == 3
        row = next(item for item in verdict["hard"]
                   if item["code"] == "signature_seat_lost")
        assert (row["baseline"], row["artifact"]) == (6, 4)

    def test_writing_an_rrn_into_the_생년월일_seat_is_caught(self, tmp_path):
        path = rewrite(
            KSTARTUP, tmp_path / "rrn.hwpx",
            lambda xml: xml.replace("<hp:t>생년월일</hp:t>",
                                    "<hp:t>생년월일 900101-1234567</hp:t>"))
        verdict, code = cg.check(path, baseline=KSTARTUP)
        assert code == 3
        assert "identity_value_invented" in codes(verdict)

    def test_the_same_rrn_passes_once_the_operator_declares_it(self, tmp_path):
        path = rewrite(
            KSTARTUP, tmp_path / "rrn2.hwpx",
            lambda xml: xml.replace("<hp:t>생년월일</hp:t>",
                                    "<hp:t>생년월일 900101-1234567</hp:t>"))
        fill_map = tmp_path / "fill.json"
        fill_map.write_text('{"생년월일": "900101-1234567"}', encoding="utf-8")
        verdict, code = cg.check(path, baseline=KSTARTUP, fill_map=fill_map)
        assert code == 0, verdict["hard"]


# --------------------------------------------------------------------------- #
# T114 — the module's protected_text is DERIVED from the form, not remembered.
# --------------------------------------------------------------------------- #

class TestProtectedTextMatchesTheForm:
    """`protected_text` says "this text is legally required to survive". A list
    of remembered sentences drifts the moment the guide detector moves, and the
    drift is silent because a keep that matches nothing just keeps nothing.

    Measured after T110: the 동의서's REMAINING removal targets are exactly the
    PIPA §22 고지 paragraphs — a 동의서 has no deletable guide text at all. So the
    two sets must be equal, and either side changing is a decision someone has
    to make on purpose.
    """

    EXPECTATIONS = (_MODULE_ROOT / "references" / "visual_expectations"
                    / "grant.json")

    def _declared(self) -> set:
        import json
        payload = json.loads(self.EXPECTATIONS.read_text(encoding="utf-8"))
        return {" ".join(item.split())
                for item in payload["protected_text"]}

    def _removal_targets(self) -> set:
        import form_inspect
        profile, _ = form_inspect.analyze(str(DONGUISEO), want_baseline=False)
        targets = {row["para_idx"] for row in profile["removal_targets"]}
        return {" ".join((row["text"] or "").split())
                for row in profile["guide_text"]
                if row["para_idx"] in targets}

    def test_the_declared_set_equals_the_forms_removal_targets(self):
        declared, actual = self._declared(), self._removal_targets()
        assert declared == actual, {
            "declared_but_not_removable": sorted(declared - actual),
            "removable_but_unprotected": sorted(actual - declared)}

    def test_the_sets_are_non_empty_and_are_the_statutory_notices(self):
        """Non-vacuity: two empty sets are also equal."""
        declared = self._declared()
        assert len(declared) == 3, sorted(declared)
        assert sum(1 for item in declared
                   if "거부할 권리가 있습니다" in item) == 2
        assert any("동의 여부를 결정하여 주십시오" in item for item in declared)

    def test_no_protected_entry_is_also_forbidden(self):
        """The module must not claim both about one string; visual_verify
        refuses that, and this catches it in the payload instead of at run
        time."""
        import json
        payload = json.loads(self.EXPECTATIONS.read_text(encoding="utf-8"))
        assert not (set(payload["protected_text"])
                    & set(payload.get("forbidden_text") or []))
