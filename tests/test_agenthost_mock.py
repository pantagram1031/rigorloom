# -*- coding: utf-8 -*-
"""The deterministic mock provider, end to end through a real agent door."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from _agenthost_support import HOST_CLI, agenthost_scripts_on_path
from _runtime_client import CORPUS_FORM, run_cli

agenthost_scripts_on_path()

import ah_mock  # noqa: E402
import mock_agent  # noqa: E402
import rt_core  # noqa: E402
from ah_host import AgentHost, summarize  # noqa: E402
from ah_provider import ProviderRequest  # noqa: E402

#: Above the loaded-spawn distribution measured in tests/test_subprocess_bounds.py;
#: the host spawns a runtime which spawns form_inspect.
HOST_TIMEOUT = 300.0

EXPECTED_TARGET = {"table": 0, "row": 0, "col": 14}


def _source(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    shutil.copyfile(CORPUS_FORM, target)
    return target


def run_host(root, *extra, expect_code=0):
    argv = [sys.executable, str(HOST_CLI), "--root", str(root)]
    argv += [str(item) for item in extra]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run(argv, capture_output=True, env=env, timeout=HOST_TIMEOUT)
    stdout = done.stdout.decode("utf-8", errors="replace")
    stderr = done.stderr.decode("utf-8", errors="replace")
    assert done.returncode == expect_code, (
        f"exit {done.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}")
    return json.loads(stdout)


@pytest.fixture()
def opened(tmp_path):
    root = tmp_path / "root"
    source = _source(tmp_path)
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    return root, source, session


# --- the provider in isolation ---------------------------------------------

def test_the_provider_asks_for_inspect_first():
    provider = ah_mock.MockProvider()
    response = provider.complete(ProviderRequest("do it", {"sessionId": "s"}, []))
    assert [call.name for call in response.tool_calls] == ["document_inspect"]
    assert response.finish_reason == "tool_calls"


def test_the_provider_is_a_pure_function_of_what_it_has_seen():
    provider = ah_mock.MockProvider()
    request = ProviderRequest("do it", {"sessionId": "s"}, [], history=[
        {"tool": "document_inspect", "ok": True,
         "result": {"regions": {"regions": [
             {"kind": "cell", "table": 0, "row": 5, "col": 1,
              "scriptAnomaly": False}]}}},
    ])
    first = provider.complete(request)
    second = provider.complete(request)
    assert first.tool_calls[0].public() == second.tool_calls[0].public()
    assert first.tool_calls[0].name == "plan_propose"
    op = first.tool_calls[0].arguments["ops"][0]
    assert op == {"kind": "fill_cell", "table": 0, "row": 5, "col": 1,
                  "text": ah_mock.MARKER}


def test_the_provider_uses_the_runtime_fixtures_own_seat_rule():
    """One rule for 'which seat', shared with runtime/scripts/mock_agent.py."""
    regions = [{"kind": "cell", "table": 0, "row": 2, "col": 0,
                "scriptAnomaly": True},
               {"kind": "cell", "table": 0, "row": 9, "col": 9,
                "scriptAnomaly": False}]
    assert mock_agent.choose_target(regions)["row"] == 9
    provider = ah_mock.MockProvider()
    response = provider.complete(ProviderRequest(
        "x", {"sessionId": "s"}, [], history=[
            {"tool": "document_inspect", "ok": True,
             "result": {"regions": {"regions": regions}}}]))
    assert response.tool_calls[0].arguments["ops"][0]["row"] == 9


def test_the_stream_is_the_same_answer_in_pieces():
    provider = ah_mock.MockProvider()
    request = ProviderRequest("x", {"sessionId": "s"}, [])
    chunks = list(provider.stream(request))
    assert chunks[-1]["type"] == "done"
    text = "".join(chunk["text"] for chunk in chunks if chunk["type"] == "text")
    assert text.strip() == provider.complete(request).text
    assert [c for c in chunks if c["type"] == "tool_call"]


def test_an_unknown_scenario_is_refused():
    from ah_codes import AgentHostError

    with pytest.raises(AgentHostError):
        ah_mock.MockProvider(scenario="do-whatever")


def test_the_summary_helper_keeps_events_small():
    assert summarize("plan_validate", {"validation": {"verdict": "fail", "ok": False,
                                                      "hard": [{"code": "x"}]}}) == \
        {"verdict": "fail", "ok": False, "hard": ["x"]}
    assert summarize("candidate_list", {"candidates": [1, 2]}) == {"candidates": 2}


# --- end to end -------------------------------------------------------------

def test_the_host_drives_inspect_propose_validate_approve_request(opened):
    root, _source_path, session = opened
    out = run_host(root, "--provider", "mock", "--scenario", "propose-one")
    assert out["ok"] is True and out["expectationMet"] is True
    assert out["sessionId"] == session
    assert out["plan"]["proposer"] == "agenthost-mock"
    op = out["plan"]["ops"][0]["params"]
    assert {k: op[k] for k in EXPECTED_TARGET} == EXPECTED_TARGET
    assert op["text"] == ah_mock.MARKER
    assert out["validation"]["ok"] is True
    assert out["approval"]["state"] == "pending"
    assert out["refusals"] == []
    assert out["providerFault"] is None


def test_the_event_log_tells_the_whole_story(opened):
    root, _source_path, _session = opened
    out = run_host(root, "--provider", "mock")
    kinds = [event["kind"] for event in out["events"]["events"]]
    assert kinds[0] == "run.started" and kinds[1] == "provider.selected"
    assert kinds[-1] == "run.finished"
    assert kinds.count("tool.compiled") == 4
    assert kinds.count("runtime.result") == 4
    assert [event["seq"] for event in out["events"]["events"]] == \
        list(range(len(kinds)))
    for event in out["events"]["events"]:
        assert set(event) <= {"seq", "kind", "detail"}


def test_the_event_log_can_be_mirrored_to_jsonl(opened, tmp_path):
    root, _source_path, _session = opened
    log = tmp_path / "events.jsonl"
    out = run_host(root, "--provider", "mock", "--events", str(log))
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    # the file is written as events happen, so it lacks only run.finished's echo
    assert len(lines) >= len(out["events"]["events"]) - 1
    for line in lines:
        assert set(json.loads(line)) <= {"seq", "kind", "detail"}


def test_no_candidate_is_ever_published_by_the_host_alone(opened):
    root, _source_path, session = opened
    run_host(root, "--provider", "mock")
    assert run_cli(root, "candidates", "--session",
                   session).result["candidates"] == []


def test_propose_invalid_stops_at_the_refusal(opened):
    root, _source_path, _session = opened
    out = run_host(root, "--provider", "mock", "--scenario", "propose-invalid")
    assert out["expectationMet"] is True
    assert out["validation"]["ok"] is False
    assert [row["code"] for row in out["validation"]["hard"]] == \
        ["cell_address_unknown"]
    assert out["approval"] is None


def test_escalating_is_refused_at_the_compile_gate_not_by_the_runtime(opened):
    root, _source_path, _session = opened
    out = run_host(root, "--provider", "mock", "--scenario", "escalate")
    assert out["expectationMet"] is True
    forbidden = [row for row in out["refusals"] if row["code"] == "tool_forbidden"]
    assert len(forbidden) == 1
    assert forbidden[0]["stage"] == "compile"
    assert forbidden[0]["data"]["method"] == "plan/apply"
    # the Runtime was never asked: no runtime.refused event for that tool
    kinds = [event["kind"] for event in out["events"]["events"]]
    assert "runtime.refused" not in kinds
    refused = [event for event in out["events"]["events"]
               if event["kind"] == "tool.refused"]
    assert len(refused) == 1 and refused[0]["detail"]["stage"] == "compile"
    # and it still finished politely rather than looping
    assert out["ok"] is True
    assert "refused" in (out["closingText"] or "")


def test_the_host_never_holds_a_host_method(opened):
    root, _source_path, _session = opened
    out = run_host(root, "--provider", "mock")
    assert set(out["surface"]).isdisjoint(rt_core.HOST_ONLY_METHODS)
    assert out["neverCompiled"] == list(rt_core.HOST_ONLY_METHODS)


def test_a_root_with_no_session_refuses_rather_than_inventing_one(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    out = run_host(empty, "--provider", "mock", expect_code=3)
    assert out["error"]["code"] == "runtime_unavailable"


def test_capabilities_needs_no_document_and_no_root():
    argv = [sys.executable, str(HOST_CLI), "--capabilities", "--provider", "mock"]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run(argv, capture_output=True, env=env, timeout=HOST_TIMEOUT)
    assert done.returncode == 0
    payload = json.loads(done.stdout.decode("utf-8"))
    assert payload["provider"]["providerId"] == "mock"


def test_running_without_a_root_is_a_usage_error():
    argv = [sys.executable, str(HOST_CLI), "--provider", "mock"]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run(argv, capture_output=True, env=env, timeout=HOST_TIMEOUT)
    assert done.returncode == 2


# --- determinism ------------------------------------------------------------

def test_two_runs_on_byte_identical_sources_agree_on_the_intent_hash(tmp_path):
    hashes = []
    for name in ("a", "b"):
        root = tmp_path / f"root-{name}"
        run_cli(root, "open", "--path", str(_source(tmp_path, f"{name}.hwpx")))
        hashes.append(run_host(root, "--provider", "mock")["plan"]["opsHash"])
    assert hashes[0] == hashes[1] and len(hashes[0]) == 64


def test_the_redacted_run_is_a_stable_golden_document(tmp_path):
    documents = []
    for name in ("a", "b"):
        root = tmp_path / f"root-{name}"
        run_cli(root, "open", "--path", str(_source(tmp_path, f"{name}.hwpx")))
        documents.append(run_host(root, "--provider", "mock", "--redact"))
    assert documents[0] == documents[1]
    # not two blank pages: identity redacted, content kept
    assert documents[0]["plan"]["planId"] == mock_agent.REDACTED
    assert documents[0]["plan"]["opsHash"] != mock_agent.REDACTED
    assert documents[0]["events"]["count"] > 10


def test_the_same_root_twice_repeats(opened):
    root, _source_path, _session = opened
    assert run_host(root, "--provider", "mock", "--redact") == \
        run_host(root, "--provider", "mock", "--redact")


def test_both_doors_reach_the_same_intent(opened):
    root, _source_path, _session = opened
    over_protocol = run_host(root, "--provider", "mock", "--door", "protocol")
    over_mcp = run_host(root, "--provider", "mock", "--door", "mcp")
    assert over_protocol["plan"]["opsHash"] == over_mcp["plan"]["opsHash"]


# --- the loop is bounded ----------------------------------------------------

def test_the_turn_budget_is_enforced_and_reported(opened):
    root, _source_path, _session = opened
    out = run_host(root, "--provider", "mock", "--max-turns", "2",
                   expect_code=3)
    assert out["turnBudgetExhausted"] is True
    assert out["turns"] == 2
    assert out["ok"] is False


def test_a_provider_that_raises_ends_the_run_as_a_provider_fault(tmp_path):
    """In-process, so the fault can be injected: no document verdict appears."""
    from ah_codes import ProviderError
    from ah_provider import CapabilityProfile, ProviderAdapter, cap
    from ah_codes import CAPABILITY_NAMES

    root = tmp_path / "root"
    run_cli(root, "open", "--path", str(_source(tmp_path)))

    class Broken(ProviderAdapter):
        provider_id = "broken"

        def capabilities(self):
            return CapabilityProfile(
                provider_id="broken", auth_ownership="none",
                capabilities={name: cap("unknown") for name in CAPABILITY_NAMES})

        def complete(self, request):
            raise ProviderError("provider_timeout", "nothing came back",
                                provider="broken")

    door = mock_agent.open_door("protocol", root, None)
    try:
        payload = AgentHost(door, Broken()).run("do it")
    finally:
        door.close()
    assert payload["ok"] is False
    assert payload["providerFault"]["code"] == "provider_timeout"
    assert payload["plan"] is None and payload["validation"] is None
    # nothing about the document was decided
    assert payload["refusals"] == []
    kinds = [event["kind"] for event in payload["events"]["events"]]
    assert "provider.failed" in kinds
    assert "runtime.refused" not in kinds
