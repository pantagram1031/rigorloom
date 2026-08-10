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
import os
import re
import shutil
import subprocess
import sys
import textwrap
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
        assert "engine/scripts/document_evidence.py" in names
        assert any(n.startswith("pipeline/scripts/") for n in names)
        assert "studio/main.py" in names
        assert "modules/README.md" in names
        # no distribution-module payloads, no test suites
        assert not any(n.startswith("modules/") and n != "modules/README.md"
                       for n in names)
        assert not any("/tests/" in n for n in names)

        report, code = package_module.verify_bundle(bundle)
        assert code == 0, report

    def test_packaged_runtime_help_imports_adapter_package_under_cp949(
            self, tmp_path: Path):
        """A clean extracted core bundle must run its shipped CLIs.

        ``doc_backend.py`` executes from ``pipeline/scripts`` and imports the
        sibling ``pipeline/adapters_impl`` package.  This is an installed
        runtime check (not merely a zip-member assertion) and reproduces the
        Windows CP949 console mode that exposed the missing package.
        """
        bundle = package_module.build_bundle(
            "core", tmp_path / "dist", version="0.16.0")
        install = tmp_path / "installed"
        install.mkdir()
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(install)

        env = os.environ.copy()
        env.pop("PYTHONUTF8", None)
        env["PYTHONIOENCODING"] = "cp949"
        for script in (
                install / "pipeline" / "scripts" / "doc_backend.py",
                install / "pipeline" / "scripts" / "submission_preflight.py",
                install / "pipeline" / "scripts" / "story_graph.py",
                install / "pipeline" / "scripts" / "story_edit.py",
                install / "pipeline" / "scripts" / "hwp_ingress.py",
                install / "pipeline" / "scripts" / "hwp_source_coverage.py",
                install / "pipeline" / "scripts" / "hwp_docinfo_coverage.py"):
            completed = subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=install,
                env=env,
                capture_output=True,
                encoding="cp949",
                errors="replace",
                timeout=30,
            )
            assert completed.returncode == 0, (
                script.name, completed.stdout, completed.stderr)
            assert "Traceback" not in completed.stderr
            assert "ModuleNotFoundError" not in completed.stderr
            assert "adapters_impl" not in completed.stderr

        oracle_help = subprocess.run(
            [sys.executable,
             str(install / "pipeline" / "scripts" / "hwp_semantic_oracle.py"),
             "--help"],
            cwd=install,
            env=env,
            capture_output=True,
            encoding="cp949",
            errors="replace",
            timeout=30,
        )
        assert oracle_help.returncode == 0, (
            oracle_help.stdout, oracle_help.stderr)
        assert "semantic" in oracle_help.stdout.lower()
        assert "Traceback" not in oracle_help.stderr
        assert "ModuleNotFoundError" not in oracle_help.stderr

        diagnostic_help = subprocess.run(
            [sys.executable,
             str(install / "pipeline" / "scripts" / "hwp_diagnostic_candidate.py"),
             "--help"],
            cwd=install,
            env=env,
            capture_output=True,
            encoding="cp949",
            errors="replace",
            timeout=30,
        )
        assert diagnostic_help.returncode == 0, (
            diagnostic_help.stdout, diagnostic_help.stderr)
        assert "rhwp" in diagnostic_help.stdout.lower()
        assert "Traceback" not in diagnostic_help.stderr
        assert "ModuleNotFoundError" not in diagnostic_help.stderr

        java_diagnostic_help = subprocess.run(
            [sys.executable,
             str(install / "pipeline" / "scripts"
                 / "hwp_java_diagnostic_candidate.py"),
             "--help"],
            cwd=install,
            env=env,
            capture_output=True,
            encoding="cp949",
            errors="replace",
            timeout=30,
        )
        assert java_diagnostic_help.returncode == 0, (
            java_diagnostic_help.stdout, java_diagnostic_help.stderr)
        assert "java" in java_diagnostic_help.stdout.lower()
        assert "Traceback" not in java_diagnostic_help.stderr
        assert "ModuleNotFoundError" not in java_diagnostic_help.stderr

        java_lock_check = subprocess.run(
            [sys.executable, "-c",
             "import sys; "
             "sys.path.insert(0, r'pipeline/scripts'); "
             "import hwp_java_diagnostic_candidate as m; "
             "print(m._load_toolchain()[1])"],
            cwd=install,
            env=env,
            capture_output=True,
            encoding="cp949",
            errors="replace",
            timeout=30,
        )
        assert java_lock_check.returncode == 0, (
            java_lock_check.stdout, java_lock_check.stderr)
        assert java_lock_check.stdout.strip() == (
            "6be2ef8320f8987c7b8025682f4ede5e921cac3cfebc105f1c2fd5abc9f9a017")

        names = set()
        with zipfile.ZipFile(bundle) as archive:
            names.update(archive.namelist())
        assert "pipeline/scripts/story_graph.py" in names
        assert "pipeline/scripts/story_edit.py" in names
        assert "pipeline/scripts/hwp_ingress.py" in names
        assert "pipeline/scripts/diagnostic_candidate_core.py" in names
        assert "pipeline/scripts/hwp_diagnostic_candidate.py" in names
        assert "pipeline/scripts/hwp_java_diagnostic_candidate.py" in names
        assert "pipeline/scripts/hwp_semantic_oracle.py" in names
        assert "pipeline/scripts/hwp_source_coverage.py" in names
        assert "pipeline/scripts/hwp_docinfo_coverage.py" in names
        assert "pipeline/references/hwp_java/Hwp2HwpxBridge.java" in names
        assert "pipeline/references/hwp_java/toolchain-lock.json" in names
        assert "pipeline/references/hwp_semantic_oracle/rhwp-allowlist.json" in names
        assert not any(name.lower().endswith((".jar", ".class")) for name in names)
        assert not any(name.lower().endswith((".hwp", ".hwpx")) for name in names)
        assert not any(Path(name).name in {"candidate.hwpx", "receipt.json"}
                       for name in names)
        assert "pipeline/adapters_impl/__init__.py" in names
        assert "pipeline/adapters_impl/bundle_backend.py" in names
        assert "pipeline/adapters_impl/docx_backend.py" in names
        assert not any("tests/corpus" in name for name in names)
        assert not any(Path(name).name in {"secret.hwpx", "private.pdf"}
                       for name in names)

    def test_generated_install_manifest_syncs_adapter_package_under_cp949(
            self, tmp_path: Path):
        """Follow the generated INSTALL.md instructions, not a test copy."""
        bundle = package_module.build_bundle(
            "core", tmp_path / "dist", version="0.16.0")
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(checkout)
            install_md = archive.read("INSTALL.md").decode("utf-8")

        # The YAML block is the actual generated manifest shown to operators.
        # Extract it from INSTALL.md so this regression cannot drift into a
        # second hand-written source_map contract.
        match = re.search(
            r"(?ms)^[ \t]*```yaml\r?\n(?P<body>.*?)^[ \t]*```",
            install_md,
        )
        assert match, "generated INSTALL.md must carry its router manifest"
        manifest_text = textwrap.dedent(match.group("body"))
        assert manifest_text.startswith("install_root:"), manifest_text
        destination = tmp_path / "skill-install"
        manifest_text = manifest_text.replace(
            "<YOUR SKILLS DIR>/rigorloom-hwp",
            str(destination).replace("\\", "/"),
        )
        manifest = checkout / "generated-install.yaml"
        manifest.write_text(manifest_text, encoding="utf-8")

        env = os.environ.copy()
        env.pop("PYTHONUTF8", None)
        env["PYTHONIOENCODING"] = "cp949"
        installer = checkout / "scripts" / "sync_local.py"
        synced = subprocess.run(
            [sys.executable, str(installer), "--manifest", str(manifest),
             "--checkout-root", str(checkout)],
            cwd=checkout,
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert synced.returncode == 0, (synced.stdout, synced.stderr)

        for script_name in ("doc_backend.py", "submission_preflight.py"):
            script = destination / "pipeline" / "scripts" / script_name
            completed = subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=destination,
                env=env,
                capture_output=True,
                encoding="cp949",
                errors="replace",
                timeout=30,
            )
            assert completed.returncode == 0, (
                script_name, completed.stdout, completed.stderr)
            assert "ModuleNotFoundError" not in completed.stderr
            assert "adapters_impl" not in completed.stderr

        installed_files = [
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*") if path.is_file()
        ]
        assert "pipeline/adapters_impl/__init__.py" in installed_files
        assert not any("tests/corpus" in name for name in installed_files)
        assert not any(Path(name).suffix.lower() in {".hwp", ".hwpx"}
                       for name in installed_files)


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


