import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { Icon } from "./icon-stub.mjs";

const require = createRequire(import.meta.url);
const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const runtimeSource = readFileSync(new URL("../src/runtime.ts", import.meta.url), "utf8");
const treeSource = readFileSync(
  new URL("../src/components/StructureTree.tsx", import.meta.url),
  "utf8",
);
const contextSource = readFileSync(
  new URL("../src/components/ContextPanel.tsx", import.meta.url),
  "utf8",
);
const smokeSource = readFileSync(new URL("../src/smoke.ts", import.meta.url), "utf8");

const regionStart = actionsSource.indexOf("export function selectionToReadRegions(");
const regionEnd = actionsSource.indexOf("async function loadCandidates(", regionStart);
assert.ok(regionStart >= 0 && regionEnd > regionStart, "region source action boundary changed");
const regionImplementation = stripTypeScriptTypes(
  actionsSource.slice(regionStart, regionEnd),
).replaceAll("export ", "");

function compileComponent(relPath, fileName) {
  const source = readFileSync(new URL(relPath, import.meta.url), "utf8");
  return ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2021,
      jsx: ts.JsxEmit.ReactJSX,
    },
    fileName,
  }).outputText;
}

const contextCompiled = compileComponent("../src/components/ContextPanel.tsx", "ContextPanel.tsx");

function inspectFixture(overrides = {}) {
  return {
    documentHash: "abc",
    sessionId: "s",
    summary: {
      documentHash: "abc",
      sessionId: "s",
      anchors: ["양식 앵커"],
      removalTargets: [{ para_idx: 2, confidence: "high" }],
    },
    graph: {
      documentHash: "abc",
      sessionId: "s",
      paragraphs: [{ section: "본문", at_para: 2, para_idx: 2, text: "graph preview only" }],
      tables: [
        {
          index: 0,
          cells: [
            { addr: { row: 0, col: 0 }, classification: "fill_target", textPreview: "값" },
            { addr: { row: 0, col: 1 }, classification: "guide", textPreview: "안내" },
          ],
        },
      ],
    },
    regions: {
      documentHash: "abc",
      sessionId: "s",
      regions: [{ kind: "cell", table: 0, row: 0, col: 0 }],
    },
    ...overrides,
  };
}

function loadRegionHelpers() {
  const context = vm.createContext({
    getState: () => ({}),
    setState: () => {},
    activeInspect: () => null,
    headCandidate: () => null,
    selectionId: (s) => (s ? JSON.stringify(s) : "none"),
    locateSelection: () => {},
    rt: { readRegion: async () => ({ regions: [] }), asRuntimeError: (e) => e },
  });
  vm.runInContext(
    `${regionImplementation}\nglobalThis.selectionToReadRegions = selectionToReadRegions;\nglobalThis.regionAccess = regionAccess;`,
    context,
  );
  return {
    selectionToReadRegions: context.selectionToReadRegions,
    regionAccess: context.regionAccess,
  };
}

