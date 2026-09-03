# -*- coding: utf-8 -*-
"""Apply class: execution, atomic publication, receipt binding, cancellation.

The end-to-end tests drive a real corpus form
(``tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx``) through real
``preedit`` and ``check_residue`` children. The rollback and unavailable-checker
tests call the library in-process, because the seam they need is a failure
injected between two renames — a monkeypatch is honest there and a test-only
hook inside the shipped module would not be.
"""
from __future__ import annotations

import hashlib
import shutil

import pytest

from _runtime_client import CORPUS_FORM, RuntimeClient, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_apply  # noqa: E402
import rt_codes  # noqa: E402
import rt_engine  # noqa: E402

OPS_ONE = [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "한빛"}]
OPS_THREE = [
    {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "하나"},
    {"kind": "fill_cell", "table": 0, "row": 5, "col": 2, "text": "둘"},
    {"kind": "fill_cell", "table": 0, "row": 5, "col": 4, "text": "셋"},
]


def _source(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    shutil.copyfile(CORPUS_FORM, target)
    return target


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drive(client, source, ops, *, approve=True):
    """openPath -> propose -> validate -> request -> resolve -> apply."""
    client.initialize()
    session = client.ok("workspace/openPath", {"path": str(source)})["sessionId"]
    plan = client.ok("plan/propose", {"sessionId": session, "backend": "preedit",
                                      "ops": ops})["plan"]
    validation = client.ok("plan/validate", {"planId": plan["planId"]})["validation"]
    assert validation["ok"] is True, validation["hard"]
    approval = client.ok("approval/request", {"planId": plan["planId"]})["approval"]
    if approve:
        client.ok("approval/resolve", {
            "approvalId": approval["approvalId"], "planId": plan["planId"],
            "planHash": plan["planHash"], "decision": "approved",
            "approver": "test-operator"})
    return session, plan, approval


# --- end to end -------------------------------------------------------------

def test_apply_publishes_a_bound_candidate(tmp_path):
    source = _source(tmp_path)
    with RuntimeClient(tmp_path / "root") as client:
        session, plan, approval = drive(client, source, OPS_ONE)
        result = client.ok("plan/apply", {"planId": plan["planId"],
                                          "approvalId": approval["approvalId"]})
        candidate = result["candidate"]
        assert candidate["canonical"] is True
        assert candidate["candidate"]["role"] == "assembled_hwpx"
        assert len(candidate["candidate"]["sha256"]) == 64

        listed = client.ok("candidate/list", {"sessionId": session})["candidates"]
        assert [row["runId"] for row in listed] == [candidate["runId"]]

        receipt = client.ok("receipt/read", {"sessionId": session,
                                             "runId": candidate["runId"]})["receipt"]
        assert receipt["schema"] == "rigorloom/runtime-candidate/v0"
        assert receipt["planHash"] == plan["planHash"]
        assert receipt["source"]["sha256"] == _sha256(source)
        assert receipt["approval"]["state"] == "approved"
        assert receipt["approval"]["approver"] == "test-operator"
        assert [step["opId"] for step in receipt["steps"]] == ["op-1"]
        assert receipt["steps"][0]["exitCode"] == 0
        assert receipt["implVersion"] == rt_codes.IMPL_VERSION
        assert receipt["evidence"]["class"] == "structural_only"

    artifact = (tmp_path / "root" / "sessions" / session / "candidates"
                / candidate["runId"] / candidate["candidate"]["path"])
    assert _sha256(artifact) == candidate["candidate"]["sha256"]


def test_the_candidate_actually_carries_the_edit(tmp_path):
    source = _source(tmp_path)
    with RuntimeClient(tmp_path / "root") as client:
        session, plan, approval = drive(client, source, OPS_ONE)
        result = client.ok("plan/apply", {"planId": plan["planId"],
                                          "approvalId": approval["approvalId"]})
        run_id = result["candidate"]["runId"]
        artifact = (tmp_path / "root" / "sessions" / session / "candidates"
                    / run_id / result["candidate"]["candidate"]["path"])
        second = client.ok("workspace/openPath", {"path": str(artifact)})["sessionId"]
        region = client.ok("document/readRegion", {
            "sessionId": second,
            "regions": [{"table": 0, "row": 5, "col": 1}]})["regions"][0]
        assert region["text"] == "한빛"


def test_a_multi_op_plan_chains_through_preedit(tmp_path):
    source = _source(tmp_path)
    with RuntimeClient(tmp_path / "root") as client:
        session, plan, approval = drive(client, source, OPS_THREE)
        result = client.ok("plan/apply", {"planId": plan["planId"],
                                          "approvalId": approval["approvalId"]})
        receipt = client.ok("receipt/read", {
            "sessionId": session,
            "runId": result["candidate"]["runId"]})["receipt"]
        assert [step["opId"] for step in receipt["steps"]] == ["op-1", "op-2", "op-3"]
        assert all(step["exitCode"] == 0 for step in receipt["steps"])


def test_a_backend_refusal_is_passed_through_verbatim(tmp_path):
    """The second fill hits a now-non-empty cell; preedit refuses at apply.

    Validation cannot see it — both ops are clean against the ORIGINAL profile —
    which is exactly the class ``preflight.deferred`` exists to admit.
    """
    source = _source(tmp_path)
    ops = [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "처음"},
           {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "두번째",
            "opId": "collide"}]
    with RuntimeClient(tmp_path / "root") as client:
        session, plan, approval = drive(client, source, ops)
        error = client.err("plan/apply", {"planId": plan["planId"],
                                          "approvalId": approval["approvalId"]})
        assert error["code"] == "backend_refused"
        assert error["data"]["opId"] == "collide"
        assert error["data"]["backend"] == "preedit"
        assert "--overwrite" in error["data"]["refusal"]["error"]
        # nothing was published
        assert client.ok("candidate/list", {"sessionId": session})["candidates"] == []


