"""Frozen report compilation and extracted XML worker tests (S4 guards).

All tests in this module use self-contained synthetic HWPX, PNG, and PDF
fixtures generated inside ``tmp_path``.  They have zero dependency on
``tests/real``, ``tests/hwp5/gt``, or ``HWP_MASTER_WS``.
"""
from __future__ import annotations

import argparse
import ast
import copy
import errno
import hashlib
import inspect
import io
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

HERE = Path(__file__).resolve().parent
ENGINE_ROOT = HERE.parent
SCRIPTS_DIR = ENGINE_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_report as br  # noqa: E402
import document_evidence  # noqa: E402
import fill_report as fr  # noqa: E402
import form_inspect  # noqa: E402
import layout_qa  # noqa: E402
import report_xml_worker as worker  # noqa: E402
import style_diff  # noqa: E402
import xml_backend  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
OPF = "http://www.idpf.org/2007/opf/"
ODF_MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"


def _tiny_png(path: Path, width: int = 8, height: int = 4) -> bytes:
    def chunk(name: bytes, payload: bytes) -> bytes:
        body = name + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body))
        )

    rows = b"".join(b"\x00" + b"\x11\x22\x33" * width for _ in range(height))
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _make_synthetic_form_hwpx(
    path: Path,
    *,
    include_bold: bool = True,
    anchors: tuple[str, ...] = ("I. Intro", "II. Results"),
    blanks_before_second: int = 3,
    include_label_table: bool = False,
) -> Path:
    """Create a deterministic self-contained synthetic HWPX report form."""
    if include_bold:
        char_prs = (
            '<hh:charPr id="0" height="1000" textColor="#000000"><hh:fontRef hangul="0"/></hh:charPr>'
            '<hh:charPr id="1" height="1000" textColor="#000000"><hh:fontRef hangul="0"/><hh:bold/></hh:charPr>'
            '<hh:charPr id="2" height="900" textColor="#000000"><hh:fontRef hangul="0"/></hh:charPr>'
            '<hh:charPr id="3" height="1200" textColor="#000000"><hh:fontRef hangul="0"/><hh:bold/></hh:charPr>'
        )
        char_cnt = 4
        heading_charpr = "3"
    else:
        char_prs = (
            '<hh:charPr id="0" height="1000" textColor="#000000"><hh:fontRef hangul="0"/></hh:charPr>'
            '<hh:charPr id="2" height="900" textColor="#000000"><hh:fontRef hangul="0"/></hh:charPr>'
            '<hh:charPr id="3" height="1200" textColor="#000000"><hh:fontRef hangul="0"/></hh:charPr>'
        )
        char_cnt = 3
        heading_charpr = "3"

    header = (
        f'<hh:head xmlns:hh="{HH}">'
        '<hh:refList>'
        '<hh:fontfaces itemCnt="1">'
        '<hh:fontface lang="HANGUL" fontCnt="1">'
        '<hh:font id="0" face="HamchoromBatang" type="TTF" isEmbedded="0"/>'
        '</hh:fontface>'
        '</hh:fontfaces>'
        '<hh:borderFills itemCnt="2">'
        '<hh:borderFill id="0"/>'
        '<hh:borderFill id="1">'
        '<hh:leftBorder type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hh:rightBorder type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hh:topBorder type="SOLID" width="0.12 mm" color="#000000"/>'
        '<hh:bottomBorder type="SOLID" width="0.12 mm" color="#000000"/>'
        '</hh:borderFill>'
        '</hh:borderFills>'
        '<hh:paraProperties itemCnt="3">'
        '<hh:paraPr id="0"><hh:align horizontal="JUSTIFY"/>'
        '<hh:breakSetting keepWithNext="0" widowOrphan="0"/>'
        '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hh:paraPr>'
        '<hh:paraPr id="1"><hh:align horizontal="CENTER"/>'
        '<hh:breakSetting keepWithNext="0" widowOrphan="0"/>'
        '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hh:paraPr>'
        '<hh:paraPr id="2"><hh:align horizontal="JUSTIFY"/>'
        '<hh:breakSetting keepWithNext="0" widowOrphan="0"/>'
        '<hh:lineSpacing type="PERCENT" value="180" unit="HWPUNIT"/></hh:paraPr>'
        '</hh:paraProperties>'
        f'<hh:charProperties itemCnt="{char_cnt}">{char_prs}</hh:charProperties>'
        '</hh:refList>'
        '<hh:binDataList itemCnt="1">'
        '<hh:binData id="image1" href="BinData/image1.png" media-type="image/png"/>'
        '</hh:binDataList>'
        '</hh:head>'
    ).encode("utf-8")

    sec_pr = (
        '<hp:secPr>'
        '<hp:pagePr width="59528" height="84188">'
        '<hp:margin left="4000" right="5000" top="5000" bottom="5000" '
        'header="0" footer="0" gutter="1000"/>'
        '</hp:pagePr>'
        '</hp:secPr>'
    )
    paras = [
        f'<hp:p id="1" paraPrIDRef="2"><hp:run charPrIDRef="{heading_charpr}">'
        f'{sec_pr}<hp:t>TITLE_PLACEHOLDER</hp:t></hp:run></hp:p>'
    ]
    next_id = 2

    if include_label_table:
        paras.append(
            f'<hp:p id="{next_id}" paraPrIDRef="0"><hp:run charPrIDRef="0">'
            '<hp:tbl borderFillIDRef="1">'
            '<hp:tr><hp:tc borderFillIDRef="1"><hp:subList>'
            f'<hp:p id="{next_id + 1}" paraPrIDRef="1"><hp:run charPrIDRef="0"><hp:t>Summary</hp:t></hp:run></hp:p>'
            '</hp:subList><hp:cellAddr colAddr="0" rowAddr="0"/></hp:tc></hp:tr>'
            '<hp:tr><hp:tc borderFillIDRef="1"><hp:subList>'
            f'<hp:p id="{next_id + 2}" paraPrIDRef="0"><hp:run charPrIDRef="0"/></hp:p>'
            '</hp:subList><hp:cellAddr colAddr="0" rowAddr="1"/></hp:tc></hp:tr>'
            '</hp:tbl></hp:run></hp:p>'
        )
        next_id += 3

    for idx, anchor in enumerate(anchors):
        if idx > 0:
            for _ in range(blanks_before_second):
                paras.append(
                    f'<hp:p id="{next_id}" paraPrIDRef="0"><hp:run charPrIDRef="0"/></hp:p>'
                )
                next_id += 1
        paras.append(
            f'<hp:p id="{next_id}" paraPrIDRef="2"><hp:run charPrIDRef="{heading_charpr}">'
            f'<hp:t>{anchor}</hp:t></hp:run></hp:p>'
        )
        next_id += 1
        paras.append(
            f'<hp:p id="{next_id}" paraPrIDRef="0"><hp:run charPrIDRef="0"/></hp:p>'
        )
        next_id += 1

    section = f'<hp:sec xmlns:hp="{HP}" xmlns:hc="{HC}">{"".join(paras)}</hp:sec>'.encode("utf-8")
    content_hpf = (
        f'<opf:package xmlns:opf="{OPF}"><opf:manifest>'
        '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
        '<opf:item id="image1" href="BinData/image1.png" media-type="image/png" isEmbeded="1"/>'
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
        '</opf:manifest></opf:package>'
    ).encode("utf-8")
    manifest = (
        f'<manifest:manifest xmlns:manifest="{ODF_MANIFEST}">'
        '<manifest:file-entry manifest:media-type="application/xml" manifest:full-path="Contents/header.xml"/>'
        '<manifest:file-entry manifest:media-type="image/png" manifest:full-path="BinData/image1.png"/>'
        '</manifest:manifest>'
    ).encode("utf-8")

    path.parent.mkdir(parents=True, exist_ok=True)
    fixed_dt = (2026, 1, 2, 3, 4, 6)
    members = {
        "mimetype": b"application/hwp+zip",
        "Contents/header.xml": header,
        "Contents/section0.xml": section,
        "Contents/content.hpf": content_hpf,
        "META-INF/manifest.xml": manifest,
        "BinData/image1.png": b"\x89PNG\r\n\x1a\nplaceholder",
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=fixed_dt)
            zf.writestr(info, data)
    return path


def _build_rich_workspace(
    ws: Path,
    *,
    include_profile: bool = True,
    include_baseline: bool = True,
    explicit_tidy_and_kwn: bool = True,
) -> dict[str, Path]:
    ws.mkdir(parents=True, exist_ok=True)
    form = _make_synthetic_form_hwpx(ws / "output" / "form_copy.hwpx")
    fig_path = ws / "bundle" / "figures" / "plot.png"
    _tiny_png(fig_path, 8, 4)

    content = ws / "bundle" / "content.md"
    content.write_text(
        "---\n"
        'title: "Synthetic Frozen Report"\n'
        'title_anchor: "TITLE_PLACEHOLDER"\n'
        "binding: submit\n"
        "base_pt: 10\n"
        "caption_pt: 9\n"
        "line_spacing: 160\n"
        "---\n\n"
        "## SECTION: I. Intro\n\n"
        'Intro **bold span** with inline math [[EQ latex="x^2 + \\alpha"]] here.\n\n'
        '[[EQ display hwpeqn="{a} over {b}"]]\n\n'
        "## SECTION: II. Results\n\n"
        '[[TABLE cols=30,70 pt=9 caption="Table 1. Summary"]]\n'
        "| Metric | Value |\n"
        "| --- | --- |\n"
        "| Speed | 42 |\n"
        "[[/TABLE]]\n\n"
        '[[FIG file="plot.png" width=80 caption="Figure 1. Plot"]]\n',
        encoding="utf-8",
    )

    by_lines = [
        "base_pt: 10",
        "caption_pt: 9",
        "line_spacing: 160",
        "fill:",
        "  target_pages: [1, 5]",
        "  min_figures: 1",
    ]
    if explicit_tidy_and_kwn:
        by_lines.extend([
            "tidy_blank_before:",
            '  - "II. Results"',
            "keep_with_next:",
            '  - "Table 1."',
        ])
    build_yaml = ws / "build.yaml"
    build_yaml.write_text("\n".join(by_lines) + "\n", encoding="utf-8")

    profile_path = ws / "form_profile.json"
    baseline_path = ws / "form_baseline.json"
    if include_profile or include_baseline:
        profile, baseline = form_inspect.analyze(form, want_baseline=True)
        if include_profile:
            profile_path.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if include_baseline:
            baseline_path.write_text(
                json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    return {
        "ws": ws,
        "form": form,
        "content": content,
        "build_yaml": build_yaml,
        "profile": profile_path if include_profile else None,
        "baseline": baseline_path if include_baseline else None,
        "figure": fig_path,
    }


def _zip_members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name) for name in sorted(zf.namelist())}


def _freeze_zipfile_time(monkeypatch) -> None:
    fixed_struct = (2026, 2, 3, 4, 5, 6, 1, 34, 0)
    monkeypatch.setattr(zipfile.time, "time", lambda: 1770091506.0)
    monkeypatch.setattr(
        zipfile.time, "localtime", lambda _secs=None: fixed_struct
    )


def _normalize_verdict(verdict: dict, hwpx_path: Path) -> dict:
    norm = dict(verdict)
    norm["hwpx"] = "<OUT_HWPX>" if norm.get("hwpx") == str(hwpx_path.resolve()) else norm.get("hwpx")
    return norm


def _local_nodes(root: ET.Element, name: str) -> list[ET.Element]:
    return [n for n in root.iter() if n.tag.rsplit("}", 1)[-1] == name]


# ---------------------------------------------------------------------------
# 1. End-to-end synthetic integration
# ---------------------------------------------------------------------------


def test_synthetic_end_to_end_real_compiler_worker_and_para_check(tmp_path: Path):
    """Real compiler + xml_backend + tidy + restore + keep_with_next + typeset + style_diff."""
    env = _build_rich_workspace(tmp_path / "ws")
    snap_dir = tmp_path / "snap"
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        snap_dir,
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    out_hwpx = tmp_path / "out" / "assembled.hwpx"
    res = worker.execute_frozen_xml_worker(req, out_hwpx)

    assert res.ok is True
    assert res.steps_executed == [
        "xml_edit",
        "tidy_hwpx",
        "restore_para_formats",
        "keep_with_next",
        "typeset_defaults",
        "para_format_check",
    ]
    assert res.para_verification["ok"] is True
    assert res.para_verification["anomalies"] == []

    # Verify via standalone style_diff check as well.
    sd_check = style_diff.check_para_formats(env["form"], out_hwpx)
    assert sd_check["ok"] is True
    assert sd_check["anomalies"] == []

    members = _zip_members(out_hwpx)
    assert "BinData/image2.png" in members
    assert members["BinData/image2.png"] == env["figure"].read_bytes()

    sec_root = ET.fromstring(members["Contents/section0.xml"])
    hdr_root = ET.fromstring(members["Contents/header.xml"])
    all_text = "\n".join("".join(p.itertext()) for p in _local_nodes(sec_root, "p"))
    assert "Synthetic Frozen Report" in all_text
    assert "TITLE_PLACEHOLDER" not in all_text
    assert "bold span" in all_text
    assert "Table 1. Summary" in all_text
    assert "Figure 1. Plot" in all_text

    scripts = [n.text for n in _local_nodes(sec_root, "script")]
    assert len(scripts) == 2
    assert "alpha" in scripts[0]
    assert scripts[1] == "{a} over {b}"

    shape_comments = [n.text for n in _local_nodes(sec_root, "shapeComment") if n.text]
    assert any("Original file: plot.png" in c for c in shape_comments)

    # page_binding mode=submit balanced margins symmetrically.
    margin = _local_nodes(sec_root, "margin")[0]
    assert margin.get("left") == "5000"
    assert margin.get("right") == "5000"
    assert margin.get("gutter") == "0"

    # tidy_hwpx collapsed the 3 blanks before II. Results + 1 inserted blank -> 1 blank.
    top_paras = [p for p in sec_root if p.tag.rsplit("}", 1)[-1] == "p"]
    ii_idx = next(
        idx for idx, p in enumerate(top_paras) if "II. Results" in "".join(p.itertext())
    )
    assert "".join(top_paras[ii_idx - 1].itertext()).strip() == ""
    assert "".join(top_paras[ii_idx - 2].itertext()).strip() != ""

    # typeset_defaults + keep_with_next populated breakSetting attributes in header.
    break_settings = _local_nodes(hdr_root, "breakSetting")
    assert any(bs.get("widowOrphan") == "1" for bs in break_settings)
    assert any(bs.get("keepWithNext") == "1" for bs in break_settings)


