# -*- coding: utf-8 -*-
"""The minwon module's side of the distribution-module contract.

The claim that matters for a *work-type* module: minwon is not a report add-on
and not a gongmun add-on. It declares no ``requires_modules``, its payload
imports nothing from another module, and enabling it ALONE — with report, style
AND gongmun all present on disk but disabled — surfaces its checker. This mirrors
``pipeline/tests/test_module_registry.py``'s
``TestSelectiveEnablementIndependence``, over the real ``modules/`` tree with a
temporary ``enabled.yaml`` (never the repo's).

It also pins the two properties this module's design rests on: the vocabulary is
DATA (no Korean literal decides a rule), and there is deliberately NO pack type.
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
import check_minwon  # noqa: E402

MODULES_ROOT = _REPO_ROOT / "modules"


def registry_with(tmp_path: Path, names) -> ModuleRegistry:
    enabled = tmp_path / "enabled.yaml"
    enabled.write_text(
        "schema: rigorloom-enabled-modules/v1\n"
        f"enabled: [{', '.join(names)}]\n",
        encoding="utf-8",
    )
    return ModuleRegistry(MODULES_ROOT, enabled_file=enabled)


class TestIndependence:
    def test_minwon_declares_no_module_dependency(self, tmp_path):
        registry = registry_with(tmp_path, ["minwon"])
        assert registry.summary()["requires_modules"]["minwon"] == []

    def test_minwon_enables_without_report_and_without_gongmun(self, tmp_path):
        """A work-type module must stand alone — no report, no style, and no
        sibling work-type module either."""
        registry = registry_with(tmp_path, ["minwon"])
        assert {"minwon", "gongmun", "report", "style"} <= set(
            registry.discover())
        assert [spec.name for spec in registry.enabled_modules()] == ["minwon"]
        checkers = registry.enabled_checkers()
        assert {row["name"] for row in checkers} == {"check_minwon"}
        assert registry.enabled_pack_types() == []
        contributions = (
            checkers + registry.enabled_cli() + registry.enabled_run_modes()
            + registry.enabled_gate_kinds() + registry.enabled_studio_panels()
            + registry.enabled_preflight() + registry.enabled_playbooks())
        assert all(row["module"] == "minwon" for row in contributions)

    def test_the_two_work_type_modules_coexist_without_collision(self, tmp_path):
        """Both enabled: distinct checker names, no shared pack type, and each
        contribution still attributed to its own module."""
        registry = registry_with(tmp_path, ["gongmun", "minwon"])
        assert {spec.name for spec in registry.enabled_modules()} == {
            "gongmun", "minwon"}
        checkers = registry.enabled_checkers()
        assert {row["name"] for row in checkers} == {"check_gongmun",
                                                     "check_minwon"}
        assert registry.enabled_pack_types() == ["gongmun_org"]

    def test_minwon_contributes_nothing_when_disabled(self, tmp_path):
        registry = registry_with(tmp_path, ["gongmun"])
        assert "minwon" in registry.discover()
        assert [spec.name for spec in registry.enabled_modules()] == ["gongmun"]
        assert "check_minwon" not in {row["name"]
                                      for row in registry.enabled_checkers()}

    def test_payload_imports_no_other_module(self):
        """Dependency points one way: core only, never a sibling module."""
        sources = sorted((_MODULE_ROOT / "scripts").glob("*.py"))
        assert sources
        for source in sources:
            text = source.read_text(encoding="utf-8")
            for sibling in ("report", "style", "gongmun"):
                assert f"modules/{sibling}" not in text
                assert f"modules.{sibling}" not in text
                assert f"check_{sibling}" not in text

    def test_checker_only_imports_core_helpers(self):
        """The module reaches core through the documented one mechanism."""
        text = (_MODULE_ROOT / "scripts" / "check_minwon.py").read_text(
            encoding="utf-8")
        assert 'CORE_SCRIPTS_DIR = INSTALL_ROOT / "pipeline" / "scripts"' in text
        assert 'ENGINE_SCRIPTS_DIR = INSTALL_ROOT / "engine" / "scripts"' in text


class TestDeclaration:
    def test_declaration_matches_the_payload_on_disk(self, tmp_path):
        registry = registry_with(tmp_path, ["minwon"])
        spec = registry.discover()["minwon"]
        assert spec.name == "minwon"
        for entry in spec.provides["checkers"]:
            assert spec.payload_path(entry["script"]).is_file()
        skill = spec.provides["skill"]
        assert spec.payload_path(skill["fragment"]).is_file()
        for reference in skill.get("references", []):
            assert spec.payload_path(reference).is_file()

    def test_the_checker_declares_that_it_wants_the_blank_baseline(self,
                                                                  tmp_path):
        registry = registry_with(tmp_path, ["minwon"])
        row = next(entry for entry in registry.enabled_checkers()
                   if entry["name"] == "check_minwon")
        assert row["wants"] == ["baseline"]
        source = (_MODULE_ROOT / "scripts" / "check_minwon.py").read_text(
            encoding="utf-8")
        assert '"--baseline"' in source

    def test_the_declaration_matches_what_a_baseline_actually_changes(
            self, tmp_path):
        """The declaration is only honest if it tracks behaviour. Without a
        baseline nine rules self-skip for ``no_baseline``; supplying one makes
        every one of them decidable. If a baseline stopped changing anything,
        ``wants: [baseline]`` would be a lie — and this fails.

        (Which rule needs it, one by one, is ``test_check_minwon.py``'s job.)
        """
        import minwon_fixtures as fx  # noqa: PLC0415 — module-local fixture

        document = fx.write_minwon(tmp_path / "filled.hwpx", fx.FILLED)
        blank = fx.write_minwon(tmp_path / "blank.hwpx", fx.BLANK)

        without, _code = check_minwon.check(document)
        undecided = {row["rule"] for row in without["skipped"]
                     if row["reason"] == "no_baseline"}
        assert undecided, "no rule reports no_baseline — wants: [baseline] " \
                          "would be declaring a need that does not exist"

        with_baseline, _code = check_minwon.check(document, baseline=blank)
        still_undecided = {row["rule"] for row in with_baseline["skipped"]
                           if row["reason"] == "no_baseline"}
        assert still_undecided == set(), still_undecided

    def test_the_privacy_rule_is_not_gated_behind_the_baseline(self, tmp_path):
        """``identity_value_invented`` must fire on its own evidence. Gating the
        one privacy rule behind an optional input the caller can forget would
        make the module's headline claim conditional."""
        import minwon_fixtures as fx  # noqa: PLC0415

        document = fx.write_minwon(tmp_path / "rrn.hwpx", fx.FILLED,
                                   rrn_value="900101-1234567")
        verdict, code = check_minwon.check(document)
        assert code == 3
        assert "identity_value_invented" in {row["code"]
                                            for row in verdict["hard"]}
        assert "identity_value_invented" not in {row["rule"]
                                                for row in verdict["skipped"]}

    def test_no_pack_type_is_declared_and_that_is_deliberate(self, tmp_path):
        """A 민원 서식's 접수 기관 is printed by the regulation and the applicant's
        data is per-document personal data. There is no per-operator vocabulary
        to pack, and inventing one would create the very store of personal data
        the identity rules exist to prevent — so the declaration says nothing and
        the module.yaml comment explains why."""
        registry = registry_with(tmp_path, ["minwon"])
        spec = registry.discover()["minwon"]
        assert "pack_types" not in spec.provides
        assert registry.enabled_pack_types() == []
        packs = _MODULE_ROOT / "references" / "preference_packs"
        assert not packs.exists()
        declaration = (_MODULE_ROOT / "module.yaml").read_text(encoding="utf-8")
        assert "NO pack_types" in declaration

    def test_the_declaration_provides_only_what_it_has(self, tmp_path):
        registry = registry_with(tmp_path, ["minwon"])
        spec = registry.discover()["minwon"]
        assert set(spec.provides) == {"checkers", "skill"}

    def test_visual_expectations_payload_is_valid_json_and_inverts_gongmun(self):
        """A 민원 서식 has almost nothing forbidden and a lot to keep — the
        opposite balance to gongmun.json, and the file says so."""
        path = (_MODULE_ROOT / "references" / "visual_expectations"
                / "minwon.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        vocabulary = check_minwon.load_vocabulary()
        assert len(payload["intentionally_blank"]) > len(
            payload["forbidden_text"])
        blank_seats = set(payload["intentionally_blank"])
        assert set(check_minwon._terms(vocabulary, "staff", "labels")) & \
            blank_seats
        assert set(check_minwon._terms(vocabulary, "identity", "labels")) & \
            blank_seats
        # nothing on the keep-list may appear in forbidden_text
        forbidden = " ".join(payload["forbidden_text"])
        for label in check_minwon.keep_labels(vocabulary):
            assert label not in forbidden


class TestVocabularyIsData:
    def test_vocabulary_is_data_not_code(self):
        """No Korean literal belongs in the checker: the table is the vocabulary."""
        text = (_MODULE_ROOT / "scripts" / "check_minwon.py").read_text(
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
            assert "_findall(" not in line

    def test_no_magic_threshold_lives_in_the_checker(self):
        """Both numeric discriminators are declared values with their measured
        corpus numbers written down beside them."""
        vocabulary = check_minwon.load_vocabulary()
        assert vocabulary["shaded_face_max_brightness"] == 0.86
        assert vocabulary["identity_seat_max_cell_chars"] == 40
        assert "shaded_face_brightness_note" in vocabulary
        assert "identity_seat_note" in vocabulary

    @pytest.mark.parametrize("key", [
        "sections", "family_minimum", "byeolji_header_re", "paper_spec_re",
        "unfilled_date_seat_re", "unmarked_glyph_re", "marked_glyph_re",
        "select_instruction_re", "shading_declaration_re",
        "signature_marker_re", "rrn_re", "placeholder_glyph_re", "noise_re",
        "shaded_face_max_brightness", "identity_value_min_length",
        "identity_seat_max_cell_chars",
    ])
    def test_vocabulary_carries_every_key_the_rules_read(self, key):
        assert key in check_minwon.load_vocabulary()

    @pytest.mark.parametrize("section", [
        "furniture", "staff", "select", "guide", "human", "identity"])
    def test_every_declared_section_exists(self, section):
        assert section in check_minwon.load_vocabulary()["sections"]

    def test_every_regex_compiles_and_a_broken_one_is_loud(self, tmp_path):
        vocabulary = check_minwon.load_vocabulary()
        broken = dict(vocabulary)
        broken["rrn_re"] = "(unclosed"
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(check_minwon.MinwonError) as excinfo:
            check_minwon.load_vocabulary(path)
        assert "rrn_re" in str(excinfo.value)

    def test_an_out_of_range_brightness_threshold_is_loud(self, tmp_path):
        broken = dict(check_minwon.load_vocabulary())
        broken["shaded_face_max_brightness"] = 42
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8")
        with pytest.raises(check_minwon.MinwonError):
            check_minwon.load_vocabulary(path)

    def test_the_staff_labels_exclude_the_addressee_term(self):
        """접수기관 lives only in '(접수 기관의 장) 귀하', which an agent SHOULD
        replace. Listing it as a staff label made a correct fill a HARD."""
        vocabulary = check_minwon.load_vocabulary()
        labels = check_minwon._terms(vocabulary, "staff", "labels")
        assert "접수기관" not in labels
        assert "접수번호" in labels

    def test_the_keep_list_and_the_staff_labels_are_distinct_concerns(self):
        vocabulary = check_minwon.load_vocabulary()
        keep = set(check_minwon.keep_labels(vocabulary))
        staff = set(check_minwon._terms(vocabulary, "staff", "labels"))
        assert keep and staff
        assert not keep & staff
