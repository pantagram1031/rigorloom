"""fill_report.py <-> tidy_hwpx.py 연동 회귀 테스트 (T7 이후 통합, item 5).

COM 불필요: read_tidy_anchors/run_tidy_hwpx는 순수 로직이고, mode_loop/mode_assemble
안의 분기(use_tidy)는 COM 호출부(run_build_report/run_com_edit/run_com_convert)를
monkeypatch로 대체해 순서만 검증한다.

주의: 라이브 워크스페이스 out.hwpx는 이후 빌드에서 빈 문단이 정리될 수 있어
(tidy 상태가 드리프트) 앵커 앞 빈 문단 개수에 결정론적으로 의존할 수 없다 —
그 카운트를 검증하는 테스트는 tmp 복사본에 빈 문단을 합성 삽입해 라이브 상태와
무관하게 만든다(tests/test_tidy_hwpx.py의 동일 헬퍼 재사용).
`python -m pytest tests/ -q`.
"""
import argparse
import json
import os
import shutil
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)

import fill_report as fr  # noqa: E402
import tidy_hwpx  # noqa: E402
import test_tidy_hwpx as _tidy_test_helpers  # noqa: E402
from test_tidy_hwpx import (  # noqa: E402
    _copy_fixture_with_synthetic_blanks, _copy_fixture_with_keep_with_next_reset,
)

_WS = os.environ.get("HWP_MASTER_WS", "")  # set to a local agenthwpx workspace to run fixture-backed tests
_FIXTURE_CANDIDATES = ([
    os.path.join(_WS, "output", "out.hwpx"),
    os.path.join(_WS, "reports", "report-aliasing-sampling", "output", "out.hwpx"),
] if _WS else [])
FIXTURE = next((path for path in _FIXTURE_CANDIDATES if os.path.exists(path)), "")
if FIXTURE:
    _tidy_test_helpers.FIXTURE = FIXTURE
REAL_TIDY_ANCHOR = "I.  서론" if FIXTURE == (_FIXTURE_CANDIDATES[0] if _FIXTURE_CANDIDATES else "") else "Ⅰ. 서 론"

pytestmark = pytest.mark.skipif(
    not os.path.exists(FIXTURE),
    reason="real fixture (report-aliasing-sampling/output/out.hwpx) not present on this machine",
)


def _write_build_yaml(tmp_path, lines):
    p = tmp_path / "build.yaml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_read_tidy_anchors_absent_returns_none_none(tmp_path):
    p = _write_build_yaml(tmp_path, ["base_pt: 10"])
    before, after = fr.read_tidy_anchors(str(p))
    assert before is None
    assert after is None


def test_read_tidy_anchors_present(tmp_path):
    p = _write_build_yaml(tmp_path, [
        "tidy_blank_before:",
        '  - "Ⅰ. 서 론"',
        "tidy_blank_after:",
        '  - "그림 1. 캡션"',
    ])
    before, after = fr.read_tidy_anchors(str(p))
    assert before == ["Ⅰ. 서 론"]
    assert after == ["그림 1. 캡션"]


def test_read_tidy_anchors_no_build_yaml():
    before, after = fr.read_tidy_anchors(None)
    assert before is None
    assert after is None


def test_run_tidy_hwpx_uses_real_fixture(tmp_path):
    dst = _copy_fixture_with_synthetic_blanks(tmp_path, REAL_TIDY_ANCHOR, 18)
    result = fr.run_tidy_hwpx(dst, [REAL_TIDY_ANCHOR], [])
    assert result["ok"] is True
    assert result["removed"][REAL_TIDY_ANCHOR] == 17


def test_run_tidy_hwpx_missing_anchor_dies(tmp_path):
    dst = tmp_path / "fixture.hwpx"
    shutil.copyfile(FIXTURE, dst)
    with pytest.raises(SystemExit) as ei:
        fr.run_tidy_hwpx(dst, ["NOT_A_REAL_ANCHOR_XYZ"], [])
    assert ei.value.code == 2  # fill_report.die() default code


