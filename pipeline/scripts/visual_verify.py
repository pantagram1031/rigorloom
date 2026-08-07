# -*- coding: utf-8 -*-
"""visual_verify.py — the render->judge loop driver (deterministic half).

Renders an artifact's pages, runs every DETERMINISTIC backstop over them,
prepares the vision task the rubric describes, and consumes the vision
verdict when it is handed back. The script NEVER calls a model: it is the
half that must never be skippable, and the vision half is the half a model
performs against ``docs/research/visual-rubric.md``.

    # 1. machine half + vision task preparation
    python pipeline/scripts/visual_verify.py --artifact OUT.hwpx \
        --expectations exp.json --out visual_verdict.json
    #    -> exit 3, verdict "vision_pending", PNGs written, vision_required[]

    # 2. an agent reads the PNGs against the rubric, writes vision.json

    # 3. machine half + vision merge = acceptance
    python pipeline/scripts/visual_verify.py --artifact OUT.hwpx \
        --expectations exp.json --vision-verdict vision.json \
        --out visual_verdict.json
    #    -> exit 0 only when BOTH halves are clean

Exit codes: 0 = accepted, 2 = usage/config error, 3 = finding (including a
pending vision half). ``--deterministic-only`` caps the run at the machine
half; it can exit 0, but the verdict then says ``deterministic_pass`` and
``acceptance: false`` — it is a smoke check, never an acceptance.

Rendering rules (non-negotiable):
  * fitz at ``--dpi`` (default 130) for the page PNGs;
  * an ``.hwpx``/``.hwp`` artifact with no ``--pdf`` is converted through
    ``engine/scripts/com_backend.py convert`` — ONE serial subprocess, and
    never with ``--kill-stale`` (killing a live Hancom belongs to an operator,
    not to a verification loop);
  * no Hancom and no ``--pdf`` is a usage error, never a silent pass.

``--max-fix-attempts N`` semantics for callers: this script does not loop.
The loop lives in the skill/playbook, which re-runs the script after each
fix. Pass ``--attempt M --max-fix-attempts N`` and the verdict carries
``loop: {attempt, max_fix_attempts, exhausted}``; when ``M >= N`` and the run
is not accepted, a HARD ``loop_exhausted`` finding is added so the caller
escalates to a human instead of grinding.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent.parent
_ENGINE_SCRIPTS = _REPO_ROOT / "engine" / "scripts"
for _dir in (_SCRIPTS_DIR, _ENGINE_SCRIPTS):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from checker_base import (  # noqa: E402
    EXIT_HARD, EXIT_PASS, _utf8_stdio, emit_verdict, usage_error,
    verdict_skeleton,
)

SCHEMA = "rigorloom/visual-verdict/v1"
VISION_SCHEMA = "rigorloom/visual-vision-verdict/v1"
RUBRIC_POINTER = "docs/research/visual-rubric.md"

#: Closed class vocabulary — the rubric's §1 table. An agent-supplied finding
#: whose class is not in here is a usage error, not a finding.
RUBRIC_CLASSES = (
    "blank_render",
    "artifact_malformed",
    "imposition_mismatch",
    "page_budget_violation",
    "guide_text_visible",
    "empty_cell_expected_fill",
    "format_noncompliance",
    "overprint",
    "text_clipped",
    "alignment_drift",
    "orphan_widow",
    "figure_overlap",
)
VISION_SEVERITIES = ("hard", "warn")

#: Tolerances. Changed only by argument or expectations, never by editing.
DEFAULT_DPI = 130
BASE_PT_TOL = 0.6           # pt
LINE_SPACING_TOL_PCT = 15.0  # percentage points
MARGIN_TOL_MM = 3.0
OVERPRINT_RATIO_HINT = 0.02  # >=2% of text lines overlapping -> rank for vision
MM_PER_PT = 25.4 / 72.0

PRINT_METHOD_RE = re.compile(r'name="PrintMethod"\s+type="short">(\d+)<')
_HWPX_XML_MEMBERS = re.compile(r"^Contents/(section\d+|header)\.xml$")


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------

def finding(code, severity, *, cls=None, page=None, detector=None, **extra):
    """One merged finding. ``class`` is the rubric class (None for the
    script's own loop/plumbing codes, which are not agent vocabulary)."""
    item = {"code": code, "class": cls, "severity": severity}
    if page is not None:
        item["page"] = page
    if detector:
        item["detector"] = detector
    item.update(extra)
    return item


# --------------------------------------------------------------------------
# artifact-side deterministic checks (offline, no renderer)
# --------------------------------------------------------------------------

def xml_wellformedness(artifact):
    """T23: a malformed section/header member renders the whole document
    blank in Hancom. Parse every one before trusting any render.

    Returns (findings, checked_member_names). A non-zip or non-hwpx artifact
    is not a finding — it is simply out of this check's scope.
    """
    path = Path(artifact)
    if path.suffix.lower() != ".hwpx" or not path.is_file():
        return [], []
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return [finding("artifact_malformed", "hard",
                        cls="artifact_malformed",
                        detector="visual_verify.zip",
                        member=None, error=str(exc))], []
    out, checked = [], []
    with archive:
        for name in sorted(archive.namelist()):
            if not _HWPX_XML_MEMBERS.match(name):
                continue
            checked.append(name)
            try:
                ET.fromstring(archive.read(name))
            except (ET.ParseError, OSError, UnicodeDecodeError) as exc:
                out.append(finding(
                    "artifact_malformed", "hard", cls="artifact_malformed",
                    detector="visual_verify.xml_parse",
                    member=name, error=str(exc)))
    return out, checked


def stored_print_method(artifact):
    """The source's own ``PrintInfo/PrintMethod`` (W6.2 imposition mechanism).

    != 0 means Hancom's PDF export applies n-up print imposition, which is
    how a 4-page document became a 2-page landscape PDF (XC-1 §9.3). Returns
    None when the value cannot be read (not a zip, no settings.xml).
    """
    path = Path(artifact)
    if path.suffix.lower() != ".hwpx" or not path.is_file():
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            if "settings.xml" not in archive.namelist():
                return None
            match = PRINT_METHOD_RE.search(
                archive.read("settings.xml").decode("utf-8", "replace"))
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError):
        return None
    return int(match.group(1)) if match else None


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _import_fitz():
    try:
        import fitz  # noqa: PLC0415
    except ImportError:
        return None
    return fitz


