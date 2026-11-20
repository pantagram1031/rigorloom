import assert from "node:assert/strict";
import { test } from "node:test";

import { createEnginePageSource, pageRasterScale } from "../src/model/enginePage.ts";

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

test("page scale follows zoom and device pixel ratio up to the cap", () => {
  assert.equal(pageRasterScale(0.75, 2), 1.5);
  assert.equal(pageRasterScale(2, 3), 3);
});
