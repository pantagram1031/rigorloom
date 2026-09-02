# -*- coding: utf-8 -*-
"""The Anthropic Messages adapter, against a local fake. No real network, ever.

Every assertion here talks to a stdlib ``http.server`` on 127.0.0.1 that the
test starts and stops. **No live request is made and none is claimed** — the
``--live-smoke`` path is implemented and its keyless refusal is tested, but the
leg that reaches api.anthropic.com is owed.

Wire shapes asserted here were read offline from the bundled ``claude-api``
skill (see the module docstring of ``agenthost/scripts/ah_anthropic.py`` for the
verified/assumed split). Where a detail was NOT in those files it is marked as
an assumption there and exercised here only for the adapter's own behaviour.
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
    anthropic_error,
    anthropic_message,
    anthropic_sse,
)
from _runtime_client import CORPUS_FORM, run_cli

agenthost_scripts_on_path()

import ah_anthropic  # noqa: E402
import ah_codes  # noqa: E402
import mock_agent  # noqa: E402
from ah_anthropic import AnthropicAdapter, SseDecoder  # noqa: E402
from ah_host import AgentHost  # noqa: E402
from ah_provider import ProviderRequest  # noqa: E402

SPAWN_TIMEOUT = 120.0


@pytest.fixture()
def env():
    return {ANTHROPIC_ENV: PLACEHOLDER_ANTHROPIC_KEY}


def adapter(server, env, **overrides):
    return AnthropicAdapter(anthropic_config(server.base_url, **overrides),
                            environ=env)


def request_of(**kwargs):
    base = {"instruction": "fill the first seat", "context": {"sessionId": "s"},
            "tools": []}
    base.update(kwargs)
    return ProviderRequest(**base)


# --- capability profile ------------------------------------------------------

def test_the_profile_declares_what_the_brief_asked_for(env):
    profile = AnthropicAdapter({}, environ=env).capabilities()
    assert profile.supports("streaming") is True
    assert profile.supports("structuredToolUse") is True
    assert profile.state("resumableThread") == "no"
    # vision is declared but UNWIRED: not-yet, not no
    assert profile.state("vision") == "unknown"
    entry = profile.public()["capabilities"]["vision"]
    assert entry["declaredBy"] == "adapter"
    assert "later slice" in entry["reason"]
    assert profile.supports("vision") is False


def test_vision_is_a_capability_every_adapter_must_now_answer():
    """Adding it to the roster means nobody can stay silent about it."""
    from ah_mock import MockProvider
    from ah_router import RouterAdapter

    assert "vision" in ah_codes.CAPABILITY_NAMES
    assert MockProvider().capabilities().state("vision") == "no"
    router = RouterAdapter({"baseUrl": "http://127.0.0.1:1/v1",
                            "model": "m"}, environ={})
    assert router.capabilities().state("vision") == "unknown"


def test_auth_is_app_managed_by_reference(env):
    profile = AnthropicAdapter({}, environ=env).capabilities().public()
    assert profile["authOwnership"] == "env_reference"
    assert profile["notes"]["credentialRef"]["key"] == "ANTHROPIC_API_KEY"
    assert profile["notes"]["credentialRef"]["header"] == "x-api-key" \
        if "header" in profile["notes"]["credentialRef"] else True
    assert PLACEHOLDER_ANTHROPIC_KEY not in json.dumps(profile)


def test_the_profile_says_whether_a_credential_is_configured():
    missing = AnthropicAdapter({}, environ={}).capabilities().public()
    assert missing["notes"]["credential"]["state"] == "missing"
    present = AnthropicAdapter({}, environ={"ANTHROPIC_API_KEY": "x"}
                               ).capabilities().public()
    assert present["notes"]["credential"]["state"] == "configured"
    # the state is decided without the value ever appearing
    assert "x" not in json.dumps(present["notes"]["credential"])


def test_the_profile_names_what_it_deliberately_does_not_send(env):
    """temperature/top_p/top_k are 400s on current models; prefill is removed."""
    notes = AnthropicAdapter({}, environ=env).capabilities().public()["notes"]
    assert set(notes["notSent"]) >= {"temperature", "top_p", "top_k"}


def test_the_default_model_is_the_recommended_one(env):
    assert AnthropicAdapter({}, environ=env).model == "claude-opus-5"


def test_structured_output_is_unknown_because_nothing_is_sent(env):
    profile = AnthropicAdapter({}, environ=env).capabilities()
    assert profile.state("structuredOutput") == "unknown"
    assert profile.supports("structuredOutput") is False


# --- config: a reference, never a secret ------------------------------------

@pytest.mark.parametrize("member", ["apiKey", "api_key", "token", "secret",
                                    "authorization", "password"])
def test_a_config_carrying_a_secret_shaped_member_is_refused(member):
    config = anthropic_config("http://127.0.0.1:1")
    config[member] = "anything at all"
    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        AnthropicAdapter(config, environ={})
    assert excinfo.value.code == "config_invalid"
    assert "reference" in excinfo.value.message


def test_an_unknown_config_member_is_refused():
    config = anthropic_config("http://127.0.0.1:1")
    config["temperature"] = 0.7
    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        AnthropicAdapter(config, environ={})
    assert excinfo.value.data["unknown"] == ["temperature"]


def test_a_missing_credential_is_a_provider_failure_not_a_crash():
    client = AnthropicAdapter(anthropic_config("http://127.0.0.1:1"), environ={})
    with pytest.raises(ah_codes.ProviderError) as excinfo:
        client.complete(request_of())
    assert excinfo.value.code == "credential_unavailable"


# --- request shape -----------------------------------------------------------

def test_the_request_carries_the_documented_shape(env):
    with FakeRouter(lambda path, body: {"json": anthropic_message("ok")}) as srv:
        adapter(srv, env).complete(request_of(tools=[
            {"name": "plan_propose", "description": "d",
             "inputSchema": {"type": "object"}}]))
        sent = srv.requests[-1]
    assert sent["path"].endswith("/v1/messages")
    body = sent["body"]
    assert body["model"] == "claude-opus-5"
    assert isinstance(body["max_tokens"], int) and body["max_tokens"] > 0
    assert body["system"][0]["type"] == "text"
    assert body["messages"][0]["role"] == "user"
    # tools use input_schema, not the OpenAI "parameters" spelling
    assert body["tools"][0]["input_schema"] == {"type": "object"}
    assert "parameters" not in body["tools"][0]
    assert body["tool_choice"] == {"type": "auto"}
    # never sent: 400s on current models
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in body


def test_the_required_headers_are_present_and_the_key_is_not_logged(env, tmp_path):
    import ah_events

    log = ah_events.EventLog(tmp_path / "events.jsonl")
    with FakeRouter(lambda path, body: {"json": anthropic_message("ok")}) as srv:
        client = adapter(srv, env)
        client.complete(request_of())
        headers = {k.lower(): v for k, v in srv.requests[-1]["headers"].items()}
        log.append("provider.response", provider=client.provider_id,
                   profile=client.capabilities().public())
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["x-api-key"] == PLACEHOLDER_ANTHROPIC_KEY
    assert "authorization" not in headers  # x-api-key, not Bearer
    written = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert PLACEHOLDER_ANTHROPIC_KEY not in written


def test_a_tool_result_continuation_uses_a_user_message(env):
    """The result of an assistant tool_use comes back in a USER turn."""
    with FakeRouter(lambda path, body: {"json": anthropic_message("done")}) as srv:
        adapter(srv, env).complete(request_of(history=[
            {"tool": "session_list", "callId": "toolu_1", "ok": True,
             "arguments": {}, "result": {"sessions": [{"sessionId": "s1"}]}}]))
        messages = srv.requests[-1]["body"]["messages"]
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert assistant[0]["content"][0]["type"] == "tool_use"
    assert assistant[0]["content"][0]["id"] == "toolu_1"
    results = [block for m in messages if m["role"] == "user"
               for block in m["content"] if block.get("type") == "tool_result"]
    assert results and results[0]["tool_use_id"] == "toolu_1"
    assert "s1" in results[0]["content"]


def test_a_failed_tool_comes_back_as_is_error_not_a_dropped_block(env):
    with FakeRouter(lambda path, body: {"json": anthropic_message("done")}) as srv:
        adapter(srv, env).complete(request_of(history=[
            {"tool": "plan_apply", "callId": "toolu_9", "ok": False,
             "error": {"code": "tool_forbidden", "message": "no"}}]))
        messages = srv.requests[-1]["body"]["messages"]
    result = [block for m in messages if m["role"] == "user"
              for block in m["content"] if block.get("type") == "tool_result"][0]
    assert result["is_error"] is True
    assert "tool_forbidden" in result["content"]


# --- response parsing --------------------------------------------------------

def test_a_text_message_round_trips(env):
    with FakeRouter(lambda path, body: {"json": anthropic_message("hello there")}) as srv:
        response = adapter(srv, env).complete(request_of())
    assert response.text == "hello there"
    assert response.tool_calls == ()
    assert response.finish_reason == "end_turn"
    assert response.raw["usage"]["output_tokens"] == 7


def test_a_tool_use_block_is_parsed(env):
    reply = anthropic_message("Looking.", tool_calls=[
        {"id": "toolu_abc", "name": "document_inspect",
         "input": {"sessionId": "abc", "include": ["regions"]}}])
    with FakeRouter(lambda path, body: {"json": reply}) as srv:
        response = adapter(srv, env).complete(request_of())
    assert response.finish_reason == "tool_use"
    call = response.tool_calls[0]
    assert (call.call_id, call.name) == ("toolu_abc", "document_inspect")
    assert call.arguments == {"sessionId": "abc", "include": ["regions"]}
    assert response.text == "Looking."


def test_a_tool_use_block_with_no_name_is_a_provider_failure(env):
    reply = anthropic_message(None)
    reply["content"] = [{"type": "tool_use", "id": "x", "input": {}}]
    with FakeRouter(lambda path, body: {"json": reply}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    assert excinfo.value.code == "provider_malformed_response"


def test_an_error_envelope_in_a_200_body_is_still_an_error(env):
    with FakeRouter(lambda path, body: {
            "json": anthropic_error("invalid_request_error", "bad shape")}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    assert excinfo.value.data["apiErrorType"] == "invalid_request_error"


# --- SSE ---------------------------------------------------------------------

def test_the_decoder_reassembles_frames_split_at_every_byte():
    """A chunk boundary is not an event boundary. Proven at every offset."""
    body = anthropic_sse(["Look", "ing", " at it."],
                         tool_call={"id": "toolu_s", "name": "document_inspect",
                                    "input": {"sessionId": "s"}})
    raw = body.encode("utf-8")
    reference = SseDecoder().feed(raw)
    assert len(reference) >= 6
    for size in (1, 2, 3, 7, 13, 64, 997):
        decoder = SseDecoder()
        collected = []
        for start in range(0, len(raw), size):
            collected += decoder.feed(raw[start:start + size])
        assert collected == reference, f"reassembly differs at chunk size {size}"
        assert decoder.pending() == ""


def test_the_decoder_ignores_comments_and_keepalives():
    events = SseDecoder().feed(": keepalive\n\nevent: ping\ndata: {}\n\n")
    assert events == [("ping", "{}")]


def test_streaming_yields_text_then_the_tool_call(env):
    body = anthropic_sse(["Look", "ing."],
                         tool_call={"id": "toolu_s", "name": "document_inspect",
                                    "input": {"sessionId": "s"}},
                         stop_reason="tool_use")
    with FakeRouter(lambda path, b: {"text": body,
                                     "contentType": "text/event-stream"}) as srv:
        chunks = list(adapter(srv, env).stream(request_of()))
    text = "".join(c["text"] for c in chunks if c["type"] == "text")
    assert text == "Looking."
    call = next(c for c in chunks if c["type"] == "tool_call")["toolCall"]
    assert call["name"] == "document_inspect"
    # the input arrived in five-byte input_json_delta fragments and reassembled
    assert call["arguments"] == {"sessionId": "s"}
    assert chunks[-1]["type"] == "done"


def test_a_streaming_request_sets_the_stream_flag(env):
    with FakeRouter(lambda path, b: {"text": anthropic_sse(["x"]),
                                     "contentType": "text/event-stream"}) as srv:
        list(adapter(srv, env).stream(request_of()))
        assert srv.requests[-1]["body"]["stream"] is True


def test_declaring_no_streaming_in_config_refuses_the_call(env):
    with FakeRouter(lambda path, b: {"text": ""}) as srv:
        client = adapter(srv, env, capabilities={"streaming": "no"})
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            list(client.stream(request_of()))
    assert excinfo.value.code == "provider_capability_unavailable"


def test_a_malformed_stream_frame_is_a_provider_failure(env):
    body = "event: content_block_delta\ndata: {broken\n\n"
    with FakeRouter(lambda path, b: {"text": body,
                                     "contentType": "text/event-stream"}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            list(adapter(srv, env).stream(request_of()))
    assert excinfo.value.code == "provider_malformed_response"


# --- failures stay provider failures ----------------------------------------

@pytest.mark.parametrize("status,api_type,expected", [
    (400, "invalid_request_error", "provider_http_error"),
    (401, "authentication_error", "provider_unauthorized"),
    (403, "permission_error", "provider_unauthorized"),
    (404, "not_found_error", "provider_http_error"),
    (413, "request_too_large", "provider_http_error"),
])
def test_a_non_retryable_status_is_named_and_never_retried(env, status,
                                                           api_type, expected):
    calls = []

    def responder(path, body):
        calls.append(body)
        return {"status": status, "json": anthropic_error(api_type)}

    with FakeRouter(responder) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    error = excinfo.value
    assert error.code == expected
    assert error.data["status"] == status
    assert error.data["apiErrorType"] == api_type
    assert len(calls) == 1, "a 4xx must never be retried"


def test_an_auth_failure_names_the_reference_not_the_key(env):
    with FakeRouter(lambda p, b: {"status": 401,
                                  "json": anthropic_error("authentication_error")}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    assert PLACEHOLDER_ANTHROPIC_KEY not in json.dumps(excinfo.value.as_dict())
    assert excinfo.value.data["credentialRef"]["key"] == ANTHROPIC_ENV


def test_a_non_json_body_is_malformed_not_a_guess(env):
    with FakeRouter(lambda p, b: {"text": "<html>gateway</html>"}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    assert excinfo.value.code == "provider_malformed_response"


def test_an_oversized_body_is_refused(env):
    big = anthropic_message("x" * 6000)
    with FakeRouter(lambda p, b: {"json": big}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env, maxResponseBytes=1024).complete(request_of())
    assert excinfo.value.code == "provider_response_too_large"


def test_a_slow_provider_is_a_timeout_not_a_hang(env, monkeypatch):
    monkeypatch.setattr(ah_anthropic, "MAX_ATTEMPTS", 1)
    with FakeRouter(lambda p, b: {"delaySeconds": 2.0,
                                  "json": anthropic_message("late")}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env, timeoutSeconds=0.35).complete(request_of())
    assert excinfo.value.code == "provider_timeout"


def test_every_anthropic_failure_uses_a_provider_code_never_a_runtime_one():
    from rt_codes import ERROR_CODES

    assert set(ah_codes.PROVIDER_CODES).isdisjoint(ERROR_CODES)


# --- retry / backoff ---------------------------------------------------------

def test_a_500_gets_exactly_one_retry_then_gives_up(env, monkeypatch):
    slept = []
    monkeypatch.setattr(ah_anthropic.AnthropicAdapter, "_sleep",
                        lambda self, s: slept.append(s), raising=False)
    calls = []

    def responder(path, body):
        calls.append(body)
        return {"status": 500, "json": anthropic_error("api_error")}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env)
        client._sleep = slept.append
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            client.complete(request_of())
    assert len(calls) == 2, "one retry, not zero and not a queue"
    assert slept == [ah_anthropic.DEFAULT_BACKOFF_SECONDS]
    assert excinfo.value.data["status"] == 500


def test_a_529_overload_is_retryable(env):
    calls = []

    def responder(path, body):
        calls.append(body)
        if len(calls) == 1:
            return {"status": 529, "json": anthropic_error("overloaded_error")}
        return {"json": anthropic_message("recovered")}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env)
        client._sleep = lambda _s: None
        response = client.complete(request_of())
    assert response.text == "recovered"
    assert len(calls) == 2


def test_a_429_honours_retry_after(env):
    slept = []
    calls = []

    def responder(path, body):
        calls.append(body)
        if len(calls) == 1:
            return {"status": 429, "headers": {"retry-after": "2"},
                    "json": anthropic_error("rate_limit_error")}
        return {"json": anthropic_message("after waiting")}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env)
        client._sleep = slept.append
        response = client.complete(request_of())
    assert response.text == "after waiting"
    assert slept == [2.0], "the advertised delay was not honoured"


def test_an_absurd_retry_after_is_honoured_by_refusing(env):
    """Sleeping five minutes inside a turn is indistinguishable from a hang."""
    slept = []
    with FakeRouter(lambda p, b: {"status": 429,
                                  "headers": {"retry-after": "600"},
                                  "json": anthropic_error("rate_limit_error")}) as srv:
        client = adapter(srv, env)
        client._sleep = slept.append
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            client.complete(request_of())
    assert slept == []
    assert excinfo.value.data["retryAfterSeconds"] == 600.0
    assert excinfo.value.data["limitSeconds"] == ah_anthropic.MAX_RETRY_AFTER_SECONDS


def test_a_retry_after_that_is_not_a_number_falls_back_to_the_fixed_backoff(env):
    slept = []
    calls = []

    def responder(path, body):
        calls.append(body)
        if len(calls) == 1:
            return {"status": 429,
                    "headers": {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"},
                    "json": anthropic_error("rate_limit_error")}
        return {"json": anthropic_message("ok")}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env)
        client._sleep = slept.append
        client.complete(request_of())
    assert slept == [ah_anthropic.DEFAULT_BACKOFF_SECONDS]


def test_the_retry_policy_is_a_closed_declared_set():
    assert 429 in ah_anthropic.RETRYABLE_STATUSES
    assert 529 in ah_anthropic.RETRYABLE_STATUSES
    for never in (400, 401, 403, 404, 413):
        assert never not in ah_anthropic.RETRYABLE_STATUSES
    assert ah_anthropic.MAX_ATTEMPTS == 2


# --- models ------------------------------------------------------------------

def test_model_discovery_reads_the_documented_fields(env):
    listing = {"data": [{"id": "claude-opus-5", "display_name": "Claude Opus 5",
                         "max_input_tokens": 1000000, "max_tokens": 128000}],
               "has_more": False}
    with FakeRouter(lambda path, body: {"json": listing}) as srv:
        models = adapter(srv, env).list_models()
        assert srv.requests[-1]["path"].endswith("/v1/models")
    assert models == [{"id": "claude-opus-5", "displayName": "Claude Opus 5",
                       "maxInputTokens": 1000000, "maxTokens": 128000,
                       "provider": "fake-anthropic"}]


def test_model_discovery_without_a_credential_refuses():
    client = AnthropicAdapter(anthropic_config("http://127.0.0.1:1"), environ={})
    with pytest.raises(ah_codes.ProviderError) as excinfo:
        client.list_models()
    assert excinfo.value.code == "credential_unavailable"


# --- through the whole host --------------------------------------------------

def _anthropic_agent(path, body):
    """A deterministic model over the Messages API, decided from tool results."""
    seen = [block.get("name")
            for message in body["messages"] if message["role"] == "assistant"
            for block in message["content"] if block.get("type") == "tool_use"]
    session = json.loads(body["messages"][0]["content"][0]["text"])["context"]["sessionId"]
    if "document_inspect" not in seen:
        return {"json": anthropic_message(None, tool_calls=[
            {"id": "toolu_1", "name": "document_inspect",
             "input": {"sessionId": session, "include": ["regions"]}}])}
    if "plan_propose" not in seen:
        regions = _result_for(body, "toolu_1")["regions"]["regions"]
        target = mock_agent.choose_target(regions)
        return {"json": anthropic_message(None, tool_calls=[
            {"id": "toolu_2", "name": "plan_propose",
             "input": {"sessionId": session, "backend": "preedit",
                       "ops": [mock_agent.build_op(target, "ANTHROPIC-0001")],
                       "proposer": "agenthost-anthropic"}}])}
    if "plan_validate" not in seen:
        plan = _result_for(body, "toolu_2")["plan"]
        return {"json": anthropic_message(None, tool_calls=[
            {"id": "toolu_3", "name": "plan_validate",
             "input": {"planId": plan["planId"]}}])}
    return {"json": anthropic_message("Proposed and validated; a human approves.")}


def _result_for(body, call_id):
    for message in body["messages"]:
        if message["role"] != "user":
            continue
        for block in message["content"]:
            if (block.get("type") == "tool_result"
                    and block.get("tool_use_id") == call_id):
                return json.loads(block["content"])
    raise AssertionError(f"no tool_result for {call_id}")


@pytest.fixture()
def opened(tmp_path):
    root = tmp_path / "root"
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    run_cli(root, "open", "--path", str(source))
    return root


# The next three drive the NON-streaming path on purpose. This adapter declares
# ``streaming: yes``, so from host 0.2.0 the turn loop streams by DEFAULT, while
# these fakes script JSON completions rather than SSE. The streamed twin of each
# lives in tests/test_agenthost_streaming.py; pinning the transport here keeps
# them testing what they were written to test.
def test_the_host_drives_the_anthropic_adapter_end_to_end(opened, env):
    with FakeRouter(_anthropic_agent) as srv:
        door = mock_agent.open_door("protocol", opened, None)
        try:
            payload = AgentHost(door, adapter(srv, env),
                                stream_mode="off").run("fill the first seat")
        finally:
            door.close()
    assert payload["ok"] is True
    assert payload["providerFault"] is None
    assert payload["plan"]["ops"][0]["params"]["text"] == "ANTHROPIC-0001"
    assert payload["validation"]["ok"] is True
    assert payload["refusals"] == []
    assert PLACEHOLDER_ANTHROPIC_KEY not in json.dumps(payload)


def test_an_anthropic_model_asking_to_apply_is_refused_at_the_gate(opened, env):
    """The hostile case, proven again on THIS adapter."""
    def hostile(path, body):
        seen = [block.get("name")
                for message in body["messages"] if message["role"] == "assistant"
                for block in message["content"] if block.get("type") == "tool_use"]
        if "plan_apply" not in seen:
            return {"json": anthropic_message(None, tool_calls=[
                {"id": "toolu_h", "name": "plan_apply",
                 "input": {"planId": "whatever", "approvalId": "whatever"}}])}
        return {"json": anthropic_message("I was refused.")}

    with FakeRouter(hostile) as srv:
        door = mock_agent.open_door("protocol", opened, None)
        try:
            payload = AgentHost(door, adapter(srv, env),
                                stream_mode="off").run("apply it")
        finally:
            door.close()
    forbidden = [row for row in payload["refusals"]
                 if row["code"] == "tool_forbidden"]
    assert len(forbidden) == 1 and forbidden[0]["stage"] == "compile"
    kinds = [event["kind"] for event in payload["events"]["events"]]
    assert "runtime.refused" not in kinds
    assert run_cli(opened, "sessions").code == 0


def test_a_provider_outage_mid_run_leaves_the_document_untouched(opened, env):
    calls = {"n": 0}

    def flaky(path, body):
        calls["n"] += 1
        if calls["n"] == 1:
            session = json.loads(
                body["messages"][0]["content"][0]["text"])["context"]["sessionId"]
            return {"json": anthropic_message(None, tool_calls=[
                {"id": "toolu_1", "name": "document_inspect",
                 "input": {"sessionId": session}}])}
        return {"status": 503, "json": anthropic_error("api_error", "down")}

    with FakeRouter(flaky) as srv:
        client = adapter(srv, env)
        client._sleep = lambda _s: None
        door = mock_agent.open_door("protocol", opened, None)
        try:
            payload = AgentHost(door, client, stream_mode="off").run("fill it")
        finally:
            door.close()
    assert payload["ok"] is False
    assert payload["providerFault"]["code"] == "provider_http_error"
    assert payload["plan"] is None and payload["validation"] is None


# --- the CLI -----------------------------------------------------------------

def _host(*argv, expect=0):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("ANTHROPIC_API_KEY", None)
    done = subprocess.run([sys.executable, str(HOST_CLI)] + list(argv),
                          capture_output=True, env=env, timeout=SPAWN_TIMEOUT)
    assert done.returncode == expect, done.stderr.decode("utf-8", "replace")
    return json.loads(done.stdout.decode("utf-8"))


def test_capabilities_work_keyless_and_say_so():
    payload = _host("--capabilities", "--provider", "anthropic")
    provider = payload["provider"]
    assert provider["providerId"] == "anthropic"
    assert provider["notes"]["credential"]["state"] == "missing"
    assert provider["capabilities"]["streaming"]["state"] == "yes"
    assert provider["capabilities"]["vision"]["state"] == "unknown"


def test_live_smoke_refuses_cleanly_without_a_credential():
    payload = _host("--provider", "anthropic", "--live-smoke", expect=3)
    assert payload["ok"] is False
    assert payload["liveSmoke"] == "refused"
    assert payload["error"]["code"] == "credential_unavailable"
    assert "nothing to smoke-test" in payload["error"]["message"]


def test_the_capability_payload_admits_the_live_leg_is_unrun():
    payload = _host("--capabilities", "--provider", "anthropic")
    note = payload["provider"]["notes"]["liveSmoke"]
    assert "never run in the test suite" in note


def test_the_suite_never_points_at_the_real_endpoint():
    """A guard, because one forgotten baseUrl would send a live request.

    Structural, not textual: the prose above is allowed to NAME the endpoint
    while explaining that nothing reaches it. Only a scheme-qualified URL in a
    string constant could actually be used as a baseUrl.
    """
    import ast
    from pathlib import Path

    # Assembled at runtime so no single string constant in this file contains
    # the needle - otherwise the guard's own assertion is the first thing it
    # finds, which is a trap I walked into writing it.
    needle = "https://" + "api." + "anthropic" + ".com"
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert needle not in node.value, (
                f"a real endpoint URL at line {node.lineno}")
    # the adapter's default IS the real endpoint - that is correct, and it is
    # why every test above passes an explicit fake baseUrl
    assert ah_anthropic.DEFAULT_BASE_URL == needle
