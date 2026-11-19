# -*- coding: utf-8 -*-
"""Apply and preview read one private snapshot of the approved input.

The digest an apply checks and the bytes it executes must be the same bytes.
These tests change the runtime's own copy of the input (the session source, or
a published base candidate) after the digest check, from inside the first
backend call, and require that the published candidate is still exactly what
the approved bytes produce, and that the receipt records the plan's binding.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from _runtime_client import CORPUS_FORM, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_apply  # noqa: E402
import rt_core  # noqa: E402
from rt_codes import RpcError  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

OPS_ONE = [{"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "한빛"}]
OPS_CHAIN = [{"kind": "fill_cell", "table": 0, "row": 5, "col": 2, "text": "둘"}]
# What the concurrent writer puts in place: the same form with another cell
# filled, so the approved ops still run on it and produce DIFFERENT bytes.
OPS_INTRUDER = [{"kind": "fill_cell", "table": 0, "row": 5, "col": 4, "text": "변조"}]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_ops(core, ops, origin: Path, work: Path) -> bytes:
    """What these ops produce from exactly these bytes, outside any session."""
    work.mkdir(parents=True, exist_ok=True)
    pristine = work / origin.name
    shutil.copyfile(origin, pristine)
    final, _ = rt_apply._execute_preedit_steps(
        core.tools, [dict(op, opId=f"op-{i + 1}", params=dict(op)) for i, op in enumerate(ops)],
        pristine, work, origin.suffix)
    return final.read_bytes()


def _approved(core, session_id, ops, *, base_run_id=None):
    plan = core.plan_propose(session_id, "preedit", ops, proposer="test-builder",
                             base_run_id=base_run_id)["plan"]
    assert core.plan_validate(plan["planId"])["validation"]["ok"] is True
    approval = core.approval_request(plan["planId"], requested_by="test-builder")["approval"]
    core.approval_resolve(approval["approvalId"], plan["planId"], plan["planHash"],
                          "approved", "test-operator")
    return plan, approval


def _swap_on_first_call(monkeypatch, tools, method: str, target: Path, intruder: bytes):
    """Replace ``target``'s bytes the first time ``tools.<method>`` is called."""
    real = getattr(tools, method)
    state = {"fired": False}

    def wrapper(*args, **kwargs):
        if not state["fired"]:
            state["fired"] = True
            target.write_bytes(intruder)
        return real(*args, **kwargs)

    monkeypatch.setattr(tools, method, wrapper)
    return state


def _no_snapshot_left(session) -> None:
    leftovers = [p.name for p in session.work_dir.iterdir()] if session.work_dir.is_dir() else []
    assert leftovers == [], leftovers


@pytest.fixture
def core(tmp_path):
    return rt_core.RuntimeCore(tmp_path / "root", engine_root=REPO)


@pytest.fixture
def opened(core, tmp_path):
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    answer = core.open_path(str(source))
    return (answer.get("session") or answer)["sessionId"]


@pytest.mark.parametrize("hook", ["profile", "preedit_run"])
def test_a_source_change_after_the_digest_check_does_not_reach_the_candidate(
        core, opened, tmp_path, monkeypatch, hook):
    session = core.store.get(opened)
    approved_bytes = session.source.read_bytes()
    expected = _run_ops(core, OPS_ONE, session.source, tmp_path / "expected")
    intruder = _run_ops(core, OPS_INTRUDER, session.source, tmp_path / "intruder")
    assert expected != _run_ops(core, OPS_ONE, Path(_write(tmp_path / "i.hwpx", intruder)),
                                tmp_path / "differs")

    plan, approval = _approved(core, opened, OPS_ONE)
    fired = _swap_on_first_call(monkeypatch, core.tools, hook, session.source, intruder)
    try:
        result = core.plan_apply(plan["planId"], approval["approvalId"])
    except RpcError:  # stopping publication is the other honest outcome
        assert fired["fired"]
        assert core.candidate_list(opened)["candidates"] == []
        _no_snapshot_left(session)
        return
    assert fired["fired"], "the hook never ran, so nothing was raced"

    run_id = result["candidate"]["runId"]
    artifact = session.candidates_dir / run_id / result["candidate"]["candidate"]["path"]
    assert artifact.read_bytes() == expected, "the candidate was built from bytes nobody approved"
    receipt = core.receipt_read(opened, run_id)["receipt"]
    assert receipt["input"]["sha256"] == plan["boundSha256"] == _sha(approved_bytes)
    assert receipt["input"]["kind"] == "session_source"
    assert receipt["source"]["sha256"] == plan["boundSha256"]
    _no_snapshot_left(session)


