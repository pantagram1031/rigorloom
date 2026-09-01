#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Agent Host: a provider on one side, the agent-safe Runtime on the other.

This is the only network-capable component in the program, and it is
deliberately the one that cannot touch a document. It asks a model what to do,
compiles the answer through ``ah_compile`` — which refuses anything that is not
on the agent surface — and executes what survives against an agent-authority
Runtime connection. Document processing stays network-free: the Runtime and the
engine never learn that a provider exists.

THREE THINGS THIS LOOP WILL NOT DO:

  * turn a provider fault into a document verdict. A dead endpoint, a timeout
    or a malformed completion ends the run as a PROVIDER fault, named as such,
    with the plan state untouched;
  * fabricate an answer when the provider gives none. There is no fallback
    reply, no retry with a guess;
  * run forever. ``max_turns`` bounds the loop, and exhausting it is a refusal
    with the turn count, not a quiet stop.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import (  # noqa: E402
    HOST_VERSION,
    RUN_SCHEMA,
    AgentHostError,
    ProviderError,
)
from ah_compile import compile_tool_call, tool_definitions  # noqa: E402
from ah_events import EventLog  # noqa: E402
from ah_provider import ProviderRequest  # noqa: E402

RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

from mock_agent import DoorRefusal, redact  # noqa: E402
from rt_core import HOST_ONLY_METHODS  # noqa: E402

HOST_NAME = "rigorloom-agenthost"
DEFAULT_MAX_TURNS = 8


def summarize(tool: str, result: dict) -> dict:
    """What an event carries: enough to render, never the whole payload.

    A ``document/inspect`` result is a document's structure and a receipt is a
    receipt; pouring either into an event log makes it unreadable and makes the
    log grow with the document. The identifying fields are what a UI draws.
    """
    if not isinstance(result, dict):
        return {"shape": type(result).__name__}
    if tool == "document_inspect":
        regions = ((result.get("regions") or {}).get("regions")
                   if isinstance(result.get("regions"), dict) else None)
        return {"documentHash": result.get("documentHash"),
                "regions": len(regions) if regions is not None else None}
    if tool == "plan_propose":
        plan = result.get("plan") or {}
        return {"planId": plan.get("planId"), "opsHash": plan.get("opsHash"),
                "ops": len(plan.get("ops") or [])}
    if tool == "plan_validate":
        validation = result.get("validation") or {}
        return {"verdict": validation.get("verdict"), "ok": validation.get("ok"),
                "hard": [row.get("code") for row in validation.get("hard") or []]}
    if tool in ("approval_request", "approval_get"):
        approval = result.get("approval") or {}
        return {"approvalId": approval.get("approvalId"),
                "state": approval.get("state")}
    if tool == "candidate_list":
        return {"candidates": len(result.get("candidates") or [])}
    return {"keys": sorted(result)}


