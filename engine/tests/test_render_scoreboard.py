# -*- coding: utf-8 -*-
"""render_scoreboard.py — the own renderer's measurement against Hancom.

What is pinned here, and why each one is worth a test:

  * SSIM behaves like SSIM.  An identical pair scores 1.0 and an inverted pair
    scores far below it — without that, every "improvement" this scoreboard
    reports could be noise;
  * IoU is IoU, including the disjoint case, because a pairing that scored 0
    boxes as 1.0 would flatter every render;
  * pairing is one-to-one and deterministic, since the scoreboard is committed
    and a re-run has to reproduce it byte for byte;
  * the reference-geometry-scale detector fires on the three corpus references
    that are NOT 1:1 renders and stays quiet on the ones that are.  This is the
    honesty gate of the whole slice: without it the scoreboard would score the
    reference facility's print reduction as a renderer defect;
  * a blocked verdict is ``pass: None``, never ``False`` — a form we cannot
    fairly measure must not read as a failing renderer.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.dirname(HERE)
ROOT = os.path.dirname(ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import own_render  # noqa: E402
import render_scoreboard  # noqa: E402

CORPUS = os.path.join(ROOT, "tests", "corpus", "forms", "converted")
RENDERS = os.path.join(ROOT, "tests", "corpus", "forms", "render")

pytestmark = pytest.mark.skipif(
    not own_render.pillow_available(),
    reason="Pillow is not installed; own_render cannot rasterise")


def _need(path):
    if not os.path.isfile(path):
        pytest.skip(f"corpus fixture missing: {path}")
    return path


def _need_fitz():
    try:
        import fitz  # noqa: F401
    except ImportError:
        pytest.skip("PyMuPDF is not installed")


def _form(slug):
    return (_need(os.path.join(CORPUS, f"{slug}.hwpx")),
            _need(os.path.join(RENDERS, f"{slug}.pdf")))


# ---------------------------------------------------------------- ssim

def test_ssim_of_a_page_against_itself_is_one():
    from PIL import Image, ImageDraw

    image = Image.new("L", (256, 256), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle([40, 40, 200, 120], fill=0)
    draw.line([10, 200, 240, 210], fill=64, width=3)
    value, blocks, inked, inked_blocks = render_scoreboard.ssim(image, image)
    assert blocks == 32 * 32
    assert value == pytest.approx(1.0, abs=1e-9)
    assert inked == pytest.approx(1.0, abs=1e-9)
    # Only the drawn region counts as inked, and it is a real subset.
    assert 0 < inked_blocks < blocks


def test_ssim_falls_hard_on_an_inverted_page():
    from PIL import Image, ImageDraw

    image = Image.new("L", (256, 256), 255)
    ImageDraw.Draw(image).rectangle([40, 40, 200, 120], fill=0)
    inverted = image.point(lambda v: 255 - v)
    value, _blocks, inked, _n = render_scoreboard.ssim(image, inverted)
    assert value < 0.1, value
    assert inked < 0.1, inked


def test_inked_ssim_ignores_the_paper_the_plain_mean_is_diluted_by():
    """The reason ssim_inked exists, made falsifiable.

    Two pages that agree everywhere except one small mark score close to 1.0
    on the plain mean — most of a government form is paper — while the inked
    mean, which only looks at blocks either page marked, sees the difference.
    """
    from PIL import Image, ImageDraw

    left = Image.new("L", (512, 512), 255)
    ImageDraw.Draw(left).rectangle([16, 16, 48, 48], fill=0)
    right = Image.new("L", (512, 512), 255)
    ImageDraw.Draw(right).rectangle([100, 100, 132, 132], fill=0)
    plain, _b, inked, _n = render_scoreboard.ssim(left, right)
    assert plain > 0.97, plain
    assert inked < plain / 2.0, (plain, inked)


def test_ssim_rejects_mismatched_sizes():
    from PIL import Image

    with pytest.raises(ValueError):
        render_scoreboard.ssim(Image.new("L", (16, 16)),
                               Image.new("L", (16, 32)))


# ---------------------------------------------------------------- geometry

def test_iou_is_one_for_identical_boxes_and_zero_when_disjoint():
    box = {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 4.0}
    assert render_scoreboard._iou(box, dict(box)) == pytest.approx(1.0)
    away = {"x0": 50.0, "y0": 50.0, "x1": 60.0, "y1": 54.0}
    assert render_scoreboard._iou(box, away) == 0.0
    half = {"x0": 5.0, "y0": 0.0, "x1": 15.0, "y1": 4.0}
    # intersection 5x4=20, union 40+40-20=60
    assert render_scoreboard._iou(box, half) == pytest.approx(20 / 60)


def test_pairing_is_one_to_one_and_prefers_the_nearer_box():
    reference = [
        {"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 4.0},
        {"x0": 0.0, "y0": 20.0, "x1": 10.0, "y1": 24.0},
    ]
    candidate = [
        {"x0": 0.0, "y0": 19.0, "x1": 10.0, "y1": 23.0},
        {"x0": 1.0, "y0": 0.0, "x1": 11.0, "y1": 4.0},
        {"x0": 0.0, "y0": 500.0, "x1": 10.0, "y1": 504.0},
    ]
    matched, unpaired_ref, unpaired_cand = render_scoreboard.pair_line_boxes(
        reference, candidate, cap=50.0)
    assert [(m["reference_index"], m["candidate_index"]) for m in matched] == [
        (0, 1), (1, 0)]
    assert unpaired_ref == 0
    assert unpaired_cand == 1


def test_pairing_respects_the_distance_cap():
    reference = [{"x0": 0.0, "y0": 0.0, "x1": 10.0, "y1": 4.0}]
    candidate = [{"x0": 0.0, "y0": 900.0, "x1": 10.0, "y1": 904.0}]
    matched, unpaired_ref, unpaired_cand = render_scoreboard.pair_line_boxes(
        reference, candidate, cap=100.0)
    assert matched == []
    assert (unpaired_ref, unpaired_cand) == (1, 1)


# -------------------------------------------------- reference honesty gate

@pytest.mark.parametrize("slug", [
    "gianmun-byeolji-1ho",
    "gianmun-byeolji-2ho",
    "nrf-gyeolgwa-bogoseo-yangsik",
])
def test_the_three_reduced_references_are_detected_and_refused(slug):
    """These three reference PDFs are ~1/sqrt(2) renders of their documents.

    Measured: their text is drawn at ~70.7% of the ``hh:charPr@height`` the
    file declares, while the documents' own embedded ``Preview/PrvImage.png``
    shows content filling the page.  Scoring against them would grade the
    reference facility, so the detector must fire.
    """
    _need_fitz()
    hwpx, pdf = _form(slug)
    record = render_scoreboard.reference_geometry_scale(hwpx, pdf)
    assert record["comparable"] is False, record
    assert record["scale"] == pytest.approx(0.7071, abs=0.02), record
    assert record["reason"]


@pytest.mark.parametrize("slug", [
    "admrul-gajokdolbom-hyuga-sinchengseo",
    "jeongbo-gonggae-cheongguseo",
    "jumin-deungchobon-sinchengseo",
    "kstartup-jiwon-sincheongseo-saeopgyehoekseo",
    "moel-pyojun-geunrogyeyakseo-2013",
    "moel-pyojun-geunrogyeyakseo-2025",
    "saeopja-deungnok-sinchengseo",
])
def test_the_one_to_one_references_are_accepted(slug):
    """Positive control: the detector must not refuse a usable reference."""
    _need_fitz()
    hwpx, pdf = _form(slug)
    record = render_scoreboard.reference_geometry_scale(hwpx, pdf)
    assert record["comparable"] is True, record
    assert record["scale"] == pytest.approx(1.0, abs=0.05), record


def test_a_blocked_verdict_is_not_a_failing_verdict():
    summary = {
        "page_count": {"exact": True, "reference": 1, "candidate": 1},
        "ssim_min": 0.99,
        "ssim_inked_min": 0.95,
        "text_line_iou_mean": 0.9,
        "text_line_pair_rate_mean": 1.0,
        "ink_delta_abs_max": 0.0,
    }
    blocked = render_scoreboard.evaluate(
        summary, render_scoreboard.PROPOSED_THRESHOLDS,
        {"comparable": False})
    assert blocked["pass"] is None
    assert blocked["blocked"] is True
    assert blocked["blocked_reason"] == "reference_geometry_scale"
    passing = render_scoreboard.evaluate(
        summary, render_scoreboard.PROPOSED_THRESHOLDS, {"comparable": True})
    assert passing["pass"] is True
    assert passing["blocked"] is False
    # A pass against unratified thresholds promotes nothing.
    assert passing["ratified"] is False


# ---------------------------------------------------------------- end to end

def test_scoring_a_comparable_form_reconciles_with_its_render(tmp_path):
    _need_fitz()
    hwpx, pdf = _form("jeongbo-gonggae-cheongguseo")
    report = render_scoreboard.score_form(hwpx, pdf, dpi=96, label="test")
    assert report["grade"] == "own-uncertified"
    assert report["reference_geometry_scale"]["comparable"] is True
    summary = report["summary"]
    assert summary["pages_scored"] == len(report["pages"])
    assert 0.0 <= summary["ssim_mean"] <= 1.0
    # Every scored page's line-box counts must reconcile with its pairing.
    for page in report["pages"]:
        iou = page["text_line_iou"]
        assert (iou["pairs"] + iou["unpaired_reference"]
                == iou["reference_lines"])
        assert (iou["pairs"] + iou["unpaired_candidate"]
                == iou["candidate_lines"])


def test_two_scorings_of_one_form_agree(tmp_path):
    """The scoreboard is committed; a re-run has to reproduce it."""
    _need_fitz()
    hwpx, pdf = _form("jeongbo-gonggae-cheongguseo")
    first = render_scoreboard.score_form(hwpx, pdf, dpi=96)
    second = render_scoreboard.score_form(hwpx, pdf, dpi=96)
    assert json.dumps(first, sort_keys=True) == json.dumps(second,
                                                           sort_keys=True)


def test_cli_writes_a_scoreboard(tmp_path):
    _need_fitz()
    hwpx, pdf = _form("jeongbo-gonggae-cheongguseo")
    proc = subprocess.run(
        [sys.executable,
         os.path.join(ENGINE, "scripts", "render_scoreboard.py"),
         hwpx, pdf, "--out", str(tmp_path), "--dpi", "96", "--label", "cli"],
        capture_output=True, text=True, encoding="utf-8", timeout=900)
    assert proc.returncode == 0, proc.stderr
    written = tmp_path / "jeongbo-gonggae-cheongguseo.cli.scoreboard.json"
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["grade"] == "own-uncertified"
    assert payload["thresholds"]["ratified"] is False


def test_the_proposed_floor_is_a_floor_the_current_state_clears(tmp_path):
    """A regression gate only works if today passes it.

    The thresholds are set just below the worst comparable-form measurement,
    so this is the test that would fail the day a renderer change makes any
    scored channel worse than 2026-09.  ``jeongbo`` is one of the two
    committed sample forms and the cheapest comparable one to score.
    """
    _need_fitz()
    hwpx, pdf = _form("jeongbo-gonggae-cheongguseo")
    report = render_scoreboard.score_form(hwpx, pdf, dpi=144)
    failed = [c for c in report["verdict"]["checks"] if not c["pass"]]
    assert report["verdict"]["blocked"] is False
    assert failed == [], failed
    assert report["verdict"]["pass"] is True
    # ... and passing it promotes nothing.
    assert report["grade"] == "own-uncertified"
    assert report["thresholds"]["kind"] == "regression_floor"
    assert report["fidelity_target"]["ssim_inked_min"] > \
        report["thresholds"]["ssim_inked_min"]


def test_cli_rejects_a_missing_reference(tmp_path):
    proc = subprocess.run(
        [sys.executable,
         os.path.join(ENGINE, "scripts", "render_scoreboard.py"),
         os.path.join(CORPUS, "gianmun-byeolji-1ho.hwpx"),
         str(tmp_path / "nope.pdf"), "--out", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert proc.returncode == 2