def convert_to_pdf(artifact, out_pdf):
    """One serial ``com_backend.py convert`` call. Never ``--kill-stale``.

    Returns (pdf_path, conversion_json, error_message).
    """
    try:
        import render_probe  # noqa: PLC0415
        capable = bool(render_probe.probe()["capabilities"]["hancom_com"])
    except Exception:  # probe never raises, but never let it gate on a crash
        capable = False
    if not capable:
        return None, None, (
            "no --pdf supplied and Hancom COM is unavailable on this machine "
            "— render the artifact on the operator machine and pass "
            "--pdf <rendered.pdf>. (This is a usage error on purpose: a "
            "verification loop that cannot render must not report a pass.)")
    backend = _ENGINE_SCRIPTS / "com_backend.py"
    if not backend.is_file():
        return None, None, f"com_backend.py not found: {backend}"
    Path(out_pdf).parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(backend), "convert",
         "--file", str(artifact), "--to", str(out_pdf)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    payload = None
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except ValueError:
                payload = None
            break
    if proc.returncode != 0 or not Path(out_pdf).is_file():
        return None, payload, (
            f"com_backend convert failed (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '')[:500]}")
    return str(out_pdf), payload, None


def render_pages(fitz, pdf_path, png_dir, dpi):
    """Rasterize every page to ``png_dir/page_<n>.png`` and measure it."""
    png_dir = Path(png_dir)
    png_dir.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    records, pixmaps = [], []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            out = png_dir / f"page_{index:03d}.png"
            pixmap.save(str(out))
            pixmaps.append(pixmap)
            records.append(_measure_page(page, index, out, pixmap))
    return records, pixmaps