def test_mode_loop_uses_tidy_path_when_anchors_present(tmp_path, monkeypatch):
    """tidy_blank_before가 build.yaml에 있으면: edit(out_pdf=None) -> tidy_hwpx ->
    convert 순서로 호출되어야 한다(기존 한 방 edit+export-pdf 대신)."""
    form = tmp_path / "form.hwpx"
    form.write_text("dummy", encoding="utf-8")
    content = tmp_path / "content.md"
    content.write_text("## SECTION: Ⅰ. 서 론\nbody\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    build_yaml = _write_build_yaml(tmp_path, [
        "tidy_blank_before:",
        '  - "Ⅰ. 서 론"',
    ])

    calls = []

    def fake_run_build_report(content_, form_, build_yaml_, ops_out, form_profile=None):
        calls.append(("build_report",))
        from pathlib import Path
        Path(ops_out).write_text("[]", encoding="utf-8")
        return {"ok": True, "ops": []}

    def fake_run_com_edit(form_, ops_path, out_hwpx, out_pdf, kill_stale):
        calls.append(("com_edit", out_pdf))
        from pathlib import Path
        Path(out_hwpx).write_bytes(open(FIXTURE, "rb").read())

    def fake_run_tidy_hwpx(hwpx_path, before, after, soft=False, keep_map=None):
        calls.append(("tidy_hwpx", tuple(before or []), tuple(after or [])))
        return {"ok": True, "removed": {}}

    def fake_run_com_convert(src_hwpx, dst_pdf):
        calls.append(("com_convert",))
        from pathlib import Path
        Path(dst_pdf).write_bytes(b"%PDF-1.4 fake")

    def fake_analyze(pdf_path, **kwargs):
        return {"ok": True, "page_count": 1, "pages": [
            {"page": 1, "bottom_white_pct": 5.0, "max_gap_lines": 1.0}],
            "pass": True, "checks": {k: [] for k in
                                      ("line_spacing_uniformity", "figure_placement",
                                       "tables", "body_markers", "equations")},
            "flagged_pages": [], "thresholds": {}, "file": str(pdf_path)}

    monkeypatch.setattr(fr, "run_build_report", fake_run_build_report)
    monkeypatch.setattr(fr, "run_com_edit", fake_run_com_edit)
    monkeypatch.setattr(fr, "run_tidy_hwpx", fake_run_tidy_hwpx)
    monkeypatch.setattr(fr, "run_com_convert", fake_run_com_convert)
    monkeypatch.setattr(fr.layout_qa, "analyze", fake_analyze)
    monkeypatch.setattr(fr, "count_figures", lambda pdf: 0)

    args = argparse.Namespace(
        form=str(form), content=str(content), out_dir=str(out_dir),
        build_yaml=str(build_yaml), max_loops=1, baseline=None,
        trouble_table=None, guide_file=None, spacing_skip_pages=None,
        gap_skip_pages=None, fig_count=0, kill_stale=False, out=None,
    )
    fr.mode_loop(args)

    kinds = [c[0] for c in calls]
    assert kinds == ["build_report", "com_edit", "tidy_hwpx", "com_convert"]
    assert calls[1][1] is None  # com_edit called with out_pdf=None
    assert calls[2][1] == ("Ⅰ. 서 론",)


def test_read_keep_with_next_absent_returns_none(tmp_path):
    p = _write_build_yaml(tmp_path, ["base_pt: 10"])
    kwn = fr.read_keep_with_next(str(p))
    assert kwn is None


def test_read_keep_with_next_present(tmp_path):
    p = _write_build_yaml(tmp_path, [
        "keep_with_next:",
        '  - "표 1."',
        '  - "표 2."',
    ])
    kwn = fr.read_keep_with_next(str(p))
    assert kwn == ["표 1.", "표 2."]


def test_read_keep_with_next_no_build_yaml():
    assert fr.read_keep_with_next(None) is None


