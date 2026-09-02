# -*- coding: utf-8 -*-
"""Runtime GAP 20, §15.8's first gap: a workspace member can be READ.

The write half (§15.6, ``test_runtime_workspace_ops.py``) needs an exact
anchor to aim ``ws_replace_text`` at, and there was no agent-safe way to get
one: ``workspace/inspect`` says which declared parts are present, never what
they say. ``workspace/readMember`` and ``workspace/listMembers`` close that —
the same shape ``document/readRegion`` already has, one level up (a workspace
member instead of a table cell or a paragraph).

THAT A READ IS BOUNDED THE SAME WAY A WRITE REFUSES. ``workspace/readMember``
reuses the exact codes ``rt_wsops`` already refuses a write op with —
``member_too_large``, ``member_not_text``, ``member_missing``,
``path_not_relative`` — so a caller learns one rule for "can this path be
touched" rather than two.

THAT NEITHER METHOD EVER TOUCHES THE OPERATOR'S DIRECTORY. Both read the
session's own copy, or a published candidate when ``runId`` is given — never
the path a host handed to ``workspace/openDirectory``.

THAT THE SURFACE STILL DERIVES. Adding two agent-safe methods to
``rt_core.AGENT_METHODS`` is the only edit; the MCP tool table, the compile
gate, and the JSONL handler-map assertion all pick it up, or import-time and
construction-time assertions already elsewhere in this codebase would fail
first.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from _runtime_client import runtime_scripts_on_path
import _workspace_fixture as fixture

runtime_scripts_on_path()

import mcp_server  # noqa: E402
import rt_codes  # noqa: E402
import rt_core  # noqa: E402
import rt_wsops  # noqa: E402
from rt_codes import RpcError  # noqa: E402

#: The modules the assembled fixture's checkers want; a TEST may know a
#: module's name, core may not (modules/README.md rule 1).
WORKSPACE_MODULES = ("report", "style")


def write_enabled(path: Path, names) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("schema: rigorloom-enabled-modules/v1\n"
                    "enabled: [%s]\n" % ", ".join(names), encoding="utf-8")
    return path


# --- fixtures -----------------------------------------------------------------

@pytest.fixture(scope="session")
def assembled(tmp_path_factory):
    """One assembled workspace for the whole file; see _workspace_fixture."""
    home = tmp_path_factory.mktemp("wsreadfixture")
    enabled = write_enabled(home / "enablement" / "enabled.yaml",
                            list(WORKSPACE_MODULES))
    target = home / "workspaces" / "report-e4readfixture"
    return fixture.scaffold(target,
                            modules_root=fixture.REPO_ROOT / "modules",
                            enabled_file=enabled)


@pytest.fixture()
def workspace(tmp_path, assembled):
    """A private copy, so a test that mutates the operator's dir is isolated."""
    target = tmp_path / "ws" / assembled.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(assembled, target)
    return target


@pytest.fixture()
def tiny(tmp_path):
    """A small workspace, for the refusals a real fixture is the wrong size for."""
    root = tmp_path / "ws" / "report-tiny"
    (root / "bundle").mkdir(parents=True)
    # newline="" so the bytes on disk are exactly what is written here (no
    # LF->CRLF translation): the anchor tests below need the "old" string to
    # occur byte-for-byte, and a write op reads raw bytes, never translated.
    (root / "bundle" / "content.md").write_text(
        "측정은 세 번 반복하였다.\n", encoding="utf-8", newline="")
    return root


@pytest.fixture()
def opened(tmp_path):
    def _open(path):
        core = rt_core.RuntimeCore(tmp_path / "root")
        session_id = core.open_workspace(str(path))["sessionId"]
        return core, session_id
    return _open


# --- the derived surface --------------------------------------------------------

def test_the_new_methods_reach_their_surfaces_without_editing_a_gate():
    """The registries derive; this only states what they then enforce.

    ``rt_server`` asserts its handler map equals the roster at construction
    (a mismatch there is a crash, not a silent gap), and ``mcp_server``
    asserts its tool table equals the agent roster at import.
    """
    assert "workspace/readMember" in rt_core.AGENT_METHODS
    assert "workspace/listMembers" in rt_core.AGENT_METHODS
    assert "workspace/readMember" not in rt_core.HOST_ONLY_METHODS
    assert "workspace/listMembers" not in rt_core.HOST_ONLY_METHODS
    assert mcp_server.tool_name("workspace/readMember") in mcp_server.TOOL_TO_METHOD
    assert mcp_server.tool_name("workspace/listMembers") in mcp_server.TOOL_TO_METHOD


