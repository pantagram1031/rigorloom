# -*- coding: utf-8 -*-
"""Tests for the clean-room validation harness (evals/, v0.17 items A + 4).

Four axes:

1. **Real bundles, real install.** ``package_module`` builds core + style
   bundles in ``tmp_path``; ``cleanroom.prepare`` installs them into a fresh
   root and the whole self-check (shipped ``--verify``, registry enable,
   capability probe, CLI smoke) must come back green.
2. **Containment is not decorative.** A source-checkout path is deliberately
   planted into a prepared install and the harness must catch it; the other
   axes (env scrub, sandbox-root placement, reported paths) are asserted
   directly.
3. **Task YAML schema.** The shipped definitions validate; every violation
   class is a loud refusal; the parser handles the shapes the definitions use.
4. **score.py.** Run-record validation, scorecard join, comparison table.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


cleanroom = _load("_evals_cleanroom", REPO_ROOT / "evals" / "cleanroom.py")
score = _load("_evals_score", REPO_ROOT / "evals" / "score.py")
package_module = _load(
    "_evals_package_module", REPO_ROOT / "scripts" / "package_module.py")

TASKS_DIR = REPO_ROOT / "evals" / "tasks"
A1_TASK = TASKS_DIR / "A1-pps-recognize-fill.yaml"
CORPUS_MANIFEST = REPO_ROOT / "tests" / "corpus" / "forms" / "manifest.json"

#: Non-vacuity floor for the shipped-task scan (see
#: ``TestTaskDefinitions.test_every_shipped_task_validates``). This is NOT the
#: task count — adding a task must never require editing a core test — it only
#: stops a scan over an empty or gutted ``evals/tasks/`` from reading as a pass.
MIN_SHIPPED_TASKS = 5


def corpus_families() -> set[str]:
    """The form families the blank-form corpus actually backs.

    Derived from ``tests/corpus/forms/manifest.json`` rather than listed here:
    the manifest is the only place that knows which families have a real blank
    template on disk, and a hardcoded list is exactly the coupling #26 is about.
    ``skipped[]`` entries are excluded on purpose — a recorded corpus gap (family
    ③ school, family ⑤ corp) has no document to write a task against.
    """
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    return {row["family"] for row in manifest["documents"]
            if isinstance(row.get("family"), str) and row["family"].strip()}


def declared_skips(task: dict, enabled_modules: Iterable[str] = ()) -> dict:
    """The check ids a task DECLARES will skip, given the enabled modules (#27).

    Derived from the task definition by mirroring the two declared gates in
    ``cleanroom.run_machine_check``, in its order:

    * ``blocked_on`` — skips in every sandbox, by definition;
    * ``requires_module: NAME`` — skips wherever ``NAME`` is not enabled.

    Returns ``{check_id: gate_key}``, so a caller gets both the count and the
    identities and can assert the set both ways instead of a number.

    This exists because pinning the number was the bug. A core test used to
    assert A1's skipped count ``== 1``; every ``requires_module`` check added to
    a shipped task skips by design in a core-only sandbox, so growing a task's
    module-gated coverage failed a core test that knew nothing about the module
    — the grant module wired its A1 checks onto A2/A3 to route around it. The
    expected count is a function of the definition, so compute it.

    NOT modelled here, on purpose: the third skip reason in
    ``run_machine_check`` — a ``python`` check whose checker declares
    ``wants: [baseline]`` while the task declares no ``baseline``. That one is
    not visible in the task alone (it depends on the installed module's
    ``module.yaml``), and it is a defect rather than a declaration: a task that
    triggers it is missing a baseline. Callers therefore compare the derived set
    to the observed set BOTH ways, which is what makes an unmodelled skip a
    failure here rather than a silent tolerance.
    """
    enabled = set(enabled_modules)
    skips: dict[str, str] = {}
    for check in task["machine_checks"]:
        if check.get("blocked_on"):
            skips[check["id"]] = "blocked_on"
        elif check.get("requires_module") and (
                check["requires_module"] not in enabled):
            skips[check["id"]] = "requires_module"
    return skips


# --------------------------------------------------------------------------- #
# session fixtures: build real bundles once, install them once
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def bundles(tmp_path_factory) -> list[Path]:
    """core + style bundles, built by the real packager from this checkout."""
    out = tmp_path_factory.mktemp("dist")
    return [package_module.build_bundle("core", out),
            package_module.build_bundle("style", out)]


@pytest.fixture(scope="module")
def prepared(tmp_path_factory, bundles) -> dict:
    """One clean-room install, shared by the tests that only read it.

    No ``allow_gaps``: as of v0.17 a healthy bundle set installs with ZERO
    acknowledged gaps. If this fixture starts needing one again, something
    stopped shipping.
    """
    root = tmp_path_factory.mktemp("cleanroom") / "sandbox"
    report, code = cleanroom.prepare(root, bundles, enable="all")
    return {"root": Path(report["sandbox_root"]), "report": report,
            "code": code, "bundles": bundles}


# --------------------------------------------------------------------------- #
# 1. prepare against real dist bundles
# --------------------------------------------------------------------------- #
class TestCleanroomPrepare:
    def test_install_is_green_end_to_end(self, prepared):
        report, code = prepared["report"], prepared["code"]
        assert code == 0, report["failures"]
        assert report["ok"] is True
        assert report["failures"] == []

    def test_a_current_bundle_set_installs_with_zero_allowed_gaps(
            self, prepared):
        """The v0.17 packaging fix, stated as a product property: nothing has
        to be acknowledged for a healthy install."""
        report = prepared["report"]
        assert report["gaps"] == []
        assert report["gaps_acknowledged"] == []

    def test_bundles_verify_through_the_shipped_verifier(self, prepared):
        report = prepared["report"]
        # the bundle list comes from the fixture that built them, not a literal
        # (#27): which bundles this sandbox installs is the fixture's decision
        assert [row["bundle"] for row in report["verify"]] == [
            path.name for path in prepared["bundles"]]
        assert all(row["ok"] for row in report["verify"])
        assert all(row["problems"] == [] for row in report["verify"])
        # the verifier that ran is the one that shipped, not the repo's copy
        verifier = prepared["root"] / "install" / "scripts" / "package_module.py"
        assert verifier.is_file()

    def test_registry_and_probe_agree(self, prepared):
        report = prepared["report"]
        assert report["registry"]["enabled"] == ["style"]
        assert report["probe"]["modules"]["enabled"] == ["style"]
        assert "humanize" in report["registry"]["cli"]

    def test_every_cli_answers_help(self, prepared):
        failures = [row for row in prepared["report"]["cli_smoke"]
                    if not row["ok"]]
        assert failures == []
        assert any(row["target"].startswith("module:style")
                   for row in prepared["report"]["cli_smoke"])

    def test_install_report_is_written_and_self_describing(self, prepared):
        path = prepared["root"] / "install_report.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema"] == cleanroom.INSTALL_REPORT_SCHEMA
        assert payload["commands"], "every executed command must be recorded"
        assert payload["containment"]["contained"] is True

    def test_bundle_references_never_carry_a_build_path(self, prepared):
        """The report names bundles by filename: a dist/ absolute path would
        embed the checkout and defeat containment on a re-verify."""
        for name in prepared["report"]["bundles"]:
            assert os.sep not in name and "/" not in name

    def test_skill_surface_gap_is_not_reported_because_it_is_bundled(
            self, prepared):
        """The gap CODE stays (it is a real check); what changed is that a
        current bundle no longer trips it."""
        assert "skill_surface_not_bundled" in cleanroom._ALLOWED_GAPS
        assert "skill_surface_not_bundled" not in {
            gap["id"] for gap in prepared["report"]["gaps"]}
        assert prepared["report"]["skill"].get("gap") is None
        assert prepared["report"]["skill"]["ok"] is True

    def test_the_gap_check_still_bites_when_the_surface_is_absent(
            self, tmp_path, bundles):
        """Negative control: strip the bundled skill surface out of a prepared
        install and the harness must report the gap again. Otherwise 'no gap'
        would only prove the check went quiet."""
        report, _code = cleanroom.prepare(
            tmp_path / "stripped", bundles, enable="all", skip_skill=True)
        install = Path(report["sandbox_root"]) / "install"
        shutil.rmtree(install / "skill")
        (install / "scripts" / "sync_local.py").unlink()
        sandbox = cleanroom.Sandbox(report["sandbox_root"])
        result = cleanroom.install_skill(sandbox)
        assert result["gap"] == "skill_surface_not_bundled"
        assert set(result["missing"]) == {"scripts/sync_local.py", "SKILL.md"}

    def test_unacknowledged_gap_fails_the_run(self, tmp_path, bundles):
        """A core-only install still reports ``no_module_bundles``; without an
        acknowledgement the run fails. The gap machinery is intact."""
        report, code = cleanroom.prepare(
            tmp_path / "unack", [bundles[0]], enable="none")
        assert code == 3
        assert report["ok"] is False
        assert any("no_module_bundles" in failure
                   for failure in report["failures"])

    def test_core_only_install(self, tmp_path, bundles):
        report, code = cleanroom.prepare(
            tmp_path / "coreonly", [bundles[0]], enable="none",
            allow_gaps=["no_module_bundles"])
        assert code == 0, report["failures"]
        assert report["registry"]["enabled"] == []
        assert {gap["id"] for gap in report["gaps"]} == {"no_module_bundles"}
        # core alone still carries a usable skill surface
        assert report["skill"]["ok"] is True
        installed = Path(report["skill"]["install_root"]) / "SKILL.md"
        assert installed.is_file()
        assert "## Module:" not in installed.read_text(encoding="utf-8")

    def test_refuses_a_non_empty_root(self, tmp_path, bundles):
        root = tmp_path / "dirty"
        root.mkdir()
        (root / "leftover.txt").write_text("x", encoding="utf-8")
        with pytest.raises(cleanroom.CleanroomError) as excinfo:
            cleanroom.prepare(root, bundles)
        assert excinfo.value.exit_code == 2

    def test_refuses_without_a_core_bundle(self, tmp_path, bundles):
        with pytest.raises(cleanroom.CleanroomError) as excinfo:
            cleanroom.prepare(tmp_path / "nocore", [bundles[1]])
        assert "core bundle" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# 2. containment
# --------------------------------------------------------------------------- #
class TestContainment:
    def test_planted_source_reference_is_caught(self, tmp_path, bundles):
        """The whole point of the harness: an install that reaches back into
        the checkout must fail loudly, even though everything else is green."""
        root = tmp_path / "planted"
        report, code = cleanroom.prepare(root, bundles, enable="all")
        assert code == 0 and report["containment"]["contained"] is True

        planted = (Path(report["sandbox_root"]) / "install" / "pipeline"
                   / "references" / "planted_note.md")
        planted.write_text(
            f"helper lives at {REPO_ROOT}{os.sep}pipeline{os.sep}scripts\n",
            encoding="utf-8")

        sandbox = cleanroom.Sandbox(report["sandbox_root"])
        verdict = cleanroom.containment_report(sandbox, runtime=False)
        assert verdict["contained"] is False
        findings = [f for f in verdict["findings"]
                    if f["rule"] == "source_path_in_install"]
        assert findings, verdict["findings"]
        # Scan order is filesystem-dependent (CI Linux vs Windows), so assert
        # the planted file is AMONG the findings, not that it is first.
        planted_hits = [f for f in findings
                        if f["file"].endswith("planted_note.md")]
        assert planted_hits, [f["file"] for f in findings]
        assert planted_hits[0]["forbidden_root"] == str(REPO_ROOT)

    def test_planted_reference_is_caught_through_the_cli(self, tmp_path,
                                                         bundles, prepared):
        planted = (prepared["root"] / "install" / "pipeline" / "references"
                   / "cli_planted.md")
        planted.write_text(f"see {REPO_ROOT}\n", encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "evals" / "cleanroom.py"),
                 "verify-containment", "--root", str(prepared["root"]),
                 "--no-runtime"],
                capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            assert proc.returncode == 3, proc.stdout
            verdict = json.loads(proc.stdout)
            assert verdict["contained"] is False
        finally:
            planted.unlink()

    def test_forward_slash_variant_is_caught(self, tmp_path):
        sandbox_root = tmp_path / "sb"
        (sandbox_root / "install").mkdir(parents=True)
        (sandbox_root / "install" / "note.md").write_text(
            "path: " + str(REPO_ROOT).replace("\\", "/") + "/engine\n",
            encoding="utf-8")
        findings = cleanroom.scan_for_source_references(
            sandbox_root, [REPO_ROOT])
        assert findings and findings[0]["rule"] == "source_path_in_install"

    def test_sandbox_root_inside_the_checkout_is_refused(self):
        with pytest.raises(cleanroom.CleanroomError) as excinfo:
            cleanroom.Sandbox(REPO_ROOT / "build" / "sandbox")
        assert excinfo.value.exit_code == 2
        assert "INSIDE forbidden root" in str(excinfo.value)

    def test_env_is_scrubbed_and_repinned(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT / "pipeline"))
        monkeypatch.setenv("RIGORLOOM_BACKENDS", "whatever")
        monkeypatch.setenv("SOMETHING_ELSE", str(REPO_ROOT / "engine"))
        sandbox = cleanroom.Sandbox(tmp_path / "sb")
        env = sandbox.env
        assert "PYTHONPATH" not in env
        assert "RIGORLOOM_BACKENDS" not in env
        assert "SOMETHING_ELSE" not in env
        assert env["RIGORLOOM_ROOT"] == str(sandbox.install)
        assert not any(
            cleanroom._is_within(entry, REPO_ROOT)
            for entry in env["PATH"].split(os.pathsep) if entry)

    def test_reported_path_outside_the_sandbox_is_a_finding(self, tmp_path):
        sandbox = cleanroom.Sandbox(tmp_path / "sb")
        verdict = cleanroom.containment_report(
            sandbox, runtime=False,
            reported_paths=[("registry.cli.compose",
                             str(REPO_ROOT / "modules" / "report"))])
        assert verdict["contained"] is False
        assert any(f["rule"] == "reported_path_outside_sandbox"
                   for f in verdict["findings"])

    def test_extra_forbidden_root_is_honoured(self, tmp_path):
        other = tmp_path / "other-checkout"
        other.mkdir()
        sandbox_root = tmp_path / "sb2"
        (sandbox_root / "install").mkdir(parents=True)
        (sandbox_root / "install" / "n.md").write_text(
            f"see {other}\n", encoding="utf-8")
        sandbox = cleanroom.Sandbox(sandbox_root, [other])
        verdict = cleanroom.containment_report(sandbox, runtime=False)
        assert verdict["contained"] is False
        assert str(other) in verdict["forbidden_roots"]

    def test_runtime_import_origin_resolves_inside_the_sandbox(self, prepared):
        probe = prepared["report"]["containment"]["import_probe"]
        assert cleanroom._is_within(
            probe["module_registry"], prepared["root"] / "install")
        assert cleanroom._is_within(
            probe["privacy_scan"], prepared["root"] / "install")


class TestSkillInstallFromBundlesAlone:
    """The buyer's skill install, end to end, out of the bundles and nothing
    else. Before v0.17 this could only be simulated by copying ``skill/`` and
    ``scripts/sync_local.py`` out of the checkout — the copying is gone, which
    is the point of the fix."""

    def test_the_surface_is_located_inside_the_installed_tree(self, prepared):
        surface = cleanroom.locate_skill_surface(prepared["root"] / "install")
        assert surface == {"present": True, "skill_md": "skill/SKILL.md",
                           "references": "skill/references"}

    def test_prepare_installed_the_skill_with_module_fragments_merged(
            self, prepared):
        result = prepared["report"]["skill"]
        assert result["ok"] is True, result
        assert result["skill_md_installed"] is True
        installed = Path(result["install_root"]) / "SKILL.md"
        body = installed.read_text(encoding="utf-8")
        assert "rigorloom-hwp" in body
        # merge_skill_fragments pulled every enabled module's fragment in
        for name in prepared["report"]["registry"]["enabled"]:
            assert f"## Module: {name}" in body
        assert "## Module: style" in body
        assert cleanroom._is_within(result["install_root"], prepared["root"])
        # core references travelled with the skill
        references = Path(result["install_root"]) / "references"
        assert {"operations.md", "forms.md", "troubleshooting.md"} <= {
            path.name for path in references.glob("*.md")}

    def test_a_module_skill_reference_lands_beside_the_installed_skill(
            self, tmp_path, tmp_path_factory):
        """The report module declares `skill.references`; installing its bundle
        must put that file into the installed skill's references/."""
        out = tmp_path_factory.mktemp("dist_report")
        report_bundles = [package_module.build_bundle(name, out)
                          for name in ("core", "style", "report")]
        report, code = cleanroom.prepare(
            tmp_path / "withreport", report_bundles, enable="all")
        assert code == 0, report["failures"]
        install_root = Path(report["skill"]["install_root"])
        body = (install_root / "SKILL.md").read_text(encoding="utf-8")
        assert "## Module: report" in body
        names = {path.name for path in (install_root / "references").glob("*.md")}
        assert "report_pipeline.md" in names

    def test_installing_twice_is_idempotent(self, tmp_path, bundles):
        """A buyer re-runs the installer after enabling another module; the
        second run must not be refused as drift."""
        report, code = cleanroom.prepare(
            tmp_path / "twice", bundles, enable="all")
        assert code == 0, report["failures"]
        sandbox = cleanroom.Sandbox(report["sandbox_root"])
        again = cleanroom.install_skill(sandbox)
        assert again["ok"] is True, again
        body = (Path(again["install_root"]) / "SKILL.md").read_text(
            encoding="utf-8")
        # NOT an inventory count: 1 means "once, not twice" — the whole point of
        # the test. It does not move when a module is added, because it counts
        # one named module's heading, not the modules.
        assert body.count("## Module: style") == 1


# --------------------------------------------------------------------------- #
# 3. task definitions
# --------------------------------------------------------------------------- #
GOOD_TASK = """\
schema: rigorloom-eval-task/v1
id: T1-demo
family: grant
prompt: |
  이 양식을 채워줘.
  결과는 filled.hwpx 로 저장해줘.
input_files:
  - tests/corpus/forms/grant/pps-jeongbogonggae-donguiseo.hwpx
expected_behavior:
  - "[judgment] 서명란은 비워 둔다: 사람 몫이다."
machine_checks:
  - id: produced
    kind: file
    path: "${WORK}/filled.hwpx"
    mode: nonempty
  - id: floors
    kind: python
    argv: ["engine/scripts/form_inspect.py", "${INPUTS}/x.hwpx", "--out", "${WORK}/p.json"]
    expect_exit: 0
    json_file: "${WORK}/p.json"
    assert_json: ["len(anchors) >= 28", "constraints.max_pages == null"]
"""


class TestTaskDefinitions:
    def test_every_shipped_task_validates(self):
        """The task inventory is a PROPERTY, not a count (#26).

        Three claims, none of which a new ``evals/tasks/*.yaml`` can break:

        * every shipped definition validates against the task schema, and its
          inputs come from the blank-form corpus;
        * every corpus-backed family has at least one task, with the family list
          *derived* from ``tests/corpus/forms/manifest.json``. Adding a family to
          the corpus therefore obliges a task for it; adding a task for a family
          the corpus does not back is equally a defect (the inputs would have to
          come from somewhere else);
        * a non-vacuity floor, so a scan over an empty tasks directory cannot
          silently pass.

        The old form asserted ``len(tasks) == 7`` and the exact family set, which
        made "ship one more eval task" a core-test edit — the coupling this test
        now refuses to have.
        """
        tasks = cleanroom.load_tasks(TASKS_DIR)
        assert len(tasks) >= MIN_SHIPPED_TASKS, (
            f"only {len(tasks)} shipped eval task(s) — below the non-vacuity "
            f"floor of {MIN_SHIPPED_TASKS}; the scan below would prove nothing")

        backed = corpus_families()
        assert backed, "the corpus manifest declares no families — vacuous scan"
        covered = {task["family"] for task in tasks}
        assert backed <= covered, (
            "corpus-backed families with no eval task: "
            f"{sorted(backed - covered)}")
        assert covered <= backed, (
            "eval tasks claim families the blank-form corpus does not back: "
            f"{sorted(covered - backed)}")

        for task in tasks:
            assert task["prompt"].strip()
            assert all(entry.startswith("tests/corpus/forms/")
                       for entry in task["input_files"])

    def test_the_family_coverage_property_bites_on_an_uncovered_family(
            self, tmp_path):
        """Negative control: the derived-family scan must catch a gap it is
        shown. Planting a corpus family with no task has to fail, otherwise the
        property above is decoration."""
        backed = corpus_families() | {"planted-family"}
        covered = {task["family"] for task in cleanroom.load_tasks(TASKS_DIR)}
        assert backed - covered == {"planted-family"}

    def test_no_binaries_live_under_evals(self):
        """The eval tree references corpus files by path; embedding one would
        break the repo privacy gate (bundle/corpus allowlist is elsewhere)."""
        binary_suffixes = {".hwp", ".hwpx", ".pdf", ".doc", ".docx", ".zip"}
        offenders = [path for path in (REPO_ROOT / "evals").rglob("*")
                     if path.is_file()
                     and path.suffix.lower() in binary_suffixes]
        assert offenders == []

    def test_shipped_input_files_exist_in_the_corpus(self):
        for task in cleanroom.load_tasks(TASKS_DIR):
            for entry in task["input_files"]:
                assert (REPO_ROOT / entry).is_file(), entry

    def test_parser_handles_quoted_colons_and_block_scalars(self, tmp_path):
        path = tmp_path / "t.yaml"
        path.write_text(GOOD_TASK, encoding="utf-8")
        task = cleanroom.load_task(path)
        assert task["prompt"].startswith("이 양식을 채워줘.")
        assert "\n" in task["prompt"]
        assert task["expected_behavior"][0].endswith("사람 몫이다.")
        assert task["machine_checks"][1]["argv"][0].endswith("form_inspect.py")
        assert task["machine_checks"][1]["expect_exit"] == 0

    @pytest.mark.parametrize("mutation,fragment", [
        ("schema: rigorloom-eval-task/v0", "schema must be"),
        ("id: has space", "filesystem-safe"),
        ("family:", "family is required"),
    ])
    def test_schema_violations_are_loud(self, tmp_path, mutation, fragment):
        key = mutation.split(":")[0]
        lines = [mutation if line.startswith(f"{key}:") else line
                 for line in GOOD_TASK.splitlines()]
        path = tmp_path / "bad.yaml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(cleanroom.CleanroomError) as excinfo:
            cleanroom.load_task(path)
        assert fragment in str(excinfo.value)

    def test_unknown_check_kind_is_refused(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(GOOD_TASK.replace("kind: file", "kind: telepathy"),
                        encoding="utf-8")
        with pytest.raises(cleanroom.CleanroomError) as excinfo:
            cleanroom.load_task(path)
        assert "kind must be one of" in str(excinfo.value)

    def test_absolute_input_path_is_refused(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            GOOD_TASK.replace(
                "  - tests/corpus/forms/grant/pps-jeongbogonggae-donguiseo.hwpx",
                "  - /etc/passwd"), encoding="utf-8")
        with pytest.raises(cleanroom.CleanroomError) as excinfo:
            cleanroom.load_task(path)
        assert "repo-relative" in str(excinfo.value)

    def test_unparseable_assertion_is_refused(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            GOOD_TASK.replace('"len(anchors) >= 28"', '"anchors is fine"'),
            encoding="utf-8")
        with pytest.raises(cleanroom.CleanroomError) as excinfo:
            cleanroom.load_task(path)
        assert "unparseable assertion" in str(excinfo.value)

    def test_assertion_evaluation(self):
        document = {"anchors": [1, 2, 3],
                    "table_map": [{"rowCnt": 19}],
                    "constraints": {"max_pages": None}}
        results = cleanroom.evaluate_assertions(document, [
            "len(anchors) >= 3", "table_map[0].rowCnt == 19",
            "constraints.max_pages == null", "len(anchors) > 5",
            "missing.key == 1",
        ])
        assert [row["ok"] for row in results] == [True, True, True, False, False]


# --------------------------------------------------------------------------- #
# 4. task materialization + machine checks (end to end on a real form)
# --------------------------------------------------------------------------- #
class TestTaskRun:
    @pytest.fixture(scope="class")
    def materialized(self, prepared):
        task = cleanroom.load_task(A1_TASK)
        payload = cleanroom.materialize_task(prepared["root"], task)
        return {"task": task, "payload": payload, "root": prepared["root"]}

    def test_inputs_are_copied_and_prompt_rendered(self, materialized):
        payload = materialized["payload"]
        work = Path(payload["work_dir"])
        assert (work / "PROMPT.txt").is_file()
        assert (work / "task.json").is_file()
        # every declared input arrives, derived from the task (#27) — giving A1
        # a second attachment must not be a core-test edit
        declared = materialized["task"]["input_files"]
        assert declared, "A1 declares no input file — nothing to copy"
        assert len(payload["inputs"]) == len(declared)
        copied = Path(payload["inputs"][0]["sandbox_path"])
        assert copied.is_file()
        assert copied.read_bytes() == (
            REPO_ROOT / materialized["task"]["input_files"][0]).read_bytes()
        prompt = (work / "PROMPT.txt").read_text(encoding="utf-8")
        assert str(copied) in prompt

    def test_checks_fail_loudly_when_the_agent_produced_nothing(
            self, materialized):
        results = cleanroom.run_checks(
            materialized["root"], materialized["task"])
        assert results["ok"] is False
        by_id = {row["id"]: row for row in results["checks"]}
        assert by_id["profile_blank"]["status"] == "pass"
        assert by_id["filled_produced"]["status"] == "fail"

        # The skips are a PROPERTY of the task definition, not a number (#27):
        # exactly the checks A1 declares a gate on, no more and no fewer. The
        # old form pinned ``counts["skipped"] == 1``, which made "add a
        # module-gated check to a shipped task" a core-test edit.
        expected = declared_skips(
            materialized["task"], results["enabled_modules"])
        assert expected, (
            "A1 declares no gated check in this sandbox — the scan below "
            "would prove nothing")
        observed = {cid for cid, row in by_id.items()
                    if row["status"] == "skipped"}
        assert observed == set(expected), {
            "declared": sorted(expected), "observed": sorted(observed)}
        assert results["counts"]["skipped"] == len(expected)
        for cid, gate in expected.items():
            assert by_id[cid].get("reason"), (cid, gate)

    def test_checks_pass_on_a_faithful_fill(self, materialized):
        """Prove the rubric is satisfiable: fill the form with the SANDBOX
        copy of preedit and every non-skipped check must come back green."""
        work = Path(materialized["payload"]["work_dir"])
        source = Path(materialized["payload"]["inputs"][0]["sandbox_path"])
        # "기 업 명" is printed in TWO blocks of this form (신청기업 / 협업기업),
        # so it is scoped by paragraph address — an unscoped key would be
        # refused, and the assertion below proves that is what happens (T41).
        mapping = {
            "우(     -     )": "우 서울특별시 강남구 테헤란로 100",
            "년      월      일": "2026년   8월   20일",
            "기 업 명": {"text": "기 업 명 한빛정밀", "at_para": 6},
            "협업제품명": "협업제품명 저진동 정밀 이송 스테이지",
        }
        (work / "map.json").write_text(
            json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        sandbox = cleanroom.Sandbox(materialized["root"])
        proc = sandbox.run_python(
            sandbox.install / "engine" / "scripts" / "preedit.py",
            ["replace", str(source), "--out", str(work / "filled.hwpx"),
             "--map", str(work / "map.json")])
        assert proc.returncode == 0, proc.stderr

        # the same map with that one key left unscoped: refused, not written
        loose = dict(mapping, **{"기 업 명": "기 업 명 한빛정밀"})
        (work / "loose.json").write_text(
            json.dumps(loose, ensure_ascii=False), encoding="utf-8")
        refused = sandbox.run_python(
            sandbox.install / "engine" / "scripts" / "preedit.py",
            ["replace", str(source), "--out", str(work / "loose.hwpx"),
             "--map", str(work / "loose.json")])
        assert refused.returncode == 2, refused.stdout
        payload = json.loads(refused.stdout.strip().splitlines()[-1])
        assert payload["code_name"] == "replace_key_ambiguous"
        assert [row["key"] for row in payload["keys"]] == ["기 업 명"]
        assert not (work / "loose.hwpx").exists()

        results = cleanroom.run_checks(
            materialized["root"], materialized["task"])
        failed = [row for row in results["checks"] if row["status"] == "fail"]
        assert failed == [], failed
        assert results["ok"] is True
        residue = next(row for row in results["checks"]
                       if row["id"] == "residue_clean")
        assert residue["consumed"], "residue gate must be non-vacuous"

    def test_residue_gate_is_vacuous_on_an_untouched_copy(self, materialized):
        """Negative control: 'filling' by copying the blank form through must
        NOT score a green residue gate."""
        work = Path(materialized["payload"]["work_dir"])
        source = Path(materialized["payload"]["inputs"][0]["sandbox_path"])
        shutil.copy2(source, work / "untouched.hwpx")
        sandbox = cleanroom.Sandbox(materialized["root"])
        check = dict(
            next(row for row in materialized["task"]["machine_checks"]
                 if row["id"] == "residue_clean"),
            id="vacuity", artifact="${WORK}/untouched.hwpx")
        result = cleanroom.run_machine_check(sandbox, check, {
            "WORK": str(work), "INSTALL": str(sandbox.install),
            "SANDBOX": str(sandbox.root), "INPUTS": str(work / "inputs"),
            "SKILLS": str(sandbox.skills)})
        assert result["status"] == "fail"
        assert "vacuous" in result["detail"]

    def test_unmodified_check_catches_an_in_place_edit(self, materialized):
        work = Path(materialized["payload"]["work_dir"])
        source = Path(materialized["payload"]["inputs"][0]["sandbox_path"])
        backup = source.read_bytes()
        try:
            source.write_bytes(backup + b"\x00")
            sandbox = cleanroom.Sandbox(materialized["root"])
            result = cleanroom.run_machine_check(
                sandbox,
                {"id": "u", "kind": "unmodified", "input": source.name},
                {"WORK": str(work), "INSTALL": str(sandbox.install),
                 "SANDBOX": str(sandbox.root), "INPUTS": str(work / "inputs"),
                 "SKILLS": str(sandbox.skills)})
            assert result["status"] == "fail"
            assert "modified in place" in result["detail"]
        finally:
            source.write_bytes(backup)

    def test_task_refuses_an_unprepared_root(self, tmp_path):
        task = cleanroom.load_task(A1_TASK)
        with pytest.raises(cleanroom.CleanroomError) as excinfo:
            cleanroom.materialize_task(tmp_path / "empty", task)
        assert excinfo.value.exit_code == 2


# --------------------------------------------------------------------------- #
# 4b. requires_module — the per-module machine-check gate (v0.17 G2)
# --------------------------------------------------------------------------- #
G1_TASK = TASKS_DIR / "G1-gianmun-body-edit.yaml"


def _module_gated_task(module: str) -> dict:
    """A minimal task whose single check is gated on ``module``. The check is
    `file`/`absent` on a path that cannot exist, so it PASSES whenever it is
    allowed to run — the only thing under test is the gate."""
    return {
        "schema": cleanroom.TASK_SCHEMA,
        "id": f"gate-{module}",
        "family": "grant",
        "prompt": "gate probe",
        "input_files": [
            "tests/corpus/forms/grant/pps-jeongbogonggae-donguiseo.hwpx"],
        "expected_behavior": ["[judgment] n/a"],
        "machine_checks": [
            {"id": "ungated", "kind": "file",
             "path": "${WORK}/nothing-here", "mode": "absent"},
            {"id": "gated", "kind": "file", "requires_module": module,
             "path": "${WORK}/nothing-here", "mode": "absent"},
        ],
    }


class TestRequiresModuleGate:
    def test_the_shipped_gongmun_checks_declare_the_gate(self):
        task = cleanroom.load_task(G1_TASK)
        gated = {check["id"]: check.get("requires_module")
                 for check in task["machine_checks"]}
        assert gated["gongmun_blank_form_shape"] == "gongmun"
        assert gated["gongmun_structure"] == "gongmun"
        # …and nothing else in the task is gated: the core checks must run
        # everywhere, module or no module.
        assert {cid for cid, module in gated.items() if module} == {
            "gongmun_blank_form_shape", "gongmun_structure"}

    def test_a_bad_requires_module_value_is_refused(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            GOOD_TASK.replace("    kind: file\n",
                              "    kind: file\n    requires_module: Not A Name\n"),
            encoding="utf-8")
        with pytest.raises(cleanroom.CleanroomError) as excinfo:
            cleanroom.load_task(path)
        assert "requires_module must be" in str(excinfo.value)

    def test_gated_check_runs_where_the_module_is_enabled(self, prepared):
        """``prepared`` installs core + style with ``--enable all``: style IS
        enabled, so a check gated on it must actually run."""
        assert prepared["report"]["registry"]["enabled"] == ["style"]
        task = _module_gated_task("style")
        cleanroom.materialize_task(prepared["root"], task)
        results = cleanroom.run_checks(prepared["root"], task)
        by_id = {row["id"]: row for row in results["checks"]}
        assert by_id["gated"]["status"] == "pass"
        assert by_id["ungated"]["status"] == "pass"
        assert results["enabled_modules"] == ["style"]
        assert results["counts"] == {"pass": 2, "fail": 0, "skipped": 0,
                                     "total": 2}

    def test_gated_check_skips_where_the_module_is_absent(self, prepared):
        """Same sandbox, a module that is not installed: skipped with a reason,
        NOT failed. Before the gate this was a red check about a product that
        was working exactly as designed."""
        task = _module_gated_task("gongmun")
        cleanroom.materialize_task(prepared["root"], task)
        results = cleanroom.run_checks(prepared["root"], task)
        by_id = {row["id"]: row for row in results["checks"]}
        assert by_id["gated"]["status"] == "skipped"
        assert by_id["gated"]["requires_module"] == "gongmun"
        assert "not enabled in this sandbox" in by_id["gated"]["reason"]
        assert "ok" not in by_id["gated"]
        # the ungated sibling still ran: the gate is per check, not per task
        assert by_id["ungated"]["status"] == "pass"

    def test_gated_check_skips_in_a_core_only_sandbox(self, tmp_path, bundles):
        report, code = cleanroom.prepare(
            tmp_path / "coreonly-gate", [bundles[0]], enable="none",
            allow_gaps=["no_module_bundles"])
        assert code == 0, report["failures"]
        root = Path(report["sandbox_root"])
        task = _module_gated_task("gongmun")
        cleanroom.materialize_task(root, task)
        results = cleanroom.run_checks(root, task)
        by_id = {row["id"]: row for row in results["checks"]}
        assert results["enabled_modules"] == []
        assert by_id["gated"]["status"] == "skipped"
        assert results["ok"] is True  # a skip is not a failure either

    def test_a_skipped_gate_never_inflates_the_pass_count(self, prepared):
        """The load-bearing property: counts.pass must not move when a gate
        skips, and score.py (which reads counts) must not call the run green
        on the strength of a skip."""
        enabled = _module_gated_task("style")
        absent = _module_gated_task("gongmun")
        cleanroom.materialize_task(prepared["root"], enabled)
        cleanroom.materialize_task(prepared["root"], absent)
        ran = cleanroom.run_checks(prepared["root"], enabled)
        skipped = cleanroom.run_checks(prepared["root"], absent)

        # These integers are the arity of ``_module_gated_task``, which this
        # file writes six lines up: exactly two checks, exactly one of them
        # gated. Not inventory — no shipped task, module or corpus document can
        # move them, and stating them literally is what makes the arithmetic
        # (1 pass + 1 skip, total unchanged) readable.
        assert ran["counts"]["pass"] == 2 and ran["counts"]["skipped"] == 0
        assert skipped["counts"]["pass"] == 1, (
            "a skipped gate was counted as a pass")
        assert skipped["counts"]["skipped"] == 1
        assert skipped["counts"]["total"] == ran["counts"]["total"]

        card = score.score_run(
            _run_record(task_id=absent["id"], judgment=[]),
            {**skipped, "task_id": absent["id"]}, absent)
        assert card["machine"]["pass"] == 1
        assert card["machine"]["skipped"] == 1
        assert card["machine"]["skipped_ids"] == ["gated"]
        # the skip is visible, and it is not counted among the passes
        assert card["machine"]["pass"] + card["machine"]["skipped"] == (
            card["machine"]["total"])


# --------------------------------------------------------------------------- #
# 4c. checkers[].wants: [baseline] — the harness supplies the blank form (G3)
# --------------------------------------------------------------------------- #
# The checker under test records the argv it was given, so the tests can assert
# what the HARNESS decided rather than trusting a verdict.
ARGV_RECORDER = """\
import json
import sys
from pathlib import Path

out = Path(sys.argv[0]).with_name("argv_seen.json")
out.write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
print(json.dumps({"ok": True, "checker": "recorder", "hard": [], "warn": [],
                  "counts": {"hard": 0, "warn": 0}}))
"""


def _baseline_task(*, declare_baseline: bool) -> dict:
    task = {
        "schema": cleanroom.TASK_SCHEMA,
        "id": f"wants-{'with' if declare_baseline else 'without'}-baseline",
        "family": "gongmun",
        "prompt": "wants probe",
        "input_files": [
            "tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx"],
        "expected_behavior": ["[judgment] n/a"],
        "machine_checks": [{"id": "probe", "kind": "file",
                            "path": "${WORK}/nothing", "mode": "absent"}],
    }
    if declare_baseline:
        task["baseline"] = "gianmun-byeolji-1ho.hwpx"
    return task


class TestCheckerWantsBaseline:
    """A checker DECLARES it needs the blank baseline; the harness supplies it.

    The harness is the consumer that was wired (evals/README.md §"wants:
    [baseline]"): it is the only runner that actually invokes gongmun's
    check_gongmun, and its tasks are where the blank form is declared.
    """

    @pytest.fixture
    def recorder(self, prepared):
        """A checker script inside the sandbox, plus the registry row that
        declares wants: [baseline] for it."""
        work = prepared["root"] / "work" / "recorder"
        work.mkdir(parents=True, exist_ok=True)
        script = work / "recorder.py"
        script.write_text(ARGV_RECORDER, encoding="utf-8")
        seen = work / "argv_seen.json"
        if seen.exists():
            seen.unlink()
        return {"script": script, "seen": seen, "work": work,
                "sandbox": cleanroom.Sandbox(prepared["root"])}

    @staticmethod
    def _variables(recorder) -> dict[str, str]:
        sandbox = recorder["sandbox"]
        return {"WORK": str(recorder["work"]), "INSTALL": str(sandbox.install),
                "SANDBOX": str(sandbox.root),
                "INPUTS": str(recorder["work"] / "inputs"),
                "SKILLS": str(sandbox.skills)}

    def test_a_declaring_checker_receives_the_baseline(self, recorder, tmp_path):
        blank = recorder["work"] / "blank.hwpx"
        blank.write_bytes(b"blank form")
        result = cleanroom.run_machine_check(
            recorder["sandbox"],
            {"id": "wants", "kind": "python",
             "argv": [str(recorder["script"]), "${WORK}/filled.hwpx"]},
            self._variables(recorder),
            checkers=[{"name": "recorder", "script": str(recorder["script"]),
                       "wants": ["baseline"]}],
            baseline=str(blank))
        assert result["status"] == "pass", result
        assert result["baseline"] == "supplied-by-harness"
        assert result["wants"] == ["baseline"]
        argv = json.loads(recorder["seen"].read_text(encoding="utf-8"))
        assert argv == [f"{recorder['work']}/filled.hwpx",
                        "--baseline", str(blank)]

    def test_without_a_declared_baseline_it_is_skipped_not_passed(
            self, recorder):
        result = cleanroom.run_machine_check(
            recorder["sandbox"],
            {"id": "wants", "kind": "python",
             "argv": [str(recorder["script"]), "${WORK}/filled.hwpx"]},
            self._variables(recorder),
            checkers=[{"name": "recorder", "script": str(recorder["script"]),
                       "wants": ["baseline"]}],
            baseline=None)
        assert result["status"] == "skipped"
        assert "no baseline" in result["reason"]
        assert "ok" not in result
        # and it really did not run: a self-skipping verdict would have
        # exited 0 and scored a pass
        assert not recorder["seen"].exists()

    def test_a_baseline_already_in_argv_is_not_supplied_twice(self, recorder):
        """Explicit --baseline, and 'the target IS the baseline' (a document is
        never its own baseline) — both leave the argv alone."""
        blank = recorder["work"] / "blank.hwpx"
        blank.write_bytes(b"blank form")
        checkers = [{"name": "recorder", "script": str(recorder["script"]),
                     "wants": ["baseline"]}]
        explicit = cleanroom.run_machine_check(
            recorder["sandbox"],
            {"id": "explicit", "kind": "python",
             "argv": [str(recorder["script"]), "${WORK}/filled.hwpx",
                      "--baseline", str(blank)]},
            self._variables(recorder), checkers=checkers, baseline=str(blank))
        assert explicit["baseline"] == "already-in-argv"
        assert json.loads(recorder["seen"].read_text(encoding="utf-8")).count(
            "--baseline") == 1

        recorder["seen"].unlink()
        on_the_blank = cleanroom.run_machine_check(
            recorder["sandbox"],
            {"id": "self", "kind": "python",
             "argv": [str(recorder["script"]), str(blank)]},
            self._variables(recorder), checkers=checkers, baseline=str(blank))
        assert on_the_blank["baseline"] == "already-in-argv"
        assert json.loads(recorder["seen"].read_text(encoding="utf-8")) == [
            str(blank)]

    def test_a_non_declaring_checker_is_unaffected(self, recorder):
        blank = recorder["work"] / "blank.hwpx"
        blank.write_bytes(b"blank form")
        result = cleanroom.run_machine_check(
            recorder["sandbox"],
            {"id": "plain", "kind": "python",
             "argv": [str(recorder["script"]), "${WORK}/filled.hwpx"]},
            self._variables(recorder),
            checkers=[{"name": "recorder", "script": str(recorder["script"]),
                       "wants": []}],
            baseline=str(blank))
        assert result["status"] == "pass", result
        assert "baseline" not in result and "wants" not in result
        assert json.loads(recorder["seen"].read_text(encoding="utf-8")) == [
            f"{recorder['work']}/filled.hwpx"]

    def test_an_unregistered_script_declares_nothing(self, recorder):
        """Resolution is by path against the registry — a script the registry
        never reported (core CLI, disabled module) is left alone."""
        assert cleanroom.checker_wants(
            recorder["sandbox"], str(recorder["script"]),
            [{"name": "other", "script": str(recorder["work"] / "other.py"),
              "wants": ["baseline"]}]) == []

    def test_materialize_records_the_declared_baseline(self, prepared):
        task = _baseline_task(declare_baseline=True)
        payload = cleanroom.materialize_task(prepared["root"], task)
        assert Path(payload["baseline"]).is_file()
        assert Path(payload["baseline"]).name == task["baseline"]
        on_disk = json.loads(
            (Path(payload["work_dir"]) / "task.json").read_text(
                encoding="utf-8"))
        assert on_disk["baseline"] == payload["baseline"]

        results = cleanroom.run_checks(prepared["root"], task)
        assert results["baseline"] == payload["baseline"]

    def test_no_declared_baseline_is_recorded_as_none(self, prepared):
        task = _baseline_task(declare_baseline=False)
        payload = cleanroom.materialize_task(prepared["root"], task)
        assert payload["baseline"] is None
        assert cleanroom.task_baseline(Path(payload["work_dir"]), task) is None

    def test_a_baseline_that_is_not_an_input_is_refused(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            GOOD_TASK + "baseline: not-an-input.hwpx\n", encoding="utf-8")
        with pytest.raises(cleanroom.CleanroomError) as excinfo:
            cleanroom.load_task(path)
        assert "must be a task input" in str(excinfo.value)

    def test_end_to_end_the_real_checker_gets_its_baseline(
            self, tmp_path, tmp_path_factory):
        """The whole G3 loop over real payload: gongmun's module.yaml declares
        wants: [baseline], the G1 task declares the blank form, and the harness
        hands it to the checker — proven from the checker's OWN verdict, whose
        baseline-only rules must no longer report ``no_baseline``."""
        out = tmp_path_factory.mktemp("dist_gongmun")
        gongmun_bundles = [package_module.build_bundle(name, out)
                           for name in ("core", "gongmun")]
        report, code = cleanroom.prepare(
            tmp_path / "gongmun", gongmun_bundles, enable="all")
        assert code == 0, report["failures"]
        root = Path(report["sandbox_root"])
        assert report["registry"]["enabled"] == ["gongmun"]

        task = cleanroom.load_task(G1_TASK)
        payload = cleanroom.materialize_task(root, task)
        work = Path(payload["work_dir"])
        # stand in for the agent: a "draft" that is the form passed through
        shutil.copy2(payload["baseline"], work / "filled.hwpx")

        results = cleanroom.run_checks(root, task)
        by_id = {row["id"]: row for row in results["checks"]}
        assert by_id["gongmun_structure"]["baseline"] == "supplied-by-harness"
        # the check deliberately targets the blank form itself: no self-baseline
        assert by_id["gongmun_blank_form_shape"]["baseline"] == "already-in-argv"
        assert by_id["gongmun_blank_form_shape"]["status"] == "pass"

        verdict = json.loads(
            (work / "gongmun_verdict.json").read_text(encoding="utf-8"))
        assert [row for row in verdict["skipped"]
                if row["reason"] == "no_baseline"] == [], (
            "the checker still says no_baseline — the harness did not supply "
            "the declared blank form")

    def test_the_gongmun_task_declares_a_baseline_and_stops_hardcoding_it(self):
        task = cleanroom.load_task(G1_TASK)
        assert task["baseline"] == "gianmun-byeolji-1ho.hwpx"
        structure = next(check for check in task["machine_checks"]
                         if check["id"] == "gongmun_structure")
        assert "--baseline" not in structure["argv"], (
            "the task should no longer have to know; check_gongmun declares "
            "wants: [baseline] and the harness supplies it")
        blank_shape = next(check for check in task["machine_checks"]
                           if check["id"] == "gongmun_blank_form_shape")
        assert "${BASELINE}" in blank_shape["argv"]

    def test_g1_draft_intent_does_not_require_the_forbidden_bigo_block(self):
        """T45: task intent and document evidence are separate inputs.

        The prompt asks for a draft, while the form says its 비고 block is not
        part of the form.  Encoding "draft" as auto-state forced an agent to
        retain that block, making the machine task green and the mandatory
        visual rubric red.  The task must force its requested state and also
        prove the visible instruction is absent.
        """
        task = cleanroom.load_task(G1_TASK)
        structure = next(check for check in task["machine_checks"]
                         if check["id"] == "gongmun_structure")
        assert structure["argv"][2:4] == ["--mode", "draft"]
        assert 'document.state_used == "draft"' in structure["assert_json"]
        assert 'document.state == "draft"' not in structure["assert_json"]

        absence = next(check for check in task["machine_checks"]
                       if check["id"] == "bigo_removed")
        assert absence["kind"] == "text_absent"
        assert absence["artifact"] == "${WORK}/filled.hwpx"
        assert "이 난은 서식에 포함하지 아니한다" in absence["strings"]

    def test_installed_recipe_pins_native_powershell_exit_capture(self,
                                                                  prepared):
        """T46: Codex's outer shell may display 1 for native exit 3.

        The buyer-facing recipe must show how to capture the checker process'
        own 0/2/3 result before a harness wrapper can normalize it.
        """
        recipe = (Path(prepared["report"]["skill"]["install_root"])
                  / "references" / "fill-recipe.md").read_text(
                      encoding="utf-8")
        assert "$LASTEXITCODE" in recipe
        assert "DIRECT_EXIT=$native" in recipe
        assert "exit $native" in recipe


# --------------------------------------------------------------------------- #
# 5. score.py
# --------------------------------------------------------------------------- #
def _run_record(**overrides) -> dict:
    record = {
        "schema": "rigorloom-eval-run/v1",
        "run_id": "A1-opus-001",
        "task_id": "A1-pps-recognize-fill",
        "tier": {"label": "opus", "model": "claude-opus-5"},
        "launcher": {"kind": "task-tool", "skill_loaded": True},
        "outcome": {"completed": True, "operator_intervened": False},
        "transcript": {"steps": 12, "tool_calls": 19, "retries": 1,
                       "tokens": {"input": 40000, "output": 3000,
                                  "total": 43000}},
        "judgment": [{"verdict": "pass"}] * 5,
        "failure_mode": None,
    }
    record.update(overrides)
    return record


def _checks(fail: int = 0) -> dict:
    """A checks payload for A1, DERIVED from A1's definition (#27).

    Every check A1 declares a gate on is ``skipped``, every other check
    ``pass``, and ``counts`` is tallied from the rows — so the payload keeps
    describing a core-only clean-room run of the real task no matter how many
    gated checks A1 grows. The old form listed three hand-written rows and
    pinned ``{"pass": 2, "skipped": 1}``, which is the same coupling as the
    direct assertion above: a second gated check in A1 made this fixture lie,
    and ``test_scorecard_join`` failed on a product that was working.
    """
    task = cleanroom.load_task(A1_TASK)
    skips = declared_skips(task)  # core-only: no distribution modules enabled
    rows = [{"id": check["id"],
             "status": "skipped" if check["id"] in skips else "pass"}
            for check in task["machine_checks"]]
    rows += [{"id": f"broken{index}", "status": "fail"}
             for index in range(fail)]
    tally = {status: sum(1 for row in rows if row["status"] == status)
             for status in ("pass", "fail", "skipped")}
    return {
        "schema": "rigorloom-eval-checks/v1",
        "task_id": task["id"],
        "family": task["family"],
        "counts": {**tally, "total": len(rows)},
        "ok": fail == 0,
        "checks": rows,
    }


class TestScore:
    def test_scorecard_join(self):
        task = cleanroom.load_task(A1_TASK)
        card = score.score_run(_run_record(), _checks(), task)
        assert card["schema"] == score.SCORECARD_SCHEMA
        assert card["passed"] is True
        assert card["blockers"] == []
        # Derived from the task, not pinned (#27): the scorecard must report
        # every declared gate as a skip, by identity.
        gated = declared_skips(task)
        assert gated, "A1 declares no gated check — this claim would be vacuous"
        assert card["machine"]["skipped"] == len(gated)
        assert sorted(card["machine"]["skipped_ids"]) == sorted(gated)
        assert card["machine"]["total"] == len(task["machine_checks"])
        assert card["judgment"]["rubric_total"] == len(task["expected_behavior"])
        assert card["judgment"]["complete"] is True
        assert card["efficiency"]["tokens_total"] == 43000

    def test_failed_machine_check_blocks_the_run(self):
        card = score.score_run(_run_record(), _checks(fail=2))
        assert card["passed"] is False
        assert "2 machine check(s) failed" in card["blockers"]
        assert card["machine"]["failed_ids"] == ["broken0", "broken1"]

    def test_missing_checks_are_never_scored_as_a_pass(self):
        card = score.score_run(_run_record())
        assert card["passed"] is False
        assert "machine checks were never run" in card["blockers"]
        assert card["machine"]["known"] is False

    def test_operator_intervention_invalidates_the_run(self):
        card = score.score_run(
            _run_record(outcome={"completed": True,
                                 "operator_intervened": True}),
            _checks())
        assert card["passed"] is False
        assert any("operator intervened" in blocker
                   for blocker in card["blockers"])

    def test_checks_for_another_task_are_refused(self):
        with pytest.raises(score.ScoreError):
            score.score_run(_run_record(task_id="P1-jumin-recognize-fill"),
                            _checks())

    @pytest.mark.parametrize("overrides,fragment", [
        ({"schema": "rigorloom-eval-run/v0"}, "schema must be"),
        ({"tier": {}}, "tier.label"),
        ({"launcher": {"kind": "telepathy"}}, "launcher.kind"),
        ({"transcript": {"steps": -1}}, "steps"),
        ({"judgment": [{"verdict": "maybe"}]}, "verdict"),
    ])
    def test_run_record_validation_is_loud(self, overrides, fragment):
        with pytest.raises(score.ScoreError) as excinfo:
            score.validate_run_record(_run_record(**overrides))
        assert fragment in str(excinfo.value)

    def test_comparison_table(self):
        opus = score.score_run(_run_record(), _checks())
        sonnet = score.score_run(
            _run_record(run_id="A1-sonnet-001",
                        tier={"label": "sonnet"},
                        failure_mode="edited the original in place",
                        transcript={"steps": 21, "tool_calls": 34,
                                    "retries": 4,
                                    "tokens": {"total": 61000}}),
            _checks(fail=1))
        comparison = score.compare([sonnet, opus])
        assert comparison["tiers"] == ["opus", "sonnet"]
        assert [row["tier"] for row in comparison["rows"]] == ["opus", "sonnet"]
        assert comparison["by_tier"]["opus"]["passed"] == 1
        assert comparison["by_tier"]["sonnet"]["passed"] == 0

        table = score.comparison_markdown(comparison)
        assert "| task | tier | result |" in table
        assert "edited the original in place" in table
        assert "PASS" in table and "FAIL" in table
        assert "61000" in table

    def test_compare_accepts_raw_run_records(self):
        comparison = score.compare(
            [score._as_scorecard(_run_record(), "run.json")])
        assert comparison["rows"][0]["machine"] == "unknown"

    def test_compare_cli_alias(self, tmp_path):
        card = score.score_run(_run_record(), _checks())
        path = tmp_path / "card.json"
        path.write_text(json.dumps(card), encoding="utf-8")
        out = tmp_path / "table.md"
        code = score.main(["--compare", str(path), "--out", str(out)])
        assert code == 0
        assert "| task | tier |" in out.read_text(encoding="utf-8")
