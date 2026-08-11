# -*- coding: utf-8 -*-
"""visual_verify.py — the render->judge loop driver (deterministic half).

Renders an artifact's pages, runs every DETERMINISTIC backstop over them,
prepares the vision task the rubric describes, and consumes the vision
verdict when it is handed back. The script NEVER calls a model: it is the
half that must never be skippable, and the vision half is the half a model
performs against ``skill/references/visual-rubric.md``.

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

Exit codes — the WHOLE table, one row per terminal state, and nothing else
is reachable (``test_exit_code_matrix`` pins every row, including that no
invocation ever exits 1):

    verdict                exit  meaning
    pass                    0    accepted: both halves clean, every SAFETY
                                 check ran (or was explicitly waived)
    deterministic_pass      0    --deterministic-only smoke check;
                                 acceptance: false by construction
    vision_pending          3    machine half clean, vision half still owed
    fail                    3    a HARD finding (deterministic or vision)
    safety_incomplete       3    nothing failed, but a SAFETY check never RAN
                                 and was not waived — see SAFETY_CHECKS
    usage_error             2    bad input, unreadable file, unwritable --out

``--deterministic-only`` caps the run at the machine half; it can exit 0, but
the verdict then says ``deterministic_pass`` and ``acceptance: false`` — it is
a smoke check, never an acceptance.

ACCEPTANCE IS NOT "NOTHING FAILED". ``acceptance: true`` claims that every
check in ``SAFETY_CHECKS`` actually RAN. A run that could not run one of them
(no fill map, no form profile, no page-count source, a non-hwpx artifact)
reports ``safety_incomplete`` and exits 3 instead of quietly accepting; the
only way past it is ``--accept-without CHECK``, which is recorded in the
verdict as ``acceptance_waivers`` so a waiver is auditable and never implicit.

The closed ``expectations.operation_scope: "story_edit"`` contract is a
two-pass render path for the current `.hwpx`/PDF pair. It requires explicit
PDF/baseline/hash-bound conversion inputs plus non-empty per-page
``required_text`` and full-string ``forbidden_text`` lists. Its fill-only
checks are audited under ``deterministic.not_applicable_checks`` (never as
waivers); XML/page parity, baseline comparability, and all-page vision remain
mandatory. The structural story-edit receipt has no hashes and is not used as
artifact evidence.

Rendering rules (non-negotiable):
  * fitz at ``--dpi`` (default 130) for the page PNGs;
  * an ``.hwpx``/``.hwp`` artifact with no ``--pdf`` is converted through
    ``engine/scripts/com_backend.py convert`` — ONE serial subprocess, and
    never with ``--kill-stale`` (killing a live Hancom belongs to an operator,
    not to a verification loop);
  * no Hancom and no ``--pdf`` is a usage error, never a silent pass;
  * a PDF converted by an EARLIER step carries its provenance in a
    ``<pdf>.conversion.json`` sidecar (``--conversion-record`` to name it
    elsewhere), which is how print-method normalisation performed by
    ``com_backend.py convert`` survives the step boundary. The record is
    believed only when its ``source_sha256``/``pdf_sha256`` match the files
    actually under verification; a mismatch is a usage error. With no record
    the imposition HARD stands unchanged (T38);
  * ``--baseline`` names the BLANK FORM, so it takes one: an ``.hwpx``/``.hwp``
    baseline goes through the SAME serial conversion, and with no renderer the
    pixel diff is a skip-with-reason (``deterministic.skipped``) rather than a
    failure — losing one check, not the run (T35). An ``.hwpx`` baseline is
    read a SECOND way, offline and with no renderer needed: the T30 charPr
    post-flight compares each filled seat against the same seat in the blank
    form, so a signature the printed form always had is a named WARN instead
    of a HARD blaming the fill for the form's own typography (T40).

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
import hashlib
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

import charpr_script  # noqa: E402  (engine/scripts — shared T30 vocabulary)
import check_residue  # noqa: E402
import preedit  # noqa: E402  (T39 fill-value paragraph semantics)
from checker_base import (  # noqa: E402
    EXIT_HARD, EXIT_PASS, _utf8_stdio, dump_json, emit_verdict, usage_error,
    verdict_skeleton,
)

SCHEMA = "rigorloom/visual-verdict/v1"
VISION_SCHEMA = "rigorloom/visual-vision-verdict/v1"
#: The rubric ships INSIDE the skill surface (v0.17: it was in docs/research/
#: and therefore in no bundle at all — the mandatory vision half arrived
#: undocumented). In an installed skill the same file is ``references/
#: visual-rubric.md`` relative to the skill root; ``resolve_rubric`` finds
#: whichever spelling exists so the verdict can carry a real path.
RUBRIC_POINTER = "skill/references/visual-rubric.md"
RUBRIC_CANDIDATES = (
    _REPO_ROOT / "skill" / "references" / "visual-rubric.md",
    _REPO_ROOT / "references" / "visual-rubric.md",
)


def resolve_rubric():
    """Absolute path of the shipped rubric, or None if this tree lacks it."""
    for candidate in RUBRIC_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return None

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
    "missing_glyphs",
    "overprint",
    "text_clipped",
    "alignment_drift",
    "orphan_widow",
    "figure_overlap",
)
VISION_SEVERITIES = ("hard", "warn")
# The rubric fixes this class at HARD: a vision agent may corroborate the
# deterministic Hangul checker, but it cannot downgrade a missing-glyph defect
# to a warning and still leave the render eligible for acceptance.
VISION_HARD_CLASSES = frozenset({"missing_glyphs"})

#: THE SAFETY SET — deterministic checks whose ABSENCE invalidates acceptance,
#: named by the exact key each one reports itself under in
#: ``deterministic.skipped`` (and, for four of the five, the exact finding code
#: the detector emits). ONE place: the waiver vocabulary, the skip bookkeeping
#: and the acceptance rule all read this tuple, so they cannot drift.
#:
#: The v0.17 clean-room run is why this exists: the luna tier supplied a CLI
#: ``--fill-map``, got ``empty_cell_expected_fill``, ``fill_charpr_script_
#: mismatch`` AND ``page_parity`` into ``skipped[]``, and still received
#: ``acceptance: true`` with exit 0 — a verdict claiming more than it checked,
#: which is worse than a missing feature.
#:
#: What is NOT in here, on purpose: ``baseline_pixel_diff`` (T35 decided a
#: machine with no renderer loses ONE check, not the run) and the
#: ``format_noncompliance/*`` legs, which are per-tolerance declarations rather
#: than defect detectors — a caller who declares no ``base_pt`` is not hiding a
#: defect class, they are declining to pin a tolerance.
SAFETY_CHECKS = (
    "page_parity",
    "xml_wellformedness",
    "check_residue",
    "empty_cell_expected_fill",
    "fill_charpr_script_mismatch",
)

# ``story_edit.py`` deliberately publishes a structural receipt with no
# artifact hashes.  It therefore cannot bind a later render, but a caller can
# still ask this verifier to judge the current artifact/PDF with the narrower
# story-edit expectations below.  Keep this vocabulary closed: an unknown
# scope must never silently inherit ordinary form-fill semantics.
STORY_OPERATION_SCOPE = "story_edit"
_OPERATION_SCOPES = frozenset({STORY_OPERATION_SCOPE})
_MAX_REQUIRED_TEXT_CHARS = 4096

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


def derive_pages_document(artifact):
    """The document's own page count, read OFFLINE from its layout cache.

    Page parity (the second leg of the W6.2 imposition mechanism) used to need
    ``conversion["pages_document"]`` — Hancom's ``hwp.PageCount``, which only
    exists when THIS script did the conversion. On the ``--pdf`` path there was
    no source at all, so parity skipped by default and the v0.17 clean-room sol
    tier had to hand-declare ``expectations.pages_document`` to get it back. A
    safety check that requires the caller to remember a number is a safety
    check that does not run.

    So derive it from the artifact, which already records Hancom's last layout:
    every laid-out line carries ``<hp:lineseg vertpos=...>``, a HWPUNIT offset
    from the TOP OF ITS PAGE, so page boundaries are exactly the points where
    ``vertpos`` stops increasing. Linesegs inside a table cell
    (``hp:tc``/``hp:subList``) are cell-relative and must be excluded — counting
    them turns a 1-page form into 216 pages (measured on
    ``saeopja-deungnok-sinchengseo``).

    Returns ``(pages, note)``. ``pages`` is None when the artifact carries no
    readable layout cache at all (not an .hwpx, or an XML-engine output whose
    sections have no ``linesegarray``), and ``note`` then says which.

    ACCURACY, measured against the ten rendered corpus forms: 5/10 exact, and
    every disagreement is an UNDER-count (a form whose body lives entirely
    inside tables caches no top-level linesegs) except ``nrf-gyeolgwa-bogoseo-
    yangsik``, which derives 4 against a 2-page PDF — and that one is the real
    W6.2 incident (``PrintMethod=4``). Hence the directional rule in
    ``check_imposition``: n-up imposition can only FOLD pages, so
    ``pages_pdf < pages_document`` is HARD while the under-count direction is a
    WARN naming both explanations. See ``check_imposition``.
    """
    path = Path(artifact)
    if path.suffix.lower() != ".hwpx" or not path.is_file():
        return None, ("page_parity: pages_document could not be derived — "
                      f"{path.suffix or 'the artifact'} carries no hwpx layout "
                      "cache")
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(n for n in archive.namelist()
                           if re.match(r"Contents/section\d+\.xml$", n))
            if not names:
                return None, ("page_parity: pages_document could not be "
                              "derived — the artifact has no Contents/"
                              "section*.xml member")
            total, seen_any = 0, False
            for name in names:
                positions = _section_lineseg_vertpos(archive.read(name))
                if not positions:
                    continue
                seen_any = True
                pages, previous = 1, None
                for vertpos in positions:
                    if previous is not None and vertpos < previous:
                        pages += 1
                    previous = vertpos
                total += pages
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        return None, ("page_parity: pages_document could not be derived — the "
                      "artifact's sections are not readable (see "
                      "artifact_malformed)")
    if not seen_any:
        return None, ("page_parity: pages_document could not be derived — no "
                      "top-level <hp:lineseg> in any section, so this artifact "
                      "carries no layout cache to count pages from")
    return total, None


def _section_lineseg_vertpos(xml_bytes):
    """``vertpos`` of every lineseg OUTSIDE a table cell, in document order."""
    out = []

    def walk(node, in_cell):
        for child in node:
            if not isinstance(child.tag, str):
                continue
            name = _localname(child.tag)
            if name in ("tc", "subList"):
                walk(child, True)
                continue
            if name == "lineseg" and not in_cell:
                raw = child.get("vertpos")
                if raw is not None:
                    try:
                        out.append(int(raw))
                    except ValueError:
                        pass
            walk(child, in_cell)

    walk(ET.fromstring(xml_bytes), False)
    return out


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _import_fitz():
    try:
        import fitz  # noqa: PLC0415
    except ImportError:
        return None
    return fitz


def render_capable():
    """Whether this machine can convert a Hancom document to PDF at all."""
    try:
        import render_probe  # noqa: PLC0415
        return bool(render_probe.probe()["capabilities"]["hancom_com"])
    except Exception:  # probe never raises, but never let it gate on a crash
        return False


def convert_to_pdf(artifact, out_pdf):
    """One serial ``com_backend.py convert`` call. Never ``--kill-stale``.

    Returns (pdf_path, conversion_json, error_message).
    """
    if not render_capable():
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


# ---------------------------------------------------------------------------
# Conversion provenance across a step boundary (T38)
# ---------------------------------------------------------------------------

CONVERSION_RECORD_SCHEMA = "rigorloom/conversion-record/v1"
#: WIRE CONTRACT with ``com_backend.py`` — it writes this sidecar, this script
#: reads it. Both constants are asserted equal by the test suite rather than
#: imported, so that visual_verify never takes an import-time dependency on
#: the COM backend (which must stay optional on non-Hancom machines).
CONVERSION_RECORD_SUFFIX = ".conversion.json"


def conversion_record_path(pdf_path):
    """Where ``com_backend.py convert`` leaves the sidecar for ``pdf_path``."""
    return Path(str(pdf_path) + CONVERSION_RECORD_SUFFIX)


def sha256_file(path, _chunk=1024 * 1024):
    digest = hashlib.sha256()
    try:
        with open(str(path), "rb") as handle:
            while True:
                block = handle.read(_chunk)
                if not block:
                    break
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def load_conversion_record(record_path, artifact, pdf_path):
    """Rebuild the ``conversion`` dict from a record written by an EARLIER step.

    Why this exists. ``check_imposition``'s print_method leg HARDs when the
    source stores a non-zero ``PrintMethod`` and nothing says the imposition
    was neutralised. ``com_backend.py convert`` DOES neutralise it — but the
    canonical recipe converts in one process and verifies in another, so the
    proof died at the step boundary and this script, seeing nothing, could not
    tell "the normalisation did not happen" from "nobody told me it happened".
    It correctly assumed the worse of the two. This function is the telling.

    It is plumbing, NOT a relaxation. The record only counts when it is bound
    to the exact bytes under verification: ``source_sha256`` must match the
    ``--artifact`` being checked and ``pdf_sha256`` must match the ``--pdf``
    being rendered. Anything else — wrong file, edited artifact, regenerated
    PDF, hand-written claim — is a usage error, never a quiet accept. With no
    record at all the HARD stands exactly as before.

    Returns ``(conversion_dict, error_message)``; exactly one is None.
    """
    record_path = Path(record_path)
    if not record_path.is_file():
        return None, f"--conversion-record not found: {record_path}"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"unreadable conversion record {record_path}: {exc}"
    if not isinstance(record, dict):
        return None, (f"conversion record {record_path} is not a JSON object")
    schema = record.get("schema")
    if schema != CONVERSION_RECORD_SCHEMA:
        return None, (
            f"conversion record {record_path} has schema {schema!r}, "
            f"expected {CONVERSION_RECORD_SCHEMA!r}")

    # -- the binding. A provenance claim that can be pointed at the wrong PDF
    #    is worse than no claim, so both ends are checked before anything in
    #    the record is believed.
    for label, claimed, actual_path in (
            ("source", record.get("source_sha256"), artifact),
            ("pdf", record.get("pdf_sha256"), pdf_path)):
        actual = sha256_file(actual_path)
        if not claimed:
            return None, (
                f"conversion record {record_path} carries no {label}_sha256; "
                "an unbound conversion record is not evidence")
        if actual is None:
            return None, (
                f"cannot hash {label} {actual_path} to check the conversion "
                f"record {record_path}")
        if claimed != actual:
            return None, (
                f"conversion record {record_path} describes a different "
                f"{label}: record says {label}_sha256={claimed[:16]}… but "
                f"{actual_path} hashes to {actual[:16]}…. Re-run "
                "`com_backend.py convert` on the artifact you are verifying "
                "— a stale record is a claim about bytes that no longer exist.")

    conversion = {
        "print_method_normalized": record.get("print_method_normalized"),
        "pages_document": record.get("pages_document"),
        "pages_pdf": record.get("pages_pdf"),
        "source_print_method": record.get("source_print_method"),
        "provenance": "conversion_record",
        "record": str(record_path),
        "record_created_utc": record.get("created_utc"),
    }
    return conversion, None


def validate_story_conversion(conversion, artifact, page_count, print_method):
    """Validate the additional current-render contract for story scope.

    ``load_conversion_record`` already performs the byte binding.  This
    second, scope-specific check closes the page-count fields and source
    print-method fact so a hand-written or stale-but-hash-matching sidecar
    cannot make a story render look eligible.
    """
    if not isinstance(conversion, dict):
        return "story_edit operation_scope requires a hash-bound conversion record"
    values = {}
    for key in ("pages_document", "pages_pdf"):
        value = conversion.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return (
                f"story_edit conversion record {key} must be a positive integer")
        values[key] = value
    if values["pages_pdf"] != page_count:
        return (
            "story_edit conversion record pages_pdf does not match the current "
            f"rendered PDF page count ({values['pages_pdf']} != {page_count})")
    source_print_method = conversion.get("source_print_method")
    if (source_print_method is not None
            and (isinstance(source_print_method, bool)
                 or not isinstance(source_print_method, int)
                 or source_print_method < 0)):
        return "story_edit conversion record source_print_method is invalid"
    if source_print_method != print_method:
        return (
            "story_edit conversion record source_print_method does not match "
            "the current HWPX")
    normalized = conversion.get("print_method_normalized")
    if print_method in (None, 0):
        if normalized is not None:
            return (
                "story_edit conversion record print_method_normalized must be "
                "null when the stored PrintMethod is zero or unavailable")
    elif normalized != {"from": print_method, "to": 0}:
        return (
            "story_edit conversion record print_method_normalized must be "
            "{from: stored PrintMethod, to: 0}")
    return None


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

#: Document suffixes ``--baseline`` converts itself rather than refusing.
BASELINE_DOC_SUFFIXES = (".hwpx", ".hwp")
#: One sentence naming everything ``--baseline`` accepts, for the usage string
#: and for every error message about the flag (T35 nit (b)).
BASELINE_SOURCES = (
    "--baseline accepts the BLANK FORM itself (.hwpx/.hwp — converted here, "
    "serially, on a render-capable machine), an already-rendered .pdf, or a "
    "directory of page images (.png/.ppm/.pnm)")


def resolve_baseline(baseline, out_dir):
    """Turn a ``--baseline`` argument into something ``_baseline_pixmaps`` reads.

    The flag NAMES the blank form, so it must take one: an ``.hwpx``/``.hwp``
    baseline goes through the very conversion path the artifact already takes
    (one serial ``com_backend.py convert``, never ``--kill-stale``). A PDF or an
    image directory is passed through untouched.

    Returns ``(path, conversion_json, skip_reason, error)``. ``skip_reason`` is
    set — and ``error`` is not — when the baseline is a document and this machine
    has no renderer: the pixel diff is then reported as skipped-with-reason, so
    an unrenderable machine loses one check instead of the whole run.
    """
    path = Path(baseline).expanduser()
    if not path.exists():
        return None, None, None, f"--baseline not found: {baseline}. " \
                                 f"{BASELINE_SOURCES}"
    if path.is_file() and path.suffix.lower() in BASELINE_DOC_SUFFIXES:
        if not render_capable():
            return None, None, (
                "baseline_pixel_diff: --baseline is a document "
                f"({path.suffix}) and Hancom COM is unavailable on this "
                "machine, so it could not be rendered for comparison — "
                "re-run on the operator machine, or pass the blank form's "
                "already-rendered PDF as --baseline"), None
        out_pdf = Path(out_dir) / f"{path.stem}_baseline.pdf"
        pdf_path, conversion, error = convert_to_pdf(path, out_pdf)
        if error:
            return None, conversion, None, f"--baseline conversion failed: {error}"
        return Path(pdf_path), conversion, None, None
    return path, None, None, None


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


#: Tri-state attribution for a finding whose property the BLANK FORM may
#: already carry (T100). Closed on purpose: one field with a bool and a string
#: in it is the T35 shape this line has already paid for once.
INHERITED_YES = "yes"
INHERITED_NO = "no"
INHERITED_UNKNOWN = "unknown"


def _baseline_format_records(fitz, baseline, dpi):
    """Measured page records for the blank form, or ``None``.

    Reuses ``_measure_page`` so the baseline is measured by exactly the code
    that measures the artifact — a second measurement path would be a second
    thing to keep in agreement.

    Only a PDF baseline can support this. A directory of page images has no
    text layer, so point size, line pitch and content bbox are not recoverable
    from it; that case returns ``None`` and the caller reports attribution as
    ``unknown`` rather than guessing. ``png_path`` is ``None`` because these
    records exist to be measured, never to be shown.
    """
    path = Path(baseline)
    if not (path.is_file() and path.suffix.lower() == ".pdf"):
        return None
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    try:
        with fitz.open(str(path)) as doc:
            return [_measure_page(page, index,
                                  None, page.get_pixmap(matrix=matrix,
                                                        alpha=False))
                    for index, page in enumerate(doc, start=1)]
    except (RuntimeError, ValueError, OSError):
        return None


def _attribute(baseline_records, page, predicate):
    """Was this finding's property already true of the blank form?

    ``predicate`` receives the baseline record for the same page number and
    answers whether the blank form violates the same declaration. Returns
    ``(state, reason)`` where ``state`` is one of the ``INHERITED_*`` tokens.

    Attribution NEVER changes a severity here. The declaration is still
    violated by the document as submitted, so the finding stands; what changes
    is what the operator should do about it, because a violation the blank form
    already carries cannot be fixed by editing the fill.
    """
    if baseline_records is None:
        return INHERITED_UNKNOWN, ("no measurable blank-form baseline in this "
                                   "run: pass the blank form as --baseline "
                                   "(.hwpx/.hwp/.pdf) to attribute this")
    match = next((r for r in baseline_records if r["page"] == page), None)
    if match is None:
        return INHERITED_UNKNOWN, ("the blank form has no page %s to compare "
                                   "against" % page)
    try:
        return (INHERITED_YES if predicate(match) else INHERITED_NO), None
    except (KeyError, TypeError, ZeroDivisionError):
        return INHERITED_UNKNOWN, "the blank-form page could not be measured"


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


def run_layout_qa(pdf_path, guide_strings=None, declared_blank=()):
    """Run the engine's layout_qa and map what it finds onto rubric classes.

    Unmapped findings (citation markers, latex leaks, whitespace flags) are
    preserved verbatim under ``unmapped`` rather than stretched into a class
    they do not fit — see the rubric §4 rule.

    ``header_cell_empty`` gets a policy rather than a straight mapping: a
    blank the GRID owns (a separator band, a matrix stub head) and a blank the
    CALLER declared are both correct, and a warning every correct run emits is
    a warning nobody reads. Both are suppressed *on the record* — the summary
    carries ``empty_cell_suppressed`` with the reason and the label — and what
    survives is named by its label instead of a y coordinate.
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
    findings, unmapped, suppressed = [], [], []
    for group, items in (raw.get("checks") or {}).items():
        for item in items:
            key = (group, item.get("kind"))
            mapped = _LAYOUT_QA_MAP.get(key) or _LAYOUT_QA_MAP.get((group, None))
            if not mapped:
                unmapped.append({"group": group, **item})
                continue
            cls, severity = mapped
            evidence = {k: v for k, v in item.items() if k != "page"}
            if key == ("tables", "header_cell_empty"):
                reason, label = resolve_header_cell_empty(
                    item, declared_blank or ())
                if reason:
                    suppressed.append({"reason": reason, "label": label,
                                       "at_y": item.get("at_y"),
                                       "page": item.get("page")})
                    continue
                evidence["seat"] = label or "(unnamed — no printed neighbour)"
            findings.append(finding(
                cls, severity, cls=cls, page=item.get("page"),
                detector=f"layout_qa.{group}",
                evidence=evidence))
    summary = {
        "page_count": raw.get("page_count"),
        "flagged_pages": raw.get("flagged_pages"),
        "pass": raw.get("pass"),
        "pages": raw.get("pages"),
        "unmapped": unmapped,
        "empty_cell_suppressed": suppressed,
    }
    return raw, findings, summary


