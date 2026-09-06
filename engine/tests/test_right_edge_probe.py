# -*- coding: utf-8 -*-
"""``right_edge_probe`` — the bracket arithmetic and the two populations.

The probe's claim is that the cache is a TWO-SIDED oracle about the right
edge: a cached line is a span Hancom fitted, and the span reaching the last
non-space character before the next break opportunity is one it rejected.
Everything the notes conclude rests on those two populations being read
correctly, so what is pinned here is how they are built and how a candidate
is scored against them — never a corpus count, which is a measurement and
belongs in the notes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "scripts"))

import own_render  # noqa: E402
import right_edge_probe as probe  # noqa: E402


def _record(w_visible, avail, *, w_full=None, w_no_trail_punct=None,
            slack=0.0, rejected=None):
    """One synthetic measured line, in the shape ``bracket`` consumes."""
    return {
        "w_full": w_visible if w_full is None else w_full,
        "w_visible": w_visible,
        "w_no_trail_punct": (w_visible if w_no_trail_punct is None
                             else w_no_trail_punct),
        "avail": avail, "slack": slack, "rejected": rejected,
        "form": "synthetic", "stem": "synthetic", "address": 0, "line": 0,
        "in_cell": False, "align": "LEFT", "condense": 0, "chars": 1,
        "trailing": "other", "fill": w_visible / avail, "width_break": True,
        "horzsize": avail, "indent": 0, "last_line": False,
    }


def test_every_candidate_is_priced_and_carries_a_public_basis():
    assert set(probe.CANDIDATE_ORDER) == set(probe.CANDIDATES)
    for name in probe.CANDIDATE_ORDER:
        assert probe.CANDIDATE_BASIS[name].strip()


def test_the_strict_candidate_counts_the_trailing_space_and_space_does_not():
    rec = _record(1000.0, 1000.0, w_full=1200.0)
    assert probe._excess_strict(rec) == pytest.approx(200.0)
    assert probe._excess_space(rec) == pytest.approx(0.0)


def test_condense_forgives_exactly_what_the_spaces_can_give_up():
    rec = _record(1050.0, 1000.0, slack=60.0)
    assert probe._excess_space(rec) == pytest.approx(50.0)
    assert probe._excess_condense(rec) == pytest.approx(-10.0)


def test_the_pen_candidate_rounds_the_sum_onto_the_grid():
    step = probe.PEN_GRID_HWP
    # The box has to sit on the grid too, or the rounding of the sum shows up
    # as a constant offset rather than as the thing being measured.
    box = step * 83
    rec = _record(box + step / 3, box)
    assert probe._excess_pen(rec) == pytest.approx(0.0)
    rec = _record(box + step * 0.7, box)
    assert probe._excess_pen(rec) == pytest.approx(step)


def test_the_bracket_is_the_room_between_what_was_kept_and_what_was_rejected():
    kept_tight = _record(1000.0, 1000.0,
                         rejected={"w_full": 1500.0, "w_visible": 1500.0,
                                   "w_no_trail_punct": 1500.0,
                                   "avail": 1000.0, "slack": 0.0})
    kept_over = _record(1030.0, 1000.0,
                        rejected={"w_full": 1400.0, "w_visible": 1400.0,
                                  "w_no_trail_punct": 1400.0,
                                  "avail": 1000.0, "slack": 0.0})
    row = probe.bracket([kept_tight, kept_over], "space")
    assert row["kept_max"] == pytest.approx(30.0)
    assert row["rejected_min"] == pytest.approx(400.0)
    assert row["room"] == pytest.approx(370.0)
    assert row["consistent"] is True
    # At the strict threshold the over line is a line the candidate would
    # wrongly break, and no rejected span is wrongly kept.
    assert row["kept_wrong"] == 1
    assert row["rejected_wrong"] == 0


def test_a_candidate_the_cache_refutes_reports_no_room():
    kept = _record(1500.0, 1000.0,
                   rejected={"w_full": 1200.0, "w_visible": 1200.0,
                             "w_no_trail_punct": 1200.0,
                             "avail": 1000.0, "slack": 0.0})
    row = probe.bracket([kept], "space")
    assert row["consistent"] is False
    assert row["room"] < 0


def test_the_tolerance_candidate_reads_its_threshold_off_both_populations():
    """``tol12`` picks the k that gets the most lines right on BOTH sides.

    A threshold high enough to forgive every kept line is not the answer when
    it keeps spans Hancom rejected; the sweep is what says so, and the row
    has to agree with it.
    """
    records = [
        _record(1000.0 + probe.PEN_GRID_HWP * 2, 1000.0),
        _record(1000.0 + probe.PEN_GRID_HWP * 3, 1000.0,
                rejected={"w_full": 1000.0 + probe.PEN_GRID_HWP * 40,
                          "w_visible": 1000.0 + probe.PEN_GRID_HWP * 40,
                          "w_no_trail_punct": 1000.0 + probe.PEN_GRID_HWP * 40,
                          "avail": 1000.0, "slack": 0.0}),
    ]
    row = probe.bracket(records, "tol12")
    assert row["k"] == 3
    assert row["kept_wrong"] == 0
    assert row["rejected_wrong"] == 0
    sweep = {item["k"]: item for item in probe.tolerance_sweep(records)}
    assert sweep[3]["kept_wrong"] == 0
    assert sweep[2]["kept_wrong"] == 1
    assert sweep[40]["rejected_wrong"] == 1


def test_the_sweep_is_monotone_in_both_directions():
    records = [_record(1000.0 + probe.PEN_GRID_HWP * n, 1000.0)
               for n in range(6)]
    rows = probe.tolerance_sweep(records)
    kept = [row["kept_wrong"] for row in rows]
    rejected = [row["rejected_wrong"] for row in rows]
    assert kept == sorted(kept, reverse=True)
    assert rejected == sorted(rejected)


def test_an_installed_candidate_overrides_only_the_fit_seam():
    """``installed`` is how a rule is priced: one method, both renderers."""
    base_renderer = own_render.OwnRenderer
    base_recorder = probe.advance_probe.BreakRecordingRenderer
    with probe.installed("space", 0.0):
        assert own_render.OwnRenderer is not base_renderer
        assert issubclass(own_render.OwnRenderer, base_renderer)
        assert "_line_fits" in vars(own_render.OwnRenderer)
        # Nothing else is replaced -- an installed fit rule must not be able
        # to change what a character measures.
        assert set(vars(own_render.OwnRenderer)) - {
            "__module__", "__qualname__", "__doc__", "__dict__",
            "__weakref__"} == {"_line_fits"}
        assert issubclass(probe.advance_probe.BreakRecordingRenderer,
                          base_recorder)
    assert own_render.OwnRenderer is base_renderer
    assert probe.advance_probe.BreakRecordingRenderer is base_recorder


def test_the_installed_seam_matches_the_breakers_own_signature():
    """A rule the breaker cannot call is a rule that was never scored.

    #297 found ``advance_probe --fallback-rules`` silently broken because an
    override's signature had drifted from the seam's.  The same trap is here.
    """
    import inspect
    seam = inspect.signature(own_render.OwnRenderer._line_fits)
    override = inspect.signature(probe._fits_factory("space", 0.0))
    assert list(seam.parameters) == list(override.parameters)


def test_a_kept_line_and_its_rejected_span_share_one_column():
    """The two populations are only comparable against the same box."""
    forms = probe.layout_divergence.corpus_forms(ROOT)
    assert forms, "the corpus has to be present for this to mean anything"
    path, _reference = forms[0]
    records = probe.probe_form(path, repo_root=ROOT)
    assert records
    for rec in records:
        assert rec["avail"] == pytest.approx(
            max(1, rec["horzsize"] - rec["indent"]))
        if rec["rejected"] is not None:
            assert rec["rejected"]["avail"] == rec["avail"]
            # A rejected span is a strict extension of the line it follows.
            assert rec["rejected"]["chars"] > rec["chars"] - 1
            assert rec["rejected"]["w_full"] >= rec["w_visible"]


# -- the three over-broken cells (#312) ------------------------------------

def _cell(excess, *, offered, trailing_gap=0.0, punct=0, hft_delta=0.0,
          uncovered=0, w_fit=1000.0):
    """One synthetic cell whose first cached line is the deciding one."""
    return {
        "cache_breaks": [10], "our_breaks": [8], "deciding": 0,
        "lines": [{
            "line": 0, "start": 0, "visible": 10, "end": 10,
            "excess": excess, "break_offered": offered,
            "trailing_gap": trailing_gap, "punct_installed": punct,
            "w_fit": w_fit,
            "hft": {"measured": 0, "measured_delta": hft_delta,
                    "uncovered": uncovered},
        }],
    }


def test_the_named_cells_are_addressed_by_file_and_paragraph():
    """#311's three carriers, so a rerun cannot silently measure others."""
    assert probe.OVERBROKEN_CELLS
    total = sum(len(rows) for rows in probe.OVERBROKEN_CELLS.values())
    assert total == 3
    for stem, rows in probe.OVERBROKEN_CELLS.items():
        assert stem and not stem.endswith(".hwpx")
        for address, label in rows.items():
            assert isinstance(address, int)
            assert "row" in label and "cell" in label