def test_a_refused_apply_leaves_no_work_directory(tmp_path):
    source = _source(tmp_path)
    ops = [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "처음"},
           {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "두번째"}]
    with RuntimeClient(tmp_path / "root") as client:
        session, plan, approval = drive(client, source, ops)
        client.err("plan/apply", {"planId": plan["planId"],
                                  "approvalId": approval["approvalId"]})
    work = tmp_path / "root" / "sessions" / session / "work"
    assert list(work.iterdir()) == []
    candidates = tmp_path / "root" / "sessions" / session / "candidates"
    assert list(candidates.iterdir()) == []


# --- the two-caller identity (orchestrator scope add) -----------------------

def test_an_agent_authored_plan_and_a_host_authored_plan_produce_identical_bytes(
        tmp_path):
    """One OperationPlan path: no code forks on who proposed it.

    Path A: the host opens the document, an AGENT connection proposes and
    validates the plan and requests approval, the host resolves and applies.
    Path B: the host does all of it against a byte-identical source.
    The candidate bytes must be the same.
    """
    source_a = _source(tmp_path, "a.hwpx")
    source_b = _source(tmp_path, "b.hwpx")
    assert _sha256(source_a) == _sha256(source_b)
    root = tmp_path / "shared"

    with RuntimeClient(root, entry="host") as host:
        host.initialize()
        session = host.ok("workspace/openPath", {"path": str(source_a)})["sessionId"]

        with RuntimeClient(root, entry="agent") as agent:
            agent.initialize()
            # the agent can see the host-opened session and address it
            assert session in [row["sessionId"]
                               for row in agent.ok("session/list", {})["sessions"]]
            plan_a = agent.ok("plan/propose", {
                "sessionId": session, "backend": "preedit",
                "ops": OPS_THREE, "proposer": "agent-of-record"})["plan"]
            assert agent.ok("plan/validate",
                            {"planId": plan_a["planId"]})["validation"]["ok"] is True
            approval_a = agent.ok("approval/request", {
                "planId": plan_a["planId"], "requestedBy": "agent-of-record"})["approval"]
            # and it cannot resolve or apply its own plan
            assert agent.err("approval/resolve", {
                "approvalId": approval_a["approvalId"],
                "planId": plan_a["planId"], "planHash": plan_a["planHash"],
                "decision": "approved"})["code"] == "unknown_method"

        host.ok("approval/resolve", {
            "approvalId": approval_a["approvalId"], "planId": plan_a["planId"],
            "planHash": plan_a["planHash"], "decision": "approved",
            "approver": "operator"})
        run_a = host.ok("plan/apply", {"planId": plan_a["planId"],
                                       "approvalId": approval_a["approvalId"]})
        sha_a = run_a["candidate"]["candidate"]["sha256"]

    with RuntimeClient(tmp_path / "solo", entry="host") as host:
        _, plan_b, approval_b = drive(host, source_b, OPS_THREE)
        run_b = host.ok("plan/apply", {"planId": plan_b["planId"],
                                       "approvalId": approval_b["approvalId"]})
        sha_b = run_b["candidate"]["candidate"]["sha256"]

    # the two plans really did differ in proposer, so the test is not vacuous
    assert plan_a["proposer"] == "agent-of-record"
    assert plan_b["proposer"] == "host-client"
    assert plan_a["planHash"] != plan_b["planHash"]
    assert sha_a == sha_b, "the candidate bytes depend on who authored the plan"