def filter_layout_findings_for_scope(findings, summary, operation_scope):
    """Remove only form-fill layout noise from the closed story-edit scope.

    The returned summary records an aggregate count rather than document seat
    labels or page positions.  Ordinary form verification is returned
    unchanged.
    """
    if operation_scope != STORY_OPERATION_SCOPE:
        return findings, summary
    kept = [item for item in findings
            if item.get("class") != "empty_cell_expected_fill"]
    suppressed = len(findings) - len(kept)
    if not suppressed:
        return kept, summary
    scoped_summary = dict(summary or {})
    scoped_summary["story_scope_empty_cell_suppressed"] = suppressed
    return kept, scoped_summary


#: One loader, one normalization: the derivation below must agree with the
#: gate about what the document contains, so it reads the map and the
#: artifact text through ``check_residue`` itself rather than reimplementing
#: either.
load_fill_map = check_residue.load_fill_map


def reconcile_fill_map(expectations, fill_map_path):
    """ONE user-visible fill map, whichever surface it arrives on.

    ``--fill-map`` and ``expectations.fill_map`` used to be two different
    inputs with materially different effects and nothing saying so: the CLI
    flag drove the residue keep derivation, while the expectations MEMBER was
    what activated the fill-value presence check and the T30 post-flight. A
    caller who passed the flag (the v0.17 clean-room luna tier did) got a
    verdict with both of those checks in ``skipped[]`` — and, before this fix,
    ``acceptance: true`` anyway.

    They are the same fact — "label -> value that was filled" — so they are now
    one concept: the CLI map SEEDS ``expectations.fill_map`` when the
    expectations file does not carry one. Declaring both is fine when they
    agree (passing one expectations file to both flags is the T35-blessed
    invocation); declaring both DIFFERENTLY is a usage error rather than a
    silent precedence rule, because there is no honest answer to "which map did
    you actually fill with".

    Returns ``(expectations, source, error)`` where ``source`` is one of
    ``expectations``, ``cli``, ``cli+expectations`` (both, agreeing) or None.
    """
    declared = expectations.get("fill_map")
    if declared is not None and not isinstance(declared, dict):
        return expectations, None, (
            "expectations.fill_map must be a JSON object of {label: value}, "
            f"got {type(declared).__name__}")
    if declared:
        # Scoped values are flattened on BOTH surfaces or the equality test
        # below compares a scoped map against a flattened one and reports two
        # identical maps as different (T41).
        declared, error = check_residue.normalize_fill_map(declared)
        if error:
            return expectations, None, error.replace("--fill-map",
                                                     "expectations.fill_map")
        expectations = dict(expectations, fill_map=declared)
    if fill_map_path is None:
        return expectations, ("expectations" if declared else None), None
    mapping, error = load_fill_map(fill_map_path)
    if error:
        return expectations, None, error
    if declared:
        if declared != mapping:
            return expectations, None, (
                f"--fill-map ({fill_map_path}) and expectations.fill_map "
                "declare DIFFERENT maps, so it is not decidable which one the "
                "artifact was filled with. They are one concept: pass the map "
                "on one surface only, or pass the same expectations file to "
                "both flags. "
                f"--fill-map keys={sorted(mapping)}; "
                f"expectations.fill_map keys={sorted(declared)}")
        return expectations, "cli+expectations", None
    seeded = dict(expectations)
    seeded["fill_map"] = mapping
    return seeded, "cli", None


