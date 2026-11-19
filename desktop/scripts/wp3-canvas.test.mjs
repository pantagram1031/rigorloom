import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import ts from "typescript";

const require = createRequire(import.meta.url);
const DESKTOP_ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function loadTsModule(relPath, stubs = {}) {
  const fullPath = path.join(DESKTOP_ROOT, relPath);
  const source = readFileSync(fullPath, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
    fileName: fullPath,
  });
  const module = { exports: {} };
  const req = (id) => (id in stubs ? stubs[id] : require(id));
  vm.runInThisContext(`(function(exports, require, module) {\n${outputText}\n})`)(
    module.exports,
    req,
    module,
  );
  return module.exports;
}

const corpus = JSON.parse(
  readFileSync(path.join(DESKTOP_ROOT, "src/fixtures/corpus.json"), "utf8"),
);

// Build clean in-memory state + legacy action stubs matching `store.ts` & `actions.ts`
function createStoreHarness() {
  const queuedOps = [];
  const state = {
    activeSessionId: "sess-1",
    language: "ko",
    page: 1,
    inlineEdit: null,
    sawComposition: false,
    selection: null,
    lastCommit: null,
    sessions: [
      {
        sessionId: "sess-1",
        source: corpus.source,
      },
    ],
    inspects: { "sess-1": corpus.inspect },
    texts: { "sess-1": corpus.regions },
    candidates: { "sess-1": [] },
    draft: {
      ops: queuedOps,
      opsCount: 0,
      preview: null,
      validation: null,
      plan: null,
      boundSha256: corpus.source.sha256,
      reverses: null,
      agentRun: null,
    },
    render: null,
    geometry: null,
  };

  const storeStub = {
    activeSession: (s) => s.sessions.find((x) => x.sessionId === s.activeSessionId) ?? null,
    cellKey: (t, r, c) => `c:${t}:${r}:${c}`,
    getState: () => state,
    setState: (patch) => {
      const next = typeof patch === "function" ? patch(state) : patch;
      Object.assign(state, next);
    },
    queuedCellOpAt: (s, t, r, c) =>
      s.draft.ops.find(
        (o) =>
          (o.kind === "fill_cell" || o.kind === "replace_at_cell") &&
          o.table === t &&
          o.row === r &&
          o.col === c,
      ) ?? null,
    useWorkspace: (sel) => sel(state),
  };

  const upsertCalls = [];
  const removeCalls = [];

  const legacyActionsStub = {
    seatAt: (inspect, t, r, c) => {
      const tbl = inspect?.graph?.tables?.find((tb) => tb.index === t);
      const cell = tbl?.cells?.find((cl) => cl.addr.row === r && cl.addr.col === c);
      if (!cell || cell.classification !== "fill_target") return null;
      return {
        table: t,
        row: r,
        col: c,
        scriptAnomaly: t === 0 && r === 2 && c === 0,
        charPrSuggested: "23",
      };
    },
    seatText: (inspect, texts, t, r, c) => {
      const reg = texts?.find((x) => x.table === t && x.addr?.row === r && x.addr?.col === c);
      if (reg) return reg.text;
      const tbl = inspect?.graph?.tables?.find((tb) => tb.index === t);
      const cell = tbl?.cells?.find((cl) => cl.addr.row === r && cl.addr.col === c);
      return cell?.textPreview ?? "";
    },
    addQueueOp: async (op) => {
      upsertCalls.push({ op, replaceOpId: null });
      queuedOps.push(op);
      state.draft.opsCount = queuedOps.length;
    },
    undoQueuedOp: async (opId) => {
      removeCalls.push(opId);
      const idx = queuedOps.findIndex((o) => o.opId === opId);
      if (idx >= 0) queuedOps.splice(idx, 1);
      state.draft.opsCount = queuedOps.length;
    },
  };

  return { state, queuedOps, upsertCalls, removeCalls, storeStub, legacyActionsStub };
}

