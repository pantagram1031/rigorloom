# -*- coding: utf-8 -*-
"""Runtime GAP 17: a distribution module's checkers, run against a session.

Two halves, and the second is the one that matters.

The HAPPY half runs the real ``gongmun`` module's real checker against the real
corpus 기안문 the rest of the runtime suite uses — the same document, so a
verdict here is about the product and not about a fixture written to agree with
it.

The HONESTY half is everything else. A checker that takes a report workspace,
a checker whose declaration says nothing, a checker that hangs, one that dies
on an import, one that prints nothing, one that exits 2: every one of them must
come back named, with a reason from the closed set, and must never be counted
as a pass. That is the property the whole method exists to keep, because a
verification surface that reports a skip as a pass is worse than no surface.

ON BOUNDS. ``HANG_BOUND_SECONDS`` is deliberately small and is NOT the mistake
tests/test_subprocess_bounds.py guards against. That guard is about a bound the
suite races the code with: a checker that would have finished at 9s under load
killed at 10s and read as a failure. Here the child sleeps for five minutes and
can never finish, so there is nothing to race — the kill IS the behaviour under
test, and a large bound would only make the test slow. The guard's own scope
agrees: it reads ``subprocess.run(timeout=…)`` in test files, and this is a
Runtime parameter, not a spawn kwarg.
"""
from __future__ import annotations

import json
import shutil

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
import rt_module  # noqa: E402
import rt_session  # noqa: E402

#: The real module whose real checker takes a document. Named here because the
#: TEST is allowed to know a module's name — core is not (modules/README.md
#: rule 1), and nothing under runtime/ or pipeline/ mentions it.
REAL_MODULE = "gongmun"
REAL_CHECKER = "check_gongmun"

#: See the module docstring. The child under this bound sleeps for five
#: minutes; there is no finish to race.
HANG_BOUND_SECONDS = 2.0

CLEAN_OP = {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "한빛"}


# --- synthetic modules --------------------------------------------------------

CLEAN_SOURCE = """\
import json, sys
print(json.dumps({"ok": True, "checker": "tidy", "hard": [], "warn": [],
                  "counts": {"hard": 0, "warn": 0}, "verdict": "pass"}))
sys.exit(0)
"""

FINDING_SOURCE = """\
import json, sys
print(json.dumps({
    "ok": False, "checker": "picky", "verdict": "fail",
    "hard": [{"code": "seat_wrong", "msg": "the seat is wrong",
              "at": {"table": 0, "addr": [1, 2]}}],
    "warn": [{"code": "soft", "msg": "a warning", "at": {"para": 7}}],
    "skipped": [{"rule": "needs_more", "reason": "no_baseline"}],
    "counts": {"hard": 1, "warn": 1},
}))
sys.exit(3)
"""

HANG_SOURCE = """\
import time
time.sleep(300)
"""

SILENT_SOURCE = """\
import sys
sys.exit(0)
"""

USAGE_SOURCE = """\
import json, sys
print(json.dumps({"ok": False, "verdict": "usage_error",
                  "error": "that is not a workspace"}))
sys.exit(2)
"""

IMPORT_FAIL_SOURCE = """\
import rigorloom_module_that_does_not_exist  # noqa: F401
"""

WRITER_SOURCE = """\
import json, pathlib, sys
subject = pathlib.Path(sys.argv[1])
subject.write_bytes(b"clobbered")
(pathlib.Path.cwd() / "sidecar.txt").write_text("scribble", encoding="utf-8")
print(json.dumps({"ok": True, "checker": "writer", "hard": [], "warn": [],
                  "counts": {"hard": 0, "warn": 0}, "verdict": "pass"}))
sys.exit(0)
"""

