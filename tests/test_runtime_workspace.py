# -*- coding: utf-8 -*-
"""Runtime GAP 20: a workspace session, so the workspace checkers can run.

Thirteen of the seventeen checkers the six shipped distribution modules declare
take a report WORKSPACE directory. The Runtime knew only documents, so
``module/check`` skipped every one of them with ``needs_workspace`` and the
report pipeline — this repository's original product — could not run inside the
application at all. This suite is that gap closed, and it is organised around
the two things a new session kind has to prove.

THAT IT IS HONEST. The summary says which declared parts are there, per part,
and says ``undeclared`` when no enabled module declares a layout rather than
carrying a path list core is not allowed to have. A refusal names a reason from
a closed set. A checker whose subject is the other kind is skipped with
``needs_document`` — the exact mirror of the reason that made this slice
necessary — and is never counted as a pass.

THAT IT IS ISOLATED. The operator's directory is read and copied; a checker
that writes reaches only the per-call scratch. That is asserted against a
checker that really does write, not promised.

The REAL-checker half runs the shipped report and style modules against a
workspace assembled by ``tests/_workspace_fixture.py``, whose docstring names
every piece and where it came from. That fixture is not a corpus and this file
does not treat it as one: what it proves is that the wire carries a real
checker's real verdict, not anything about report quality.
"""
from __future__ import annotations

import json
import os
import shutil

import pytest

from _runtime_client import (
    CORPUS_FORM,
    McpClient,
    RuntimeClient,
    run_cli,
    runtime_scripts_on_path,
)
import _workspace_fixture as fixture

runtime_scripts_on_path()

import mcp_server  # noqa: E402
import rt_codes  # noqa: E402
import rt_core  # noqa: E402
import rt_module  # noqa: E402
import rt_session  # noqa: E402
import rt_workspace  # noqa: E402

#: The shipped modules whose checkers take a workspace, and the one whose
#: checker takes a document. Named here because a TEST may know a module's
#: name; core may not (modules/README.md rule 1).
WORKSPACE_MODULES = ("report", "style")
DOCUMENT_MODULE = "gongmun"


def write_enabled(path, names):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("schema: rigorloom-enabled-modules/v1\n"
                    "enabled: [%s]\n" % ", ".join(names), encoding="utf-8")
    return path


# --- fixtures -----------------------------------------------------------------

@pytest.fixture()
def root(tmp_path):
    return tmp_path / "root"


@pytest.fixture()
def enabled_all(tmp_path, monkeypatch):
    """The checkout's own modules, enabled for THIS test only.

    Never the operator's ``modules/enabled.yaml``: this checkout is core-only
    and must stay so, which is exactly why ``RIGORLOOM_MODULES_ENABLED`` exists
    (§13.6).
    """
    path = write_enabled(tmp_path / "enablement" / "enabled.yaml",
                         list(WORKSPACE_MODULES) + [DOCUMENT_MODULE])
    monkeypatch.setenv(rt_module.MODULES_ENABLED_ENV, str(path))
    monkeypatch.delenv(rt_module.MODULES_ROOT_ENV, raising=False)
    return path


@pytest.fixture()
def enabled_none(tmp_path, monkeypatch):
    """A modules root with nothing enabled, so 'undeclared' is reachable."""
    path = write_enabled(tmp_path / "no-enablement" / "enabled.yaml", [])
    monkeypatch.setenv(rt_module.MODULES_ENABLED_ENV, str(path))
    monkeypatch.delenv(rt_module.MODULES_ROOT_ENV, raising=False)
    return path


@pytest.fixture(scope="session")
def assembled(tmp_path_factory):
    """One assembled workspace for the whole file; see _workspace_fixture."""
    home = tmp_path_factory.mktemp("wsfixture")
    enabled = write_enabled(home / "enablement" / "enabled.yaml",
                            list(WORKSPACE_MODULES))
    target = home / "workspaces" / "report-e4fixture"
    return fixture.scaffold(target,
                            modules_root=fixture.REPO_ROOT / "modules",
                            enabled_file=enabled)


