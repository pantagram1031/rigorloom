#!/usr/bin/env python3
"""S3 boundary tests: read-only RuntimeCore.plan_preview and rt_ui delegation."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = REPO / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

import rt_guard  # noqa: E402
import rt_ui  # noqa: E402
from rt_codes import RpcError  # noqa: E402
from rt_core import (  # noqa: E402
    AGENT_METHODS,
    HOST_ONLY_METHODS,
    METHODS,
    PROTOCOL_ONLY_METHODS,
    RuntimeCore,
)
from rt_session import sha256_file  # noqa: E402

CORPUS_FORM = REPO / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"

OPS_BASE = [
    {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "한빛"},
]
OPS_CHAIN = [
    {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "두빛", "overwrite": True},
    {"kind": "fill_cell", "table": 0, "row": 6, "col": 1, "text": "30", "overwrite": True},
]


def _copy_form(tmp_path: Path, name: str = "form.hwpx") -> Path:
    dst = tmp_path / name
    shutil.copyfile(CORPUS_FORM, dst)
    return dst


def _snapshot_root(root: Path) -> tuple[set[str], dict[str, bytes]]:
    dirs = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_dir()
    }
    files = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }
    return dirs, files


def _strip_diff_labels(diff_payload: dict) -> dict:
    cleaned = dict(diff_payload)
    cleaned.pop("before", None)
    cleaned.pop("after", None)
    return cleaned


def test_plan_preview_does_not_expose_new_wire_methods() -> None:
    """S3 keeps the Runtime JSON-RPC wire roster unchanged."""
    for roster in (AGENT_METHODS, HOST_ONLY_METHODS, PROTOCOL_ONLY_METHODS, METHODS):
        assert "plan/preview" not in roster
        assert "plan_preview" not in roster


def test_plan_preview_stale_source_refuses_without_mutating_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    core = RuntimeCore(root, engine_root=REPO)
    source = _copy_form(tmp_path)
    opened = core.open_path(str(source))
    s_id = (opened.get("session") or opened)["sessionId"]

    plan = core.plan_propose(s_id, "preedit", OPS_BASE, proposer="test-builder")["plan"]
    session = core.store.get(s_id)
    # Tamper / advance session source on disk after proposal
    session.source.write_bytes(b"stale-modified-bytes")
    before_snap = _snapshot_root(root)

    with pytest.raises(RpcError) as exc_info:
        core.plan_preview(s_id, plan["planId"], out_path=tmp_path / "out.hwpx")
    assert exc_info.value.code == "plan_stale"
    assert not (tmp_path / "out.hwpx").exists()
    assert _snapshot_root(root) == before_snap

    bridge = rt_ui.BridgeApplication(root=root, engine_root=REPO, explicit_root=True)
    with pytest.raises(rt_ui.BridgeError) as b_exc:
        bridge.guard_diff({"sessionId": s_id, "planId": plan["planId"]})
    assert b_exc.value.code == "plan_stale"
    assert _snapshot_root(root) == before_snap


def test_plan_preview_tampered_base_candidate_refuses_without_mutation(tmp_path: Path) -> None:
    root = tmp_path / "root"
    core = RuntimeCore(root, engine_root=REPO)
    source = _copy_form(tmp_path)
    opened = core.open_path(str(source))
    s_id = (opened.get("session") or opened)["sessionId"]

    plan1 = core.plan_propose(s_id, "preedit", OPS_BASE, proposer="test-builder")["plan"]
    core.plan_validate(plan1["planId"])
    app1 = core.approval_request(plan1["planId"], requested_by="test-builder")["approval"]
    core.approval_resolve(app1["approvalId"], plan1["planId"], plan1["planHash"], "approved", "op")
    run1 = core.plan_apply(plan1["planId"], app1["approvalId"])["candidate"]["runId"]

    plan2 = core.plan_propose(
        s_id, "preedit", OPS_CHAIN, proposer="test-builder", base_run_id=run1,
    )["plan"]

    artifact1 = root / "sessions" / s_id / "candidates" / run1 / "artifact.hwpx"
    raw = bytearray(artifact1.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    artifact1.write_bytes(bytes(raw))
    before_snap = _snapshot_root(root)

    with pytest.raises(RpcError) as exc_info:
        core.plan_preview(s_id, plan2["planId"], out_path=tmp_path / "chained-out.hwpx")
    assert exc_info.value.code == "candidate_hash_mismatch"
    assert not (tmp_path / "chained-out.hwpx").exists()
    assert _snapshot_root(root) == before_snap

    bridge = rt_ui.BridgeApplication(root=root, engine_root=REPO, explicit_root=True)
    with pytest.raises(rt_ui.BridgeError) as b_exc:
        bridge.guard_diff({"sessionId": s_id, "planId": plan2["planId"]})
    assert b_exc.value.code == "candidate_hash_mismatch"
    assert _snapshot_root(root) == before_snap


def test_chained_preview_to_apply_diff_parity_and_read_only_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    core = RuntimeCore(root, engine_root=REPO)
    source = _copy_form(tmp_path)
    opened = core.open_path(str(source))
    s_id = (opened.get("session") or opened)["sessionId"]
    orig_source_sha = sha256_file(core.store.get(s_id).source)[0]

    # Step 1: produce base candidate run1
    plan1 = core.plan_propose(s_id, "preedit", OPS_BASE, proposer="test-builder")["plan"]
    core.plan_validate(plan1["planId"])
    app1 = core.approval_request(plan1["planId"], requested_by="test-builder")["approval"]
    core.approval_resolve(app1["approvalId"], plan1["planId"], plan1["planHash"], "approved", "op")
    run1 = core.plan_apply(plan1["planId"], app1["approvalId"])["candidate"]["runId"]

    # Step 2: propose chained plan2 -> validate -> request & approve approval2, WITHOUT applying
    plan2 = core.plan_propose(
        s_id, "preedit", OPS_CHAIN, proposer="test-builder", base_run_id=run1,
    )["plan"]
    core.plan_validate(plan2["planId"])
    app2 = core.approval_request(plan2["planId"], requested_by="test-builder")["approval"]
    core.approval_resolve(app2["approvalId"], plan2["planId"], plan2["planHash"], "approved", "op")

    # Remove cached profile directory entry if any was created only for base, to ensure preview
    # does not populate or alter session/profile/events/plans/approvals/candidates/apply-attempts.
    snap_before_preview = _snapshot_root(root)
    candidates_before = [c["runId"] for c in core.candidate_list(s_id)["candidates"]]

    preview_hwpx = tmp_path / "preview-dir" / "preview.hwpx"
    preview_res = core.plan_preview(s_id, plan2["planId"], out_path=preview_hwpx)
    assert preview_hwpx.is_file()
    assert preview_res["sessionId"] == s_id
    assert preview_res["planId"] == plan2["planId"]

    bridge = rt_ui.BridgeApplication(root=root, engine_root=REPO, explicit_root=True)
    preview_diff = bridge.guard_diff({"sessionId": s_id, "planId": plan2["planId"]})

    # Verify zero mutation across entire runtime root, source unchanged, no publication,
    # and approval2 remains approved/unconsumed.
    assert _snapshot_root(root) == snap_before_preview
    assert sha256_file(core.store.get(s_id).source)[0] == orig_source_sha
    assert [c["runId"] for c in core.candidate_list(s_id)["candidates"]] == candidates_before
    assert core.approval_get(app2["approvalId"])["approval"]["state"] == "approved"

    # Now actually apply plan2 using the unconsumed approval2
    applied2 = core.plan_apply(plan2["planId"], app2["approvalId"])
    run2 = applied2["candidate"]["runId"]
    artifact2 = root / "sessions" / s_id / "candidates" / run2 / "artifact.hwpx"

    assert preview_hwpx.read_bytes() == artifact2.read_bytes()
    assert preview_res["preview"]["sha256"] == applied2["candidate"]["candidate"]["sha256"]
    assert rt_guard.guard(preview_hwpx, artifact2)["pass"] is True

    apply_diff = bridge.guard_diff({
        "sessionId": s_id,
        "againstRunId": run1,
        "runId": run2,
    })
    assert preview_diff["before"] == f"run:{run1}"
    assert apply_diff["before"] == f"run:{run1}"
    assert preview_diff["after"] == f"plan:{plan2['planId']}"
    assert apply_diff["after"] == f"run:{run2}"
    assert _strip_diff_labels(preview_diff) == _strip_diff_labels(apply_diff)


def test_old_root_two_sessions_root_records_and_ignores_session_local_decoy(tmp_path: Path) -> None:
    """Authoritative plans live under root/plans/; session-local decoys and other sessions are ignored/refused."""
    root = tmp_path / "root"
    core = RuntimeCore(root, engine_root=REPO)
    src1 = _copy_form(tmp_path, "form1.hwpx")
    src2 = _copy_form(tmp_path, "form2.hwpx")

    o1 = core.open_path(str(src1))
    o2 = core.open_path(str(src2))
    s1 = (o1.get("session") or o1)["sessionId"]
    s2 = (o2.get("session") or o2)["sessionId"]

    p1 = core.plan_propose(
        s1, "preedit", [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "진짜값"}],
        proposer="test-builder",
    )["plan"]
    p2 = core.plan_propose(
        s2, "preedit", [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "세션2값"}],
        proposer="test-builder",
    )["plan"]
    core.approval_request(p1["planId"], requested_by="test-builder")

    # Verify records live at root-level plans/ and approvals/
    assert (root / "plans" / f"{p1['planId']}.json").is_file()
    assert (root / "plans" / f"{p2['planId']}.json").is_file()

    # Plant session-local decoys under sessions/<s1>/plans/ that rt_ui's old _load_plan_record used to prefer
    decoy_dir = root / "sessions" / s1 / "plans"
    decoy_dir.mkdir(parents=True, exist_ok=True)
    decoy_same_id = dict(p1)
    decoy_same_id["ops"] = [
        {"opId": p1["ops"][0]["opId"], "kind": "fill_cell",
         "params": {"table": 0, "row": 5, "col": 1, "text": "가짜값"}},
    ]
    (decoy_dir / f"{p1['planId']}.json").write_text(json.dumps(decoy_same_id), encoding="utf-8")
    decoy_only = dict(decoy_same_id)
    decoy_only["planId"] = "plan_decoy_only"
    (decoy_dir / "plan_decoy_only.json").write_text(json.dumps(decoy_only), encoding="utf-8")

    snap_with_decoys = _snapshot_root(root)
    bridge = rt_ui.BridgeApplication(root=root, engine_root=REPO, explicit_root=True)

    # Preview via Core and Bridge resolves the authoritative root plan, not the session-local decoy
    preview_out = tmp_path / "s1-preview.hwpx"
    core.plan_preview(s1, p1["planId"], out_path=preview_out)
    diff = bridge.guard_diff({"sessionId": s1, "planId": p1["planId"]})
    joined_after = "\n".join(row["after"] for row in diff["changed"])
    assert "진짜값" in joined_after
    assert "가짜값" not in joined_after

    # Session-local-only decoy ID does not exist in authoritative root/plans/
    with pytest.raises(RpcError) as exc_decoy:
        core.plan_preview(s1, "plan_decoy_only")
    assert exc_decoy.value.code == "unknown_plan"
    with pytest.raises(rt_ui.BridgeError) as b_decoy:
        bridge.guard_diff({"sessionId": s1, "planId": "plan_decoy_only"})
    assert b_decoy.value.code == "plan_not_found"

    # Cross-session lookup (p2 belongs to s2, requested under s1) is refused
    with pytest.raises(RpcError) as exc_cross:
        core.plan_preview(s1, p2["planId"])
    assert exc_cross.value.code == "unknown_plan"
    with pytest.raises(rt_ui.BridgeError) as b_cross:
        bridge.guard_diff({"sessionId": s1, "planId": p2["planId"]})
    assert b_cross.value.code == "plan_not_found"

    # Also verify no sidecar / apply / profile / plan mutations occurred during any preview or refusal
    assert _snapshot_root(root) == snap_with_decoys
