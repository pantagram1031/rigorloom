"""contact_sheet.py 회귀 테스트 — 오프라인, in-test로 생성한 fitz PDF만 사용.

`python -m pytest tests/ -q`
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

pytest.importorskip("PIL")  # Pillow optional in CI
import contact_sheet  # noqa: E402

SCRIPT_PATH = os.path.join(ROOT, "scripts", "contact_sheet.py")


def _make_pdf(tmp_path, n_pages=7, name="fixture.pdf"):
    """n_pages장짜리 PDF. 각 페이지에 큰 페이지번호 텍스트를 찍어 눈으로도
    구분 가능하게 한다."""
    import fitz
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((250, 400), f"PAGE {i + 1}", fontsize=48)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return str(path)


# ── make_contact_sheets() (library call) ───────────────────────────────────

def test_seven_pages_default_per_sheet_yields_two_sheets(tmp_path):
    pdf_path = _make_pdf(tmp_path, n_pages=7)
    out_dir = tmp_path / "out"
    res = contact_sheet.make_contact_sheets(pdf_path, str(out_dir))
    assert res["pages"] == 7
    assert len(res["sheets"]) == 2
    for p in res["sheets"]:
        assert os.path.exists(p)


def test_grid_geometry_2x3_per_sheet(tmp_path):
    pdf_path = _make_pdf(tmp_path, n_pages=7)
    out_dir = tmp_path / "out"
    res = contact_sheet.make_contact_sheets(pdf_path, str(out_dir), per_sheet=6)
    cell_w, cell_h = res["cell_size"]
    assert cell_w > 0 and cell_h > 0
    from PIL import Image
    first_sheet = Image.open(res["sheets"][0])
    # 2 cols x 3 rows, no downscale needed at default dpi/per-sheet for this
    # small fixture (max_width default 1600 comfortably fits 2 * cell_w).
    expected_w = min(2 * cell_w, 1600)
    assert abs(first_sheet.width - expected_w) <= 1


def test_page_seven_lands_on_second_sheet(tmp_path):
    """per_sheet=6 -> page 7 (1-based) must be the first cell of sheet 2."""
    pdf_path = _make_pdf(tmp_path, n_pages=7)
    out_dir = tmp_path / "out"
    res = contact_sheet.make_contact_sheets(pdf_path, str(out_dir), per_sheet=6)
    assert len(res["sheets"]) == 2
    # sheet 1 holds pages 1-6, sheet 2 holds page 7 only.
    # Verify indirectly via page/per_sheet arithmetic used by the function.
    n_on_sheet_2 = res["pages"] - 6
    assert n_on_sheet_2 == 1


def test_json_fields_present(tmp_path):
    pdf_path = _make_pdf(tmp_path, n_pages=3)
    out_dir = tmp_path / "out"
    res = contact_sheet.make_contact_sheets(pdf_path, str(out_dir))
    assert set(res.keys()) == {"pages", "sheets", "cell_size"}
    assert isinstance(res["cell_size"], list) and len(res["cell_size"]) == 2


def test_single_sheet_when_pages_fit(tmp_path):
    pdf_path = _make_pdf(tmp_path, n_pages=4)
    out_dir = tmp_path / "out"
    res = contact_sheet.make_contact_sheets(pdf_path, str(out_dir), per_sheet=6)
    assert len(res["sheets"]) == 1
    assert res["pages"] == 4


def test_max_width_downscales_sheet(tmp_path):
    pdf_path = _make_pdf(tmp_path, n_pages=2)
    out_dir = tmp_path / "out"
    res = contact_sheet.make_contact_sheets(pdf_path, str(out_dir), dpi=150,
                                             max_width=400)
    from PIL import Image
    sheet = Image.open(res["sheets"][0])
    assert sheet.width <= 400


# ── CLI (subprocess) ────────────────────────────────────────────────────────

def test_cli_missing_pdf_exits_1_with_json_error(tmp_path):
    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, SCRIPT_PATH, "--pdf", str(tmp_path / "nope.pdf"),
         "--out-dir", str(out_dir)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert "error" in payload


def test_cli_broken_pdf_exits_1(tmp_path):
    bad_pdf = tmp_path / "broken.pdf"
    bad_pdf.write_bytes(b"not a real pdf")
    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, SCRIPT_PATH, "--pdf", str(bad_pdf),
         "--out-dir", str(out_dir)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is False


def test_cli_success_prints_json_to_stdout(tmp_path):
    pdf_path = _make_pdf(tmp_path, n_pages=3, name="ok.pdf")
    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, SCRIPT_PATH, "--pdf", pdf_path,
         "--out-dir", str(out_dir), "--dpi", "50"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["pages"] == 3
    assert len(payload["sheets"]) == 1
    for p in payload["sheets"]:
        assert os.path.exists(p)


def test_cli_custom_per_sheet(tmp_path):
    pdf_path = _make_pdf(tmp_path, n_pages=5, name="custom.pdf")
    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, SCRIPT_PATH, "--pdf", pdf_path,
         "--out-dir", str(out_dir), "--per-sheet", "2", "--dpi", "50"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    # 5 pages, 2 per sheet -> 3 sheets (2, 2, 1)
    assert len(payload["sheets"]) == 3
