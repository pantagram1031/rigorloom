# -*- coding: utf-8 -*-
"""The write half of the workspace fix loop (§15.6).

A workspace session could be opened, summarised and checked, and then nothing.
The checkers produce findings about FILES and there was no way to act on one, so
the E4 loop — check, propose the fix, get it approved, apply it, check again —
had a read half only.

This suite is that loop closed, and it is organised around what a write half
has to prove that a read half does not.

THAT AN EDIT IS AIMED. ``ws_replace_text`` refuses an anchor that matches twice
rather than taking the first one, ``ws_set_yaml_key`` refuses a key declared on
two lines, and a binary member is never operable at all. Each refusal is
asserted by name, from the closed set, against a workspace that really has the
shape that triggers it.

THAT THE SOURCE IS NEVER THE SUBJECT. The session's own copy is re-hashed after
every apply and must be the byte-for-byte tree it was at open; the candidate is
a second tree under the run directory, and the receipt names both ends.

THAT THE LOOP MOVES A REAL NUMBER. The last test runs the shipped report
module's real checkers against the assembled workspace, proposes the fix its
findings ask for, applies it, and re-runs the same checkers against the
candidate. The before and after hard-finding counts are the evidence; the
findings it could NOT target are named rather than quietly dropped.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from _runtime_client import CORPUS_FORM, runtime_scripts_on_path
import _workspace_fixture as fixture

runtime_scripts_on_path()

import mcp_server  # noqa: E402
import rt_codes  # noqa: E402
import rt_core  # noqa: E402
import rt_module  # noqa: E402
import rt_wsops  # noqa: E402
from rt_codes import RpcError  # noqa: E402

#: The module whose declaration this file leans on, and the module that
#: declaration requires. A TEST may know a module's name; core may not
#: (modules/README.md rule 1).
REPORT_MODULE = "report"
REQUIRED_MODULES = (REPORT_MODULE, "style")

BUILD_YAML = """\
# Build declaration; update from form inspection and approved design.
base_pt: 10
title: "TBD"
fill:
  min_figures: 4
  bottom_white_max: 25
allow_colors: []
"""

NOTES_MD = """\
# 서론

측정은 세 번 반복하였다. 값은 표에 정리하였다.

## 결과

