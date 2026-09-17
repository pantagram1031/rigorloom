# -*- coding: utf-8 -*-
"""The custom-router adapter, against a local fake. No real network, ever.

Everything here talks to a stdlib ``http.server`` on 127.0.0.1 that the test
starts and stops. There is no live-provider smoke test in this suite and none
is claimed — see the handoff.
"""
from __future__ import annotations

import json
import shutil

import pytest

from _agenthost_support import (
    CREDENTIAL_ENV,
    PLACEHOLDER_CREDENTIAL,
    FakeRouter,
    agenthost_scripts_on_path,
    completion,
    router_config,
    sse_lines,
)
from _runtime_client import CORPUS_FORM, run_cli

agenthost_scripts_on_path()

import ah_codes  # noqa: E402
import ah_events  # noqa: E402
import mock_agent  # noqa: E402
from ah_host import AgentHost  # noqa: E402
from ah_provider import ProviderRequest  # noqa: E402
from ah_router import RouterAdapter  # noqa: E402


@pytest.fixture()
def env():
    return {CREDENTIAL_ENV: PLACEHOLDER_CREDENTIAL}


def adapter(server, env, **overrides):
    return RouterAdapter(router_config(server.base_url, **overrides), environ=env)


def request_of(**kwargs):
    base = {"instruction": "fill the first seat", "context": {"sessionId": "s"},
            "tools": []}
    base.update(kwargs)
    return ProviderRequest(**base)


# --- config: a reference, never a secret ------------------------------------

@pytest.mark.parametrize("member", ["apiKey", "api_key", "token", "secret",
                                    "authorization", "password"])
def test_a_config_carrying_a_secret_shaped_member_is_refused(member):
    config = router_config("http://127.0.0.1:1/v1")
    config[member] = "anything at all"
    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        RouterAdapter(config, environ={})
    assert excinfo.value.code == "config_invalid"
    assert "reference" in excinfo.value.message


def test_a_secret_inside_the_credential_block_is_refused_too():
    config = router_config("http://127.0.0.1:1/v1")
    config["credential"] = {"source": "env", "key": "K", "token": "leaked"}
    with pytest.raises(ah_codes.AgentHostError):
        RouterAdapter(config, environ={})


def test_extra_headers_cannot_smuggle_a_secret():
    config = router_config("http://127.0.0.1:1/v1")
    config["extraHeaders"] = {"Authorization": "Bearer whatever"}
    with pytest.raises(ah_codes.AgentHostError):
        RouterAdapter(config, environ={})


def test_an_unknown_config_member_is_refused():
    config = router_config("http://127.0.0.1:1/v1")
    config["temperature"] = 0.7
    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        RouterAdapter(config, environ={})
    assert excinfo.value.data["unknown"] == ["temperature"]


def test_a_non_http_base_url_is_refused():
    with pytest.raises(ah_codes.AgentHostError):
        RouterAdapter(router_config("ftp://example.invalid/v1"), environ={})


def test_the_profile_reports_the_reference_and_never_a_value(env):
    client = RouterAdapter(router_config("http://127.0.0.1:1/v1"), environ=env)
    public = client.capabilities().public()
    assert public["authOwnership"] == "env_reference"
    assert public["notes"]["credentialRef"] == {"source": "env",
                                                "key": CREDENTIAL_ENV,
                                                "scheme": "bearer"}
    assert PLACEHOLDER_CREDENTIAL not in json.dumps(public)


def test_a_missing_credential_is_a_provider_failure_not_a_crash():
    client = RouterAdapter(router_config("http://127.0.0.1:1/v1"), environ={})
    with pytest.raises(ah_codes.ProviderError) as excinfo:
        client.complete(request_of())
    assert excinfo.value.code == "credential_unavailable"
    assert excinfo.value.data["credentialRef"] == CREDENTIAL_ENV


def test_omitting_credential_means_none_is_required():
    """A keyless OpenAI-compatible bridge is a reference of source none, not a
    missing env var. The adapter must complete without an Authorization header.
    """
    with FakeRouter(lambda path, body: {"json": completion("ok")}) as srv:
        client = RouterAdapter(
            {"providerId": "keyless", "baseUrl": srv.base_url,
             "model": "fake-model"},
            environ={})
        public = client.capabilities().public()
        assert public["authOwnership"] == "provider_managed"
        assert public["notes"]["credential"]["state"] == "not_required"
        response = client.complete(request_of())
        assert srv.last_authorization() is None
    assert response.text == "ok"


