# -*- coding: utf-8 -*-
"""The grant module's side of the distribution-module contract.

The claim that matters for the FOURTH work-type module: grant is not a report
add-on, not a style add-on, and not a gongmun / minwon / hr add-on either. It
declares no ``requires_modules``, its payload imports nothing from another
module, and enabling it ALONE — with all five siblings present on disk but
disabled — surfaces its checker and nothing else.

It also pins the properties this module's design rests on: the vocabulary is DATA
(no Korean literal decides a rule), the extendable-table geometry rule compares a
column count and never a cell count, the money-cap idea is reported rather than
gated, and there is deliberately NO pack type.
"""
from __future__ import annotations

import json
import re
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

from module_registry import ModuleRegistry  # noqa: E402
import check_grant as cg  # noqa: E402

MODULES_ROOT = _REPO_ROOT / "modules"
SIBLINGS = ("report", "style", "gongmun", "minwon", "hr")
WORK_TYPES = ("gongmun", "minwon", "hr", "grant")


def registry_with(tmp_path: Path, names) -> ModuleRegistry:
    enabled = tmp_path / "enabled.yaml"
    enabled.write_text(
        "schema: rigorloom-enabled-modules/v1\n"
        f"enabled: [{', '.join(names)}]\n",
        encoding="utf-8",
    )
    return ModuleRegistry(MODULES_ROOT, enabled_file=enabled)


class TestIndependence:
    def test_grant_declares_no_module_dependency(self, tmp_path):
        registry = registry_with(tmp_path, ["grant"])
        assert registry.summary()["requires_modules"]["grant"] == []

    def test_grant_enables_with_every_sibling_present_but_disabled(self,
                                                                  tmp_path):
        """A work-type module must stand alone — no report, no style, and no
        sibling work-type module either."""
        registry = registry_with(tmp_path, ["grant"])
        assert {"grant", *SIBLINGS} <= set(registry.discover())
        assert [spec.name for spec in registry.enabled_modules()] == ["grant"]
        checkers = registry.enabled_checkers()
        assert {row["name"] for row in checkers} == {"check_grant"}
        assert registry.enabled_pack_types() == []
        contributions = (
            checkers + registry.enabled_cli() + registry.enabled_run_modes()
            + registry.enabled_gate_kinds() + registry.enabled_studio_panels()
            + registry.enabled_preflight() + registry.enabled_playbooks())
        assert all(row["module"] == "grant" for row in contributions)

    def test_all_four_work_type_modules_coexist_without_collision(self,
                                                                 tmp_path):
        registry = registry_with(tmp_path, WORK_TYPES)
        assert {spec.name for spec in registry.enabled_modules()} == set(
            WORK_TYPES)
        assert {row["name"] for row in registry.enabled_checkers()} == {
            f"check_{name}" for name in WORK_TYPES}
        assert registry.enabled_pack_types() == ["gongmun_org"]

    def test_grant_contributes_nothing_when_disabled(self, tmp_path):
        registry = registry_with(tmp_path, ["hr"])
        assert "grant" in registry.discover()
        assert [spec.name for spec in registry.enabled_modules()] == ["hr"]
        assert "check_grant" not in {row["name"]
                                     for row in registry.enabled_checkers()}

    def test_payload_imports_no_other_module(self):
        """Dependency points one way: core only, never a sibling module."""
        sources = sorted((_MODULE_ROOT / "scripts").glob("*.py"))
        assert sources
        for source in sources:
            text = source.read_text(encoding="utf-8")
            for sibling in SIBLINGS:
                assert f"modules/{sibling}" not in text
                assert f"modules.{sibling}" not in text
                assert f"import check_{sibling}" not in text

    def test_the_privacy_rule_reuses_minwons_pattern_not_its_code(self):
        """``identity_value_invented`` is minwon's rule name and its shape, and
        that is deliberate: a caller who learned it on a 민원 서식 should meet the
        same name here. What must NOT be shared is the implementation."""
        text = (_MODULE_ROOT / "scripts" / "check_grant.py").read_text(
            encoding="utf-8")
        assert "identity_value_invented" in text
        assert "check_minwon" not in text
        assert "check_hr" not in text

    def test_checker_only_imports_core_helpers(self):
        text = (_MODULE_ROOT / "scripts" / "check_grant.py").read_text(
            encoding="utf-8")
        assert 'CORE_SCRIPTS_DIR = INSTALL_ROOT / "pipeline" / "scripts"' in text
        assert 'ENGINE_SCRIPTS_DIR = INSTALL_ROOT / "engine" / "scripts"' in text


