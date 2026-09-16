# -*- coding: utf-8 -*-
"""S1: COM capability production and first-wave plan contract.

No test here imports pyhwpx or starts Hancom. ``hancom_facts`` and the
``com_backend.py`` path are substituted; propose/validate run in-process
through ``RuntimeCore``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _runtime_client import CORPUS_FORM, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_convert  # noqa: E402
import rt_plan  # noqa: E402
from rt_codes import RpcError  # noqa: E402
from rt_core import RuntimeCore  # noqa: E402
from rt_plan import COM_DEFERRED_OP_KINDS, COM_FIRST_WAVE  # noqa: E402

NO_PYHWPX = {
    "state": "no",
    "reason": "pyhwpx is not importable; the COM backend needs it",
    "progid": None,
    "pyhwpx": False,
}
YES_HANCOM = {
    "state": "yes",
    "reason": None,
    "progid": "HWPFrame.HwpObject",
    "pyhwpx": True,
}

FIRST_WAVE_OP = {"kind": "replace_all", "find": "수신", "replace": "한빛"}
DEFERRED_OP = {"kind": "find_delete", "text": "수신"}
FOREIGN_OP = {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "값"}


def _hwpx(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    target.write_bytes(Path(CORPUS_FORM).read_bytes())
    return target


@pytest.fixture()
def core(tmp_path):
    return RuntimeCore(tmp_path / "root")


@pytest.fixture()
def session(core, tmp_path):
    return core.open_path(str(_hwpx(tmp_path)))["sessionId"]


def _patch_hancom(monkeypatch, facts):
    monkeypatch.setattr(rt_convert, "hancom_facts", lambda: dict(facts))


def _hide_com_script(core, monkeypatch):
    monkeypatch.setattr(core.tools, "com_backend",
                        core.tools.root / "engine" / "scripts" / "no_such_com_backend.py")


# --- unavailable ------------------------------------------------------------

def test_unavailable_capability_uses_the_probe_reason_not_the_old_constant(
        core, monkeypatch):
    _patch_hancom(monkeypatch, NO_PYHWPX)
    com = core.capability_snapshot(methods=["plan/propose"])["backends"]["com"]
    assert com["state"] == "unavailable"
    assert com["reason"] == NO_PYHWPX["reason"]
    assert "declared by the protocol" not in (com["reason"] or "")
    assert com["facts"]["platform"]
    assert com["facts"]["pyhwpx"] is False
    assert com["facts"]["progid"] is None
    assert com["missing"] == "pyhwpx"
    assert com["opKinds"] == list(COM_FIRST_WAVE)
    assert com["deferredOpKinds"] == sorted(COM_DEFERRED_OP_KINDS)


def test_unavailable_propose_is_capability_unavailable_naming_the_missing_fact(
        core, session, monkeypatch):
    _patch_hancom(monkeypatch, NO_PYHWPX)
    with pytest.raises(RpcError) as caught:
        core.plan_propose(session, "com", [FIRST_WAVE_OP], "test")
    error = caught.value
    assert error.code == "capability_unavailable"
    assert error.message == NO_PYHWPX["reason"]
    assert error.data["missing"] == "pyhwpx"
    assert error.data["facts"]["pyhwpx"] is False
    assert error.data["backend"] == "com"


def test_missing_script_keeps_the_probe_yes_but_capability_unavailable(
        core, session, monkeypatch):
    _patch_hancom(monkeypatch, YES_HANCOM)
    _hide_com_script(core, monkeypatch)
    com = core.capability_snapshot(methods=["plan/propose"])["backends"]["com"]
    assert com["state"] == "unavailable"
    assert com["missing"] == "script"
    assert com["reason"] == "engine/scripts/com_backend.py is not in this install"
    assert "declared by the protocol" not in com["reason"]
    with pytest.raises(RpcError) as caught:
        core.plan_propose(session, "com", [FIRST_WAVE_OP], "test")
    assert caught.value.code == "capability_unavailable"
    assert caught.value.data["missing"] == "script"


# --- available --------------------------------------------------------------

def test_available_capability_lists_exactly_the_first_wave(
        core, monkeypatch):
    _patch_hancom(monkeypatch, YES_HANCOM)
    assert core.tools.com_backend.is_file()
    com = core.capability_snapshot(methods=["plan/propose"])["backends"]["com"]
    assert com["state"] == "available"
    assert com["reason"] is None
    assert "missing" not in com
    assert com["opKinds"] == list(COM_FIRST_WAVE)
    assert com["opKinds"] == [
        "replace_all", "goto_text", "insert_text", "set_cell",
        "insert_equation", "insert_picture", "insert_hyperlink",
    ]
    assert com["deferredOpKinds"] == sorted(COM_DEFERRED_OP_KINDS)
    assert "find_delete" in com["deferredOpKinds"]
    assert "page_numbers" in com["deferredOpKinds"]
    assert "set_header" in com["deferredOpKinds"]
    assert com["facts"]["pyhwpx"] is True
    assert com["facts"]["progid"] == "HWPFrame.HwpObject"


def test_available_propose_accepts_a_first_wave_op(
        core, session, monkeypatch):
    _patch_hancom(monkeypatch, YES_HANCOM)
    plan = core.plan_propose(session, "com", [FIRST_WAVE_OP], "test")["plan"]
    assert plan["backend"] == "com"
    assert plan["ops"][0]["kind"] == "replace_all"
    assert plan["ops"][0]["params"] == {"find": "수신", "replace": "한빛"}
    report = core.plan_validate(plan["planId"])["validation"]
    assert report["ok"] is True
    assert report["backend"] == "com"
    assert report["preflight"]["level"] == "structural+backend-schema"
    assert "equation_preflight" in report["preflight"]["deferred"]


def test_deferred_com_op_is_refused(core, session, monkeypatch):
    _patch_hancom(monkeypatch, YES_HANCOM)
    with pytest.raises(RpcError) as caught:
        core.plan_propose(session, "com", [DEFERRED_OP], "test")
    error = caught.value
    assert error.code == "unknown_op_kind"
    assert error.data["kind"] == "find_delete"
    assert error.data["servedBy"] == "com"
    assert error.data["knownKinds"] == list(COM_FIRST_WAVE)
    assert "find_delete" in error.data["notImplemented"]


def test_preedit_kind_on_a_com_plan_is_foreign_mix(
        core, session, monkeypatch):
    _patch_hancom(monkeypatch, YES_HANCOM)
    with pytest.raises(RpcError) as caught:
        core.plan_propose(session, "com", [FOREIGN_OP], "test")
    error = caught.value
    assert error.code == "unsupported_backend"
    assert error.data["servedBy"] == "preedit"
    assert error.data["kind"] == "fill_cell"


def test_ops_hash_incorporates_the_backend(core, session, monkeypatch):
    _patch_hancom(monkeypatch, YES_HANCOM)
    plan = core.plan_propose(session, "com", [FIRST_WAVE_OP], "test")["plan"]
    same_ops = plan["ops"]
    bound = plan["boundSha256"]
    com_hash = rt_plan.ops_hash("com", bound, same_ops)
    preedit_hash = rt_plan.ops_hash("preedit", bound, same_ops)
    assert plan["opsHash"] == com_hash
    assert com_hash != preedit_hash


def test_set_cell_without_addr_is_refused(core, session, monkeypatch):
    _patch_hancom(monkeypatch, YES_HANCOM)
    with pytest.raises(RpcError) as caught:
        core.plan_propose(session, "com",
                          [{"kind": "set_cell", "text": "값"}], "test")
    error = caught.value
    assert error.code == "invalid_params"
    assert error.data["missing"] == ["addr"]


def test_set_cell_row_col_is_translated_to_addr(
        core, session, monkeypatch):
    _patch_hancom(monkeypatch, YES_HANCOM)
    plan = core.plan_propose(
        session, "com",
        [{"kind": "set_cell", "text": "값", "row": 2, "col": 3}],
        "test")["plan"]
    params = plan["ops"][0]["params"]
    assert params["addr"] == [2, 3]
    assert "row" not in params and "col" not in params
    assert "raw_traversal" not in params


def test_set_cell_raw_traversal_is_refused(core, session, monkeypatch):
    _patch_hancom(monkeypatch, YES_HANCOM)
    with pytest.raises(RpcError) as caught:
        core.plan_propose(
            session, "com",
            [{"kind": "set_cell", "text": "값", "raw_traversal": True,
              "row": 1, "col": 1}],
            "test")
    assert caught.value.code in {"unknown_field", "invalid_params"}
    if caught.value.code == "unknown_field":
        assert "raw_traversal" in caught.value.data["unknown"]


def test_apply_routes_a_com_plan_into_apply_plan(core, session, monkeypatch):
    """S1 refused apply before the child. S2+S3 opens the gate; the child is faked."""
    import rt_core
    _patch_hancom(monkeypatch, YES_HANCOM)
    plan = core.plan_propose(session, "com", [FIRST_WAVE_OP], "test")["plan"]
    validation = core.plan_validate(plan["planId"])["validation"]
    assert validation["ok"] is True
    approval = core.approval_request(plan["planId"], "test")["approval"]
    core.approval_resolve(
        approval["approvalId"], plan["planId"], plan["planHash"],
        "approved", "test-operator")
    calls = []

    def fake_apply(*args, **kwargs):
        calls.append(kwargs)
        raise RpcError("backend_refused", "test short-circuit before COM",
                       backend="com")

    monkeypatch.setattr(rt_core, "apply_plan", fake_apply)
    with pytest.raises(RpcError) as caught:
        core.plan_apply(plan["planId"], approval["approvalId"])
    assert calls
    assert caught.value.code == "backend_refused"
    assert caught.value.data["backend"] == "com"