test("runtime.ts already wraps document/readRegion for region source", () => {
  assert.match(runtimeSource, /export const readRegion/);
  assert.match(runtimeSource, /["']document\/readRegion["']/);
});

test("structure tree loads a selected node through selectStructureNode", () => {
  assert.match(treeSource, /selectStructureNode/);
  assert.match(actionsSource, /rt\.readRegion\(sessionId, addresses, runId\)/);
  assert.match(smokeSource, /restoreViaHistory/);
  assert.match(smokeSource, /history-restore-\$\{runId\}/);
  assert.match(smokeSource, /button\?\.click\(\)/);
});

test("region text display is read-only and does not gate approve or apply", () => {
  assert.match(contextSource, /data-testid="region-source"/);
  assert.match(contextSource, /data-testid="region-source-forbidden"/);
  assert.doesNotMatch(contextSource, /isComposing/);
  assert.doesNotMatch(
    contextSource.slice(
      contextSource.indexOf("function RegionSourceSection"),
      contextSource.indexOf("function CellDetail"),
    ),
    /<input|<textarea|contentEditable|beginEdit/,
  );
});

test("selection addresses become the read-region payload; tables do not invent a cell", () => {
  const helpers = loadRegionHelpers();
  assert.equal(
    JSON.stringify(helpers.selectionToReadRegions({ kind: "paragraph", atPara: 4 })),
    JSON.stringify([{ atPara: 4 }]),
  );
  assert.equal(
    JSON.stringify(helpers.selectionToReadRegions({ kind: "cell", table: 1, row: 2, col: 3 })),
    JSON.stringify([{ table: 1, row: 2, col: 3 }]),
  );
  assert.equal(helpers.selectionToReadRegions({ kind: "table", table: 0 }), null);
  assert.equal(helpers.selectionToReadRegions(null), null);
});

test("forbidden status comes only from inspect.forbidden, never invented summary anchors", () => {
  const helpers = loadRegionHelpers();
  const inspect = inspectFixture();
  assert.equal(helpers.regionAccess(inspect, { kind: "paragraph", atPara: 2 }), "readonly");
  assert.equal(
    helpers.regionAccess(
      inspectFixture({
        forbidden: {
          sessionId: "s",
          documentHash: "abc",
          anchors: [{ kind: "anchor", text: "양식 앵커", atPara: 2 }],
          placeholders: [],
          removalTargets: [],
          counts: { anchors: 1, placeholders: 0, removalTargets: 0 },
        },
      }),
      { kind: "paragraph", atPara: 2 },
    ),
    "forbidden",
  );
  assert.equal(
    helpers.regionAccess(inspect, { kind: "cell", table: 0, row: 0, col: 0 }),
    "editable",
  );
  assert.equal(
    helpers.regionAccess(inspect, { kind: "cell", table: 0, row: 0, col: 1 }),
    "readonly",
  );
});

test("loadSelectedRegion calls readRegion with the selected address", async () => {
  const calls = [];
  let state = {
    activeSessionId: "session-A",
    selection: { kind: "cell", table: 0, row: 1, col: 2 },
    inspects: { "session-A": inspectFixture() },
    selectedRegionSource: null,
    head: "run-head",
    candidates: { "session-A": [{ runId: "run-head" }] },
  };
  const context = vm.createContext({
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    activeInspect: () => state.inspects[state.activeSessionId] ?? null,
    headCandidate: () => ({ runId: "run-head" }),
    selectionId: (s) => {
      if (!s) return "none";
      if (s.kind === "paragraph") return `p:${s.atPara}`;
      if (s.kind === "table") return `t:${s.table}`;
      return `c:${s.table}:${s.row}:${s.col}`;
    },
    locateSelection: (selection) => {
      state = { ...state, selection };
    },
    rt: {
      readRegion: async (sessionId, regions, runId) => {
        calls.push({ sessionId, regions, runId });
        return {
          regions: [
            {
              table: 0,
              addr: { row: 1, col: 2 },
              text: "exact cell text",
              runs: [{ index: 0, text: "exact cell text" }],
            },
          ],
        };
      },
      asRuntimeError: (error) => ({ code: "test", message: String(error) }),
    },
  });
  vm.runInContext(
    `${regionImplementation}\nglobalThis.loadSelectedRegion = loadSelectedRegion;`,
    context,
  );
  await context.loadSelectedRegion({ kind: "cell", table: 0, row: 1, col: 2 });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].sessionId, "session-A");
  assert.equal(JSON.stringify(calls[0].regions), JSON.stringify([{ table: 0, row: 1, col: 2 }]));
  assert.equal(calls[0].runId, "run-head");
  assert.equal(state.selectedRegionSource.region.text, "exact cell text");
  assert.equal(state.selectedRegionSource.address.row, 1);
  assert.equal(state.selectedRegionSource.address.col, 2);
});

test("a missing read-region payload is left empty rather than filled from the graph", async () => {
  let state = {
    activeSessionId: "session-A",
    selection: { kind: "paragraph", atPara: 2 },
    inspects: { "session-A": inspectFixture() },
    selectedRegionSource: null,
    candidates: { "session-A": [] },
  };
  const context = vm.createContext({
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    activeInspect: () => state.inspects[state.activeSessionId] ?? null,
    headCandidate: () => null,
    selectionId: (s) => (s?.kind === "paragraph" ? `p:${s.atPara}` : "none"),
    locateSelection: () => {},
    rt: {
      readRegion: async () => ({ regions: [] }),
      asRuntimeError: (error) => ({ code: "test", message: String(error) }),
    },
  });
  vm.runInContext(
    `${regionImplementation}\nglobalThis.loadSelectedRegion = loadSelectedRegion;`,
    context,
  );
  await context.loadSelectedRegion({ kind: "paragraph", atPara: 2 });
  assert.equal(state.selectedRegionSource.region, null);
  assert.notEqual(state.selectedRegionSource.region?.text, "graph preview only");
});

