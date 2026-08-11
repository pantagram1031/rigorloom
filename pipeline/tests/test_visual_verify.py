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
  (c2) T38  the SAME mechanism after the conversion normalised it, where the
            proof lived in another step: a hash-bound conversion record lifts
            the print_method leg, and its absence still HARDs
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

import hashlib
import json
import re
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
sys.path.insert(0, str(REPO_ROOT / "engine" / "scripts"))
import check_residue  # noqa: E402
import layout_qa  # noqa: E402
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


def _laid_out_pages(n_pages: int) -> str:
    """One laid-out paragraph per page, as Hancom's layout cache records them.

    Every laid-out line carries ``<hp:lineseg vertpos=...>``, a HWPUNIT offset
    from the top of ITS page, so a page boundary is exactly a point where
    ``vertpos`` stops increasing. That is what ``derive_pages_document`` counts,
    and it is the cache a real .hwpx carries — so a fixture can have a document
    page count without anybody declaring one.

    ``_SECTION_OK``'s own paragraph already sits at ``vertpos="0"``, so the FIRST
    block here continues page 1 (equal, not a decrease) and each later block
    resets and adds one page: N blocks == N pages.
    """
    body = ('<hp:run charPrIDRef="0"><hp:t>laid out line</hp:t></hp:run>'
            '<hp:linesegarray>'
            + "".join(f'<hp:lineseg textpos="0" vertpos="{v}"/>'
                      for v in (0, 1000, 2000))
            + '</hp:linesegarray>')
    return "".join(f'<hp:p id="{100 + i}">{body}</hp:p>'
                   for i in range(max(n_pages, 1)))


def make_hwpx(path: Path, *, malformed: bool = False,
              print_method: int = 0, pages: int = 1) -> Path:
    """Minimal but structurally real .hwpx (mimetype + settings + Contents).

    ``pages=N`` writes a layout cache that lays the document out over N pages.
    """
    section = _SECTION_MALFORMED if malformed else _SECTION_OK
    if pages > 1 and not malformed:
        section = section.replace("</hs:sec>", _laid_out_pages(pages)
                                  + "</hs:sec>")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip")
        zf.writestr("settings.xml", _settings(print_method))
        zf.writestr("Contents/header.xml", _HEADER_OK)
        zf.writestr("Contents/section0.xml", section)
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
    """pages = [ {width, height, lines:[(x, y, text, size)]} , ...].

    Non-ASCII lines are drawn with PyMuPDF's built-in ``korea`` CJK font, which
    DOES carry a ToUnicode map — the default base-14 face silently drops Hangul,
    which is what the module docstring's original fixture note was about. Korean
    fill values therefore round-trip through text extraction, so a fixture can
    exercise the render-side ``empty_cell_expected_fill`` leg with the same
    values its artifact carries.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for spec in pages:
        page = doc.new_page(width=spec.get("width", 595),
                            height=spec.get("height", 842))
        for x, y, text, size in spec.get("lines", []):
            page.insert_text((x, y), text, fontsize=size,
                             fontname="korea" if not text.isascii() else "helv")
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
# (c2) T38 — conversion provenance across the step boundary
#
# ``com_backend.py convert`` neutralises a stored n-up PrintMethod before
# SaveAs(PDF) and says so in its own stdout JSON. The canonical recipe
# converts in one step and verifies in another, so that report used to die at
# the step boundary: visual_verify saw no evidence and — correctly, given what
# it knew — HARDed. These tests pin the plumbing that carries the evidence
# across, and pin that the plumbing is NOT a relaxation.
# --------------------------------------------------------------------------

def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_conversion_record(path, artifact, pdf, **over):
    """A record shaped exactly as ``com_backend.write_conversion_record`` writes
    one. Overrides let a test corrupt precisely one field."""
    record = {
        "schema": visual_verify.CONVERSION_RECORD_SCHEMA,
        "tool": "com_backend.py convert",
        "created_utc": "2026-08-08T00:00:00Z",
        "source": str(artifact),
        "source_sha256": _sha256(artifact),
        "pdf": str(pdf),
        "pdf_sha256": _sha256(pdf),
        "source_print_method": 4,
        "print_method_normalized": {"from": 4, "to": 0},
        "pages_document": 1,
        "pages_pdf": 1,
    }
    record.update(over)
    path = Path(path)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


def _folded_form(tmp_path, name="t38"):
    """A PrintMethod=4 source plus the UNFOLDED single-page PDF a normalised
    conversion actually produces."""
    artifact = make_hwpx(tmp_path / f"{name}.hwpx", print_method=4, pages=1)
    pdf = make_pdf(tmp_path / f"{name}.pdf", [_body_page(n_lines=10)])
    return artifact, pdf


def test_conversion_record_suffix_matches_com_backend():
    """The sidecar name is a wire contract between two scripts that do not
    import each other. If this drifts, auto-discovery silently stops working
    and every gongmun form quietly goes back to HARDing."""
    sys.path.insert(0, str(REPO_ROOT / "engine" / "scripts"))
    import com_backend
    assert (com_backend.CONVERSION_RECORD_SUFFIX
            == visual_verify.CONVERSION_RECORD_SUFFIX)
    assert (com_backend.CONVERSION_RECORD_SCHEMA
            == visual_verify.CONVERSION_RECORD_SCHEMA)
    assert (str(com_backend.conversion_record_path("x/y.pdf"))
            == str(visual_verify.conversion_record_path("x/y.pdf")))


def test_com_backends_own_writer_round_trips_through_the_reader(tmp_path):
    """The contract that actually matters: a record produced by the WRITER is
    accepted by the READER. Asserting matching constants is not enough — the
    field names have to line up too, and only the real writer can prove that.
    """
    sys.path.insert(0, str(REPO_ROOT / "engine" / "scripts"))
    import com_backend
    artifact, pdf = _folded_form(tmp_path, name="rt")
    record_path = com_backend.conversion_record_path(pdf)
    com_backend.write_conversion_record(
        record_path, source=artifact, pdf=pdf,
        normalized={"from": 4, "to": 0}, source_print_method=4,
        pages_document=1, pages_pdf=1)

    conversion, error = visual_verify.load_conversion_record(
        record_path, artifact, pdf)
    assert error is None, error
    assert conversion["print_method_normalized"] == {"from": 4, "to": 0}
    assert conversion["pages_document"] == 1
    assert conversion["provenance"] == "conversion_record"
    # and end to end through the CLI, with nothing named on the command line
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert not [f for f in verdict["hard"]
                if f["class"] == "imposition_mismatch"], verdict


def test_t38_no_record_and_print_method_4_still_hards(tmp_path):
    """THE STILL-CATCHES. Nothing says the imposition was neutralised, so the
    gate must keep assuming it was not. This is the behaviour the fix is
    forbidden to weaken."""
    artifact, pdf = _folded_form(tmp_path)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    hard = [f for f in verdict["hard"]
            if f["detector"] == "visual_verify.print_method"]
    assert len(hard) == 1, verdict
    assert hard[0]["class"] == "imposition_mismatch"
    assert hard[0]["evidence"]["stored_print_method"] == 4
    # and no waiver exists for it, then or now
    assert "imposition_mismatch" not in visual_verify.SAFETY_CHECKS


def test_t38_record_round_trips_and_lifts_the_hard(tmp_path):
    """The fix. Same artifact, same PDF, same PrintMethod=4 — the only new
    thing is the proof that the conversion already normalised it."""
    artifact, pdf = _folded_form(tmp_path)
    record = make_conversion_record(tmp_path / "rec.json", artifact, pdf)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--conversion-record", record,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert not [f for f in verdict["hard"]
                if f["class"] == "imposition_mismatch"], verdict
    det = verdict["deterministic"]
    # the source's stored value is still REPORTED — the fix hides nothing
    assert det["stored_print_method"] == 4
    assert det["conversion"]["provenance"] == "conversion_record"
    assert det["conversion"]["print_method_normalized"] == {"from": 4, "to": 0}
    # and the record's page count becomes the authoritative parity source,
    # exactly as it would had this script done the conversion itself
    assert det["pages_document_source"] == "conversion"
    assert det["pages_document"] == 1


def test_t38_sidecar_is_discovered_without_a_flag(tmp_path):
    """The recipe must not depend on the operator remembering a flag: the
    sidecar sits beside the PDF and is picked up on its own."""
    artifact, pdf = _folded_form(tmp_path)
    make_conversion_record(
        visual_verify.conversion_record_path(pdf), artifact, pdf)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert not [f for f in verdict["hard"]
                if f["class"] == "imposition_mismatch"], verdict
    assert verdict["deterministic"]["conversion"]["record"].endswith(
        visual_verify.CONVERSION_RECORD_SUFFIX)


def test_t38_record_bound_to_a_different_source_is_a_usage_error(tmp_path):
    """A provenance claim that can be pointed at another file is worse than no
    claim. Wrong source bytes -> exit 2, never a quiet accept."""
    artifact, pdf = _folded_form(tmp_path)
    other = make_hwpx(tmp_path / "other.hwpx", print_method=4, pages=1)
    other.write_bytes(other.read_bytes() + b"\x00")  # perturb the bytes
    record = make_conversion_record(tmp_path / "rec.json", artifact, pdf,
                                    source_sha256=_sha256(other))
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--conversion-record", record,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "different source" in json.dumps(verdict, ensure_ascii=False)


def test_t38_record_bound_to_a_different_pdf_is_a_usage_error(tmp_path):
    """The other end of the binding: the record must describe THIS render."""
    artifact, pdf = _folded_form(tmp_path)
    other_pdf = make_pdf(tmp_path / "other.pdf", [_body_page(n_lines=3)])
    record = make_conversion_record(tmp_path / "rec.json", artifact, pdf,
                                    pdf_sha256=_sha256(other_pdf))
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--conversion-record", record,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "different pdf" in json.dumps(verdict, ensure_ascii=False)


def test_t38_stale_sidecar_after_an_artifact_edit_is_a_usage_error(tmp_path):
    """The realistic failure this binding buys us: fix the artifact, forget to
    re-convert, verify the OLD pdf. The sidecar no longer describes the
    artifact, so the run stops instead of passing on a stale render."""
    artifact, pdf = _folded_form(tmp_path)
    make_conversion_record(
        visual_verify.conversion_record_path(pdf), artifact, pdf)
    artifact.write_bytes(artifact.read_bytes() + b"\x00")   # edited after
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "Re-run" in json.dumps(verdict, ensure_ascii=False)


def test_t38_unbound_record_is_refused(tmp_path):
    """A record with no hashes is a bare assertion. Refused."""
    artifact, pdf = _folded_form(tmp_path)
    record = make_conversion_record(tmp_path / "rec.json", artifact, pdf)
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload.pop("source_sha256")
    record.write_text(json.dumps(payload), encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--conversion-record", record,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "not evidence" in json.dumps(verdict, ensure_ascii=False)


def test_t38_wrong_schema_record_is_refused(tmp_path):
    artifact, pdf = _folded_form(tmp_path)
    record = make_conversion_record(tmp_path / "rec.json", artifact, pdf,
                                    schema="something/else/v9")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--conversion-record", record,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict


def test_t38_missing_named_record_is_a_usage_error(tmp_path):
    artifact, pdf = _folded_form(tmp_path)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--conversion-record", tmp_path / "nope.json",
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict


def test_t38_print_method_zero_needs_no_record(tmp_path):
    """Unaffected path: nothing to normalise, nothing to prove, no record."""
    artifact = make_hwpx(tmp_path / "clean.hwpx", print_method=0, pages=1)
    pdf = make_pdf(tmp_path / "clean.pdf", [_body_page(n_lines=10)])
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert verdict["hard"] == []
    assert verdict["deterministic"]["conversion"] is None


def test_t38_record_does_not_suppress_the_page_parity_leg(tmp_path):
    """Scope check: the record explains print-method normalisation ONLY. A
    genuine fold still fails parity, now against Hancom's own PageCount."""
    artifact = make_hwpx(tmp_path / "fold.hwpx", print_method=4, pages=4)
    pdf = make_pdf(tmp_path / "fold.pdf", [
        {"width": 842, "height": 595, **_body_page(n_lines=10)},
        {"width": 842, "height": 595, **_body_page(n_lines=10)},
    ])
    make_conversion_record(
        visual_verify.conversion_record_path(pdf), artifact, pdf,
        pages_document=4, pages_pdf=2)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    parity = [f for f in verdict["hard"]
              if f["detector"] == "visual_verify.page_parity"]
    assert len(parity) == 1, verdict
    assert parity[0]["evidence"]["pages_document_source"] == "conversion"
    # the print_method leg IS lifted; only the real fold remains
    assert not [f for f in verdict["hard"]
                if f["detector"] == "visual_verify.print_method"]


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
    # a PDF baseline is passed through, never converted
    assert verdict["deterministic"]["baseline_diff"]["baseline_pdf"] is None


# -- T35 nit (b): --baseline names the BLANK FORM, so it must take one -------
#
# The round-3 agent read "--baseline" as "the blank form", handed it the
# .hwpx, got a refusal that wanted a PDF, and dropped pixel-diff entirely
# rather than converting. The flag now converts a document baseline through
# the same serial COM path the artifact takes, and says so in its usage
# string; with no renderer it is a skip-with-reason, never a crash.

