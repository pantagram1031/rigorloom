# -*- coding: utf-8 -*-
"""Authority class: the agent entry does not BUILD the host methods.

Absence, not a permission check (orchestrator decision D8). The mutation test
at the bottom is the point of the file: if someone later merges the two
registries and puts a permission check in front instead, the spoof tests here
would keep passing while the property they exist for is gone — so one test
mutates the registry construction itself and asserts the suite notices.
"""
from __future__ import annotations

import pytest

from _runtime_client import CORPUS_FORM, RuntimeClient, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_server  # noqa: E402

HOST_ONLY = ("workspace/openPath", "approval/resolve", "plan/apply")


@pytest.fixture()
def agent(tmp_path):
    with RuntimeClient(tmp_path / "root", entry="agent") as handle:
        yield handle


@pytest.fixture()
def host(tmp_path):
    with RuntimeClient(tmp_path / "hostroot", entry="host") as handle:
        yield handle


# --- the registries themselves ---------------------------------------------

def test_the_agent_registry_does_not_contain_the_host_methods(tmp_path):
    server = rt_server.RuntimeServer(entry="agent", root=tmp_path)
    for method in HOST_ONLY:
        assert method not in server._methods
    assert sorted(server._host_only_methods()) == sorted(HOST_ONLY)


def test_the_host_registry_is_the_agent_registry_plus_the_host_methods(tmp_path):
    agent_server = rt_server.RuntimeServer(entry="agent", root=tmp_path / "a")
    host_server = rt_server.RuntimeServer(entry="host", root=tmp_path / "h")
    assert set(agent_server._methods) < set(host_server._methods)
    assert set(host_server._methods) - set(agent_server._methods) == set(HOST_ONLY)


def test_an_unknown_entry_is_refused(tmp_path):
    with pytest.raises(ValueError):
        rt_server.RuntimeServer(entry="superuser", root=tmp_path)


# --- over the wire ----------------------------------------------------------

@pytest.mark.parametrize("method", HOST_ONLY)
def test_host_methods_are_absent_on_an_agent_connection(agent, method):
    agent.initialize()
    error = agent.err(method, {})
    assert error["code"] == "unknown_method"
    assert error["data"]["entry"] == "agent"
    # the diagnostic the design doc asked for: absent here, present on host
    assert error["data"]["knownOnHostEntry"] is True
    assert method not in error["data"]["known"]


def test_capabilities_do_not_advertise_host_methods_to_an_agent(agent):
    result = agent.initialize()["result"]
    for method in HOST_ONLY:
        assert method not in result["capabilities"]["methods"]
    assert result["entry"] == "agent"


def test_a_client_role_field_cannot_promote_an_agent(agent):
    """A spoofed role is an unknown field, and it changes nothing either way."""
    agent.initialize()
    error = agent.err("plan/apply", {"planId": "x", "approvalId": "y",
                                     "client_role": "host"})
    assert error["code"] == "unknown_method"


def test_a_client_role_frame_member_cannot_promote_an_agent(agent):
    agent.initialize()
    agent.send_frame({"kind": "request", "id": "spoof", "method": "plan/apply",
                      "client_role": "host",
                      "params": {"planId": "x", "approvalId": "y"}})
    error = agent.recv()["error"]
    assert error["code"] == "unknown_field"
    assert error["data"]["unknown"] == ["client_role"]


def test_a_client_role_declared_at_initialize_is_refused(agent):
    frame = agent.call("initialize", {"protocolVersion": "0",
                                      "client_role": "host"})
    assert frame["error"]["code"] == "unknown_field"


def test_the_ignore_policy_still_cannot_promote_an_agent(agent):
    """Under 'ignore' the spoof field is dropped; the method is still absent."""
    agent.initialize(policy="ignore")
    error = agent.err("workspace/openPath", {"path": str(CORPUS_FORM),
                                             "client_role": "host"})
    assert error["code"] == "unknown_method"


def test_the_agent_surface_is_the_one_the_decision_named(agent):
    result = agent.initialize()["result"]
    methods = set(result["capabilities"]["methods"])
    assert {"plan/propose", "plan/validate", "approval/request", "plan/get",
            "approval/get", "candidate/list", "receipt/read",
            "document/inspect", "document/readRegion"} <= methods


def test_the_host_entry_can_reach_its_own_methods(host):
    host.initialize()
    assert host.ok("workspace/openPath", {"path": str(CORPUS_FORM)})["sessionId"]


# --- mutation ---------------------------------------------------------------

def test_mutating_the_registry_split_is_caught(tmp_path, monkeypatch):
    """Restore-from-saved, never git checkout.

    Replace ``_build_registry`` with the merged version a future refactor might
    write (one table for both entries, authority checked later) and assert the
    agent entry then exposes a host method — i.e. the property above is really
    load-bearing and not incidentally true.
    """
    original = rt_server.RuntimeServer._build_registry
    try:
        def merged(self):
            methods = self._agent_methods()
            methods.update(self._host_only_methods())
            return methods

        monkeypatch.setattr(rt_server.RuntimeServer, "_build_registry", merged)
        mutated = rt_server.RuntimeServer(entry="agent", root=tmp_path / "m")
        assert "plan/apply" in mutated._methods, (
            "the mutation did not take; this test proves nothing")
    finally:
        monkeypatch.undo()
    restored = rt_server.RuntimeServer(entry="agent", root=tmp_path / "r")
    assert "plan/apply" not in restored._methods
    assert rt_server.RuntimeServer._build_registry is original
