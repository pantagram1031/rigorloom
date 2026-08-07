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
import types
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


class TestCoreBundleShipsTheSkillSurface:
    """v0.17 regression: the clean-room harness found that the core bundle
    shipped the engine and no skill surface at all — no ``SKILL.md``, no
    references, no installer. A buyer got tooling they could not route.

    These assertions run against the real bundle so the gap cannot come back
    through an edit to ``_CORE_COMPONENTS`` or to the staging code.
    """

    @pytest.fixture(scope="class")
    def core_names(self, tmp_path_factory) -> list[str]:
        bundle = package_module.build_bundle(
            "core", tmp_path_factory.mktemp("dist"), version="0.16.0")
        with zipfile.ZipFile(bundle) as archive:
            return archive.namelist()

    def test_router_skill_and_references_are_in_the_bundle(self, core_names):
        assert "skill/SKILL.md" in core_names
        references = [n for n in core_names
                      if n.startswith("skill/references/") and n.endswith(".md")]
        assert references, core_names
        # every reference the repo carries ships; none is left behind
        expected = sorted(
            f"skill/references/{p.name}"
            for p in (REPO_ROOT / "skill" / "references").glob("*.md"))
        assert sorted(references) == expected

    def test_the_skill_installer_and_its_manifest_example_ship(self, core_names):
        assert "scripts/sync_local.py" in core_names
        assert "scripts/sync_manifest.example.yaml" in core_names
        # the verifier still ships too (it did before; nothing regressed)
        assert "scripts/package_module.py" in core_names

    def test_sync_local_needs_nothing_from_scripts_beyond_itself(self):
        """sync_local imports stdlib only, plus ``module_registry`` loaded by
        path from ``pipeline/scripts`` (already core). If that ever changes,
        the new dependency has to be added to ``_CORE_COMPONENTS`` — this test
        is the tripwire."""
        source = (REPO_ROOT / "scripts" / "sync_local.py").read_text(
            encoding="utf-8")
        sibling_scripts = {
            p.stem for p in (REPO_ROOT / "scripts").glob("*.py")
            if p.name != "sync_local.py"
        }
        for name in sibling_scripts:
            assert f"import {name}" not in source, (
                f"sync_local.py now imports scripts/{name}.py — ship it in "
                "_CORE_COMPONENTS or the installer breaks for a buyer")
        assert "import module_registry" in source
        # module_registry is resolved out of pipeline/scripts, which is core
        assert (REPO_ROOT / "pipeline" / "scripts"
                / "module_registry.py").is_file()

    def test_install_md_documents_the_skill_install_step(self, tmp_path: Path):
        bundle = package_module.build_bundle(
            "core", tmp_path / "dist", version="0.16.0")
        with zipfile.ZipFile(bundle) as archive:
            install_md = archive.read("INSTALL.md").decode("utf-8")
        assert "scripts/sync_local.py" in install_md
        assert "sync_manifest.example.yaml" in install_md
        assert "merge_skill_fragments: true" in install_md
        assert "--checkout-root" in install_md
        # says where the skill lands
        assert "<install_root>/SKILL.md" in install_md

    def test_dropping_the_skill_surface_from_the_components_is_refused(
            self, tmp_path: Path, monkeypatch):
        """The structural half: even if someone edits the component list back
        to the v0.16 contents, packaging refuses instead of shipping."""
        monkeypatch.setattr(
            package_module, "_CORE_COMPONENTS",
            tuple(c for c in package_module._CORE_COMPONENTS
                  if not c.startswith("skill")
                  and c != "scripts/sync_local.py"))
        with pytest.raises(package_module.PackageError) as ctx:
            package_module.build_bundle(
                "core", tmp_path / "dist", version="0.16.0")
        assert ctx.value.exit_code == 3
        assert "skill surface" in str(ctx.value)
        assert not list((tmp_path / "dist").glob("*.zip")) \
            if (tmp_path / "dist").exists() else True