#: The alias kept for the module payloads that already ship it. ONE concept,
#: two spellings, reconciled in one place — the same discipline
#: ``reconcile_fill_map`` applies to the map itself.
DECLARED_BLANK_ALIASES = ("declared_blank", "intentionally_blank")


def reconcile_declared_blank(expectations, fill_map_path):
    """The seats the caller says they left blank ON PURPOSE, and where from.

    A blank seat is not a defect the tool can infer: a form's signature line,
    a staff-only box and a field the operator simply has no value for all look
    identical in the render. Before this, the only outlet was
    ``expectations.intentionally_blank`` on the fill-value leg, and the
    layout side had none at all — so every accepted run on a form with a
    by-design blank emitted the same ``empty_cell_expected_fill`` warning, and
    a warning every correct run emits teaches people to ignore warnings.

    So the declaration is explicit, it is ONE list however it arrives, and it
    is recorded: the verdict publishes ``deterministic.declared_blank`` and
    ``declared_blank_source``. ``declared_blank`` is the name to use;
    ``intentionally_blank`` is accepted as its alias (module payloads ship it)
    and folded into the same list. The fill-map file may carry it too when it
    is the wrapper shape, which keeps ONE file for the whole fill.

    Returns ``(entries, sources, error)``.
    """
    entries, sources = [], []

    def _take(payload, origin):
        for name in DECLARED_BLANK_ALIASES:
            value = payload.get(name)
            if value is None:
                continue
            if not isinstance(value, list) or not all(
                    isinstance(item, str) for item in value):
                return (f"{origin}.{name} must be a list of seat names "
                        "(labels or fill-map keys), "
                        f"got {type(value).__name__}")
            source = f"{origin}.{name}"
            if value and source not in sources:
                sources.append(source)
            for item in value:
                if item not in entries:
                    entries.append(item)
        return None

    error = _take(expectations, "expectations")
    if error:
        return [], [], error
    if fill_map_path is not None:
        try:
            payload = json.loads(
                Path(fill_map_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None          # load_fill_map already reported the shape
        if isinstance(payload, dict) and "fill_map" in payload:
            error = _take(payload, "fill_map")
            if error:
                return [], [], error
    return entries, sources, None


def validate_operation_scope(expectations, args):
    """Validate the closed story-edit render scope before any work starts.

    ``story_edit.py`` receipts are intentionally unbound, so this is only a
    *render expectation* and never an artifact-binding shortcut.  Story scope
    has no form-fill inputs: accepting one alongside a fill map/profile would
    make it ambiguous whether the fill-only safety checks were supposed to
    run.  Refuse that combination rather than weakening either contract.

    Returns ``(scope, error)`` where ``scope`` is ``None`` for the ordinary
    form-fill path.
    """
    scope_declared = "operation_scope" in expectations
    scope = expectations.get("operation_scope")
    if (scope_declared
            and (not isinstance(scope, str) or scope not in _OPERATION_SCOPES)):
        return None, (
            "expectations.operation_scope must be the closed value "
            f"{STORY_OPERATION_SCOPE!r}, got {scope!r}")

    required_declared = "required_text" in expectations
    required = expectations.get("required_text")
    if required_declared:
        if (not isinstance(required, list) or not required
                or any(not isinstance(item, str)
                       or not item.strip()
                       or len(item) > _MAX_REQUIRED_TEXT_CHARS
                       for item in required)):
            return None, (
                "expectations.required_text must be a non-empty list of "
                f"non-empty strings (max {_MAX_REQUIRED_TEXT_CHARS} chars)")
        if len(set(required)) != len(required):
            return None, "expectations.required_text must not contain duplicates"
    if required_declared and scope != STORY_OPERATION_SCOPE:
        return None, (
            "expectations.required_text requires "
            f"operation_scope {STORY_OPERATION_SCOPE!r}")
    if scope != STORY_OPERATION_SCOPE:
        return None, None
    if not required_declared:
        return None, (
            "story_edit operation_scope requires a non-empty "
            "expectations.required_text list")
    allowed = {"operation_scope", "required_text", "forbidden_text"}
    conflict_keys = set(("fill_map", "declared_blank", "intentionally_blank"))
    unknown = sorted(set(expectations) - allowed - conflict_keys)
    if unknown:
        return None, (
            "story_edit operation_scope expectations has unknown key(s): "
            + ", ".join(unknown))
    forbidden = expectations.get("forbidden_text")
    if (not isinstance(forbidden, list) or not forbidden
            or any(not isinstance(item, str)
                   or not item.strip()
                   or len(item) > _MAX_REQUIRED_TEXT_CHARS
                   for item in forbidden)):
        return None, (
            "story_edit operation_scope requires a non-empty list of "
            f"non-empty expectations.forbidden_text strings (max "
            f"{_MAX_REQUIRED_TEXT_CHARS} chars)")
    if Path(str(getattr(args, "artifact", ""))).suffix.lower() != ".hwpx":
        return None, "story_edit operation_scope requires a .hwpx artifact"
    if getattr(args, "pdf", None) is None:
        return None, "story_edit operation_scope requires explicit --pdf"
    if getattr(args, "baseline", None) is None:
        return None, "story_edit operation_scope requires explicit --baseline"
    if getattr(args, "conversion_record", None) is None:
        return None, (
            "story_edit operation_scope requires explicit hash-bound "
            "--conversion-record")
    if getattr(args, "deterministic_only", False):
        return None, (
            "story_edit operation_scope cannot use --deterministic-only; "
            "the vision half remains mandatory")
    if getattr(args, "accept_without", None):
        return None, (
            "story_edit operation_scope cannot use --accept-without; "
            "fill checks are audited as not_applicable, not waived")
    if getattr(args, "vision_scope", "all") != "all":
        return None, (
            "story_edit operation_scope requires --vision-scope all; "
            "targeted vision is not permitted")

    conflicts = []
    # Presence, not truthiness, is intentional: even an empty/null map is a
    # declaration whose semantics would otherwise be unclear in this scope.
    if "fill_map" in expectations:
        conflicts.append("fill_map")
    if getattr(args, "fill_map", None) is not None:
        conflicts.append("--fill-map")
    if getattr(args, "form_profile", None) is not None:
        conflicts.append("--form-profile")
    if any(name in expectations for name in DECLARED_BLANK_ALIASES):
        conflicts.extend(name for name in DECLARED_BLANK_ALIASES
                         if name in expectations)
    if getattr(args, "keep", None) or getattr(args, "keep_pattern", None) is not None:
        conflicts.extend(flag for flag, present in (
            ("--keep", bool(getattr(args, "keep", None))),
            ("--keep-pattern", getattr(args, "keep_pattern", None) is not None),
        ) if present)
    if conflicts:
        labels = ", ".join(dict.fromkeys(conflicts))
        return None, (
            f"operation_scope {STORY_OPERATION_SCOPE!r} conflicts with "
            f"{labels}; story scope has no form-fill inputs")
    return STORY_OPERATION_SCOPE, None


def declared_blank_match(declared, label):
    """Does a declaration name this seat? Whitespace-normalized, either way.

    Form labels arrive with the form's own padding (``성    명``), and a
    caller writing the declaration by hand will not reproduce it. Containment
    in either direction also lets one entry cover a seat the PDF reports under
    a longer name.
    """
    target = _norm(label or "")
    if not target:
        return None
    for entry in declared:
        normalized = _norm(entry)
        if normalized and (normalized in target or target in normalized):
            return entry
    return None


def resolve_header_cell_empty(item, declared_blank):
    """(suppression_reason, label) for one ``layout_qa`` header_cell_empty.

    ``None`` reason means "report it" — and then the finding is named by its
    LABEL, not by the y coordinate that made the old warning unactionable.
    """
    pattern = item.get("spacer_pattern")
    if pattern:
        return f"spacer:{pattern}", item.get("label")
    entry = declared_blank_match(declared_blank, item.get("label"))
    if entry is not None:
        return "declared_blank", item.get("label")
    return None, item.get("label")


def artifact_haystack(artifact):
    """The gate's own normalized view of the artifact text, or None.

    None means the artifact could not be read at all — the delegate reports
    that loudly (``pinned_target_missing`` / ``artifact_malformed``), so the
    derivation must not turn it into a verdict of its own.
    """
    try:
        return check_residue.artifact_text(Path(artifact))
    except (OSError, UnicodeError, zipfile.BadZipFile, ET.ParseError):
        return None


class AmbiguousFillKeyError(ValueError):
    """A ``--fill-map`` key does not name ONE thing in the form (T41).

    ``derive_form_keep`` matches keys against the anchor/placeholder inventory
    by whitespace-normalized substring **in either direction**, so a bare label
    key claims every inventory string that contains it or is contained by it,
    and the claimed strings leave the keep list. On a 민원 form 성명/연락처 sit
    in three seats and ``[  ]통`` also claims the generic ``[ ]`` checkbox, so
    every OTHER untouched occurrence came back as HARD residue — a false HARD
    the operator could only diagnose by reading this source.

    The refusal is about ONE key claiming SEVERAL inventory strings, which is
    where the derivation guesses. It is deliberately NOT about a key whose one
    string repeats in the document: that case is already per-occurrence and
    honest — the value's own occurrence is attributed to its span and a second,
    genuinely unfilled occurrence still HARDs with its offset and context
    (T31). Turning that into a usage error would trade a working gate for a
    prompt.

    Keep-listing and forbidding are STRING-level in ``check_residue``: either
    no occurrence of a claimed label is residue, or every unattributed one is.
    There is no third answer for the tool to compute, so it must ask.

    ``keys``: ``[{key, normalized_key, matched}]`` — the exact user key, the
    comparison key, every inventory string it claimed, and how many times each
    is present in the artifact.
    """

    def __init__(self, keys):
        self.keys = list(keys)
        lines = []
        for row in self.keys:
            claimed = ", ".join(
                f"{entry['text']!r}"
                + (f"×{entry['occurrences']}"
                   if entry["occurrences"] is not None else "")
                for entry in row["matched"])
            lines.append(
                f"key {row['key']!r} claims {len(row['matched'])} inventory "
                f"strings: {claimed}")
        super().__init__(
            f"--fill-map: {len(self.keys)} key(s) each claim more than one "
            "form string, so the residue keep derivation cannot tell which of "
            "them you actually filled and which the form still prints "
            "untouched. Either use a key that names exactly one of them (no "
            "declaration needed then), or say what the rest are, per key: "
            '{"KEY": {"text": VALUE, "other_occurrences": "form_text"}} '
            "keep-lists every string that key claims (the form prints them), "
            '"seats" forbids them (every occurrence outside a declared value '
            f"still HARDs — the pre-T41 behavior). {' / '.join(lines)}")


def derive_form_keep(profile, fill_map, haystack=None, scopes=None):
    """Form-fill keep list: ``(anchors ∪ placeholders) − targeted``.

    The residue gate's forbidden list is auto-derived from the form scan, and
    on a FILL the form's own labels legitimately survive — so without a keep
    list every surviving anchor reads as residue and the delegate can never
    return pass (v0.17 clean-room finding, both agents). Entries no fill key
    targeted are KEPT, matched on whitespace-normalized substring in either
    direction (form-eval-scenarios protocol note 1). Guide text is
    deliberately NOT keepable: instruction prose must never survive a fill.

    A targeted entry is split three ways against the document, because the
    first derivation assumed the key TEXT VANISHES and that is not what a
    correct fill does (second clean-room run, T31). Filling a labeled field
    keeps the label as a prefix — ``" http://"`` becomes
    ``" http://hanbit.example.kr"`` — so the key survives by construction:

    * ``consumed`` — an occurrence of the targeted entry is wholly inside a
      mapped VALUE span in ``haystack``: the fill happened. The entry is not
      keep-listed; that occurrence is attributed there by the gate's
      ``--fill-map`` accounting, and an occurrence anywhere else still HARDs.
    * ``consumed`` — no value found but the entry text is gone too: nothing
      to flag either way (key-absence fallback).
    * ``unfilled`` — no value found and the entry is still in the document:
      neither kept nor consumed, so the gate flags it. That is the point.

    With ``haystack=None`` (no document to probe) every targeted entry counts
    as consumed, the pre-T31 behavior.

    A key whose claim is AMBIGUOUS raises :class:`AmbiguousFillKeyError`
    (T41) — it claimed more than one distinct inventory string. One claimed
    string repeating in the artifact remains T31's per-occurrence case and is
    deliberately not refused. ``scopes``
    (``{key: "form_text"|"seats"}``, from ``check_residue.fill_map_scopes``)
    is the operator's answer: ``form_text`` keep-lists every string that key
    claimed, ``seats`` runs the three-way split above unchanged — which is
    exactly the pre-T41 behavior, now said out loud.

    Returns (keep, consumed, unfilled).
    """
    keys = {}
    key_labels = {}
    for key, value in (fill_map or {}).items():
        if str(key).strip():
            normalized_key = _norm(str(key))
            keys.setdefault(normalized_key, []).append(value)
            key_labels.setdefault(normalized_key, []).append(str(key))
    scope_by_norm = {_norm(str(key)): value
                     for key, value in (scopes or {}).items()
                     if str(key).strip()}
    entries = []
    seen = set()
    for field in ("anchors", "placeholders"):
        for entry in profile.get(field) or []:
            text = entry if isinstance(entry, str) else (
                entry.get("text") if isinstance(entry, dict) else None)
            if not isinstance(text, str):
                continue
            normalized = _norm(text)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            entries.append((text, normalized, [
                key for key in keys
                if normalized in key or key in normalized]))

    # Ambiguity is a property of the KEY, not of one entry, so it is decided
    # over the whole inventory before any entry is classified: a key that
    # claims two strings must be refused even if the first one looks fine.
    claims = {}
    for text, _normalized, matched in entries:
        for key in matched:
            claims.setdefault(key, []).append(text)
    ambiguous = []
    for key, texts in sorted(claims.items()):
        if key in scope_by_norm or len(texts) < 2:
            continue
        ambiguous.append({"key": key_labels[key][0],
                          "normalized_key": key, "matched": [
            {"text": text,
             "occurrences": (_occurrence_count(haystack, text)
                             if haystack is not None else None)}
            for text in texts]})
    if ambiguous:
        raise AmbiguousFillKeyError(ambiguous)

    keep, consumed, unfilled = [], [], []
    for text, _normalized, matched in entries:
        if not matched:
            keep.append(text)
        elif any(scope_by_norm.get(key) == "form_text" for key in matched):
            keep.append(text)              # declared: the form prints this
        elif haystack is None or _fill_landed(keys, matched, text, haystack):
            consumed.append(text)
        elif check_residue.normalize_text(text) not in haystack:
            consumed.append(text)          # key-absence fallback
        else:
            unfilled.append(text)
    return keep, consumed, unfilled


def _occurrence_count(haystack, text):
    """How many times an inventory string is present, the gate's own way.

    ``check_residue`` counts overlapping occurrences of the SAME normalized
    string it will scan for, so the ambiguity test and the gate agree about
    what "repeated" means.
    """
    needle = check_residue.normalize_text(text)
    return len(check_residue.occurrences(haystack, needle)) if needle else 0


def _fill_landed(keys, matched, target, haystack):
    """True when ``target`` lands *inside* one of its mapped value spans.

    Merely finding a mapped fragment somewhere after a surviving form label
    contradicts the residue delegate: that label is outside the declared
    value and therefore still residue. Reuse the delegate's own occurrence
    and span primitives so the keep report and the gate cannot disagree (T43).
    """
    target = check_residue.normalize_text(target)
    for key in matched:
        for value in keys[key]:
            spans = check_residue.value_spans(haystack, {key: value})
            for start in check_residue.occurrences(haystack, target):
                end = start + len(target)
                if any(span["start"] <= start and end <= span["end"]
                       for span in spans):
                    return True
    return False


def build_residue_argv(form_profile, artifact, *, keep=(), keep_pattern=None,
                       fill_map=None):
    """``check_residue`` argv plus the keep report the verdict records.

    ``fill_map`` is the PATH to the map file: the derived keep list and the
    per-occurrence fill attribution are two halves of one mechanism, so the
    delegate gets the map too (``--fill-map``).

    Returns (argv, report, error).
    """
    argv = ["--form-profile", str(form_profile), "--artifact", str(artifact)]
    report = {"explicit_keep": list(keep), "keep_pattern": keep_pattern,
              "derived_keep": [], "consumed": [], "unfilled": [],
              "fill_map": None}
    derived = []
    if fill_map is not None:
        mapping, error = load_fill_map(fill_map)
        if error:
            return None, report, error
        try:
            profile = json.loads(
                Path(form_profile).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return None, report, f"form profile unreadable: {exc}"
        if not isinstance(profile, dict):
            return None, report, "form profile must be a JSON object"
        try:
            derived, consumed, unfilled = derive_form_keep(
                profile, mapping, artifact_haystack(artifact),
                check_residue.load_fill_scopes(fill_map))
        except AmbiguousFillKeyError as exc:
            # The refusal payload IS the escape hatch (the T34 shape): it names
            # every inventory string the key claimed and how often each is
            # present, so the operator answers from this JSON alone.
            report["ambiguous_fill_keys"] = exc.keys
            return None, report, str(exc)
        report.update(derived_keep=derived, consumed=consumed,
                      unfilled=unfilled, fill_map=sorted(mapping))
        argv += ["--fill-map", str(fill_map)]
    ordered, seen = [], set()
    for entry in (*keep, *derived):
        if entry not in seen:
            seen.add(entry)
            ordered.append(entry)
    for entry in ordered:
        argv += ["--keep", entry]
    if keep_pattern is not None:
        argv += ["--keep-pattern", keep_pattern]
    report["keep_total"] = len(ordered)
    return argv, report, None


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

def check_page_budget(expectations, page_count, baseline_records=None):
    """Declared page budget, with T100 attribution.

    A blank form can already exceed the budget it is filed under — a three-page
    form declared ``max: 2`` fails before anyone types a character. The
    violation is real either way, so the severity does not move; what the
    evidence adds is whether editing the fill could ever fix it.
    """
    budget = expectations.get("page_budget") or {}
    lo = budget.get("min")
    hi = budget.get("max", expectations.get("max_pages"))
    baseline_pages = len(baseline_records) if baseline_records else None
    out = []

    def attribution(violates):
        if baseline_pages is None:
            return {"inherited": INHERITED_UNKNOWN,
                    "inherited_reason": "no measurable blank-form baseline in "
                                        "this run"}
        state = INHERITED_YES if violates(baseline_pages) else INHERITED_NO
        item = {"inherited": state, "baseline_pages": baseline_pages}
        if state == INHERITED_YES:
            item["note"] = ("the blank form already violates this budget, so "
                            "the declaration or the form is wrong — editing "
                            "the fill cannot satisfy it")
        return item

    if lo is not None and page_count < lo:
        evidence = {"pages": page_count, "min": lo}
        evidence.update(attribution(lambda pages: pages < lo))
        out.append(finding(
            "page_budget_violation", "hard", cls="page_budget_violation",
            detector="visual_verify.page_budget", evidence=evidence))
    if hi is not None and page_count > hi:
        evidence = {"pages": page_count, "max": hi}
        evidence.update(attribution(lambda pages: pages > hi))
        out.append(finding(
            "page_budget_violation", "hard", cls="page_budget_violation",
            detector="visual_verify.page_budget", evidence=evidence))
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
                     normalized, pages_source=None):
    """The W6.2 mechanism, both legs.

    ``pages_source`` names where ``pages_document`` came from and decides how
    much the parity leg is allowed to claim:

    * ``conversion`` (Hancom's own ``PageCount``) and ``expectations`` (an
      operator declaration) are AUTHORITATIVE — any inequality is HARD, as it
      has always been;
    * ``artifact_layout_cache`` is DERIVED (``derive_pages_document``), and the
      cache under-counts on table-heavy forms and goes stale after an offline
      XML edit (T24). Imposition can only FOLD pages, so only
      ``pages_pdf < pages_document`` is HARD there; the other direction is a
      WARN that names both explanations instead of pretending to know.
    """
    out = []
    if print_method not in (None, 0) and not normalized:
        out.append(finding(
            "imposition_mismatch", "hard", cls="imposition_mismatch",
            detector="visual_verify.print_method",
            evidence={"stored_print_method": print_method,
                      "note": "source stores n-up print imposition; Hancom "
                              "SaveAs(PDF) honours it (XC-1 §9.3)"}))
    if pages_document and pages_pdf and pages_document != pages_pdf:
        derived = pages_source == "artifact_layout_cache"
        folded = pages_pdf < pages_document
        evidence = {"pages_document": pages_document,
                    "pages_pdf": pages_pdf,
                    "pages_document_source": pages_source}
        if derived and not folded:
            evidence["note"] = (
                "derived from the artifact's layout cache, which under-counts "
                "when the body lives inside tables and goes stale after an "
                "offline XML edit (T24); the PDF has MORE pages than the cache "
                "records, which n-up imposition cannot cause — so this is "
                "reported, not failed. Declare expectations.pages_document (or "
                "let this script do the conversion) for an authoritative "
                "comparison")
        out.append(finding(
            "imposition_mismatch", "warn" if (derived and not folded)
            else "hard", cls="imposition_mismatch",
            detector="visual_verify.page_parity", evidence=evidence))
    landscape = [r["page"] for r in records if r["landscape"]]
    if landscape and print_method not in (None, 0):
        out.append(finding(
            "imposition_mismatch", "warn", cls="imposition_mismatch",
            detector="visual_verify.orientation",
            evidence={"landscape_pages": landscape,
                      "stored_print_method": print_method}))
    return out


def check_format(records, expectations, baseline_records=None):
    """Declared typography and margins, with T100 attribution.

    All three metrics here are predominantly properties of the FORM, not of the
    fill. A page's median point size on a form is dominated by the form's own
    printed labels and boilerplate; margins are its page setup outright. So a
    declaration the blank form already fails will fail on every page no matter
    how correct the fill is.

    Severity is unchanged — the document as submitted really does violate the
    declaration, and that is what ``format_noncompliance`` means. What the
    evidence adds is attribution, because "your fill is wrong" and "this form
    cannot satisfy this declaration" call for opposite actions.
    """
    out = []
    base_pt = expectations.get("base_pt")
    spacing = expectations.get("line_spacing_pct")
    margins = expectations.get("margins_mm") or {}

    def attributed(evidence, page, predicate):
        state, reason = _attribute(baseline_records, page, predicate)
        evidence["inherited"] = state
        if reason:
            evidence["inherited_reason"] = reason
        elif state == INHERITED_YES:
            evidence["note"] = ("the blank form fails the same declaration on "
                                "this page, so the declaration or the form is "
                                "wrong — editing the fill cannot satisfy it")
        return evidence

    for rec in records:
        if base_pt and rec["median_pt"]:
            if abs(rec["median_pt"] - base_pt) > BASE_PT_TOL:
                evidence = {"measured_pt": rec["median_pt"],
                            "declared_pt": base_pt, "tol_pt": BASE_PT_TOL}
                out.append(finding(
                    "format_noncompliance", "hard", cls="format_noncompliance",
                    page=rec["page"], detector="visual_verify.base_pt",
                    evidence=attributed(
                        evidence, rec["page"],
                        lambda b: bool(b["median_pt"]) and abs(
                            b["median_pt"] - base_pt) > BASE_PT_TOL)))
        if spacing and rec["line_pitch_pt"] and rec["median_pt"]:
            measured = rec["line_pitch_pt"] / rec["median_pt"] * 100.0
            if abs(measured - spacing) > LINE_SPACING_TOL_PCT:
                evidence = {"measured_pct": round(measured, 1),
                            "declared_pct": spacing,
                            "tol_pct": LINE_SPACING_TOL_PCT}

                def _spacing_fails(b):
                    if not (b["line_pitch_pt"] and b["median_pt"]):
                        return False
                    base_measured = b["line_pitch_pt"] / b["median_pt"] * 100.0
                    return abs(base_measured - spacing) > LINE_SPACING_TOL_PCT

                out.append(finding(
                    "format_noncompliance", "hard", cls="format_noncompliance",
                    page=rec["page"], detector="visual_verify.line_spacing",
                    evidence=attributed(evidence, rec["page"],
                                        _spacing_fails)))
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
                    evidence = {"side": side,
                                "measured_mm": round(actual[side], 1),
                                "declared_mm": declared,
                                "tol_mm": MARGIN_TOL_MM}
                    # side/declared are bound as defaults rather than closed
                    # over. Defensive only: ``attributed`` invokes the
                    # predicate immediately, so a closure would read the
                    # current iteration's values and behave the same today.
                    # The binding is here so a later refactor that DEFERS the
                    # call cannot silently attribute every side using the last
                    # one. Mutating it away does not fail any test, and the
                    # per-side test says so instead of pretending otherwise.
                    def _margin_fails(b, side=side, declared=declared):
                        if not b["content_bbox_pt"]:
                            return False
                        bx0, by0, bx1, by1 = b["content_bbox_pt"]
                        base_actual = {
                            "left": bx0 * MM_PER_PT,
                            "top": by0 * MM_PER_PT,
                            "right": (b["width_pt"] - bx1) * MM_PER_PT,
                            "bottom": (b["height_pt"] - by1) * MM_PER_PT,
                        }
                        return base_actual[side] < declared - MARGIN_TOL_MM

                    out.append(finding(
                        "format_noncompliance", "hard",
                        cls="format_noncompliance", page=rec["page"],
                        detector="visual_verify.margins",
                        evidence=attributed(evidence, rec["page"],
                                            _margin_fails)))
    return out


def _norm(text):
    return re.sub(r"\s+", "", text or "")


def _fill_value_parts(value):
    """Non-empty normalized paragraphs in one declared fill value (T44).

    ``preedit.split_fill_lines`` is the authoring contract for JSON arrays,
    LF/CRLF/CR strings and intentional blank paragraphs. Reusing it here
    keeps the post-flight from treating a multi-paragraph fill as one XML run
    that can never exist.
    """
    return [part for line in preedit.split_fill_lines(value)
            if (part := _norm(line))]


def _cell_address_key(label):
    match = re.fullmatch(r"\s*(\d+)\s*,\s*(\d+)\s*", str(label))
    return tuple(map(int, match.groups())) if match else None


def _seat_matches_address(seat, address):
    if not seat or address is None:
        return False
    match = re.fullmatch(r"(\d+),(\d+)", seat[-1].rsplit("/", 1)[-1])
    return bool(match) and tuple(map(int, match.groups())) == address


def check_fill_map(records, expectations, declared_blank=()):
    """Declared fill values must be visible somewhere in the render."""
    fill_map = expectations.get("fill_map") or {}
    if not fill_map:
        return []
    haystack = _norm("".join(r["_text"] for r in records))
    out = []
    for label, value in sorted(fill_map.items()):
        if declared_blank_match(declared_blank, label) is not None:
            continue
        parts = preedit.split_fill_lines(value)
        declared = _norm("".join(parts))
        if not declared:
            continue
        if declared not in haystack:
            out.append(finding(
                "empty_cell_expected_fill", "hard",
                cls="empty_cell_expected_fill",
                detector="visual_verify.fill_map",
                evidence={"label": label,
                          "declared_value": str(value)[:80],
                          "note": "declared value not present in the render"}))
    return out


# --------------------------------------------------------------------------
# T30 — script/scale/offset inheritance on fill-modified runs
# --------------------------------------------------------------------------

#: The profile extraction, the signature, the baseline choice and the
#: difference test are SHARED with the pre-flight half of T30
#: (``form_inspect``'s ``script_anomaly``) via ``engine/scripts/
#: charpr_script.py`` — a pre-flight that disagreed with this detector would
#: be worse than no pre-flight at all. Nothing about the trap is redefined
#: here; only the artifact plumbing (zip, hwpx-only scope) lives in this file.
_SCRIPT_FLAG_TAGS = charpr_script.SCRIPT_FLAG_TAGS
_SCRIPT_SCALE_TAGS = charpr_script.SCRIPT_SCALE_TAGS
_SCRIPT_RENDER_FACTOR = charpr_script.SCRIPT_RENDER_FACTOR
_localname = charpr_script.localname
_script_signature = charpr_script.signature


def charpr_script_profiles(artifact):
    """``charPr id -> script/scale/offset profile`` from Contents/header.xml.

    Returns ``{}`` for anything that is not a readable hwpx — this check is
    scoped to the offline XML engine's own format.
    """
    path = Path(artifact)
    if path.suffix.lower() != ".hwpx" or not path.is_file():
        return {}
    try:
        with zipfile.ZipFile(path) as archive:
            if "Contents/header.xml" not in archive.namelist():
                return {}
            header = archive.read("Contents/header.xml")
    except (OSError, zipfile.BadZipFile):
        return {}
    return charpr_script.profiles_from_header(header)


def _hwpx_seat_runs(artifact):
    """``[(seat, charPrIDRef, text)]`` over every section, in document order.

    ``seat`` is the run's structural address (``charpr_script.iter_seat_runs``)
    — the table cell it sits in, or ``()`` for a run outside every cell.
    """
    path = Path(artifact)
    if path.suffix.lower() != ".hwpx" or not path.is_file():
        return []
    out = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(n for n in archive.namelist()
                           if re.match(r"Contents/section\d+\.xml$", n))
            for name in names:
                xml = archive.read(name).decode("utf-8", "replace")
                out.extend(charpr_script.iter_seat_runs(xml, name))
    except (OSError, zipfile.BadZipFile):
        return []
    return out


def _hwpx_seat_empty_runs(artifact):
    """``[(seat, charPrIDRef)]`` for reserved, text-less table-cell runs."""
    path = Path(artifact)
    if path.suffix.lower() != ".hwpx" or not path.is_file():
        return []
    out = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(n for n in archive.namelist()
                           if re.match(r"Contents/section\d+\.xml$", n))
            for name in names:
                xml = archive.read(name).decode("utf-8", "replace")
                out.extend(charpr_script.iter_seat_empty_runs(xml, name))
    except (OSError, zipfile.BadZipFile):
        return []
    return out


def _hwpx_runs(artifact):
    """``[(charPrIDRef, text)]`` over every section, in document order."""
    return [(cid, text) for _seat, cid, text in _hwpx_seat_runs(artifact)]


def _hwpx_seats(artifact):
    """Every table-cell seat in the document, text-carrying or not."""
    path = Path(artifact)
    seats = set()
    if path.suffix.lower() != ".hwpx" or not path.is_file():
        return seats
    try:
        with zipfile.ZipFile(path) as archive:
            for name in sorted(n for n in archive.namelist()
                               if re.match(r"Contents/section\d+\.xml$", n)):
                xml = archive.read(name).decode("utf-8", "replace")
                seats |= charpr_script.seat_addresses(xml, name)
    except (OSError, zipfile.BadZipFile):
        return set()
    return seats


#: ``--baseline`` takes four shapes (T35): the blank ``.hwpx``, a ``.hwp``, an
#: already-rendered PDF, or a directory of page images. Only the first can be
#: read as XML, and the seat comparison below needs XML — so this returns the
#: path when there is one and, when there is not, the sentence the verdict
#: publishes instead of a claim it did not earn.
def seat_baseline_source(baseline):
    """``(path, unavailable_reason)`` — the blank ``.hwpx`` seats can be read
    from, or None plus why not. Exactly one of the two is ever set."""
    if not baseline:
        return None, ("no --baseline was given, so whether the blank form's "
                      "own seat already carried this signature could not be "
                      "checked")
    path = Path(str(baseline)).expanduser()
    if path.is_dir():
        return None, ("--baseline is a directory of page images; the seat "
                      "comparison needs the blank .hwpx, so whether the form "
                      "already carried this signature could not be checked")
    if path.suffix.lower() != ".hwpx":
        return None, (f"--baseline is {path.suffix or 'not a document'}, which "
                      f"carries no readable charPr definitions; the seat "
                      f"comparison needs the blank .hwpx, so whether the form "
                      f"already carried this signature could not be checked")
    if not path.is_file():
        return None, f"--baseline .hwpx is not a readable file: {path}"
    return path, None


def check_fill_charpr_script(artifact, expectations, baseline_form=None):
    """T30: a filled value inherited a charPr that is body text PLUS a script.

    The live incident: the PPS 협업제품명 cell's filled value carried a charPr
    identical to body except for a trailing ``<hh:supscript/>``. Nominal
    height stayed 10pt, so ``charpr_check --base-pt 10`` and ``style_diff``
    both passed it while Hancom rendered the value at ~6.35pt raised off the
    baseline; only the render caught it.

    SCOPE — fill-modified runs only. A run is fill-modified when its text
    carries one of the declared ``expectations.fill_map`` values. That is the
    false-positive guard: an intentionally superscripted footnote marker,
    ordinal or unit exponent is not a fill value, so it is never compared.

    TWO baselines, and the difference is the whole of T40:

    * the **document body baseline** — the charPr carrying the most non-fill
      text. It answers "does this run differ from the prose around it", and on
      a document that is mostly prose that is the right question.
    * the **form seat baseline** — the charPr on the blank run named by the
      fill-map key, inside the SAME SEAT (``baseline_form``, the ``.hwpx``
      ``--baseline`` already names). It answers the question that actually
      decides the finding: *did the fill introduce this signature?* Choosing
      the seat's most common charPr would be unsafe in a multi-run cell: an
      unrelated sibling could then excuse a real change to the filled run.

    A seat is a structural address, not text: see the seat-matching rule in
    ``engine/scripts/charpr_script.py`` (``iter_seat_runs``). Text cannot be
    the key because an ``--at-cell-append`` fill keeps the printed label and
    appends the value — the same seat reads "수신" in the blank and
    "수신 국가유산청장" in the artifact (T31) — while an ``--at-cell`` fill
    replaces the seat text outright. The table cell address survives both.

    A run is HARD only when it differs from BOTH baselines. That ordering is
    deliberate: the seat can only ever DOWNGRADE a finding, never create one,
    so adopting a seat baseline cannot invent a HARD on any other family.

      * differs from neither → clean, as before.
      * differs from body, matches its own seat in the blank form → the
        printed form was always like that and the fill introduced nothing:
        WARN ``fill_charpr_script_inherited``, named and on the record. This
        is why the whole 기안문 별지 gongmun family was unfillable — every
        substantive seat on that form is ratio 97%% while the heaviest charPr
        is the 비고 fine print at 100%%.
      * differs from body and an address-keyed fill matches a repeated block
        of reserved empty runs in the blank seat → WARN only when every run
        has one exact matching charPr whose sole body difference is ``ratio``
        (T42). A single empty run, mixed ids, a changed signature or any
        script/scale/offset anomaly stays HARD.
      * differs from body and no ``.hwpx`` baseline was available → HARD, and
        the finding SAYS the inheritance question was not checked. The
        detection stays, the claim does not exceed the evidence.
    """
    fill_map = expectations.get("fill_map") or {}
    if not any(_fill_value_parts(value) for value in fill_map.values()):
        return [], None
    profiles = charpr_script_profiles(artifact)
    runs = _hwpx_seat_runs(artifact)
    if not profiles or not runs:
        return [], None

    normalized_values = [
        (label, part, _cell_address_key(label))
        for label, value in sorted(fill_map.items())
        for part in _fill_value_parts(value)]
    filled, body_weight = [], collections.Counter()
    for seat, cid, text in runs:
        normalized = _norm(text)
        hit = next((label for label, part, address in normalized_values
                    if part in normalized
                    and (address is None
                         or _seat_matches_address(seat, address))), None)
        if hit is not None:
            filled.append((seat, cid, text, hit))
        else:
            body_weight[cid] += len(normalized)
    if not filled or not body_weight:
        return [], None

    baseline_cid = charpr_script.body_baseline_id(body_weight)
    baseline = profiles.get(baseline_cid)
    if baseline is None:
        return [], None
    baseline_signature = _script_signature(baseline)

    # -- the blank form's own seats, when one is readable -------------------
    form_source, form_note = seat_baseline_source(baseline_form)
    form_profiles, form_runs = {}, None
    form_empty_runs, form_addresses = [], set()
    if form_source is not None:
        form_profiles = charpr_script_profiles(form_source)
        baseline_runs = _hwpx_seat_runs(form_source)
        baseline_empty_runs = _hwpx_seat_empty_runs(form_source)
        if not form_profiles or not (baseline_runs or baseline_empty_runs):
            form_note = (f"--baseline {form_source.name} carries no readable "
                         f"charPr definitions or no runs, so whether the "
                         f"form already carried this signature could not be "
                         f"checked")
        else:
            form_runs = baseline_runs
            form_empty_runs = baseline_empty_runs
            form_addresses = _hwpx_seats(form_source)

    report = {"baseline_charpr_id": baseline_cid,
              "baseline": baseline_signature,
              "baseline_height_pt": baseline.get("height_pt"),
              "fill_modified_runs": len(filled),
              "form_baseline": (str(form_source) if form_runs is not None
                                 else None),
              "form_baseline_note": form_note,
              "inherited": 0}

    out, seen = [], set()
    for seat, cid, text, label in filled:
        profile = profiles.get(cid)
        if profile is None:
            continue
        signature = _script_signature(profile)
        differing = charpr_script.differing_keys(profile, baseline)
        if not differing or (cid, label) in seen:
            continue
        seen.add((cid, label))
        evidence = {
            "label": label,
            "charpr_id": cid,
            "baseline_charpr_id": baseline_cid,
            "differing": differing,
            "run": {key: signature[key] for key in differing},
            "baseline_values": {key: baseline_signature.get(key)
                                for key in differing},
            "nominal_height_pt": profile.get("height_pt"),
            "text": text.strip()[:60],
            "seat": "/".join(seat) or None,
        }
        rendered = charpr_script.rendered_pt_estimate(profile)
        if rendered is not None:
            evidence["rendered_pt_estimate"] = rendered

        # Was this seat already like this on the untouched form?
        form_cid = form_seat_note = None
        form_match = None
        if form_runs is None:
            form_seat_note = form_note
        elif not seat:
            form_seat_note = ("this run is not inside a table cell, so it has "
                              "no seat address to look up in the blank form")
        else:
            candidates = charpr_script.seat_label_runs(form_runs, seat, label)
            candidate_cids = sorted({candidate[0] for candidate in candidates})
            if len(candidate_cids) == 1:
                form_cid = candidate_cids[0]
                form_match = "fill_map_key"
            elif len(candidate_cids) > 1:
                form_seat_note = (
                    "the fill-map key matches several runs with different "
                    "charPr ids in the blank form's same seat, so the exact "
                    "baseline is ambiguous and nothing can be excused")
                evidence["form_baseline_candidates"] = [
                    {"charpr_id": candidate_cid, "text": candidate_text[:60]}
                    for candidate_cid, candidate_text in candidates]
            elif seat not in form_addresses:
                form_seat_note = (
                    "the blank form has no such seat, so the comparison could "
                    "not be made")
            elif (wanted := _cell_address_key(label)) is not None:
                reserved = [(run_seat, empty_cid)
                            for run_seat, empty_cid in form_empty_runs
                            if (run_seat == seat
                                and _seat_matches_address(run_seat, wanted))]
                empty_cids = sorted({empty_cid for _run_seat, empty_cid
                                     in reserved})
                evidence["form_baseline_reserved_runs"] = len(reserved)
                evidence["form_baseline_empty_charpr_ids"] = empty_cids
                if not reserved:
                    form_seat_note = (
                        "the blank form's same seat has no repeated reserved "
                        "empty runs, so there is no address-keyed typography "
                        "to inherit")
                elif len(reserved) < 2:
                    form_seat_note = (
                        "the blank form's same seat has only a genuinely "
                        "empty run, not a repeated reserved typography block, "
                        "so there is nothing safe to inherit")
                elif len(empty_cids) != 1:
                    form_seat_note = (
                        "the blank form's reserved runs in this seat carry "
                        "several charPr ids, so the address baseline is "
                        "ambiguous and nothing can be excused")
                else:
                    reserved_cid = empty_cids[0]
                    reserved_profile = form_profiles.get(reserved_cid)
                    reserved_differing = (
                        charpr_script.differing_keys(reserved_profile, baseline)
                        if reserved_profile is not None else [])
                    if reserved_profile is None:
                        form_seat_note = (
                            "the blank form's reserved runs refer to undefined "
                            f"charPr {reserved_cid}, so nothing can be excused")
                    elif set(reserved_differing) - {"ratio"}:
                        form_seat_note = (
                            "the blank form's repeated reserved typography "
                            "itself carries a script/scale/offset anomaly, so "
                            "it cannot excuse the filled run")
                    elif charpr_script.differing_keys(profile,
                                                       reserved_profile):
                        form_seat_note = (
                            "the filled run does not match the blank form's "
                            "repeated reserved typography, so the fill changed "
                            "its script/scale/offset signature")
                    else:
                        form_cid = reserved_cid
                        form_match = "cell_address_reserved_runs"
            elif not any(run_seat == seat for run_seat, _cid, _text in form_runs):
                form_seat_note = (
                    "the blank form's same seat carries no text at all (a "
                    "genuinely empty run), so there was no typography to "
                    "inherit — the fill introduced this signature")
            else:
                form_seat_note = (
                    "the fill-map key does not match a text run in the blank "
                    "form's same seat, so the exact pre-fill signature could "
                    "not be identified and nothing can be excused")
        evidence["form_baseline_charpr_id"] = form_cid
        evidence["form_baseline_checked"] = form_runs is not None
        evidence["form_baseline_match"] = form_match

        if form_cid is not None:
            form_profile = form_profiles.get(form_cid)
            if form_profile is None:
                form_seat_note = (
                    f"the blank form's matched run refers to undefined charPr "
                    f"{form_cid}, so its signature could not be checked and "
                    f"nothing can be excused")
            else:
                form_differing = charpr_script.differing_keys(
                    profile, form_profile)
                evidence["form_baseline_values"] = {
                    key: _script_signature(form_profile).get(key)
                    for key in differing}
                if not form_differing:
                    evidence["note"] = (
                        "the blank form's exact run in this seat already "
                        "carries this script/scale/offset signature, so the "
                        "fill introduced nothing — this is the form's "
                        "typography, not a T30 trap. Reported rather than "
                        "dropped: read the render to confirm the seat is "
                        "legible (T40)")
                    report["inherited"] += 1
                    out.append(finding(
                        "fill_charpr_script_inherited", "warn",
                        cls="format_noncompliance",
                        detector="visual_verify.fill_charpr_script",
                        evidence=evidence))
                    continue
                evidence["form_baseline_differing"] = form_differing
                form_seat_note = (
                    "the blank form's exact run in the same seat carries a "
                    "DIFFERENT signature, so the fill changed it")
        evidence["form_baseline_note"] = form_seat_note
        evidence["note"] = (
            "fill-modified run inherits a script/scale/offset the document "
            "body does not use; nominal height is unchanged so charpr_check "
            "and style_diff cannot see it (T30)")
        out.append(finding(
            "fill_charpr_script_mismatch", "hard",
            cls="format_noncompliance",
            detector="visual_verify.fill_charpr_script",
            evidence=evidence))
    report["findings"] = sum(1 for item in out if item["severity"] == "hard")
    return out, report


def check_forbidden_text(records, expectations):
    out = []
    story_scope = expectations.get("operation_scope") == STORY_OPERATION_SCOPE
    for needle in expectations.get("forbidden_text") or []:
        # Ordinary form guidance keeps the historical bounded prefix match.
        # Story-edit text is an explicit full-string contract: a common prefix
        # with a different suffix is not the old text.
        target = _norm(needle) if story_scope else _norm(needle)[:20]
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


def check_required_text(records, expectations):
    """Require every story-edit replacement marker in the current PDF text.

    This is deliberately render-bound: it reads only the text extracted from
    the PDF being verified and never consults the structural story-edit
    receipt.  ``validate_operation_scope`` closes the shape and requires the
    list for story scope; the empty result keeps ordinary form-fill behavior
    unchanged.
    """
    required = expectations.get("required_text") or []
    if not required:
        return []
    # Do not join page text: a forged ``ABC`` on page 1 plus ``DEF`` on page 2
    # must not satisfy one required ``ABCDEF`` replacement.
    page_text = [_norm(r["_text"]) for r in records]
    out = []
    for needle in required:
        target = _norm(needle)
        if target and not any(target in text for text in page_text):
            out.append(finding(
                "required_text_missing", "hard", cls=None,
                detector="visual_verify.required_text",
                evidence={"text": str(needle)[:80],
                          "note": "required text is absent from the current PDF"}))
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
        if cls in VISION_HARD_CLASSES and severity != "hard":
            return None, [], (
                f"findings[{i}] rubric class {cls!r} requires severity 'hard'")
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

def _out_target_error(out):
    """``--out`` refused BEFORE the work, so it cannot destroy a real verdict.

    An unwritable ``--out`` used to escape as an uncaught ``PermissionError``
    from ``emit_verdict`` — a traceback and process exit 1, which is not in this
    script's contract at all and is exactly how the v0.17 clean-room sol/terra
    tiers saw 1 where the contract says 3.
    """
    if not out:
        return None
    target = Path(out).expanduser()
    if target.is_dir():
        return (f"--out is an existing directory, not a file: {target} — "
                "name the verdict JSON file to write")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"--out parent directory is not creatable: {exc}"
    if not os.access(target.parent, os.W_OK):
        return f"--out directory is not writable: {target.parent}"
    return None


def verify(args):
    artifact = Path(args.artifact).expanduser()
    if not artifact.is_file():
        return usage_error(str(artifact), "visual_verify",
                           f"artifact not found: {artifact}")
    out_error = _out_target_error(getattr(args, "out", None))
    if out_error:
        return usage_error(str(artifact), "visual_verify", out_error)
    waivers = sorted(set(getattr(args, "accept_without", None) or ()))
    unknown = [w for w in waivers if w not in SAFETY_CHECKS]
    if unknown:
        return usage_error(
            str(artifact), "visual_verify",
            f"--accept-without: unknown check(s) {unknown} — the vocabulary is "
            f"closed: {', '.join(SAFETY_CHECKS)}")
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

    operation_scope, scope_error = validate_operation_scope(expectations, args)
    if scope_error:
        return usage_error(str(artifact), "visual_verify", scope_error)

    # ONE fill map, whichever flag carried it (see reconcile_fill_map): a CLI
    # --fill-map now seeds expectations.fill_map, so it can no longer leave the
    # fill-value presence check and the T30 post-flight silently inactive.
    expectations, fill_map_source, error = reconcile_fill_map(
        expectations, args.fill_map)
    if error:
        return usage_error(str(artifact), "visual_verify", error)
    # The residue delegate needs the SAME map path for per-occurrence value
    # attribution and T41 scopes. When the map arrived only inside
    # --expectations, that file is the map source; dropping it here would make
    # `other_occurrences` disappear and turn a valid declaration back into an
    # ambiguity refusal.
    residue_fill_map = args.fill_map
    if residue_fill_map is None and fill_map_source == "expectations":
        residue_fill_map = args.expectations
    # Same discipline for "I deliberately left this blank": one list, however
    # it is spelled, recorded in the verdict with where it came from.
    declared_blank, declared_blank_sources, error = reconcile_declared_blank(
        expectations, args.fill_map)
    if error:
        return usage_error(str(artifact), "visual_verify", error)

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

    # A conversion this script did not perform can still be PROVEN, when the
    # step that did perform it left a record bound to these exact bytes (T38).
    # Auto-discovery is deliberate: the canonical recipe converts then
    # verifies, and the operator must not have to remember a flag to keep the
    # evidence from evaporating between the two. An explicitly named record
    # that is missing or unbound is a usage error; so is a DISCOVERED one that
    # does not match, because a stale sidecar next to the PDF means the PDF
    # itself is stale — exactly the thing that must never verify quietly.
    if conversion is None:
        named = getattr(args, "conversion_record", None)
        candidate = Path(named) if named else conversion_record_path(pdf_path)
        if named or candidate.is_file():
            conversion, error = load_conversion_record(
                candidate, artifact, pdf_path)
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
    if operation_scope == STORY_OPERATION_SCOPE:
        if not any(re.fullmatch(r"Contents/section\d+\.xml", name)
                   for name in xml_members):
            return usage_error(
                str(artifact), "visual_verify",
                "story_edit operation_scope requires non-empty section XML")
        conversion_error = validate_story_conversion(
            conversion, artifact, page_count, print_method)
        if conversion_error:
            return usage_error(str(artifact), "visual_verify", conversion_error)
    blank_pages = set(expectations.get("blank_pages") or [])

    # -- deterministic backstops --------------------------------------------
    det = check_blank(records, blank_pages)
    # Page parity needs a document-side page count, and it must not depend on
    # the caller remembering to declare one: prefer the conversion this script
    # performed (Hancom's own PageCount), then an explicit declaration, then the
    # artifact's own layout cache. Only when all three are unavailable does
    # parity skip, and then ``pages_document_note`` says which leg was missing.
    # --baseline is resolved HERE, before the deterministic legs, because T100
    # attribution needs the blank form's own measurements: several legs compare
    # the artifact against a declaration the FORM largely determines, and
    # without the baseline they can only report the violation, never say whether
    # editing the fill could fix it. The pixel diff below reuses this result
    # rather than resolving a second time.
    base_source = base_conversion = baseline_skip = None
    if args.baseline:
        base_source, base_conversion, baseline_skip, error = resolve_baseline(
            args.baseline, Path(pdf_path).parent)
        if error:
            return usage_error(str(artifact), "visual_verify", error)
    baseline_records = (
        _baseline_format_records(fitz, base_source, args.dpi)
        if (base_source and not baseline_skip) else None)

    pages_document_note = None
    if (conversion or {}).get("pages_document") is not None:
        pages_document = conversion["pages_document"]
        pages_document_source = "conversion"
    elif expectations.get("pages_document") is not None:
        pages_document = expectations["pages_document"]
        pages_document_source = "expectations"
    else:
        pages_document, pages_document_note = derive_pages_document(artifact)
        pages_document_source = ("artifact_layout_cache"
                                 if pages_document is not None else None)
    pages_pdf = (conversion or {}).get("pages_pdf", page_count)
    det += check_imposition(
        records, print_method, pages_document, pages_pdf,
        normalized=bool((conversion or {}).get("print_method_normalized")),
        pages_source=pages_document_source)
    det += check_page_budget(expectations, page_count, baseline_records)
    det += check_format(records, expectations, baseline_records)
    det += check_fill_map(records, expectations, declared_blank)
    # --baseline is the BLANK FORM. The pixel diff below converts it; the T30
    # post-flight reads its XML, to tell a signature the fill INTRODUCED from
    # one the printed form always had (T40). Passing the raw argument, not the
    # converted PDF, is the point — and a --baseline that is a PDF or an image
    # directory cannot answer the question, which the verdict then says.
    script_findings, script_report = check_fill_charpr_script(
        artifact, expectations, args.baseline)
    det += script_findings
    det += check_required_text(records, expectations)
    det += check_forbidden_text(records, expectations)

    # Story scope owns an exact full-string per-page forbidden-text contract;
    # legacy layout_qa intentionally uses a bounded 20-character prefix and
    # would reintroduce suffix false positives.  Keep the ordinary form path
    # unchanged.
    guide_strings = (None if operation_scope == STORY_OPERATION_SCOPE
                     else expectations.get("forbidden_text") or None)
    layout_raw, layout_findings, layout_summary = run_layout_qa(
        pdf_path, guide_strings=guide_strings, declared_blank=declared_blank)
    # ``layout_qa``'s header-cell warning is a form-fill heuristic.  A story
    # edit has no seat map by contract, so retaining that warning would
    # contradict the audited ``empty_cell_expected_fill`` N/A state.
    layout_findings, layout_summary = filter_layout_findings_for_scope(
        layout_findings, layout_summary, operation_scope)
    det += layout_findings

    delegates = []
    residue_keep = None
    if args.form_profile:
        residue_argv, residue_keep, error = build_residue_argv(
            args.form_profile, artifact, keep=args.keep,
            keep_pattern=args.keep_pattern, fill_map=residue_fill_map)
        if error:
            extra = ({"ambiguous_fill_keys": residue_keep["ambiguous_fill_keys"]}
                     if "ambiguous_fill_keys" in residue_keep else None)
            return usage_error(str(artifact), "visual_verify", error,
                               extra=extra)
        delegates.append(_delegate(
            _SCRIPTS_DIR / "check_residue.py", residue_argv, "check_residue"))
    elif args.keep or args.keep_pattern is not None:
        # --fill-map is NOT in this list any more: since it seeds
        # expectations.fill_map it is meaningful on its own (it activates the
        # fill-value presence check and the T30 post-flight). --keep and
        # --keep-pattern really are residue-delegate-only.
        return usage_error(
            str(artifact), "visual_verify",
            "--keep / --keep-pattern only apply to the check_residue "
            "delegate; pass --form-profile too")
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
    # base_source / base_conversion / baseline_skip were resolved above, before
    # the deterministic legs, so that T100 attribution could use the blank
    # form's own measurements. Do NOT re-initialise baseline_skip here: that
    # reset is what silently discarded the earlier resolution and sent an
    # unrenderable .hwpx baseline into the pixel diff as None.
    if args.baseline and baseline_skip:
        baseline_report = {"baseline": str(args.baseline),
                           "baseline_pages": None, "skipped": baseline_skip,
                           "pages": []}
    elif args.baseline:
        base_pix = _baseline_pixmaps(fitz, base_source, args.dpi, page_count)
        if base_pix is None:
            return usage_error(str(artifact), "visual_verify",
                               f"--baseline is neither a document, a PDF nor a "
                               f"directory of page images: {args.baseline}. "
                               f"{BASELINE_SOURCES}")
        converted = (Path(args.baseline).suffix.lower()
                     in BASELINE_DOC_SUFFIXES)
        baseline_report = {"baseline": str(args.baseline),
                           "baseline_pdf": (str(base_source) if converted
                                            else None),
                           "baseline_conversion": base_conversion,
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

    if operation_scope == STORY_OPERATION_SCOPE:
        if baseline_skip or baseline_report is None:
            return usage_error(
                str(artifact), "visual_verify",
                "story_edit operation_scope requires a comparable baseline "
                "pixel diff")
        if baseline_report.get("baseline_pages") != page_count \
                or any(not page.get("comparable")
                       for page in baseline_report.get("pages", ())):
            return usage_error(
                str(artifact), "visual_verify",
                "story_edit operation_scope requires baseline pages with "
                "comparable geometry and matching page count")

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
            if operation_scope == STORY_OPERATION_SCOPE:
                return usage_error(
                    str(artifact), "visual_verify",
                    "story_edit operation_scope vision verdict must review "
                    f"all pages; missing {missing}")
            hard.append(finding(
                "vision_incomplete", "hard", cls=None, detector="visual_verify",
                evidence={"unreviewed_pages": missing,
                          "note": "the vision half is not skippable"}))
        for item in vision_findings:
            (hard if item["severity"] == "hard" else warn).append(item)

    # -- what did NOT run, and may acceptance still be claimed? --------------
    skipped = _skipped(expectations, pages_document, layout_raw, script_report,
                       baseline_skip, form_profile=args.form_profile,
                       xml_members=xml_members,
                       pages_document_note=pages_document_note,
                       operation_scope=operation_scope)
    not_applicable = [row for row in skipped
                      if row.get("status") == "not_applicable"]
    skipped_active = [row for row in skipped
                      if row.get("status") != "not_applicable"]
    blockers = [row for row in skipped_active
                if row["check"] in SAFETY_CHECKS
                and row["check"] not in waivers]

    # -- verdict -------------------------------------------------------------
    loop = {"attempt": args.attempt, "max_fix_attempts": args.max_fix_attempts,
            "exhausted": False}
    if hard:
        state = "fail"
    elif args.deterministic_only:
        state = "deterministic_pass"
    elif not vision["supplied"] and vision_required:
        state = "vision_pending"
    elif blockers:
        # Nothing failed — but a SAFETY check never RAN, so "accepted" would be
        # a claim about work that was not done. This is the ONLY state that can
        # turn a would-be pass into a finding, which is why it sits after the
        # states that are already not acceptances (deterministic_pass is a
        # declared smoke check; vision_pending still owes the vision half and
        # will land here on the merge run if the input is still missing).
        state = "safety_incomplete"
        hard.append(finding(
            "acceptance_safety_skipped", "hard", cls=None,
            detector="visual_verify.acceptance",
            evidence={
                "skipped_safety_checks": [row["check"] for row in blockers],
                "reasons": [f"{row['check']}: {row['reason']}"
                            for row in blockers],
                "safety_checks": list(SAFETY_CHECKS),
                "waivers": waivers,
                "note": "acceptance claims every SAFETY check RAN; supply the "
                        "missing input, or waive each one explicitly with "
                        "--accept-without CHECK (recorded in "
                        "acceptance_waivers)",
            }))
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
            "operation_scope": operation_scope,
            "dpi": args.dpi,
            "png_dir": str(png_dir),
            "rubric": RUBRIC_POINTER,
            "rubric_path": resolve_rubric(),
            "acceptance": accepted,
            "acceptance_waivers": waivers,
            "acceptance_blockers": blockers,
            "pages": [{k: v for k, v in r.items() if k != "_text"}
                      for r in records],
            "deterministic": {
                "safety_checks": list(SAFETY_CHECKS),
                "xml_members_parsed": xml_members,
                "stored_print_method": print_method,
                "pages_document": pages_document,
                "pages_document_source": pages_document_source,
                "pages_pdf": pages_pdf,
                "conversion": conversion,
                "fill_map_source": fill_map_source,
                "declared_blank": declared_blank,
                "declared_blank_source": declared_blank_sources,
                "layout_qa": layout_summary,
                "fill_charpr_script": script_report,
                "residue_keep": residue_keep,
                "delegates": delegates,
                "baseline_diff": baseline_report,
                "operation_scope": operation_scope,
                # Scope-limited fill checks are audited here, not represented
                # as waivers or ordinary skipped safety checks.
                "not_applicable_checks": sorted({row["check"] for row in
                                                   not_applicable}),
                "not_applicable_details": not_applicable,
                "skipped": [f"{row['check']}: {row['reason']}"
                            for row in skipped_active],
                "skipped_details": skipped_active,
                "skipped_checks": sorted({row["check"] for row in
                                           skipped_active}),
            },
            "vision": vision,
            "vision_required": vision_required,
            "loop": loop,
        })
    return verdict, code


def _skipped(expectations, pages_document, layout_raw, script_report=None,
             baseline_skip=None, *, form_profile=None, xml_members=None,
             pages_document_note=None, operation_scope=None):
    """What the machine half could NOT check, stated out loud.

    Returns ``[{"check": KEY, "reason": TEXT}]``. ``KEY`` is machine-readable on
    purpose: it is what the acceptance rule matches against ``SAFETY_CHECKS``
    and what ``--accept-without`` names. The verdict still publishes the flat
    ``"KEY: REASON"`` strings under ``deterministic.skipped`` — the human view
    — plus ``deterministic.skipped_checks`` for the keys alone.
    """
    out = []

    def skip(check, reason, *, status=None):
        row = {"check": check, "reason": reason}
        if status is not None:
            row["status"] = status
        out.append(row)

    if baseline_skip:
        # resolve_baseline already formats "baseline_pixel_diff: <reason>", and
        # baseline_diff.skipped carries that exact string, so split rather than
        # re-word it. Not a SAFETY check: T35 decided a renderer-less machine
        # loses the pixel diff, not the run.
        check, _, reason = baseline_skip.partition(": ")
        skip(check, reason or baseline_skip)
    if not xml_members:
        skip("xml_wellformedness",
             "no Contents/section*.xml or header.xml member was parsed (not an "
             ".hwpx, or unreadable) — T23's blank-render trap is unchecked")
    if form_profile is None:
        if operation_scope == STORY_OPERATION_SCOPE:
            skip("check_residue",
                 "not_applicable: operation_scope story_edit has no "
                 "form_profile; residue is not a form-fill claim",
                 status="not_applicable")
        else:
            skip("check_residue",
                 "no --form-profile, so the residue gate did not run: surviving "
                 "guide text, placeholders and unfilled anchors are unchecked")
    if expectations.get("fill_map") and script_report is None:
        skip("fill_charpr_script_mismatch",
             "charPr definitions were not readable (not an .hwpx, or no run "
             "carries a declared fill value) — the T30 trap is unchecked on "
             "this run")
    if pages_document is None:
        skip("page_parity",
             pages_document_note.partition(": ")[2] if pages_document_note
             else "pages_document unknown (no conversion JSON, no "
                  "expectations.pages_document and no derivable layout cache)")
    if not expectations.get("base_pt"):
        skip("format_noncompliance/base_pt", "not declared")
    if not expectations.get("line_spacing_pct"):
        skip("format_noncompliance/line_spacing", "not declared")
    if not expectations.get("margins_mm"):
        skip("format_noncompliance/margins", "not declared")
    if not expectations.get("fill_map"):
        if operation_scope == STORY_OPERATION_SCOPE:
            skip("empty_cell_expected_fill",
                 "not_applicable: operation_scope story_edit has no fill_map",
                 status="not_applicable")
            skip("fill_charpr_script_mismatch",
                 "not_applicable: operation_scope story_edit has no fill_map",
                 status="not_applicable")
        else:
            skip("empty_cell_expected_fill", "no fill_map declared")
            skip("fill_charpr_script_mismatch",
                 "no fill_map declared, so no run is known to be fill-modified "
                 "(T30)")
    if not (expectations.get("page_budget") or expectations.get("max_pages")):
        skip("page_budget_violation", "no budget declared")
    if layout_raw is None:
        skip("layout_qa", "unavailable")
    return out


def main(argv=None):
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="render->judge loop driver: deterministic backstops + "
                    "vision task preparation for "
                    "skill/references/visual-rubric.md")
    parser.add_argument("--artifact", required=True,
                        help=".hwpx/.hwp artifact, or a .pdf to judge directly")
    parser.add_argument("--pdf", default=None,
                        help="already-rendered PDF (skips conversion)")
    parser.add_argument("--conversion-record", default=None,
                        help="JSON record written by `com_backend.py convert` "
                             "proving what that conversion did (notably "
                             "print-method normalisation). Defaults to the "
                             f"<--pdf>{CONVERSION_RECORD_SUFFIX} sidecar when "
                             "present. The record must carry the sha256 of "
                             "BOTH this --artifact and this --pdf; a record "
                             "that does not match is a usage error, not a "
                             "weaker check.")
    parser.add_argument("--expectations", default=None,
                        help="JSON: pages_document, page_budget{min,max}/"
                             "max_pages, base_pt, line_spacing_pct, "
                             "margins_mm{top,bottom,left,right}, fill_map "
                             "(the same map --fill-map takes — one concept, "
                             "either surface), declared_blank (the seats you "
                             "deliberately left empty; intentionally_blank is "
                             "accepted as its alias), blank_pages, "
                             "forbidden_text, or the closed story-edit "
                             "operation_scope + required_text contract")
    parser.add_argument("--png-dir", default=None,
                        help="where page PNGs are written "
                             "(default: <pdf>_pages/ next to the PDF)")
    parser.add_argument("--dpi", type=float, default=DEFAULT_DPI,
                        help=f"page raster dpi (default {DEFAULT_DPI})")
    parser.add_argument("--baseline", default=None,
                        help="pixel-diff baseline — the BLANK FORM as .hwpx/"
                             ".hwp (converted here, serially), an "
                             "already-rendered .pdf, or a directory of page "
                             "images; reports changed-region bboxes so a "
                             "caller can assert unchanged regions stayed so. "
                             "With no renderer available an .hwpx baseline is "
                             "reported under deterministic.skipped, not failed. "
                             "An .hwpx baseline additionally supplies the T30 "
                             "seat comparison (T40), which needs no renderer: "
                             "a script/scale the blank form's own seat already "
                             "carried is a WARN, not a HARD")
    parser.add_argument("--form-profile", default=None,
                        help="form_profile.json -> also run check_residue")
    parser.add_argument("--keep", action="append", default=[],
                        help="exact anchor text check_residue must keep "
                             "(repeatable); forwarded verbatim")
    parser.add_argument("--keep-pattern", default=None,
                        help="regex for anchors that legitimately remain; "
                             "forwarded to check_residue --keep-pattern "
                             "(omitted = the checker's own default)")
    parser.add_argument("--fill-map", default=None,
                        help="JSON fill mapping ({key: value}, or an object "
                             "with a 'fill_map' member) — THE map of what was "
                             "filled, and the SAME concept as "
                             "expectations.fill_map: passing it here seeds that "
                             "member, so it drives all three consumers at once "
                             "— the form-fill keep list (anchors ∪ placeholders "
                             "minus the entries the fill targeted, instead of "
                             "hand-building repeated --keep), the declared-value "
                             "presence check (empty_cell_expected_fill) and the "
                             "T30 charPr post-flight. Declaring it on both "
                             "surfaces is fine when the maps agree; declaring "
                             "two DIFFERENT maps is a usage error")
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
    parser.add_argument("--accept-without", action="append", default=[],
                        choices=SAFETY_CHECKS, metavar="CHECK",
                        help="allow acceptance even though this SAFETY check "
                             "could not run (repeatable; closed vocabulary: "
                             + ", ".join(SAFETY_CHECKS) + "). Every waiver is "
                             "recorded in the verdict as acceptance_waivers, so "
                             "it is auditable and never implicit; without one, "
                             "a skipped SAFETY check makes the verdict "
                             "'safety_incomplete' (exit 3) instead of an "
                             "acceptance")
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
    # A refused --out must not be written to on the way out: ``verify`` already
    # turned it into the usage verdict, and handing the same bad path to
    # ``emit_verdict`` would raise over the top of that verdict.
    out = None if _out_target_error(args.out) else args.out
    try:
        return emit_verdict(verdict, code, out, create_parent=True)
    except Exception as exc:
        # EMISSION MUST NOT INVENT AN EXIT CODE. Serializing or writing the
        # verdict used to sit outside every guard, so an unwritable --out or an
        # unserializable value escaped as a traceback and process exit 1 — a
        # code this script's contract does not define, which is how the v0.17
        # clean-room sol/terra tiers saw 1 where the table says 3. Degrade to
        # the usage row (2) and say what was lost.
        fallback, usage_code = usage_error(
            str(args.artifact), "visual_verify",
            f"could not emit the verdict (it said "
            f"{verdict.get('verdict')!r}, exit {code}): "
            f"{type(exc).__name__}: {exc}")
        try:
            print(dump_json(fallback))
        except Exception:  # even the fallback must not raise
            print('{"ok": false, "checker": "visual_verify", '
                  '"verdict": "usage_error"}')
        return usage_code


if __name__ == "__main__":
    raise SystemExit(main())