BASELINE_SOURCE = """\
import argparse, json, sys
parser = argparse.ArgumentParser()
parser.add_argument("artifact")
parser.add_argument("--baseline", default=None)
args = parser.parse_args()
print(json.dumps({"ok": True, "checker": "compares", "hard": [], "warn": [],
                  "counts": {"hard": 0, "warn": 0}, "verdict": "pass",
                  "baseline_seen": args.baseline is not None}))
sys.exit(0)
"""


def write_module(root, name, entries):
    """A throwaway distribution module on disk. ``entries`` are declarations."""
    module = root / name
    (module / "scripts").mkdir(parents=True, exist_ok=True)
    lines = ["schema: rigorloom-module/v1", f"name: {name}",
             'requires: { rigorloom: ">=0.1" }', "provides:", "  checkers:"]
    for entry in entries:
        script = f"{entry['name']}.py"
        (module / "scripts" / script).write_text(entry["source"], encoding="utf-8")
        body = f"name: {entry['name']}, script: scripts/{script}"
        if entry.get("subject") is not None:
            body += f", subject: {entry['subject']}"
        if entry.get("wants"):
            body += ", wants: [%s]" % ", ".join(entry["wants"])
        lines.append("    - { %s }" % body)
    (module / "module.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return module


def write_enabled(path, names):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("schema: rigorloom-enabled-modules/v1\n"
                    "enabled: [%s]\n" % ", ".join(names), encoding="utf-8")
    return path


# --- fixtures -----------------------------------------------------------------

@pytest.fixture()
def source(tmp_path):
    target = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, target)
    return target


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "root"


@pytest.fixture()
def real_modules(tmp_path, monkeypatch):
    """The checkout's own modules, with gongmun enabled for this test only.

    The enablement override exists so a test never writes the operator's
    ``modules/enabled.yaml`` — this checkout is core-only and must stay so.
    """
    enabled = write_enabled(tmp_path / "enablement" / "enabled.yaml", [REAL_MODULE])
    monkeypatch.setenv(rt_module.MODULES_ENABLED_ENV, str(enabled))
    monkeypatch.delenv(rt_module.MODULES_ROOT_ENV, raising=False)
    return enabled


@pytest.fixture()
def synthetic(tmp_path, monkeypatch):
    """A modules root this test owns entirely."""
    modules = tmp_path / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(rt_module.MODULES_ROOT_ENV, str(modules))
    monkeypatch.setenv(rt_module.MODULES_ENABLED_ENV, str(modules / "enabled.yaml"))
    return modules


def opened(root, source):
    core = rt_core.RuntimeCore(root)
    return core, core.open_path(str(source))["sessionId"]


# --- the derived surface -------------------------------------------------------

def test_the_new_methods_are_agent_methods_and_the_surfaces_follow():
    """The gate is not edited; it extends itself. That property is the point.

    ``rt_server`` asserts its handler map equals ``AGENT_METHODS`` at
    construction and ``mcp_server`` derives its whole tool table from the same
    tuple with a hard assert at import, so this only has to state the
    membership those two then enforce everywhere.
    """
    for method in ("module/list", "module/check"):
        assert method in rt_core.AGENT_METHODS
        assert method not in rt_core.HOST_ONLY_METHODS
        assert mcp_server.tool_name(method) in mcp_server.TOOL_TO_METHOD
        assert mcp_server.TOOL_SCHEMAS[method]["description"].strip()
    assert "module.checked" in rt_session.EVENT_KINDS


def test_an_agent_connection_can_reach_them(tmp_path, real_modules):
    with RuntimeClient(tmp_path / "agentroot", entry="agent") as agent:
        result = agent.initialize()["result"]
        assert "module/check" in result["capabilities"]["methods"]
        listing = agent.ok("module/list")
    assert REAL_MODULE in listing["discovered"]
    assert listing["enabled"] == [REAL_MODULE]


# --- module/list ----------------------------------------------------------------