def test_the_deciding_line_is_the_first_break_our_breaker_missed():
    """A greedy breaker's later lines are downstream of its first miss."""
    assert probe._deciding_line([10, 20, 30], [10, 20, 30]) is None
    assert probe._deciding_line([10, 20, 30], [10, 18, 26]) == 1
    # Fewer breaks than the cache: the first one we never made decides.
    assert probe._deciding_line([10, 20], [10]) == 1
    assert probe._deciding_line([10, 20], []) == 0


def test_a_cut_the_breaker_was_never_offered_has_no_width_story():
    """The whole point of the view: a missing opportunity is not a width.

    Our width for the cache's own line is UNDER the box, so no width term of
    any size reaches the cut, and the decomposition has to say so rather than
    price a residual that would be meaningless.
    """
    piece = probe.decompose(_cell(-784.3, offered=False))
    assert piece["width_kind"] == "not width-limited"
    assert piece["terms"]["residual"] is None
    assert "break_opportunities" in piece["verdict"]


def test_a_width_limited_line_prices_the_budget_and_names_the_residual():
    """Every named term comes out of the excess; what is left is declared."""
    budget = own_render.RIGHT_EDGE_TOLERANCE_HWP
    piece = probe.decompose(_cell(budget + 200.0, offered=True, punct=4,
                                  hft_delta=-50.0))
    assert piece["width_kind"] == "width-limited"
    assert piece["terms"]["budget"] == pytest.approx(budget)
    assert piece["terms"]["punct_installed"] == pytest.approx(
        4 * probe.INSTALLED_PUNCT_RESIDUAL_HWP)
    # residual = (excess - budget) - punctuation - the HFT table's own move
    assert piece["terms"]["residual"] == pytest.approx(
        200.0 - 4 * probe.INSTALLED_PUNCT_RESIDUAL_HWP + 50.0)


