import json
import os
import struct
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "xml_backend.py"
sys.path.insert(0, str(ROOT / "scripts"))
import fill_report as fr  # noqa: E402
HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
OPF = "http://www.idpf.org/2007/opf/"
ODF_MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"


def tiny_png(path, width=4, height=2):
    def chunk(name, payload):
        body = name + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    data = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    path.write_bytes(data)
    return data


def make_hwpx(path, table_label=False, solid_border=False):
    borders = ('<hh:borderFills itemCnt="2"><hh:borderFill id="0"/>'
               '<hh:borderFill id="4"><hh:leftBorder type="SOLID"/>'
               '<hh:rightBorder type="SOLID"/><hh:topBorder type="SOLID"/>'
               '<hh:bottomBorder type="SOLID"/></hh:borderFill></hh:borderFills>'
               if solid_border else
               '<hh:borderFills itemCnt="1"><hh:borderFill id="0"/></hh:borderFills>')
    header = f'''<hh:head xmlns:hh="{HH}"><hh:refList>
<hh:paraProperties itemCnt="2">
<hh:paraPr id="0"><hh:align horizontal="JUSTIFY"/></hh:paraPr>
<hh:paraPr id="1"><hh:align horizontal="CENTER"/></hh:paraPr>
</hh:paraProperties><hh:charProperties itemCnt="3">
<hh:charPr id="0" height="1000"/><hh:charPr id="1" height="900"><hh:bold/></hh:charPr>
<hh:charPr id="2" height="900"/>
</hh:charProperties>{borders}
</hh:refList><hh:binDataList itemCnt="1">
<hh:binData id="image1" href="BinData/image1.png" media-type="image/png"/>
</hh:binDataList></hh:head>'''.encode()
    secpr = ('<hp:secPr><hp:pagePr width="60000" height="84000">'
             '<hp:margin left="4000" right="5000" top="5000" bottom="5000" '
             'header="0" footer="0" gutter="1000"/></hp:pagePr></hp:secPr>')
    anchor = ('<hp:p id="10" paraPrIDRef="0"><hp:run charPrIDRef="0">'
              '<hp:t>Generic anchor</hp:t></hp:run></hp:p>')
    if table_label:
        body = (f'<hp:p id="1" paraPrIDRef="0"><hp:run charPrIDRef="0">{secpr}'
                f'</hp:run></hp:p><hp:p id="11" paraPrIDRef="1">'
                f'<hp:run charPrIDRef="0"><hp:tbl><hp:tr><hp:tc><hp:subList>{anchor}'
                f'</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>')
    else:
        body = ('<hp:p id="10" paraPrIDRef="0"><hp:run charPrIDRef="0">'
                f'{secpr}<hp:t>Generic anchor</hp:t></hp:run></hp:p>')
    section = f'<hp:sec xmlns:hp="{HP}">{body}</hp:sec>'.encode()
    content_hpf = f'''<opf:package xmlns:opf="{OPF}"><opf:manifest>
<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>
<opf:item id="image1" href="BinData/image1.png" media-type="image/png" isEmbeded="1"/>
<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>
</opf:manifest></opf:package>'''.encode()
    manifest = f'''<manifest:manifest xmlns:manifest="{ODF_MANIFEST}">
<manifest:file-entry manifest:media-type="application/xml" manifest:full-path="Contents/header.xml"/>
<manifest:file-entry manifest:media-type="image/png" manifest:full-path="BinData/image1.png"/>
</manifest:manifest>'''.encode()
    members = {"mimetype": b"application/hwp+zip",
               "Contents/header.xml": header,
               "Contents/section0.xml": section,
               "Contents/content.hpf": content_hpf,
               "META-INF/manifest.xml": manifest,
               "BinData/image1.png": b"existing-image",
               "BinData/untouched.bin": b"\x00untouched\xff"}
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return members


def run_cli(tmp_path, ops, table_label=False, solid_border=False):
    src, dst, ops_file = (tmp_path / n for n in ("in.hwpx", "out.hwpx", "ops.json"))
    members = make_hwpx(src, table_label, solid_border)
    ops_file.write_text(json.dumps(ops), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "edit", "--file", str(src),
         "--ops", str(ops_file), "--save-as", str(dst), "--json"],
        capture_output=True, text=True, encoding="utf-8")
    return result, dst, members


def local_nodes(root, name):
    return [n for n in root.iter() if n.tag.rsplit("}", 1)[-1] == name]


def section(path):
    with zipfile.ZipFile(path) as zf:
        return ET.fromstring(zf.read("Contents/section0.xml"))


def header(path):
    with zipfile.ZipFile(path) as zf:
        return ET.fromstring(zf.read("Contents/header.xml"))


def paragraph_structure(para):
    """Compact run/control/layout shape used by unit and real-workspace parity."""
    result = []
    for child in para:
        name = child.tag.rsplit("}", 1)[-1]
        children = tuple(grandchild.tag.rsplit("}", 1)[-1]
                         for grandchild in child)
        if name == "run" and not children and not "".join(child.itertext()):
            continue
        if name == "linesegarray":
            children = ("lineseg",)
        result.append((name, children))
    return result