MANIFEST_WITH_SKILL = """\
schema: rigorloom-module/v1
name: throwaway
requires: { rigorloom: ">=0.1" }
provides:
  checkers:
    - { name: dummy_probe, script: scripts/check_dummy.py }
  skill:
    fragment: skill/FRAGMENT.md
    references: [skill/references/play.md]
"""


def make_skill_module(root: Path, fragment_body: str,
                      reference_body: str = "reference body\n") -> Path:
    module = make_module(root, manifest=MANIFEST_WITH_SKILL)
    (module / "skill" / "references").mkdir(parents=True)
    (module / "skill" / "FRAGMENT.md").write_text(
        fragment_body, encoding="utf-8")
    (module / "skill" / "references" / "play.md").write_text(
        reference_body, encoding="utf-8")
    return module


class TestShippedSurfaceReferencesResolve:
    """v0.17 clean-room defect #2 (trouble-table T29): the shipped skill
    referenced ``docs/research/visual-rubric.md``, which was in no bundle, so
    the mandatory vision half of the verify loop reached a buyer with no class
    definitions — both clean-room agents had to recover the vocabulary from
    ``RUBRIC_CLASSES`` in source.

    The guard is DERIVED from the surface's own text, not a filename list: any
    future dangling reference fails the build with nobody updating a constant.
    """

    @pytest.fixture(scope="class")
    def core_tree(self, tmp_path_factory) -> Path:
        """The real core bundle, extracted — byte-identical to the staged tree
        the guard runs over during a build."""
        bundle = package_module.build_bundle(
            "core", tmp_path_factory.mktemp("dist"), version="0.16.0")
        extracted = tmp_path_factory.mktemp("core-tree")
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(extracted)
        return extracted

    def test_the_shipped_rubric_is_in_the_bundle_and_has_the_classes(
            self, core_tree: Path):
        rubric = core_tree / "skill" / "references" / "visual-rubric.md"
        assert rubric.is_file(), "the vision half must ship with the skill"
        text = rubric.read_text(encoding="utf-8")
        assert "## 1. Class table" in text
        assert "`overprint`" in text and "`text_clipped`" in text

    def test_the_real_core_surface_has_no_dangling_reference(
            self, core_tree: Path):
        package_module._assert_skill_surface_references(
            core_tree, Path("skill"), "core bundle")

    def test_a_planted_dangling_reference_is_exit_3(self, core_tree: Path,
                                                    tmp_path: Path):
        """The deliberate plant: add a pointer to a doc the bundle does not
        carry and the guard must refuse, naming both ends."""
        planted = tmp_path / "planted"
        shutil.copytree(core_tree, planted)
        target = planted / "skill" / "references" / "operations.md"
        target.write_text(
            target.read_text(encoding="utf-8")
            + "\nSee `docs/research/not-shipped-anywhere.md` for details.\n",
            encoding="utf-8")
        with pytest.raises(package_module.PackageError) as ctx:
            package_module._assert_skill_surface_references(
                planted, Path("skill"), "core bundle")
        assert ctx.value.exit_code == 3
        message = str(ctx.value)
        assert "docs/research/not-shipped-anywhere.md" in message
        assert "skill/references/operations.md" in message

    def test_moving_the_rubric_back_out_of_the_surface_is_caught(
            self, core_tree: Path, tmp_path: Path):
        """The exact v0.17 regression, replayed: delete the shipped rubric and
        the references that point at it become dangling."""
        stripped = tmp_path / "stripped"
        shutil.copytree(core_tree, stripped)
        (stripped / "skill" / "references" / "visual-rubric.md").unlink()
        with pytest.raises(package_module.PackageError) as ctx:
            package_module._assert_skill_surface_references(
                stripped, Path("skill"), "core bundle")
        assert ctx.value.exit_code == 3
        assert "visual-rubric.md" in str(ctx.value)
        # SKILL.md AND operations.md both point at it; both are reported.
        assert "skill/SKILL.md" in str(ctx.value)
        assert "skill/references/operations.md" in str(ctx.value)

    @pytest.mark.parametrize("spelling", [
        "references/forms.md",            # skill-root relative (installed)
        "engine/references/ops_schema.md",  # bundle-root relative
    ])
    def test_every_legitimate_spelling_resolves(self, core_tree: Path,
                                                tmp_path: Path, spelling: str):
        """Both ways a shipped doc is legitimately addressed must pass, or the
        guard would force churn instead of catching real gaps."""
        probed = tmp_path / f"probe-{abs(hash(spelling))}"
        shutil.copytree(core_tree, probed)
        target = probed / "skill" / "references" / "forms.md"
        target.write_text(
            target.read_text(encoding="utf-8") + f"\nSee `{spelling}`.\n",
            encoding="utf-8")
        package_module._assert_skill_surface_references(
            probed, Path("skill"), "core bundle")

    @pytest.mark.parametrize("ignored", [
        "PIPELINE.md",                      # workspace artifact, not a path
        "https://example.invalid/spec.md",  # a URL is not a bundle path
    ])
    def test_non_paths_are_not_treated_as_bundle_references(self, ignored: str):
        assert package_module._referenced_doc_paths(
            f"read `{ignored}` first") == []

    # ── shipped-surface tables are rectangular ───────────────────────
    #
    # failing-before: SKILL.md's task-routing table had
    # `com_backend.py inspect|edit` in a cell. In GFM a raw `|` splits a cell
    # even inside a code span, so that row had FOUR cells where every other row
    # had three and the last column fell off — in the FIRST table a router
    # reads. The fix is `\|`; the guard is that nobody has to remember it.

    def test_every_table_in_the_real_core_surface_is_rectangular(
            self, core_tree: Path):
        """Every row of every table in every shipped surface doc has the same
        cell count as its own header row."""
        package_module._assert_skill_surface_tables(
            core_tree, Path("skill"), "core bundle")
        # non-empty control: the surface really does contain tables
        docs = package_module._surface_docs(core_tree, Path("skill"))
        rows = sum(1 for doc in docs
                   for line in doc.read_text(encoding="utf-8").splitlines()
                   if line.strip().startswith("|"))
        assert rows > 20, "no tables found — the assertion above proves nothing"

    def test_an_unescaped_pipe_in_a_code_span_is_caught(self):
        """The exact reported defect, reproduced."""
        text = "\n".join([
            "| intent | command | freedom |",
            "|---|---|---|",
            "| COM edit | `com_backend.py inspect|edit --file ...` | LOW |",
        ])
        defects = package_module.markdown_table_defects(text)
        assert len(defects) == 1
        assert defects[0]["cells"] == 4 and defects[0]["expected"] == 3
        # and escaping it is accepted
        assert package_module.markdown_table_defects(
            text.replace("inspect|edit", "inspect\\|edit")) == []

    def test_a_planted_ragged_row_fails_the_shipped_surface_guard(
            self, core_tree: Path, tmp_path: Path):
        planted = tmp_path / "planted"
        shutil.copytree(core_tree, planted)
        skill = planted / "skill" / "SKILL.md"
        skill.write_text(
            skill.read_text(encoding="utf-8")
            + "\n| a | b |\n|---|---|\n| one | two | three |\n",
            encoding="utf-8")
        with pytest.raises(package_module.PackageError) as ctx:
            package_module._assert_skill_surface_tables(
                planted, Path("skill"), "core bundle")
        assert ctx.value.exit_code == 3
        assert "ragged table row" in str(ctx.value)
        assert "skill/SKILL.md" in str(ctx.value)

    def test_table_cell_splitter_matches_gfm_not_intuition(self):
        cells = package_module.markdown_table_cells
        assert cells("| a | b | c |") == [" a ", " b ", " c "]
        assert cells("| a | `x\\|y` |") == [" a ", " `x\\|y` "]
        assert len(cells("| a | `x|y` |")) == 3      # code span does NOT shield

    def test_module_bundle_with_a_dangling_fragment_reference_is_refused(
            self, tmp_path: Path):
        """Full build path, module side: the same guard runs over a
        distribution module's declared skill surface."""
        make_skill_module(
            tmp_path / "modules",
            "## Module: throwaway\n\nSee `references/nowhere.md`.\n")
        with pytest.raises(package_module.PackageError) as ctx:
            build(tmp_path)
        assert ctx.value.exit_code == 3
        assert "references/nowhere.md" in str(ctx.value)

    def test_module_bundle_with_resolving_references_builds(
            self, tmp_path: Path):
        make_skill_module(
            tmp_path / "modules",
            "## Module: throwaway\n\nSee `references/play.md`.\n")
        bundle = build(tmp_path)
        with zipfile.ZipFile(bundle) as archive:
            names = set(archive.namelist())
        assert "modules/throwaway/skill/references/play.md" in names