function loadWp3Stack() {
  const h = createStoreHarness();
  const vocabulary = loadTsModule("src/i18n/vocabulary.ts");
  const formTokens = loadTsModule("src/i18n/formTokens.ts");
  const wp3 = loadTsModule("src/i18n/v2/wp3.ts", {
    "../vocabulary": vocabulary,
    "../vocabulary.ts": vocabulary,
  });
  const wp3FormTokens = loadTsModule("src/i18n/v2/wp3FormTokens.ts");
  const fieldLabels = loadTsModule("src/workspace/fieldLabels.ts", {
    "../i18n/formTokens.ts": formTokens,
    "../i18n/formTokens": formTokens,
    "../i18n/vocabulary.ts": vocabulary,
    "../i18n/vocabulary": vocabulary,
  });
  const pageModel = loadTsModule("src/model/page.ts", {
    "../i18n/v2/wp3": wp3,
    "../i18n/v2/wp3FormTokens": wp3FormTokens,
    "../workspace/fieldLabels": fieldLabels,
  });
  const shim = loadTsModule("src/canvas/_shim.ts", {
    react: React,
    "../i18n/v2/wp3FormTokens": wp3FormTokens,
    "../store": h.storeStub,
  });
  const controller = loadTsModule("src/canvas/controller.ts", {
    "./_shim": shim,
  });
  const actions = loadTsModule("src/canvas/actions.ts", {
    "../actions": h.legacyActionsStub,
    "../i18n/v2/wp3": wp3,
    "../store": h.storeStub,
    "../workspace/fieldLabels": fieldLabels,
    "./controller": controller,
  });
  return {
    ...h,
    wp3,
    wp3FormTokens,
    fieldLabels,
    pageModel,
    shim,
    controller,
    actions,
  };
}

test("PageSource contract: exposes kind, grade, rev, pageCount, size, layer, boxes, hitTest, caretRect, seats, outline, fonts", () => {
  const { pageModel } = loadWp3Stack();
  const textMap = {};
  for (const r of corpus.regions) {
    if (r.addr) textMap[`c:${r.table ?? 0}:${r.addr.row}:${r.addr.col}`] = r;
  }

  const changes = [
    {
      id: "op-5",
      n: 5,
      at: "t0/r1/c0",
      kind: "replace_at_cell",
      opKind: "replace_at_cell",
      label: "기관명",
      before: "행 정 기 관 명",
      after: "가온공공기록원",
      page: 1,
      source: "agent",
      decision: "pending",
      guard: "none",
      hard: false,
      isFactChanged: false,
      isStale: false,
      cellKey: "c:0:1:0",
      run: 0,
    },
    {
      id: "op-6",
      n: 6,
      at: "t0/r1/c0",
      kind: "replace_at_cell",
      opKind: "replace_at_cell",
      label: "수신",
      before: "수신",
      after: "수신 협조기관장",
      page: 1,
      source: "agent",
      decision: "rejected",
      guard: "none",
      hard: false,
      isFactChanged: false,
      isStale: false,
      cellKey: "c:0:1:0",
      run: 1,
    },
  ];

  const src = pageModel.createProjectionPageSource({
    inspect: corpus.inspect,
    texts: corpus.regions,
    textMap,
    changes,
    rev: "원본",
    language: "ko",
  });

  assert.equal(src.kind, "projection");
  assert.equal(src.grade, "own-uncertified");
  assert.equal(src.rev, "원본");
  assert.equal(src.pageCount(), 1);
  const sz = src.size(1);
  assert.ok(sz.widthPt > 590 && sz.heightPt > 830, `Expected A4 points, got ${JSON.stringify(sz)}`);
  assert.equal(src.layer(1, "marks").marks.length, 2);
  assert.equal(src.layer(1, "clean").marks.length, 0);
  assert.equal(src.layer(1, "base").marks.length, 0); // original has zero diff marks
  assert.ok(src.boxes(1).length > 20);
  assert.ok(src.changedRects("op-5").length >= 1);
  assert.ok(Array.isArray(src.seats()));
  assert.ok(Array.isArray(src.outline()));
  assert.ok(src.fonts().total >= 0);

  const seatBox = src.boxes(1).find((b) => b.address);
  assert.ok(seatBox && seatBox.address);
  const hit = src.hitTest(1, seatBox.rect.x + 2, seatBox.rect.y + 2);
  assert.ok(hit && hit.kind !== "none");
  const caret = src.caretRect(1, seatBox.address, 0);
  assert.ok(caret && caret.h > 0);

  const previewSrc = pageModel.createProjectionPageSource({
    inspect: corpus.inspect,
    texts: corpus.regions,
    textMap,
    changes,
    render: { grade: "preview", pageCount: 1 },
    rev: "원본",
    language: "ko",
  });
  assert.equal(previewSrc.grade, "preview");
});