class AgentHost:
    def __init__(self, door, provider, events: EventLog | None = None,
                 max_turns: int = DEFAULT_MAX_TURNS):
        self.door = door
        self.provider = provider
        self.events = events if events is not None else EventLog()
        self.max_turns = max_turns

    def run(self, instruction: str, session_id: str | None = None) -> dict:
        profile = self.provider.capabilities()
        self.events.append("run.started", instruction=instruction,
                           maxTurns=self.max_turns)
        self.events.append("provider.selected", provider=profile.public())

        session_id = session_id or self._discover_session()
        context = {"sessionId": session_id, "surface": self.door.surface()}
        tools = tool_definitions()

        # Each entry carries the provider's own callId and arguments, not just
        # the tool name: a continuation that has to invent an id discards the
        # model's reference and only looks right because both halves are ours.
        history: list[dict] = []
        refusals: list[dict] = []
        provider_fault: dict | None = None
        closing_text: str | None = None
        finish_reason: str | None = None
        turns = 0
        budget_exhausted = False

        while True:
            if turns >= self.max_turns:
                budget_exhausted = True
                break
            turns += 1
            request = ProviderRequest(instruction=instruction, context=context,
                                      tools=tools, history=list(history))
            self.events.append("provider.request", turn=turns,
                               historyLength=len(history))
            try:
                response = self.provider.complete(request)
            except ProviderError as exc:
                # The model side broke. Nothing about the document changed, and
                # nothing is invented in its place.
                provider_fault = exc.as_dict()
                self.events.append("provider.failed", turn=turns, **exc.as_dict())
                break
            self.events.append("provider.response", turn=turns,
                               **response.public())
            closing_text = response.text or closing_text
            finish_reason = response.finish_reason

            if not response.tool_calls:
                break

            for call in response.tool_calls:
                self.events.append("tool.requested", turn=turns, **call.public())
                try:
                    compiled = compile_tool_call(call)
                except AgentHostError as exc:
                    # Refused at the boundary, before the Runtime is touched.
                    refusals.append({"stage": "compile", **exc.as_dict()})
                    self.events.append("tool.refused", turn=turns,
                                       stage="compile", **exc.as_dict())
                    history.append({"tool": call.name, "callId": call.call_id,
                                    "arguments": call.arguments, "ok": False,
                                    "error": exc.as_dict()})
                    continue
                self.events.append("tool.compiled", turn=turns,
                                   tool=compiled.tool, method=compiled.method)
                try:
                    result = self.door.call(compiled.method, compiled.params)
                except DoorRefusal as exc:
                    refusals.append({"stage": "runtime", "tool": compiled.tool,
                                     **exc.as_dict()})
                    self.events.append("runtime.refused", turn=turns,
                                       tool=compiled.tool, **exc.as_dict())
                    history.append({"tool": call.name, "callId": call.call_id,
                                    "arguments": call.arguments, "ok": False,
                                    "error": exc.as_dict()})
                    continue
                self.events.append("runtime.result", turn=turns,
                                   tool=compiled.tool,
                                   summary=summarize(compiled.tool, result))
                history.append({"tool": call.name, "callId": call.call_id,
                                "arguments": call.arguments, "ok": True,
                                "result": result})

        plan = self._latest(history, "plan_propose", "plan")
        validation = self._latest(history, "plan_validate", "validation")
        approval = self._latest(history, "approval_request", "approval")
        ok = provider_fault is None and not budget_exhausted

        payload = {
            "ok": ok,
            "schema": RUN_SCHEMA,
            "host": HOST_NAME,
            "hostVersion": HOST_VERSION,
            "provider": profile.public(),
            "instruction": instruction,
            "sessionId": session_id,
            "turns": turns,
            "finishReason": finish_reason,
            "closingText": closing_text,
            "plan": plan,
            "validation": validation,
            "approval": approval,
            "refusals": refusals,
            "providerFault": provider_fault,
            "turnBudgetExhausted": budget_exhausted,
            "surface": self.door.surface(),
            "neverCompiled": list(HOST_ONLY_METHODS),
            "events": self.events.public(),
        }
        self.events.append("run.finished", ok=ok, turns=turns,
                           refusals=len(refusals))
        payload["events"] = self.events.public()
        return payload

    # -- helpers ------------------------------------------------------------
    def _discover_session(self) -> str:
        try:
            rows = self.door.call("session/list")["sessions"]
        except DoorRefusal as exc:
            raise AgentHostError("runtime_unavailable",
                                 "could not list sessions on the agent door",
                                 detail=exc.as_dict()) from exc
        if not rows:
            raise AgentHostError(
                "runtime_unavailable",
                "no session under this root; a host must open a document first "
                "(neither this host nor its provider can)")
        return sorted(row["sessionId"] for row in rows)[0]

    @staticmethod
    def _latest(history: list, tool: str, member: str):
        for entry in reversed(history):
            if entry.get("tool") == tool and entry.get("ok"):
                return (entry.get("result") or {}).get(member)
        return None


def redact_run(payload: dict) -> dict:
    """Blank identity and timestamps, keeping content hashes.

    The Runtime's own rule, imported rather than re-stated
    (runtime/scripts/mock_agent.py ``VOLATILE_KEYS``), so a Desktop golden file
    of an Agent Host run and one of a mock-agent run redact identically.
    """
    return redact(payload)
