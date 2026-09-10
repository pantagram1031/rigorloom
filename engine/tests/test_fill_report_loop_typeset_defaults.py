"""COM-free: --loop must apply typeset-defaults like --assemble.

mode_assemble already calls run_typeset_defaults after restore/keep_with_next
and before convert when --form-profile is set. These tests pin the same
order and anchors on mode_loop (COM tidy path and XML path).
"""
import argparse
import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import fill_report as fr  # noqa: E402


def _write_build_yaml(tmp_path, extra_lines=None):
    lines = ["base_pt: 10"]
    if extra_lines:
        lines.extend(extra_lines)
    p = tmp_path / "build.yaml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _profile(tmp_path, anchors):
    p = tmp_path / "form_profile.json"
    p.write_text(json.dumps({"anchors": anchors}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def _fake_analyze(pdf_path, **kwargs):
    return {
        "ok": True, "page_count": 1,
        "pages": [{"page": 1, "bottom_white_pct": 5.0, "max_gap_lines": 1.0}],
        "pass": True,
        "checks": {k: [] for k in (
            "line_spacing_uniformity", "figure_placement",
            "tables", "body_markers", "equations")},
        "flagged_pages": [], "thresholds": {}, "file": str(pdf_path),
    }


def _loop_ns(form, content, out_dir, build_yaml, **extra):
    ns = dict(
        form=str(form), content=str(content), out_dir=str(out_dir),
        build_yaml=str(build_yaml), max_loops=1, baseline=None,
        trouble_table=None, guide_file=None, spacing_skip_pages=None,
        gap_skip_pages=None, bottom_skip_pages=None, fig_count=0,
        kill_stale=False, out=None, form_profile=None, proof=False,
        engine="com", pdf_cmd=None,
    )
    ns.update(extra)
    return argparse.Namespace(**ns)


def test_mode_loop_typeset_defaults_after_restore_keep_with_next(tmp_path, monkeypatch):
    """COM tidy path: edit → tidy → restore → keep_with_next → typeset → convert."""
    form = tmp_path / "form.hwpx"
    form.write_bytes(b"form")
    content = tmp_path / "content.md"
    content.write_text("## SECTION: Ⅰ. 서 론\nbody\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    anchors = ["Ⅰ. 서 론", "Ⅱ. 본 론"]
    profile = _profile(tmp_path, anchors)
    baseline = tmp_path / "form_baseline.json"
    baseline.write_text(json.dumps({"para_formats": [{"text_head": "Ⅰ. 서 론"}]}),
                         encoding="utf-8")
    build_yaml = _write_build_yaml(tmp_path, [
        "keep_with_next:",
        '  - "표 1."',
    ])
    calls = []

    def fake_build(content_, form_, build_yaml_, ops_out, form_profile=None):
        calls.append(("build_report", form_profile))
        from pathlib import Path
        Path(ops_out).write_text("[]", encoding="utf-8")
        return {"ok": True, "ops": []}

    def fake_edit(form_, ops_path, out_hwpx, out_pdf, kill_stale):
        calls.append(("com_edit", out_pdf))
        from pathlib import Path
        Path(out_hwpx).write_bytes(b"hwpx")

    def fake_tidy(*a, **k):
        calls.append(("tidy_hwpx",))
        return {"ok": True, "removed": {}}

    def fake_restore(hwpx_path, baseline_path):
        calls.append(("restore_para_formats",))
        return {"ok": True, "restored": []}

    def fake_kwn(hwpx_path, prefixes):
        calls.append(("keep_with_next", tuple(prefixes or [])))
        return {"ok": True, "patched": []}

    def fake_typeset(hwpx_path, anchors_):
        calls.append(("typeset_defaults", tuple(anchors_ or [])))
        return {"ok": True, "patched": []}

    def fake_convert(src_hwpx, dst_pdf):
        calls.append(("com_convert",))
        from pathlib import Path
        Path(dst_pdf).write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(fr, "run_build_report", fake_build)
    monkeypatch.setattr(fr, "run_com_edit", fake_edit)
    monkeypatch.setattr(fr, "run_tidy_hwpx", fake_tidy)
    monkeypatch.setattr(fr, "run_restore_para_formats", fake_restore)
    monkeypatch.setattr(fr, "run_keep_with_next", fake_kwn)
    monkeypatch.setattr(fr, "run_typeset_defaults", fake_typeset)
    monkeypatch.setattr(fr, "run_com_convert", fake_convert)
    monkeypatch.setattr(fr.layout_qa, "analyze", _fake_analyze)
    monkeypatch.setattr(fr, "count_figures", lambda pdf: 0)
    monkeypatch.setattr(fr, "run_style_diff", lambda *a, **k: [])

    args = _loop_ns(form, content, out_dir, build_yaml,
                    baseline=str(baseline), form_profile=str(profile))
    fr.mode_loop(args)

    kinds = [c[0] for c in calls]
    assert kinds == [
        "build_report", "com_edit", "tidy_hwpx", "restore_para_formats",
        "keep_with_next", "typeset_defaults", "com_convert",
    ]
    assert calls[1][1] is None
    assert calls[0][1] == str(profile)
    assert calls[4][1] == ("표 1.",)
    assert calls[5][1] == tuple(anchors)


def test_mode_loop_form_profile_alone_takes_offline_path(tmp_path, monkeypatch):
    """form_profile with no tidy_blank_*/keep_with_next/baseline still uses
    the offline path so typeset-defaults can run before convert (assemble)."""
    form = tmp_path / "form.hwpx"
    form.write_bytes(b"form")
    content = tmp_path / "content.md"
    content.write_text("body\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    anchors = ["Ⅲ. 탐구 방법"]
    profile = _profile(tmp_path, anchors)
    build_yaml = _write_build_yaml(tmp_path)
    calls = []

    def fake_build(content_, form_, build_yaml_, ops_out, form_profile=None):
        calls.append(("build_report",))
        from pathlib import Path
        Path(ops_out).write_text("[]", encoding="utf-8")
        return {"ok": True, "ops": []}

    def fake_edit(form_, ops_path, out_hwpx, out_pdf, kill_stale):
        calls.append(("com_edit", out_pdf))
        from pathlib import Path
        Path(out_hwpx).write_bytes(b"hwpx")

    def fake_tidy(*a, **k):
        calls.append(("tidy_hwpx",))
        return {"ok": True, "removed": {}}

    def fake_typeset(hwpx_path, anchors_):
        calls.append(("typeset_defaults", tuple(anchors_ or [])))
        return {"ok": True, "patched": []}

    def fake_convert(src_hwpx, dst_pdf):
        calls.append(("com_convert",))
        from pathlib import Path
        Path(dst_pdf).write_bytes(b"%PDF-1.4 fake")

    def fake_kwn(*a, **k):
        raise AssertionError("keep_with_next must not run without prefixes")

    def fake_restore(*a, **k):
        raise AssertionError("restore must not run without para_formats")

    monkeypatch.setattr(fr, "run_build_report", fake_build)
    monkeypatch.setattr(fr, "run_com_edit", fake_edit)
    monkeypatch.setattr(fr, "run_tidy_hwpx", fake_tidy)
    monkeypatch.setattr(fr, "run_restore_para_formats", fake_restore)
    monkeypatch.setattr(fr, "run_keep_with_next", fake_kwn)
    monkeypatch.setattr(fr, "run_typeset_defaults", fake_typeset)
    monkeypatch.setattr(fr, "run_com_convert", fake_convert)
    monkeypatch.setattr(fr.layout_qa, "analyze", _fake_analyze)
    monkeypatch.setattr(fr, "count_figures", lambda pdf: 0)
    monkeypatch.setattr(fr, "run_style_diff", lambda *a, **k: [])

    args = _loop_ns(form, content, out_dir, build_yaml, form_profile=str(profile))
    fr.mode_loop(args)

    kinds = [c[0] for c in calls]
    assert kinds == [
        "build_report", "com_edit", "tidy_hwpx", "typeset_defaults", "com_convert",
    ]
    assert calls[1][1] is None
    assert calls[3][1] == tuple(anchors)


def test_mode_loop_xml_typeset_defaults_before_para_check(tmp_path, monkeypatch):
    """XML loop: typeset-defaults after keep_with_next, before para_format_check."""
    form = tmp_path / "form.hwpx"
    form.write_bytes(b"form")
    content = tmp_path / "content.md"
    content.write_text("## SECTION: Anchor\nbody\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    anchors = ["Anchor"]
    profile = _profile(tmp_path, anchors)
    build_yaml = _write_build_yaml(tmp_path, [
        "keep_with_next:",
        '  - "표 1."',
    ])
    calls = []
    emitted = []

    def fake_build(content_, form_, build_yaml_, ops_out, form_profile=None):
        calls.append("build_report")
        from pathlib import Path
        Path(ops_out).write_text("[]", encoding="utf-8")
        return {"ok": True, "ops": []}

    def fake_xml(form_, ops_path, out_hwpx):
        calls.append("xml_edit")
        from pathlib import Path
        Path(out_hwpx).write_bytes(b"hwpx")
        return {"ok": True, "applied": 0}

    def fake_tidy(*a, **k):
        calls.append("tidy_hwpx")
        return {"ok": True, "removed": {}}

    def fake_kwn(*a, **k):
        calls.append("keep_with_next")
        return {"ok": True, "patched": []}

    def fake_typeset(hwpx_path, anchors_):
        calls.append(("typeset_defaults", tuple(anchors_ or [])))
        return {"ok": True, "patched": []}

    def fake_para(out_hwpx, baseline_form):
        calls.append("check_para_formats")
        return {"ok": True, "anomalies": []}

    monkeypatch.setattr(fr, "run_build_report", fake_build)
    monkeypatch.setattr(fr, "run_xml_edit", fake_xml, raising=False)
    monkeypatch.setattr(fr, "run_tidy_hwpx", fake_tidy)
    monkeypatch.setattr(fr, "run_keep_with_next", fake_kwn)
    monkeypatch.setattr(fr, "run_typeset_defaults", fake_typeset)
    monkeypatch.setattr(fr, "run_para_format_check", fake_para, raising=False)
    monkeypatch.setattr(fr, "run_com_edit", lambda *a, **k: pytest.fail("COM path used"))
    monkeypatch.setattr(fr.layout_qa, "analyze", lambda *a, **k: pytest.fail("PDF QA used"))
    monkeypatch.setattr(fr, "_emit", lambda obj, out=None: emitted.append(obj))

    args = _loop_ns(form, content, out_dir, build_yaml,
                    form_profile=str(profile), engine="xml", pdf_cmd=None)
    fr.mode_loop(args)

    assert calls == [
        "build_report", "xml_edit", "tidy_hwpx", "keep_with_next",
        ("typeset_defaults", tuple(anchors)), "check_para_formats",
    ]
    assert emitted
    assert emitted[0].get("engine") == "xml"


def test_mode_loop_absent_profile_keeps_oneshot_path(tmp_path, monkeypatch):
    """form_profile=None and no tidy/restore/keep: prior one-shot edit+pdf."""
    form = tmp_path / "form.hwpx"
    form.write_bytes(b"form")
    content = tmp_path / "content.md"
    content.write_text("body\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    build_yaml = _write_build_yaml(tmp_path)
    calls = []

    def fake_build(content_, form_, build_yaml_, ops_out, form_profile=None):
        calls.append(("build_report",))
        from pathlib import Path
        Path(ops_out).write_text("[]", encoding="utf-8")
        return {"ok": True, "ops": []}

    def fake_edit(form_, ops_path, out_hwpx, out_pdf, kill_stale):
        calls.append(("com_edit", out_pdf))
        from pathlib import Path
        Path(out_hwpx).write_bytes(b"hwpx")
        Path(out_pdf).write_bytes(b"%PDF-1.4 fake")

    def fake_typeset(*a, **k):
        raise AssertionError("run_typeset_defaults must not run without form_profile")

    def fake_convert(*a, **k):
        raise AssertionError("com_convert must not run on the one-shot path")

    monkeypatch.setattr(fr, "run_build_report", fake_build)
    monkeypatch.setattr(fr, "run_com_edit", fake_edit)
    monkeypatch.setattr(fr, "run_typeset_defaults", fake_typeset)
    monkeypatch.setattr(fr, "run_com_convert", fake_convert)
    monkeypatch.setattr(fr.layout_qa, "analyze", _fake_analyze)
    monkeypatch.setattr(fr, "count_figures", lambda pdf: 0)
    monkeypatch.setattr(fr, "run_style_diff", lambda *a, **k: [])

    args = _loop_ns(form, content, out_dir, build_yaml, form_profile=None)
    fr.mode_loop(args)

    kinds = [c[0] for c in calls]
    assert kinds == ["build_report", "com_edit"]
    assert calls[1][1] is not None