# ---------------------------------------------------------------------------
# 2. Legacy mode_assemble vs frozen worker parity (bytes + members + verdict)
# ---------------------------------------------------------------------------


def test_legacy_vs_frozen_parity_exact_bytes_and_zip_members(
    tmp_path: Path, monkeypatch
):
    """Compare legacy mode_assemble vs frozen worker across text/bold/table/eq/pic."""
    env = _build_rich_workspace(tmp_path / "ws")

    # 2a. Unmocked subprocess mode_assemble vs execute_frozen_xml_worker:
    #     byte-for-byte ZIP member equality + normalized verdict equality.
    legacy_out_dir = tmp_path / "legacy-subproc-out"
    legacy_verdict_path = legacy_out_dir / "verdict_v06.json"
    args_legacy = argparse.Namespace(
        form=str(env["form"]),
        content=str(env["content"]),
        out_dir=str(legacy_out_dir),
        build_yaml=str(env["build_yaml"]),
        baseline=str(env["baseline"]),
        form_profile=str(env["profile"]),
        engine="xml",
        pdf_cmd=None,
        max_iters=1,
        fig_count=None,
        out=str(legacy_verdict_path),
    )
    fr.mode_assemble(args_legacy)
    legacy_hwpx = legacy_out_dir / "out.hwpx"

    snap_dir = tmp_path / "snap"
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        snap_dir,
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    frozen_hwpx = tmp_path / "frozen-direct" / "out.hwpx"
    res = worker.execute_frozen_xml_worker(req, frozen_hwpx)

    assert _zip_members(legacy_hwpx) == _zip_members(frozen_hwpx)
    legacy_verdict = json.loads(legacy_verdict_path.read_text(encoding="utf-8"))
    frozen_verdict = fr.xml_only_verdict(frozen_hwpx, res.para_verification, 1)
    assert _normalize_verdict(legacy_verdict, legacy_hwpx) == _normalize_verdict(
        frozen_verdict, frozen_hwpx
    )

    # 2b. Under controlled zipfile.time metadata (both running in-process),
    #     assert exact archive bytes including ZIP header timestamps.
    _freeze_zipfile_time(monkeypatch)
    monkeypatch.setattr(fr, "run_xml_edit", worker._default_xml_edit)

    inproc_legacy_dir = tmp_path / "legacy-inproc-out"
    args_inproc_legacy = argparse.Namespace(**{
        **vars(args_legacy),
        "out_dir": str(inproc_legacy_dir),
        "out": str(inproc_legacy_dir / "verdict_v06.json"),
    })
    fr.mode_assemble(args_inproc_legacy)
    frozen_inproc_hwpx = tmp_path / "frozen-inproc" / "out.hwpx"
    worker.execute_frozen_xml_worker(req, frozen_inproc_hwpx)
    assert (inproc_legacy_dir / "out.hwpx").read_bytes() == frozen_inproc_hwpx.read_bytes()

    # 2c. mode_assemble(..., frozen_request=req) also matches byte-for-byte.
    assemble_frozen_dir = tmp_path / "assemble-frozen-out"
    args_assemble_frozen = argparse.Namespace(**{
        **vars(args_legacy),
        "out_dir": str(assemble_frozen_dir),
        "out": str(assemble_frozen_dir / "verdict_v06.json"),
    })
    fr.mode_assemble(args_assemble_frozen, frozen_request=req)
    assert (assemble_frozen_dir / "out.hwpx").read_bytes() == frozen_inproc_hwpx.read_bytes()


# ---------------------------------------------------------------------------
# 3. Exact 6-step pass order and zero PDF/measurement/receipt side effects
# ---------------------------------------------------------------------------


def test_worker_pass_order_and_zero_pdf_measurement_or_receipt_calls(
    tmp_path: Path, monkeypatch
):
    env = _build_rich_workspace(tmp_path / "ws")
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        tmp_path / "snap",
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )

    monkeypatch.setattr(
        fr, "run_pdf_command", lambda *a, **k: pytest.fail("PDF renderer called")
    )
    monkeypatch.setattr(
        layout_qa, "analyze", lambda *a, **k: pytest.fail("layout_qa called")
    )
    monkeypatch.setattr(
        document_evidence,
        "write_receipt",
        lambda *a, **k: pytest.fail("write_receipt called"),
    )
    monkeypatch.setattr(
        style_diff, "analyze", lambda *a, **k: pytest.fail("style_diff.analyze called")
    )

    calls: list[str] = []

    def wrap_edit(form_p, ops_p, out_p):
        calls.append("xml_edit")
        return worker._default_xml_edit(form_p, ops_p, out_p)

    def wrap_tidy(hwpx_p, before, after, soft=False, keep_map=None):
        calls.append("tidy_hwpx")
        return worker._default_tidy_hwpx(
            hwpx_p, before, after, soft=soft, keep_map=keep_map
        )

    def wrap_restore(hwpx_p, baseline_p):
        calls.append("restore_para_formats")
        return worker._default_restore_para_formats(hwpx_p, baseline_p)

    def wrap_kwn(hwpx_p, prefixes):
        calls.append("keep_with_next")
        return worker._default_keep_with_next(hwpx_p, prefixes)

    def wrap_typeset(hwpx_p, anchors):
        calls.append("typeset_defaults")
        return worker._default_typeset_defaults(hwpx_p, anchors)

    def wrap_para(hwpx_p, form_p):
        calls.append("para_format_check")
        return worker._default_para_format_check(hwpx_p, form_p)

    out_dir = tmp_path / "worker-only"
    out_hwpx = out_dir / "out.hwpx"
    res = worker.execute_frozen_xml_worker(
        req,
        out_hwpx,
        runners=worker.XmlWorkerRunners(
            xml_edit=wrap_edit,
            tidy_hwpx=wrap_tidy,
            restore_para_formats=wrap_restore,
            keep_with_next=wrap_kwn,
            typeset_defaults=wrap_typeset,
            para_format_check=wrap_para,
        ),
    )

    expected_order = [
        "xml_edit",
        "tidy_hwpx",
        "restore_para_formats",
        "keep_with_next",
        "typeset_defaults",
        "para_format_check",
    ]
    assert calls == expected_order
    assert res.steps_executed == expected_order
    assert [p.name for p in out_dir.iterdir()] == ["out.hwpx"]


# ---------------------------------------------------------------------------
# 4. Strict explicit vs derived soft tidy, absent settings, discovery parity
# ---------------------------------------------------------------------------


def test_derived_soft_tidy_keep_map_and_absent_settings_parity(
    tmp_path: Path, monkeypatch
):
    """Derived soft tidy + keep_map + absent optional settings match legacy exactly."""
    _freeze_zipfile_time(monkeypatch)
    monkeypatch.setattr(fr, "run_xml_edit", worker._default_xml_edit)
    # Case A: form_profile without explicit tidy_blank_* in build.yaml
    # Include an anchor missing from the form so soft tidy emits tidy_warnings.
    ws_a = tmp_path / "ws_a"
    form_a = _make_synthetic_form_hwpx(
        ws_a / "output" / "form_copy.hwpx",
        anchors=("I. Intro", "II. Results"),
        blanks_before_second=4,
    )
    content_a = ws_a / "bundle" / "content.md"
    content_a.parent.mkdir(parents=True, exist_ok=True)
    content_a.write_text(
        "---\nbase_pt: 10\n---\n\n## SECTION: I. Intro\n\nFilled intro.\n",
        encoding="utf-8",
    )
    build_a = ws_a / "build.yaml"
    build_a.write_text("base_pt: 10\n", encoding="utf-8")
    profile_a = ws_a / "form_profile.json"
    profile_a.write_text(
        json.dumps({
            "anchors": ["I. Intro", "II. Results", "NON_EXISTENT_SOFT_ANCHOR"],
            "anchors_blanks_before": {"I. Intro": 2, "II. Results": 4},
        }),
        encoding="utf-8",
    )

    req_a = worker.freeze_report_xml_request(
        form_a,
        content_a,
        tmp_path / "snap_a",
        build_yaml_path=build_a,
        form_profile_path=profile_a,
    )
    settings_a = req_a["operation"]["params"]["settings"]
    assert settings_a["tidy_soft"] is True
    assert settings_a["derived_tidy_anchors"] == [
        "I. Intro", "II. Results", "NON_EXISTENT_SOFT_ANCHOR"
    ]
    # Because "I. Intro" is filled, "II. Results" keep_map collapses to 1.
    assert settings_a["tidy_keep_map"] == {
        "I. Intro": 2,
        "II. Results": 1,
        "NON_EXISTENT_SOFT_ANCHOR": 1,
    }
    res_a = worker.execute_frozen_xml_worker(req_a, tmp_path / "frozen_a.hwpx")
    assert len(res_a.tidy_warnings) == 1
    assert res_a.tidy_warnings[0]["anchor"] == "NON_EXISTENT_SOFT_ANCHOR"

    legacy_a_dir = tmp_path / "legacy_a"
    fr.mode_assemble(argparse.Namespace(
        form=str(form_a),
        content=str(content_a),
        out_dir=str(legacy_a_dir),
        build_yaml=str(build_a),
        baseline=None,
        form_profile=str(profile_a),
        engine="xml",
        pdf_cmd=None,
        max_iters=1,
        fig_count=None,
        out=None,
    ))
    assert (tmp_path / "frozen_a.hwpx").read_bytes() == (
        legacy_a_dir / "out.hwpx"
    ).read_bytes()

    # Case B: Absent optional settings (build_yaml=None, form_profile=None, baseline=None)
    ws_b = tmp_path / "ws_b"
    form_b = _make_synthetic_form_hwpx(ws_b / "output" / "form_copy.hwpx")
    content_b = ws_b / "bundle" / "content.md"
    content_b.parent.mkdir(parents=True, exist_ok=True)
    content_b.write_text(
        "---\nbase_pt: 10\n---\n\n## SECTION: I. Intro\n\nPlain body.\n",
        encoding="utf-8",
    )
    req_b = worker.freeze_report_xml_request(
        form_b, content_b, tmp_path / "snap_b"
    )
    settings_b = req_b["operation"]["params"]["settings"]
    assert settings_b == {
        "tidy_before": None,
        "tidy_after": None,
        "tidy_soft": False,
        "tidy_keep_map": None,
        "derived_tidy_anchors": None,
        "use_restore": False,
        "baseline_ref": None,
        "keep_with_next": None,
        "use_typeset_defaults": False,
        "profile_anchors": [],
    }
    res_b = worker.execute_frozen_xml_worker(req_b, tmp_path / "frozen_b.hwpx")
    assert res_b.steps_executed == ["xml_edit", "tidy_hwpx", "para_format_check"]

    legacy_b_dir = tmp_path / "legacy_b"
    fr.mode_assemble(argparse.Namespace(
        form=str(form_b),
        content=str(content_b),
        out_dir=str(legacy_b_dir),
        build_yaml=None,
        baseline=None,
        form_profile=None,
        engine="xml",
        pdf_cmd=None,
        max_iters=1,
        fig_count=None,
        out=None,
    ))
    assert (tmp_path / "frozen_b.hwpx").read_bytes() == (
        legacy_b_dir / "out.hwpx"
    ).read_bytes()

    # Case C: Discovered build.yaml (build_yaml_path=None) feeds compiler meta ONLY
    # and NEVER silently enables omitted tidy_blank_* / keep_with_next post-processing.
    ws_c = tmp_path / "ws_c"
    form_c = _make_synthetic_form_hwpx(ws_c / "output" / "form_copy.hwpx")
    content_c = ws_c / "bundle" / "content.md"
    content_c.parent.mkdir(parents=True, exist_ok=True)
    content_c.write_text("## SECTION: I. Intro\n\nDiscovered build test.\n", encoding="utf-8")
    (ws_c / "build.yaml").write_text(
        "base_pt: 9\n"
        "tidy_blank_before:\n"
        '  - "MISSING_SHOULD_NOT_RUN"\n'
        "keep_with_next:\n"
        '  - "MISSING_PREFIX_SHOULD_NOT_RUN"\n',
        encoding="utf-8",
    )
    req_c = worker.freeze_report_xml_request(
        form_c, content_c, tmp_path / "snap_c", build_yaml_path=None
    )
    assert req_c["manifest"]["inputs"]["build_yaml"]["selection"] == "discovered_parent"
    assert req_c["operation"]["params"]["settings"]["tidy_before"] is None
    assert req_c["operation"]["params"]["settings"]["keep_with_next"] is None
    assert any(
        o.get("pt") == 9
        for o in req_c["operation"]["params"]["ops"]
        if o["op"] == "insert_text"
    )
    res_c = worker.execute_frozen_xml_worker(req_c, tmp_path / "frozen_c.hwpx")

    legacy_c_dir = tmp_path / "legacy_c"
    fr.mode_assemble(argparse.Namespace(
        form=str(form_c),
        content=str(content_c),
        out_dir=str(legacy_c_dir),
        build_yaml=None,
        baseline=None,
        form_profile=None,
        engine="xml",
        pdf_cmd=None,
        max_iters=1,
        fig_count=None,
        out=None,
    ))
    assert (tmp_path / "frozen_c.hwpx").read_bytes() == (
        legacy_c_dir / "out.hwpx"
    ).read_bytes()
    assert res_c.steps_executed == ["xml_edit", "tidy_hwpx", "para_format_check"]

    # Case D: Empty-string optional paths normalize cleanly to None (never Path(".")).
    req_empty = worker.freeze_report_xml_request(
        form_b,
        content_b,
        tmp_path / "snap_empty_opts",
        build_yaml_path="",
        form_profile_path="",
        baseline_path="",
    )
    assert req_empty["manifest_digest"] == req_b["manifest_digest"]
    meas_empty = worker.freeze_report_measurement_settings(
        build_yaml_path="", baseline_path=""
    )
    assert meas_empty["build_yaml"] == {"present": False, "reason": "not_requested"}
    assert meas_empty["baseline"] == {"present": False, "reason": "not_requested"}


