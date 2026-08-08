"""Contract tests for the distribution-module registry (W3-S1).

The headline test is the plan's acceptance proof: a throwaway distribution
module built in tmp_path is discovered, enabled, and surfaces its checker
through the typed accessors with ZERO changes to core files.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(SCRIPTS))
import module_registry  # noqa: E402
from module_registry import (  # noqa: E402
    ModuleError,
    ModuleRegistry,
    parse_yaml_subset,
    project_version,
    validate_declaration,
    version_satisfies,
    write_enabled,
)

DUMMY_CHECKER = """\
import json
import sys

print(json.dumps({
    "ok": True,
    "checker": "dummy_probe",
    "hard": [],
    "warn": [],
    "counts": {"hard": 0, "warn": 0},
}))
sys.exit(0)
"""


def make_module(
    root: Path,
    name: str = "throwaway",
    *,
    requires: str = ">=0.1",
    manifest: str | None = None,
) -> Path:
    """Create a complete throwaway distribution module under ``root``."""
    module = root / name
    (module / "scripts").mkdir(parents=True)
    (module / "skill" / "references").mkdir(parents=True)
    (module / "references" / "playbooks").mkdir(parents=True)
    (module / "studio").mkdir(parents=True)
    (module / "scripts" / "check_dummy.py").write_text(DUMMY_CHECKER, encoding="utf-8")
    (module / "scripts" / "dummy_cli.py").write_text("print('hi')\n", encoding="utf-8")
    (module / "skill" / "FRAGMENT.md").write_text("# fragment\n", encoding="utf-8")
    (module / "skill" / "references" / "rules.md").write_text("rules\n", encoding="utf-8")
    (module / "references" / "playbooks" / "night.md").write_text("play\n", encoding="utf-8")
    (module / "studio" / "panel.js").write_text("// panel\n", encoding="utf-8")
    if manifest is None:
        manifest = f"""\
schema: rigorloom-module/v1
name: {name}
requires: {{ rigorloom: "{requires}" }}
provides:
  checkers:
    - {{ name: dummy_probe, script: scripts/check_dummy.py }}
  cli:
    - {{ command: dummy-run, script: scripts/dummy_cli.py }}
  pack_types:
    - dummy_pack
  run_modes:
    - {{ name: night, state_policy: stage_machine, gates: [content_audit, dummy_probe] }}
  gate_kinds:
    - {{ kind: dummy_kind, checker: dummy_probe }}
  studio_panels:
    - {{ id: dummy-panel, title: "Dummy panel", entry: studio/panel.js }}
  skill:
    fragment: skill/FRAGMENT.md
    references: [skill/references/rules.md]
  playbooks:
    - references/playbooks/night.md
"""
    (module / "module.yaml").write_text(manifest, encoding="utf-8")
    return module


def registry_for(root: Path, *, version: str = "0.16.0") -> ModuleRegistry:
    return ModuleRegistry(root, version=version)


# ---------------------------------------------------------------------------
# The acceptance proof: adding a module requires no core change
# ---------------------------------------------------------------------------

class TestThrowawayModuleProof:
    def test_discovery_and_checker_integration_without_core_changes(self, tmp_path):
        """Plan §3.1 rule 4: a brand-new module lights up via the registry only.

        Everything here lives in tmp_path; no file under pipeline/, engine/,
        or studio/ is created, edited, or special-cased for 'throwaway'.
        """
        make_module(tmp_path)
        write_enabled(tmp_path, ["throwaway"])
        registry = registry_for(tmp_path)

        assert sorted(registry.discover()) == ["throwaway"]
        assert [spec.name for spec in registry.enabled_modules()] == ["throwaway"]

        checkers = registry.enabled_checkers()
        assert [entry["name"] for entry in checkers] == ["dummy_probe"]
        assert checkers[0]["module"] == "throwaway"
        script = Path(checkers[0]["script"])
        assert script.is_file() and tmp_path in script.parents

        # Presence is integration: the surfaced checker actually runs and
        # honours the JSON-verdict convention, driven purely off registry data.
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert proc.returncode == 0
        verdict = json.loads(proc.stdout)
        assert verdict["ok"] is True and verdict["checker"] == "dummy_probe"

    def test_all_typed_accessors_surface_contributions(self, tmp_path):
        make_module(tmp_path)
        write_enabled(tmp_path, ["throwaway"])
        registry = registry_for(tmp_path)

        assert [c["command"] for c in registry.enabled_cli()] == ["dummy-run"]
        assert registry.enabled_pack_types() == ["dummy_pack"]
        modes = registry.enabled_run_modes()
        assert modes == [{
            "name": "night", "state_policy": "stage_machine",
            "gates": ["content_audit", "dummy_probe"], "module": "throwaway",
        }]
        assert registry.enabled_gate_kinds() == [{
            "kind": "dummy_kind", "checker": "dummy_probe",
            "module": "throwaway",
        }]
        panels = registry.enabled_studio_panels()
        assert [p["id"] for p in panels] == ["dummy-panel"]
        assert panels[0]["title"] == "Dummy panel"
        skills = registry.enabled_skill_fragments()
        assert len(skills) == 1
        assert Path(skills[0]["fragment"]).name == "FRAGMENT.md"
        assert [Path(r).name for r in skills[0]["references"]] == ["rules.md"]
        plays = registry.enabled_playbooks()
        assert [Path(p["path"]).name for p in plays] == ["night.md"]
        assert all(p["module"] == "throwaway" for p in plays)

    def test_a_checker_can_declare_the_inputs_it_wants(self, tmp_path):
        """v0.17 G3: ``checkers[].wants`` lets a checker say it needs the blank
        baseline, so a runner supplies it instead of every caller knowing.
        ``wants`` is always present on the accessor rows (``[]`` when omitted),
        so a consumer never has to guess whether a module bothered."""
        make_module(tmp_path, "throwaway", manifest=f"""\
