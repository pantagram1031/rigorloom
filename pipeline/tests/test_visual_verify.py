# -*- coding: utf-8 -*-
"""Rubric calibration — every real incident must be caught, or the rubric
does not ship.

Each of the four promoted render incidents gets a synthetic reproduction and
an assertion that ``visual_verify`` catches it, through the DETERMINISTIC
half where a mechanism exists and through a recorded vision verdict where
only vision can see it:

  (a) T23  malformed section XML -> Hancom renders the document blank
  (b) T24  stale ``linesegarray`` + longer replaced text -> overprint
  (c) W6.2 stored 2-up ``PrintMethod`` -> imposition / page-count mismatch
  (d) T25  missing input -> Hancom opens an empty document -> blank render
  (e) T30  a filled value inherits a charPr identical to body except for a
           trailing ``<hh:supscript/>`` -> 10pt nominal, ~6.35pt raised

plus the residue keep-list passthrough that lets a form fill reach a pass at
all (``--keep`` / ``--keep-pattern`` / ``--fill-map``), with a still-catches
control.

``INCIDENT_MATRIX`` at the bottom is the shipping gate: it records, per
incident, whether the catch is deterministic or vision-required, and the test
asserts the recorded attribution matches what the code actually does.

Fixture note: fitz's built-in CJK font has no ToUnicode map, so Korean text
inserted into a synthetic PDF does not round-trip through text extraction.
These fixtures are therefore ASCII; the mechanisms under test (page geometry,
text length, XML validity, glyph-bbox overlap, declared-value presence) are
script-independent.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "pipeline" / "scripts" / "visual_verify.py"
RUBRIC = REPO_ROOT / "skill" / "references" / "visual-rubric.md"

sys.path.insert(0, str(REPO_ROOT / "pipeline" / "scripts"))
import visual_verify  # noqa: E402


# --------------------------------------------------------------------------
# fixture generators
# --------------------------------------------------------------------------

_SECTION_OK = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
    ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
    '<hp:p id="1"><hp:run charPrIDRef="0"><hp:t>body</hp:t></hp:run>'
    '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0"/></hp:linesegarray>'
    '</hp:p></hs:sec>'
)
# T23 as it actually happened: a truncated/unclosed element that the old
# regex residue scan walked straight past while Hancom rendered blank.
_SECTION_MALFORMED = _SECTION_OK.replace("</hs:sec>", "")

_HEADER_OK = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head"'
    ' secCnt="1"/>'
)


def _settings(print_method: int) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ha:HWPApplicationSetting'
        ' xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app">'
        '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/>'
        '<config-item name="PrintMethod" type="short">'
        f'{print_method}</config-item>'
        '</ha:HWPApplicationSetting>'
    )


def make_hwpx(path: Path, *, malformed: bool = False,
              print_method: int = 0) -> Path:
    """Minimal but structurally real .hwpx (mimetype + settings + Contents)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip")
        zf.writestr("settings.xml", _settings(print_method))
        zf.writestr("Contents/header.xml", _HEADER_OK)
        zf.writestr("Contents/section0.xml",
                    _SECTION_MALFORMED if malformed else _SECTION_OK)
    return path


# -- the PPS 협업제품명 cell, reproduced -------------------------------------
#
# charPr 0 is body. charPr 7 is body PLUS a trailing <hh:supscript/> and
# nothing else: same face, same colour, same nominal height="1000". That is
# exactly the shape the live incident had, and why charpr_check --base-pt 10
# and style_diff both passed it while Hancom drew the value at ~6.35pt raised.
# charPr 8 is a legitimately superscripted footnote marker — same script flag,
# but no fill ever touched it, so the detector must leave it alone.

_CHARPR_BODY_ATTRS = (
    ' height="1000" textColor="#000000" shadeColor="none"'
    ' useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="0"'
)
_CHARPR_BODY_CHILDREN = (
    '<hh:fontRef hangul="0" latin="0"/>'
    '<hh:ratio hangul="100" latin="100"/>'
    '<hh:spacing hangul="0" latin="0"/>'
    '<hh:relSz hangul="100" latin="100"/>'
    '<hh:offset hangul="0" latin="0"/>'
)


def _charpr(identifier: int, extra: str = "") -> str:
    return (f'<hh:charPr id="{identifier}"{_CHARPR_BODY_ATTRS}>'
            f'{_CHARPR_BODY_CHILDREN}{extra}</hh:charPr>')


_FORM_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" secCnt="1">'
    '<hh:refList><hh:charProperties itemCnt="3">'
    + _charpr(0)
    + _charpr(7, "<hh:supscript/>")      # the trap
    + _charpr(8, "<hh:supscript/>")      # a real footnote marker
    + '</hh:charProperties></hh:refList></hh:head>'
)


def _run(charpr: int, text: str) -> str:
    return f'<hp:run charPrIDRef="{charpr}"><hp:t>{text}</hp:t></hp:run>'


