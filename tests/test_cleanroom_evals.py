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
        assert [row["bundle"] for row in report["verify"]] == [
            "rigorloom-core-0.16.0.zip", "rigorloom-style-0.16.0.zip"]
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
        tasks = cleanroom.load_tasks(TASKS_DIR)
        assert len(tasks) == 7
        assert {task["family"] for task in tasks} == {
            "grant", "petition", "gongmun", "hr", "research"}
        for task in tasks:
            assert task["prompt"].strip()
            assert all(entry.startswith("tests/corpus/forms/")
                       for entry in task["input_files"])

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
        assert len(payload["inputs"]) == 1
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
        assert by_id["repeat_fill_idempotent"]["status"] == "skipped"
        assert results["counts"]["skipped"] == 1

    def test_checks_pass_on_a_faithful_fill(self, materialized):
        """Prove the rubric is satisfiable: fill the form with the SANDBOX
        copy of preedit and every non-skipped check must come back green."""
        work = Path(materialized["payload"]["work_dir"])
        source = Path(materialized["payload"]["inputs"][0]["sandbox_path"])
        mapping = {
            "우(     -     )": "우 서울특별시 강남구 테헤란로 100",
            "년      월      일": "2026년   8월   20일",
            "기 업 명": "기 업 명 한빛정밀",
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
    rows = [{"id": "profile_blank", "status": "pass"},
            {"id": "residue_clean", "status": "pass"},
            {"id": "repeat_fill_idempotent", "status": "skipped"}]
    for index in range(fail):
        rows.append({"id": f"broken{index}", "status": "fail"})
    return {
        "schema": "rigorloom-eval-checks/v1",
        "task_id": "A1-pps-recognize-fill",
        "family": "grant",
        "counts": {"pass": 2, "fail": fail, "skipped": 1, "total": 3 + fail},
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
        assert card["machine"]["skipped"] == 1
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
