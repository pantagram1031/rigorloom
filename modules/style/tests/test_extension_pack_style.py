# -*- coding: utf-8 -*-
"""The humanization controller consumes the canonical extension resolution.

Moved from tests/test_extension_pack.py (v0.16 W4.2): the controller under
test is style-module payload; the extension-pack machinery it consumes stays
core (scripts/extension_pack.py + personalization_ctl). Synthetic packs only.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_MODULE_ROOT = Path(__file__).parents[1]
_REPO_ROOT = Path(__file__).parents[3]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


extension_pack = _load(
    "extension_pack_for_style_tests", _REPO_ROOT / "scripts" / "extension_pack.py")
humanization = _load(
    "humanization_ctl_for_style_tests",
    _MODULE_ROOT / "scripts" / "humanization_ctl.py")


def _prose_pack(name: str, marker: str) -> dict:
    return {
        "schema": "report-pipeline/preference-pack/prose_rules-v1",
        "pack_type": "prose_rules",
        "name": name,
        "version": 1,
        "banned_patterns": [
            {
                "id": f"marker-{name}",
                "regex": marker,
                "severity": "hard",
                "description": "synthetic extension marker",
            }
        ],
    }


def _extension(root: Path, *, marker: str) -> Path:
    extension_id = "example.report-style"
    packs = root / "packs"
    packs.mkdir(parents=True)
    (packs / "prose_rules.json").write_text(
        json.dumps(_prose_pack(extension_id, marker), ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "rigorloom/extension-pack-v1",
                "id": extension_id,
                "version": "1.0.0",
                "kind": "data-pack",
                "rigorloom_api": 1,
                "priority": 100,
                "description": "synthetic test extension",
                "packs": {"prose_rules": "packs/prose_rules.json"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return root


def test_humanization_consumes_the_canonical_extension_resolution(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    source = _extension(tmp_path / "source", marker="HUMANIZE_EXTENSION_MARKER")
    extension_pack.install_pack(source, profile)

    resolved = humanization._merged_pack(profile, "prose_rules")

    assert resolved["name"] == "example.report-style"
    assert resolved["banned_patterns"][0]["regex"] == "HUMANIZE_EXTENSION_MARKER"