def test_source_none_is_the_same_as_omitting_the_block():
    with FakeRouter(lambda path, body: {"json": completion("ok")}) as srv:
        client = RouterAdapter(
            router_config(srv.base_url, credential={"source": "none"}),
            environ={})
        assert client.capabilities().public()["notes"]["credential"]["state"] \
            == "not_required"
        client.complete(request_of())
        assert srv.last_authorization() is None


def test_os_store_outside_the_desktop_is_a_provider_config_refusal():
    config = router_config("http://127.0.0.1:1/v1",
                           credential={"source": "os_store", "key": "some-key"})
    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        RouterAdapter(config, environ={})
    assert excinfo.value.code == "provider_config"
    message = excinfo.value.message.lower()
    assert "desktop" in message
    assert "keychain" in message


# --- capabilities are declared, never assumed -------------------------------

def test_an_unprobed_router_declares_unknown_not_yes(env):
    client = RouterAdapter(router_config("http://127.0.0.1:1/v1",
                                         capabilities={}), environ=env)
    profile = client.capabilities()
    assert profile.state("streaming") == "unknown"
    assert profile.supports("streaming") is False


def test_config_can_declare_that_this_router_does_not_stream(env):
    client = RouterAdapter(router_config("http://127.0.0.1:1/v1",
                                         capabilities={"streaming": "no"}),
                           environ=env)
    with pytest.raises(ah_codes.ProviderError) as excinfo:
        list(client.stream(request_of()))
    assert excinfo.value.code == "provider_capability_unavailable"
    assert excinfo.value.data["capability"] == "streaming"


# --- happy path -------------------------------------------------------------

def test_a_plain_completion_round_trips(env):
    with FakeRouter(lambda path, body: {"json": completion("hello there")}) as srv:
        response = adapter(srv, env).complete(request_of())
    assert response.text == "hello there"
    assert response.tool_calls == ()
    assert response.finish_reason == "stop"


def test_the_credential_is_sent_but_never_recorded(env, tmp_path):
    log = ah_events.EventLog(tmp_path / "events.jsonl")
    with FakeRouter(lambda path, body: {"json": completion("ok")}) as srv:
        client = adapter(srv, env)
        client.complete(request_of())
        log.append("provider.response", provider=client.provider_id,
                   profile=client.capabilities().public())
        sent = srv.last_authorization()
    assert sent == f"Bearer {PLACEHOLDER_CREDENTIAL}"
    written = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert PLACEHOLDER_CREDENTIAL not in written
    assert PLACEHOLDER_CREDENTIAL not in json.dumps(log.public())


def test_the_request_body_carries_the_model_and_the_tools(env):
    with FakeRouter(lambda path, body: {"json": completion("ok")}) as srv:
        adapter(srv, env).complete(request_of(tools=[
            {"name": "plan_propose", "description": "d",
             "inputSchema": {"type": "object"}}]))
        body = srv.requests[-1]["body"]
    assert srv.requests[-1]["path"].endswith("/chat/completions")
    assert body["model"] == "fake-model"
    assert "max_tokens" not in body
    assert body["tools"][0]["function"]["name"] == "plan_propose"
    assert "tool_choice" not in body
    assert body["messages"][0]["role"] == "system"


def test_max_tokens_is_sent_only_when_configured(env):
    with FakeRouter(lambda path, body: {"json": completion("ok")}) as srv:
        adapter(srv, env, maxTokens=256).complete(request_of())
        assert srv.requests[-1]["body"]["max_tokens"] == 256


# --- tool-call round trip ---------------------------------------------------

def test_a_tool_call_comes_back_parsed(env):
    reply = completion(None, tool_calls=[
        {"id": "tc-1", "name": "document_inspect",
         "arguments": {"sessionId": "abc", "include": ["regions"]}}])
    with FakeRouter(lambda path, body: {"json": reply}) as srv:
        response = adapter(srv, env).complete(request_of())
    assert response.finish_reason == "tool_calls"
    call = response.tool_calls[0]
    assert (call.call_id, call.name) == ("tc-1", "document_inspect")
    assert call.arguments == {"sessionId": "abc", "include": ["regions"]}


def test_legacy_function_call_is_parsed_as_a_tool_call(env):
    reply = {"choices": [{"index": 0, "finish_reason": "function_call",
                          "message": {"role": "assistant", "content": None,
                                      "function_call": {
                                          "name": "session_list",
                                          "arguments": "{}"}}}]}
    with FakeRouter(lambda path, body: {"json": reply}) as srv:
        response = adapter(srv, env).complete(request_of())
    assert response.tool_calls[0].name == "session_list"
    assert response.tool_calls[0].arguments == {}


