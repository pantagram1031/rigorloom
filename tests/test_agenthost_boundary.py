"""Tests for Agent Host authority and storage boundary (S7c)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO_ROOT / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))
TESTS_DIR = REPO_ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from _agenthost_support import agenthost_scripts_on_path  # noqa: E402

agenthost_scripts_on_path()

import ah_compile  # noqa: E402
import ah_mock  # noqa: E402
import mcp_server  # noqa: E402
import mock_agent  # noqa: E402
import rt_core  # noqa: E402
from ah_codes import AgentHostError  # noqa: E402
from ah_events import EventLog  # noqa: E402
from ah_host import AgentHost  # noqa: E402
from ah_provider import ToolCall  # noqa: E402

CORPUS_FORM = REPO_ROOT / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"
AGENTHOST_SCRIPTS = REPO_ROOT / "agenthost" / "scripts"


def test_allowed_tools_matches_agent_methods_minus_initialize():
    expected = {
        mcp_server.tool_name(method): method
        for method in rt_core.AGENT_METHODS
        if method != "initialize"
    }
    assert ah_compile.ALLOWED_TOOLS == expected
    assert "initialize" not in ah_compile.ALLOWED_TOOLS
    assert set(ah_compile.ALLOWED_TOOLS).isdisjoint(rt_core.HOST_ONLY_METHODS)
    assert set(ah_compile.ALLOWED_TOOLS).isdisjoint(
        {mcp_server.tool_name(m) for m in rt_core.HOST_ONLY_METHODS}
    )


@pytest.mark.parametrize("host_method", sorted(rt_core.HOST_ONLY_METHODS))
def test_every_host_only_method_is_refused_in_both_spellings(host_method: str):
    underscored = mcp_server.tool_name(host_method)
    for spelling in (host_method, underscored):
        with pytest.raises(AgentHostError) as exc_info:
            ah_compile.compile_tool_call(
                ToolCall(call_id=f"call-{underscored}", name=spelling, arguments={})
            )
        assert exc_info.value.code == "tool_forbidden"
        assert spelling in ah_compile.FORBIDDEN_TOOLS


def test_agenthost_keeps_no_local_plan_store_and_escalate_leaves_runtime_untouched(tmp_path: Path):
    # Static check: agenthost/scripts imports no runtime host write/apply modules or raw engine workers
    # and references no local plan-store directory names.
    forbidden_modules = {
        "rt_apply",
        "rt_session",
        "preedit",
        "xml_backend",
        "com_backend",
        "story_edit",
        "fill_report",
        "build_report",
        "tidy_hwpx",
    }
    for py_file in sorted(AGENTHOST_SCRIPTS.glob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                names = []
            for mod_name in names:
                leaf = mod_name.split(".")[-1]
                assert leaf not in forbidden_modules, f"{py_file.name} imports {mod_name}"
        assert "PlanStore" not in source, f"{py_file.name} defines or uses PlanStore"

    # End-to-end escalate check over an agent door: plan/apply is compiled/refused before
    # touching Runtime, Runtime plans/approvals remain host-controlled, and no agenthost store exists.
    root = tmp_path / "runtime-root"
    core = rt_core.RuntimeCore(root, engine_root=REPO_ROOT)
    opened = core.open_path(str(CORPUS_FORM))
    session_id = (opened.get("session") or opened)["sessionId"]

    events_path = tmp_path / "agenthost-events.jsonl"
    log = EventLog(path=events_path)
    with mock_agent.open_door("protocol", root=root, engine_root=REPO_ROOT) as door:
        result = AgentHost(door, ah_mock.MockProvider(scenario="escalate"), events=log).run(
            "apply without approval",
            session_id=session_id,
        )

    forbidden = [row for row in result["refusals"] if row["code"] == "tool_forbidden"]
    assert forbidden and forbidden[0]["stage"] == "compile"
    event_records = list(events_path.read_text(encoding="utf-8").splitlines())
    assert any("tool_forbidden" in line for line in event_records)
    assert core.candidate_list(session_id)["candidates"] == []
    if (root / "candidates").exists():
        assert [p.name for p in (root / "candidates").iterdir()] == []
    # AgentHost creates no plan/approval/candidate files next to its event log or scripts.
    assert [p.name for p in tmp_path.iterdir() if p.name in {"plans", "approvals", "candidates"}] == []
