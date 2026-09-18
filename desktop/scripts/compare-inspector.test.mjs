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
const helperStart = actionsSource.indexOf("export function selectionToCompareRegions(");
const helperEnd = actionsSource.indexOf("interface HeadSelectionLease");
assert.ok(helperStart >= 0 && helperEnd > helperStart, "compare inspect source boundary changed");
const helperImplementation = stripTypeScriptTypes(actionsSource.slice(helperStart, helperEnd)).replaceAll(
  "export ",
  "",
);

function loadHelpers() {
  globalThis.getState = () => ({});
  globalThis.setState = () => {};
  globalThis.loadReceipt = async () => true;
  globalThis.rt = { compareCandidate: async () => ({}), asRuntimeError: (e) => e };
  vm.runInThisContext(helperImplementation);
  return {
    selectionToCompareRegions: globalThis.selectionToCompareRegions,
    rpcExitCode: globalThis.rpcExitCode,
    compareInspectRefusals: globalThis.compareInspectRefusals,
    runCompareInspect: globalThis.runCompareInspect,
  };
}

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

const helpers = loadHelpers();

test("runCompareInspect talks only to candidate/compare and never to verify/*", () => {
  const slice = actionsSource.slice(helperStart, helperEnd);
  assert.match(slice, /rt\.compareCandidate/);
  assert.doesNotMatch(slice, /rt\.\w*[Vv]erify/);
  assert.doesNotMatch(slice, /["']verify\//);
});

test("selection addresses become compare regions only for cells and paragraphs", () => {
  assert.equal(helpers.selectionToCompareRegions(null), undefined);
  assert.deepEqual(helpers.selectionToCompareRegions({ kind: "paragraph", atPara: 4 }), [
    { atPara: 4 },
  ]);
  assert.deepEqual(
    helpers.selectionToCompareRegions({ kind: "cell", table: 1, row: 2, col: 3 }),
    [{ table: 1, row: 2, col: 3 }],
  );
  assert.equal(helpers.selectionToCompareRegions({ kind: "table", table: 0 }), undefined);
});

test("acceptance false and exit 3 are refusals, never a green pass", () => {
  const clean = helpers.compareInspectRefusals({ acceptance: true, exitCodes: [0] });
  assert.equal(clean.acceptanceRefused, false);
  assert.equal(clean.exit3, false);
  assert.equal(clean.errorRefused, false);
  const refused = helpers.compareInspectRefusals({
    acceptance: false,
    exitCodes: [3],
    error: { code: "refused", data: { exitCode: 3 } },
  });
  assert.equal(refused.acceptanceRefused, true);
  assert.equal(refused.exit3, true);
  assert.equal(refused.errorRefused, true);
  assert.equal(helpers.rpcExitCode({ code: "x", data: { exitCode: 3 } }), 3);
});

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

test("runCompareInspect sends the existing compare command and records a refusal on error", async () => {
  let state = {
    activeSessionId: "s",
    compareLeftRunId: "run-A",
    historySelected: "run-A",
    head: "run-A",
    compareAgainst: { source: true },
    compareUseSelection: false,
    selection: null,
    receipts: { "run-A": { steps: [] } },
  };
  const pending = deferred();
  const calls = [];
  const context = vm.createContext({
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    loadReceipt: async () => true,
    rt: {
      compareCandidate(...args) {
        calls.push(args);
        return pending.promise;
      },
      asRuntimeError(error) {
        return { code: "compare_refused", message: String(error), data: { exitCode: 3 } };
      },
    },
  });
  vm.runInContext(
    `${helperImplementation}\nglobalThis.runCompareInspect = runCompareInspect;`,
    context,
  );
  const running = context.runCompareInspect();
  pending.reject(new Error("regions unreadable"));
  await running;
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "s");
  assert.equal(calls[0][1], "run-A");
  assert.deepEqual(calls[0][2], { source: true });
  assert.equal(state.comparePhase, "failed");
  assert.equal(state.compareError.data.exitCode, 3);
  assert.equal(helpers.compareInspectRefusals({ error: state.compareError }).exit3, true);
});

const historyCompiled = compileComponent("../src/components/History.tsx", "History.tsx");
const receiptCompiled = compileComponent("../src/components/ReceiptPanel.tsx", "ReceiptPanel.tsx");

function renderHistory(overrides = {}) {
  const candidate = {
    runId: "run-A",
    createdUtc: "2026-09-16T00:00:00Z",
    acceptance: false,
    opKinds: ["fill_cell"],
    sha256: "deadbeef",
    ...overrides.candidate,
  };
  const state = {
    activeSessionId: "s",
    candidates: { s: [candidate] },
    head: "run-A",
    historySelected: "run-A",
    undoPhase: "idle",
    undoError: null,
    inverseProof: null,
    events: [],
    compareLeftRunId: "run-A",
    compareAgainst: { source: true },
    compareUseSelection: false,
    comparePhase: "idle",
    compareError: overrides.compareError ?? null,
    compareResult: overrides.compareResult ?? null,
    receipts: {
      "run-A": {
        checks: { acceptance: false },
        steps: overrides.steps ?? [{ opId: "op-1", exitCode: 3 }],
      },
    },
    ...overrides.state,
  };
  const module = { exports: {} };
  const context = vm.createContext({
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return require(id);
      if (id === "react") return require(id);
      if (id === "../actions") {
        return {
          compareInspectRefusals: helpers.compareInspectRefusals,
          exportApplied: () => {},
          loadReceipt: () => {},
          proposeUndoOf: () => {},
          restoreRun: () => {},
          loadSessionEvents: () => {},
          runCompareInspect: () => {},
          selectHistory: () => {},
          setCompareAgainst: () => {},
          setCompareLeft: () => {},
          setCompareUseSelection: () => {},
          setHead: () => {},
        };
      }
      if (id === "../store") {
        return {
          useWorkspace: (selector) => selector(state),
          activeCandidates: (s) => s.candidates[s.activeSessionId] ?? [],
          headCandidate: (s) => (s.candidates[s.activeSessionId] ?? [])[0] ?? null,
          lineage: (rows) => rows,
          reversedBy: () => null,
          sessionHistory: (s) =>
            (s.candidates[s.activeSessionId] ?? []).map((row) => ({
              key: row.runId,
              at: row.createdUtc ?? "",
              seq: null,
              eventKind: null,
              runId: row.runId,
              parent: row.base?.runId ?? null,
              backend: s.receipts?.[row.runId]?.backend ?? null,
              receiptPresent: Boolean(s.receipts?.[row.runId] || row.receipt),
              candidate: row,
            })),
          previewIsStale: () => false,
        };
      }
      if (id === "../label") {
        return { relativeWhen: () => "방금", stampWhen: (iso) => String(iso ?? "") };
      }
      if (id === "../types") return {};
      if (id === "./Tag") {
        return {
          Tag: ({ tone, children }) =>
            React.createElement("span", { "data-tone": tone }, children),
        };
      }
      if (id === "./EmptyState") {
        return {
          EmptyState: ({ title, body, testId }) =>
            React.createElement("div", { className: "empty-state", "data-testid": testId }, title, body),
          EmptyIconHistory: () => null,
        };
      }
      if (id === "./Timeline") {
        return { Timeline: () => React.createElement("div", { "data-testid": "timeline" }) };
      }
      if (id === "./Icon") return { Icon };
      throw new Error(`unexpected import: ${id}`);
    },
  });
  vm.runInContext(historyCompiled, context);
  return renderToStaticMarkup(React.createElement(module.exports.History));
}

