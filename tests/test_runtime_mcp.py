# -*- coding: utf-8 -*-
"""MCP class: JSON-RPC 2.0 over newline-delimited stdio, agent-safe surface only."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from _runtime_client import (
    CORPUS_FORM,
    McpClient,
    RuntimeClient,
    run_cli,
    runtime_scripts_on_path,
)

runtime_scripts_on_path()

import mcp_server  # noqa: E402
import rt_core  # noqa: E402

SPAWN_TIMEOUT = 120.0
CLEAN_OP = {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "한빛"}


@pytest.fixture()
def source(tmp_path):
    target = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, target)
    return target


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "root"


@pytest.fixture()
def opened(root, source):
    """A session a HOST opened; the MCP adapter can only ever read it."""
    return run_cli(root, "open", "--path", str(source)).result["sessionId"]


@pytest.fixture()
def mcp(root):
    with McpClient(root) as client:
        yield client


# --- surface ----------------------------------------------------------------

def test_the_tool_surface_is_derived_from_the_agent_registry():
    expected = {mcp_server.tool_name(m)
                for m in rt_core.AGENT_METHODS if m != "initialize"}
    assert set(mcp_server.TOOL_TO_METHOD) == expected


def test_no_host_method_is_reachable_as_a_tool():
    for method in rt_core.HOST_ONLY_METHODS:
        assert method not in mcp_server.TOOL_SCHEMAS
        assert mcp_server.tool_name(method) not in mcp_server.TOOL_TO_METHOD


def test_every_exposed_method_has_a_schema_and_no_schema_is_orphaned():
    assert set(mcp_server.TOOL_SCHEMAS) == set(mcp_server.EXPOSED_METHODS)
    for method, spec in mcp_server.TOOL_SCHEMAS.items():
        assert spec["description"].strip(), method
        assert spec["inputSchema"]["type"] == "object", method


def test_list_tools_names_what_is_not_exposed(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(mcp_server.__file__), "--root", str(tmp_path),
         "--list-tools"],
        capture_output=True, timeout=SPAWN_TIMEOUT)
    assert completed.returncode == 0
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert set(payload["notExposed"]) == set(rt_core.HOST_ONLY_METHODS) | {"initialize"}


def test_root_is_required(tmp_path):
    completed = subprocess.run([sys.executable, str(mcp_server.__file__)],
                               capture_output=True, timeout=SPAWN_TIMEOUT)
    assert completed.returncode == 2
    assert b"--root" in completed.stderr


# --- protocol ---------------------------------------------------------------

def test_initialize_negotiates_a_supported_revision(mcp):
    response = mcp.initialize("2025-06-18")
    result = response["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "rigorloom-runtime"
    assert result["capabilities"]["tools"] == {"listChanged": False}


def test_an_unknown_revision_falls_back_to_our_preferred(mcp):
    result = mcp.initialize("1999-01-01")["result"]
    assert result["protocolVersion"] == mcp_server.PREFERRED_MCP_VERSION


def test_calls_before_initialize_are_refused(mcp):
    response = mcp.request("tools/list")
    assert response["error"]["code"] == mcp_server.INVALID_REQUEST
    mcp.initialize()
    assert mcp.tools()


def test_notifications_get_no_response(mcp):
    mcp.initialize()
    # initialize() already sent notifications/initialized; the next reply must
    # belong to the request after it, not to the notification.
    assert mcp.request("ping")["result"] == {}


def test_tools_list_matches_the_derived_surface(mcp):
    mcp.initialize()
    names = {tool["name"] for tool in mcp.tools()}
    assert names == set(mcp_server.TOOL_TO_METHOD)
    assert "plan_apply" not in names and "approval_resolve" not in names
    assert "workspace_openPath" not in names


def test_an_unsupported_mcp_method_is_method_not_found(mcp):
    mcp.initialize()
    response = mcp.request("resources/list")
    assert response["error"]["code"] == mcp_server.METHOD_NOT_FOUND


def test_malformed_json_is_a_parse_error_and_the_adapter_survives(mcp):
    mcp.initialize()
    mcp.write_raw(b"{not json\n")
    response = mcp.recv()
    assert response["error"]["code"] == mcp_server.PARSE_ERROR
    assert mcp.request("ping")["result"] == {}


def test_duplicate_members_are_refused_on_the_wire(mcp):
    mcp.initialize()
    mcp.write_raw(b'{"jsonrpc":"2.0","id":9,"method":"ping","method":"ping"}\n')
    assert mcp.recv()["error"]["code"] == mcp_server.PARSE_ERROR


def test_every_response_is_one_line_of_json(mcp):
    """MCP stdio framing is newline-delimited; no message may contain a newline."""
    mcp.initialize()
    mcp.tools()
    for line in mcp.stdout_lines():
        assert line.endswith(b"\n")
        assert b"\n" not in line[:-1]
        json.loads(line.decode("utf-8"))


# --- tools ------------------------------------------------------------------

def test_a_tool_call_reaches_the_shared_session_store(mcp, opened):
    mcp.initialize()
    sessions = mcp.ok("session_list")["sessions"]
    assert opened in [row["sessionId"] for row in sessions]


def test_inspect_and_propose_and_validate_work_as_tools(mcp, opened):
    mcp.initialize()
    inspected = mcp.ok("document_inspect", {"sessionId": opened,
                                            "include": ["regions"]})
    assert len(inspected["regions"]["regions"]) == 9
    plan = mcp.ok("plan_propose", {"sessionId": opened, "backend": "preedit",
                                   "ops": [CLEAN_OP]})["plan"]
    assert plan["proposer"] == "mcp-client"
    validation = mcp.ok("plan_validate", {"planId": plan["planId"]})["validation"]
    assert validation["ok"] is True


def test_approval_request_is_available_but_resolution_is_not(mcp, opened):
    mcp.initialize()
    plan = mcp.ok("plan_propose", {"sessionId": opened, "backend": "preedit",
                                   "ops": [CLEAN_OP]})["plan"]
    approval = mcp.ok("approval_request", {"planId": plan["planId"]})["approval"]
    assert approval["state"] == "pending"
    for tool in ("approval_resolve", "plan_apply", "workspace_openPath"):
        error = mcp.err(tool, {"planId": plan["planId"]})
        assert error["code"] == "unknown_method"
        assert error["data"]["knownOnHostEntry"] is True


def test_a_domain_refusal_comes_back_as_a_tool_error_with_its_payload(mcp, opened):
    """isError, not a JSON-RPC error — and the engine's payload survives."""
    mcp.initialize()
    error = mcp.err("plan_propose", {
        "sessionId": opened, "backend": "preedit",
        "ops": [{"kind": "insert_equation", "latex": "E=mc^2"}]})
    assert error["code"] == "unsupported_backend"
    assert error["data"]["servedBy"] == "xml or com"


