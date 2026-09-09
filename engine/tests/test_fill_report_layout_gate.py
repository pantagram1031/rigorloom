# -*- coding: utf-8 -*-
"""A clean verdict (dict of empty anomaly lists) must not read as a hard layout failure."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for d in (os.path.join(ROOT, "engine", "scripts"), os.path.join(ROOT, "pipeline", "scripts")):
    if d not in sys.path:
        sys.path.insert(0, d)

import fill_report  # noqa: E402
import render_quality  # noqa: E402


def _passed_quality():
    return {"schema": render_quality.QUALITY_SCHEMA, "state": "passed", "reason_code": "passed"}


def test_clean_checks_dict_keeps_the_native_grade(monkeypatch, tmp_path):
    monkeypatch.setattr(render_quality, "inspect", lambda *_a, **_k: _passed_quality())
    verdict = {
        "converged": True,
        "checks": {"line_spacing_uniformity": [], "figure_placement": [], "tables": [],
                   "body_markers": [], "equations": []},
        "style_anomalies": [],
        "proof_grade": "hancom",
    }
    fill_report._apply_render_quality(verdict, tmp_path / "a.hwpx", tmp_path / "a.pdf")
    assert verdict["render_quality"]["state"] == "passed"
    assert verdict["proof_grade"] == "hancom"


def test_a_real_anomaly_still_fails_the_layout_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(render_quality, "inspect", lambda *_a, **_k: _passed_quality())
    verdict = {
        "converged": True,
        "checks": {"line_spacing_uniformity": [{"page": 1, "gap_pt": 32.2}], "figure_placement": []},
        "style_anomalies": [],
        "proof_grade": "hancom",
    }
    fill_report._apply_render_quality(verdict, tmp_path / "a.hwpx", tmp_path / "a.pdf")
    assert verdict["render_quality"]["reason_code"] == "layout_hard_failed"
    assert verdict["proof_grade"] == "none"
