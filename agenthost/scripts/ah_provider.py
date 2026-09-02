#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The provider-adapter contract and its explicit CapabilityProfile.

A consumer must be able to ask "can this provider stream?" and get a TRUTHFUL
answer — which means three states, not two. ``yes`` is a promise the adapter
will keep; ``no`` is a promise it will refuse; ``unknown`` is an admission, and
``supports()`` treats it as no because acting on an unverified maybe is how a
UI ends up waiting forever for a stream that was never coming.

Nothing here is assumed from a provider's name or its base URL. Every value is
declared by the adapter, or overridden in config, or probed — and the profile
records WHICH, so a reader can tell a vendor's marketing from a measurement.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import (  # noqa: E402
    AUTH_OWNERSHIP,
    CAPABILITY_NAMES,
    CAPABILITY_STATES,
    DECLARED_BY,
    AgentHostError,
    ProviderError,
)


@dataclass(frozen=True)
class Capability:
    """One capability: a state, why, and who said so."""

    state: str = "unknown"
    reason: str | None = None
    declared_by: str = "adapter"

    def __post_init__(self) -> None:
        if self.state not in CAPABILITY_STATES:
            raise AgentHostError("config_invalid",
                                 f"capability state must be one of "
                                 f"{list(CAPABILITY_STATES)}", offered=self.state)
        if self.declared_by not in DECLARED_BY:
            raise AgentHostError("config_invalid",
                                 f"declaredBy must be one of {list(DECLARED_BY)}",
                                 offered=self.declared_by)

    @property
    def yes(self) -> bool:
        return self.state == "yes"

    def public(self) -> dict:
        return {"state": self.state, "reason": self.reason,
                "declaredBy": self.declared_by}


def cap(state: str, reason: str | None = None,
        declared_by: str = "adapter") -> Capability:
    return Capability(state=state, reason=reason, declared_by=declared_by)


@dataclass(frozen=True)
class CapabilityProfile:
    """What an adapter can actually do, per capability, with provenance."""

    provider_id: str
    auth_ownership: str
    capabilities: dict = field(default_factory=dict)
    model: str | None = None
    notes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.auth_ownership not in AUTH_OWNERSHIP:
            raise AgentHostError("config_invalid",
                                 f"authOwnership must be one of "
                                 f"{list(AUTH_OWNERSHIP)}",
                                 offered=self.auth_ownership)
        missing = [name for name in CAPABILITY_NAMES
                   if name not in self.capabilities]
        if missing:
            # Absence is not "no" — an adapter that forgets a capability must
            # say ``unknown`` on purpose, not be read as declining by accident.
            raise AgentHostError(
                "config_invalid",
                "a profile must name every capability, even as unknown",
                missing=missing, known=list(CAPABILITY_NAMES))
        extra = [name for name in self.capabilities if name not in CAPABILITY_NAMES]
        if extra:
            raise AgentHostError("config_invalid",
                                 "profile declares capabilities nobody defined",
                                 unknown=extra, known=list(CAPABILITY_NAMES))

    def supports(self, name: str) -> bool:
        """True only for a declared ``yes``. ``unknown`` is never a yes."""
        if name not in CAPABILITY_NAMES:
            raise AgentHostError("config_invalid", f"no such capability {name!r}",
                                 known=list(CAPABILITY_NAMES))
        return self.capabilities[name].yes

    def state(self, name: str) -> str:
        if name not in CAPABILITY_NAMES:
            raise AgentHostError("config_invalid", f"no such capability {name!r}",
                                 known=list(CAPABILITY_NAMES))
        return self.capabilities[name].state

    def require(self, name: str) -> None:
        """Refuse loudly rather than attempt a capability we were not promised."""
        if not self.supports(name):
            entry = self.capabilities[name]
            raise ProviderError(
                "provider_capability_unavailable",
                f"{self.provider_id} does not offer {name} "
                f"(state {entry.state!r})",
                provider=self.provider_id, capability=name, state=entry.state,
                reason=entry.reason)

    def with_overrides(self, overrides: dict | None) -> "CapabilityProfile":
        """Apply config-declared overrides, stamped ``declaredBy: config``.

        A router operator who knows their gateway strips SSE must be able to
        say so, and the profile must then remember that the answer came from
        config rather than from the adapter.
        """
        if not overrides:
            return self
        merged = dict(self.capabilities)
        for name, value in overrides.items():
            if name not in CAPABILITY_NAMES:
                raise AgentHostError("config_invalid",
                                     f"capability override names {name!r}, which "
                                     "is not a capability",
                                     known=list(CAPABILITY_NAMES))
            if isinstance(value, str):
                merged[name] = cap(value, "declared in adapter config", "config")
            elif isinstance(value, dict):
                merged[name] = cap(value.get("state", "unknown"),
                                   value.get("reason",
                                             "declared in adapter config"),
                                   "config")
            else:
                raise AgentHostError(
                    "config_invalid",
                    f"capability override for {name!r} must be a state string or "
                    "an object", offered=repr(value))
        return CapabilityProfile(provider_id=self.provider_id,
                                 auth_ownership=self.auth_ownership,
                                 capabilities=merged, model=self.model,
                                 notes=dict(self.notes))

    def public(self) -> dict:
        return {
            "providerId": self.provider_id,
            "model": self.model,
            "authOwnership": self.auth_ownership,
            "capabilities": {name: self.capabilities[name].public()
                             for name in CAPABILITY_NAMES},
            "notes": dict(self.notes),
        }


@dataclass(frozen=True)
class ToolCall:
    """One tool the model asked for. Names are provider-side, never trusted."""

    call_id: str
    name: str
    arguments: dict

    def public(self) -> dict:
        return {"callId": self.call_id, "name": self.name,
                "arguments": self.arguments}


@dataclass(frozen=True)
class ProviderRequest:
    """One turn's worth of input to a provider.

    ``history`` is THIS turn-loop's tool traffic. ``conversation`` is what came
    before it — earlier exchanges in the same persistent host session, oldest
    first, each ``{"instruction": str, "reply": str | None}``. They are
    separate fields because they are separate things (a tool result belongs to
    the assistant turn that asked for it; an earlier exchange does not), and
    because the default is empty: an adapter that has not learned the new
    field still behaves honestly rather than silently dropping memory it was
    supposed to carry.
    """

    instruction: str
    context: dict
    tools: list
    history: list = field(default_factory=list)
    thread_id: str | None = None
    stream: bool = False
    conversation: tuple = ()


@dataclass(frozen=True)
class ProviderResponse:
    text: str | None = None
    tool_calls: tuple = ()
    finish_reason: str = "stop"
    raw: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {"text": self.text,
                "toolCalls": [call.public() for call in self.tool_calls],
                "finishReason": self.finish_reason}


class ProviderAdapter:
    """What every provider must offer. Subclasses declare, they do not assume."""

    provider_id = "abstract"

    def capabilities(self) -> CapabilityProfile:  # pragma: no cover - interface
        raise NotImplementedError

    def complete(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover
        raise NotImplementedError

    def stream(self, request: ProviderRequest) -> Iterator[dict]:
        """Default: refuse. An adapter that streams overrides this AND says yes."""
        self.capabilities().require("streaming")
        raise NotImplementedError(  # pragma: no cover - unreachable when honest
            f"{self.provider_id} declares streaming but did not implement it")

    def list_models(self) -> list:
        self.capabilities().require("modelDiscovery")
        raise NotImplementedError(  # pragma: no cover - unreachable when honest
            f"{self.provider_id} declares modelDiscovery but did not implement it")