def test_strict_explicit_tidy_and_keep_with_next_refusal_parity(tmp_path: Path):
    """Explicit tidy_blank_before (missing/ambiguous) and keep_with_next (missing prefix)
    refuse loudly in both worker and legacy mode_assemble, contrasting with soft derived tidy.
    """
    # 1. Explicit tidy_blank_before with missing anchor
    ws_miss = tmp_path / "ws_tidy_missing"
    form_m = _make_synthetic_form_hwpx(ws_miss / "form.hwpx")
    content_m = ws_miss / "bundle" / "content.md"
    content_m.parent.mkdir(parents=True, exist_ok=True)
    content_m.write_text("## SECTION: I. Intro\n\nBody.\n", encoding="utf-8")
    by_m = ws_miss / "build.yaml"
    by_m.write_text('tidy_blank_before:\n  - "NON_EXISTENT_EXPLICIT"\n', encoding="utf-8")
    profile_m = ws_miss / "form_profile.json"
    profile_m.write_text(
        json.dumps({"anchors": ["I. Intro", "NON_EXISTENT_EXPLICIT"]}),
        encoding="utf-8",
    )

    req_m = worker.freeze_report_xml_request(
        form_m, content_m, tmp_path / "snap_tm",
        build_yaml_path=by_m, form_profile_path=profile_m,
    )
    assert req_m["operation"]["params"]["settings"]["tidy_soft"] is False
    with pytest.raises(worker.FrozenWorkerRefusal) as tm_exc:
        worker.execute_frozen_xml_worker(req_m, tmp_path / "out_tm.hwpx")
    assert tm_exc.value.code == "tidy_failed"

    with pytest.raises(SystemExit) as legacy_tm_exc:
        fr.mode_assemble(argparse.Namespace(
            form=str(form_m), content=str(content_m), out_dir=str(tmp_path / "leg_tm"),
            build_yaml=str(by_m), baseline=None, form_profile=str(profile_m),
            engine="xml", pdf_cmd=None, max_iters=1, fig_count=None, out=None,
        ))
    assert legacy_tm_exc.value.code == 2

    # 2. Explicit tidy_blank_before with ambiguous anchor (appears twice in form)
    ws_amb = tmp_path / "ws_tidy_ambiguous"
    form_amb = _make_synthetic_form_hwpx(
        ws_amb / "form.hwpx", anchors=("DUP_ANCHOR", "DUP_ANCHOR"),
    )
    content_amb = ws_amb / "bundle" / "content.md"
    content_amb.parent.mkdir(parents=True, exist_ok=True)
    content_amb.write_text("## SECTION: DUP_ANCHOR\n\nBody.\n", encoding="utf-8")
    by_amb = ws_amb / "build.yaml"
    by_amb.write_text('tidy_blank_before:\n  - "DUP_ANCHOR"\n', encoding="utf-8")

    req_amb = worker.freeze_report_xml_request(
        form_amb, content_amb, tmp_path / "snap_amb", build_yaml_path=by_amb,
    )
    with pytest.raises(worker.FrozenWorkerRefusal) as amb_exc:
        worker.execute_frozen_xml_worker(req_amb, tmp_path / "out_amb.hwpx")
    assert amb_exc.value.code == "tidy_failed"

    with pytest.raises(SystemExit) as legacy_amb_exc:
        fr.mode_assemble(argparse.Namespace(
            form=str(form_amb), content=str(content_amb), out_dir=str(tmp_path / "leg_amb"),
            build_yaml=str(by_amb), baseline=None, form_profile=None,
            engine="xml", pdf_cmd=None, max_iters=1, fig_count=None, out=None,
        ))
    assert legacy_amb_exc.value.code == 2

    # Contrast: removing explicit tidy_blank_before lets form_profile derive soft tidy
    # and skip the ambiguous anchor with a warning instead of failing.
    profile_amb = ws_amb / "form_profile.json"
    profile_amb.write_text(json.dumps({"anchors": ["DUP_ANCHOR"]}), encoding="utf-8")
    by_soft = ws_amb / "build_soft.yaml"
    by_soft.write_text("base_pt: 10\n", encoding="utf-8")
    req_soft = worker.freeze_report_xml_request(
        form_amb, content_amb, tmp_path / "snap_soft",
        build_yaml_path=by_soft, form_profile_path=profile_amb,
    )
    res_soft = worker.execute_frozen_xml_worker(req_soft, tmp_path / "out_soft.hwpx")
    assert res_soft.ok is True
    assert len(res_soft.tidy_warnings) == 1
    assert res_soft.tidy_warnings[0]["anchor"] == "DUP_ANCHOR"

    # 3. Explicit keep_with_next with missing prefix refuses loudly in both paths.
    by_kwn = ws_miss / "build_kwn.yaml"
    by_kwn.write_text('keep_with_next:\n  - "MISSING_CAPTION_PREFIX"\n', encoding="utf-8")
    req_kwn = worker.freeze_report_xml_request(
        form_m, content_m, tmp_path / "snap_kwn", build_yaml_path=by_kwn,
    )
    with pytest.raises(worker.FrozenWorkerRefusal) as kwn_exc:
        worker.execute_frozen_xml_worker(req_kwn, tmp_path / "out_kwn.hwpx")
    assert kwn_exc.value.code == "keep_with_next_failed"

    with pytest.raises(SystemExit) as legacy_kwn_exc:
        fr.mode_assemble(argparse.Namespace(
            form=str(form_m), content=str(content_m), out_dir=str(tmp_path / "leg_kwn"),
            build_yaml=str(by_kwn), baseline=None, form_profile=None,
            engine="xml", pdf_cmd=None, max_iters=1, fig_count=None, out=None,
        ))
    assert legacy_kwn_exc.value.code == 2


def test_subdirectory_figure_preserves_basename_rel_path_and_exact_parity(
    tmp_path: Path, monkeypatch
):
    """Subdirectory figure reference preserves basename in asset_ref/shapeComment and exact bytes."""
    ws = tmp_path / "ws_subfig"
    form = _make_synthetic_form_hwpx(ws / "output" / "form_copy.hwpx")
    fig_path = ws / "bundle" / "figures" / "sub" / "plot.png"
    _tiny_png(fig_path, 12, 6)
    content = ws / "bundle" / "content.md"
    content.write_text(
        "---\nbase_pt: 10\n---\n\n"
        "## SECTION: I. Intro\n\n"
        '[[FIG file="sub/plot.png" width=80 caption="Figure 1. Sub"]]\n',
        encoding="utf-8",
    )

    req = worker.freeze_report_xml_request(form, content, tmp_path / "snap_subfig")
    pic_op = next(
        o for o in req["operation"]["params"]["ops"] if o["op"] == "insert_picture"
    )
    assert pic_op["asset_ref"]["name"] == "plot.png"
    assert req["manifest"]["inputs"]["assets"][0]["rel_path"] == "sub/plot.png"
    assert req["manifest"]["inputs"]["assets"][0]["name"] == "plot.png"

    _freeze_zipfile_time(monkeypatch)
    monkeypatch.setattr(fr, "run_xml_edit", worker._default_xml_edit)

    frozen_hwpx = tmp_path / "frozen_subfig.hwpx"
    worker.execute_frozen_xml_worker(req, frozen_hwpx)

    legacy_dir = tmp_path / "legacy_subfig"
    fr.mode_assemble(argparse.Namespace(
        form=str(form),
        content=str(content),
        out_dir=str(legacy_dir),
        build_yaml=None,
        baseline=None,
        form_profile=None,
        engine="xml",
        pdf_cmd=None,
        max_iters=1,
        fig_count=None,
        out=None,
    ))
    assert frozen_hwpx.read_bytes() == (legacy_dir / "out.hwpx").read_bytes()
    sec_root = ET.fromstring(_zip_members(frozen_hwpx)["Contents/section0.xml"])
    shape_comments = [n.text for n in _local_nodes(sec_root, "shapeComment") if n.text]
    assert any("Original file: plot.png" in c for c in shape_comments)


# ---------------------------------------------------------------------------
# 5. Unsupported compiler operations and form-dependent XML refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_name,content_body,build_yaml_text,expected_op",
    [
        (
            "find_delete",
            "## SECTION: I. Intro\n\nHello.\n",
            'delete_texts:\n  - "Guide line"\n',
            "find_delete",
        ),
        (
            "delete_ctrls",
            "---\nabstract: false\n---\n\n## SECTION: I. Intro\n\nHello.\n",
            "base_pt: 10\n",
            "delete_ctrls",
        ),
        (
            "page_break_before",
            "## SECTION: I. Intro\n\nHello.\n",
            'page_break_before:\n  - "I. Intro"\n',
            "page_break_before",
        ),
        (
            "insert_hyperlink",
            '## SECTION: I. Intro\n\n[[URL href="https://example.com" text="site"]]\n',
            "base_pt: 10\n",
            "insert_hyperlink",
        ),
        (
            "collapse_empty_paragraphs",
            "---\ncollapse_blank_runs: true\n---\n\n## SECTION: I. Intro\n\nHello.\n",
            "base_pt: 10\n",
            "collapse_empty_paragraphs",
        ),
    ],
)
def test_unsupported_compiler_ops_refused_before_execution(
    tmp_path: Path,
    monkeypatch,
    case_name: str,
    content_body: str,
    build_yaml_text: str,
    expected_op: str,
):
    ws = tmp_path / f"ws_{case_name}"
    form = _make_synthetic_form_hwpx(ws / "form.hwpx")
    content = ws / "bundle" / "content.md"
    content.parent.mkdir(parents=True, exist_ok=True)
    content.write_text(content_body, encoding="utf-8")
    by = ws / "build.yaml"
    by.write_text(build_yaml_text, encoding="utf-8")

    # Freezing refuses unsupported compiled ops before any worker execution.
    with pytest.raises(worker.FrozenWorkerRefusal) as exc_info:
        worker.freeze_report_xml_request(
            form, content, tmp_path / f"snap_{case_name}", build_yaml_path=by
        )
    assert exc_info.value.code == "unsupported_xml_op"
    assert exc_info.value.details.get("op") == expected_op

    # Direct validation/worker execution also refuses before invoking xml_backend.
    monkeypatch.setattr(
        xml_backend, "main", lambda *_a, **_k: pytest.fail("xml_backend executed")
    )
    baseline_req = worker.freeze_report_xml_request(
        form,
        _write_plain_content(tmp_path / f"plain_ws_{case_name}" / "plain.md"),
        tmp_path / f"snap_ok_{case_name}",
    )
    tampered = copy.deepcopy(baseline_req)
    tampered["manifest"]["compiled"]["ops"].append({"op": expected_op})
    tampered["operation"]["params"]["ops"].append({"op": expected_op})
    digest = worker.compute_manifest_digest(tampered["manifest"])
    tampered["manifest_digest"] = digest
    tampered["operation"]["params"]["manifest_digest"] = digest
    with pytest.raises(worker.FrozenWorkerRefusal) as op_exc:
        worker.execute_frozen_xml_worker(tampered, tmp_path / "never.hwpx")
    assert op_exc.value.code == "unsupported_xml_op"