def test_module_list_reports_the_installation_without_the_operators_paths(
        root, real_modules):
    core = rt_core.RuntimeCore(root)
    listing = core.module_list()
    assert set(listing["discovered"]) >= {REAL_MODULE}
    assert listing["enabled"] == [REAL_MODULE]
    by_name = {row["name"]: row for row in listing["modules"]}
    checkers = by_name[REAL_MODULE]["checkers"]
    row = next(entry for entry in checkers if entry["name"] == REAL_CHECKER)
    assert row["subject"] == "document"
    assert row["runnableAgainstDocument"] is True
    assert row["wants"] == ["baseline"]
    # A script path on the wire is module-relative, never the operator's tree.
    for module_row in listing["modules"]:
        for entry in module_row["checkers"]:
            assert not entry["script"].startswith("/")
            assert ":" not in entry["script"]
            assert listing["modulesRoot"] not in entry["script"]


def test_a_disabled_module_is_listed_and_says_it_contributes_nothing(
        root, real_modules):
    listing = rt_core.RuntimeCore(root).module_list()
    disabled = [row for row in listing["modules"] if not row["enabled"]]
    assert disabled, listing["modules"]
    assert all(row["name"] != REAL_MODULE for row in disabled)


def test_capabilities_carry_the_module_state(root, real_modules):
    snapshot = rt_core.RuntimeCore(root).capability_snapshot(methods=[])
    modules = snapshot["modules"]
    assert modules["state"] == "ready"
    assert modules["enabled"] == [REAL_MODULE]
    assert set(modules["skipReasons"]) == set(rt_module.SKIP_REASONS)
    assert set(modules["unavailableReasons"]) == set(rt_module.UNAVAILABLE_REASONS)
    assert modules["containment"] == "not_established"


# --- happy path, on the real module and the real corpus form ---------------------

def test_the_real_module_checker_runs_against_the_real_corpus_form(
        root, source, real_modules):
    core, session_id = opened(root, source)
    report = core.module_check(session_id, REAL_MODULE)

    assert report["module"] == REAL_MODULE
    assert report["selected"] == [REAL_CHECKER]
    assert report["subject"]["kind"] == "session_source"
    assert report["ranAll"] is True
    row = report["checks"][0]
    assert row["state"] == "ran" and row["reason"] is None
    assert row["exitCode"] == 0 and row["timedOut"] is False
    assert row["ok"] is True and row["verdict"] == "pass"
    assert row["durationMs"] >= 0
    # It really read the document: the checker's own counts are populated by
    # the blank 기안문's seats, which a fixture could not have produced.
    assert row["counts"]["seats"] > 0
    assert row["counts"]["guide_terms"] > 0
    # And its own per-rule skips arrive as findings rather than as silence.
    skipped = [f for f in row["findings"] if f["severity"] == "skipped"]
    assert skipped
    assert all(f["code"] for f in skipped)


def test_checking_the_source_is_partial_because_there_is_no_baseline(
        root, source, real_modules):
    """A document is never its own baseline, and the answer says so out loud."""
    core, session_id = opened(root, source)
    report = core.module_check(session_id, REAL_MODULE)
    row = report["checks"][0]
    assert row["wants"] == ["baseline"]
    assert row["wantsUnsatisfied"] == ["baseline"]
    assert row["partial"] is True
    assert report["baseline"]["supplied"] is False
    # ran + ok, and still NOT accepted: an input the checker declares it needs
    # was missing, so its verdict is thinner than a clean one.
    assert row["ok"] is True
    assert report["acceptance"] is False
    assert report["reason"] == "a checker ran without an input it declares it needs"
    assert report["counts"]["partial"] == 1


def test_a_check_leaves_the_session_bytes_and_the_scratch_alone(
        root, source, real_modules):
    core, session_id = opened(root, source)
    session = core.store.get(session_id)
    before = session.current_source_sha256()
    core.module_check(session_id, REAL_MODULE)
    assert session.current_source_sha256() == before
    assert session.meta["sourceSha256"] == before
    checks_dir = session.dir / "checks"
    assert not checks_dir.exists() or not any(checks_dir.iterdir())