@pytest.fixture()
def workspace(tmp_path, assembled):
    """A private copy, so a test that writes cannot disturb another."""
    target = tmp_path / "ws" / assembled.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(assembled, target)
    return target


def opened(root, path):
    core = rt_core.RuntimeCore(root)
    return core, core.open_workspace(str(path))["sessionId"]


# --- the closed vocabularies ----------------------------------------------------

def test_the_session_kinds_and_reject_reasons_are_closed_sets():
    assert rt_codes.SESSION_KINDS == ("document", "workspace")
    assert set(rt_workspace.WORKSPACE_REJECT_REASONS) == \
        set(rt_codes.WORKSPACE_REJECT_REASONS)
    # Every reason the module can actually raise is in the declared set —
    # ``reject`` asserts membership, so a typo is a crash here and not a code
    # a client has to guess about.
    with pytest.raises(AssertionError):
        rt_workspace.reject("no_such_reason", "nope")


def test_the_skip_reasons_gained_the_mirror_and_nothing_else():
    assert set(rt_module.SKIP_REASONS) == {
        "subject_undeclared", "needs_workspace", "needs_document"}
    assert rt_module.MISMATCH_REASON == {"document": "needs_document",
                                         "workspace": "needs_workspace"}


# --- the derived surface --------------------------------------------------------

def test_the_new_methods_reach_their_surfaces_without_editing_a_gate():
    """The registries derive; this only states what they then enforce.

    ``rt_server`` asserts its handler map equals the roster at construction,
    ``mcp_server`` asserts its tool table equals the agent roster at import,
    and ``ah_compile`` derives the model-facing allow-list from the same tuple.
    So an agent-safe addition appears in all three and a host-only one appears
    in none of them, with nobody editing a list.
    """
    assert "workspace/inspect" in rt_core.AGENT_METHODS
    assert "workspace/openDirectory" in rt_core.HOST_ONLY_METHODS
    assert mcp_server.tool_name("workspace/inspect") in mcp_server.TOOL_TO_METHOD
    assert mcp_server.tool_name("workspace/openDirectory") not in \
        mcp_server.TOOL_TO_METHOD
    assert "workspace.opened" in rt_session.EVENT_KINDS


def test_the_mcp_tool_surface_grew_by_exactly_the_agent_addition():
    """A count, so a silent widening is visible rather than argued about."""
    expected = len([m for m in rt_core.AGENT_METHODS if m != "initialize"])
    assert len(mcp_server.tool_definitions()) == expected
    assert len(mcp_server.TOOL_TO_METHOD) == expected


def test_a_fake_model_asking_for_the_workspace_opener_is_refused_at_compile():
    """The Agent Host gate, not the Runtime's absence — a boundary that relies
    on the far side catching everything is not a boundary."""
    from _agenthost_support import agenthost_scripts_on_path

    agenthost_scripts_on_path()
    import ah_codes  # noqa: PLC0415
    import ah_compile  # noqa: PLC0415
    from ah_provider import ToolCall  # noqa: PLC0415

    for name in ("workspace_openDirectory", "workspace/openDirectory"):
        with pytest.raises(ah_codes.AgentHostError) as excinfo:
            ah_compile.compile_tool_call(
                ToolCall(call_id="c1", name=name,
                         arguments={"path": "C:/anything"}))
        assert excinfo.value.code == "tool_forbidden"
        assert excinfo.value.data["method"] == "workspace/openDirectory"
    # And the agent-safe half IS reachable, so the split is a split and not a
    # blanket refusal of everything with 'workspace' in the name.
    compiled = ah_compile.compile_tool_call(
        ToolCall(call_id="c2", name="workspace_inspect",
                 arguments={"sessionId": "s"}))
    assert compiled.method == "workspace/inspect"


