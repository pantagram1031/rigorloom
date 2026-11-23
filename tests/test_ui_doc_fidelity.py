"""Verify rendered engine pages against document table borders, fills, and line geometry."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET
import zipfile

import pytest

from _runtime_client import runtime_scripts_on_path

runtime_scripts_on_path()
import rt_doc  # noqa: E402
from rt_engine import EngineTools  # noqa: E402
from rt_own import run_own_render  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "tests" / "corpus" / "forms"
FIXTURES = [
    (CORPUS / "converted" / "gianmun-byeolji-1ho.hwpx", 1),
    (REPO / "tests" / "fixtures" / "rt_doc_contract" / "basic.hwpx", 2),
]
SCALE = 3
POSITION_TOLERANCE_PT = 1.5
MIN_INK_COVERAGE = 0.70
FILL_INSET_PT = 2.0
FILL_TOLERANCE = 24.0


@dataclass(frozen=True)
class Segment:
    horizontal: bool
    axis: float
    start: float
    end: float
    category: str
    color: str | None = None
    threshold: float | None = None


@dataclass(frozen=True)
class CellSpec:
    table: str
    row: int
    col: int
    row_span: int
    col_span: int
    table_rows: int
    table_cols: int
    width_pt: float
    height_pt: float
    edges: dict[str, tuple[str, str]]
    fill_color: str | None


def color_luminance(hex_color: str) -> float:
    """ITU-R BT.601 luminance (0.299R + 0.587G + 0.114B) for a hex colour."""
    cleaned = hex_color.strip().lstrip("#")
    if len(cleaned) == 8:
        cleaned = cleaned[-6:]
    r, g, b = int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def ink_threshold(hex_color: str) -> float:
    """Midpoint between the stroke colour's luminance and white (255)."""
    return (color_luminance(hex_color) + 255.0) / 2.0


def _xml_root_and_ns(raw: bytes) -> tuple[ET.Element, dict[str, str]]:
    ns: dict[str, str] = {}
    root: ET.Element | None = None
    for event, item in ET.iterparse(io.BytesIO(raw), events=("start-ns", "start")):
        if event == "start-ns":
            prefix, uri = item
            ns.setdefault(prefix, uri)
        elif root is None:
            root = item
    assert root is not None, "empty XML document"
    return root, ns