test("compare inspector surfaces acceptance false and exit 3 as refusals, never green", () => {
  const html = renderHistory();
  assert.match(html, /data-testid="compare-inspect"/);
  assert.match(html, /candidate\/compare/);
  assert.match(html, /verify\/\*/);
  assert.match(html, /data-testid="compare-acceptance-refusal"/);
  assert.match(html, /data-testid="compare-exit3-refusal"/);
  assert.match(html, /class="refusal"[^>]*data-testid="compare-acceptance-refusal"|data-testid="compare-acceptance-refusal"[^>]*class="refusal"/);
  assert.match(html, /class="refusal"[^>]*data-testid="compare-exit3-refusal"|data-testid="compare-exit3-refusal"[^>]*class="refusal"/);
  assert.doesNotMatch(
    html.match(/data-testid="compare-acceptance-refusal"[\s\S]*?<\/div>/)[0],
    /data-tone="ok"/,
  );
  assert.doesNotMatch(
    html.match(/data-testid="compare-exit3-refusal"[\s\S]*?<\/div>/)[0],
    /data-tone="ok"/,
  );
});

function renderReceipt(receipt) {
  const state = {
    receiptOpen: "run-A",
    receipts: { "run-A": receipt },
    receiptError: null,
  };
  const module = { exports: {} };
  const context = vm.createContext({
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return require(id);
      if (id === "react") return require(id);
      if (id === "../actions") return { openReceipt: () => {} };
      if (id === "../store") {
        return { useWorkspace: (selector) => selector(state), showToast: () => {} };
      }
      if (id === "../label") {
        return {
          formatBytes: (n) => `${n} B`,
          humanCellAddress: (t, r, c) => `표 ${t + 1} · ${r + 1}행 ${c + 1}열`,
          quoteKo: (s) => `「${s}」`,
          shortHash: (v, n = 12) => String(v ?? "").slice(0, n),
          stampWhen: (iso) => (iso ? String(iso).replace("T", " ").slice(0, 16) : ""),
        };
      }
      if (id === "../types") return {};
      if (id === "./Tag") {
        return {
          Tag: ({ tone, children }) =>
            React.createElement("span", { "data-tone": tone }, children),
        };
      }
      throw new Error(`unexpected import: ${id}`);
    },
  });
  vm.runInContext(receiptCompiled, context);
  return renderToStaticMarkup(React.createElement(module.exports.ReceiptPanel));
}