def test_the_t30_refusal_payload_survives_the_tool_envelope(mcp, opened):
    mcp.initialize()
    plan = mcp.ok("plan_propose", {
        "sessionId": opened, "backend": "preedit",
        "ops": [{"kind": "fill_cell", "table": 0, "row": 2, "col": 0,
                 "text": "X"}]})["plan"]
    validation = mcp.ok("plan_validate", {"planId": plan["planId"]})["validation"]
    row = next(r for r in validation["hard"]
               if r["code"] == "fill_charpr_script_anomaly")
    assert row["preeditFlag"] == ["--charpr-per-cell", "2,0=23"]


def test_an_unknown_tool_is_a_tool_error_naming_the_surface(mcp):
    mcp.initialize()
    error = mcp.err("delete_everything")
    assert error["code"] == "unknown_method"
    assert "plan_propose" in error["data"]["known"]


def test_a_bad_session_id_refuses_rather_than_crashing(mcp):
    mcp.initialize()
    assert mcp.err("document_inspect", {"sessionId": "nope"})["code"] == \
        "unknown_session"


def test_the_adapter_cannot_be_talked_into_opening_a_document(mcp, source):
    mcp.initialize()
    for tool in ("workspace_openPath", "workspace_open_path", "open"):
        assert mcp.err(tool, {"path": str(source)})["code"] == "unknown_method"


def test_eof_shuts_the_adapter_down_cleanly(root):
    client = McpClient(root)
    client.initialize()
    client.close()
    assert client.proc.returncode == 0


def test_the_host_runtime_still_has_what_mcp_does_not(root, source):
    """The same build, reached the other way, does expose the host methods."""
    with RuntimeClient(root, entry="host") as host:
        host.initialize()
        session = host.ok("workspace/openPath", {"path": str(source)})["sessionId"]
        assert session