def hwpx_cell_specs(source: Path) -> dict[str, CellSpec]:
    """Read Contents/header.xml and Contents/section*.xml to map cell addresses to borderFill specs."""
    with zipfile.ZipFile(source) as zf:
        hdr_root, hdr_ns = _xml_root_and_ns(zf.read("Contents/header.xml"))
        hh = f"{{{hdr_ns['hh']}}}"
        hc = f"{{{hdr_ns['hc']}}}" if "hc" in hdr_ns else None
        border_fills: dict[str, tuple[dict[str, tuple[str, str]], str | None]] = {}
        for bf in hdr_root.findall(f".//{hh}borderFill"):
            bf_id = bf.attrib["id"]
            edges: dict[str, tuple[str, str]] = {}
            for side, tag in (
                ("left", "leftBorder"),
                ("right", "rightBorder"),
                ("top", "topBorder"),
                ("bottom", "bottomBorder"),
            ):
                el = bf.find(f"{hh}{tag}")
                btype = el.attrib.get("type", "NONE") if el is not None else "NONE"
                color = el.attrib.get("color", "#000000") if el is not None else "#000000"
                edges[side] = (btype, color)
            fill_color: str | None = None
            if hc is not None:
                wb = bf.find(f".//{hc}winBrush")
                if wb is not None:
                    face = wb.attrib.get("faceColor")
                    if face and face.lower() != "none":
                        fill_color = face
            border_fills[bf_id] = (edges, fill_color)

        section_names = sorted(
            (n for n in zf.namelist() if n.startswith("Contents/section") and n.endswith(".xml")),
            key=lambda n: int(n[len("Contents/section") : -len(".xml")]),
        )
        specs: dict[str, CellSpec] = {}
        top_table_idx = 0

        for sname in section_names:
            sec_root, sec_ns = _xml_root_and_ns(zf.read(sname))
            hp = f"{{{sec_ns['hp']}}}"

            def iter_container_tables(container: ET.Element):
                for child in container:
                    if child.tag == f"{hp}tbl":
                        yield child
                    elif child.tag != f"{hp}tc":
                        yield from iter_container_tables(child)

            def walk_container(container: ET.Element, prefix: str) -> None:
                nonlocal top_table_idx
                nested_idx = 0
                for tbl in iter_container_tables(container):
                    if prefix == "":
                        t_addr = f"t{top_table_idx}"
                        top_table_idx += 1
                    else:
                        t_addr = f"{prefix}/t{nested_idx}"
                        nested_idx += 1
                    spacing = int(tbl.attrib.get("cellSpacing", "0") or 0)
                    assert spacing == 0, (
                        f"{source.name}: table {t_addr} has cellSpacing={spacing} > 0; "
                        "table-level borders are not modelled yet"
                    )
                    row_cnt = int(tbl.attrib.get("rowCnt", "0") or 0)
                    col_cnt = int(tbl.attrib.get("colCnt", "0") or 0)
                    for tr in tbl.findall(f"{hp}tr"):
                        for tc in tr.findall(f"{hp}tc"):
                            ca = tc.find(f"{hp}cellAddr")
                            assert ca is not None, f"{source.name}: table {t_addr} has hp:tc without hp:cellAddr"
                            cs = tc.find(f"{hp}cellSpan")
                            sz = tc.find(f"{hp}cellSz")
                            assert sz is not None, f"{source.name}: table {t_addr} has hp:tc without hp:cellSz"
                            row = int(ca.attrib["rowAddr"])
                            col = int(ca.attrib["colAddr"])
                            row_span = int(cs.attrib.get("rowSpan", "1")) if cs is not None else 1
                            col_span = int(cs.attrib.get("colSpan", "1")) if cs is not None else 1
                            width_pt = int(sz.attrib["width"]) / 100.0
                            height_pt = int(sz.attrib["height"]) / 100.0
                            bf_ref = tc.attrib.get("borderFillIDRef", "")
                            assert bf_ref in border_fills, (
                                f"{source.name}: cell {t_addr}/r{row}/c{col} references unknown borderFillIDRef={bf_ref!r}"
                            )
                            edges, fill_color = border_fills[bf_ref]
                            c_addr = f"{t_addr}/r{row}/c{col}"
                            specs[c_addr] = CellSpec(
                                table=t_addr,
                                row=row,
                                col=col,
                                row_span=row_span,
                                col_span=col_span,
                                table_rows=row_cnt,
                                table_cols=col_cnt,
                                width_pt=width_pt,
                                height_pt=height_pt,
                                edges=edges,
                                fill_color=fill_color,
                            )
                            sub = tc.find(f"{hp}subList")
                            if sub is not None:
                                walk_container(sub, c_addr)

            walk_container(sec_root, "")
    return specs