측정은 세 번 반복하였다. 감쇠 계수는 0.42 로 나타났다.
"""

SOURCES = [{"id": "S1", "title": "Synthetic source", "kind": "journal"}]


def write_enabled(path: Path, names) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("schema: rigorloom-enabled-modules/v1\n"
                    "enabled: [%s]\n" % ", ".join(names), encoding="utf-8")
    return path


@pytest.fixture()
def enabled_report(tmp_path, monkeypatch):
    """The checkout's own report module, enabled for THIS test only.

    Never the operator's ``modules/enabled.yaml``; that is what
    ``RIGORLOOM_MODULES_ENABLED`` is for (§13.6). The declaration is what says
    which paths are read-only, so the write path needs it enabled.
    """
    path = write_enabled(tmp_path / "enablement" / "enabled.yaml",
                         list(REQUIRED_MODULES))
    monkeypatch.setenv(rt_module.MODULES_ENABLED_ENV, str(path))
    monkeypatch.delenv(rt_module.MODULES_ROOT_ENV, raising=False)
    return path


@pytest.fixture()
def tiny(tmp_path):
    """A small workspace with one member of every shape the ops meet.

    Not the assembled fixture: these tests are about the ops, and a checker
    never runs here. The assembled workspace costs a subprocess and a real
    checker run, and is used by the one test that needs real findings.
    """
    root = tmp_path / "ws" / "report-tiny"
    (root / "bundle" / "figures").mkdir(parents=True)
    (root / "research").mkdir(parents=True)
    (root / "_saeteuk").mkdir(parents=True)
    (root / ".pipeline").mkdir(parents=True)
    (root / "build.yaml").write_text(BUILD_YAML, encoding="utf-8")
    (root / "bundle" / "content.md").write_text(NOTES_MD, encoding="utf-8")
    (root / "bundle" / "figures" / "plot1.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    (root / "research" / "sources.json").write_text(
        json.dumps(SOURCES, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (root / "_saeteuk" / "notes.md").write_text("한 문단.\n", encoding="utf-8")
    (root / ".pipeline" / "handoff.json").write_text(
        json.dumps({"final": None}) + "\n", encoding="utf-8")
    return root


@pytest.fixture()
def opened(tmp_path, tiny, enabled_report):
    core = rt_core.RuntimeCore(tmp_path / "root")
    session_id = core.open_workspace(str(tiny))["sessionId"]
    return core, session_id


def member(core, session_id, relative: str) -> Path:
    """A path inside the SESSION's copy — never the operator's directory."""
    return core.store.get(session_id).workspace / relative


def propose(core, session_id, ops, proposer="test-agent"):
    return core.plan_propose(session_id, rt_wsops.WS_BACKEND, ops,
                             proposer)["plan"]


def validation_of(core, session_id, ops):
    plan = propose(core, session_id, ops)
    return core.plan_validate(plan["planId"])["validation"]


def refusal_of(core, session_id, ops) -> dict:
    """The one hard finding a refused plan carries. Asserts there is exactly one."""
    report = validation_of(core, session_id, ops)
    assert report["ok"] is False and report["verdict"] == "fail"
    assert len(report["hard"]) == 1, report["hard"]
    return report["hard"][0]


def applied(core, session_id, ops, approver="operator"):
    """propose → validate → request → approve → apply. The whole gate, once."""
    plan = propose(core, session_id, ops)
    report = core.plan_validate(plan["planId"])["validation"]
    assert report["ok"], report["hard"]
    approval = core.approval_request(plan["planId"], "test-agent")["approval"]
    core.approval_resolve(approval["approvalId"], plan["planId"],
                          plan["planHash"], "approved", approver)
    return plan, core.plan_apply(plan["planId"], approval["approvalId"])["candidate"]


def candidate_member(core, session_id, candidate, relative: str) -> Path:
    session = core.store.get(session_id)
    return (session.candidates_dir / candidate["runId"]
            / candidate["candidate"]["path"] / relative)


# --- the closed vocabularies -------------------------------------------------

def test_the_op_kinds_and_their_refusals_are_closed_sets():
    assert rt_wsops.WS_OP_KINDS == ("ws_replace_text", "ws_set_yaml_key",
                                    "ws_append_source")
    assert set(rt_wsops.WS_OP_FIELDS) == set(rt_wsops.WS_OP_KINDS)
    # A refusal code that is not declared cannot be emitted: ``finding``
    # asserts membership, so a typo is a crash here and not a code a client has
    # to guess about — the discipline ``rt_workspace.reject`` already applies.
    with pytest.raises(AssertionError):
        rt_wsops.finding("no_such_reason", "nope", "ops[x]")


def test_the_ops_this_build_does_not_have_are_named_not_implied():
    """No create, no delete, no rename — said out loud, on the wire."""
    assert rt_wsops.WS_NOT_IMPLEMENTED == ("ws_create_member",
                                           "ws_delete_member",
                                           "ws_rename_member")
    core = rt_core.RuntimeCore(Path("."))
    snapshot = core.capability_snapshot(methods=list(rt_core.METHODS))
    backend = snapshot["backends"][rt_wsops.WS_BACKEND]
    assert backend["state"] == "available"
    assert backend["subject"] == "workspace"
    assert backend["opKinds"] == sorted(rt_wsops.WS_OP_KINDS)
    assert backend["notImplemented"] == list(rt_wsops.WS_NOT_IMPLEMENTED)
    assert backend["refusalCodes"] == list(rt_wsops.WS_REFUSAL_CODES)


# --- the surface still derives ------------------------------------------------

def test_the_write_half_adds_no_method_so_every_surface_derives_unchanged():
    """A new backend is not a new door. The rosters did not move."""
    assert rt_wsops.WS_BACKEND in rt_codes.SUPPORTED_BACKENDS
    assert "plan/propose" in rt_core.AGENT_METHODS
    for host_only in ("plan/apply", "approval/resolve",
                      "workspace/openDirectory"):
        assert host_only in rt_core.HOST_ONLY_METHODS
        assert mcp_server.tool_name(host_only) not in mcp_server.TOOL_TO_METHOD
    expected = len([m for m in rt_core.AGENT_METHODS if m != "initialize"])
    assert len(mcp_server.tool_definitions()) == expected


def test_the_mcp_tool_schema_grew_the_backend_by_deriving_it():
    """``plan_propose``'s enum reads the roster, so nobody edited the adapter."""
    schema = mcp_server.TOOL_SCHEMAS["plan/propose"]["inputSchema"]
    assert schema["properties"]["backend"]["enum"] == list(
        rt_codes.SUPPORTED_BACKENDS)
    assert rt_wsops.WS_BACKEND in schema["properties"]["backend"]["enum"]


