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
  const changeModel = loadTsModule("src/model/changes.ts");
  const controller = loadTsModule("src/canvas/controller.ts", { "../store": h.store, "../model/changes": changeModel });
  const actions = loadTsModule("src/canvas/actions.ts", {
    "../actions": h.legacyActionsStub,
    "../i18n/v2/wp3": wp3,
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
    locationLabel: "1쪽 · 표 1 2행 1열",
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
