import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import ts from "typescript";

const require = createRequire(import.meta.url);
const DESKTOP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

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
  const req = (id) => {
    if (id in stubs) return stubs[id];
    // The below-label helpers import nothing, so every module gets the real ones.
    if (/(^|\/)belowLabel\.ts$/.test(id)) return loadTsModule("src/model/belowLabel.ts");
    return require(id);
  };
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

  const store = loadTsModule("src/store.ts", { react: React });
  store.setState(state);

  const upsertCalls = [];

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
    upsertQueueOp: async (op) => {
      const { ops, queued } = store.upsertQueuedOp(queuedOps, op);
      upsertCalls.push(queued);
      queuedOps.splice(0, queuedOps.length, ...ops);
      return queued;
    },
    undoQueuedOp: async (opId) => {
      const idx = queuedOps.findIndex((op) => op.opId === opId);
      if (idx >= 0) queuedOps.splice(idx, 1);
    },
  };

  return { store, queuedOps, upsertCalls, legacyActionsStub };
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
    "../uiVariant.ts": { uiVariant: () => "v2" },
    "../i18n/formTokens.ts": formTokens,
    "../i18n/formTokens": formTokens,
    "../i18n/v2/wp3.ts": wp3,
    "../i18n/v2/wp3": wp3,
    "../i18n/vocabulary.ts": vocabulary,
    "../i18n/vocabulary": vocabulary,
  });
  const pageModel = loadTsModule("src/model/page.ts", {
    "../i18n/v2/wp3": wp3,
    "../i18n/v2/wp3FormTokens": wp3FormTokens,
    "../workspace/fieldLabels": fieldLabels,
  });
  const changeModel = loadTsModule("src/model/changes.ts");
  const controller = loadTsModule("src/canvas/controller.ts", { "../store": h.store, "../model/changes": changeModel });
  // Cell runs the stubbed runtime answers for a cell edit; a test sets them.
  const cellRuns = { regions: [] };
  const actions = loadTsModule("src/canvas/actions.ts", {
    "../actions": h.legacyActionsStub,
    "../i18n/v2/wp3": wp3,
    "../run_map": loadTsModule("src/run_map.ts"),
    "../runtime": { readRegion: async () => ({ subject: null, regions: cellRuns.regions }) },
    "../store": h.store,
    "../workspace/fieldLabels": fieldLabels,
    "./controller": controller,
  });
  const changes = loadTsModule("src/canvas/changes.ts", {
    react: React,
    "../model/changes": changeModel,
    "../store": h.store,
    "../workspace/guardHelper": {},
    "./controller": controller,
  });
  const keys = loadTsModule("src/shell/keys.ts", { react: React });
  const keymap = loadTsModule("src/shell/keymap.ts", { "./keys.ts": keys });
  const slots = loadTsModule("src/shell/slots.ts", { react: React });
  const shell = loadTsModule("src/shell/shellState.ts", { react: React, "../store.ts": h.store });
  const commands = loadTsModule("src/shell/commands.ts", { react: React });
  const bindings = loadTsModule("src/shell/bindings.ts", {
    "../actions": {},
    "../i18n/v2/shell": {},
    "../runtime": { isTauri: () => false },
    "../store": h.store,
    "./commands": commands,
    "./keymap": keymap,
    "./keys": keys,
    "./open": {},
    "./shellState": shell,
    "./tabs": {},
  });
  const noopComp = () => null;
  const registerMod = loadTsModule("src/canvas/register.ts", {
    "../i18n/v2/wp3": wp3,
    "../panes/BlanksPane": { BlanksPane: noopComp },
    "../panes/FindPane": { FindPane: noopComp },
    "../panes/OutlinePane": { OutlinePane: noopComp },
    "../shell/bindings": bindings,
    "../shell/commands": commands,
    "../shell/keymap": keymap,
    "../shell/keys": keys,
    "../shell/shellState": shell,
    "../shell/slots": slots,
    "./actions": actions,
    "./controller": controller,
    "./CanvasPane": {
      CanvasPane: noopComp,
      CanvasStatusLeft: noopComp,
      CanvasStatusRight: noopComp,
    },
    "./DocumentStrip": { DocumentStrip: noopComp, DocumentStripStart: noopComp },
  });
  shell.setShell({ tabs: [{ kind: "doc", id: "doc:sess-1", sessionId: "sess-1" }], activeTab: "doc:sess-1" });

  return {
    ...h,
    cellRuns,
    wp3,
    wp3FormTokens,
    fieldLabels,
    pageModel,
    bindings,
    changes,
    changeModel,
    commands,
    keymap,
    keymap,
    keys,
    shell,
    slots,
    controller,
    actions,
    registerMod,
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
  const { fieldLabels, actions, store, upsertCalls } = loadWp3Stack();

  const appendRes = fieldLabels.classifyCellEditMode("성명(", "성명(홍길동)");
  assert.equal(appendRes.kind, "replace_at_cell");
  assert.equal(appendRes.mode, "append");
  assert.equal(appendRes.hasFormText, true);

  // Full commit path produces op.text as appended suffix "홍길동)" (`modeLabelKey === "replace_at_cell:append"`)
  const state = store.getState();
  state.texts[state.activeSessionId] = [
    { table: 0, addr: { row: 0, col: 0 }, text: "성명(" },
    ...corpus.regions.filter((r) => !(r.table === 0 && r.addr?.row === 0 && r.addr?.col === 0)),
  ];
  assert.equal(actions.beginCellEditV2(0, 0, 0), true);
  const commit = await actions.commitCellEditV2("성명(홍길동)");
  assert.equal(commit.committed, true);
  assert.equal(commit.modeLabelKey, "replace_at_cell:append");
  assert.equal(upsertCalls[0].kind, "replace_at_cell");
  assert.equal(upsertCalls[0].mode, "append");
  assert.equal(upsertCalls[0].text, "홍길동)");

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
  for (const seat of seats) {
    assert.equal(seat.page, null);
    assert.equal(seat.locationLabel.includes("쪽"), false);
    assert.match(seat.cellLocationLabel, /^\d+행 \d+열$/);
  }
});

test("a cell with its label printed at the top is a blank named by that label", () => {
  const { pageModel } = loadWp3Stack();
  const inspect = structuredClone(corpus.inspect);
  const cells = inspect.graph.tables[0].cells;
  const cell = cells.find((c) => c.classification === "static");
  assert.ok(cell, "the corpus has a printed cell");
  const key = `c:0:${cell.addr.row}:${cell.addr.col}`;
  const before = pageModel.detectDocumentSeats(inspect, {}, [], "ko").filter((s) => s.key === key);
  assert.equal(before.length, 0);

  cell.labelTop = { paras: 1, lines: 1, reserved: true };
  const region = { table: 0, addr: cell.addr, text: "주소(소재지)\n" };
  let [seat] = pageModel.detectDocumentSeats(inspect, { [key]: region }, [], "ko").filter((s) => s.key === key);
  assert.equal(seat.baseLabel, "주소(소재지)");
  assert.equal(seat.isFillTarget, false);
  assert.equal(seat.filled, false);
  [seat] = pageModel.detectDocumentSeats(
    inspect, { [key]: { ...region, text: "주소(소재지)\n          (    )" } }, [], "ko",
  ).filter((s) => s.key === key);
  assert.equal(seat.filled, false, "a printed bracket under the label is not a value");

  // Filled once a value is under the label, in the document or in the queue.
  [seat] = pageModel.detectDocumentSeats(
    inspect, { [key]: { ...region, text: "주소(소재지)\n서울" } }, [], "ko",
  ).filter((s) => s.key === key);
  assert.equal(seat.filled, true);
  [seat] = pageModel.detectDocumentSeats(
    inspect, { [key]: region }, [{ id: "x", cellKey: key, after: "주소(소재지)\n서울", decision: "pending" }], "ko",
  ).filter((s) => s.key === key);
  assert.equal(seat.filled, true);
  assert.equal(seat.currentText, "주소(소재지)\n서울");
});

