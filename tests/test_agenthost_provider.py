# -*- coding: utf-8 -*-
"""The provider contract: three states, declared provenance, no assumptions."""
from __future__ import annotations

import pytest

from _agenthost_support import agenthost_scripts_on_path

agenthost_scripts_on_path()

import ah_codes  # noqa: E402
import ah_events  # noqa: E402
import ah_provider  # noqa: E402
from ah_mock import MockProvider  # noqa: E402


def _full(**overrides):
    caps = {name: ah_provider.cap("unknown")
            for name in ah_codes.CAPABILITY_NAMES}
    caps.update(overrides)
    return caps


# --- capability semantics ---------------------------------------------------

def test_a_capability_has_three_states_and_unknown_is_not_yes():
    profile = ah_provider.CapabilityProfile(
        provider_id="p", auth_ownership="none",
        capabilities=_full(streaming=ah_provider.cap("unknown", "not probed")))
    assert profile.state("streaming") == "unknown"
    assert profile.supports("streaming") is False


def test_a_declared_no_is_a_promise_to_refuse():
    profile = ah_provider.CapabilityProfile(
        provider_id="p", auth_ownership="none",
        capabilities=_full(streaming=ah_provider.cap("no", "gateway strips SSE")))
    with pytest.raises(ah_codes.ProviderError) as excinfo:
        profile.require("streaming")
    assert excinfo.value.code == "provider_capability_unavailable"
    assert excinfo.value.data["state"] == "no"
    assert excinfo.value.data["reason"] == "gateway strips SSE"


def test_require_also_refuses_an_unknown():
    """An unverified maybe is not permission to try and hang."""
    profile = ah_provider.CapabilityProfile(
        provider_id="p", auth_ownership="none", capabilities=_full())
    with pytest.raises(ah_codes.ProviderError):
        profile.require("structuredToolUse")


def test_a_profile_must_name_every_capability_even_as_unknown():
    partial = {name: ah_provider.cap("yes")
               for name in ah_codes.CAPABILITY_NAMES[:-1]}
    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        ah_provider.CapabilityProfile(provider_id="p", auth_ownership="none",
                                      capabilities=partial)
    assert excinfo.value.code == "config_invalid"
    assert excinfo.value.data["missing"] == [ah_codes.CAPABILITY_NAMES[-1]]


def test_a_profile_cannot_invent_a_capability():
    caps = _full()
    caps["telepathy"] = ah_provider.cap("yes")
    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        ah_provider.CapabilityProfile(provider_id="p", auth_ownership="none",
                                      capabilities=caps)
    assert excinfo.value.data["unknown"] == ["telepathy"]


def test_an_unknown_auth_ownership_is_refused():
    with pytest.raises(ah_codes.AgentHostError):
        ah_provider.CapabilityProfile(provider_id="p", auth_ownership="vibes",
                                      capabilities=_full())


def test_asking_about_a_capability_nobody_defined_is_an_error():
    profile = ah_provider.CapabilityProfile(provider_id="p",
                                            auth_ownership="none",
                                            capabilities=_full())
    with pytest.raises(ah_codes.AgentHostError):
        profile.supports("telepathy")


# --- overrides carry provenance --------------------------------------------

def test_a_config_override_wins_and_is_stamped_as_config():
    profile = ah_provider.CapabilityProfile(
        provider_id="p", auth_ownership="none",
        capabilities=_full(streaming=ah_provider.cap("unknown")))
    overridden = profile.with_overrides({"streaming": "no"})
    assert overridden.state("streaming") == "no"
    entry = overridden.public()["capabilities"]["streaming"]
    assert entry["declaredBy"] == "config"
    # the original is untouched — profiles are values, not mutable state
    assert profile.state("streaming") == "unknown"