def _verify_args(artifact, **overrides):
    """The ``verify()`` argument namespace, so a test can monkeypatch."""
    fields = {
        "artifact": str(artifact), "pdf": None, "expectations": None,
        "conversion_record": None,
        "png_dir": None, "dpi": 130, "baseline": None,
        "form_profile": None, "content": None, "vision_verdict": None,
        "vision_scope": "all", "deterministic_only": True,
        "keep": [], "keep_pattern": None, "fill_map": None,
        "accept_without": [],
        "attempt": None, "max_fix_attempts": None, "out": None}
    fields.update({k: (str(v) if isinstance(v, Path) else v)
                   for k, v in overrides.items()})
    return type("A", (), fields)()


def test_an_hwpx_baseline_is_converted_and_the_pixel_diff_runs(
        tmp_path, monkeypatch):
    """The blank form goes in; changed-region bboxes come out."""
    artifact = make_hwpx(tmp_path / "filled.hwpx")
    blank = make_hwpx(tmp_path / "blank.hwpx")
    base_pdf = make_pdf(tmp_path / "rendered_blank.pdf",
                        [_body_page(n_lines=6)])
    changed = _body_page(n_lines=6)
    changed["lines"].append((72.0, 400.0, "an inserted extra line", 10.0))
    after = make_pdf(tmp_path / "after.pdf", [changed])

    calls = []

    def fake_convert(source, out_pdf):
        calls.append((Path(source), Path(out_pdf)))
        Path(out_pdf).parent.mkdir(parents=True, exist_ok=True)
        Path(out_pdf).write_bytes(base_pdf.read_bytes())
        return str(out_pdf), {"pages_document": 1, "pages_pdf": 1}, None

    monkeypatch.setattr(visual_verify, "render_capable", lambda: True)
    monkeypatch.setattr(visual_verify, "convert_to_pdf", fake_convert)

    verdict, code = visual_verify.verify(_verify_args(
        artifact, pdf=after, baseline=blank, png_dir=tmp_path / "png"))
    diff = verdict["deterministic"]["baseline_diff"]
    assert code == 0, verdict
    assert "skipped" not in diff
    assert diff["baseline"] == str(blank)
    assert diff["baseline_pdf"], "the converted baseline PDF must be reported"
    assert diff["baseline_pages"] == 1
    assert diff["pages"][0]["comparable"] is True
    assert diff["pages"][0]["changed_regions"], (
        "the inserted line must show up as a changed region")
    # converted through the artifact's own path, and only the baseline
    assert [c[0] for c in calls] == [blank]
    # the converted PDF must not collide with the artifact's own render
    assert calls[0][1].name.endswith("_baseline.pdf")


def test_an_hwpx_baseline_with_no_renderer_is_a_skip_with_reason(
        tmp_path, monkeypatch):
    """One check lost, not the whole run — and never a traceback."""
    artifact = make_hwpx(tmp_path / "filled.hwpx")
    blank = make_hwpx(tmp_path / "blank.hwpx")
    pdf = make_pdf(tmp_path / "after.pdf", [_body_page(n_lines=6)])

    monkeypatch.setattr(visual_verify, "render_capable", lambda: False)

    def never(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("convert_to_pdf must not run without a renderer")

    monkeypatch.setattr(visual_verify, "convert_to_pdf", never)

    verdict, code = visual_verify.verify(_verify_args(
        artifact, pdf=pdf, baseline=blank, png_dir=tmp_path / "png"))
    assert code == 0, verdict
    assert verdict["verdict"] == "deterministic_pass"
    diff = verdict["deterministic"]["baseline_diff"]
    assert diff["baseline_pages"] is None
    assert diff["pages"] == []
    reason = diff["skipped"]
    assert reason.startswith("baseline_pixel_diff:")
    assert reason in verdict["deterministic"]["skipped"], (
        "a skipped check must be stated out loud in deterministic.skipped")


def test_a_missing_baseline_names_every_accepted_shape(tmp_path):
    artifact = make_hwpx(tmp_path / "b.hwpx")
    pdf = make_pdf(tmp_path / "p.pdf", [_body_page(n_lines=4)])
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--baseline", tmp_path / "nope.hwpx",
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    for token in (".hwpx", ".pdf", "directory of page images"):
        assert token in verdict["error"], token


def test_the_baseline_usage_string_states_what_the_flag_accepts():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT))
    help_text = " ".join(proc.stdout.split())
    assert "--baseline" in help_text
    for token in (".hwpx", ".pdf", "directory of page images"):
        assert token in help_text, token


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
# (e2) T40 — the detector was baseline-BLIND, and inverted on forms
#
# The 기안문 별지 제1호서식 could not reach acceptance by any shipped path: its
# heaviest charPr is the 비고 fine print (10pt, ratio 100%), so the document
# body baseline IS the fine print and every substantive seat on the form —
# 수신, (경유), 제목, 직인, 발신명의, all ratio 97% — differed from it and
# HARDed. Two defects, one fix: nothing asked whether the BLANK form's same
# seat already carried that signature, and a text-weight body baseline is the
# wrong reference on a mostly-empty form.
#
# The fixture reproduces the inversion exactly: one labelled seat cell at
# charPr 9 (ratio 97) and one fine-print cell at charPr 0 that outweighs it.
# --------------------------------------------------------------------------

_SEAT_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" secCnt="1">'
    '<hh:refList><hh:charProperties itemCnt="4">'
    + _charpr(0)                            # body / the fine print
    + _charpr(7, "<hh:supscript/>")          # the T30 trap
    + _charpr(8, "<hh:supscript/>")          # a real footnote marker
    + _charpr(9).replace('<hh:ratio hangul="100" latin="100"/>',
                         '<hh:ratio hangul="97" latin="97"/>')
    + '</hh:charProperties></hh:refList></hh:head>'
)

#: The seat's printed label. An --at-cell-append fill keeps it and puts the
#: value after it (T31), so the SAME seat reads "Recipient" in the blank form
#: and "Recipient RIGORLOOM-A1" in the artifact — which is exactly why the seat
#: key cannot be the text.
_SEAT_LABEL = "Recipient"
_SEAT_FILLED = f"{_SEAT_LABEL} {_FILL_VALUE}"
_SEAT_FINE_PRINT = " ".join(
    f"Remark line {i}: this block is the form's own fine print."
    for i in range(6))


def make_seat_form_hwpx(path: Path, *, seat, seat_charpr: int = 9,
                        seat_extra_run: tuple[int, str] | None = None,
                        seat_empty_runs: int = 1,
                        seat_paragraphs: tuple[str, ...] | None = None) -> Path:
    """A form with ONE labelled seat cell (0,0) and a fine-print cell (1,0).

    ``seat`` is the seat cell's run text; ``None`` writes the genuinely empty
    self-closing run a ``fill-cells`` target carries in a blank form. The
    fine-print cell (charPr 0) holds most of the page's characters, so it wins
    the document body-baseline weighting exactly as the 비고 block does on the
    real 기안문 별지. ``<hp:cellAddr>`` sits after ``<hp:subList>``, as OWPML
    writes it.
    """
    value_run = (_run(seat_charpr, seat) if seat is not None
                 else f'<hp:run charPrIDRef="{seat_charpr}"/>'
                 * seat_empty_runs)
    if seat_extra_run is not None:
        value_run += _run(*seat_extra_run)
    seat_body = ("".join(
        f'<hp:p id="{10 + index}">{_run(seat_charpr, line)}</hp:p>'
        for index, line in enumerate(seat_paragraphs))
        if seat_paragraphs is not None
        else f'<hp:p id="10">{value_run}</hp:p>')

    def cell(row, body):
        return ('<hp:tc name="" header="0"><hp:subList>' + body +
                f'</hp:subList><hp:cellAddr colAddr="0" rowAddr="{row}"/>'
                '<hp:cellSpan colSpan="1" rowSpan="1"/></hp:tc>')

    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
        ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        '<hp:p id="1"><hp:tbl id="20" rowCnt="2" colCnt="1">'
        '<hp:tr>' + cell(0, seat_body) + '</hp:tr>'
        '<hp:tr>' + cell(1, f'<hp:p id="11">{_run(0, _SEAT_FINE_PRINT)}</hp:p>')
        + '</hp:tr></hp:tbl></hp:p>'
        # a genuinely superscripted footnote marker no fill produced: the
        # existing scope guard must keep ignoring it in this shape too
        f'<hp:p id="12">{_run(0, "See the remark block.")}{_run(8, "1)")}'
        '</hp:p>'
        '</hs:sec>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip")
        zf.writestr("settings.xml", _settings(0))
        zf.writestr("Contents/header.xml", _SEAT_HEADER)
        zf.writestr("Contents/section0.xml", section)
    return path


def _seat_pdf(path: Path, *, value: str = _SEAT_FILLED) -> Path:
    """A render carrying the seat's full text, so ``empty_cell_expected_fill``
    stays green and only the charPr legs can speak."""
    page = _body_page(n_lines=8)
    page["lines"].append((72.0, 300.0, value, 10.0))
    return make_pdf(path, [page])


def _seat_expectations(path: Path, **extra) -> Path:
    payload = {"fill_map": {_SEAT_LABEL: _SEAT_FILLED}}
    payload.update(extra)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _seat_run(tmp_path, monkeypatch, *, artifact, baseline=None,
              pdf_value=_SEAT_FILLED, **overrides):
    """``verify()`` in-process, with the renderer denied.

    ``--baseline`` on a document normally converts it through Hancom; denying
    the renderer keeps the unit test offline AND proves the property that
    matters operationally: the seat comparison reads the blank form's XML, so
    it still runs on a machine that cannot render (the pixel diff is the only
    thing lost, exactly as T35 decided).
    """
    monkeypatch.setattr(visual_verify, "render_capable", lambda: False)
    args = _verify_args(artifact,
                        pdf=str(_seat_pdf(tmp_path / "seat.pdf",
                                          value=pdf_value)),
                        png_dir=str(tmp_path / "png"),
                        baseline=(str(baseline) if baseline else None),
                        **overrides)
    return visual_verify.verify(args)


def _script_findings(verdict, bucket):
    return [f for f in verdict[bucket]
            if f["detector"] == "visual_verify.fill_charpr_script"]


def test_t40_a_seat_signature_the_blank_form_already_had_is_a_named_warn(
        tmp_path, monkeypatch):
    """The blocker itself. The fill preserved the printed label's charPr — that
    is what --at-cell-append is FOR — so it introduced nothing, and the form's
    own 97% ratio must not be reported as a defect the fill caused. It is not
    dropped either: a named WARN, on the record, with the seat named."""
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=_SEAT_LABEL)
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx", seat=_SEAT_FILLED)
    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=blank,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))

    assert code == 0, verdict
    assert _script_findings(verdict, "hard") == []
    warns = _script_findings(verdict, "warn")
    assert len(warns) == 1, verdict["warn"]
    hit = warns[0]
    assert hit["code"] == "fill_charpr_script_inherited"
    assert hit["severity"] == "warn"
    assert hit["class"] == "format_noncompliance"
    evidence = hit["evidence"]
    assert evidence["label"] == _SEAT_LABEL
    assert evidence["seat"] == "Contents/section0.xml/t1/0,0"
    assert evidence["differing"] == ["ratio"]          # vs the document body
    assert evidence["form_baseline_checked"] is True
    assert evidence["form_baseline_charpr_id"] == "9"
    assert evidence["form_baseline_values"]["ratio"] == {"hangul": "97",
                                                        "latin": "97"}
    report = verdict["deterministic"]["fill_charpr_script"]
    assert report["baseline_charpr_id"] == "0"         # the fine print
    assert report["inherited"] == 1
    assert report["findings"] == 0
    assert report["form_baseline"] == str(blank)
    assert report["form_baseline_note"] is None
    # the SAFETY check RAN — a suppression is never a skip
    assert "fill_charpr_script_mismatch" not in \
        verdict["deterministic"]["skipped_checks"]


def test_t40_the_same_fill_hards_without_the_seat_comparison(
        tmp_path, monkeypatch):
    """Control for the test above: identical artifact, no --baseline. The HARD
    is exactly the pre-T40 behaviour, and the finding SAYS the inheritance
    question was not checked rather than implying it was."""
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx", seat=_SEAT_FILLED)
    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))

    assert code == 3, verdict
    hards = _script_findings(verdict, "hard")
    assert [f["code"] for f in hards] == ["fill_charpr_script_mismatch"]
    evidence = hards[0]["evidence"]
    assert evidence["form_baseline_checked"] is False
    assert evidence["form_baseline_charpr_id"] is None
    assert "--baseline" in evidence["form_baseline_note"]
    assert verdict["deterministic"]["fill_charpr_script"]["inherited"] == 0


def test_t40_a_pdf_baseline_cannot_answer_the_question_and_says_so(
        tmp_path, monkeypatch):
    """--baseline also takes a PDF or an image directory (T35). Neither carries
    charPr definitions, so the verdict may not claim the seat was checked."""
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx", seat=_SEAT_FILLED)
    base_pdf = make_pdf(tmp_path / "blank.pdf", [_body_page(n_lines=6)])
    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=base_pdf,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))

    assert code == 3, verdict
    hards = _script_findings(verdict, "hard")
    assert len(hards) == 1
    note = hards[0]["evidence"]["form_baseline_note"]
    assert ".pdf" in note and ".hwpx" in note
    assert hards[0]["evidence"]["form_baseline_checked"] is False
    assert verdict["deterministic"]["fill_charpr_script"]["form_baseline"] \
        is None