def test_open_save_preserves_untouched_members_byte_for_byte(tmp_path):
    result, dst, original = run_cli(tmp_path, [])
    assert result.returncode == 0
    assert json.loads(result.stdout)["applied"] == 0
    with zipfile.ZipFile(dst) as zf:
        assert all(zf.read(name) == data for name, data in original.items())


def _write_fake_renderer(path, *, fail=False):
    if fail:
        source = "import sys\nsys.exit(7)\n"
    else:
        source = """\
import fitz
import sys

doc = fitz.open()
for text_y in (500, 700):
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, text_y), "rendered body")
doc.save(sys.argv[2])
"""
    path.write_text(source, encoding="utf-8")
    return [sys.executable, str(path), "{in}", "{out}"]


def _run_xml_fill_loop(tmp_path, monkeypatch, pdf_cmd, *, calibration=None):
    form = tmp_path / "form.hwpx"
    form.write_bytes(b"form")
    content = tmp_path / "content.md"
    content.write_text("## SECTION: Generic anchor\nbody\n", encoding="utf-8")
    build_yaml = tmp_path / "build.yaml"
    build_yaml.write_text(
        "fill:\n  target_pages: [1, 999]\n  bottom_white_max: 25\n"
        "  max_gap_lines: 3\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "fill"
    emitted = []

    def fake_build(content_, form_, build_yaml_, ops_out, form_profile=None):
        Path(ops_out).write_text("[]", encoding="utf-8")
        return {"ok": True, "ops": []}

    def fake_xml(form_, ops_path, out_hwpx):
        Path(out_hwpx).write_bytes(b"hwpx")
        return {"ok": True, "applied": 0}

    monkeypatch.setattr(fr, "run_build_report", fake_build)
    monkeypatch.setattr(fr, "run_xml_edit", fake_xml)
    monkeypatch.setattr(fr, "run_tidy_hwpx", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        fr, "run_para_format_check", lambda *a, **k: {"ok": True, "anomalies": []})
    monkeypatch.setattr(fr, "run_style_diff", lambda *a, **k: [])
    monkeypatch.setattr(fr, "_emit", lambda obj, out=None: emitted.append(obj))

    args = type("Args", (), {
        "form": str(form), "content": str(content), "out_dir": str(out_dir),
        "build_yaml": str(build_yaml), "max_loops": 1, "baseline": None,
        "trouble_table": None, "guide_file": None, "spacing_skip_pages": None,
        "gap_skip_pages": None, "bottom_skip_pages": None, "fig_count": 0,
        "kill_stale": False, "out": None, "engine": "xml", "pdf_cmd": pdf_cmd,
        "pdf_timeout": 10.0, "calibration": calibration, "form_profile": None,
        "proof": False,
    })()
    fr.mode_loop(args)
    assert len(emitted) == 1
    return emitted[0]


def test_xml_fill_loop_external_renderer_emits_com_contract(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    renderer = _write_fake_renderer(tmp_path / "render.py")
    verdict = _run_xml_fill_loop(tmp_path, monkeypatch, renderer)

    # The test's synthetic source is intentionally not a valid HWPX package;
    # quality must fail closed rather than treating unreadable source as
    # ASCII-only/not-applicable.
    assert verdict["proof_grade"] == "none"
    assert verdict["render_quality"]["state"] == "unknown"
    assert verdict["render_quality"]["reason_code"] == "source_unreadable"
    assert verdict["engine"] == "xml"
    assert {
        "converged", "state", "gappy_pages", "bottom_white_worst",
        "gaps_worst", "needs", "iterations", "escalate", "proof_grade",
    } <= verdict.keys()
    assert verdict["iterations"] == 1


def test_xml_fill_loop_calibration_relaxes_advisory_threshold(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    renderer = _write_fake_renderer(tmp_path / "render.py")
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps({
        "bottom_white_tolerance_pt": 79.2,
        "max_gap_scale": 2.0,
    }), encoding="utf-8")

    verdict = _run_xml_fill_loop(
        tmp_path, monkeypatch, renderer, calibration=str(calibration))

    assert verdict["proof_grade"] == "none"
    assert verdict["render_quality"]["state"] == "unknown"
    assert verdict["render_quality"]["reason_code"] == "source_unreadable"
    assert verdict["thresholds"]["bottom_white_max"] == pytest.approx(35.0)
    assert verdict["thresholds"]["max_gap_lines"] == 6.0
    assert verdict["calibration"]["max_gap_scale"] == 2.0


def test_direct_fill_report_advisory_quality_pass_stays_on_shared_hold(
    tmp_path, monkeypatch
):
    renderer = _write_fake_renderer(tmp_path / "render.py")
    quality = {
        "schema": fr.render_quality.QUALITY_SCHEMA,
        "checker": fr.render_quality.CHECKER_ID,
        "version": fr.render_quality.QUALITY_VERSION,
        "artifact_sha256": "a" * 64,
        "artifact_bytes": 1,
        "state": "passed",
        "reason_code": "passed",
        "source_hangul_count": 1,
        "pdf_hangul_count": 1,
        "page_count": 1,
        "mapped_font_xrefs": 1,
        "checked_font_xrefs": 1,
        "max_unique_hangul_per_xref": 1,
        "min_glyph_capacity": 2,
    }
    monkeypatch.setattr(fr.render_quality, "inspect", lambda *a, **k: quality)
    gate_calls = []

    def fake_apply_layout_gate(result, **kwargs):
        gate_calls.append(kwargs)
        assert kwargs["advisory_hold"] is True
        held = dict(result)
        held["state"] = "failed"
        held["reason_code"] = "visual_quality_gate_pending"
        return held

    monkeypatch.setattr(fr.render_quality, "apply_layout_gate", fake_apply_layout_gate)
    verdict = _run_xml_fill_loop(tmp_path, monkeypatch, renderer)
    assert fr.document_evidence.ADVISORY_PROOF_RELEASE_ENABLED is False
    assert len(gate_calls) == 1
    assert verdict["proof_grade"] == "none"
    assert verdict["render_quality"]["state"] == "failed"
    assert verdict["render_quality"]["reason_code"] == "visual_quality_gate_pending"


def test_fill_report_native_type3_quality_unknown_keeps_hancom_provenance(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.hwpx"
    rendered = tmp_path / "rendered.pdf"
    source.write_bytes(b"assembled")
    rendered.write_bytes(b"pdf")
    quality = {
        "schema": fr.render_quality.QUALITY_SCHEMA,
        "checker": fr.render_quality.CHECKER_ID,
        "version": fr.render_quality.QUALITY_VERSION,
        "artifact_sha256": "a" * 64,
        "artifact_bytes": 1,
        "state": "unknown",
        "reason_code": "type3_font",
        "source_hangul_count": 1,
        "pdf_hangul_count": 1,
        "page_count": 1,
        "mapped_font_xrefs": 1,
        "checked_font_xrefs": 0,
        "max_unique_hangul_per_xref": 1,
        "min_glyph_capacity": 0,
    }
    monkeypatch.setattr(fr.render_quality, "inspect", lambda *a, **k: quality)
    verdict = {
        "proof_grade": "hancom",
        "converged": True,
        "checks": {},
        "style_anomalies": [],
    }
    result = fr._apply_render_quality(verdict, source, rendered)
    assert result["state"] == "unknown"
    assert verdict["proof_grade"] == "hancom"
    assert verdict["quality_reason"] == "type3_font"


def test_xml_fill_loop_renderer_failure_is_never_a_pass(tmp_path, monkeypatch):
    renderer = _write_fake_renderer(tmp_path / "fail_renderer.py", fail=True)
    verdict = _run_xml_fill_loop(tmp_path, monkeypatch, renderer)

    assert verdict["state"] == "renderer_failed"
    assert verdict["status"] == "renderer_failed"
    assert verdict["ok"] is False
    assert verdict["converged"] is False
    assert verdict["proof_grade"] == "none"


def test_xml_fill_loop_no_renderer_writes_structural_receipt(tmp_path, monkeypatch):
    verdict = _run_xml_fill_loop(tmp_path, monkeypatch, None)

    receipt = fr.document_evidence.load_and_validate_receipt(tmp_path)
    assert verdict["proof_grade"] == "none"
    assert receipt["proof_grade"] == "none"
    assert receipt["execution"]["backend"] == "xml_only"
    assert receipt["execution"]["state"] == "succeeded"


def test_xml_no_renderer_verdict_keeps_contract_and_grade_none(tmp_path):
    verdict = fr.xml_only_verdict(
        tmp_path / "out.hwpx", {"ok": True, "anomalies": []})

    assert set(verdict) == {
        "status", "converged", "iterations", "engine", "phase",
        "proof_grade", "proof_unavailable", "reason", "checks",
        "style_anomalies", "needs", "hwpx", "pdf", "preview_pdf",
    }
    assert verdict["status"] == "xml_verified_no_proof"
    assert verdict["proof_grade"] == "none"


def test_hancom_measurement_ignores_advisory_calibration(tmp_path):
    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "hancom.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 700), "Hancom proof")
    doc.save(pdf)
    doc.close()
    fill = {
        "min_figures": 0, "target_pages": [1, 999],
        "bottom_white_max": 25.0, "max_gap_lines": 3.0,
    }

    verdict = fr.measure_rendered_pdf(
        pdf, fill, "hancom", fig_count_override=0,
        calibration={"bottom_white_tolerance_pt": 79.2, "max_gap_scale": 2.0})

    assert verdict["proof_grade"] == "hancom"
    assert verdict["thresholds"] == {
        "bottom_white_max": 25.0, "max_gap_lines": 3.0}
    assert "calibration" not in verdict


def test_goto_text_finds_single_run_anchor(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_text", "text": "Body"}])
    assert result.returncode == 0, result.stdout
    assert ["".join(p.itertext()) for p in local_nodes(section(dst), "p")] == [
        "Generic anchor", "Body"]


def test_anchor_missing_exits_3(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Absent anchor"}])
    assert result.returncode == 3
    assert json.loads(result.stdout)["anchors_missing"] == ["Absent anchor"]
    assert not dst.exists()


def test_replace_all_is_literal_per_text_node_and_reports_count(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "replace_all", "find": "e", "replace": "EE"}])
    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["results"] == [{"op": "replace_all", "replaced": 2}]
    assert "GEEnEEric anchor" == "".join(local_nodes(section(dst), "p")[0].itertext())


def test_insert_blank_before_precedes_anchor_and_inherits_refs(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "insert_blank_before", "text": "Generic anchor"}])
    assert result.returncode == 0, result.stdout
    paras = local_nodes(section(dst), "p")
    assert ["".join(p.itertext()) for p in paras] == ["", "Generic anchor"]
    assert paras[0].get("paraPrIDRef") == paras[1].get("paraPrIDRef") == "0"
    assert local_nodes(paras[0], "run")[0].get("charPrIDRef") == "0"
    assert json.loads(result.stdout)["results"][0]["inserted"] is True


def test_page_binding_submit_updates_section_margin_and_reports_note(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "page_binding", "mode": "submit"}])
    assert result.returncode == 0, result.stdout
    margin = local_nodes(section(dst), "margin")[0]
    assert {key: margin.get(key) for key in ("left", "right", "gutter")} == {
        "left": "5000", "right": "5000", "gutter": "0"}
    op_result = json.loads(result.stdout)["results"][0]
    assert op_result["binding"] == "submit"
    assert "section page definition" in op_result["note"]


