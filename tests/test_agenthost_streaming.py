# -*- coding: utf-8 -*-
"""Streaming from the adapter all the way into the turn loop.

Two provers, no live calls anywhere:

  * the deterministic mock, whose stream is a pure function of its answer, and
  * the fake Anthropic server from ``tests/_agenthost_support.py``, over real
    SSE frames.

The property that matters most is negative: a partial tool call is never
dispatched. It is proven by cutting an SSE stream in the middle of a tool
block's ``input_json_delta`` and showing that the Runtime is never asked
anything, the plan stays ``None``, and the run ends as a named provider fault
rather than as a short answer.
"""
from __future__ import annotations

import json
import shutil

import pytest

from _agenthost_support import (
    ANTHROPIC_ENV,
    PLACEHOLDER_ANTHROPIC_KEY,
    FakeRouter,
    agenthost_scripts_on_path,
    anthropic_config,
    anthropic_sse,
    router_config,
    sse_lines,
)
from _runtime_client import CORPUS_FORM, run_cli

agenthost_scripts_on_path()

import ah_mock  # noqa: E402
import ah_stream  # noqa: E402
import mock_agent  # noqa: E402
from ah_anthropic import AnthropicAdapter  # noqa: E402
from ah_codes import CAPABILITY_NAMES, STREAM_CHUNK_TYPES, ProviderError  # noqa: E402
from ah_host import AgentHost  # noqa: E402
from ah_provider import (  # noqa: E402
    CapabilityProfile,
    ProviderAdapter,
    ProviderRequest,
    cap,
)
from ah_router import RouterAdapter  # noqa: E402

SPAWN_TIMEOUT = 300.0


@pytest.fixture()
def opened(tmp_path):
    root = tmp_path / "root"
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    run_cli(root, "open", "--path", str(source))
    return root


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv(ANTHROPIC_ENV, PLACEHOLDER_ANTHROPIC_KEY)
    return ANTHROPIC_ENV


def _request(**kwargs) -> ProviderRequest:
    base = {"instruction": "x", "context": {"sessionId": "s"}, "tools": []}
    base.update(kwargs)
    return ProviderRequest(**base)


class Scripted(ProviderAdapter):
    """Yields exactly the chunks a test hands it. Nothing clever."""

    provider_id = "scripted"

    def __init__(self, chunks, streaming: str = "yes"):
        self.chunks = list(chunks)
        self.streaming = streaming
        self.completed = 0

    def capabilities(self) -> CapabilityProfile:
        caps = {name: cap("yes") for name in CAPABILITY_NAMES}
        caps["streaming"] = cap(self.streaming, "scripted for a test")
        return CapabilityProfile(provider_id=self.provider_id,
                                 auth_ownership="none", capabilities=caps)

    def complete(self, request):
        from ah_provider import ProviderResponse
        self.completed += 1
        return ProviderResponse(text="non-streamed", finish_reason="stop")

    def stream(self, request):
        self.capabilities().require("streaming")
        yield from self.chunks


# --- the assembler ----------------------------------------------------------

def test_the_chunk_vocabulary_has_no_partial_tool_call_shape():
    """The negative property, stated as a fact about the vocabulary itself."""
    assert set(STREAM_CHUNK_TYPES) == {"text", "tool_call", "finish", "done"}


def test_text_deltas_assemble_into_one_answer():
    outcome = ah_stream.drain(Scripted([
        {"type": "text", "text": "he"},
        {"type": "text", "text": "llo "},
        {"type": "text", "text": "world"},
        {"type": "done", "finishReason": "stop"},
    ]), _request())
    assert outcome.response.text == "hello world"
    assert outcome.text_chunks == 3 and outcome.chunks == 4
    assert outcome.response.finish_reason == "stop"


def test_a_finish_chunk_outranks_the_terminal_chunks_default():
    """Anthropic sends the real stop_reason on message_delta, then stops."""
    outcome = ah_stream.drain(Scripted([
        {"type": "finish", "finishReason": "tool_use"},
        {"type": "done", "finishReason": "stop"},
    ]), _request())
    assert outcome.response.finish_reason == "tool_use"


def test_a_stream_with_no_terminal_chunk_is_a_named_fault():
    with pytest.raises(ProviderError) as excinfo:
        ah_stream.drain(Scripted([{"type": "text", "text": "half an ans"}]),
                        _request())
    assert excinfo.value.code == "provider_stream_incomplete"
    assert excinfo.value.data["textChunks"] == 1