def test_a_check_appends_one_event(root, source, real_modules):
    core, session_id = opened(root, source)
    before = len(core.event_poll(session_id)["events"])
    core.module_check(session_id, REAL_MODULE)
    events = core.event_poll(session_id)["events"]
    assert len(events) == before + 1
    last = events[-1]
    assert last["kind"] == "module.checked"
    assert last["detail"]["module"] == REAL_MODULE
    assert last["detail"]["acceptance"] is False


def test_a_candidate_is_checked_against_the_form_it_came_from(
        root, source, real_modules):
    """With a runId the baseline is not guessed: rt_apply built the candidate
    FROM the session source, so the source is the blank form by construction."""
    core, session_id = opened(root, source)
    plan = core.plan_propose(session_id, "preedit", [CLEAN_OP], "test")["plan"]
    core.plan_validate(plan["planId"])
    approval = core.approval_request(plan["planId"], "test")["approval"]
    core.approval_resolve(approval["approvalId"], plan["planId"],
                          plan["planHash"], "approved", "operator")
    run_id = core.plan_apply(plan["planId"], approval["approvalId"])[
        "candidate"]["runId"]

    report = core.module_check(session_id, REAL_MODULE, run_id=run_id)
    assert report["subject"]["kind"] == "candidate"
    assert report["subject"]["runId"] == run_id
    assert report["baseline"]["supplied"] is True
    assert report["baseline"]["kind"] == "session_source"
    row = report["checks"][0]
    assert row["state"] == "ran"
    assert row["wantsUnsatisfied"] == []
    assert row["partial"] is False
    assert report["ranAll"] is True


# --- honesty: a checker that did not run is never a pass -------------------------

def test_a_workspace_checker_is_skipped_and_never_run(root, source, synthetic):
    write_module(synthetic, "twosided", [
        {"name": "doc_side", "subject": "document", "source": CLEAN_SOURCE},
        {"name": "ws_side", "subject": "workspace", "source": WRITER_SOURCE},
    ])
    write_enabled(synthetic / "enabled.yaml", ["twosided"])
    core, session_id = opened(root, source)
    report = core.module_check(session_id, "twosided")

    rows = {row["checker"]: row for row in report["checks"]}
    assert rows["ws_side"]["state"] == "skipped"
    assert rows["ws_side"]["reason"] == "needs_workspace"
    assert rows["ws_side"]["ok"] is None
    # It was skipped BEFORE anything spawned: no exit code, no duration.
    assert "exitCode" not in rows["ws_side"]
    assert rows["doc_side"]["state"] == "ran"
    assert report["ranAll"] is False
    assert report["acceptance"] is False
    assert report["counts"] == {"selected": 2, "ran": 1, "skipped": 1,
                                "unavailable": 0, "partial": 0,
                                "hard": 0, "warn": 0}


def test_an_undeclared_subject_is_skipped_rather_than_guessed(
        root, source, synthetic):
    write_module(synthetic, "mute", [
        {"name": "unsaid", "subject": None, "source": WRITER_SOURCE},
    ])
    write_enabled(synthetic / "enabled.yaml", ["mute"])
    core, session_id = opened(root, source)
    report = core.module_check(session_id, "mute")
    row = report["checks"][0]
    assert row["subject"] is None
    assert row["state"] == "skipped"
    assert row["reason"] == "subject_undeclared"
    assert report["acceptance"] is False
    assert report["ranAll"] is False