def test_set_line_spacing_only_repoints_inserted_paragraphs_and_is_partial(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_text", "text": "Inserted body"},
        {"op": "set_line_spacing", "percent": 155, "all": True}])
    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["partial"] == [payload["results"][-1]["note"]]
    assert payload["results"][-1]["partial"] is True

    paras = local_nodes(section(dst), "p")
    assert paras[0].get("paraPrIDRef") == "0"
    inserted_ref = paras[1].get("paraPrIDRef")
    assert inserted_ref not in {None, "0"}
    variant = next(node for node in local_nodes(header(dst), "paraPr")
                   if node.get("id") == inserted_ref)
    spacing = local_nodes(variant, "lineSpacing")
    assert spacing and {node.get("type") for node in spacing} == {"PERCENT"}
    assert {node.get("value") for node in spacing} == {"155"}


def test_insert_picture_registers_package_and_preserves_png_aspect(tmp_path):
    image_path = tmp_path / "tiny.png"
    image_bytes = tiny_png(image_path, 4, 2)
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_picture", "path": str(image_path), "width_mm": 25.4,
         "caption": "Figure 1. Tiny image"}])
    assert result.returncode == 0, result.stdout

    with zipfile.ZipFile(dst) as zf:
        assert zf.read("BinData/image2.png") == image_bytes
        content_hpf = ET.fromstring(zf.read("Contents/content.hpf"))
        manifest = ET.fromstring(zf.read("META-INF/manifest.xml"))

    bin_item = next(node for node in local_nodes(header(dst), "binData")
                    if node.get("id") == "image2")
    assert bin_item.get("href") == "BinData/image2.png"
    opf_item = next(node for node in local_nodes(content_hpf, "item")
                    if node.get("id") == "image2")
    assert opf_item.get("href") == "BinData/image2.png"
    odf_entry = next(node for node in local_nodes(manifest, "file-entry")
                     if any(key.rsplit("}", 1)[-1] == "full-path"
                            and value == "BinData/image2.png"
                            for key, value in node.attrib.items()))
    assert odf_entry is not None

    root = section(dst)
    pic = local_nodes(root, "pic")[0]
    image_ref = local_nodes(pic, "img")[0].get("binaryItemIDRef")
    assert image_ref == "image2"
    size = local_nodes(pic, "sz")[0]
    assert int(size.get("width")) == 7200
    assert int(size.get("height")) == 3600
    paras = local_nodes(root, "p")
    picture_para = next(p for p in paras if pic in local_nodes(p, "pic"))
    assert picture_para.get("paraPrIDRef") == "1"
    caption_para = paras[paras.index(picture_para) + 1]
    assert "".join(caption_para.itertext()) == "Figure 1. Tiny image"
    assert local_nodes(caption_para, "run")[0].get("charPrIDRef") == "2"