def test_an_undeclared_chunk_type_is_refused_not_dropped():
    with pytest.raises(ProviderError) as excinfo:
        ah_stream.drain(Scripted([{"type": "thinking", "text": "hm"},
                                  {"type": "done"}]), _request())
    assert excinfo.value.code == "provider_stream_chunk_invalid"


def test_content_after_the_close_is_refused():
    with pytest.raises(ProviderError) as excinfo:
        ah_stream.drain(Scripted([{"type": "done"},
                                  {"type": "text", "text": "oh also"}]),
                        _request())
    assert excinfo.value.code == "provider_stream_chunk_invalid"


@pytest.mark.parametrize("bad", [
    {"type": "tool_call", "toolCall": {"callId": "c", "arguments": {}}},
    {"type": "tool_call", "toolCall": {"name": "document_inspect",
                                       "arguments": {}}},
    {"type": "tool_call", "toolCall": {"callId": "c",
                                       "name": "document_inspect",
                                       "arguments": "not an object"}},
    {"type": "tool_call", "toolCall": "not an object"},
])
def test_a_malformed_tool_call_chunk_never_becomes_a_tool_call(bad):
    with pytest.raises(ProviderError) as excinfo:
        ah_stream.drain(Scripted([bad, {"type": "done"}]), _request())
    assert excinfo.value.code == "provider_stream_chunk_invalid"


# --- the mock, in the loop --------------------------------------------------

def test_the_mock_streams_the_same_bytes_it_completes():
    provider = ah_mock.MockProvider()
    request = _request()
    chunks = list(provider.stream(request))
    text = "".join(c["text"] for c in chunks if c["type"] == "text")
    assert text == provider.complete(request).text


def test_the_mock_capability_is_a_promise_it_keeps():
    profile = ah_mock.MockProvider().capabilities()
    assert profile.state("streaming") == "yes"
    assert profile.supports("streaming") is True


def test_the_turn_loop_streams_by_default_and_says_so(opened):
    door = mock_agent.open_door("protocol", opened, None)
    try:
        payload = AgentHost(door, ah_mock.MockProvider()).run("fill it")
    finally:
        door.close()
    assert payload["ok"] is True
    assert payload["transports"] == ["stream"]
    assert all(row["transport"] == "stream" for row in payload["turnLog"])
    assert all(row["fallbackReason"] is None for row in payload["turnLog"])
    chunks = [e for e in payload["events"]["events"]
              if e["kind"] == "provider.stream.chunk"]
    assert chunks, "streaming a turn must emit chunk events"
    assert chunks[0]["detail"]["index"] == 0
    # every chunk names a declared type, and the last of each turn closes it
    assert {c["detail"]["chunkType"] for c in chunks} <= set(STREAM_CHUNK_TYPES)
    assert any(c["detail"]["chunkType"] == "done" for c in chunks)
    # and the streamed turns actually assembled tool calls
    assert payload["plan"]["opsHash"]
    assert payload["validation"]["ok"] is True


def test_streaming_and_not_streaming_reach_the_same_plan(tmp_path):
    hashes = {}
    for name, mode in (("a", "auto"), ("b", "off")):
        root = tmp_path / f"root-{name}"
        source = tmp_path / f"{name}.hwpx"
        shutil.copyfile(CORPUS_FORM, source)
        run_cli(root, "open", "--path", str(source))
        door = mock_agent.open_door("protocol", root, None)
        try:
            payload = AgentHost(door, ah_mock.MockProvider(),
                                stream_mode=mode).run("fill it")
        finally:
            door.close()
        hashes[mode] = payload["plan"]["opsHash"]
        assert payload["transports"] == (["stream"] if mode == "auto"
                                         else ["complete"])
        assert payload["closingText"] == ah_mock.CLOSING_TEXT["propose-one"]
    assert hashes["auto"] == hashes["off"]


def test_two_streamed_runs_produce_identical_event_logs(tmp_path):
    documents = []
    for name in ("a", "b"):
        root = tmp_path / f"root-{name}"
        source = tmp_path / f"{name}.hwpx"
        shutil.copyfile(CORPUS_FORM, source)
        run_cli(root, "open", "--path", str(source))
        door = mock_agent.open_door("protocol", root, None)
        try:
            payload = AgentHost(door, ah_mock.MockProvider()).run("fill it")
        finally:
            door.close()
        documents.append(mock_agent.redact(payload))
    assert documents[0] == documents[1]


# --- the fallback is honest -------------------------------------------------

