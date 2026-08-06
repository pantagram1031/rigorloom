#!/usr/bin/env python3
"""Cross-renderer calibration — render the SAME hwpx via Hancom COM and via
LibreOffice through WSL, run layout_qa on both PDFs, and report
metric deltas (page count, per-page bottom-whitespace, max_gap, text length,
image count). Emits a calibration JSON (tolerance offsets the advisory FILL loop
applies so LibreOffice-measured verdicts don't chase Hancom-invisible ghosts)
plus a human-readable table.

    render_calibrate.py --hwpx <file> --out-dir <dir> [--json]

Renderers:
  (a) Hancom COM  : scripts/com_backend.py convert --file X --to Y (subprocess).
  (b) LibreOffice : wsl -e bash -lc "soffice --headless ... --convert-to pdf ..."

If WSL soffice is unavailable, exits 3 (capability-missing) — installs nothing.
COM is single-instance: the two renders run serially, never in parallel.
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import layout_qa  # noqa: E402

COM_BACKEND = HERE / "com_backend.py"


# ---------------------------------------------------------------------------
# path translation
# ---------------------------------------------------------------------------
def win_to_wsl_path(p):
    """Translate a Windows path (C:\\Users\\x) to its WSL /mnt/c/Users/x form.

    Drive letter is lowercased; backslashes become forward slashes. Already-POSIX
    paths (starting with '/') pass through unchanged. Pure function — no I/O."""
    s = str(p)
    if s.startswith("/"):
        return s
    s = s.replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", s)
    if m:
        drive, rest = m.group(1).lower(), m.group(2)
        return f"/mnt/{drive}/{rest}"
    return s


def _sh_quote(s):
    """Single-quote a string for a POSIX shell (bash -lc)."""
    return "'" + str(s).replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------
# capability probe
# ---------------------------------------------------------------------------
def wsl_soffice_available():
    """True iff `wsl -e bash -lc 'command -v soffice'` resolves. Never raises."""
    try:
        r = subprocess.run(
            ["wsl", "-e", "bash", "-lc", "command -v soffice"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------
def render_hancom(hwpx, out_pdf):
    """Render hwpx -> out_pdf via Hancom COM (com_backend.py convert). Blocking."""
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.unlink(missing_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, str(COM_BACKEND), "convert",
         "--file", str(hwpx), "--to", str(out_pdf)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=600,
    )
    if r.returncode != 0 or not out_pdf.exists():
        raise RuntimeError(
            f"Hancom convert failed (rc={r.returncode}):\n{r.stdout}\n{r.stderr}")
    return out_pdf


def render_libreoffice(hwpx, out_dir):
    """Render hwpx -> PDF via LibreOffice in WSL. Returns the produced PDF path.

    soffice writes <stem>.pdf into out_dir. Uses an isolated UserInstallation so
    a headless run doesn't collide with an interactive profile."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = out_dir / (Path(hwpx).stem + ".pdf")
    produced.unlink(missing_ok=True)
    wsl_in = win_to_wsl_path(Path(hwpx).resolve())
    wsl_out = win_to_wsl_path(out_dir.resolve())
    cmd = (
        "soffice --headless -env:UserInstallation=file:///tmp/lo-cal "
        "--convert-to 'pdf:writer_pdf_Export' "
        f"--outdir {_sh_quote(wsl_out)} {_sh_quote(wsl_in)}"
    )
    r = subprocess.run(
        ["wsl", "-e", "bash", "-lc", cmd],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600,
    )
    if r.returncode != 0 or not produced.exists():
        raise RuntimeError(
            f"LibreOffice convert failed (rc={r.returncode}):\n{r.stdout}\n{r.stderr}")
    return produced


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def extract_metrics(pdf_path):
    """Per-PDF metric dict via layout_qa + pymupdf.

    Returns:
      page_count, layout_qa_pass, total_text_len, total_images,
      pages: [{page, text_len, bottom_white_pt, bottom_white_pct,
               max_gap_lines, image_count}, ...]
    bottom_white_pt = page_height - content_bbox.y1 (points below content)."""
    import fitz  # local import so tests never need pymupdf for pure helpers

    qa = layout_qa.analyze(pdf_path)
    qa_pages = {p["page"]: p for p in qa.get("pages", [])}
    doc = fitz.open(pdf_path)
    try:
        page_count = doc.page_count
        pages = []
        for i, page in enumerate(doc):
            pno = i + 1
            height = page.rect.height
            blks = layout_qa._blocks(page)
            img_count = sum(1 for b in blks if b[4] == "image")
            text_len = len(re.sub(r"\s+", "", page.get_text("text")))
            if blks:
                y1 = max(b[3] for b in blks)
                bottom_white_pt = round(height - y1, 1)
            else:
                bottom_white_pt = round(height, 1)
            qp = qa_pages.get(pno, {})
            pages.append({
                "page": pno,
                "text_len": text_len,
                "bottom_white_pt": bottom_white_pt,
                "bottom_white_pct": qp.get("bottom_white_pct"),
                "max_gap_lines": qp.get("max_gap_lines"),
                "image_count": img_count,
            })
    finally:
        doc.close()
    return {
        "page_count": page_count,
        "layout_qa_page_count": qa.get("page_count"),
        "layout_qa_pass": qa.get("pass"),
        "layout_qa_flagged_pages": qa.get("flagged_pages", []),
        "total_text_len": sum(p["text_len"] for p in pages),
        "total_images": sum(p["image_count"] for p in pages),
        "pages": pages,
    }