@pytest.mark.parametrize("hook", ["profile", "preedit_run"])
def test_a_base_candidate_change_after_the_digest_check_does_not_reach_the_candidate(
        core, opened, tmp_path, monkeypatch, hook):
    session = core.store.get(opened)
    plan1, approval1 = _approved(core, opened, OPS_ONE)
    run1 = core.plan_apply(plan1["planId"], approval1["approvalId"])["candidate"]["runId"]
    base_path, base_receipt = rt_apply.candidate_artifact(session, run1)
    base_bytes = base_path.read_bytes()
    expected = _run_ops(core, OPS_CHAIN, base_path, tmp_path / "expected")
    intruder = _run_ops(core, OPS_INTRUDER, base_path, tmp_path / "intruder")

    plan2, approval2 = _approved(core, opened, OPS_CHAIN, base_run_id=run1)
    assert plan2["boundSha256"] == base_receipt["candidate"]["sha256"]
    fired = _swap_on_first_call(monkeypatch, core.tools, hook, base_path, intruder)
    try:
        result = core.plan_apply(plan2["planId"], approval2["approvalId"])
    except RpcError:  # stopping publication is the other honest outcome
        assert fired["fired"]
        assert [r["runId"] for r in core.candidate_list(opened)["candidates"]] == [run1]
        _no_snapshot_left(session)
        return
    finally:
        base_path.write_bytes(base_bytes)  # the writer puts it back: a transient race
    assert fired["fired"], "the hook never ran, so nothing was raced"

    run2 = result["candidate"]["runId"]
    artifact = session.candidates_dir / run2 / result["candidate"]["candidate"]["path"]
    assert artifact.read_bytes() == expected, "the candidate was built from bytes nobody approved"
    receipt = core.receipt_read(opened, run2)["receipt"]
    assert receipt["input"]["sha256"] == plan2["boundSha256"] == _sha(base_bytes)
    assert receipt["input"]["kind"] == "candidate"
    assert receipt["base"]["sha256"] == plan2["boundSha256"]
    _no_snapshot_left(session)


def test_a_preview_reads_the_same_snapshot_it_checked(core, opened, tmp_path, monkeypatch):
    session = core.store.get(opened)
    expected = _run_ops(core, OPS_ONE, session.source, tmp_path / "expected")
    intruder = _run_ops(core, OPS_INTRUDER, session.source, tmp_path / "intruder")
    plan = core.plan_propose(opened, "preedit", OPS_ONE, proposer="test-builder")["plan"]

    fired = _swap_on_first_call(monkeypatch, core.tools, "preedit_run", session.source, intruder)
    preview = core.plan_preview(opened, plan["planId"], out_path=tmp_path / "preview.hwpx")
    assert fired["fired"]
    assert preview["preview"]["sha256"] == _sha(expected)
    assert (tmp_path / "preview.hwpx").read_bytes() == expected
    _no_snapshot_left(session)


def test_an_input_that_no_longer_matches_the_binding_is_refused_and_cleaned_up(
        core, opened, tmp_path):
    session = core.store.get(opened)
    plan, approval = _approved(core, opened, OPS_ONE)
    session.source.write_bytes(_run_ops(core, OPS_INTRUDER, session.source, tmp_path / "x"))
    with pytest.raises(RpcError) as exc_info:
        core.plan_apply(plan["planId"], approval["approvalId"])
    assert exc_info.value.code == "plan_stale"
    assert exc_info.value.data["boundSha256"] == plan["boundSha256"]
    assert core.candidate_list(opened)["candidates"] == []
    _no_snapshot_left(session)


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path
