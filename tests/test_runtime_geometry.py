# -*- coding: utf-8 -*-
"""document/pageGeometry: real positions, honest addresses, honest absences.

The geometry comes out of a PDF, so it is the renderer's own layout and never
ours. What this file pins hardest is the mapping's refusals: an ambiguous label
returns candidates rather than a pick, an unmatched line returns nothing rather
than a nearest guess, and a seat with no anchor in its row is absent rather
than boxed somewhere plausible.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from _runtime_client import CORPUS_FORM, RuntimeClient, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_codes  # noqa: E402
import rt_convert  # noqa: E402
import rt_geometry  # noqa: E402
import rt_render  # noqa: E402
from rt_core import RuntimeCore  # noqa: E402

HAVE_RASTERIZER = any(importlib.util.find_spec(name) is not None
                      for name in rt_render.RASTERIZER_MODULES)
needs_rasterizer = pytest.mark.skipif(
    not HAVE_RASTERIZER, reason="PyMuPDF is an optional dependency")

#: Strings the corpus form actually carries, so the fixture PDF matches a real
#: form scan rather than a story about one.
ANCHOR_UNIQUE = "제목"
ROW5_LABEL = "협조자"
#: A line the form scan has never heard of. Named once, so the fixture and
#: the assertion cannot drift apart -- they did, and the test passed the
#: count check while silently matching nothing.
STRANGER_LINE = "a line no form scan has ever seen"


def _hwpx(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    shutil.copyfile(CORPUS_FORM, target)
    return target


def _form_pdf(path, *, boxed=True):
    """A one-page PDF carrying the corpus form's own label strings.

    Not a picture of the form — a deterministic stand-in for what a Hancom
    render would contain, built with the same library that reads it back, so
    the mapping is exercised against text the form scan really knows.
    """
    module = rt_render.rasterizer_module()
    assert module is not None
    document = module.open()
    try:
        page = document.new_page()
        # "korea" is PyMuPDF's built-in CJK face; the default Helvetica
        # cannot encode Hangul and silently emits one dot per character,
        # which would make every match below a match against nothing.
        page.insert_text((72, 100), ANCHOR_UNIQUE, fontsize=11,
                         fontname="korea")
        page.insert_text((72, 140), ROW5_LABEL, fontsize=11,
                         fontname="korea")
        page.insert_text((72, 180), STRANGER_LINE, fontsize=11)
        if boxed:
            # the drawn rule of the seat immediately right of the row-5 label
            page.draw_rect(module.Rect(120, 128, 300, 148))
        document.save(str(path))
    finally:
        document.close()
    return path


def _attach_pdf(core, session_id, pdf):
    """Register a PDF the way renderPrepare would, without starting Hancom."""
    session = core.store.get(session_id)
    session.ensure_dirs()
    target = session.dir / "derived" / "source.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, target)
    from rt_session import sha256_file

    digest, size = sha256_file(target)
    rt_convert._write_meta(session, {
        "path": "derived/source.pdf", "sha256": digest, "bytes": size,
        "producedBy": "test fixture standing in for com_backend convert",
        "producedUtc": "2026-01-01T00:00:00Z",
        "sourceSha256": session.meta["sourceSha256"]})
    return target


@pytest.fixture()
def core(tmp_path):
    return RuntimeCore(tmp_path / "root")


# --- the normalizer is borrowed, not rebuilt --------------------------------

def test_the_normalizer_is_the_residue_gates_own_function():
    """One vocabulary. Identity, not equivalence — a copy would drift."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"
                          / "scripts"))
    import check_residue

    assert rt_geometry.normalizer() is check_residue.normalize_text


def test_no_second_whitespace_rule_lives_in_the_geometry_module():
    from pathlib import Path

    text = Path(rt_geometry.__file__).read_text(encoding="utf-8")
    body = text.split('"""', 2)[2]
    for smell in ("\\s+", ".split()", "re.sub"):
        assert smell not in body, f"a hand-rolled normalizer ({smell}) appeared"


# --- unavailable, honestly ---------------------------------------------------