def test_json_assistant_text_is_recovered_as_a_tool_call_when_tools_were_offered(env):
    """The live Cursor bridge on this PC emitted this instead of tool_calls."""
    blob = json.dumps({"name": "document_inspect",
                       "arguments": {"sessionId": "s1"}})
    tools = [{"name": "document_inspect", "description": "d",
              "inputSchema": {"type": "object"}}]
    with FakeRouter(lambda path, body: {"json": completion(blob)}) as srv:
        response = adapter(srv, env).complete(request_of(tools=tools))
    assert response.finish_reason == "tool_calls"
    assert response.text is None
    assert response.tool_calls[0].name == "document_inspect"
    assert response.tool_calls[0].arguments == {"sessionId": "s1"}


def test_json_assistant_text_that_is_not_an_offered_tool_stays_text(env):
    blob = json.dumps({"name": "not_a_tool", "arguments": {}})
    tools = [{"name": "document_inspect", "description": "d",
              "inputSchema": {"type": "object"}}]
    with FakeRouter(lambda path, body: {"json": completion(blob)}) as srv:
        response = adapter(srv, env).complete(request_of(tools=tools))
    assert response.tool_calls == ()
    assert response.text == blob


def test_prompt_mode_omits_the_tools_array_and_recovers_json_text(env):
    tools = [{"name": "document_inspect", "description": "look",
              "inputSchema": {"type": "object"}}]
    blob = json.dumps({"name": "document_inspect",
                       "arguments": {"sessionId": "s1"}})
    with FakeRouter(lambda path, body: {"json": completion(blob)}) as srv:
        client = adapter(srv, env, toolsInBody=False)
        response = client.complete(request_of(tools=tools))
        body = srv.requests[-1]["body"]
    assert "tools" not in body
    assert "document_inspect" in body["messages"][0]["content"]
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].name == "document_inspect"


def test_prompt_mode_history_is_plain_chat_not_role_tool(env):
    tools = [{"name": "session_list", "description": "d",
              "inputSchema": {"type": "object"}}]
    seen = []

    def responder(path, body):
        seen.append(body)
        if len(seen) == 1:
            return {"json": completion(json.dumps(
                {"name": "session_list", "arguments": {}}))}
        return {"json": completion("done")}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env, toolsInBody=False)
        first = client.complete(request_of(tools=tools))
        history = [{"tool": first.tool_calls[0].name,
                    "callId": first.tool_calls[0].call_id,
                    "arguments": first.tool_calls[0].arguments,
                    "ok": True,
                    "result": {"sessions": [{"sessionId": "s1"}]}}]
        second = client.complete(request_of(tools=tools, history=history))
    assert second.text == "done"
    roles = [m["role"] for m in seen[1]["messages"]]
    assert "tool" not in roles
    assert any(m["role"] == "assistant" and "session_list" in (m.get("content") or "")
               for m in seen[1]["messages"])


def test_a_tools_array_500_falls_back_to_prompt_mode_for_the_session(env):
    """Desktop Settings cannot name toolsInBody; the adapter has to notice."""
    tools = [{"name": "document_inspect", "description": "look",
              "inputSchema": {"type": "object"}}]
    blob = json.dumps({"name": "document_inspect",
                       "arguments": {"sessionId": "s1"}})
    seen = []

    def responder(path, body):
        seen.append(body)
        if body.get("tools"):
            return {"status": 500,
                    "text": json.dumps({"error": "cursor_cli_error",
                                        "message": "tools not supported"})}
        return {"json": completion(blob)}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env)
        first = client.complete(request_of(tools=tools))
        second = client.complete(request_of(tools=tools, history=[{
            "tool": first.tool_calls[0].name,
            "callId": first.tool_calls[0].call_id,
            "arguments": first.tool_calls[0].arguments,
            "ok": True, "result": {"sessions": []},
        }]))
    assert "tools" in seen[0]
    assert "tools" not in seen[1]
    assert "tools" not in seen[2]
    assert first.finish_reason == "tool_calls"
    assert first.tool_calls[0].name == "document_inspect"
    fallback = first.public()["promptModeFallback"]
    assert fallback["status"] == 500
    assert "cursor_cli_error" in fallback["body"]
    assert fallback["fault"]["code"] == "provider_http_error"
    assert "promptModeFallback" not in second.public()
    assert client.tools_in_body is False
    assert client.capabilities().public()["notes"]["toolsInBody"] is False
    assert client.capabilities().public()["notes"]["promptModeFallback"]["status"] == 500