class TestTestFilenamesAreModulePrefixed:
    def test_every_shipped_test_file_is_prefixed_with_the_module_name(self):
        """The #68 lesson, enforced at source. pytest's prepend import mode
        names a test module after its basename alone, so two modules shipping the
        same test filename collide with 'import file mismatch' and interrupt
        collection — invisible to per-module targeted runs.
        ``pipeline/tests/test_module_registry.py`` proves uniqueness across the
        tree; this asserts the *convention* that keeps it true by construction.
        """
        names = sorted(path.name for path in _HERE.glob("test_*.py"))
        assert names
        assert all(name.startswith("test_grant_") for name in names), names

    def test_no_sibling_module_ships_a_test_with_one_of_these_basenames(self):
        mine = {path.name for path in _HERE.glob("test_*.py")}
        others = {path.name
                  for path in MODULES_ROOT.glob("*/tests/test_*.py")
                  if path.parent.parent.name != "grant"}
        assert mine and others
        assert not (mine & others)

    def test_the_fixture_module_is_module_prefixed_too(self):
        """``grant_fixtures.py`` is imported by basename from the tests, so it
        has the same collision surface as a test file."""
        helpers = sorted(path.name for path in _HERE.glob("*.py")
                         if path.name not in {"conftest.py"}
                         and not path.name.startswith("test_"))
        assert helpers == ["grant_fixtures.py"]