def test_t40_still_catches_a_script_written_into_a_genuinely_empty_seat(
        tmp_path, monkeypatch):
    """STILL-CATCHES, the one that matters. The blank form's seat holds the
    self-closing empty run a ``fill-cells`` target has — it carries no text, so
    there is no typography to inherit and nothing is excused. This is the live
    T30 incident's own shape, now run WITH a baseline in hand."""
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=None,
                                seat_charpr=7)
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx",
                                   seat=_FILL_VALUE, seat_charpr=7)
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"fill_map": {"0,0": _FILL_VALUE}}),
                            encoding="utf-8")
    verdict, code = _seat_run(tmp_path, monkeypatch, artifact=artifact,
                              baseline=blank, pdf_value=_FILL_VALUE,
                              expectations=str(expectations))

    assert code == 3, verdict
    hards = _script_findings(verdict, "hard")
    assert [f["code"] for f in hards] == ["fill_charpr_script_mismatch"]
    evidence = hards[0]["evidence"]
    assert evidence["differing"] == ["supscript"]
    assert evidence["rendered_pt_estimate"] == pytest.approx(6.35, abs=0.01)
    assert evidence["form_baseline_checked"] is True
    assert evidence["form_baseline_charpr_id"] is None
    assert "genuinely empty run" in evidence["form_baseline_note"]
    assert _script_findings(verdict, "warn") == []


def test_t42_address_keyed_reserved_body_runs_inherit_safe_form_typography(
        tmp_path, monkeypatch):
    """The canonical gongmun path: fill-cells writes the address-keyed body
    into a block of reserved blank runs. The form chose one non-script charPr
    for that whole block, so a filled run with the same signature inherits the
    form's typography even though no blank run carried visible text."""
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=None,
                                seat_charpr=9, seat_empty_runs=3)
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx",
                                   seat=_FILL_VALUE, seat_charpr=9)
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"fill_map": {"0,0": _FILL_VALUE}}),
                            encoding="utf-8")
    verdict, code = _seat_run(tmp_path, monkeypatch, artifact=artifact,
                              baseline=blank, pdf_value=_FILL_VALUE,
                              expectations=str(expectations))

    assert code == 0, verdict
    assert _script_findings(verdict, "hard") == []
    warns = _script_findings(verdict, "warn")
    assert [row["code"] for row in warns] == ["fill_charpr_script_inherited"]
    evidence = warns[0]["evidence"]
    assert evidence["form_baseline_charpr_id"] == "9"
    assert evidence["form_baseline_match"] == "cell_address_reserved_runs"
    assert evidence["form_baseline_reserved_runs"] == 3


def test_t42_multiple_reserved_runs_do_not_excuse_a_script_trap(
        tmp_path, monkeypatch):
    """Still-catches: repetition alone is not authority. A reserved block whose
    charPr has a script/scale/offset anomaly remains the T30 trap."""
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=None,
                                seat_charpr=7, seat_empty_runs=3)
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx",
                                   seat=_FILL_VALUE, seat_charpr=7)
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"fill_map": {"0,0": _FILL_VALUE}}),
                            encoding="utf-8")
    verdict, code = _seat_run(tmp_path, monkeypatch, artifact=artifact,
                              baseline=blank, pdf_value=_FILL_VALUE,
                              expectations=str(expectations))
    assert code == 3, verdict
    hards = _script_findings(verdict, "hard")
    assert [row["code"] for row in hards] == ["fill_charpr_script_mismatch"]
    assert hards[0]["evidence"]["form_baseline_charpr_id"] is None
    assert "script/scale/offset" in hards[0]["evidence"]["form_baseline_note"]


def test_t42_filled_signature_must_match_the_reserved_block(
        tmp_path, monkeypatch):
    """Still-catches: the form reserves a safe ratio-only face, but the fill
    changed it to a superscript charPr. Reserved typography is evidence only
    for the exact signature the blank carried."""
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=None,
                                seat_charpr=9, seat_empty_runs=3)
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx",
                                   seat=_FILL_VALUE, seat_charpr=7)
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"fill_map": {"0,0": _FILL_VALUE}}),
                            encoding="utf-8")
    verdict, code = _seat_run(tmp_path, monkeypatch, artifact=artifact,
                              baseline=blank, pdf_value=_FILL_VALUE,
                              expectations=str(expectations))
    assert code == 3, verdict
    evidence = _script_findings(verdict, "hard")[0]["evidence"]
    assert evidence["form_baseline_charpr_id"] is None
    assert "does not match" in evidence["form_baseline_note"]


def test_t42_mixed_reserved_charprs_are_ambiguous_and_stay_hard(
        tmp_path, monkeypatch):
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=None,
                                seat_charpr=9, seat_empty_runs=2,
                                seat_extra_run=(7, ""))
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx",
                                   seat=_FILL_VALUE, seat_charpr=9)
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"fill_map": {"0,0": _FILL_VALUE}}),
                            encoding="utf-8")
    verdict, code = _seat_run(tmp_path, monkeypatch, artifact=artifact,
                              baseline=blank, pdf_value=_FILL_VALUE,
                              expectations=str(expectations))
    assert code == 3, verdict
    evidence = _script_findings(verdict, "hard")[0]["evidence"]
    assert evidence["form_baseline_charpr_id"] is None
    assert evidence["form_baseline_empty_charpr_ids"] == ["7", "9"]
    assert "several charPr ids" in evidence["form_baseline_note"]


_MULTILINE_FILL = (
    "1. 귀 기관의 무궁한 발전을 기원합니다.",
    "2. 요청 자료를 기한까지 제출하여 주시기 바랍니다.",
)


@pytest.mark.parametrize(
    "mapped_value",
    [list(_MULTILINE_FILL), "\n".join(_MULTILINE_FILL)],
    ids=["json_array", "newline_string"],
)
def test_t44_multiline_address_values_run_the_t42_charpr_check(
        tmp_path, monkeypatch, mapped_value):
    """A multi-paragraph declaration must feed each authored paragraph to
    T30/T42; it may not turn the safety check into an un-runnable skip."""
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=None,
                                seat_charpr=9, seat_empty_runs=3)
    artifact = make_seat_form_hwpx(
        tmp_path / "filled.hwpx", seat=None, seat_charpr=9,
        seat_paragraphs=_MULTILINE_FILL)
    expectations = tmp_path / "exp.json"
    expectations.write_text(
        json.dumps({"fill_map": {"0,0": mapped_value}}, ensure_ascii=False),
        encoding="utf-8")
    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=blank,
        pdf_value=" ".join(_MULTILINE_FILL),
        expectations=str(expectations))

    assert code == 0, verdict
    assert not any(row["check"] == "fill_charpr_script_mismatch"
                   for row in verdict["acceptance_blockers"])
    warns = _script_findings(verdict, "warn")
    assert [row["code"] for row in warns] == [
        "fill_charpr_script_inherited"]
    assert verdict["deterministic"]["fill_charpr_script"][
        "fill_modified_runs"] == 2


def test_t44_multiline_fill_with_changed_charpr_still_hards(
        tmp_path, monkeypatch):
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=None,
                                seat_charpr=9, seat_empty_runs=3)
    artifact = make_seat_form_hwpx(
        tmp_path / "filled.hwpx", seat=None, seat_charpr=7,
        seat_paragraphs=_MULTILINE_FILL)
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({
        "fill_map": {"0,0": "\n".join(_MULTILINE_FILL)}}), encoding="utf-8")
    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=blank,
        pdf_value=" ".join(_MULTILINE_FILL),
        expectations=str(expectations))

    assert code == 3, verdict
    assert [row["code"] for row in _script_findings(verdict, "hard")] == [
        "fill_charpr_script_mismatch"]
    assert not any(row["check"] == "fill_charpr_script_mismatch"
                   for row in verdict["acceptance_blockers"])


def test_t40_a_baseline_that_is_not_this_form_excuses_nothing(
        tmp_path, monkeypatch):
    """The wrong blank must not become a free pass. Seats are addressed, so a
    baseline that has no such seat cannot answer the question — HARD, saying
    which."""
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx", seat=_SEAT_FILLED)
    other = make_form_hwpx(tmp_path / "other.hwpx", value_charpr=0)
    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=other,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))

    assert code == 3, verdict
    hards = _script_findings(verdict, "hard")
    assert [f["code"] for f in hards] == ["fill_charpr_script_mismatch"]
    assert "no such seat" in hards[0]["evidence"]["form_baseline_note"]


def test_t40_a_fill_that_changes_the_seats_own_signature_still_hards(
        tmp_path, monkeypatch):
    """The other still-catches direction: the seat DID carry a signature in the
    blank form and the fill replaced it with a different one. Inheritance is
    the excuse, not the presence of a baseline."""
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=_SEAT_LABEL,
                                seat_charpr=9)
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx", seat=_SEAT_FILLED,
                                   seat_charpr=7)
    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=blank,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))

    assert code == 3, verdict
    hards = _script_findings(verdict, "hard")
    assert [f["code"] for f in hards] == ["fill_charpr_script_mismatch"]
    evidence = hards[0]["evidence"]
    assert evidence["form_baseline_charpr_id"] == "9"
    assert evidence["form_baseline_differing"] == ["ratio", "supscript"]
    assert "the fill changed it" in evidence["form_baseline_note"]


def test_t40_an_unrelated_run_in_the_same_seat_cannot_excuse_the_fill(
        tmp_path, monkeypatch):
    """The comparison is to the blank RUN the fill consumed, not to whichever
    charPr happens to carry the most text elsewhere in the same cell.

    The blank label is charPr 0, but a longer sibling run makes charPr 9 the
    seat-wide majority. The artifact incorrectly writes the filled label with
    9. A seat-majority implementation calls that inherited; the exact label
    run proves the fill changed it and must HARD.
    """
    sibling = "Unrelated printed guidance that stays in this cell"
    blank = make_seat_form_hwpx(
        tmp_path / "blank.hwpx", seat=_SEAT_LABEL, seat_charpr=0,
        seat_extra_run=(9, sibling))
    artifact = make_seat_form_hwpx(
        tmp_path / "filled.hwpx", seat=_SEAT_FILLED, seat_charpr=9,
        seat_extra_run=(9, sibling))
    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=blank,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))

    assert code == 3, verdict
    hards = _script_findings(verdict, "hard")
    assert [f["code"] for f in hards] == ["fill_charpr_script_mismatch"]
    evidence = hards[0]["evidence"]
    assert evidence["form_baseline_charpr_id"] == "0"
    assert evidence["form_baseline_match"] == "fill_map_key"
    assert "the fill changed it" in evidence["form_baseline_note"]


def test_t40_ambiguous_blank_run_match_refuses_to_excuse(
        tmp_path, monkeypatch):
    """Two blank runs in one seat match the consumed key but use different
    faces. The detector has enough information to know the baseline is
    ambiguous and must keep the HARD, naming both candidates (the #47 rule)."""
    blank = make_seat_form_hwpx(
        tmp_path / "blank.hwpx", seat=_SEAT_LABEL, seat_charpr=0,
        seat_extra_run=(9, _SEAT_LABEL))
    artifact = make_seat_form_hwpx(
        tmp_path / "filled.hwpx", seat=_SEAT_FILLED, seat_charpr=9,
        seat_extra_run=(9, _SEAT_LABEL))
    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=blank,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))

    assert code == 3, verdict
    hards = _script_findings(verdict, "hard")
    assert [f["code"] for f in hards] == ["fill_charpr_script_mismatch"]
    evidence = hards[0]["evidence"]
    assert evidence["form_baseline_charpr_id"] is None
    assert evidence["form_baseline_match"] is None
    assert {item["charpr_id"] for item in
            evidence["form_baseline_candidates"]} == {"0", "9"}
    assert "ambiguous" in evidence["form_baseline_note"]


def test_t40_the_footnote_scope_guard_survives_the_seat_comparison(
        tmp_path, monkeypatch):
    """The pre-existing false-positive guard is the SCOPE (fill-modified runs
    only), and adding a second baseline must not widen it: the fixture's
    genuinely superscripted footnote marker (charPr 8) is compared against
    nothing, with or without a form baseline."""
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=_SEAT_LABEL,
                                seat_charpr=0)
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx", seat=_SEAT_FILLED,
                                   seat_charpr=0)
    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=blank,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))

    assert code == 0, verdict
    assert _script_findings(verdict, "hard") == []
    assert _script_findings(verdict, "warn") == []
    report = verdict["deterministic"]["fill_charpr_script"]
    assert report["fill_modified_runs"] == 1        # the footnote is not one
    assert report["findings"] == 0 and report["inherited"] == 0


