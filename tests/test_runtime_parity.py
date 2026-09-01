# -*- coding: utf-8 -*-
"""Phase 2 exit criterion, measured.

"The same document, target, and proposed operation produce compatible plan and
verification representations through Runtime, CLI, and MCP."

Compatible is made precise here rather than argued:

  * ``opsHash`` — the intent hash over {backend, boundSha256, ops} — is
    IDENTICAL through all three front ends;
  * ``planHash`` — the approval binding, which covers identity and timestamp —
    DIFFERS between any two proposals, and must, or approving one plan would
    approve another;
  * the plan object is otherwise field-for-field equal once the identity fields
    are removed;
  * validation returns the same verdict, the same hard codes and the same
    warn codes;
  * a candidate applied from a CLI-authored plan and one applied from a
    server-authored plan have the same SHA-256;
  * an MCP-authored plan, approved on the CLI and applied over the server,
    produces that same SHA-256 — the cross-front-end handoff.

Everything runs against one real corpus form and real engine children.
"""
from __future__ import annotations

import shutil

import pytest

from _runtime_client import (
    CORPUS_FORM,
    McpClient,
    RuntimeClient,
    run_cli,
    runtime_scripts_on_path,
)

runtime_scripts_on_path()

import mcp_server  # noqa: E402
import rt_core  # noqa: E402
import rt_plan  # noqa: E402
import rt_server  # noqa: E402

OP = {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "한빛"}
ANOMALOUS_OP = {"kind": "fill_cell", "table": 0, "row": 2, "col": 0, "text": "X"}

#: Everything that identifies a proposal rather than describing it.
IDENTITY_FIELDS = ("planId", "planHash", "createdUtc", "proposer", "sessionId")


def _intent(plan: dict) -> dict:
    return {key: value for key, value in plan.items()
            if key not in IDENTITY_FIELDS}


def _verdict_shape(validation: dict) -> dict:
    return {
        "ok": validation["ok"],
        "verdict": validation["verdict"],
        "stale": validation["stale"],
        "hard": sorted(row["code"] for row in validation["hard"]),
        "warn": sorted(row["code"] for row in validation["warn"]),
        "deferred": validation["preflight"]["deferred"],
        "level": validation["preflight"]["level"],
    }


@pytest.fixture()
def source(tmp_path):
    target = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, target)
    return target


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "shared"


@pytest.fixture()
def session(root, source):
    """One session, opened by a host. All three front ends address it."""
    return run_cli(root, "open", "--path", str(source)).result["sessionId"]


@pytest.fixture()
def three_plans(root, session):
    """The same op proposed through the server, the CLI and MCP."""
    plans = {}
    with RuntimeClient(root, entry="host") as server:
        server.initialize()
        plans["server"] = server.ok("plan/propose", {
            "sessionId": session, "backend": "preedit", "ops": [OP]})["plan"]
    plans["cli"] = run_cli(
        root, "propose", "--session", session,
        "--op", '{"kind":"fill_cell","table":0,"row":5,"col":1,"text":"\\ud55c\\ube5b"}'
    ).result["plan"]
    with McpClient(root) as mcp:
        mcp.initialize()
        plans["mcp"] = mcp.ok("plan_propose", {
            "sessionId": session, "backend": "preedit", "ops": [OP]})["plan"]
    return plans


# --- the plan ---------------------------------------------------------------

def test_the_three_front_ends_agree_on_the_intent_hash(three_plans):
    hashes = {name: plan["opsHash"] for name, plan in three_plans.items()}
    assert len(set(hashes.values())) == 1, hashes
    assert len(next(iter(hashes.values()))) == 64


def test_the_intent_hash_is_what_the_document_and_the_ops_say(three_plans, root,
                                                              session):
    """Derived, not merely equal: recompute it from first principles."""
    plan = three_plans["server"]
    assert plan["opsHash"] == rt_plan.ops_hash(
        plan["backend"], plan["boundSha256"], plan["ops"])


def test_a_different_op_gives_a_different_intent_hash(root, session):
    first = run_cli(root, "propose", "--session", session,
                    "--op", '{"kind":"fill_cell","table":0,"row":5,"col":1,'
                            '"text":"a"}').result["plan"]
    second = run_cli(root, "propose", "--session", session,
                     "--op", '{"kind":"fill_cell","table":0,"row":5,"col":1,'
                             '"text":"b"}').result["plan"]
    assert first["opsHash"] != second["opsHash"]


def test_the_plan_objects_are_field_for_field_equal_apart_from_identity(
        three_plans):
    intents = {name: _intent(plan) for name, plan in three_plans.items()}
    assert intents["server"] == intents["cli"] == intents["mcp"]
    assert intents["server"]["schema"] == "rigorloom/runtime-plan/v0"
    assert intents["server"]["ops"][0]["opId"] == "op-1"


def test_the_plan_hash_still_separates_two_proposals(three_plans):
    """Parity must not become "every plan is the same plan"."""
    hashes = [plan["planHash"] for plan in three_plans.values()]
    assert len(set(hashes)) == 3, hashes
    proposers = {plan["proposer"] for plan in three_plans.values()}
    assert proposers == {"host-client", "cli-client", "mcp-client"}