test("groupSeatsByLocation, short cell labels, unknown-page fallback, and engine page resolution", () => {
  const { pageModel, wp3 } = loadWp3Stack();
  const enginePage = loadTsModule("src/model/enginePage.ts", {
    "./page": pageModel,
  });
  const textMap = {};
  for (const r of corpus.regions) {
    if (r.addr) textMap[`c:${r.table ?? 0}:${r.addr.row}:${r.addr.col}`] = r;
  }

  // 1. Short cell labels and group headings for known vs unknown pages (ko & en).
  assert.equal(pageModel.formatSeatCellLocation(2, 0, "ko"), "3행 1열");
  assert.equal(pageModel.formatSeatCellLocation(2, 0, "en"), "row 3, col 1");
  assert.equal(pageModel.formatSeatGroupHeading(1, 0, "ko"), "1쪽 · 표 1");
  assert.equal(pageModel.formatSeatGroupHeading(1, 0, "en"), "Page 1 · Table 1");
  assert.equal(pageModel.formatSeatGroupHeading(null, 0, "ko"), "표 1");
  assert.equal(pageModel.formatSeatGroupHeading(null, 0, "en"), "Table 1");
  assert.equal(pageModel.formatSeatLocation(2, 0, 5, 1, "ko"), "2쪽 · 표 1 6행 2열");
  assert.equal(pageModel.formatSeatLocation(2, 0, 5, 1, "en"), "Page 2 · Table 1, row 6, col 2");
  assert.equal(pageModel.formatSeatLocation(null, 0, 5, 1, "ko"), "표 1 6행 2열");
  assert.equal(pageModel.formatSeatLocation(null, 0, 5, 1, "en"), "Table 1, row 6, col 2");

  // 2. Pure grouping helper: single group still emits its heading; unknown page omits page number.
  const singleGroup = pageModel.groupSeatsByLocation(
    [
      { id: "a", page: null, table: 0 },
      { id: "b", page: null, table: 0 },
    ],
    "ko",
  );
  assert.equal(singleGroup.length, 1);
  assert.equal(singleGroup[0].heading, "표 1");
  assert.equal(singleGroup[0].page, null);
  assert.equal(singleGroup[0].table, 0);
  assert.deepEqual(singleGroup[0].seats.map((s) => s.id), ["a", "b"]);

  // 3. Multi-(page, table) grouping in ko and en.
  const mixedSeats = [
    { id: "s1", page: 1, table: 0 },
    { id: "s2", page: 1, table: 0 },
    { id: "s3", page: 1, table: 2 },
    { id: "s4", page: 2, table: 0 },
    { id: "s5", page: null, table: 0 },
  ];
  const koGroups = pageModel.groupSeatsByLocation(mixedSeats, "ko");
  assert.deepEqual(
    koGroups.map((g) => ({ key: g.key, heading: g.heading, ids: g.seats.map((s) => s.id) })),
    [
      { key: "1:t0", heading: "1쪽 · 표 1", ids: ["s1", "s2"] },
      { key: "1:t2", heading: "1쪽 · 표 3", ids: ["s3"] },
      { key: "2:t0", heading: "2쪽 · 표 1", ids: ["s4"] },
      { key: "unknown:t0", heading: "표 1", ids: ["s5"] },
    ],
  );
  const enGroups = pageModel.groupSeatsByLocation(mixedSeats, "en");
  assert.deepEqual(
    enGroups.map((g) => g.heading),
    ["Page 1 · Table 1", "Page 1 · Table 3", "Page 2 · Table 1", "Table 1"],
  );

  // 4. Engine page source resolution: resolves real page from engine geometry, leaves unmeasured as null.
  const projection = pageModel.createProjectionPageSource({
    inspect: corpus.inspect,
    texts: corpus.regions,
    textMap,
    changes: [],
    rev: "head",
    language: "ko",
  });
  const engineSourcePage2 = enginePage.createEnginePageSource({
    projection,
    raster: { page: 2, rev: "head", source: "engine", url: "blob:p2", widthPt: 595, heightPt: 842 },
    count: 2,
    geometry: {
      rev: "head",
      page: 2,
      width_pt: 595,
      height_pt: 842,
      boxes: [{ kind: "cell", at: "t0/r8/c0", rect: [40, 600, 200, 30] }],
    },
    changes: [],
  });
  const resolved = pageModel.resolveSeatPages(projection.seats(), engineSourcePage2, "ko");
  const phoneSeat = resolved.find((s) => s.address === "t0/r8/c0");
  const coopSeat = resolved.find((s) => s.address === "t0/r5/c1");
  assert.ok(phoneSeat && coopSeat);
  assert.equal(phoneSeat.page, 2);
  assert.equal(phoneSeat.locationLabel, "2쪽 · 표 1 9행 1열");
  assert.equal(phoneSeat.cellLocationLabel, "9행 1열");
  assert.equal(coopSeat.page, null);
  assert.equal(coopSeat.locationLabel, "표 1 6행 2열");
  assert.equal(coopSeat.cellLocationLabel, "6행 2열");
  assert.equal(wp3.wp3t("seat_location_cell", "ko", [6, 2]), "6행 2열");

  // 5. BlanksPane component renders non-focusable (page, table) headings and short cell locations.
  const hookReact = createHookRunner();
  const storeWithHook = {
    ...loadWp3Stack().store,
    useWorkspace: (sel) => sel(loadWp3Stack().store.getState()),
  };
  let publishedSource = null;
  let knownPages = new Map();
  let lastSlicePatch = null;
  const { BlanksPane } = loadTsModule("src/panes/BlanksPane.tsx", {
    react: hookReact,
    "../i18n/v2/wp3": wp3,
    "../model/page": pageModel,
    "../store": storeWithHook,
    "../workspace/externalPlan": { buildRegionTextMap: () => textMap },
    "../shell/shellState": { getShell: () => ({ breakpoint: "wide" }), setShell: () => {} },
    "../canvas/changes": { useCanvasChanges: () => [] },
    "../canvas/actions": { beginCellEditV2: () => true },
    "../canvas/controller": {
      usePublishedKnownPages: () => knownPages,
      scrollCanvasToTarget: () => {},
      setCanvasSlice: (patch) => {
        lastSlicePatch = patch;
      },
      useCanvasSlice: () => ({ selectedSeatKey: null, hoveredSeatKey: null }),
      usePublishedPageSource: () => publishedSource,
    },
    "./panes.css": {},
  });

  const collectTestNodes = (node, acc = []) => {
    if (!node || typeof node !== "object") return acc;
    if (Array.isArray(node)) {
      for (const child of node) collectTestNodes(child, acc);
      return acc;
    }
    if (node.props) {
      acc.push(node);
      collectTestNodes(node.props.children, acc);
    }
    return acc;
  };

  // Unknown-page render: single group heading shows "표 1" with role="presentation", rows show short "6행 2열".
  const unknownTree = hookReact.renderWith("blanks-unknown", () => BlanksPane());
  const unknownNodes = collectTestNodes(unknownTree);
  const unknownHeadings = unknownNodes.filter(
    (n) => n.props["data-testid"] === "blanks-group-heading",
  );
  assert.deepEqual(
    unknownHeadings.map((n) => n.props.children),
    ["표 1"],
  );
  for (const h of unknownHeadings) {
    assert.equal(h.props.role, "presentation");
    assert.equal(h.props.tabIndex, undefined);
  }
  const coopBtnUnknown = unknownNodes.find(
    (n) => n.props["data-testid"] === "blank-seat-t0/r5/c1",
  );
  assert.ok(coopBtnUnknown);
  const coopLocUnknown = collectTestNodes(coopBtnUnknown).find(
    (n) => typeof n.props.className === "string" && n.props.className.includes("rl-blank-loc"),
  );
  assert.equal(coopLocUnknown.props.children, "6행 2열");
  coopBtnUnknown.props.onMouseEnter();
  assert.equal(lastSlicePatch.hoveredSeatLabel, "협조자 1 · 표 1 6행 2열");

  // Known-page render via engine page source: headings include real page numbers ("1쪽 · 표 1", "2쪽 · 표 1").
  publishedSource = engineSourcePage2;
  knownPages = new Map([
    ["t0/r5/c1", 1],
    ["t0/r8/c0", 2],
  ]);
  const knownTree = hookReact.renderWith("blanks-known", () => BlanksPane());
  const knownNodes = collectTestNodes(knownTree);
  const knownHeadings = knownNodes.filter(
    (n) => n.props["data-testid"] === "blanks-group-heading",
  );
  assert.ok(knownHeadings.some((n) => n.props.children === "1쪽 · 표 1"));
  assert.ok(knownHeadings.some((n) => n.props.children === "2쪽 · 표 1"));
  const coopBtnKnown = knownNodes.find(
    (n) => n.props["data-testid"] === "blank-seat-t0/r5/c1",
  );
  coopBtnKnown.props.onMouseEnter();
  assert.equal(lastSlicePatch.hoveredSeatLabel, "협조자 1 · 1쪽 · 표 1 6행 2열");
});

test("beginCellEditV2 opens static/guide cells without refusal and commits only on explicit commit", async () => {
  const stack = loadWp3Stack();
  const { upsertCalls } = stack;

  // Clicking a guide cell (t0, r0, c0) must open editor cleanly with zero refusal notice
  const openedGuide = stack.actions.beginCellEditV2(0, 0, 0);
  assert.equal(openedGuide, true);
  assert.ok(stack.store.getState().inlineEdit);
  assert.equal(stack.controller.getCanvasSlice().statusNotice, null);
  assert.equal(upsertCalls.length, 0); // zero network/queue writes while editing

  // Reopen blank fill target (t0, r2, c0) which has scriptAnomaly -> auto charPrSuggested
  const openedBlank = stack.actions.beginCellEditV2(0, 2, 0);
  assert.equal(openedBlank, true);
  assert.equal(stack.store.getState().inlineEdit.charPr, "23");
  assert.equal(upsertCalls.length, 0);

  const commitRes = await stack.actions.commitCellEditV2("가온공공기록원 본문");
  assert.equal(commitRes.committed, true);
  assert.equal(commitRes.bodyStyleMatched, true);
  assert.equal(upsertCalls.length, 1);
  assert.equal(upsertCalls[0].origin, "user");
  assert.equal(upsertCalls[0].kind, "fill_cell");
  assert.equal(upsertCalls[0].charPr, "23");

});