class TestDeclaration:
    def test_declaration_matches_the_payload_on_disk(self, tmp_path):
        registry = registry_with(tmp_path, ["grant"])
        spec = registry.discover()["grant"]
        assert spec.name == "grant"
        for entry in spec.provides["checkers"]:
            assert spec.payload_path(entry["script"]).is_file()
        skill = spec.provides["skill"]
        assert spec.payload_path(skill["fragment"]).is_file()
        for reference in skill.get("references", []):
            assert spec.payload_path(reference).is_file()

    def test_the_declaration_provides_only_what_it_has(self, tmp_path):
        registry = registry_with(tmp_path, ["grant"])
        spec = registry.discover()["grant"]
        assert set(spec.provides) == {"checkers", "skill"}

    def test_the_checker_declares_that_it_wants_the_blank_baseline(self,
                                                                  tmp_path):
        registry = registry_with(tmp_path, ["grant"])
        row = next(entry for entry in registry.enabled_checkers()
                   if entry["name"] == "check_grant")
        assert row["wants"] == ["baseline"]
        source = (_MODULE_ROOT / "scripts" / "check_grant.py").read_text(
            encoding="utf-8")
        assert '"--baseline"' in source

    def test_the_declaration_matches_what_a_baseline_actually_changes(
            self, tmp_path):
        """The declaration is only honest if it tracks behaviour. Without a
        baseline six rules self-skip for ``no_baseline``; supplying one makes
        every one of them decidable. If a baseline stopped changing anything,
        ``wants: [baseline]`` would be a lie — and this fails."""
        import grant_fixtures as fx  # noqa: PLC0415 — module-local fixture

        packet = fx.write_grant(tmp_path / "filled.hwpx", fx.FILLED)
        blank = fx.write_grant(tmp_path / "blank.hwpx", fx.BLANK)

        without, _code = cg.check(packet)
        undecided = {row["rule"] for row in without["skipped"]
                     if row["reason"] == "no_baseline"}
        assert len(undecided) == 6, sorted(undecided)

        with_baseline, _code = cg.check(packet, baseline=blank)
        assert {row["rule"] for row in with_baseline["skipped"]
                if row["reason"] == "no_baseline"} == set()

    def test_the_baseline_also_decides_the_document_state(self, tmp_path):
        """The second thing the baseline buys, and the reason it is declared:
        this family's forms ship pre-filled with worked examples, so without the
        blank form there is no evidence of writing to read."""
        import grant_fixtures as fx  # noqa: PLC0415

        packet = fx.write_grant(tmp_path / "filled.hwpx", fx.FILLED)
        blank = fx.write_grant(tmp_path / "blank.hwpx", fx.BLANK)
        without, _c1 = cg.check(packet)
        with_form, _c2 = cg.check(packet, baseline=blank)
        assert without["document"]["state_basis"] == "date_seat_only"
        assert with_form["document"]["state_basis"] == "baseline_diff"

    def test_the_privacy_rules_are_not_gated_behind_the_baseline(self, tmp_path):
        """Both privacy rules must fire on their own evidence. Gating them
        behind an optional input the caller can forget would make the module's
        headline claim conditional."""
        import grant_fixtures as fx  # noqa: PLC0415

        grid = [["구    분", "성    명", "생년월일"],
                ["지원 신청자", "이서준", "900101-1234567"],
                ["계좌번호", "110-234-567890", ""]]
        packet = fx.write_grant(tmp_path / "leak.hwpx", fx.FILLED,
                               applicant_grid=grid)
        verdict, code = cg.check(packet)
        assert code == 3
        found = {row["code"] for row in verdict["hard"]}
        assert {"identity_value_invented", "account_number_invented"} <= found
        undecided = {row["rule"] for row in verdict["skipped"]}
        assert "identity_value_invented" not in undecided
        assert "account_number_invented" not in undecided

    def test_the_packet_and_budget_rules_are_not_gated_either(self, tmp_path):
        """A packet asked about ITSELF needs no second document, and neither
        does a 합계 that must equal its column. Both are the strongest form of
        their rule and both stay baseline-free."""
        import grant_fixtures as fx  # noqa: PLC0415

        packet = fx.write_grant(tmp_path / "p.hwpx", fx.FILLED)
        verdict, _code = cg.check(packet)
        undecided = {row["rule"] for row in verdict["skipped"]
                     if row["reason"] == "no_baseline"}
        assert "packet_reference_dangling" not in undecided
        assert "budget_total_mismatch" not in undecided
        assert "consent_unmarked" not in undecided

    def test_no_pack_type_is_declared_and_that_is_deliberate(self, tmp_path):
        """The seats a 지원사업 pack would cache — 기업명, 대표자명,
        사업자등록번호, 법인등록번호 — sit next to the shapes the privacy rule
        refuses to synthesize, and this family asks for more of them than any
        other."""
        registry = registry_with(tmp_path, ["grant"])
        spec = registry.discover()["grant"]
        assert "pack_types" not in spec.provides
        assert registry.enabled_pack_types() == []
        assert not (_MODULE_ROOT / "references" / "preference_packs").exists()
        declaration = (_MODULE_ROOT / "module.yaml").read_text(encoding="utf-8")
        assert "NO pack_types" in declaration

    def test_visual_expectations_payload_matches_this_familys_asymmetry(self):
        """Unlike 민원, this family's form INSTRUCTS the applicant to remove
        things, so forbidden_text carries real weight — and it is the render-side
        twin of the two residue rules."""
        path = _MODULE_ROOT / "references" / "visual_expectations" / "grant.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["forbidden_text"]
        assert payload["intentionally_blank"]
        vocabulary = cg.load_vocabulary()
        blank_seats = set(payload["intentionally_blank"])
        assert set(cg._terms(vocabulary, "identity", "labels")) & blank_seats
        # the consent choice may not be demanded either way: marking it is the
        # applicant's decision, not the tool's
        for label in cg._terms(vocabulary, "consent", "option_labels"):
            assert label not in blank_seats
            assert label not in payload["forbidden_text"]
        # no page_budget: the corpus declares none (test_grant_corpus.py)
        assert "page_budget" not in payload
        # no fill/pack specimen ships here (it would be shipping personal data)
        assert "fill_map" not in payload

    def test_the_flow_doc_names_every_rule_the_checker_can_emit(self):
        """A rule nobody documented is a rule nobody can act on."""
        flow = (_MODULE_ROOT / "skill" / "references"
                / "grant_flow.md").read_text(encoding="utf-8")
        assert len(cg.RULES) == 17
        missing = sorted(code for code in cg.RULES if code not in flow)
        assert missing == [], missing

    def test_the_rule_inventory_and_the_source_cannot_drift_apart(self):
        """``RULES`` is the declared inventory; both directions are checked so it
        can neither grow past the code nor fall behind it."""
        source = (_MODULE_ROOT / "scripts" / "check_grant.py").read_text(
            encoding="utf-8")
        body = source.split("_WS_RE = re.compile", 1)[1]
        emitted = set(re.findall(r'_finding\(\s*\n?\s*"([a-z_]+)"', body))
        emitted |= set(re.findall(r'"rule": "([a-z_]+)"', body))
        emitted |= set(re.findall(r'\("([a-z_]+)",\s*"[a-z_]+_re"', body))
        assert emitted, "no rule literals found — the scan proves nothing"
        assert emitted <= set(cg.RULES), sorted(emitted - set(cg.RULES))
        for code in cg.RULES:
            assert code in body, code

    def test_every_declared_rule_is_reachable_from_a_shipped_fixture(self,
                                                                    tmp_path):
        """The inventory is only meaningful if the suite actually exercises it.
        ``test_grant_check.py`` asserts each rule one at a time; this asserts that
        the set it covers is the whole set."""
        covered = (_HERE / "test_grant_check.py").read_text(encoding="utf-8")
        missing = sorted(code for code in cg.RULES if code not in covered)
        assert missing == [], missing

    def test_the_fragment_names_the_familys_distinguishing_property(self):
        fragment = (_MODULE_ROOT / "skill" / "FRAGMENT.md").read_text(
            encoding="utf-8")
        for code in ("table_column_changed", "packet_reference_dangling",
                     "budget_total_mismatch", "consent_unmarked",
                     "identity_value_invented"):
            assert code in fragment, code