def compute_deltas(hancom, lo):
    """Deltas (LibreOffice minus Hancom) + suggested tolerances. Pure function.

    hancom/lo are extract_metrics() dicts. Per-page deltas align by page index up
    to the shorter document. Tolerances:
      bottom_white_tolerance_pt : ceil(max |per-page bottom_white_pt delta|)
      max_gap_scale             : max over pages of lo.max_gap / hancom.max_gap
                                  (>=1.0; how much larger LO gaps run than Hancom)
      page_count_drift_allowed  : |lo.page_count - hancom.page_count|
    """
    hp, lp = hancom["pages"], lo["pages"]
    n = min(len(hp), len(lp))
    per_page = []
    abs_bw, ratios = [], []
    for i in range(n):
        h, l = hp[i], lp[i]
        h_gap = h.get("max_gap_lines") or 0.0
        l_gap = l.get("max_gap_lines") or 0.0
        bw_d = round(l["bottom_white_pt"] - h["bottom_white_pt"], 1)
        per_page.append({
            "page": i + 1,
            "text_len_delta": l["text_len"] - h["text_len"],
            "bottom_white_pt_delta": bw_d,
            "max_gap_lines_delta": round(l_gap - h_gap, 2),
            "image_count_delta": l["image_count"] - h["image_count"],
        })
        abs_bw.append(abs(bw_d))
        if h_gap > 0:
            ratios.append(l_gap / h_gap)

    pc_delta = lo["page_count"] - hancom["page_count"]
    max_bw = max(abs_bw) if abs_bw else 0.0
    max_gap_scale = round(max(ratios), 2) if ratios else 1.0
    if max_gap_scale < 1.0:
        max_gap_scale = 1.0

    return {
        "page_count": {
            "hancom": hancom["page_count"],
            "lo": lo["page_count"],
            "delta": pc_delta,
        },
        "aggregate": {
            "max_abs_bottom_white_pt_delta": round(max_bw, 1),
            "total_text_len_delta": lo["total_text_len"] - hancom["total_text_len"],
            "total_image_delta": lo["total_images"] - hancom["total_images"],
        },
        "per_page": per_page,
        "suggested_tolerances": {
            "bottom_white_tolerance_pt": int(math.ceil(max_bw)),
            "max_gap_scale": max_gap_scale,
            "page_count_drift_allowed": abs(pc_delta),
        },
    }


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def human_table(hancom, lo, deltas):
    """Build a human-readable calibration table (string)."""
    lines = []
    pc = deltas["page_count"]
    lines.append("Cross-renderer calibration (LibreOffice minus Hancom)")
    lines.append("=" * 60)
    lines.append(f"page_count   Hancom={pc['hancom']}  LO={pc['lo']}  delta={pc['delta']}")
    agg = deltas["aggregate"]
    lines.append(f"total_text   Hancom={hancom['total_text_len']}  "
                 f"LO={lo['total_text_len']}  delta={agg['total_text_len_delta']}")
    lines.append(f"total_images Hancom={hancom['total_images']}  "
                 f"LO={lo['total_images']}  delta={agg['total_image_delta']}")
    lines.append("")
    hdr = (f"{'pg':>3} {'text_delta':>10} {'bottom_pt_delta':>15} "
           f"{'gap_delta':>10} {'image_delta':>11}")
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for r in deltas["per_page"]:
        lines.append(
            f"{r['page']:>3} {r['text_len_delta']:>10} "
            f"{r['bottom_white_pt_delta']:>15} {r['max_gap_lines_delta']:>10} "
            f"{r['image_count_delta']:>11}")
    lines.append("")
    tol = deltas["suggested_tolerances"]
    lines.append("suggested tolerances:")
    lines.append(f"  bottom_white_tolerance_pt = {tol['bottom_white_tolerance_pt']}")
    lines.append(f"  max_gap_scale             = {tol['max_gap_scale']}")
    lines.append(f"  page_count_drift_allowed  = {tol['page_count_drift_allowed']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Calibrate Hancom COM and LibreOffice WSL rendering.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hwpx", required=True, help="input hwpx to render both ways")
    ap.add_argument("--out-dir", required=True, help="output dir for PDFs + JSON")
    ap.add_argument("--json", action="store_true",
                    help="emit calibration JSON to stdout instead of the human table")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if not wsl_soffice_available():
        sys.stderr.write(
            "capability-missing: WSL soffice not found. "
            "Provide LibreOffice soffice in WSL, then re-run. "
            "Nothing installed.\n")
        sys.exit(3)

    hwpx = Path(args.hwpx).resolve()
    if not hwpx.exists():
        sys.stderr.write(f"error: --hwpx not found: {hwpx}\n")
        sys.exit(2)
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Serial: Hancom COM first (single-instance), then LibreOffice.
    hancom_pdf = render_hancom(hwpx, out_dir / "hancom.pdf")
    lo_pdf = render_libreoffice(hwpx, out_dir / "lo")

    hancom_m = extract_metrics(hancom_pdf)
    lo_m = extract_metrics(lo_pdf)
    deltas = compute_deltas(hancom_m, lo_m)

    result = {
        "ok": True,
        "hwpx": str(hwpx),
        "hancom_pdf": str(hancom_pdf),
        "lo_pdf": str(lo_pdf),
        "hancom_metrics": hancom_m,
        "lo_metrics": lo_m,
        "deltas": deltas,
        "calibration": deltas["suggested_tolerances"],
    }
    (out_dir / "calibration.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        sys.stdout.buffer.write(
            json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
    else:
        sys.stdout.buffer.write(human_table(hancom_m, lo_m, deltas).encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