def _write_plain_content(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("## SECTION: I. Intro\n\nPlain text.\n", encoding="utf-8")
    return path


def test_xml_only_form_dependent_refusals(tmp_path: Path):
    """Bold insert without bold charPr and missing form anchor raise FrozenWorkerRefusal."""
    ws = tmp_path / "ws_form_dep"
    no_bold_form = _make_synthetic_form_hwpx(
        ws / "no_bold.hwpx", include_bold=False
    )
    bold_content = ws / "bundle" / "content.md"
    bold_content.parent.mkdir(parents=True, exist_ok=True)
    bold_content.write_text(
        "## SECTION: I. Intro\n\nText with **bold** span.\n", encoding="utf-8"
    )
    req_bold = worker.freeze_report_xml_request(
        no_bold_form, bold_content, tmp_path / "snap_bold"
    )
    with pytest.raises(worker.FrozenWorkerRefusal) as bold_exc:
        worker.execute_frozen_xml_worker(req_bold, tmp_path / "bold_out.hwpx")
    assert bold_exc.value.code == "xml_backend_unsupported"
    assert "insert_text:bold" in bold_exc.value.details.get("unsupported", [])

    # Missing anchor in form raises FrozenWorkerRefusal("anchors_missing").
    missing_content = ws / "bundle" / "missing.md"
    missing_content.write_text(
        "## SECTION: ABSENT_HEADING\n\nBody.\n", encoding="utf-8"
    )
    req_missing = worker.freeze_report_xml_request(
        no_bold_form, missing_content, tmp_path / "snap_missing"
    )
    with pytest.raises(worker.FrozenWorkerRefusal) as miss_exc:
        worker.execute_frozen_xml_worker(req_missing, tmp_path / "miss_out.hwpx")
    assert miss_exc.value.code == "anchors_missing"
    assert miss_exc.value.details.get("anchors_missing") == ["ABSENT_HEADING"]


# ---------------------------------------------------------------------------
# 6. Closed schema, recipe, path traversal, symlink, and tampered blob refusals
# ---------------------------------------------------------------------------


def test_closed_validation_rejects_extra_fields_recipes_live_paths_and_bad_eq(
    tmp_path: Path,
):
    env = _build_rich_workspace(tmp_path / "ws")
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        tmp_path / "snap",
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    base_op = req["operation"]

    # Extra top-level / params fields, caller output paths, argv/pdf_cmd, base/reverses.
    for extra_top in (
        {"opId": "op-1"},
        {"out_hwpx": "/tmp/evil.hwpx"},
        {"base": "prev"},
        {"reverses": "cand"},
    ):
        bad = copy.deepcopy(base_op)
        bad.update(extra_top)
        with pytest.raises(worker.FrozenWorkerRefusal):
            worker.validate_report_assemble_op(bad)

    for extra_param in (
        {"argv": ["sh"]},
        {"pdf_cmd": "soffice"},
        {"out_dir": "/tmp/out"},
        {"base": None},
        {"reverses": None},
    ):
        bad = copy.deepcopy(base_op)
        bad["params"].update(extra_param)
        with pytest.raises(worker.FrozenWorkerRefusal):
            worker.validate_report_assemble_op(bad)

    # Unknown recipe.
    bad_recipe = copy.deepcopy(base_op)
    bad_recipe["params"]["recipe"] = "rigorloom/report-xml/v999"
    with pytest.raises(worker.FrozenWorkerRefusal) as rec_exc:
        worker.validate_report_assemble_op(bad_recipe)
    assert rec_exc.value.code == "unknown_recipe"

    # Unrecognized nested op field.
    bad_nested = copy.deepcopy(base_op)
    bad_nested["params"]["ops"][0]["unexpected_key"] = True
    with pytest.raises(worker.FrozenWorkerRefusal) as nest_exc:
        worker.validate_report_assemble_op(bad_nested)
    assert nest_exc.value.code == "unknown_op_field"

    # Live path in frozen insert_picture op.
    bad_pic = copy.deepcopy(base_op)
    pic_op = next(o for o in bad_pic["params"]["ops"] if o["op"] == "insert_picture")
    pic_op["path"] = "/etc/passwd"
    with pytest.raises(worker.FrozenWorkerRefusal) as live_exc:
        worker.validate_report_assemble_op(bad_pic)
    assert live_exc.value.code == "live_path_forbidden"

    # Invalid equation operation rejected statically.
    bad_eq = copy.deepcopy(base_op)
    bad_eq["params"]["ops"].append(
        {"op": "insert_equation", "hwpeqn": "x={y", "display": False}
    )
    with pytest.raises(worker.FrozenWorkerRefusal) as eq_exc:
        worker.validate_report_assemble_op(bad_eq)
    assert eq_exc.value.code == "invalid_equation"

    # Tampered asset_ref basename / blob path traversal.
    bad_asset = copy.deepcopy(base_op)
    pic_op2 = next(o for o in bad_asset["params"]["ops"] if o["op"] == "insert_picture")
    pic_op2["asset_ref"]["name"] = "../escape.png"
    with pytest.raises(worker.FrozenWorkerRefusal):
        worker.validate_report_assemble_op(bad_asset)


_SYMLINK_UNSUPPORTED_ERRNOS = frozenset(
    v
    for v in (
        getattr(errno, "EPERM", None),
        getattr(errno, "EACCES", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "ENOTSUP", None),
        1314,
    )
    if v is not None
)


def _is_symlink_capability_error(exc: OSError) -> bool:
    return (
        getattr(exc, "winerror", None) == 1314
        or getattr(exc, "errno", None) in _SYMLINK_UNSUPPORTED_ERRNOS
    )


def _try_symlink(
    link_path: Path, target: Path, *, target_is_directory: bool = False
) -> bool:
    if os.path.lexists(link_path) and link_path.is_symlink():
        link_path.unlink()
    try:
        os.symlink(
            str(target), str(link_path), target_is_directory=target_is_directory
        )
        return True
    except NotImplementedError:
        return False
    except OSError as exc:
        if _is_symlink_capability_error(exc):
            return False
        raise


def _symlink_or_skip(
    link_path: Path, target: Path, *, target_is_directory: bool = False
) -> None:
    if os.path.lexists(link_path) and link_path.is_symlink():
        link_path.unlink()
    try:
        os.symlink(
            str(target), str(link_path), target_is_directory=target_is_directory
        )
    except NotImplementedError as exc:
        pytest.skip(f"Windows symlink capability unavailable: {exc}")
    except OSError as exc:
        if _is_symlink_capability_error(exc):
            pytest.skip(f"Windows symlink capability unavailable: {exc}")
        raise


def test_asset_path_traversal_symlink_escape_and_tampered_blob_refusals(
    tmp_path: Path,
):
    ws = tmp_path / "ws"
    form = _make_synthetic_form_hwpx(ws / "form.hwpx")
    figs_dir = ws / "bundle" / "figures"
    figs_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.png"
    _tiny_png(outside)

    # 1. Absolute figure path
    c_abs = ws / "bundle" / "abs.md"
    c_abs.write_text(
        f'## SECTION: I. Intro\n\n[[FIG file="{outside.as_posix()}" width=80]]\n',
        encoding="utf-8",
    )
    with pytest.raises(worker.FrozenRequestError) as abs_exc:
        worker.freeze_report_xml_request(form, c_abs, tmp_path / "snap_abs")
    assert abs_exc.value.code == "asset_path_escape"

    # 2. .. traversal
    c_trav = ws / "bundle" / "trav.md"
    c_trav.write_text(
        '## SECTION: I. Intro\n\n[[FIG file="../../outside.png" width=80]]\n',
        encoding="utf-8",
    )
    with pytest.raises(worker.FrozenRequestError) as trav_exc:
        worker.freeze_report_xml_request(form, c_trav, tmp_path / "snap_trav")
    assert trav_exc.value.code == "asset_path_escape"

    # 3. Symlink escaping bundle/figures (skip only symlink subcase if unavailable)
    sym_fig = figs_dir / "link_out.png"
    if _try_symlink(sym_fig, outside):
        c_sym = ws / "bundle" / "sym.md"
        c_sym.write_text(
            '## SECTION: I. Intro\n\n[[FIG file="link_out.png" width=80]]\n',
            encoding="utf-8",
        )
        with pytest.raises(worker.FrozenRequestError) as sym_exc:
            worker.freeze_report_xml_request(form, c_sym, tmp_path / "snap_sym")
        assert sym_exc.value.code == "asset_symlink_escape"

    # 4. Tampered blob bytes & symlinked blob in snapshot_dir
    env = _build_rich_workspace(tmp_path / "ws_tamper")
    snap = tmp_path / "snap_tamper"
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        snap,
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    form_blob_path = snap / req["manifest"]["inputs"]["form"]["blob"]
    orig_form_bytes = form_blob_path.read_bytes()
    form_blob_path.write_bytes(b"corrupted" + orig_form_bytes[9:])
    with pytest.raises(worker.FrozenRequestError) as tam_exc:
        worker.execute_frozen_xml_worker(req, tmp_path / "tam_out.hwpx")
    assert tam_exc.value.code == "blob_digest_mismatch"

    # Replace blob with a symlink -> refused (when symlinks can be created).
    form_blob_path.unlink()
    if _try_symlink(form_blob_path, env["form"]):
        with pytest.raises(worker.FrozenRequestError) as sblob_exc:
            worker.execute_frozen_xml_worker(req, tmp_path / "sblob_out.hwpx")
        assert sblob_exc.value.code == "blob_path_escape"


# ---------------------------------------------------------------------------
# 7. Post-freeze mutation and deletion -> identical bytes, 0 compiler calls
# ---------------------------------------------------------------------------


def test_post_freeze_mutation_and_deletion_identical_output_zero_compiler_calls(
    tmp_path: Path, monkeypatch
):
    env = _build_rich_workspace(tmp_path / "ws")
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        tmp_path / "snap",
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    baseline_hwpx = tmp_path / "baseline" / "out.hwpx"
    _freeze_zipfile_time(monkeypatch)
    monkeypatch.setattr(fr, "run_xml_edit", worker._default_xml_edit)
    worker.execute_frozen_xml_worker(req, baseline_hwpx)
    baseline_bytes = baseline_hwpx.read_bytes()

    # Mutate every workspace source input after freeze.
    env["content"].write_text("## SECTION: CHANGED\n\nDifferent text.\n", encoding="utf-8")
    env["build_yaml"].write_text("base_pt: 22\n", encoding="utf-8")
    env["profile"].write_text('{"anchors": ["CHANGED"]}', encoding="utf-8")
    env["baseline"].write_text('{"para_formats": []}', encoding="utf-8")
    _tiny_png(env["figure"], 32, 32)

    compiler_calls: list[str] = []

    def _fail_compile(*_a, **_k):
        compiler_calls.append("compile")
        raise AssertionError("compiler must not run after freeze")

    monkeypatch.setattr(br, "compile_bundle_text", _fail_compile)
    monkeypatch.setattr(br, "parse_content", _fail_compile)
    monkeypatch.setattr(br, "parse_build_yaml_text", _fail_compile)
    monkeypatch.setattr(fr, "run_build_report", _fail_compile)

    real_subproc_run = subprocess.run

    def _guard_subproc(cmd, *a, **kw):
        if any("build_report.py" in str(part) for part in cmd):
            raise AssertionError("build_report.py subprocess must not be invoked")
        return real_subproc_run(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _guard_subproc)

    mutated_hwpx = tmp_path / "after_mutation" / "out.hwpx"
    worker.execute_frozen_xml_worker(req, mutated_hwpx)
    assert mutated_hwpx.read_bytes() == baseline_bytes
    assert compiler_calls == []

    # Delete all mutable workspace inputs after freeze and run both worker & mode_assemble.
    for key in ("content", "build_yaml", "profile", "baseline", "figure"):
        env[key].unlink()

    deleted_hwpx = tmp_path / "after_deletion" / "out.hwpx"
    worker.execute_frozen_xml_worker(req, deleted_hwpx)
    assert deleted_hwpx.read_bytes() == baseline_bytes

    assemble_dir = tmp_path / "assemble_after_deletion"
    fr.mode_assemble(
        argparse.Namespace(
            form=str(env["form"]),
            content=str(env["content"]),
            out_dir=str(assemble_dir),
            build_yaml=str(env["build_yaml"]),
            baseline=str(env["baseline"]),
            form_profile=str(env["profile"]),
            engine="xml",
            pdf_cmd=None,
            max_iters=1,
            fig_count=None,
            out=None,
        ),
        frozen_request=req,
    )
    assert (assemble_dir / "out.hwpx").read_bytes() == baseline_bytes
    assert compiler_calls == []


# ---------------------------------------------------------------------------
# 8. Change-during-capture and expected_form_sha256 mismatch
# ---------------------------------------------------------------------------


def test_change_during_capture_and_expected_form_sha256_mismatch(tmp_path: Path):
    env = _build_rich_workspace(tmp_path / "ws")

    # Mismatch on expected_form_sha256.
    with pytest.raises(worker.FrozenRequestError) as f_exc:
        worker.freeze_report_xml_request(
            env["form"],
            env["content"],
            tmp_path / "snap_mismatch",
            expected_form_sha256="0" * 64,
        )
    assert f_exc.value.code == "form_digest_mismatch"

    # Mutate content mid-capture -> input_changed_during_capture.
    def mutate_content_hook():
        env["content"].write_text(
            "## SECTION: I. Intro\n\nMutated mid capture.\n", encoding="utf-8"
        )

    with pytest.raises(worker.FrozenRequestError) as c_exc:
        worker.freeze_report_xml_request(
            env["form"],
            env["content"],
            tmp_path / "snap_drift_content",
            build_yaml_path=env["build_yaml"],
            _capture_hook=mutate_content_hook,
        )
    assert c_exc.value.code == "input_changed_during_capture"

    # Create higher-priority bundle/build.yaml mid-capture when parent was selected.
    ws_disc = tmp_path / "ws_disc"
    form_d = _make_synthetic_form_hwpx(ws_disc / "output" / "form_copy.hwpx")
    content_d = ws_disc / "bundle" / "content.md"
    content_d.parent.mkdir(parents=True, exist_ok=True)
    content_d.write_text("## SECTION: I. Intro\n\nBody.\n", encoding="utf-8")
    (ws_disc / "build.yaml").write_text("base_pt: 10\n", encoding="utf-8")

    def create_bundle_yaml_hook():
        (ws_disc / "bundle" / "build.yaml").write_text("base_pt: 11\n", encoding="utf-8")

    with pytest.raises(worker.FrozenRequestError) as d_exc:
        worker.freeze_report_xml_request(
            form_d,
            content_d,
            tmp_path / "snap_drift_disc",
            _capture_hook=create_bundle_yaml_hook,
        )
    assert d_exc.value.code == "input_changed_during_capture"


# ---------------------------------------------------------------------------
# 9. manifest_digest relocation invariance and sensitivity
# ---------------------------------------------------------------------------


def test_manifest_digest_relocation_invariance_and_sensitivity(
    tmp_path: Path, monkeypatch
):
    ws_a = tmp_path / "loc_a" / "alpha_ws"
    env_a = _build_rich_workspace(ws_a)
    ws_b = tmp_path / "loc_b" / "nested" / "beta_ws"
    ws_b.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ws_a, ws_b)

    req_a = worker.freeze_report_xml_request(
        env_a["form"],
        env_a["content"],
        tmp_path / "snap_loc_a",
        build_yaml_path=env_a["build_yaml"],
        form_profile_path=env_a["profile"],
        baseline_path=env_a["baseline"],
    )
    req_b = worker.freeze_report_xml_request(
        ws_b / "output" / "form_copy.hwpx",
        ws_b / "bundle" / "content.md",
        tmp_path / "snap_loc_b",
        build_yaml_path=ws_b / "build.yaml",
        form_profile_path=ws_b / "form_profile.json",
        baseline_path=ws_b / "form_baseline.json",
    )
    assert req_a["manifest_digest"] == req_b["manifest_digest"]

    # Relocated snapshot_dir still executes identically.
    relocated_snap = tmp_path / "relocated" / "snap_copy"
    shutil.copytree(tmp_path / "snap_loc_a", relocated_snap)
    _freeze_zipfile_time(monkeypatch)
    out_a = tmp_path / "out_a.hwpx"
    out_reloc = tmp_path / "out_reloc.hwpx"
    worker.execute_frozen_xml_worker(req_a, out_a)
    worker.execute_frozen_xml_worker(req_a, out_reloc, snapshot_dir=relocated_snap)
    assert out_a.read_bytes() == out_reloc.read_bytes()

    base_digest = req_a["manifest_digest"]

    # Sensitivity: every effective input or setting change moves manifest_digest.
    env_c = _build_rich_workspace(tmp_path / "loc_c")
    # 1. Explicit vs discovered build.yaml
    req_disc = worker.freeze_report_xml_request(
        env_c["form"],
        env_c["content"],
        tmp_path / "snap_disc",
        build_yaml_path=None,
        form_profile_path=env_c["profile"],
        baseline_path=env_c["baseline"],
    )
    assert req_disc["manifest_digest"] != base_digest

    # 2. Content change
    env_c["content"].write_text(
        env_c["content"].read_text(encoding="utf-8") + "\nExtra line.\n",
        encoding="utf-8",
    )
    req_c2 = worker.freeze_report_xml_request(
        env_c["form"],
        env_c["content"],
        tmp_path / "snap_c2",
        build_yaml_path=env_c["build_yaml"],
        form_profile_path=env_c["profile"],
        baseline_path=env_c["baseline"],
    )
    assert req_c2["manifest_digest"] != base_digest

    # 3. Figure change
    env_d = _build_rich_workspace(tmp_path / "loc_d")
    _tiny_png(env_d["figure"], 16, 8)
    req_fig = worker.freeze_report_xml_request(
        env_d["form"],
        env_d["content"],
        tmp_path / "snap_fig",
        build_yaml_path=env_d["build_yaml"],
        form_profile_path=env_d["profile"],
        baseline_path=env_d["baseline"],
    )
    assert req_fig["manifest_digest"] != base_digest

    # 4. Omitting profile / baseline
    req_no_prof = worker.freeze_report_xml_request(
        env_a["form"],
        env_a["content"],
        tmp_path / "snap_no_prof",
        build_yaml_path=env_a["build_yaml"],
        form_profile_path=None,
        baseline_path=env_a["baseline"],
    )
    assert req_no_prof["manifest_digest"] != base_digest

    req_no_base = worker.freeze_report_xml_request(
        env_a["form"],
        env_a["content"],
        tmp_path / "snap_no_base",
        build_yaml_path=env_a["build_yaml"],
        form_profile_path=env_a["profile"],
        baseline_path=None,
    )
    assert req_no_base["manifest_digest"] != base_digest

    # 5. Form change
    env_e = _build_rich_workspace(tmp_path / "loc_e")
    _make_synthetic_form_hwpx(env_e["form"], blanks_before_second=5)
    req_form = worker.freeze_report_xml_request(
        env_e["form"],
        env_e["content"],
        tmp_path / "snap_form",
        build_yaml_path=env_e["build_yaml"],
        form_profile_path=env_e["profile"],
        baseline_path=env_e["baseline"],
    )
    assert req_form["manifest_digest"] != base_digest