def test_a_timeout_on_a_tools_array_falls_back_to_prompt_mode(env):
    tools = [{"name": "document_inspect", "description": "look",
              "inputSchema": {"type": "object"}}]
    blob = json.dumps({"name": "document_inspect", "arguments": {"sessionId": "s1"}})

    def responder(path, body):
        if body.get("tools"):
            return {"delaySeconds": 2.0, "json": completion("late")}
        return {"json": completion(blob)}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env, timeoutSeconds=0.35)
        response = client.complete(request_of(tools=tools))
    assert response.tool_calls[0].name == "document_inspect"
    assert response.public()["promptModeFallback"]["code"] == "provider_timeout"
    assert client.tools_in_body is False
    tools = [{"name": "session_list", "description": "d",
              "inputSchema": {"type": "object"}}]
    blob = json.dumps({"name": "session_list", "arguments": {}})

    def responder(path, body):
        if body.get("tools"):
            return {"status": 400, "text": "unknown field: tools"}
        return {"json": completion(blob)}

    with FakeRouter(responder) as srv:
        response = adapter(srv, env).complete(request_of(tools=tools))
    assert response.tool_calls[0].name == "session_list"
    assert response.public()["promptModeFallback"]["status"] == 400


def test_a_500_that_does_not_mention_tools_stays_a_provider_fault(env):
    tools = [{"name": "session_list", "description": "d",
              "inputSchema": {"type": "object"}}]
    with FakeRouter(lambda path, body: {"status": 500, "text": "upstream boom"}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of(tools=tools))
    assert excinfo.value.code == "provider_http_error"
    assert excinfo.value.data["status"] == 500


def test_a_cursor_named_model_starts_in_prompt_mode_without_a_tools_probe(env):
    """A tools-array probe hangs this bridge's single worker; skip it."""
    tools = [{"name": "document_inspect", "description": "look",
              "inputSchema": {"type": "object"}}]
    blob = json.dumps({"name": "document_inspect",
                       "arguments": {"sessionId": "s1"}})
    seen = []

    def responder(path, body):
        seen.append(body)
        return {"json": completion(blob)}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env, model="cursor-grok-4.6-high-fast")
        response = client.complete(request_of(tools=tools))
    assert all("tools" not in body for body in seen)
    assert response.tool_calls[0].name == "document_inspect"
    assert client.tools_in_body is False
    fallback = response.public()["promptModeFallback"]
    assert "Cursor-named" in fallback["reason"]
    assert "cursor_cli_error" in fallback["body"]
    assert client.timeout >= 180.0


def test_explicit_tools_in_body_still_probes_a_cursor_model(env):
    tools = [{"name": "document_inspect", "description": "look",
              "inputSchema": {"type": "object"}}]
    blob = json.dumps({"name": "document_inspect", "arguments": {}})
    seen = []

    def responder(path, body):
        seen.append(body)
        if body.get("tools"):
            return {"status": 500,
                    "text": json.dumps({"error": "cursor_cli_error"})}
        return {"json": completion(blob)}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env, model="cursor-grok-4.6-high-fast",
                         toolsInBody=True)
        response = client.complete(request_of(tools=tools))
    assert "tools" in seen[0]
    assert "tools" not in seen[1]
    assert response.tool_calls[0].name == "document_inspect"
    assert response.public()["promptModeFallback"]["status"] == 500


def test_explicit_prompt_mode_does_not_send_tools_even_once(env):
    tools = [{"name": "document_inspect", "description": "look",
              "inputSchema": {"type": "object"}}]
    blob = json.dumps({"name": "document_inspect", "arguments": {}})
    with FakeRouter(lambda path, body: {"json": completion(blob)}) as srv:
        client = adapter(srv, env, toolsInBody=False)
        client.complete(request_of(tools=tools))
        assert "tools" not in srv.requests[-1]["body"]
        assert client.capabilities().public()["notes"]["toolsInBodyConfigured"] is True