# --- atomic publication -----------------------------------------------------

def test_a_failure_between_the_two_renames_leaves_no_canonical_candidate(
        tmp_path, monkeypatch):
    """Kill mid-publish: the artifact landed, the receipt did not, so nothing did."""
    import rt_plan
    import rt_session

    source = _source(tmp_path)
    store = rt_session.SessionStore(tmp_path / "root")
    session = store.open_path(str(source))
    tools = rt_engine.EngineTools()
    plan = rt_plan.build_plan(session_id=session.id, backend="preedit",
                              ops=list(OPS_ONE), proposer="test",
                              bound_sha256=session.current_source_sha256())
    approval = rt_plan.request_approval(plan, "test")
    rt_plan.resolve_approval(approval, plan_id=plan.id, plan_hash=plan.hash,
                             decision="approved", approver="test")

    boom = RuntimeError("power cut between the artifact and the receipt")

    def explode(run_dir, receipt):
        raise boom

    monkeypatch.setattr(rt_apply, "_publish_receipt", explode)
    with pytest.raises(RuntimeError):
        rt_apply.apply_plan(tools, session, plan, approval)

    assert list(session.candidates_dir.iterdir()) == []
    assert list(session.work_dir.iterdir()) == []
    assert rt_apply.list_candidates(session) == []

    monkeypatch.undo()
    result = rt_apply.apply_plan(tools, session, plan, approval)
    assert result["canonical"] is True
    assert [row["runId"] for row in rt_apply.list_candidates(session)] == \
        [result["runId"]]


def test_a_run_directory_without_a_receipt_is_not_a_candidate(tmp_path):
    import rt_session

    store = rt_session.SessionStore(tmp_path / "root")
    session = store.open_path(str(_source(tmp_path)))
    orphan = session.candidates_dir / ("0" * 32)
    orphan.mkdir(parents=True)
    (orphan / "artifact.hwpx").write_bytes(b"not a candidate")
    assert rt_apply.list_candidates(session) == []


# --- receipt binding --------------------------------------------------------

