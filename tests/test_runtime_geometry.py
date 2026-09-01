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
        "grid_gap", "cell_mismatch", "alignment_failed",
        "lattice_inconsistent"}


# --- the walk is 2D: a label above a column is a label ------------------------
# The shipped walk read one row band, so it reached the seats BESIDE a label
# and nothing else. Measured on the corpus, 252 fill regions sat in tables that
# WERE anchored on the page and still got no box, because their own row held no
# label of its own. These pin the vertical half and the gates that pay for it.
# Mechanics only: whether this reconstructs a REAL form is settled against the
# corpus renders further down.


def _column_profile(rows, table=0):
    """rows: {row: [(col, text, classification, rowspan)]} -> a form scan."""
    cells = []
    for row, entries in rows.items():
        for col, text, classification, rowspan in entries:
            cells.append({"addr": {"row": row, "col": col},
                          "span": {"row": rowspan, "col": 1},
                          "text_preview": text,
                          "classification": classification})
    return {"anchor_records": [], "table_map": [{"index": table,
                                                 "cells": cells}]}


def _stacked_cells(rows, cols, *, left=100.0, top=100.0, w=90.0, h=30.0):
    """A drawn grid of ``rows`` x ``cols`` boxes, edge to edge."""
    return [(left + c * w, top + r * h, left + (c + 1) * w, top + (r + 1) * h)
            for r in range(rows) for c in range(cols)]


def test_a_header_label_seats_the_cell_under_it():
    """The label is in row 0; the empty seat is in row 1, under it.

    Nothing in row 1 is matched or matchable. It gets a box because the page
    draws one directly below the box whose label the render confirmed.
    """
    cells = _stacked_cells(2, 2)
    profile = _column_profile({0: [(0, "성명", "static", 1),
                                   (1, "생년월일", "static", 1)],
                               1: [(0, "", "fill_target", 1),
                                   (1, "", "fill_target", 1)]})
    spans = [_span_at([0.21, 0.21, 0.3, 0.25],
                      {"kind": "cell", "table": 0, "row": 0, "col": 0})]
    lines = [_line_at("성명", (110.0, 105.0, 160.0, 120.0)),
             _line_at("생년월일", (200.0, 105.0, 250.0, 120.0))]
    placed, absences = rt_geometry.align_drawn_grid(
        profile, spans, cells, lines, 500.0, 500.0, _norm())
    assert placed[(0, 1, 0)] == (100.0, 130.0, 190.0, 160.0)
    assert placed[(0, 1, 1)] == (190.0, 130.0, 280.0, 160.0)
    assert absences == {}


def test_the_vertical_walk_stops_where_the_page_contradicts_the_scan():
    """A box below holding the wrong text ends that direction, as sideways."""
    cells = _stacked_cells(3, 1)
    profile = _column_profile({0: [(0, "성명", "static", 1)],
                               1: [(0, "", "fill_target", 1)],
                               2: [(0, "", "fill_target", 1)]})
    spans = [_span_at([0.21, 0.21, 0.3, 0.25],
                      {"kind": "cell", "table": 0, "row": 0, "col": 0})]
    lines = [_line_at("성명", (110.0, 105.0, 160.0, 120.0)),
             # the box below the first seat is not empty, so it is not a seat
             _line_at("이미 찬 값", (110.0, 135.0, 160.0, 150.0))]
    placed, absences = rt_geometry.align_drawn_grid(
        profile, spans, cells, lines, 500.0, 500.0, _norm())
    assert placed == {}
    assert absences["cell_mismatch"] == 1
    assert absences["no_anchor_in_row"] == 2, "nothing past the lie either"


def test_a_vertical_neighbour_comes_from_the_declared_rowspan():
    """A label spanning three rows sits above the row at ``row + rowspan``,
    not above ``row + 1``. The table says so; nothing is inferred."""
    profile = _column_profile({0: [(0, "구분", "static", 3)],
                               3: [(0, "", "fill_target", 1)]})
    _by_addr, neighbours = rt_geometry.declared_lattice(
        profile["table_map"][0])
    assert neighbours[(0, 0)]["down"] == (3, 0)
    assert neighbours[(3, 0)]["up"] == (0, 0)
    assert "down" not in neighbours[(3, 0)]


def test_a_wide_cell_steps_down_to_the_box_that_starts_where_it_does():
    """A label spanning two columns above a pair of narrow ones.

    The declared cell below ``(row, col)`` is the one at the SAME starting
    column, which on the page is the left-hand box. Nothing is chosen here:
    the right-hand box does not start where the wide one starts, so it is not
    a candidate at all.
    """
    wide = (100.0, 100.0, 280.0, 130.0)
    below_left = (100.0, 130.0, 190.0, 160.0)
    below_right = (190.0, 130.0, 280.0, 160.0)
    adjacency = rt_geometry.drawn_adjacency([wide, below_left, below_right])
    assert adjacency[wide]["down"] == below_left
    assert adjacency[below_left]["right"] == below_right
    assert adjacency[below_left]["up"] == wide
    assert "up" not in adjacency[below_right], "nothing starts where it does"


def test_two_candidates_below_are_no_candidate():
    """Where the direction forks, the walk has no step and does not take one.

    A fork is exactly where a walk would drift, so ``drawn_adjacency`` answers
    with nothing rather than with the first one.
    """
    here = (100.0, 100.0, 190.0, 130.0)
    one = (100.0, 130.0, 190.0, 160.0)
    two = (100.0, 131.0, 160.0, 158.0)
    adjacency = rt_geometry.drawn_adjacency([here, one, two])
    assert "down" not in adjacency[here]