def table_segments(cells, cell_specs: dict[str, CellSpec], source_name: str):
    """Split shared edges at cell boundaries, classify expected vs suppressed from HWPX borderFill."""
    tables = defaultdict(list)
    for box in cells:
        at = box["at"]
        assert at in cell_specs, f"{source_name}: geometry cell {at!r} cannot be mapped to any HWPX hp:tc"
        spec = cell_specs[at]
        table, _, _ = at.rsplit("/", 2)
        assert table == spec.table, f"{source_name}: table address mismatch for {at}: {table} != {spec.table}"
        x, y, w, h = box["rect"]
        assert 0 <= spec.row and spec.row + spec.row_span <= spec.table_rows, (
            f"{source_name}: cell {at} row span ({spec.row}+{spec.row_span}) exceeds table rowCnt {spec.table_rows}"
        )
        assert 0 <= spec.col and spec.col + spec.col_span <= spec.table_cols, (
            f"{source_name}: cell {at} col span ({spec.col}+{spec.col_span}) exceeds table colCnt {spec.table_cols}"
        )
        assert abs(w - spec.width_pt) <= 1.0 and h + 1.0 >= spec.height_pt, (
            f"{source_name}: cell {at} geometry rect {box['rect']} disagrees with XML cellSz "
            f"({spec.width_pt:.2f} x {spec.height_pt:.2f} pt)"
        )
        if w > 0 and h > 0:
            rect = tuple(round(v, 1) for v in (x, y, x + w, y + h))
            tables[table].append((rect, spec, at))

    for items in tables.values():
        for (ax0, ay0, ax1, ay1), aspec, a_at in items:
            for (bx0, by0, bx1, by1), bspec, b_at in items:
                if (
                    aspec.col + aspec.col_span == bspec.col
                    and aspec.row < bspec.row + bspec.row_span
                    and bspec.row < aspec.row + aspec.row_span
                ):
                    assert abs(ax1 - bx0) <= 0.2, (
                        f"{source_name}: adjacent cells {a_at} and {b_at} disagree on x boundary ({ax1} vs {bx0})"
                    )
                if (
                    aspec.row + aspec.row_span == bspec.row
                    and aspec.col < bspec.col + bspec.col_span
                    and bspec.col < aspec.col + aspec.col_span
                ):
                    assert abs(ay1 - by0) <= 0.2, (
                        f"{source_name}: adjacent cells {a_at} and {b_at} disagree on y boundary ({ay1} vs {by0})"
                    )

        rectangles = [r for r, _, _ in items]
        left = min(r[0] for r in rectangles)
        top = min(r[1] for r in rectangles)
        right = max(r[2] for r in rectangles)
        bottom = max(r[3] for r in rectangles)
        edges = defaultdict(set)
        edge_specs = defaultdict(list)
        for (x0, y0, x1, y1), spec, _ in items:
            for key, interval, side in (
                ((True, y0), (x0, x1), "top"),
                ((True, y1), (x0, x1), "bottom"),
                ((False, x0), (y0, y1), "left"),
                ((False, x1), (y0, y1), "right"),
            ):
                edges[key].add(interval)
                edge_specs[key].append((interval, spec.edges[side]))

        for (horizontal, axis), intervals in edges.items():
            limits = sorted({value for interval in intervals for value in interval})
            boundary = (top, bottom) if horizontal else (left, right)
            category = "border" if axis in boundary else "rule"
            for start, end in zip(limits, limits[1:]):
                if end - start >= 3 and any(a <= start and end <= b for a, b in intervals):
                    touching = [
                        edge_spec
                        for (a, b), edge_spec in edge_specs[(horizontal, axis)]
                        if a <= start and end <= b
                    ]
                    visible = [color for btype, color in touching if btype != "NONE"]
                    if visible:
                        chosen_color = min(visible, key=color_luminance)
                        yield Segment(
                            horizontal,
                            axis,
                            start,
                            end,
                            category,
                            color=chosen_color,
                            threshold=ink_threshold(chosen_color),
                        )
                    else:
                        yield Segment(horizontal, axis, start, end, category, color=None, threshold=None)


def ink_covers(gray, segment: Segment) -> bool:
    """Look for a sustained stroke darker than the colour-relative threshold inside a tolerance band."""
    assert segment.threshold is not None
    threshold = segment.threshold
    axis = round(segment.axis * SCALE)
    tolerance = math.ceil(POSITION_TOLERANCE_PT * SCALE)
    length = segment.end - segment.start
    start = round((segment.start + length * 0.05) * SCALE)
    end = round((segment.end - length * 0.05) * SCALE)
    width, height = gray.size if segment.horizontal else gray.size[::-1]
    along = range(max(0, start), min(width, end))
    if not along:
        return False
    pixel = gray.load()
    for p in range(max(0, axis - tolerance), min(height, axis + tolerance + 1)):
        ink = sum(pixel[a, p] < threshold if segment.horizontal else pixel[p, a] < threshold for a in along)
        if ink / len(along) >= MIN_INK_COVERAGE:
            return True
    return False


