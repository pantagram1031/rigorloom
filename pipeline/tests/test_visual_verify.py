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
RUBRIC = REPO_ROOT / "docs" / "research" / "visual-rubric.md"

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
    assert task[0]["rubric"] == "docs/research/visual-rubric.md"
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
        "rubric": "docs/research/visual-rubric.md",
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