def test_insert_text_adds_paragraphs_with_inherited_refs_and_bold_run(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_text", "text": "First bold\nSecond", "segments": [
            {"text": "First ", "bold": False},
            {"text": "bold\n", "bold": True},
            {"text": "Second", "bold": False}]}])
    assert result.returncode == 0, result.stdout
    paras = local_nodes(section(dst), "p")
    assert len(paras) == 3
    assert [p.attrib["paraPrIDRef"] for p in paras[1:]] == ["0", "0"]
    assert [r.attrib["charPrIDRef"] for r in local_nodes(paras[1], "run")] == ["0", "1"]
    assert "".join(paras[2].itertext()) == "Second"
    for para in paras[1:]:
        assert paragraph_structure(para)[-1] == ("linesegarray", ("lineseg",))
        lineseg = local_nodes(para, "lineseg")[0]
        assert set(lineseg.attrib) == {
            "textpos", "vertpos", "vertsize", "textheight", "baseline",
            "spacing", "horzpos", "horzsize", "flags"}
        assert lineseg.attrib["textpos"] == lineseg.attrib["vertpos"] == "0"
        assert int(lineseg.attrib["horzsize"]) > 0


def test_table_label_guard_splits_and_uses_justify(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor", "next_para": True},
        {"op": "insert_text", "text": "Body outside label paragraph"}],
        table_label=True)
    assert result.returncode == 0, result.stdout
    cells = local_nodes(section(dst), "tc")
    paras = local_nodes(cells[0], "p")
    assert ["".join(p.itertext()) for p in paras] == [
        "Generic anchor", "Body outside label paragraph"]
    assert paras[1].attrib["paraPrIDRef"] == "0"