schema: rigorloom-module/v1
name: throwaway
requires: {{ rigorloom: ">=0.1" }}
provides:
  checkers:
    - {{ name: dummy_probe, script: scripts/check_dummy.py, wants: [baseline] }}
    - {{ name: plain_probe, script: scripts/dummy_cli.py }}
""")
        write_enabled(tmp_path, ["throwaway"])
        rows = {row["name"]: row for row in registry_for(tmp_path).enabled_checkers()}
        assert rows["dummy_probe"]["wants"] == ["baseline"]
        assert rows["plain_probe"]["wants"] == []

    def test_second_module_joins_without_touching_the_first(self, tmp_path):
        make_module(tmp_path, "throwaway")
        second = tmp_path / "extra"
        (second / "scripts").mkdir(parents=True)
        (second / "scripts" / "check_extra.py").write_text(DUMMY_CHECKER, encoding="utf-8")
        (second / "module.yaml").write_text(
            "schema: rigorloom-module/v1\n"
            "name: extra\n"
            'requires: { rigorloom: ">=0.1" }\n'
            "provides:\n"
            "  checkers:\n"
            "    - { name: extra_probe, script: scripts/check_extra.py }\n",
            encoding="utf-8",
        )
        write_enabled(tmp_path, ["throwaway", "extra"])
        registry = registry_for(tmp_path)
        assert sorted(registry.discover()) == ["extra", "throwaway"]
        assert {c["name"] for c in registry.enabled_checkers()} == {
            "dummy_probe", "extra_probe"}


# ---------------------------------------------------------------------------
# Rule 4, the other half: the TEST HARNESS must be module-agnostic too
# ---------------------------------------------------------------------------
#
# The gongmun module (PR #65) disproved the registry-only reading of rule 4:
# the registry needed nothing, but adding the module still required two core
# edits — pyproject's ``testpaths`` (a hardcoded per-module list) and CI's
# ``py_compile`` glob (likewise). Both are now module-agnostic, and the proof
# below is a PROPERTY test, not a mechanism test: it drops a brand-new module
# into a synthetic root that carries the repo's real pytest configuration
# verbatim, and asserts (a) pytest collects the module's tests and (b) the
# compile sweep compiles the module's scripts — with no file outside
# ``modules/`` created, edited, or naming the module.

PYPROJECT = REPO_ROOT / "pyproject.toml"
MODULES_ROOT = REPO_ROOT / "modules"
SWEEP = REPO_ROOT / "scripts" / "py_compile_sweep.py"

NEW_MODULE = "brandnew"

NEW_MODULE_TEST = """\
def test_the_brand_new_module_was_collected():
    assert True
"""

NEW_MODULE_SCRIPT = """\
def contribution():
    return "brandnew"