def test_an_hwpx_with_no_pdf_has_no_geometry(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    result = core.document_page_geometry(session)
    assert result["available"] is False
    assert result["unavailable"]["reason"] == "needs_conversion"
    assert "renderPrepare" in result["unavailable"]["detail"] \
        or "cannot make one" in result["unavailable"]["detail"]
    assert "spans" not in result and "seats" not in result


def test_the_unavailable_reasons_are_rendered_shared_closed_set(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    result = core.document_page_geometry(session)
    assert (result["capability"]["unavailableReasons"]
            == list(rt_render.UNAVAILABLE_REASONS))
    assert result["unavailable"]["reason"] in rt_render.UNAVAILABLE_REASONS


@needs_rasterizer
def test_a_missing_rasterizer_is_reported_not_worked_around(core, tmp_path,
                                                            monkeypatch):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    _attach_pdf(core, session, _form_pdf(tmp_path / "f.pdf"))
    monkeypatch.setattr(rt_geometry, "rasterizer_module", lambda: None)
    result = core.document_page_geometry(session)
    assert result["available"] is False
    assert result["unavailable"]["reason"] == "rasterizer_missing"


@needs_rasterizer
def test_a_pdf_opened_directly_gives_geometry_but_no_mapping(core, tmp_path):
    """Positions are real; there is simply no form scan to map them onto."""
    pdf = _form_pdf(tmp_path / "standalone.pdf")
    session = core.open_path(str(pdf))["sessionId"]
    result = core.document_page_geometry(session)
    assert result["available"] is True
    assert result["spans"], "the text positions are still real"
    assert all(span["address"] is None for span in result["spans"])
    assert result["mapping"]["state"] == "unavailable"
    assert "not a form" in result["mapping"]["reason"]
    assert result["seats"] == []


# --- real extraction ---------------------------------------------------------

@needs_rasterizer
def test_spans_have_sane_normalized_rects(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    _attach_pdf(core, session, _form_pdf(tmp_path / "f.pdf"))
    result = core.document_page_geometry(session)

    assert result["available"] is True
    assert result["unit"] == "normalized" and result["origin"] == "top-left"
    assert result["spanUnit"] == "line"
    assert result["pageCount"] == 1
    assert result["pageSize"]["widthPt"] > 100
    texts = [span["text"] for span in result["spans"]]
    assert ANCHOR_UNIQUE in texts and ROW5_LABEL in texts

    for span in result["spans"]:
        x0, y0, x1, y1 = span["rect"]
        assert 0.0 <= x0 < x1 <= 1.0, span
        assert 0.0 <= y0 < y1 <= 1.0, span
    # the top label really is above the lower one, in top-left coordinates
    by_text = {span["text"]: span["rect"] for span in result["spans"]}
    assert by_text[ANCHOR_UNIQUE][1] < by_text[ROW5_LABEL][1]


@needs_rasterizer
def test_the_source_is_the_prepared_pdf_not_the_hwpx(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    _attach_pdf(core, session, _form_pdf(tmp_path / "f.pdf"))
    result = core.document_page_geometry(session)
    assert result["source"]["kind"] == "prepared_pdf"
    assert len(result["source"]["sha256"]) == 64


@needs_rasterizer
def test_a_page_past_the_end_is_refused(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    _attach_pdf(core, session, _form_pdf(tmp_path / "f.pdf"))
    with pytest.raises(rt_codes.RpcError) as excinfo:
        core.document_page_geometry(session, page=5)
    assert excinfo.value.code == "page_out_of_range"


# --- mapping: unique, ambiguous, unmapped -----------------------------------

def _profile(cells=(), anchors=()):
    return {
        "anchor_records": [{"text": text, "at_para": index}
                           for index, text in enumerate(anchors)],
        "table_map": [{"index": 0, "cells": list(cells)}],
    }


def _line(text, bbox=(10, 10, 50, 20)):
    return {"text": text, "bbox": list(bbox), "spanCount": 1}


def test_a_unique_target_maps_to_one_address():
    normalize = rt_geometry.normalizer()
    targets, _ = rt_geometry.build_targets(_profile(anchors=["제목"]), normalize)
    spans = rt_geometry.map_spans([_line("제목")], targets, normalize, 100, 100)
    assert spans[0]["confidence"] == "unique"
    assert spans[0]["address"]["kind"] == "anchor"
    assert "candidates" not in spans[0]


def test_an_ambiguous_label_returns_candidates_and_never_picks_one():
    """T41: one unscoped key overwrote five sibling contracts."""
    normalize = rt_geometry.normalizer()
    cells = [{"addr": {"row": 1, "col": 0}, "text_preview": "근 무 장 소",
              "classification": "static"},
             {"addr": {"row": 9, "col": 0}, "text_preview": "근 무 장 소",
              "classification": "static"}]
    targets, _ = rt_geometry.build_targets(_profile(cells=cells), normalize)
    spans = rt_geometry.map_spans([_line("근 무 장 소")], targets, normalize,
                                  100, 100)
    span = spans[0]
    assert span["confidence"] == "ambiguous"
    assert span["address"] is None, "an ambiguous span must not carry an address"
    assert len(span["candidates"]) == 2
    assert {c["row"] for c in span["candidates"]} == {1, 9}


def test_an_unmatched_line_is_unmapped_not_nearest_guess():
    normalize = rt_geometry.normalizer()
    targets, _ = rt_geometry.build_targets(_profile(anchors=["제목"]), normalize)
    spans = rt_geometry.map_spans([_line("제목입니다만")], targets, normalize,
                                  100, 100)
    assert spans[0]["confidence"] == "unmapped"
    assert spans[0]["address"] is None
    assert "candidates" not in spans[0]


def test_matching_uses_the_gates_whitespace_rule():
    """Reflowed whitespace matches; that is the whole point of borrowing it."""
    normalize = rt_geometry.normalizer()
    targets, _ = rt_geometry.build_targets(_profile(anchors=["행 정  기관 명"]),
                                           normalize)
    spans = rt_geometry.map_spans([_line("행 정 기관   명")], targets,
                                  normalize, 100, 100)
    assert spans[0]["confidence"] == "unique"


def test_a_truncated_cell_preview_is_excluded_rather_than_guessed_at():
    normalize = rt_geometry.normalizer()
    cells = [{"addr": {"row": 0, "col": 0}, "text_preview": "a" * 30,
              "truncated": True, "classification": "static"}]
    targets, excluded = rt_geometry.build_targets(_profile(cells=cells),
                                                  normalize)
    assert targets == {}
    assert excluded["truncatedCells"] == 1


@needs_rasterizer
def test_the_mapping_summary_counts_every_span(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    _attach_pdf(core, session, _form_pdf(tmp_path / "f.pdf"))
    result = core.document_page_geometry(session)
    mapping = result["mapping"]
    assert mapping["state"] == "ran"
    assert mapping["normalizer"].endswith("normalize_text")
    total = mapping["unique"] + mapping["ambiguous"] + mapping["unmapped"]
    assert total == len(result["spans"])
    # the line nobody has ever seen is genuinely unmapped
    stranger = next(s for s in result["spans"]
                    if s["text"] == STRANGER_LINE)
    assert stranger["confidence"] == "unmapped" and stranger["address"] is None


# --- empty seats -------------------------------------------------------------

def _seat_cells():
    return [
        {"addr": {"row": 5, "col": 0}, "text_preview": ROW5_LABEL,
         "classification": "static"},
        {"addr": {"row": 5, "col": 1}, "text_preview": "",
         "classification": "fill_target"},
        {"addr": {"row": 5, "col": 8}, "text_preview": "",
         "classification": "fill_target"},
        {"addr": {"row": 9, "col": 3}, "text_preview": "",
         "classification": "fill_target"},
    ]


def _mapped_label_span():
    return [{"index": 0, "text": ROW5_LABEL, "rect": [0.1, 0.2, 0.2, 0.24],
             "address": {"kind": "cell", "table": 0, "row": 5, "col": 0},
             "confidence": "unique"}]


def test_an_empty_seat_next_to_a_label_is_interpolated():
    seats, _ = rt_geometry.derive_seats(_profile(cells=_seat_cells()),
                                        _mapped_label_span(), [], 600.0, 800.0)
    placed = {(s["row"], s["col"]): s for s in seats}
    seat = placed[(5, 1)]
    assert seat["derivation"] == "interpolated"
    assert seat["rect"][0] == pytest.approx(0.2)   # starts where the label ends
    assert seat["rect"][2] == pytest.approx(1.0)   # runs to the page edge
    assert seat["basis"]["fromCell"] == {"table": 0, "row": 5, "col": 0}


def test_a_drawn_rule_snaps_the_seat_and_upgrades_the_derivation():
    # The interpolated seat runs x 0.2..1.0, y 0.2..0.24 of a 600x800
    # page, so its midpoint in points is (360, 176). A drawn box has to
    # enclose THAT to be believed.
    drawn = [[300.0, 160.0, 450.0, 195.0]]
    seats, _ = rt_geometry.derive_seats(_profile(cells=_seat_cells()),
                                        _mapped_label_span(), drawn,
                                        600.0, 800.0)
    seat = {(s["row"], s["col"]): s for s in seats}[(5, 1)]
    assert seat["derivation"] == "cell_borders"
    assert seat["rect"] == [0.5, 0.2, 0.75, 0.24375]
    assert seat["basis"]["snappedTo"].startswith("a rule")


def test_a_seat_with_no_label_in_its_row_is_absent_not_boxed():
    seats, _ = rt_geometry.derive_seats(_profile(cells=_seat_cells()),
                                        _mapped_label_span(), [], 600.0, 800.0)
    placed = {(s["row"], s["col"]) for s in seats}
    assert (9, 3) not in placed, "a seat with no anchor must not be invented"


def test_a_far_seat_does_not_inherit_the_first_labels_box():
    """One label and two seats: we know where the first is, not the second."""
    seats, _ = rt_geometry.derive_seats(_profile(cells=_seat_cells()),
                                        _mapped_label_span(), [], 600.0, 800.0)
    placed = {(s["row"], s["col"]) for s in seats}
    assert (5, 1) in placed
    assert (5, 8) not in placed
    assert len({tuple(s["rect"]) for s in seats}) == len(seats)


def test_a_seat_that_already_has_text_uses_its_own_span():
    cells = [{"addr": {"row": 2, "col": 3}, "text_preview": "값",
              "classification": "fill_target"}]
    spans = [{"index": 0, "text": "값", "rect": [0.3, 0.4, 0.5, 0.44],
              "address": {"kind": "cell", "table": 0, "row": 2, "col": 3},
              "confidence": "unique"}]
    seats, _ = rt_geometry.derive_seats(_profile(cells=cells), spans, [],
                                        600, 800)
    assert seats[0]["derivation"] == "matched_text"
    assert seats[0]["rect"] == [0.3, 0.4, 0.5, 0.44]


def test_the_page_frame_is_not_mistaken_for_a_cell():
    whole_page = [[0.0, 0.0, 600.0, 800.0]]
    seats, _ = rt_geometry.derive_seats(_profile(cells=_seat_cells()),
                                        _mapped_label_span(), whole_page,
                                        600.0, 800.0)
    seat = {(s["row"], s["col"]): s for s in seats}[(5, 1)]
    assert seat["derivation"] == "interpolated", "the page frame is not a cell"


def test_every_derivation_reported_is_in_the_closed_set():
    seats, _ = rt_geometry.derive_seats(_profile(cells=_seat_cells()),
                                        _mapped_label_span(),
                                        [[150.0, 155.0, 300.0, 195.0]],
                                        600, 800)
    for seat in seats:
        assert seat["derivation"] in rt_geometry.DERIVATION_METHODS


@needs_rasterizer
def test_seat_derivations_are_counted_in_the_answer(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    _attach_pdf(core, session, _form_pdf(tmp_path / "f.pdf"))
    result = core.document_page_geometry(session)
    counts = result["seatDerivations"]
    assert set(counts) == set(rt_geometry.DERIVATION_METHODS)
    assert sum(counts.values()) == len(result["seats"])


# --- cache -------------------------------------------------------------------

@needs_rasterizer
def test_a_second_read_of_the_same_page_hits_the_cache(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    _attach_pdf(core, session, _form_pdf(tmp_path / "f.pdf"))
    first = core.document_page_geometry(session)
    second = core.document_page_geometry(session)
    assert first["cache"]["hit"] is False
    assert second["cache"]["hit"] is True
    assert first["cache"]["key"] == second["cache"]["key"]
    assert first["spans"] == second["spans"]


@needs_rasterizer
def test_the_cache_key_is_the_pdf_hash_so_new_bytes_miss(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    _attach_pdf(core, session, _form_pdf(tmp_path / "a.pdf"))
    first = core.document_page_geometry(session)
    _attach_pdf(core, session, _form_pdf(tmp_path / "b.pdf", boxed=False))
    second = core.document_page_geometry(session)
    assert first["cache"]["key"] != second["cache"]["key"]
    assert second["cache"]["hit"] is False


def test_the_cache_is_bounded():
    cache = {}
    for index in range(rt_geometry.MAX_CACHE_ENTRIES + 10):
        if len(cache) >= rt_geometry.MAX_CACHE_ENTRIES:
            cache.pop(next(iter(cache)))
        cache[f"k{index}"] = index
    assert len(cache) == rt_geometry.MAX_CACHE_ENTRIES


# --- surfaces -----------------------------------------------------------------

def test_capabilities_carry_the_geometry_block(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        capabilities = client.initialize()["result"]["capabilities"]
    # a sibling of render, not a field inside it: geometry is zoom-independent
    # and cached separately, which is why it is its own method
    assert "geometry" not in capabilities["render"]
    geometry = capabilities["geometry"]
    assert geometry["method"] == "document/pageGeometry"
    assert geometry["unit"] == "normalized"
    assert geometry["origin"] == "top-left"
    assert geometry["derivationMethods"] == list(rt_geometry.DERIVATION_METHODS)
    assert "check_residue" in geometry["normalizer"]


@needs_rasterizer
def test_geometry_travels_over_the_wire(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open",
                      "--path", str(_hwpx(tmp_path))).result["sessionId"]
    _attach_pdf(RuntimeCore(root), session, _form_pdf(tmp_path / "f.pdf"))
    with RuntimeClient(root) as client:
        client.initialize()
        result = client.ok("document/pageGeometry", {"sessionId": session})
    assert result["available"] is True
    assert result["spans"]


def test_it_is_an_agent_safe_method_and_an_mcp_tool():
    import mcp_server
    import rt_core

    assert "document/pageGeometry" in rt_core.AGENT_METHODS
    assert "document/pageGeometry" not in rt_core.HOST_ONLY_METHODS
    assert "document_pageGeometry" in mcp_server.TOOL_TO_METHOD


@needs_rasterizer
def test_the_cli_mirrors_it(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open",
                      "--path", str(_hwpx(tmp_path))).result["sessionId"]
    _attach_pdf(RuntimeCore(root), session, _form_pdf(tmp_path / "f.pdf"))
    result = run_cli(root, "geometry", "--session", session)
    assert result.code == 0
    assert result.result["available"] is True


def test_the_cli_reports_unavailable_as_a_success_unless_asked_otherwise(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open",
                      "--path", str(_hwpx(tmp_path))).result["sessionId"]
    assert run_cli(root, "geometry", "--session", session).code == 0
    strict = run_cli(root, "geometry", "--session", session,
                     "--require-geometry")
    assert strict.code == 3
    assert strict.payload["result"]["unavailable"]["reason"] == "needs_conversion"


# --- the drawn grid: rules, not rectangles -----------------------------------
# Hancom strokes every ruling as a line segment. These pin the reconstruction's
# mechanics on PDFs built here; whether it reconstructs a REAL form is settled
# further down against the corpus renders, which is the only evidence that
# counts for that claim.

def _ruled_pdf(path, rows, cols, *, x0=100.0, y0=100.0, w=90.0, h=30.0,
               dashed=False, omit=()):
    """A grid of ``rows`` x ``cols`` boxes drawn as separate line segments."""
    module = rt_render.rasterizer_module()
    assert module is not None
    document = module.open()
    try:
        page = document.new_page()

        def line(ax, ay, bx, by):
            if not dashed:
                page.draw_line(module.Point(ax, ay), module.Point(bx, by))
                return
            # A dashed rule really is many short collinear pieces. The dash and
            # gap here are the ones Hancom actually emits: measured across the
            # corpus renders, 12,045 of 13,972 horizontal segments are under
            # 3pt and their collinear gaps cluster at 0.4-0.8pt.
            dash, gap = 2.0, 0.7
            length = max(abs(bx - ax), abs(by - ay))
            ux = (bx - ax) / length if length else 0.0
            uy = (by - ay) / length if length else 0.0
            at = 0.0
            while at < length:
                end = min(at + dash, length)
                page.draw_line(module.Point(ax + ux * at, ay + uy * at),
                               module.Point(ax + ux * end, ay + uy * end))
                at = end + gap

        for row in range(rows + 1):
            y = y0 + row * h
            line(x0, y, x0 + cols * w, y)
        for col in range(cols + 1):
            if col in omit:
                continue
            x = x0 + col * w
            line(x, y0, x, y0 + rows * h)
        document.save(str(path))
    finally:
        document.close()
    return path


@needs_rasterizer
def test_a_grid_of_stroked_rules_becomes_cells(tmp_path):
    """The defect in one line: Hancom draws lines, and lines have no area."""
    module = rt_render.rasterizer_module()
    pdf = _ruled_pdf(tmp_path / "grid.pdf", 3, 4)
    extracted = rt_geometry.extract_page(module, pdf, 0)
    # the old reading saw only hairlines and found nothing cell-shaped
    believable = [rect for rect in extracted["drawnRects"]
                  if (rect[2] - rect[0]) * (rect[3] - rect[1])
                  >= rt_geometry.MIN_SEAT_AREA_PT]
    assert believable == [], "a stroked rule is not a rectangle with area"
    assert len(extracted["drawnCells"]) == 12


@needs_rasterizer
def test_a_dashed_rule_is_one_rule_not_many(tmp_path):
    module = rt_render.rasterizer_module()
    pdf = _ruled_pdf(tmp_path / "dashed.pdf", 2, 2, dashed=True)
    cells = rt_geometry.extract_page(module, pdf, 0)["drawnCells"]
    assert len(cells) == 4


@needs_rasterizer
def test_a_cell_missing_a_side_is_not_a_cell(tmp_path):
    """Three sides drawn is not an enclosure, and never becomes one."""
    # drop the last vertical: the rightmost column no longer closes
    pdf = _ruled_pdf(tmp_path / "open.pdf", 2, 3, omit=(3,))
    module = rt_render.rasterizer_module()
    cells = rt_geometry.extract_page(module, pdf, 0)["drawnCells"]
    assert len(cells) == 4, "2 rows x 2 closed columns; the open one is absent"


def test_a_rule_positions_product_is_not_the_grid():
    """Two stacked tables must not slice each other into cells nobody drew.

    A plain product of the x and y rule positions would invent them, which is
    why the reconstruction grows each cell to its NEAREST closing partners.
    """
    horizontal = [[0.0, 0.0, 100.0], [40.0, 0.0, 100.0],      # upper table
                  [200.0, 0.0, 100.0], [240.0, 0.0, 100.0]]   # lower table
    vertical = [[0.0, 0.0, 40.0], [100.0, 0.0, 40.0],         # upper: 1 column
                [0.0, 200.0, 240.0], [50.0, 200.0, 240.0],    # lower: 2 columns
                [100.0, 200.0, 240.0]]
    cells = rt_geometry.drawn_cells(horizontal, vertical, 600.0, 800.0)
    assert sorted(cells) == [(0.0, 0.0, 100.0, 40.0),
                             (0.0, 200.0, 50.0, 240.0),
                             (50.0, 200.0, 100.0, 240.0)]


def test_the_page_frame_is_still_not_a_cell():
    horizontal = [[0.0, 0.0, 600.0], [800.0, 0.0, 600.0]]
    vertical = [[0.0, 0.0, 800.0], [600.0, 0.0, 800.0]]
    assert rt_geometry.drawn_cells(horizontal, vertical, 600.0, 800.0) == []


def test_a_hairline_gap_between_double_rules_is_not_a_cell():
    """A border drawn twice is one border, not a cell a point tall."""
    horizontal = [[100.0, 0.0, 90.0], [101.2, 0.0, 90.0],
                  [140.0, 0.0, 90.0], [141.2, 0.0, 90.0]]
    vertical = [[0.0, 100.0, 141.2], [90.0, 100.0, 141.2]]
    cells = rt_geometry.drawn_cells(horizontal, vertical, 600.0, 800.0)
    assert len(cells) == 1
    assert cells[0][3] - cells[0][1] > rt_geometry.MIN_CELL_HEIGHT_PT


def test_a_diagonal_is_not_a_cell_border():
    horizontal, vertical = rt_geometry.ruling_segments(
        [{"items": [("l", (0.0, 0.0), (100.0, 100.0))]}])
    assert horizontal == [] and vertical == []


def test_a_rule_drawn_as_a_thin_filled_box_still_counts():
    """Some rules are strokes, some are slivers. Both are rules.

    A 100x0.6pt box contributes two long horizontal edges and two 0.6pt stubs;
    the stubs are dropped when the rule's own length is judged, so the sliver
    ends up as the single horizontal rule a reader sees.
    """
    horizontal, vertical = rt_geometry.ruling_segments(
        [{"items": [("re", (10.0, 20.0, 110.0, 20.6))]}])
    assert len(horizontal) == 2
    assert rt_geometry.cluster_rules(vertical) == [], "0.6pt is not a rule"
    rules = rt_geometry.cluster_rules(horizontal)
    assert len(rules) == 1 and rules[0][1] == [[10.0, 110.0]]


# --- alignment: earned from an anchor, and abandoned where it is not ---------

def _grid_cells(cols, *, top=100.0, bottom=130.0, left=100.0, width=90.0):
    """``cols`` drawn cells in one row, edge to edge."""
    return [(left + i * width, top, left + (i + 1) * width, bottom)
            for i in range(cols)]


def _row_profile(entries, table=0, row=5):
    """entries: [(col, text, classification)] -> a one-row form scan."""
    cells = []
    for col, text, classification in entries:
        cells.append({"addr": {"row": row, "col": col},
                      "text_preview": text,
                      "classification": classification})
    return {"anchor_records": [], "table_map": [{"index": table,
                                                 "cells": cells}]}


def _span_at(rect, address, *, index=0, text="x", confidence="unique"):
    span = {"index": index, "text": text, "rect": rect, "address": address,
            "confidence": confidence}
    return span


def _line_at(text, box):
    return {"text": text, "bbox": list(box), "spanCount": 1}


def _norm():
    normalize = rt_geometry.normalizer()
    assert normalize is not None
    return normalize


def test_an_anchor_carries_its_neighbours_along_the_drawn_row():
    """The label is matched; the empty seat beside it is not, and cannot be.

    It gets a rect because the page draws a box there AND the walk to it
    passed through a cell whose text the render confirmed.
    """
    cells = _grid_cells(3)
    profile = _row_profile([(0, "성명", "static"),
                            (1, "", "fill_target"),
                            (2, "", "fill_target")])
    spans = [_span_at([0.2, 0.2, 0.3, 0.24],
                      {"kind": "cell", "table": 0, "row": 5, "col": 0})]
    lines = [_line_at("성명", (110.0, 105.0, 160.0, 120.0))]
    placed, absences = rt_geometry.align_drawn_grid(
        profile, spans, cells, lines, 500.0, 500.0, _norm())
    assert placed[(0, 5, 1)] == cells[1]
    assert placed[(0, 5, 2)] == cells[2]
    assert absences == {}


def test_the_walk_stops_where_the_page_contradicts_the_scan():
    """A box holding the wrong text ends the walk; nothing past it is placed."""
    cells = _grid_cells(4)
    profile = _row_profile([(0, "성명", "static"),
                            (1, "", "fill_target"),
                            (2, "생년월일", "static"),
                            (3, "", "fill_target")])
    spans = [_span_at([0.2, 0.2, 0.3, 0.24],
                      {"kind": "cell", "table": 0, "row": 5, "col": 0})]
    lines = [_line_at("성명", (110.0, 105.0, 160.0, 120.0)),
             # the third box says something the scan never declared there
             _line_at("주소", (290.0, 105.0, 340.0, 120.0))]
    placed, absences = rt_geometry.align_drawn_grid(
        profile, spans, cells, lines, 500.0, 500.0, _norm())
    assert placed == {(0, 5, 1): cells[1]}, "the seat before the lie is fine"
    assert (0, 5, 3) not in placed, "nothing past a contradiction is placed"
    assert absences["cell_mismatch"] == 1
    assert absences["no_anchor_in_row"] == 1


def test_a_seat_whose_box_already_holds_text_is_refused():
    """An empty cell that is not empty on the page is somebody else's box."""
    cells = _grid_cells(2)
    profile = _row_profile([(0, "성명", "static"), (1, "", "fill_target")])
    spans = [_span_at([0.2, 0.2, 0.3, 0.24],
                      {"kind": "cell", "table": 0, "row": 5, "col": 0})]
    lines = [_line_at("성명", (110.0, 105.0, 160.0, 120.0)),
             _line_at("이미 찬 값", (200.0, 105.0, 250.0, 120.0))]
    placed, absences = rt_geometry.align_drawn_grid(
        profile, spans, cells, lines, 500.0, 500.0, _norm())
    assert placed == {}
    assert absences["cell_mismatch"] == 1


def test_an_anchor_that_cannot_verify_itself_vouches_for_nothing():
    """Gating the anchor on its own cell text is what removed the last 31
    wrong correspondences in the corpus audit."""
    cells = _grid_cells(3)
    profile = _row_profile([(0, "성명", "static"),
                            (1, "", "fill_target"),
                            (2, "", "fill_target")])
    spans = [_span_at([0.2, 0.2, 0.3, 0.24],
                      {"kind": "cell", "table": 0, "row": 5, "col": 0})]
    # the box the anchor landed in carries different text than the scan says
    lines = [_line_at("전혀 다른 말", (110.0, 105.0, 160.0, 120.0))]
    placed, absences = rt_geometry.align_drawn_grid(
        profile, spans, cells, lines, 500.0, 500.0, _norm())
    assert placed == {}
    assert absences["alignment_failed"] == 1


def test_a_gap_in_the_drawn_grid_stops_the_walk():
    """Where the form draws no box, there is no seat -- the row does not
    reconcile and the cells past the hole stay absent."""
    cells = [(100.0, 100.0, 190.0, 130.0), (190.0, 100.0, 280.0, 130.0),
             # a deliberate hole, then the row resumes
             (400.0, 100.0, 490.0, 130.0)]
    profile = _row_profile([(0, "성명", "static"),
                            (1, "", "fill_target"),
                            (2, "", "fill_target")])
    spans = [_span_at([0.2, 0.2, 0.3, 0.24],
                      {"kind": "cell", "table": 0, "row": 5, "col": 0})]
    lines = [_line_at("성명", (110.0, 105.0, 160.0, 120.0))]
    placed, absences = rt_geometry.align_drawn_grid(
        profile, spans, cells, lines, 500.0, 500.0, _norm())
    assert placed == {(0, 5, 1): cells[1]}
    assert absences["grid_gap"] == 1
    assert absences["no_anchor_in_row"] == 1


def test_two_anchors_that_disagree_refuse_the_cell_between_them():
    """One declared row, two drawn bands -- a header repeated down the page.

    Each anchor walks its own band and reaches col 1 in a different box. There
    is no way to tell which band the scan meant, so col 1 is refused. Averaging
    them, or taking the first, is the T41 mistake in a new costume.
    """
    upper = _grid_cells(3, top=100.0, bottom=130.0)
    lower = _grid_cells(3, top=200.0, bottom=230.0)
    cells = upper + lower
    profile = _row_profile([(0, "가", "static"),
                            (1, "", "fill_target"),
                            (2, "다", "static")])
    spans = [_span_at([0.22, 0.21, 0.3, 0.25],
                      {"kind": "cell", "table": 0, "row": 5, "col": 0}),
             _span_at([0.58, 0.41, 0.66, 0.45],
                      {"kind": "cell", "table": 0, "row": 5, "col": 2},
                      index=1)]
    lines = [_line_at("가", (110.0, 105.0, 150.0, 120.0)),
             _line_at("다", (290.0, 205.0, 330.0, 220.0))]
    placed, absences = rt_geometry.align_drawn_grid(
        profile, spans, cells, lines, 500.0, 500.0, _norm())
    assert (0, 5, 1) not in placed
    assert absences["alignment_failed"] == 1


def test_a_table_nothing_identified_here_is_absent_with_its_own_reason():
    profile = _row_profile([(0, "성명", "static"), (1, "", "fill_target")])
    placed, absences = rt_geometry.align_drawn_grid(
        profile, [], _grid_cells(2), [], 500.0, 500.0, _norm())
    assert placed == {}
    assert absences == {"no_anchor_on_page": 1}


def test_a_page_with_no_drawn_grid_says_so(tmp_path):
    profile = _row_profile([(0, "성명", "static"), (1, "", "fill_target")])
    seats, absences = rt_geometry.derive_seats(
        profile, [], [], 500.0, 500.0, cells=[], lines=[],
        normalize=_norm())
    assert seats == []
    assert absences == {"no_drawn_grid": 1}


def test_every_absence_reason_is_in_the_closed_set():
    assert set(rt_geometry.ABSENCE_REASONS) == {
        "no_drawn_grid", "no_anchor_on_page", "no_anchor_in_row",
        "grid_gap", "cell_mismatch", "alignment_failed"}


# --- the anchor supply, and what it still refuses ----------------------------

def test_one_anchor_and_one_cell_name_one_place_so_it_anchors():
    """Ambiguous about what to CALL it, not about where it is."""
    span = {"confidence": "ambiguous", "address": None, "candidates": [
        {"kind": "anchor", "text": "성명"},
        {"kind": "cell", "table": 0, "row": 5, "col": 0}]}
    assert rt_geometry.sole_cell_address(span) == (0, 5, 0)


def test_two_distinct_cells_still_refuse_to_anchor():
    """T41 untouched: a label on six sheets pins nothing."""
    span = {"confidence": "ambiguous", "address": None, "candidates": [
        {"kind": "cell", "table": 0, "row": 1, "col": 0},
        {"kind": "cell", "table": 0, "row": 9, "col": 0}]}
    assert rt_geometry.sole_cell_address(span) is None


def test_anchoring_never_writes_an_address_onto_an_ambiguous_span():
    """The wire contract is unchanged; this reading is internal to seating."""
    normalize = _norm()
    cells = [{"addr": {"row": 1, "col": 0}, "text_preview": "근 무 장 소",
              "classification": "static"},
             {"addr": {"row": 9, "col": 0}, "text_preview": "근 무 장 소",
              "classification": "static"}]
    targets, _ = rt_geometry.build_targets(_profile(cells=cells), normalize)
    spans = rt_geometry.map_spans([_line("근 무 장 소")], targets, normalize,
                                  100, 100)
    assert spans[0]["address"] is None
    assert spans[0]["confidence"] == "ambiguous"


# --- the corpus measurement, which is the only evidence that counts ----------
# These 10 PDFs are real Hancom output: engine/scripts/com_backend.py drove
# Hancom Office 13.0.0.2986 on the operator machine (docs/research/
# xc1-conversion-bench.md §4). Nothing here is drawn by this repo, which is
# the entire point -- a border-finder validated against a fixture I drew
# myself would prove nothing about Hancom's layout.

CORPUS_RENDERS = (Path(__file__).resolve().parents[1] / "tests" / "corpus"
                  / "forms" / "render")
CORPUS_CONVERTED = (Path(__file__).resolve().parents[1] / "tests" / "corpus"
                    / "forms" / "converted")

#: Measured, per form: (editable fill regions, seats document/pageGeometry
#: places). Recorded as data so a regression names the form it broke. The
#: totals below are the deliverable's headline and are asserted exactly.
CORPUS_SEATS = {
    "admrul-gajokdolbom-hyuga-sinchengseo": (7, 5),
    "gianmun-byeolji-1ho": (9, 0),
    "gianmun-byeolji-2ho": (35, 3),
    "jeongbo-gonggae-cheongguseo": (13, 0),
    "jumin-deungchobon-sinchengseo": (5, 1),
    "kstartup-jiwon-sincheongseo-saeopgyehoekseo": (125, 55),
    "moel-pyojun-geunrogyeyakseo-2013": (3, 0),
    "moel-pyojun-geunrogyeyakseo-2025": (0, 0),
    "nrf-gyeolgwa-bogoseo-yangsik": (5, 1),
    "saeopja-deungnok-sinchengseo": (271, 8),
}
CORPUS_FILL_TOTAL = 473
CORPUS_SEAT_TOTAL = 73

have_renders = all((CORPUS_RENDERS / f"{slug}.pdf").is_file()
                   for slug in CORPUS_SEATS)
needs_corpus_renders = pytest.mark.skipif(
    not have_renders,
    reason=("the real Hancom renders are not on this machine; corpus seat "
            "placement is UNPROVEN here and must not be asserted against a "
            "PDF this repo drew itself"))


def _profile_of(slug, tmp_path):
    """The form scan, from the converted hwpx, via the engine's own tool."""
    import subprocess
    import sys as _sys

    out = tmp_path / f"{slug}.json"
    source = CORPUS_CONVERTED / f"{slug}.hwpx"
    result = subprocess.run(
        [_sys.executable,
         str(Path(__file__).resolve().parents[1] / "engine" / "scripts"
             / "form_inspect.py"), str(source), "--out", str(out)],
        capture_output=True)
    assert result.returncode == 0, result.stderr[:2000]
    return json.loads(out.read_text(encoding="utf-8"))


def _seats_for_form(slug, profile):
    """Every seat document/pageGeometry places across the form's pages."""
    module = rt_render.rasterizer_module()
    pdf = CORPUS_RENDERS / f"{slug}.pdf"
    normalize = rt_geometry.normalizer()
    document = module.open(str(pdf))
    pages = document.page_count
    document.close()
    placed = {}
    for page in range(pages):
        extracted = rt_geometry.extract_page(module, pdf, page)
        width, height = extracted["widthPt"], extracted["heightPt"]
        targets, _ = rt_geometry.build_targets(profile, normalize)
        spans = rt_geometry.map_spans(extracted["lines"], targets, normalize,
                                      width, height)
        seats, _ = rt_geometry.derive_seats(
            profile, spans, extracted["drawnRects"], width, height,
            cells=extracted["drawnCells"], lines=extracted["lines"],
            normalize=normalize)
        for seat in seats:
            placed[(seat["table"], seat["row"], seat["col"])] = seat
    return placed, pages


@needs_rasterizer
@needs_corpus_renders
@pytest.mark.parametrize("slug", sorted(CORPUS_SEATS))
def test_seats_placed_on_the_real_hancom_render(slug, tmp_path):
    expected_fill, expected_seats = CORPUS_SEATS[slug]
    profile = _profile_of(slug, tmp_path)
    fills = sum(1 for table in profile.get("table_map") or []
                for cell in table.get("cells") or []
                if cell.get("classification") == "fill_target")
    assert fills == expected_fill, "the form scan itself moved"
    placed, _ = _seats_for_form(slug, profile)
    assert len(placed) == expected_seats
    assert all(seat["derivation"] == "cell_borders"
               for seat in placed.values()), "text cannot reach an empty cell"


@needs_rasterizer
@needs_corpus_renders
def test_the_corpus_headline_number(tmp_path):
    """0 of 473 was the measurement that opened this slice. This is where it
    stands now, and it is asserted exactly so it cannot quietly drift."""
    total_fill = sum(fill for fill, _ in CORPUS_SEATS.values())
    total_seats = sum(seats for _, seats in CORPUS_SEATS.values())
    assert total_fill == CORPUS_FILL_TOTAL
    assert total_seats == CORPUS_SEAT_TOTAL


@needs_rasterizer
@needs_corpus_renders
@pytest.mark.parametrize("slug", sorted(CORPUS_SEATS))
def test_every_placed_seat_is_a_box_the_page_really_drew(slug, tmp_path):
    """The audit that decides whether the number above is worth anything.

    A seat must BE one of the reconstructed cells (not a rectangle derived
    from one), and it must be empty in the render -- an empty fill cell whose
    box holds text is a misalignment, however plausible the box looked.
    """
    module = rt_render.rasterizer_module()
    profile = _profile_of(slug, tmp_path)
    pdf = CORPUS_RENDERS / f"{slug}.pdf"
    normalize = rt_geometry.normalizer()
    document = module.open(str(pdf))
    pages = document.page_count
    document.close()
    checked = 0
    for page in range(pages):
        extracted = rt_geometry.extract_page(module, pdf, page)
        width, height = extracted["widthPt"], extracted["heightPt"]
        targets, _ = rt_geometry.build_targets(profile, normalize)
        spans = rt_geometry.map_spans(extracted["lines"], targets, normalize,
                                      width, height)
        seats, _ = rt_geometry.derive_seats(
            profile, spans, extracted["drawnRects"], width, height,
            cells=extracted["drawnCells"], lines=extracted["lines"],
            normalize=normalize)
        inside = rt_geometry.text_by_drawn_cell(
            extracted["lines"], extracted["drawnCells"], normalize)
        for seat in seats:
            x0, y0, x1, y1 = seat["rect"]
            assert 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0, seat
            box = (x0 * width, y0 * height, x1 * width, y1 * height)
            drawn = next((cell for cell in extracted["drawnCells"]
                          if all(abs(a - b) < 0.05
                                 for a, b in zip(box, cell))), None)
            assert drawn is not None, "a seat rect that nothing on the page drew"
            assert not inside.get(drawn), "an empty seat whose box holds text"
            checked += 1
    assert checked == CORPUS_SEATS[slug][1]


@needs_rasterizer
@needs_corpus_renders
def test_seats_do_not_overlap_each_other_on_a_page(tmp_path):
    """Two seats sharing a box would put one caret in two places."""
    module = rt_render.rasterizer_module()
    for slug in sorted(CORPUS_SEATS):
        if not CORPUS_SEATS[slug][1]:
            continue
        profile = _profile_of(slug, tmp_path)
        pdf = CORPUS_RENDERS / f"{slug}.pdf"
        normalize = rt_geometry.normalizer()
        document = module.open(str(pdf))
        pages = document.page_count
        document.close()
        for page in range(pages):
            extracted = rt_geometry.extract_page(module, pdf, page)
            width, height = extracted["widthPt"], extracted["heightPt"]
            targets, _ = rt_geometry.build_targets(profile, normalize)
            spans = rt_geometry.map_spans(extracted["lines"], targets,
                                          normalize, width, height)
            seats, _ = rt_geometry.derive_seats(
                profile, spans, extracted["drawnRects"], width, height,
                cells=extracted["drawnCells"], lines=extracted["lines"],
                normalize=normalize)
            rects = [seat["rect"] for seat in seats]
            for i, a in enumerate(rects):
                for b in rects[i + 1:]:
                    assert not (a[0] < b[2] and b[0] < a[2]
                                and a[1] < b[3] and b[1] < a[3]), \
                        f"{slug} page {page}: two seats share a box"


@needs_rasterizer
@needs_corpus_renders
def test_the_grid_is_zoom_independent(tmp_path):
    """Normalized rects are the same fractions whatever dpi anyone renders at.

    Geometry never sees a dpi, so the guard is that the same page read twice
    gives identical fractions and that they are fractions, not points.
    """
    slug = "kstartup-jiwon-sincheongseo-saeopgyehoekseo"
    profile = _profile_of(slug, tmp_path)
    first, _ = _seats_for_form(slug, profile)
    second, _ = _seats_for_form(slug, profile)
    assert first.keys() == second.keys()
    assert all(first[key]["rect"] == second[key]["rect"] for key in first)
    assert all(0.0 <= value <= 1.0
               for seat in first.values() for value in seat["rect"])


@needs_rasterizer
@needs_corpus_renders
def test_a_form_the_grid_cannot_reach_places_nothing_and_says_why(tmp_path):
    """gianmun-byeolji-1ho is ruled with underlines, not boxes: 6 horizontal
    rules and 4 verticals on the page, so almost nothing closes. Its 9 fill
    regions are absent, and that is the correct answer, not a failure."""
    slug = "gianmun-byeolji-1ho"
    profile = _profile_of(slug, tmp_path)
    placed, _ = _seats_for_form(slug, profile)
    assert placed == {}
    module = rt_render.rasterizer_module()
    extracted = rt_geometry.extract_page(
        module, CORPUS_RENDERS / f"{slug}.pdf", 0)
    assert len(extracted["drawnCells"]) < 5, "the page really is barely ruled"


# --- sub-line offsets: where each character begins --------------------------
#
# The gap §12.6 recorded as "a span is a line; a click resolves to the line's
# address, not to a character offset within it". A line still IS the mapping
# unit -- nothing about matching changed -- but the line now carries the x
# where each of its characters starts, read from the same render, so an editor
# can put a caret inside a line instead of only at its front.
#
# What these pin is the refusals. Boxes that are not one-per-character, or not
# left to right, produce NO offsets rather than approximate ones: a caret
# placed from a guess is a cursor standing where the glyph is not, which is
# the same fabrication as a synthesized rect.

def test_char_edges_refuses_a_count_that_does_not_match_the_text():
    spans = [{"chars": [{"c": "가", "bbox": (10, 0, 20, 12)}]}]
    assert rt_geometry.char_edges(spans, "가나") is None


def test_char_edges_refuses_boxes_that_run_backwards():
    spans = [{"chars": [{"c": "가", "bbox": (30, 0, 40, 12)},
                        {"c": "나", "bbox": (10, 0, 20, 12)}]}]
    assert rt_geometry.char_edges(spans, "가나") is None


def test_char_edges_refuses_a_span_with_no_char_boxes_at_all():
    assert rt_geometry.char_edges([{"text": "가나"}], "가나") is None


def test_char_edges_gives_one_x_per_character_plus_the_last_right_edge():
    spans = [{"chars": [{"c": "가", "bbox": (10, 0, 20, 12)},
                        {"c": "나", "bbox": (20, 0, 31, 12)}]}]
    assert rt_geometry.char_edges(spans, "가나") == [10.0, 20.0, 31.0]


def test_line_size_refuses_a_line_whose_spans_disagree():
    """A PyMuPDF line splits at every font run, so it CAN carry two sizes.
    Reporting one of them would be a pick, and this file does not pick."""
    assert rt_geometry.line_size([{"size": 11.0}, {"size": 14.0}]) is None
    assert rt_geometry.line_size([{"size": 11.0}, {"size": 11.004}]) == 11.0
    assert rt_geometry.line_size([{"size": 11.0}, {}]) is None


@needs_rasterizer
def test_every_span_carries_where_its_characters_begin(core, tmp_path):
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    _attach_pdf(core, session, _form_pdf(tmp_path / "f.pdf"))
    result = core.document_page_geometry(session)

    assert result["charOffsets"]["state"] == "read"
    assert result["charOffsets"]["reason"] is None
    assert result["charOffsets"]["lines"] == result["charOffsets"]["of"] > 0
    for span in result["spans"]:
        xs = span["charX"]
        assert len(xs) == len(span["text"]) + 1, span["text"]
        assert xs == sorted(xs), span["text"]
        assert all(0.0 <= x <= 1.0 for x in xs)
        # The offsets live in the SAME coordinate system as the rect, which is
        # what lets a client multiply both by one pixel width.
        assert xs[0] >= span["rect"][0] - 1e-3
        assert xs[-1] <= span["rect"][2] + 1e-3


@needs_rasterizer
def test_the_capability_advertises_sub_line_offsets_before_a_page_is_asked_for():
    """A build either extracts them or it does not, and the packaged bundle's
    role check asserts this rather than discovering it on a user's first
    click."""
    capability = rt_geometry.geometry_capability()
    assert capability["charOffsets"]["emitted"] is True
    assert capability["charOffsets"]["field"] == "spans[].charX"
    assert capability["charOffsets"]["unit"] == "normalized"
    assert (capability["charOffsets"]["states"]
            == list(rt_geometry.CHAR_OFFSET_STATES))
    assert capability["spanUnit"] == "line", "the MAPPING unit did not change"


@needs_rasterizer
def test_a_page_past_the_density_bound_drops_offsets_and_says_so(
        core, tmp_path, monkeypatch):
    """The bound is on the FRAME, not on the feature. Positions survive; the
    offsets do not, and the answer names the reason rather than going quiet."""
    session = core.open_path(str(_hwpx(tmp_path)))["sessionId"]
    _attach_pdf(core, session, _form_pdf(tmp_path / "f.pdf"))
    monkeypatch.setattr(rt_geometry, "MAX_CHAR_EDGES_PER_PAGE", 1)
    result = core.document_page_geometry(session)

    assert result["available"] is True
    assert result["spans"], "the positions are unaffected"
    assert all("charX" not in span for span in result["spans"])
    assert result["charOffsets"]["state"] == "page_too_dense"
    assert "1 bound" in result["charOffsets"]["reason"]
    assert result["charOffsets"]["lines"] == 0
    assert result["charOffsets"]["chars"] > 1


@needs_rasterizer
def test_a_pdf_with_no_form_scan_still_carries_offsets(core, tmp_path):
    """A page with no mapping has real positions, and the offsets are part of
    them. A client that could place a caret on a mapped page but not on an
    unmapped one would be reporting the mapping's absence as the renderer's."""
    pdf = _form_pdf(tmp_path / "standalone.pdf")
    session = core.open_path(str(pdf))["sessionId"]
    result = core.document_page_geometry(session)
    assert result["mapping"]["state"] == "unavailable"
    assert all("charX" in span for span in result["spans"])


@needs_rasterizer
@needs_corpus_renders
def test_the_line_text_did_not_move_when_the_extraction_did():
    """THE LOAD-BEARING ONE. Reading per-character boxes meant reading the page
    as ``rawdict`` rather than ``dict``, and the mapping matches on the text
    that traversal assembles. If the two disagreed anywhere, every address on
    every page would be up for renegotiation. They are compared here on all
    ten real Hancom renders rather than argued about."""
    module = rt_render.rasterizer_module()
    lines = 0
    for slug in sorted(CORPUS_SEATS):
        pdf = CORPUS_RENDERS / f"{slug}.pdf"
        document = module.open(str(pdf))
        try:
            for page in range(document.page_count):
                loaded = document.load_page(page)
                legacy = []
                for block in loaded.get_text("dict").get("blocks", []):
                    for line in block.get("lines", []) or []:
                        text = "".join(str(s.get("text") or "")
                                       for s in (line.get("spans") or []))
                        if text.strip():
                            legacy.append((text, tuple(line.get("bbox") or ())))
                now = rt_geometry.extract_page(module, pdf, page)["lines"]
                assert [(x["text"], tuple(x["bbox"])) for x in now] == legacy, \
                    f"{slug} page {page}: the line inventory moved"
                lines += len(now)
        finally:
            document.close()
    assert lines == 2591, f"the corpus render carries {lines} lines"


@needs_rasterizer
@needs_corpus_renders
def test_the_real_renders_resolve_every_line_to_its_characters():
    """Measured, not assumed: how much of the corpus a caret can reach mid-line.

    Every one of the 2,591 lines across 51 real Hancom-rendered pages resolves
    one box per character, in order. That is the number the Desktop's status
    bar promises when it does NOT say it snapped to the line start."""
    module = rt_render.rasterizer_module()
    total = resolved = sized = 0
    for slug in sorted(CORPUS_SEATS):
        pdf = CORPUS_RENDERS / f"{slug}.pdf"
        document = module.open(str(pdf))
        try:
            pages = document.page_count
        finally:
            document.close()
        for page in range(pages):
            extracted = rt_geometry.extract_page(module, pdf, page)
            width, height = extracted["widthPt"], extracted["heightPt"]
            for index, line in enumerate(extracted["lines"]):
                span = rt_geometry.base_span(index, line, width, height,
                                             with_chars=True)
                total += 1
                if "sizePt" in span:
                    sized += 1
                if "charX" not in span:
                    continue
                resolved += 1
                xs = span["charX"]
                assert len(xs) == len(span["text"]) + 1
                assert xs == sorted(xs)
    assert (total, resolved) == (2591, 2591), (total, resolved)
    # 83 lines are set in two sizes at once, so they carry no single size --
    # which is the honest answer, and the reason the field is optional.
    assert sized == 2508, sized


# --- tier 3: the page OUR renderer drew ---------------------------------------
#
# Same mapping, same three verdicts, one extra witness. The witness is the
# renderer's own record of which paragraph or cell it drew a line from, and
# every test below is about what that witness is and is not allowed to do.

def _own_box(text, box, address=None, *, page=1, mode="lineseg", chars=True):
    """One sidecar line box, in the renderer's own device pixels."""
    x0, y0, x1, y1 = box
    entry = {"page": page, "mode": mode,
             "x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": text}
    if chars and text:
        step = (x1 - x0) / len(text)
        entry["char_x"] = [round(x0 + i * step, 3)
                           for i in range(len(text) + 1)]
    if address is not None:
        entry["address"] = address
    return entry


def _own_profile(cells, anchors=(), table=0):
    """cells: [(row, col, text, classification)]; anchors: [(atPara, text)]."""
    return {
        "anchor_records": [{"at_para": at_para, "text": text}
                           for at_para, text in anchors],
        "table_map": [{"index": table, "cells": [
            {"addr": {"row": row, "col": col}, "text_preview": text,
             "classification": classification}
            for row, col, text, classification in cells]}],
    }


def _mapped_own(boxes, profile, width=600.0, height=800.0):
    lines, declared = rt_geometry.own_lines(boxes)
    targets, _excluded = rt_geometry.build_targets(profile, _norm())
    spans = rt_geometry.map_spans(lines, targets, _norm(), width, height)
    checks = rt_geometry.cross_check_own(spans, declared)
    return spans, checks


def test_own_lines_speak_the_shape_the_pdf_mapping_already_speaks():
    """The tier-3 boxes are RESHAPED, not mapped by a second implementation.

    If this ever diverges, "mapped exactly like tier 1" stops being a fact.
    """
    boxes = [_own_box("성명", (100.0, 50.0, 160.0, 70.0),
                      {"kind": "cell", "table": 0, "row": 5, "col": 0})]
    boxes[0]["size_pt"] = 10.5
    lines, declared = rt_geometry.own_lines(boxes)
    assert lines[0]["text"] == "성명"
    assert lines[0]["bbox"] == [100.0, 50.0, 160.0, 70.0]
    assert lines[0]["sizePt"] == 10.5
    assert len(lines[0]["charEdges"]) == 3
    assert declared[0]["kind"] == "cell"
    span = rt_geometry.base_span(0, lines[0], 600.0, 800.0, with_chars=True)
    # normalized the same way a PDF line is: divided by the page's own width
    assert span["charX"][0] == round(100.0 / 600.0, 6)


def test_a_box_with_no_text_is_a_position_and_nothing_more():
    """An older sidecar, a stamped page number, an equation band."""
    lines, declared = rt_geometry.own_lines(
        [{"page": 1, "mode": "pagenum", "x0": 1.0, "y0": 2.0,
          "x1": 3.0, "y1": 4.0}])
    assert lines[0]["text"] == ""
    assert "charEdges" not in lines[0]
    assert declared == [None]


def test_a_char_x_that_does_not_count_the_characters_is_dropped():
    box = _own_box("성명", (100.0, 50.0, 160.0, 70.0))
    box["char_x"] = [100.0, 130.0]           # two edges for two characters
    lines, _declared = rt_geometry.own_lines([box])
    assert "charEdges" not in lines[0]


def test_the_scan_and_the_renderer_agreeing_is_what_makes_a_span_unique():
    profile = _own_profile([(5, 0, "성명", "static")])
    spans, checks = _mapped_own(
        [_own_box("성명", (100.0, 50.0, 160.0, 70.0),
                  {"kind": "cell", "table": 0, "row": 5, "col": 0})], profile)
    assert spans[0]["confidence"] == "unique"
    assert spans[0]["addressBasis"] == "scan+sidecar"
    assert checks["agree"] == 1 and checks["disagree"] == 0


def test_the_scan_and_the_renderer_disagreeing_makes_it_ambiguous():
    """NEITHER side wins. The span carries both and a person decides."""
    profile = _own_profile([(5, 0, "성명", "static")])
    spans, checks = _mapped_own(
        [_own_box("성명", (100.0, 50.0, 160.0, 70.0),
                  {"kind": "cell", "table": 0, "row": 9, "col": 3})], profile)
    assert spans[0]["confidence"] == "ambiguous"
    assert spans[0]["address"] is None
    assert len(spans[0]["candidates"]) == 2
    assert {c["col"] for c in spans[0]["candidates"]} == {0, 3}
    assert checks["disagree"] == 1 and checks["agree"] == 0


def test_a_paragraph_the_scan_calls_an_anchor_and_we_call_a_cell_agrees():
    """The two sides name the same place at different granularities.

    Measured on the corpus: 256 of 393 scan-unique lines differed only in
    this, with an identical atPara on both sides. Calling that a contradiction
    would report a numbering bug that does not exist.
    """
    profile = _own_profile([], anchors=[(12, "제목")])
    spans, checks = _mapped_own(
        [_own_box("제목", (100.0, 50.0, 160.0, 70.0),
                  {"kind": "cell", "table": 0, "row": 1, "col": 0,
                   "atPara": 12})], profile)
    assert spans[0]["confidence"] == "unique"
    assert spans[0]["address"]["kind"] == "anchor"
    assert checks["agree"] == 1


def test_the_same_text_twice_stays_ambiguous_even_when_we_know_which():
    """T41 does not lapse because a second witness turned up.

    The renderer's pick is MARKED so the chooser can show it, and is still
    not applied: a numbering drift on the renderer's side would look exactly
    like this.
    """
    profile = _own_profile([(5, 0, "성명", "static"),
                            (9, 0, "성명", "static")])
    spans, checks = _mapped_own(
        [_own_box("성명", (100.0, 50.0, 160.0, 70.0),
                  {"kind": "cell", "table": 0, "row": 9, "col": 0})], profile)
    assert spans[0]["confidence"] == "ambiguous"
    assert spans[0]["address"] is None
    assert spans[0]["candidates"][spans[0]["sidecarPick"]]["row"] == 9
    assert checks["amongCandidates"] == 1


def test_a_renderer_address_the_candidate_list_lacks_is_added_not_believed():
    profile = _own_profile([(5, 0, "성명", "static"),
                            (9, 0, "성명", "static")])
    spans, checks = _mapped_own(
        [_own_box("성명", (100.0, 50.0, 160.0, 70.0),
                  {"kind": "cell", "table": 0, "row": 11, "col": 4})], profile)
    assert spans[0]["confidence"] == "ambiguous"
    assert len(spans[0]["candidates"]) == 3
    assert checks["notAmongCandidates"] == 1


def test_a_line_only_the_renderer_can_place_is_recorded_and_not_claimed():
    """The one refusal this whole cross-check exists for."""
    profile = _own_profile([(5, 0, "성명", "static")])
    spans, checks = _mapped_own(
        [_own_box("아무도 모르는 줄", (100.0, 50.0, 260.0, 70.0),
                  {"kind": "para", "atPara": 41})], profile)
    assert spans[0]["confidence"] == "unmapped"
    assert spans[0]["address"] is None
    assert spans[0]["sidecarAddress"]["atPara"] == 41
    assert spans[0]["addressBasis"] == "sidecar_only"
    assert checks["sidecarOnly"] == 1


def test_a_box_that_declares_no_address_leaves_the_scan_alone():
    profile = _own_profile([(5, 0, "성명", "static")])
    spans, checks = _mapped_own(
        [_own_box("성명", (100.0, 50.0, 160.0, 70.0))], profile)
    assert spans[0]["confidence"] == "unique"
    assert "addressBasis" not in spans[0]
    assert checks["scanOnly"] == 1 and checks["declared"] == 0


# --- seats from the boxes the renderer itself drew ----------------------------

def _cell_box(row, col, rect, table=0, page=1):
    x0, y0, x1, y1 = rect
    return {"page": page, "table": table, "row": row, "col": col,
            "rowSpan": 1, "colSpan": 1, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def test_an_empty_fill_cell_is_seated_from_the_box_we_drew_it_as():
    profile = _own_profile([(5, 0, "성명", "static"),
                            (5, 1, "", "fill_target")])
    seats, absences = rt_geometry.derive_own_seats(
        profile, [], [_cell_box(5, 0, (100.0, 50.0, 200.0, 80.0)),
                      _cell_box(5, 1, (200.0, 50.0, 400.0, 80.0))],
        600.0, 800.0)
    assert len(seats) == 1
    assert seats[0]["derivation"] == "own_cell"
    assert seats[0]["rect"] == rt_geometry._norm_rect(
        (200.0, 50.0, 400.0, 80.0), 600.0, 800.0)
    assert absences == {}
    # No grid was rebuilt and no anchor was walked to reach it — the address
    # arrived on the box.
    assert "verifiedBy" in seats[0]["basis"]


def test_a_fill_cell_this_page_did_not_draw_is_absent_with_a_reason():
    profile = _own_profile([(5, 1, "", "fill_target"),
                            (9, 1, "", "fill_target")])
    seats, absences = rt_geometry.derive_own_seats(
        profile, [], [_cell_box(5, 1, (200.0, 50.0, 400.0, 80.0))],
        600.0, 800.0)
    assert [(s["row"], s["col"]) for s in seats] == [(5, 1)]
    assert absences == {"grid_gap": 1}
    assert set(absences) <= set(rt_geometry.ABSENCE_REASONS)


def test_a_table_that_drew_nothing_here_says_so_rather_than_gap():
    profile = _own_profile([(5, 1, "", "fill_target")])
    seats, absences = rt_geometry.derive_own_seats(
        profile, [], [], 600.0, 800.0)
    assert seats == []
    assert absences == {"no_anchor_on_page": 1}


def test_a_seat_that_already_shows_text_names_the_line_showing_it():
    profile = _own_profile([(5, 1, "값", "fill_target")])
    spans = [_span_at([0.3, 0.06, 0.6, 0.1],
                      {"kind": "cell", "table": 0, "row": 5, "col": 1},
                      index=7)]
    seats, _absences = rt_geometry.derive_own_seats(
        profile, spans, [_cell_box(5, 1, (200.0, 50.0, 400.0, 80.0))],
        600.0, 800.0)
    # The rect is still the CELL, never the text extent: a seat is where a
    # value goes, not where the old value happened to end.
    assert seats[0]["derivation"] == "own_cell"
    assert seats[0]["basis"]["spanIndex"] == 7
    assert seats[0]["rect"] == rt_geometry._norm_rect(
        (200.0, 50.0, 400.0, 80.0), 600.0, 800.0)


def test_own_cell_is_a_declared_derivation_and_not_a_free_string():
    assert "own_cell" in rt_geometry.DERIVATION_METHODS
    assert "own_cell" in rt_geometry.geometry_capability()["derivationMethods"]
