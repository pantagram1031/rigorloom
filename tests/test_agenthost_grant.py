# -*- coding: utf-8 -*-
"""Read-scoped document context: only an operator grants it, and it is bounded.

The claims under test, in the order they matter:

  1. The agent CANNOT grant itself context. ``context/grant`` is refused by
     name at the compile gate, in either spelling, before the Runtime is asked.
  2. The agent CANNOT widen a grant. Under ``--read-scope granted`` a
     ``document_readRegion`` for an address the operator did not name is
     refused at the compile gate, not by the Runtime.
  3. What was granted, and what was actually disclosed, is recorded — with
     ADDRESSES and hashes, and without a character of document text.
  4. The grant survives the process. A second host on the same session finds
     the operator's decision still in force.

Nothing here talks to a provider over the network: the granted context is
inspected in the request the fake server received.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from _agenthost_support import (
    ANTHROPIC_ENV,
    PLACEHOLDER_ANTHROPIC_KEY,
    HOST_CLI,
    FakeRouter,
    agenthost_scripts_on_path,
    anthropic_config,
    anthropic_message,
)
from _runtime_client import CORPUS_FORM, run_cli

agenthost_scripts_on_path()

import ah_compile  # noqa: E402
import ah_mock  # noqa: E402
import mock_agent  # noqa: E402
import rt_core  # noqa: E402
from ah_anthropic import AnthropicAdapter  # noqa: E402
from ah_codes import HOST_CONTROL_METHODS, AgentHostError  # noqa: E402
from ah_grant import ContextGrant, GrantItem, parse_region_spec  # noqa: E402
from ah_host import AgentHost  # noqa: E402
from ah_provider import ToolCall  # noqa: E402
from ah_session import HostSession, read_records  # noqa: E402

SPAWN_TIMEOUT = 300.0

#: A real seat in the corpus form — the same one the mock provider fills.
GRANTED_SPEC = "0:0,14"
OTHER_SPEC = "0:1,3"


@pytest.fixture()
def opened(tmp_path):
    root = tmp_path / "root"
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    return root, session


def _grant(*specs, summary=False, scope="open"):
    items = ([GrantItem("summary")] if summary else [])
    items += [GrantItem("region", parse_region_spec(spec)) for spec in specs]
    return ContextGrant(items=tuple(items), granted_by="operator:cli",
                        read_scope=scope)


# --- 1. the agent cannot grant itself anything ------------------------------

def test_the_control_methods_are_on_no_provider_surface():
    assert set(HOST_CONTROL_METHODS).isdisjoint(rt_core.AGENT_METHODS)
    assert set(HOST_CONTROL_METHODS).isdisjoint(rt_core.METHODS)
    assert set(ah_compile.ALLOWED_TOOLS).isdisjoint(ah_compile.HOST_CONTROL_TOOLS)


@pytest.mark.parametrize("name", ["context/grant", "context_grant",
                                  "context/revoke", "context_revoke",
                                  "shutdown", "turn"])
def test_a_model_asking_for_a_control_method_is_refused_by_name(name):
    with pytest.raises(AgentHostError) as excinfo:
        ah_compile.compile_tool_call(ToolCall("c1", name, {}))
    assert excinfo.value.code == "tool_forbidden"
    assert excinfo.value.data["hostControl"] == list(HOST_CONTROL_METHODS)


def test_the_host_only_refusals_are_unchanged(opened):
    """The Phase-2 gate still refuses what it always refused."""
    for method in rt_core.HOST_ONLY_METHODS:
        for spelling in (method, method.replace("/", "_")):
            with pytest.raises(AgentHostError) as excinfo:
                ah_compile.compile_tool_call(ToolCall("c", spelling, {}))
            assert excinfo.value.code == "tool_forbidden"
            assert excinfo.value.data["method"] == method

    root, _session = opened
    door = mock_agent.open_door("protocol", root, None)
    try:
        payload = AgentHost(door, ah_mock.MockProvider(scenario="escalate")
                            ).run("apply it")
    finally:
        door.close()
    forbidden = [row for row in payload["refusals"]
                 if row["code"] == "tool_forbidden"]
    assert len(forbidden) == 1
    assert forbidden[0]["data"]["method"] == "plan/apply"
    assert payload["neverCompiled"] == list(rt_core.HOST_ONLY_METHODS)


# --- 2. the agent cannot widen a grant --------------------------------------

def test_an_open_scope_leaves_the_phase_two_surface_alone():
    """The default is not a silent tightening of what already shipped."""
    grant = ContextGrant.empty()
    assert grant.read_scope == "open"
    compiled = ah_compile.compile_tool_call(
        ToolCall("c", "document_readRegion",
                 {"sessionId": "s", "regions": [{"table": 9, "row": 9,
                                                 "col": 9}]}),
        scope=grant)
    assert compiled.method == "document/readRegion"


def test_a_granted_scope_refuses_an_address_the_operator_did_not_name():
    grant = _grant(GRANTED_SPEC, scope="granted")
    inside = ah_compile.compile_tool_call(
        ToolCall("c", "document_readRegion",
                 {"sessionId": "s", "regions": [parse_region_spec(GRANTED_SPEC)]}),
        scope=grant)
    assert inside.method == "document/readRegion"

    with pytest.raises(AgentHostError) as excinfo:
        ah_compile.compile_tool_call(
            ToolCall("c", "document_readRegion",
                     {"sessionId": "s",
                      "regions": [parse_region_spec(OTHER_SPEC)]}),
            scope=grant)
    assert excinfo.value.code == "grant_scope_exceeded"
    assert excinfo.value.data["granted"] == [GRANTED_SPEC]


def test_a_mixed_batch_is_refused_whole_rather_than_partly_served():
    grant = _grant(GRANTED_SPEC, scope="granted")
    with pytest.raises(AgentHostError) as excinfo:
        ah_compile.compile_tool_call(
            ToolCall("c", "document_readRegion",
                     {"sessionId": "s",
                      "regions": [parse_region_spec(GRANTED_SPEC),
                                  parse_region_spec(OTHER_SPEC)]}),
            scope=grant)
    assert excinfo.value.code == "grant_scope_exceeded"
    assert len(excinfo.value.data["refused"]) == 1


def test_a_none_scope_reads_nothing_at_all():
    with pytest.raises(AgentHostError) as excinfo:
        ah_compile.compile_tool_call(
            ToolCall("c", "document_readRegion",
                     {"sessionId": "s", "regions": [{"atPara": 1}]}),
            scope=ContextGrant.empty(read_scope="none"))
    assert excinfo.value.code == "grant_scope_exceeded"


def test_a_scope_never_touches_the_other_agent_methods():
    grant = _grant(GRANTED_SPEC, scope="granted")
    for tool in ("document_inspect", "plan_propose", "candidate_list"):
        compiled = ah_compile.compile_tool_call(
            ToolCall("c", tool, {"sessionId": "s"}), scope=grant)
        assert compiled.tool == tool


def test_the_runtime_is_never_asked_for_context_outside_the_grant(opened, env):
    """End to end: a model reaching past the grant, refused before the door."""
    root, session_id = opened

    def greedy(path, body):
        seen = [block.get("name")
                for message in body["messages"] if message["role"] == "assistant"
                for block in message["content"] if block.get("type") == "tool_use"]
        if "document_readRegion" not in seen:
            return {"json": anthropic_message(None, tool_calls=[
                {"id": "toolu_g", "name": "document_readRegion",
                 "input": {"sessionId": session_id,
                           "regions": [parse_region_spec(OTHER_SPEC)]}}])}
        return {"json": anthropic_message("I was told no.")}

    with FakeRouter(greedy) as srv:
        door = mock_agent.open_door("protocol", root, None)
        try:
            payload = AgentHost(
                door, AnthropicAdapter(anthropic_config(srv.base_url)),
                grant=_grant(GRANTED_SPEC, scope="granted"),
                stream_mode="off").run("read the whole form")
        finally:
            door.close()
    refused = [row for row in payload["refusals"]
               if row["code"] == "grant_scope_exceeded"]
    assert len(refused) == 1 and refused[0]["stage"] == "compile"
    kinds = [event["kind"] for event in payload["events"]["events"]]
    assert "context.refused" in kinds
    assert "runtime.refused" not in kinds
    assert "tool.compiled" not in kinds


# --- 3. what is recorded, and what is not -----------------------------------

def test_granted_context_reaches_the_prompt_and_only_the_prompt(opened, env):
    root, session_id = opened
    grant = _grant(GRANTED_SPEC, summary=True)

    with FakeRouter(lambda path, body: {
            "json": anthropic_message("Read it, thanks.")}) as srv:
        door = mock_agent.open_door("protocol", root, None)
        try:
            payload = AgentHost(
                door, AnthropicAdapter(anthropic_config(srv.base_url)),
                grant=grant, stream_mode="off").run("summarise it")
        finally:
            door.close()
        sent = json.loads(
            srv.requests[0]["body"]["messages"][0]["content"][0]["text"])

    block = sent["context"]["documentContext"]
    assert block["grantId"] == grant.grant_id
    assert block["grantedBy"] == "operator:cli"
    assert "documentSummary" in block and block["regions"]

    disclosed = payload["contextDisclosed"]
    assert disclosed["count"] == 2
    assert {row["kind"] for row in disclosed["items"]} == {"summary", "region"}
    for row in disclosed["items"]:
        assert len(row["sha256"]) == 64 and row["bytes"] > 0
    # the addresses are named; the text is not anywhere in the run document
    assert payload["grant"]["items"][1]["spec"] == GRANTED_SPEC
    document = json.dumps(payload, ensure_ascii=False)
    for region in block["regions"]:
        for value in region.values():
            if isinstance(value, str) and len(value) > 8:
                assert value not in document, "document text leaked into the run"


def test_the_disclosure_event_carries_hashes_not_text(opened, env):
    root, _session_id = opened
    with FakeRouter(lambda path, body: {
            "json": anthropic_message("ok")}) as srv:
        door = mock_agent.open_door("protocol", root, None)
        try:
            payload = AgentHost(
                door, AnthropicAdapter(anthropic_config(srv.base_url)),
                grant=_grant(GRANTED_SPEC), stream_mode="off").run("read it")
        finally:
            door.close()
    included = [event for event in payload["events"]["events"]
                if event["kind"] == "context.included"]
    assert len(included) == 1
    detail = included[0]["detail"]
    assert detail["grantId"] and detail["count"] == 1
    assert set(detail["items"][0]) == {"kind", "spec", "bytes", "sha256"}


def test_the_grant_record_names_addresses_and_no_text(opened):
    root, session_id = opened
    store = HostSession(root, session_id).load()
    record = store.append_grant(_grant(GRANTED_SPEC, summary=True))
    assert record["action"] == "grant"
    assert record["at"].endswith("Z")
    assert [item["kind"] for item in record["items"]] == ["summary", "region"]
    assert record["items"][1]["spec"] == GRANTED_SPEC
    assert set(json.loads(json.dumps(record))) == {
        "schema", "at", "sessionId", "action", "grantId", "grantedBy",
        "readScope", "items"}


def test_an_empty_grant_discloses_nothing(opened):
    root, _session_id = opened
    door = mock_agent.open_door("protocol", root, None)
    try:
        payload = AgentHost(door, ah_mock.MockProvider()).run("fill it")
    finally:
        door.close()
    assert payload["contextDisclosed"] is None
    assert payload["grant"]["items"] == []
    assert "context.included" not in [event["kind"]
                                      for event in payload["events"]["events"]]


# --- 4. the grant outlives the process --------------------------------------

def test_a_grant_survives_into_the_next_host(opened):
    root, session_id = opened
    first = HostSession(root, session_id).load()
    first.append_grant(_grant(GRANTED_SPEC, scope="granted"))
    second = HostSession(root, session_id).load()
    live = second.current_grant()
    assert live.keys == (GRANTED_SPEC,)
    assert live.read_scope == "granted"
    assert live.granted_by == "operator:cli"


def test_a_revoke_is_a_record_rather_than_a_deletion(opened):
    root, session_id = opened
    store = HostSession(root, session_id).load()
    store.append_grant(_grant(GRANTED_SPEC, scope="granted"))
    store.append_grant(ContextGrant.empty(read_scope="granted"),
                       action="revoke")
    reloaded = HostSession(root, session_id).load()
    assert reloaded.current_grant().is_empty()
    records, _skipped = read_records(reloaded.grants_path)
    assert [row["action"] for row in records] == ["grant", "revoke"]


def test_the_cli_grant_flags_are_the_operator_channel(opened):
    root, session_id = opened
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run(
        [sys.executable, str(HOST_CLI), "--root", str(root),
         "--provider", "mock", "--memory", "--grant-summary",
         "--grant-region", GRANTED_SPEC, "--read-scope", "granted"],
        capture_output=True, env=env, timeout=SPAWN_TIMEOUT)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    payload = json.loads(done.stdout.decode("utf-8"))
    assert payload["grant"]["readScope"] == "granted"
    assert payload["grant"]["grantedBy"] == "operator:cli"
    assert payload["contextDisclosed"]["count"] == 2
    records, _skipped = read_records(
        HostSession(root, session_id).grants_path)
    assert len(records) == 1 and records[0]["action"] == "grant"


def test_an_unparseable_grant_spec_is_a_usage_refusal(opened):
    root, _session_id = opened
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run(
        [sys.executable, str(HOST_CLI), "--root", str(root),
         "--provider", "mock", "--grant-region", "nonsense"],
        capture_output=True, env=env, timeout=SPAWN_TIMEOUT)
    assert done.returncode == 3
    payload = json.loads(done.stdout.decode("utf-8"))
    assert payload["error"]["code"] == "grant_invalid"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv(ANTHROPIC_ENV, PLACEHOLDER_ANTHROPIC_KEY)
    return ANTHROPIC_ENV