def test_the_installed_punctuation_residual_is_the_number_307_measured():
    """A term in a decomposition, per glyph, and nothing applies it."""
    assert probe.INSTALLED_PUNCT_RESIDUAL_HWP == pytest.approx(253.3 / 487)
    assert 0.5 < probe.INSTALLED_PUNCT_RESIDUAL_HWP < 0.55


def test_the_syllable_seam_forces_break_word_and_puts_the_function_back():
    """The seam still swaps and still restores -- and it is now a no-op.

    The shipped breaker BECAME the syllable unit (#316): breakNonLatinWord is
    read, reported and not obeyed, so a declared KEEP_WORD already yields
    every syllable boundary.  This candidate therefore buys nothing any more,
    which is exactly what ``syllable_break_probe --candidates`` measures
    (shipped and ``syllable`` score identically, 89/113 and 32/47).  What the
    test still has to hold is the SEAM: the context manager replaces the
    module-level function and puts the original back, because every other
    candidate in this probe is scored through the same mechanism.
    """
    base = own_render.break_opportunities
    text = "가나다 라마바"
    # 글자 단위, under the DECLARED 어절 단위 -- the override.
    assert base(text, "KEEP_WORD", "KEEP_WORD") == [1, 2, 4, 5, 6]
    with probe.syllable_opportunities():
        assert own_render.break_opportunities is not base
        # The candidate agrees with the shipped breaker by construction now.
        assert own_render.break_opportunities(
            text, "KEEP_WORD", "KEEP_WORD") == [1, 2, 4, 5, 6]
    assert own_render.break_opportunities is base


def test_the_budget_seam_puts_the_constant_back():
    base = own_render.RIGHT_EDGE_TOLERANCE_HWP
    with probe.tolerance_budget(probe.CELL_BUDGET_HWP):
        assert own_render.RIGHT_EDGE_TOLERANCE_HWP == probe.CELL_BUDGET_HWP
    assert own_render.RIGHT_EDGE_TOLERANCE_HWP == base