def test_latex_equation_is_converted_and_inserted(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_equation", "latex": r"\frac{1}{2}"}])
    assert result.returncode == 0, result.stdout
    assert dst.exists()
    assert local_nodes(section(dst), "script")[0].text == "{1}over{2}"


def test_inline_equation_is_inserted_in_anchor_paragraph_verbatim(tmp_path):
    script = 'x < y & z = {[a]} + "quoted"'
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_equation", "hwpeqn": script, "display": False}])
    assert result.returncode == 0, result.stdout
    paras = local_nodes(section(dst), "p")
    assert len(paras) == 1
    assert len(local_nodes(paras[0], "run")) == 1
    equations = local_nodes(paras[0], "equation")
    assert len(equations) == 1
    assert "treatAsChar" not in equations[0].attrib
    assert equations[0].attrib["dropcapstyle"] == "None"
    assert equations[0].attrib["version"] == "Equation Version 60"
    assert equations[0].attrib["textColor"] == "#000000"
    assert [child.tag.rsplit("}", 1)[-1] for child in equations[0]] == [
        "sz", "pos", "outMargin", "shapeComment", "script"]
    pos = local_nodes(equations[0], "pos")[0]
    assert pos.attrib == {
        "treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1",
        "allowOverlap": "0", "holdAnchorAndSO": "0", "vertRelTo": "PARA",
        "horzRelTo": "PARA", "vertAlign": "TOP", "horzAlign": "LEFT",
        "vertOffset": "0", "horzOffset": "0",
    }
    assert local_nodes(equations[0], "outMargin")[0].attrib == {
        "left": "56", "right": "56", "top": "0", "bottom": "0"}
    assert local_nodes(equations[0], "shapeComment")[0].text == "수식입니다."
    assert local_nodes(equations[0], "script")[0].text == script
    assert [n.tag.rsplit("}", 1)[-1] for n in list(local_nodes(paras[0], "run")[0])][-1] == "t"


def test_display_equation_gets_own_centered_paragraph(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_equation", "hwpeqn": "E={mc^2}", "display": True},
        {"op": "insert_text", "text": "Body after equation"}])
    assert result.returncode == 0, result.stdout
    paras = local_nodes(section(dst), "p")
    assert len(paras) == 3
    assert paras[1].attrib["paraPrIDRef"] == "1"
    assert paras[2].attrib["paraPrIDRef"] == "0"
    assert "".join(paras[2].itertext()) == "Body after equation"
    assert len(local_nodes(paras[0], "equation")) == 0
    assert local_nodes(paras[1], "script")[0].text == "E={mc^2}"
    assert paragraph_structure(paras[1]) == [
        ("run", ("equation", "t")), ("linesegarray", ("lineseg",))]