def make_form_hwpx(path: Path, *, value_charpr: int = 0,
                   value: str = "RIGORLOOM-A1",
                   footnote: bool = True,
                   residue: tuple[str, ...] = ()) -> Path:
    """A filled PPS-shaped form: a label cell, a value cell, body prose.

    ``value_charpr=7`` reproduces the incident (the value inherited the
    superscript clone); ``0`` is the clean control. ``footnote`` adds a
    genuinely superscripted marker that no fill produced.
    """
    body = " ".join(
        f"본문 문장 {i} 은 표준 서식으로 작성한 일반 서술 문단입니다."
        for i in range(6))
    cells = (
        '<hp:tbl id="20" rowCnt="1" colCnt="2">'
        '<hp:tr><hp:tc><hp:subList><hp:p id="10">'
        + _run(0, "협업제품명")
        + '</hp:p></hp:subList></hp:tc>'
        '<hp:tc><hp:subList><hp:p id="11">'
        + _run(value_charpr, value)
        + '</hp:p></hp:subList></hp:tc></hp:tr></hp:tbl>'
    )
    marker = (f'<hp:p id="12">{_run(0, "각주 대상 문구")}'
              f'{_run(8, "1)")}</hp:p>') if footnote else ""
    leftovers = "".join(f'<hp:p id="{20 + i}">{_run(0, text)}</hp:p>'
                        for i, text in enumerate(residue))
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
        ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        f'<hp:p id="1">{_run(0, "I.  서론")}</hp:p>'
        f'<hp:p id="2">{_run(0, "신청인")}</hp:p>'
        f'<hp:p id="3">{_run(0, "[별지 제2호의 8서식]")}</hp:p>'
        f'<hp:p id="4">{cells}</hp:p>'
        f'<hp:p id="5">{_run(0, body)}</hp:p>'
        f'{marker}{leftovers}'
        '</hs:sec>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip")
        zf.writestr("settings.xml", _settings(0))
        zf.writestr("Contents/header.xml", _FORM_HEADER)
        zf.writestr("Contents/section0.xml", section)
    return path


#: The form scan inventory the residue gate auto-derives its forbidden list
#: from. ``20101`` is the placeholder the fill consumes; the bracketed 서식
#: label is a placeholder that legitimately SURVIVES a fill (form-eval A1).
FORM_PROFILE = {
    "form_hash": "sha256:synthetic",
    "anchors": ["협업제품명", "신청인", "I.  서론"],
    "guide_text": ["여기에 입력하세요"],
    "placeholders": ["[별지 제2호의 8서식]", "20101"],
}


def write_form_profile(path: Path) -> Path:
    path.write_text(json.dumps(FORM_PROFILE, ensure_ascii=False),
                    encoding="utf-8")
    return path


def make_pdf(path: Path, pages) -> Path:
    """pages = [ {width, height, lines:[(x, y, text, size)]} , ...]."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for spec in pages:
        page = doc.new_page(width=spec.get("width", 595),
                            height=spec.get("height", 842))
        for x, y, text, size in spec.get("lines", []):
            page.insert_text((x, y), text, fontsize=size)
    doc.save(str(path))
    doc.close()
    return path


def _body_page(n_lines: int = 20, size: float = 10.0, start_y: float = 90.0,
               pitch: float = 16.0, prefix: str = "line"):
    return {"lines": [(72.0, start_y + i * pitch,
                       f"{prefix} {i} of a perfectly ordinary body paragraph",
                       size)
                      for i in range(n_lines)]}


def run(*argv):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *[str(a) for a in argv]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT))
    payload = None
    text = (proc.stdout or "")
    brace = text.find("{")
    if brace >= 0:
        try:
            payload = json.loads(text[brace:])
        except ValueError:
            payload = None
    return proc.returncode, payload, proc.stderr


def codes(verdict, bucket="hard"):
    return sorted(f["code"] for f in verdict[bucket])


def classes(verdict, bucket="hard"):
    return sorted({f["class"] for f in verdict[bucket] if f["class"]})


# --------------------------------------------------------------------------
# (a) T23 — malformed XML renders blank
# --------------------------------------------------------------------------

def test_incident_t23_malformed_xml_blank_render(tmp_path):
    artifact = make_hwpx(tmp_path / "t23.hwpx", malformed=True)
    pdf = make_pdf(tmp_path / "t23.pdf", [{"lines": []}])

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert "artifact_malformed" in codes(verdict)
    assert "blank_render" in codes(verdict)

    malformed = [f for f in verdict["hard"] if f["code"] == "artifact_malformed"]
    assert malformed[0]["detector"] == "visual_verify.xml_parse"
    assert malformed[0]["member"] == "Contents/section0.xml"
    # DETERMINISTIC: caught with no vision verdict supplied at all.
    assert verdict["vision"]["supplied"] is False
    assert "Contents/header.xml" in verdict["deterministic"]["xml_members_parsed"]


def test_t23_wellformed_artifact_is_not_flagged(tmp_path):
    """False-positive guard: a valid artifact never trips artifact_malformed."""
    artifact = make_hwpx(tmp_path / "ok.hwpx")
    pdf = make_pdf(tmp_path / "ok.pdf", [_body_page()])
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert verdict["hard"] == []


# --------------------------------------------------------------------------
# (b) T24 — stale lineseg overprint (vision-required, deterministically targeted)
# --------------------------------------------------------------------------

_LONG_TITLE = ("A seventy four character replacement title that no longer "
               "fits the cached layout")


def _overprint_pdf(path):
    """Page 2 reproduces T24: the long replacement title is drawn at the
    short placeholder's cached coordinates, so two text layers collide."""
    clean = _body_page()
    collided = {"lines": [
        (72.0, 100.0, _LONG_TITLE, 14.0),
        (72.0, 101.5, "Placeholder title", 14.0),
        (72.0, 103.0, _LONG_TITLE[:40], 14.0),
        *[(72.0, 160.0 + i * 16.0, f"body line {i}", 10.0) for i in range(12)],
    ]}
    return make_pdf(path, [clean, collided, clean])