def test_the_compile_gate_still_refuses_the_host_half_of_the_loop():
    """An agent proposes; a host approves and applies. Both spellings refused."""
    from _agenthost_support import agenthost_scripts_on_path

    agenthost_scripts_on_path()
    import ah_codes  # noqa: PLC0415
    import ah_compile  # noqa: PLC0415
    from ah_provider import ToolCall  # noqa: PLC0415

    for name in ("approval_resolve", "approval/resolve", "plan_apply",
                 "plan/apply", "workspace_openDirectory",
                 "workspace/openDirectory"):
        with pytest.raises(ah_codes.AgentHostError) as excinfo:
            ah_compile.compile_tool_call(
                ToolCall(call_id="c1", name=name,
                         arguments={"planId": "p", "decision": "approved"}))
        assert excinfo.value.code == "tool_forbidden"
        assert excinfo.value.data["method"] in rt_core.HOST_ONLY_METHODS
    # And the agent half IS reachable, so this is a split and not a wall.
    compiled = ah_compile.compile_tool_call(
        ToolCall(call_id="c2", name="plan_propose",
                 arguments={"sessionId": "s", "backend": "workspace",
                            "ops": [{"kind": "ws_replace_text"}]}))
    assert compiled.method == "plan/propose"


# --- routing: which backend, which session kind -------------------------------

@pytest.fixture()
def document_session(tmp_path, enabled_report):
    """A document session, for the refusals that are about the OTHER kind."""
    core = rt_core.RuntimeCore(tmp_path / "docroot")
    return core, core.open_path(str(CORPUS_FORM))["sessionId"]


def test_a_workspace_op_kind_under_the_document_backend_names_its_backend(
        document_session):
    core, session_id = document_session
    with pytest.raises(RpcError) as excinfo:
        core.plan_propose(session_id, "preedit",
                          [{"kind": "ws_replace_text", "path": "a", "old": "x",
                            "new": "y"}], "test-agent")
    assert excinfo.value.code == "unsupported_backend"
    assert excinfo.value.data["servedBy"] == rt_wsops.WS_BACKEND


def test_a_document_op_kind_under_the_workspace_backend_names_preedit(opened):
    core, session_id = opened
    with pytest.raises(RpcError) as excinfo:
        core.plan_propose(session_id, rt_wsops.WS_BACKEND,
                          [{"kind": "fill_cell", "row": 1, "col": 1,
                            "text": "x"}], "test-agent")
    assert excinfo.value.code == "unsupported_backend"
    assert excinfo.value.data["servedBy"] == "preedit"


def test_an_unknown_op_kind_lists_what_exists_and_what_is_missing(opened):
    core, session_id = opened
    with pytest.raises(RpcError) as excinfo:
        core.plan_propose(session_id, rt_wsops.WS_BACKEND,
                          [{"kind": "ws_delete_member", "path": "a"}],
                          "test-agent")
    assert excinfo.value.code == "unknown_op_kind"
    assert excinfo.value.data["knownKinds"] == sorted(rt_wsops.WS_OP_KINDS)
    assert "ws_delete_member" in excinfo.value.data["notImplemented"]


def test_a_field_the_op_does_not_define_is_refused(opened):
    core, session_id = opened
    with pytest.raises(RpcError) as excinfo:
        core.plan_propose(session_id, rt_wsops.WS_BACKEND,
                          [{"kind": "ws_replace_text", "path": "build.yaml",
                            "old": "a", "new": "b", "regex": True}],
                          "test-agent")
    assert excinfo.value.code == "unknown_field"
    assert excinfo.value.data["unknown"] == ["regex"]


def test_a_workspace_plan_on_a_document_session_is_a_kind_mismatch(tmp_path,
                                                                   enabled_report):
    core = rt_core.RuntimeCore(tmp_path / "root")
    session_id = core.open_path(str(CORPUS_FORM))["sessionId"]
    with pytest.raises(RpcError) as excinfo:
        core.plan_propose(session_id, rt_wsops.WS_BACKEND,
                          [{"kind": "ws_replace_text", "path": "a", "old": "x",
                            "new": "y"}], "test-agent")
    assert excinfo.value.code == "session_kind_mismatch"
    assert excinfo.value.data["required"] == "workspace"