function renderContext(overrides = {}) {
  const inspect = inspectFixture(overrides.inspect);
  const state = {
    selection: overrides.selection ?? { kind: "paragraph", atPara: 2 },
    selectedRegionSource: overrides.selectedRegionSource ?? null,
    ...overrides.state,
  };
  const module = { exports: {} };
  const context = vm.createContext({
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return require(id);
      if (id === "react") return require(id);
      if (id === "../actions") return { beginEdit: () => {}, bindFormToActiveDocument: () => {}, needsBoundFormHint: () => false };
      if (id === "../label") {
        return {
          humanCellAddress: (t, r, c) => `표 ${t + 1} · ${r + 1}행 ${c + 1}열`,
        };
      }
      if (id === "../store") {
        return {
          useWorkspace: (selector) => selector(state),
          selectionId: (s) => {
            if (!s) return "none";
            if (s.kind === "paragraph") return `p:${s.atPara}`;
            if (s.kind === "table") return `t:${s.table}`;
            return `c:${s.table}:${s.row}:${s.col}`;
          },
          visibleInspectorTab: (s) => {
            if (s.view === "agent") return "agent";
            if (s.inspectorTabUserSet && s.inspectorTab && s.inspectorTab !== "agent") {
              return s.inspectorTab;
            }
            if ((s.draft?.ops?.length ?? 0) > 0 || s.approvalPhase === "pending") return "review";
            return "selection";
          },
          selectInspectorTab: () => {},
          markAgentTurnsSeen: () => {},
          markHistoryCandidatesSeen: () => {},
          inspectorHistoryBadge: () => 0,
          inspectorAgentUnread: () => 0,
        };
      }
      if (id === "../types") return {};
      if (id === "./History") return { History: () => null };
      if (id === "./ReviewQueue") return { ReviewQueue: () => null };
      if (id === "./Composer") return { Composer: () => null };
      if (id === "./Conversation") return { Conversation: () => null };
      if (id === "./DocumentContext") return { DocumentContext: () => null };
      if (id === "./Timeline") return { Timeline: () => null };
      if (id === "./Tag") {
        return {
          Tag: ({ tone, children }) =>
            React.createElement("span", { "data-tone": tone }, children),
          CLASSIFICATION_LABEL: {
            fill_target: "채움",
            guide: "안내",
            static: "고정",
            spacer: "여백",
          },
        };
      }
      if (id === "./Icon") return { Icon };
      throw new Error(`unexpected import: ${id}`);
    },
  });
  vm.runInContext(contextCompiled, context);
  return renderToStaticMarkup(
    React.createElement(module.exports.ContextPanel, { inspect, status: null }),
  );
}

test("forbidden regions show read-only text and never an editable control", () => {
  const html = renderContext({
    selection: { kind: "paragraph", atPara: 2 },
    selectedRegionSource: {
      sessionId: "s",
      selectionId: "p:2",
      address: { atPara: 2 },
      region: {
        at_para: 2,
        text: "양식 앵커 원문",
        runs: [{ index: 0, text: "양식 앵커 원문" }],
      },
      access: "forbidden",
      phase: "ready",
      error: null,
    },
  });
  assert.match(html, /data-testid="region-source"/);
  assert.match(html, /data-testid="region-source-address"/);
  assert.match(html, /at_para 2/);
  assert.match(
    html,
    /data-testid="region-source"[^>]*data-editable="false"|data-editable="false"[^>]*data-testid="region-source"/,
  );
  assert.match(html, /data-testid="region-source-forbidden"/);
  assert.match(html, /양식 앵커 원문/);
  const forbidden = html.match(
    /data-testid="region-source-forbidden"[\s\S]*?<\/div>/,
  )?.[0] ?? "";
  assert.match(forbidden, /양식 앵커 원문/);
  assert.doesNotMatch(forbidden, /<input|<textarea|contenteditable|seat-input|edit-seat/i);
  assert.doesNotMatch(html, /data-testid="region-source"[^>]*data-editable="true"/);
});

test("when read-region omits the region the panel does not invent its text", () => {
  const html = renderContext({
    selection: { kind: "paragraph", atPara: 2 },
    selectedRegionSource: {
      sessionId: "s",
      selectionId: "p:2",
      address: { atPara: 2 },
      region: null,
      access: "readonly",
      phase: "ready",
      error: null,
    },
  });
  assert.match(html, /data-testid="region-source-missing"/);
  assert.doesNotMatch(html, /data-testid="region-source-forbidden"/);
  const source = html.match(/data-testid="region-source"[\s\S]*?<div class="section">/)?.[0] ?? html;
  assert.doesNotMatch(source, /graph preview only/);
});