test("Font substitution counting reports exact count of unbundled Windows/Hancom faces (Advisor Gate)", () => {
  const { pageModel } = loadWp3Stack();

  const bundledInspect = {
    ...corpus.inspect,
    summary: {
      ...corpus.inspect.summary,
      typefaces: {
        state: "read",
        faces: [
          { role: "body", script: "hangul", name: "NanumGothic" },
          { role: "table", script: "hangul", name: "나눔명조" },
        ],
      },
    },
  };
  const cleanFonts = pageModel.collectPageFonts(bundledInspect, null, "ko");
  assert.equal(cleanFonts.substitutedCount, 0);

  const mixedInspect = {
    ...corpus.inspect,
    summary: {
      ...corpus.inspect.summary,
      typefaces: {
        state: "read",
        faces: [
          { role: "body", script: "hangul", name: "한양중고딕" },
          { role: "body", script: "latin", name: "한양신명조" },
          { role: "table", script: "hangul", name: "돋움" },
          { role: "caption", script: "hangul", name: "함초롬바탕" },
          { role: "note", script: "hangul", name: "나눔고딕" },
        ],
      },
    },
  };
  const subFonts = pageModel.collectPageFonts(mixedInspect, null, "ko");
  assert.equal(subFonts.total, 5);
  assert.equal(subFonts.substitutedCount, 4);
  assert.equal(subFonts.entries[0].resolved, "나눔고딕");
  assert.equal(subFonts.entries[1].resolved, "나눔명조");
});

test("classifyCellEditMode & commitCellEditV2 turn typing into '성명(' into 칸 문구 덧붙임 (replace_at_cell append)", async () => {
  const { fieldLabels, actions, state } = loadWp3Stack();

  const appendRes = fieldLabels.classifyCellEditMode("성명(", "성명(홍길동)");
  assert.equal(appendRes.kind, "replace_at_cell");
  assert.equal(appendRes.mode, "append");
  assert.equal(appendRes.hasFormText, true);

  // Full commit path produces op.text as appended suffix "홍길동)" (`modeLabelKey === "replace_at_cell:append"`)
  const spyOps = [];
  actions.setCanvasQueueAdapter({
    upsertOp: (op) => spyOps.push(op),
    removeOp: () => {},
  });
  state.texts[state.activeSessionId] = [
    { table: 0, addr: { row: 0, col: 0 }, text: "성명(" },
    ...corpus.regions.filter((r) => !(r.table === 0 && r.addr?.row === 0 && r.addr?.col === 0)),
  ];
  assert.equal(actions.beginCellEditV2(0, 0, 0), true);
  const commit = await actions.commitCellEditV2("성명(홍길동)");
  assert.equal(commit.committed, true);
  assert.equal(commit.modeLabelKey, "replace_at_cell:append");
  assert.equal(spyOps[0].kind, "replace_at_cell");
  assert.equal(spyOps[0].mode, "append");
  assert.equal(spyOps[0].text, "홍길동)");
  actions.setCanvasQueueAdapter(null);

  const slotRes = fieldLabels.classifyCellEditMode("전화번호(   )", "전화번호(044-555-0142)");
  assert.equal(slotRes.kind, "replace_at_cell");
  assert.equal(slotRes.mode, "replace");
  assert.equal(slotRes.hasFormText, true);

  const blankRes = fieldLabels.classifyCellEditMode("", "가온공공기록원");
  assert.equal(blankRes.kind, "fill_cell");
});