def fill_covers(gray, rect: list[float], hex_color: str) -> bool:
    """Sample cell interior inset by 2 pt at scale 3 and check median gray within 24 of fill luminance."""
    x, y, w, h = rect
    x0 = max(0, round((x + FILL_INSET_PT) * SCALE))
    y0 = max(0, round((y + FILL_INSET_PT) * SCALE))
    x1 = min(gray.width, round((x + w - FILL_INSET_PT) * SCALE))
    y1 = min(gray.height, round((y + h - FILL_INSET_PT) * SCALE))
    if x1 <= x0 or y1 <= y0:
        return False
    pixel = gray.load()
    samples = [pixel[ix, iy] for iy in range(y0, y1) for ix in range(x0, x1)]
    return abs(statistics.median(samples) - color_luminance(hex_color)) <= FILL_TOLERANCE


def projection_placements(source, tmp_path):
    """Use the built-in renderer's cell placements if the engine omitted geometry."""
    result = run_own_render(EngineTools(REPO), source, tmp_path, dpi=144)
    assert result["exitCode"] == 0, result["stderr"]
    report = json.loads((tmp_path / "own.render.json").read_text(encoding="utf-8"))
    pages = defaultdict(list)
    for box in report["cell_boxes"]:
        x, y, right, bottom = (box[key] / 2 for key in ("x0", "y0", "x1", "y1"))
        pages[box["page"]].append({"at": f"t{box['table']}/r{box['row']}/c{box['col']}",
                                   "rect": [x, y, right - x, bottom - y]})
    lines = Counter((box["page"], box["address"]["atPara"]) for box in report["line_boxes"]
                    if "atPara" in box.get("address", {}))
    return pages, lines


