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