class TestModuleSkillFragmentsShip:
    """A module that declares ``provides.skill`` must carry the fragment and
    its references in its own bundle — otherwise the installer's skill merge
    fails on a file the buyer never received."""

    def test_every_declaring_module_ships_its_fragment_and_references(
            self, tmp_path: Path):
        declaring = []
        for manifest_path in sorted((REPO_ROOT / "modules").glob("*/module.yaml")):
            spec = package_module.module_registry.ModuleRegistry(
                REPO_ROOT / "modules").discover()[manifest_path.parent.name]
            if spec.provides.get("skill"):
                declaring.append(spec)
        assert declaring, "repo must have at least one skill-declaring module"

        for spec in declaring:
            bundle = package_module.build_bundle(
                spec.name, tmp_path / "dist", version="0.16.0")
            with zipfile.ZipFile(bundle) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("MANIFEST.json"))
            skill = spec.provides["skill"]
            wanted = [skill["fragment"], *skill.get("references", [])]
            for relative in wanted:
                assert f"modules/{spec.name}/{relative}" in names, (
                    spec.name, relative)
            assert manifest["provides"]["skill"] is True

    def test_declared_fragment_absent_from_the_payload_is_a_hard_refusal(
            self, tmp_path: Path):
        """Direct test of the packaging assertion: a staged payload that lacks
        a declared fragment must be a loud exit-3 refusal, not a silent ship."""
        staging = tmp_path / "staging"
        (staging / "modules" / "ghost" / "skill").mkdir(parents=True)
        spec = types.SimpleNamespace(
            name="ghost",
            provides={"skill": {"fragment": "skill/FRAGMENT.md",
                                "references": ["skill/references/g.md"]}})
        with pytest.raises(package_module.PackageError) as ctx:
            package_module._assert_module_skill_shipped("ghost", spec, staging)
        assert ctx.value.exit_code == 3
        assert "skill/FRAGMENT.md" in str(ctx.value)

        (staging / "modules" / "ghost" / "skill" / "FRAGMENT.md").write_text(
            "frag\n", encoding="utf-8")
        with pytest.raises(package_module.PackageError,
                           match="skill/references/g.md"):
            package_module._assert_module_skill_shipped("ghost", spec, staging)

        refs = staging / "modules" / "ghost" / "skill" / "references"
        refs.mkdir()
        (refs / "g.md").write_text("ref\n", encoding="utf-8")
        package_module._assert_module_skill_shipped("ghost", spec, staging)

    def test_a_module_without_a_skill_declaration_is_unaffected(
            self, tmp_path: Path):
        make_module(tmp_path / "modules")  # MANIFEST declares no skill
        bundle = build(tmp_path)
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("MANIFEST.json"))
            install_md = archive.read("INSTALL.md").decode("utf-8")
        assert "skill" not in manifest["provides"]
        assert "sync_local.py" not in install_md

    def test_a_declaring_module_install_md_says_to_resync_the_skill(
            self, tmp_path: Path):
        bundle = package_module.build_bundle(
            "style", tmp_path / "dist", version="0.16.0")
        with zipfile.ZipFile(bundle) as archive:
            install_md = archive.read("INSTALL.md").decode("utf-8")
        assert "scripts/sync_local.py" in install_md
        assert "## Module: style" in install_md


class TestCorpusNeverShips:
    """W5.2 privacy ruling #4: tests/corpus/forms is repo-only material.

    The corpus binaries pass privacy_scan only through the sha256-pinned
    allowlist; a bundle is a distribution artifact where no allowlist applies,
    so no corpus member may ever be staged into any bundle. Module bundles
    include their OWN tests only.
    """

    def test_no_corpus_member_in_core_or_any_real_module_bundle(
            self, tmp_path: Path):
        corpus_dir = REPO_ROOT / "tests" / "corpus" / "forms"
        corpus_members = {
            p.name for p in corpus_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in (".hwp", ".hwpx")
        }
        assert corpus_members, "corpus must exist for this test to bite"

        registry_names = sorted(
            p.parent.name
            for p in (REPO_ROOT / "modules").glob("*/module.yaml"))
        assert registry_names, "repo must declare distribution modules"

        for name in ["core", *registry_names]:
            bundle = package_module.build_bundle(
                name, tmp_path / "dist", version="0.16.0")
            with zipfile.ZipFile(bundle) as archive:
                names = archive.namelist()
            assert not any("tests/corpus/forms" in n for n in names), name
            assert not any(
                n.rsplit(".", 1)[-1].lower() in ("hwp", "hwpx")
                for n in names), name
            assert not any(Path(n).name in corpus_members for n in names), name
            if name != "core":
                # module bundles carry only their own directory (+ metadata)
                payload = [n for n in names
                           if n not in ("MANIFEST.json", "INSTALL.md")]
                assert all(n.startswith(f"modules/{name}/") for n in payload), name

    def test_module_bundle_keeps_own_tests_only(self, tmp_path: Path):
        module = make_module(tmp_path / "modules")
        (module / "tests").mkdir()
        (module / "tests" / "test_own.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8")
        # a repo-level corpus next to modules/ must never be picked up
        stray = tmp_path / "tests" / "corpus" / "forms" / "fam"
        stray.mkdir(parents=True)
        (stray / "blank.hwpx").write_bytes(b"PK\x03\x04corpus")

        bundle = build(tmp_path)
        with zipfile.ZipFile(bundle) as archive:
            names = archive.namelist()

        assert "modules/throwaway/tests/test_own.py" in names
        assert not any("corpus" in n for n in names)
        assert not any(n.endswith(".hwpx") for n in names)
