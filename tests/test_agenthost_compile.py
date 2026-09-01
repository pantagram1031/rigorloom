# -*- coding: utf-8 -*-
"""The compile gate: a provider cannot reach a host action, whatever it asks."""
from __future__ import annotations

import pytest

from _agenthost_support import agenthost_scripts_on_path

agenthost_scripts_on_path()

import ah_codes  # noqa: E402
import ah_compile  # noqa: E402
import mcp_server  # noqa: E402
import rt_core  # noqa: E402
from ah_provider import ToolCall  # noqa: E402


def call(name, arguments=None, call_id="c1"):
    return ToolCall(call_id=call_id, name=name, arguments=arguments)


# --- the allowed set is derived ---------------------------------------------

def test_the_allowed_tools_are_the_agent_surface_minus_the_handshake():
    expected = {mcp_server.tool_name(method)
                for method in rt_core.AGENT_METHODS if method != "initialize"}
    assert set(ah_compile.ALLOWED_TOOLS) == expected


def test_the_gate_and_the_mcp_adapter_expose_the_same_surface():
    """Two doors, one surface. If they drift, a model learns two dialects."""
    assert set(ah_compile.ALLOWED_TOOLS) == set(mcp_server.TOOL_TO_METHOD)


def test_no_host_method_is_in_the_allowed_set():
    for method in rt_core.HOST_ONLY_METHODS:
        assert method not in ah_compile.ALLOWED_TOOLS
        assert mcp_server.tool_name(method) not in ah_compile.ALLOWED_TOOLS


def test_the_tool_definitions_handed_to_a_provider_match_the_allowed_set():
    names = {tool["name"] for tool in ah_compile.tool_definitions()}
    assert names == set(ah_compile.ALLOWED_TOOLS)


# --- what it lets through ---------------------------------------------------

@pytest.mark.parametrize("tool,method", sorted(ah_compile.ALLOWED_TOOLS.items()))
def test_every_allowed_tool_compiles_to_its_runtime_method(tool, method):
    compiled = ah_compile.compile_tool_call(call(tool, {"sessionId": "s"}))
    assert compiled.method == method
    assert compiled.tool == tool
    assert compiled.params == {"sessionId": "s"}


def test_missing_arguments_become_an_empty_object():
    compiled = ah_compile.compile_tool_call(call("session_list", None))
    assert compiled.params == {}


def test_the_compiled_params_are_a_copy_not_the_providers_object():
    arguments = {"sessionId": "s"}
    compiled = ah_compile.compile_tool_call(call("document_inspect", arguments))
    arguments["sessionId"] = "mutated"
    assert compiled.params["sessionId"] == "s"


# --- what it refuses --------------------------------------------------------

@pytest.mark.parametrize("name", [
    "plan_apply", "approval_resolve", "workspace_openPath",
    "plan/apply", "approval/resolve", "workspace/openPath",
])
def test_a_host_action_is_refused_by_name_in_either_spelling(name):
    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        ah_compile.compile_tool_call(call(name, {"planId": "p"}))
    error = excinfo.value
    assert error.code == "tool_forbidden"
    assert error.data["tool"] == name
    assert error.data["method"] in rt_core.HOST_ONLY_METHODS
    assert "propose" in error.message


def test_a_hostile_provider_gets_the_same_answer_as_a_confused_one():
    """No argument, framing or call id changes the outcome."""
    for arguments in ({}, {"planId": "p", "approvalId": "a"},
                      {"force": True}, {"client_role": "host"}):
        with pytest.raises(ah_codes.AgentHostError) as excinfo:
            ah_compile.compile_tool_call(
                call("plan_apply", arguments, call_id="urgent"))
        assert excinfo.value.code == "tool_forbidden"


def test_an_unknown_tool_is_refused_and_the_surface_is_named():
    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        ah_compile.compile_tool_call(call("delete_everything"))
    assert excinfo.value.code == "tool_unknown"
    assert "plan_propose" in excinfo.value.data["allowed"]


def test_an_empty_or_non_string_name_is_refused():
    for name in ("", None, 7):
        with pytest.raises(ah_codes.AgentHostError) as excinfo:
            ah_compile.compile_tool_call(call(name))
        assert excinfo.value.code == "tool_unknown"


def test_non_object_arguments_are_refused():
    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        ah_compile.compile_tool_call(call("plan_propose", ["not", "an", "object"]))
    assert excinfo.value.code == "tool_arguments_invalid"


# --- the gate cannot be widened by accident ---------------------------------

def test_adding_a_host_method_to_the_allowed_set_would_break_the_module():
    """The invariant is an assert at import, not a hope."""
    import importlib

    module = importlib.reload(ah_compile)
    assert not set(module.ALLOWED_TOOLS) & set(module.FORBIDDEN_TOOLS)


def test_the_forbidden_map_covers_every_host_method_both_ways():
    for method in rt_core.HOST_ONLY_METHODS:
        assert ah_compile.FORBIDDEN_TOOLS[method] == method
        assert ah_compile.FORBIDDEN_TOOLS[mcp_server.tool_name(method)] == method
    assert len(ah_compile.FORBIDDEN_TOOLS) >= len(rt_core.HOST_ONLY_METHODS)