"""


def _pytest_ini_block(text: str) -> str:
    """The ``[tool.pytest.ini_options]`` table of a pyproject, verbatim."""
    marker = "[tool.pytest.ini_options]"
    start = text.index(marker)
    rest = text[start + len(marker):]
    end = rest.find("\n[")
    return marker + (rest if end == -1 else rest[:end]) + "\n"


def _configured_testpaths() -> list[str]:
    """testpaths as declared in the repo's pyproject (no toml dependency:
    the block is a literal list of quoted strings, by repo convention)."""
    block = _pytest_ini_block(PYPROJECT.read_text(encoding="utf-8"))
    body = block[block.index("testpaths"):]
    body = body[body.index("["):body.index("]") + 1]
    return re.findall(r'"([^"]+)"', body)


def _synthetic_root(root: Path) -> Path:
    """A minimal checkout carrying the repo's REAL pytest config plus one
    brand-new distribution module — and nothing else."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "synthetic"\nversion = "0.16.0"\n\n'
        + _pytest_ini_block(PYPROJECT.read_text(encoding="utf-8")),
        encoding="utf-8")
    module = root / "modules" / NEW_MODULE
    (module / "tests").mkdir(parents=True)
    (module / "scripts").mkdir(parents=True)
    (module / "module.yaml").write_text(
        "schema: rigorloom-module/v1\n"
        f"name: {NEW_MODULE}\n"
        'requires: { rigorloom: ">=0.16" }\n'
        "provides:\n"
        "  checkers:\n"
        "    - { name: brandnew_probe, script: scripts/probe.py }\n",
        encoding="utf-8")
    (module / "scripts" / "probe.py").write_text(
        NEW_MODULE_SCRIPT, encoding="utf-8")
    (module / "tests" / "test_brandnew.py").write_text(
        NEW_MODULE_TEST, encoding="utf-8")
    return root


class TestHarnessIsModuleAgnostic:
    """Rule 4 for the test harness: a brand-new module's tests are COLLECTED
    and its scripts are COMPILED with zero edits outside ``modules/``."""

    def test_new_module_tests_are_collected_by_the_configured_testpaths(
            self, tmp_path):
        root = _synthetic_root(tmp_path / "checkout")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q",
             "-p", "no:cacheprovider"],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        collected = proc.stdout.replace("\\", "/")
        assert (f"modules/{NEW_MODULE}/tests/test_brandnew.py::"
                "test_the_brand_new_module_was_collected") in collected, (
            "the configured testpaths did not pick up a brand-new module's "
            f"tests — glob expansion of 'modules/*/tests' failed:\n{proc.stdout}")
        # and it was testpaths that did it, not a recursive fallback scan
        assert "Searching recursively from the current directory" not in (
            proc.stdout + proc.stderr)

    def test_new_module_scripts_are_covered_by_the_compile_sweep(self, tmp_path):
        root = _synthetic_root(tmp_path / "checkout")
        proc = subprocess.run(
            [sys.executable, str(SWEEP), "--root", str(root), "--json"],
            capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        report = json.loads(proc.stdout)
        assert f"modules/{NEW_MODULE}/scripts/probe.py" in report["compiled"]

    def test_the_compile_sweep_actually_compiles_the_new_module(self, tmp_path):
        """Negative control: coverage that cannot fail is not coverage."""
        root = _synthetic_root(tmp_path / "checkout")
        (root / "modules" / NEW_MODULE / "scripts" / "broken.py").write_text(
            "def oops(:\n", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(SWEEP), "--root", str(root), "--json"],
            capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 3, proc.stdout
        report = json.loads(proc.stdout)
        assert [row["file"] for row in report["failures"]] == [
            f"modules/{NEW_MODULE}/scripts/broken.py"]

    def test_zero_edits_outside_modules_are_needed(self, tmp_path):
        """The synthetic root's only non-``modules/`` file is the repo's own
        pytest configuration, copied VERBATIM: nothing in it was written for
        this module, and nothing in the harness configuration names a module.
        """
        root = _synthetic_root(tmp_path / "checkout")
        outside = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and not path.as_posix().count("/modules/"))
        assert outside == ["pyproject.toml"]
        block = _pytest_ini_block(PYPROJECT.read_text(encoding="utf-8"))
        assert block in (root / "pyproject.toml").read_text(encoding="utf-8")

        on_disk = sorted(
            path.name for path in (REPO_ROOT / "modules").iterdir()
            if path.is_dir() and (path / "module.yaml").is_file())
        assert on_disk, "no distribution modules on disk — nothing to prove"
        # testpaths reaches every module through one glob, naming none.
        testpaths = _configured_testpaths()
        assert "modules/*/tests" in testpaths
        for name in on_disk + [NEW_MODULE]:
            assert not any(name in entry for entry in testpaths), (
                f"testpaths names distribution module {name!r} — rule 4 says "
                "adding a module must require no core change")
        # the compile sweep does the same for scripts.
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        try:
            import py_compile_sweep
        finally:
            sys.path.pop(0)
        assert "modules/*/scripts/*.py" in py_compile_sweep.PATTERNS
        for name in on_disk + [NEW_MODULE]:
            assert not any(name in pattern
                           for pattern in py_compile_sweep.PATTERNS), (
                f"the compile sweep names distribution module {name!r}")

    def test_ci_delegates_the_sweep_instead_of_inlining_module_globs(self):
        """The workflow must not carry a per-module compile list again."""
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8")
        assert "scripts/py_compile_sweep.py" in workflow
        compile_lines = [line for line in workflow.splitlines()
                         if "py_compile " in line or "py_compile\t" in line]
        assert compile_lines == [], compile_lines


