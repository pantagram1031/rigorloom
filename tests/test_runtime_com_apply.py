# -*- coding: utf-8 -*-
"""S3: COM apply branch and native_com_session receipt. No live COM.

``hancom_facts``, the process probe, and ``EngineTools.com_edit_run`` are
substituted. The fake child writes the save-as bytes (a copy of the opened
file) and returns the engine JSON shape.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from _runtime_client import CORPUS_FORM, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_apply  # noqa: E402
import rt_convert  # noqa: E402
import rt_engine  # noqa: E402
import rt_plan  # noqa: E402
from rt_apply import apply_plan, read_receipt  # noqa: E402
from rt_codes import RpcError  # noqa: E402
from rt_core import RuntimeCore  # noqa: E402
from rt_session import SessionStore, sha256_file  # noqa: E402

YES_HANCOM = {
    "state": "yes",
    "reason": None,
    "progid": "HWPFrame.HwpObject",
    "pyhwpx": True,
}
IDLE = {"state": "no", "processes": [], "reason": None}
COM_OP = {"kind": "replace_all", "find": "수신", "replace": "한빛"}
TWO_OPS = [
    {"kind": "replace_all", "find": "수신", "replace": "한빛"},
    {"kind": "insert_text", "text": "본문", "pt": 10},
]


def _hwpx(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    shutil.copyfile(CORPUS_FORM, target)
    return target


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture()
def hancom_ok(monkeypatch):
    monkeypatch.setattr(rt_convert, "hancom_facts", lambda: dict(YES_HANCOM))
    monkeypatch.setattr(rt_convert, "running_hancom_processes", lambda: dict(IDLE))


def _install_fake_edit(monkeypatch, tools, *, fail=False, write_pdf=False,
                       results=None):
    calls = []

    def fake(file, ops_path, save_as, export_pdf=None, timeout=None):
        if fail:
            raise RpcError("backend_refused", "fake COM child failed",
                           tool="com_backend", exitCode=3)
        Path(save_as).parent.mkdir(parents=True, exist_ok=True)
        Path(save_as).write_bytes(Path(file).read_bytes())
        pdf_out = None
        if export_pdf is not None:
            Path(export_pdf).write_bytes(b"%PDF-1.4\n%stub\n")
            pdf_out = str(export_pdf)
        elif write_pdf:
            raise AssertionError("export_pdf was not requested")
        payload = {
            "ok": True,
            "results": results or [
                {"op": "replace_all", "n": 1, "hwpeqn": "should-strip"},
                {"op": "insert_text", "ok": True},
            ],
            "saved": str(save_as),
            "pdf": pdf_out,
            "post_inspect": {"ok": True, "equations": [{"index": 0, "script": "E=mc^2"}]},
        }
        argv = rt_engine.com_edit_argv(
            tools.com_backend, file, ops_path, save_as, export_pdf)
        calls.append({"argv": argv, "file": str(file), "save_as": str(save_as),
                      "export_pdf": str(export_pdf) if export_pdf else None})
        return {"exitCode": 0, "payload": payload, "argv": argv}

    monkeypatch.setattr(tools, "com_edit_run", fake)
    return calls


def _approve_com(core, session_id, ops):
    plan = core.plan_propose(session_id, "com", ops, "test")["plan"]
    assert core.plan_validate(plan["planId"])["validation"]["ok"] is True
    approval = core.approval_request(plan["planId"], "test")["approval"]
    core.approval_resolve(
        approval["approvalId"], plan["planId"], plan["planHash"],
        "approved", "test-operator")
    return plan, approval


def test_com_apply_publishes_native_evidence_and_leaves_the_source(
        tmp_path, hancom_ok, monkeypatch):
    source = _hwpx(tmp_path)
    before = _sha(source)
    core = RuntimeCore(tmp_path / "root")
    session_id = core.open_path(str(source))["sessionId"]
    session = core.store.get(session_id)
    calls = _install_fake_edit(monkeypatch, core.tools)
    plan, approval = _approve_com(core, session_id, TWO_OPS)
    result = core.plan_apply(plan["planId"], approval["approvalId"])
    candidate = result["candidate"]
    assert candidate["canonical"] is True
    assert len(calls) == 1
    argv = calls[0]["argv"]
    assert argv[2] == "edit"
    assert "--kill-stale" not in argv
    assert Path(calls[0]["file"]).name.startswith("opened")
    assert Path(calls[0]["save_as"]).name.startswith("edited")
    assert Path(calls[0]["file"]).resolve() != Path(calls[0]["save_as"]).resolve()

    receipt = read_receipt(session, candidate["runId"])
    assert receipt["backend"] == "com"
    assert receipt["evidence"]["class"] == "native_com_session"
    assert "not a render certificate" in receipt["evidence"]["note"]
    assert receipt["evidence"]["native"]["pdf"] is None
    assert receipt["evidence"]["native"]["post_inspect"]["equations"] == [{"index": 0}]
    assert len(receipt["steps"]) == 1
    assert receipt["steps"][0]["subcommand"] == "edit"
    assert receipt["steps"][0]["exitCode"] == 0
    assert "hwpeqn" not in receipt["steps"][0]["results"][0]
    assert receipt["source"]["sha256"] == session.meta["sourceSha256"]
    assert _sha(session.source) == before == session.meta["sourceSha256"]
    assert list(session.work_dir.iterdir()) == []
    artifact = (session.candidates_dir / candidate["runId"]
                / candidate["candidate"]["path"])
    assert artifact.is_file()
    assert _sha(artifact) == candidate["candidate"]["sha256"]


def test_com_apply_failure_publishes_nothing(tmp_path, hancom_ok, monkeypatch):
    source = _hwpx(tmp_path)
    core = RuntimeCore(tmp_path / "root")
    session_id = core.open_path(str(source))["sessionId"]
    session = core.store.get(session_id)
    _install_fake_edit(monkeypatch, core.tools, fail=True)
    plan, approval = _approve_com(core, session_id, [COM_OP])
    with pytest.raises(RpcError) as caught:
        core.plan_apply(plan["planId"], approval["approvalId"])
    assert caught.value.code == "backend_refused"
    assert list(session.work_dir.iterdir()) == []
    assert list(session.candidates_dir.iterdir()) == []


def test_xml_backend_routes_to_xml_edit_run_not_refused(tmp_path, monkeypatch):
    """S7: xml apply no longer refuses; it routes to xml_edit_run.

    Use a fake xml_edit_run that returns a success payload. This verifies
    the apply branch exists and the source is unchanged after it runs.
    """
    source = _hwpx(tmp_path)
    before = _sha(source)
    core = RuntimeCore(tmp_path / "root")
    session_id = core.open_path(str(source))["sessionId"]
    session = core.store.get(session_id)
    calls = []

    def fake_xml_edit_run(file, ops_path, save_as, timeout=None):
        Path(save_as).parent.mkdir(parents=True, exist_ok=True)
        Path(save_as).write_bytes(Path(file).read_bytes())
        calls.append({"file": str(file), "save_as": str(save_as)})
        return {"exitCode": 0,
                "payload": {"ok": True, "applied": 1, "unsupported": [],
                            "anchors_missing": [], "results": [{"op": "replace_all"}]},
                "argv": []}

    monkeypatch.setattr(core.tools, "xml_edit_run", fake_xml_edit_run)

    plan = core.plan_propose(
        session_id, "xml",
        [{"kind": "replace_all", "find": "a", "replace": "b"}],
        "test")["plan"]
    approval = core.approval_request(plan["planId"], "test")["approval"]
    core.approval_resolve(
        approval["approvalId"], plan["planId"], plan["planHash"],
        "approved", "test-operator")
    result = core.plan_apply(plan["planId"], approval["approvalId"])
    assert result["candidate"]["canonical"] is True
    assert len(calls) == 1
    # source unchanged
    assert _sha(source) == before
    receipt = read_receipt(session, result["candidate"]["runId"])
    assert receipt["backend"] == "xml"
    assert receipt["evidence"]["class"] == "structural_only"


def test_apply_once_replays_the_same_com_candidate(tmp_path, hancom_ok, monkeypatch):
    source = _hwpx(tmp_path)
    core = RuntimeCore(tmp_path / "root")
    session_id = core.open_path(str(source))["sessionId"]
    calls = _install_fake_edit(monkeypatch, core.tools)
    plan, approval = _approve_com(core, session_id, [COM_OP])
    first = core.plan_apply(plan["planId"], approval["approvalId"])
    second = core.plan_apply(plan["planId"], approval["approvalId"])
    assert second == first
    assert len(calls) == 1
    session = core.store.get(session_id)
    run_id = first["candidate"]["runId"]
    assert [entry.name for entry in session.candidates_dir.iterdir()] == [run_id]


def test_read_receipt_rehashes_the_pdf_sidecar(tmp_path, hancom_ok, monkeypatch):
    source = _hwpx(tmp_path)
    store = SessionStore(tmp_path / "root")
    session = store.open_path(str(source))
    tools = rt_engine.EngineTools()
    _install_fake_edit(monkeypatch, tools)
    plan = rt_plan.build_plan(
        session_id=session.id, backend="com", ops=[COM_OP], proposer="test",
        bound_sha256=session.current_source_sha256(),
        com_capability={"state": "available", "facts": {}})
    approval = rt_plan.request_approval(plan, "test")
    rt_plan.resolve_approval(approval, plan_id=plan.id, plan_hash=plan.hash,
                             decision="approved", approver="test")
    published = apply_plan(tools, session, plan, approval, export_pdf=True)
    receipt = read_receipt(session, published["runId"])
    pdf = receipt["evidence"]["native"]["pdf"]
    assert pdf["path"] == "native.pdf"
    assert pdf["bytes"] > 0
    assert len(pdf["sha256"]) == 64
    pdf_path = session.candidates_dir / published["runId"] / "native.pdf"
    assert sha256_file(pdf_path) == (pdf["sha256"], pdf["bytes"])
    pdf_path.write_bytes(b"%PDF-1.4\ntampered\n")
    with pytest.raises(RpcError) as caught:
        read_receipt(session, published["runId"])
    assert caught.value.code == "candidate_hash_mismatch"