def test_an_unknown_streaming_capability_falls_back_and_names_the_reason(opened):
    provider = Scripted([], streaming="unknown")
    door = mock_agent.open_door("protocol", opened, None)
    try:
        payload = AgentHost(door, provider).run("fill it")
    finally:
        door.close()
    assert payload["transports"] == ["complete"]
    assert "unknown" in payload["turnLog"][0]["fallbackReason"]
    assert provider.completed == 1
    assert payload["closingText"] == "non-streamed"


def test_a_declared_no_also_falls_back(opened):
    provider = Scripted([], streaming="no")
    door = mock_agent.open_door("protocol", opened, None)
    try:
        payload = AgentHost(door, provider).run("fill it")
    finally:
        door.close()
    assert payload["turnLog"][0]["transport"] == "complete"
    assert "'no'" in payload["turnLog"][0]["fallbackReason"]


def test_the_operator_can_force_the_non_streaming_path(opened):
    door = mock_agent.open_door("protocol", opened, None)
    try:
        payload = AgentHost(door, ah_mock.MockProvider(),
                            stream_mode="off").run("fill it")
    finally:
        door.close()
    assert payload["streamMode"] == "off"
    assert payload["transports"] == ["complete"]
    assert not [e for e in payload["events"]["events"]
                if e["kind"] == "provider.stream.chunk"]


# --- the fake Anthropic server, over real SSE -------------------------------

def _adapter(server, env_name, **overrides):
    return AnthropicAdapter(anthropic_config(server.base_url, **overrides))


def _sse(body: str) -> dict:
    return {"status": 200, "text": body, "contentType": "text/event-stream"}


def _seen_tools(body) -> list:
    return [block.get("name")
            for message in body["messages"] if message["role"] == "assistant"
            for block in message["content"] if block.get("type") == "tool_use"]


def test_the_host_drives_the_anthropic_adapter_over_sse(opened, env):
    """The end-to-end twin of the non-streamed test, on the streaming path."""
    def agent(path, body):
        assert body.get("stream") is True, "the host must ask for a stream"
        seen = _seen_tools(body)
        session = json.loads(
            body["messages"][0]["content"][0]["text"])["context"]["sessionId"]
        if "document_inspect" not in seen:
            return _sse(anthropic_sse(
                ["Looking ", "at the ", "regions."],
                tool_call={"id": "toolu_1", "name": "document_inspect",
                           "input": {"sessionId": session,
                                     "include": ["regions"]}},
                stop_reason="tool_use"))
        if "plan_propose" not in seen:
            return _sse(anthropic_sse(
                [], tool_call={"id": "toolu_2", "name": "plan_propose",
                               "input": {"sessionId": session,
                                         "backend": "preedit",
                                         "proposer": "sse-test",
                                         "ops": [{"kind": "fill_cell",
                                                  "table": 0, "row": 0,
                                                  "col": 14,
                                                  "text": "SSE-0001"}]}},
                stop_reason="tool_use"))
        return _sse(anthropic_sse(["Proposed ", "one fill."]))

    with FakeRouter(agent) as srv:
        door = mock_agent.open_door("protocol", opened, None)
        try:
            payload = AgentHost(door, _adapter(srv, env)).run("fill the seat")
        finally:
            door.close()
    assert payload["ok"] is True
    assert payload["transports"] == ["stream"]
    assert payload["plan"]["ops"][0]["params"]["text"] == "SSE-0001"
    assert payload["closingText"] == "Proposed one fill."
    # the tool arrived in fragments and was dispatched exactly once, whole
    tool_chunks = [e for e in payload["events"]["events"]
                   if e["kind"] == "provider.stream.chunk"
                   and e["detail"]["chunkType"] == "tool_call"]
    assert [c["detail"]["toolCall"]["name"] for c in tool_chunks] == \
        ["document_inspect", "plan_propose"]
    assert PLACEHOLDER_ANTHROPIC_KEY not in json.dumps(payload)


def test_a_stream_cut_mid_tool_input_never_reaches_the_runtime(opened, env):
    """The property that justifies the whole assembler.

    The server sends a tool block's opening frame and half its
    ``input_json_delta`` fragments, then stops: no ``content_block_stop``, no
    ``message_stop``. The adapter therefore yields NO tool_call chunk, the
    assembler refuses the truncated stream, and the Runtime is never asked.
    """
    whole = anthropic_sse(
        [], tool_call={"id": "toolu_x", "name": "plan_apply",
                       "input": {"planId": "p", "approvalId": "a"}},
        stop_reason="tool_use")
    frames = whole.split("\n\n")
    # keep message_start, content_block_start and the first two deltas only
    truncated = "\n\n".join(frames[:4]) + "\n\n"
    assert "input_json_delta" in truncated
    assert "content_block_stop" not in truncated

    with FakeRouter(lambda path, body: _sse(truncated)) as srv:
        door = mock_agent.open_door("protocol", opened, None)
        try:
            payload = AgentHost(door, _adapter(srv, env)).run("apply it")
        finally:
            door.close()
    assert payload["ok"] is False
    assert payload["providerFault"]["code"] == "provider_stream_incomplete"
    assert payload["providerFault"]["data"]["toolCalls"] == 0
    kinds = [e["kind"] for e in payload["events"]["events"]]
    assert "tool.requested" not in kinds
    assert "tool.compiled" not in kinds
    assert "runtime.result" not in kinds
    assert payload["plan"] is None and payload["validation"] is None
    assert payload["refusals"] == []
    assert payload["turnLog"][0]["fault"] == "provider_stream_incomplete"