def test_incident_t24_overprint_is_vision_required_and_targeted(tmp_path):
    artifact = make_hwpx(tmp_path / "t24.hwpx")
    pdf = _overprint_pdf(tmp_path / "t24.pdf")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png")
    # The machine half must NOT claim the class — it cannot see overprint.
    assert "overprint" not in classes(verdict)
    # ...but it must TARGET the page, first in the queue, with the reason.
    task = verdict["vision_required"]
    assert task, verdict
    assert task[0]["page"] == 2
    assert "overprint_suspected" in task[0]["reasons"]
    assert Path(task[0]["png"]).is_file()
    assert task[0]["rubric"] == "skill/references/visual-rubric.md"
    # Clean pages carry no overprint suspicion.
    for entry in task[1:]:
        assert "overprint_suspected" not in entry["reasons"]
    # No vision verdict => not accepted. The vision half is not skippable.
    assert verdict["verdict"] == "vision_pending"
    assert verdict["acceptance"] is False
    assert code == 3


def test_incident_t24_recorded_vision_verdict_expresses_the_defect(tmp_path):
    """The rubric's vocabulary must be able to SAY what page 2 shows."""
    artifact = make_hwpx(tmp_path / "t24.hwpx")
    pdf = _overprint_pdf(tmp_path / "t24.pdf")
    _, prepared, _ = run("--artifact", artifact, "--pdf", pdf,
                         "--png-dir", tmp_path / "png")

    recorded = {
        "schema": "rigorloom/visual-vision-verdict/v1",
        "rubric": "skill/references/visual-rubric.md",
        "pages_reviewed": [t["page"] for t in prepared["vision_required"]],
        "findings": [{
            "page": 2, "class": "overprint", "severity": "hard",
            "evidence": ("title band y~100pt: three text layers interleaved, "
                         "unreadable; long replacement title drawn over the "
                         "short placeholder's cached layout (stale lineseg, "
                         "T24)"),
        }],
    }
    vision = tmp_path / "vision.json"
    vision.write_text(json.dumps(recorded, ensure_ascii=False),
                      encoding="utf-8")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--vision-verdict", vision)
    assert code == 3, verdict
    assert verdict["verdict"] == "fail"
    merged = [f for f in verdict["hard"] if f["class"] == "overprint"]
    assert len(merged) == 1
    assert merged[0]["page"] == 2
    assert merged[0]["detector"] == "vision"
    assert "vision_incomplete" not in codes(verdict)


# --------------------------------------------------------------------------
# (c) stale-lineseg / imposition class — the W6.2 nrf mechanism as a fixture
# --------------------------------------------------------------------------

def test_incident_imposition_2up_page_count_mismatch(tmp_path):
    """nrf reproduction: the source stores PrintMethod=4, the export imposes
    two portrait pages per landscape sheet, 4 document pages become 2."""
    artifact = make_hwpx(tmp_path / "nrf.hwpx", print_method=4)
    pdf = make_pdf(tmp_path / "nrf.pdf", [
        {"width": 842, "height": 595, **_body_page(n_lines=10)},
        {"width": 842, "height": 595, **_body_page(n_lines=10)},
    ])
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"pages_document": 4}),
                            encoding="utf-8")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert "imposition_mismatch" in classes(verdict)
    detectors = {f["detector"] for f in verdict["hard"]
                 if f["class"] == "imposition_mismatch"}
    # BOTH legs of the W6.2 mechanism fire.
    assert detectors == {"visual_verify.print_method",
                         "visual_verify.page_parity"}
    assert verdict["deterministic"]["stored_print_method"] == 4
    assert verdict["deterministic"]["pages_document"] == 4
    assert verdict["deterministic"]["pages_pdf"] == 2
    assert "imposition_mismatch" in classes(verdict, "warn")  # orientation


def test_imposition_false_positive_guard_native_landscape(tmp_path):
    """A genuinely landscape form with PrintMethod=0 and matching page counts
    is NOT an imposition finding."""
    artifact = make_hwpx(tmp_path / "wide.hwpx", print_method=0)
    pdf = make_pdf(tmp_path / "wide.pdf", [
        {"width": 842, "height": 595, **_body_page(n_lines=10)},
    ])
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"pages_document": 1}),
                            encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert verdict["hard"] == []


# --------------------------------------------------------------------------
# (d) T25 — missing input, Hancom opens an empty document
# --------------------------------------------------------------------------

def test_incident_t25_missing_input_blank_render(tmp_path):
    artifact = make_hwpx(tmp_path / "t25.hwpx")   # artifact itself is fine
    pdf = make_pdf(tmp_path / "t25.pdf", [{"lines": []}, {"lines": []}])

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    blank = [f for f in verdict["hard"] if f["code"] == "blank_render"]
    assert blank, verdict
    assert blank[0]["detector"] == "visual_verify.text_length"
    # T25 is distinguishable from T23: the artifact parsed fine.
    assert "artifact_malformed" not in codes(verdict)


def test_blank_page_declared_is_not_a_finding(tmp_path):
    """False-positive guard: a declared blank continuation sheet is fine."""
    artifact = make_hwpx(tmp_path / "ok.hwpx")
    pdf = make_pdf(tmp_path / "ok.pdf", [_body_page(), {"lines": []}])
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"blank_pages": [2]}), encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert verdict["hard"] == []


# --------------------------------------------------------------------------
# the rest of the deterministic half
# --------------------------------------------------------------------------