def test_a_document_plan_on_a_workspace_session_is_a_kind_mismatch(opened):
    core, session_id = opened
    with pytest.raises(RpcError) as excinfo:
        core.plan_propose(session_id, "preedit",
                          [{"kind": "fill_cell", "row": 1, "col": 1,
                            "text": "x"}], "test-agent")
    assert excinfo.value.code == "session_kind_mismatch"
    assert excinfo.value.data["required"] == "document"


def test_the_plan_binds_the_tree_hash_and_the_ops_hash_covers_the_intent(opened):
    core, session_id = opened
    session = core.store.get(session_id)
    ops = [{"kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
            "value": 11}]
    first = propose(core, session_id, ops)
    second = propose(core, session_id, ops, proposer="another-front-end")
    assert first["boundSha256"] == session.meta["workspaceTreeSha256"]
    assert first["backend"] == rt_wsops.WS_BACKEND
    # Same tree, same ops, same intent — whoever proposed it and whenever.
    assert first["opsHash"] == second["opsHash"]
    assert first["planHash"] != second["planHash"]


# --- happy paths, one per op kind ---------------------------------------------

def test_ws_replace_text_edits_one_place_and_leaves_the_source_alone(opened):
    core, session_id = opened
    session = core.store.get(session_id)
    before = session.meta["workspaceTreeSha256"]
    anchor = "감쇠 계수는 0.42 로 나타났다."
    plan, candidate = applied(core, session_id, [{
        "kind": "ws_replace_text", "path": "bundle/content.md",
        "old": anchor, "new": anchor[:-1] + " [S1].", "opId": "cite"}])
    edited = candidate_member(core, session_id, candidate,
                              "bundle/content.md").read_text(encoding="utf-8")
    assert "[S1]" in edited
    assert "[S1]" not in member(core, session_id,
                                "bundle/content.md").read_text(encoding="utf-8")
    assert core.workspace_tree_sha256(session) == before
    assert candidate["candidate"]["treeSha256"] != before
    assert candidate["steps"][0] == {"opId": "cite", "kind": "ws_replace_text",
                                     "path": "bundle/content.md", "index": 0,
                                     "occurrences": 1, "anchorChars": len(anchor)}


def test_ws_set_yaml_key_rewrites_one_line_and_keeps_every_other_byte(opened):
    core, session_id = opened
    _plan, candidate = applied(core, session_id, [
        {"kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
         "value": 11},
        {"kind": "ws_set_yaml_key", "path": "build.yaml",
         "key": "fill.min_figures", "value": 6},
        {"kind": "ws_set_yaml_key", "path": "build.yaml", "key": "title",
         "value": "감쇠 진동의 에너지 소산 측정"},
    ])
    text = candidate_member(core, session_id, candidate,
                            "build.yaml").read_text(encoding="utf-8")
    assert "base_pt: 11" in text
    assert "  min_figures: 6" in text
    assert 'title: "감쇠 진동의 에너지 소산 측정"' in text
    # The comment, the key order and the untouched keys all survive: this
    # rewrites a line, it does not load and dump the document.
    assert text.splitlines()[0].startswith("# Build declaration")
    assert "bottom_white_max: 25" in text
    assert "allow_colors: []" in text


