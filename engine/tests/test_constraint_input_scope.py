# -*- coding: utf-8 -*-
"""A budget the form states in a plain bullet must reach the parser (T129).

`_parse_constraints` was handed `guide_text` only. The nrf 결과보고서 양식 states
its own requirement as

    ◦ 결과보고서의 전체 분량은 15쪽 이상, 글자크기는 12포인트 권장

and that line is a plain ◦ bullet — not coloured, not an instruction keyword,
not a ※/☞ note prefix — so the classifier files it under `anchors` and never
under `guide_text`. The regexes were already correct: run against that sentence
they yield 15 and 12. The profile published `constraints` all-null anyway.

Downstream that is not a neutral omission. It is the difference between a
checked length budget and `length_budget_unverified: not_declared`, which is
what a sibling run actually received — a gate reporting "no budget declared" on
a form that declares one, with nothing telling the operator something was
missed.

Found by a clean-room agent profiling that form, which traced it to the call
site itself rather than reporting the symptom.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import form_inspect  # noqa: E402

CORPUS = os.path.join(os.path.dirname(ROOT), "tests", "corpus", "forms",
                      "converted")
NRF = os.path.join(CORPUS, "nrf-gyeolgwa-bogoseo-yangsik.hwpx")

needs_nrf = pytest.mark.skipif(not os.path.exists(NRF), reason="corpus absent")
needs_corpus = pytest.mark.skipif(not os.path.isdir(CORPUS),
                                  reason="corpus absent")

BUDGET_SENTENCE = "15쪽 이상"


def _profile(path):
    out = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "form_inspect.py"),
         path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def _corpus_forms():
    return sorted(os.path.join(CORPUS, n) for n in os.listdir(CORPUS)
                  if n.endswith(".hwpx"))


# ---------------------------------------------------------------------------
# the reproduction, and the mechanism behind it
# ---------------------------------------------------------------------------

@needs_nrf
def test_the_form_own_stated_budget_reaches_the_profile():
    constraints = _profile(NRF)["constraints"]
    assert constraints["min_pages"] == 15, constraints
    assert constraints["base_pt"] == 12, constraints


@needs_nrf
def test_the_carrying_sentence_is_an_anchor_not_guide_text():
    """Why widening the input was the fix rather than a regex change.

    If a later change reclassifies this sentence into guide_text the profile
    would still be correct, but this test would fail and say so — the mechanism
    recorded in the trouble row would have changed and the note should follow.
    """
    profile = _profile(NRF)
    anchors = [a for a in profile["anchors"]
               if BUDGET_SENTENCE in (a if isinstance(a, str) else "")]
    guides = [g for g in profile["guide_text"]
              if BUDGET_SENTENCE in (g.get("text") or "")]
    assert len(anchors) == 1, anchors
    assert not guides, (
        "the sentence is now guide-classified, so guide_text alone would have "
        "sufficed; re-read the trouble row before trusting it")


# ---------------------------------------------------------------------------
# the still-catches: a wider input must not invent budgets
# ---------------------------------------------------------------------------

@needs_corpus
def test_no_other_corpus_form_gains_a_constraint():
    """Measured before the change: current behaviour detected a constraint on
    ZERO of the ten corpus forms, and widening the input changes exactly one.
    The other nine are the false-positive fixtures.

    Globbed rather than listed by name on purpose — a hardcoded roster is the
    defect class this repo has fixed four times (#23, #26, #27, #59). If a form
    is added that legitimately declares a budget, this fails and the addition
    has to be acknowledged rather than absorbed silently.
    """
    gained = {}
    examined = 0
    for path in _corpus_forms():
        if os.path.basename(path) == os.path.basename(NRF):
            continue
        examined += 1
        constraints = _profile(path)["constraints"]
        present = {k: v for k, v in constraints.items() if v is not None}
        if present:
            gained[os.path.basename(path)] = present
    # Non-vacuity: an empty sweep would satisfy every assertion below.
    assert examined >= 8, (
        "only %d corpus form(s) were examined; this guard proves nothing at "
        "that size" % examined)
    assert not gained, (
        "widening the constraint parser's input invented a budget on a form "
        "that declares none, or a new corpus form declares one and this guard "
        "needs updating with the reason: %s" % gained)


# ---------------------------------------------------------------------------
# the parser itself, and a limit it cannot see
# ---------------------------------------------------------------------------

def test_the_parser_reads_both_halves_of_one_sentence():
    out = form_inspect._parse_constraints(
        ["◦ 결과보고서의 전체 분량은 15쪽 이상, 글자크기는 12포인트 권장"])
    assert out["min_pages"] == 15
    assert out["base_pt"] == 12
    assert out["max_pages"] is None
    assert out["line_spacing_pct"] is None


def test_a_form_that_declares_nothing_stays_all_null():
    out = form_inspect._parse_constraints(
        ["신청인 성명", "주소", "※ [  ]에는 해당하는 곳에 √표를 합니다."])
    assert out == {"base_pt": None, "line_spacing_pct": None,
                   "max_pages": None, "min_pages": None}


def test_a_bare_point_number_needs_a_font_keyword():
    """The keyword gate is what stops "20포인트" in unrelated prose becoming a
    font budget. Added because a mutation removing the gate failed nothing:
    no corpus form carries a point number outside a font sentence, so the
    corpus cannot exercise it and only a unit case can.
    """
    assert form_inspect.PT_KEYWORDS == ("글자", "글씨", "폰트", "본문"), (
        "the keyword set moved; the cases below were chosen against it")
    gated = form_inspect._parse_constraints(["가산점은 20포인트까지 부여합니다."])
    assert gated["base_pt"] is None, gated
    allowed = form_inspect._parse_constraints(["본문 글자크기는 11포인트로 한다."])
    assert allowed["base_pt"] == 11, allowed


def test_line_spacing_needs_both_keywords():
    """Same shape for the spacing gate: a bare percentage is not a budget."""
    assert form_inspect.SPACING_KEYWORDS == ("줄", "간격")
    assert form_inspect._parse_constraints(
        ["지원 비율은 70%입니다."])["line_spacing_pct"] is None
    assert form_inspect._parse_constraints(
        ["줄 간격은 160%로 한다."])["line_spacing_pct"] == 160


def test_a_page_count_about_another_document_is_indistinguishable():
    """A STATED LIMIT, pinned so it is not mistaken for correctness.

    The shipped regex is ``(\\d+)\\s*(?:쪽|페이지|장)\\s*이상`` and it cannot tell
    a requirement about THIS document from a reference to another one. No form
    in the corpus contains such a sentence — that is why widening the input
    produced zero false positives there — but the day one does, the fix is a
    scope rule and not a wider input. This test records today's behaviour so a
    future scope rule has something to change.
    """
    out = form_inspect._parse_constraints(
        ["「별지 제7호서식」의 첨부 서류는 3쪽 이상입니다."])
    assert out["min_pages"] == 3, (
        "behaviour changed: if a scope rule now rejects this, update the "
        "trouble row — the limit it records has been closed")
