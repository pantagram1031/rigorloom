import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createEnginePageSource,
  ENGINE_PX_PER_PT,
  engineLineFontSizePx,
  pageRasterScale,
} from "../src/model/enginePage.ts";

const size = { widthPt: 600, heightPt: 800, marginPt: { top: 0, right: 0, bottom: 0, left: 0 } };
const seat = { key: "c:0:2:1", address: "t0/r2/c1", page: 1 };
const mark = { itemId: "change", address: "t0/r2/c1" };
const projection = {
  size: () => size,
  boxes: () => [],
  seats: () => [seat],
  layer: (page, view) => ({ kind: "projection", page, view, sizePt: size, marks: [mark], boxes: [] }),
};

test("raster layers keep the measured page, seats and changes", () => {
  const source = createEnginePageSource({
    projection,
    raster: { page: 1, rev: "head", source: "engine", url: "blob:page", widthPt: 595, heightPt: 841 },
    count: 3,
    geometry: {
      boxes: [{ at: "t0/r2/c1", kind: "cell", rect: [30, 40, 50, 60] }],
    },
    changes: [{ id: "change", cellKey: seat.key }],
  });
  assert.equal(source.kind, "engine");
  assert.equal(source.pageCount(), 3);
  assert.equal(source.layer(1, "marks").rasterUrl, "blob:page");
  assert.equal(source.layer(1, "clean").marks.length, 0);
  assert.equal(source.layer(2, "base").rasterUrl, undefined);
  assert.equal(source.size(1).widthPt, 595);
  const rect = { x: 30, y: 40, w: 50, h: 60 };
  assert.deepEqual(source.seats(), [{ ...seat, rect }]);
  assert.deepEqual(source.changedRects("change"), [{ page: 1, rect }]);
});

test("local hit testing uses code point offsets across lines and vertical cells", () => {
  const source = createEnginePageSource({
    projection,
    raster: { page: 1, rev: "head", source: "engine", url: "blob:page", widthPt: 600, heightPt: 800 },
    count: 1,
    changes: [],
    geometry: { boxes: [
      { at: "p0#L0", kind: "line", rect: [10, 10, 30, 10], text: "한𐐀", xs: [10, 20, 40] },
      { at: "p0#L1", kind: "line", rect: [10, 20, 10, 10], text: "글", xs: [10, 20] },
      { at: "t0/r2/c1", kind: "cell", rect: [50, 0, 40, 80] },
      { at: "t0/r2/c1/p0#L0", kind: "line", rect: [60, 10, 10, 20], text: "가나",
        vertical: true, ys: [10, 20, 30] },
    ] },
  });
  assert.equal(source.hitTest(1, 18, 25).caretOffset, 3);
  assert.deepEqual(source.caretRect(1, "p0", 2), { x: 10, y: 20, w: 1, h: 10 });
  const vertical = source.hitTest(1, 64, 19);
  assert.equal(vertical.seatKey, seat.key);
  assert.equal(vertical.address, "t0/r2/c1/p0");
  assert.deepEqual(source.caretRect(1, vertical.address, vertical.caretOffset), { x: 60, y: 20, w: 10, h: 1 });
});

test("a table's control-glyph line is not a caret target", () => {
  const source = createEnginePageSource({
    projection,
    raster: { page: 1, rev: "head", source: "engine", url: "blob:page", widthPt: 600, heightPt: 800 },
    count: 1,
    changes: [],
    geometry: { boxes: [
      // The paragraph that anchors the table: one glyph whose box spans the table.
      { at: "p0#L0", kind: "line", rect: [50, 0, 400, 700], text: "\u25a3", xs: [50, 450] },
      { at: "t0/r0/c0", kind: "cell", rect: [50, 0, 400, 30] },
      { at: "t0/r0/c0/p0#L0", kind: "line", rect: [52, 2, 100, 10], text: "머리", xs: [52, 60, 68] },
    ] },
  });
  // Inside the cell, below its text: no line, so no caret at the table's left edge.
  const below = source.hitTest(1, 100, 20);
  assert.equal(below.lineAddress, undefined);
  assert.equal(below.caretOffset, undefined);
  // On the cell's text the cell line still wins.
  const onText = source.hitTest(1, 61, 6);
  assert.equal(onText.lineAddress, "t0/r0/c0/p0#L0");
  assert.equal(onText.caretOffset, 1);
  // Offsets of the anchoring paragraph still count the glyph.
  assert.deepEqual(source.caretRect(1, "p0#L0", 0), { x: 50, y: 0, w: 1, h: 700 });
});