def test_page_budget_and_format_and_fill_map(tmp_path):
    artifact = make_hwpx(tmp_path / "a.hwpx")
    pdf = make_pdf(tmp_path / "a.pdf", [_body_page(size=14.0),
                                        _body_page(size=14.0),
                                        _body_page(size=14.0)])
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({
        "page_budget": {"max": 2},
        "base_pt": 10.0,
        "fill_map": {"applicant": "Hong Gildong", "date": "2026-08-08"},
        "intentionally_blank": ["date"],
    }), encoding="utf-8")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    found = classes(verdict)
    assert "page_budget_violation" in found
    assert "format_noncompliance" in found
    assert "empty_cell_expected_fill" in found
    # intentionally_blank suppresses its own label, and only its own.
    labels = {f["evidence"]["label"] for f in verdict["hard"]
              if f["class"] == "empty_cell_expected_fill"}
    assert labels == {"applicant"}
    # a fill_map was declared but this artifact carries no charPr table, so
    # the T30 check could not run — and says so instead of reading as clean.
    assert any("fill_charpr_script_mismatch" in row
               for row in verdict["deterministic"]["skipped"])


def test_forbidden_text_is_guide_text_visible(tmp_path):
    artifact = make_hwpx(tmp_path / "g.hwpx")
    page = _body_page(n_lines=5)
    page["lines"].append((72.0, 300.0, "Enter your answer here", 10.0))
    pdf = make_pdf(tmp_path / "g.pdf", [page])
    expectations = tmp_path / "exp.json"
    expectations.write_text(
        json.dumps({"forbidden_text": ["Enter your answer here"]}),
        encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert "guide_text_visible" in classes(verdict)


def test_pixel_diff_reports_changed_region_bboxes(tmp_path):
    artifact = make_hwpx(tmp_path / "b.hwpx")
    base = make_pdf(tmp_path / "base.pdf", [_body_page(n_lines=6)])
    changed = _body_page(n_lines=6)
    changed["lines"].append((72.0, 400.0, "an inserted extra line", 10.0))
    after = make_pdf(tmp_path / "after.pdf", [changed])

    code, verdict, _ = run("--artifact", artifact, "--pdf", after,
                           "--baseline", base, "--png-dir", tmp_path / "png")
    diff = verdict["deterministic"]["baseline_diff"]
    assert diff["baseline_pages"] == 1
    page = diff["pages"][0]
    assert page["comparable"] is True
    boxes = page["changed_regions"]
    assert boxes, "the inserted line must show up as a changed region"
    # Everything above the insertion stayed byte-identical.
    dpi_scale = 130 / 72.0
    assert min(b[1] for b in boxes) > 380 * dpi_scale
    assert code == 3  # vision still pending, by design


def test_pixel_diff_identical_render_has_no_changed_regions(tmp_path):
    artifact = make_hwpx(tmp_path / "b.hwpx")
    pdf = make_pdf(tmp_path / "same.pdf", [_body_page(n_lines=6)])
    _, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                        "--baseline", pdf, "--png-dir", tmp_path / "png")
    page = verdict["deterministic"]["baseline_diff"]["pages"][0]
    assert page["comparable"] is True
    assert page["changed_regions"] == []


# --------------------------------------------------------------------------
# (e) T30 — a fill-modified run inherits a script the body does not use
# --------------------------------------------------------------------------

_FILL_VALUE = "RIGORLOOM-A1"


def _fill_pdf(path: Path) -> Path:
    """A render carrying the declared value, so only the charPr check can
    fire — the fill-map presence check must stay green."""
    page = _body_page(n_lines=8)
    page["lines"].append((72.0, 300.0, _FILL_VALUE, 10.0))
    return make_pdf(path, [page])


def _fill_expectations(path: Path) -> Path:
    path.write_text(json.dumps({"fill_map": {"협업제품명": _FILL_VALUE}},
                               ensure_ascii=False), encoding="utf-8")
    return path


def test_incident_t30_superscript_inheritance_is_deterministic(tmp_path):
    """The live PPS trap: the filled 협업제품명 value inherited a charPr that
    differs from body ONLY by a trailing <hh:supscript/>. Nominal height is
    unchanged, so charpr_check/style_diff pass — this check must not."""
    artifact = make_form_hwpx(tmp_path / "t30.hwpx", value_charpr=7)
    pdf = _fill_pdf(tmp_path / "t30.pdf")
    expectations = _fill_expectations(tmp_path / "exp.json")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    hits = [f for f in verdict["hard"]
            if f["code"] == "fill_charpr_script_mismatch"]
    assert len(hits) == 1, verdict["hard"]
    hit = hits[0]
    assert hit["class"] == "format_noncompliance"
    assert hit["detector"] == "visual_verify.fill_charpr_script"
    evidence = hit["evidence"]
    assert evidence["label"] == "협업제품명"
    assert evidence["charpr_id"] == "7"
    assert evidence["baseline_charpr_id"] == "0"
    assert evidence["differing"] == ["supscript"]
    assert evidence["nominal_height_pt"] == 10.0
    # the point of the incident: 10pt nominal, ~6.35pt rendered
    assert evidence["rendered_pt_estimate"] == pytest.approx(6.35, abs=0.01)
    # DETERMINISTIC: no vision verdict was supplied at all.
    assert verdict["vision"]["supplied"] is False
    # and the height-based proofs really do miss it
    assert "format_noncompliance" not in {
        f["class"] for f in verdict["hard"]
        if f["detector"] == "visual_verify.base_pt"}