def test_the_mcp_tool_surface_grew_by_exactly_the_two_new_methods():
    """A count, so a silent widening is visible rather than argued about."""
    expected = len([m for m in rt_core.AGENT_METHODS if m != "initialize"])
    assert len(mcp_server.tool_definitions()) == expected
    assert len(mcp_server.TOOL_TO_METHOD) == expected
    names = {tool["name"] for tool in mcp_server.tool_definitions()}
    assert {"workspace_readMember", "workspace_listMembers"} <= names


def test_the_compile_gate_still_refuses_host_only_and_reaches_the_new_methods():
    """A boundary that relies on the far side catching everything is not one."""
    from _agenthost_support import agenthost_scripts_on_path

    agenthost_scripts_on_path()
    import ah_codes  # noqa: PLC0415
    import ah_compile  # noqa: PLC0415
    from ah_provider import ToolCall  # noqa: PLC0415

    for name in ("workspace_openDirectory", "workspace/openDirectory",
                 "workspace_openPath", "workspace/openPath"):
        with pytest.raises(ah_codes.AgentHostError) as excinfo:
            ah_compile.compile_tool_call(
                ToolCall(call_id="c1", name=name, arguments={"path": "C:/x"}))
        assert excinfo.value.code == "tool_forbidden"
    compiled = ah_compile.compile_tool_call(
        ToolCall(call_id="c2", name="workspace_readMember",
                 arguments={"sessionId": "s", "path": "bundle/content.md"}))
    assert compiled.method == "workspace/readMember"
    compiled = ah_compile.compile_tool_call(
        ToolCall(call_id="c3", name="workspace_listMembers",
                 arguments={"sessionId": "s"}))
    assert compiled.method == "workspace/listMembers"


# --- happy path, on the assembled fixture ----------------------------------------

def _lf(text: str) -> str:
    """Normalise line endings for comparison only.

    ``workspace/readMember`` decodes raw bytes and MUST NOT translate them —
    a write op anchors on exact bytes. The assembled fixture is written
    through ``Path.write_text`` with the platform default, so on Windows its
    bytes carry CRLF while the ``CONTENT_MD`` constant in memory carries LF;
    that is a fact about how the fixture was written, not about the method
    under test, so the comparison normalises rather than the read.
    """
    return text.replace("\r\n", "\n")


def test_read_member_returns_the_exact_bytes_a_write_op_would_anchor_on(
        opened, workspace):
    core, session_id = opened(workspace)
    result = core.workspace_read_member(session_id, "bundle/content.md")
    assert result["sessionId"] == session_id
    assert result["path"] == "bundle/content.md"
    assert result["subject"] == {"kind": "workspace", "runId": None}
    assert _lf(result["text"]) == fixture.CONTENT_MD
    # bytes is exactly what the session copy holds, not a reformatted guess.
    on_disk = core.store.get(session_id).workspace / "bundle" / "content.md"
    assert result["bytes"] == on_disk.stat().st_size
    assert result["bytes"] == len(result["text"].encode("utf-8"))


def test_list_members_names_the_known_parts_with_kind_and_size(opened, workspace):
    core, session_id = opened(workspace)
    result = core.workspace_list_members(session_id)
    rows = {row["path"]: row for row in result["members"]}
    assert result["count"] == len(result["members"])
    assert rows["bundle/content.md"]["kind"] == "file"
    on_disk = core.store.get(session_id).workspace / "bundle" / "content.md"
    assert rows["bundle/content.md"]["bytes"] == on_disk.stat().st_size
    assert rows["bundle"]["kind"] == "directory"
    assert "bytes" not in rows["bundle"]
    assert rows["bundle/figures/plot1.png"]["kind"] == "file"
    # Sorted, so a caller does not re-sort a possibly-large listing itself.
    assert [row["path"] for row in result["members"]] == sorted(
        row["path"] for row in result["members"])


def test_a_backslash_path_from_a_windows_caller_still_resolves(opened, workspace):
    core, session_id = opened(workspace)
    result = core.workspace_read_member(session_id, "bundle\\content.md")
    assert result["path"] == "bundle/content.md"
    assert _lf(result["text"]) == fixture.CONTENT_MD


# --- immutability: never the operator's path -------------------------------------

def test_read_member_never_reaches_the_operators_directory_after_open(
        opened, workspace):
    core, session_id = opened(workspace)
    # Mutate the operator's copy AFTER open; the session copy must not move.
    (workspace / "bundle" / "content.md").write_text("mutated after open",
                                                      encoding="utf-8")
    result = core.workspace_read_member(session_id, "bundle/content.md")
    assert _lf(result["text"]) == fixture.CONTENT_MD


# --- every refusal, by name --------------------------------------------------------

def test_member_missing_when_the_path_is_not_there(opened, tiny):
    core, session_id = opened(tiny)
    with pytest.raises(RpcError) as excinfo:
        core.workspace_read_member(session_id, "bundle/nope.md")
    assert excinfo.value.code == "member_missing"
    assert excinfo.value.data["path"] == "bundle/nope.md"