def test_every_cell_candidate_carries_a_basis_and_a_seam():
    assert set(probe.CELL_CANDIDATE_ORDER) == set(probe.CELL_CANDIDATES)
    assert probe.CELL_CANDIDATE_ORDER[0] == "shipped"
    renderer = own_render.OwnRenderer
    recorder = probe.advance_probe.BreakRecordingRenderer
    opportunities = own_render.break_opportunities
    budget = own_render.RIGHT_EDGE_TOLERANCE_HWP
    for name in probe.CELL_CANDIDATE_ORDER:
        basis, factory = probe.CELL_CANDIDATES[name]
        assert basis.strip()
        with factory():
            pass
        # Every seam has to put the tree back, or the candidate after it is
        # scored under the one before it.
        assert own_render.OwnRenderer is renderer
        assert probe.advance_probe.BreakRecordingRenderer is recorder
        assert own_render.break_opportunities is opportunities
        assert own_render.RIGHT_EDGE_TOLERANCE_HWP == budget


#: Of the three cells #311 named over-broken, which still are.  ``moel-2013``
#: ¶261 and ``saeopja`` ¶189 CLOSED on the syllable-unit slice, which is what
#: #316 predicted for them and the only prediction it made that could be
#: tested by shipping: both are paragraphs the cache cut INSIDE an 어절, so
#: the declared ``KEEP_WORD`` reading was what put the extra line there, not
#: any width term.  ``saeopja`` ¶393 is the remaining one, and #316 said why
#: no break rule reaches it: its excess is +238.0 HWPUNIT on a 2894 column,
#: it is width and not opportunity, and the budget already forgives 96.
STILL_OVERBROKEN = {("saeopja-deungnok-sinchengseo", 393)}


def test_the_named_cells_are_read_off_the_real_breaker():
    """The view's own oracle, re-measured after the syllable unit landed.

    No corpus COUNT is pinned here — that is a measurement and belongs in the
    notes — but that the three named paragraphs exist, that the view finds a
    column for each, and which of them our breaker still over-breaks is what
    every number in the notes rests on.  Two of the three closed; the one that
    did not is the width cell, and it is named rather than dropped from the
    view, because a cell that stops being over-broken is evidence and has to
    stay visible.
    """
    forms = {path.stem: path
             for path, _ in probe.layout_divergence.corpus_forms(ROOT)}
    targets = [(forms[stem], None) for stem in probe.OVERBROKEN_CELLS
               if stem in forms]
    if len(targets) != len(probe.OVERBROKEN_CELLS):
        pytest.skip("this checkout's corpus does not carry both forms")
    report = probe.cell_report(targets, ROOT, score=False)
    assert len(report["cells"]) == 3
    assert "candidates" not in report
    seen = set()
    for record in report["cells"]:
        key = (record["stem"], record["address"])
        assert record["column_hwp"] > 0
        if key in STILL_OVERBROKEN:
            seen.add(key)
            assert record["our_line_count"] == record["cached_lines"] + 1
            assert record["deciding"] is not None
            piece = record["decomposition"]
            assert piece["width_kind"] in ("width-limited",
                                           "not width-limited")
        else:
            # Closed by the syllable unit: our line count is the cache's, and
            # there is no deciding line left to decompose.
            assert record["our_line_count"] == record["cached_lines"], key
            assert record["deciding"] is None, key
        # The column the cell is laid out in IS the cached box on the cache's
        # own 4 HWPUNIT quantiser (#311), which is why the extra line cannot
        # be blamed on the track solver.
        assert abs(record["column_hwp"]
                   - record["cached_horzsize"][0]) <= 4
    assert seen == STILL_OVERBROKEN


def test_a_line_ending_on_a_control_cell_is_not_evidence_about_width():
    """An explicit line break is not a width decision, so it is left out.

    Without this the corpus' smallest "rejected" span sits tens of thousands
    of HWPUNIT UNDER its column, because a paragraph broken with shift-enter
    looks like a paragraph Hancom refused to fill.
    """
    forms = {path.stem: path
             for path, _ in probe.layout_divergence.corpus_forms(ROOT)}
    path = forms.get("moel-pyojun-geunrogyeyakseo-2025")
    if path is None:
        pytest.skip("moel-2025 is not in this checkout's corpus")
    records = probe.probe_form(path, repo_root=ROOT)
    forced = [rec for rec in records if not rec["width_break"]]
    assert forced, "moel-2025 carries explicit line breaks"
    assert all(rec["rejected"] is None for rec in forced)
    # And a rejected span, being one Hancom refused, must be at least as wide
    # as the line it extends -- which the forced ones were not.
    for rec in records:
        if rec["rejected"] is not None:
            assert (rec["rejected"]["w_full"]
                    >= rec["w_visible"] - probe.PEN_GRID_HWP)