def test_t40_the_gongmun_shape_reaches_acceptance_with_no_waiver(
        tmp_path, monkeypatch):
    """End of the blocker: a correct fill of a form whose seats are all 97%
    reaches ``acceptance: true`` with ``acceptance_waivers: []``, and
    ``fill_charpr_script_mismatch`` is still in SAFETY_CHECKS and still RAN."""
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=_SEAT_LABEL)
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx", seat=_SEAT_FILLED)
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(
        {"form_hash": "sha256:synthetic", "anchors": [], "guide_text": [],
         "placeholders": []}, ensure_ascii=False),
        encoding="utf-8")
    expectations = _seat_expectations(tmp_path / "exp.json", pages_document=1)

    verdict, code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=blank,
        expectations=str(expectations), form_profile=str(profile),
        deterministic_only=False,
        vision_verdict=str(_reviewed(tmp_path)))

    assert code == 0, verdict
    assert verdict["verdict"] == "pass"
    assert verdict["acceptance"] is True
    assert verdict["acceptance_waivers"] == []
    assert verdict["acceptance_blockers"] == []
    assert verdict["counts"]["hard"] == 0
    assert "fill_charpr_script_mismatch" in visual_verify.SAFETY_CHECKS
    assert not set(verdict["deterministic"]["skipped_checks"]) & set(
        visual_verify.SAFETY_CHECKS)
    # accepted, and the suppression is still visible
    assert [f["code"] for f in _script_findings(verdict, "warn")] == [
        "fill_charpr_script_inherited"]


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


# -- T35: --fill-map is ONE flag with ONE loader ----------------------------
#
# The round-3 Opus run built one file for both consumers and ate a usage_error
# retry, because visual_verify documented the wrapper shape and check_residue
# wanted the bare map. Both shapes must work at every consumer of the flag,
# and the shape error must name both shapes so a wrong guess costs no retry.

def test_visual_verify_shares_the_core_fill_map_loader(tmp_path):
    """Not a copy: the same function object, so the shape rule cannot fork."""
    assert visual_verify.load_fill_map is check_residue.load_fill_map


@pytest.mark.parametrize("wrap", [False, True])
def test_the_delegate_run_accepts_both_fill_map_shapes(tmp_path, wrap):
    artifact, pdf, profile, _ = _labeled(tmp_path)
    payload = dict(_LABELED_MAP)
    path = tmp_path / f"map_{int(wrap)}.json"
    path.write_text(json.dumps({"fill_map": payload, "base_pt": 10}
                               if wrap else payload, ensure_ascii=False),
                    encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile, "--fill-map", path,
                           "--png-dir", tmp_path / f"png{int(wrap)}",
                           "--deterministic-only")
    assert code == 0, verdict
    keep = verdict["deterministic"]["residue_keep"]
    assert keep["fill_map"] == sorted(payload)


def test_a_wrapper_with_a_non_object_fill_map_is_a_usage_error(tmp_path):
    artifact, pdf, profile, _ = _labeled(tmp_path)
    path = tmp_path / "nullmap.json"
    path.write_text(json.dumps({"fill_map": None, "base_pt": 10}),
                    encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile, "--fill-map", path,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "'fill_map' member" in verdict["error"]
    # names BOTH shapes, so the caller does not have to guess again
    assert "BARE" in verdict["error"] and "WRAPPER" in verdict["error"]


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
    """(artifact, pdf, profile, fill_map) for one labeled-form run.

    The PDF carries the SAME labeled-field lines the artifact does. That is not
    decoration: ``--fill-map`` now seeds ``expectations.fill_map`` (one map, one
    concept), so the declared values are checked against the render too — a
    fixture whose render did not show what its artifact contains would be
    asserting a defect, not a clean fill.
    """
    artifact = make_labeled_form_hwpx(tmp_path / "labeled.hwpx", **kwargs)
    rendered = _body_page(n_lines=8)
    for offset, text in enumerate((f"누리집{kwargs.get('url', _URL_VALUE)}",
                                   f"주소{kwargs.get('zip_line', _ZIP_VALUE)}",
                                   *kwargs.get("trailing", ()))):
        rendered["lines"].append((72.0, 420.0 + offset * 16.0, text, 10.0))
    pdf = make_pdf(tmp_path / "labeled.pdf", [rendered])
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


def test_t43_consumed_requires_the_label_inside_a_declared_value_span():
    """A mapped fragment appearing after a label is not a prefix-preserving
    value. Reporting the label as consumed contradicts the residue delegate,
    which correctly HARDs the label outside that fragment's span."""
    profile = {"anchors": ["수신"], "placeholders": []}
    keep, consumed, unfilled = visual_verify.derive_form_keep(
        profile, {"수신": "국가유산청장"}, "수신 국가유산청장")
    assert keep == []
    assert consumed == []
    assert unfilled == ["수신"]

    keep, consumed, unfilled = visual_verify.derive_form_keep(
        profile, {"수신": "수신 국가유산청장"}, "수신 국가유산청장")
    assert keep == []
    assert consumed == ["수신"]
    assert unfilled == []


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


# --------------------------------------------------------------------------
# T41 — a fill-map key that claims several form strings is refused
#
# The keep derivation matches keys against the inventory by normalized
# substring in EITHER direction, so a bare-label key claims every string it
# contains or is contained by. On a 민원 form "[  ]통" also claims the generic
# "[ ]" checkbox, both leave the keep list, and every untouched "[ ]" on the
# sheet came back HARD — a false HARD only readable from this source.
# --------------------------------------------------------------------------

_BRACKET_PROFILE = {
    "form_hash": "sha256:synthetic-bracket",
    "anchors": ["성    명", "I.  서론"],
    "guide_text": [],
    # the generic checkbox AND the specific one — the over-claim in one profile
    "placeholders": ["[  ]", "[  ]통", "[  ]부"],
}


def test_a_key_claiming_several_form_strings_is_refused(tmp_path):
    with pytest.raises(visual_verify.AmbiguousFillKeyError) as excinfo:
        visual_verify.derive_form_keep(
            _BRACKET_PROFILE, {"[  ]통": "[√]통"},
            "성 명 이하율 [ ]통 [ ] [ ]부 I. 서론")
    exc = excinfo.value
    assert [row["key"] for row in exc.keys] == ["[  ]통"]
    assert exc.keys[0]["normalized_key"] == "[]통"
    # the refusal NAMES both strings it claimed, with how often each is present
    assert exc.keys[0]["matched"] == [{"text": "[  ]", "occurrences": 3},
                                      {"text": "[  ]통", "occurrences": 1}]
    assert "other_occurrences" in str(exc)


def test_a_key_naming_exactly_one_form_string_is_unaffected(tmp_path):
    """still-catches: the unambiguous key behaves exactly as before, even
    though the string it names is present three times (that repetition is
    T31's per-occurrence business, not an ambiguity)."""
    keep, consumed, unfilled = visual_verify.derive_form_keep(
        _BRACKET_PROFILE, {"성    명": "성    명 : 이하율"},
        "성 명 : 이하율 [ ]통 [ ] [ ]부 성 명 성 명 I. 서론")
    assert consumed == ["성    명"]      # the declared value landed
    assert unfilled == []
    assert keep == ["I.  서론", "[  ]", "[  ]통", "[  ]부"]


@pytest.mark.parametrize("declared,expect_keep", [
    ("form_text", True),
    ("seats", False),
])
def test_other_occurrences_is_the_declaration_that_resolves_it(declared,
                                                               expect_keep):
    """Both answers are honest and neither is guessed. ``seats`` reproduces the
    pre-T41 behavior exactly — now said out loud."""
    haystack = "성 명 이하율 [ ]통 [ ] [ ]부 I. 서론"
    keep, consumed, unfilled = visual_verify.derive_form_keep(
        _BRACKET_PROFILE, {"[  ]통": "[√]통"}, haystack,
        {"[  ]통": declared})
    assert (("[  ]" in keep) and ("[  ]통" in keep)) is expect_keep
    if not expect_keep:
        assert set(unfilled) == {"[  ]", "[  ]통"}


def test_the_scoped_value_object_flattens_for_every_other_consumer(tmp_path):
    """ONE file serves --map and --fill-map (T35): the gate sees a plain
    string value and only the keep derivation reads the scope."""
    path = tmp_path / "fill.json"
    path.write_text(json.dumps(
        {"[  ]통": {"text": "[√]통", "other_occurrences": "form_text",
                   "at_para": 4}}, ensure_ascii=False), encoding="utf-8")
    mapping, error = visual_verify.load_fill_map(path)
    assert error is None
    assert mapping == {"[  ]통": "[√]통"}          # flattened, scope stripped
    assert check_residue.load_fill_scopes(path) == {"[  ]통": "form_text"}


def test_one_scoped_file_on_both_surfaces_is_not_two_different_maps(tmp_path):
    """T35's blessed invocation (same file to --fill-map and --expectations)
    must survive scoping: the equality test compares flattened maps."""
    payload = {"fill_map": {"20101": {"text": _FILL_VALUE, "at_para": 3}},
               "base_pt": 10}
    path = tmp_path / "exp.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    expectations = json.loads(path.read_text(encoding="utf-8"))
    reconciled, source, error = visual_verify.reconcile_fill_map(
        expectations, path)
    assert error is None
    assert source == "cli+expectations"
    assert reconciled["fill_map"] == {"20101": _FILL_VALUE}


def test_expectations_only_preserves_the_scope_for_the_residue_delegate(
        tmp_path):
    """T36 permits a map on either surface. A scoped map supplied only inside
    --expectations must still reach both residue consumers; otherwise
    `other_occurrences` is dropped and the valid declaration is refused."""
    artifact = make_form_hwpx(tmp_path / "filled.hwpx")
    pdf = _fill_pdf(tmp_path / "filled.pdf")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(_BRACKET_PROFILE, ensure_ascii=False),
                       encoding="utf-8")
    expectations = tmp_path / "expectations.json"
    expectations.write_text(json.dumps({
        "fill_map": {"[  ]통": {
            "text": "[√]통", "other_occurrences": "form_text"}}
    }, ensure_ascii=False), encoding="utf-8")

    code, verdict, _ = run(
        "--artifact", artifact, "--pdf", pdf,
        "--form-profile", profile, "--expectations", expectations,
        "--png-dir", tmp_path / "png", "--deterministic-only")

    assert code != 2, verdict
    assert verdict["deterministic"]["fill_map_source"] == "expectations"
    keep = verdict["deterministic"]["residue_keep"]
    assert {"[  ]", "[  ]통"} <= set(keep["derived_keep"])
    assert "ambiguous_fill_keys" not in verdict


def test_an_unknown_scope_member_is_a_usage_error_not_a_silent_unscoped_key(
        tmp_path):
    path = tmp_path / "fill.json"
    path.write_text(json.dumps({"[  ]통": {"text": "x", "other_occurence": 1}}),
                    encoding="utf-8")
    mapping, error = visual_verify.load_fill_map(path)
    assert mapping is None
    assert "other_occurence" in error


def test_a_bad_other_occurrences_answer_is_a_usage_error(tmp_path):
    path = tmp_path / "fill.json"
    path.write_text(json.dumps(
        {"[  ]통": {"text": "x", "other_occurrences": "maybe"}}),
        encoding="utf-8")
    mapping, error = visual_verify.load_fill_map(path)
    assert mapping is None
    assert "form_text" in error


def test_the_refusal_reaches_the_cli_as_a_usage_error_with_its_payload(
        tmp_path):
    artifact = make_form_hwpx(tmp_path / "filled.hwpx")
    pdf = _fill_pdf(tmp_path / "filled.pdf")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(_BRACKET_PROFILE, ensure_ascii=False),
                       encoding="utf-8")
    fill_map = tmp_path / "fill.json"
    fill_map.write_text(json.dumps({"[  ]통": "[√]통"}, ensure_ascii=False),
                        encoding="utf-8")

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--form-profile", profile, "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 2, verdict
    assert verdict["verdict"] == "usage_error"
    assert [row["key"] for row in verdict["ambiguous_fill_keys"]] == ["[  ]통"]


#: These vision-contract fixtures are a bare document with no form profile and
#: no fill map, so three SAFETY checks genuinely cannot run. Acceptance now says
#: so (``safety_incomplete``), and the only way to an acceptance is to waive
#: them ON THE RECORD — which is exactly the UX under test here, so the waivers
#: are spelled out rather than hidden in a helper default.
_CLEAN_WAIVERS = ("--accept-without", "check_residue",
                  "--accept-without", "empty_cell_expected_fill",
                  "--accept-without", "fill_charpr_script_mismatch")


def test_clean_artifact_passes_only_with_the_vision_half(tmp_path):
    artifact, pdf = _clean_run(tmp_path)

    code, pending, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png", *_CLEAN_WAIVERS)
    assert code == 3
    assert pending["verdict"] == "vision_pending"
    assert [t["page"] for t in pending["vision_required"]] == [1, 2]

    vision = tmp_path / "v.json"
    vision.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": [1, 2], "findings": []}), encoding="utf-8")
    code, accepted, _ = run("--artifact", artifact, "--pdf", pdf,
                            "--png-dir", tmp_path / "png",
                            "--vision-verdict", vision, *_CLEAN_WAIVERS)
    assert code == 0, accepted
    assert accepted["verdict"] == "pass"
    assert accepted["acceptance"] is True
    # the waiver is recorded, so the acceptance names what it did not check
    assert accepted["acceptance_waivers"] == [
        "check_residue", "empty_cell_expected_fill",
        "fill_charpr_script_mismatch"]
    assert accepted["acceptance_blockers"] == []


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


