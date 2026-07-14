"""render_calibrate unit tests — pure helpers only, no COM/WSL/pymupdf.

Covers: Windows->WSL path translation, delta computation on synthetic metric
dicts, and the missing-WSL capability path (exit 3). COM and WSL are never
invoked here (the capability probe is monkeypatched).
    python -m pytest tests/test_render_calibrate.py -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import render_calibrate as rc  # noqa: E402


# --------------------------------------------------------------------------
# path translation
# --------------------------------------------------------------------------
def test_win_to_wsl_basic(monkeypatch):
    monkeypatch.setenv("CALIBRATION_TEST_ROOT", r"Q:\synthetic")
    source = os.path.join(os.environ["CALIBRATION_TEST_ROOT"], "input", "out.hwpx")
    assert rc.win_to_wsl_path(source) == "/mnt/q/synthetic/input/out.hwpx"


def test_win_to_wsl_lowercases_drive():
    assert rc.win_to_wsl_path(r"D:\a\b.pdf") == "/mnt/d/a/b.pdf"


def test_win_to_wsl_passthrough_posix():
    assert rc.win_to_wsl_path("/mnt/c/already/posix") == "/mnt/c/already/posix"


def test_win_to_wsl_forward_slashes():
    assert rc.win_to_wsl_path("C:/synthetic/input/y.hwpx") == \
        "/mnt/c/synthetic/input/y.hwpx"


# --------------------------------------------------------------------------
# subprocess contracts (all process calls are monkeypatched)
# --------------------------------------------------------------------------
def test_wsl_soffice_probe_uses_argv(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return rc.subprocess.CompletedProcess(argv, 0, stdout="/usr/bin/soffice\n",
                                              stderr="")

    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    assert rc.wsl_soffice_available() is True
    assert calls[0][0] == ["wsl", "-e", "bash", "-lc", "command -v soffice"]


def test_render_hancom_uses_com_backend_argv(tmp_path, monkeypatch):
    hwpx = tmp_path / "source.hwpx"
    hwpx.write_bytes(b"synthetic")
    target = tmp_path / "out" / "hancom.pdf"
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        target.write_bytes(b"pdf")
        return rc.subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    assert rc.render_hancom(hwpx, target) == target
    assert calls[0][0] == [
        sys.executable, str(rc.COM_BACKEND), "convert",
        "--file", str(hwpx), "--to", str(target),
    ]
    assert calls[0][1]["env"]["PYTHONIOENCODING"] == "utf-8"


def test_render_libreoffice_uses_wsl_bash_command(tmp_path, monkeypatch):
    hwpx = tmp_path / "source.hwpx"
    hwpx.write_bytes(b"synthetic")
    out_dir = tmp_path / "lo"
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        (out_dir / "source.pdf").write_bytes(b"pdf")
        return rc.subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(rc.subprocess, "run", fake_run)
    assert rc.render_libreoffice(hwpx, out_dir) == out_dir / "source.pdf"
    argv = calls[0][0]
    assert argv[:4] == ["wsl", "-e", "bash", "-lc"]
    assert argv[4].startswith(
        "soffice --headless -env:UserInstallation=file:///tmp/lo-cal "
        "--convert-to 'pdf:writer_pdf_Export' --outdir ")
    assert rc._sh_quote(rc.win_to_wsl_path(out_dir.resolve())) in argv[4]
    assert rc._sh_quote(rc.win_to_wsl_path(hwpx.resolve())) in argv[4]


# --------------------------------------------------------------------------
# delta computation
# --------------------------------------------------------------------------
def _metrics(page_count, pages, total_text=None, total_images=None):
    return {
        "page_count": page_count,
        "layout_qa_pass": True,
        "total_text_len": total_text if total_text is not None
        else sum(p["text_len"] for p in pages),
        "total_images": total_images if total_images is not None
        else sum(p["image_count"] for p in pages),
        "pages": pages,
    }


def _page(page, text_len, bottom_white_pt, max_gap_lines, image_count):
    return {
        "page": page, "text_len": text_len,
        "bottom_white_pt": bottom_white_pt, "bottom_white_pct": None,
        "max_gap_lines": max_gap_lines, "image_count": image_count,
    }


def test_compute_deltas_basic():
    hancom = _metrics(2, [
        _page(1, 1000, 40.0, 2.0, 1),
        _page(2, 800, 120.0, 1.0, 0),
    ])
    lo = _metrics(2, [
        _page(1, 1010, 52.5, 3.0, 1),
        _page(2, 790, 118.0, 1.0, 0),
    ])
    d = rc.compute_deltas(hancom, lo)
    assert d["page_count"]["delta"] == 0
    p1 = d["per_page"][0]
    assert p1["text_len_delta"] == 10
    assert p1["bottom_white_pt_delta"] == 12.5
    assert p1["max_gap_lines_delta"] == 1.0
    assert p1["image_count_delta"] == 0
    # max abs bottom_white delta = 12.5 -> tolerance ceil = 13
    assert d["suggested_tolerances"]["bottom_white_tolerance_pt"] == 13
    # max gap scale = max(3.0/2.0, 1.0/1.0) = 1.5
    assert d["suggested_tolerances"]["max_gap_scale"] == 1.5
    assert d["suggested_tolerances"]["page_count_drift_allowed"] == 0


def test_compute_deltas_page_count_drift():
    hancom = _metrics(3, [_page(1, 500, 30.0, 0.0, 0)])
    lo = _metrics(4, [_page(1, 500, 30.0, 0.0, 0)])
    d = rc.compute_deltas(hancom, lo)
    assert d["page_count"]["delta"] == 1
    assert d["suggested_tolerances"]["page_count_drift_allowed"] == 1


def test_compute_deltas_handles_none_gaps_and_no_hancom_gap():
    # hancom gap 0 / None -> excluded from ratio; scale floors to 1.0
    hancom = _metrics(1, [_page(1, 100, 10.0, None, 0)])
    lo = _metrics(1, [_page(1, 100, 10.0, 5.0, 0)])
    d = rc.compute_deltas(hancom, lo)
    assert d["suggested_tolerances"]["max_gap_scale"] == 1.0
    assert d["per_page"][0]["max_gap_lines_delta"] == 5.0


def test_compute_deltas_aligns_to_shorter_doc():
    hancom = _metrics(1, [_page(1, 100, 10.0, 0.0, 0)])
    lo = _metrics(2, [_page(1, 100, 10.0, 0.0, 0), _page(2, 50, 200.0, 0.0, 0)])
    d = rc.compute_deltas(hancom, lo)
    assert len(d["per_page"]) == 1  # only the shared page compared
    assert d["page_count"]["delta"] == 1


# --------------------------------------------------------------------------
# missing-WSL capability path
# --------------------------------------------------------------------------
def test_main_exits_3_when_wsl_soffice_missing(monkeypatch):
    monkeypatch.setattr(rc, "wsl_soffice_available", lambda: False)
    # Guard: if the capability gate ever fails to fire, these would raise loudly
    # instead of silently invoking COM/WSL.
    def _boom(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("renderer invoked despite missing capability")
    monkeypatch.setattr(rc, "render_hancom", _boom)
    monkeypatch.setattr(rc, "render_libreoffice", _boom)
    with pytest.raises(SystemExit) as ei:
        rc.main(["--hwpx", os.environ.get("CALIBRATION_TEST_INPUT", "missing.hwpx"),
                 "--out-dir", os.environ.get("CALIBRATION_TEST_OUTPUT", "unused")])
    assert ei.value.code == 3


def test_main_renders_serially_and_writes_json(tmp_path, monkeypatch, capsys):
    hwpx = tmp_path / "source.hwpx"
    hwpx.write_bytes(b"synthetic")
    out_dir = tmp_path / "calibration"
    calls = []

    hancom_metrics = _metrics(1, [_page(1, 100, 20.0, 2.0, 0)])
    lo_metrics = _metrics(1, [_page(1, 103, 25.5, 2.5, 0)])

    monkeypatch.setattr(rc, "wsl_soffice_available", lambda: True)

    def fake_hancom(source, target):
        calls.append(("hancom", Path(source), Path(target)))
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(b"hancom-pdf")
        return Path(target)

    def fake_lo(source, target_dir):
        assert calls and calls[-1][0] == "hancom"
        calls.append(("lo", Path(source), Path(target_dir)))
        target = Path(target_dir) / "source.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"lo-pdf")
        return target

    def fake_extract(pdf):
        calls.append(("measure", Path(pdf)))
        return hancom_metrics if Path(pdf).name == "hancom.pdf" else lo_metrics

    monkeypatch.setattr(rc, "render_hancom", fake_hancom)
    monkeypatch.setattr(rc, "render_libreoffice", fake_lo)
    monkeypatch.setattr(rc, "extract_metrics", fake_extract)

    assert rc.main(["--hwpx", str(hwpx), "--out-dir", str(out_dir), "--json"]) == 0

    stdout_result = json.loads(capsys.readouterr().out)
    file_result = json.loads((out_dir / "calibration.json").read_text(encoding="utf-8"))
    assert stdout_result == file_result
    assert stdout_result["calibration"] == {
        "bottom_white_tolerance_pt": 6,
        "max_gap_scale": 1.25,
        "page_count_drift_allowed": 0,
    }
    assert [call[0] for call in calls] == ["hancom", "lo", "measure", "measure"]
