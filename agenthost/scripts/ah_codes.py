#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The Agent Host's closed vocabularies, kept apart from the Runtime's.

TWO FAILURE WORLDS, AND THEY MUST NOT MERGE. The Runtime refuses things about
documents: a stale plan, an anomalous seat, a candidate whose bytes moved. The
Agent Host refuses things about providers: a dead endpoint, a malformed
completion, a credential that is not configured. A provider failure is never a
verdict about a document, and a document refusal is never a reason to retry a
provider. So the two vocabularies are separate sets in separate modules, and
``AgentHostError`` is not ``RpcError``.

Exit codes follow the repository's, plus the CLI's fourth
(pipeline/scripts/checker_base.py:13-16, runtime/scripts/cli.py):
0 ok, 2 usage, 3 refusal, 4 internal.
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3
EXIT_INTERNAL = 4

#: Bumped when the host's observable behaviour changes, not its docstrings.
HOST_VERSION = "0.1.0"

EVENT_SCHEMA = "rigorloom/agenthost-events/v0"
RUN_SCHEMA = "rigorloom/agenthost-run/v0"

# --- capability vocabulary --------------------------------------------------

#: Three states, never two. A provider that has not told us whether it streams
#: is ``unknown``, and ``unknown`` is not ``yes``. Same posture as
#: ``render_probe``'s ``"yes"|"no"|"unknown"`` (pipeline/scripts/render_probe.py:22).
CAPABILITY_STATES = ("yes", "no", "unknown")

#: Every capability a consumer may ask about. Adding one here without adding it
#: to ``CapabilityProfile`` is a loud failure, not a silent absence.
CAPABILITY_NAMES = (
    "modelDiscovery",
    "text",
    "structuredToolUse",
    "structuredOutput",
    "streaming",
    "resumableThread",
)

#: Who holds the secret, and in what form. The host never holds a secret in
#: config and never writes one to an event.
AUTH_OWNERSHIP = (
    "none",              # the adapter needs no credential at all (the mock)
    "env_reference",     # config names an environment variable; the value is read at call time
    "os_store_reference",  # config names an OS credential-store key
    "provider_managed",  # the endpoint authenticates by other means (mTLS, a proxy)
)

#: Where a capability value came from. A consumer that cares can tell a
#: declared answer from a probed one.
DECLARED_BY = ("adapter", "config", "probe")

# --- error codes ------------------------------------------------------------

#: The provider boundary failed. None of these say anything about a document.
PROVIDER_CODES = frozenset({
    "provider_unreachable",
    "provider_timeout",
    "provider_http_error",
    "provider_unauthorized",
    "provider_malformed_response",
    "provider_response_too_large",
    "provider_empty_response",
    "provider_capability_unavailable",
    "credential_unavailable",
    "credential_source_unsupported",
})

#: The host itself refused: a bad config, a forbidden tool, a runaway loop.
HOST_CODES = frozenset({
    "config_invalid",
    "unknown_provider",
    "tool_unknown",
    "tool_forbidden",
    "tool_arguments_invalid",
    "turn_budget_exhausted",
    "scenario_expectation_failed",
    "runtime_unavailable",
    "host_internal_error",
})

AGENTHOST_CODES = PROVIDER_CODES | HOST_CODES


class AgentHostError(Exception):
    """A host-side refusal. Deliberately NOT ``rt_codes.RpcError``.

    Keeping the types apart is what stops a provider outage from being reported
    as a document verdict. ``ProviderError`` narrows it further, so a caller can
    write ``except ProviderError`` and mean exactly "the model side broke".
    """

    def __init__(self, code: str, message: str, **data):
        assert code in AGENTHOST_CODES, f"undeclared agent-host code: {code!r}"
        self.code = code
        self.message = message
        self.data = dict(data)
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.data:
            out["data"] = self.data
        return out


class ProviderError(AgentHostError):
    """The provider boundary failed. Never a document verdict, never an answer.

    A caller must not paper over one of these with a guess at what the model
    would have said. The host records it, stops the turn, and reports it as a
    provider fault with the provider named.
    """

    def __init__(self, code: str, message: str, **data):
        assert code in PROVIDER_CODES, f"not a provider code: {code!r}"
        super().__init__(code, message, **data)