def test_prompt_mode_slims_inspect_history(env):
    tools = [{"name": "document_inspect", "description": "look"}]
    inspect_result = {
        "documentHash": "abc",
        "summary": {"anchors": ["I.  서론"], "fillTargetCount": 0,
                    "noise": "drop-me"},
        "regions": {"regions": []},
        "graph": {"huge": True},
        "forbidden": {
            "counts": {"anchors": 1},
            "residue": {"profileSource": "bound_form"},
            "anchors": [{"text": "학번", "keepable": True,
                         "atPara": 3, "drop": "addr"}],
            "placeholders": [],
            "removalTargets": [],
        },
    }
    seen = []

    def responder(path, body):
        seen.append(body)
        if len(seen) == 1:
            return {"json": completion(json.dumps(
                {"name": "document_inspect",
                 "arguments": {"sessionId": "s"}}))}
        return {"json": completion("done")}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env, toolsInBody=False)
        first = client.complete(request_of(tools=tools))
        client.complete(request_of(tools=tools, history=[{
            "tool": first.tool_calls[0].name,
            "callId": first.tool_calls[0].call_id,
            "arguments": first.tool_calls[0].arguments,
            "ok": True, "result": inspect_result,
        }]))
    user = [m for m in seen[1]["messages"] if m["role"] == "user"][-1]
    payload = json.loads(user["content"])
    assert payload["result"]["summary"]["anchors"] == ["I.  서론"]
    assert "graph" not in payload["result"]
    assert "noise" not in payload["result"]["summary"]
    assert payload["result"]["forbidden"]["anchors"] == [
        {"text": "학번", "keepable": True}]
    assert payload["result"]["forbidden"]["counts"] == {"anchors": 1}


def test_prompt_mode_catalogue_lists_argument_keys(env):
    tools = [{"name": "plan_propose",
              "description": "propose",
              "inputSchema": {"type": "object",
                              "properties": {"ops": {}, "declares": {},
                                             "backend": {}}}}]
    seen = []

    def responder(path, body):
        seen.append(body)
        return {"json": completion("done")}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env, toolsInBody=False)
        client.complete(request_of(tools=tools))
    catalogue = json.loads(
        seen[0]["messages"][0]["content"].split("Catalogue: ", 1)[1])
    assert catalogue[0]["arguments"] == ["backend", "declares", "ops"]


def test_the_second_turn_carries_the_tool_result_back(env):
    seen = []

    def responder(path, body):
        seen.append(body)
        if len(seen) == 1:
            return {"json": completion(None, tool_calls=[
                {"id": "tc-1", "name": "session_list", "arguments": {}}])}
        return {"json": completion("done")}

    with FakeRouter(responder) as srv:
        client = adapter(srv, env)
        first = client.complete(request_of())
        history = [{"tool": first.tool_calls[0].name,
                    "callId": first.tool_calls[0].call_id,
                    "arguments": first.tool_calls[0].arguments,
                    "ok": True,
                    "result": {"sessions": [{"sessionId": "s1"}]}}]
        second = client.complete(request_of(history=history))
    assert second.text == "done"
    tool_messages = [m for m in seen[1]["messages"] if m["role"] == "tool"]
    assert tool_messages and tool_messages[0]["name"] == "session_list"
    assert tool_messages[0]["tool_call_id"] == "tc-1"
    assert "s1" in tool_messages[0]["content"]
    echoed = [m for m in seen[1]["messages"] if m.get("tool_calls")]
    assert echoed and echoed[0]["tool_calls"][0]["id"] == "tc-1"
    assert echoed[0]["tool_calls"][0]["function"]["name"] == "session_list"


def test_usage_from_the_gateway_is_surfaced_not_dropped(env):
    reply = completion("hello there")
    reply["usage"] = {"prompt_tokens": 11, "completion_tokens": 3,
                      "total_tokens": 14}
    with FakeRouter(lambda path, body: {"json": reply}) as srv:
        response = adapter(srv, env).complete(request_of())
    assert response.public()["usage"]["total_tokens"] == 14
    assert response.raw["usage"]["prompt_tokens"] == 11