test("a cell edit inside one run of a mixed cell queues an edit of that run only", async () => {
  const stack = loadWp3Stack();
  const { upsertCalls } = stack;
  stack.actions.beginCellEditV2(0, 0, 0);
  const before = stack.store.getState().inlineEdit.before;
  assert.ok(before.length > 4);
  // Split the cell's text into three runs; the last one is the "blue note".
  const cut = [2, before.length - 2];
  const runs = [before.slice(0, cut[0]), before.slice(cut[0], cut[1]), before.slice(cut[1])]
    .map((text, index) => ({ index, text }));
  stack.cellRuns.regions = [{ table: 0, addr: { row: 0, col: 0 }, text: before, runs }];

  const after = before.slice(0, cut[0] + 1) + "X" + before.slice(cut[0] + 1);
  const res = await stack.actions.commitCellEditV2(after);
  assert.equal(res.committed, true);
  const op = upsertCalls[upsertCalls.length - 1];
  assert.equal(op.kind, "replace_at_cell");
  assert.equal(op.run, 1);
  assert.equal(op.mode, "replace");
  assert.equal(op.expect, runs[1].text);
  assert.equal(op.before, before);
  assert.equal(op.text, runs[1].text.slice(0, 1) + "X" + runs[1].text.slice(1));
  assert.equal(op.runStart, cut[0]);
  // The editor and the preview see the whole cell.
  const enginePage = loadTsModule("src/model/enginePage.ts");
  assert.equal(enginePage.queuedCellText(op), after);
  assert.deepEqual(enginePage.engineTextEdit(op), [{ at: "t0/r0/c0", before, text: after }]);

  // A change across two runs stays a whole-cell edit.
  stack.actions.beginCellEditV2(0, 0, 0);
  const across = before.slice(0, 1) + "Y" + before.slice(cut[1] + 1);
  await stack.actions.commitCellEditV2(across);
  const wide = upsertCalls[upsertCalls.length - 1];
  assert.equal(wide.run, undefined);
  assert.equal(wide.text, across);
});

test("lines typed under a label printed at the top of a cell queue a fill under that label", async () => {
  const stack = loadWp3Stack();
  const { upsertCalls } = stack;
  stack.actions.beginCellEditV2(0, 0, 0);
  const before = stack.store.getState().inlineEdit.before;
  assert.ok(before.trim() && !before.includes("\n"));

  // Without a label at the top, a new line is an edit of the cell's own text.
  let res = await stack.actions.commitCellEditV2(`${before}\n홍길동`);
  assert.equal(res.committed, true);
  assert.equal(upsertCalls[upsertCalls.length - 1].kind, "replace_at_cell");
  assert.equal(upsertCalls[upsertCalls.length - 1].belowLabel, undefined);

  const state = stack.store.getState();
  const sid = state.activeSessionId;
  const inspect = structuredClone(state.inspects[sid]);
  const cell = inspect.graph.tables[0].cells.find((c) => c.addr.row === 0 && c.addr.col === 0);
  cell.labelTop = { paras: 1, lines: 1, reserved: false };
  stack.store.setState({ inspects: { ...state.inspects, [sid]: inspect } });
  stack.actions.beginCellEditV2(0, 0, 0);
  res = await stack.actions.commitCellEditV2(`${before}\n홍길동`);
  assert.equal(res.committed, true);
  assert.equal(res.modeLabelKey, "fill_cell");
  const op = upsertCalls[upsertCalls.length - 1];
  assert.equal(op.kind, "fill_cell");
  assert.deepEqual(op.belowLabel, { label: before, previous: "" });
  assert.equal(op.text, `${before}\n홍길동`);
  assert.equal(op.before, before);
  assert.equal(op.overwrite, undefined);

  // Typing on the label's own line stays an edit of the cell's text.
  stack.actions.beginCellEditV2(0, 0, 0);
  await stack.actions.commitCellEditV2(`${before} 홍길동`);
  const same = upsertCalls[upsertCalls.length - 1];
  assert.equal(same.kind, "replace_at_cell");
  assert.equal(same.belowLabel, undefined);
});

test("a cell whose text is only a cut-short preview opens for editing once its whole text is read", async () => {
  const stack = loadWp3Stack();
  const state = stack.store.getState();
  const sid = state.activeSessionId;
  const full = "가온공공기록원 기록관리과 전자기록 담당 주무관 연락처 044-000-0000";
  // The graph holds only the first part of the cell, and no region was read.
  const inspect = structuredClone(state.inspects[sid]);
  const cell = inspect.graph.tables[0].cells.find((c) => c.addr.row === 1 && c.addr.col === 0);
  Object.assign(cell, { textPreview: full.slice(0, 12), truncated: true });
  stack.store.setState({
    inspects: { ...state.inspects, [sid]: inspect },
    texts: { ...state.texts, [sid]: state.texts[sid].filter((r) => !(r.table === 0 && r.addr?.row === 1 && r.addr?.col === 0)) },
  });
  stack.cellRuns.regions = [{ table: 0, addr: { row: 1, col: 0 }, text: full, runs: [{ index: 0, text: full }] }];

  assert.equal(stack.actions.beginCellEditV2(0, 1, 0), true);
  // No editor on the preview: it would write the preview over the rest.
  assert.equal(stack.store.getState().inlineEdit, null);
  assert.equal(stack.controller.getCanvasSlice().statusNotice, stack.wp3.wp3t("cell_text_loading", "ko"));
  await new Promise((resolve) => setTimeout(resolve, 0));
  const edit = stack.store.getState().inlineEdit;
  assert.equal(edit?.kind, "cell");
  assert.equal(edit.before, full);
  assert.equal(stack.controller.getCanvasSlice().statusNotice, null);

  // A cell that cannot be read does not open, and says why.
  stack.store.setState({ inlineEdit: null });
  stack.cellRuns.regions = [];
  stack.actions.beginCellEditV2(0, 1, 0);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(stack.store.getState().inlineEdit, null);
  assert.equal(stack.controller.getCanvasSlice().statusNotice, stack.wp3.wp3t("cell_text_unread", "ko"));
});

test("find replacement and cell edits upsert the same address", async () => {
  const stack = loadWp3Stack();
  const match = {
    id: "c:0:1:0",
    targetType: "cell",
    cellKey: "c:0:1:0",
    table: 0,
    row: 1,
    col: 0,
    label: "기관명",
    locationLabel: "표 1 2행 1열",
    text: "가온공공기록원",
    matchStart: 0,
    matchEnd: 2,
  };
  const state = stack.store.getState();
  state.texts[state.activeSessionId] = [
    { table: 0, addr: { row: 1, col: 0 }, text: match.text },
    ...corpus.regions.filter((r) => !(r.table === 0 && r.addr?.row === 1 && r.addr?.col === 0)),
  ];
  const ok = await stack.actions.replaceFindMatch(match, "가온", "한울");
  assert.equal(ok, true);
  assert.equal(stack.queuedOps.length, 1);
  assert.equal(stack.queuedOps[0].origin, "user");
  assert.equal(stack.queuedOps[0].text, "한울공공기록원");

  const id = stack.queuedOps[0].opId;
  await stack.actions.replaceAllFindMatches(
    [{ ...match, text: "한울공공기록원" }],
    "한울",
    "새움",
  );
  assert.equal(stack.queuedOps.length, 1);
  assert.equal(stack.queuedOps[0].text, "새움공공기록원");
  assert.equal(stack.queuedOps[0].expect, match.text);

  stack.actions.beginCellEditV2(0, 1, 0);
  await stack.actions.commitCellEditV2("마루공공기록원");
  assert.equal(stack.queuedOps.length, 1);
  assert.equal(stack.queuedOps[0].opId, id);
  assert.equal(stack.queuedOps[0].text, "마루공공기록원");
  assert.equal(stack.queuedOps[0].before, match.text);

});