def test_missing_glyphs_vision_finding_is_hard_and_blocks(tmp_path):
    artifact, pdf = _clean_run(tmp_path)
    vision = tmp_path / "missing-glyphs.json"
    vision.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": [1, 2],
        "findings": [{
            "page": 1,
            "class": "missing_glyphs",
            "severity": "hard",
            "evidence": "synthetic glyph defect",
        }],
    }), encoding="utf-8")
    code, verdict, _ = run(
        "--artifact", artifact, "--pdf", pdf,
        "--png-dir", tmp_path / "png",
        "--vision-verdict", vision, *_CLEAN_WAIVERS)
    assert code == 3, verdict
    assert any(item["class"] == "missing_glyphs"
               and item["severity"] == "hard"
               for item in verdict["hard"])


def test_missing_glyphs_cannot_be_downgraded_to_warning(tmp_path):
    artifact, pdf = _clean_run(tmp_path)
    vision = tmp_path / "missing-glyphs-warn.json"
    vision.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": [1, 2],
        "findings": [{"page": 1, "class": "missing_glyphs",
                      "severity": "warn"}],
    }), encoding="utf-8")
    code, verdict, _ = run(
        "--artifact", artifact, "--pdf", pdf,
        "--png-dir", tmp_path / "png",
        "--vision-verdict", vision, *_CLEAN_WAIVERS)
    assert code == 2, verdict
    assert verdict["verdict"] == "usage_error"


def test_every_rubric_class_is_accepted_from_vision(tmp_path):
    """The closed vocabulary is exactly the rubric's, in both directions."""
    artifact, pdf = _clean_run(tmp_path)
    vision = tmp_path / "v.json"
    vision.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": [1, 2],
        "findings": [{"page": 1, "class": cls,
                      "severity": ("hard" if cls == "missing_glyphs"
                                    else "warn"),
                      "evidence": "synthetic"}
                     for cls in visual_verify.RUBRIC_CLASSES]}),
        encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--vision-verdict", vision, *_CLEAN_WAIVERS)
    # Every class is parsed, but the HARD missing-glyph class must make the
    # merged visual verdict fail rather than being treated as a warning.
    assert code == 3, verdict
    assert set(classes(verdict, "warn")) >= (
        set(visual_verify.RUBRIC_CLASSES) - {"missing_glyphs"})
    assert "missing_glyphs" in classes(verdict, "hard")


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
# (h) P0-A — acceptance may not claim more than the run checked
#
# The v0.17 clean-room harness, luna tier: a CLI --fill-map was supplied and
# the verdict STILL carried empty_cell_expected_fill, fill_charpr_script_
# mismatch AND page_parity in deterministic.skipped[] — and returned
# acceptance: true with exit 0. Two root causes, both fixed here: acceptance
# ignored skipped[], and --fill-map / expectations.fill_map were different
# inputs with materially different effects.
# --------------------------------------------------------------------------

def _luna_shape(tmp_path, *, value_charpr=7):
    """luna's exact invocation shape: a CLI --fill-map, and an expectations
    file that does NOT carry a fill_map member."""
    artifact = make_form_hwpx(tmp_path / "luna.hwpx", value_charpr=value_charpr)
    pdf = _fill_pdf(tmp_path / "luna.pdf")
    profile = write_form_profile(tmp_path / "profile.json")
    fill_map = tmp_path / "map.json"
    fill_map.write_text(json.dumps({"20101": _FILL_VALUE}, ensure_ascii=False),
                        encoding="utf-8")
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"base_pt": 10.0}), encoding="utf-8")
    return artifact, pdf, profile, fill_map, expectations


def _reviewed(tmp_path, pages=(1,)):
    """A clean vision handback, so a test can reach the acceptance decision."""
    path = tmp_path / "vision.json"
    path.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": list(pages), "findings": []}), encoding="utf-8")
    return path


def test_luna_cli_fill_map_no_longer_leaves_the_t30_post_flight_inactive(
        tmp_path):
    """The CLI map seeds expectations.fill_map, so ALL of its consumers run —
    and the T30 trap this artifact carries is caught instead of skipped."""
    artifact, pdf, profile, fill_map, expectations = _luna_shape(tmp_path)

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--form-profile", profile, "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png",
                           "--vision-scope", "targeted")
    skipped = verdict["deterministic"]["skipped_checks"]
    assert "empty_cell_expected_fill" not in skipped, verdict["deterministic"]
    assert "fill_charpr_script_mismatch" not in skipped
    assert verdict["deterministic"]["fill_map_source"] == "cli"
    # the point of the whole fix: the trap fires
    assert "fill_charpr_script_mismatch" in codes(verdict)
    assert code == 3


def test_luna_shape_a_skipped_safety_check_is_never_an_acceptance(tmp_path):
    """luna's other half: with page parity still unobtainable and no residue
    gate, the run must NOT report acceptance — it must name what it skipped."""
    artifact, pdf, _, fill_map, expectations = _luna_shape(
        tmp_path, value_charpr=0)          # clean artifact: nothing FAILS

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png",
                           "--vision-verdict", _reviewed(tmp_path))
    assert verdict["hard"], "the skip itself must be a finding"
    assert code == 3, verdict
    assert verdict["verdict"] == "safety_incomplete"
    assert verdict["acceptance"] is False
    blocked = {row["check"] for row in verdict["acceptance_blockers"]}
    # make_form_hwpx carries no layout cache and no --form-profile was passed
    assert blocked == {"page_parity", "check_residue"}
    named = [f for f in verdict["hard"]
             if f["code"] == "acceptance_safety_skipped"]
    assert len(named) == 1
    assert named[0]["detector"] == "visual_verify.acceptance"
    assert set(named[0]["evidence"]["skipped_safety_checks"]) == blocked
    # every reason is stated, not just the count
    assert all(any(check in reason for reason in
                   named[0]["evidence"]["reasons"]) for check in blocked)
    assert verdict["acceptance_waivers"] == []


def test_a_waiver_flips_acceptance_back_and_is_recorded(tmp_path):
    """Same run, same skips, plus an explicit per-check opt-out."""
    artifact, pdf, _, fill_map, expectations = _luna_shape(
        tmp_path, value_charpr=0)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png",
                           "--vision-verdict", _reviewed(tmp_path),
                           "--accept-without", "page_parity",
                           "--accept-without", "check_residue")
    assert code == 0, verdict
    assert verdict["verdict"] == "pass"
    assert verdict["acceptance"] is True
    assert verdict["acceptance_waivers"] == ["check_residue", "page_parity"]
    assert verdict["acceptance_blockers"] == []
    # a waiver hides nothing: the skip is still reported out loud
    assert "page_parity" in verdict["deterministic"]["skipped_checks"]


def test_a_partial_waiver_still_blocks_on_the_rest(tmp_path):
    """Still-catches: waiving one skipped SAFETY check does not waive the
    others. Per-check, never a blanket switch."""
    artifact, pdf, _, fill_map, expectations = _luna_shape(
        tmp_path, value_charpr=0)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png",
                           "--vision-verdict", _reviewed(tmp_path),
                           "--accept-without", "page_parity")
    assert code == 3, verdict
    assert verdict["verdict"] == "safety_incomplete"
    assert [row["check"] for row in verdict["acceptance_blockers"]] == [
        "check_residue"]
    assert verdict["acceptance_waivers"] == ["page_parity"]


def test_an_unknown_waiver_is_a_usage_error_naming_the_vocabulary(tmp_path):
    artifact, pdf = _clean_run(tmp_path)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--accept-without", "everything")
    # argparse's closed `choices` rejects it before the run even starts
    assert code == 2, verdict


def test_the_safety_set_lives_in_exactly_one_place():
    """The waiver vocabulary, the skip bookkeeping and the acceptance rule all
    read SAFETY_CHECKS. Non-vacuity: every member must be a key ``_skipped``
    can actually emit, or a waiver would name a check that never appears."""
    emitted = {row["check"] for row in visual_verify._skipped(
        {}, None, None, None, None, form_profile=None, xml_members=[],
        pages_document_note=None)}
    assert set(visual_verify.SAFETY_CHECKS) <= emitted, (
        "SAFETY_CHECKS names a check _skipped() cannot report: "
        f"{sorted(set(visual_verify.SAFETY_CHECKS) - emitted)}")
    assert len(set(visual_verify.SAFETY_CHECKS)) == len(
        visual_verify.SAFETY_CHECKS)


# --------------------------------------------------------------------------
# (i) P0-A — page parity must not need a hand-declared page count
#
# The sol tier only got page parity because it hand-declared
# expectations.pages_document: on the --pdf path there was no conversion JSON,
# so parity skipped by default. It is now derived from the artifact's own
# layout cache, and the verdict names which source it used.
# --------------------------------------------------------------------------

def test_page_parity_runs_on_the_pdf_path_with_no_declared_count(tmp_path):
    artifact = make_hwpx(tmp_path / "p.hwpx", pages=3)
    pdf = make_pdf(tmp_path / "p.pdf", [_body_page()] * 3)

    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    det = verdict["deterministic"]
    assert det["pages_document"] == 3
    assert det["pages_document_source"] == "artifact_layout_cache"
    assert "page_parity" not in det["skipped_checks"]
    assert code == 0, verdict


def test_derived_page_parity_catches_the_w62_fold_without_a_declaration(
        tmp_path):
    """Still-catches, and it is the real incident: PrintMethod=4 folds four
    document pages onto two landscape sheets. Nobody declares anything."""
    artifact = make_hwpx(tmp_path / "nrf.hwpx", print_method=4, pages=4)
    pdf = make_pdf(tmp_path / "nrf.pdf", [
        {"width": 842, "height": 595, **_body_page(n_lines=10)},
        {"width": 842, "height": 595, **_body_page(n_lines=10)},
    ])
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    parity = [f for f in verdict["hard"]
              if f["detector"] == "visual_verify.page_parity"]
    assert len(parity) == 1
    assert parity[0]["evidence"] == {
        "pages_document": 4, "pages_pdf": 2,
        "pages_document_source": "artifact_layout_cache"}


def test_a_derived_undercount_is_a_warn_not_a_hard(tmp_path):
    """False-positive guard, calibrated on the corpus: the layout cache
    under-counts whenever the body lives inside tables (measured: 4 of the 10
    rendered corpus forms), and imposition can only FOLD pages — so MORE PDF
    pages than the cache records is reported, never failed."""
    artifact = make_hwpx(tmp_path / "u.hwpx", pages=1)
    pdf = make_pdf(tmp_path / "u.pdf", [_body_page()] * 3)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert not [f for f in verdict["hard"]
                if f["detector"] == "visual_verify.page_parity"]
    warned = [f for f in verdict["warn"]
              if f["detector"] == "visual_verify.page_parity"]
    assert len(warned) == 1
    assert "under-count" in warned[0]["evidence"]["note"]


def test_a_declared_count_still_wins_over_the_derivation(tmp_path):
    """An operator declaration is authoritative, so both directions stay HARD
    — the derivation is a floor under parity, never a ceiling on it."""
    artifact = make_hwpx(tmp_path / "d.hwpx", pages=1)
    pdf = make_pdf(tmp_path / "d.pdf", [_body_page()] * 3)
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"pages_document": 5}),
                            encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    parity = [f for f in verdict["hard"]
              if f["detector"] == "visual_verify.page_parity"]
    assert parity[0]["evidence"]["pages_document_source"] == "expectations"
    assert parity[0]["evidence"]["pages_document"] == 5


def test_page_parity_skips_with_a_reason_when_nothing_is_derivable(tmp_path):
    """A .pdf judged directly has no layout cache: parity skips, and the
    reason says which leg was missing rather than just 'unknown'."""
    pdf = make_pdf(tmp_path / "only.pdf", [_body_page()])
    code, verdict, _ = run("--artifact", pdf, "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    det = verdict["deterministic"]
    assert det["pages_document"] is None
    assert det["pages_document_source"] is None
    reason = next(row for row in det["skipped"]
                  if row.startswith("page_parity:"))
    assert "layout cache" in reason


def test_derive_pages_document_on_the_real_corpus():
    """Calibration, pinned: the derivation never OVER-counts a form whose PDF
    is the ground truth, except on the one form that really is imposed."""
    corpus = REPO_ROOT / "tests" / "corpus" / "forms"
    renders = corpus / "render"
    checked = 0
    for hwpx in sorted((corpus / "converted").glob("*.hwpx")):
        rendered = renders / f"{hwpx.stem}.pdf"
        if not rendered.is_file():
            continue
        checked += 1
        derived, note = visual_verify.derive_pages_document(hwpx)
        assert derived is not None and note is None, hwpx.name
        pages_pdf = fitz.open(str(rendered)).page_count
        if derived > pages_pdf:
            # An OVER-count is the imposition direction, and across the corpus
            # it happens on exactly the forms that store n-up print imposition
            # (nrf-gyeolgwa-bogoseo-yangsik, PrintMethod=4, derives 4 against a
            # 2-page PDF). A form with PrintMethod=0/absent must never
            # over-count, or the HARD leg would false-positive.
            assert visual_verify.stored_print_method(hwpx), (
                f"{hwpx.name}: derived {derived} > pdf {pages_pdf} on a form "
                "that stores no imposition — the HARD parity leg would "
                "false-positive")
    assert checked >= 8, "corpus render set shrank; recalibrate"


# --------------------------------------------------------------------------
# (j) P0-A — ONE fill map, whichever flag carried it
# --------------------------------------------------------------------------

def test_the_same_map_on_both_surfaces_is_the_blessed_invocation(tmp_path):
    """T35's shape rule means one expectations file can serve both flags."""
    artifact = make_form_hwpx(tmp_path / "both.hwpx")
    pdf = _fill_pdf(tmp_path / "both.pdf")
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({"fill_map": _FILL_MAP},
                                       ensure_ascii=False), encoding="utf-8")
    profile = write_form_profile(tmp_path / "profile.json")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--form-profile", profile,
                           "--fill-map", expectations,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 0, verdict
    assert verdict["deterministic"]["fill_map_source"] == "cli+expectations"