# ---------------------------------------------------------------------------
# Absence is not failure
# ---------------------------------------------------------------------------

    def test_module_test_basenames_are_unique_across_modules(self):
        """No two distribution modules may ship the same test filename.

        pytest's default prepend import mode names a test module after its
        basename alone, so a duplicate collides with 'import file mismatch'
        and interrupts collection. Found by CI on PR #68 (gongmun and minwon
        both shipped tests/test_module_contract.py) — invisible to
        per-module targeted runs. importlib mode would sidestep it but drops
        the test dir from sys.path and breaks tests/_module_gating.py
        imports, so the rule is enforced here instead.
        """
        seen: dict[str, list[str]] = {}
        for path in sorted(MODULES_ROOT.glob("*/tests/test_*.py")):
            seen.setdefault(path.name, []).append(path.parent.parent.name)
        collisions = {n: m for n, m in seen.items() if len(m) > 1}
        assert not collisions, (
            "module test basenames must be unique across modules "
            f"(prefix them with the module name): {collisions}")
        assert seen, "no module tests found — the scan is vacuous"

    def test_the_basename_rule_bites_on_a_planted_duplicate(self, tmp_path):
        """Negative control: the scan must catch a duplicate it is shown."""
        root = tmp_path / "modules"
        for name in ("alpha", "beta"):
            d = root / name / "tests"
            d.mkdir(parents=True)
            (d / "test_module_contract.py").write_text("", encoding="utf-8")
        seen: dict[str, list[str]] = {}
        for path in sorted(root.glob("*/tests/test_*.py")):
            seen.setdefault(path.name, []).append(path.parent.parent.name)
        collisions = {n: m for n, m in seen.items() if len(m) > 1}
        assert collisions == {"test_module_contract.py": ["alpha", "beta"]}

    def test_missing_modules_root_is_core_only(self, tmp_path):
        registry = registry_for(tmp_path / "does-not-exist")
        assert registry.discover() == {}
        assert registry.enabled_modules() == []
        assert registry.enabled_checkers() == []
        assert registry.enabled_pack_types() == []

    def test_missing_enabled_file_means_none_enabled(self, tmp_path):
        make_module(tmp_path)
        registry = registry_for(tmp_path)
        assert sorted(registry.discover()) == ["throwaway"]
        assert registry.enabled_modules() == []

    def test_explicit_empty_enabled_file_is_core_only(self, tmp_path):
        make_module(tmp_path)
        write_enabled(tmp_path, [])
        registry = registry_for(tmp_path)
        assert registry.enabled_modules() == []

    def test_disabled_module_contributes_nothing(self, tmp_path):
        make_module(tmp_path, "throwaway")
        make_module(tmp_path, "silent")
        write_enabled(tmp_path, ["throwaway"])
        registry = registry_for(tmp_path)
        assert sorted(registry.discover()) == ["silent", "throwaway"]
        assert [spec.name for spec in registry.enabled_modules()] == ["throwaway"]
        assert all(
            entry["module"] == "throwaway"
            for entry in registry.enabled_checkers() + registry.enabled_cli())

    def test_repo_default_registry_loads_cleanly(self):
        """The committed repo state must always construct: discovery never
        errors and every enabled module (if an installer wrote enabled.yaml)
        is a discovered one."""
        registry = ModuleRegistry()
        discovered = registry.discover()
        enabled = registry.enabled_modules()
        assert {spec.name for spec in enabled} <= set(discovered)


# ---------------------------------------------------------------------------
# Selective enablement — real modules are independent (W4.2 acceptance)
# ---------------------------------------------------------------------------