test("IME composition & editable-target guard block Y/N/E/U/J/K/V during Hangul composition", () => {
  const stack = loadWp3Stack();
  stack.controller.publishCanvasContext(
    [
      {
        id: "op-1",
        n: 1,
        at: "t0/r1/c0",
        kind: "replace_at_cell",
        opKind: "replace_at_cell",
        label: "기관명",
        before: "행 정 기 관 명",
        after: "가온공공기록원",
        page: 1,
        source: "agent",
        decision: "pending",
        contentHash: "reviewed",
        guard: "none",
        hard: false,
        isFactChanged: false,
        isStale: false,
      },
      {
        id: "op-2",
        n: 2,
        at: "t0/r2/c0",
        kind: "fill_cell",
        opKind: "fill_cell",
        label: "본문",
        before: "",
        after: "내용",
        page: 1,
        source: "agent",
        decision: "pending",
        contentHash: "reviewed",
        guard: "none",
        hard: false,
        isFactChanged: false,
        isStale: false,
      },
    ],
    null,
  );
  stack.controller.canvas.select("op-1");

  // During IME composition (isComposing: true or keyCode: 229), all shortcuts must return null
  for (const code of ["KeyY", "KeyN", "KeyE", "KeyU", "KeyJ", "KeyK", "KeyV"]) {
    assert.equal(
      stack.keys.dispatch({ code, isComposing: true }),
      false,
      `Expected ${code} blocked when isComposing=true`,
    );
    assert.equal(
      stack.keys.dispatch({ code, keyCode: 229 }),
      false,
      `Expected ${code} blocked when keyCode=229`,
    );
  }
  assert.equal(stack.controller.getCanvasSlice().view, "marks");

  // Single keys must be blocked inside TEXTAREA/INPUT while Ctrl+F still works
  assert.equal(
    stack.keys.dispatch({ code: "KeyV", target: { tagName: "TEXTAREA" } }),
    false,
  );
  assert.equal(
    stack.keys.dispatch({
      code: "KeyF",
      ctrlKey: true,
      target: { tagName: "TEXTAREA" },
    }),
    true,
  );

  // Physical KeyV (even with Korean key:"ㅍ") cycles view marks -> clean -> base
  assert.equal(
    stack.keys.dispatch({ code: "KeyV", key: "ㅍ" }),
    true,
  );
  assert.equal(stack.controller.getCanvasSlice().view, "clean");
  stack.keys.dispatch({ code: "KeyV" });
  assert.equal(stack.controller.getCanvasSlice().view, "base");

  stack.controller.canvas.setView("marks");

  // KeyY accepts op-1 & advances to op-2; Ctrl+Z undoes decision back to pending on op-1
  assert.equal(
    stack.keys.dispatch({ code: "KeyY", key: "ㅛ" }),
    true,
  );
  assert.equal(stack.controller.getCanvasSlice().decisions["op-1"].decision, "accepted");
  assert.equal(stack.controller.getCanvasSlice().selectedChangeId, "op-2");
  assert.equal(
    stack.keys.dispatch({ code: "KeyZ", ctrlKey: true }),
    true,
  );
  assert.equal(stack.controller.getCanvasSlice().decisions["op-1"], undefined);
  assert.equal(stack.controller.getCanvasSlice().selectedChangeId, "op-1");

  stack.registerMod.unregisterCanvasModule();
});