# ---------------------------------------------------------------------------
# 10. mode_loop per-iteration compile vs frozen_request zero compiles
# ---------------------------------------------------------------------------


def test_mode_loop_per_iter_compile_vs_frozen_request_zero_compiles(
    tmp_path: Path, monkeypatch
):
    fitz = pytest.importorskip("fitz")
    _ = fitz  # confirm PyMuPDF available for layout_qa measurement
    renderer_script = tmp_path / "render_one_page.py"
    renderer_script.write_text(
        "import fitz, sys\n"
        "doc = fitz.open()\n"
        "p = doc.new_page(width=612, height=792)\n"
        "p.insert_text((72, 650), 'Rendered line')\n"
        "doc.save(sys.argv[2])\n",
        encoding="utf-8",
    )
    pdf_cmd = [sys.executable, str(renderer_script), "{in}", "{out}"]

    ws = tmp_path / "ws_loop"
    env = _build_rich_workspace(ws)
    # Require 2..3 pages while renderer produces 1 page so mode_loop runs 2 iterations.
    env["build_yaml"].write_text(
        "base_pt: 10\n"
        "caption_pt: 9\n"
        "line_spacing: 160\n"
        "fill:\n"
        "  target_pages: [2, 3]\n"
        "  min_figures: 0\n"
        "tidy_blank_before:\n"
        '  - "II. Results"\n',
        encoding="utf-8",
    )

    compile_calls = 0
    real_compile = br.compile_bundle_text

    def spy_compile(*a, **kw):
        nonlocal compile_calls
        compile_calls += 1
        return real_compile(*a, **kw)

    monkeypatch.setattr(br, "compile_bundle_text", spy_compile)

    out_unfrozen = tmp_path / "loop_unfrozen"
    args_unfrozen = argparse.Namespace(
        form=str(env["form"]),
        content=str(env["content"]),
        out_dir=str(out_unfrozen),
        build_yaml=str(env["build_yaml"]),
        max_loops=2,
        baseline=str(env["baseline"]),
        trouble_table=None,
        guide_file=None,
        spacing_skip_pages=None,
        gap_skip_pages=None,
        bottom_skip_pages=None,
        fig_count=0,
        kill_stale=False,
        out=None,
        engine="xml",
        pdf_cmd=pdf_cmd,
        pdf_timeout=30.0,
        calibration=None,
        form_profile=str(env["profile"]),
        proof=False,
    )
    fr.mode_loop(args_unfrozen)
    assert compile_calls == 2
    verdict_unfrozen = json.loads(
        (out_unfrozen / "verdict_v06.json").read_text(encoding="utf-8")
    )
    assert verdict_unfrozen["iterations"] == 2

    # Freeze once, then delete content.md and pass frozen_request to mode_loop.
    compile_calls = 0
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        tmp_path / "snap_loop",
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    assert compile_calls == 1

    compile_calls = 0
    env["content"].unlink()
    out_frozen = tmp_path / "loop_frozen"
    args_frozen = argparse.Namespace(**{
        **vars(args_unfrozen),
        "out_dir": str(out_frozen),
    })
    fr.mode_loop(args_frozen, frozen_request=req)
    assert compile_calls == 0
    verdict_frozen = json.loads(
        (out_frozen / "verdict_v06.json").read_text(encoding="utf-8")
    )
    assert verdict_frozen["iterations"] == 2


# ---------------------------------------------------------------------------
# 11. build_report text APIs and separated measurement helper
# ---------------------------------------------------------------------------


def test_build_report_text_apis_and_measurement_separation(
    tmp_path: Path, capsys
):
    cfg = br.parse_build_yaml_text('base_pt: 11\ndelete_texts:\n  - "a, b"\n')
    assert cfg["base_pt"] == "11"
    assert cfg["delete_texts"] == ["a, b"]
    assert br.load_form_profile_text(None) is None
    assert br.load_form_profile_text("{bad") is None
    assert br.load_form_profile_text('{"anchors": ["A"]}') == {"anchors": ["A"]}

    with pytest.raises(br.CompileReportError) as empty_exc:
        br.compile_bundle_text("No section header here\n")
    assert empty_exc.value.exit_code == 2
    assert capsys.readouterr().out == ""

    with pytest.raises(br.CompileReportError) as tag_exc:
        br.compile_bundle_text("## SECTION: A\n[[BOGUS]]\n")
    assert tag_exc.value.exit_code == 2
    assert capsys.readouterr().out == ""

    env = _build_rich_workspace(tmp_path / "ws_meas")
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        tmp_path / "snap_meas",
        build_yaml_path=env["build_yaml"],
    )
    meas = worker.freeze_report_measurement_settings(
        build_yaml_path=env["build_yaml"],
        baseline_path=env["baseline"],
        pdf_cmd=["soffice", "--headless", "{in}"],
        renderer_id="soffice_local",
        calibration={"max_gap_scale": 1.5},
        spacing_skip_pages={1},
    )
    assert meas["schema"] == worker.MEASUREMENT_SCHEMA
    assert meas["proof_grade_policy"] == "advisory"
    assert meas["spacing_skip_pages"] == [1]
    assert set(req["operation"]["params"]) == {
        "recipe", "manifest_digest", "ops", "settings"
    }
    assert "pdf_cmd" not in req["operation"]["params"]
    assert "calibration" not in req["operation"]["params"]

    # CLI parity: build_report.py --dry-run matches compile_bundle_text.
    cli_proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "build_report.py"),
            "--content",
            str(env["content"]),
            "--build-yaml",
            str(env["build_yaml"]),
            "--form-profile",
            str(env["profile"]),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    cli_payload = json.loads(cli_proc.stdout)
    compiled = br.compile_bundle_text(
        env["content"].read_text(encoding="utf-8"),
        build_yaml_text=env["build_yaml"].read_text(encoding="utf-8"),
        form_profile_obj=json.loads(env["profile"].read_text(encoding="utf-8")),
        bundle_dir=env["content"].parent,
    )
    assert cli_payload["ops"] == compiled["ops"]
    assert cli_payload["counts"] == compiled["counts"]
    assert cli_payload["anchors"] == compiled["anchors"]
    assert cli_payload["warnings"] == compiled["warnings"]


def test_mode_assemble_max_iters_compile_timing_and_worker_form_mismatch(
    tmp_path: Path, monkeypatch
):
    env = _build_rich_workspace(tmp_path / "ws_iters")
    compile_calls = 0
    real_compile = br.compile_bundle_text

    def spy_compile(*a, **kw):
        nonlocal compile_calls
        compile_calls += 1
        return real_compile(*a, **kw)

    monkeypatch.setattr(br, "compile_bundle_text", spy_compile)

    out_unfrozen = tmp_path / "assemble_2_unfrozen"
    args_unfrozen = argparse.Namespace(
        form=str(env["form"]),
        content=str(env["content"]),
        out_dir=str(out_unfrozen),
        build_yaml=str(env["build_yaml"]),
        baseline=str(env["baseline"]),
        form_profile=str(env["profile"]),
        engine="xml",
        pdf_cmd=None,
        max_iters=2,
        fig_count=None,
        out=None,
    )
    fr.mode_assemble(args_unfrozen)
    assert compile_calls == 2
    v_unfrozen = json.loads(
        (out_unfrozen / "verdict_v06.json").read_text(encoding="utf-8")
    )
    assert v_unfrozen["idempotent"] is True
    assert v_unfrozen["iterations"] == 2

    compile_calls = 0
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        tmp_path / "snap_iters",
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    assert compile_calls == 1

    compile_calls = 0
    for key in ("content", "build_yaml", "profile", "baseline", "figure"):
        env[key].unlink()
    out_frozen = tmp_path / "assemble_2_frozen"
    args_frozen = argparse.Namespace(**{
        **vars(args_unfrozen),
        "out_dir": str(out_frozen),
    })
    fr.mode_assemble(args_frozen, frozen_request=req)
    assert compile_calls == 0
    v_frozen = json.loads(
        (out_frozen / "verdict_v06.json").read_text(encoding="utf-8")
    )
    assert v_frozen["idempotent"] is True
    assert v_frozen["iterations"] == 2

    # mode_loop XML-only with frozen_request also succeeds with 0 compiles.
    out_loop_xml = tmp_path / "loop_xml_only_frozen"
    args_loop_xml = argparse.Namespace(
        form=str(env["form"]),
        content=str(env["content"]),
        out_dir=str(out_loop_xml),
        build_yaml=str(env["build_yaml"]),
        max_loops=2,
        baseline=str(env["baseline"]),
        trouble_table=None,
        guide_file=None,
        spacing_skip_pages=None,
        gap_skip_pages=None,
        bottom_skip_pages=None,
        fig_count=None,
        kill_stale=False,
        out=None,
        engine="xml",
        pdf_cmd=None,
        form_profile=str(env["profile"]),
        proof=False,
    )
    fr.mode_loop(args_loop_xml, frozen_request=req)
    assert compile_calls == 0
    v_loop = json.loads(
        (out_loop_xml / "verdict_v06.json").read_text(encoding="utf-8")
    )
    assert v_loop["status"] == "xml_verified_no_proof"
    assert v_loop["converged"] is True

    # Host staleness helper refuses when live form_path points to different bytes,
    # while worker never reads live form_path and succeeds even after live form deletion.
    assert worker.verify_live_form_digest(req, env["form"])["sha256"] == req["manifest"]["inputs"]["form"]["sha256"]
    wrong_form = _make_synthetic_form_hwpx(
        tmp_path / "wrong_form.hwpx", blanks_before_second=6
    )
    with pytest.raises(worker.FrozenRequestError) as fm_exc:
        worker.verify_live_form_digest(req, wrong_form)
    assert fm_exc.value.code == "form_digest_mismatch"

    env["form"].unlink()
    deleted_form_res = worker.execute_frozen_xml_worker(
        req, tmp_path / "deleted_live_form.hwpx", form_path=env["form"]
    )
    assert deleted_form_res.ok is True