def test_every_front_end_records_the_same_document_binding(three_plans):
    bound = {plan["boundSha256"] for plan in three_plans.values()}
    assert len(bound) == 1
    assert len(next(iter(bound))) == 64


# --- validation -------------------------------------------------------------

def test_the_three_front_ends_return_the_same_clean_verdict(root, three_plans):
    shapes = {}
    with RuntimeClient(root, entry="host") as server:
        server.initialize()
        shapes["server"] = _verdict_shape(server.ok(
            "plan/validate", {"planId": three_plans["server"]["planId"]}
        )["validation"])
    shapes["cli"] = _verdict_shape(run_cli(
        root, "validate", "--plan", three_plans["cli"]["planId"]
    ).result["validation"])
    with McpClient(root) as mcp:
        mcp.initialize()
        shapes["mcp"] = _verdict_shape(mcp.ok(
            "plan_validate", {"planId": three_plans["mcp"]["planId"]}
        )["validation"])
    assert shapes["server"] == shapes["cli"] == shapes["mcp"]
    assert shapes["server"]["ok"] is True
    assert shapes["server"]["hard"] == []


def test_the_three_front_ends_return_the_same_refusal_verdict(root, session):
    """A T30 anomaly must read identically wherever it is validated."""
    shapes = {}
    with RuntimeClient(root, entry="host") as server:
        server.initialize()
        plan = server.ok("plan/propose", {"sessionId": session,
                                          "backend": "preedit",
                                          "ops": [ANOMALOUS_OP]})["plan"]
        shapes["server"] = _verdict_shape(server.ok(
            "plan/validate", {"planId": plan["planId"]})["validation"])
    cli_plan = run_cli(root, "propose", "--session", session,
                       "--op", '{"kind":"fill_cell","table":0,"row":2,"col":0,'
                               '"text":"X"}').result["plan"]
    shapes["cli"] = _verdict_shape(run_cli(
        root, "validate", "--plan", cli_plan["planId"]).result["validation"])
    with McpClient(root) as mcp:
        mcp.initialize()
        mcp_plan = mcp.ok("plan_propose", {"sessionId": session,
                                           "backend": "preedit",
                                           "ops": [ANOMALOUS_OP]})["plan"]
        shapes["mcp"] = _verdict_shape(mcp.ok(
            "plan_validate", {"planId": mcp_plan["planId"]})["validation"])
    assert shapes["server"] == shapes["cli"] == shapes["mcp"]
    assert shapes["server"]["hard"] == ["fill_charpr_script_anomaly"]
    assert shapes["server"]["ok"] is False


def test_a_refusal_reads_the_same_through_every_front_end(root, session):
    """Same code, same data, whichever door the caller came through."""
    bad = {"kind": "insert_hyperlink", "url": "https://example.invalid"}
    with RuntimeClient(root, entry="host") as server:
        server.initialize()
        from_server = server.err("plan/propose", {"sessionId": session,
                                                  "backend": "preedit",
                                                  "ops": [bad]})
    from_cli = run_cli(root, "propose", "--session", session,
                       "--op", '{"kind":"insert_hyperlink",'
                               '"url":"https://example.invalid"}').error
    with McpClient(root) as mcp:
        mcp.initialize()
        from_mcp = mcp.err("plan_propose", {"sessionId": session,
                                            "backend": "preedit", "ops": [bad]})
    assert from_server["code"] == from_cli["code"] == from_mcp["code"] == \
        "unsupported_backend"
    assert (from_server["data"]["servedBy"] == from_cli["data"]["servedBy"]
            == from_mcp["data"]["servedBy"] == "com")


# --- the candidate ----------------------------------------------------------

def _approve_and_apply_over_server(root, plan):
    with RuntimeClient(root, entry="host") as server:
        server.initialize()
        approval = server.ok("approval/request",
                             {"planId": plan["planId"]})["approval"]
        server.ok("approval/resolve", {
            "approvalId": approval["approvalId"], "planId": plan["planId"],
            "planHash": plan["planHash"], "decision": "approved",
            "approver": "operator"})
        return server.ok("plan/apply", {"planId": plan["planId"],
                                        "approvalId": approval["approvalId"]})


def _approve_and_apply_over_cli(root, plan):
    approval = run_cli(root, "request-approval",
                       "--plan", plan["planId"]).result["approval"]
    run_cli(root, "approve", "--approval", approval["approvalId"],
            "--plan", plan["planId"], "--plan-hash", plan["planHash"],
            "--approver", "operator")
    return run_cli(root, "apply", "--plan", plan["planId"],
                   "--approval", approval["approvalId"]).result


def test_server_and_cli_produce_the_same_candidate_bytes(root, three_plans):
    from_server = _approve_and_apply_over_server(root, three_plans["server"])
    from_cli = _approve_and_apply_over_cli(root, three_plans["cli"])
    assert (from_server["candidate"]["candidate"]["sha256"]
            == from_cli["candidate"]["candidate"]["sha256"])
    assert (from_server["candidate"]["candidate"]["bytes"]
            == from_cli["candidate"]["candidate"]["bytes"])


