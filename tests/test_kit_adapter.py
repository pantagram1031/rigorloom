# -*- coding: utf-8 -*-
"""The optional HWP engine adapter (runtime/scripts/rt_kit.py).

Two worlds, both must hold: with no engine every call is a structured refusal
naming the missing capability; with an engine (a stand-in that speaks the
kit_api api-1 contract) calls go through a child process and contract breaks
become refusals, never exceptions.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime" / "scripts"))

import rt_kit  # noqa: E402

FAKE_ENGINE = textwrap.dedent('''
    import json, sys, time
    fn = sys.argv[1]
    args = json.loads(sys.argv[sys.argv.index("--args") + 1])
    if fn == "features":
        out = {"api": 1, "ok": True, "backend": "python", "fn": fn, "features": ["fill"]}
    elif fn == "fill":
        out = {"api": 1, "ok": True, "backend": "python", "fn": fn, "echo": args}
    elif fn == "pages":
        out = {"api": 1, "ok": False, "backend": "python", "fn": fn,
               "error": {"code": "bad_input", "message": "no such file"}}
    elif fn == "edit":
        print("not json at all")
        sys.exit(1)
    elif fn == "build":
        out = {"api": 2, "ok": True, "fn": fn}
    elif fn == "pdf":
        time.sleep(5)
        out = {"api": 1, "ok": True, "fn": fn}
    else:
        out = {"api": 1, "ok": True, "backend": "python", "fn": fn}
    print("engine log line")
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0 if out.get("ok") else 1)
''')


@pytest.fixture()
def engine(tmp_path):
    root = tmp_path / "engine"
    root.mkdir()
    (root / "kit_api.py").write_text(FAKE_ENGINE, encoding="utf-8")
    return {rt_kit.ENGINE_ENV: str(root)}


def test_absent_engine_refuses_every_function_with_its_reason():
    for fn in rt_kit.FUNCTIONS:
        out = rt_kit.call(fn, {"x": 1}, env={})
        assert out["ok"] is False
        assert out["error"]["code"] == "capability_unavailable"
        assert out["error"]["reason"] == rt_kit.CANNOT[fn][0]
        assert out["error"]["engine"] == "engine_not_configured"
        assert out["error"]["message"]


def test_cannot_table_covers_exactly_the_forwarded_functions():
    assert set(rt_kit.CANNOT) == set(rt_kit.FUNCTIONS)


def test_env_pointing_nowhere_is_a_reasoned_refusal(tmp_path):
    env = {rt_kit.ENGINE_ENV: str(tmp_path / "missing")}
    found = rt_kit.detect(env)
    assert found["available"] is False
    assert found["reason"] == "engine_path_missing"
    out = rt_kit.call("fill", {}, env=env)
    assert out["error"]["engine"] == "engine_path_missing"


def test_unknown_function_is_refused_without_running_anything(engine):
    out = rt_kit.call("format_disk", {}, env=engine)
    assert out["error"]["reason"] == "unknown_engine_function"


def test_present_engine_round_trips_arguments(engine):
    out = rt_kit.call("fill", {"form": "양식.hwpx", "n": 3}, env=engine)
    assert out["ok"] is True
    assert out["echo"] == {"form": "양식.hwpx", "n": 3}
    assert out["schema"] == rt_kit.ADAPTER_SCHEMA


def test_engine_refusal_keeps_the_engine_error(engine):
    out = rt_kit.call("pages", {}, env=engine)
    assert out["ok"] is False
    assert out["error"]["reason"] == "engine_refused"
    assert out["error"]["engine"] == {"code": "bad_input", "message": "no such file"}


def test_non_json_and_wrong_api_are_contract_violations(engine):
    assert rt_kit.call("edit", {}, env=engine)["error"]["reason"] == "engine_contract_violation"
    assert rt_kit.call("build", {}, env=engine)["error"]["reason"] == "engine_contract_violation"


def test_timeout_is_a_refusal(engine):
    out = rt_kit.call("pdf", {}, env=engine, timeout=0.5)
    assert out["error"]["reason"] == "engine_timeout"


def test_engine_is_never_imported_into_this_process(engine):
    rt_kit.call("fill", {}, env=engine)
    assert "kit_api" not in sys.modules


def test_status_lists_limits_without_engine():
    st = rt_kit.status(env={})
    assert st["available"] is False
    assert set(st["withoutEngine"]) == set(rt_kit.FUNCTIONS)


def test_status_with_engine_reports_backend(engine):
    st = rt_kit.status(env=engine)
    assert st["available"] is True
    assert st["engine"]["ok"] is True and st["engine"]["backend"] == "python"


@pytest.mark.parametrize("with_engine", [False, True])
def test_cli_engine_command_exit_codes(engine, with_engine, tmp_path):
    env = {k: v for k, v in __import__("os").environ.items() if k != rt_kit.ENGINE_ENV}
    if with_engine:
        env.update(engine)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(REPO / "runtime" / "scripts" / "cli.py"), "engine"],
        capture_output=True, env=env, check=False)
    body = json.loads(proc.stdout.decode("utf-8"))
    assert body["command"] == "engine"
    assert body["result"]["available"] is with_engine
    assert proc.returncode == (0 if with_engine else 3)


def test_adapter_ships_no_engine_material():
    text = (REPO / "runtime" / "scripts" / "rt_kit.py").read_text(encoding="utf-8")
    for marker in ("hnc_layout", "hwpx_kit", "hancom-licensed", "/home/", "C:\\"):
        assert marker not in text