# ---------------------------------------------------------------------------
# 12. Parent (0fa897a) parity oracle & S4b regressions (items 1-13)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parent_0fa897a_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git unavailable for 0fa897a parent parity")
    repo_root = ENGINE_ROOT.parent
    check = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "0fa897a^{commit}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        pytest.skip("parent commit 0fa897a unavailable in repository")
    dest = tmp_path_factory.mktemp("parent_0fa897a")
    arc = subprocess.run(
        ["git", "archive", "--format=tar", "0fa897a", "engine", "pipeline"],
        cwd=str(repo_root),
        capture_output=True,
        check=True,
    )
    with tarfile.open(fileobj=io.BytesIO(arc.stdout), mode="r:") as tf:
        if hasattr(tarfile, "data_filter"):
            tf.extractall(path=str(dest), filter="data")
        else:
            tf.extractall(path=str(dest))
    assert (dest / "engine" / "scripts" / "fill_report.py").is_file()
    return dest


def _run_fill_cli(
    repo_root: Path,
    *,
    mode: str,
    form: Path,
    content: Path,
    out_dir: Path,
    extra: tuple[str, ...] = (),
) -> tuple[int, dict, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cmd = [
        sys.executable,
        str(repo_root / "engine" / "scripts" / "fill_report.py"),
        mode,
        "--engine",
        "xml",
        "--form",
        str(form),
        "--content",
        str(content),
        "--out-dir",
        str(out_dir),
        *extra,
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8")
    try:
        payload = json.loads(proc.stdout)
    except Exception:
        payload = {"stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, payload, proc.stderr


def _normalize_cli_verdict(verdict: dict, out_dir: Path) -> dict:
    norm = dict(verdict)
    for key in ("hwpx", "pdf", "preview_pdf"):
        val = norm.get(key)
        if isinstance(val, str) and val:
            try:
                norm[key] = "<OUT_DIR>/" + Path(val).relative_to(out_dir.resolve()).as_posix()
            except ValueError:
                pass
    return norm


def _normalize_receipt(receipt: dict, form_path: Path, out_hwpx: Path) -> dict:
    assert receipt["execution"]["input"]["sha256"] == hashlib.sha256(form_path.read_bytes()).hexdigest()
    assert receipt["execution"]["output"]["sha256"] == hashlib.sha256(out_hwpx.read_bytes()).hexdigest()
    assert receipt["execution"]["output"]["bytes"] == out_hwpx.stat().st_size
    norm = copy.deepcopy(receipt)
    norm.pop("created_utc", None)
    norm.pop("receipt_sha256", None)
    norm["execution"]["output"]["sha256"] = "<VERIFIED_OUT_HWPX_SHA256>"
    norm["execution"]["output"]["bytes"] = "<VERIFIED_OUT_HWPX_BYTES>"
    return norm


def test_regression_item1_legacy_and_worker_alias_refusal(
    tmp_path: Path
):
    """Item 1: refuse form/output/ops aliasing in legacy & worker without touching form."""
    repo_root = ENGINE_ROOT.parent
    for mode in ("--assemble", "--loop"):
        # Direct out.hwpx collision
        ws_cur = tmp_path / f"cur-{mode.strip('-')}"
        for label, root, ws in (
            ("current", repo_root, ws_cur),
        ):
            form = _make_synthetic_form_hwpx(ws / "output" / "out.hwpx")
            content = _write_plain_content(ws / "bundle" / "content.md")
            before_sha = hashlib.sha256(form.read_bytes()).hexdigest()
            rc, payload, _ = _run_fill_cli(
                root, mode=mode, form=form, content=content, out_dir=form.parent
            )
            assert rc == 2, f"{label} {mode}: {payload}"
            assert payload == {
                "ok": False,
                "error": "xml_backend edit failed: unsupported=[] anchors_missing=[]",
            }
            assert hashlib.sha256(form.read_bytes()).hexdigest() == before_sha

        # Symlink out.hwpx -> form, parent dir symlink, and ops.json alias
        ws_sym = tmp_path / f"sym-{mode.strip('-')}"
        real_out = ws_sym / "real_out"
        real_out.mkdir(parents=True)
        form_s = _make_synthetic_form_hwpx(ws_sym / "pristine.hwpx")
        before_sha = hashlib.sha256(form_s.read_bytes()).hexdigest()
        _symlink_or_skip(real_out / "out.hwpx", form_s)
        content_s = _write_plain_content(ws_sym / "bundle" / "content.md")
        rc_s, payload_s, _ = _run_fill_cli(
            repo_root, mode=mode, form=form_s, content=content_s, out_dir=real_out
        )
        assert rc_s == 2
        assert payload_s == {
            "ok": False,
            "error": "xml_backend edit failed: unsupported=[] anchors_missing=[]",
        }
        assert hashlib.sha256(form_s.read_bytes()).hexdigest() == before_sha

        # Parent directory symlink alias
        ws_pdir = tmp_path / f"pdir-{mode.strip('-')}"
        real_dir = ws_pdir / "real_dir"
        form_p = _make_synthetic_form_hwpx(real_dir / "out.hwpx")
        before_p_sha = hashlib.sha256(form_p.read_bytes()).hexdigest()
        alias_dir = ws_pdir / "alias_dir"
        _symlink_or_skip(alias_dir, real_dir, target_is_directory=True)
        content_p = _write_plain_content(ws_pdir / "bundle" / "content.md")
        rc_p, payload_p, _ = _run_fill_cli(
            repo_root, mode=mode, form=form_p, content=content_p, out_dir=alias_dir
        )
        assert rc_p == 2
        assert payload_p == {
            "ok": False,
            "error": "xml_backend edit failed: unsupported=[] anchors_missing=[]",
        }
        assert hashlib.sha256(form_p.read_bytes()).hexdigest() == before_p_sha

        # form aliasing ops.json
        ws_ops = tmp_path / f"ops-{mode.strip('-')}"
        ops_out = ws_ops / "out"
        form_ops = _make_synthetic_form_hwpx(ops_out / "ops.json")
        before_ops_sha = hashlib.sha256(form_ops.read_bytes()).hexdigest()
        content_ops = _write_plain_content(ws_ops / "bundle" / "content.md")
        rc_o, payload_o, _ = _run_fill_cli(
            repo_root, mode=mode, form=form_ops, content=content_ops, out_dir=ops_out
        )
        assert rc_o == 2
        assert payload_o == {
            "ok": False,
            "error": "xml_backend edit failed: unsupported=[] anchors_missing=[]",
        }
        assert hashlib.sha256(form_ops.read_bytes()).hexdigest() == before_ops_sha

    # Worker direct guards: out_hwpx aliases form_path (even after deletion / via parent symlink)
    # and out_hwpx inside snapshot_dir.
    ws_w = tmp_path / "worker-guards"
    form_w = _make_synthetic_form_hwpx(ws_w / "real" / "form.hwpx")
    content_w = _write_plain_content(ws_w / "bundle" / "content.md")
    snap_w = ws_w / "snap"
    req = worker.freeze_report_xml_request(form_w, content_w, snap_w)
    alias_parent = ws_w / "alias_parent"
    _symlink_or_skip(alias_parent, form_w.parent, target_is_directory=True)
    form_w.unlink()
    with pytest.raises(worker.FrozenWorkerRefusal) as alias_exc:
        worker.execute_frozen_xml_worker(
            req, alias_parent / "form.hwpx", form_path=form_w
        )
    assert alias_exc.value.code == "output_aliases_form"

    with pytest.raises(worker.FrozenWorkerRefusal) as snap_exc:
        worker.execute_frozen_xml_worker(req, snap_w / "blobs" / "evil.hwpx")
    assert snap_exc.value.code == "output_inside_snapshot"


def test_regression_item2_ops_json_replayable_and_no_legacy_ops_out(
    tmp_path: Path
):
    """Item 2: remove legacy_ops_out from worker; legacy ops.json stays replayable."""
    assert "legacy_ops_out" not in inspect.signature(
        worker.execute_frozen_xml_worker
    ).parameters
    repo_root = ENGINE_ROOT.parent
    env = _build_rich_workspace(tmp_path / "ws")

    out_current = tmp_path / "out_current"
    rc_c, _, _ = _run_fill_cli(
        repo_root,
        mode="--assemble",
        form=env["form"],
        content=env["content"],
        out_dir=out_current,
    )
    assert rc_c == 0

    ops_c = json.loads((out_current / "ops.json").read_text(encoding="utf-8"))
    pic_op = next(o for o in ops_c if o["op"] == "insert_picture")
    assert Path(pic_op["path"]).is_file()
    assert Path(pic_op["path"]).resolve() == env["figure"].resolve()

    replay_proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "xml_backend.py"),
            "edit",
            "--file",
            str(env["form"]),
            "--ops",
            str(out_current / "ops.json"),
            "--save-as",
            str(tmp_path / "replayed.hwpx"),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(replay_proc.stdout)["ok"] is True

    # Frozen caller writes frozen params.ops (with asset_ref, no temp staging path).
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        tmp_path / "snap",
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    frozen_out = tmp_path / "frozen_out"
    fr.mode_assemble(
        argparse.Namespace(
            form=str(env["form"]),
            content=str(env["content"]),
            out_dir=str(frozen_out),
            build_yaml=str(env["build_yaml"]),
            baseline=str(env["baseline"]),
            form_profile=str(env["profile"]),
            engine="xml",
            pdf_cmd=None,
            max_iters=1,
            fig_count=None,
            out=None,
        ),
        frozen_request=req,
    )
    frozen_ops = json.loads((frozen_out / "ops.json").read_text(encoding="utf-8"))
    assert frozen_ops == req["operation"]["params"]["ops"]


def test_regression_item3_legacy_loop_postprocess_settings_fixed_before_loop(
    tmp_path: Path
):
    """Item 3: legacy XML loop resolves post-processing once before loop while compiling per iter."""
    pytest.importorskip("fitz")
    repo_root = ENGINE_ROOT.parent
    results = {}
    for label, root in (("current", repo_root),):
        ws = tmp_path / f"ws-{label}"
        form = _make_synthetic_form_hwpx(ws / "output" / "form_copy.hwpx")
        content = _write_plain_content(ws / "bundle" / "content.md")
        by = ws / "build.yaml"
        by.write_text("fill:\n  target_pages: [2, 3]\n", encoding="utf-8")
        renderer = ws / "renderer.py"
        renderer.write_text(
            "import fitz, sys\n"
            "from pathlib import Path\n"
            "d = fitz.open(); p = d.new_page(); p.insert_text((72, 650), 'Rendered')\n"
            "d.save(sys.argv[2])\n"
            "Path(sys.argv[3]).write_text("
            "'fill:\\n  target_pages: [2, 3]\\nkeep_with_next:\\n  - MISSING_PREFIX\\n', "
            "encoding='utf-8')\n",
            encoding="utf-8",
        )
        cmd = shlex.join([sys.executable, str(renderer), "{in}", "{out}", str(by)])
        out_dir = ws / "results"
        rc, payload, _ = _run_fill_cli(
            root,
            mode="--loop",
            form=form,
            content=content,
            out_dir=out_dir,
            extra=("--max-loops", "2", "--build-yaml", str(by), "--pdf-cmd", cmd),
        )
        results[label] = (rc, payload)
    assert results["current"][0] == 0
    assert results["current"][1]["iterations"] == 2
    assert results["current"][1].get("error") is None


def test_regression_item4_zero_byte_blobs_and_optional_input_policies(
    tmp_path: Path
):
    """Item 4: zero-byte blobs allowed; legacy skips dir/unreadable optional inputs, strict refuses."""
    repo_root = ENGINE_ROOT.parent
    ws = tmp_path / "ws"
    form = _make_synthetic_form_hwpx(ws / "output" / "form_copy.hwpx")
    content = _write_plain_content(ws / "bundle" / "content.md")

    empty_by = ws / "empty_build.yaml"
    empty_prof = ws / "empty_profile.json"
    empty_base = ws / "empty_baseline.json"
    for p in (empty_by, empty_prof, empty_base):
        p.touch()

    # Strict frozen mode accepts 0-byte blobs and verifies exact SHA-256 + length=0.
    req_empty = worker.freeze_report_xml_request(
        form,
        content,
        tmp_path / "snap_empty",
        build_yaml_path=empty_by,
        form_profile_path=empty_prof,
        baseline_path=empty_base,
    )
    assert req_empty["manifest"]["inputs"]["build_yaml"]["bytes"] == 0
    assert req_empty["manifest"]["inputs"]["form_profile"]["bytes"] == 0
    assert req_empty["manifest"]["inputs"]["baseline"]["bytes"] == 0
    res_empty = worker.execute_frozen_xml_worker(req_empty, tmp_path / "empty_out.hwpx")
    assert res_empty.ok is True

    # Strict frozen mode refuses directory optional inputs.
    dir_opt = ws / "opt_dir"
    dir_opt.mkdir()
    with pytest.raises(worker.FrozenRequestError):
        worker.freeze_report_xml_request(
            form, content, tmp_path / "snap_dir_prof", form_profile_path=dir_opt
        )
    with pytest.raises(worker.FrozenRequestError):
        worker.freeze_report_xml_request(
            form, content, tmp_path / "snap_dir_base", baseline_path=dir_opt
        )
    with pytest.raises(worker.FrozenRequestError):
        worker.freeze_report_measurement_settings(baseline_path=dir_opt)

    # Legacy CLI parity vs 0fa897a for empty files and directory optional inputs.
    for case_name, extra_args in (
        ("empty_build", ("--build-yaml", str(empty_by))),
        ("empty_profile", ("--form-profile", str(empty_prof))),
        ("empty_baseline", ("--baseline", str(empty_base))),
        ("profile_dir", ("--form-profile", str(dir_opt))),
        ("baseline_dir", ("--baseline", str(dir_opt))),
    ):
        rc_c, v_c, _ = _run_fill_cli(
            repo_root,
            mode="--assemble",
            form=form,
            content=content,
            out_dir=tmp_path / f"c-{case_name}",
            extra=extra_args,
        )
        assert rc_c == 0
        assert v_c["status"] == "xml_verified_no_proof"


def test_regression_item5_universal_newlines_and_legacy_error_parity(
    tmp_path: Path
):
    """Item 5: universal newline decoding (raw bytes hashed) & legacy error formatting parity."""
    repo_root = ENGINE_ROOT.parent

    # build_report text APIs normalize CR and CRLF.
    for nl in ("\r", "\r\n"):
        by_cfg = br.parse_build_yaml_text(f"base_pt: 11{nl}delete_texts:{nl}  - \"x\"{nl}")
        assert by_cfg["base_pt"] == "11"
        assert by_cfg["delete_texts"] == ["x"]
        compiled = br.compile_bundle_text(
            f"---{nl}base_pt: 12{nl}---{nl}{nl}## SECTION: I. Intro{nl}{nl}Body.{nl}",
            build_yaml_text=f"caption_pt: 8{nl}",
        )
        assert compiled["ok"] is True

    # Freeze preserves raw CR/CRLF bytes in blob digest while compiling cleanly.
    for tag, nl in (("cr", "\r"), ("crlf", "\r\n")):
        ws = tmp_path / f"nl-{tag}"
        form = _make_synthetic_form_hwpx(ws / "form.hwpx")
        content = ws / "bundle" / "content.md"
        content.parent.mkdir(parents=True, exist_ok=True)
        raw_bytes = f"---{nl}base_pt: 12{nl}---{nl}{nl}## SECTION: I. Intro{nl}{nl}Body.{nl}".encode(
            "utf-8"
        )
        content.write_bytes(raw_bytes)
        req = worker.freeze_report_xml_request(form, content, ws / "snap")
        assert req["manifest"]["inputs"]["content"]["sha256"] == hashlib.sha256(raw_bytes).hexdigest()
        assert worker.execute_frozen_xml_worker(req, ws / "frozen.hwpx").ok is True

        rc_c, v_c, _ = _run_fill_cli(
            repo_root, mode="--assemble", form=form, content=content, out_dir=ws / "c_out"
        )
        assert rc_c == 0
        assert v_c["status"] == "xml_verified_no_proof"

    # Legacy error formatting parity: bad content, unsupported op, missing figure.
    ws_err = tmp_path / "err_cases"
    form_e = _make_synthetic_form_hwpx(ws_err / "form.hwpx")

    bad_content = ws_err / "bundle" / "bad.md"
    bad_content.parent.mkdir(parents=True, exist_ok=True)
    bad_content.write_text("no section header\n", encoding="utf-8")

    unsup_content = ws_err / "bundle" / "unsup.md"
    unsup_content.write_text("## SECTION: I. Intro\n\nBody.\n", encoding="utf-8")
    unsup_by = ws_err / "unsup_build.yaml"
    unsup_by.write_text('delete_texts:\n  - "Guide"\n', encoding="utf-8")

    miss_fig_content = ws_err / "bundle" / "miss_fig.md"
    miss_fig_content.write_text(
        '## SECTION: I. Intro\n\n[[FIG file="missing.png" width=80]]\n', encoding="utf-8"
    )

    for cname, cpath, extra in (
        ("bad_content", bad_content, ()),
        ("unsup_op", unsup_content, ("--build-yaml", str(unsup_by))),
        ("miss_fig", miss_fig_content, ()),
    ):
        rc_c, p_c, _ = _run_fill_cli(
            repo_root,
            mode="--assemble",
            form=form_e,
            content=cpath,
            out_dir=ws_err / f"c-{cname}",
            extra=extra,
        )
        assert rc_c == 2
        assert p_c.get("error")


def test_regression_item6_figure_containment_backslashes_and_resolved_basename(
    tmp_path: Path
):
    """Item 6: strict figure containment + backslash rel + resolved.name; legacy abs/symlink parity."""
    repo_root = ENGINE_ROOT.parent
    ws = tmp_path / "ws"
    env = _build_rich_workspace(ws)
    sub_fig = ws / "bundle" / "figures" / "nested" / "sub.png"
    _tiny_png(sub_fig, 10, 5)

    # Strict rejections: leading /, leading \, UNC \\, drive prefix C:, NUL, ..
    for bad_ref in (
        "/etc/passwd",
        "\\abs\\plot.png",
        "\\\\server\\share\\plot.png",
        "C:plot.png",
        "C:\\plot.png",
        "a\x00b.png",
        "nested\\..\\..\\outside.png",
    ):
        with pytest.raises(worker.FrozenRequestError) as bad_exc:
            worker._resolve_bundle_figure(ws / "bundle", bad_ref)
        assert bad_exc.value.code in {"asset_path_escape", "invalid_asset_path"}

    # Strict accepts relative backslash nested\sub.png -> rel_posix="nested/sub.png".
    cand_bs, rel_bs, name_bs = worker._resolve_bundle_figure(
        ws / "bundle", "nested\\sub.png"
    )
    assert cand_bs.resolve() == sub_fig.resolve()
    assert rel_bs == "nested/sub.png"
    assert name_bs == "sub.png"

    # Internal symlink inside bundle/figures preserves resolved target basename plot.png.
    alias = env["figure"].with_name("alias.png")
    if _try_symlink(alias, env["figure"]):
        env["content"].write_text(
            '## SECTION: I. Intro\n\n[[FIG file="alias.png" width=80]]\n',
            encoding="utf-8",
        )
        req = worker.freeze_report_xml_request(env["form"], env["content"], ws / "snap_sym")
        pic_op = next(o for o in req["operation"]["params"]["ops"] if o["op"] == "insert_picture")
        assert pic_op["asset_ref"]["name"] == "plot.png"
        frozen_out = ws / "frozen_sym.hwpx"
        worker.execute_frozen_xml_worker(req, frozen_out)

        c_out = ws / "c_sym"
        assert _run_fill_cli(repo_root, mode="--assemble", form=env["form"], content=env["content"], out_dir=c_out)[0] == 0
        for hwpx in (frozen_out, c_out / "out.hwpx"):
            sec_xml = _zip_members(hwpx)["Contents/section0.xml"].decode("utf-8")
            assert "Original file: plot.png" in sec_xml

    # Legacy CLI allows absolute figure path just like 0fa897a.
    ws_abs = tmp_path / "ws_abs"
    env_abs = _build_rich_workspace(ws_abs)
    env_abs["content"].write_text(
        f'## SECTION: I. Intro\n\n[[FIG file="{env_abs["figure"]}" width=80]]\n',
        encoding="utf-8",
    )
    rc_ca, _, _ = _run_fill_cli(
        repo_root,
        mode="--assemble",
        form=env_abs["form"],
        content=env_abs["content"],
        out_dir=ws_abs / "c_abs",
    )
    assert rc_ca == 0


def test_regression_item7_private_exec_subdir_and_symlink_staging_defense(tmp_path: Path):
    """Item 7: worker uses fresh private exec-* dir inside work_dir and rejects symlink work_dir."""
    env = _build_rich_workspace(tmp_path / "ws")
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        tmp_path / "snap",
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    work = tmp_path / "work"
    work.mkdir()
    victim = tmp_path / "outside.txt"
    victim.write_bytes(b"KEEP ME")
    _symlink_or_skip(work / "source_form.hwpx", victim)
    _symlink_or_skip(work / "ops.json", victim)
    _symlink_or_skip(work / "baseline.json", victim)

    res = worker.execute_frozen_xml_worker(req, tmp_path / "out.hwpx", work_dir=work)
    assert res.ok is True
    assert victim.read_bytes() == b"KEEP ME"
    assert sorted(p.name for p in work.iterdir()) == [
        "baseline.json",
        "ops.json",
        "source_form.hwpx",
    ]

    sym_work = tmp_path / "sym_work"
    _symlink_or_skip(sym_work, tmp_path / "real_target", target_is_directory=True)
    with pytest.raises(worker.FrozenWorkerRefusal) as w_exc:
        worker.execute_frozen_xml_worker(req, tmp_path / "out2.hwpx", work_dir=sym_work)
    assert w_exc.value.code == "invalid_work_dir"


def test_regression_item8_blob_read_defends_intermediate_dir_toctou_swap(tmp_path: Path):
    """Item 8: dir_fd pinned blob read refuses intermediate blobs/ TOCTOU swaps."""
    if os.name == "nt" or os.open not in os.supports_dir_fd:
        pytest.skip("POSIX dir_fd TOCTOU test requires dir_fd support")
    env = _build_rich_workspace(tmp_path / "ws")
    snap = tmp_path / "snap"
    req = worker.freeze_report_xml_request(env["form"], env["content"], snap)
    form_ref = {
        k: req["manifest"]["inputs"]["form"][k] for k in ("blob", "sha256", "bytes")
    }
    blobs = snap / "blobs"
    external = tmp_path / "external_blobs"
    shutil.copytree(blobs, external)

    # Case A: swap blobs/ to symlink right before os.open("blobs", ..., dir_fd=snap_fd)
    real_open = os.open

    def race_before_blobs_open(path, flags, *a, **kw):
        if str(path) == "blobs" and "dir_fd" in kw and (blobs.exists() and not blobs.is_symlink()):
            blobs.rename(snap / "blobs_orig_a")
            _symlink_or_skip(blobs, external, target_is_directory=True)
        return real_open(path, flags, *a, **kw)

    with patch.object(os, "open", race_before_blobs_open):
        with pytest.raises(worker.FrozenRequestError) as exc_a:
            worker._read_verified_blob(snap, form_ref)
    assert exc_a.value.code == "blob_path_escape"

    # Restore real blobs/ and test Case B: swap blobs/ AFTER blobs_fd opened, before leaf open.
    if blobs.is_symlink():
        blobs.unlink()
    (snap / "blobs_orig_a").rename(blobs)

    opened_paths: list[str] = []

    def race_after_blobs_open(path, flags, *a, **kw):
        if str(path) == form_ref["sha256"] and "dir_fd" in kw:
            blobs.rename(snap / "blobs_orig_b")
            _symlink_or_skip(blobs, external, target_is_directory=True)
            opened_paths.append(str(path))
        return real_open(path, flags, *a, **kw)

    with patch.object(os, "open", race_after_blobs_open):
        with pytest.raises(worker.FrozenRequestError) as exc_b:
            worker._read_verified_blob(snap, form_ref)
    assert exc_b.value.code == "blob_path_escape"
    assert opened_paths == [form_ref["sha256"]]


def test_regression_item9_worker_never_reads_live_form_and_host_staleness_helper(
    tmp_path: Path,
):
    """Item 9: worker and frozen mode_assemble/mode_loop succeed when live form is deleted."""
    env = _build_rich_workspace(tmp_path / "ws")
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        tmp_path / "snap",
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    wrong_form = _make_synthetic_form_hwpx(tmp_path / "wrong.hwpx", blanks_before_second=6)
    with pytest.raises(worker.FrozenRequestError) as staleness_exc:
        worker.verify_live_form_digest(req, wrong_form)
    assert staleness_exc.value.code == "form_digest_mismatch"

    # Even with wrong_form as form_path (different path), worker consumes frozen snapshot only.
    res_wrong = worker.execute_frozen_xml_worker(
        req, tmp_path / "out_wrong_path.hwpx", form_path=wrong_form
    )
    assert res_wrong.ok is True

    # Delete live form; worker, frozen mode_assemble, and frozen mode_loop all succeed.
    env["form"].unlink()
    res_del = worker.execute_frozen_xml_worker(
        req, tmp_path / "out_deleted.hwpx", form_path=env["form"]
    )
    assert res_del.ok is True

    for mode_fn, out_name in ((fr.mode_assemble, "asm_del"), (fr.mode_loop, "loop_del")):
        out_dir = tmp_path / out_name
        ns = argparse.Namespace(
            form=str(env["form"]),
            content=str(env["content"]),
            out_dir=str(out_dir),
            build_yaml=str(env["build_yaml"]),
            baseline=str(env["baseline"]),
            form_profile=str(env["profile"]),
            engine="xml",
            pdf_cmd=None,
            max_iters=1,
            max_loops=1,
            trouble_table=None,
            guide_file=None,
            spacing_skip_pages=None,
            gap_skip_pages=None,
            bottom_skip_pages=None,
            fig_count=None,
            kill_stale=False,
            proof=False,
            out=None,
        )
        mode_fn(ns, frozen_request=req)
        assert (out_dir / "out.hwpx").is_file()


@pytest.mark.parametrize(
    "input_key",
    ["form", "content", "build_yaml", "form_profile", "baseline", "asset"],
)
def test_regression_item10_worker_verifies_all_present_input_blobs_before_staging(
    tmp_path: Path, monkeypatch, input_key: str
):
    """Item 10: tampering or symlinking ANY present manifest input blob refuses before edit."""
    env = _build_rich_workspace(tmp_path / "ws")
    # Ensure baseline has empty para_formats so use_restore=False still has baseline present=True.
    env["baseline"].write_text('{"para_formats": []}', encoding="utf-8")
    snap = tmp_path / "snap"
    req = worker.freeze_report_xml_request(
        env["form"],
        env["content"],
        snap,
        build_yaml_path=env["build_yaml"],
        form_profile_path=env["profile"],
        baseline_path=env["baseline"],
    )
    if input_key == "asset":
        rel_blob = req["manifest"]["inputs"]["assets"][0]["blob"]
    else:
        rel_blob = req["manifest"]["inputs"][input_key]["blob"]
    blob_path = snap / rel_blob
    orig = blob_path.read_bytes()

    monkeypatch.setattr(
        xml_backend, "main", lambda *_a, **_k: pytest.fail("xml_backend must not run")
    )

    blob_path.write_bytes(orig + b"tampered")
    with pytest.raises(worker.FrozenRequestError) as tam_exc:
        worker.execute_frozen_xml_worker(req, tmp_path / "never_tam.hwpx")
    assert tam_exc.value.code == "blob_digest_mismatch"

    blob_path.unlink()
    _symlink_or_skip(blob_path, env["form"])
    with pytest.raises(worker.FrozenRequestError) as sym_exc:
        worker.execute_frozen_xml_worker(req, tmp_path / "never_sym.hwpx")
    assert sym_exc.value.code == "blob_path_escape"


def test_local_optional_live_parent_0fa897a_oracle(
    tmp_path: Path, parent_0fa897a_root: Path
):
    """Item 11: full CLI parity vs 0fa897a parent across ops, replay, ZIP, verdicts, receipts."""
    repo_root = ENGINE_ROOT.parent
    ws_p = tmp_path / "ws_parent"
    ws_c = tmp_path / "ws_current"
    env_p = _build_rich_workspace(ws_p)
    env_c = _build_rich_workspace(ws_c)

    out_p = ws_p / "output"
    out_c = ws_c / "output"
    extra = (
        "--build-yaml",
        str(env_p["build_yaml"]),
        "--form-profile",
        str(env_p["profile"]),
        "--baseline",
        str(env_p["baseline"]),
    )
    extra_c = (
        "--build-yaml",
        str(env_c["build_yaml"]),
        "--form-profile",
        str(env_c["profile"]),
        "--baseline",
        str(env_c["baseline"]),
    )

    rc_p, v_p, _ = _run_fill_cli(
        parent_0fa897a_root,
        mode="--assemble",
        form=env_p["form"],
        content=env_p["content"],
        out_dir=out_p,
        extra=extra,
    )
    rc_c, v_c, _ = _run_fill_cli(
        repo_root,
        mode="--assemble",
        form=env_c["form"],
        content=env_c["content"],
        out_dir=out_c,
        extra=extra_c,
    )
    assert rc_c == rc_p == 0
    assert _normalize_cli_verdict(v_c, out_c) == _normalize_cli_verdict(v_p, out_p)
    assert _zip_members(out_c / "out.hwpx") == _zip_members(out_p / "out.hwpx")

    # Compare receipts
    rec_p = json.loads((out_p / "proof" / "backend" / "receipt.json").read_text(encoding="utf-8"))
    rec_c = json.loads((out_c / "proof" / "backend" / "receipt.json").read_text(encoding="utf-8"))
    assert _normalize_receipt(rec_c, env_c["form"], out_c / "out.hwpx") == _normalize_receipt(
        rec_p, env_p["form"], out_p / "out.hwpx"
    )

    # Compare against direct frozen worker ZIP members as well
    req = worker.freeze_report_xml_request(
        env_c["form"],
        env_c["content"],
        tmp_path / "snap_parity",
        build_yaml_path=env_c["build_yaml"],
        form_profile_path=env_c["profile"],
        baseline_path=env_c["baseline"],
    )
    frozen_hwpx = tmp_path / "frozen_parity.hwpx"
    worker.execute_frozen_xml_worker(req, frozen_hwpx)
    assert _zip_members(frozen_hwpx) == _zip_members(out_p / "out.hwpx")


def test_regression_item12_symlink_escape_asset_refusal(tmp_path: Path):
    """Item 12: dedicated symlink escape test using _symlink_or_skip."""
    ws = tmp_path / "ws"
    form = _make_synthetic_form_hwpx(ws / "form.hwpx")
    figs = ws / "bundle" / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.png"
    _tiny_png(outside)
    _symlink_or_skip(figs / "escape.png", outside)
    content = ws / "bundle" / "content.md"
    content.write_text('## SECTION: I. Intro\n\n[[FIG file="escape.png" width=80]]\n', encoding="utf-8")
    with pytest.raises(worker.FrozenRequestError) as exc:
        worker.freeze_report_xml_request(form, content, tmp_path / "snap")
    assert exc.value.code == "asset_symlink_escape"


def test_regression_item12_symlink_snapshot_blob_refusal(tmp_path: Path):
    """Item 12: dedicated symlink snapshot blob test using _symlink_or_skip."""
    env = _build_rich_workspace(tmp_path / "ws")
    snap = tmp_path / "snap"
    req = worker.freeze_report_xml_request(env["form"], env["content"], snap)
    blob = snap / req["manifest"]["inputs"]["form"]["blob"]
    blob.unlink()
    _symlink_or_skip(blob, env["form"])
    with pytest.raises(worker.FrozenRequestError) as exc:
        worker.execute_frozen_xml_worker(req, tmp_path / "out.hwpx")
    assert exc.value.code == "blob_path_escape"


def test_regression_item12_symlink_or_skip_handles_oserror_1314(tmp_path: Path):
    """Item 12: _symlink_or_skip skips cleanly with reason on Windows OSError(1314)."""
    target = tmp_path / "target.txt"
    target.write_text("hi", encoding="utf-8")
    with patch.object(
        os,
        "symlink",
        side_effect=OSError(1314, "A required privilege is not held by the client"),
    ):
        with pytest.raises(pytest.skip.Exception) as skip_exc:
            _symlink_or_skip(tmp_path / "link.txt", target)
    assert "Windows symlink capability unavailable" in str(skip_exc.value)


def test_regression_item13_live_path_forbidden_reachable_and_no_unused_shutil(
    tmp_path: Path,
):
    """Item 13: insert_picture.path raises live_path_forbidden; report_xml_worker has no shutil."""
    env = _build_rich_workspace(tmp_path / "ws")
    req = worker.freeze_report_xml_request(env["form"], env["content"], tmp_path / "snap")
    op = copy.deepcopy(req["operation"])
    pic = next(o for o in op["params"]["ops"] if o["op"] == "insert_picture")
    pic["path"] = "/etc/passwd"
    with pytest.raises(worker.FrozenWorkerRefusal) as exc:
        worker.validate_report_assemble_op(op)
    assert exc.value.code == "live_path_forbidden"

    src_path = SCRIPTS_DIR / "report_xml_worker.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))
    shutil_refs = sum(
        isinstance(node, ast.Name) and node.id == "shutil" for node in ast.walk(tree)
    )
    shutil_imports = sum(
        isinstance(node, ast.alias) and node.name == "shutil" for node in ast.walk(tree)
    )
    assert shutil_refs == 0
    assert shutil_imports == 0

# Committed 0fa897a oracle: shared by capture.py and the mandatory CI tests.
_PARENT_FIXTURES = HERE / "fixtures" / "report_xml_parent_0fa897a"
_PARENT_CASES = (
    "alias_assemble", "alias_loop", "ops_replay", "iteration_settings",
    "empty_build", "empty_profile", "empty_baseline", "profile_dir", "baseline_dir",
    "newline_cr", "newline_crlf", "bad_content", "unsup_op", "miss_fig",
    "absolute_figure", "symlink_basename", "rich_receipt",
)


def _parent_probe(root: Path, ws: Path, case: str) -> dict:
    """Build identical inputs for capture and verification, and retain stable results."""
    ws.mkdir(parents=True, exist_ok=True)
    mode, extra = "--assemble", ()
    rich = case in {"ops_replay", "absolute_figure", "symlink_basename", "rich_receipt"}
    if rich:
        env = _build_rich_workspace(ws)
        form, content = env["form"], env["content"]
    else:
        form = _make_synthetic_form_hwpx(ws / "output" / ("out.hwpx" if case.startswith("alias_") else "form_copy.hwpx"))
        content = _write_plain_content(ws / "bundle" / "content.md")
    out = form.parent if case.startswith("alias_") else ws / "results"
    if case == "alias_loop":
        mode = "--loop"
    if case == "iteration_settings":
        mode = "--loop"
        by = ws / "build.yaml"
        by.write_text("fill:\n  target_pages: [2, 3]\n", encoding="utf-8")
        renderer = ws / "renderer.py"
        renderer.write_text(
            "import fitz, sys\nfrom pathlib import Path\n"
            "d = fitz.open(); p = d.new_page(); p.insert_text((72, 650), 'Rendered')\n"
            "d.save(sys.argv[2])\n"
            "Path(sys.argv[3]).write_text('fill:\\n  target_pages: [2, 3]\\nkeep_with_next:\\n  - MISSING_PREFIX\\n', encoding='utf-8')\n",
            encoding="utf-8")
        cmd = shlex.join([sys.executable, str(renderer), "{in}", "{out}", str(by)])
        extra = ("--max-loops", "2", "--build-yaml", str(by), "--pdf-cmd", cmd)
    if case in {"empty_build", "empty_profile", "empty_baseline", "profile_dir", "baseline_dir"}:
        opt = ws / "optional"
        if case.endswith("_dir"):
            opt.mkdir()
        else:
            opt.touch()
        flag = {"empty_build": "--build-yaml", "empty_profile": "--form-profile", "empty_baseline": "--baseline", "profile_dir": "--form-profile", "baseline_dir": "--baseline"}[case]
        extra = (flag, str(opt))
    if case in {"newline_cr", "newline_crlf"}:
        nl = "\r" if case == "newline_cr" else "\r\n"
        content.write_bytes(f"---{nl}base_pt: 12{nl}---{nl}{nl}## SECTION: I. Intro{nl}{nl}Body.{nl}".encode())
    if case == "bad_content":
        content.write_text("no section header\n", encoding="utf-8")
    if case == "unsup_op":
        by = ws / "unsup_build.yaml"
        by.write_text('delete_texts:\n  - "Guide"\n', encoding="utf-8")
        extra = ("--build-yaml", str(by))
    if case == "miss_fig":
        content.write_text('## SECTION: I. Intro\n\n[[FIG file="missing.png" width=80]]\n', encoding="utf-8")
    if case == "absolute_figure":
        content.write_text(f'## SECTION: I. Intro\n\n[[FIG file="{env["figure"]}" width=80]]\n', encoding="utf-8")
    if case == "symlink_basename":
        _symlink_or_skip(env["figure"].with_name("alias.png"), env["figure"])
        content.write_text('## SECTION: I. Intro\n\n[[FIG file="alias.png" width=80]]\n', encoding="utf-8")
    if case == "rich_receipt":
        extra = ("--build-yaml", str(env["build_yaml"]), "--form-profile", str(env["profile"]), "--baseline", str(env["baseline"]))
    before = hashlib.sha256(form.read_bytes()).hexdigest()
    rc, payload, _ = _run_fill_cli(root, mode=mode, form=form, content=content, out_dir=out, extra=extra)
    result = {"exit_code": rc, "error": payload.get("error"), "result": payload,
              "source_changed": hashlib.sha256(form.read_bytes()).hexdigest() != before}
    if case == "iteration_settings" and payload.get("render_quality"):
        quality = payload["render_quality"]
        assert quality["artifact_sha256"] == hashlib.sha256((out / "out.pdf").read_bytes()).hexdigest()
        quality["artifact_sha256"] = "<VERIFIED_PDF_SHA256>"
    ops_file = out / "ops.json"
    if ops_file.is_file() and ops_file != form:
        result["ops"] = json.loads(ops_file.read_text(encoding="utf-8"))
    receipt_file = form.parent / "proof" / "backend" / "receipt.json"
    if receipt_file.is_file():
        result["receipt"] = _normalize_receipt(json.loads(receipt_file.read_text(encoding="utf-8")), form, out / "out.hwpx")
        # The synthetic input HWPX ZIP timestamps vary too.
        result["receipt"]["execution"]["input"]["sha256"] = "<VERIFIED_INPUT_HWPX_SHA256>"
    if case == "ops_replay":
        proc = subprocess.run([sys.executable, str(root / "engine" / "scripts" / "xml_backend.py"), "edit", "--file", str(form), "--ops", str(ops_file), "--save-as", str(ws / "replayed.hwpx"), "--json"], capture_output=True, text=True, encoding="utf-8")
        result["replay_exit_code"] = proc.returncode
        result["replay_result"] = json.loads(proc.stdout)
    if case in {"absolute_figure", "symlink_basename", "rich_receipt"} and rc == 0:
        result["zip_members_sha256"] = {name: hashlib.sha256(data).hexdigest()
                                         for name, data in sorted(_zip_members(out / "out.hwpx").items())}
    if case == "symlink_basename" and rc == 0:
        section = _zip_members(out / "out.hwpx")["Contents/section0.xml"].decode("utf-8")
        result["shape_comments"] = [node.text for node in _local_nodes(ET.fromstring(section), "shapeComment")]
    def normalize(value):
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        if isinstance(value, str):
            value = value.replace(str(ws.resolve()), "<workspace>").replace(ws.resolve().as_posix(), "<workspace>")
            if "<workspace>" in value:
                # Fixtures were captured on POSIX; Windows joins with backslashes.
                value = value.replace("\\", "/")
            return value
        return value
    return normalize(result)


@pytest.mark.parametrize("case", _PARENT_CASES)
def test_committed_parent_0fa897a_parity(tmp_path: Path, case: str):
    expected = json.loads((_PARENT_FIXTURES / f"{case}.json").read_text(encoding="utf-8"))
    actual = _parent_probe(ENGINE_ROOT.parent, tmp_path / "probe", case)
    if case.startswith("alias_"):
        # The current guard refuses before writing ops; the parent wrote them first.
        assert expected.pop("ops")
        assert "ops" not in actual
    assert actual == expected