def test_an_mcp_authored_plan_applied_by_a_host_lands_on_the_same_bytes(
        root, three_plans):
    """The cross-front-end handoff: MCP proposes, CLI approves, server applies."""
    mcp_plan = three_plans["mcp"]
    approval = run_cli(root, "request-approval",
                       "--plan", mcp_plan["planId"]).result["approval"]
    run_cli(root, "approve", "--approval", approval["approvalId"],
            "--plan", mcp_plan["planId"], "--plan-hash", mcp_plan["planHash"],
            "--approver", "operator")
    with RuntimeClient(root, entry="host") as server:
        server.initialize()
        applied = server.ok("plan/apply", {"planId": mcp_plan["planId"],
                                           "approvalId": approval["approvalId"]})
    from_cli = _approve_and_apply_over_cli(root, three_plans["cli"])
    assert (applied["candidate"]["candidate"]["sha256"]
            == from_cli["candidate"]["candidate"]["sha256"])


def test_the_receipts_agree_on_everything_but_identity(root, three_plans):
    from_server = _approve_and_apply_over_server(root, three_plans["server"])
    from_cli = _approve_and_apply_over_cli(root, three_plans["cli"])
    session = three_plans["server"]["sessionId"]
    with RuntimeClient(root, entry="host") as server:
        server.initialize()
        server_receipt = server.ok("receipt/read", {
            "sessionId": session,
            "runId": from_server["candidate"]["runId"]})["receipt"]
    cli_receipt = run_cli(root, "receipt", "--session", session,
                          "--run", from_cli["candidate"]["runId"]
                          ).result["receipt"]
    for receipt in (server_receipt, cli_receipt):
        assert receipt["schema"] == "rigorloom/runtime-candidate/v0"
    assert server_receipt["candidate"]["sha256"] == cli_receipt["candidate"]["sha256"]
    assert server_receipt["source"] == cli_receipt["source"]
    assert server_receipt["backend"] == cli_receipt["backend"]
    assert ([step["kind"] for step in server_receipt["steps"]]
            == [step["kind"] for step in cli_receipt["steps"]])
    assert (server_receipt["checks"]["ranAll"]
            == cli_receipt["checks"]["ranAll"] is True)
    assert server_receipt["planHash"] != cli_receipt["planHash"]


# --- the surfaces themselves ------------------------------------------------

def test_the_mcp_surface_equals_the_live_agent_registry(tmp_path):
    """Derived from a running agent server, not from a roster in this file.

    Two exclusions, both principled: ``initialize`` is MCP's own handshake, and
    the protocol-only methods push notifications, which an MCP tool call has
    nowhere to put. ``event/poll`` is the tool-shaped equivalent and IS exposed,
    so an MCP client is not left without the events.
    """
    agent = rt_server.RuntimeServer(entry="agent", root=tmp_path / "probe")
    excluded = {"initialize", *rt_core.PROTOCOL_ONLY_METHODS}
    expected = {mcp_server.tool_name(name) for name in agent._methods
                if name not in excluded}
    assert set(mcp_server.TOOL_TO_METHOD) == expected
    assert "event_poll" in mcp_server.TOOL_TO_METHOD
    for name in rt_core.PROTOCOL_ONLY_METHODS:
        assert mcp_server.tool_name(name) not in mcp_server.TOOL_TO_METHOD


def test_no_front_end_exposes_a_method_outside_the_roster(tmp_path):
    host = rt_server.RuntimeServer(entry="host", root=tmp_path / "h")
    assert set(host._methods) == set(rt_core.METHODS)
    agent = rt_server.RuntimeServer(entry="agent", root=tmp_path / "a")
    assert set(agent._methods) == (set(rt_core.AGENT_METHODS)
                                   | set(rt_core.PROTOCOL_ONLY_METHODS))
    # protocol-only methods are agent-SAFE: on both entries, adding no
    # authority, which is why the host set is simply the union
    assert set(rt_core.PROTOCOL_ONLY_METHODS) <= set(host._methods)
    assert set(rt_core.PROTOCOL_ONLY_METHODS).isdisjoint(
        rt_core.HOST_ONLY_METHODS)


def test_the_cli_reaches_host_methods_that_mcp_cannot(tmp_path, source):
    root = tmp_path / "r"
    assert run_cli(root, "open", "--path", str(source)).code == 0
    with McpClient(root) as mcp:
        mcp.initialize()
        assert mcp.err("workspace_openPath",
                       {"path": str(source)})["code"] == "unknown_method"


def test_candidate_verify_is_deliberately_not_a_protocol_method():
    """The CLI composes it; the wire does not grow a tool for it."""
    assert hasattr(rt_core.RuntimeCore, "candidate_verify")
    assert "candidate/verify" not in rt_core.METHODS
    assert "candidate_verify" not in mcp_server.TOOL_TO_METHOD
