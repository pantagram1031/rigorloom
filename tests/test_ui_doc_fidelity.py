"""Measure opt-in engine pages using the pinned forms and synthetic fixtures."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path

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


@dataclass(frozen=True)
class Segment:
    horizontal: bool
    axis: float
    start: float
    end: float
    category: str


def table_segments(cells):
    """Split shared edges at cell boundaries and count each interval once."""
    tables = defaultdict(list)
    for box in cells:
        table, _, _ = box["at"].rsplit("/", 2)
        x, y, w, h = box["rect"]
        if w > 0 and h > 0:
            tables[table].append(tuple(round(v, 1) for v in (x, y, x + w, y + h)))

    for rectangles in tables.values():
        left = min(r[0] for r in rectangles)
        top = min(r[1] for r in rectangles)
        right = max(r[2] for r in rectangles)
        bottom = max(r[3] for r in rectangles)
        edges = defaultdict(set)
        for x0, y0, x1, y1 in rectangles:
            for key, interval in (
                ((True, y0), (x0, x1)), ((True, y1), (x0, x1)),
                ((False, x0), (y0, y1)), ((False, x1), (y0, y1)),
            ):
                edges[key].add(interval)

        for (horizontal, axis), intervals in edges.items():
            limits = sorted({value for interval in intervals for value in interval})
            boundary = (top, bottom) if horizontal else (left, right)
            category = "border" if axis in boundary else "rule"
            for start, end in zip(limits, limits[1:]):
                if end - start >= 3 and any(a <= start and end <= b for a, b in intervals):
                    yield Segment(horizontal, axis, start, end, category)


def ink_covers(gray, segment):
    """Look for a sustained dark stroke inside a perpendicular tolerance band."""
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
        ink = sum(pixel[a, p] < 128 if segment.horizontal else pixel[p, a] < 128 for a in along)
        if ink / len(along) >= MIN_INK_COVERAGE:
            return True
    return False


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

    listed = rt_doc.pages(source)
    assert listed["ok"], listed.get("error")
    rendered = rt_doc.render(source, "all", scale=SCALE, out_dir=tmp_path)
    assert rendered["ok"], rendered.get("error")
    gaps = []
    if listed["count"] != expected_pages or len(rendered["pages"]) != expected_pages:
        gaps.append(f"page count {listed['count']} listed, {len(rendered['pages'])} drawn, {expected_pages} expected")

    report = {"document": source.name, "listed_pages": listed["count"], "expected_pages": expected_pages,
              "raster_pages": len(rendered["pages"]), "pages": [], "line_breaks_by_paragraph": {},
              "position_tolerance_pt": POSITION_TOLERANCE_PT, "min_ink_coverage": MIN_INK_COVERAGE}
    all_lines = defaultdict(set)
    projection = None
    totals = Counter()
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
        segments = list(table_segments(cells))
        with Image.open(page["file"]) as png:
            gray = png.convert("L")
            counts = {}
            for category in ("border", "rule"):
                expected = [seg for seg in segments if seg.category == category]
                drawn = sum(ink_covers(gray, seg) for seg in expected)
                counts[category] = {"drawn": drawn, "expected": len(expected)}
                totals[f"{category}_drawn"] += drawn
                totals[f"{category}_expected"] += len(expected)
        report["pages"].append({"page": n, "placement_source": placement_source,
                                "line_breaks_by_paragraph": breaks, "table_segments": counts})
        if breaks is None:
            report["pages"][-1]["projection_line_breaks_by_paragraph"] = {
                f"p{para}": count - 1 for (page, para), count in sorted(projected_lines.items()) if page == n
            }
    report["line_breaks_by_paragraph"] = {at: len(ids) - 1 for at, ids in sorted(all_lines.items())} or None
    report["table_segments"] = dict(totals)
    for category in ("border", "rule"):
        expected, drawn = totals[f"{category}_expected"], totals[f"{category}_drawn"]
        assert expected > 0, f"{source.name}: no {category} segments were checked"
        if drawn < expected:
            gaps.append(f"table {category} segments {drawn}/{expected} drawn")
    report["gaps"] = gaps
    (tmp_path / "fidelity.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{source.name}: pages {report['raster_pages']}/{expected_pages}, "
          f"paragraphs with line geometry {len(all_lines)}, "
          f"line breaks {sum(len(ids) - 1 for ids in all_lines.values()) if all_lines else 'unavailable'}, "
          f"borders {totals['border_drawn']}/{totals['border_expected']}, "
          f"rules {totals['rule_drawn']}/{totals['rule_expected']}")

    if gaps:
        pytest.xfail(f"{source.name}: " + "; ".join(gaps))
