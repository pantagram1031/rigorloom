# -*- coding: utf-8 -*-
"""The hr module's side of the distribution-module contract.

The claim that matters for a *work-type* module: hr is not a report add-on, not a
gongmun add-on, and — the new one — not a minwon add-on. Its privacy rule follows
minwon's precedent and shares no code with it, because module → module imports
are outside the contract. It declares no ``requires_modules``, its payload
imports nothing from another module, and enabling it ALONE — with report, style,
gongmun AND minwon all present on disk but disabled — surfaces its checker.

It also pins the properties this module's design rests on: the vocabulary is DATA
(no Korean literal decides a rule), the versioned pair is declared as two
disjoint fingerprints rather than hardcoded, and there is deliberately NO pack
type.
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
             _REPO_ROOT / "engine" / "scripts", _MODULE_ROOT / "scripts"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from module_registry import ModuleRegistry  # noqa: E402
import check_hr  # noqa: E402

MODULES_ROOT = _REPO_ROOT / "modules"
SIBLINGS = ("report", "style", "gongmun", "minwon")


def registry_with(tmp_path: Path, names) -> ModuleRegistry:
    enabled = tmp_path / "enabled.yaml"
    enabled.write_text(
        "schema: rigorloom-enabled-modules/v1\n"
        f"enabled: [{', '.join(names)}]\n",
        encoding="utf-8",
    )
    return ModuleRegistry(MODULES_ROOT, enabled_file=enabled)


class TestIndependence:
    def test_hr_declares_no_module_dependency(self, tmp_path):
        registry = registry_with(tmp_path, ["hr"])
        assert registry.summary()["requires_modules"]["hr"] == []

    def test_hr_enables_with_every_sibling_present_but_disabled(self, tmp_path):
        """A work-type module must stand alone — no report, no style, and no
        sibling work-type module either."""
        registry = registry_with(tmp_path, ["hr"])
        assert {"hr", *SIBLINGS} <= set(registry.discover())
        assert [spec.name for spec in registry.enabled_modules()] == ["hr"]
        checkers = registry.enabled_checkers()
        assert {row["name"] for row in checkers} == {"check_hr"}
        assert registry.enabled_pack_types() == []
        contributions = (
            checkers + registry.enabled_cli() + registry.enabled_run_modes()
            + registry.enabled_gate_kinds() + registry.enabled_studio_panels()
            + registry.enabled_preflight() + registry.enabled_playbooks())
        assert all(row["module"] == "hr" for row in contributions)

    def test_all_three_work_type_modules_coexist_without_collision(self,
                                                                  tmp_path):
        registry = registry_with(tmp_path, ["gongmun", "minwon", "hr"])
        assert {spec.name for spec in registry.enabled_modules()} == {
            "gongmun", "minwon", "hr"}
        assert {row["name"] for row in registry.enabled_checkers()} == {
            "check_gongmun", "check_minwon", "check_hr"}
        assert registry.enabled_pack_types() == ["gongmun_org"]

    def test_hr_contributes_nothing_when_disabled(self, tmp_path):
        registry = registry_with(tmp_path, ["minwon"])
        assert "hr" in registry.discover()
        assert [spec.name for spec in registry.enabled_modules()] == ["minwon"]
        assert "check_hr" not in {row["name"]
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

    def test_the_privacy_rule_reuses_minwons_pattern_not_its_code(self):
        """``identity_value_invented`` is minwon's rule name and its shape, and
        that is deliberate: a caller who learned it on a 민원 서식 should meet the
        same name here. What must NOT be shared is the implementation."""
        text = (_MODULE_ROOT / "scripts" / "check_hr.py").read_text(
            encoding="utf-8")
        assert "identity_value_invented" in text
        assert "import check_minwon" not in text
        assert "from check_minwon" not in text

    def test_checker_only_imports_core_helpers(self):
        """The module reaches core through the documented one mechanism."""
        text = (_MODULE_ROOT / "scripts" / "check_hr.py").read_text(
            encoding="utf-8")
        assert 'CORE_SCRIPTS_DIR = INSTALL_ROOT / "pipeline" / "scripts"' in text
        assert 'ENGINE_SCRIPTS_DIR = INSTALL_ROOT / "engine" / "scripts"' in text


class TestTestFilenamesAreModulePrefixed:
    def test_every_shipped_test_file_is_prefixed_with_the_module_name(self):
        """The #68 lesson, enforced at source. pytest's prepend import mode
        names a test module after its basename alone, so two modules shipping
        the same test filename collide with 'import file mismatch' and interrupt
        collection — invisible to per-module targeted runs.
        ``pipeline/tests/test_module_registry.py`` proves uniqueness across the
        tree; this asserts the *convention* that keeps it true by construction.
        """
        names = sorted(path.name for path in _HERE.glob("test_*.py"))
        assert names
        assert all(name.startswith("test_hr_") for name in names), names

    def test_no_sibling_module_ships_a_test_with_one_of_these_basenames(self):
        mine = {path.name for path in _HERE.glob("test_*.py")}
        others = {path.name
                  for path in MODULES_ROOT.glob("*/tests/test_*.py")
                  if path.parent.parent.name != "hr"}
        assert mine and others
        assert not (mine & others)


class TestDeclaration:
    def test_declaration_matches_the_payload_on_disk(self, tmp_path):
        registry = registry_with(tmp_path, ["hr"])
        spec = registry.discover()["hr"]
        assert spec.name == "hr"
        for entry in spec.provides["checkers"]:
            assert spec.payload_path(entry["script"]).is_file()
        skill = spec.provides["skill"]
        assert spec.payload_path(skill["fragment"]).is_file()
        for reference in skill.get("references", []):
            assert spec.payload_path(reference).is_file()

    def test_the_checker_declares_that_it_wants_the_blank_baseline(self,
                                                                  tmp_path):
        registry = registry_with(tmp_path, ["hr"])
        row = next(entry for entry in registry.enabled_checkers()
                   if entry["name"] == "check_hr")
        assert row["wants"] == ["baseline"]
        source = (_MODULE_ROOT / "scripts" / "check_hr.py").read_text(
            encoding="utf-8")
        assert '"--baseline"' in source

    def test_the_declaration_matches_what_a_baseline_actually_changes(
            self, tmp_path):
        """The declaration is only honest if it tracks behaviour. Without a
        baseline twelve rules self-skip for ``no_baseline``; supplying one makes
        every one of them decidable. If a baseline stopped changing anything,
        ``wants: [baseline]`` would be a lie — and this fails.

        (Which rule needs it, one by one, is ``test_hr_check.py``'s job.)
        """
        import hr_fixtures as fx  # noqa: PLC0415 — module-local fixture

        document = fx.write_hr(tmp_path / "filled.hwpx", fx.FILLED)
        blank = fx.write_hr(tmp_path / "blank.hwpx", fx.BLANK)

        without, _code = check_hr.check(document)
        undecided = {row["rule"] for row in without["skipped"]
                     if row["reason"] == "no_baseline"}
        assert len(undecided) == 12, sorted(undecided)

        with_baseline, _code = check_hr.check(document, baseline=blank)
        assert {row["rule"] for row in with_baseline["skipped"]
                if row["reason"] == "no_baseline"} == set()

    def test_the_privacy_rules_are_not_gated_behind_the_baseline(self, tmp_path):
        """Both privacy rules must fire on their own evidence. Gating them
        behind an optional input the caller can forget would make the module's
        headline claim conditional."""
        import hr_fixtures as fx  # noqa: PLC0415

        document = fx.write_hr(tmp_path / "rrn.hwpx", fx.FILLED, consent_rows=[
            "○ 친권자(후견인) 인적사항", "   성    명 :",
            "   생년월일 : 900101-1234567", "   연 락 처 :"])
        verdict, code = check_hr.check(document)
        assert code == 3
        found = {row["code"] for row in verdict["hard"]}
        assert {"identity_value_invented", "personal_number_invented"} <= found
        undecided = {row["rule"] for row in verdict["skipped"]}
        assert "identity_value_invented" not in undecided
        assert "personal_number_invented" not in undecided

    def test_no_pack_type_is_declared_and_that_is_deliberate(self, tmp_path):
        """A 근로계약서 looks like it has a per-operator vocabulary (사업체명,
        대표자, 주소 recur for one employer) and must not have one: a repository
        store of one party's data is a standing supply of exactly the
        half-filled contract ``party_half_filled`` exists to catch, and it sits
        next to the two shapes the privacy rule refuses to synthesize."""
        registry = registry_with(tmp_path, ["hr"])
        spec = registry.discover()["hr"]
        assert "pack_types" not in spec.provides
        assert registry.enabled_pack_types() == []
        packs = _MODULE_ROOT / "references" / "preference_packs"
        assert not packs.exists()
        declaration = (_MODULE_ROOT / "module.yaml").read_text(encoding="utf-8")
        assert "NO pack_types" in declaration

    def test_the_declaration_provides_only_what_it_has(self, tmp_path):
        registry = registry_with(tmp_path, ["hr"])
        spec = registry.discover()["hr"]
        assert set(spec.provides) == {"checkers", "skill"}

    def test_visual_expectations_payload_keeps_what_the_family_must_keep(self):
        """This family's text IS the instrument, so forbidden_text is nearly
        empty and intentionally_blank names only what a TOOL must not write."""
        path = (_MODULE_ROOT / "references" / "visual_expectations" / "hr.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        vocabulary = check_hr.load_vocabulary()
        assert len(payload["intentionally_blank"]) > len(
            payload["forbidden_text"])
        blank_seats = set(payload["intentionally_blank"])
        assert set(check_hr._terms(vocabulary, "identity", "labels")) \
            & blank_seats
        # a statute term must never be listed as forbidden or as blank
        for label in check_hr._terms(vocabulary, "statute", "labels"):
            assert label not in " ".join(payload["forbidden_text"])
            assert label not in blank_seats
        # no pack/fill specimen ships here (it would be shipping personal data)
        assert "fill_map" not in payload

    def test_the_skill_fragment_and_flow_doc_name_every_rule(self):
        """A rule nobody documented is a rule nobody can act on. The flow doc's
        rule table must mention every code the checker can emit."""
        flow = (_MODULE_ROOT / "skill" / "references" / "hr_flow.md").read_text(
            encoding="utf-8")
        source = (_MODULE_ROOT / "scripts" / "check_hr.py").read_text(
            encoding="utf-8")
        import re  # noqa: PLC0415
        emitted = set(re.findall(r'_finding\(\s*\n?\s*"([a-z_]+)"', source))
        emitted |= set(re.findall(r'"rule": "([a-z_]+)"', source))
        assert len(emitted) >= 15, sorted(emitted)
        missing = sorted(code for code in emitted if code not in flow)
        assert missing == [], missing


class TestVocabularyIsData:
    def test_vocabulary_is_data_not_code(self):
        """No Korean literal belongs in the checker: the table is the vocabulary."""
        text = (_MODULE_ROOT / "scripts" / "check_hr.py").read_text(
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

    def test_no_magic_threshold_lives_in_the_checker(self):
        """Every numeric discriminator is a declared value with its measured
        corpus number written down beside it."""
        vocabulary = check_hr.load_vocabulary()
        assert vocabulary["stencil_fragment_min_chars"] == 6
        assert vocabulary["clause_label_max_chars"] == 24
        assert vocabulary["contract_title_max_chars"] == 40
        assert vocabulary["identity_seat_max_chars"] == 40
        assert vocabulary["personal_number_min_digits"] == 10
        assert vocabulary["family_minimum"] == 4
        for key in ("stencil_fragment_note", "clause_label_note",
                    "contract_title_note", "identity_seat_note",
                    "personal_number_note", "family_minimum_note",
                    "blank_run_note", "mark_glyph_note", "marked_slot_note",
                    "unfilled_date_seat_note", "unfilled_time_seat_note"):
            assert key in vocabulary, key

    @pytest.mark.parametrize("key", check_hr.REGEX_KEYS)
    def test_vocabulary_carries_every_pattern_the_rules_read(self, key):
        assert key in check_hr.load_vocabulary()

    @pytest.mark.parametrize("section", [
        "contract", "clause", "party", "statute", "identity"])
    def test_every_declared_section_exists(self, section):
        assert section in check_hr.load_vocabulary()["sections"]

    def test_every_regex_compiles_and_a_broken_one_is_loud(self, tmp_path):
        vocabulary = check_hr.load_vocabulary()
        broken = dict(vocabulary)
        broken["rrn_re"] = "(unclosed"
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(check_hr.HrError) as excinfo:
            check_hr.load_vocabulary(path)
        assert "rrn_re" in str(excinfo.value)

    def test_a_non_integer_threshold_is_loud(self, tmp_path):
        broken = dict(check_hr.load_vocabulary())
        broken["stencil_fragment_min_chars"] = "six"
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(check_hr.HrError):
            check_hr.load_vocabulary(path)

    def test_a_single_version_table_is_refused(self, tmp_path):
        """The versioned pair is this family's distinguishing feature. A
        one-version table cannot detect a splice, and silently degrading to
        'version always matches' would be the worst outcome."""
        broken = dict(check_hr.load_vocabulary())
        broken["versions"] = {"v2025": broken["versions"]["v2025"]}
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(check_hr.HrError) as excinfo:
            check_hr.load_vocabulary(path)
        assert "versions" in str(excinfo.value)

    def test_an_empty_marker_list_is_loud(self, tmp_path):
        broken = json.loads(json.dumps(check_hr.load_vocabulary()))
        broken["versions"]["v2013"]["markers"] = []
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(check_hr.HrError):
            check_hr.load_vocabulary(path)

    def test_the_two_version_fingerprints_share_no_marker(self):
        """Overlap would make every document 'mixed'. Disjointness ON THE REAL
        CORPUS is test_hr_corpus.py's job; this is the weaker structural claim
        that no marker string is literally listed twice."""
        vocabulary = check_hr.load_vocabulary()
        names = check_hr.version_names(vocabulary)
        assert len(names) == 2
        first, second = (set(check_hr._markers(vocabulary, name))
                         for name in names)
        assert first and second
        assert not (first & second)

    def test_the_identity_labels_carry_both_revisions_seats(self):
        """2013 asked for 주민등록번호 and 2025 replaced it with 생년월일. A
        vocabulary that dropped either would stop protecting one revision."""
        labels = check_hr._terms(check_hr.load_vocabulary(), "identity",
                                 "labels")
        assert "주민등록번호" in labels
        assert "생년월일" in labels

    def test_the_party_seat_labels_and_the_identity_labels_are_distinct(self):
        """A party seat is something a fill WRITES; an identity seat is
        something it must not."""
        vocabulary = check_hr.load_vocabulary()
        party = set(check_hr._terms(vocabulary, "party", "seat_labels"))
        identity = set(check_hr._terms(vocabulary, "identity", "labels"))
        assert party and identity
        assert not (party & identity)
