# -*- coding: utf-8 -*-
"""The gongmun module's side of the distribution-module contract.

The claim that matters for a *work-type* module: gongmun is not a report
add-on. It declares no ``requires_modules``, its payload imports nothing from
another module, and enabling it ALONE surfaces its checker and its pack type.
This mirrors ``pipeline/tests/test_module_registry.py``'s
``TestSelectiveEnablementIndependence``, over the real ``modules/`` tree with a
temporary ``enabled.yaml`` (never the repo's).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_MODULE_ROOT = _HERE.parent
_REPO_ROOT = _MODULE_ROOT.parents[1]
for _dir in (_REPO_ROOT / "pipeline" / "scripts", _MODULE_ROOT / "scripts"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from module_registry import ModuleRegistry  # noqa: E402
import personalization_ctl  # noqa: E402
import check_gongmun  # noqa: E402

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
    def test_gongmun_declares_no_module_dependency(self, tmp_path):
        registry = registry_with(tmp_path, ["gongmun"])
        assert registry.summary()["requires_modules"]["gongmun"] == []

    def test_gongmun_enables_without_report(self, tmp_path):
        """A work-type module must stand alone — no report, no style."""
        registry = registry_with(tmp_path, ["gongmun"])
        assert {"gongmun", "report", "style"} <= set(registry.discover())
        assert [spec.name for spec in registry.enabled_modules()] == ["gongmun"]
        checkers = registry.enabled_checkers()
        assert {row["name"] for row in checkers} == {"check_gongmun"}
        assert registry.enabled_pack_types() == ["gongmun_org"]
        contributions = (
            checkers + registry.enabled_cli() + registry.enabled_run_modes()
            + registry.enabled_gate_kinds() + registry.enabled_studio_panels()
            + registry.enabled_preflight() + registry.enabled_playbooks())
        assert all(row["module"] == "gongmun" for row in contributions)

    def test_gongmun_contributes_nothing_when_disabled(self, tmp_path):
        registry = registry_with(tmp_path, ["style"])
        assert "gongmun" in registry.discover()
        assert [spec.name for spec in registry.enabled_modules()] == ["style"]
        assert "check_gongmun" not in {
            row["name"] for row in registry.enabled_checkers()}
        assert "gongmun_org" not in registry.enabled_pack_types()

    def test_payload_imports_no_other_module(self):
        """Dependency points one way: core only, never a sibling module."""
        sources = sorted((_MODULE_ROOT / "scripts").glob("*.py"))
        assert sources
        for source in sources:
            text = source.read_text(encoding="utf-8")
            assert "modules/report" not in text
            assert "modules/style" not in text
            assert "modules.report" not in text
            assert "modules.style" not in text

    def test_checker_only_imports_core_helpers(self):
        """The module reaches core through the documented one mechanism."""
        text = (_MODULE_ROOT / "scripts" / "check_gongmun.py").read_text(
            encoding="utf-8")
        assert 'CORE_SCRIPTS_DIR = INSTALL_ROOT / "pipeline" / "scripts"' in text
        assert 'ENGINE_SCRIPTS_DIR = INSTALL_ROOT / "engine" / "scripts"' in text


class TestDeclaration:
    def test_declaration_matches_the_payload_on_disk(self, tmp_path):
        registry = registry_with(tmp_path, ["gongmun"])
        spec = registry.discover()["gongmun"]
        assert spec.name == "gongmun"
        for entry in spec.provides["checkers"]:
            assert spec.payload_path(entry["script"]).is_file()
        skill = spec.provides["skill"]
        assert spec.payload_path(skill["fragment"]).is_file()
        for reference in skill.get("references", []):
            assert spec.payload_path(reference).is_file()

    def test_pack_type_ships_its_schema_and_default(self, tmp_path):
        """A module-declared pack type resolves through the core convention."""
        packs = _MODULE_ROOT / "references" / "preference_packs"
        schema = packs / "gongmun_org.schema.json"
        default = packs / "defaults" / "gongmun_org.json"
        assert schema.is_file() and default.is_file()
        instance = json.loads(default.read_text(encoding="utf-8"))
        assert instance["pack_type"] == "gongmun_org"
        errors = personalization_ctl.validate_instance(
            instance, json.loads(schema.read_text(encoding="utf-8")))
        assert errors == []

    def test_shipped_default_pack_is_empty_by_design(self):
        """An organization chart is per-install and personal: none ships."""
        instance = json.loads(
            check_gongmun.DEFAULT_PACK.read_text(encoding="utf-8"))
        assert instance["organizations"] == []
        assert instance["departments"] == []
        assert instance["ranks"] == []

    def test_visual_expectations_payload_is_valid_json_and_names_the_residue(
            self):
        path = (_MODULE_ROOT / "references" / "visual_expectations"
                / "gongmun.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        vocabulary = check_gongmun.load_vocabulary()
        forbidden = set(payload["forbidden_text"])
        assert set(check_gongmun.all_placeholders(vocabulary)) <= forbidden
        assert vocabulary["bigo_marker"] in " ".join(forbidden)

    def test_vocabulary_is_data_not_code(self):
        """No Korean literal belongs in the checker: the table is the vocabulary."""
        text = (_MODULE_ROOT / "scripts" / "check_gongmun.py").read_text(
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
            assert "_terms(" not in line and "_contains(" not in line

    @pytest.mark.parametrize("key", [
        "bigo_marker", "bigo_quoted_term_re", "placeholder_glyph_re",
        "issue_number_re", "noise_re", "sections", "family_minimum",
        "human_completed_terms", "seal_border_colors",
    ])
    def test_vocabulary_carries_every_key_the_rules_read(self, key):
        assert key in check_gongmun.load_vocabulary()