def test_two_different_maps_are_a_usage_error_not_a_precedence_rule(tmp_path):
    artifact = make_form_hwpx(tmp_path / "two.hwpx")
    pdf = _fill_pdf(tmp_path / "two.pdf")
    expectations = _fill_expectations(tmp_path / "exp.json")
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"20101": "SOMETHING ELSE"}), encoding="utf-8")
    # the conflict is refused before any check runs
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--fill-map", other,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "DIFFERENT maps" in verdict["error"]


def test_a_cli_fill_map_alone_is_no_longer_a_usage_error(tmp_path):
    """It used to require --form-profile because it 'only applied' to the
    residue delegate. It now seeds expectations.fill_map, so it stands alone —
    while --keep/--keep-pattern really are delegate-only and still refuse."""
    artifact = make_form_hwpx(tmp_path / "alone.hwpx", value_charpr=7)
    pdf = _fill_pdf(tmp_path / "alone.pdf")
    fill_map = tmp_path / "map.json"
    fill_map.write_text(json.dumps({"20101": _FILL_VALUE}), encoding="utf-8")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--fill-map", fill_map,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert "fill_charpr_script_mismatch" in codes(verdict)


def test_the_fill_map_help_states_that_it_is_one_concept():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT))
    help_text = " ".join(proc.stdout.split())
    assert "seeds that member" in help_text
    assert "--accept-without" in help_text
    for check in visual_verify.SAFETY_CHECKS:
        assert check in help_text, check


# --------------------------------------------------------------------------
# T82 -- story-edit render scope
#
# The structural story editor's receipt is deliberately unbound: visual
# verification must judge the current artifact/PDF pair, not turn that receipt
# into a substitute for page/XML/vision evidence.  A story-scoped render has
# no form-fill map, so the fill-only checks are explicitly not applicable;
# XML wellformedness, page parity, required/forbidden text, baseline diff, and
# the mandatory vision handback remain live.
# --------------------------------------------------------------------------

def _story_expectations(path: Path, **extra) -> Path:
    payload = {
        "operation_scope": "story_edit",
        "required_text": ["STORY-NEW"],
        "forbidden_text": ["STORY-OLD"],
    }
    payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _story_support_args(tmp_path, artifact: Path, pdf: Path, *, pages=1):
    """Explicit story-scope proof inputs used by every two-pass invocation."""
    baseline = make_pdf(tmp_path / "baseline.pdf",
                        [_body_page(prefix="STORY-OLD")] * pages)
    conversion = make_conversion_record(
        tmp_path / "conversion.json", artifact, pdf,
        source_print_method=0, print_method_normalized=None,
        pages_document=pages, pages_pdf=pages)
    return ["--artifact", artifact, "--pdf", pdf,
            "--baseline", baseline,
            "--conversion-record", conversion]