def test_t30_false_positive_guard_intentional_superscript_footnote(tmp_path):
    """Scope guard: the same document keeps a genuinely superscripted footnote
    marker (charPr 8). No fill produced it, so it must NOT be flagged."""
    artifact = make_form_hwpx(tmp_path / "clean.hwpx", value_charpr=0)
    pdf = _fill_pdf(tmp_path / "clean.pdf")
    expectations = _fill_expectations(tmp_path / "exp.json")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert verdict["hard"] == []
    report = verdict["deterministic"]["fill_charpr_script"]
    # the check actually ran, found the baseline, and cleared the document
    assert report["baseline_charpr_id"] == "0"
    assert report["fill_modified_runs"] == 1
    assert report["findings"] == 0
    assert report["baseline"]["supscript"] is False


def test_t30_scaling_and_offset_inheritance_also_count(tmp_path):
    """The trap is not superscript-specific: ratio/relSz/offset move or resize
    a run with the nominal height untouched too."""
    header = _FORM_HEADER.replace(
        _charpr(7, "<hh:supscript/>"),
        _charpr(7).replace('<hh:relSz hangul="100" latin="100"/>',
                           '<hh:relSz hangul="65" latin="65"/>'))
    artifact = make_form_hwpx(tmp_path / "scaled.hwpx", value_charpr=7)
    with zipfile.ZipFile(artifact) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    members["Contents/header.xml"] = header.encode("utf-8")
    with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)

    pdf = _fill_pdf(tmp_path / "scaled.pdf")
    expectations = _fill_expectations(tmp_path / "exp.json")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    hits = [f for f in verdict["hard"]
            if f["code"] == "fill_charpr_script_mismatch"]
    assert len(hits) == 1
    assert hits[0]["evidence"]["differing"] == ["relSz"]
    assert hits[0]["evidence"]["run"]["relSz"] == {"hangul": "65",
                                                   "latin": "65"}
    # no script flag involved, so no rendered-pt estimate is claimed
    assert "rendered_pt_estimate" not in hits[0]["evidence"]


def test_t30_is_skipped_out_loud_without_a_fill_map(tmp_path):
    artifact = make_form_hwpx(tmp_path / "nofill.hwpx", value_charpr=7)
    pdf = _fill_pdf(tmp_path / "nofill.pdf")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert verdict["deterministic"]["fill_charpr_script"] is None
    assert any("fill_charpr_script_mismatch" in row
               for row in verdict["deterministic"]["skipped"])


# --------------------------------------------------------------------------
# (f) the residue keep-list passthrough — a form fill must be able to pass
# --------------------------------------------------------------------------

_FILL_MAP = {"20101": _FILL_VALUE}