test("canvas and the mounted panel never own the same review key", () => {
  const { bindings, controller, keys, keymap, shell, slots, commands, changeModel, registerMod } = loadWp3Stack();
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  globalThis.window = { addEventListener() {}, removeEventListener() {} };
  let modal = false;
  const doc = { activeElement: null, querySelector: () => modal ? {} : null };
  globalThis.document = doc;
  const focus = (testId) => {
    doc.activeElement = { closest: (selector) => selector.includes(`[data-testid="${testId}"]`) };
  };
  const change = { id: "change-1", decision: "pending", contentHash: "reviewed" };
  const calls = [];
  const action = (id) => () => { calls.push(id); };
  const off = bindings.installShellBindings();
  try {
    loadTsModule("src/panel/register.ts", {
      "./panel.css": {},
      react: React,
      "../components/OperatorAgentModal": {},
      "../i18n/v2/shell": {},
      "../model/changes": changeModel,
      "../shell/bindings": bindings,
      "../shell/commands": commands,
      "../shell/keymap": keymap,
      "../shell/keys": keys,
      "../shell/shellState": shell,
      "../shell/slots": slots,
      "./actions": {
        step: (delta) => calls.push(delta > 0 ? "J" : "K"),
        decide: (_id, decision) => calls.push(decision === "accepted" ? "Y" : "N"),
        selectedId: () => change.id,
        undoDecision: action("U"),
      },
      "./ChangeItemRow": { requestEdit: action("E") },
      "./i18n": {},
      "./RightPanel": {},
      "./state": {
        latestView: (session) => session ? { items: [change] } : null,
        panelSlice: { get: () => ({ sheetOpen: false }) },
      },
    });
    assert.equal(slots.hasSlot("rightPanel"), true);
    assert.equal(slots.hasSlot("narrowSheet"), true);
    controller.publishCanvasContext([change], null);
    controller.canvas.select(change.id);

    for (const id of ["canvas-scroll", "composer-input", "panel-tab-agent", "change-list", "approve-sheet", "return-popover"]) {
      focus(id);
      assert.deepEqual(keys.activeConflicts(), [], id);
    }
    focus("change-list");
    for (const letter of ["J", "K", "Y", "N", "E", "U"]) {
      assert.equal(keys.dispatch({ code: `Key${letter}` }), true);
    }
    assert.deepEqual(calls, ["J", "K", "Y", "N", "E", "U"]);
    focus("canvas-scroll");
    assert.equal(keys.dispatch({ code: "KeyN" }), true);
    assert.equal(controller.getCanvasSlice().decisions[change.id].decision, "rejected");
    assert.equal(calls.length, 6);

    focus("change-list");
    for (const overlay of ["paletteOpen", "settingsOpen", "appMenuOpen", "tabListOpen", "narrowDrawerOpen"]) {
      shell.setShell({ [overlay]: true });
      assert.deepEqual(keys.activeConflicts(), [], overlay);
      assert.equal(keys.dispatch({ code: "KeyN" }), false, overlay);
      shell.setShell({ [overlay]: false });
    }
    modal = true;
    for (const id of ["change-list", "canvas-scroll"]) {
      focus(id);
      assert.equal(keys.dispatch({ code: "KeyN" }), false, id);
      assert.equal(keys.dispatch({ code: "Enter", ctrlKey: true, shiftKey: true }), false, id);
    }
    modal = false;
    shell.setShell({ activeTab: "start" });
    assert.deepEqual(keys.activeConflicts(), []);
    assert.equal(keys.dispatch({ code: "KeyN" }), false);
  } finally {
    off();
    registerMod.unregisterCanvasModule();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});

test("change source and decision come from the operation, plan and decision flags", () => {
  const { changes, changeModel } = loadWp3Stack();
  const input = [
    { opId: "agent", origin: "agent", proposer: "시험용" },
    { opId: "test", origin: "user" },
    { opId: "user", origin: "user" },
    { opId: "flag", origin: "agent", provenance: "mock" },
  ].map((op, index) => ({
    op: { ...op, kind: "fill_cell", table: 0, row: index, col: 0 },
    opId: op.opId,
    beforeText: "",
    afterText: "내용",
  }));
  const options = { plan: { provenance: "mock", mockOps: ["test"] }, isStale: true };
  const audits = { flag: { status: "changed" } };
  const [, testChange, userChange] = changes.indexedChangesToCanvasRefs(input, audits, {}, options);
  const decisions = changeModel.recordDecision(changeModel.recordDecision({}, testChange, "accepted"), userChange, "rejected");
  const projected = changes.indexedChangesToCanvasRefs(input, audits, decisions, options);
  const rewritten = input.map((item) => item.opId === "test" ? { ...item, afterText: "수정된 내용" } : item);
  assert.equal(changes.indexedChangesToCanvasRefs(rewritten, audits, decisions, options)[1].decision, "pending");
  assert.deepEqual(projected.map(({ source }) => source), ["agent", "test", "user", "test"]);
  assert.deepEqual(projected.map(({ decision }) => decision), ["pending", "accepted", "rejected", "pending"]);
  assert.equal(projected[3].isFactChanged, true);
  assert.equal(projected[3].isStale, true);
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

test("changing operation formatting or flags invalidates a shared decision", () => {
  const { changes, changeModel } = loadWp3Stack();
  const op = { opId: "change", kind: "fill_cell", table: 0, row: 1, col: 0, text: "Value", origin: "agent" };
  const project = (op, decisions = {}) => changes.indexedChangesToCanvasRefs(
    [{ op, opId: op.opId, beforeText: "", afterText: op.text }], {}, decisions, {},
  )[0];
  const decisions = changeModel.recordDecision({}, project(op), "accepted");
  assert.equal(project(op, decisions).decision, "accepted");
  for (const params of [{ charPr: "17" }, { paraPr: "4" }, { overwrite: true }, { lines: ["Value"] }]) {
    assert.equal(project({ ...op, ...params }, decisions).decision, "pending");
  }
  const replace = { ...op, kind: "replace_at_cell", mode: "replace", run: 0 };
  const replaceDecisions = changeModel.recordDecision({}, project(replace), "accepted");
  assert.equal(project({ ...replace, expect: "Original" }, replaceDecisions).decision, "pending");
});

function createHookRunner({ runEffects = false } = {}) {
  const slots = new Map();
  let currentKey = "default";
  let stateCursor = 0;
  let refCursor = 0;
  let effectCursor = 0;
  const bucket = () => {
    if (!slots.has(currentKey)) {
      slots.set(currentKey, { states: [], refs: [], effects: [], pendingEffects: null, dirty: false });
    }
    return slots.get(currentKey);
  };
  return {
    ...React,
    reset(key) {
      slots.delete(key);
    },
    renderWith(key, fn) {
      const prevKey = currentKey;
      const prevState = stateCursor;
      const prevRef = refCursor;
      const prevEffect = effectCursor;
      currentKey = key;
      try {
        const b = bucket();
        let result;
        do {
          b.dirty = false;
          stateCursor = 0;
          refCursor = 0;
          effectCursor = 0;
          const pendingEffects = [];
          b.pendingEffects = pendingEffects;
          result = fn();
          b.pendingEffects = null;
          for (const effect of pendingEffects) effect();
        } while (runEffects && b.dirty);
        return result;
      } finally {
        currentKey = prevKey;
        stateCursor = prevState;
        refCursor = prevRef;
        effectCursor = prevEffect;
      }
    },
    useState(initial) {
      const b = bucket();
      const idx = stateCursor++;
      if (!(idx in b.states)) {
        b.states[idx] = typeof initial === "function" ? initial() : initial;
      }
      const set = (next) => {
        const value = typeof next === "function" ? next(b.states[idx]) : next;
        if (!Object.is(value, b.states[idx])) {
          b.states[idx] = value;
          b.dirty = true;
        }
      };
      return [b.states[idx], set];
    },
    useRef(initial) {
      const b = bucket();
      const idx = refCursor++;
      if (!(idx in b.refs)) {
        b.refs[idx] = { current: initial };
      }
      return b.refs[idx];
    },
    useMemo(fn) {
      return fn();
    },
    useEffect(fn, deps) {
      if (!runEffects) return;
      const b = bucket();
      const idx = effectCursor++;
      const prev = b.effects[idx];
      const changed =
        !prev ||
        !deps ||
        !prev.deps ||
        deps.length !== prev.deps.length ||
        deps.some((d, i) => !Object.is(d, prev.deps[i]));
      if (changed) {
        b.effects[idx] = { deps };
        b.pendingEffects?.push(fn);
      }
    },
  };
}

test("SeatEditor and EngineEditOverlay preserve the next blur commit when Tab cannot move", () => {
  const stack = loadWp3Stack();
  const previousWindow = globalThis.window;
  globalThis.window = { clearTimeout, setTimeout };
  try {
    const hookReact = createHookRunner();
    const storeWithHook = {
      ...stack.store,
      useWorkspace: (sel) => sel(stack.store.getState()),
    };
    const vocabulary = loadTsModule("src/i18n/vocabulary.ts");
    const canvasSeatMod = loadTsModule("src/canvas/SeatEditor.tsx", {
      react: hookReact,
      "../i18n/v2/wp3": stack.wp3,
      "../store": storeWithHook,
    });
    const componentsSeatMod = loadTsModule("src/components/SeatEditor.tsx", {
      react: hookReact,
      "../i18n/vocabulary": vocabulary,
      "../store": storeWithHook,
    });

    const tabEvent = () => ({
      key: "Tab",
      shiftKey: false,
      keyCode: 9,
      nativeEvent: { isComposing: false },
      preventDefault() {},
      stopPropagation() {},
    });

    for (const [label, SeatEditor] of [
      ["canvas/SeatEditor", canvasSeatMod.SeatEditor],
      ["components/SeatEditor", componentsSeatMod.SeatEditor],
    ]) {
      // 1. When onCycleBlank returns false, Tab did not move so the next blur must commit.
      const refusedCommits = [];
      const refusedCycles = [];
      const refusedEl = hookReact.renderWith(`${label}-refused`, () =>
        SeatEditor({
          value: "기록정책담당관",
          onCommit: (next, reason) => refusedCommits.push([next, reason]),
          onCancel: () => {},
          onCycleBlank: (dir, cur) => {
            refusedCycles.push([dir, cur]);
            return false;
          },
        }),
      );
      refusedEl.props.onKeyDown(tabEvent());
      assert.deepEqual(refusedCycles, [[1, "기록정책담당관"]], label);
      refusedEl.props.onBlur();
      assert.deepEqual(refusedCommits, [["기록정책담당관", "blur"]], label);

      // 2. When onCycleBlank returns nothing (void), blur does not commit.
      const movedCommits = [];
      const movedCycles = [];
      const movedEl = hookReact.renderWith(`${label}-moved`, () =>
        SeatEditor({
          value: "기록정책담당관",
          onCommit: (next, reason) => movedCommits.push([next, reason]),
          onCancel: () => {},
          onCycleBlank: (dir, cur) => {
            movedCycles.push([dir, cur]);
          },
        }),
      );
      movedEl.props.onKeyDown(tabEvent());
      assert.deepEqual(movedCycles, [[1, "기록정책담당관"]], label);
      movedEl.props.onBlur();
      assert.deepEqual(movedCommits, [], label);
    }

    // 3. EngineEditOverlay: refused submit on Tab returns false and lets the subsequent blur commit.
    const enginePage = loadTsModule("src/model/enginePage.ts", {
      "./page": stack.pageModel,
    });
    const { useEngineEditOverlay } = loadTsModule("src/canvas/EngineEditOverlay.tsx", {
      react: hookReact,
      "../actions": {
        cancelEdit: () => stack.store.setState({ inlineEdit: null }),
        setInlineEditMultiline: () => {},
      },
      "../model/enginePage": enginePage,
      "../model/page": stack.pageModel,
      "../run_map": { locateSpanInRuns: () => ({ kind: "refused" }) },
      "../revision": { runTextAfterEdit: (_edit, val) => val },
      "../runtime": { readRegion: async () => ({ subject: null, regions: [] }) },
      "../store": storeWithHook,
      "./actions": stack.actions,
      "./SeatEditor": canvasSeatMod,
    });

    stack.actions.beginCellEditV2(0, 5, 1);
    const lineBox = {
      at: "t0/r5/c1/p0#L0",
      kind: "line",
      rect: [10, 10, 80, 16],
      text: "",
    };
    const staleGeometry = {
      page: 1,
      rev: "stale-geometry-rev",
      widthPt: 595,
      heightPt: 842,
      boxes: [lineBox],
    };
    const cycled = [];
    const renderOverlay = (geometry) =>
      hookReact.renderWith("engine-overlay", () =>
        useEngineEditOverlay({
          sessionId: "sess-1",
          geometry,
          editable: true,
          isNarrow: false,
          settled: true,
          displayedEdits: [],
          inspect: corpus.inspect,
          hit: null,
          onCycleCell: (t, r, c, dir) => cycled.push([t, r, c, dir]),
        }),
      );

    let overlay = renderOverlay(staleGeometry);
    assert.ok(overlay.editor);
    let input = hookReact.renderWith("engine-seat", () =>
      overlay.editor.type(overlay.editor.props),
    );
    input.props.onChange({ target: { value: "기록정책담당관" } });
    overlay = renderOverlay(staleGeometry);
    input = hookReact.renderWith("engine-seat", () =>
      overlay.editor.type(overlay.editor.props),
    );

    // Tab while geometry.rev !== head: submit returns false, editor does not cycle.
    assert.equal(overlay.editor.props.onCycleBlank(1, "기록정책담당관"), false);
    input.props.onKeyDown(tabEvent());
    assert.deepEqual(cycled, []);
    assert.equal(stack.upsertCalls.length, 0);

    // Once geometry catches up to session head, blurring the still-open editor commits.
    const headGeometry = { ...staleGeometry, rev: corpus.source.sha256 };
    overlay = renderOverlay(headGeometry);
    input = hookReact.renderWith("engine-seat", () =>
      overlay.editor.type(overlay.editor.props),
    );
    input.props.onBlur();
    assert.equal(stack.upsertCalls.length, 1);
    assert.equal(stack.upsertCalls[0].text, "기록정책담당관");

    // When submit succeeds on Tab, EngineEditOverlay cycles to the next cell and returns true.
    stack.actions.beginCellEditV2(0, 5, 1);
    overlay = renderOverlay(headGeometry);
    assert.equal(overlay.editor.props.onCycleBlank(1, "기록정책담당관"), true);
    assert.deepEqual(cycled, [[0, 5, 1, 1]]);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});

test("EngineEditOverlay keeps the inline editor open on idle commit settle and closes on explicit commit", () => {
  const stack = loadWp3Stack();
  const previousWindow = globalThis.window;
  let pendingTimer = null;
  globalThis.window = {
    clearTimeout: (id) => {
      if (pendingTimer && pendingTimer.id === id) pendingTimer = null;
    },
    setTimeout: (fn) => {
      const id = (pendingTimer?.id ?? 0) + 1;
      pendingTimer = { id, fn };
      return id;
    },
  };
  const flushIdleTimer = () => {
    const timer = pendingTimer;
    assert.ok(timer, "Expected idle commit timer to be scheduled");
    pendingTimer = null;
    timer.fn();
  };

  try {
    const hookReact = createHookRunner({ runEffects: true });
    const storeWithHook = {
      ...stack.store,
      useWorkspace: (sel) => sel(stack.store.getState()),
    };
    const canvasSeatMod = loadTsModule("src/canvas/SeatEditor.tsx", {
      react: hookReact,
      "../i18n/v2/wp3": stack.wp3,
      "../store": storeWithHook,
    });
    const enginePage = loadTsModule("src/model/enginePage.ts", {
      "./page": stack.pageModel,
    });
    let cancelCalls = 0;
    const { useEngineEditOverlay } = loadTsModule("src/canvas/EngineEditOverlay.tsx", {
      react: hookReact,
      "../actions": {
        cancelEdit: () => {
          cancelCalls += 1;
          stack.store.setState({ inlineEdit: null });
        },
        setInlineEditMultiline: () => {},
      },
      "../model/enginePage": enginePage,
      "../model/page": stack.pageModel,
      "../run_map": { locateSpanInRuns: () => ({ kind: "refused" }) },
      "../revision": { runTextAfterEdit: (_edit, val) => val },
      "../runtime": { readRegion: async () => ({ subject: null, regions: [] }) },
      "../store": storeWithHook,
      "./actions": stack.actions,
      "./SeatEditor": canvasSeatMod,
    });

    const headGeometry = {
      page: 1,
      rev: corpus.source.sha256,
      widthPt: 595,
      heightPt: 842,
      boxes: [
        {
          at: "t0/r0/c0/p0#L0",
          kind: "line",
          rect: [10, 4, 240, 12],
          text: "■ 행정업무의 운영 및 혁신에 관한 규정 시행규칙",
        },
        {
          at: "t0/r5/c1/p0#L0",
          kind: "line",
          rect: [10, 10, 80, 16],
          text: "",
        },
      ],
    };
    const regionHeightPt = 9;
    const guideHeightPt = 8;
    assert.notEqual(regionHeightPt, corpus.inspect.summary.baselineCharPr.height_pt);
    const inspectWithRegionHeight = {
      ...corpus.inspect,
      graph: {
        ...corpus.inspect.graph,
        tables: corpus.inspect.graph.tables.map((t) =>
          t.index === 0
            ? {
                ...t,
                cells: t.cells.map((c) =>
                  c.addr.row === 0 && c.addr.col === 0
                    ? {
                        ...c,
                        textCharPr: "9",
                        textCharPrFace: { hangul: "돋움" },
                        textCharPrHeightPt: guideHeightPt,
                      }
                    : c,
                ),
              }
            : t,
        ),
      },
      regions: {
        ...corpus.inspect.regions,
        regions: corpus.inspect.regions.regions.map((region) =>
          region.table === 0 && region.row === 5 && region.col === 1
            ? { ...region, charPrHeightPt: regionHeightPt }
            : region,
        ),
      },
    };
    const renderOverlay = (settled) => {
      const res = hookReact.renderWith("engine-overlay", () =>
        useEngineEditOverlay({
          sessionId: "sess-1",
          geometry: headGeometry,
          editable: true,
          isNarrow: false,
          settled,
          displayedEdits: [],
          inspect: inspectWithRegionHeight,
          hit: null,
          onCycleCell: () => {},
        }),
      );
      if (!res.editor) hookReact.reset("engine-seat");
      return res;
    };
    const renderInput = (overlay) =>
      hookReact.renderWith("engine-seat", () =>
        overlay.editor.type(overlay.editor.props),
      );
    const enterEvent = () => ({
      key: "Enter",
      shiftKey: false,
      ctrlKey: false,
      metaKey: false,
      keyCode: 13,
      nativeEvent: { isComposing: false },
      preventDefault() {},
      stopPropagation() {},
    });

    // 1. idle commit + preview settles with unchanged value -> editor stays open (cancelEdit not called).
    stack.actions.beginCellEditV2(0, 5, 1);
    let overlay = renderOverlay(true);
    assert.ok(overlay.editor);
    assert.equal(
      overlay.editor.props.style.fontSize,
      regionHeightPt * (96 / 72),
    );
    let input = renderInput(overlay);
    input.props.onChange({ target: { value: "기록정책담당관" } });
    input = renderInput(overlay);
    flushIdleTimer();
    overlay = renderOverlay(false);
    assert.ok(overlay.editor);
    overlay = renderOverlay(true);
    assert.equal(cancelCalls, 0);
    assert.ok(stack.store.getState().inlineEdit);
    assert.ok(overlay.editor);

    // 2. explicit commit (Enter) + settle -> editor closes; while unsettled, pending span matches editor fontSize.
    input = renderInput(overlay);
    input.props.onChange({ target: { value: "기록정책담당관 수정" } });
    input = renderInput(overlay);
    input.props.onKeyDown(enterEvent());
    overlay = renderOverlay(false);
    assert.equal(overlay.pending.length, 1);
    assert.equal(
      overlay.pending[0].props.style.fontSize,
      regionHeightPt * (96 / 72),
    );
    overlay = renderOverlay(true);
    assert.equal(stack.store.getState().inlineEdit, null);
    assert.equal(overlay.editor, null);

    // 3. idle commit, then Enter with the same value (dedupe path), then settle -> editor closes.
    stack.actions.beginCellEditV2(0, 5, 1);
    overlay = renderOverlay(true);
    assert.ok(overlay.editor);
    input = renderInput(overlay);
    input.props.onChange({ target: { value: "기획조정실" } });
    input = renderInput(overlay);
    flushIdleTimer();
    overlay = renderOverlay(false);
    assert.ok(overlay.editor);
    cancelCalls = 0;
    input = renderInput(overlay);
    input.props.onKeyDown(enterEvent());
    overlay = renderOverlay(true);
    assert.equal(cancelCalls, 1);
    assert.equal(stack.store.getState().inlineEdit, null);
    assert.equal(overlay.editor, null);

    // 4. idle commit + settle, then Enter with the same value after it already settled -> editor closes (no hang).
    stack.actions.beginCellEditV2(0, 5, 1);
    overlay = renderOverlay(true);
    assert.ok(overlay.editor);
    input = renderInput(overlay);
    input.props.onChange({ target: { value: "운영지원과" } });
    input = renderInput(overlay);
    flushIdleTimer();
    overlay = renderOverlay(false);
    cancelCalls = 0;
    overlay = renderOverlay(true);
    assert.equal(cancelCalls, 0);
    assert.ok(stack.store.getState().inlineEdit);
    assert.ok(overlay.editor);
    input = renderInput(overlay);
    input.props.onKeyDown(enterEvent());
    overlay = renderOverlay(true);
    assert.equal(cancelCalls, 1);
    assert.equal(stack.store.getState().inlineEdit, null);
    assert.equal(overlay.editor, null);

    // 5. Non-fill cell (t0/r0/c0, not in inspect.regions) uses graph cell textCharPrFace and textCharPrHeightPt (8pt) for editor and pending span.
    stack.actions.beginCellEditV2(0, 0, 0, { inspect: inspectWithRegionHeight });
    overlay = renderOverlay(true);
    assert.ok(overlay.editor);
    assert.equal(overlay.editor.props.fontFace, "돋움");
    assert.equal(
      overlay.editor.props.style.fontSize,
      guideHeightPt * (96 / 72),
    );
    input = renderInput(overlay);
    input.props.onChange({ target: { value: "■ 수정된 서식 머리말" } });
    input = renderInput(overlay);
    input.props.onKeyDown(enterEvent());
    overlay = renderOverlay(false);
    assert.equal(overlay.pending.length, 1);
    assert.equal(
      overlay.pending[0].props.style.fontSize,
      guideHeightPt * (96 / 72),
    );
    assert.ok(overlay.pending[0].props.style.fontFamily.includes('"돋움"'));
    overlay = renderOverlay(true);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});

test("object-holding cells address lead paragraphs in preview and queue, and open read-only when every paragraph holds an object", async () => {
  const stack = loadWp3Stack();
  const previousWindow = globalThis.window;
  let pendingTimer = null;
  globalThis.window = {
    clearTimeout: (id) => {
      if (pendingTimer && pendingTimer.id === id) pendingTimer = null;
    },
    setTimeout: (fn) => {
      const id = (pendingTimer?.id ?? 0) + 1;
      pendingTimer = { id, fn };
      return id;
    },
  };

  try {
    const hookReact = createHookRunner({ runEffects: true });
    const storeWithHook = {
      ...stack.store,
      useWorkspace: (sel) => sel(stack.store.getState()),
    };
    const canvasSeatMod = loadTsModule("src/canvas/SeatEditor.tsx", {
      react: hookReact,
      "../i18n/v2/wp3": stack.wp3,
      "../store": storeWithHook,
    });
    const enginePage = loadTsModule("src/model/enginePage.ts", {
      "./page": stack.pageModel,
    });
    let cancelCalls = 0;
    const { useEngineEditOverlay } = loadTsModule("src/canvas/EngineEditOverlay.tsx", {
      react: hookReact,
      "../actions": {
        cancelEdit: () => {
          cancelCalls += 1;
          stack.store.setState({ inlineEdit: null });
        },
        setInlineEditMultiline: () => {},
      },
      "../i18n/v2/wp3": stack.wp3,
      "../model/enginePage": enginePage,
      "../model/page": stack.pageModel,
      "../run_map": { locateSpanInRuns: () => ({ kind: "refused" }) },
      "../revision": { runTextAfterEdit: (_edit, val) => val },
      "../runtime": { readRegion: async () => ({ subject: null, regions: [] }) },
      "../store": storeWithHook,
      "./actions": stack.actions,
      "./SeatEditor": canvasSeatMod,
    });

    // 1. t0/r2/c0 holds nested tables and lead paragraphs p0..p19: queued op has no `at`, engineTextEdit uses cell address.
    const openedBody = stack.actions.beginCellEditV2(0, 2, 0);
    assert.equal(openedBody, true);
    assert.equal(stack.store.getState().inlineEdit.leadPara, 0);
    assert.equal(stack.store.getState().inlineEdit.readOnly, undefined);
    const bodyCommit = await stack.actions.commitCellEditV2("붙임 자료를 보내 드립니다.");
    assert.equal(bodyCommit.committed, true);
    assert.equal(stack.upsertCalls.length, 1);
    assert.equal("at" in stack.upsertCalls[0], false);
    assert.equal(stack.upsertCalls[0].at, undefined);
    assert.deepEqual(enginePage.engineTextEdit(stack.upsertCalls[0]), [
      { at: "t0/r2/c0", text: "붙임 자료를 보내 드립니다." },
    ]);
    const bodyRef = stack.changes.indexedChangesToCanvasRefs(
      [{ op: stack.upsertCalls[0], opId: stack.upsertCalls[0].opId, beforeText: "", afterText: stack.upsertCalls[0].text }],
      {},
      {},
      {},
    )[0];
    assert.equal(bodyRef.at, "t0/r2/c0");

    // Multi-line edit in t0/r2/c0 also sends cell address t0/r2/c0 with no `at` on the queued op.
    stack.actions.beginCellEditV2(0, 2, 0);
    await stack.actions.commitCellEditV2("첫째 줄\n둘째 줄");
    const multiOp = stack.upsertCalls[stack.upsertCalls.length - 1];
    assert.equal("at" in multiOp, false);
    assert.equal(multiOp.at, undefined);
    assert.deepEqual(enginePage.engineTextEdit(multiOp), [
      { at: "t0/r2/c0", text: "첫째 줄\n둘째 줄" },
    ]);

    // 2. Object-only cell with no usable lead paragraph (leadPara: null, leadParas: []) opens read-only and sends no edit.
    const koMsg = stack.wp3.wp3t("cell_object_only_readonly", "ko");
    const enMsg = stack.wp3.wp3t("cell_object_only_readonly", "en");
    assert.ok(typeof koMsg === "string" && koMsg.length > 0 && koMsg !== enMsg);
    assert.ok(typeof enMsg === "string" && enMsg.length > 0);

    const objectOnlyInspect = {
      ...corpus.inspect,
      graph: {
        ...corpus.inspect.graph,
        tables: corpus.inspect.graph.tables.map((t) =>
          t.index === 0
            ? {
                ...t,
                cells: [
                  ...t.cells,
                  {
                    addr: { row: 31, col: 0 },
                    classification: "static",
                    textPreview: "",
                    truncated: false,
                    hasObject: true,
                    leadPara: null,
                    leadParas: [],
                  },
                ],
              }
            : t,
        ),
      },
    };
    stack.store.setState({ inspects: { "sess-1": objectOnlyInspect } });
    const beforeUpserts = stack.upsertCalls.length;

    const openedReadOnly = stack.actions.beginCellEditV2(0, 31, 0, { inspect: objectOnlyInspect });
    assert.equal(openedReadOnly, true);
    const roEdit = stack.store.getState().inlineEdit;
    assert.ok(roEdit);
    assert.equal(roEdit.readOnly, true);
    assert.equal(roEdit.readOnlyMessage, koMsg);

    const geometry = {
      page: 1,
      rev: corpus.source.sha256,
      widthPt: 595,
      heightPt: 842,
      boxes: [
        {
          at: "t0/r31/c0",
          kind: "cell",
          rect: [20, 40, 200, 32],
          text: "▣",
        },
      ],
    };
    const overlay = hookReact.renderWith("ro-overlay", () =>
      useEngineEditOverlay({
        sessionId: "sess-1",
        geometry,
        editable: true,
        isNarrow: false,
        settled: true,
        displayedEdits: [],
        inspect: objectOnlyInspect,
        hit: null,
        onCycleCell: () => {},
      }),
    );
    assert.ok(overlay.editor);
    assert.equal(overlay.editor.props.readOnly, true);
    assert.equal(overlay.editor.props.value, koMsg);

    const input = hookReact.renderWith("ro-seat", () =>
      overlay.editor.type(overlay.editor.props),
    );
    assert.equal(input.props.readOnly, true);
    assert.equal(input.props.value, koMsg);

    // Typing and Enter on read-only editor must not schedule idle timer or send any edit.
    input.props.onChange({ target: { value: "무시되어야 함" } });
    assert.equal(pendingTimer, null);
    assert.equal(stack.upsertCalls.length, beforeUpserts);

    const directCommit = await stack.actions.commitCellEditV2("무시되어야 함", {
      inspect: objectOnlyInspect,
      keepOpen: true,
    });
    assert.equal(directCommit.committed, false);
    assert.equal(stack.upsertCalls.length, beforeUpserts);

    input.props.onKeyDown({
      key: "Enter",
      shiftKey: false,
      ctrlKey: false,
      metaKey: false,
      keyCode: 13,
      nativeEvent: { isComposing: false },
      preventDefault() {},
      stopPropagation() {},
    });
    assert.equal(cancelCalls, 1);
    assert.equal(stack.store.getState().inlineEdit, null);
    assert.equal(stack.upsertCalls.length, beforeUpserts);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});

test("strip: the page source label never repeats the word the preview grade label starts with", () => {
  const stack = loadWp3Stack();
  for (const lang of ["ko", "en"]) {
    const grade = stack.wp3.wp3t("canvas_grade_preview", lang);
    const lead = grade.split(" · ")[0].trim().toLowerCase();
    for (const key of ["page_source_projection", "page_source_engine", "page_source_own", "page_source_hancom", "page_source_pdf"]) {
      const label = stack.wp3.wp3t(key, lang).toLowerCase();
      assert.ok(!label.includes(lead), `${key} (${lang}) "${label}" repeats "${lead}"`);
    }
  }
});

test("status bar character shape: cell region face and size, else graph cell text, else the body baseline", () => {
  const { pageModel, wp3 } = loadWp3Stack();
  const inspect = {
    summary: { baselineCharPr: { id: "0", height_pt: 10, signature: null, face: { hangul: "함초롬바탕" } } },
    graph: {
      documentHash: "h",
      sessionId: "s",
      paragraphs: [],
      tables: [
        {
          index: 0,
          cells: [
            {
              addr: { row: 0, col: 0 },
              classification: "fill_target",
              textCharPr: "9",
              textCharPrFace: { hangul: "돋움체" },
              textCharPrHeightPt: 8,
            },
            {
              addr: { row: 0, col: 2 },
              classification: "guide",
              textCharPr: "9",
              textCharPrFace: { hangul: "돋움체" },
              textCharPrHeightPt: 8,
            },
            {
              addr: { row: 0, col: 3 },
              classification: "static",
              textCharPr: "10",
              textCharPrFace: null,
              textCharPrHeightPt: 9,
            },
          ],
        },
      ],
    },
    regions: {
      documentHash: "h",
      sessionId: "s",
      regions: [
        { kind: "cell", table: 0, row: 0, col: 0, charPrFace: { hangul: "HY헤드라인M" }, charPrHeightPt: 15 },
        { kind: "cell", table: 0, row: 1, col: 0, charPrFace: null },
      ],
    },
  };
  // Region wins over graph cell on the same coordinates.
  assert.deepEqual(pageModel.cellCharShape(inspect, 0, 0, 0), { face: "HY헤드라인M", sizePt: 15 });
  // No region, graph cell with textCharPrHeightPt 8 and face -> graph cell is used.
  assert.deepEqual(pageModel.cellCharShape(inspect, 0, 0, 2), { face: "돋움체", sizePt: 8 });
  // Field-by-field fallback: graph cell has height 9 and null face -> face from baseline, size from graph cell.
  assert.deepEqual(pageModel.cellCharShape(inspect, 0, 0, 3), { face: "함초롬바탕", sizePt: 9 });
  // A region that declares no face or size falls back to the body baseline.
  assert.deepEqual(pageModel.cellCharShape(inspect, 0, 1, 0), { face: "함초롬바탕", sizePt: 10 });
  // Outside a cell, or in a cell with no region or graph cell, the baseline.
  assert.deepEqual(pageModel.cellCharShape(inspect, null), { face: "함초롬바탕", sizePt: 10 });
  assert.deepEqual(pageModel.cellCharShape(inspect, 3, 0, 0), { face: "함초롬바탕", sizePt: 10 });
  assert.deepEqual(pageModel.cellCharShape(null, null), { face: null, sizePt: null });
  const graphed = {
    graph: { tables: [{ index: 1, cells: [{ addr: { row: 2, col: 3 }, classification: "static" }] }] },
  };
  assert.equal(pageModel.graphCellAt(graphed, 1, 2, 3)?.classification, "static");
  assert.equal(pageModel.graphCellAt(graphed, 1, 2, 4), undefined);
  assert.equal(pageModel.graphCellAt(graphed, 0, 2, 3), undefined);
  assert.equal(pageModel.graphCellAt(null, 1, 2, 3), undefined);

  assert.equal(pageModel.formatCharShape({ face: "HY헤드라인M", sizePt: 15 }), "HY헤드라인M 15.0pt");
  assert.equal(pageModel.formatCharShape({ face: "함초롬바탕", sizePt: 10.5 }), "함초롬바탕 10.5pt");
  assert.equal(pageModel.formatCharShape({ face: null, sizePt: 12 }), "12.0pt");
  assert.equal(pageModel.formatCharShape({ face: "바탕", sizePt: null }), "바탕");
  assert.equal(pageModel.formatCharShape({ face: null, sizePt: null }), null);
  assert.equal(wp3.wp3t("status_char_shape", "ko", ["바탕 10.0pt"]), "글자 모양: 바탕 10.0pt");
  assert.equal(wp3.wp3t("status_char_shape", "en", ["바탕 10.0pt"]), "Character shape: 바탕 10.0pt");
});

test("deriveBlankCellLabel names blanks, returns null for printed static/guide cells, falls back on spacers, and deriveOpFieldLabel uses location text for printed cells", () => {
  const { fieldLabels } = loadWp3Stack();
  const textMap = {};
  for (const r of corpus.regions) {
    if (r.addr) textMap[`c:${r.table ?? 0}:${r.addr.row}:${r.addr.col}`] = r;
  }

  // 1. fill_target cell -> blank name
  assert.equal(
    fieldLabels.deriveBlankCellLabel(corpus.inspect, textMap, 0, 5, 1, "ko"),
    "협조자",
  );
  assert.equal(
    fieldLabels.deriveBlankCellLabel(corpus.inspect, textMap, 0, 2, 0, "ko"),
    "본문",
  );

  // 2. placeholder-seat static cell -> blank name
  assert.equal(
    fieldLabels.deriveBlankCellLabel(corpus.inspect, textMap, 0, 8, 0, "ko"),
    "전화번호",
  );
  assert.equal(
    fieldLabels.deriveBlankCellLabel(corpus.inspect, textMap, 0, 4, 0, "ko"),
    "기안자 직위(직급) 서명",
  );

  // 3. printed static cell and guide cell -> null (never "빈칸 N")
  assert.equal(
    fieldLabels.deriveBlankCellLabel(corpus.inspect, textMap, 0, 1, 0, "ko"),
    null,
  );
  assert.equal(
    fieldLabels.deriveBlankCellLabel(corpus.inspect, textMap, 0, 5, 0, "ko"),
    null,
  );
  assert.equal(
    fieldLabels.deriveBlankCellLabel(corpus.inspect, textMap, 0, 9, 0, "ko"),
    null,
  );
  assert.equal(
    fieldLabels.deriveBlankCellLabel(corpus.inspect, textMap, 0, 0, 0, "ko"),
    null,
  );
  assert.equal(
    fieldLabels.deriveBlankCellLabel(corpus.inspect, textMap, 1, 0, 0, "ko"),
    null,
  );

  // 4. spacer cell -> fallback from deriveCellFieldLabel
  assert.equal(
    fieldLabels.deriveBlankCellLabel(corpus.inspect, textMap, 0, 3, 0, "ko", 4),
    "빈칸 4",
  );

  // 5. deriveOpFieldLabel for replace_at_cell on a static cell gives location text, not "빈칸 N"
  assert.equal(
    fieldLabels.deriveOpFieldLabel(
      { kind: "replace_at_cell", table: 0, row: 1, col: 0, text: "가온공공기록원" },
      corpus.inspect,
      textMap,
      "ko",
      1,
    ),
    "표 1 2행 1열",
  );
  assert.equal(
    fieldLabels.deriveOpFieldLabel(
      { kind: "replace_at_cell", table: 0, row: 0, col: 0, text: "서식 머리말" },
      corpus.inspect,
      textMap,
      "ko",
      1,
    ),
    "표 1 1행 1열",
  );
  assert.equal(
    fieldLabels.deriveOpFieldLabel(
      { kind: "replace_at_cell", table: 0, row: 9, col: 0, text: "A4" },
      corpus.inspect,
      textMap,
      "en",
      1,
    ),
    "Table 1, row 10, col 1",
  );
});

test("known pages: measured pages fill in, first page wins, and targets resolve by cell, paragraph or change", () => {
  const { controller } = loadWp3Stack();
  const layerless = {
    kind: "engine",
    rev: "rev-1",
    seats: () => [],
    pageCount: () => 3,
    layer: () => ({ kind: "projection", boxes: [] }),
  };
  controller.publishCanvasContext(
    [{ id: "op-1", cellKey: "c:0:6:1" }, { id: "op-2", atPara: 4 }, { id: "op-3" }],
    layerless,
  );
  assert.equal(controller.knownPageOf({ cellKey: "c:0:6:1" }), null);
  assert.equal(controller.isPageMeasured("rev-1", 2), false);

  controller.publishMeasuredPage("rev-1", 2, ["t0/r6/c1", "p4", "t0/r7/c1"]);
  controller.publishMeasuredPage("rev-1", 3, ["t0/r7/c1"]);
  // A different revision is ignored.
  controller.publishMeasuredPage("rev-0", 3, ["t0/r9/c1"]);

  assert.equal(controller.isPageMeasured("rev-1", 2), true);
  assert.equal(controller.isPageMeasured("rev-0", 3), false);
  assert.equal(controller.knownPageOf({ cellKey: "c:0:6:1" }), 2);
  assert.equal(controller.knownPageOf({ cellKey: "c:0:7:1" }), 2, "an address keeps its first page");
  assert.equal(controller.knownPageOf({ atPara: 4 }), 2);
  assert.equal(controller.knownPageOf({ itemId: "op-1" }), 2);
  assert.equal(controller.knownPageOf({ itemId: "op-2" }), 2);
  assert.equal(controller.knownPageOf({ itemId: "op-3" }), null);
  assert.equal(controller.knownPageOf({ cellKey: "c:0:9:1" }), null);
  assert.equal(controller.getPublishedKnownPages().get("t0/r6/c1"), 2);

  // Turning to a known page sets the page; the current or an unknown page does nothing.
  controller.setCanvasSlice({ page: 1, pageCount: 3 });
  assert.equal(controller.turnToTargetPage({ cellKey: "c:0:9:1" }), false);
  assert.equal(controller.turnToTargetPage({ cellKey: "c:0:6:1" }), true);
  assert.equal(controller.getCanvasSlice().page, 2);
  assert.equal(controller.turnToTargetPage({ cellKey: "c:0:6:1" }), false);

  // A change picked outside the canvas turns to its page.
  controller.setCanvasSlice({ page: 1 });
  controller.canvas.select("op-2");
  assert.equal(controller.getCanvasSlice().page, 2);
  controller.setCanvasSlice({ page: 1 });
  controller.canvas.select("op-2", { fromCanvas: true });
  assert.equal(controller.getCanvasSlice().page, 1);

  // A new revision forgets the measured pages.
  controller.publishCanvasContext([], { ...layerless, rev: "rev-2" });
  assert.equal(controller.knownPageOf({ cellKey: "c:0:6:1" }), null);
  assert.equal(controller.isPageMeasured("rev-2", 2), false);
});
