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


def test_the_os_store_source_says_it_is_not_implemented():
    config = router_config("http://127.0.0.1:1/v1",
                           credential={"source": "os_store", "key": "some-key"})
    client = RouterAdapter(config, environ={})
    assert client.capabilities().public()["authOwnership"] == "os_store_reference"
    with pytest.raises(ah_codes.ProviderError) as excinfo:
        client.complete(request_of())
    assert excinfo.value.code == "credential_source_unsupported"


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
    assert body["tools"][0]["function"]["name"] == "plan_propose"
    assert body["messages"][0]["role"] == "system"


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
        history = [{"tool": first.tool_calls[0].name, "ok": True,
                    "result": {"sessions": [{"sessionId": "s1"}]}}]
        second = client.complete(request_of(history=history))
    assert second.text == "done"
    tool_messages = [m for m in seen[1]["messages"] if m["role"] == "tool"]
    assert tool_messages and tool_messages[0]["name"] == "session_list"
    assert "s1" in tool_messages[0]["content"]


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
