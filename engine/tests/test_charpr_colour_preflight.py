# -*- coding: utf-8 -*-
"""T30's pre-flight must not report "clean" about colour it never looked at (T127).

`script_anomaly` compares five charPr properties — supscript, subscript, ratio,
relSz, offset — and colour is none of them. `charpr_script` does not parse
colour at all. So a fill that inherits a guide-blue run passed the pre-flight as
`script_anomaly: false`, which the field docs define as "checked and clean", and
shipped text that reads as a form hint rather than an answer.

The file already stated the principle it was breaking:

    False(=검사했고 깨끗하다)와 구별된다 — 못 본 것을 깨끗하다고 보고하면
    사전 점검이 아니다.

Found by a clean-room agent filling the kstartup form: its own freshly typed
prose came back classified as `guide_text` with `reason: "colored"` while every
cell it touched reported `script_anomaly: false`. It then had to discover a
usable charPr by trial, because the pre-flight's own remedy is worse than
useless on this document — `charpr_suggested` is the body baseline, and this
form's body baseline is itself blue.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import form_inspect  # noqa: E402

CORPUS = os.path.join(os.path.dirname(ROOT), "tests", "corpus", "forms")
KSTARTUP = os.path.join(CORPUS, "converted",
                        "kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx")

needs_corpus = pytest.mark.skipif(not os.path.exists(KSTARTUP),
                                  reason="corpus absent")

# A cell body whose fill would inherit `cid` — the same shape
# preedit.fill_target_run_charpr reads, so the pre-flight and the writer cannot
# disagree about which run is meant.
BODY = ('<hp:p paraPrIDRef="0" styleIDRef="0">'
        '<hp:run charPrIDRef="{cid}"/>'
        '</hp:p>')


def _profile(path):
    out = subprocess.run(
        # No --out: the profile goes to stdout, and JSON is the only format.
        [sys.executable, os.path.join(ROOT, "scripts", "form_inspect.py"),
         path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def _fill_targets(profile):
    return [cell for table in profile["table_map"]
            for cell in (table.get("cells") or [])
            if cell.get("classification") == "fill_target"]


# ---------------------------------------------------------------------------
# the blind spot, on the document that exposed it
# ---------------------------------------------------------------------------

@needs_corpus
def test_the_blind_spot_is_reproduced_on_the_corpus_form():
    """Cells the old pre-flight called clean while their colour was not."""
    cells = _fill_targets(_profile(KSTARTUP))
    assert cells, "no fill targets — the fixture stopped exercising this"
    blind = [c for c in cells
             if c.get("color_anomaly") is True
             and c.get("script_anomaly") is False]
    assert blind, (
        "this form is the T127 reproduction: it must still carry fill targets "
        "whose inherited run is coloured while the five script properties "
        "match the baseline")
    assert all(c.get("color_value") for c in blind), (
        "a flagged cell must carry the colour as evidence, not just a boolean")


@needs_corpus
def test_colour_is_reported_for_every_fill_target_not_only_the_flagged_ones():
    """None would mean "not judged"; a judged form must say False out loud."""
    cells = _fill_targets(_profile(KSTARTUP))
    unjudged = [c for c in cells if c.get("color_anomaly") is None]
    assert not unjudged, (
        "%d fill target(s) got no colour verdict on a document whose charPr "
        "colours are all readable" % len(unjudged))


# ---------------------------------------------------------------------------
# the remedy — and why it is a separate field
# ---------------------------------------------------------------------------

@needs_corpus
def test_the_body_baseline_may_itself_be_coloured():
    """The reason `charpr_suggested` cannot be the colour remedy.

    `body_baseline_charpr` is the heaviest single body charPr, and on this form
    that is guide blue: the blue is concentrated in one charPr while black prose
    is spread across many ids, so blue wins the maximum even though black is
    most of the document. Pinned because it is the whole argument for a second
    field, and because the tie-break must stay identical to visual_verify's.
    """
    profile = _profile(KSTARTUP)
    baseline = profile["body_baseline_charpr"]
    charpr_colour = {
        cell["charpr"]: cell.get("color_value")
        for cell in _fill_targets(profile)
        if cell.get("color_anomaly") and cell.get("charpr")
    }
    assert baseline["id"], baseline
    assert charpr_colour, "expected at least one coloured inherited charPr"
    # The claim itself: a flagged seat inherits the BASELINE charPr, so the
    # baseline is the coloured run and recommending it would re-ship the bug.
    assert baseline["id"] in charpr_colour, (
        "no fill target inherits the baseline charPr, so this form no longer "
        "shows why the colour remedy cannot be `charpr_suggested`")
    assert not form_inspect._is_black_or_auto(charpr_colour[baseline["id"]]), (
        baseline["id"], charpr_colour[baseline["id"]])
    black = profile["body_black_charpr"]
    assert black["id"] != baseline["id"], (
        "if the black baseline and the plain baseline coincide, this form has "
        "stopped being the reproduction")


@needs_corpus
def test_body_black_charpr_is_black_and_keeps_the_nominal_height():
    """Swapping a 10pt blue seat for a 12pt black one fixes one bug and adds one."""
    profile = _profile(KSTARTUP)
    black = profile["body_black_charpr"]
    baseline = profile["body_baseline_charpr"]
    assert form_inspect._is_black_or_auto(black["color"]), black
    assert black["same_height_as_baseline"] is True, black
    assert black["height_pt"] == baseline["height_pt"], (black, baseline)


# ---------------------------------------------------------------------------
# the three-state contract, unit level
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("colour,anomaly", [
    ("#000000", False),
    ("AUTO", False),
    (None, False),          # no textColor: renders as body colour
    ("#0000FF", True),
    ("#0C0CFF", True),      # the Hancom guide blue
    ("#FF0000", True),
    ("#999999", True),
])
def test_colour_verdict_matches_the_guide_text_predicate(colour, anomaly):
    """One vocabulary: the pre-flight must use the predicate that decides
    whether the result gets classified as guide text. A second, private
    colour rule here would let the two halves of this tool disagree."""
    out = form_inspect._fill_preflight(
        BODY.format(cid="9"), {}, None, {"9": {"color": colour}})
    assert out["color_anomaly"] is anomaly
    assert out["color_anomaly"] is (not form_inspect._is_black_or_auto(colour))
    assert ("color_value" in out) is anomaly


def test_colour_is_judged_even_when_the_script_verdict_cannot_be():
    """Colour needs no baseline, so a form with no derivable one still gets a
    verdict. Before T127 the missing-baseline early return skipped everything."""
    out = form_inspect._fill_preflight(
        BODY.format(cid="9"), {}, None, {"9": {"color": "#0000FF"}})
    assert out["script_anomaly"] is None, "no baseline: must stay unjudged"
    assert out["color_anomaly"] is True


def test_an_unknown_charpr_is_unjudged_rather_than_clean():
    for defs in ({}, None, {"other": {"color": "#000000"}}):
        out = form_inspect._fill_preflight(BODY.format(cid="9"), {}, None, defs)
        assert out["color_anomaly"] is None, defs


def test_a_cell_with_no_run_is_unjudged():
    out = form_inspect._fill_preflight(
        "<hp:p paraPrIDRef=\"0\"></hp:p>", {}, None, {"9": {"color": "#F00"}})
    assert out["charpr"] is None
    assert out["color_anomaly"] is None
