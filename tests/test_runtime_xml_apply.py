# -*- coding: utf-8 -*-
"""S7: xml backend apply branch — real xml_backend child and fake-child refusal paths.

Requirement: ``plan.payload["backend"] == "xml"`` routes through ``xml_edit_run``;
opened copy → xml_edit_run → atomic move to candidate → residue checks →
receipt with ``backend: "xml"`` and ``evidence.class: "structural_only"`` plus
``evidence.xml: {proofGrade: "structural", wellFormed: true}``.

Test matrix:
  - Real xml_backend on a tiny fixture hwpx (replace_all + insert_text plan):
    * candidate section XML contains the new text and is well-formed.
  - Fake-child tests (monkeypatch xml_edit_run):
    * Non-zero exit → backend_refused, session source unchanged.
    * Boxed equation refusal → backend_refused with equation_box_unsupported_xml.
    * file == save_as → invalid_params before spawn.
    * Source unchanged assertion after every failure.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from _runtime_client import CORPUS_FORM, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_engine  # noqa: E402
import rt_plan  # noqa: E402
from rt_apply import apply_plan, read_receipt  # noqa: E402
from rt_codes import RpcError  # noqa: E402
from rt_plan import XML_FIRST_WAVE  # noqa: E402
from rt_session import SessionStore, sha256_file  # noqa: E402

# ---------------------------------------------------------------------------
# Namespace constants (same as engine/tests/test_xml_backend.py)
# ---------------------------------------------------------------------------
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
OPF = "http://www.idpf.org/2007/opf/"
ODF_MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"

FIND_TEXT = "Generic anchor"
REPLACE_TEXT = "신형 안내문"
INSERT_TEXT = "추가된 텍스트"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_hwpx(path):
    """Minimal valid hwpx zip — mirrors engine/tests/test_xml_backend.py:make_hwpx."""
    header = f'''<hh:head xmlns:hh="{HH}"><hh:refList>
<hh:paraProperties itemCnt="2">
<hh:paraPr id="0"><hh:align horizontal="JUSTIFY"/></hh:paraPr>
<hh:paraPr id="1"><hh:align horizontal="CENTER"/></hh:paraPr>
</hh:paraProperties><hh:charProperties itemCnt="3">
<hh:charPr id="0" height="1000"/><hh:charPr id="1" height="900"><hh:bold/></hh:charPr>
<hh:charPr id="2" height="900"/>
</hh:charProperties>
<hh:borderFills itemCnt="1"><hh:borderFill id="0"/></hh:borderFills>
</hh:refList></hh:head>'''.encode()
    secpr = (f'<hp:secPr><hp:pagePr width="60000" height="84000">'
             f'<hp:margin left="4000" right="5000" top="5000" bottom="5000" '
             f'header="0" footer="0" gutter="1000"/></hp:pagePr></hp:secPr>')
    body = (f'<hp:p id="10" paraPrIDRef="0"><hp:run charPrIDRef="0">'
            f'{secpr}<hp:t>{FIND_TEXT}</hp:t></hp:run></hp:p>')
    section = f'<hp:sec xmlns:hp="{HP}">{body}</hp:sec>'.encode()
    content_hpf = f'''<opf:package xmlns:opf="{OPF}"><opf:manifest>
<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>
</opf:manifest></opf:package>'''.encode()
    manifest = f'''<manifest:manifest xmlns:manifest="{ODF_MANIFEST}">
<manifest:file-entry manifest:media-type="application/xml" manifest:full-path="Contents/header.xml"/>
</manifest:manifest>'''.encode()
    members = {
        "mimetype": b"application/hwp+zip",
        "Contents/header.xml": header,
        "Contents/section0.xml": section,
        "Contents/content.hpf": content_hpf,
        "META-INF/manifest.xml": manifest,
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _section_xml(path):
    with zipfile.ZipFile(path) as zf:
        return zf.read("Contents/section0.xml").decode("utf-8")


def _open_session(tmp_path, hwpx_path=None):
    """Open a session on the given hwpx (or a fresh minimal one)."""
    if hwpx_path is None:
        hwpx_path = make_hwpx(tmp_path / "form.hwpx")
    store = SessionStore(tmp_path / "root")
    session = store.open_path(str(hwpx_path))
    return session


def _build_and_approve(session, backend, ops, *, xml_cap=None):
    """Build, save, and approve a plan in one step."""
    if xml_cap is None:
        xml_cap = {"state": "available"}
    plan = rt_plan.build_plan(
        session_id=session.id, backend=backend, ops=ops,
        proposer="test",
        bound_sha256=session.current_source_sha256(),
        xml_capability=xml_cap)
    approval = rt_plan.request_approval(plan, "test")
    rt_plan.resolve_approval(
        approval, plan_id=plan.id, plan_hash=plan.hash,
        decision="approved", approver="test-operator")
    return plan, approval


# ---------------------------------------------------------------------------
# Real xml_backend integration
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "engine" / "scripts" / "xml_backend.py").is_file(),
    reason="engine/scripts/xml_backend.py not found")
def test_real_xml_backend_replace_all_succeeds(tmp_path):
    """Real xml_backend on a minimal hwpx: replace_all produces a candidate
    whose section XML contains the replacement text and is well-formed."""
    hwpx = make_hwpx(tmp_path / "form.hwpx")
    before_sha = _sha(hwpx)
    session = _open_session(tmp_path, hwpx)
    tools = rt_engine.EngineTools()

    plan, approval = _build_and_approve(session, "xml", [
        {"kind": "replace_all", "find": FIND_TEXT, "replace": REPLACE_TEXT},
    ])

    result = apply_plan(tools, session, plan, approval)

    # Receipt fields live on the published receipt, not the apply summary.
    receipt = read_receipt(session, result["runId"])
    assert receipt["backend"] == "xml"
    assert receipt["evidence"]["class"] == "structural_only"
    assert receipt["evidence"]["xml"]["proofGrade"] == "structural"
    assert receipt["evidence"]["xml"]["wellFormed"] is True

    # Candidate file exists
    candidate_path = (session.candidates_dir / result["runId"]
                      / receipt["candidate"]["path"])
    assert candidate_path.is_file()

    # Section XML is well-formed and contains replacement text
    section = _section_xml(candidate_path)
    ET.fromstring(section)  # raises if not well-formed
    assert REPLACE_TEXT in section
    assert FIND_TEXT not in section  # old text replaced

    # Source unchanged
    assert _sha(hwpx) == before_sha


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "engine" / "scripts" / "xml_backend.py").is_file(),
    reason="engine/scripts/xml_backend.py not found")
def test_real_xml_backend_insert_text_after_goto_succeeds(tmp_path):
    """Real xml_backend: goto_text + insert_text — candidate contains new text."""
    hwpx = make_hwpx(tmp_path / "form.hwpx")
    before_sha = _sha(hwpx)
    session = _open_session(tmp_path, hwpx)
    tools = rt_engine.EngineTools()

    plan, approval = _build_and_approve(session, "xml", [
        {"kind": "goto_text", "text": FIND_TEXT},
        {"kind": "insert_text", "text": INSERT_TEXT},
    ])

    result = apply_plan(tools, session, plan, approval)
    receipt = read_receipt(session, result["runId"])
    assert receipt["backend"] == "xml"
    assert receipt["evidence"]["class"] == "structural_only"
    candidate_path = (session.candidates_dir / result["runId"]
                      / receipt["candidate"]["path"])
    section = _section_xml(candidate_path)
    ET.fromstring(section)
    assert INSERT_TEXT in section

    # Source unchanged
    assert _sha(hwpx) == before_sha


# ---------------------------------------------------------------------------
# Fake-child refusal paths
# ---------------------------------------------------------------------------

def _fake_xml_tools(tmp_path, *, fail=False, unsupported=None):
    """Build EngineTools and patch xml_edit_run to fake success or failure."""
    tools = rt_engine.EngineTools()
    calls = []

    if fail:
        def fake_edit_run(file, ops_path, save_as, timeout=None):
            calls.append({"file": str(file)})
            raise RpcError(
                "backend_refused",
                unsupported[0] if unsupported else "fake xml child failed",
                tool="xml_backend", exitCode=4,
                timedOut=False,
                unsupported=unsupported or [])
    else:
        def fake_edit_run(file, ops_path, save_as, timeout=None):
            Path(save_as).parent.mkdir(parents=True, exist_ok=True)
            Path(save_as).write_bytes(Path(file).read_bytes())
            calls.append({"file": str(file), "save_as": str(save_as)})
            return {
                "exitCode": 0,
                "payload": {"ok": True, "applied": 1, "unsupported": [],
                            "anchors_missing": [], "results": [{"op": "replace_all"}]},
                "argv": [],
            }

    tools.xml_edit_run = fake_edit_run
    return tools, calls


def test_fake_xml_nonzero_exit_is_backend_refused(tmp_path):
    """Non-zero exit from xml_backend → backend_refused; session source unchanged."""
    hwpx = make_hwpx(tmp_path / "form.hwpx")
    before_sha = _sha(hwpx)
    session = _open_session(tmp_path, hwpx)
    tools, calls = _fake_xml_tools(tmp_path, fail=True)

    plan, approval = _build_and_approve(session, "xml", [
        {"kind": "replace_all", "find": "a", "replace": "b"},
    ])

    with pytest.raises(RpcError) as caught:
        apply_plan(tools, session, plan, approval)

    assert caught.value.code == "backend_refused"
    # Source unchanged
    assert _sha(hwpx) == before_sha
    # No candidate published
    assert not session.candidates_dir.exists() or list(session.candidates_dir.iterdir()) == []


def test_fake_xml_equation_box_is_backend_refused(tmp_path):
    """Boxed equation → backend_refused with equation_box_unsupported_xml reason."""
    hwpx = make_hwpx(tmp_path / "form.hwpx")
    before_sha = _sha(hwpx)
    session = _open_session(tmp_path, hwpx)
    tools, _ = _fake_xml_tools(tmp_path, fail=True,
                               unsupported=["equation_box_unsupported_xml"])

    plan, approval = _build_and_approve(session, "xml", [
        {"kind": "goto_text", "text": FIND_TEXT},
        {"kind": "insert_equation", "latex": r"\boxed{E=mc^2}", "boxed": True},
    ])

    with pytest.raises(RpcError) as caught:
        apply_plan(tools, session, plan, approval)

    assert caught.value.code == "backend_refused"
    assert "equation_box_unsupported_xml" in (
        caught.value.message or ""
        or str(caught.value.data.get("unsupported", [])))
    # Source unchanged
    assert _sha(hwpx) == before_sha


def test_fake_xml_success_produces_xml_evidence_receipt(tmp_path):
    """Successful fake xml apply → receipt has backend=xml and evidence.xml."""
    hwpx = make_hwpx(tmp_path / "form.hwpx")
    session = _open_session(tmp_path, hwpx)
    tools, calls = _fake_xml_tools(tmp_path, fail=False)

    plan, approval = _build_and_approve(session, "xml", [
        {"kind": "replace_all", "find": "a", "replace": "b"},
    ])

    result = apply_plan(tools, session, plan, approval)
    receipt = read_receipt(session, result["runId"])
    assert receipt["backend"] == "xml"
    evidence = receipt["evidence"]
    assert evidence["class"] == "structural_only"
    assert "xml" in evidence
    assert evidence["xml"]["proofGrade"] == "structural"
    assert evidence["xml"]["wellFormed"] is True
    assert len(calls) == 1


def test_fake_xml_malformed_candidate_is_refused_not_published(tmp_path):
    """The child never asserts well-formedness; the Runtime parses every XML
    part of the candidate itself. A candidate with a broken part is refused
    with reason xml_not_well_formed, nothing is published, source unchanged."""
    import zipfile

    hwpx = make_hwpx(tmp_path / "form.hwpx")
    before_sha = _sha(hwpx)
    session = _open_session(tmp_path, hwpx)
    tools, _ = _fake_xml_tools(tmp_path, fail=False)

    def corrupting_edit_run(file, ops_path, save_as, timeout=None):
        Path(save_as).parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(file) as src, zipfile.ZipFile(save_as, "w") as dst:
            for name in src.namelist():
                data = src.read(name)
                if name.lower().endswith("section0.xml"):
                    data = data[: len(data) // 2] + b"<unclosed>"
                dst.writestr(name, data)
        return {"exitCode": 0,
                "payload": {"ok": True, "applied": 1, "unsupported": [],
                            "anchors_missing": [], "results": [{"op": "replace_all"}]},
                "argv": []}

    tools.xml_edit_run = corrupting_edit_run
    plan, approval = _build_and_approve(session, "xml", [
        {"kind": "replace_all", "find": "a", "replace": "b"},
    ])

    with pytest.raises(RpcError) as caught:
        apply_plan(tools, session, plan, approval)

    assert caught.value.code == "backend_refused"
    assert caught.value.data.get("reason") == "xml_not_well_formed"
    assert caught.value.data.get("part", "").lower().endswith("section0.xml")
    assert _sha(hwpx) == before_sha
    assert not session.candidates_dir.exists() or list(session.candidates_dir.iterdir()) == []


def test_fake_xml_source_unchanged_on_success(tmp_path):
    """Source file bytes are never modified — only the candidate is written."""
    hwpx = make_hwpx(tmp_path / "form.hwpx")
    before_sha = _sha(hwpx)
    session = _open_session(tmp_path, hwpx)
    tools, _ = _fake_xml_tools(tmp_path, fail=False)

    plan, approval = _build_and_approve(session, "xml", [
        {"kind": "replace_all", "find": "a", "replace": "b"},
    ])

    apply_plan(tools, session, plan, approval)
    assert _sha(hwpx) == before_sha


def test_xml_edit_run_refuses_file_equals_save_as(tmp_path, monkeypatch):
    """file == save_as is invalid_params before spawn."""
    tools = rt_engine.EngineTools()

    def must_not_spawn(*_a, **_k):
        raise AssertionError("xml child started for an in-place save")

    monkeypatch.setattr(rt_engine, "run_child", must_not_spawn)
    src = tmp_path / "same.hwpx"
    src.write_bytes(b"pk")
    ops = tmp_path / "ops.json"
    ops.write_text("[]", encoding="utf-8")
    with pytest.raises(RpcError) as caught:
        tools.xml_edit_run(src, ops, src)
    assert caught.value.code == "invalid_params"


def test_xml_capability_lists_first_wave_when_script_resolves():
    tools = rt_engine.EngineTools()
    cap = tools.xml_capability()
    assert cap["state"] == "available"
    assert cap["proofGrade"] == "structural"
    assert cap["reason"] is None
    assert cap["opKinds"] == list(XML_FIRST_WAVE)


def test_xml_capability_unavailable_without_script(monkeypatch):
    tools = rt_engine.EngineTools()
    monkeypatch.setattr(
        tools, "xml_backend",
        tools.root / "engine" / "scripts" / "no_such_xml_backend.py")
    cap = tools.xml_capability()
    assert cap["state"] == "unavailable"
    assert cap["proofGrade"] == "structural"
    assert cap["opKinds"] == list(XML_FIRST_WAVE)
    assert "xml_backend.py" in (cap["reason"] or "")
