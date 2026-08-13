# -*- coding: utf-8 -*-
"""A paragraph seat gets the same colour verdict a table cell does (T128).

T127 taught the T30 pre-flight to stop calling colour clean when it had never
looked. It reaches only table cells: ``_fill_preflight`` has exactly one call
site, inside ``_table_map``, guarded by ``classification == "fill_target"``.

A document whose seats are top-level paragraphs therefore got nothing. The
standard labour contract is exactly that: it profiles as ``fill_target_count:
0``, so the pre-flight never engages, and the two writers used for paragraph
seats — ``preedit set-runs`` and ``preedit replace --at-para`` — run no charPr
check of their own. ``set_runs`` deliberately never touches the run opener, so
whatever charPr the seat carries is what the value inherits, unexamined.

Found by a clean-room agent filling that contract. Its fill was fine only by
luck of the form: it checked the ten charPr ids it wrote into by calling
``_charpr_defs`` itself, because no shipped surface reports colour for a
paragraph seat.

The verdict is attached to the ``--full-text`` run record, which is where the
operator already looks to find a paragraph seat, and it uses the same predicate
as the table pre-flight and the guide-text classifier.
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
JUMIN = os.path.join(CORPUS, "converted", "jumin-deungchobon-sinchengseo.hwpx")
CONTRACT = os.path.join(CORPUS, "converted",
                        "moel-pyojun-geunrogyeyakseo-2025.hwpx")

needs_jumin = pytest.mark.skipif(not os.path.exists(JUMIN),
                                 reason="corpus absent")
needs_contract = pytest.mark.skipif(not os.path.exists(CONTRACT),
                                    reason="corpus absent")


def _profile(path, paras=()):
    argv = [sys.executable, os.path.join(ROOT, "scripts", "form_inspect.py"),
            path]
    for n in paras:
        argv += ["--full-text", "PARA:%d" % n]
    out = subprocess.run(argv, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def _run_records(profile):
    """Every ``--full-text`` run record in the payload, wherever it sits."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for record in node.get("runs") or []:
                found.append(record)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(profile)
    return found


# ---------------------------------------------------------------------------
# the gap, on the document that exposed it
# ---------------------------------------------------------------------------

@needs_contract
def test_a_paragraph_seat_form_gets_a_verdict_the_table_preflight_cannot_give():
    profile = _profile(CONTRACT, paras=(2, 3, 4, 5, 10, 20, 63, 67, 131, 156))
    # The premise: the table pre-flight structurally cannot engage here.
    assert profile["fill_target_count"] == 0, (
        "this form stopped being the reproduction — it now has table fill "
        "targets, so the pre-flight would engage and the gap would be hidden")
    records = _run_records(profile)
    assert records, "no run records came back; --full-text stopped reporting"
    judged = [r for r in records if "color_anomaly" in r]
    assert len(judged) == len(records), (
        "%d of %d paragraph run records got no colour verdict"
        % (len(records) - len(judged), len(records)))


@needs_jumin
def test_the_verdict_fires_on_a_coloured_paragraph_run():
    """Non-vacuity: a suite that only ever sees False proves nothing."""
    profile = _profile(JUMIN, paras=range(0, 60))
    records = _run_records(profile)
    flagged = [r for r in records if r.get("color_anomaly") is True]
    clean = [r for r in records if r.get("color_anomaly") is False]
    assert flagged, (
        "no paragraph run on this form reports a coloured charPr; the field "
        "can no longer be shown to fire")
    assert clean, "every run flagged — the predicate has stopped discriminating"
    assert all(r.get("color_value") for r in flagged), (
        "a flagged run must carry the colour as evidence, not just a boolean")


# ---------------------------------------------------------------------------
# one vocabulary, three consumers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("colour,anomaly", [
    ("#000000", False),
    ("AUTO", False),
    (None, False),
    ("#0000FF", True),
    ("#0C0CFF", True),
    ("#FF0000", True),
])
def test_run_record_verdict_matches_the_shared_predicate(colour, anomaly):
    """The table pre-flight, the guide-text classifier and this record must
    agree. A private colour rule in any one of them is the defect."""
    run = {"index": 0, "text": "x", "charpr": "9"}
    out = form_inspect._run_record(run, {"9": {"color": colour}})
    assert out["color_anomaly"] is anomaly
    assert out["color_anomaly"] is (not form_inspect._is_black_or_auto(colour))
    assert ("color_value" in out) is anomaly


def test_an_unreadable_colour_is_omitted_rather_than_called_clean():
    """No key at all means "not judged" — never False."""
    run = {"index": 0, "text": "x", "charpr": "9"}
    for defs in ({}, None, {"other": {"color": "#000000"}}, {"9": {}}):
        out = form_inspect._run_record(run, defs)
        assert "color_anomaly" not in out, defs


def test_the_ruled_flag_still_works_alongside_the_colour_verdict():
    """T111's marker and T128's verdict are independent facts about one run."""
    run = {"index": 0, "text": "   ", "charpr": "9"}
    defs = {"9": {"color": "#0000FF", "underline": "BOTTOM"}}
    out = form_inspect._run_record(run, defs)
    assert out.get("ruled") is True
    assert out["color_anomaly"] is True
    assert out["color_value"] == "#0000FF"
