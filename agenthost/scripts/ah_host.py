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

STREAMING, AND WHY THE TURN RECORD SAYS WHICH PATH RAN

A turn takes the streaming path when — and only when — the profile's
``streaming`` capability is a declared ``yes``. ``no`` and ``unknown`` both
fall back to ``complete()``, because an unverified maybe is not permission to
open an SSE connection and wait. Which path a turn ACTUALLY took is recorded
per turn in ``turnLog``, alongside the reason for any fallback, so a reader
never has to infer a measurement from a promise. The two paths produce the same
``ProviderResponse`` shape and the compile gate cannot tell them apart — which
is the point: a streamed tool call is a tool call, assembled whole by the
adapter, and a partial one has no shape to arrive in.

CONVERSATION MEMORY

An ``AgentHost`` with a ``HostSession`` remembers: prior exchanges are resent
inside a declared, bounded window, the turn is appended to the session's
append-only log, and a fresh process on the same session continues where the
last one stopped. Without a session it behaves exactly as it did in 0.1.0 —
one shot, no memory, nothing written.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import (  # noqa: E402
    HOST_VERSION,
    RUN_SCHEMA,
    STREAM_MODES,
    AgentHostError,
    ProviderError,
)
from ah_compile import compile_tool_call, tool_definitions  # noqa: E402
from ah_events import EventLog  # noqa: E402
from ah_grant import ContextGrant, materialize  # noqa: E402
from ah_provider import ProviderRequest  # noqa: E402
from ah_stream import drain  # noqa: E402

RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

from mock_agent import DoorRefusal, redact  # noqa: E402
from rt_core import HOST_ONLY_METHODS  # noqa: E402

HOST_NAME = "rigorloom-agenthost"
DEFAULT_MAX_TURNS = 8

#: How much of a streamed text delta an event carries. A chunk event exists so
#: a UI can render the answer as it arrives, so the text has to be in it; the
#: cap is here because a pathological adapter should not be able to make one
#: event unbounded.
MAX_CHUNK_EVENT_CHARS = 4096