def test_a_hung_checker_is_killed_and_the_pack_finishes(root, source, synthetic):
    """The bound is per checker, so one hang does not cost the other rows."""
    write_module(synthetic, "slow", [
        {"name": "aaa_hangs", "subject": "document", "source": HANG_SOURCE},
        {"name": "bbb_fine", "subject": "document", "source": CLEAN_SOURCE},
    ])
    write_enabled(synthetic / "enabled.yaml", ["slow"])
    core, session_id = opened(root, source)
    report = core.module_check(session_id, "slow",
                               timeout=HANG_BOUND_SECONDS)

    rows = {row["checker"]: row for row in report["checks"]}
    hung = rows["aaa_hangs"]
    assert hung["state"] == "unavailable"
    assert hung["reason"] == "timed_out"
    assert hung["timedOut"] is True
    assert hung["ok"] is None
    # The one after it still ran: the bound is per checker, not per call.
    assert rows["bbb_fine"]["state"] == "ran"
    assert report["ranAll"] is False
    assert report["acceptance"] is False
    assert report["bounds"]["perCheckerSeconds"] == HANG_BOUND_SECONDS
    assert report["bounds"]["worstCaseSeconds"] == HANG_BOUND_SECONDS * 2


def test_the_runtime_survives_a_hang_and_answers_the_next_call(
        root, source, synthetic):
    write_module(synthetic, "slow", [
        {"name": "hangs", "subject": "document", "source": HANG_SOURCE},
    ])
    write_enabled(synthetic / "enabled.yaml", ["slow"])
    core, session_id = opened(root, source)
    core.module_check(session_id, "slow", timeout=HANG_BOUND_SECONDS)
    assert core.document_inspect(session_id, ["summary"])["sessionId"] == session_id


@pytest.mark.parametrize("name,script,reason", [
    ("mum", SILENT_SOURCE, "no_verdict"),
    ("broken", IMPORT_FAIL_SOURCE, "missing_dependency"),
    ("misused", USAGE_SOURCE, "usage_error"),
])
def test_a_checker_that_produced_no_usable_verdict_is_unavailable(
        root, source, synthetic, name, script, reason):
    write_module(synthetic, "assorted", [
        {"name": name, "subject": "document", "source": script},
    ])
    write_enabled(synthetic / "enabled.yaml", ["assorted"])
    core, session_id = opened(root, source)
    report = core.module_check(session_id, "assorted")
    row = report["checks"][0]
    assert row["state"] == "unavailable"
    assert row["reason"] == reason
    assert row["ok"] is None
    assert row["detail"]
    assert report["ranAll"] is False
    assert report["acceptance"] is False


def test_every_not_run_reason_is_in_the_closed_set(root, source, synthetic):
    """A reason nobody declared is a reason nobody can branch on."""
    write_module(synthetic, "mixed", [
        {"name": "a_mute", "subject": None, "source": SILENT_SOURCE},
        {"name": "b_ws", "subject": "workspace", "source": SILENT_SOURCE},
        {"name": "c_silent", "subject": "document", "source": SILENT_SOURCE},
        {"name": "d_broken", "subject": "document", "source": IMPORT_FAIL_SOURCE},
        {"name": "e_usage", "subject": "document", "source": USAGE_SOURCE},
    ])
    write_enabled(synthetic / "enabled.yaml", ["mixed"])
    core, session_id = opened(root, source)
    report = core.module_check(session_id, "mixed")
    reasons = {row["checker"]: row["reason"] for row in report["checks"]}
    assert set(reasons.values()) <= set(rt_module.NOT_RUN_REASONS)
    assert len(set(reasons.values())) == 5
    assert report["counts"]["ran"] == 0
    assert report["acceptance"] is False


def test_acceptance_is_true_only_when_everything_ran_clean_and_complete(
        root, source, synthetic):
    write_module(synthetic, "tidy", [
        {"name": "spotless", "subject": "document", "source": CLEAN_SOURCE},
    ])
    write_enabled(synthetic / "enabled.yaml", ["tidy"])
    core, session_id = opened(root, source)
    report = core.module_check(session_id, "tidy")
    assert report["ranAll"] is True
    assert report["acceptance"] is True
    assert report["reason"] is None