def test_an_agent_connection_can_inspect_but_cannot_open(tmp_path, workspace,
                                                         enabled_all):
    host_root = tmp_path / "shared"
    session_id = run_cli(host_root, "open-workspace",
                         "--path", str(workspace)).result["sessionId"]
    with RuntimeClient(host_root, entry="agent") as agent:
        result = agent.initialize()["result"]
        assert "workspace/inspect" in result["capabilities"]["methods"]
        assert "workspace/openDirectory" not in result["capabilities"]["methods"]
        error = agent.err("workspace/openDirectory", {"path": str(workspace)})
        assert error["code"] == "unknown_method"
        assert error["data"]["knownOnHostEntry"] is True
        summary = agent.ok("workspace/inspect", {"sessionId": session_id})
    assert summary["kind"] == "workspace"


# --- open: bounds and honesty ----------------------------------------------------

def test_open_records_the_tree_hash_and_the_copy_cost(root, workspace):
    core, session_id = opened(root, workspace)
    session = core.store.get(session_id)
    assert session.kind == "workspace"
    summary = core.workspace_inspect(session_id)
    assert summary["workspace"]["files"] == summary["copy"]["files"]
    assert summary["workspace"]["bytes"] > 0
    assert len(summary["workspace"]["treeSha256"]) == 64
    # The cost is published, not assumed small: a workspace is a tree and a
    # caller sizing a fix loop needs the number.
    assert summary["copy"]["millis"] >= 0


def test_the_tree_hash_is_content_addressed_and_order_independent(tmp_path,
                                                                  workspace):
    first = rt_workspace.copy_tree(workspace, tmp_path / "a")
    second = rt_workspace.copy_tree(workspace, tmp_path / "b")
    assert first["treeSha256"] == second["treeSha256"]
    (workspace / "bundle" / "content.md").write_text("changed", encoding="utf-8")
    third = rt_workspace.copy_tree(workspace, tmp_path / "c")
    assert third["treeSha256"] != first["treeSha256"]


def test_the_operators_directory_is_never_written(root, workspace, enabled_all):
    before = rt_workspace.copy_tree(workspace, root / "witness")["treeSha256"]
    core, session_id = opened(root, workspace)
    core.workspace_inspect(session_id)
    for module in WORKSPACE_MODULES:
        core.module_check(session_id, module)
    after = rt_workspace.copy_tree(workspace, root / "witness2")["treeSha256"]
    assert after == before, "the Runtime modified the operator's workspace"


@pytest.mark.parametrize("relative", ["form.hwpx", "notes.txt"])
def test_a_file_is_not_a_workspace(root, tmp_path, relative):
    plain = tmp_path / relative
    plain.write_bytes(b"x")
    core = rt_core.RuntimeCore(root)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.open_workspace(str(plain))
    assert excinfo.value.code == "workspace_rejected"
    assert excinfo.value.data["reason"] == "not_a_directory"


def test_a_relative_path_is_refused(root):
    core = rt_core.RuntimeCore(root)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.open_workspace("workspaces/report-x")
    assert excinfo.value.data["reason"] == "path_not_absolute"


def test_a_missing_directory_is_refused(root, tmp_path):
    core = rt_core.RuntimeCore(root)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.open_workspace(str(tmp_path / "nope"))
    assert excinfo.value.data["reason"] == "unreadable"