def discover_session(door) -> str:
    """The session a host already opened. Never invents one.

    Module-level because the long-lived host needs it BEFORE it builds an
    ``AgentHost`` — it has to know which session directory to reattach to.
    """
    try:
        rows = door.call("session/list")["sessions"]
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
                 max_turns: int = DEFAULT_MAX_TURNS,
                 session=None, grant: ContextGrant | None = None,
                 stream_mode: str = "auto"):
        if stream_mode not in STREAM_MODES:
            raise AgentHostError("config_invalid",
                                 f"streamMode must be one of {list(STREAM_MODES)}",
                                 offered=stream_mode)
        self.door = door
        self.provider = provider
        self.events = events if events is not None else EventLog()
        self.max_turns = max_turns
        #: An ``ah_session.HostSession``, or None for the one-shot behaviour.
        self.session = session
        #: Operator-granted document context. Empty unless an operator acted.
        self.grant = grant if grant is not None else ContextGrant.empty()
        self.stream_mode = stream_mode

    # -- the transport decision ---------------------------------------------
    def _transport(self, profile) -> tuple[str, str | None]:
        """Which path this turn takes, and why it is not the other one.

        Never a guess: ``supports()`` is true only for a declared ``yes``, so
        ``no`` and ``unknown`` both land on ``complete`` with the state named.
        """
        if self.stream_mode == "off":
            return "complete", "streaming disabled by the operator"
        if not hasattr(self.provider, "stream"):
            return "complete", "the adapter has no stream()"
        state = profile.state("streaming")
        if state == "yes":
            return "stream", None
        return "complete", (f"the provider declares streaming {state!r}; an "
                            "unverified maybe is not permission to wait on a "
                            "stream that may never come")

    def _stream_turn(self, request, turn: int) -> tuple:
        """Run one streamed turn, emitting a chunk event for every piece."""
        def on_chunk(index: int, chunk: dict) -> None:
            detail = {"turn": turn, "index": index, "chunkType": chunk["type"]}
            if chunk["type"] == "text":
                text = chunk.get("text") or ""
                detail["text"] = text[:MAX_CHUNK_EVENT_CHARS]
                if len(text) > MAX_CHUNK_EVENT_CHARS:
                    detail["truncatedChars"] = len(text) - MAX_CHUNK_EVENT_CHARS
            elif chunk["type"] == "tool_call":
                raw = chunk.get("toolCall") or {}
                # The whole call, because by the time it is a chunk it IS
                # whole: the vocabulary has no partial shape.
                detail["toolCall"] = raw
            elif chunk.get("finishReason"):
                detail["finishReason"] = chunk["finishReason"]
            self.events.append("provider.stream.chunk", **detail)

        outcome = drain(self.provider, request, on_chunk=on_chunk)
        return outcome.response, outcome

    def run(self, instruction: str, session_id: str | None = None) -> dict:
        profile = self.provider.capabilities()
        self.events.append("run.started", instruction=instruction,
                           maxTurns=self.max_turns)
        self.events.append("provider.selected", provider=profile.public())

        session_id = session_id or self._discover_session()
        context: dict = {"sessionId": session_id, "surface": self.door.surface()}
        tools = tool_definitions()

        conversation: tuple = ()
        truncation = None
        if self.session is not None:
            conversation, truncation = self.session.conversation()
            if self.session.attached:
                self.events.append("session.attached",
                                   turns=self.session.turn_count,
                                   exchanges=len(conversation),
                                   unreadableLines=self.session.turns_skipped)
            if truncation is not None:
                # Loud, always. A dropped exchange the operator cannot see is
                # a model contradicting itself for invisible reasons.
                self.events.append("session.truncated", **truncation.public())

        # Operator-granted document context, fetched fresh from the Runtime.
        # It rides in ``context``, which both adapters already serialise, so
        # no adapter had to learn a new field to carry it.
        disclosure = None
        if not self.grant.is_empty():
            block, disclosure = materialize(self.door, session_id, self.grant)
            if block:
                context["documentContext"] = block
                self.events.append("context.included",
                                   grantId=self.grant.grant_id,
                                   grantedBy=self.grant.granted_by,
                                   **disclosure.public())
        context["readScope"] = self.grant.read_scope

        # Each entry carries the provider's own callId and arguments, not just
        # the tool name: a continuation that has to invent an id discards the
        # model's reference and only looks right because both halves are ours.
        history: list[dict] = []
        refusals: list[dict] = []
        turn_log: list[dict] = []
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
            transport, fallback_reason = self._transport(profile)
            request = ProviderRequest(instruction=instruction, context=context,
                                      tools=tools, history=list(history),
                                      conversation=conversation,
                                      stream=transport == "stream")
            self.events.append("provider.request", turn=turns,
                               historyLength=len(history),
                               conversationLength=len(conversation),
                               transport=transport)
            record = {"turn": turns, "transport": transport,
                      "fallbackReason": fallback_reason,
                      "historyLength": len(history),
                      "conversationLength": len(conversation)}
            try:
                if transport == "stream":
                    response, outcome = self._stream_turn(request, turns)
                    record["stream"] = outcome.public()
                else:
                    response = self.provider.complete(request)
            except ProviderError as exc:
                # The model side broke. Nothing about the document changed, and
                # nothing is invented in its place. A stream that died halfway
                # is a fault too: the partial text is NOT promoted to an answer.
                provider_fault = exc.as_dict()
                record["fault"] = exc.code
                turn_log.append(record)
                self.events.append("provider.failed", turn=turns, **exc.as_dict())
                break
            record["toolCalls"] = len(response.tool_calls)
            record["finishReason"] = response.finish_reason
            turn_log.append(record)
            self.events.append("provider.response", turn=turns,
                               transport=transport, **response.public())
            closing_text = response.text or closing_text
            finish_reason = response.finish_reason

            if not response.tool_calls:
                break

            for call in response.tool_calls:
                self.events.append("tool.requested", turn=turns, **call.public())
                try:
                    compiled = compile_tool_call(call, scope=self.grant)
                except AgentHostError as exc:
                    if exc.code == "grant_scope_exceeded":
                        self.events.append("context.refused", turn=turns,
                                           **exc.as_dict())
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
            # Which path each turn ACTUALLY took, and why it was not the other
            # one. A measurement, never inferred from the capability profile.
            "turnLog": turn_log,
            "transports": sorted({row["transport"] for row in turn_log}),
            "streamMode": self.stream_mode,
            "conversation": {"resent": len(conversation),
                             "truncation": (truncation.public() if truncation
                                            else None)},
            "grant": self.grant.public(),
            "contextDisclosed": disclosure.public() if disclosure else None,
            "events": self.events.public(),
        }
        if self.session is not None:
            payload["session"] = self._persist(payload, instruction,
                                               closing_text, finish_reason,
                                               turn_log, refusals, disclosure,
                                               ok)
        self.events.append("run.finished", ok=ok, turns=turns,
                           refusals=len(refusals))
        payload["events"] = self.events.public()
        return payload

    def _persist(self, payload, instruction, reply, finish_reason, turn_log,
                 refusals, disclosure, ok) -> dict:
        """Append this exchange to the session's turn log.

        WHAT GOES IN: the instruction, the model's reply, the transport per
        turn, the tools called and whether each survived, the plan's identity,
        and — when context was disclosed — the grant id with the addresses and
        hashes of what was sent.

        WHAT DOES NOT: any document text, and any tool RESULT. Reattach
        re-fetches granted context from the Runtime rather than replaying it,
        so the log has nothing to leak in the first place.
        """
        plan = payload.get("plan") or {}
        validation = payload.get("validation") or {}
        approval = payload.get("approval") or {}
        record = {
            "turn": self.session.next_turn_number(),
            "hostVersion": HOST_VERSION,
            "instruction": instruction,
            "reply": reply,
            "finishReason": finish_reason,
            "ok": ok,
            "providerId": payload["provider"]["providerId"],
            "model": payload["provider"].get("model"),
            "transports": [row["transport"] for row in turn_log],
            "providerTurns": len(turn_log),
            "refusals": [{"stage": row.get("stage"), "code": row.get("code")}
                         for row in refusals],
            "planId": plan.get("planId"),
            "opsHash": plan.get("opsHash"),
            "validationOk": validation.get("ok"),
            "approvalId": approval.get("approvalId"),
            "truncation": payload["conversation"]["truncation"],
            "grantId": (self.grant.grant_id if not self.grant.is_empty()
                        else None),
            "contextDisclosed": disclosure.public() if disclosure else None,
            "providerFault": (payload["providerFault"] or {}).get("code"),
        }
        stored = self.session.append_turn(record)
        self.events.append("session.turn", turn=stored["turn"],
                           totalTurns=self.session.turn_count)
        return self.session.public()

    # -- helpers ------------------------------------------------------------
    def _discover_session(self) -> str:
        return discover_session(self.door)

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