def test_member_not_text_on_a_binary_member(opened, workspace):
    core, session_id = opened(workspace)
    with pytest.raises(RpcError) as excinfo:
        core.workspace_read_member(session_id, "bundle/figures/plot1.png")
    assert excinfo.value.code == "member_not_text"


def test_member_too_large_refuses_before_reading_the_whole_file(opened, tmp_path):
    root = tmp_path / "ws" / "report-huge"
    (root / "bundle").mkdir(parents=True)
    big = root / "bundle" / "huge.md"
    big.write_bytes(b"a" * (rt_wsops.MAX_MEMBER_BYTES + 1))
    core, session_id = opened(root)
    with pytest.raises(RpcError) as excinfo:
        core.workspace_read_member(session_id, "bundle/huge.md")
    assert excinfo.value.code == "member_too_large"
    assert excinfo.value.data["limit"] == rt_wsops.MAX_MEMBER_BYTES
    assert excinfo.value.data["bytes"] > rt_wsops.MAX_MEMBER_BYTES


@pytest.mark.parametrize("raw", ["../outside.md", "C:/Windows/win.ini",
                                 "/etc/passwd", "bundle/../../outside.md"])
def test_path_not_relative_refuses_anything_outside_the_tree(opened, tiny, raw):
    core, session_id = opened(tiny)
    with pytest.raises(RpcError) as excinfo:
        core.workspace_read_member(session_id, raw)
    assert excinfo.value.code == "path_not_relative"


def test_the_refusal_codes_are_the_same_ones_a_write_op_already_uses():
    """One vocabulary, not two: §15.8 wants the write ops' own refusal words."""
    for code in ("member_missing", "member_not_text", "member_too_large",
                 "path_not_relative"):
        assert code in rt_wsops.WS_REFUSAL_CODES
        assert code in rt_codes.DOMAIN_CODES


# --- candidate read after apply: the fix loop's own aim ----------------------------

def propose_validate_approve_apply(core, session_id, ops):
    plan = core.plan_propose(session_id, rt_wsops.WS_BACKEND, ops,
                             "test-agent")["plan"]
    report = core.plan_validate(plan["planId"])["validation"]
    assert report["ok"], report["hard"]
    approval = core.approval_request(plan["planId"], "test-agent")["approval"]
    core.approval_resolve(approval["approvalId"], plan["planId"],
                          plan["planHash"], "approved", "operator")
    return core.plan_apply(plan["planId"], approval["approvalId"])["candidate"]


def test_read_member_on_a_candidate_sees_the_edit_the_session_copy_does_not(
        opened, tiny):
    core, session_id = opened(tiny)
    before = core.workspace_read_member(session_id, "bundle/content.md")
    assert "측정은 세 번 반복하였다" in before["text"]
    ops = [{"opId": "op1", "kind": "ws_replace_text", "path": "bundle/content.md",
           "old": "측정은 세 번 반복하였다.\n",
           "new": "측정은 다섯 번 반복하였다.\n"}]
    candidate = propose_validate_approve_apply(core, session_id, ops)
    run_id = candidate["runId"]

    on_candidate = core.workspace_read_member(session_id, "bundle/content.md",
                                              run_id=run_id)
    assert "다섯 번" in on_candidate["text"]
    assert on_candidate["subject"]["kind"] == "candidate_workspace"
    assert on_candidate["subject"]["runId"] == run_id

    # The session copy itself is untouched — the candidate is a second tree.
    still_before = core.workspace_read_member(session_id, "bundle/content.md")
    assert still_before["text"] == before["text"]


def test_list_members_on_a_candidate_reports_the_same_membership(opened, tiny):
    core, session_id = opened(tiny)
    before = core.workspace_list_members(session_id)
    ops = [{"opId": "op1", "kind": "ws_replace_text", "path": "bundle/content.md",
           "old": "측정은 세 번 반복하였다.\n",
           "new": "측정은 다섯 번 반복하였다.\n"}]
    candidate = propose_validate_approve_apply(core, session_id, ops)
    after = core.workspace_list_members(session_id, run_id=candidate["runId"])
    # A write op moves content, never membership (§15.6): same paths, and the
    # edited member's size can differ.
    assert ({row["path"] for row in before["members"]}
            == {row["path"] for row in after["members"]})


def test_an_unknown_run_id_refuses_the_same_way_module_check_already_does(
        opened, tiny):
    core, session_id = opened(tiny)
    with pytest.raises(RpcError) as excinfo:
        core.workspace_read_member(session_id, "bundle/content.md",
                                   run_id="no-such-run")
    assert excinfo.value.code == "artifact_missing"
