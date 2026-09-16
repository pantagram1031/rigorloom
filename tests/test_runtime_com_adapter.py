# -*- coding: utf-8 -*-
"""S2: COM child adapter. No pyhwpx, no live Hancom, no --kill-stale.

``hancom_facts``, the process probe, and ``run_child`` are substituted. The
fake child writes the save-as bytes and prints the engine's stdout JSON.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _runtime_client import runtime_scripts_on_path

runtime_scripts_on_path()

import rt_convert  # noqa: E402
import rt_engine  # noqa: E402
from rt_codes import RpcError  # noqa: E402
from rt_engine import (  # noqa: E402
    ChildResult,
    EngineTools,
    com_edit_argv,
    stage_com_ops,
    write_com_ops_file,
)

YES_HANCOM = {
    "state": "yes",
    "reason": None,
    "progid": "HWPFrame.HwpObject",
    "pyhwpx": True,
}
NO_HANCOM = {
    "state": "no",
    "reason": "pyhwpx is not importable; the COM backend needs it",
    "progid": None,
    "pyhwpx": False,
}
IDLE = {"state": "no", "processes": [], "reason": None}
BUSY = {"state": "yes", "reason": None,
        "processes": [{"image": "Hwp.exe", "pid": "42"}]}


def _flag(argv, name):
    return argv[argv.index(name) + 1] if name in argv else None


def _child(returncode=0, payload=None, stdout=None, timed_out=False):
    if stdout is None:
        body = payload if payload is not None else {
            "ok": True, "results": [{"op": "replace_all", "n": 1}],
            "saved": "edited.hwpx", "pdf": None, "post_inspect": {},
        }
        stdout = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
    return ChildResult([], returncode, stdout, b"", False, timed_out)


@pytest.fixture()
def tools():
    return EngineTools()


@pytest.fixture()
def ready(monkeypatch):
    monkeypatch.setattr(rt_convert, "hancom_facts", lambda: dict(YES_HANCOM))
    monkeypatch.setattr(rt_convert, "running_hancom_processes", lambda: dict(IDLE))


def _ops_file(tmp_path, rows):
    path = tmp_path / "ops.json"
    write_com_ops_file(rows, path)
    return path


def test_refuses_when_the_probe_says_no(tools, tmp_path, monkeypatch):
    monkeypatch.setattr(rt_convert, "hancom_facts", lambda: dict(NO_HANCOM))
    monkeypatch.setattr(rt_convert, "running_hancom_processes", lambda: dict(IDLE))

    def must_not_spawn(*a, **k):
        raise AssertionError("COM child started without Hancom")

    monkeypatch.setattr(rt_engine, "run_child", must_not_spawn)
    src, dest = tmp_path / "in.hwpx", tmp_path / "out.hwpx"
    src.write_bytes(b"pk")
    ops = _ops_file(tmp_path, [{"op": "replace_all", "find": "a", "replace": "b"}])
    with pytest.raises(RpcError) as caught:
        tools.com_edit_run(src, ops, dest)
    assert caught.value.code == "needs_hancom"
    assert "pyhwpx" in caught.value.message


def test_refuses_com_busy_when_hwp_is_reported(tools, tmp_path, monkeypatch):
    monkeypatch.setattr(rt_convert, "hancom_facts", lambda: dict(YES_HANCOM))
    monkeypatch.setattr(rt_convert, "running_hancom_processes", lambda: dict(BUSY))

    def must_not_spawn(*a, **k):
        raise AssertionError("COM child started while Hwp.exe was live")

    monkeypatch.setattr(rt_engine, "run_child", must_not_spawn)
    src, dest = tmp_path / "in.hwpx", tmp_path / "out.hwpx"
    src.write_bytes(b"pk")
    ops = _ops_file(tmp_path, [{"op": "replace_all", "find": "a", "replace": "b"}])
    with pytest.raises(RpcError) as caught:
        tools.com_edit_run(src, ops, dest)
    assert caught.value.code == "com_busy"
    assert caught.value.data["processes"][0]["pid"] == "42"


def test_refuses_when_file_equals_save_as(tools, tmp_path, ready, monkeypatch):
    def must_not_spawn(*a, **k):
        raise AssertionError("COM child started for an in-place save")

    monkeypatch.setattr(rt_engine, "run_child", must_not_spawn)
    src = tmp_path / "same.hwpx"
    src.write_bytes(b"pk")
    ops = _ops_file(tmp_path, [{"op": "replace_all", "find": "a", "replace": "b"}])
    with pytest.raises(RpcError) as caught:
        tools.com_edit_run(src, ops, src)
    assert caught.value.code == "invalid_params"


def test_refuses_a_deferred_op(tools, tmp_path, ready, monkeypatch):
    def must_not_spawn(*a, **k):
        raise AssertionError("COM child started for a deferred op")

    monkeypatch.setattr(rt_engine, "run_child", must_not_spawn)
    src, dest = tmp_path / "in.hwpx", tmp_path / "out.hwpx"
    src.write_bytes(b"pk")
    ops = _ops_file(tmp_path, [{"op": "find_delete", "text": "수신"}])
    with pytest.raises(RpcError) as caught:
        tools.com_edit_run(src, ops, dest)
    assert caught.value.code == "unknown_op_kind"
    assert caught.value.data["kind"] == "find_delete"


def test_argv_has_no_kill_stale_and_parses_json(tools, tmp_path, ready, monkeypatch):
    captured = {}

    def fake_run_child(argv, **kwargs):
        captured["argv"] = list(argv)
        file = Path(_flag(argv, "--file"))
        save_as = Path(_flag(argv, "--save-as"))
        save_as.write_bytes(file.read_bytes())
        payload = {
            "ok": True,
            "results": [
                {"op": "replace_all", "n": 2},
                {"op": "insert_text", "ok": True},
            ],
            "saved": str(save_as),
            "pdf": None,
            "post_inspect": {},
        }
        return _child(payload=payload)

    monkeypatch.setattr(rt_engine, "run_child", fake_run_child)
    src, dest = tmp_path / "opened.hwpx", tmp_path / "edited.hwpx"
    src.write_bytes(b"document-bytes")
    ops = _ops_file(tmp_path, [
        {"op": "replace_all", "find": "수신", "replace": "한빛"},
        {"op": "insert_text", "text": "본문", "pt": 10},
    ])
    outcome = tools.com_edit_run(src, ops, dest)
    argv = captured["argv"]
    assert argv == com_edit_argv(tools.com_backend, src, ops, dest)
    assert argv[2] == "edit"
    assert "--kill-stale" not in argv
    assert "--json" not in argv
    assert "--visible" not in argv
    assert outcome["payload"]["ok"] is True
    assert outcome["payload"]["results"][0]["n"] == 2
    assert dest.read_bytes() == b"document-bytes"


def test_nonzero_exit_is_backend_refused_with_redacted_paths(
        tools, tmp_path, ready, monkeypatch):
    src, dest = tmp_path / "opened.hwpx", tmp_path / "edited.hwpx"
    src.write_bytes(b"pk")
    ops = _ops_file(tmp_path, [{"op": "replace_all", "find": "a", "replace": "b"}])

    def fake_run_child(argv, **kwargs):
        leak = f"failed opening {src} into {dest}"
        return _child(returncode=3, stdout=leak.encode("utf-8"))

    monkeypatch.setattr(rt_engine, "run_child", fake_run_child)
    with pytest.raises(RpcError) as caught:
        tools.com_edit_run(src, ops, dest)
    error = caught.value
    assert error.code == "backend_refused"
    assert str(src) not in error.data["stdout"]
    assert src.name in error.data["stdout"]


def test_unparsable_stdout_is_backend_refused(tools, tmp_path, ready, monkeypatch):
    src, dest = tmp_path / "in.hwpx", tmp_path / "out.hwpx"
    src.write_bytes(b"pk")
    ops = _ops_file(tmp_path, [{"op": "insert_text", "text": "x"}])
    monkeypatch.setattr(
        rt_engine, "run_child",
        lambda *a, **k: _child(returncode=0, stdout=b"not-json"))
    with pytest.raises(RpcError) as caught:
        tools.com_edit_run(src, ops, dest)
    assert caught.value.code == "backend_refused"


def test_stage_com_ops_copies_a_picture_into_assets(tmp_path):
    picture = tmp_path / "graph.png"
    picture.write_bytes(b"png")
    work = tmp_path / "work" / "run"
    work.mkdir(parents=True)
    rows = stage_com_ops(
        [{"kind": "insert_picture", "params": {"path": str(picture),
                                              "width_mm": 80}}],
        work)
    copied = Path(rows[0]["path"])
    assert copied.parent == work / "assets"
    assert copied.read_bytes() == b"png"
    assert rows[0]["op"] == "insert_picture"
    assert rows[0]["width_mm"] == 80