def test_run_keep_with_next_uses_real_fixture(tmp_path):
    # 라이브 fixture는 fill_report 재빌드로 --keep-with-next가 이미 적용돼
    # 있을 수 있어(캡션 keepWithNext=1) 리셋된 사본에서 시작한다(패치 카운트에
    # 결정론적으로 의존 — test_tidy_hwpx.py와 동일 전략).
    dst = _copy_fixture_with_keep_with_next_reset(tmp_path, ["표 1.", "표 2."])
    result = fr.run_keep_with_next(dst, ["표 1.", "표 2."])
    assert result["ok"] is True
    assert len(result["patched"]) == 2


def test_run_keep_with_next_missing_prefix_dies(tmp_path):
    dst = tmp_path / "fixture.hwpx"
    shutil.copyfile(FIXTURE, dst)
    with pytest.raises(SystemExit) as ei:
        fr.run_keep_with_next(dst, ["NOT_A_REAL_CAPTION_PREFIX_XYZ"])
    assert ei.value.code == 2  # fill_report.die() default code


def test_mode_loop_uses_tidy_path_when_only_keep_with_next_present(tmp_path, monkeypatch):
    """keep_with_next만 있고 tidy_blank_*/baseline이 없어도 오프라인 경로(edit
    out_pdf=None -> ... -> keep_with_next -> convert)로 전환돼야 한다."""
    form = tmp_path / "form.hwpx"
    form.write_text("dummy", encoding="utf-8")
    content = tmp_path / "content.md"
    content.write_text("## SECTION: Ⅰ. 서 론\nbody\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    build_yaml = _write_build_yaml(tmp_path, [
        "keep_with_next:",
        '  - "표 1."',
    ])

    calls = []

    def fake_run_build_report(content_, form_, build_yaml_, ops_out, form_profile=None):
        calls.append(("build_report",))
        from pathlib import Path
        Path(ops_out).write_text("[]", encoding="utf-8")
        return {"ok": True, "ops": []}

    def fake_run_com_edit(form_, ops_path, out_hwpx, out_pdf, kill_stale):
        calls.append(("com_edit", out_pdf))
        from pathlib import Path
        Path(out_hwpx).write_bytes(open(FIXTURE, "rb").read())

    def fake_run_keep_with_next(hwpx_path, prefixes):
        calls.append(("keep_with_next", tuple(prefixes or [])))
        return {"ok": True, "patched": []}

    def fake_run_com_convert(src_hwpx, dst_pdf):
        calls.append(("com_convert",))
        from pathlib import Path
        Path(dst_pdf).write_bytes(b"%PDF-1.4 fake")

    def fake_analyze(pdf_path, **kwargs):
        return {"ok": True, "page_count": 1, "pages": [
            {"page": 1, "bottom_white_pct": 5.0, "max_gap_lines": 1.0}],
            "pass": True, "checks": {k: [] for k in
                                      ("line_spacing_uniformity", "figure_placement",
                                       "tables", "body_markers", "equations")},
            "flagged_pages": [], "thresholds": {}, "file": str(pdf_path)}

    monkeypatch.setattr(fr, "run_build_report", fake_run_build_report)
    monkeypatch.setattr(fr, "run_com_edit", fake_run_com_edit)
    monkeypatch.setattr(fr, "run_keep_with_next", fake_run_keep_with_next)
    monkeypatch.setattr(fr, "run_com_convert", fake_run_com_convert)
    monkeypatch.setattr(fr.layout_qa, "analyze", fake_analyze)
    monkeypatch.setattr(fr, "count_figures", lambda pdf: 0)

    args = argparse.Namespace(
        form=str(form), content=str(content), out_dir=str(out_dir),
        build_yaml=str(build_yaml), max_loops=1, baseline=None,
        trouble_table=None, guide_file=None, spacing_skip_pages=None,
        gap_skip_pages=None, fig_count=0, kill_stale=False, out=None,
    )
    fr.mode_loop(args)

    kinds = [c[0] for c in calls]
    assert kinds == ["build_report", "com_edit", "keep_with_next", "com_convert"]
    assert calls[1][1] is None  # com_edit called with out_pdf=None
    assert calls[2][1] == ("표 1.",)