def test_tool_arguments_that_are_not_json_are_a_provider_failure(env):
    reply = {"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "tool_calls": [
            {"id": "x", "type": "function",
             "function": {"name": "session_list", "arguments": "{not json"}}]}}]}
    with FakeRouter(lambda path, body: {"json": reply}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    assert excinfo.value.code == "provider_malformed_response"


def test_duplicate_members_in_tool_arguments_are_refused(env):
    """The Runtime's strict JSON, reused on the provider boundary."""
    reply = {"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "tool_calls": [
            {"id": "x", "type": "function",
             "function": {"name": "session_list",
                          "arguments": '{"a": 1, "a": 2}'}}]}}]}
    with FakeRouter(lambda path, body: {"json": reply}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    assert excinfo.value.data["strictCode"] == "duplicate_key"


def test_a_tool_call_with_no_function_name_is_refused(env):
    reply = {"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant",
        "tool_calls": [{"id": "x", "type": "function", "function": {}}]}}]}
    with FakeRouter(lambda path, body: {"json": reply}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    assert excinfo.value.code == "provider_malformed_response"


# --- streaming --------------------------------------------------------------

def test_sse_streams_when_the_config_declares_it(env):
    lines = sse_lines(["Look", "ing", " at it."],
                      tool_calls=[{"id": "tc-1", "name": "document_inspect",
                                   "arguments": {"sessionId": "s"}}])
    with FakeRouter(lambda path, body: {"sse": lines}) as srv:
        client = adapter(srv, env, capabilities={"streaming": "yes"})
        assert client.capabilities().supports("streaming") is True
        chunks = list(client.stream(request_of()))
    text = "".join(c["text"] for c in chunks if c["type"] == "text")
    assert text == "Looking at it."
    tool_chunk = next(c for c in chunks if c["type"] == "tool_call")
    assert tool_chunk["toolCall"]["name"] == "document_inspect"
    assert chunks[-1]["type"] == "done"


def test_a_streaming_request_sets_the_stream_flag(env):
    with FakeRouter(lambda path, body: {"sse": sse_lines(["x"])}) as srv:
        client = adapter(srv, env, capabilities={"streaming": "yes"})
        list(client.stream(request_of()))
        assert srv.requests[-1]["body"]["stream"] is True


def test_a_stream_done_event_carries_usage_when_the_gateway_sends_it(env):
    lines = sse_lines(["ok"])
    lines.insert(-1, "data: " + json.dumps(
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 4, "completion_tokens": 1,
                   "total_tokens": 5}}))
    with FakeRouter(lambda path, body: {"sse": lines}) as srv:
        client = adapter(srv, env, capabilities={"streaming": "yes"})
        chunks = list(client.stream(request_of()))
    done = chunks[-1]
    assert done["type"] == "done"
    assert done["finishReason"] == "stop"
    assert done["usage"]["total_tokens"] == 5


def test_a_malformed_stream_chunk_is_a_provider_failure(env):
    with FakeRouter(lambda path, body: {"sse": ["data: {broken", "data: [DONE]"]}) as srv:
        client = adapter(srv, env, capabilities={"streaming": "yes"})
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            list(client.stream(request_of()))
    assert excinfo.value.code == "provider_malformed_response"


# --- provider failures stay provider failures -------------------------------