def test_a_declared_baseline_that_cannot_be_supplied_marks_the_row_partial(
        root, source, synthetic):
    write_module(synthetic, "comparer", [
        {"name": "compares", "subject": "document", "wants": ["baseline"],
         "source": BASELINE_SOURCE},
    ])
    write_enabled(synthetic / "enabled.yaml", ["comparer"])
    core, session_id = opened(root, source)
    report = core.module_check(session_id, "comparer")
    row = report["checks"][0]
    assert row["state"] == "ran" and row["ok"] is True
    assert row["partial"] is True and row["wantsUnsatisfied"] == ["baseline"]
    assert report["acceptance"] is False


# --- findings -------------------------------------------------------------------

def test_findings_carry_severity_and_a_translated_address(
        root, source, synthetic):
    write_module(synthetic, "picky", [
        {"name": "picky", "subject": "document", "source": FINDING_SOURCE},
    ])
    write_enabled(synthetic / "enabled.yaml", ["picky"])
    core, session_id = opened(root, source)
    report = core.module_check(session_id, "picky")
    row = report["checks"][0]
    assert row["state"] == "ran" and row["exitCode"] == 3 and row["ok"] is False

    by_severity = {finding["severity"]: finding for finding in row["findings"]}
    assert set(by_severity) == {"hard", "warn", "skipped"}
    assert by_severity["hard"]["code"] == "seat_wrong"
    # {table, addr:[r, c]} is the engine's shape; the wire carries the
    # Runtime's own addressing so the Desktop can select the cell.
    assert by_severity["hard"]["address"] == {"table": 0, "row": 1, "col": 2}
    assert by_severity["warn"]["address"] == {"atPara": 7}
    # A rule-level skip has no place, and is not given a fabricated one.
    assert by_severity["skipped"]["address"] is None
    assert by_severity["skipped"]["code"] == "needs_more"
    assert report["counts"]["hard"] == 1 and report["counts"]["warn"] == 1
    assert report["acceptance"] is False


# --- containment ------------------------------------------------------------------

def test_a_checker_that_writes_can_only_reach_the_scratch_copy(
        root, source, synthetic):
    """The read-only claim is a property, not a promise about module authors.

    ``WRITER_SOURCE`` clobbers its subject and drops a file in its cwd. Both
    land in the per-call scratch directory, which is removed; the session copy
    keeps its hash and the operator's original is not even in the tree.
    """
    write_module(synthetic, "rude", [
        {"name": "writer", "subject": "document", "source": WRITER_SOURCE},
    ])
    write_enabled(synthetic / "enabled.yaml", ["rude"])
    core, session_id = opened(root, source)
    session = core.store.get(session_id)
    before = session.current_source_sha256()
    original = source.read_bytes()

    report = core.module_check(session_id, "rude")
    assert report["checks"][0]["state"] == "ran"
    assert session.current_source_sha256() == before
    assert source.read_bytes() == original
    assert not list(session.dir.rglob("sidecar.txt"))
    checks_dir = session.dir / "checks"
    assert not checks_dir.exists() or not any(checks_dir.iterdir())


# --- refusals -----------------------------------------------------------------------

def test_a_module_that_is_present_but_not_enabled_is_refused(
        root, source, real_modules):
    core, session_id = opened(root, source)
    with pytest.raises(Exception) as excinfo:
        core.module_check(session_id, "report")
    error = excinfo.value
    assert error.code == "capability_unavailable"
    assert "report" in error.data["declared"]
    assert error.data["enabled"] == [REAL_MODULE]


def test_a_module_nobody_declared_is_refused(root, source, real_modules):
    core, session_id = opened(root, source)
    with pytest.raises(Exception) as excinfo:
        core.module_check(session_id, "nosuchmodule")
    assert excinfo.value.code == "capability_unavailable"
    assert excinfo.value.data["module"] == "nosuchmodule"


