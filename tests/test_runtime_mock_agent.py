# -*- coding: utf-8 -*-
"""The deterministic mock agent: repeatable, structurally powerless, and honest.

Desktop tests and acceptance task C stand on this fixture, so what it promises
has to be measured here rather than described in its docstring: the same
document gives the same target and the same ``opsHash``, the redacted output is
a stable golden document, and the agent cannot approve or apply because those
methods are absent from the connection it holds.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from _runtime_client import CORPUS_FORM, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

import mock_agent  # noqa: E402
import rt_core  # noqa: E402

#: Above the loaded-spawn distribution measured in tests/test_subprocess_bounds.py;
#: the agent spawns a runtime which spawns form_inspect.
AGENT_TIMEOUT = 300.0

#: The first fill_target of this corpus form with no charPr anomaly. (2,0)
#: carries one and must be skipped; (0,14) is the answer.
EXPECTED_TARGET = {"table": 0, "row": 0, "col": 14}


def _source(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    shutil.copyfile(CORPUS_FORM, target)
    return target


def run_agent(root, *extra, expect_code=0):
    argv = [sys.executable, str(mock_agent.__file__), "--root", str(root)]
    argv += [str(item) for item in extra]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run(argv, capture_output=True, env=env,
                          timeout=AGENT_TIMEOUT)
    stdout = done.stdout.decode("utf-8", errors="replace")
    stderr = done.stderr.decode("utf-8", errors="replace")
    assert done.returncode == expect_code, (
        f"exit {done.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}")
    return json.loads(stdout)


@pytest.fixture()
def opened(tmp_path):
    """A host opens a document; the agent may only ever read it."""
    root = tmp_path / "root"
    source = _source(tmp_path)
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    return root, source, session


# --- unit: the deterministic choices ---------------------------------------

def test_the_target_is_the_first_clean_seat_in_document_order():
    regions = [
        {"kind": "cell", "table": 0, "row": 2, "col": 0, "scriptAnomaly": True,
         "charPr": "14"},
        {"kind": "cell", "table": 0, "row": 3, "col": 0, "scriptAnomaly": False,
         "colorAnomaly": True, "charPr": "15"},
        {"kind": "cell", "table": 0, "row": 5, "col": 1, "scriptAnomaly": False,
         "charPr": "18"},
        {"kind": "cell", "table": 0, "row": 5, "col": 2, "scriptAnomaly": False,
         "charPr": "18"},
    ]
    target = mock_agent.choose_target(regions)
    assert (target["row"], target["col"]) == (5, 1)
    assert target["documentIndex"] == 2


def test_a_seat_needing_a_charpr_is_never_silently_filled():
    regions = [{"kind": "cell", "table": 0, "row": 2, "col": 0,
                "scriptAnomaly": True}]
    with pytest.raises(mock_agent.DoorRefusal) as excinfo:
        mock_agent.choose_target(regions)
    assert excinfo.value.code == "no_clean_seat"
    assert excinfo.value.data["regionsConsidered"] == 1


def test_redact_blanks_identity_but_keeps_content_hashes():
    payload = {"planId": "abc", "createdUtc": "2026-01-01T00:00:00Z",
               "opsHash": "f" * 64, "boundSha256": "a" * 64,
               "nested": [{"approvalId": "x", "marker": "M"}]}
    out = mock_agent.redact(payload)
    assert out["planId"] == mock_agent.REDACTED
    assert out["createdUtc"] == mock_agent.REDACTED
    assert out["nested"][0]["approvalId"] == mock_agent.REDACTED
    assert out["opsHash"] == "f" * 64
    assert out["boundSha256"] == "a" * 64
    assert out["nested"][0]["marker"] == "M"


def test_the_invalid_address_is_a_fixed_constant():
    assert mock_agent.INVALID_ADDRESS == {"table": 0, "row": 9999, "col": 9999}
    assert mock_agent.DEFAULT_MARKER == "MOCK-AGENT-0001"


# --- structural powerlessness ----------------------------------------------

def test_the_agents_surface_has_no_host_method(opened):
    root, _source_path, _session = opened
    out = run_agent(root)
    assert set(out["surface"]).isdisjoint(rt_core.HOST_ONLY_METHODS)
    assert out["neverCalled"] == list(rt_core.HOST_ONLY_METHODS)


def test_probing_a_host_method_gets_unknown_method_not_permission_denied(opened):
    root, _source_path, _session = opened
    out = run_agent(root, "--probe-authority")
    probes = {row["method"]: row for row in out["authorityProbes"]}
    assert set(probes) == set(rt_core.HOST_ONLY_METHODS)
    for row in probes.values():
        assert row["code"] == "unknown_method"
        assert row["knownOnHostEntry"] is True


def test_no_candidate_appears_from_the_agent_alone(opened):
    root, _source_path, session = opened
    out = run_agent(root)
    assert out["observed"]["candidates"] == []
    assert run_cli(root, "candidates", "--session",
                   session).result["candidates"] == []


# --- scenarios --------------------------------------------------------------

def test_propose_one_walks_the_whole_agent_path(opened):
    root, _source_path, session = opened
    out = run_agent(root)
    assert out["ok"] is True and out["expectationMet"] is True
    assert out["door"] == "protocol" and out["scenario"] == "propose-one"
    assert out["sessionId"] == session
    assert {k: out["target"][k] for k in EXPECTED_TARGET} == EXPECTED_TARGET
    assert out["target"]["documentIndex"] == 0
    assert out["plan"]["proposer"] == "rigorloom-mock-agent"
    assert out["plan"]["ops"][0]["params"]["text"] == mock_agent.DEFAULT_MARKER
    assert out["validation"]["ok"] is True
    assert out["approval"]["state"] == "pending"
    assert out["observed"]["plan"]["state"] == "validated"
    assert [row["step"] for row in out["steps"]][:3] == [
        "session/list", "document/inspect", "target"]


def test_propose_invalid_expects_the_refusal_and_says_so(opened):
    root, _source_path, _session = opened
    out = run_agent(root, "--scenario", "propose-invalid")
    assert out["ok"] is True, "the scenario succeeded at failing, which is the point"
    assert out["expectationMet"] is True
    assert out["expectation"] == "validation refuses the target"
    assert out["validation"]["ok"] is False
    assert [row["code"] for row in out["validation"]["hard"]] == \
        ["cell_address_unknown"]
    assert out["approval"] is None
    assert out["observed"]["plan"]["state"] == "invalid"


def test_propose_then_wait_parks_on_a_pending_approval(opened):
    root, _source_path, _session = opened
    out = run_agent(root, "--scenario", "propose-then-wait")
    assert out["plan"]["planId"]
    assert out["waitingOn"]["approvalId"] == out["approval"]["approvalId"]
    assert out["waitingOn"]["state"] == "pending"
    assert out["waitingOn"]["resolvedBy"] == "a host; this agent cannot"
    assert out["pollAttempts"] == 2
    assert out["stableAcrossPolls"] is True


def test_a_root_with_no_session_refuses_rather_than_inventing_one(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    out = run_agent(empty, expect_code=3)
    assert out["ok"] is False
    assert out["error"]["code"] == "no_session"


def test_a_missing_root_is_a_usage_error(tmp_path):
    out = run_agent(tmp_path / "nope", expect_code=2)
    assert out["error"]["code"] == "invalid_params"


# --- determinism ------------------------------------------------------------

def test_two_runs_on_byte_identical_sources_agree_on_the_intent_hash(tmp_path):
    hashes = []
    for name in ("a", "b"):
        root = tmp_path / f"root-{name}"
        source = _source(tmp_path, f"{name}.hwpx")
        run_cli(root, "open", "--path", str(source))
        hashes.append(run_agent(root)["plan"]["opsHash"])
    assert hashes[0] == hashes[1]
    assert len(hashes[0]) == 64


def test_the_redacted_output_is_a_stable_golden_document(tmp_path):
    documents = []
    for name in ("a", "b"):
        root = tmp_path / f"root-{name}"
        source = _source(tmp_path, f"{name}.hwpx")
        run_cli(root, "open", "--path", str(source))
        documents.append(run_agent(root, "--redact"))
    assert documents[0] == documents[1]
    # and the redaction really happened, so this is not two blank pages
    assert documents[0]["plan"]["planId"] == mock_agent.REDACTED
    assert documents[0]["plan"]["opsHash"] != mock_agent.REDACTED
    assert documents[0]["target"]["row"] == 0


def test_the_same_root_twice_also_repeats(opened):
    root, _source_path, _session = opened
    first = run_agent(root, "--redact")
    second = run_agent(root, "--redact")
    assert first == second


def test_both_doors_reach_the_same_intent(opened):
    root, _source_path, _session = opened
    over_protocol = run_agent(root, "--door", "protocol")
    over_mcp = run_agent(root, "--door", "mcp")
    assert over_protocol["plan"]["opsHash"] == over_mcp["plan"]["opsHash"]
    assert over_protocol["target"] == over_mcp["target"]
    assert over_mcp["door"] == "mcp"
    # the MCP surface is the agent surface minus the protocol handshake
    assert set(over_mcp["surface"]) == {
        name.replace("/", "_")
        for name in over_protocol["surface"] if name != "initialize"}


# --- acceptance task C ------------------------------------------------------

def test_an_agent_proposed_plan_applied_by_a_host_matches_the_host_authored_one(
        tmp_path):
    """Agent proposes; host approves and applies; bytes match the host's own.

    Two roots, two byte-identical sources. On the first, the mock agent
    proposes and a host (in-process core) approves and applies. On the second,
    a host proposes the identical op itself and applies. The candidates must be
    the same bytes — otherwise "the agent uses the same plan path" is a slogan.
    """
    from rt_core import RuntimeCore

    agent_root = tmp_path / "agent-root"
    agent_source = _source(tmp_path, "agent.hwpx")
    run_cli(agent_root, "open", "--path", str(agent_source))
    proposed = run_agent(agent_root, "--scenario", "propose-then-wait")
    plan = proposed["plan"]
    approval = proposed["approval"]

    host = RuntimeCore(agent_root)
    host.approval_resolve(approval["approvalId"], plan["planId"],
                          plan["planHash"], "approved", "host-operator")
    applied = host.plan_apply(plan["planId"], approval["approvalId"])
    agent_sha = applied["candidate"]["candidate"]["sha256"]

    # the host's own equivalent, same op, no agent involved
    host_root = tmp_path / "host-root"
    host_source = _source(tmp_path, "host.hwpx")
    host_core = RuntimeCore(host_root)
    session = host_core.open_path(str(host_source))["sessionId"]
    op = mock_agent.build_op(proposed["target"], proposed["marker"])
    host_plan = host_core.plan_propose(session, "preedit", [op],
                                       "host-client")["plan"]
    assert host_core.plan_validate(host_plan["planId"])["validation"]["ok"]
    host_approval = host_core.approval_request(host_plan["planId"],
                                               "host-client")["approval"]
    host_core.approval_resolve(host_approval["approvalId"], host_plan["planId"],
                               host_plan["planHash"], "approved", "host-operator")
    host_applied = host_core.plan_apply(host_plan["planId"],
                                        host_approval["approvalId"])
    host_sha = host_applied["candidate"]["candidate"]["sha256"]

    assert plan["opsHash"] == host_plan["opsHash"]
    assert agent_sha == host_sha
    assert plan["planHash"] != host_plan["planHash"]


def test_the_applied_candidate_carries_the_agents_marker(tmp_path):
    from rt_core import RuntimeCore

    root = tmp_path / "root"
    source = _source(tmp_path)
    run_cli(root, "open", "--path", str(source))
    proposed = run_agent(root, "--scenario", "propose-then-wait")
    plan, approval = proposed["plan"], proposed["approval"]

    host = RuntimeCore(root)
    host.approval_resolve(approval["approvalId"], plan["planId"],
                          plan["planHash"], "approved", "operator")
    applied = host.plan_apply(plan["planId"], approval["approvalId"])
    run_id = applied["candidate"]["runId"]

    artifact = (root / "sessions" / proposed["sessionId"] / "candidates"
                / run_id / "artifact.hwpx")
    reopened = host.open_path(str(artifact))["sessionId"]
    region = host.document_read_region(reopened, [{
        "table": proposed["target"]["table"],
        "row": proposed["target"]["row"],
        "col": proposed["target"]["col"]}])["regions"][0]
    assert region["text"] == mock_agent.DEFAULT_MARKER

    # and the source the host opened is still byte-identical
    receipt = host.receipt_read(proposed["sessionId"], run_id)["receipt"]
    assert receipt["source"]["sha256"] == plan["boundSha256"]