def test_a_500_is_a_provider_http_error(env):
    with FakeRouter(lambda path, body: {"status": 500, "text": "upstream boom"}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    error = excinfo.value
    assert error.code == "provider_http_error"
    assert error.data["status"] == 500
    assert "boom" in error.data["body"]


@pytest.mark.parametrize("status", [401, 403])
def test_an_auth_rejection_names_the_reference_not_the_secret(env, status):
    with FakeRouter(lambda path, body: {"status": status, "text": "nope"}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    error = excinfo.value
    assert error.code == "provider_unauthorized"
    assert error.data["credentialRef"]["key"] == CREDENTIAL_ENV
    assert PLACEHOLDER_CREDENTIAL not in json.dumps(error.as_dict())


def test_a_slow_router_is_a_timeout_not_a_hang(env):
    with FakeRouter(lambda path, body: {"delaySeconds": 2.0,
                                        "json": completion("late")}) as srv:
        client = adapter(srv, env, timeoutSeconds=0.35)
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            client.complete(request_of())
    assert excinfo.value.code == "provider_timeout"


def test_a_non_json_body_is_a_provider_malformed_response(env):
    with FakeRouter(lambda path, body: {"text": "<html>gateway</html>"}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    assert excinfo.value.code == "provider_malformed_response"


def test_no_choices_is_an_empty_response_not_a_guess(env):
    with FakeRouter(lambda path, body: {"json": {"choices": []}}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env).complete(request_of())
    assert excinfo.value.code == "provider_empty_response"


def test_an_oversized_body_is_refused(env):
    big = completion("x" * 5000)
    with FakeRouter(lambda path, body: {"json": big}) as srv:
        with pytest.raises(ah_codes.ProviderError) as excinfo:
            adapter(srv, env, maxResponseBytes=1024).complete(request_of())
    assert excinfo.value.code == "provider_response_too_large"


def test_an_unreachable_endpoint_is_a_provider_failure(env):
    server = FakeRouter(lambda path, body: {"json": completion("x")}).start()
    base = server.base_url
    server.stop()
    client = RouterAdapter(router_config(base, timeoutSeconds=2), environ=env)
    with pytest.raises(ah_codes.ProviderError) as excinfo:
        client.complete(request_of())
    assert excinfo.value.code in ("provider_unreachable", "provider_timeout")


def test_every_router_failure_uses_a_provider_code_never_a_runtime_one():
    from rt_codes import ERROR_CODES

    assert set(ah_codes.PROVIDER_CODES).isdisjoint(ERROR_CODES)


# --- through the whole host -------------------------------------------------

def _agent_model(path, body):
    """A deterministic model over HTTP: decides from the tool messages it sees."""
    tools = [m["name"] for m in body["messages"] if m["role"] == "tool"]
    if "document_inspect" not in tools:
        return {"json": completion(None, tool_calls=[
            {"id": "t1", "name": "document_inspect",
             "arguments": {"sessionId": _session_of(body), "include": ["regions"]}}])}
    if "plan_propose" not in tools:
        regions = _result_of(body, "document_inspect")["regions"]["regions"]
        target = mock_agent.choose_target(regions)
        return {"json": completion(None, tool_calls=[
            {"id": "t2", "name": "plan_propose",
             "arguments": {"sessionId": _session_of(body), "backend": "preedit",
                           "ops": [mock_agent.build_op(target, "ROUTER-0001")],
                           "proposer": "agenthost-router"}}])}
    if "plan_validate" not in tools:
        plan = _result_of(body, "plan_propose")["plan"]
        return {"json": completion(None, tool_calls=[
            {"id": "t3", "name": "plan_validate",
             "arguments": {"planId": plan["planId"]}}])}
    return {"json": completion("Proposed and validated; a human must approve.")}


def _session_of(body):
    user = next(m for m in body["messages"] if m["role"] == "user")
    return json.loads(user["content"])["context"]["sessionId"]


def _result_of(body, tool):
    for message in reversed(body["messages"]):
        if message.get("role") == "tool" and message.get("name") == tool:
            return json.loads(message["content"])["result"]
    raise AssertionError(f"no result for {tool}")


def test_the_host_drives_a_router_provider_end_to_end(tmp_path, env, monkeypatch):
    monkeypatch.setenv(CREDENTIAL_ENV, PLACEHOLDER_CREDENTIAL)
    root = tmp_path / "root"
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    run_cli(root, "open", "--path", str(source))

    with FakeRouter(_agent_model) as srv:
        client = adapter(srv, env)
        door = mock_agent.open_door("protocol", root, None)
        try:
            payload = AgentHost(door, client).run("fill the first seat")
        finally:
            door.close()

    assert payload["ok"] is True
    assert payload["providerFault"] is None
    assert payload["plan"]["ops"][0]["params"]["text"] == "ROUTER-0001"
    assert payload["validation"]["ok"] is True
    assert payload["refusals"] == []
    assert PLACEHOLDER_CREDENTIAL not in json.dumps(payload)


def test_a_router_that_asks_to_apply_is_refused_at_the_gate(tmp_path, env,
                                                            monkeypatch):
    monkeypatch.setenv(CREDENTIAL_ENV, PLACEHOLDER_CREDENTIAL)
    root = tmp_path / "root"
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    run_cli(root, "open", "--path", str(source))

    def hostile(path, body):
        tools = [m["name"] for m in body["messages"] if m["role"] == "tool"]
        if "plan_apply" not in tools:
            return {"json": completion(None, tool_calls=[
                {"id": "h1", "name": "plan_apply",
                 "arguments": {"planId": "whatever", "approvalId": "whatever"}}])}
        return {"json": completion("I was refused.")}

    with FakeRouter(hostile) as srv:
        door = mock_agent.open_door("protocol", root, None)
        try:
            payload = AgentHost(door, adapter(srv, env)).run("apply it")
        finally:
            door.close()

    forbidden = [row for row in payload["refusals"]
                 if row["code"] == "tool_forbidden"]
    assert len(forbidden) == 1 and forbidden[0]["stage"] == "compile"
    kinds = [event["kind"] for event in payload["events"]["events"]]
    assert "runtime.refused" not in kinds
    assert run_cli(root, "sessions").code == 0


def test_a_router_outage_mid_run_is_a_provider_fault_not_a_document_verdict(
        tmp_path, env, monkeypatch):
    monkeypatch.setenv(CREDENTIAL_ENV, PLACEHOLDER_CREDENTIAL)
    root = tmp_path / "root"
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]

    calls = {"n": 0}

    def flaky(path, body):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"json": completion(None, tool_calls=[
                {"id": "t1", "name": "document_inspect",
                 "arguments": {"sessionId": _session_of(body)}}])}
        return {"status": 503, "text": "gateway down"}

    with FakeRouter(flaky) as srv:
        door = mock_agent.open_door("protocol", root, None)
        try:
            payload = AgentHost(door, adapter(srv, env)).run("fill it")
        finally:
            door.close()

    assert payload["ok"] is False
    assert payload["providerFault"]["code"] == "provider_http_error"
    assert payload["providerFault"]["data"]["status"] == 503
    # the document is untouched and nothing was decided about it
    assert payload["plan"] is None and payload["validation"] is None
    assert run_cli(root, "candidates", "--session",
                   session).result["candidates"] == []


def _prompt_names(body):
    """Tool names recovered from prompt-mode assistant JSON, not role=tool."""
    names = []
    for message in body.get("messages") or []:
        if message.get("role") != "assistant":
            continue
        raw = message.get("content") or ""
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("name"), str):
            names.append(parsed["name"])
    return names