test("detectDocumentSeats disambiguates 7 협조자 blanks and collapses 접수 agency cells", () => {
  const { pageModel } = loadWp3Stack();
  const textMap = {};
  for (const r of corpus.regions) {
    if (r.addr) textMap[`c:${r.table ?? 0}:${r.addr.row}:${r.addr.col}`] = r;
  }

  const seats = pageModel.detectDocumentSeats(corpus.inspect, textMap, [], "ko");
  const coopSeats = seats.filter((s) => s.baseLabel === "협조자");
  assert.equal(coopSeats.length, 7);
  assert.deepEqual(
    coopSeats.map((s) => s.displayLabel),
    ["협조자 1", "협조자 2", "협조자 3", "협조자 4", "협조자 5", "협조자 6", "협조자 7"],
  );
  // Every disambiguated seat carries a distinct table/row/col coordinate
  assert.equal(new Set(coopSeats.map((s) => s.address)).size, 7);

  const agencySeats = seats.filter((s) => s.group === "agency");
  assert.ok(agencySeats.some((s) => s.baseLabel.includes("접수")));
});

test("beginCellEditV2 opens static/guide cells without refusal and commits only on explicit commit", async () => {
  const stack = loadWp3Stack();
  const spyUpserts = [];
  stack.actions.setCanvasQueueAdapter({
    upsertOp: (op, replaceOpId) => spyUpserts.push({ op, replaceOpId }),
    removeOp: () => {},
  });

  // Clicking a guide cell (t0, r0, c0) must open editor cleanly with zero refusal notice
  const openedGuide = stack.actions.beginCellEditV2(0, 0, 0);
  assert.equal(openedGuide, true);
  assert.ok(stack.state.inlineEdit);
  assert.equal(stack.controller.getCanvasSlice().statusNotice, null);
  assert.equal(spyUpserts.length, 0); // zero network/queue writes while editing

  // Reopen blank fill target (t0, r2, c0) which has scriptAnomaly -> auto charPrSuggested
  const openedBlank = stack.actions.beginCellEditV2(0, 2, 0);
  assert.equal(openedBlank, true);
  assert.equal(stack.state.inlineEdit.charPr, "23");
  assert.equal(spyUpserts.length, 0);

  const commitRes = await stack.actions.commitCellEditV2("가온공공기록원 본문");
  assert.equal(commitRes.committed, true);
  assert.equal(commitRes.bodyStyleMatched, true);
  assert.equal(spyUpserts.length, 1);
  assert.equal(spyUpserts[0].op.origin, "user");
  assert.equal(spyUpserts[0].op.kind, "fill_cell");
  assert.equal(spyUpserts[0].op.charPr, "23");

  // Clean up custom adapter
  stack.actions.setCanvasQueueAdapter(null);
});

test("replaceFindMatch enqueues origin:'user' (내 입력) edit op", async () => {
  const stack = loadWp3Stack();
  const match = {
    id: "c:0:1:0",
    targetType: "cell",
    cellKey: "c:0:1:0",
    table: 0,
    row: 1,
    col: 0,
    run: 0,
    label: "기관명",
    locationLabel: "1쪽 · 표 1 2행 1열",
    text: "가온공공기록원",
    matchStart: 0,
    matchEnd: 2,
  };
  const ok = await stack.actions.replaceFindMatch(match, "가온", "한울");
  assert.equal(ok, true);
  assert.equal(stack.queuedOps.length, 1);
  assert.equal(stack.queuedOps[0].origin, "user");
  assert.equal(stack.queuedOps[0].text, "한울공공기록원");
});

test("WP3 static hygiene: zero hex literals in canvas/ & panes/, zero 결재 in wp3.ts", () => {
  const dirs = ["src/canvas", "src/panes", "src/model", "src/i18n/v2"];
  const hexRe = /#[0-9a-fA-F]{3,8}\b/;
  for (const relDir of dirs) {
    const absDir = path.join(DESKTOP_ROOT, relDir);
    if (!existsSync(absDir)) continue;
    for (const entry of readdirSync(absDir, { withFileTypes: true })) {
      if (!entry.isFile()) continue;
      if (!/\.(ts|tsx|css|html)$/.test(entry.name)) continue;
      const content = readFileSync(path.join(absDir, entry.name), "utf8");
      assert.equal(
        hexRe.test(content),
        false,
        `Unexpected hex literal in ${relDir}/${entry.name}`,
      );
    }
  }

  const wp3Src = readFileSync(path.join(DESKTOP_ROOT, "src/i18n/v2/wp3.ts"), "utf8");
  assert.equal(wp3Src.includes("결재"), false, "Forbidden word 결재 in wp3.ts");
});