def test_mode_loop_keep_with_next_runs_after_tidy_and_restore(tmp_path, monkeypatch):
    """tidy_blank_before + keep_with_next가 함께 있으면 순서는
    edit -> tidy_hwpx -> keep_with_next -> convert (restore_para_formats 생략,
    baseline 없음)여야 한다 — 표 캡션 patch가 tidy 이후 최신 paraPrIDRef를
    본다(뒤에서 patch해야 tidy가 지운 문단의 유령 참조를 안 만든다)."""
    form = tmp_path / "form.hwpx"
    form.write_text("dummy", encoding="utf-8")
    content = tmp_path / "content.md"
    content.write_text("## SECTION: Ⅰ. 서 론\nbody\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    build_yaml = _write_build_yaml(tmp_path, [
        "tidy_blank_before:",
        '  - "Ⅰ. 서 론"',
        "keep_with_next:",
        '  - "표 1."',
    ])

    calls = []

    def fake_run_build_report(content_, form_, build_yaml_, ops_out, form_profile=None):
        calls.append(("build_report",))
        from pathlib import Path
        Path(ops_out).write_text("[]", encoding="utf-8")
        return {"ok": True, "ops": []}

    def fake_run_com_edit(form_, ops_path, out_hwpx, out_pdf, kill_stale):
        calls.append(("com_edit", out_pdf))
        from pathlib import Path
        Path(out_hwpx).write_bytes(open(FIXTURE, "rb").read())

    def fake_run_tidy_hwpx(hwpx_path, before, after, soft=False, keep_map=None):
        calls.append(("tidy_hwpx",))
        return {"ok": True, "removed": {}}

    def fake_run_keep_with_next(hwpx_path, prefixes):
        calls.append(("keep_with_next",))
        return {"ok": True, "patched": []}

    def fake_run_com_convert(src_hwpx, dst_pdf):
        calls.append(("com_convert",))
        from pathlib import Path
        Path(dst_pdf).write_bytes(b"%PDF-1.4 fake")

    def fake_analyze(pdf_path, **kwargs):
        return {"ok": True, "page_count": 1, "pages": [
            {"page": 1, "bottom_white_pct": 5.0, "max_gap_lines": 1.0}],
            "pass": True, "checks": {k: [] for k in
                                      ("line_spacing_uniformity", "figure_placement",
                                       "tables", "body_markers", "equations")},
            "flagged_pages": [], "thresholds": {}, "file": str(pdf_path)}

    monkeypatch.setattr(fr, "run_build_report", fake_run_build_report)
    monkeypatch.setattr(fr, "run_com_edit", fake_run_com_edit)
    monkeypatch.setattr(fr, "run_tidy_hwpx", fake_run_tidy_hwpx)
    monkeypatch.setattr(fr, "run_keep_with_next", fake_run_keep_with_next)
    monkeypatch.setattr(fr, "run_com_convert", fake_run_com_convert)
    monkeypatch.setattr(fr.layout_qa, "analyze", fake_analyze)
    monkeypatch.setattr(fr, "count_figures", lambda pdf: 0)

    args = argparse.Namespace(
        form=str(form), content=str(content), out_dir=str(out_dir),
        build_yaml=str(build_yaml), max_loops=1, baseline=None,
        trouble_table=None, guide_file=None, spacing_skip_pages=None,
        gap_skip_pages=None, fig_count=0, kill_stale=False, out=None,
    )
    fr.mode_loop(args)

    kinds = [c[0] for c in calls]
    assert kinds == ["build_report", "com_edit", "tidy_hwpx", "keep_with_next", "com_convert"]


