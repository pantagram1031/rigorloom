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