def _measure_page(page, index, png_path, pixmap):
    text_blocks, image_blocks, lines = 0, 0, []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") == 1:
            image_blocks += 1
            continue
        has_text = False
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", [])
                     if s.get("text", "").strip()]
            if not spans:
                continue
            has_text = True
            lines.append({
                "bbox": tuple(line["bbox"]),
                "size": max(s.get("size", 0.0) for s in spans),
                "text": "".join(s.get("text", "") for s in spans),
            })
        if has_text:
            text_blocks += 1
    text = page.get_text("text")
    sizes = sorted(ln["size"] for ln in lines if ln["size"])
    median_pt = sizes[len(sizes) // 2] if sizes else None
    pitches = []
    ordered = sorted(lines, key=lambda ln: ln["bbox"][1])
    for a, b in zip(ordered, ordered[1:]):
        delta = b["bbox"][1] - a["bbox"][1]
        if 0 < delta < 200:
            pitches.append(delta)
    pitches.sort()
    pitch = pitches[len(pitches) // 2] if pitches else None
    rect = page.rect
    content = None
    if lines:
        content = [
            round(min(ln["bbox"][0] for ln in lines), 1),
            round(min(ln["bbox"][1] for ln in lines), 1),
            round(max(ln["bbox"][2] for ln in lines), 1),
            round(max(ln["bbox"][3] for ln in lines), 1),
        ]
    return {
        "page": index,
        "png": str(png_path),
        "width_px": pixmap.width,
        "height_px": pixmap.height,
        "width_pt": round(rect.width, 1),
        "height_pt": round(rect.height, 1),
        "landscape": rect.width > rect.height,
        "text_len": len(text.strip()),
        "n_text_blocks": text_blocks,
        "n_image_blocks": image_blocks,
        "n_lines": len(lines),
        "median_pt": round(median_pt, 2) if median_pt else None,
        "line_pitch_pt": round(pitch, 2) if pitch else None,
        "content_bbox_pt": content,
        "glyph_overlap_ratio": _overlap_ratio(lines),
        "_text": text,
    }


def _overlap_ratio(lines):
    """Fraction of text lines whose bbox substantially overlaps another's.

    TARGETING ONLY. The rubric is explicit that this ratio false-positives on
    watermarks, underlines, sub/superscripts and equations, so it never emits
    a class — it only ranks a page into ``vision_required`` with reason
    ``overprint_suspected`` so the vision half looks there first (T24).
    """
    if len(lines) < 2:
        return 0.0
    boxes = [ln["bbox"] for ln in lines]
    hit = set()
    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            ox = min(a[2], b[2]) - max(a[0], b[0])
            oy = min(a[3], b[3]) - max(a[1], b[1])
            if ox <= 0 or oy <= 0:
                continue
            small = min((a[2] - a[0]) * (a[3] - a[1]),
                        (b[2] - b[0]) * (b[3] - b[1]))
            if small > 0 and (ox * oy) / small >= 0.30:
                hit.add(i)
                hit.add(j)
    return round(len(hit) / len(boxes), 4)


# --------------------------------------------------------------------------
# pixel diff
# --------------------------------------------------------------------------

def _baseline_pixmaps(fitz, baseline, dpi, count):
    """Baseline pages as pixmaps, from a PDF or a directory of page PNGs."""
    path = Path(baseline)
    if path.is_file() and path.suffix.lower() == ".pdf":
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        with fitz.open(str(path)) as doc:
            return [page.get_pixmap(matrix=matrix, alpha=False) for page in doc]
    if path.is_dir():
        images = sorted(p for p in path.iterdir()
                        if p.suffix.lower() in (".png", ".ppm", ".pnm"))
        return [fitz.Pixmap(str(p)) for p in images[:max(count, len(images))]]
    return None


def diff_regions(pix_a, pix_b, tile=8):
    """Changed-region bboxes (image pixels) between two pixmaps.

    Exact byte comparison per tile: both sides come from the same
    deterministic rasterizer, so there is no anti-aliasing noise to threshold
    away. ``None`` means the pages are not comparable (different geometry).
    """
    if (pix_a.width != pix_b.width or pix_a.height != pix_b.height
            or pix_a.n != pix_b.n):
        return None
    width, height, comps = pix_a.width, pix_a.height, pix_a.n
    sa, sb = pix_a.samples, pix_b.samples
    stride_a, stride_b = pix_a.stride, pix_b.stride
    cols = -(-width // tile)
    rows = -(-height // tile)
    grid = bytearray(cols * rows)
    row_bytes = width * comps
    for y in range(height):
        oa = y * stride_a
        ob = y * stride_b
        ra = sa[oa:oa + row_bytes]
        rb = sb[ob:ob + row_bytes]
        if ra == rb:
            continue
        base = (y // tile) * cols
        for gx in range(cols):
            if grid[base + gx]:
                continue
            x0 = gx * tile * comps
            x1 = min((gx + 1) * tile, width) * comps
            if ra[x0:x1] != rb[x0:x1]:
                grid[base + gx] = 1
    return _grid_bboxes(grid, cols, rows, tile, width, height)


def _grid_bboxes(grid, cols, rows, tile, width, height):
    """4-connected components of the changed-tile grid -> pixel bboxes."""
    seen = bytearray(cols * rows)
    out = []
    for start in range(cols * rows):
        if not grid[start] or seen[start]:
            continue
        queue = collections.deque([start])
        seen[start] = 1
        gx0 = gx1 = start % cols
        gy0 = gy1 = start // cols
        while queue:
            cell = queue.popleft()
            cx, cy = cell % cols, cell // cols
            gx0, gx1 = min(gx0, cx), max(gx1, cx)
            gy0, gy1 = min(gy0, cy), max(gy1, cy)
            for nx, ny in ((cx - 1, cy), (cx + 1, cy),
                           (cx, cy - 1), (cx, cy + 1)):
                if not (0 <= nx < cols and 0 <= ny < rows):
                    continue
                nxt = ny * cols + nx
                if grid[nxt] and not seen[nxt]:
                    seen[nxt] = 1
                    queue.append(nxt)
        out.append([gx0 * tile, gy0 * tile,
                    min((gx1 + 1) * tile, width),
                    min((gy1 + 1) * tile, height)])
    out.sort(key=lambda b: (b[1], b[0]))
    return out


# --------------------------------------------------------------------------
# layout_qa + checker delegates
# --------------------------------------------------------------------------

_LAYOUT_QA_MAP = {
    ("body_markers", "guide_remnant"): ("guide_text_visible", "hard"),
    ("figure_placement", "figure_overlap"): ("figure_overlap", "warn"),
    ("figure_placement", "caption_missing"): ("orphan_widow", "warn"),
    ("figure_placement", "figure_width"): ("alignment_drift", "warn"),
    ("line_spacing_uniformity", None): ("alignment_drift", "warn"),
    ("tables", "ragged"): ("alignment_drift", "warn"),
    ("tables", "header_cell_empty"): ("empty_cell_expected_fill", "warn"),
    ("tables", "table_too_wide"): ("alignment_drift", "warn"),
}


def run_layout_qa(pdf_path, guide_strings=None):
    """Run the engine's layout_qa and map what it finds onto rubric classes.

    Unmapped findings (citation markers, latex leaks, whitespace flags) are
    preserved verbatim under ``unmapped`` rather than stretched into a class
    they do not fit — see the rubric §4 rule.
    """
    try:
        import layout_qa  # noqa: PLC0415
    except ImportError as exc:
        return None, [], {"error": f"layout_qa unavailable: {exc}"}
    try:
        # PyMuPDF's table finder prints an advisory line to stdout; stdout is
        # this script's machine-readable verdict channel, so fence it off.
        with contextlib.redirect_stdout(sys.stderr):
            raw = layout_qa.analyze(str(pdf_path), guide_strings=guide_strings)
    except Exception as exc:  # a QA crash must not read as a pass
        return None, [finding("layout_qa_failed", "hard", cls=None,
                              detector="layout_qa", error=str(exc)[:400])], {}
    findings, unmapped = [], []
    for group, items in (raw.get("checks") or {}).items():
        for item in items:
            key = (group, item.get("kind"))
            mapped = _LAYOUT_QA_MAP.get(key) or _LAYOUT_QA_MAP.get((group, None))
            if not mapped:
                unmapped.append({"group": group, **item})
                continue
            cls, severity = mapped
            findings.append(finding(
                cls, severity, cls=cls, page=item.get("page"),
                detector=f"layout_qa.{group}",
                evidence={k: v for k, v in item.items() if k != "page"}))
    summary = {
        "page_count": raw.get("page_count"),
        "flagged_pages": raw.get("flagged_pages"),
        "pass": raw.get("pass"),
        "pages": raw.get("pages"),
        "unmapped": unmapped,
    }
    return raw, findings, summary


def _delegate(script, argv, label):
    proc = subprocess.run(
        [sys.executable, str(script), *argv],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    payload = None
    text = (proc.stdout or "").strip()
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
    return {
        "checker": label, "exit": proc.returncode,
        "verdict": (payload or {}).get("verdict"),
        "hard": (payload or {}).get("hard", []),
        "warn": (payload or {}).get("warn", []),
        "stderr": (proc.stderr or "")[:400] or None,
    }


# --------------------------------------------------------------------------
# expectation-driven deterministic checks
# --------------------------------------------------------------------------

def check_page_budget(expectations, page_count):
    budget = expectations.get("page_budget") or {}
    lo = budget.get("min")
    hi = budget.get("max", expectations.get("max_pages"))
    out = []
    if lo is not None and page_count < lo:
        out.append(finding(
            "page_budget_violation", "hard", cls="page_budget_violation",
            detector="visual_verify.page_budget",
            evidence={"pages": page_count, "min": lo}))
    if hi is not None and page_count > hi:
        out.append(finding(
            "page_budget_violation", "hard", cls="page_budget_violation",
            detector="visual_verify.page_budget",
            evidence={"pages": page_count, "max": hi}))
    return out


def check_blank(records, blank_pages):
    """T25 floor: a render with no text is not a render."""
    out = []
    total = sum(r["text_len"] for r in records)
    if not records:
        out.append(finding("blank_render", "hard", cls="blank_render",
                           detector="visual_verify.page_count",
                           evidence={"pages": 0}))
        return out
    if total == 0:
        out.append(finding(
            "blank_render", "hard", cls="blank_render",
            detector="visual_verify.text_length",
            evidence={"document_text_len": 0,
                      "note": "T25 render-honesty floor: zero extractable "
                              "text across the whole PDF"}))
        return out
    for rec in records:
        if rec["page"] in blank_pages:
            continue
        if rec["text_len"] == 0 and rec["n_image_blocks"] == 0:
            out.append(finding(
                "blank_render", "hard", cls="blank_render", page=rec["page"],
                detector="visual_verify.page_content",
                evidence={"text_len": 0, "image_blocks": 0}))
    return out


def check_imposition(records, print_method, pages_document, pages_pdf,
                     normalized):
    """The W6.2 mechanism, both legs."""
    out = []
    if print_method not in (None, 0) and not normalized:
        out.append(finding(
            "imposition_mismatch", "hard", cls="imposition_mismatch",
            detector="visual_verify.print_method",
            evidence={"stored_print_method": print_method,
                      "note": "source stores n-up print imposition; Hancom "
                              "SaveAs(PDF) honours it (XC-1 §9.3)"}))
    if pages_document and pages_pdf and pages_document != pages_pdf:
        out.append(finding(
            "imposition_mismatch", "hard", cls="imposition_mismatch",
            detector="visual_verify.page_parity",
            evidence={"pages_document": pages_document,
                      "pages_pdf": pages_pdf}))
    landscape = [r["page"] for r in records if r["landscape"]]
    if landscape and print_method not in (None, 0):
        out.append(finding(
            "imposition_mismatch", "warn", cls="imposition_mismatch",
            detector="visual_verify.orientation",
            evidence={"landscape_pages": landscape,
                      "stored_print_method": print_method}))
    return out


def check_format(records, expectations):
    out = []
    base_pt = expectations.get("base_pt")
    spacing = expectations.get("line_spacing_pct")
    margins = expectations.get("margins_mm") or {}
    for rec in records:
        if base_pt and rec["median_pt"]:
            if abs(rec["median_pt"] - base_pt) > BASE_PT_TOL:
                out.append(finding(
                    "format_noncompliance", "hard", cls="format_noncompliance",
                    page=rec["page"], detector="visual_verify.base_pt",
                    evidence={"measured_pt": rec["median_pt"],
                              "declared_pt": base_pt, "tol_pt": BASE_PT_TOL}))
        if spacing and rec["line_pitch_pt"] and rec["median_pt"]:
            measured = rec["line_pitch_pt"] / rec["median_pt"] * 100.0
            if abs(measured - spacing) > LINE_SPACING_TOL_PCT:
                out.append(finding(
                    "format_noncompliance", "hard", cls="format_noncompliance",
                    page=rec["page"], detector="visual_verify.line_spacing",
                    evidence={"measured_pct": round(measured, 1),
                              "declared_pct": spacing,
                              "tol_pct": LINE_SPACING_TOL_PCT}))
        if margins and rec["content_bbox_pt"]:
            x0, y0, x1, y1 = rec["content_bbox_pt"]
            actual = {
                "left": x0 * MM_PER_PT,
                "top": y0 * MM_PER_PT,
                "right": (rec["width_pt"] - x1) * MM_PER_PT,
                "bottom": (rec["height_pt"] - y1) * MM_PER_PT,
            }
            for side, declared in margins.items():
                if side not in actual or declared is None:
                    continue
                if actual[side] < declared - MARGIN_TOL_MM:
                    out.append(finding(
                        "format_noncompliance", "hard",
                        cls="format_noncompliance", page=rec["page"],
                        detector="visual_verify.margins",
                        evidence={"side": side,
                                  "measured_mm": round(actual[side], 1),
                                  "declared_mm": declared,
                                  "tol_mm": MARGIN_TOL_MM}))
    return out


def _norm(text):
    return re.sub(r"\s+", "", text or "")


def check_fill_map(records, expectations):
    """Declared fill values must be visible somewhere in the render."""
    fill_map = expectations.get("fill_map") or {}
    skip = set(expectations.get("intentionally_blank") or [])
    if not fill_map:
        return []
    haystack = _norm("".join(r["_text"] for r in records))
    out = []
    for label, value in sorted(fill_map.items()):
        if label in skip or value is None or str(value) == "":
            continue
        if _norm(str(value)) not in haystack:
            out.append(finding(
                "empty_cell_expected_fill", "hard",
                cls="empty_cell_expected_fill",
                detector="visual_verify.fill_map",
                evidence={"label": label,
                          "declared_value": str(value)[:80],
                          "note": "declared value not present in the render"}))
    return out


def check_forbidden_text(records, expectations):
    out = []
    for needle in expectations.get("forbidden_text") or []:
        target = _norm(needle)[:20]
        if not target:
            continue
        for rec in records:
            if target in _norm(rec["_text"]):
                out.append(finding(
                    "guide_text_visible", "hard", cls="guide_text_visible",
                    page=rec["page"],
                    detector="visual_verify.forbidden_text",
                    evidence={"text": needle[:80]}))
    return out


# --------------------------------------------------------------------------
# vision task + vision verdict
# --------------------------------------------------------------------------

def build_vision_task(records, det_findings, changed_pages, scope):
    """Which pages the vision half must read, and why.

    Default scope is ``all`` — the vision half is not skippable, and the
    classes it owns (overprint, clipping, alignment drift) can appear on a
    page with a perfectly clean machine half. ``--vision-scope targeted``
    narrows to pages with a deterministic finding, a suspected overprint, or
    a pixel-diff change; use it only when a baseline pins the rest.
    """
    flagged = {f["page"] for f in det_findings if f.get("page")}
    tasks = []
    for rec in records:
        reasons = []
        if rec["page"] in flagged:
            reasons.append("deterministic_finding")
        if rec["glyph_overlap_ratio"] >= OVERPRINT_RATIO_HINT:
            reasons.append("overprint_suspected")
        if rec["page"] in changed_pages:
            reasons.append("changed_vs_baseline")
        if scope == "all":
            reasons.append("full_sweep")
        if not reasons:
            continue
        tasks.append({
            "page": rec["page"],
            "png": rec["png"],
            "reasons": reasons,
            "overlap_ratio": rec["glyph_overlap_ratio"],
            "rubric": RUBRIC_POINTER,
        })
    priority = {"overprint_suspected": 0, "deterministic_finding": 1,
                "changed_vs_baseline": 2, "full_sweep": 3}
    tasks.sort(key=lambda t: (min(priority[r] for r in t["reasons"]),
                              t["page"]))
    return tasks


def load_vision_verdict(path, page_count):
    """Parse + validate an agent-supplied vision verdict.

    Returns (payload, findings, error). ``error`` is a usage error string —
    an unknown class is a usage error by contract, never a silent drop.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [], f"vision verdict unreadable: {exc}"
    if not isinstance(payload, dict):
        return None, [], "vision verdict must be a JSON object"
    schema = payload.get("schema", VISION_SCHEMA)
    if schema != VISION_SCHEMA:
        return None, [], (
            f"vision verdict schema {schema!r} != {VISION_SCHEMA!r}")
    raw = payload.get("findings", [])
    if not isinstance(raw, list):
        return None, [], "vision verdict 'findings' must be a list"
    reviewed = payload.get("pages_reviewed", [])
    if not isinstance(reviewed, list) or not all(
            isinstance(p, int) for p in reviewed):
        return None, [], "vision verdict 'pages_reviewed' must be a list of ints"
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, [], f"findings[{i}] must be an object"
        cls = item.get("class")
        if cls not in RUBRIC_CLASSES:
            return None, [], (
                f"findings[{i}] unknown rubric class {cls!r} — the vocabulary "
                f"is closed: {', '.join(RUBRIC_CLASSES)} "
                f"(see {RUBRIC_POINTER})")
        severity = item.get("severity", "hard")
        if severity not in VISION_SEVERITIES:
            return None, [], (
                f"findings[{i}] unknown severity {severity!r} — expected one "
                f"of {', '.join(VISION_SEVERITIES)}")
        page = item.get("page")
        if page is not None and not (isinstance(page, int)
                                     and 1 <= page <= page_count):
            return None, [], (
                f"findings[{i}] page {page!r} outside 1..{page_count}")
        out.append(finding(cls, severity, cls=cls, page=page,
                           detector="vision",
                           evidence=item.get("evidence")))
    return payload, out, None


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def verify(args):
    artifact = Path(args.artifact).expanduser()
    if not artifact.is_file():
        return usage_error(str(artifact), "visual_verify",
                           f"artifact not found: {artifact}")
    expectations = {}
    if args.expectations:
        try:
            expectations = json.loads(
                Path(args.expectations).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return usage_error(str(artifact), "visual_verify",
                               f"expectations unreadable: {exc}")
        if not isinstance(expectations, dict):
            return usage_error(str(artifact), "visual_verify",
                               "expectations must be a JSON object")

    fitz = _import_fitz()
    if fitz is None:
        return usage_error(str(artifact), "visual_verify",
                           "pymupdf (fitz) is required to render and measure "
                           "pages; install the 'engine' extra")

    hard, warn = [], []

    # -- artifact-side, before trusting any render ---------------------------
    xml_findings, xml_members = xml_wellformedness(artifact)
    hard.extend(xml_findings)
    print_method = stored_print_method(artifact)

    # -- obtain a PDF --------------------------------------------------------
    conversion = None
    if args.pdf:
        pdf_path = str(Path(args.pdf).expanduser())
        if not Path(pdf_path).is_file():
            return usage_error(str(artifact), "visual_verify",
                               f"--pdf not found: {pdf_path}")
    elif artifact.suffix.lower() == ".pdf":
        pdf_path = str(artifact)
    else:
        out_pdf = (Path(args.png_dir) if args.png_dir
                   else artifact.parent / "visual_verify") / (
            artifact.stem + ".pdf")
        pdf_path, conversion, error = convert_to_pdf(artifact, out_pdf)
        if error:
            return usage_error(str(artifact), "visual_verify", error)

    png_dir = Path(args.png_dir) if args.png_dir else (
        Path(pdf_path).parent / (Path(pdf_path).stem + "_pages"))
    try:
        records, pixmaps = render_pages(fitz, pdf_path, png_dir, args.dpi)
    except Exception as exc:
        return usage_error(str(artifact), "visual_verify",
                           f"failed to render {pdf_path}: {exc}")

    page_count = len(records)
    blank_pages = set(expectations.get("blank_pages") or [])

    # -- deterministic backstops --------------------------------------------
    det = check_blank(records, blank_pages)
    pages_document = (conversion or {}).get(
        "pages_document", expectations.get("pages_document"))
    pages_pdf = (conversion or {}).get("pages_pdf", page_count)
    det += check_imposition(
        records, print_method, pages_document, pages_pdf,
        normalized=bool((conversion or {}).get("print_method_normalized")))
    det += check_page_budget(expectations, page_count)
    det += check_format(records, expectations)
    det += check_fill_map(records, expectations)
    det += check_forbidden_text(records, expectations)

    guide_strings = expectations.get("forbidden_text") or None
    layout_raw, layout_findings, layout_summary = run_layout_qa(
        pdf_path, guide_strings=guide_strings)
    det += layout_findings

    delegates = []
    if args.form_profile:
        delegates.append(_delegate(
            _SCRIPTS_DIR / "check_residue.py",
            ["--form-profile", str(args.form_profile),
             "--artifact", str(artifact)], "check_residue"))
    if args.content:
        delegates.append(_delegate(
            _SCRIPTS_DIR / "check_density.py",
            [str(Path(args.content).parent.parent), "--content",
             str(args.content)], "check_density"))
    for result in delegates:
        if result["exit"] == 3:
            det.append(finding(
                f"{result['checker']}_hard", "hard", cls=None,
                detector=result["checker"],
                evidence=result["hard"][:10]))
        elif result["exit"] not in (0, 3):
            det.append(finding(
                f"{result['checker']}_error", "hard", cls=None,
                detector=result["checker"],
                evidence={"exit": result["exit"], "stderr": result["stderr"]}))
        for item in result["warn"][:10]:
            warn.append(finding(f"{result['checker']}_warn", "warn", cls=None,
                                detector=result["checker"], evidence=item))

    # -- pixel diff ----------------------------------------------------------
    changed_pages = set()
    baseline_report = None
    if args.baseline:
        base_pix = _baseline_pixmaps(fitz, args.baseline, args.dpi, page_count)
        if base_pix is None:
            return usage_error(str(artifact), "visual_verify",
                               f"--baseline is neither a PDF nor a directory "
                               f"of page images: {args.baseline}")
        baseline_report = {"baseline": str(args.baseline),
                           "baseline_pages": len(base_pix), "pages": []}
        if len(base_pix) != page_count:
            warn.append(finding(
                "baseline_page_count_differs", "warn", cls=None,
                detector="visual_verify.pixel_diff",
                evidence={"baseline_pages": len(base_pix),
                          "pages": page_count}))
        for index, pixmap in enumerate(pixmaps, start=1):
            if index > len(base_pix):
                changed_pages.add(index)
                baseline_report["pages"].append(
                    {"page": index, "comparable": False,
                     "changed_regions": None, "note": "no baseline page"})
                continue
            regions = diff_regions(base_pix[index - 1], pixmap)
            if regions is None:
                changed_pages.add(index)
                baseline_report["pages"].append(
                    {"page": index, "comparable": False,
                     "changed_regions": None,
                     "note": "page geometry differs from baseline"})
                continue
            if regions:
                changed_pages.add(index)
            baseline_report["pages"].append(
                {"page": index, "comparable": True,
                 "changed_regions": regions})

    for item in det:
        (hard if item["severity"] == "hard" else warn).append(item)

    # -- vision half ---------------------------------------------------------
    vision_required = build_vision_task(records, det, changed_pages,
                                        args.vision_scope)
    vision = {"supplied": False, "pages_reviewed": [],
              "rubric": RUBRIC_POINTER}
    if args.vision_verdict:
        payload, vision_findings, error = load_vision_verdict(
            args.vision_verdict, page_count)
        if error:
            return usage_error(str(artifact), "visual_verify", error)
        reviewed = sorted(set(payload.get("pages_reviewed", [])))
        vision.update(supplied=True, pages_reviewed=reviewed,
                      source=str(args.vision_verdict))
        missing = sorted({t["page"] for t in vision_required} - set(reviewed))
        if missing:
            hard.append(finding(
                "vision_incomplete", "hard", cls=None, detector="visual_verify",
                evidence={"unreviewed_pages": missing,
                          "note": "the vision half is not skippable"}))
        for item in vision_findings:
            (hard if item["severity"] == "hard" else warn).append(item)

    # -- verdict -------------------------------------------------------------
    loop = {"attempt": args.attempt, "max_fix_attempts": args.max_fix_attempts,
            "exhausted": False}
    if hard:
        state = "fail"
    elif args.deterministic_only:
        state = "deterministic_pass"
    elif not vision["supplied"] and vision_required:
        state = "vision_pending"
    else:
        state = "pass"
    if (args.max_fix_attempts is not None and state != "pass"
            and args.attempt is not None
            and args.attempt >= args.max_fix_attempts):
        loop["exhausted"] = True
        hard.append(finding(
            "loop_exhausted", "hard", cls=None, detector="visual_verify",
            evidence={"attempt": args.attempt,
                      "max_fix_attempts": args.max_fix_attempts,
                      "note": "escalate to a human; do not keep retrying"}))
        state = "fail"

    accepted = state == "pass"
    code = EXIT_PASS if state in ("pass", "deterministic_pass") else EXIT_HARD

    verdict = verdict_skeleton(
        str(artifact), "visual_verify", hard=hard, warn=warn,
        ok=(code == EXIT_PASS), verdict=state,
        extra={
            "schema": SCHEMA,
            "artifact": str(artifact),
            "pdf": str(pdf_path),
            "dpi": args.dpi,
            "png_dir": str(png_dir),
            "rubric": RUBRIC_POINTER,
            "acceptance": accepted,
            "pages": [{k: v for k, v in r.items() if k != "_text"}
                      for r in records],
            "deterministic": {
                "xml_members_parsed": xml_members,
                "stored_print_method": print_method,
                "pages_document": pages_document,
                "pages_pdf": pages_pdf,
                "conversion": conversion,
                "layout_qa": layout_summary,
                "delegates": delegates,
                "baseline_diff": baseline_report,
                "skipped": _skipped(expectations, pages_document, layout_raw),
            },
            "vision": vision,
            "vision_required": vision_required,
            "loop": loop,
        })
    return verdict, code


def _skipped(expectations, pages_document, layout_raw):
    """What the machine half could NOT check, stated out loud."""
    out = []
    if pages_document is None:
        out.append("page_parity: pages_document unknown (no conversion JSON "
                   "and no expectations.pages_document)")
    if not expectations.get("base_pt"):
        out.append("format_noncompliance/base_pt: not declared")
    if not expectations.get("line_spacing_pct"):
        out.append("format_noncompliance/line_spacing: not declared")
    if not expectations.get("margins_mm"):
        out.append("format_noncompliance/margins: not declared")
    if not expectations.get("fill_map"):
        out.append("empty_cell_expected_fill: no fill_map declared")
    if not (expectations.get("page_budget") or expectations.get("max_pages")):
        out.append("page_budget_violation: no budget declared")
    if layout_raw is None:
        out.append("layout_qa: unavailable")
    return out


def main(argv=None):
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="render->judge loop driver: deterministic backstops + "
                    "vision task preparation for docs/research/visual-rubric.md")
    parser.add_argument("--artifact", required=True,
                        help=".hwpx/.hwp artifact, or a .pdf to judge directly")
    parser.add_argument("--pdf", default=None,
                        help="already-rendered PDF (skips conversion)")
    parser.add_argument("--expectations", default=None,
                        help="JSON: pages_document, page_budget{min,max}/"
                             "max_pages, base_pt, line_spacing_pct, "
                             "margins_mm{top,bottom,left,right}, fill_map, "
                             "intentionally_blank, blank_pages, forbidden_text")
    parser.add_argument("--png-dir", default=None,
                        help="where page PNGs are written "
                             "(default: <pdf>_pages/ next to the PDF)")
    parser.add_argument("--dpi", type=float, default=DEFAULT_DPI,
                        help=f"page raster dpi (default {DEFAULT_DPI})")
    parser.add_argument("--baseline", default=None,
                        help="pixel-diff baseline: a PDF or a directory of "
                             "page images; reports changed-region bboxes so a "
                             "caller can assert unchanged regions stayed so")
    parser.add_argument("--form-profile", default=None,
                        help="form_profile.json -> also run check_residue")
    parser.add_argument("--content", default=None,
                        help="bundle/content.md -> also run check_density")
    parser.add_argument("--vision-verdict", default=None,
                        help="agent-supplied per-page findings to merge; "
                             "classes are validated against the rubric "
                             "vocabulary (unknown class = usage error)")
    parser.add_argument("--vision-scope", choices=("all", "targeted"),
                        default="all",
                        help="which pages the vision half must read "
                             "(default all — the vision half is not skippable)")
    parser.add_argument("--deterministic-only", action="store_true",
                        help="cap the run at the machine half; can exit 0 but "
                             "the verdict says acceptance:false")
    parser.add_argument("--attempt", type=int, default=None,
                        help="1-based fix-loop attempt number (caller-tracked)")
    parser.add_argument("--max-fix-attempts", type=int, default=None,
                        help="escalate instead of retrying once attempt >= N")
    parser.add_argument("--out", default=None, help="write verdict JSON here")
    args = parser.parse_args(argv)

    try:
        verdict, code = verify(args)
    except Exception as exc:  # a crash must never read as a pass
        verdict, code = usage_error(
            str(args.artifact), "visual_verify",
            f"visual_verify crashed: {type(exc).__name__}: {exc}")
    return emit_verdict(verdict, code, args.out, create_parent=True)


if __name__ == "__main__":
    raise SystemExit(main())