def test_an_override_may_carry_its_own_reason():
    profile = ah_provider.CapabilityProfile(
        provider_id="p", auth_ownership="none", capabilities=_full())
    overridden = profile.with_overrides(
        {"structuredToolUse": {"state": "yes", "reason": "measured on staging"}})
    entry = overridden.public()["capabilities"]["structuredToolUse"]
    assert entry["state"] == "yes" and entry["reason"] == "measured on staging"


def test_an_override_for_a_nonexistent_capability_is_refused():
    profile = ah_provider.CapabilityProfile(
        provider_id="p", auth_ownership="none", capabilities=_full())
    with pytest.raises(ah_codes.AgentHostError):
        profile.with_overrides({"telepathy": "yes"})


def test_an_override_of_the_wrong_shape_is_refused():
    profile = ah_provider.CapabilityProfile(
        provider_id="p", auth_ownership="none", capabilities=_full())
    with pytest.raises(ah_codes.AgentHostError):
        profile.with_overrides({"streaming": True})


# --- the base adapter refuses rather than pretends --------------------------

def test_the_base_adapter_will_not_stream_without_declaring_it():
    class Silent(ah_provider.ProviderAdapter):
        provider_id = "silent"

        def capabilities(self):
            return ah_provider.CapabilityProfile(
                provider_id="silent", auth_ownership="none",
                capabilities=_full())

    with pytest.raises(ah_codes.ProviderError):
        list(Silent().stream(ah_provider.ProviderRequest("i", {}, [])))


def test_the_mock_declares_a_complete_and_honest_profile():
    profile = MockProvider().capabilities()
    public = profile.public()
    assert set(public["capabilities"]) == set(ah_codes.CAPABILITY_NAMES)
    assert profile.supports("streaming") is True
    assert profile.state("resumableThread") == "no"
    assert public["authOwnership"] == "none"
    assert public["notes"]["network"] == "none"


# --- error worlds stay apart ------------------------------------------------

def test_provider_and_host_code_sets_do_not_overlap():
    assert ah_codes.PROVIDER_CODES & ah_codes.HOST_CODES == frozenset()
    assert ah_codes.AGENTHOST_CODES == (ah_codes.PROVIDER_CODES
                                        | ah_codes.HOST_CODES)


def test_a_provider_error_cannot_carry_a_host_code():
    with pytest.raises(AssertionError):
        ah_codes.ProviderError("tool_forbidden", "wrong world")


def test_an_agenthost_error_is_not_a_runtime_rpc_error():
    """A provider outage must never be catchable as a document refusal."""
    from rt_codes import RpcError

    error = ah_codes.AgentHostError("config_invalid", "x")
    assert not isinstance(error, RpcError)
    assert not issubclass(ah_codes.AgentHostError, RpcError)
    assert set(ah_codes.AGENTHOST_CODES).isdisjoint(
        __import__("rt_codes").ERROR_CODES)


# --- events -----------------------------------------------------------------

def test_secret_shaped_headers_are_redacted_in_every_casing():
    redacted = ah_events.redact_headers({
        "Authorization": "Bearer PLACEHOLDER-FAKE-CREDENTIAL",
        "X-Api-Key": "PLACEHOLDER-FAKE-CREDENTIAL",
        "content-type": "application/json"})
    assert redacted["Authorization"] == ah_events.REDACTED
    assert redacted["X-Api-Key"] == ah_events.REDACTED
    assert redacted["content-type"] == "application/json"


def test_events_are_ordered_and_carry_no_clock(tmp_path):
    log = ah_events.EventLog(tmp_path / "events.jsonl")
    log.append("run.started", instruction="x")
    log.append("host.note", note="y")
    events = log.events()
    assert [event["seq"] for event in events] == [0, 1]
    for event in events:
        assert set(event) <= {"seq", "kind", "detail"}
    assert (tmp_path / "events.jsonl").read_text(
        encoding="utf-8").count("\n") == 2


def test_an_undeclared_event_kind_is_refused(tmp_path):
    log = ah_events.EventLog()
    with pytest.raises(ValueError):
        log.append("something.invented")
