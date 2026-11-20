import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const nodeRequire = createRequire(import.meta.url);

function loadTsModule(relPath, stubs = {}) {
  const source = readFileSync(new URL(relPath, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  });
  const module = { exports: {} };
  const req = (id) => (id in stubs ? stubs[id] : nodeRequire(id));
  vm.runInThisContext(`(function(exports, require, module) {\n${outputText}\n})`)(
    module.exports,
    req,
    module,
  );
  return module.exports;
}

const vocabulary = loadTsModule("../src/i18n/vocabulary.ts");
const formTokens = loadTsModule("../src/i18n/formTokens.ts");
const planProjection = loadTsModule("../src/agent/planProjection.ts", {
  "../i18n/vocabulary.ts": vocabulary,
  "../i18n/vocabulary": vocabulary,
});
const fieldLabels = loadTsModule("../src/workspace/fieldLabels.ts", {
  "../uiVariant.ts": { uiVariant: () => "v1" },
  "../i18n/vocabulary.ts": vocabulary,
  "../i18n/vocabulary": vocabulary,
  "../i18n/formTokens.ts": formTokens,
  "../i18n/formTokens": formTokens,
});
const guardHelper = loadTsModule("../src/workspace/guardHelper.ts", {
  react: { useSyncExternalStore: (_sub, snap) => snap() },
  "../agent/planProjection": planProjection,
  "../i18n/vocabulary": vocabulary,
  "../i18n/formTokens.ts": formTokens,
  "../i18n/formTokens": formTokens,
  "./fieldLabels": fieldLabels,
  "../runtime": {
    guardDiff: async () => {
      throw new Error("unused");
    },
    asRuntimeError: (err) => ({ code: "guard_unavailable", message: String(err) }),
  },
});
const reviewSummary = loadTsModule("../src/workspace/reviewSummary.ts", {
  "../store": {
    draftStaleness: () => null,
  },
});

const reviewViewSrc = readFileSync(new URL("../src/views/ReviewView.tsx", import.meta.url), "utf8");
const changeListSrc = readFileSync(new URL("../src/components/ChangeList.tsx", import.meta.url), "utf8");
const changeRowSrc = readFileSync(new URL("../src/components/ChangeRow.tsx", import.meta.url), "utf8");
const pageSheetSrc = readFileSync(new URL("../src/components/PageSheet.tsx", import.meta.url), "utf8");

test("buildIndexedChanges indexes cell, run, and guide operations with preserved ordinals", () => {
  const draft = {
    ops: [
      { opId: "c1", kind: "fill_cell", table: 2, row: 3, col: 4, text: "값", before: "", origin: "user" },
      { opId: "r1", kind: "set_run", atPara: 9, run: 1, text: "새 문구", before: "기존 문구", origin: "agent" },
      { opId: "g1", kind: "delete_guides", color: "#0000FF", text: "(안내문 삭제됨)", before: "안내문", origin: "agent" },
    ],
    plan: null,
    validation: null,
    sessionId: "session-A",
    boundSha256: null,
    phase: "idle",
    error: null,
    rewrittenFromAgent: false,
    baseRunId: null,
    reverses: null,
  };
  const inspect = {
    documentHash: "h",
    sessionId: "session-A",
    summary: { anchors: [], fillTargetCount: 1, spacerCells: [], scriptAnomalyTargets: [], removalTargets: [] },
    graph: { tables: [{ index: 2, cells: [{ addr: { row: 3, col: 4 }, classification: "fill_target" }] }], paragraphs: [] },
    regions: { regions: [] },
  };
  const changes = guardHelper.buildIndexedChanges(draft, inspect, {}, "ko");
  assert.deepEqual(changes.map((c) => [c.ordinal, c.opId, c.targetKey]), [
    [1, "c1", "c:2:3:4"],
    [2, "r1", "p:9"],
    [3, "g1", null],
  ]);
  assert.equal(changes[0].isAuditable, false);
  assert.equal(changes[1].isAuditable, true);
  assert.equal(changes[2].isAuditable, true);
});

test("kept ReviewView, ChangeList, ChangeRow, and PageSheet wire selection without legacy ReviewQueue", () => {
  for (const src of [reviewViewSrc, changeListSrc, changeRowSrc, pageSheetSrc]) {
    assert.doesNotMatch(src, /ReviewQueue/);
  }
  assert.match(reviewViewSrc, /setSelectedChangeId/);
  assert.match(reviewViewSrc, /setExpandedChangeId/);
  assert.match(changeRowSrc, /onSelect\(change\.opId\)/);
  assert.match(changeRowSrc, /onToggleExpand\(change\.opId\)/);
  assert.match(pageSheetSrc, /onSelectChange/);
});

test("another session's preserved draft reports 0 active review ops for current session", () => {
  const baseState = {
    activeSessionId: "session-A",
    draft: { sessionId: "session-A", ops: [{ opId: "c1" }] },
  };
  assert.equal(reviewSummary.activeReviewQueueCount(baseState), 1);
  assert.equal(
    reviewSummary.activeReviewQueueCount({ ...baseState, activeSessionId: "session-B" }),
    0,
  );
  assert.match(reviewViewSrc, /const sessionId = session\?\.sessionId \?\? null;/);
});