class TestSelectiveEnablementIndependence:
    """Selective enablement over the REAL modules/ tree (a temp enabled.yaml,
    never the repo's). style requires nothing and enables alone; report
    declares requires_modules: [style], so report-without-style is a loud
    enablement refusal — the dependency is real (content_audit composes
    check_style) and now visible in the contract."""

    def _registry(self, tmp_path, names):
        enabled = tmp_path / "enabled.yaml"
        enabled.write_text(
            "schema: rigorloom-enabled-modules/v1\n"
            f"enabled: [{', '.join(names)}]\n",
            encoding="utf-8",
        )
        return ModuleRegistry(REPO_ROOT / "modules", enabled_file=enabled)

    def test_style_enables_alone(self, tmp_path):
        registry = self._registry(tmp_path, ["style"])
        assert {"style", "report"} <= set(registry.discover())
        assert [spec.name for spec in registry.enabled_modules()] == ["style"]
        checkers = registry.enabled_checkers()
        assert {row["name"] for row in checkers} == {"check_style"}
        assert {row["command"] for row in registry.enabled_cli()} == {
            "humanize"}
        assert registry.enabled_pack_types() == []
        contributions = (
            checkers + registry.enabled_cli() + registry.enabled_run_modes()
            + registry.enabled_gate_kinds() + registry.enabled_studio_panels()
            + registry.enabled_preflight() + registry.enabled_playbooks())
        assert all(row["module"] == "style" for row in contributions)

    def test_report_without_style_is_a_loud_refusal(self, tmp_path):
        # style is present on disk but not enabled — still a refusal.
        registry = self._registry(tmp_path, ["report"])
        with pytest.raises(ModuleError, match=r"'report'.*\['style'\]"):
            registry.enabled_modules()

    def test_report_with_style_enables_both(self, tmp_path):
        registry = self._registry(tmp_path, ["report", "style"])
        specs = registry.enabled_modules()
        assert {spec.name for spec in specs} == {"report", "style"}
        by_name = {row["name"]: row["module"]
                   for row in registry.enabled_checkers()}
        assert by_name["check_style"] == "style"
        assert by_name["content_audit"] == "report"
        summary = registry.summary()
        assert summary["requires_modules"] == {
            "report": ["style"], "style": []}


class TestRequiresModulesValidation:
    def _declaration(self, requires_modules):
        return {
            "schema": "rigorloom-module/v1",
            "name": "demo",
            "requires": {"rigorloom": ">=0.1"},
            "requires_modules": requires_modules,
            "provides": {},
        }

    def test_normalizes_and_defaults_to_empty(self):
        normalized = validate_declaration("demo", self._declaration(["style"]))
        assert normalized["requires_modules"] == ["style"]
        without = validate_declaration("demo", {
            "schema": "rigorloom-module/v1", "name": "demo",
            "requires": {"rigorloom": ">=0.1"}, "provides": {}})
        assert without["requires_modules"] == []

    @pytest.mark.parametrize("bad, fragment", [
        ("style", "must be a list"),
        (["style", "style"], "duplicates"),
        (["demo"], "must not name the module itself"),
        (["Bad_Name"], "does not match"),
    ])
    def test_invalid_requires_modules_is_loud(self, bad, fragment):
        with pytest.raises(ModuleError, match=fragment):
            validate_declaration("demo", self._declaration(bad))


# ---------------------------------------------------------------------------
# Invalid declarations are loud
# ---------------------------------------------------------------------------