def test_a_streamed_apply_request_is_still_refused_at_the_compile_gate(opened, env):
    """Assembling honestly does not mean dispatching obediently."""
    def hostile(path, body):
        if "plan_apply" not in _seen_tools(body):
            return _sse(anthropic_sse(
                [], tool_call={"id": "toolu_h", "name": "plan_apply",
                               "input": {"planId": "p", "approvalId": "a"}},
                stop_reason="tool_use"))
        return _sse(anthropic_sse(["I was refused."]))

    with FakeRouter(hostile) as srv:
        door = mock_agent.open_door("protocol", opened, None)
        try:
            payload = AgentHost(door, _adapter(srv, env)).run("apply it")
        finally:
            door.close()
    forbidden = [row for row in payload["refusals"]
                 if row["code"] == "tool_forbidden"]
    assert len(forbidden) == 1 and forbidden[0]["stage"] == "compile"
    assert "runtime.refused" not in [e["kind"]
                                     for e in payload["events"]["events"]]


# --- the OpenAI-compatible router -------------------------------------------

def test_the_router_stays_unknown_until_an_operator_declares_it():
    """Not a missing implementation — an unmeasured gateway."""
    client = RouterAdapter(router_config("http://127.0.0.1:1/v1"))
    profile = client.capabilities()
    assert profile.state("streaming") == "unknown"
    assert profile.supports("streaming") is False
    assert "gateway-specific" in profile.capabilities["streaming"].reason


def test_a_router_declared_streaming_reaches_the_turn_loop(opened, monkeypatch):
    from _agenthost_support import CREDENTIAL_ENV, PLACEHOLDER_CREDENTIAL
    monkeypatch.setenv(CREDENTIAL_ENV, PLACEHOLDER_CREDENTIAL)

    def gateway(path, body):
        assert body.get("stream") is True
        called = [message.get("name") for message in body["messages"]
                  if message["role"] == "tool"]
        session = json.loads(body["messages"][1]["content"])["context"]["sessionId"]
        if "document_inspect" not in called:
            return {"sse": sse_lines(["Looking."], tool_calls=[
                {"id": "call-1", "name": "document_inspect",
                 "arguments": {"sessionId": session, "include": ["regions"]}}])}
        return {"sse": sse_lines(["Done looking."])}

    with FakeRouter(gateway) as srv:
        client = RouterAdapter(router_config(
            srv.base_url, capabilities={"streaming": "yes",
                                        "structuredToolUse": "yes"}))
        assert client.capabilities().state("streaming") == "yes"
        assert client.capabilities().public()["capabilities"]["streaming"][
            "declaredBy"] == "config"
        door = mock_agent.open_door("protocol", opened, None)
        try:
            payload = AgentHost(door, client).run("look at it")
        finally:
            door.close()
    assert payload["transports"] == ["stream"]
    assert payload["closingText"] == "Done looking."
    assert [e["detail"]["tool"] for e in payload["events"]["events"]
            if e["kind"] == "tool.compiled"] == ["document_inspect"]


def test_an_undeclared_router_falls_back_to_the_completion_path(opened, monkeypatch):
    from _agenthost_support import (
        CREDENTIAL_ENV,
        PLACEHOLDER_CREDENTIAL,
        completion,
    )
    monkeypatch.setenv(CREDENTIAL_ENV, PLACEHOLDER_CREDENTIAL)

    with FakeRouter(lambda path, body: {"json": completion("plain")}) as srv:
        client = RouterAdapter(router_config(srv.base_url))
        door = mock_agent.open_door("protocol", opened, None)
        try:
            payload = AgentHost(door, client).run("look at it")
        finally:
            door.close()
    assert payload["transports"] == ["complete"]
    assert srv.requests[-1]["body"].get("stream") is None
    assert payload["closingText"] == "plain"