test("receipt panel never paints acceptance false or exit 3 as success", () => {
  const html = renderReceipt({
    source: { name: "a.hwpx", sha256: "aa".repeat(32), bytes: 10 },
    candidate: { path: "c.hwpx", sha256: "bb".repeat(32), bytes: 11, role: "candidate" },
    backend: "preedit",
    planHash: "cc".repeat(32),
    steps: [{ opId: "op-1", kind: "fill_cell", subcommand: "fill-cell", exitCode: 3 }],
    approval: {
      state: "approved",
      approver: "host",
      requestedBy: "desktop",
      resolvedUtc: "2026-09-16T00:00:00Z",
      planHash: "cc".repeat(32),
    },
    checks: {
      acceptance: false,
      ranAll: true,
      reason: "residue",
      checks: [{ checker: "check_residue", state: "ran", ok: false }],
      note: "offline",
    },
    evidence: { class: "structural_only", note: "no render" },
  });
  assert.match(html, /data-testid="receipt-acceptance-refusal"/);
  assert.match(html, /data-testid="receipt-exit3-refusal"/);
  const acceptance = html.match(
    /data-testid="receipt-acceptance-refusal"[^>]*>[\s\S]*?<\/span>/,
  )[0];
  const exit3 = html.match(/data-testid="receipt-exit3-refusal"[^>]*>[\s\S]*?<\/div>/)[0];
  assert.doesNotMatch(acceptance, /data-tone="ok"/);
  assert.doesNotMatch(exit3, /data-tone="ok"/);
});

test("receipt summary is first and the full JSON lives under 기술 정보", () => {
  const receipt = {
    source: { name: "a.hwpx", sha256: "aa".repeat(32), bytes: 10 },
    candidate: { path: "c.hwpx", sha256: "bb".repeat(32), bytes: 30720, role: "candidate" },
    backend: "xml",
    planHash: "cc".repeat(32),
    steps: [
      {
        opId: "op-1",
        kind: "fill_cell",
        subcommand: "fill-cell",
        exitCode: 0,
        result: { table: 0, row: 0, col: 0 },
      },
    ],
    approval: {
      state: "approved",
      approver: "host-operator",
      requestedBy: "desktop",
      resolvedUtc: "2026-09-17T10:30:00Z",
      planHash: "cc".repeat(32),
    },
    checks: {
      acceptance: true,
      ranAll: true,
      reason: null,
      checks: [{ checker: "check_residue", state: "ran", ok: true }],
      note: "offline",
    },
    evidence: { class: "structural_only", note: "no render" },
    createdUtc: "2026-09-17T10:30:00Z",
  };
  const html = renderReceipt(receipt);
  assert.match(html, /data-testid="receipt-summary"/);
  const summaryAt = html.indexOf('data-testid="receipt-summary"');
  const rawAt = html.indexOf('data-testid="receipt-raw"');
  assert.ok(summaryAt >= 0 && rawAt > summaryAt);
  assert.match(html, /host-operator 승인/);
  assert.match(html, /xml 편집 1건/);
  const raw = html.match(/data-testid="receipt-raw"[\s\S]*?<\/details>/)[0];
  assert.match(raw, />기술 정보</);
  assert.match(raw, /<pre>/);
  assert.match(raw, /&quot;planHash&quot;/);
  assert.match(raw, /&quot;structural_only&quot;/);
});