def test_a_vertical_step_does_not_require_the_width_to_match():
    """A label spanning two columns above one narrow cell is still above it:
    a vertical step shares the LEFT edge, because colspan changes per row."""
    wide = (100.0, 100.0, 280.0, 130.0)
    narrow = (100.0, 130.0, 190.0, 160.0)
    adjacency = rt_geometry.drawn_adjacency([wide, narrow])
    assert adjacency[wide]["down"] == narrow
    assert adjacency[narrow]["up"] == wide


def test_a_horizontal_step_does_require_the_whole_row_band():
    """Sideways stays inside one declared row, so the band has to match."""
    here = (100.0, 100.0, 190.0, 130.0)
    taller = (190.0, 100.0, 280.0, 175.0)
    adjacency = rt_geometry.drawn_adjacency([here, taller])
    assert "right" not in adjacency[here]


def test_a_correspondence_that_claims_one_box_twice_is_not_consistent():
    """Two declared cells, one drawn box: a walk that slipped a row."""
    box = (100.0, 100.0, 190.0, 130.0)
    assert not rt_geometry.lattice_is_consistent({(5, 0): box, (7, 0): box})


def test_a_correspondence_out_of_order_is_not_consistent():
    """Declared col 0 must not take a box to the RIGHT of declared col 1."""
    left = (100.0, 100.0, 190.0, 130.0)
    right = (190.0, 100.0, 280.0, 130.0)
    lower = (100.0, 130.0, 190.0, 160.0)
    assert rt_geometry.lattice_is_consistent({(5, 0): left, (5, 1): right})
    assert not rt_geometry.lattice_is_consistent({(5, 0): right, (5, 1): left})
    assert rt_geometry.lattice_is_consistent({(0, 3): left, (2, 3): lower})
    assert not rt_geometry.lattice_is_consistent({(2, 3): left, (0, 3): lower})


def test_a_drifted_table_is_refused_whole_not_seat_by_seat():
    """Two anchors, one drawn box between them: the shallow grid cannot be the
    declared table, so nothing from it is placed here.

    A run of empty cells agrees with anything -- the text gate is silent
    there -- so reach is paid for with a structural check on the whole table.
    """
    left = (100.0, 100.0, 190.0, 130.0)
    right = (190.0, 100.0, 280.0, 130.0)
    profile = _column_profile({5: [(0, "", "fill_target", 1),
                                   (1, "성명", "static", 1)],
                               7: [(0, "", "fill_target", 1),
                                   (1, "성명", "static", 1)]})
    spans = [_span_at([0.41, 0.21, 0.45, 0.25],
                      {"kind": "cell", "table": 0, "row": 5, "col": 1}),
             _span_at([0.46, 0.21, 0.5, 0.25],
                      {"kind": "cell", "table": 0, "row": 7, "col": 1},
                      index=1)]
    lines = [_line_at("성명", (200.0, 105.0, 250.0, 120.0))]
    placed, absences = rt_geometry.align_drawn_grid(
        profile, spans, [left, right], lines, 500.0, 500.0, _norm())
    assert placed == {}
    assert absences == {"lattice_inconsistent": 2}


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
    "admrul-gajokdolbom-hyuga-sinchengseo": (7, 6),
    "gianmun-byeolji-1ho": (9, 0),
    "gianmun-byeolji-2ho": (35, 13),
    "jeongbo-gonggae-cheongguseo": (13, 0),
    "jumin-deungchobon-sinchengseo": (5, 1),
    "kstartup-jiwon-sincheongseo-saeopgyehoekseo": (125, 123),
    "moel-pyojun-geunrogyeyakseo-2013": (3, 0),
    "moel-pyojun-geunrogyeyakseo-2025": (0, 0),
    "nrf-gyeolgwa-bogoseo-yangsik": (5, 5),
    "saeopja-deungnok-sinchengseo": (271, 81),
}
CORPUS_FILL_TOTAL = 473
CORPUS_SEAT_TOTAL = 229
#: Every corpus seat is reached by the drawn grid. ``matched_text`` needs the
#: seat to already hold text (an empty fill cell never does) and
#: ``interpolated`` needs a mapped label in the same row with the seat right
#: next to it, which no corpus row provides. Asserted so a seat quietly
#: arriving by a weaker route shows up as a failure.
CORPUS_SEATS_BY_DERIVATION = {"cell_borders": 229, "matched_text": 0,
                              "interpolated": 0}

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
    """0 of 473 was the measurement that opened this work. This is where it
    stands now, and it is asserted exactly so it cannot quietly drift."""
    total_fill = sum(fill for fill, _ in CORPUS_SEATS.values())
    total_seats = sum(seats for _, seats in CORPUS_SEATS.values())
    assert total_fill == CORPUS_FILL_TOTAL
    assert total_seats == CORPUS_SEAT_TOTAL


@needs_rasterizer
@needs_corpus_renders
def test_the_corpus_headline_by_derivation_class(tmp_path):
    """Which derivation earned each seat, counted across the whole corpus.

    A total alone would hide a seat that arrived by a weaker route than the
    one it is credited to, so the split is asserted exactly too.
    """
    counted = {method: 0 for method in rt_geometry.DERIVATION_METHODS}
    for slug in sorted(CORPUS_SEATS):
        placed, _ = _seats_for_form(slug, _profile_of(slug, tmp_path))
        for seat in placed.values():
            counted[seat["derivation"]] += 1
    assert counted == CORPUS_SEATS_BY_DERIVATION
    assert sum(counted.values()) == CORPUS_SEAT_TOTAL


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
