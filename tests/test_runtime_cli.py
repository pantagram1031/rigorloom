# -*- coding: utf-8 -*-
"""CLI class: one JSON document per invocation, and honest exit codes."""
from __future__ import annotations

import json
import shutil

import pytest

from _runtime_client import CORPUS_FORM, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

import cli as runtime_cli  # noqa: E402

CLEAN_OP = json.dumps({"kind": "fill_cell", "table": 0, "row": 5, "col": 1,
                       "text": "한빛"}, ensure_ascii=False)
ANOMALOUS_OP = json.dumps({"kind": "fill_cell", "table": 0, "row": 2, "col": 0,
                           "text": "X"}, ensure_ascii=False)


@pytest.fixture()
def source(tmp_path):
    target = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, target)
    return target


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "root"


def _engine_without_pipeline(tmp_path):
    """An engine root that can edit but has no checkers.

    Real, not simulated: ``engine/scripts`` is copied verbatim so preedit and
    form_inspect genuinely run, and ``pipeline/scripts`` simply is not there,
    so ``check_residue`` is genuinely absent.
    """
    from _runtime_client import REPO_ROOT

    fake = tmp_path / "engine-only"
    shutil.copytree(REPO_ROOT / "engine" / "scripts", fake / "engine" / "scripts")
    return fake


def _drive(root, source, op=CLEAN_OP, engine_root=None):
    kwargs = {"engine_root": engine_root}
    session = run_cli(root, "open", "--path", str(source), **kwargs).result
    plan = run_cli(root, "propose", "--session", session["sessionId"],
                   "--op", op, **kwargs).result["plan"]
    run_cli(root, "validate", "--plan", plan["planId"], **kwargs)
    approval = run_cli(root, "request-approval", "--plan", plan["planId"],
                       **kwargs).result["approval"]
    run_cli(root, "approve", "--approval", approval["approvalId"],
            "--plan", plan["planId"], "--plan-hash", plan["planHash"],
            "--approver", "cli-operator", **kwargs)
    return session, plan, approval


# --- shape ------------------------------------------------------------------

def test_every_invocation_emits_exactly_one_json_document(root, source):
    result = run_cli(root, "open", "--path", str(source))
    assert result.code == 0
    assert result.stdout.count("\n") >= 1
    parsed = json.loads(result.stdout)
    assert parsed["ok"] is True and parsed["command"] == "open"
    assert len(parsed["result"]["source"]["sha256"]) == 64


def test_capabilities_reports_the_whole_method_roster(root):
    result = run_cli(root, "capabilities")
    assert result.code == 0
    methods = result.result["methods"]
    assert "plan/apply" in methods and "plan/propose" in methods


def test_inspect_and_read_region_work_from_the_command_line(root, source):
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    inspected = run_cli(root, "inspect", "--session", session,
                        "--include", "summary,regions").result
    assert inspected["summary"]["fillTargetCount"] == 9
    assert "graph" not in inspected
    region = run_cli(root, "read-region", "--session", session,
                     "--region", "0:5,1").result["regions"][0]
    assert region["addr"] == {"row": 5, "col": 1}


@pytest.mark.parametrize("spec,expected", [
    ("0:5,1", {"table": 0, "row": 5, "col": 1}),
    ("5,1", {"table": 0, "row": 5, "col": 1}),
    ("para:12", {"atPara": 12}),
])
def test_region_addresses_parse(spec, expected):
    assert runtime_cli._parse_region(spec) == expected


def test_a_malformed_region_address_is_a_usage_error(root, source):
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    result = run_cli(root, "read-region", "--session", session, "--region", "nope")
    assert result.code == 2
    assert result.error["code"] == "invalid_params"


# --- exit codes -------------------------------------------------------------

def test_usage_refusal_and_domain_refusal_have_different_exit_codes(root, source):
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]

    usage = run_cli(root, "propose", "--session", session,
                    "--op", '{"kind":"fill_cell","row":5,"col":1,"text":"x",'
                            '"sneaky":1}')
    assert usage.code == 2
    assert usage.error["code"] == "unknown_field"

    refusal = run_cli(root, "propose", "--session", session, "--backend", "com",
                      "--op", CLEAN_OP)
    assert refusal.code == 3
    assert refusal.error["code"] == "unsupported_backend"

    unknown = run_cli(root, "validate", "--plan", "0" * 32)
    assert unknown.code == 3
    assert unknown.error["code"] == "unknown_plan"


def test_bad_arguments_never_reach_the_domain(root):
    result = run_cli(root, "propose", "--session", "s")
    assert result.code == 2
    assert result.error["message"].startswith("propose needs")


def test_an_unreadable_ops_file_is_a_usage_error(root, tmp_path, source):
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    broken = tmp_path / "ops.json"
    broken.write_text("{not json", encoding="utf-8")
    result = run_cli(root, "propose", "--session", session,
                     "--ops-file", str(broken))
    assert result.code == 2


def test_the_exit_code_table_is_four_distinct_values():
    from rt_codes import EXIT_OK, EXIT_REFUSED, EXIT_USAGE

    values = {EXIT_OK, EXIT_USAGE, EXIT_REFUSED, runtime_cli.EXIT_INTERNAL}
    assert values == {0, 2, 3, 4}


# --- the whole path ---------------------------------------------------------