def test_unbalanced_equation_script_exits_4_and_lists_op(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_equation", "hwpeqn": "x={y", "display": False}])
    assert result.returncode == 4
    payload = json.loads(result.stdout)
    assert payload["unsupported"] == ["insert_equation"]
    assert not dst.exists()


def test_table_ratios_cells_and_caption_are_emitted(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_table", "data": [["H1", "H2", "H3"], ["a", "b", "c"]],
         "col_ratios": [0.2, 0.3, 0.5], "font_pt": 9,
         "caption": "Table 1. Results"}])
    assert result.returncode == 0, result.stdout
    root = section(dst)
    tables = local_nodes(root, "tbl")
    assert len(tables) == 1
    assert tables[0].attrib["rowCnt"] == "2"
    assert tables[0].attrib["colCnt"] == "3"
    assert tables[0].attrib["dropcapstyle"] == "None"
    assert [child.tag.rsplit("}", 1)[-1] for child in list(tables[0])[:4]] == [
        "sz", "pos", "outMargin", "inMargin"]
    assert local_nodes(tables[0], "pos")[0].attrib == {
        "treatAsChar": "1", "affectLSpacing": "0", "flowWithText": "1",
        "allowOverlap": "0", "holdAnchorAndSO": "0", "vertRelTo": "PARA",
        "horzRelTo": "PARA", "vertAlign": "TOP", "horzAlign": "LEFT",
        "vertOffset": "0", "horzOffset": "0",
    }
    assert local_nodes(tables[0], "outMargin")[0].attrib == {
        "left": "141", "right": "141", "top": "141", "bottom": "141"}
    assert local_nodes(tables[0], "inMargin")[0].attrib == {
        "left": "510", "right": "510", "top": "141", "bottom": "141"}
    assert len(local_nodes(tables[0], "tc")) == 6
    widths = [int(n.attrib["width"]) for n in local_nodes(tables[0], "cellSz")[:3]]
    assert sum(widths) == 60000 - 5000 - 5000 - 567
    assert widths[0] / widths[1] == pytest.approx(2 / 3, rel=1e-3)
    assert widths[1] / widths[2] == pytest.approx(3 / 5, rel=1e-3)
    cell_runs = [local_nodes(cell, "run")[0]
                 for cell in local_nodes(tables[0], "tc")]
    assert [run.attrib["charPrIDRef"] for run in cell_runs] == ["2"] * 6
    for cell in local_nodes(tables[0], "tc"):
        assert cell.attrib["header"] == "0"
        assert [child.tag.rsplit("}", 1)[-1] for child in cell] == [
            "subList", "cellAddr", "cellSpan", "cellSz", "cellMargin"]
        cell_para = local_nodes(cell, "p")[0]
        assert cell_para.attrib == {
            "id": "0", "paraPrIDRef": "0", "styleIDRef": "0",
            "pageBreak": "0", "columnBreak": "0", "merged": "0"}
        assert paragraph_structure(cell_para) == [
            ("run", ("t",)), ("linesegarray", ("lineseg",))]
        assert local_nodes(cell, "cellSz")[0].attrib["height"] == "282"
    table_run = next(run for run in local_nodes(root, "run") if tables[0] in list(run))
    assert [child.tag.rsplit("}", 1)[-1] for child in table_run][-1] == "t"
    paras = local_nodes(root, "p")
    assert "".join(paras[-1].itertext()) == "Table 1. Results"
    assert paras[-1].attrib["paraPrIDRef"] == "0"


