import assert from "node:assert/strict";
import test from "node:test";

import {
  editorRunsForInitial,
  normalizeRunColor,
  runColorSegments,
} from "../src/model/runColors.ts";

const GIANMUN_HEADER_RUNS = [
  { text: "■ ", color: "#000000" },
  { text: "행정업무의 운영 및 혁신에 관한 규정 시행규칙", color: "#000000" },
  { text: " [별지 제1호서식] ", color: "#000000" },
  { text: "<개정 2016. 7. 11.>", color: "#0000FF" },
];
const GIANMUN_HEADER_TEXT =
  "■ 행정업무의 운영 및 혁신에 관한 규정 시행규칙 [별지 제1호서식] <개정 2016. 7. 11.>";

test("prefix and suffix keep the colours of the runs they came from", () => {
  assert.deepEqual(runColorSegments(GIANMUN_HEADER_RUNS, GIANMUN_HEADER_TEXT), [
    {
      text: "■ 행정업무의 운영 및 혁신에 관한 규정 시행규칙 [별지 제1호서식] ",
      color: "#000000",
    },
    {
      text: "<개정 2016. 7. 11.>",
      color: "#0000FF",
    },
  ]);

  const threeColors = [
    { text: "머리 ", color: "#000000" },
    { text: "[중간]", color: "#008000" },
    { text: " <개정>", color: "#0000FF" },
  ];
  assert.deepEqual(runColorSegments(threeColors, "머리 [중간 수정] <개정>"), [
    { text: "머리 ", color: "#000000" },
    { text: "[중간 수정]", color: "#008000" },
    { text: " <개정>", color: "#0000FF" },
  ]);
});

test("insertion inside the blue run stays blue", () => {
  const edited =
    "■ 행정업무의 운영 및 혁신에 관한 규정 시행규칙 [별지 제1호서식] <개정 2026. 1. 1.>";
  assert.deepEqual(runColorSegments(GIANMUN_HEADER_RUNS, edited), [
    {
      text: "■ 행정업무의 운영 및 혁신에 관한 규정 시행규칙 [별지 제1호서식] ",
      color: "#000000",
    },
    {
      text: "<개정 2026. 1. 1.>",
      color: "#0000FF",
    },
  ]);

  const appended = `${GIANMUN_HEADER_TEXT}X`;
  assert.deepEqual(runColorSegments(GIANMUN_HEADER_RUNS, appended), [
    {
      text: "■ 행정업무의 운영 및 혁신에 관한 규정 시행규칙 [별지 제1호서식] ",
      color: "#000000",
    },
    {
      text: "<개정 2016. 7. 11.>X",
      color: "#0000FF",
    },
  ]);
});

test("insertion at a run boundary takes the colour of the run on the left", () => {
  const runs = [
    { text: "제목 ", color: "#000000" },
    { text: "<개정>", color: "#0000FF" },
  ];
  assert.deepEqual(runColorSegments(runs, "제목 추가<개정>"), [
    { text: "제목 추가", color: "#000000" },
    { text: "<개정>", color: "#0000FF" },
  ]);

  // Insertion at the very start of the text takes the first run's colour.
  assert.deepEqual(runColorSegments(runs, "■ 제목 <개정>"), [
    { text: "■ 제목 ", color: "#000000" },
    { text: "<개정>", color: "#0000FF" },
  ]);
});

test("deletion and replacement across a run boundary keep remaining prefix and suffix colours", () => {
  const runs = [
    { text: "■ 규정 ", color: "#000000" },
    { text: "<개정 2016>", color: "#0000FF" },
  ];
  assert.deepEqual(runColorSegments(runs, "■ 2016>"), [
    { text: "■ ", color: "#000000" },
    { text: "2016>", color: "#0000FF" },
  ]);

  assert.deepEqual(runColorSegments(runs, "■ 새문구 2016>"), [
    { text: "■ 새문구", color: "#000000" },
    { text: " 2016>", color: "#0000FF" },
  ]);
});

test("empty value returns an empty segment list when runs have mixed colours", () => {
  assert.deepEqual(runColorSegments(GIANMUN_HEADER_RUNS, ""), []);
});

test("single colour or absent runs return null so no mirror is rendered", () => {
  assert.equal(runColorSegments(null, "텍스트"), null);
  assert.equal(runColorSegments(undefined, "텍스트"), null);
  assert.equal(runColorSegments([], ""), null);
  assert.equal(runColorSegments([{ text: "단일 런", color: "#0000FF" }], "단일 런"), null);
  assert.equal(
    runColorSegments(
      [
        { text: "첫째 ", color: "#000000" },
        { text: "둘째", color: "#000000" },
      ],
      "첫째 둘째",
    ),
    null,
  );
  assert.equal(
    runColorSegments(
      [
        { text: "첫째 " },
        { text: "둘째", color: null },
      ],
      "첫째 둘째",
    ),
    null,
  );
});

test("a run without a declared colour uses inherit alongside a coloured run", () => {
  assert.equal(normalizeRunColor(undefined), "inherit");
  assert.equal(normalizeRunColor(null), "inherit");
  assert.equal(normalizeRunColor("  "), "inherit");
  assert.equal(normalizeRunColor("#0000FF"), "#0000FF");

  const runs = [
    { text: "기본색 " },
    { text: "<파랑>", color: "#0000FF" },
  ];
  assert.deepEqual(runColorSegments(runs, "기본색 <파랑>"), [
    { text: "기본색 ", color: "inherit" },
    { text: "<파랑>", color: "#0000FF" },
  ]);
});

test("editorRunsForInitial passes runs only when their joined text matches the initial value", () => {
  const regionRuns = [
    { text: "제목 ", charpr_color: "#000000" },
    { text: "<개정>", charpr_color: "#0000FF" },
  ];
  assert.deepEqual(editorRunsForInitial(regionRuns, "제목 <개정>"), [
    { text: "제목 ", color: "#000000" },
    { text: "<개정>", color: "#0000FF" },
  ]);
  assert.equal(editorRunsForInitial(regionRuns, "제목 <개정>X"), undefined);
  assert.equal(editorRunsForInitial([{ text: "제목", charpr_color: "#000000" }], "제목"), undefined);
  assert.equal(editorRunsForInitial(null, "제목"), undefined);
});