def test_ws_append_source_appends_to_the_array_the_checkers_read(opened):
    core, session_id = opened
    _plan, candidate = applied(core, session_id, [{
        "kind": "ws_append_source",
        "source": {"id": "S2", "title": "Second source", "kind": "journal"}}])
    payload = json.loads(candidate_member(
        core, session_id, candidate,
        "research/sources.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in payload] == ["S1", "S2"]
    assert candidate["steps"][0]["sourceId"] == "S2"
    assert candidate["steps"][0]["sources"] == 2


def test_the_ops_chain_so_a_later_one_sees_what_an_earlier_one_wrote(opened):
    """Two anchors on one member, the second only reachable after the first."""
    core, session_id = opened
    _plan, candidate = applied(core, session_id, [
        {"kind": "ws_replace_text", "path": "bundle/content.md",
         "old": "## 결과", "new": "## 결과와 해석", "opId": "one"},
        {"kind": "ws_replace_text", "path": "bundle/content.md",
         "old": "## 결과와 해석", "new": "## 결과 및 해석", "opId": "two"},
    ])
    text = candidate_member(core, session_id, candidate,
                            "bundle/content.md").read_text(encoding="utf-8")
    assert "## 결과 및 해석" in text
    assert [step["opId"] for step in candidate["steps"]] == ["one", "two"]


# --- every refusal ------------------------------------------------------------

def test_an_anchor_that_is_not_there_refuses(opened):
    core, session_id = opened
    row = refusal_of(core, session_id, [{
        "kind": "ws_replace_text", "path": "bundle/content.md",
        "old": "이 문장은 이 보고서에 없다", "new": "x"}])
    assert row["code"] == "anchor_not_found"


def test_an_anchor_that_matches_twice_refuses_rather_than_choosing(opened):
    """The whole point: 'first match' is how an edit lands in the wrong section."""
    core, session_id = opened
    row = refusal_of(core, session_id, [{
        "kind": "ws_replace_text", "path": "bundle/content.md",
        "old": "측정은 세 번 반복하였다.", "new": "측정은 네 번 반복하였다."}])
    assert row["code"] == "anchor_ambiguous"
    assert row["occurrences"] == 2


def test_a_binary_member_is_never_operable(opened):
    core, session_id = opened
    row = refusal_of(core, session_id, [{
        "kind": "ws_replace_text", "path": "bundle/figures/plot1.png",
        "old": "PNG", "new": "JPG"}])
    assert row["code"] == "member_not_text"
    assert row["path"] == "bundle/figures/plot1.png"


def test_a_member_that_is_not_there_refuses_and_names_the_missing_ops(opened):
    core, session_id = opened
    row = refusal_of(core, session_id, [{
        "kind": "ws_replace_text", "path": "output/QUESTIONS.md",
        "old": "a", "new": "b"}])
    assert row["code"] == "member_missing"
    assert "ws_create_member" in row["notImplemented"]


def test_a_member_larger_than_this_build_edits_refuses(opened, monkeypatch):
    core, session_id = opened
    monkeypatch.setattr(rt_wsops, "MAX_MEMBER_BYTES", 8)
    row = refusal_of(core, session_id, [{
        "kind": "ws_replace_text", "path": "bundle/content.md",
        "old": "## 결과", "new": "## 결과와 해석"}])
    assert row["code"] == "member_too_large"
    assert row["limit"] == 8


@pytest.mark.parametrize("path", [
    "_saeteuk/notes.md",        # a declared read-only DIRECTORY
    ".pipeline/handoff.json",   # a declared read-only FILE
])
def test_a_path_a_module_declared_read_only_refuses(opened, path):
    """Writing one would edit the evidence a checker is about to read."""
    core, session_id = opened
    row = refusal_of(core, session_id, [{
        "kind": "ws_replace_text", "path": path, "old": "a", "new": "b"}])
    assert row["code"] == "member_read_only"
    assert row["role"] in ("saeteuk-artifacts", "handoff")


def test_with_no_module_enabled_nothing_is_read_only_and_the_summary_says_so(
        tmp_path, tiny, monkeypatch):
    """A disclosure, not a feature.

    Read-only is a MODULE's declaration (§15.1) and core holds no path list, so
    with nothing enabled there is nothing to enforce and ``_saeteuk/`` is an
    ordinary member. The summary already reports ``layout.state: undeclared``
    with a reason, which is the only honest place for a caller to learn it —
    recorded in §15.8 as a gap rather than papered over with a hardcoded list.
    """
    enabled = write_enabled(tmp_path / "none" / "enabled.yaml", [])
    monkeypatch.setenv(rt_module.MODULES_ENABLED_ENV, str(enabled))
    monkeypatch.delenv(rt_module.MODULES_ROOT_ENV, raising=False)
    core = rt_core.RuntimeCore(tmp_path / "root")
    session_id = core.open_workspace(str(tiny))["sessionId"]
    assert core.workspace_inspect(session_id)["layout"]["state"] == "undeclared"
    report = validation_of(core, session_id, [{
        "kind": "ws_replace_text", "path": "_saeteuk/notes.md",
        "old": "한 문단.", "new": "두 문단."}])
    assert report["ok"] is True


@pytest.mark.parametrize("path", [
    "../outside.md", "/etc/passwd", "C:/Windows/system.ini",
    "bundle/../../escape.md",
])
def test_a_path_that_leaves_the_workspace_refuses(opened, path):
    core, session_id = opened
    row = refusal_of(core, session_id, [{
        "kind": "ws_replace_text", "path": path, "old": "a", "new": "b"}])
    assert row["code"] == "path_not_relative"


def test_a_yaml_this_build_does_not_model_refuses_rather_than_guessing(opened):
    core, session_id = opened
    member(core, session_id, "build.yaml").write_bytes(
        b"base_pt: 10\n\tbroken: 1\n")
    row = refusal_of(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": 11}])
    assert row["code"] == "yaml_unparseable"
    assert row["line"] == 2


def test_a_key_the_file_does_not_declare_refuses(opened):
    core, session_id = opened
    row = refusal_of(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "fill.pages",
        "value": 5}])
    assert row["code"] == "yaml_key_unknown"
    assert "fill.min_figures" in row["knownKeys"]


def test_a_key_declared_twice_refuses_rather_than_picking_one(opened):
    core, session_id = opened
    member(core, session_id, "build.yaml").write_text(
        "base_pt: 10\nbase_pt: 12\n", encoding="utf-8")
    row = refusal_of(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": 11}])
    assert row["code"] == "yaml_key_ambiguous"
    assert row["lines"] == [1, 2]


def test_a_key_that_holds_a_structure_is_not_a_scalar(opened):
    core, session_id = opened
    row = refusal_of(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "fill",
        "value": 4}])
    assert row["code"] == "yaml_key_not_scalar"