class TestLoudValidation:
    @pytest.mark.parametrize("mutation, fragment", [
        ("schema: wrong/v1\nname: badmod\n"
         'requires: { rigorloom: ">=0.1" }\nprovides: {}\n',
         "schema must be"),
        ("schema: rigorloom-module/v1\n"
         'requires: { rigorloom: ">=0.1" }\nprovides: {}\n',
         "missing required key 'name'"),
        ("schema: rigorloom-module/v1\nname: BadMod\n"
         'requires: { rigorloom: ">=0.1" }\nprovides: {}\n',
         "does not match"),
        ("schema: rigorloom-module/v1\nname: other\n"
         'requires: { rigorloom: ">=0.1" }\nprovides: {}\n',
         "must equal its directory name"),
        ("schema: rigorloom-module/v1\nname: badmod\n"
         "requires: { rigorloom: 1 }\nprovides: {}\n",
         "must be a non-empty string"),
        ("schema: rigorloom-module/v1\nname: badmod\n"
         'requires: { rigorloom: "banana" }\nprovides: {}\n',
         "invalid range clause"),
        ("schema: rigorloom-module/v1\nname: badmod\n"
         'requires: { rigorloom: ">=0.1" }\n'
         "provides:\n  gadgets:\n    - x\n",
         "unknown keys"),
        ("schema: rigorloom-module/v1\nname: badmod\n"
         'requires: { rigorloom: ">=0.1" }\n'
         "provides:\n  checkers:\n    - { name: dummy_probe }\n",
         "missing required key 'script'"),
        ("schema: rigorloom-module/v1\nname: badmod\n"
         'requires: { rigorloom: ">=0.1" }\n'
         "provides:\n  run_modes:\n"
         "    - { name: night, state_policy: vibes, gates: [] }\n",
         "state_policy"),
        ("schema: rigorloom-module/v1\nname: badmod\n"
         'requires: { rigorloom: ">=0.1" }\n'
         "provides:\n  pack_types:\n    - Bad-Pack\n",
         "does not match"),
        ("schema: rigorloom-module/v1\nname: badmod\n"
         'requires: { rigorloom: ">=0.1" }\nprovides: {}\nextra: 1\n',
         "unknown top-level keys"),
        # checkers[].wants is a CLOSED vocabulary (v0.17 G3)
        ("schema: rigorloom-module/v1\nname: badmod\n"
         'requires: { rigorloom: ">=0.1" }\n'
         "provides:\n  checkers:\n"
         "    - { name: p, script: s.py, wants: [telepathy] }\n",
         "must be a non-empty list drawn from"),
        ("schema: rigorloom-module/v1\nname: badmod\n"
         'requires: { rigorloom: ">=0.1" }\n'
         "provides:\n  checkers:\n"
         "    - { name: p, script: s.py, wants: [] }\n",
         "must be a non-empty list drawn from"),
        ("schema: rigorloom-module/v1\nname: badmod\n"
         'requires: { rigorloom: ">=0.1" }\n'
         "provides:\n  checkers:\n"
         "    - { name: p, script: s.py, wants: [baseline, baseline] }\n",
         "duplicates"),
        ("schema: rigorloom-module/v1\nname: badmod\n"
         'requires: { rigorloom: ">=0.1" }\n'
         "provides:\n  checkers:\n"
         "    - { name: p, script: s.py, needs: [baseline] }\n",
         "unknown keys"),
    ])
    def test_invalid_manifest_is_loud_and_names_the_module(
        self, tmp_path, mutation, fragment,
    ):
        module = tmp_path / "badmod"
        module.mkdir()
        (module / "module.yaml").write_text(mutation, encoding="utf-8")
        registry = registry_for(tmp_path)
        with pytest.raises(ModuleError) as excinfo:
            registry.discover()
        message = str(excinfo.value)
        assert "badmod" in message
        assert fragment in message

    def test_invalid_module_is_loud_even_when_disabled(self, tmp_path):
        """Discovery validates every declaration so packaging never ships a
        dud — a broken module.yaml fails even with nothing enabled."""
        module = tmp_path / "broken"
        module.mkdir()
        (module / "module.yaml").write_text("name: [\n", encoding="utf-8")
        registry = registry_for(tmp_path)
        with pytest.raises(ModuleError):
            registry.discover()

    def test_enabling_unknown_module_is_loud(self, tmp_path):
        make_module(tmp_path)
        write_enabled(tmp_path, ["throwaway", "ghost"])
        registry = registry_for(tmp_path)
        with pytest.raises(ModuleError, match="ghost"):
            registry.enabled_modules()

    def test_missing_payload_file_is_loud_at_enablement(self, tmp_path):
        module = make_module(tmp_path)
        (module / "scripts" / "check_dummy.py").unlink()
        write_enabled(tmp_path, ["throwaway"])
        registry = registry_for(tmp_path)
        with pytest.raises(ModuleError, match="check_dummy.py"):
            registry.enabled_modules()

    def test_payload_path_escaping_module_dir_is_loud(self, tmp_path):
        make_module(
            tmp_path,
            manifest=(
                "schema: rigorloom-module/v1\n"
                "name: throwaway\n"
                'requires: { rigorloom: ">=0.1" }\n'
                "provides:\n"
                "  playbooks:\n"
                "    - ../outside.md\n"
            ),
        )
        (tmp_path / "outside.md").write_text("x\n", encoding="utf-8")
        write_enabled(tmp_path, ["throwaway"])
        registry = registry_for(tmp_path)
        with pytest.raises(ModuleError, match="escapes the module directory"):
            registry.enabled_modules()

    def test_checker_name_collision_across_modules_is_loud(self, tmp_path):
        make_module(tmp_path, "throwaway")
        clone = make_module(tmp_path, "clone")
        (clone / "module.yaml").write_text(
            "schema: rigorloom-module/v1\n"
            "name: clone\n"
            'requires: { rigorloom: ">=0.1" }\n'
            "provides:\n"
            "  checkers:\n"
            "    - { name: dummy_probe, script: scripts/check_dummy.py }\n",
            encoding="utf-8",
        )
        write_enabled(tmp_path, ["throwaway", "clone"])
        registry = registry_for(tmp_path)
        with pytest.raises(ModuleError, match="both provide checkers"):
            registry.enabled_modules()

    def test_gate_kind_collision_across_modules_is_loud(self, tmp_path):
        make_module(tmp_path, "throwaway")
        clone = make_module(tmp_path, "clone")
        (clone / "module.yaml").write_text(
            "schema: rigorloom-module/v1\n"
            "name: clone\n"
            'requires: { rigorloom: ">=0.1" }\n'
            "provides:\n"
            "  checkers:\n"
            "    - { name: clone_probe, script: scripts/check_dummy.py }\n"
            "  gate_kinds:\n"
            "    - { kind: dummy_kind, checker: clone_probe }\n",
            encoding="utf-8",
        )
        write_enabled(tmp_path, ["throwaway", "clone"])
        registry = registry_for(tmp_path)
        with pytest.raises(ModuleError, match="both provide gate_kinds"):
            registry.enabled_modules()

    def test_gate_kind_bound_to_unprovided_checker_is_loud(self, tmp_path):
        module = make_module(tmp_path)
        (module / "module.yaml").write_text(
            "schema: rigorloom-module/v1\n"
            "name: throwaway\n"
            'requires: { rigorloom: ">=0.1" }\n'
            "provides:\n"
            "  gate_kinds:\n"
            "    - { kind: dummy_kind, checker: nobody_provides_this }\n",
            encoding="utf-8",
        )
        write_enabled(tmp_path, ["throwaway"])
        registry = registry_for(tmp_path)
        with pytest.raises(ModuleError, match="nobody_provides_this"):
            registry.enabled_modules()

    def test_malformed_enabled_file_is_loud(self, tmp_path):
        make_module(tmp_path)
        (tmp_path / "enabled.yaml").write_text(
            "schema: rigorloom-enabled-modules/v1\n"
            "enabled: [throwaway, throwaway]\n",
            encoding="utf-8",
        )
        registry = registry_for(tmp_path)
        with pytest.raises(ModuleError, match="duplicates"):
            registry.enabled_names()