def _fill_map_file(path: Path) -> Path:
    path.write_text(json.dumps(_FILL_MAP, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _residue_delegate(verdict):
    return next(d for d in verdict["deterministic"]["delegates"]
                if d["checker"] == "check_residue")


def test_form_fill_without_a_keep_list_cannot_pass(tmp_path):
    """The defect both clean-room agents hit: with no way to forward a keep
    list, every surviving legitimate anchor reads as residue."""
    artifact = make_form_hwpx(tmp_path / "filled.hwpx")
    pdf = _fill_pdf(tmp_path / "filled.pdf")
    profile = write_form_profile(tmp_path / "profile.json")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert "check_residue_hard" in codes(verdict)
    residue = _residue_delegate(verdict)
    assert residue["exit"] == 3
    surviving = {row["at"] for row in residue["hard"]}
    assert "협업제품명" in surviving          # a label, not residue
    assert "[별지 제2호의 8서식]" in surviving  # survives a legitimate fill
    assert verdict["deterministic"]["residue_keep"] == {
        "explicit_keep": [], "keep_pattern": None, "derived_keep": [],
        "consumed": [], "unfilled": [], "fill_map": None, "keep_total": 0}


def test_form_fill_passes_with_the_derived_keep_list(tmp_path):
    """--fill-map derives (anchors ∪ placeholders) − consumed for the caller."""
    artifact = make_form_hwpx(tmp_path / "filled.hwpx")
    pdf = _fill_pdf(tmp_path / "filled.pdf")
    profile = write_form_profile(tmp_path / "profile.json")
    fill_map = _fill_map_file(tmp_path / "map.json")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile,
                           "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert verdict["hard"] == []
    assert _residue_delegate(verdict)["exit"] == 0
    keep = verdict["deterministic"]["residue_keep"]
    assert keep["consumed"] == ["20101"]
    assert set(keep["derived_keep"]) == {
        "협업제품명", "신청인", "I.  서론", "[별지 제2호의 8서식]"}
    # guide text is never keepable — instruction prose must not survive a fill
    assert "여기에 입력하세요" not in keep["derived_keep"]


def test_derived_keep_list_still_catches_real_residue(tmp_path):
    """Still-catches: the same derived keep list must fail an artifact where
    the consumed placeholder and the guide text survived."""
    artifact = make_form_hwpx(
        tmp_path / "bad.hwpx",
        residue=("20101", "여기에 입력하세요"))
    pdf = _fill_pdf(tmp_path / "bad.pdf")
    profile = write_form_profile(tmp_path / "profile.json")
    fill_map = _fill_map_file(tmp_path / "map.json")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile,
                           "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    residue = _residue_delegate(verdict)
    assert residue["exit"] == 3
    assert {row["at"] for row in residue["hard"]} == {
        "20101", "여기에 입력하세요"}


def test_explicit_keep_and_keep_pattern_are_forwarded(tmp_path):
    """The hand-built path stays available and composes with the derivation."""
    artifact = make_form_hwpx(tmp_path / "filled.hwpx")
    pdf = _fill_pdf(tmp_path / "filled.pdf")
    profile = write_form_profile(tmp_path / "profile.json")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile,
                           "--keep", "협업제품명",
                           "--keep", "신청인",
                           "--keep", "[별지 제2호의 8서식]",
                           "--keep", "20101",
                           "--keep-pattern", r"^[IVX]+\.",
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    keep = verdict["deterministic"]["residue_keep"]
    assert keep["keep_pattern"] == r"^[IVX]+\."
    assert keep["keep_total"] == 4
    assert keep["derived_keep"] == []
    assert _residue_delegate(verdict)["exit"] == 0


def test_keep_derivation_unit(tmp_path):
    keep, consumed, unfilled = visual_verify.derive_form_keep(
        FORM_PROFILE, _FILL_MAP)
    assert consumed == ["20101"]
    assert unfilled == []
    assert keep == ["협업제품명", "신청인", "I.  서론", "[별지 제2호의 8서식]"]
    # whitespace-normalized substring match, in both directions
    keep2, consumed2, _ = visual_verify.derive_form_keep(
        FORM_PROFILE, {"작성자 신청인 성명": "홍길동"})
    assert consumed2 == ["신청인"]
    assert "신청인" not in keep2


def test_fill_map_accepts_an_expectations_shaped_file(tmp_path):
    path = tmp_path / "exp.json"
    path.write_text(json.dumps({"fill_map": _FILL_MAP, "base_pt": 10},
                               ensure_ascii=False), encoding="utf-8")
    mapping, error = visual_verify.load_fill_map(path)
    assert error is None
    assert mapping == _FILL_MAP


def test_keep_flags_without_a_form_profile_are_a_usage_error(tmp_path):
    artifact = make_form_hwpx(tmp_path / "filled.hwpx")
    pdf = _fill_pdf(tmp_path / "filled.pdf")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--keep", "협업제품명",
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert verdict["verdict"] == "usage_error"
    assert "--form-profile" in verdict["error"]


def test_unreadable_fill_map_is_a_usage_error(tmp_path):
    artifact = make_form_hwpx(tmp_path / "filled.hwpx")
    pdf = _fill_pdf(tmp_path / "filled.pdf")
    profile = write_form_profile(tmp_path / "profile.json")
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile, "--fill-map", bad,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "--fill-map" in verdict["error"]


# --------------------------------------------------------------------------
# (g) T31 — a prefix-preserving fill is the NORMAL shape of a labeled field
#
# Filling a labeled field semantically means keeping the label as a prefix:
# a URL field goes " http://" -> " http://host", a zip field keeps its
# " 우(     -     )" skeleton and appends the address. The first derivation
# assumed the key TEXT VANISHES, so the surviving prefix read as form_residue
# and a CORRECT fill could not pass — the second clean-room run lost a retry
# to it and hand-built --keep instead.
# --------------------------------------------------------------------------

_URL_KEY = " http://"
_URL_VALUE = " http://hanbit-precision.example.kr"
_ZIP_KEY = " 우(     -     )"
_ZIP_VALUE = " 우(     -     ) 서울특별시 중구 세종대로 110"

LABELED_PROFILE = {
    "form_hash": "sha256:synthetic-labeled",
    "anchors": ["기관명", "I.  서론"],
    "guide_text": ["여기에 입력하세요"],
    "placeholders": [_URL_KEY, _ZIP_KEY],
}
_LABELED_MAP = {_URL_KEY: _URL_VALUE, _ZIP_KEY: _ZIP_VALUE}


def make_labeled_form_hwpx(path: Path, *, url: str = _URL_VALUE,
                           zip_line: str = _ZIP_VALUE,
                           trailing: tuple[str, ...] = ()) -> Path:
    """A filled labeled-field form: label-prefixed values, then body prose.

    ``trailing`` paragraphs land AFTER the body block on purpose — a second
    occurrence of a key has to be far enough from the filled one that the
    reported context cannot be confused for it.
    """
    body = " ".join(f"본문 문장 {i} 은 표준 서식으로 작성한 일반 서술 문단입니다."
                    for i in range(6))
    paragraphs = [
        _run(0, "I.  서론"),
        _run(0, "기관명") + _run(0, " 한빛정밀"),
        _run(0, "누리집") + _run(0, url),
        _run(0, "주소") + _run(0, zip_line),
        _run(0, body),
        *[_run(0, text) for text in trailing],
    ]
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
        ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        + "".join(f'<hp:p id="{i + 1}">{p}</hp:p>'
                  for i, p in enumerate(paragraphs))
        + '</hs:sec>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip")
        zf.writestr("settings.xml", _settings(0))
        zf.writestr("Contents/header.xml", _FORM_HEADER)
        zf.writestr("Contents/section0.xml", section)
    return path


def _labeled(tmp_path: Path, *, mapping=None, **kwargs):
    """(artifact, pdf, profile, fill_map) for one labeled-form run."""
    artifact = make_labeled_form_hwpx(tmp_path / "labeled.hwpx", **kwargs)
    pdf = make_pdf(tmp_path / "labeled.pdf", [_body_page(n_lines=8)])
    profile = tmp_path / "labeled_profile.json"
    profile.write_text(json.dumps(LABELED_PROFILE, ensure_ascii=False),
                       encoding="utf-8")
    fill_map = tmp_path / "labeled_map.json"
    fill_map.write_text(
        json.dumps(_LABELED_MAP if mapping is None else mapping,
                   ensure_ascii=False), encoding="utf-8")
    return artifact, pdf, profile, fill_map


def _residue_hard(verdict, code="form_residue"):
    return [row for row in _residue_delegate(verdict)["hard"]
            if row["code"] == code]


def test_t31_prefix_preserving_fill_passes_with_only_a_fill_map(tmp_path):
    """The regression: no manual --keep, and a correct fill must pass."""
    artifact, pdf, profile, fill_map = _labeled(tmp_path)

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile, "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert verdict["hard"] == []
    assert _residue_delegate(verdict)["exit"] == 0
    keep = verdict["deterministic"]["residue_keep"]
    # the labels the fill targeted are CONSUMED (their values landed), not
    # keep-listed — the surviving prefix is attributed to the value's span
    assert keep["consumed"] == [_URL_KEY, _ZIP_KEY]
    assert keep["unfilled"] == []
    assert set(keep["derived_keep"]) == {"기관명", "I.  서론"}


def test_t31_still_catches_a_key_that_was_never_filled(tmp_path):
    """Still-catches: the SAME map, but the zip field kept its bare skeleton
    and its value is nowhere in the document."""
    artifact, pdf, profile, fill_map = _labeled(tmp_path, zip_line=_ZIP_KEY)

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile, "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert _residue_delegate(verdict)["exit"] == 3
    assert {row["at"] for row in _residue_hard(verdict)} == {_ZIP_KEY}
    keep = verdict["deterministic"]["residue_keep"]
    assert keep["unfilled"] == [_ZIP_KEY]
    assert keep["consumed"] == [_URL_KEY]


def test_t31_still_catches_a_second_unfilled_occurrence(tmp_path):
    """Still-catches, the one a global keep-string would swallow: the URL
    value landed once, and the same key ALSO sits at a second, untouched
    field. Attribution is per occurrence, so that location must flag."""
    artifact, pdf, profile, fill_map = _labeled(
        tmp_path, trailing=(f"보조 누리집{_URL_KEY}",))

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile, "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    rows = _residue_hard(verdict)
    assert [row["at"] for row in rows] == [_URL_KEY]
    row = rows[0]
    assert len(row["at_offsets"]) == 1
    assert "1 of 2" in row["msg"]
    # the finding names the UNFILLED location, not the filled one
    assert "보조 누리집" in row["context"]
    assert "hanbit-precision" not in row["context"]
    # the derivation still reports the fill as consumed — it did land once
    assert verdict["deterministic"]["residue_keep"]["consumed"] == [
        _URL_KEY, _ZIP_KEY]


def test_t31_whitespace_normalization_boundary(tmp_path):
    """The skeleton's internal spacing in the document is not the spacing the
    map declares (5 spaces in the form, 2 in the reflowed document): matching
    is whitespace-normalized on BOTH sides, so this is still a consumed fill.
    A raw substring comparison flags it."""
    reflowed = " 우(  -  ) 서울특별시 중구 세종대로 110"
    assert _ZIP_KEY not in reflowed, "the raw prefix must NOT survive verbatim"
    artifact, pdf, profile, fill_map = _labeled(tmp_path, zip_line=reflowed)

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile, "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert _residue_delegate(verdict)["exit"] == 0
    assert verdict["deterministic"]["residue_keep"]["unfilled"] == []


def test_t31_whitespace_boundary_still_catches_an_unfilled_skeleton(tmp_path):
    """The same reflowed spacing, with nothing appended: still residue."""
    artifact, pdf, profile, fill_map = _labeled(
        tmp_path, zip_line=" 우(  -  )")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile, "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert {row["at"] for row in _residue_hard(verdict)} == {_ZIP_KEY}


def test_t31_derivation_unit_falls_back_to_key_absence(tmp_path):
    """No value anywhere and the key gone too: consumed, nothing to flag.
    The same map with the key still present: unfilled, so the gate flags it."""
    keep, consumed, unfilled = visual_verify.derive_form_keep(
        LABELED_PROFILE, _LABELED_MAP, "기관명 한빛정밀 I.  서론 본문")
    assert consumed == [_URL_KEY, _ZIP_KEY]     # both keys are simply gone
    assert unfilled == []
    keep, consumed, unfilled = visual_verify.derive_form_keep(
        LABELED_PROFILE, _LABELED_MAP, "기관명 http:// 본문")
    assert consumed == [_ZIP_KEY]
    assert unfilled == [_URL_KEY]
    assert "기관명" in keep


# --------------------------------------------------------------------------
# the vision contract
# --------------------------------------------------------------------------

def _clean_run(tmp_path):
    artifact = make_hwpx(tmp_path / "c.hwpx")
    pdf = make_pdf(tmp_path / "c.pdf", [_body_page(), _body_page()])
    return artifact, pdf


def test_clean_artifact_passes_only_with_the_vision_half(tmp_path):
    artifact, pdf = _clean_run(tmp_path)

    code, pending, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png")
    assert code == 3
    assert pending["verdict"] == "vision_pending"
    assert [t["page"] for t in pending["vision_required"]] == [1, 2]

    vision = tmp_path / "v.json"
    vision.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": [1, 2], "findings": []}), encoding="utf-8")
    code, accepted, _ = run("--artifact", artifact, "--pdf", pdf,
                            "--png-dir", tmp_path / "png",
                            "--vision-verdict", vision)
    assert code == 0, accepted
    assert accepted["verdict"] == "pass"
    assert accepted["acceptance"] is True


def test_deterministic_only_is_never_an_acceptance(tmp_path):
    artifact, pdf = _clean_run(tmp_path)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0
    assert verdict["verdict"] == "deterministic_pass"
    assert verdict["acceptance"] is False
    assert verdict["vision_required"], "the vision task is still owed"


def test_unreviewed_page_is_vision_incomplete(tmp_path):
    artifact, pdf = _clean_run(tmp_path)
    vision = tmp_path / "v.json"
    vision.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": [1], "findings": []}), encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--vision-verdict", vision)
    assert code == 3
    incomplete = [f for f in verdict["hard"] if f["code"] == "vision_incomplete"]
    assert incomplete and incomplete[0]["evidence"]["unreviewed_pages"] == [2]


@pytest.mark.parametrize("bad", [
    {"page": 1, "class": "looks_bad", "severity": "hard"},
    {"page": 1, "class": "overprint", "severity": "catastrophic"},
    {"page": 99, "class": "overprint", "severity": "hard"},
])
def test_vision_verdict_vocabulary_is_closed(tmp_path, bad):
    artifact, pdf = _clean_run(tmp_path)
    vision = tmp_path / "v.json"
    vision.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": [1, 2], "findings": [bad]}), encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--vision-verdict", vision)
    assert code == 2, verdict
    assert verdict["verdict"] == "usage_error"