def test_mode_loop_uses_old_path_when_anchors_absent(tmp_path, monkeypatch):
    """tidy_blank_before/after가 없으면 기존 한 방(edit out_pdf!=None) 경로 유지,
    tidy_hwpx/com_convert는 호출되지 않는다."""
    form = tmp_path / "form.hwpx"
    form.write_text("dummy", encoding="utf-8")
    content = tmp_path / "content.md"
    content.write_text("## SECTION: Ⅰ. 서 론\nbody\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    build_yaml = _write_build_yaml(tmp_path, ["base_pt: 10"])

    calls = []

    def fake_run_build_report(content_, form_, build_yaml_, ops_out, form_profile=None):
        from pathlib import Path
        Path(ops_out).write_text("[]", encoding="utf-8")
        return {"ok": True, "ops": []}

    def fake_run_com_edit(form_, ops_path, out_hwpx, out_pdf, kill_stale):
        calls.append(("com_edit", out_pdf))
        from pathlib import Path
        Path(out_hwpx).write_bytes(open(FIXTURE, "rb").read())
        Path(out_pdf).write_bytes(b"%PDF-1.4 fake")

    def fake_run_tidy_hwpx(*a, **k):
        calls.append(("tidy_hwpx",))
        raise AssertionError("tidy_hwpx must not be called when anchors are absent")

    def fake_run_com_convert(*a, **k):
        calls.append(("com_convert",))
        raise AssertionError("com_convert must not be called when anchors are absent")

    def fake_analyze(pdf_path, **kwargs):
        return {"ok": True, "page_count": 1, "pages": [
            {"page": 1, "bottom_white_pct": 5.0, "max_gap_lines": 1.0}],
            "pass": True, "checks": {k: [] for k in
                                      ("line_spacing_uniformity", "figure_placement",
                                       "tables", "body_markers", "equations")},
            "flagged_pages": [], "thresholds": {}, "file": str(pdf_path)}

    monkeypatch.setattr(fr, "run_build_report", fake_run_build_report)
    monkeypatch.setattr(fr, "run_com_edit", fake_run_com_edit)
    monkeypatch.setattr(fr, "run_tidy_hwpx", fake_run_tidy_hwpx)
    monkeypatch.setattr(fr, "run_com_convert", fake_run_com_convert)
    monkeypatch.setattr(fr.layout_qa, "analyze", fake_analyze)
    monkeypatch.setattr(fr, "count_figures", lambda pdf: 0)

    args = argparse.Namespace(
        form=str(form), content=str(content), out_dir=str(out_dir),
        build_yaml=str(build_yaml), max_loops=1, baseline=None,
        trouble_table=None, guide_file=None, spacing_skip_pages=None,
        gap_skip_pages=None, fig_count=0, kill_stale=False, out=None,
    )
    fr.mode_loop(args)

    kinds = [c[0] for c in calls]
    assert kinds == ["com_edit"]
    assert calls[0][1] is not None  # out_pdf passed through (old one-shot path)


def test_mode_loop_xml_without_renderer_stops_after_xml_verification(tmp_path, monkeypatch):
    form = tmp_path / "form.hwpx"
    form.write_text("dummy", encoding="utf-8")
    content = tmp_path / "content.md"
    content.write_text("## SECTION: Anchor\nbody\n", encoding="utf-8")
    build_yaml = _write_build_yaml(tmp_path, ["base_pt: 10"])
    out_dir = tmp_path / "out"
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

    def fake_tidy(*args, **kwargs):
        calls.append("tidy_hwpx")
        return {"ok": True, "removed": {}}

    def fake_para(out_hwpx, baseline_form):
        calls.append("check_para_formats")
        return {"ok": True, "anomalies": []}

    monkeypatch.setattr(fr, "run_build_report", fake_build)
    monkeypatch.setattr(fr, "run_xml_edit", fake_xml, raising=False)
    monkeypatch.setattr(fr, "run_tidy_hwpx", fake_tidy)
    monkeypatch.setattr(fr, "run_para_format_check", fake_para, raising=False)
    monkeypatch.setattr(fr, "run_com_edit", lambda *a, **k: pytest.fail("COM path used"))
    monkeypatch.setattr(fr.layout_qa, "analyze", lambda *a, **k: pytest.fail("PDF QA used"))
    monkeypatch.setattr(fr, "_emit", lambda obj, out=None: emitted.append(obj))

    args = argparse.Namespace(
        form=str(form), content=str(content), out_dir=str(out_dir),
        build_yaml=str(build_yaml), max_loops=4, baseline=None,
        trouble_table=None, guide_file=None, spacing_skip_pages=None,
        gap_skip_pages=None, bottom_skip_pages=None, fig_count=0,
        kill_stale=False, out=None, engine="xml", pdf_cmd=None,
        form_profile=None, proof=False,
    )
    fr.mode_loop(args)

    assert calls == ["build_report", "xml_edit", "tidy_hwpx", "check_para_formats"]
    assert emitted[0]["engine"] == "xml"
    assert emitted[0]["status"] == "xml_verified_no_proof"
    assert emitted[0]["proof_grade"] == "none"
    assert emitted[0]["proof_unavailable"] is True
    assert emitted[0]["converged"] is True
    assert emitted[0]["pdf"] is None


def test_run_pdf_command_expands_argv_template(tmp_path, monkeypatch):
    source = tmp_path / "out.hwpx"
    destination = tmp_path / "out.pdf"
    source.write_bytes(b"hwpx")
    seen = []

    class Result:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(argv, capture_output, env, timeout=None, shell=False):
        seen.append(argv)
        destination.write_bytes(b"%PDF-1.4")
        return Result()

    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    fr.run_pdf_command(
        'renderer --input "{input}" --output "{output}" --outdir "{outdir}"',
        source, destination)
    assert seen == [["renderer", "--input", str(source), "--output", str(destination),
                     "--outdir", str(tmp_path)]]


def test_mode_loop_xml_runs_real_backend_tidy_and_para_check(tmp_path, monkeypatch):
    real_form = os.path.join(_WS, "output", "form_copy.hwpx") if _WS else ""
    if not os.path.isfile(real_form):
        pytest.skip("finished workspace form_copy.hwpx not available")
    content = tmp_path / "content.md"
    content.write_text("## SECTION: I.  서론\nXML backend smoke text.\n", encoding="utf-8")
    build_yaml = _write_build_yaml(tmp_path, ["base_pt: 10"])
    out_dir = tmp_path / "xml-out"
    emitted = []

    def fake_build(content_, form_, build_yaml_, ops_out, form_profile=None):
        ops = [
            {"op": "goto_text", "text": "I.  서론"},
            {"op": "insert_text", "text": "XML backend smoke text.",
             "pt": 10, "break_after": True},
        ]
        from pathlib import Path
        Path(ops_out).write_text(json.dumps(ops), encoding="utf-8")
        return {"ok": True, "ops": ops}

    monkeypatch.setattr(fr, "run_build_report", fake_build)
    monkeypatch.setattr(fr, "_emit", lambda obj, out=None: emitted.append(obj))
    args = argparse.Namespace(
        form=real_form, content=str(content), out_dir=str(out_dir),
        build_yaml=str(build_yaml), max_loops=1, baseline=None,
        trouble_table=None, guide_file=None, spacing_skip_pages=None,
        gap_skip_pages=None, bottom_skip_pages=None, fig_count=0,
        kill_stale=False, out=None, engine="xml", pdf_cmd=None,
        form_profile=None, proof=False,
    )
    fr.mode_loop(args)

    assert emitted[0]["converged"] is True
    assert emitted[0]["status"] == "xml_verified_no_proof"
    assert emitted[0]["proof_grade"] == "none"
    assert emitted[0]["proof_unavailable"] is True
    assert os.path.isfile(emitted[0]["hwpx"])
