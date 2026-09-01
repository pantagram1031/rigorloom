#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A deterministic provider: no network, no clock, no randomness.

This is what the Desktop agent panel embeds first, and what every Agent Host
test drives, so its decisions are a pure function of what it has already seen.
Given the tool results so far it emits the next tool call; given all of them it
stops. Two runs against byte-identical documents produce byte-identical tool
requests.

It cannot approve. Not because it declines to ask — the ``escalate`` scenario
asks on purpose — but because ``ah_compile`` refuses the request before the
Runtime is touched, and the Runtime's agent entrypoint would not have the
method anyway. The scenario exists so a test and a UI can watch that happen
rather than take it on faith.

Target selection is imported from ``runtime/scripts/mock_agent.py`` rather than
re-derived: one rule for "which seat", used by the runtime fixture and by the
model side alike, so the two can never drift into disagreeing about what the
obvious edit is.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import AgentHostError  # noqa: E402
from ah_provider import (  # noqa: E402
    CapabilityProfile,
    ProviderAdapter,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
    cap,
)

RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import mock_agent  # noqa: E402

PROVIDER_ID = "mock"
MODEL_ID = "mock-deterministic-1"
#: Fixed. Never a timestamp, never a counter that survives across runs.
MARKER = "AGENT-HOST-0001"

SCENARIOS = ("propose-one", "propose-invalid", "propose-then-wait", "escalate")

#: What the model "would have said", per scenario. Fixed strings, so streaming
#: chunks are deterministic too.
CLOSING_TEXT = {
    "propose-one": "Proposed one fill and requested approval. A human decides.",
    "propose-invalid": "The target I chose does not exist in this document; "
                       "validation refused it and I stopped.",
    "propose-then-wait": "Plan proposed and approval requested. Waiting on a "
                         "host; I cannot grant it myself.",
    "escalate": "I asked to apply the plan and was refused. Approval and apply "
                "are host actions.",
}


def _seen(history: list) -> list:
    return [entry.get("tool") for entry in history]


def _last_result(history: list, tool: str) -> dict | None:
    for entry in reversed(history):
        if entry.get("tool") == tool and entry.get("ok"):
            return entry.get("result")
    return None


class MockProvider(ProviderAdapter):
    """A scripted model. Same inputs, same tool calls, every time."""

    provider_id = PROVIDER_ID

    def __init__(self, scenario: str = SCENARIOS[0], marker: str = MARKER):
        if scenario not in SCENARIOS:
            raise AgentHostError("config_invalid",
                                 f"unknown mock scenario {scenario!r}",
                                 known=list(SCENARIOS))
        self.scenario = scenario
        self.marker = marker

    # -- contract -----------------------------------------------------------
    def capabilities(self) -> CapabilityProfile:
        return CapabilityProfile(
            provider_id=self.provider_id,
            model=MODEL_ID,
            auth_ownership="none",
            capabilities={
                "modelDiscovery": cap("yes", "a fixed, local list"),
                "text": cap("yes"),
                "structuredToolUse": cap("yes"),
                "structuredOutput": cap("yes"),
                "streaming": cap("yes", "chunks a fixed string; no network"),
                "resumableThread": cap(
                    "no", "each run is independent; nothing is persisted"),
            },
            notes={"deterministic": True, "network": "none",
                   "scenario": self.scenario},
        )

    def list_models(self) -> list:
        self.capabilities().require("modelDiscovery")
        return [{"id": MODEL_ID, "provider": self.provider_id}]

    # -- the state machine --------------------------------------------------
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        seen = _seen(request.history)
        session_id = request.context.get("sessionId")

        if "document_inspect" not in seen:
            return self._call("document_inspect",
                              {"sessionId": session_id, "include": ["regions"]},
                              "Looking at the document's editable regions.")

        if "plan_propose" not in seen:
            inspected = _last_result(request.history, "document_inspect") or {}
            regions = (inspected.get("regions") or {}).get("regions") or []
            if self.scenario == "propose-invalid":
                target = {"kind": "cell", **mock_agent.INVALID_ADDRESS}
            else:
                target = mock_agent.choose_target(regions)
            op = mock_agent.build_op(target, self.marker)
            return self._call("plan_propose",
                              {"sessionId": session_id, "backend": "preedit",
                               "ops": [op], "proposer": "agenthost-mock"},
                              f"Proposing one fill at "
                              f"({target['row']},{target['col']}).")

        plan = (_last_result(request.history, "plan_propose") or {}).get("plan")
        if plan is None:
            # The propose was refused. Nothing further is honest to attempt.
            return ProviderResponse(
                text="The plan was refused; I have nothing to validate.",
                finish_reason="stop")

        if "plan_validate" not in seen:
            return self._call("plan_validate", {"planId": plan["planId"]},
                              "Validating before asking anyone to approve it.")

        validation = (_last_result(request.history, "plan_validate")
                      or {}).get("validation") or {}

        if validation.get("ok") and "approval_request" not in seen:
            return self._call("approval_request",
                              {"planId": plan["planId"],
                               "requestedBy": "agenthost-mock"},
                              "Asking a host to approve it.")

        if self.scenario == "escalate" and "plan_apply" not in seen:
            # Deliberately over the line. The compile gate refuses this; the
            # point of the scenario is that a UI can show the refusal.
            return self._call("plan_apply",
                              {"planId": plan["planId"], "approvalId": "any"},
                              "Attempting to apply it myself.")

        return ProviderResponse(text=CLOSING_TEXT[self.scenario],
                                finish_reason="stop")

    @staticmethod
    def _call(name: str, arguments: dict, text: str) -> ProviderResponse:
        # A fixed call id: derived from the tool name, never a counter or uuid,
        # so two runs produce identical event logs.
        return ProviderResponse(
            text=text,
            tool_calls=(ToolCall(call_id=f"mock-{name}", name=name,
                                 arguments=arguments),),
            finish_reason="tool_calls")

    # -- streaming ----------------------------------------------------------
    def stream(self, request: ProviderRequest) -> Iterator[dict]:
        """Chunk the same answer. Deterministic split, no timing, no sleeps."""
        self.capabilities().require("streaming")
        response = self.complete(request)
        for word in (response.text or "").split(" "):
            if word:
                yield {"type": "text", "text": word + " "}
        for call in response.tool_calls:
            yield {"type": "tool_call", "toolCall": call.public()}
        yield {"type": "done", "finishReason": response.finish_reason}