def test_a_checker_the_module_does_not_declare_is_a_usage_refusal(
        root, source, real_modules):
    core, session_id = opened(root, source)
    with pytest.raises(Exception) as excinfo:
        core.module_check(session_id, REAL_MODULE, checkers=["check_nothing"])
    assert excinfo.value.code == "invalid_params"
    assert excinfo.value.data["unknown"] == ["check_nothing"]


@pytest.mark.parametrize("bad", [0, -1, 10_000, "soon", True])
def test_an_out_of_range_bound_is_refused(root, source, real_modules, bad):
    core, session_id = opened(root, source)
    with pytest.raises(Exception) as excinfo:
        core.module_check(session_id, REAL_MODULE, timeout=bad)
    assert excinfo.value.code == "invalid_params"


# --- parity: the same answer through all three front ends --------------------------

def _shape(report):
    """What every front end must agree about, identity and timing removed."""
    return {
        "module": report["module"],
        "selected": report["selected"],
        "ranAll": report["ranAll"],
        "acceptance": report["acceptance"],
        "reason": report["reason"],
        "counts": report["counts"],
        "subjectKind": report["subject"]["kind"],
        "subjectSha256": report["subject"]["sha256"],
        "baselineSupplied": report["baseline"]["supplied"],
        "rows": [
            {
                "checker": row["checker"],
                "state": row["state"],
                "reason": row["reason"],
                "ok": row["ok"],
                "verdict": row["verdict"],
                "findings": row.get("findings"),
                "partial": row.get("partial"),
                "wantsUnsatisfied": row.get("wantsUnsatisfied"),
            }
            for row in report["checks"]
        ],
    }


def test_the_cli_the_server_and_mcp_agree_on_the_result(
        root, source, real_modules):
    session_id = run_cli(root, "open", "--path", str(source)).result["sessionId"]

    cli = run_cli(root, "module-check", "--session", session_id,
                  "--module", REAL_MODULE)
    assert cli.code == 0
    from_cli = cli.result

    with RuntimeClient(root, entry="agent") as agent:
        agent.initialize()
        from_server = agent.ok("module/check",
                               {"sessionId": session_id, "module": REAL_MODULE})

    with McpClient(root) as mcp:
        mcp.initialize()
        from_mcp = mcp.ok("module_check",
                          {"sessionId": session_id, "module": REAL_MODULE})

    assert _shape(from_cli) == _shape(from_server) == _shape(from_mcp)
    assert from_cli["checks"][0]["state"] == "ran"


def test_module_list_is_the_same_through_the_cli_and_mcp(root, real_modules):
    from_cli = run_cli(root, "modules").result
    with McpClient(root) as mcp:
        mcp.initialize()
        from_mcp = mcp.ok("module_list")
    assert json.dumps(from_cli, sort_keys=True) == json.dumps(from_mcp,
                                                              sort_keys=True)


def test_require_checks_turns_a_partial_report_into_exit_three(
        root, source, real_modules):
    """The report is still printed. A caller that wants the acceptance as an
    exit code gets one; a caller that wants the findings still gets them."""
    session_id = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    plain = run_cli(root, "module-check", "--session", session_id,
                    "--module", REAL_MODULE)
    strict = run_cli(root, "module-check", "--session", session_id,
                     "--module", REAL_MODULE, "--require-checks")
    assert plain.code == 0 and plain.payload["ok"] is True
    assert strict.code == 3
    assert strict.payload["result"]["checks"][0]["state"] == "ran"
    assert strict.payload["result"]["acceptance"] is False


def test_the_mcp_tool_refuses_a_disabled_module_as_a_tool_error(
        root, source, real_modules):
    session_id = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    with McpClient(root) as mcp:
        mcp.initialize()
        error = mcp.err("module_check",
                        {"sessionId": session_id, "module": "report"})
    assert error["code"] == "capability_unavailable"
    assert "report" in error["data"]["declared"]
