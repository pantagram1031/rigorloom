# -*- coding: utf-8 -*-
"""T102: the rubric's coverage column is derived, not remembered.

`visual-rubric.md` tells a vision agent which rubric classes the deterministic
half has already decided. A wrong entry is not cosmetic:

* understating coverage (calling a covered class NONE) invites the judge to
  re-adjudicate an answered question and treat its own disagreement as
  authoritative;
* overstating it (calling an uncovered class FULL) invites the judge to skip an
  unanswered one.

Both happened. `alignment_drift` was called NONE while four `_LAYOUT_QA_MAP`
legs mapped to it, and `missing_glyphs` was called FULL by naming
`render_quality` — a real deterministic checker that runs in the `doc_backend`
/ `submission_preflight` pipeline, not in the tool this rubric governs. The
same stale belief was in a `visual_verify` comment, so the document was
mirroring the code rather than disagreeing with it.

This asserts the BINARY only: covered versus not covered. FULL versus PARTIAL
is a judgement about what a detector establishes and stays prose; a test that
claimed to check it would be the same kind of overclaim it exists to prevent.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "scripts"))

RUBRIC = ROOT / "skill" / "references" / "visual-rubric.md"
SOURCE = ROOT / "pipeline" / "scripts" / "visual_verify.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def _governed_classes() -> tuple[str, ...]:
    block = re.search(r"RUBRIC_CLASSES\s*=\s*\((.*?)\)", _source(), re.S)
    assert block, "RUBRIC_CLASSES not found in visual_verify.py"
    return tuple(re.findall(r'"([a-z_]+)"', block.group(1)))


def _detected_classes() -> dict[str, set[str]]:
    """``class -> detectors`` for everything ``visual_verify`` can emit.

    Two sources, because the script has two ways of producing a class: a
    ``finding(...)`` call naming both ``cls`` and ``detector``, and the
    ``_LAYOUT_QA_MAP`` translation of the engine's layout_qa findings.
    """
    text = _source()
    found: dict[str, set[str]] = {}
    for pattern in (r'cls="([a-z_]+)"[^)]*?detector="([a-z_.]+)"',
                    r'detector="([a-z_.]+)"[^)]*?cls="([a-z_]+)"'):
        for match in re.finditer(pattern, text, re.S):
            first, second = match.groups()
            cls, detector = ((first, second) if pattern.startswith("cls")
                             else (second, first))
            found.setdefault(cls, set()).add(detector)
    mapping = re.search(r"_LAYOUT_QA_MAP\s*=\s*\{(.*?)\n\}", text, re.S)
    assert mapping, "_LAYOUT_QA_MAP not found in visual_verify.py"
    for match in re.finditer(
            r'\(\s*"([a-z_]+)"\s*,\s*(?:"([a-z_]+)"|None)\s*\)\s*:\s*\(\s*"([a-z_]+)"',
            mapping.group(1)):
        leg, sub, cls = match.groups()
        label = "layout_qa." + leg + ("/" + sub if sub else "")
        found.setdefault(cls, set()).add(label)
    return found


def _rubric_rows() -> dict[str, str]:
    """``class -> the coverage cell`` as the shipped table states it."""
    rows = {}
    for line in RUBRIC.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\|\s*`([a-z_]+)`\s*\|\s*(?:hard|warn)\s*\|(.*)\|\s*$",
                         line)
        if match:
            rows[match.group(1)] = match.group(2).strip()
    return rows


def _says_none(cell: str) -> bool:
    """Does this cell claim no deterministic coverage in visual_verify?

    Matched on the leading token so that a cell naming coverage elsewhere --
    ``NONE in visual_verify ... covers it FULLY in a DIFFERENT run`` -- still
    reads as NONE for this tool, which is the honest reading.
    """
    return re.match(r"\**NONE\b", cell.strip().lstrip("*")) is not None \
        or cell.strip().startswith("**NONE")


def test_the_rubric_documents_every_governed_class():
    """Non-vacuity floor: the rest is trivially true over an empty table."""
    rows = _rubric_rows()
    missing = [cls for cls in _governed_classes() if cls not in rows]
    assert missing == []
    assert len(rows) >= len(_governed_classes())


def test_no_covered_class_is_documented_as_uncovered():
    """The alignment_drift error, and the one that misleads most.

    A class the deterministic half already decides, documented as NONE, tells
    the vision agent to decide it alone.
    """
    detected = _detected_classes()
    rows = _rubric_rows()
    wrong = {cls: sorted(detected[cls]) for cls in _governed_classes()
             if cls in detected and _says_none(rows.get(cls, ""))}
    assert wrong == {}


def test_no_uncovered_class_is_documented_as_covered():
    """The missing_glyphs error, in the opposite direction.

    A class no detector in this tool emits, documented as covered, tells the
    vision agent the question is already answered. Naming a checker from
    another pipeline is allowed, but the cell has to lead with NONE for THIS
    tool -- which is what the corrected row does.
    """
    detected = _detected_classes()
    rows = _rubric_rows()
    wrong = {cls: rows.get(cls, "") for cls in _governed_classes()
             if cls not in detected and not _says_none(rows.get(cls, ""))}
    assert wrong == {}


def test_the_derivation_finds_the_detectors_it_should():
    """Guards the parser, not the document.

    If the extraction silently stopped matching, both assertions above would
    pass vacuously for every class at once -- the failure mode of a test that
    derives its own expectations.
    """
    detected = _detected_classes()
    assert len(detected) >= 8, detected
    assert "layout_qa.line_spacing_uniformity" in detected["alignment_drift"]
    assert len(detected["alignment_drift"]) >= 4
    assert any(d.startswith("visual_verify.") for d in detected["blank_render"])
    assert "missing_glyphs" not in detected


def test_the_vision_owned_hard_class_is_not_claimed_as_deterministic():
    """VISION_HARD_CLASSES is the source of truth for who decides.

    A class the vision half owns and cannot downgrade must not be presented as
    deterministically covered in this tool.
    """
    block = re.search(r"VISION_HARD_CLASSES\s*=\s*frozenset\(\{(.*?)\}\)",
                      _source(), re.S)
    assert block, "VISION_HARD_CLASSES not found"
    rows = _rubric_rows()
    for cls in re.findall(r'"([a-z_]+)"', block.group(1)):
        assert _says_none(rows[cls]), (cls, rows[cls])
