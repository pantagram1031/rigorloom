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
    """One clean-room install, shared by the tests that only read it."""
    root = tmp_path_factory.mktemp("cleanroom") / "sandbox"
    report, code = cleanroom.prepare(
        root, bundles, enable="all",
        allow_gaps=["skill_surface_not_bundled"])
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

    def test_skill_surface_gap_is_reported_not_papered_over(self, prepared):
        gaps = {gap["id"]: gap for gap in prepared["report"]["gaps"]}
        assert "skill_surface_not_bundled" in gaps, (
            "if this fails the skill surface is now bundled — delete the "
            "acknowledgement from the fixture and README §4")
        assert gaps["skill_surface_not_bundled"]["severity"] == "HARD"
        assert set(prepared["report"]["skill"]["missing"]) == {
            "scripts/sync_local.py", "SKILL.md"}

    def test_unacknowledged_gap_fails_the_run(self, tmp_path, bundles):
        report, code = cleanroom.prepare(
            tmp_path / "unack", bundles, enable="all")
        assert code == 3
        assert report["ok"] is False
        assert any("skill_surface_not_bundled" in failure
                   for failure in report["failures"])

    def test_core_only_install(self, tmp_path, bundles):
        report, code = cleanroom.prepare(
            tmp_path / "coreonly", [bundles[0]], enable="none",
            allow_gaps=["no_module_bundles", "skill_surface_not_bundled"])
        assert code == 0, report["failures"]
        assert report["registry"]["enabled"] == []
        assert {gap["id"] for gap in report["gaps"]} == {
            "no_module_bundles", "skill_surface_not_bundled"}

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
        report, code = cleanroom.prepare(
            root, bundles, enable="all",
            allow_gaps=["skill_surface_not_bundled"])
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


class TestSkillInstallSeam:
    """The skill-install step is written against the BUNDLE tree and is
    dormant only because ``package_module`` does not yet ship ``skill/`` or
    ``scripts/sync_local.py``. Stage those two into an install and the step
    must work — otherwise closing the gap would land on untested code."""

    def test_skill_installs_from_the_sandbox_tree(self, tmp_path, bundles):
        report, code = cleanroom.prepare(
            tmp_path / "skillseam", bundles, enable="all", skip_skill=True,
            allow_gaps=["skill_surface_not_bundled"])
        assert code == 0, report["failures"]
        install = Path(report["sandbox_root"]) / "install"

        # simulate a future core bundle that carries the skill surface
        shutil.copytree(REPO_ROOT / "skill", install / "skill")
        shutil.copy2(REPO_ROOT / "scripts" / "sync_local.py",
                     install / "scripts" / "sync_local.py")

        sandbox = cleanroom.Sandbox(report["sandbox_root"])
        surface = cleanroom.locate_skill_surface(install)
        assert surface == {"present": True, "skill_md": "skill/SKILL.md",
                           "references": "skill/references"}

        result = cleanroom.install_skill(sandbox)
        assert result["ok"] is True, result
        installed = Path(result["install_root"]) / "SKILL.md"
        assert installed.is_file()
        body = installed.read_text(encoding="utf-8")
        assert "rigorloom-hwp" in body
        # merge_skill_fragments pulled the enabled module's fragment in
        assert "## Module: style" in body
        assert cleanroom._is_within(result["install_root"], sandbox.root)


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
