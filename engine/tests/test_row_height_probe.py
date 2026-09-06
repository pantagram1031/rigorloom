# -*- coding: utf-8 -*-
"""row_height_probe.py --remainder — the class-B row-height remainder.

What is pinned here is the SHAPE of the answer and the arithmetic of the one
clip candidate the grouping suggested, never a corpus count: the corpus is
the training set and a count would pin it.  The candidate is scored by the
probe and deliberately NOT wired into ``own_render.py``; these tests exist so
that the next reading of it starts from the same numbers.
"""
from __future__ import annotations

import os
import sys
from xml.etree import ElementTree

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import own_render  # noqa: E402
import row_height_probe  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus", "forms", "converted")


def _form(stem):
    path = os.path.join(CORPUS, stem + ".hwpx")
    if not os.path.isfile(path):
        pytest.skip("corpus fixture %s.hwpx not present" % stem)
    return path


def test_the_overflowing_row_pays_reproduces_a_real_corpus_row_pair():
    """``saeopja`` table 4, the smallest of the three carriers, in numbers.

    Two rows that both declare 2430 in a box that declares 4860.  Under the
    computed policy one cell in row 0 breaks into a third line, so the row
    asks 3562 and the table asks 5992 — 1132 over its box.  #276 takes that
    off the LAST row (row 1 falls to 1298 and every cell in it moves up);
    charging it to the row that overflowed its own declaration puts both rows
    back on the boundary the cache read draws.
    """
    natural = [3562, 2430]
    floors = [2430, 2430]
    assert own_render.clip_tracks(natural, 4860) == [3562, 1298]
    assert row_height_probe.clip_overflow_rows(natural, 4860, floors) == \
        [2430, 2430]


def test_the_candidate_falls_through_to_276_when_no_row_overflowed():
    """The counter-case: a file whose ROW declarations overflow its own box.

    ``kstartup`` table 5's shape — every row asks exactly the height it
    declares, and their sum is 78 past the table's ``hp:sz@height``.  Nothing
    overflowed its declaration, so there is nothing for the candidate to
    charge and it has to leave #276's measured answer (the last row pays,
    which is what Hancom's own export draws there) alone.
    """
    natural = [3682, 19626, 19626, 19626]
    floors = list(natural)
    assert row_height_probe.clip_overflow_rows(natural, 62482, floors) == \
        own_render.clip_tracks(natural, 62482)


def test_the_candidate_never_leaves_a_negative_row_or_misses_the_box():
    """A row the excess would drive negative carries into the row above it."""
    out = row_height_probe.clip_overflow_rows([100, 5000], 200, [0, 0])
    assert sum(out) == 200
    assert min(out) >= 0


def test_a_row_floor_is_the_largest_declaration_in_the_row():
    """``declared_row_heights`` drops a row whose cells disagree; a FLOOR
    cannot be dropped, so the disagreement resolves to the largest claim."""
    tbl = ElementTree.Element("tbl", {"rowCnt": "2", "colCnt": "2"})
    record = {
        "tbl": tbl,
        "cells": [
            {"row": 0, "col": 0, "rspan": 1, "declared": 2175},
            {"row": 0, "col": 1, "rspan": 1, "declared": 2458},
            {"row": 1, "col": 0, "rspan": 2, "declared": 9999},
        ],
    }
    floors = row_height_probe._row_floors(record)
    assert floors[0] == 2458
    assert floors[1] == 0


@pytest.fixture(scope="module")
def saeopja_remainder():
    """One form, read once: the view costs four renders of it."""
    return row_height_probe.remainder_report(
        _form("saeopja-deungnok-sinchengseo"), repo_root=ROOT)


def test_the_remainder_view_accounts_for_every_paragraph_it_claims(
        saeopja_remainder):
    """Shape, on one real form: every ``table_row_heights`` class-B paragraph
    gets a named mechanism, and the row deltas above it are the step
    ``class_b_probe`` measured — that identity is the view's own oracle."""
    report = saeopja_remainder
    assert report["table_row_heights_paragraphs"] >= 1
    assert report["exact"] == report["table_row_heights_paragraphs"]
    for entry in report["paragraphs"]:
        assert entry["mechanism"]
        assert entry["predicted_d_row_top_hwp"] == \
            entry["measured_d_row_top_hwp"]
    assert sum(group["paragraphs"] for group in report["groups"]) == \
        report["table_row_heights_paragraphs"]


def test_the_declared_ceiling_candidate_is_refuted_on_the_cache_read(
        saeopja_remainder):
    """A row's declared ``cellSz@height`` is #273's floor and not a ceiling:
    the cache read itself draws rows taller than the height their cells
    declare, so clamping to it would clip content Hancom's own save did not."""
    ceiling = saeopja_remainder["declared_ceiling"]
    assert ceiling["rows_with_a_declared_height"] <= ceiling["rows"]
    assert ceiling["cache_row_over_declared"] > 0