# ---------------------------------------------------------------------------
# Version gate
# ---------------------------------------------------------------------------

class TestVersionGate:
    def test_unsatisfied_requirement_is_a_load_refusal(self, tmp_path):
        make_module(tmp_path, requires=">=99.0")
        write_enabled(tmp_path, ["throwaway"])
        registry = registry_for(tmp_path, version="0.16.0")
        with pytest.raises(ModuleError) as excinfo:
            registry.enabled_modules()
        message = str(excinfo.value)
        assert "refusing to load distribution module 'throwaway'" in message
        assert ">=99.0" in message and "0.16.0" in message

    def test_disabled_toonew_module_does_not_refuse(self, tmp_path):
        make_module(tmp_path, requires=">=99.0")
        registry = registry_for(tmp_path, version="0.16.0")
        assert registry.enabled_modules() == []

    def test_satisfied_range_loads(self, tmp_path):
        make_module(tmp_path, requires=">=0.16, <1.0")
        write_enabled(tmp_path, ["throwaway"])
        registry = registry_for(tmp_path, version="0.16.3")
        assert [spec.name for spec in registry.enabled_modules()] == ["throwaway"]

    def test_version_comes_from_pyproject(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "x"\nversion = "0.20.1"\n', encoding="utf-8")
        make_module(tmp_path / "mods", requires=">=0.20")
        write_enabled(tmp_path / "mods", ["throwaway"])
        registry = ModuleRegistry(tmp_path / "mods", pyproject=pyproject)
        assert registry.version == "0.20.1"
        assert [spec.name for spec in registry.enabled_modules()] == ["throwaway"]

    def test_real_pyproject_version_is_readable(self):
        version = project_version()
        assert version_satisfies(version, ">=0.1")

    @pytest.mark.parametrize("version, spec, expected", [
        ("0.16.0", ">=0.16", True),
        ("0.15.9", ">=0.16", False),
        ("0.16.0", ">=0.16, <0.17", True),
        ("0.17.0", ">=0.16, <0.17", False),
        ("1.2.3", "==1.2.3", True),
        ("1.2.3", "!=1.2.3", False),
        ("0.16.0-alpha", ">=0.16", True),
        ("2.0.0", ">0.16", True),
        ("0.16.0", "<=0.16.0", True),
    ])
    def test_version_satisfies_table(self, version, spec, expected):
        assert version_satisfies(version, spec) is expected


# ---------------------------------------------------------------------------
# YAML subset parser + declaration normalizer
# ---------------------------------------------------------------------------

class TestYamlSubset:
    def test_full_manifest_shape_parses(self, tmp_path):
        module = make_module(tmp_path)
        payload = parse_yaml_subset(
            (module / "module.yaml").read_text(encoding="utf-8"), "module.yaml")
        declaration = validate_declaration("throwaway", payload)
        assert declaration["name"] == "throwaway"
        assert declaration["requires"] == {"rigorloom": ">=0.1"}
        assert declaration["provides"]["run_modes"][0]["gates"] == [
            "content_audit", "dummy_probe"]

    def test_comments_blank_lines_and_quotes(self):
        payload = parse_yaml_subset(
            "# leading comment\n"
            "schema: rigorloom-module/v1  # trailing\n"
            "\n"
            'name: "quoted-name"\n',
            "inline")
        assert payload == {"schema": "rigorloom-module/v1", "name": "quoted-name"}

    def test_tabs_in_indentation_rejected(self):
        with pytest.raises(ModuleError, match="tabs"):
            parse_yaml_subset("a:\n\tb: 1\n", "inline")

    def test_duplicate_keys_rejected(self):
        with pytest.raises(ModuleError, match="duplicate key"):
            parse_yaml_subset("a: 1\na: 2\n", "inline")

    def test_nested_block_under_list_item_rejected(self):
        with pytest.raises(ModuleError, match="flow mapping"):
            parse_yaml_subset("items:\n  - a\n      b: 1\n", "inline")

    def test_unbalanced_flow_rejected(self):
        with pytest.raises(ModuleError, match="flow"):
            parse_yaml_subset("a: {b: 1\n", "inline")


# ---------------------------------------------------------------------------
# CLI surface (list / write-enabled) — what CI's matrix points drive
# ---------------------------------------------------------------------------

def run_cli(*args: str) -> tuple[dict, int]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "module_registry.py"), *args],
        capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(proc.stdout), proc.returncode


