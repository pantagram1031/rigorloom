#!/usr/bin/env python3
"""S1 boundary suite: replay the Phase-1 CLI inventory and verify approval separation."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

TIMEOUT = 60

REPO = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

from rt_codes import RpcError  # noqa: E402
from rt_core import RuntimeCore  # noqa: E402

FORM_GIANMUN = REPO / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"
FORM_MINWON = REPO / "tests" / "corpus" / "forms" / "converted" / "jumin-deungchobon-sinchengseo.hwpx"
FORM_HR = REPO / "tests" / "corpus" / "forms" / "converted" / "moel-pyojun-geunrogyeyakseo-2013.hwpx"
FORM_GRANT = REPO / "tests" / "corpus" / "forms" / "converted" / "kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx"
FORM_HWP = REPO / "tests" / "corpus" / "forms" / "gongmun" / "gianmun-byeolji-1ho.hwp"
GUARD_BEFORE = REPO / "examples" / "guard" / "before.hwpx"
GUARD_AFTER = REPO / "examples" / "guard" / "after.hwpx"
ENABLED_YAML = REPO / "modules" / "enabled.yaml"


def _base_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _run_py(args: list[str], *, python_exe: str | None = None) -> subprocess.CompletedProcess[str]:
    exe = python_exe or sys.executable
    return subprocess.run(
        [exe, *args],
        cwd=str(REPO),
        env=_base_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT,
    )


def _runtime_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run_py([
        "runtime/scripts/cli.py",
        "--root", str(root),
        "--engine-root", str(REPO),
        *args,
    ])


def _pipeline_cli(subcmd: str, ws: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run_py([
        "modules/report/scripts/pipeline_ctl.py",
        subcmd,
        str(ws),
        *args,
    ])


def _enabled_modules_set() -> set[str]:
    if not ENABLED_YAML.is_file():
        return set()
    proc = _run_py(["pipeline/scripts/module_registry.py", "list"])
    if proc.returncode != 0:
        return set()
    data = json.loads(proc.stdout)
    return set(data.get("enabled") or [])


def _json_stdout(proc: subprocess.CompletedProcess[str], label: str) -> dict:
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"{label} did not emit valid JSON (exit={proc.returncode}): "
            f"stdout={proc.stdout[-400:]!r} stderr={proc.stderr[-400:]!r}"
        ) from exc


def test_inventory_static_help_and_probe_commands(tmp_path: Path) -> None:
    """Replay inventory rows 02, 05-14, 16-19, 34-37, 39-46c, 49 with isolated temp files."""
    # Row 02: doctor
    proc = _run_py(["runtime/scripts/cli.py", "doctor"])
    assert proc.returncode == 0
    _json_stdout(proc, "02-cli-doctor")

    # Row 05: guard exits 3 on protected change (distinct from prose_fidelity exit 1)
    proc = _run_py(["runtime/scripts/cli.py", "guard", str(GUARD_BEFORE), str(GUARD_AFTER)])
    assert proc.returncode == 3

    # Rows 06-14, 16, 18-19, 34-37, 39-41c, 46-46c (--help and read-only checks)
    zero_exit_cmds = [
        ["pipeline/scripts/module_registry.py", "--help"],
        ["pipeline/scripts/module_registry.py", "list"],
        ["engine/scripts/probe.py"],
        ["scripts/support_matrix.py", "--check"],
        ["scripts/support_matrix.py"],
        ["scripts/py_compile_sweep.py", "--help"],
        ["evals/score.py", "--help"],
        ["evals/cleanroom.py", "--help"],
        ["agenthost/scripts/host.py", "--help"],
        ["engine/scripts/form_inspect.py", "--help"],
        ["evals/cleanroom.py", "list-tasks"],
        ["modules/report/scripts/pipeline_ctl.py", "--help"],
        ["pipeline/scripts/doc_backend.py", "--help"],
        ["pipeline/scripts/privacy_scan.py", "runtime/scripts", "--json"],
        ["pipeline/scripts/render_probe.py", "--json"],
        ["agenthost/scripts/host.py", "--provider", "mock", "--capabilities"],
        ["desktop/scripts/agent_roundtrip.py", "--help"],
        ["runtime/scripts/serve.py", "--help"],
        ["scripts/bootstrap.py", "--help"],
        ["scripts/package_module.py", "--help"],
        ["scripts/sync_local.py", "--help"],
        ["modules/style/scripts/check_style.py", "--help"],
        ["modules/style/scripts/humanization_ctl.py", "--help"],
        ["modules/style/scripts/prose_fidelity.py", "--help"],
    ]
    for cmd in zero_exit_cmds:
        res = _run_py(cmd)
        assert res.returncode == 0, f"{cmd} failed (exit={res.returncode}): {res.stderr}"

    # Row 17: engine form_inspect writing fresh temp files
    profile_out = tmp_path / "profile.json"
    baseline_out = tmp_path / "baseline.json"
    res = _run_py([
        "engine/scripts/form_inspect.py",
        str(FORM_GIANMUN),
        "--out", str(profile_out),
        "--baseline", str(baseline_out),
    ])
    assert res.returncode == 0, res.stderr
    assert profile_out.is_file() and baseline_out.is_file()

    # Rows 42, 43, 44, 45: read-only module checkers on corpus forms
    for script, form in [
        ("modules/gongmun/scripts/check_gongmun.py", FORM_GIANMUN),
        ("modules/minwon/scripts/check_minwon.py", FORM_MINWON),
        ("modules/hr/scripts/check_hr.py", FORM_HR),
        ("modules/grant/scripts/check_grant.py", FORM_GRANT),
    ]:
        res = _run_py([script, str(form)])
        assert res.returncode == 0, f"{script} failed: {res.stderr}"

    # Row 49: hwp_ingress inspect
    res = _run_py(["pipeline/scripts/hwp_ingress.py", "inspect", str(FORM_HWP)])
    assert res.returncode == 0, res.stderr

    # Row 47: prose_fidelity exits 1 (distinct from guard exit 3)
    before_txt = tmp_path / "before.txt"
    after_txt = tmp_path / "after.txt"
    before_txt.write_text("총 예산은 30억원 18.6% 증가하였으나 변동은 없다.\n", encoding="utf-8")
    after_txt.write_text("총 예산은 30억원 19% 증가하였으나 변동은 있다.\n", encoding="utf-8")
    res = _run_py(["modules/style/scripts/prose_fidelity.py", str(before_txt), str(after_txt)])
    assert res.returncode == 1
    payload = _json_stdout(res, "47-prose-fidelity-check")
    assert payload["pass"] is False


def test_inventory_runtime_session_pipeline_and_agenthost_flow(tmp_path: Path) -> None:
    """Replay inventory rows 03-04, 20-33, 38, 40b, 42b with captured S/L/H/A/U."""
    runtime_root = tmp_path / "rt-root"
    ws = tmp_path / "pipeline-ws"
    ops_file = tmp_path / "ops.json"
    ops_file.write_text(
        json.dumps([{"kind": "fill_cell", "col": 1, "row": 5, "table": 0, "text": "김철수"}],
                   ensure_ascii=False),
        encoding="utf-8",
    )

    # Rows 03-04: capabilities, modules
    cap_res = _runtime_cli(runtime_root, "capabilities")
    assert cap_res.returncode == 0
    assert _json_stdout(cap_res, "03-capabilities")["ok"] is True

    mod_res = _runtime_cli(runtime_root, "modules")
    assert mod_res.returncode == 0
    assert _json_stdout(mod_res, "04-modules")["ok"] is True

    # Row 20: open -> S
    open_res = _runtime_cli(runtime_root, "open", "--path", str(FORM_GIANMUN))
    assert open_res.returncode == 0, open_res.stderr
    open_payload = _json_stdout(open_res, "20-open")
    session_obj = open_payload["result"].get("session") or open_payload["result"]
    s_id = session_obj["sessionId"]

    # Rows 21-23: inspect, render, read-region
    for args in [
        ("inspect", "--session", s_id, "--include", "summary,graph,regions,forbidden"),
        ("render", "--session", s_id, "--page", "0", "--no-inline"),
        ("read-region", "--session", s_id, "--region", "0:2,0", "--region", "0:5,1"),
    ]:
        res = _runtime_cli(runtime_root, *args)
        assert res.returncode == 0, f"{args} failed: {res.stderr}"

    # Row 24: propose -> L, H
    prop_res = _runtime_cli(runtime_root, "propose", "--session", s_id, "--backend", "preedit", "--ops-file", str(ops_file))
    assert prop_res.returncode == 0, prop_res.stderr
    plan_obj = _json_stdout(prop_res, "24-propose")["result"]["plan"]
    l_id = plan_obj["planId"]
    h_val = plan_obj["planHash"]

    # Row 25: validate
    val_res = _runtime_cli(runtime_root, "validate", "--plan", l_id)
    assert val_res.returncode == 0, val_res.stderr
    assert _json_stdout(val_res, "25-validate")["result"]["validation"]["ok"] is True

    # Row 26: request-approval -> A
    req_res = _runtime_cli(runtime_root, "request-approval", "--plan", l_id)
    assert req_res.returncode == 0, req_res.stderr
    a_id = _json_stdout(req_res, "26-request-approval")["result"]["approval"]["approvalId"]

    # Runtime failure before approval exits 3 (distinct from pipeline gate 1 and usage 2)
    unapproved_apply = _runtime_cli(runtime_root, "apply", "--plan", l_id, "--approval", a_id)
    assert unapproved_apply.returncode == 3

    # Row 27: approve
    app_res = _runtime_cli(
        runtime_root, "approve",
        "--approval", a_id,
        "--plan", l_id,
        "--plan-hash", h_val,
        "--approver", "audit-operator",
    )
    assert app_res.returncode == 0, app_res.stderr

    # Row 28: apply -> U
    apply_res = _runtime_cli(runtime_root, "apply", "--plan", l_id, "--approval", a_id)
    assert apply_res.returncode == 0, apply_res.stderr
    u_id = _json_stdout(apply_res, "28-apply")["result"]["candidate"]["runId"]

    # Rows 28b-28e, 29: verify, receipt, read-region --run, compare, geometry
    for args in [
        ("verify", "--session", s_id, "--run", u_id),
        ("receipt", "--session", s_id, "--run", u_id),
        ("read-region", "--session", s_id, "--region", "0:5,1", "--run", u_id),
        ("compare", "--session", s_id, "--run", u_id, "--region", "0:5,1"),
        ("geometry", "--session", s_id, "--page", "0"),
    ]:
        res = _runtime_cli(runtime_root, *args)
        assert res.returncode == 0, f"{args} failed: {res.stderr}"

    # Row 42b: check_gongmun against applied candidate artifact
    candidate_hwpx = runtime_root / "sessions" / s_id / "candidates" / u_id / "artifact.hwpx"
    assert candidate_hwpx.is_file()
    gongmun_res = _run_py([
        "modules/gongmun/scripts/check_gongmun.py",
        str(candidate_hwpx),
        "--baseline", str(FORM_GIANMUN),
    ])
    assert gongmun_res.returncode == 0, gongmun_res.stderr

    # Rows 38, 40b: agenthost mock run and mcp_server --list-tools against shared runtime root
    ah_res = _run_py([
        "agenthost/scripts/host.py",
        "--root", str(runtime_root),
        "--session", s_id,
        "--engine-root", str(REPO),
        "--provider", "mock",
        "--scenario", "propose-one",
    ])
    assert ah_res.returncode == 0, ah_res.stderr
    assert _json_stdout(ah_res, "38-agenthost-mock")["ok"] is True

    mcp_res = _run_py([
        "runtime/scripts/mcp_server.py",
        "--root", str(runtime_root),
        "--engine-root", str(REPO),
        "--list-tools",
    ])
    assert mcp_res.returncode == 0, mcp_res.stderr
    _json_stdout(mcp_res, "40b-mcp-list-tools")

    # Rows 30-33: pipeline_ctl init, resume, advance, gate (unapproved -> exit 1)
    init_res = _pipeline_cli(
        "init", ws,
        "--slug", "demo-audit",
        "--mode", "supervised",
        "--subject", "general",
        "--topic", "audit test",
        "--form", str(FORM_GIANMUN),
    )
    assert init_res.returncode == 0, init_res.stderr
    assert _pipeline_cli("resume", ws).returncode == 0
    assert _pipeline_cli("advance", ws, "0", "--status", "in_progress").returncode == 0
    gate_res = _pipeline_cli("gate", ws, "topic_pick", "--mode", "supervised")
    assert gate_res.returncode == 1
    assert _json_stdout(gate_res, "33-pipeline-gate")["ok"] is False

    # Missing plan / runtime refusal preserves exit 3 vs pipeline gate exit 1
    missing_plan_res = _runtime_cli(runtime_root, "validate", "--plan", "plan_does_not_exist")
    assert missing_plan_res.returncode == 3


def test_inventory_env_gated_rows_system_python_pytest() -> None:
    """Row 01: system python3 without pytest exits 1; skip if absent or pytest installed."""
    sys_python = shutil.which("python3", path="/usr/bin")
    if not sys_python:
        pytest.skip("requires /usr/bin/python3 without pytest")
    probe = _run_py(["-c", "import pytest"], python_exe=sys_python)
    if probe.returncode == 0:
        pytest.skip("requires /usr/bin/python3 without pytest installed")
    res = _run_py(["-m", "pytest", "-q", "tests/test_guard.py"], python_exe=sys_python)
    assert res.returncode == 1
    assert "No module named pytest" in res.stderr


def test_inventory_env_gated_rows_studio_fastapi() -> None:
    """Row 15: studio/main.py exits 1 when fastapi is absent."""
    if importlib.util.find_spec("fastapi") is not None:
        pytest.skip("requires environment without fastapi installed")
    res = _run_py(["studio/main.py"])
    assert res.returncode == 1
    assert "fastapi" in res.stderr


def test_inventory_disabled_module_exit_codes(tmp_path: Path) -> None:
    """Rows 28f, 41d, 48: disabled-module exit distinctions (3, 2, 3)."""
    enabled = _enabled_modules_set()

    # Row 41d: new_report --help exits 2 when report module is disabled
    if "report" in enabled:
        pytest.skip("requires report module disabled (modules/enabled.yaml absent)")
    nr_res = _run_py(["scripts/new_report.py", "--help"])
    assert nr_res.returncode == 2

    # Row 28f: runtime module-check on disabled module exits 3
    if "gongmun" in enabled:
        pytest.skip("requires gongmun module disabled")
    root = tmp_path / "disabled-mod-root"
    open_res = _runtime_cli(root, "open", "--path", str(FORM_GIANMUN))
    assert open_res.returncode == 0
    s_id = (_json_stdout(open_res, "open")["result"].get("session") or _json_stdout(open_res, "open")["result"])["sessionId"]
    mc_res = _runtime_cli(root, "module-check", "--session", s_id, "--module", "gongmun")
    assert mc_res.returncode == 3

    # Row 48: desktop/scripts/agent_roundtrip.py exits 3 when modules disabled
    if {"report", "style"} <= enabled:
        pytest.skip("requires disabled module state for inventory exit 3")
    rt_res = _run_py(["desktop/scripts/agent_roundtrip.py"])
    assert rt_res.returncode == 3


def test_pipeline_approvals_md_cannot_resolve_or_apply_runtime_plan(tmp_path: Path) -> None:
    """APPROVALS.md gate approvals have zero authority over Runtime plans/approvals."""
    shared_root = tmp_path / "shared-root"
    shared_root.mkdir(parents=True)

    core = RuntimeCore(shared_root, engine_root=REPO)
    opened = core.open_path(str(FORM_GIANMUN))
    s_id = (opened.get("session") or opened)["sessionId"]
    ops = [{"kind": "fill_cell", "col": 1, "row": 5, "table": 0, "text": "김철수"}]
    proposed = core.plan_propose(s_id, "preedit", ops, proposer="test-builder")
    l_id = proposed["plan"]["planId"]
    h_val = proposed["plan"]["planHash"]
    a_id = core.approval_request(l_id, requested_by="test-builder")["approval"]["approvalId"]

    # Initialize a pipeline workspace directly at the shared runtime root
    init_res = _pipeline_cli(
        "init", shared_root,
        "--slug", "boundary-check",
        "--mode", "supervised",
        "--subject", "general",
        "--topic", "boundary",
        "--form", str(FORM_GIANMUN),
    )
    assert init_res.returncode == 0, init_res.stderr

    approvals_md_text = "\n".join([
        "# Approvals",
        "topic_pick: approved by audit-operator at=2026-11-15T12:00:00Z",
        f"{l_id}: approved by audit-operator at=2026-11-15T12:00:00Z plan_hash={h_val}",
        f"{a_id}: approved by audit-operator at=2026-11-15T12:00:00Z",
        f"plan/apply: approved by audit-operator at=2026-11-15T12:00:00Z plan={l_id}",
        "",
    ])
    (shared_root / "APPROVALS.md").write_text(approvals_md_text, encoding="utf-8")

    # Confirm the pipeline gate CLI accepts APPROVALS.md as a pipeline gate approval
    gate_res = _pipeline_cli("gate", shared_root, "topic_pick", "--mode", "supervised")
    assert gate_res.returncode == 0, gate_res.stderr

    # 1. Sharing a root with APPROVALS.md leaves the runtime approval pending and apply refused
    assert core.approval_get(a_id)["approval"]["state"] == "pending"
    with pytest.raises(RpcError) as exc_info:
        core.plan_apply(l_id, a_id)
    assert exc_info.value.code == "plan_not_approved"
    assert _runtime_cli(shared_root, "apply", "--plan", l_id, "--approval", a_id).returncode == 3

    # 2. Passing a pipeline gate name or APPROVALS.md path as approval ID fails cleanly
    for bogus_id in ("topic_pick", "APPROVALS.md"):
        with pytest.raises(RpcError):
            core.plan_apply(l_id, bogus_id)
        assert _runtime_cli(shared_root, "apply", "--plan", l_id, "--approval", bogus_id).returncode == 3

    # 3. Copying APPROVALS.md into runtime approvals/ (either as APPROVALS.md or over <approvalId>.json)
    #    cannot trick RuntimeCore or CLI into resolving or applying the plan.
    approvals_dir = shared_root / "approvals"
    (approvals_dir / "APPROVALS.md").write_text(approvals_md_text, encoding="utf-8")
    (approvals_dir / "topic_pick.json").write_text(
        json.dumps({"gate": "topic_pick", "state": "approved", "planId": l_id, "planHash": h_val}),
        encoding="utf-8",
    )
    with pytest.raises(RpcError):
        core.plan_apply(l_id, a_id)
    with pytest.raises(RpcError):
        core.plan_apply(l_id, "topic_pick")
    assert _runtime_cli(shared_root, "apply", "--plan", l_id, "--approval", a_id).returncode == 3
    assert _runtime_cli(shared_root, "apply", "--plan", l_id, "--approval", "topic_pick").returncode == 3

    # Overwriting the approval record file with raw APPROVALS.md markdown text also fails cleanly
    (approvals_dir / f"{a_id}.json").write_text(approvals_md_text, encoding="utf-8")
    with pytest.raises(RpcError):
        core.plan_apply(l_id, a_id)
    assert _runtime_cli(shared_root, "apply", "--plan", l_id, "--approval", a_id).returncode == 3

    # Zero candidates were published during any of the refused apply attempts
    assert core.candidate_list(s_id)["candidates"] == []