test("page scale follows zoom and device pixel ratio up to the cap", () => {
  assert.equal(pageRasterScale(0.75, 2), 1.5);
  assert.equal(pageRasterScale(2, 3), 3);
});

test("engineLineFontSizePx converts known pt character size to px and falls back to clamped line box size when unknown", () => {
  const headerLine = { at: "t0/r0/c0/p0#L0", kind: "line", rect: [60, 60, 390, 15] };
  const verticalLine = { at: "t0/r5/c1/p0#L0", kind: "line", rect: [60, 110, 20, 35], vertical: true };
  const tinyLine = { at: "t0/r3/c0/p0#L0", kind: "line", rect: [60, 536, 440, 4] };

  assert.equal(engineLineFontSizePx(headerLine, 9), 9 * ENGINE_PX_PER_PT);
  assert.equal(engineLineFontSizePx(headerLine, 10), 10 * ENGINE_PX_PER_PT);
  assert.equal(engineLineFontSizePx(verticalLine, 10), 10 * ENGINE_PX_PER_PT);

  for (const unknown of [undefined, null, 0, -5, Number.NaN]) {
    assert.equal(engineLineFontSizePx(headerLine, unknown), 18);
    assert.equal(engineLineFontSizePx(verticalLine, unknown), 18);
    assert.equal(engineLineFontSizePx(tinyLine, unknown), 10);
  }
});

test("a chart box the engine does not draw keeps no address and catches no hit", () => {
  const source = createEnginePageSource({
    projection,
    raster: { page: 1, rev: "head", source: "engine", url: "blob:page", widthPt: 600, heightPt: 800 },
    count: 1,
    changes: [],
    geometry: { boxes: [
      { at: "p0", kind: "para", rect: [10, 10, 300, 200] },
      { at: "p0#L0", kind: "line", rect: [10, 10, 300, 200], text: "￼", xs: [10, 310] },
      { at: null, kind: "object", object: "chart", rect: [10, 10, 300, 200], text: "" },
    ] },
  });
  const boxes = source.boxes(1);
  const chart = boxes.filter((box) => box.kind === "object");
  assert.deepEqual(chart.map(({ address, object }) => ({ address, object })), [{ address: undefined, object: "chart" }]);
  // a click on the chart lands on its paragraph, never on the object box
  assert.equal(source.hitTest(1, 50, 50).address, "p0");
});

test("a whole-cell edit names the one run it changes", async () => {
  const { resolveCellRunEdit } = await import("../src/run_map.ts");
  const runs = [{ index: 0, text: "■ " }, { index: 1, text: "규정" }, { index: 2, text: "<개정>" }];
  const before = "■ 규정<개정>";
  // inside a run
  assert.deepEqual(resolveCellRunEdit(before, "■ 규칙<개정>", runs),
    { kind: "run", run: 1, runText: "규정", runStart: 2, text: "규칙" });
  // typing at a boundary goes to the run on its left, at the start to the first run
  assert.deepEqual(resolveCellRunEdit(before, "■ 규정!<개정>", runs),
    { kind: "run", run: 1, runText: "규정", runStart: 2, text: "규정!" });
  assert.deepEqual(resolveCellRunEdit(before, "!■ 규정<개정>", runs),
    { kind: "run", run: 0, runText: "■ ", runStart: 0, text: "!■ " });
  // appending at the end goes to the last run
  assert.equal(resolveCellRunEdit(before, `${before}!`, runs).run, 2);
  // deleting inside one run
  assert.deepEqual(resolveCellRunEdit(before, "■ 규<개정>", runs),
    { kind: "run", run: 1, runText: "규정", runStart: 2, text: "규" });
  // a change over two runs, or a cell the runs do not spell, or one run
  assert.deepEqual(resolveCellRunEdit(before, "■ 새<개정>!", runs), { kind: "cross_run" });
  assert.deepEqual(resolveCellRunEdit("다른 글", "다른 글!", runs), { kind: "none" });
  assert.deepEqual(resolveCellRunEdit("규정", "규칙", [{ index: 0, text: "규정" }]), { kind: "none" });
  assert.deepEqual(resolveCellRunEdit(before, "■ 규정\n<개정>", runs), { kind: "none" });
});
