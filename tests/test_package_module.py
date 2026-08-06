"""Tests for scripts/package_module.py (v0.16 plan §3.5).

A throwaway distribution module built in tmp_path (the S1 fixture pattern)
is bundled, its manifest hashes verify, tampering is detected, and both
refusal paths (invalid/missing payload = config, privacy HARD = findings)
are loud. Everything lives in tmp_path — no repo module is special-cased.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


package_module = _load(
    "package_module", REPO_ROOT / "scripts" / "package_module.py")

DUMMY_CHECKER = (
    "import json, sys\n"
    "print(json.dumps({'ok': True, 'checker': 'dummy_probe',"
    " 'hard': [], 'warn': [], 'counts': {'hard': 0, 'warn': 0}}))\n"
    "sys.exit(0)\n"
)

MANIFEST = """\
schema: rigorloom-module/v1
name: throwaway
requires: { rigorloom: ">=0.1" }
provides:
  checkers:
    - { name: dummy_probe, script: scripts/check_dummy.py }
  gate_kinds:
    - { kind: dummy_kind, checker: dummy_probe }
  pack_types:
    - dummy_pack
  playbooks:
    - references/play.md
"""


def make_module(root: Path, name: str = "throwaway",
                manifest: str = MANIFEST) -> Path:
    module = root / name
    (module / "scripts").mkdir(parents=True)
    (module / "references").mkdir(parents=True)
    (module / "scripts" / "check_dummy.py").write_text(
        DUMMY_CHECKER, encoding="utf-8")
    (module / "references" / "play.md").write_text("play\n", encoding="utf-8")
    (module / "module.yaml").write_text(manifest, encoding="utf-8")
    return module


def build(tmp_path: Path, **kwargs) -> Path:
    return package_module.build_bundle(
        kwargs.pop("name", "throwaway"),
        tmp_path / "dist",
        modules_root=tmp_path / "modules",
        version=kwargs.pop("version", "0.16.0"),
        **kwargs,
    )


class TestModuleBundle:
    def test_bundle_layout_manifest_and_hashes(self, tmp_path: Path):
        make_module(tmp_path / "modules")
        bundle = build(tmp_path)

        assert bundle.name == "rigorloom-throwaway-0.16.0.zip"
        with zipfile.ZipFile(bundle) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("MANIFEST.json"))
            module_yaml = archive.read("modules/throwaway/module.yaml")

        assert "INSTALL.md" in names
        assert "modules/throwaway/scripts/check_dummy.py" in names
        assert manifest["schema"] == "rigorloom-bundle-manifest/v1"
        assert manifest["name"] == "throwaway"
        assert manifest["version"] == "0.16.0"
        assert manifest["requires"] == {"rigorloom": ">=0.1"}
        assert manifest["provides"]["checkers"] == ["dummy_probe"]
        assert manifest["provides"]["gate_kinds"] == ["dummy_kind"]
        assert manifest["provides"]["pack_types"] == ["dummy_pack"]
        assert manifest["provides"]["playbooks"] == 1

        listed = {entry["path"]: entry["sha256"]
                  for entry in manifest["files"]}
        assert "MANIFEST.json" not in listed
        assert "INSTALL.md" in listed
        expected = hashlib.sha256(module_yaml).hexdigest()
        assert listed["modules/throwaway/module.yaml"] == expected

        report, code = package_module.verify_bundle(bundle)
        assert code == 0 and report["ok"], report

    def test_tampered_file_and_unlisted_file_fail_verification(
            self, tmp_path: Path):
        make_module(tmp_path / "modules")
        bundle = build(tmp_path)
        extracted = tmp_path / "extracted"
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(extracted)

        target = extracted / "modules" / "throwaway" / "references" / "play.md"
        target.write_text("tampered\n", encoding="utf-8")
        (extracted / "modules" / "throwaway" / "smuggled.txt").write_text(
            "extra\n", encoding="utf-8")

        report, code = package_module.verify_bundle(extracted)
        assert code == 3 and not report["ok"]
        problems = {item["path"]: item["problem"]
                    for item in report["problems"]}
        assert problems["modules/throwaway/references/play.md"] == "hash_mismatch"
        assert problems["modules/throwaway/smuggled.txt"] == "not_in_manifest"

    def test_invalid_module_yaml_is_config_refusal(self, tmp_path: Path):
        make_module(tmp_path / "modules",
                    manifest="schema: wrong/v1\nname: throwaway\n"
                             'requires: { rigorloom: ">=0.1" }\n'
                             "provides: {}\n")
        with pytest.raises(package_module.module_registry.ModuleError):
            build(tmp_path)
        code = package_module.main([
            "--module", "throwaway",
            "--out", str(tmp_path / "dist"),
            "--modules-root", str(tmp_path / "modules"),
        ])
        assert code == 2
        assert not list((tmp_path / "dist").glob("*.zip")) \
            if (tmp_path / "dist").exists() else True

    def test_missing_declared_payload_is_refusal(self, tmp_path: Path):
        module = make_module(tmp_path / "modules")
        (module / "references" / "play.md").unlink()
        with pytest.raises(package_module.PackageError,
                           match="play.md"):
            build(tmp_path)

    def test_unknown_module_is_refusal(self, tmp_path: Path):
        make_module(tmp_path / "modules")
        with pytest.raises(package_module.PackageError,
                           match="no distribution module named"):
            build(tmp_path, name="nonexistent")

    def test_privacy_hard_finding_refuses_the_build(self, tmp_path: Path):
        module = make_module(tmp_path / "modules")
        # a binary document in module payload is a privacy_scan HARD
        # finding (binary_document_ext) — bundles never ship it
        (module / "references" / "filled_form.hwpx").write_bytes(b"HWPX")
        with pytest.raises(package_module.PackageError) as ctx:
            build(tmp_path)
        assert ctx.value.exit_code == 3
        assert "privacy_scan" in str(ctx.value)
        assert not list((tmp_path / "dist").glob("*.zip")) \
            if (tmp_path / "dist").exists() else True

    def test_profile_store_content_in_payload_refuses_the_build(
            self, tmp_path: Path):
        # v0.16 W4.1 artifact leak gate: personalization-store content in a
        # staged bundle (here a store manifest.json) is a privacy_scan HARD
        # finding (profile_store_content) — the build refuses, exit 3.
        module = make_module(tmp_path / "modules")
        (module / "references" / "leaked-profile.json").write_text(
            json.dumps({"schema": "rigorloom/personalization-v1",
                        "version": 1, "redact_logs": True}),
            encoding="utf-8")
        with pytest.raises(package_module.PackageError) as ctx:
            build(tmp_path)
        assert ctx.value.exit_code == 3
        assert "privacy_scan" in str(ctx.value)
        assert not list((tmp_path / "dist").glob("*.zip")) \
            if (tmp_path / "dist").exists() else True


class TestCoreBundle:
    def test_core_bundle_contains_core_surface_and_no_module_payloads(
            self, tmp_path: Path):
        bundle = package_module.build_bundle(
            "core", tmp_path / "dist", version="0.16.0")
        assert bundle.name == "rigorloom-core-0.16.0.zip"
        with zipfile.ZipFile(bundle) as archive:
            names = archive.namelist()
            manifest = json.loads(archive.read("MANIFEST.json"))

        assert manifest["name"] == "core"
        assert manifest["requires"] is None
        assert manifest["provides"]["core_components"]
        assert any(n.startswith("engine/scripts/") for n in names)
        assert any(n.startswith("pipeline/scripts/") for n in names)
        assert "studio/main.py" in names
        assert "modules/README.md" in names
        # no distribution-module payloads, no test suites
        assert not any(n.startswith("modules/") and n != "modules/README.md"
                       for n in names)
        assert not any("/tests/" in n for n in names)

        report, code = package_module.verify_bundle(bundle)
        assert code == 0, report
