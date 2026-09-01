# -*- coding: utf-8 -*-
"""document/renderPrepare: the host-only step that makes the PDF.

THE LIVE COM LEG IS NOT EXERCISED HERE. This repository forbids starting
Hancom from the suite, and this bench happens to have it installed, so every
test below either substitutes ``rt_convert.run_convert`` with a prebuilt PDF or
stops before it. What IS tested for real: the ProgID probe, the tasklist busy
check, all four refusals, the source-binding rule, the authority split, and the
prepare → render chain end to end with the convert step stood in for.

One live smoke on an operator machine remains owed and is stated as owed.
"""
from __future__ import annotations

import importlib.util
import shutil

import pytest

from _runtime_client import CORPUS_FORM, RuntimeClient, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_codes  # noqa: E402
import rt_convert  # noqa: E402
import rt_core  # noqa: E402
import rt_render  # noqa: E402
from rt_core import RuntimeCore  # noqa: E402

HAVE_RASTERIZER = any(importlib.util.find_spec(name) is not None
                      for name in rt_render.RASTERIZER_MODULES)


def _hwpx(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    shutil.copyfile(CORPUS_FORM, target)
    return target


def _tiny_pdf(path, pages=2):
    """A real, tiny PDF standing in for what the converter would emit."""
    module = rt_render.rasterizer_module()
    if module is None:  # pragma: no cover - only on a build without PyMuPDF
        path.write_bytes(b"%PDF-1.4\n%stub\n")
        return path
    document = module.open()
    try:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 144), f"converted page {index}", fontsize=28)
        document.save(str(path))
    finally:
        document.close()
    return path


@pytest.fixture()
def core(tmp_path):
    return RuntimeCore(tmp_path / "root")


@pytest.fixture()
def session(core, tmp_path):
    return core.open_path(str(_hwpx(tmp_path)))["sessionId"]


@pytest.fixture()
def hancom_present(monkeypatch):
    """Pretend Hancom is installed and idle, without touching COM."""
    monkeypatch.setattr(rt_convert, "hancom_facts",
                        lambda: {"state": "yes", "reason": None,
                                 "progid": "HWPFrame.HwpObject", "pyhwpx": True})
    monkeypatch.setattr(rt_convert, "running_hancom_processes",
                        lambda: {"state": "no", "processes": [], "reason": None})


@pytest.fixture()
def fake_convert(monkeypatch, tmp_path):
    """Substitute the ONLY function that would start Hancom."""
    calls = []

    def convert(tools, source, target, *, timeout=None):
        calls.append({"source": source, "target": target, "timeout": timeout})
        _tiny_pdf(target)
        return {"argv": ["com_backend.py", "convert"], "exitCode": 0,
                "timedOut": False, "stdout": "{}", "stderr": ""}

    monkeypatch.setattr(rt_convert, "run_convert", convert)
    return calls


# --- authority --------------------------------------------------------------

def test_render_prepare_is_host_only():
    assert "document/renderPrepare" in rt_core.HOST_ONLY_METHODS
    assert "document/renderPrepare" not in rt_core.AGENT_METHODS
    assert "document/renderPrepare" not in rt_core.PROTOCOL_ONLY_METHODS


def test_an_agent_connection_cannot_reach_it(tmp_path):
    with RuntimeClient(tmp_path / "root", entry="agent") as client:
        client.initialize()
        error = client.err("document/renderPrepare", {"sessionId": "x"})
    assert error["code"] == "unknown_method"
    assert error["data"]["knownOnHostEntry"] is True


def test_it_is_not_an_mcp_tool():
    import mcp_server

    assert "document_renderPrepare" not in mcp_server.TOOL_TO_METHOD


