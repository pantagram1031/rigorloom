// Integration: field labels on the recorded 기안문 (desktop/src/fixtures/corpus.json).
// A static form line being edited is named by its own words, never by the row
// above (WP4 saw the paper-size line labelled `전화번호( )`), and an empty slot
// never leaves a dangling bracket (`전화번호(` in the 빈칸 pane).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const { setUiVariant } = await import("../src/uiVariant.ts");
setUiVariant("v2");
const labels = await import("../src/workspace/fieldLabels.ts");
const corpus = JSON.parse(readFileSync(new URL("../src/fixtures/corpus.json", import.meta.url), "utf8"));

const textMap = {};
for (const r of corpus.regions) {
  if (r.table === undefined || !r.addr) continue;
  textMap[`c:${r.table}:${r.addr.row}:${r.addr.col}`] = r;
}
const label = (row, col) => labels.deriveCellFieldLabel(corpus.inspect, textMap, 0, row, col, "ko");

test("labelFromCellText drops empty slots and keeps real brackets", () => {
  assert.equal(labels.labelFromCellText("전화번호(   )"), "전화번호");
  assert.equal(labels.labelFromCellText("팩스번호( )"), "팩스번호");
  assert.equal(labels.labelFromCellText("210㎜×297㎜(백상지 80g/㎡)"), "210㎜×297㎜(백상지 80g/㎡)");
  assert.equal(labels.labelFromCellText("기안자  직위(직급) 서명"), "기안자");
  assert.equal(labels.labelFromCellText("성명("), "성명");
  assert.equal(labels.labelFromCellText("행 정 기 관 명"), "행정기관명");
});

test("a static form line is named by its own words on the 기안문", () => {
  assert.equal(label(9, 0), "210㎜×297㎜(백상지 80g/㎡)");
  assert.equal(label(8, 0), "전화번호");
  assert.equal(label(8, 2), "팩스번호");
  assert.equal(label(7, 0), "우");
  // Fields on one line keep their own names, not the neighbour's.
  assert.equal(label(4, 3), "검토자 직위(직급) 서명");
  assert.equal(label(7, 1), "도로명주소");
  assert.equal(label(8, 12), "공개 구분");
  assert.equal(label(10, 0), "비고");
  // A value cell still takes the label to its left.
  assert.equal(label(5, 1), "협조자");
  for (const row of [6, 7, 8, 9]) {
    for (const col of [0, 1, 2, 7, 12]) assert.doesNotMatch(label(row, col), /[(（]\s*[)）]?$/);
  }
});

test("a form separator stops label inheritance in editor v2", () => {
  const cells = [
    { addr: { row: 0, col: 0 }, classification: "static", textPreview: "왼쪽 항목" },
    { addr: { row: 0, col: 1 }, classification: "static", textPreview: "/" },
    { addr: { row: 0, col: 2 }, classification: "fill_target", textPreview: "" },
  ];
  const inspect = { graph: { tables: [{ index: 0, cells }] } };
  assert.equal(labels.deriveCellFieldLabel(inspect, {}, 0, 0, 0, "en"), "왼쪽 항목");
  assert.equal(labels.deriveCellFieldLabel(inspect, {}, 0, 0, 2, "en"), "Blank 1");
});