def test_too_many_files_is_refused_before_anything_is_copied(root, tmp_path,
                                                             monkeypatch):
    """The cap is on ENTRIES, because entries are what the copy costs.

    Measured on this bench: 4096 small files copy in 72.4 s (17.7 ms each)
    while 64 MB in 64 files copies in 1.16 s. A byte-only bound would let a
    16 MB workspace cost seventy seconds on every single check.
    """
    crowd = tmp_path / "crowd"
    crowd.mkdir()
    for index in range(12):
        (crowd / f"f{index}.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(rt_workspace, "MAX_WORKSPACE_FILES", 5)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_workspace.survey(crowd)
    assert excinfo.value.data["reason"] == "too_many_files"
    assert excinfo.value.data["limit"] == 5
    # Nothing was staged: the refusal happens during the walk, before copy.
    core = rt_core.RuntimeCore(root)
    with pytest.raises(rt_codes.RpcError):
        core.open_workspace(str(crowd))
    assert not (core.store.root / "sessions").exists() or not list(
        (core.store.root / "sessions").iterdir())


def test_an_oversized_workspace_is_refused(tmp_path, monkeypatch):
    big = tmp_path / "big"
    big.mkdir()
    (big / "blob.bin").write_bytes(b"x" * 4096)
    monkeypatch.setattr(rt_workspace, "MAX_WORKSPACE_BYTES", 1024)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_workspace.survey(big)
    assert excinfo.value.data["reason"] == "workspace_too_large"
    assert excinfo.value.data["limit"] == 1024


def test_a_workspace_that_nests_too_deep_is_refused(tmp_path, monkeypatch):
    deep = tmp_path / "deep"
    current = deep
    for index in range(6):
        current = current / f"level{index}"
    current.mkdir(parents=True)
    (current / "leaf.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(rt_workspace, "MAX_WORKSPACE_DEPTH", 3)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_workspace.survey(deep)
    assert excinfo.value.data["reason"] == "too_deep"


@pytest.mark.skipif(os.name == "nt" and not os.environ.get("RIGORLOOM_TEST_SYMLINKS"),
                    reason="creating a symlink on Windows needs privilege; set "
                           "RIGORLOOM_TEST_SYMLINKS=1 on a machine that has it")
def test_a_symlink_inside_the_workspace_is_refused(tmp_path):
    ws = tmp_path / "linked"
    (ws / "bundle").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (ws / "bundle" / "link.txt").symlink_to(outside)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        rt_workspace.survey(ws)
    assert excinfo.value.data["reason"] == "member_symlink"


# --- the summary: declared parts, present or absent, per part --------------------

def test_the_layout_is_declared_by_a_module_not_held_by_core(root, workspace,
                                                             enabled_all):
    core, session_id = opened(root, workspace)
    layout = core.workspace_inspect(session_id)["layout"]
    assert layout["state"] == "declared"
    assert "report" in layout["declaredBy"]
    assert layout["schemas"] == ["report-pipeline-workspace/v1"]
    assert layout["counts"]["declared"] > 0
    by_path = {part["path"]: part for part in layout["parts"]}
    # Parts the assembled workspace really has, answered present.
    for present in ("bundle/content.md", "claims.yaml", "PIPELINE.md",
                    "output/QUESTIONS.md", "request.yaml", "build.yaml"):
        assert by_path[present]["present"] is True, present
    # And parts it does not, answered absent rather than defaulted.
    assert by_path["archive/knowledge/*.md"]["present"] is False
    assert layout["counts"]["present"] + layout["counts"]["absent"] == \
        layout["counts"]["declared"]


def test_the_paths_the_checkers_read_are_all_declared(root, workspace,
                                                      enabled_all):
    """The contract is derived from what the checkers actually read.

    Every path below was found by reading the thirteen workspace-subject
    checkers, not by reading the layout file — four of them
    (``.pipeline/handoff.json``, ``_saeteuk/``, ``sim/results.json``,
    ``sim/provenance.json``) were read by a checker and routed by no stage,
    which is why the declaration grew a ``read_only_paths`` list.
    """
    core, session_id = opened(root, workspace)
    declared = {part["path"]
                for part in core.workspace_inspect(session_id)["layout"]["parts"]}
    read_by_checkers = {
        "PIPELINE.md", "request.yaml", "build.yaml", "claims.yaml",
        "bundle/content.md", "bundle/figures", "output/QUESTIONS.md",
        "output/scorecard.json", "research/sources.json",
        ".pipeline/handoff.json", "_saeteuk", "sim/results.json",
        "sim/provenance.json",
    }
    assert read_by_checkers <= declared, sorted(read_by_checkers - declared)


def test_with_no_module_enabled_the_layout_is_undeclared_not_guessed(
        root, workspace, enabled_none):
    core, session_id = opened(root, workspace)
    summary = core.workspace_inspect(session_id)
    layout = summary["layout"]
    assert layout["state"] == "undeclared"
    assert layout["parts"] == []
    assert layout["counts"] == {"declared": 0, "present": 0, "absent": 0,
                                "absentRequired": 0}
    assert "declares provides.workspace_layout" in layout["reason"]
    # The workspace itself is still open and still described: the absence is
    # of a CONTRACT, not of a session.
    assert summary["workspace"]["files"] > 0
    assert summary["undeclared"]["count"] > 0


def test_entries_the_declaration_does_not_name_are_listed_not_hidden(
        root, workspace, enabled_all):
    (workspace / "operator-notes.md").write_text("mine", encoding="utf-8")
    core, session_id = opened(root, workspace)
    undeclared = core.workspace_inspect(session_id)["undeclared"]
    names = {row["name"] for row in undeclared["entries"]}
    assert "operator-notes.md" in names


# --- the two kinds do not answer for each other ----------------------------------

def test_a_document_method_on_a_workspace_session_is_named_not_mangled(
        root, workspace):
    core, session_id = opened(root, workspace)
    # ``candidate/list`` is deliberately NOT here: a workspace session
    # publishes candidates of its own now (the write half, §15.6), and
    # tests/test_runtime_workspace_ops.py asserts it answers for both kinds.
    for call in (lambda: core.document_inspect(session_id),
                 lambda: core.document_read_region(
                     session_id, [{"table": 0, "row": 1, "col": 1}]),
                 lambda: core.document_render(session_id)):
        with pytest.raises(rt_codes.RpcError) as excinfo:
            call()
        assert excinfo.value.code == "session_kind_mismatch"
        assert excinfo.value.data["sessionKind"] == "workspace"
        assert excinfo.value.data["required"] == "document"


def test_workspace_inspect_on_a_document_session_is_refused(root, tmp_path):
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    core = rt_core.RuntimeCore(root)
    session_id = core.open_path(str(source))["sessionId"]
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.workspace_inspect(session_id)
    assert excinfo.value.code == "session_kind_mismatch"
    assert excinfo.value.data["required"] == "workspace"


def test_an_unknown_run_id_on_a_workspace_session_is_a_missing_candidate(
        root, workspace, enabled_all):
    """A workspace session HAS candidates now, so the answer changed.

    Before the write half it was ``invalid_params``: a workspace could not
    have a candidate at all. It can (§15.6), so an unknown
    runId gets the same answer a document session gives — the candidate is
    missing, not the concept.
    """
    core, session_id = opened(root, workspace)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.module_check(session_id, "style", run_id="0" * 32)
    assert excinfo.value.code == "artifact_missing"
    assert excinfo.value.data["runId"] == "0" * 32


def test_a_pre_kind_session_directory_still_reads_as_a_document(root, tmp_path):
    """A session opened before this kind existed has no ``kind`` member."""
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    core = rt_core.RuntimeCore(root)
    session_id = core.open_path(str(source))["sessionId"]
    meta_path = core.store.root / "sessions" / session_id / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("kind")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    reloaded = rt_session.Session.load(core.store.root, session_id)
    assert reloaded is not None and reloaded.kind == "document"


def test_session_list_carries_both_kinds(root, workspace, tmp_path):
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    core = rt_core.RuntimeCore(root)
    core.open_path(str(source))
    core.open_workspace(str(workspace))
    kinds = sorted(row["kind"] for row in core.session_list()["sessions"])
    assert kinds == ["document", "workspace"]


# --- module/check on a workspace: the real checkers -------------------------------

def test_every_workspace_checker_the_shipped_modules_declare_runs(
        root, workspace, enabled_all):
    """The measured close of GAP 20, on the real checkers.

    Counts, not adjectives: this checkout declares seventeen checkers across
    six modules — thirteen workspace-subject, four document-subject — and
    before this slice the thirteen were skipped by construction.
    """
    core, session_id = opened(root, workspace)
    ran, states = [], {}
    for module in WORKSPACE_MODULES:
        report = core.module_check(session_id, module)
        assert report["sessionKind"] == "workspace"
        assert report["subject"]["kind"] == "workspace"
        assert report["subject"]["sha256"] == \
            core.store.get(session_id).meta["workspaceTreeSha256"]
        for row in report["checks"]:
            states[row["checker"]] = row["state"]
            if row["state"] == "ran":
                ran.append(row["checker"])
    assert len(states) == 13, sorted(states)
    assert sorted(states) == sorted(ran), \
        {name: state for name, state in states.items() if state != "ran"}


def test_the_document_checkers_are_skipped_with_the_mirror_reason(
        root, workspace, enabled_all):
    core, session_id = opened(root, workspace)
    report = core.module_check(session_id, DOCUMENT_MODULE)
    row = report["checks"][0]
    assert row["state"] == "skipped"
    assert row["reason"] == "needs_document"
    assert row["ok"] is None
    # Skipped BEFORE anything spawned: no exit code, no duration.
    assert "exitCode" not in row
    assert report["ranAll"] is False
    assert report["acceptance"] is False


def test_the_same_module_is_skipped_the_other_way_on_a_document(root, tmp_path,
                                                               enabled_all):
    """The mirror is a mirror: the reason names which side is missing."""
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    core = rt_core.RuntimeCore(root)
    session_id = core.open_path(str(source))["sessionId"]
    report = core.module_check(session_id, "style")
    row = report["checks"][0]
    assert row["state"] == "skipped" and row["reason"] == "needs_workspace"


def test_a_workspace_has_no_baseline_and_none_is_claimed(root, workspace,
                                                         enabled_all):
    core, session_id = opened(root, workspace)
    report = core.module_check(session_id, "style")
    assert report["baseline"]["supplied"] is False
    assert "no blank form" in report["baseline"]["reason"]
    assert all(row.get("wantsUnsatisfied") == [] for row in report["checks"]
               if row["state"] == "ran")


def test_the_copy_cost_of_a_check_is_published(root, workspace, enabled_all):
    core, session_id = opened(root, workspace)
    report = core.module_check(session_id, "style")
    copy = report["bounds"]["subjectCopy"]
    assert copy["files"] == core.store.get(session_id).meta["workspaceFiles"]
    assert copy["treeSha256"] == \
        core.store.get(session_id).meta["workspaceTreeSha256"]
    assert copy["millis"] >= 0
    assert report["bounds"]["containment"] == "not_established"


def test_a_check_appends_one_event_and_open_appends_its_own(root, workspace,
                                                            enabled_all):
    core, session_id = opened(root, workspace)
    events = core.event_poll(session_id)["events"]
    assert [event["kind"] for event in events] == ["workspace.opened"]
    core.module_check(session_id, "style")
    events = core.event_poll(session_id)["events"]
    assert [event["kind"] for event in events] == ["workspace.opened",
                                                   "module.checked"]


# --- findings: workspace-relative locations, and no scratch paths ------------------

WRITER_SOURCE = """\
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
(root / "clobbered.txt").write_text("scribble", encoding="utf-8")
target = root / "bundle" / "content.md"
if target.is_file():
    target.write_text("destroyed", encoding="utf-8")
(pathlib.Path.cwd() / "sidecar.txt").write_text("scribble", encoding="utf-8")
print(json.dumps({"ok": True, "checker": "writer", "hard": [], "warn": [],
                  "counts": {"hard": 0, "warn": 0,
                             "sawPipelineMd": (root / "PIPELINE.md").is_file(),
                             "sawContentMd": (root / "bundle" / "content.md").is_file()},
                  "verdict": "pass"}))
sys.exit(0)
"""

PLACES_SOURCE = """\
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
print(json.dumps({
    "ok": False, "checker": "places", "verdict": "fail",
    "workspace": str(root),
    "hard": [
        {"code": "bare", "msg": "a whole path", "at": "bundle/content.md"},
        {"code": "lined", "msg": "a path and a line", "at": "bundle/content.md:12"},
        {"code": "absolute", "msg": "an absolute scratch path",
         "at": str(root / "claims.yaml")},
        {"code": "decorated", "msg": "a path plus prose",
         "at": "output/QUESTIONS.md numbers=[1,2]"},
        {"code": "absent", "msg": "a path that is not there",
         "at": "output/nothing.json"},
        {"code": "leaky", "msg": "the scratch path inside a message: " + str(root)}
    ],
    "warn": [], "counts": {"hard": 6, "warn": 0},
}))
sys.exit(3)
"""


def _synthetic_module(modules_root, name, entries):
    module = modules_root / name
    (module / "scripts").mkdir(parents=True, exist_ok=True)
    lines = ["schema: rigorloom-module/v1", f"name: {name}",
             'requires: { rigorloom: ">=0.1" }', "provides:", "  checkers:"]
    for entry in entries:
        script = f"{entry['name']}.py"
        (module / "scripts" / script).write_text(entry["source"], encoding="utf-8")
        lines.append("    - { name: %s, script: scripts/%s, subject: %s }"
                     % (entry["name"], script, entry["subject"]))
    (module / "module.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_enabled(modules_root / "enabled.yaml", [name])
    return module


@pytest.fixture()
def synthetic(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(rt_module.MODULES_ROOT_ENV, str(modules))
    monkeypatch.setenv(rt_module.MODULES_ENABLED_ENV, str(modules / "enabled.yaml"))
    return modules


def test_a_checker_that_writes_reaches_only_the_scratch(root, workspace,
                                                        synthetic):
    """Isolation as a property, not a promise about module authors.

    The checker clobbers ``bundle/content.md`` and drops a file at the
    workspace root and in its cwd. All of it lands in the per-call scratch,
    which is removed; the session copy keeps its tree hash and the operator's
    directory keeps its bytes.
    """
    _synthetic_module(synthetic, "rude", [
        {"name": "writer", "subject": "workspace", "source": WRITER_SOURCE}])
    original = (workspace / "bundle" / "content.md").read_bytes()
    core, session_id = opened(root, workspace)
    session = core.store.get(session_id)
    before = session.meta["workspaceTreeSha256"]

    report = core.module_check(session_id, "rude")
    row = report["checks"][0]
    assert row["state"] == "ran"
    # It really was handed a WORKSPACE — the whole tree, at its own paths —
    # and not an empty directory or a document.
    assert row["counts"]["sawPipelineMd"] is True
    assert row["counts"]["sawContentMd"] is True
    assert (workspace / "bundle" / "content.md").read_bytes() == original
    assert not (workspace / "clobbered.txt").exists()
    assert rt_workspace.copy_tree(session.workspace,
                                  root / "recheck")["treeSha256"] == before
    assert not list(session.dir.rglob("sidecar.txt"))
    assert not list(session.dir.rglob("clobbered.txt"))
    checks_dir = session.dir / "checks"
    assert not checks_dir.exists() or not any(checks_dir.iterdir())


def test_findings_carry_workspace_relative_places_and_no_scratch_paths(
        root, workspace, synthetic):
    _synthetic_module(synthetic, "picky", [
        {"name": "places", "subject": "workspace", "source": PLACES_SOURCE}])
    core, session_id = opened(root, workspace)
    report = core.module_check(session_id, "picky")
    row = report["checks"][0]
    assert row["state"] == "ran" and row["ok"] is False
    found = {finding["code"]: finding for finding in row["findings"]}

    assert found["bare"]["address"] == {"path": "bundle/content.md"}
    assert found["lined"]["address"] == {"path": "bundle/content.md", "line": 12}
    # An absolute scratch path becomes workspace-relative in BOTH fields.
    assert found["absolute"]["address"] == {"path": "claims.yaml"}
    assert found["absolute"]["location"] == "claims.yaml"
    # A path plus prose is not a path: the text is kept, the address is not
    # fabricated (§13.4's rule for cells, read for files).
    assert found["decorated"]["address"] is None
    assert "output/QUESTIONS.md" in found["decorated"]["location"]
    # A path the workspace does not have gets no address either.
    assert found["absent"]["address"] is None

    # Nothing anywhere in the answer carries the operator's tree or the temp
    # directory the checker actually ran in.
    blob = json.dumps(report, ensure_ascii=False)
    assert str(core.store.get(session_id).dir) not in blob
    assert "checks" + os.sep not in blob


# --- parity: the same answer through all three front ends --------------------------

def _shape(report):
    return {
        "module": report["module"],
        "sessionKind": report["sessionKind"],
        "selected": report["selected"],
        "ranAll": report["ranAll"],
        "acceptance": report["acceptance"],
        "counts": report["counts"],
        "subjectKind": report["subject"]["kind"],
        "subjectSha256": report["subject"]["sha256"],
        "rows": [{"checker": row["checker"], "state": row["state"],
                  "reason": row["reason"], "ok": row["ok"],
                  "verdict": row["verdict"]}
                 for row in report["checks"]],
    }


def test_the_cli_the_server_and_mcp_agree_on_a_workspace_check(
        tmp_path, workspace, enabled_all):
    root = tmp_path / "shared"
    session_id = run_cli(root, "open-workspace",
                         "--path", str(workspace)).result["sessionId"]

    from_cli = run_cli(root, "module-check", "--session", session_id,
                       "--module", "style").result
    with RuntimeClient(root, entry="agent") as agent:
        agent.initialize()
        from_server = agent.ok("module/check",
                               {"sessionId": session_id, "module": "style"})
    with McpClient(root) as mcp:
        mcp.initialize()
        from_mcp = mcp.ok("module_check",
                          {"sessionId": session_id, "module": "style"})
    assert _shape(from_cli) == _shape(from_server) == _shape(from_mcp)
    assert from_cli["checks"][0]["state"] == "ran"


def test_workspace_inspect_is_the_same_through_the_cli_and_mcp(
        tmp_path, workspace, enabled_all):
    root = tmp_path / "shared"
    session_id = run_cli(root, "open-workspace",
                         "--path", str(workspace)).result["sessionId"]
    from_cli = run_cli(root, "workspace", "--session", session_id).result
    with McpClient(root) as mcp:
        mcp.initialize()
        from_mcp = mcp.ok("workspace_inspect", {"sessionId": session_id})
    assert json.dumps(from_cli, sort_keys=True) == json.dumps(from_mcp,
                                                              sort_keys=True)


def test_require_parts_turns_an_absent_required_part_into_exit_three(
        tmp_path, workspace, enabled_all):
    root = tmp_path / "shared"
    session_id = run_cli(root, "open-workspace",
                         "--path", str(workspace)).result["sessionId"]
    plain = run_cli(root, "workspace", "--session", session_id)
    strict = run_cli(root, "workspace", "--session", session_id,
                     "--require-parts")
    assert plain.code == 0 and plain.payload["ok"] is True
    # The assembled workspace stops before stage 5, so some declared-required
    # outputs are genuinely absent — and saying so is the answer, not a failure.
    assert plain.result["layout"]["counts"]["absentRequired"] > 0
    assert strict.code == 3
    assert strict.payload["result"]["layout"]["counts"]["absentRequired"] > 0