@pytest.mark.skipif(not os.environ.get("RIGORLOOM_HWP_ENGINE"), reason="RIGORLOOM_HWP_ENGINE is unset")
@pytest.mark.parametrize("source, expected_pages", FIXTURES, ids=["gongmun", "basic"])
def test_engine_page_fidelity(source, expected_pages, tmp_path):
    from PIL import Image

    if source.is_relative_to(CORPUS):
        manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
        pinned = [entry for entries in manifest.values() if isinstance(entries, list) for entry in entries
                  if entry.get("path") == source.relative_to(CORPUS).as_posix()]
        assert len(pinned) == 1 and sha256(source.read_bytes()).hexdigest() == pinned[0]["sha256"]

    cell_specs = hwpx_cell_specs(source)
    listed = rt_doc.pages(source)
    assert listed["ok"], listed.get("error")
    rendered = rt_doc.render(source, "all", scale=SCALE, out_dir=tmp_path)
    assert rendered["ok"], rendered.get("error")
    gaps = []
    if listed["count"] != expected_pages or len(rendered["pages"]) != expected_pages:
        gaps.append(f"page count {listed['count']} listed, {len(rendered['pages'])} drawn, {expected_pages} expected")

    report = {"document": source.name, "listed_pages": listed["count"], "expected_pages": expected_pages,
              "raster_pages": len(rendered["pages"]), "pages": [], "line_breaks_by_paragraph": {},
              "position_tolerance_pt": POSITION_TOLERANCE_PT, "min_ink_coverage": MIN_INK_COVERAGE,
              "ink_thresholds_by_color": {}}
    all_lines = defaultdict(set)
    projection = None
    totals = Counter()
    thresholds_by_color: dict[str, float] = {}
    for page in rendered["pages"]:
        n = page["n"]
        geometry = rt_doc.geometry(source, n)
        if geometry["ok"]:
            placement_source = "engine geometry"
            cells = [box for box in geometry["boxes"] if box["kind"] == "cell" and box["at"]]
            lines = defaultdict(set)
            for box in geometry["boxes"]:
                if box["kind"] == "line" and box["at"] and "#L" in box["at"]:
                    at, index = box["at"].rsplit("#L", 1)
                    if at:
                        lines[at].add(index)
                        all_lines[at].add(index)
            breaks = {at: max(0, len(ids) - 1) for at, ids in sorted(lines.items())}
        else:
            placement_source = "built-in renderer geometry"
            if projection is None:
                projection = projection_placements(source, tmp_path)
            projected_cells, projected_lines = projection
            cells, breaks = projected_cells[n], None
            error = geometry["error"]
            gaps.append(f"page {n} line breaks unavailable ({error['code']}: {error['message']})")
        segments = list(table_segments(cells, cell_specs, source.name))
        for seg in segments:
            if seg.color is not None and seg.threshold is not None:
                thresholds_by_color[seg.color] = round(seg.threshold, 2)
        filled_cells = [
            (box, cell_specs[box["at"]].fill_color)
            for box in cells
            if cell_specs[box["at"]].fill_color is not None
        ]
        with Image.open(page["file"]) as png:
            gray = png.convert("L")
            counts = {}
            for category in ("border", "rule"):
                cat_segments = [seg for seg in segments if seg.category == category]
                expected = [seg for seg in cat_segments if seg.threshold is not None]
                suppressed = [seg for seg in cat_segments if seg.threshold is None]
                drawn = sum(ink_covers(gray, seg) for seg in expected)
                counts[category] = {"drawn": drawn, "expected": len(expected), "suppressed": len(suppressed)}
                totals[f"{category}_drawn"] += drawn
                totals[f"{category}_expected"] += len(expected)
                totals[f"{category}_suppressed"] += len(suppressed)
                totals["suppressed"] += len(suppressed)
            fill_drawn = sum(fill_covers(gray, box["rect"], color) for box, color in filled_cells if color is not None)
            counts["fill"] = {"drawn": fill_drawn, "expected": len(filled_cells)}
            totals["fill_drawn"] += fill_drawn
            totals["fill_expected"] += len(filled_cells)
        report["pages"].append({"page": n, "placement_source": placement_source,
                                "line_breaks_by_paragraph": breaks, "table_segments": counts})
        if breaks is None:
            report["pages"][-1]["projection_line_breaks_by_paragraph"] = {
                f"p{para}": count - 1 for (page, para), count in sorted(projected_lines.items()) if page == n
            }
    report["line_breaks_by_paragraph"] = {at: len(ids) - 1 for at, ids in sorted(all_lines.items())} or None
    report["ink_thresholds_by_color"] = dict(sorted(thresholds_by_color.items()))
    report["table_segments"] = dict(totals)
    for category in ("border", "rule"):
        expected, drawn = totals[f"{category}_expected"], totals[f"{category}_drawn"]
        assert expected > 0, f"{source.name}: no {category} segments were checked"
        if drawn < expected:
            gaps.append(f"table {category} segments {drawn}/{expected} drawn")
    if totals["fill_expected"] > 0 and totals["fill_drawn"] < totals["fill_expected"]:
        gaps.append(f"table fill cells {totals['fill_drawn']}/{totals['fill_expected']} drawn")
    report["gaps"] = gaps
    (tmp_path / "fidelity.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{source.name}: pages {report['raster_pages']}/{expected_pages}, "
          f"paragraphs with line geometry {len(all_lines)}, "
          f"line breaks {sum(len(ids) - 1 for ids in all_lines.values()) if all_lines else 'unavailable'}, "
          f"borders {totals['border_drawn']}/{totals['border_expected']}, "
          f"rules {totals['rule_drawn']}/{totals['rule_expected']}, "
          f"fill {totals['fill_drawn']}/{totals['fill_expected']}, "
          f"suppressed {totals['suppressed']}")

    assert not gaps, f"{source.name}: " + "; ".join(gaps)
