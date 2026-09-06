# -*- coding: utf-8 -*-
"""The MEASURED stand-in advance table, and the line it was built to close.

#316 found thirteen paragraphs the ``syllable`` break candidate loses, and
diagnosed eleven of them as a width error on runs whose declared face this
machine does not have: our resolver substitutes the bundled ``NanumMyeongjo``
for 휴먼명조 and meters the run off the substitute's outlines, which advance a
Hangul syllable at about 0.950 em where the reference PDFs draw the declared
face at 0.996.  Under-measuring every syllable by 5 % is what let our breaker
fit one syllable more than Hancom did.

``hft-widths.measured.json``'s ``standin_faces`` section carries the drawn
advances for exactly those faces, and ``OwnRenderer._standin_advance_hwp``
reads it.  What is pinned here:

* the section exists, is declared MEASURED, and carries widths only;
* the renderer reads it, and answers ``None`` for a face it does not carry;
* the rule is gated on the RESOLVER, not on anything the document declares --
  an installed face is never corrected by it;
* one of the eleven, ``moel-2013`` ¶118, actually turns on it: under the
  ``syllable`` break candidate its computed breaks equal the cached ones WITH
  the table and do not without it.

The last one is the falsifiable claim.  It is a path-B measurement -- our own
flow pass scored against the cache -- and it is deliberately run under the
``syllable`` candidate, which this branch does NOT ship: the table is inert
under the shipped breaker, and pinning it there would pin nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "scripts"))

import advance_probe  # noqa: E402
import own_render  # noqa: E402
import syllable_break_probe as probe  # noqa: E402

CORPUS = ROOT / "tests" / "corpus" / "forms" / "converted"
TABLE = ROOT / "engine" / "references" / "fonts" / "hft-widths.measured.json"

#: The face the whole public corpus substitutes, and the em its Hangul was
#: drawn at.  Loose enough to survive a re-measurement, tight enough that the
#: stand-in's own 0.950 would fail it.
STANDIN_FACE = "휴먼명조"
DRAWN_FULL_WIDTH_EM = 0.9964

#: One of the eleven.  ``moel-2013`` ¶118 is the narrowest of them -- our line
#: was inside its box by 135.4 HWPUNIT, the smallest margin of the eleven --
#: so it is the one a partial correction would fail to move.
PINNED = ("moel-pyojun-geunrogyeyakseo-2013", 118)


def _form(stem):
    path = CORPUS / (stem + ".hwpx")
    if not path.is_file():
        pytest.skip(f"corpus fixture missing: {path}")
    return path


@pytest.fixture(scope="module")
def payload():
    if not TABLE.is_file():
        pytest.skip(f"measured table missing: {TABLE}")
    return json.loads(TABLE.read_text(encoding="utf-8"))


# -- the data -------------------------------------------------------------

def test_the_section_is_declared_measured_and_widths_only(payload):
    declaration = payload.get("standin_declaration")
    assert declaration, "the stand-in section carries no declaration"
    assert declaration["status"] == "MEASURED"
    assert declaration["contains"] == "advance widths only"
    # The HFT section can say "no font program" because a Type 3 font has
    # none.  A TTF face is embedded, so this section has to say the stronger
    # thing: the measurement never opened the font object at all.
    assert "font program" in declaration["does_not_contain"]
    assert "never opens one" in declaration["why_not_the_font_object"]


def test_the_section_carries_the_face_the_corpus_substitutes(payload):
    seat = (payload.get("standin_faces") or {}).get(STANDIN_FACE)
    assert seat, f"{STANDIN_FACE} is not in the stand-in section"
    assert seat["declared_type"] == "TTF"
    assert seat["full_width_em"] == pytest.approx(DRAWN_FULL_WIDTH_EM,
                                                  abs=0.002)
    assert seat["code_points"] >= 100
    assert seat["observations"] >= 1000
    # Provenance: which reference PDFs the numbers came from, and how many
    # glyphs each code point was seen at.  A table that cannot say where a
    # number came from is not a measurement.
    assert seat["forms"], "no source form recorded"
    for entry in seat["widths"].values():
        assert entry["observations"] >= 1
        assert entry["forms"]
    assert set(seat["pdf_fonts"]) == {STANDIN_FACE}


def test_no_entry_carries_anything_but_a_width(payload):
    """Widths only -- no outline, no glyph program, no font bytes."""
    allowed = {"char", "advance_em", "observations", "spread_em", "forms",
               "pdf_fonts", "class", "slot"}
    for seat in (payload.get("standin_faces") or {}).values():
        for entry in seat["widths"].values():
            assert set(entry) <= allowed, f"unexpected keys: {set(entry)}"


# -- the reader -----------------------------------------------------------

def test_the_renderer_reads_the_section_and_shrugs_at_an_unknown_face():
    table = own_render.HftWidthTable(ROOT)
    assert table.standin, "the renderer read no stand-in section"
    assert table.standin_full_width_em(STANDIN_FACE) == pytest.approx(
        DRAWN_FULL_WIDTH_EM, abs=0.002)
    assert table.standin_full_width_em("no such face") is None
    assert table.standin_advance_em("no such face", "가") is None


def test_the_rule_is_gated_on_the_resolver_not_on_the_declaration():
    """An INSTALLED face is never corrected, whatever the table carries.

    ``_standin_declared_face`` is the whole gate, and it answers ``None`` for
    a run the resolver satisfied with the declared face itself.  Pinned over
    every ``(cid, slot)`` the form actually resolved, rather than on a stub,
    because the point of the gate is what it does to real runs -- and this
    form carries both kinds: 휴먼명조 substituted, HCI Poppy installed.
    """
    stem, _address = PINNED
    renderer = own_render.OwnRenderer(_form(stem), repo_root=ROOT)
    renderer.render()
    seen = {"installed": 0, "substituted": 0}
    for (cid, slot, bold), (_chosen, record) in renderer._face_cache.items():
        answer = renderer._standin_declared_face(cid, slot)
        if record["source"] == "installed":
            seen["installed"] += 1
            assert answer is None, (
                f"{record['declared']} is installed and was still offered "
                f"to the stand-in rule")
        elif record["declared"]:
            seen["substituted"] += 1
            assert answer == record["declared"]
    assert seen["installed"], "this form resolved nothing to an installed face"
    assert seen["substituted"], "this form substituted nothing"


# -- the line it was built to close ---------------------------------------

def _breaks_match(stem, address, standin):
    """Do our computed breaks equal the cache's, under ``syllable``?"""
    base = own_render.OwnRenderer._standin_advance_hwp
    if not standin:
        own_render.OwnRenderer._standin_advance_hwp = (
            lambda self, *a, **k: None)
    try:
        with probe.installed("syllable"):
            for row in advance_probe.break_scoreboard(
                    _form(stem), dpi=144, repo_root=ROOT):
                if row["address"] == address:
                    return bool(row["match"])
    finally:
        own_render.OwnRenderer._standin_advance_hwp = base
    raise AssertionError(f"{stem} ¶{address} is not a scorable paragraph")


def test_the_pinned_line_turns_on_the_table():
    """#316's ¶118, the narrowest of the eleven, both ways.

    Without the table our advance for the line is 135.4 HWPUNIT short of its
    box, so the breaker takes one more syllable than Hancom did; with it the
    same span is over the box and the break falls where the cache put it.
    """
    stem, address = PINNED
    assert _breaks_match(stem, address, standin=False) is False
    assert _breaks_match(stem, address, standin=True) is True