def test_every_rubric_class_is_accepted_from_vision(tmp_path):
    """The closed vocabulary is exactly the rubric's, in both directions."""
    artifact, pdf = _clean_run(tmp_path)
    vision = tmp_path / "v.json"
    vision.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": [1, 2],
        "findings": [{"page": 1, "class": cls, "severity": "warn",
                      "evidence": "synthetic"}
                     for cls in visual_verify.RUBRIC_CLASSES]}),
        encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--vision-verdict", vision)
    assert code == 0, verdict
    assert set(classes(verdict, "warn")) >= set(visual_verify.RUBRIC_CLASSES)


def test_rubric_document_and_code_vocabulary_agree():
    text = RUBRIC.read_text(encoding="utf-8")
    documented = set()
    for line in text.splitlines():
        if line.startswith("| `") and "|" in line[3:]:
            documented.add(line.split("`")[1])
    assert documented == set(visual_verify.RUBRIC_CLASSES), (
        "rubric §1 class table and visual_verify.RUBRIC_CLASSES drifted: "
        f"doc-only={sorted(documented - set(visual_verify.RUBRIC_CLASSES))} "
        f"code-only={sorted(set(visual_verify.RUBRIC_CLASSES) - documented)}")


# --------------------------------------------------------------------------
# loop control + usage
# --------------------------------------------------------------------------

