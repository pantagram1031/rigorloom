// A value written under a cell's printed label (T272): the editor commit, the
// plan payload and the preview edit all carry the label and the value lines.
import assert from "node:assert/strict";
import test from "node:test";

import { belowLabelEditAt, belowLabelLines, belowLabelValue, resolveBelowLabelEdit } from "../src/model/belowLabel.ts";
import { engineTextEdit, queuedCellText } from "../src/model/enginePage.ts";
import { isWellFormedOp, planOpsPayload } from "../src/workspace/trust.ts";

const LABEL = "성명(법인ㆍ단체명 및 대표자 성명)";

test("lines typed under the label become a below-label fill", () => {
  assert.deepEqual(resolveBelowLabelEdit(`${LABEL}\n`, `${LABEL}\n홍길동`), {
    belowLabel: { label: LABEL, previous: "" },
    text: `${LABEL}\n홍길동`,
  });
  // A label-only cell, two value lines, trailing blank lines dropped.
  assert.deepEqual(resolveBelowLabelEdit("주소(소재지)", "주소(소재지)\n서울\n세종대로 1\n\n"), {
    belowLabel: { label: "주소(소재지)", previous: "" },
    text: "주소(소재지)\n서울\n세종대로 1",
  });
  // A value already under the label is the previous value.
  assert.deepEqual(resolveBelowLabelEdit(`${LABEL}\n홍길동`, `${LABEL}\n김철수`), {
    belowLabel: { label: LABEL, previous: "홍길동" },
    text: `${LABEL}\n김철수`,
  });
});

test("a label of two paragraphs stays whole", () => {
  const label = "사업자등록번호\n(주민등록번호)";
  assert.deepEqual(resolveBelowLabelEdit(`${label}\n`, `${label}\n123-45-67890`, 2), {
    belowLabel: { label, previous: "" },
    text: `${label}\n123-45-67890`,
  });
  // Changing the label's second line is a change to the label.
  assert.equal(resolveBelowLabelEdit(`${label}\n`, "사업자등록번호\n123", 2), null);
  assert.equal(resolveBelowLabelEdit("사업자등록번호", "사업자등록번호\n1", 2), null);
});

test("a change to the label itself, or on its line, is not a below-label fill", () => {
  assert.equal(resolveBelowLabelEdit("주소(소재지)", "주소(소재지) 서울"), null);
  assert.equal(resolveBelowLabelEdit("주소(소재지)", "주소\n서울"), null);
  assert.equal(resolveBelowLabelEdit("", "\n서울"), null);
  assert.equal(resolveBelowLabelEdit("  ", "  \n서울"), null);
  // Only blank lines added: nothing under the label changed.
  assert.equal(resolveBelowLabelEdit(`${LABEL}\n`, `${LABEL}\n\n`), null);
});

test("the value under a label, and the lines a queued fill writes", () => {
  assert.equal(belowLabelValue("주소(소재지)", "주소(소재지)"), "");
  assert.equal(belowLabelValue("주소(소재지)\n서울\n", "주소(소재지)"), "서울");
  assert.equal(belowLabelValue("주소\n서울", "주소(소재지)"), null);
  const op = { text: "주소(소재지)\n서울\n세종대로 1", belowLabel: { label: "주소(소재지)" } };
  assert.deepEqual(belowLabelLines(op), ["서울", "세종대로 1"]);
  assert.deepEqual(belowLabelLines({ text: "주소(소재지)\n", belowLabel: { label: "주소(소재지)" } }), [""]);
  assert.equal(belowLabelLines({ text: "서울" }), null);
});

const queued = {
  opId: "op-t0r8c1",
  kind: "fill_cell",
  table: 0,
  row: 8,
  col: 1,
  text: "주소(소재지)\n서울\n세종대로 1",
  belowLabel: { label: "주소(소재지)", previous: "" },
  before: "주소(소재지)",
  origin: "user",
};

test("the plan op carries only the value lines and the label", () => {
  assert.equal(isWellFormedOp(queued), true);
  assert.equal(isWellFormedOp({ ...queued, belowLabel: { label: "" } }), false);
  assert.equal(isWellFormedOp({ ...queued, belowLabel: { label: "주소", previous: 3 } }), false);
  assert.deepEqual(planOpsPayload([queued]), [{
    opId: "op-t0r8c1",
    kind: "fill_cell",
    table: 0,
    row: 8,
    col: 1,
    lines: ["서울", "세종대로 1"],
    belowLabel: { label: "주소(소재지)", previous: "" },
  }]);
});

test("every view shows the whole cell; the preview edit names the label and the lines", () => {
  assert.equal(queuedCellText(queued), "주소(소재지)\n서울\n세종대로 1");
  assert.deepEqual(engineTextEdit(queued), [{
    at: "t0/r8/c1",
    text: "주소(소재지)\n서울\n세종대로 1",
    belowLabel: { label: "주소(소재지)" },
    lines: ["서울", "세종대로 1"],
  }]);
});

test("only a cell marked with its label at the top takes a fill under the label", () => {
  const inspect = { graph: { tables: [{ index: 0, cells: [
    { addr: { row: 8, col: 1 }, labelTop: { paras: 1 } },
    { addr: { row: 8, col: 2 } },
  ] }] } };
  assert.deepEqual(belowLabelEditAt(inspect, 0, 8, 1, "주소", "주소\n서울"), {
    belowLabel: { label: "주소", previous: "" },
    text: "주소\n서울",
  });
  assert.equal(belowLabelEditAt(inspect, 0, 8, 2, "주소", "주소\n서울"), null);
  assert.equal(belowLabelEditAt(inspect, 1, 8, 1, "주소", "주소\n서울"), null);
  assert.equal(belowLabelEditAt(null, 0, 8, 1, "주소", "주소\n서울"), null);
});