def test_mutating_one_candidate_byte_refuses_the_receipt(tmp_path):
    source = _source(tmp_path)
    with RuntimeClient(tmp_path / "root") as client:
        session, plan, approval = drive(client, source, OPS_ONE)
        run_id = client.ok("plan/apply", {
            "planId": plan["planId"],
            "approvalId": approval["approvalId"]})["candidate"]["runId"]
        artifact = (tmp_path / "root" / "sessions" / session / "candidates"
                    / run_id / "artifact.hwpx")
        saved = artifact.read_bytes()

        client.ok("receipt/read", {"sessionId": session, "runId": run_id})

        mutated = bytearray(saved)
        mutated[len(mutated) // 2] ^= 0x01
        artifact.write_bytes(bytes(mutated))
        error = client.err("receipt/read", {"sessionId": session, "runId": run_id})
        assert error["code"] == "candidate_hash_mismatch"

        artifact.write_bytes(saved)  # restore from the saved copy, never git
        assert client.ok("receipt/read", {"sessionId": session,
                                          "runId": run_id})["receipt"]["runId"] == run_id


def test_mutating_the_receipt_body_refuses_it(tmp_path):
    source = _source(tmp_path)
    with RuntimeClient(tmp_path / "root") as client:
        session, plan, approval = drive(client, source, OPS_ONE)
        run_id = client.ok("plan/apply", {
            "planId": plan["planId"],
            "approvalId": approval["approvalId"]})["candidate"]["runId"]
        receipt_path = (tmp_path / "root" / "sessions" / session / "candidates"
                        / run_id / "receipt.json")
        saved = receipt_path.read_text(encoding="utf-8")

        receipt_path.write_text(saved.replace('"approver": "test-operator"',
                                              '"approver": "somebody else"'),
                                encoding="utf-8")
        error = client.err("receipt/read", {"sessionId": session, "runId": run_id})
        assert error["code"] == "receipt_body_mismatch"

        receipt_path.write_text(saved, encoding="utf-8")
        assert client.ok("receipt/read", {"sessionId": session, "runId": run_id})


def test_a_receipt_with_a_duplicate_member_is_refused(tmp_path):
    source = _source(tmp_path)
    with RuntimeClient(tmp_path / "root") as client:
        session, plan, approval = drive(client, source, OPS_ONE)
        run_id = client.ok("plan/apply", {
            "planId": plan["planId"],
            "approvalId": approval["approvalId"]})["candidate"]["runId"]
        receipt_path = (tmp_path / "root" / "sessions" / session / "candidates"
                        / run_id / "receipt.json")
        saved = receipt_path.read_text(encoding="utf-8")
        receipt_path.write_text(
            saved.replace('{\n', '{\n  "runId": "forged",\n', 1), encoding="utf-8")
        error = client.err("receipt/read", {"sessionId": session, "runId": run_id})
        assert error["code"] == "receipt_body_mismatch"
        assert error["data"]["strictCode"] == "duplicate_key"
        receipt_path.write_text(saved, encoding="utf-8")


def test_reading_an_unknown_run_is_refused(tmp_path):
    source = _source(tmp_path)
    with RuntimeClient(tmp_path / "root") as client:
        client.initialize()
        session = client.ok("workspace/openPath",
                            {"path": str(source)})["sessionId"]
        assert client.err("receipt/read", {"sessionId": session,
                                           "runId": "nope"})["code"] == \
            "artifact_missing"
        assert client.err("receipt/read", {"sessionId": session,
                                           "runId": "../escape"})["code"] == \
            "invalid_params"


# --- verification -----------------------------------------------------------

def test_a_missing_checker_is_unavailable_and_never_a_pass(tmp_path):
    """A gate may not claim more than it checked (privacy_scan.py:16-25)."""
    empty_root = tmp_path / "no-pipeline"
    (empty_root / "engine" / "scripts").mkdir(parents=True)
    tools = rt_engine.EngineTools(empty_root)
    assert tools.availability()["check_residue"]["state"] == "unavailable"

    report = rt_apply.verification_report(tools, tmp_path / "profile.json",
                                          tmp_path / "artifact.hwpx")
    row = report["checks"][0]
    assert row["state"] == "unavailable"
    assert row["ok"] is None and row["verdict"] is None
    assert report["ranAll"] is False
    assert report["acceptance"] is False
    assert report["reason"] == "a required check did not run"


def test_the_verification_report_records_a_real_checker_run(tmp_path):
    source = _source(tmp_path)
    with RuntimeClient(tmp_path / "root") as client:
        session, plan, approval = drive(client, source, OPS_ONE)
        result = client.ok("plan/apply", {"planId": plan["planId"],
                                          "approvalId": approval["approvalId"]})
        checks = result["candidate"]["checks"]
        row = next(r for r in checks["checks"] if r["checker"] == "check_residue")
        assert row["state"] == "ran"
        assert row["verdict"] in ("pass", "fail")
        assert checks["ranAll"] is True
        # a blank form filled in one cell still carries the form's own anchors,
        # so the residue gate legitimately reports findings here
        assert checks["acceptance"] is (row["ok"] is True)


# --- cancellation -----------------------------------------------------------

def test_cancel_stops_a_plan_between_steps_and_publishes_nothing(tmp_path):
    source = _source(tmp_path)
    with RuntimeClient(tmp_path / "root") as client:
        session, plan, approval = drive(client, source, OPS_THREE)
        client.send_frame({"kind": "request", "id": "apply-1", "method": "plan/apply",
                           "params": {"planId": plan["planId"],
                                      "approvalId": approval["approvalId"]}})
        client.send_frame({"kind": "cancel", "id": "apply-1"})
        frame = client.recv()
        assert frame["kind"] == "error"
        assert frame["error"]["code"] == "cancelled"
        assert client.ok("candidate/list", {"sessionId": session})["candidates"] == []
        # the connection is still usable afterwards
        assert client.ok("plan/get", {"planId": plan["planId"]})["plan"]["state"] \
            != "applied"


def test_a_cancel_frame_with_extra_members_is_refused(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        client.initialize()
        client.send_frame({"kind": "cancel", "id": "x", "reason": "because"})
        assert client.recv()["error"]["code"] == "unknown_field"