def test_max_fix_attempts_escalates_instead_of_grinding(tmp_path):
    artifact = make_hwpx(tmp_path / "t25.hwpx")
    pdf = make_pdf(tmp_path / "t25.pdf", [{"lines": []}])
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--attempt", 3, "--max-fix-attempts", 3)
    assert code == 3
    assert verdict["loop"] == {"attempt": 3, "max_fix_attempts": 3,
                               "exhausted": True}
    assert "loop_exhausted" in codes(verdict)


def test_missing_artifact_is_usage_error(tmp_path):
    code, verdict, _ = run("--artifact", tmp_path / "nope.hwpx")
    assert code == 2
    assert verdict["verdict"] == "usage_error"


def test_no_pdf_and_no_renderer_is_usage_error_not_a_pass(tmp_path, monkeypatch):
    """A loop that cannot render must never report a pass."""
    artifact = make_hwpx(tmp_path / "x.hwpx")
    monkeypatch.setattr(visual_verify, "_ENGINE_SCRIPTS",
                        tmp_path / "no-engine-here")
    args = type("A", (), {
        "artifact": str(artifact), "pdf": None, "expectations": None,
        "png_dir": str(tmp_path / "png"), "dpi": 130, "baseline": None,
        "form_profile": None, "content": None, "vision_verdict": None,
        "vision_scope": "all", "deterministic_only": False,
        "keep": [], "keep_pattern": None, "fill_map": None,
        "attempt": None, "max_fix_attempts": None, "out": None})()
    verdict, code = visual_verify.verify(args)
    assert code == 2
    assert verdict["verdict"] == "usage_error"
    assert "pdf" in verdict["error"].lower()


# --------------------------------------------------------------------------
# the shipping gate
# --------------------------------------------------------------------------

#: incident -> (rubric class, how it is caught). "deterministic" means the
#: machine half HARDs on its own; "vision" means only the rubric-guided
#: vision half can see it and the machine half must TARGET the page.
INCIDENT_MATRIX = {
    "T23_malformed_xml_blank": ("artifact_malformed", "deterministic"),
    "T24_stale_lineseg_overprint": ("overprint", "vision"),
    "W62_2up_imposition": ("imposition_mismatch", "deterministic"),
    "T25_missing_input_blank": ("blank_render", "deterministic"),
    "T30_fill_superscript_inheritance": ("format_noncompliance",
                                         "deterministic"),
}


@pytest.mark.parametrize("incident", sorted(INCIDENT_MATRIX))
def test_every_incident_is_covered_by_the_rubric(incident):
    cls, how = INCIDENT_MATRIX[incident]
    assert cls in visual_verify.RUBRIC_CLASSES, (
        f"{incident} has no rubric class — the rubric does not ship")
    assert how in ("deterministic", "vision")
    if how == "vision":
        # A vision-only class must never be emitted by the machine half.
        assert cls not in {
            m[0] for m in visual_verify._LAYOUT_QA_MAP.values()}, (
            f"{incident}: {cls} is recorded vision-only but a deterministic "
            "detector emits it — update the matrix or the rubric")
