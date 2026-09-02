#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile a model's tool request into an agent-safe Runtime call, or refuse.

THIS IS THE GATE. Everything a provider asks for passes through
``compile_tool_call`` before any door is touched, and the allowed set is
DERIVED from ``rt_core.AGENT_METHODS`` — the same tuple the MCP adapter derives
from — never rostered here. A host method cannot become reachable by someone
adding a line to this file, because there is no line to add: the set is
computed, and a name that resolves to a host method is refused by identity
rather than by a denylist that could go stale.

A hostile or confused provider asking for ``approval/resolve``, ``plan/apply``
or ``workspace/openPath`` is refused HERE, before the Agent Host opens its
mouth to the Runtime. The Runtime would refuse it too — the agent entrypoint
does not build those methods — but a boundary that relies on the far side
catching everything is not a boundary.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import HOST_CONTROL_METHODS, AgentHostError  # noqa: E402
from ah_provider import ToolCall  # noqa: E402

#: The Runtime is a sibling top-level tree, imported read-only.
RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import mcp_server  # noqa: E402
from rt_core import AGENT_METHODS, HOST_ONLY_METHODS  # noqa: E402

#: Tool names a provider may use, mapped to the Runtime method each becomes.
#: ``initialize`` is the transport's handshake, not a tool, exactly as in the
#: MCP adapter (runtime/scripts/mcp_server.py).
ALLOWED_TOOLS: dict[str, str] = {
    mcp_server.tool_name(method): method
    for method in AGENT_METHODS if method != "initialize"
}

#: Every spelling of a host-only method, so a refusal can say WHY rather than
#: falling through to a vague "unknown". Both the slashed protocol name and the
#: underscored tool name resolve here.
FORBIDDEN_TOOLS: dict[str, str] = {}
for _method in HOST_ONLY_METHODS:
    FORBIDDEN_TOOLS[_method] = _method
    FORBIDDEN_TOOLS[mcp_server.tool_name(_method)] = _method

#: The long-lived host's OWN control methods, refused the same way and for the
#: same reason. ``context/grant`` would already fall through to
#: ``tool_unknown`` — the Runtime has never heard of it — but a model asking to
#: widen its own document grant deserves an answer that names the authority it
#: reached for, not a shrug. Same argument as the host-only set above: a vague
#: refusal is a refusal nobody can audit.
HOST_CONTROL_TOOLS: dict[str, str] = {}
for _method in HOST_CONTROL_METHODS:
    HOST_CONTROL_TOOLS[_method] = _method
    HOST_CONTROL_TOOLS[mcp_server.tool_name(_method)] = _method

assert not set(ALLOWED_TOOLS) & set(FORBIDDEN_TOOLS), (
    "a host method leaked into the allowed tool set")
assert not set(ALLOWED_TOOLS) & set(HOST_CONTROL_TOOLS), (
    "a host control method leaked into the allowed tool set")


@dataclass(frozen=True)
class CompiledCall:
    """A Runtime call the host is willing to make."""

    call_id: str
    tool: str
    method: str
    params: dict

    def public(self) -> dict:
        return {"callId": self.call_id, "tool": self.tool,
                "method": self.method, "params": self.params}


def tool_definitions() -> list:
    """The tool schemas to hand a provider. The MCP adapter's, unchanged.

    Reusing them means a model that has learned this surface through MCP sees
    the identical names and shapes through the Agent Host — one surface, two
    doors, which is the Phase 2 property carried forward.
    """
    return mcp_server.tool_definitions()


def compile_tool_call(call: ToolCall, scope=None) -> CompiledCall:
    """A provider tool request -> a Runtime call, or an ``AgentHostError``.

    ``scope`` is an optional ``ah_grant.ContextGrant``. When one is given its
    ``check_read`` runs as the LAST gate, after the call has resolved to a
    real agent method and before any door is touched, so an agent reaching
    past an operator's grant is refused here rather than by the Runtime — the
    Runtime has no idea a grant exists, and a boundary that relies on the far
    side catching everything is not a boundary.
    """
    name = call.name
    if not isinstance(name, str) or not name:
        raise AgentHostError("tool_unknown", "a tool call needs a name",
                             callId=call.call_id)
    if name in HOST_CONTROL_TOOLS:
        raise AgentHostError(
            "tool_forbidden",
            f"{name!r} is an operator control method of the host itself; a "
            "provider cannot grant itself document context, end the session, "
            "or drive the turn loop",
            callId=call.call_id, tool=name, method=HOST_CONTROL_TOOLS[name],
            hostControl=list(HOST_CONTROL_METHODS),
            allowed=sorted(ALLOWED_TOOLS))
    if name in FORBIDDEN_TOOLS:
        method = FORBIDDEN_TOOLS[name]
        raise AgentHostError(
            "tool_forbidden",
            f"{name!r} is a host action; a provider may propose and ask for "
            "approval, never grant or apply it",
            callId=call.call_id, tool=name, method=method,
            hostOnly=list(HOST_ONLY_METHODS), allowed=sorted(ALLOWED_TOOLS))
    method = ALLOWED_TOOLS.get(name)
    if method is None:
        raise AgentHostError(
            "tool_unknown", f"no tool named {name!r} on the agent surface",
            callId=call.call_id, tool=name, allowed=sorted(ALLOWED_TOOLS))
    arguments = call.arguments
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise AgentHostError("tool_arguments_invalid",
                             f"arguments for {name!r} must be an object",
                             callId=call.call_id, tool=name)
    if scope is not None:
        try:
            scope.check_read(method, arguments)
        except AgentHostError as exc:
            exc.data.setdefault("callId", call.call_id)
            exc.data.setdefault("tool", name)
            raise
    return CompiledCall(call_id=call.call_id, tool=name, method=method,
                        params=dict(arguments))