def test_t82_story_scope_is_closed_and_rejects_conflicting_fill_inputs(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    support = _story_support_args(tmp_path, artifact, pdf)

    unknown = tmp_path / "unknown.json"
    _story_expectations(unknown, operation_scope="future_story_scope")
    code, verdict, _ = run(*support, "--expectations", unknown,
                           "--png-dir", tmp_path / "unknown-png")
    assert code == 2, verdict
    assert "operation_scope" in verdict["error"]

    with_map = tmp_path / "with-map.json"
    _story_expectations(with_map, fill_map={"seat": "STORY-NEW"})
    code, verdict, _ = run(*support, "--expectations", with_map,
                           "--png-dir", tmp_path / "map-png")
    assert code == 2, verdict
    assert "fill_map" in verdict["error"]

    with_blank = tmp_path / "with-blank.json"
    _story_expectations(with_blank, declared_blank=[])
    code, verdict, _ = run(*support, "--expectations", with_blank,
                           "--png-dir", tmp_path / "blank-png")
    assert code == 2, verdict
    assert "declared_blank" in verdict["error"]

    with_blank_alias = tmp_path / "with-blank-alias.json"
    _story_expectations(with_blank_alias, intentionally_blank=[])
    code, verdict, _ = run(*support, "--expectations", with_blank_alias,
                           "--png-dir", tmp_path / "blank-alias-png")
    assert code == 2, verdict
    assert "intentionally_blank" in verdict["error"]

    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    clean = _story_expectations(tmp_path / "clean.json")
    code, verdict, _ = run(*support, "--expectations", clean,
                           "--form-profile", profile,
                           "--png-dir", tmp_path / "profile-png")
    assert code == 2, verdict
    assert "form-profile" in verdict["error"]


def test_t82_story_scope_rejects_missing_or_malformed_required_text(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    support = _story_support_args(tmp_path, artifact, pdf)

    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps({"operation_scope": "story_edit"}),
                       encoding="utf-8")
    code, verdict, _ = run(*support, "--expectations", missing,
                           "--png-dir", tmp_path / "missing-png")
    assert code == 2, verdict
    assert "required_text" in verdict["error"]

    malformed = tmp_path / "malformed.json"
    _story_expectations(malformed, required_text="STORY-NEW")
    code, verdict, _ = run(*support, "--expectations", malformed,
                           "--png-dir", tmp_path / "malformed-png")
    assert code == 2, verdict
    assert "required_text" in verdict["error"]


def test_t82_story_scope_requires_hwpx_source(tmp_path):
    artifact = make_pdf(tmp_path / "story.pdf",
                        [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    code, verdict, _ = run("--artifact", artifact, "--pdf", artifact,
                           "--baseline", artifact,
                           "--conversion-record", tmp_path / "record.json",
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert ".hwpx" in verdict["error"]


def test_t82_forged_story_scope_cannot_skip_xml_or_page_parity_or_vision(
        tmp_path):
    # A story scope is only valid on an HWPX.  This malformed source proves a
    # scope declaration cannot turn the XML gate into an advisory check; the
    # missing vision handback is still visible on the failed pass1 result.
    artifact = make_hwpx(tmp_path / "forged.hwpx", malformed=True)
    pdf = make_pdf(tmp_path / "forged.pdf",
                   [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    code, verdict, _ = run(*_story_support_args(tmp_path, artifact, pdf),
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert verdict["verdict"] == "fail"
    assert verdict["acceptance"] is False
    assert verdict["acceptance_waivers"] == []
    assert any(row["code"] == "artifact_malformed"
               for row in verdict["hard"])
    assert verdict["vision"]["supplied"] is False
    assert verdict["vision_required"]


def test_t82_required_text_missing_is_hard(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="OTHER")])
    expectations = _story_expectations(tmp_path / "exp.json")
    code, verdict, _ = run(*_story_support_args(tmp_path, artifact, pdf),
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    hits = [row for row in verdict["hard"]
            if row["code"] == "required_text_missing"]
    assert len(hits) == 1, verdict["hard"]
    assert hits[0]["detector"] == "visual_verify.required_text"


def test_t82_forbidden_old_text_is_hard(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [{
        "lines": [(72.0, 100.0, "STORY-NEW", 10.0),
                  (72.0, 120.0, "STORY-OLD", 10.0)],
    }])
    expectations = _story_expectations(tmp_path / "exp.json")
    code, verdict, _ = run(*_story_support_args(tmp_path, artifact, pdf),
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    hits = [row for row in verdict["hard"]
            if row["code"] == "guide_text_visible"]
    assert len(hits) == 1, verdict["hard"]
    assert hits[0]["detector"] == "visual_verify.forbidden_text"


def test_t82_story_pass1_reaches_vision_pending_without_waiver_or_blocker(
    tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    support = _story_support_args(tmp_path, artifact, pdf)
    code, verdict, _ = run(*support, "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert verdict["verdict"] == "vision_pending"
    assert verdict["acceptance"] is False
    assert verdict["acceptance_waivers"] == []
    assert verdict["acceptance_blockers"] == []
    assert verdict["deterministic"]["baseline_diff"] is not None
    assert verdict["deterministic"]["baseline_diff"]["pages"]
    details = {row["check"]: row for row in
               verdict["deterministic"]["not_applicable_details"]}
    for check in ("check_residue", "empty_cell_expected_fill",
                  "fill_charpr_script_mismatch"):
        assert details[check]["status"] == "not_applicable"
    assert not any(row.get("class") == "empty_cell_expected_fill"
                   for row in verdict["warn"])
    assert verdict["vision_required"]


def test_t82_ordinary_form_fill_still_hards_charpr_mismatch(tmp_path):
    artifact = make_form_hwpx(tmp_path / "filled.hwpx", value_charpr=7)
    pdf = _fill_pdf(tmp_path / "filled.pdf")
    expectations = _fill_expectations(tmp_path / "exp.json")
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png",
                           "--deterministic-only")
    assert code == 3, verdict
    assert any(row["code"] == "fill_charpr_script_mismatch"
               for row in verdict["hard"])


@pytest.mark.parametrize("extra", [
    ["--deterministic-only"],
    ["--accept-without", "check_residue"],
    ["--vision-scope", "targeted"],
])
def test_t82_story_scope_rejects_single_pass_or_waiver_shortcuts(tmp_path,
                                                                 extra):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    code, verdict, _ = run(*_story_support_args(tmp_path, artifact, pdf),
                           "--expectations", expectations,
                           *extra,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "story_edit" in verdict["error"]


def test_t82_story_layout_filter_removes_only_fill_warning():
    fill = {"class": "empty_cell_expected_fill", "code": "fill"}
    alignment = {"class": "alignment_drift", "code": "align"}
    findings = [fill, alignment]
    summary = {"pass": False}

    story_findings, story_summary = (
        visual_verify.filter_layout_findings_for_scope(
            findings, summary, "story_edit"))
    assert story_findings == [alignment]
    assert story_summary == {
        "pass": False, "story_scope_empty_cell_suppressed": 1}

    ordinary_findings, ordinary_summary = (
        visual_verify.filter_layout_findings_for_scope(
            findings, summary, None))
    assert ordinary_findings is findings
    assert ordinary_summary is summary


def test_t82_story_scope_requires_nonempty_forbidden_text(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json", forbidden_text=[])
    code, verdict, _ = run(*_story_support_args(tmp_path, artifact, pdf),
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "forbidden_text" in verdict["error"]


@pytest.mark.parametrize("scope", [None, 1, True, [], {}])
def test_t82_operation_scope_type_is_closed_and_traceback_free(tmp_path, scope):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(
        tmp_path / "exp.json", operation_scope=scope)
    code, verdict, stderr = run(*_story_support_args(tmp_path, artifact, pdf),
                                "--expectations", expectations,
                                "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "Traceback" not in stderr
    assert "operation_scope" in verdict["error"]


def test_t82_story_scope_rejects_ordinary_expectation_keys(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(
        tmp_path / "exp.json", blank_pages=[2])
    code, verdict, _ = run(*_story_support_args(tmp_path, artifact, pdf),
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "blank_pages" in verdict["error"]


def test_t82_required_text_cannot_cross_a_page_boundary(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx", pages=2)
    pdf = make_pdf(tmp_path / "story.pdf", [{
        "lines": [(72.0, 100.0, "ABC", 10.0)],
    }, {
        "lines": [(72.0, 100.0, "DEF", 10.0)],
    }])
    expectations = _story_expectations(
        tmp_path / "exp.json", required_text=["ABCDEF"])
    code, verdict, _ = run(*_story_support_args(
        tmp_path, artifact, pdf, pages=2),
        "--expectations", expectations,
        "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert any(row["code"] == "required_text_missing"
               for row in verdict["hard"])


def test_t82_forbidden_text_requires_full_suffix_match(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    actual = "ABCDEFGHIJKLMNOPQRSTV-GOOD"
    forbidden = "ABCDEFGHIJKLMNOPQRSTU-BAD"
    pdf = make_pdf(tmp_path / "story.pdf", [{
        "lines": [(72.0, 100.0, "STORY-NEW", 10.0),
                  (72.0, 120.0, actual, 10.0)],
    }])
    expectations = _story_expectations(
        tmp_path / "exp.json", forbidden_text=[forbidden])
    code, verdict, _ = run(*_story_support_args(tmp_path, artifact, pdf),
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert not any(row["code"] == "guide_text_visible"
                   for row in verdict["hard"]), verdict["hard"]


def test_t82_supplied_vision_must_review_every_page(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx", pages=2)
    pdf = make_pdf(tmp_path / "story.pdf",
                   [_body_page(prefix="STORY-NEW")] * 2)
    expectations = _story_expectations(tmp_path / "exp.json")
    vision = tmp_path / "vision.json"
    vision.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": [1], "findings": []}), encoding="utf-8")
    code, verdict, _ = run(*_story_support_args(
        tmp_path, artifact, pdf, pages=2),
        "--expectations", expectations,
        "--vision-verdict", vision,
        "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "all pages" in verdict["error"]


def _drop_cli_option(argv, option):
    result = list(argv)
    index = result.index(option)
    del result[index:index + 2]
    return result


def test_t82_clean_pass2_accepts_only_after_all_pages_vision(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    vision = _reviewed(tmp_path, pages=(1,))
    code, verdict, _ = run(*_story_support_args(tmp_path, artifact, pdf),
                           "--expectations", expectations,
                           "--vision-verdict", vision,
                           "--png-dir", tmp_path / "png")
    assert code == 0, verdict
    assert verdict["verdict"] == "pass"
    assert verdict["acceptance"] is True
    assert verdict["acceptance_waivers"] == []
    assert verdict["acceptance_blockers"] == []


@pytest.mark.parametrize("missing", ["--pdf", "--baseline",
                                      "--conversion-record"])
def test_t82_requires_explicit_render_proof_inputs(tmp_path, missing):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    argv = _story_support_args(tmp_path, artifact, pdf)
    code, verdict, _ = run(*_drop_cli_option(argv, missing),
                           "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert missing.lstrip("-") in verdict["error"]


def test_t82_t80_receipt_cannot_bind_render(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    argv = _story_support_args(tmp_path, artifact, pdf)
    receipt = tmp_path / "story-edit-receipt.json"
    receipt.write_text(json.dumps({
        "schema": "rigorloom/hwpx-story-edit/v1", "status": "passed",
        "render": "not_run"}), encoding="utf-8")
    index = argv.index("--conversion-record")
    argv[index + 1] = receipt
    code, verdict, _ = run(*argv, "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "schema" in verdict["error"]


@pytest.mark.parametrize("swap", ["artifact", "pdf"])
def test_t82_conversion_record_hash_binding_rejects_swapped_bytes(tmp_path,
                                                                   swap):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    argv = _story_support_args(tmp_path, artifact, pdf)
    if swap == "artifact":
        artifact.write_bytes(artifact.read_bytes() + b"SWAPPED")
    else:
        pdf.write_bytes(pdf.read_bytes() + b"SWAPPED")
    code, verdict, _ = run(*argv, "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "different" in verdict["error"] or "Re-run" in verdict["error"]


@pytest.mark.parametrize("pages_document", [None, 0, False])
def test_t82_conversion_page_fields_are_closed(tmp_path, pages_document):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    # Rewrite the explicit record after the helper created the valid one.
    record = make_conversion_record(
        tmp_path / "bad-conversion.json", artifact, pdf,
        source_print_method=0, print_method_normalized=None,
        pages_document=pages_document, pages_pdf=1)
    argv = _story_support_args(tmp_path, artifact, pdf)
    index = argv.index("--conversion-record")
    argv[index + 1] = record
    code, verdict, _ = run(*argv, "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict


def test_t82_document_pdf_page_parity_remains_hard(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx", pages=2)
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    record = make_conversion_record(
        tmp_path / "parity.json", artifact, pdf,
        source_print_method=0, print_method_normalized=None,
        pages_document=2, pages_pdf=1)
    argv = _story_support_args(tmp_path, artifact, pdf)
    index = argv.index("--conversion-record")
    argv[index + 1] = record
    code, verdict, _ = run(*argv, "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 3, verdict
    assert any(row["code"] == "imposition_mismatch"
               for row in verdict["hard"])


@pytest.mark.parametrize("source_print_method,normalized", [
    (None, None),
    (0, {"from": 4, "to": 0}),
    (4, {"from": 4, "to": 1}),
])
def test_t82_conversion_print_method_binding_is_closed(
        tmp_path, source_print_method, normalized):
    artifact = make_hwpx(tmp_path / "story.hwpx", print_method=4)
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    record = make_conversion_record(
        tmp_path / "print-method.json", artifact, pdf,
        source_print_method=source_print_method,
        print_method_normalized=normalized,
        pages_document=1, pages_pdf=1)
    argv = _story_support_args(tmp_path, artifact, pdf)
    index = argv.index("--conversion-record")
    argv[index + 1] = record
    code, verdict, _ = run(*argv, "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict


def test_t82_valid_conversion_print_method_normalization_still_runs_parity(
        tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx", print_method=4)
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    record = make_conversion_record(
        tmp_path / "print-method-valid.json", artifact, pdf,
        source_print_method=4, print_method_normalized={"from": 4, "to": 0},
        pages_document=1, pages_pdf=1)
    vision = _reviewed(tmp_path, pages=(1,))
    argv = _story_support_args(tmp_path, artifact, pdf)
    index = argv.index("--conversion-record")
    argv[index + 1] = record
    code, verdict, _ = run(*argv, "--expectations", expectations,
                           "--vision-verdict", vision,
                           "--png-dir", tmp_path / "png")
    assert code == 0, verdict
    assert not [row for row in verdict["hard"]
                if row["code"] == "imposition_mismatch"]


def test_t82_baseline_must_be_comparable(tmp_path):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    support = _story_support_args(tmp_path, artifact, pdf)
    baseline = make_pdf(tmp_path / "mismatch-baseline.pdf",
                        [_body_page(prefix="STORY-OLD"),
                         _body_page(prefix="STORY-OLD")])
    index = support.index("--baseline")
    support[index + 1] = baseline
    code, verdict, _ = run(*support, "--expectations", expectations,
                           "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "comparable" in verdict["error"]


@pytest.mark.parametrize("extra", [
    ["--fill-map", "MAP.json"],
    ["--keep", "STORY-OLD"],
    ["--keep-pattern", "STORY"],
])
def test_t82_cli_fill_inputs_conflict(tmp_path, extra):
    artifact = make_hwpx(tmp_path / "story.hwpx")
    pdf = make_pdf(tmp_path / "story.pdf", [_body_page(prefix="STORY-NEW")])
    expectations = _story_expectations(tmp_path / "exp.json")
    support = _story_support_args(tmp_path, artifact, pdf)
    if extra[0] == "--fill-map":
        (tmp_path / extra[1]).write_text(json.dumps({"seat": "STORY-NEW"}),
                                         encoding="utf-8")
        extra = [extra[0], tmp_path / extra[1]]
    code, verdict, _ = run(*support, "--expectations", expectations,
                           *extra, "--png-dir", tmp_path / "png")
    assert code == 2, verdict
    assert "story_edit" in verdict["error"]


# --------------------------------------------------------------------------
# (k) P0-B — the exit-code contract, every terminal state
#
# The clean-room sol and terra tiers both received process exit 1 for
# vision_pending, where the docs and the verdict contract say 3. 3 is right
# (it is checker_base.EXIT_HARD, the finding/pending code every checker uses);
# 1 was an UNHANDLED path — emit_verdict sat outside every guard, so an
# unwritable --out escaped as a traceback. No invocation may exit 1.
# --------------------------------------------------------------------------

def _terminal_states(tmp_path):
    """(name, expected_exit, argv) for every terminal state of the script."""
    clean, clean_pdf = _clean_run(tmp_path / "clean")
    vision = tmp_path / "vision.json"
    vision.write_text(json.dumps({
        "schema": "rigorloom/visual-vision-verdict/v1",
        "pages_reviewed": [1, 2], "findings": []}), encoding="utf-8")
    blank = make_hwpx(tmp_path / "blank" / "b.hwpx")
    blank_pdf = make_pdf(tmp_path / "blank" / "b.pdf", [{"lines": []}])
    base = ("--artifact", clean, "--pdf", clean_pdf,
            "--png-dir", tmp_path / "png")
    return [
        ("pass", 0, (*base, "--vision-verdict", vision, *_CLEAN_WAIVERS)),
        ("deterministic_pass", 0, (*base, "--deterministic-only")),
        ("vision_pending", 3, (*base, *_CLEAN_WAIVERS)),
        ("safety_incomplete", 3, (*base, "--vision-verdict", vision)),
        ("fail", 3, ("--artifact", blank, "--pdf", blank_pdf,
                     "--png-dir", tmp_path / "png2")),
        ("usage_error", 2, ("--artifact", tmp_path / "nope.hwpx")),
    ]


def test_exit_code_matrix(tmp_path):
    """Every terminal state, its verdict string and its exit code, in one
    table — and 1 is not in it."""
    for name, expected_code, argv in _terminal_states(tmp_path):
        code, verdict, stderr = run(*argv)
        assert verdict is not None, (name, stderr)
        assert verdict["verdict"] == name, (name, verdict["verdict"])
        assert code == expected_code, (name, code, verdict["verdict"])
        assert code != 1, name
        assert code in (0, 2, 3), (name, code)
        # ok/acceptance must agree with the row
        assert verdict["ok"] is (expected_code == 0)
        if name != "usage_error":
            assert verdict["acceptance"] is (name == "pass")
        else:
            assert "acceptance" not in verdict


def test_vision_pending_exits_3_not_1(tmp_path):
    """The reported defect, pinned on its own so a regression names itself."""
    artifact, pdf = _clean_run(tmp_path)
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png", *_CLEAN_WAIVERS)
    assert verdict["verdict"] == "vision_pending"
    assert code == 3, "3 = EXIT_HARD, the finding/pending code of every checker"


def test_an_unwritable_out_is_a_usage_error_not_a_traceback(tmp_path):
    """The reachable exit-1 path: --out naming an existing directory made
    emit_verdict raise PermissionError after a perfectly good verdict."""
    artifact, pdf = _clean_run(tmp_path)
    collision = tmp_path / "verdict_dir"
    collision.mkdir()
    code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                           "--png-dir", tmp_path / "png",
                           "--out", collision)
    assert code == 2, verdict
    assert verdict["verdict"] == "usage_error"
    assert "--out" in verdict["error"]


def test_a_verdict_that_cannot_be_serialized_degrades_to_usage(
        tmp_path, monkeypatch, capsys):
    """Backstop for the same class: emission failure is the usage row (2),
    never a traceback and never exit 1."""
    artifact, pdf = _clean_run(tmp_path)

    def boom(*_a, **_k):
        raise ValueError("Out of range float values are not JSON compliant")

    monkeypatch.setattr(visual_verify, "emit_verdict", boom)
    code = visual_verify.main([
        "--artifact", str(artifact), "--pdf", str(pdf),
        "--png-dir", str(tmp_path / "png")])
    assert code == 2
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["verdict"] == "usage_error"
    assert "could not emit the verdict" in payload["error"]


def test_the_exit_code_table_is_documented(tmp_path):
    """The docstring table and operations.md must agree with the code."""
    source = (REPO_ROOT / "pipeline" / "scripts" / "visual_verify.py").read_text(
        encoding="utf-8")
    operations = (REPO_ROOT / "skill" / "references" / "operations.md").read_text(
        encoding="utf-8")
    for name, expected_code, _ in _terminal_states(tmp_path):
        assert re.search(rf"{name}\s+{expected_code}\s", source), name
        assert name in operations, name
    assert "safety_incomplete" in operations
    assert "acceptance_waivers" in operations


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
        "accept_without": [],
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


# --------------------------------------------------------------------------
# Q3 — a warning every correct run emits is a warning nobody reads
#
# failing-before: every accepted tier of the v0.17 clean-room run carried the
# SAME two `empty_cell_expected_fill` warns, at y=91.2 and y=350.3 on the PPS
# fill — one for a by-design-blank matrix stub head, one for a cell nobody
# supplied. Both were correct runs. The evidence was a y coordinate, which
# says a table on this page has a blank header cell and leaves finding it to
# the reader.
# --------------------------------------------------------------------------

def _header_rows(rows, at_y=100.0):
    return layout_qa.header_cell_violations(rows, at_y)


def test_header_cell_empty_names_the_seat_by_its_label():
    """The surviving warning identifies the seat, not a coordinate."""
    rows = [["신청업체", "기 업 명", "한빛정밀(주)", "법인등록번호", ""],
            ["", "주    소", "서울…", "", ""]]
    items = _header_rows(rows, 91.2)
    assert len(items) == 1
    assert items[0]["label"] == "법인등록번호"
    assert items[0]["col"] == 4
    assert items[0]["spacer_pattern"] is None
    reason, label = visual_verify.resolve_header_cell_empty(items[0], ())
    assert reason is None                      # nothing suppresses it
    assert label == "법인등록번호"


def test_matrix_stub_head_is_a_spacer_not_a_warning():
    """PPS y=350.3: the corner where column headers meet the row labels."""
    rows = [["", "기 업 명", "대표자", "전 화", "메일주소"],
            ["참여기업", "대한기계(주)", "박정우", "031-777-0101", "경기도…"]]
    items = _header_rows(rows, 350.3)
    assert [i["spacer_pattern"] for i in items] == ["stub_head"]
    reason, _label = visual_verify.resolve_header_cell_empty(items[0], ())
    assert reason == "spacer:stub_head"


def test_wholly_blank_band_is_one_fact_not_one_per_column():
    rows = [["", "", "", ""], ["신청인", "", "", ""]]
    items = _header_rows(rows)
    assert len(items) == 1
    assert items[0]["spacer_pattern"] == "blank_band"
    assert items[0]["col"] is None
    reason, _ = visual_verify.resolve_header_cell_empty(items[0], ())
    assert reason == "spacer:blank_band"


def test_declared_blank_suppresses_only_the_seat_it_names():
    rows = [["신청업체", "기 업 명", "", "법인등록번호", ""],
            ["", "주    소", "서울…", "", ""]]
    items = _header_rows(rows)
    labels = [i["label"] for i in items]
    assert labels == ["기 업 명", "법인등록번호"]
    reasons = [visual_verify.resolve_header_cell_empty(
        item, ["법인등록번호"])[0] for item in items]
    assert reasons == [None, "declared_blank"]


def test_declared_blank_matching_is_whitespace_normalized():
    """Form labels carry the form's own padding; a caller will not retype it."""
    assert visual_verify.declared_blank_match(["성명"], "성    명") == "성명"
    assert visual_verify.declared_blank_match(["성    명"], "성명") == "성    명"
    assert visual_verify.declared_blank_match(["대표자"], "법인등록번호") is None
    assert visual_verify.declared_blank_match([], "성명") is None


def test_declared_blank_is_one_list_however_it_is_spelled(tmp_path):
    """`declared_blank` is the name; `intentionally_blank` is its alias.

    Two spellings for one concept is the T36 defect shape, so they reconcile
    into ONE list and the verdict records every surface it arrived on."""
    fill_map = tmp_path / "fill.json"
    fill_map.write_text(json.dumps({
        "fill_map": {"applicant": "Hong Gildong"},
        "declared_blank": ["signature"],
    }), encoding="utf-8")
    expectations = {"intentionally_blank": ["date"]}
    entries, sources, error = visual_verify.reconcile_declared_blank(
        expectations, fill_map)
    assert error is None
    assert entries == ["date", "signature"]
    assert sources == ["expectations.intentionally_blank",
                       "fill_map.declared_blank"]


def test_declared_blank_wrong_shape_is_a_usage_error():
    _e, _s, error = visual_verify.reconcile_declared_blank(
        {"declared_blank": "signature"}, None)
    assert error and "list of seat names" in error


def test_declared_blank_and_suppression_are_recorded_in_the_verdict(tmp_path):
    """Suppression must be auditable — never a silent drop."""
    artifact = make_hwpx(tmp_path / "a.hwpx")
    pdf = make_pdf(tmp_path / "a.pdf", [_body_page()])
    expectations = tmp_path / "exp.json"
    expectations.write_text(json.dumps({
        "fill_map": {"applicant": "Hong Gildong", "date": "2026-08-08"},
        "declared_blank": ["date"],
    }), encoding="utf-8")
    _code, verdict, _ = run("--artifact", artifact, "--pdf", pdf,
                            "--expectations", expectations,
                            "--png-dir", tmp_path / "png")
    det = verdict["deterministic"]
    assert det["declared_blank"] == ["date"]
    assert det["declared_blank_source"] == ["expectations.declared_blank"]
    assert "empty_cell_suppressed" in det["layout_qa"]
    # still-catches: the undeclared label is still reported by name.
    labels = {f["evidence"]["label"] for f in verdict["hard"]
              if f["class"] == "empty_cell_expected_fill"}
    assert labels == {"applicant"}


# ---------------------------------------------------------------------------
# T100: a gate must not blame the artifact for a property it inherited from
# the blank form. Attribution only — severity never moves.
# ---------------------------------------------------------------------------

def _fmt_record(page=1, median_pt=10.0, line_pitch_pt=16.0,
                content_bbox_pt=(60.0, 60.0, 535.0, 780.0),
                width_pt=595.0, height_pt=842.0):
    """One measured page, built directly.

    The legs under test take records, so building them beats rendering a PDF:
    the point is the attribution arithmetic, and a fixture that also exercises
    fitz would hide which of the two failed.
    """
    return {"page": page, "median_pt": median_pt,
            "line_pitch_pt": line_pitch_pt,
            "content_bbox_pt": content_bbox_pt,
            "width_pt": width_pt, "height_pt": height_pt}


def _fmt_findings(records, expectations, baseline=None):
    return visual_verify.check_format(records, expectations, baseline)


def test_t100_a_base_pt_violation_the_blank_form_also_has_is_inherited():
    """The heart of the class: the form's own labels set the median size.

    A declaration the blank form already fails will fail on every page no
    matter how correct the fill is, so the operator has to know the fill is not
    the thing to edit.
    """
    off_spec = [_fmt_record(median_pt=8.0)]
    found = _fmt_findings(off_spec, {"base_pt": 11.0}, off_spec)
    assert len(found) == 1
    assert found[0]["evidence"]["inherited"] == visual_verify.INHERITED_YES
    assert "cannot satisfy it" in found[0]["evidence"]["note"]


def test_t100_a_base_pt_violation_the_fill_introduced_is_not_inherited():
    found = _fmt_findings([_fmt_record(median_pt=8.0)], {"base_pt": 11.0},
                          [_fmt_record(median_pt=11.0)])
    assert found[0]["evidence"]["inherited"] == visual_verify.INHERITED_NO
    assert "note" not in found[0]["evidence"]


def test_t100_attribution_is_unknown_and_says_why_without_a_baseline():
    """Never guessed. A run with no measurable baseline says so."""
    found = _fmt_findings([_fmt_record(median_pt=8.0)], {"base_pt": 11.0})
    evidence = found[0]["evidence"]
    assert evidence["inherited"] == visual_verify.INHERITED_UNKNOWN
    assert "--baseline" in evidence["inherited_reason"]


def test_t100_attribution_never_changes_severity():
    """The still-catches for the whole slice.

    This is attribution, not relaxation: the document as submitted really does
    violate the declaration in both cases, so both stay HARD. A future change
    that quietly downgrades the inherited case has to fail here.
    """
    inherited = _fmt_findings([_fmt_record(median_pt=8.0)], {"base_pt": 11.0},
                              [_fmt_record(median_pt=8.0)])
    introduced = _fmt_findings([_fmt_record(median_pt=8.0)], {"base_pt": 11.0},
                               [_fmt_record(median_pt=11.0)])
    assert [f["severity"] for f in inherited] == ["hard"]
    assert [f["severity"] for f in introduced] == ["hard"]


def test_t100_a_compliant_page_reports_nothing_with_or_without_a_baseline():
    """Non-vacuity guard: the attribution code must not invent findings."""
    good = [_fmt_record(median_pt=11.0)]
    assert _fmt_findings(good, {"base_pt": 11.0}) == []
    assert _fmt_findings(good, {"base_pt": 11.0}, good) == []


def test_t100_line_spacing_attribution_uses_the_baselines_own_ratio():
    """Spacing is a ratio, so the baseline has to be recomputed, not copied."""
    artifact = [_fmt_record(median_pt=10.0, line_pitch_pt=30.0)]  # 300%
    same_ratio = [_fmt_record(median_pt=12.0, line_pitch_pt=36.0)]  # also 300%
    found = _fmt_findings(artifact, {"line_spacing_pct": 160.0}, same_ratio)
    spacing = [f for f in found
               if f["detector"] == "visual_verify.line_spacing"]
    assert len(spacing) == 1
    assert spacing[0]["evidence"]["inherited"] == visual_verify.INHERITED_YES


def test_t100_margin_attribution_is_independent_per_side():
    """Each side is attributed from its own declaration, not a shared one.

    The artifact violates BOTH left and top; the blank form violates only left.
    So a correct implementation returns one inherited finding and one not.

    Note on what this does NOT prove: the predicate is invoked immediately
    inside the loop iteration, so a closure over the loop variables would read
    the current values and behave identically. The default-argument binding in
    `_margin_fails` is defensive against a future refactor that defers the
    call; it is not what keeps this test green, and mutating it away does not
    fail here. Said out loud because the first version of this docstring
    claimed the opposite.
    """
    artifact = [_fmt_record(content_bbox_pt=(5.0, 5.0, 535.0, 780.0))]
    baseline = [_fmt_record(content_bbox_pt=(5.0, 60.0, 535.0, 780.0))]
    found = _fmt_findings(artifact, {"margins_mm": {"left": 20.0,
                                                    "top": 20.0}}, baseline)
    by_side = {f["evidence"]["side"]: f["evidence"]["inherited"]
               for f in found}
    assert by_side == {"left": visual_verify.INHERITED_YES,
                       "top": visual_verify.INHERITED_NO}


def test_t100_attribution_is_unknown_when_the_blank_form_lacks_that_page():
    """A shorter blank form cannot answer for a page it does not have."""
    found = _fmt_findings([_fmt_record(page=3, median_pt=8.0)],
                          {"base_pt": 11.0}, [_fmt_record(page=1)])
    evidence = found[0]["evidence"]
    assert evidence["inherited"] == visual_verify.INHERITED_UNKNOWN
    assert "page 3" in evidence["inherited_reason"]


def test_t100_page_budget_inherited_when_the_blank_form_already_exceeds():
    """A three-page form filed under max: 2 fails before anyone types."""
    found = visual_verify.check_page_budget(
        {"page_budget": {"max": 2}}, 3,
        [_fmt_record(page=1), _fmt_record(page=2), _fmt_record(page=3)])
    assert len(found) == 1
    assert found[0]["severity"] == "hard"
    assert found[0]["evidence"]["inherited"] == visual_verify.INHERITED_YES
    assert found[0]["evidence"]["baseline_pages"] == 3


def test_t100_page_budget_not_inherited_when_the_fill_grew_the_document():
    found = visual_verify.check_page_budget(
        {"page_budget": {"max": 2}}, 3, [_fmt_record(page=1)])
    assert found[0]["evidence"]["inherited"] == visual_verify.INHERITED_NO


def test_t100_page_budget_attribution_is_unknown_without_a_baseline():
    found = visual_verify.check_page_budget({"page_budget": {"max": 2}}, 3)
    assert (found[0]["evidence"]["inherited"]
            == visual_verify.INHERITED_UNKNOWN)


def test_t100_an_image_directory_baseline_cannot_attribute(tmp_path):
    """A directory of page images has no text layer.

    Point size, line pitch and content bbox are not recoverable from pixels, so
    this returns None and the legs report unknown — rather than measuring
    something else and calling it the same quantity.
    """
    images = tmp_path / "baseline_pages"
    images.mkdir()
    (images / "page_001.png").write_bytes(b"not really a png")
    assert visual_verify._baseline_format_records(
        visual_verify.fitz if hasattr(visual_verify, "fitz") else None,
        images, 130) is None


# ---------------------------------------------------------------------------
# T101: one attribution vocabulary per finding class
# ---------------------------------------------------------------------------

INHERITED_STATES = {"yes", "no", "unknown"}


def _attribution_carrying(verdict):
    """Every format_noncompliance finding in a verdict, all buckets."""
    out = []
    for bucket in ("hard", "warn", "deterministic"):
        for item in verdict.get(bucket) or []:
            if isinstance(item, dict) and item.get("class") == "format_noncompliance":
                out.append(item)
    return out


def test_t101_every_format_noncompliance_finding_carries_one_vocabulary(
        tmp_path, monkeypatch):
    """The regression T100 shipped and the bench caught.

    ``format_noncompliance`` had two vocabularies for one question: the T100
    legs put ``inherited`` in the evidence, while the T40 charPr leg answered
    the same thing with ``form_baseline_checked`` / ``form_baseline_match`` /
    ``form_baseline_note`` and no ``inherited`` key at all. A consumer
    filtering the class on ``inherited`` therefore skipped the strongest
    baseline comparison in the file and could not tell that from "nothing was
    inherited".

    The invariant, asserted over a real verify run rather than a constructed
    finding: every finding of this class carries ``inherited``, and its value
    is in the closed tri-state.
    """
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=_SEAT_LABEL)
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx", seat=_SEAT_FILLED)
    verdict, _code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=blank,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))
    findings = _attribution_carrying(verdict)
    assert findings, "fixture produced no format_noncompliance finding to check"
    missing = [f["code"] for f in findings if "inherited" not in f["evidence"]]
    assert missing == []
    bad = {f["code"]: f["evidence"]["inherited"] for f in findings
           if f["evidence"]["inherited"] not in INHERITED_STATES}
    assert bad == {}


def test_t101_an_inherited_seat_signature_reads_yes(tmp_path, monkeypatch):
    """The T40 WARN and the T100 legs now say the same word for the same fact."""
    blank = make_seat_form_hwpx(tmp_path / "blank.hwpx", seat=_SEAT_LABEL)
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx", seat=_SEAT_FILLED)
    verdict, _code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=blank,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))
    inherited = [f for f in _attribution_carrying(verdict)
                 if f["code"] == "fill_charpr_script_inherited"]
    assert inherited, "expected the T40 inherited WARN in this fixture"
    for item in inherited:
        assert item["evidence"]["inherited"] == visual_verify.INHERITED_YES
        # The detail behind the verdict is kept, not replaced.
        assert item["evidence"]["form_baseline_checked"] is True


def test_t101_no_hwpx_baseline_reads_unknown_not_no(tmp_path, monkeypatch):
    """Failing to find the evidence is not the same as finding the fill guilty.

    Without an ``.hwpx`` baseline the blank form's seat cannot be identified,
    so the charPr leg must report ``unknown`` with a reason — never ``no``,
    which would assert the fill introduced a signature nobody checked.
    """
    artifact = make_seat_form_hwpx(tmp_path / "filled.hwpx", seat=_SEAT_FILLED)
    verdict, _code = _seat_run(
        tmp_path, monkeypatch, artifact=artifact, baseline=None,
        expectations=str(_seat_expectations(tmp_path / "exp.json")))
    mismatches = [f for f in _attribution_carrying(verdict)
                  if f["code"] == "fill_charpr_script_mismatch"]
    assert mismatches, "expected the T40 HARD without a baseline"
    for item in mismatches:
        assert item["evidence"]["inherited"] == visual_verify.INHERITED_UNKNOWN
        assert item["evidence"]["inherited_reason"]