def test_the_agent_host_compile_gate_refuses_it():
    """A provider asking for it is refused before the Runtime is touched."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agenthost"
                          / "scripts"))
    import ah_codes
    import ah_compile
    from ah_provider import ToolCall

    with pytest.raises(ah_codes.AgentHostError) as excinfo:
        ah_compile.compile_tool_call(
            ToolCall("c1", "document_renderPrepare", {"sessionId": "s"}))
    assert excinfo.value.code == "tool_forbidden"


# --- the probes -------------------------------------------------------------

def test_the_hancom_probe_uses_the_same_progids_as_render_probe():
    import re
    import sys
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "pipeline" / "scripts"
            / "render_probe.py").read_text(encoding="utf-8")
    listed = set(re.findall(r'"(HWPFrame\.HwpObject[^"]*)"', text))
    assert listed == set(rt_convert.HWP_PROGIDS)
    assert sys is not None


def test_the_hancom_probe_answers_with_a_reason_either_way():
    facts = rt_convert.hancom_facts()
    assert facts["state"] in ("yes", "no")
    if facts["state"] == "no":
        assert facts["reason"]
    else:
        assert facts["progid"] in rt_convert.HWP_PROGIDS


def test_the_busy_check_reads_tasklist_exactly(monkeypatch):
    """An image name is matched whole, not by substring."""
    class Result:
        returncode = 0
        timed_out = False
        stdout = ('"NotHwp.exe","111","Console","1","9,000 K"\r\n'
                  '"hwp.exe","222","Console","1","90,000 K"\r\n'
                  '"chrome.exe","333","Console","1","9,000 K"\r\n'
                  ).encode("utf-8")

    monkeypatch.setattr(rt_convert.sys, "platform", "win32")
    monkeypatch.setattr(rt_convert, "run_child", lambda *a, **k: Result())
    busy = rt_convert.running_hancom_processes()
    assert busy["state"] == "yes"
    assert [row["image"] for row in busy["processes"]] == ["hwp.exe"]
    assert busy["processes"][0]["pid"] == "222"


def test_an_unreadable_tasklist_counts_as_busy_not_free(monkeypatch):
    class Result:
        returncode = 1
        timed_out = True
        stdout = b""

    monkeypatch.setattr(rt_convert.sys, "platform", "win32")
    monkeypatch.setattr(rt_convert, "run_child", lambda *a, **k: Result())
    assert rt_convert.running_hancom_processes()["state"] == "unknown"


def test_nothing_in_this_module_can_kill_anything():
    """The rule T21 paid for: no kill path, at all.

    Structural, not textual — the docstring is allowed to SAY ``--kill-stale``
    while explaining why it is not here, and a grep cannot tell the difference
    between a warning and an instruction.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(rt_convert.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(
                node.func, "id", None)
            assert name not in ("kill", "terminate", "taskkill", "TerminateProcess"), (
                f"rt_convert calls {name}() at line {node.lineno}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # a docstring may discuss it; an executable string must not BE it
            if len(node.value) < 200:
                assert "taskkill" not in node.value.lower(), (
                    f"a taskkill command string at line {node.lineno}")


# --- refusals ---------------------------------------------------------------

def test_a_busy_machine_is_refused_and_nothing_is_terminated(
        core, session, monkeypatch):
    monkeypatch.setattr(rt_convert, "hancom_facts",
                        lambda: {"state": "yes", "reason": None,
                                 "progid": "HWPFrame.HwpObject", "pyhwpx": True})
    monkeypatch.setattr(rt_convert, "running_hancom_processes",
                        lambda: {"state": "yes", "reason": None,
                                 "processes": [{"image": "Hwp.exe", "pid": "42"}]})

    def must_not_run(*args, **kwargs):  # pragma: no cover - the point is it does not
        raise AssertionError("the converter started on a busy machine")

    monkeypatch.setattr(rt_convert, "run_convert", must_not_run)
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_render_prepare(session)
    error = excinfo.value
    assert error.code == "com_busy"
    assert error.data["processes"][0]["pid"] == "42"
    assert "will not" in error.message


def test_an_unknown_busy_state_is_also_refused(core, session, monkeypatch):
    monkeypatch.setattr(rt_convert, "hancom_facts",
                        lambda: {"state": "yes", "reason": None,
                                 "progid": "HWPFrame.HwpObject", "pyhwpx": True})
    monkeypatch.setattr(rt_convert, "running_hancom_processes",
                        lambda: {"state": "unknown", "processes": [],
                                 "reason": "tasklist exited 1"})
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_render_prepare(session)
    assert excinfo.value.code == "com_busy"


def test_a_machine_without_hancom_refuses_needs_hancom(core, session, monkeypatch):
    monkeypatch.setattr(rt_convert, "hancom_facts",
                        lambda: {"state": "no", "pyhwpx": False, "progid": None,
                                 "reason": "pyhwpx is not importable; the COM "
                                           "backend needs it"})
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_render_prepare(session)
    error = excinfo.value
    assert error.code == "needs_hancom"
    assert "pyhwpx" in error.message
    assert error.data["capability"]["method"] == "document/renderPrepare"


def test_a_pdf_session_is_not_convertible(core, tmp_path, hancom_present):
    pdf = _tiny_pdf(tmp_path / "already.pdf")
    session = core.open_path(str(pdf))["sessionId"]
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_render_prepare(session)
    assert excinfo.value.code == "not_convertible"
    assert excinfo.value.data["convertibleFrom"] == [".hwpx", ".hwp"]


def test_an_opaque_source_is_not_convertible(core, tmp_path, hancom_present):
    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    session = core.open_path(str(notes))["sessionId"]
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_render_prepare(session)
    assert excinfo.value.code == "not_convertible"


def test_a_converter_that_fails_is_a_structured_refusal(core, session,
                                                        hancom_present,
                                                        monkeypatch):
    monkeypatch.setattr(rt_convert, "run_convert",
                        lambda *a, **k: {"argv": ["com_backend.py", "convert"],
                                         "exitCode": 3, "timedOut": False,
                                         "stdout": "{\"ok\": false}",
                                         "stderr": "hancom said no"})
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_render_prepare(session)
    error = excinfo.value
    assert error.code == "convert_failed"
    assert error.data["exitCode"] == 3
    assert "hancom said no" in error.data["stderr"]


def test_a_converter_that_hangs_is_a_refusal_not_a_hang(core, session,
                                                        hancom_present,
                                                        monkeypatch):
    monkeypatch.setattr(rt_convert, "run_convert",
                        lambda *a, **k: {"argv": [], "exitCode": -1,
                                         "timedOut": True, "stdout": "",
                                         "stderr": ""})
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_render_prepare(session)
    assert excinfo.value.code == "convert_failed"
    assert excinfo.value.data["timedOut"] is True


def test_a_silly_timeout_is_refused(core, session, hancom_present):
    for bad in (1, 10_000, "soon"):
        with pytest.raises(rt_codes.RpcError) as excinfo:
            core.document_render_prepare(session, timeout=bad)
        assert excinfo.value.code == "invalid_params"


# --- the happy path, with the COM leg substituted ---------------------------

def test_prepare_converts_the_session_copy_never_the_original(
        core, tmp_path, hancom_present, fake_convert):
    original = _hwpx(tmp_path)
    before = original.read_bytes()
    session_id = core.open_path(str(original))["sessionId"]
    core.document_render_prepare(session_id)
    session = core.store.get(session_id)

    assert len(fake_convert) == 1
    call = fake_convert[0]
    assert call["source"] == session.source
    assert call["source"] != original
    assert session.dir in call["target"].parents
    assert original.read_bytes() == before, "the user's file was touched"


def test_prepare_registers_the_pdf_against_the_source_bytes(
        core, session, hancom_present, fake_convert):
    result = core.document_render_prepare(session)
    assert result["prepared"] is True
    record = result["pdf"]
    assert record["path"] == "derived/source.pdf"
    assert len(record["sha256"]) == 64 and record["bytes"] > 0
    handle = core.store.get(session)
    assert record["sourceSha256"] == handle.meta["sourceSha256"]
    # and it survives a reload of the session from disk
    reloaded = RuntimeCore(core.store.root).store.get(session)
    assert rt_convert.existing_pdf(reloaded)["sha256"] == record["sha256"]


def test_preparing_twice_does_not_convert_twice(core, session, hancom_present,
                                                fake_convert):
    core.document_render_prepare(session)
    second = core.document_render_prepare(session)
    assert second["prepared"] is False
    assert "already prepared" in second["reason"]
    assert len(fake_convert) == 1


def test_a_prepared_pdf_that_no_longer_matches_is_ignored(
        core, session, hancom_present, fake_convert):
    core.document_render_prepare(session)
    handle = core.store.get(session)
    derived = handle.dir / "derived" / "source.pdf"
    derived.write_bytes(derived.read_bytes() + b"\n% tampered\n")
    assert rt_convert.existing_pdf(handle) is None


def test_preparing_appends_an_event(core, session, hancom_present, fake_convert):
    import rt_session

    core.document_render_prepare(session)
    events, _ = rt_session.read_events(core.store.get(session))
    kinds = [event["kind"] for event in events]
    assert kinds[-1] == "pdf.prepared"
    assert events[-1]["detail"]["producedBy"].endswith("convert")


# --- prepare -> render, the whole point -------------------------------------

@pytest.mark.skipif(not HAVE_RASTERIZER, reason="PyMuPDF is optional")
def test_prepare_then_render_turns_an_hwpx_session_into_pages(
        core, session, hancom_present, fake_convert):
    before = core.document_render(session)
    assert before["available"] is False
    assert before["unavailable"]["reason"] == "needs_conversion"
    assert before["unavailable"]["prepare"]["state"] == "yes"

    core.document_render_prepare(session)

    after = core.document_render(session, page=1, dpi=72)
    assert after["available"] is True
    assert after["pageCount"] == 2
    assert after["source"]["kind"] == "prepared_pdf"
    assert after["source"]["producedBy"].endswith("convert")
    assert after["image"]["widthPx"] > 100


def test_the_unavailable_state_points_at_prepare_when_it_could_work(
        core, session, hancom_present):
    result = core.document_render(session)
    assert result["unavailable"]["reason"] == "needs_conversion"
    assert "document/renderPrepare" in result["unavailable"]["detail"]


def test_the_unavailable_state_says_why_not_when_it_could_not(
        core, session, monkeypatch):
    monkeypatch.setattr(rt_convert, "hancom_facts",
                        lambda: {"state": "no", "pyhwpx": True, "progid": None,
                                 "reason": "no HWP COM ProgID is registered"})
    result = core.document_render(session)
    assert "ProgID" in result["unavailable"]["detail"]
    assert result["unavailable"]["prepare"]["state"] == "no"


# --- over the wire ----------------------------------------------------------

def test_capabilities_carry_the_prepare_row(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        capabilities = client.initialize()["result"]["capabilities"]
    prepare = capabilities["render"]["prepare"]
    assert prepare["method"] == "document/renderPrepare"
    assert prepare["authority"] == "host"
    assert prepare["state"] in ("yes", "no")
    assert "never terminated" in prepare["serial"]
    assert prepare["liveSmoke"].startswith("not run")


def test_an_unknown_session_is_refused_over_the_wire(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        client.initialize()
        error = client.err("document/renderPrepare", {"sessionId": "nope"})
    assert error["code"] == "unknown_session"


def test_the_cli_exposes_it_as_a_host_command(tmp_path, monkeypatch):
    """The CLI is host authority, so it has the command; it still refuses here."""
    root = tmp_path / "root"
    pdf = _tiny_pdf(tmp_path / "already.pdf")
    session = run_cli(root, "open", "--path", str(pdf)).result["sessionId"]
    result = run_cli(root, "render-prepare", "--session", session)
    # a PDF source is not convertible, which is the refusal we can reach
    # without ever starting Hancom
    assert result.code == 3
    assert result.error["code"] == "not_convertible"