class TestRubricHasOneHome:
    """One rubric, one home. ``docs/research/visual-rubric.md`` is a pointer;
    if it ever grows back into a copy the two can drift, which is how the
    class table and ``RUBRIC_CLASSES`` diverge silently."""

    SHIPPED = REPO_ROOT / "skill" / "references" / "visual-rubric.md"
    POINTER = REPO_ROOT / "docs" / "research" / "visual-rubric.md"

    def test_the_rubric_lives_in_the_skill_surface(self):
        assert self.SHIPPED.is_file()
        assert "## 1. Class table" in self.SHIPPED.read_text(encoding="utf-8")

    def test_the_docs_path_is_a_pointer_not_a_second_copy(self):
        text = self.POINTER.read_text(encoding="utf-8")
        assert "skill/references/visual-rubric.md" in text
        assert "## 1. Class table" not in text, (
            "docs/research/visual-rubric.md grew a class table again — there "
            "must be exactly one rubric, or the two copies will drift")
        assert len(text) < len(self.SHIPPED.read_text(encoding="utf-8")) / 4


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


# ── reproducible builds ──────────────────────────────────────────────


def _repo_bundle_names() -> list[str]:
    """Every bundle this repo can build — DERIVED from module discovery, so a
    new work-type module needs no edit here (modules/README.md contract 4)."""
    return ["core", *sorted(p.parent.name
                            for p in (REPO_ROOT / "modules").glob("*/module.yaml"))]