def test_no_table_form_adds_and_uses_solid_border_fill(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_table", "data": [["H"], ["value"]]}])
    assert result.returncode == 0, result.stdout

    table = local_nodes(section(dst), "tbl")[0]
    border_id = table.get("borderFillIDRef")
    border_fill = next(node for node in local_nodes(header(dst), "borderFill")
                       if node.get("id") == border_id)
    sides = {node.tag.rsplit("}", 1)[-1]: node.get("type")
             for node in border_fill}
    assert all(sides[name] == "SOLID" for name in (
        "leftBorder", "rightBorder", "topBorder", "bottomBorder"))
    assert {cell.get("borderFillIDRef") for cell in local_nodes(table, "tc")} == {border_id}


def test_no_table_form_reuses_existing_solid_border_fill(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_table", "data": [["H"], ["value"]]}],
        solid_border=True)
    assert result.returncode == 0, result.stdout
    assert local_nodes(section(dst), "tbl")[0].get("borderFillIDRef") == "4"
    assert [node.get("id") for node in local_nodes(header(dst), "borderFill")] == ["0", "4"]


def test_table_leaves_justified_paragraph_for_following_caption_op(tmp_path):
    result, dst, _ = run_cli(tmp_path, [
        {"op": "goto_text", "text": "Generic anchor"},
        {"op": "insert_table", "data": [["H1"], ["a"]], "font_pt": 9},
        {"op": "insert_text", "text": "Table 1. Separate caption", "break_after": True}])
    assert result.returncode == 0, result.stdout
    paras = local_nodes(section(dst), "p")
    assert "".join(paras[-1].itertext()) == "Table 1. Separate caption"
    assert paras[-1].attrib["paraPrIDRef"] == "0"


def _workspace_root():
    value = os.environ.get("HWP_MASTER_WS")
    if not value:
        return None
    path = Path(value)
    return path if (path / "bundle" / "content.md").is_file() else None


@pytest.mark.skipif(_workspace_root() is None, reason="HWP_MASTER_WS finished workspace not set")
def test_real_workspace_core_content_parity(tmp_path):
    """Compare XML-core inserted payloads with the real COM-produced document."""
    ws = _workspace_root()
    form = next((p for p in (ws / "output" / "form_copy.hwpx",
                             ws / "output" / "form_copy_orig.hwpx") if p.is_file()), None)
    real = ws / "output" / "out.hwpx"
    assert form is not None and real.is_file()

    built = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_report.py"),
         "--content", str(ws / "bundle" / "content.md"), "--dry-run",
         "--build-yaml", str(ws / "build.yaml")],
        capture_output=True, text=True, encoding="utf-8", check=True)
    all_ops = json.loads(built.stdout)["ops"]
    supported = {"goto_text", "insert_text", "insert_equation", "insert_table"}
    core_ops = [op for op in all_ops if op["op"] in supported]
    ops_path = tmp_path / "real-core-ops.json"
    out_path = tmp_path / "xml-out.hwpx"
    ops_path.write_text(json.dumps(core_ops, ensure_ascii=False), encoding="utf-8")
    applied = subprocess.run(
        [sys.executable, str(SCRIPT), "edit", "--file", str(form),
         "--ops", str(ops_path), "--save-as", str(out_path), "--json"],
        capture_output=True, text=True, encoding="utf-8")
    assert applied.returncode == 0, applied.stdout + applied.stderr

    def roots(path):
        with zipfile.ZipFile(path) as zf:
            return [ET.fromstring(zf.read(name)) for name in sorted(
                n for n in zf.namelist()
                if n.startswith("Contents/section") and n.endswith(".xml"))]

    def norm(value):
        return " ".join((value or "").split())

    xml_roots, real_roots = roots(out_path), roots(real)
    divergences = []
    text_values = [norm(op.get("text")) for op in core_ops
                   if op["op"] == "insert_text" and norm(op.get("text"))]
    for text_value in text_values:
        for label, section_roots in (("xml", xml_roots), ("com", real_roots)):
            para_texts = {norm("".join(p.itertext())) for root in section_roots
                          for p in local_nodes(root, "p")}
            if text_value not in para_texts:
                divergences.append(f"{label}: missing paragraph {text_value[:60]!r}")

    expected_scripts = [op["hwpeqn"] for op in core_ops if op["op"] == "insert_equation"]
    for label, section_roots in (("xml", xml_roots), ("com", real_roots)):
        scripts = [n.text or "" for root in section_roots for n in local_nodes(root, "script")]
        if scripts != expected_scripts:
            divergences.append(f"{label}: equation scripts differ")

    def style_maps(path):
        with zipfile.ZipFile(path) as zf:
            header = ET.fromstring(zf.read("Contents/header.xml"))
        chars = {}
        paras = {}
        for node in header.iter():
            name = node.tag.rsplit("}", 1)[-1]
            if name == "charPr":
                chars[node.get("id")] = (
                    node.get("height"), bool(local_nodes(node, "bold")))
            elif name == "paraPr":
                aligns = local_nodes(node, "align")
                paras[node.get("id")] = aligns[0].get("horizontal") if aligns else None
        return chars, paras

    def border_maps(path):
        def fingerprint(node):
            return (node.tag.rsplit("}", 1)[-1],
                    tuple(sorted((key, value) for key, value in node.attrib.items()
                                 if key != "id")),
                    tuple(fingerprint(child) for child in node))
        with zipfile.ZipFile(path) as zf:
            header = ET.fromstring(zf.read("Contents/header.xml"))
        return {node.get("id"): fingerprint(node) for node in header.iter()
                if node.tag.rsplit("}", 1)[-1] == "borderFill"}

    def contexts(section_roots, control_name, char_styles, para_styles):
        result = []
        for root in section_roots:
            parents = {child: parent for parent in root.iter() for child in parent}
            for control in local_nodes(root, control_name):
                run = parents[control]
                para = parents[run]
                result.append({
                    "attrs": {key: value for key, value in control.attrib.items()
                              if key not in {"id", "instId", "zOrder"}},
                    "children": [child.tag.rsplit("}", 1)[-1] for child in control],
                    "run_children": [child.tag.rsplit("}", 1)[-1] for child in run],
                    "para_structure": paragraph_structure(para),
                    "char_style": char_styles.get(run.get("charPrIDRef")),
                    "para_align": para_styles.get(para.get("paraPrIDRef")),
                })
        return result

    xml_styles, xml_paras = style_maps(out_path)
    com_styles, com_paras = style_maps(real)
    xml_borders, com_borders = border_maps(out_path), border_maps(real)

    def inserted_paragraphs(section_roots, text_value):
        return [p for root in section_roots for p in local_nodes(root, "p")
                if norm("".join(p.itertext())) == text_value]

    for text_value in text_values:
        xml_matches = inserted_paragraphs(xml_roots, text_value)
        com_matches = inserted_paragraphs(real_roots, text_value)
        if len(xml_matches) != 1 or len(com_matches) != 1:
            divergences.append(
                f"paragraph {text_value[:40]!r} matches xml={len(xml_matches)} "
                f"com={len(com_matches)}")
            continue
        xml_para, com_para = xml_matches[0], com_matches[0]
        if paragraph_structure(xml_para) != paragraph_structure(com_para):
            divergences.append(
                f"paragraph {text_value[:40]!r} structure: "
                f"xml={paragraph_structure(xml_para)} com={paragraph_structure(com_para)}")
        xml_refs = [xml_styles.get(run.get("charPrIDRef"))
                    for run in xml_para if run.tag.rsplit("}", 1)[-1] == "run"
                    and (list(run) or "".join(run.itertext()))]
        com_refs = [com_styles.get(run.get("charPrIDRef"))
                    for run in com_para if run.tag.rsplit("}", 1)[-1] == "run"
                    and (list(run) or "".join(run.itertext()))]
        if xml_refs != com_refs:
            divergences.append(
                f"paragraph {text_value[:40]!r} charPrIDRef: "
                f"xml={xml_refs} com={com_refs}")

    xml_eq = contexts(xml_roots, "equation", xml_styles, xml_paras)
    com_eq = contexts(real_roots, "equation", com_styles, com_paras)
    if len(xml_eq) != len(com_eq):
        divergences.append(f"equation structure counts xml={len(xml_eq)} com={len(com_eq)}")
    else:
        for index, (xml_context, com_context) in enumerate(zip(xml_eq, com_eq)):
            for key in ("attrs", "children", "para_structure", "char_style", "para_align"):
                if xml_context[key] != com_context[key]:
                    divergences.append(
                        f"equation {index} {key}: xml={xml_context[key]} com={com_context[key]}")
            if xml_context["run_children"][-2:] != com_context["run_children"][-2:]:
                divergences.append(f"equation {index} run/control structure differs")

    expected_tables = [op for op in core_ops if op["op"] == "insert_table"]
    table_signatures = {}
    for table_index, op in enumerate(expected_tables):
        expected_cells = [[norm(str(value)) for value in row] for row in op["data"]]
        for label, section_roots in (("xml", xml_roots), ("com", real_roots)):
            matches = []
            for root in section_roots:
                for table in local_nodes(root, "tbl"):
                    rows = [[norm("".join(cell.itertext())) for cell in local_nodes(row, "tc")]
                            for row in local_nodes(table, "tr")]
                    if rows == expected_cells:
                        matches.append((table, root))
            if len(matches) != 1:
                divergences.append(f"{label}: table {table_index} payload matches={len(matches)}")
                continue
            table, root = matches[0]
            first_row = local_nodes(table, "tr")[0]
            widths = [int(local_nodes(cell, "cellSz")[0].attrib["width"])
                      for cell in local_nodes(first_row, "tc")]
            ratios = [width / sum(widths) for width in widths]
            expected_ratios = op.get("col_ratios") or [1] * len(widths)
            expected_ratios = [value / sum(expected_ratios) for value in expected_ratios]
            if ratios != pytest.approx(expected_ratios, abs=2e-4):
                divergences.append(f"{label}: table {table_index} width ratios {ratios}")
            parents = {child: parent for parent in root.iter() for child in parent}
            run = parents[table]
            para = parents[run]
            char_styles = xml_styles if label == "xml" else com_styles
            para_styles = xml_paras if label == "xml" else com_paras
            cells = local_nodes(table, "tc")
            cell_styles = []
            for cell in cells:
                cell_run = local_nodes(cell, "run")[0]
                cell_styles.append(char_styles.get(cell_run.get("charPrIDRef")))
            border_styles = xml_borders if label == "xml" else com_borders
            border_style = border_styles.get(table.get("borderFillIDRef"))
            cell_border_style = border_styles.get(cells[0].get("borderFillIDRef"))
            table_signatures[label, table_index] = {
                "attrs": {key: (border_style if key == "borderFillIDRef" else value)
                          for key, value in table.attrib.items()
                          if key not in {"id", "instId", "zOrder"}},
                "children": [child.tag.rsplit("}", 1)[-1] for child in list(table)[:4]],
                "run_children": [child.tag.rsplit("}", 1)[-1] for child in run],
                "para_structure": paragraph_structure(para),
                "char_style": char_styles.get(run.get("charPrIDRef")),
                "para_align": para_styles.get(para.get("paraPrIDRef")),
                "border_style": border_style,
                "tc_attrs": {
                    key: (cell_border_style if key == "borderFillIDRef" else value)
                    for key, value in cells[0].attrib.items()
                    if key not in {"id", "instId", "zOrder"}},
                "tc_children": [child.tag.rsplit("}", 1)[-1] for child in cells[0]],
                "cell_border_style": cell_border_style,
                "cell_para_structures": [paragraph_structure(local_nodes(cell, "p")[0])
                                         for cell in cells],
                "cell_styles": cell_styles,
            }

        xml_signature = table_signatures.get(("xml", table_index))
        com_signature = table_signatures.get(("com", table_index))
        if xml_signature and com_signature:
            for key in xml_signature:
                if xml_signature[key] != com_signature[key]:
                    divergences.append(
                        f"table {table_index} {key}: xml={xml_signature[key]} "
                        f"com={com_signature[key]}")

    print("real parity divergences:", json.dumps(divergences, ensure_ascii=False))
    assert not divergences, "\n".join(divergences)