class TestCli:
    def test_list_core_only(self, tmp_path):
        make_module(tmp_path)
        payload, code = run_cli("--modules-root", str(tmp_path), "list")
        assert code == 0
        assert payload["ok"] is True
        assert payload["discovered"] == ["throwaway"]
        assert payload["enabled"] == []
        assert payload["checkers"] == []

    def test_write_enabled_all_then_none(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "x"\nversion = "0.16.0"\n', encoding="utf-8")
        mods = tmp_path / "mods"
        make_module(mods, requires=">=0.16")
        payload, code = run_cli(
            "--modules-root", str(mods), "--pyproject", str(pyproject),
            "write-enabled", "--all")
        assert code == 0
        assert payload["enabled"] == ["throwaway"]
        assert (mods / "enabled.yaml").is_file()
        assert [c["name"] for c in payload["checkers"]] == ["dummy_probe"]

        payload, code = run_cli(
            "--modules-root", str(mods), "--pyproject", str(pyproject),
            "write-enabled", "--none")
        assert code == 0
        assert payload["enabled"] == []
        assert payload["checkers"] == []

    def test_cli_error_is_json_and_nonzero(self, tmp_path):
        module = tmp_path / "badmod"
        module.mkdir()
        (module / "module.yaml").write_text("nonsense: true\n", encoding="utf-8")
        payload, code = run_cli("--modules-root", str(tmp_path), "list")
        assert code == 3
        assert payload["ok"] is False
        assert "badmod" in payload["error"]


# ---------------------------------------------------------------------------
# Terminology guard: stage contracts stay untouched
# ---------------------------------------------------------------------------

def test_stage_contract_catalog_untouched_by_this_registry():
    """The v0.12 stage-contract catalog is a different axis and must keep
    existing exactly where compose.py reads it (module payload since
    W3-S2b: compose.py resolves it module-relative)."""
    catalog = (REPO_ROOT / "modules" / "report" / "references"
               / "modules.yaml")
    assert catalog.is_file()
    assert "rigorloom-modules/v1" in catalog.read_text(encoding="utf-8")
    # And the distribution-module registry never reads it.
    source = (SCRIPTS / "module_registry.py").read_text(encoding="utf-8")
    assert 'references" / "modules.yaml' not in source