def test_the_cli_drives_a_plan_from_open_to_candidate(root, source):
    session, plan, approval = _drive(root, source)
    applied = run_cli(root, "apply", "--plan", plan["planId"],
                      "--approval", approval["approvalId"])
    assert applied.code == 0
    candidate = applied.result["candidate"]
    assert candidate["canonical"] is True

    listed = run_cli(root, "candidates", "--session",
                     session["sessionId"]).result["candidates"]
    assert [row["runId"] for row in listed] == [candidate["runId"]]

    receipt = run_cli(root, "receipt", "--session", session["sessionId"],
                      "--run", candidate["runId"]).result["receipt"]
    assert receipt["planHash"] == plan["planHash"]
    assert receipt["approval"]["approver"] == "cli-operator"
    # the source the operator named is untouched
    assert receipt["source"]["sha256"] == plan["boundSha256"]


def test_the_cli_refuses_an_ops_file_plan_it_cannot_validate(root, source):
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    plan = run_cli(root, "propose", "--session", session,
                   "--op", ANOMALOUS_OP).result["plan"]
    validation = run_cli(root, "validate", "--plan", plan["planId"]).result
    assert validation["validation"]["ok"] is False
    codes = [row["code"] for row in validation["validation"]["hard"]]
    assert "fill_charpr_script_anomaly" in codes


def test_approving_the_wrong_hash_is_refused_from_the_cli(root, source):
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    plan = run_cli(root, "propose", "--session", session,
                   "--op", CLEAN_OP).result["plan"]
    approval = run_cli(root, "request-approval",
                       "--plan", plan["planId"]).result["approval"]
    result = run_cli(root, "approve", "--approval", approval["approvalId"],
                     "--plan", plan["planId"], "--plan-hash", "0" * 64)
    assert result.code == 3
    assert result.error["code"] == "approval_binding_mismatch"


def test_reject_marks_the_plan_and_blocks_apply(root, source):
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    plan = run_cli(root, "propose", "--session", session,
                   "--op", CLEAN_OP).result["plan"]
    approval = run_cli(root, "request-approval",
                       "--plan", plan["planId"]).result["approval"]
    rejected = run_cli(root, "reject", "--approval", approval["approvalId"],
                       "--plan", plan["planId"],
                       "--plan-hash", plan["planHash"]).result["approval"]
    assert rejected["state"] == "rejected"
    blocked = run_cli(root, "apply", "--plan", plan["planId"],
                      "--approval", approval["approvalId"])
    assert blocked.code == 3
    assert blocked.error["code"] == "plan_not_approved"


# --- a successful exit does not mean verification ran -----------------------

def test_apply_exits_zero_while_a_required_check_could_not_run(root, source,
                                                               tmp_path):
    engine = _engine_without_pipeline(tmp_path)
    session, plan, approval = _drive(root, source, engine_root=engine)
    applied = run_cli(root, "apply", "--plan", plan["planId"],
                      "--approval", approval["approvalId"], engine_root=engine)
    assert applied.code == 0, applied.stdout
    checks = applied.result["candidate"]["checks"]
    assert checks["ranAll"] is False
    assert checks["acceptance"] is False
    row = checks["checks"][0]
    assert row["checker"] == "check_residue" and row["state"] == "unavailable"
    assert row["ok"] is None


def test_require_checks_turns_that_into_a_refusal_and_still_reports_it(
        root, source, tmp_path):
    engine = _engine_without_pipeline(tmp_path)
    session, plan, approval = _drive(root, source, engine_root=engine)
    applied = run_cli(root, "apply", "--plan", plan["planId"],
                      "--approval", approval["approvalId"],
                      "--require-checks", engine_root=engine)
    assert applied.code == 3
    assert applied.payload["ok"] is False
    # the candidate exists and is named: refusing to report it would be worse
    candidate = applied.payload["result"]["candidate"]
    assert candidate["canonical"] is True
    listed = run_cli(root, "candidates", "--session", session["sessionId"],
                     engine_root=engine).result["candidates"]
    assert [row["runId"] for row in listed] == [candidate["runId"]]


def test_verify_is_fail_closed_when_a_checker_is_missing(root, source, tmp_path):
    engine = _engine_without_pipeline(tmp_path)
    session, plan, approval = _drive(root, source, engine_root=engine)
    run_id = run_cli(root, "apply", "--plan", plan["planId"],
                     "--approval", approval["approvalId"],
                     engine_root=engine).result["candidate"]["runId"]
    verified = run_cli(root, "verify", "--session", session["sessionId"],
                       "--run", run_id, engine_root=engine)
    assert verified.code == 3
    assert verified.payload["result"]["checks"]["ranAll"] is False


def test_verify_passes_zero_when_the_checkers_actually_run(root, source):
    session, plan, approval = _drive(root, source)
    run_id = run_cli(root, "apply", "--plan", plan["planId"],
                     "--approval", approval["approvalId"]
                     ).result["candidate"]["runId"]
    verified = run_cli(root, "verify", "--session", session["sessionId"],
                       "--run", run_id)
    assert verified.code == 0
    row = verified.result["checks"]["checks"][0]
    assert row["state"] == "ran"


def test_verify_refuses_a_candidate_whose_bytes_moved(root, source):
    session, plan, approval = _drive(root, source)
    run_id = run_cli(root, "apply", "--plan", plan["planId"],
                     "--approval", approval["approvalId"]
                     ).result["candidate"]["runId"]
    artifact = (root / "sessions" / session["sessionId"] / "candidates" / run_id
                / "artifact.hwpx")
    saved = artifact.read_bytes()
    mutated = bytearray(saved)
    mutated[len(mutated) // 2] ^= 0x01
    artifact.write_bytes(bytes(mutated))
    result = run_cli(root, "verify", "--session", session["sessionId"],
                     "--run", run_id)
    assert result.code == 3
    assert result.error["code"] == "candidate_hash_mismatch"
    artifact.write_bytes(saved)
    assert run_cli(root, "verify", "--session", session["sessionId"],
                   "--run", run_id).code == 0