def _prompt_result_of(body, tool):
    for message in reversed(body.get("messages") or []):
        if message.get("role") != "user":
            continue
        raw = message.get("content") or ""
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("ok") is True:
            result = parsed.get("result") or {}
            if tool == "document_inspect" and "regions" in result:
                return result
            if tool == "plan_propose" and "plan" in result:
                return result
            if tool == "plan_validate" and "validation" in result:
                return result
    raise AssertionError(f"no prompt-mode result for {tool}")


def _fallback_agent_model(path, body, target):
    """Same script as `_agent_model`, over JSON-in-text after a tools 500."""
    if body.get("tools"):
        return {"status": 500,
                "text": json.dumps({"error": "cursor_cli_error",
                                    "message": "tools array rejected"})}
    names = _prompt_names(body)
    if "document_inspect" not in names:
        return {"json": completion(json.dumps({
            "name": "document_inspect",
            "arguments": {"sessionId": _session_of(body),
                          "include": ["regions"]}}))}
    if "plan_propose" not in names:
        return {"json": completion(json.dumps({
            "name": "plan_propose",
            "arguments": {"sessionId": _session_of(body), "backend": "preedit",
                          "ops": [mock_agent.build_op(target, "ROUTER-0001")],
                          "proposer": "agenthost-router"}}))}
    if "plan_validate" not in names:
        plan = _prompt_result_of(body, "plan_propose")["plan"]
        return {"json": completion(json.dumps({
            "name": "plan_validate",
            "arguments": {"planId": plan["planId"]}}))}
    return {"json": completion("Proposed and validated; a human must approve.")}


def test_the_host_records_a_tools_fallback_and_still_proposes(
        tmp_path, env, monkeypatch):
    monkeypatch.setenv(CREDENTIAL_ENV, PLACEHOLDER_CREDENTIAL)
    root = tmp_path / "root"
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    inspect = run_cli(root, "inspect", "--session", session,
                      "--include", "regions").result
    target = mock_agent.choose_target(inspect["regions"]["regions"])

    with FakeRouter(lambda path, body: _fallback_agent_model(path, body, target)) as srv:
        client = adapter(srv, env)
        door = mock_agent.open_door("protocol", root, None)
        try:
            payload = AgentHost(door, client).run("fill the first seat")
        finally:
            door.close()

    assert payload["ok"] is True
    assert payload["providerFault"] is None
    assert payload["plan"]["ops"][0]["params"]["text"] == "ROUTER-0001"
    assert payload["validation"]["ok"] is True
    notes = [event for event in payload["events"]["events"]
             if event["kind"] == "host.note"]
    assert len(notes) == 1
    assert "prompt-mode" in notes[0]["detail"]["message"]
    assert notes[0]["detail"]["providerFault"]["code"] == "provider_http_error"
    assert notes[0]["detail"]["toolsInBody"] is False
    kinds = [event["kind"] for event in payload["events"]["events"]]
    assert "provider.failed" not in kinds
    assert client.tools_in_body is False
    assert any(event["kind"] == "provider.response"
               and (event.get("detail") or {}).get("promptModeFallback")
               for event in payload["events"]["events"])
