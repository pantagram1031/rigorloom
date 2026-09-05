# -*- coding: utf-8 -*-
"""table_split_probe.py — where Hancom splits a table, and where we do.

The probe reads two independent witnesses out of the same reference PDF (the
unique text of each cell paragraph, and the strokes the page draws) and puts
them beside what this renderer drew under both layout policies.  What is
pinned here is the SHAPE of that answer and the two readings agreeing, never
a count: the corpus is the training set and a count would pin it.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import table_split_probe  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus", "forms", "converted")
RENDERS = os.path.join(ROOT, "tests", "corpus", "forms", "render")


def _need(path):
    if not os.path.isfile(path):
        pytest.skip("corpus fixture %s not present" % os.path.basename(path))
    return path


def _pair(stem):
    return (_need(os.path.join(CORPUS, stem + ".hwpx")),
            _need(os.path.join(RENDERS, stem + ".pdf")))


def test_regions_group_rules_by_their_x_span_not_by_touching():
    """A table whose middle rows declare borderFill NONE draws nothing there,
    so a connected-component grouping falls into pieces on exactly the tables
    this probe has to read.  Grouping by x-span does not."""
    horizontal = [(10.0, 50.0, 500.0), (700.0, 50.0, 500.0),
                  (300.0, 120.0, 480.0)]
    regions = table_split_probe._page_regions(horizontal, [], 300.0)
    spans = sorted(round(r["x1"] - r["x0"]) for r in regions)
    assert spans == [360, 450]
    outer = max(regions, key=lambda r: r["x1"] - r["x0"])
    assert outer["top"] == 10.0 and outer["bottom"] == 700.0


def test_a_narrow_rule_is_not_a_table_region():
    regions = table_split_probe._page_regions(
        [(10.0, 50.0, 60.0)], [], 300.0)
    assert regions == []


def test_a_one_page_form_reports_no_split_and_our_pages_match_the_pdf():
    hwpx, pdf = _pair("gianmun-byeolji-1ho")
    report = table_split_probe.probe_form(hwpx, pdf, dpi=96,
                                          repo_root=ROOT)
    assert report["pdf_split_tables"] == []
    for policy in ("cache", "computed"):
        assert report["ours"][policy]["split_tables"] == []
        assert report["ours"][policy]["pages"] == report["pdf_pages"]


def test_the_probe_reads_hp_tr_header_and_finds_none_flagged():
    """``repeatHeader`` names rows the file has to flag, and this corpus
    flags none — which is why the one split table repeats nothing."""
    hwpx, pdf = _pair("gianmun-byeolji-1ho")
    report = table_split_probe.probe_form(hwpx, pdf, dpi=96, repo_root=ROOT)
    assert report["rows_total"] > 0
    assert report["rows_flagged_header"] == 0
    assert report["tr_attributes"] == {}


def test_a_split_table_is_reported_from_the_text_and_from_the_rules():
    """kstartup's table 9 is the corpus' one cross-page table.

    Both readings have to say so: the text says which of its rows landed on
    which page, and the rules say where the continuation's own top edge is.
    The row at the boundary is DIVIDED — Hancom cut through the cell, which
    is what ``pageBreak="CELL"`` permits and what ``NONE`` forbids — and no
    row is repeated on the continuation page.
    """
    hwpx, pdf = _pair("kstartup-jiwon-sincheongseo-saeopgyehoekseo")
    report = table_split_probe.probe_form(hwpx, pdf, dpi=96, repo_root=ROOT,
                                          policies=("cache",))
    split = [t for t in report["pdf"] if t["split"]]
    assert len(split) == 1
    entry = split[0]
    assert entry["page_break"] == "CELL"
    assert entry["repeat_header"] == "1"
    assert entry["treat_as_char"] == "0"
    assert entry["boundary_row_divided"] is True
    assert entry["repeated_header"] is False
    assert entry["repeated_header_height_hwp"] == 0
    assert entry["pages"][1] == entry["pages"][0] + 1
    # The continuation is seated at the top of the body box, not at the seat
    # the first fragment had on its own page: within one line of body top.
    assert 0 <= entry["continuation_top_below_body_top_hwp"] < 1000
    ours = report["ours"]["cache"]
    assert ours["split_tables"] == [entry["table"]]
    mine = next(t for t in ours["tables"] if t["table"] == entry["table"])
    assert mine["pages"] == entry["pages"]
    assert mine["repeated_header"] is False
