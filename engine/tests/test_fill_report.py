"""fill_report.build_verdict 회귀 테스트 — gap_skip_pages 면제 버그(phantom remove_gap).

layout_qa.analyze를 모의(monkeypatch)해 PDF 없이 순수 verdict 로직만 검증한다.
`python -m pytest tests/ -q`.
"""
import os
import sys

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import fill_report  # noqa: E402
import layout_qa  # noqa: E402

FILL = {
    "min_figures": 0,
    "target_pages": [1, 999],
    "bottom_white_max": 25.0,
    "max_gap_lines": 3.0,
}


def _fake_qa(pages, checks_pass=True):
    return {
        "ok": True, "file": "fake.pdf", "page_count": len(pages),
        "thresholds": {}, "flagged_pages": [], "pass": checks_pass,
        "pages": pages, "checks": {k: [] for k in
                                    ("line_spacing_uniformity", "figure_placement",
                                     "tables", "body_markers", "equations")},
    }


def test_gap_skip_pages_excluded_from_worst_gap(monkeypatch):
    # page 1 has a huge gap (exempted), page 2 is clean.
    pages = [
        {"page": 1, "bottom_white_pct": 5.0, "max_gap_lines": 12.0},
        {"page": 2, "bottom_white_pct": 5.0, "max_gap_lines": 1.0},
    ]

    def fake_analyze(pdf_path, bottom_thr, gap_thr, guide_strings=None,
                      spacing_skip_pages=None, gap_skip_pages=None, expect_eq=0,
                      bottom_skip_pages=None):
        # emulate layout_qa's own exemption: page in gap_skip_pages doesn't flag,
        # but max_gap_lines value is still reported (measured, not hidden).
        return _fake_qa(pages, checks_pass=True)

    monkeypatch.setattr(layout_qa, "analyze", fake_analyze)

    verdict = fill_report.build_verdict("fake.pdf", FILL, fig_count_override=0,
                                         gap_skip_pages={1})
    assert verdict["gaps_worst"]["page"] == 2
    assert verdict["gaps_worst"]["lines"] == 1.0
    assert verdict["converged"] is True
    assert not any(n["kind"] == "remove_gap" for n in verdict["needs"])


def test_without_gap_skip_pages_flags_the_gap(monkeypatch):
    pages = [
        {"page": 1, "bottom_white_pct": 5.0, "max_gap_lines": 12.0},
        {"page": 2, "bottom_white_pct": 5.0, "max_gap_lines": 1.0},
    ]

    def fake_analyze(pdf_path, bottom_thr, gap_thr, guide_strings=None,
                      spacing_skip_pages=None, gap_skip_pages=None, expect_eq=0,
                      bottom_skip_pages=None):
        return _fake_qa(pages, checks_pass=False)

    monkeypatch.setattr(layout_qa, "analyze", fake_analyze)

    verdict = fill_report.build_verdict("fake.pdf", FILL, fig_count_override=0,
                                         gap_skip_pages=None)
    assert verdict["gaps_worst"]["page"] == 1
    assert verdict["gaps_worst"]["lines"] == 12.0
    assert any(n["kind"] == "remove_gap" for n in verdict["needs"])


def test_gap_skip_pages_does_not_affect_other_skipped_pages_measurement(monkeypatch):
    # multiple skipped pages; worst among the non-skipped ones should win.
    pages = [
        {"page": 1, "bottom_white_pct": 5.0, "max_gap_lines": 20.0},
        {"page": 2, "bottom_white_pct": 5.0, "max_gap_lines": 5.0},
        {"page": 3, "bottom_white_pct": 5.0, "max_gap_lines": 2.0},
    ]

    def fake_analyze(pdf_path, bottom_thr, gap_thr, guide_strings=None,
                      spacing_skip_pages=None, gap_skip_pages=None, expect_eq=0,
                      bottom_skip_pages=None):
        return _fake_qa(pages, checks_pass=True)

    monkeypatch.setattr(layout_qa, "analyze", fake_analyze)

    verdict = fill_report.build_verdict("fake.pdf", FILL, fig_count_override=0,
                                         gap_skip_pages={1, 2})
    assert verdict["gaps_worst"]["page"] == 3
    assert verdict["gaps_worst"]["lines"] == 2.0