BUNDLE_NAMES = _repo_bundle_names()
REPRO_VERSION = "0.17.0"


@pytest.fixture(scope="module")
def twice_built(tmp_path_factory) -> dict[str, tuple[Path, Path]]:
    """Every bundle built TWICE from the same unchanged tree, once per module
    run: ``{name: (first, second)}``. A successful build is also the packaging
    guards' receipt — privacy HARD, the core skill surface, shipped-surface
    references and markdown tables all refuse the build before a zip exists."""
    root = tmp_path_factory.mktemp("repro")
    built: dict[str, tuple[Path, Path]] = {}
    for name in BUNDLE_NAMES:
        built[name] = (
            package_module.build_bundle(name, root / "one",
                                        version=REPRO_VERSION),
            package_module.build_bundle(name, root / "two",
                                        version=REPRO_VERSION),
        )
    return built


class TestBundlesAreReproducible:
    """v0.17.0 release blocker: the bundles were not reproducible.

    Measured while preparing the tag — building ``core`` twice from an
    unchanged tree gave two different zip sha256 values (``97092d2e…`` then
    ``71943ea9…``), because ``ZipFile.write`` stamps each member with the
    staging file's mtime and st_mode. A published hash a reader cannot
    re-derive is not evidence, and the release record's whole job is evidence.

    These tests are the property, not the fix: same tree in, same bytes out,
    and content-identical-but-mtime-different is the same tree.
    """

    def test_there_are_bundles_to_reproduce(self):
        # non-vacuity floor, not an inventory pin: core plus at least one
        # distribution module, or every assertion below passes over nothing.
        assert len(BUNDLE_NAMES) >= 2, BUNDLE_NAMES

    @pytest.mark.parametrize("name", BUNDLE_NAMES)
    def test_two_builds_of_the_same_tree_are_byte_identical(
            self, name: str, twice_built):
        first, second = twice_built[name]
        assert first.name == second.name
        digests = tuple(hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in (first, second))
        assert digests[0] == digests[1], (
            f"{name}: two builds of an unchanged tree produced different "
            f"zips ({digests[0]} vs {digests[1]}) — a published hash table "
            "cannot be reproduced")

    @pytest.mark.parametrize("name", BUNDLE_NAMES)
    def test_verify_still_passes_on_both_builds(self, name: str, twice_built):
        """``--verify`` hashes member CONTENT, so pinning member METADATA must
        leave it untouched. Both the API and the CLI path are exercised."""
        for bundle in twice_built[name]:
            report, code = package_module.verify_bundle(bundle)
            assert code == 0 and report["ok"], (name, report)
            assert report["files"] >= 1
            assert package_module.main(["--verify", str(bundle)]) == 0

    @pytest.mark.parametrize("name", BUNDLE_NAMES)
    def test_every_member_carries_the_pinned_metadata(self, name: str,
                                                      twice_built):
        first, _ = twice_built[name]
        with zipfile.ZipFile(first) as archive:
            infos = archive.infolist()
        assert infos, name
        names = [info.filename for info in infos]
        assert names == sorted(names), (
            f"{name}: members must be written in a stable sorted order")
        assert len(set(names)) == len(names)
        for info in infos:
            assert not info.is_dir()
            assert info.date_time == package_module.ZIP_EPOCH, info.filename
            assert info.external_attr == package_module._ZIP_EXTERNAL_ATTR, \
                info.filename
            assert info.create_system == package_module._ZIP_CREATE_SYSTEM, \
                info.filename
            assert info.compress_type == package_module._ZIP_COMPRESS_TYPE, \
                info.filename

    def test_touching_payload_mtimes_leaves_the_bytes_identical(
            self, tmp_path: Path):
        """The exact failure mode observed: content unchanged, mtimes moved,
        hash must not move. Run over a COPY of a real module so the assertion
        bites on real payload rather than on a two-file fixture."""
        modules_root = tmp_path / "modules"
        shutil.copytree(REPO_ROOT / "modules" / "style", modules_root / "style")

        def build_style(out: str) -> bytes:
            return package_module.build_bundle(
                "style", tmp_path / out, modules_root=modules_root,
                version=REPRO_VERSION).read_bytes()

        before = build_style("one")
        stamp = 1_000_000_000        # 2001-09-09, i.e. emphatically not "now"
        touched = 0
        for path in sorted(modules_root.rglob("*")):
            if path.is_file():
                os.utime(path, (stamp, stamp))
                touched += 1
        assert touched > 1, "nothing was touched — the test proves nothing"

        after = build_style("two")
        assert (hashlib.sha256(before).hexdigest()
                == hashlib.sha256(after).hexdigest()), (
            "an mtime-only change moved the bundle hash — zip members are "
            "carrying staging mtimes again")

    @pytest.mark.parametrize("name", BUNDLE_NAMES)
    def test_manifest_carries_nothing_machine_specific(self, name: str,
                                                       twice_built):
        """MANIFEST.json is inside the zip, so any build-time or host-specific
        value in it would defeat the pinned member metadata."""
        first, _ = twice_built[name]
        with zipfile.ZipFile(first) as archive:
            raw = archive.read(package_module.MANIFEST_NAME).decode("utf-8")
        manifest = json.loads(raw)

        paths = [entry["path"] for entry in manifest["files"]]
        assert paths == sorted(paths), f"{name}: manifest files must be sorted"
        assert len(set(paths)) == len(paths)
        for path in paths:
            assert not path.startswith("/") and "\\" not in path, path

        assert not re.search(r"\d{4}-\d{2}-\d{2}", raw), "date in the manifest"
        assert not re.search(r"\d{2}:\d{2}:\d{2}", raw), "clock in the manifest"
        assert not re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]", raw), \
            "drive-absolute path in the manifest"
        assert str(REPO_ROOT) not in raw
        assert str(first.parent) not in raw

    def test_the_packager_reads_no_out_of_tree_state(self):
        """The bundle timestamp is a constant on purpose. A commit-derived
        stamp (``git log -1 --format=%ct``) is unreproducible for a reader who
        has the tree but not the history — a source tarball, a ``git archive``
        export, an unzipped bundle — which is exactly the reader the release
        record asks to rebuild and compare."""
        source = (REPO_ROOT / "scripts" / "package_module.py").read_text(
            encoding="utf-8")
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        for forbidden in ("subprocess", "os.environ", "getenv", "time.time",
                          "datetime"):
            assert forbidden not in code, (
                f"package_module.py reads out-of-tree state ({forbidden}) — "
                "a bundle's bytes must be a function of the source tree alone")
        assert package_module.ZIP_EPOCH == (1980, 1, 1, 0, 0, 0)
