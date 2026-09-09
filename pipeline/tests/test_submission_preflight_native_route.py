# -*- coding: utf-8 -*-
"""Native Hancom route: section skeletons must survive, header drift is WARN, anchors are HARD."""
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import submission_preflight as sp  # noqa: E402

HEADER = "<hh:head xmlns:hh='h'><hh:charPr id='0' height='1000'/><hh:paraPr id='0'/></hh:head>"


def _hwpx(path: Path, body: str, header: str = HEADER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", header)
        z.writestr("Contents/section0.xml", f"<hs:sec xmlns:hs='s'>{body}</hs:sec>")


def _native_receipt(ws: Path) -> None:
    p = ws / sp.document_evidence.RECEIPT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "schema": "rigorloom/document-evidence/v1", "proof_grade": "hancom",
        "evidence_class": "native_render",
        "execution": {"backend": "native_hancom_windows", "state": "succeeded", "exit_code": 0},
    }), encoding="utf-8")


def _profile(ws: Path, anchors) -> None:
    (ws / "form_profile.json").write_text(json.dumps({"anchors": anchors}, ensure_ascii=False), encoding="utf-8")
    (ws / "build.yaml").write_text('delete_texts:\n  - "(guide text)"\n', encoding="utf-8")


FORM_BODY = "<hs:secPr landscape='false'/><hs:tbl rowCnt='1' colCnt='1'><hs:tc colAddr='0' rowAddr='0'><p/></hs:tc></hs:tbl><p>Ⅰ. 서론</p><p>(guide text)</p><p>Ⅱ. 본론</p>"


def test_native_backend_detected_only_with_succeeded_native_receipt(tmp_path):
    assert sp._native_reserializing_backend(tmp_path) is None
    _native_receipt(tmp_path)
    assert sp._native_reserializing_backend(tmp_path) == "native_hancom_windows"


def test_pristine_form_is_accepted_only_when_its_digest_is_the_baseline(tmp_path):
    form = tmp_path / "output" / "form_copy.hwpx"
    _hwpx(form, FORM_BODY)
    digest = sp._hwpx_form_structure_sha256(form)
    assert sp._pristine_form(tmp_path, digest) == form
    assert sp._pristine_form(tmp_path, "0" * 64) is None


def test_insertions_are_allowed_but_form_section_records_must_survive_in_order(tmp_path):
    form = tmp_path / "output" / "form_copy.hwpx"
    _hwpx(form, FORM_BODY)
    # the report inserted its own table and controls, header styles were re-emitted
    art = tmp_path / "output" / "out.hwpx"
    _hwpx(art, "<hs:secPr landscape='false'/><hs:tbl rowCnt='1' colCnt='1'><hs:tc colAddr='0' rowAddr='0'><p/></hs:tc></hs:tbl>"
               "<p>Ⅰ. 서론</p><p>본문</p><hs:ctrl/><hs:tbl rowCnt='2' colCnt='2'><hs:tc colAddr='0' rowAddr='0'/><hs:tc colAddr='1' rowAddr='0'/></hs:tbl><p>Ⅱ. 본론</p>",
          header="<hh:head xmlns:hh='h'><hh:charPr id='0' height='1000'/><hh:charPr id='1' height='900'/><hh:paraPr id='0'/><hh:paraPr id='1'/></hh:head>")
    assert sp._section_skeleton_findings(form, art) == []
    # a mutated form table (colCnt changed) is a deletion of the form record
    bad = tmp_path / "output" / "bad.hwpx"
    _hwpx(bad, "<hs:secPr landscape='false'/><hs:tbl rowCnt='1' colCnt='2'><hs:tc colAddr='0' rowAddr='0'><p/></hs:tc><hs:tc colAddr='1' rowAddr='0'/></hs:tbl>")
    findings = sp._section_skeleton_findings(form, bad)
    assert [f["code"] for f in findings] == ["form_mutated"] and findings[0]["kind"] == "tbl"


def test_anchors_in_order_pass_and_guide_text_is_ignored(tmp_path):
    _profile(tmp_path, ["[title]", "Ⅰ. 서론", "(guide text)", "Ⅱ. 본론"])
    art = tmp_path / "output" / "out.hwpx"
    _hwpx(art, "<p>제목</p><p>Ⅰ. 서론</p><p>본문</p><p>Ⅱ. 본론</p>")
    assert sp._form_anchor_findings(tmp_path, art) == []


def test_missing_or_reordered_anchor_is_hard(tmp_path):
    _profile(tmp_path, ["Ⅰ. 서론", "Ⅱ. 본론"])
    art = tmp_path / "output" / "out.hwpx"
    _hwpx(art, "<p>Ⅱ. 본론</p><p>Ⅰ. 서론</p>")
    findings = sp._form_anchor_findings(tmp_path, art)
    assert [f["code"] for f in findings] == ["form_anchor_missing"]
    assert findings[0]["anchor"] == "Ⅱ. 본론"