def test_a_line_with_an_inline_comment_refuses(opened):
    """Rewriting the value would drop the comment or guess where it ends."""
    core, session_id = opened
    member(core, session_id, "build.yaml").write_text(
        "base_pt: 10  # from the form\n", encoding="utf-8")
    row = refusal_of(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": 11}])
    assert row["code"] == "yaml_inline_comment"


@pytest.mark.parametrize("value", [{"a": 1}, [1, 2]])
def test_a_value_that_is_not_a_scalar_refuses(opened, value):
    core, session_id = opened
    row = refusal_of(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": value}])
    assert row["code"] == "op_field_invalid"


def test_a_source_list_that_is_not_an_array_refuses_and_says_which_shape(opened):
    core, session_id = opened
    member(core, session_id, "research/sources.json").write_text(
        json.dumps({"schema": "rigorloom-sources/v1", "sources": SOURCES}),
        encoding="utf-8")
    row = refusal_of(core, session_id, [{
        "kind": "ws_append_source", "source": {"id": "S2", "title": "x"}}])
    assert row["code"] == "source_container_invalid"
    assert row["found"] == "dict"
    assert "claims_ledger" in row["msg"]


def test_a_source_list_that_is_not_json_refuses(opened):
    core, session_id = opened
    member(core, session_id, "research/sources.json").write_text(
        "[{", encoding="utf-8")
    row = refusal_of(core, session_id, [{
        "kind": "ws_append_source", "source": {"id": "S2", "title": "x"}}])
    assert row["code"] == "source_container_invalid"


def test_a_source_id_the_list_already_defines_refuses(opened):
    core, session_id = opened
    row = refusal_of(core, session_id, [{
        "kind": "ws_append_source",
        "source": {"id": "S1", "title": "Same id, other record"}}])
    assert row["code"] == "source_duplicate_id"
    assert row["sourceId"] == "S1"


@pytest.mark.parametrize("op,expected", [
    ({"kind": "ws_replace_text", "path": "build.yaml", "old": "base_pt: 10",
      "new": "base_pt: 10"}, "the same text"),
    ({"kind": "ws_replace_text", "path": "build.yaml", "old": "", "new": "x"},
     "non-empty string anchor"),
    ({"kind": "ws_append_source", "source": {"title": "no id"}},
     "source.id must be"),
])
def test_an_op_whose_own_fields_are_wrong_refuses(opened, op, expected):
    core, session_id = opened
    row = refusal_of(core, session_id, [op])
    assert row["code"] == "op_field_invalid"
    assert expected in row["msg"]


def test_evaluation_stops_at_the_first_refusal_and_says_what_it_skipped(opened):
    core, session_id = opened
    report = validation_of(core, session_id, [
        {"kind": "ws_replace_text", "path": "bundle/content.md",
         "old": "없는 문장", "new": "x", "opId": "doomed"},
        {"kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
         "value": 11, "opId": "never-tried"},
    ])
    assert report["counts"]["hard"] == 1
    assert report["preflight"]["notEvaluated"] == ["never-tried"]
    assert report["preflight"]["applied"] == []


# --- the gate: a refused plan cannot be applied --------------------------------

def test_a_plan_that_does_not_validate_is_refused_at_apply_and_publishes_nothing(
        opened):
    core, session_id = opened
    session = core.store.get(session_id)
    plan = propose(core, session_id, [{
        "kind": "ws_replace_text", "path": "bundle/content.md",
        "old": "측정은 세 번 반복하였다.", "new": "x"}])
    approval = core.approval_request(plan["planId"], "test-agent")["approval"]
    core.approval_resolve(approval["approvalId"], plan["planId"],
                          plan["planHash"], "approved", "operator")
    with pytest.raises(RpcError) as excinfo:
        core.plan_apply(plan["planId"], approval["approvalId"])
    assert excinfo.value.code == "plan_invalid"
    assert excinfo.value.data["hard"][0]["code"] == "anchor_ambiguous"
    assert core.candidate_list(session_id)["candidates"] == []
    assert not any(session.candidates_dir.iterdir()) \
        if session.candidates_dir.is_dir() else True


def test_a_plan_proposed_against_a_tree_that_moved_is_stale(opened):
    core, session_id = opened
    plan = propose(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": 11}])
    member(core, session_id, "bundle/content.md").write_text(
        "다른 내용.\n", encoding="utf-8")
    report = core.plan_validate(plan["planId"])["validation"]
    assert report["stale"] is True
    assert report["hard"][0]["code"] == "plan_stale"
    approval = core.approval_request(plan["planId"], "test-agent")["approval"]
    with pytest.raises(RpcError) as excinfo:
        core.approval_resolve(approval["approvalId"], plan["planId"],
                              plan["planHash"], "approved", "operator")
    assert excinfo.value.code == "plan_stale"


def test_an_unapproved_plan_cannot_be_applied(opened):
    core, session_id = opened
    plan = propose(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": 11}])
    approval = core.approval_request(plan["planId"], "test-agent")["approval"]
    with pytest.raises(RpcError) as excinfo:
        core.plan_apply(plan["planId"], approval["approvalId"])
    assert excinfo.value.code == "plan_not_approved"


def test_the_preflight_leaves_nothing_behind(opened):
    core, session_id = opened
    session = core.store.get(session_id)
    validation_of(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": 11}])
    leftovers = [entry.name for entry in session.work_dir.iterdir()] \
        if session.work_dir.is_dir() else []
    assert leftovers == []


# --- immutability, lineage, receipt -------------------------------------------

def test_the_receipt_names_both_ends_of_the_lineage_and_verifies_the_tree(opened):
    core, session_id = opened
    session = core.store.get(session_id)
    plan, candidate = applied(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": 11}])
    receipt = core.receipt_read(session_id, candidate["runId"])["receipt"]
    assert receipt["backend"] == rt_wsops.WS_BACKEND
    assert receipt["planId"] == plan["planId"]
    assert receipt["approval"]["state"] == "approved"
    assert receipt["source"]["treeSha256"] == session.meta["workspaceTreeSha256"]
    assert receipt["candidate"]["role"] == "workspace_tree"
    assert receipt["lineage"]["fromTreeSha256"] == receipt["source"]["treeSha256"]
    assert receipt["lineage"]["toTreeSha256"] == \
        receipt["candidate"]["treeSha256"]
    assert receipt["lineage"]["boundSha256"] == plan["boundSha256"]
    # No member was added or removed: these ops move content, never membership.
    assert receipt["lineage"]["membershipChanged"] is False
    assert receipt["candidate"]["files"] == session.meta["workspaceFiles"]
    # A workspace candidate is verified by module/check, and apply says so
    # rather than claiming an acceptance nothing earned.
    assert receipt["checks"]["acceptance"] is False
    assert "module/check" in receipt["checks"]["reason"]
    assert core.candidate_list(session_id)["candidates"] == [
        {"runId": candidate["runId"], "receipt": f"{candidate['runId']}/receipt.json"}]


def test_a_candidate_tree_that_drifts_after_its_receipt_refuses(opened):
    core, session_id = opened
    _plan, candidate = applied(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": 11}])
    candidate_member(core, session_id, candidate, "build.yaml").write_text(
        "tampered: true\n", encoding="utf-8")
    with pytest.raises(RpcError) as excinfo:
        core.receipt_read(session_id, candidate["runId"])
    assert excinfo.value.code == "candidate_hash_mismatch"


def test_two_candidates_from_one_session_do_not_see_each_other(opened):
    """Every candidate branches from the session copy, which never moves."""
    core, session_id = opened
    session = core.store.get(session_id)
    _p1, first = applied(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": 11}])
    _p2, second = applied(core, session_id, [{
        "kind": "ws_set_yaml_key", "path": "build.yaml", "key": "base_pt",
        "value": 12}])
    assert core.workspace_tree_sha256(session) == \
        session.meta["workspaceTreeSha256"]
    assert first["candidate"]["treeSha256"] != second["candidate"]["treeSha256"]
    assert "base_pt: 11" in candidate_member(
        core, session_id, first, "build.yaml").read_text(encoding="utf-8")
    assert "base_pt: 12" in candidate_member(
        core, session_id, second, "build.yaml").read_text(encoding="utf-8")
    assert len(core.candidate_list(session_id)["candidates"]) == 2


# --- the loop, on real checkers and a real finding ------------------------------

@pytest.fixture(scope="session")
def assembled(tmp_path_factory):
    """The assembled workspace; see tests/_workspace_fixture.py for every piece."""
    home = tmp_path_factory.mktemp("wsopsfixture")
    enabled = write_enabled(home / "enablement" / "enabled.yaml",
                            list(REQUIRED_MODULES))
    return fixture.scaffold(home / "workspaces" / "report-e4ops",
                            modules_root=fixture.REPO_ROOT / "modules",
                            enabled_file=enabled)


def test_the_fix_loop_moves_the_finding_count(tmp_path, assembled,
                                              enabled_report):
    """check → fix ops from the findings → approve → apply → check the candidate.

    The findings are real: ``check_claims`` and ``content_audit`` report four
    HARD ``claim_source_missing`` rows because the ledger's evidence cites
    ``S1`` and ``research/sources.json`` in the assembled workspace is an
    OBJECT, while the only reader of that file
    (``claims_ledger.source_identity_groups``,
    modules/report/scripts/claims_ledger.py:325-336) reads a top-level ARRAY.
    So the fix the findings ask for is: make the file the shape the reader
    reads, then the id resolves.

    WHAT THIS LOOP CANNOT TARGET, named rather than dropped: none of those four
    findings carries an ``address``. Their location is a source id (``S1``),
    not a path, and §15.4's rule is that a half-resolved location is not an
    address. The ops were therefore aimed by READING the member, not by
    following a finding's address — and there is no agent-safe method to read a
    workspace member at all, which is recorded as a gap.
    """
    workspace = tmp_path / "ws" / assembled.name
    workspace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(assembled, workspace)
    core = rt_core.RuntimeCore(tmp_path / "root")
    session_id = core.open_workspace(str(workspace))["sessionId"]
    session = core.store.get(session_id)

    before = core.module_check(session_id, REPORT_MODULE)
    assert before["counts"]["ran"] == 12
    assert before["counts"]["hard"] == 4
    unaddressed = [finding for row in before["checks"]
                   for finding in row.get("findings", [])
                   if finding["severity"] == "hard"]
    assert {finding["code"] for finding in unaddressed} == {"claim_source_missing"}
    assert all(finding["address"] is None for finding in unaddressed)

    # The anchors are the member's own bytes, read from the SESSION copy.
    text = member(core, session_id, "research/sources.json").read_bytes().decode("utf-8")
    head = text[:text.index("[") + 1]
    tail = text[text.rindex("  ]"):]
    _plan, candidate = applied(core, session_id, [
        {"kind": "ws_replace_text", "path": "research/sources.json",
         "old": head, "new": "[", "opId": "unwrap-head"},
        {"kind": "ws_replace_text", "path": "research/sources.json",
         "old": tail, "new": "]", "opId": "unwrap-tail"},
        {"kind": "ws_append_source", "opId": "add-s2",
         "source": {"id": "S2", "title": "Second synthetic source",
                    "author": "Example Author", "year": 2025,
                    "kind": "journal"}},
    ])

    after = core.module_check(session_id, REPORT_MODULE,
                              run_id=candidate["runId"])
    assert after["subject"]["kind"] == "candidate_workspace"
    assert after["subject"]["runId"] == candidate["runId"]
    assert after["subject"]["sha256"] == candidate["candidate"]["treeSha256"]
    assert after["counts"]["ran"] == before["counts"]["ran"] == 12
    assert after["counts"]["hard"] == 0
    # The warnings are the fixture's own content and this plan did not aim at
    # them; saying so is the difference between a loop and a claim.
    assert after["counts"]["warn"] == before["counts"]["warn"]
    # A workspace candidate has no baseline either, and never claims one.
    assert after["baseline"]["supplied"] is False
    assert core.workspace_tree_sha256(session) == \
        session.meta["workspaceTreeSha256"]