class TestTheGeometryRuleIsColumnBased:
    def test_the_rule_body_compares_columns_and_reports_rows(self):
        """This module's sharpest difference from minwon and hr, asserted at
        source: adding rows is legitimate, so a cell count may never be the
        comparison."""
        source = (_MODULE_ROOT / "scripts" / "check_grant.py").read_text(
            encoding="utf-8")
        body = source.split("def _check_tables", 1)[1].split("\ndef ", 1)[0]
        assert "colCnt" in body
        assert "rows_added" in body
        assert "cells" not in body
        assert "table_cells" not in body

    def test_the_grid_population_requires_a_record_shaped_table(self):
        vocabulary = cg.load_vocabulary()
        assert vocabulary["grid_min_cols"] == 3
        assert vocabulary["header_min_labels"] == 2
        assert 0 < vocabulary["header_match_min_ratio"] <= 1

    def test_a_bad_match_ratio_is_loud(self, tmp_path):
        broken = dict(cg.load_vocabulary())
        broken["header_match_min_ratio"] = 1.5
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(cg.GrantError) as excinfo:
            cg.load_vocabulary(path)
        assert "header_match_min_ratio" in str(excinfo.value)


class TestVocabularyIsData:
    def test_vocabulary_is_data_not_code(self):
        """No Korean literal belongs in the checker: the table is the vocabulary."""
        text = (_MODULE_ROOT / "scripts" / "check_grant.py").read_text(
            encoding="utf-8")
        code_lines = []
        in_docstring = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.endswith('"""'):
                if stripped.count('"""') == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            code_lines.append(line)
        offenders = [line for line in code_lines
                     if any("가" <= char <= "힣" for char in line)
                     and '"' in line.split("#")[0]]
        # Korean appears only inside finding MESSAGES (human-readable text), and
        # never as a term the rules match on — those all come from the table.
        for line in offenders:
            assert "_terms(" not in line
            assert "_contains(" not in line
            assert "_findall_raw(" not in line
            assert "_findall_sq(" not in line
            assert "re.findall" not in line
            assert "re.search" not in line

    def test_no_magic_threshold_lives_in_the_checker(self):
        """Every numeric discriminator is a declared value with its measured
        corpus number written down beside it."""
        vocabulary = cg.load_vocabulary()
        assert vocabulary["grid_min_cols"] == 3
        assert vocabulary["header_min_labels"] == 2
        assert vocabulary["budget_min_addends"] == 1
        assert vocabulary["family_minimum"] == 3
        assert vocabulary["min_options"] == 2
        assert vocabulary["account_number_min_digits"] == 10
        assert vocabulary["optional_lookahead_seats"] == 2
        for key in ("grid_min_cols_note", "header_min_labels_note",
                    "header_match_min_ratio_note", "budget_min_addends_note",
                    "family_minimum_note", "optional_lookahead_seats_note",
                    "account_number_note", "packet_header_note",
                    "packet_reference_note", "amount_note",
                    "box_glyph_note", "option_group_note",
                    "signature_marker_note", "self_deleting_guide_note",
                    "optional_section_note", "example_placeholder_note",
                    "length_budget_note", "budget_cap_note",
                    "blank_run_note", "unfilled_date_seat_note"):
            assert key in vocabulary, key

    @pytest.mark.parametrize("key", cg.REGEX_KEYS)
    def test_vocabulary_carries_every_pattern_the_rules_read(self, key):
        assert key in cg.load_vocabulary()

    @pytest.mark.parametrize("section", [
        "packet", "budget", "consent", "identity", "addressee"])
    def test_every_declared_section_exists(self, section):
        assert section in cg.load_vocabulary()["sections"]

    def test_every_regex_compiles_and_a_broken_one_is_loud(self, tmp_path):
        broken = dict(cg.load_vocabulary())
        broken["rrn_re"] = "(unclosed"
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(cg.GrantError) as excinfo:
            cg.load_vocabulary(path)
        assert "rrn_re" in str(excinfo.value)

    def test_a_non_integer_threshold_is_loud(self, tmp_path):
        broken = dict(cg.load_vocabulary())
        broken["grid_min_cols"] = "three"
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(cg.GrantError):
            cg.load_vocabulary(path)

    def test_an_empty_packet_marker_list_is_refused(self, tmp_path):
        """Packet integrity is this family's distinguishing property. A
        vocabulary with no part markers would silently degrade to 'every
        reference resolves', which is the worst outcome."""
        broken = json.loads(json.dumps(cg.load_vocabulary()))
        broken["sections"]["packet"]["markers"] = []
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(cg.GrantError) as excinfo:
            cg.load_vocabulary(path)
        assert "packet" in str(excinfo.value)

    def test_an_empty_total_label_list_is_refused(self, tmp_path):
        broken = json.loads(json.dumps(cg.load_vocabulary()))
        broken["sections"]["budget"]["total_labels"] = []
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(cg.GrantError):
            cg.load_vocabulary(path)

    def test_소계_is_not_a_total_label(self):
        """A whole-column sum would double-count a nested subtotal, and the
        corpus has none — asserted in test_grant_corpus.py."""
        labels = cg._terms(cg.load_vocabulary(), "budget", "total_labels")
        assert "소계" not in labels

    def test_the_option_labels_are_exact_tokens_not_substrings(self):
        """'예' must be matched as a whole token: it is a substring of
        예비창업자, 예시 and 예정, all of which appear in the corpus."""
        labels = cg._terms(cg.load_vocabulary(), "consent", "option_labels")
        assert "예" in labels
        assert "동의" not in labels  # would swallow 동의함 / 동의하지않음

    def test_the_identity_labels_cover_every_number_the_family_asks_for(self):
        labels = set(cg._terms(cg.load_vocabulary(), "identity", "labels"))
        assert {"주민등록번호", "생년월일", "여권번호", "법인등록번호",
                "사업자등록번호", "계좌번호"} <= labels

    def test_the_packet_markers_and_the_attachment_labels_are_distinct(self):
        """A marker cites a PART by number; an attachment label names the block
        that lists what to submit. Conflating them would make '첨부서류' a
        dangling reference on every form that has one."""
        vocabulary = cg.load_vocabulary()
        markers = set(cg._terms(vocabulary, "packet", "markers"))
        blocks = set(cg._terms(vocabulary, "packet", "attachment_list_labels"))
        assert markers and blocks
        assert not (markers & blocks)
