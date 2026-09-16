import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const historySource = readFileSync(
  new URL("../src/components/History.tsx", import.meta.url),
  "utf8",
);

const undoStart = actionsSource.indexOf("const INVERTIBLE_KINDS = new Set");
const undoEnd = actionsSource.indexOf("export async function verifyReversal(", undoStart);
assert.ok(undoStart >= 0 && undoEnd > undoStart, "restore/proposeUndoOf source boundary changed");
const undoImplementation = stripTypeScriptTypes(actionsSource.slice(undoStart, undoEnd)).replaceAll(
  "export ",
  "",
);

const {
  sessionHistory,
  getState,
  setState,
} = await import("../src/store.ts");

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

const historyCompiled = compileComponent("../src/components/History.tsx", "History.tsx");

test("History restore proposes a reverse plan and does not apply in place", () => {
  assert.match(historySource, /restoreRun/);
  assert.match(historySource, /data-testid=\{`history-restore-\$\{runId\}`\}/);
  const restoreFn = actionsSource.slice(
    actionsSource.indexOf("export async function restoreRun"),
    actionsSource.indexOf("function regionTextAt"),
  );
  const undoFn = actionsSource.slice(
    actionsSource.indexOf("export async function proposeUndoOf"),
    actionsSource.indexOf("export async function restoreRun"),
  );
  assert.match(undoFn, /reverses: runId/);
  assert.doesNotMatch(undoFn, /rt\.applyPlan/);
  assert.doesNotMatch(restoreFn, /rt\.applyPlan/);
});

test("restoreRun emits propose with reverses-run set and does not call apply", async () => {
  let state = {
    activeSessionId: "session-A",
    receipts: {},
    draft: { ops: [] },
    undoPhase: "idle",
    undoError: null,
    inverseProof: null,
    candidates: {
      "session-A": [{ runId: "head-run" }],
    },
    head: "head-run",
  };
  const proposeCalls = [];
  const applyCalls = [];
  const context = vm.createContext({
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    captureDraftFence: () => ({ generation: 0 }),
    ownsDraftFence: () => true,
    headCandidate: () => ({ runId: "head-run" }),
    showToast: () => {},
    setQueue: async (ops, options) => {
      await context.rt.proposePlan("session-A", ops, {
        baseRunId: options.baseRunId,
        reverses: options.reverses,
      });
      state = {
        ...state,
        draft: { ...state.draft, ops, reverses: options.reverses, baseRunId: options.baseRunId },
      };
    },
    rt: {
      readReceipt: async () => ({
        planId: "plan-1",
        base: null,
      }),
      getPlan: async () => ({
        planId: "plan-1",
        ops: [
          {
            opId: "op-1",
            kind: "fill_cell",
            params: { table: 0, row: 1, col: 2, text: "new" },
          },
        ],
      }),
      readRegion: async () => ({
        subject: { kind: "session_source" },
        regions: [{ table: 0, addr: { row: 1, col: 2 }, text: "old" }],
      }),
      proposePlan: async (sessionId, ops, options) => {
        proposeCalls.push({ sessionId, ops, options });
        return { planId: "plan-reverse", reverses: { runId: options.reverses } };
      },
      applyPlan: async () => {
        applyCalls.push("apply");
        return { runId: "should-not" };
      },
      asRuntimeError: (error) => ({ code: "test", message: String(error) }),
    },
  });
  vm.runInContext(
    `${undoImplementation}\nglobalThis.restoreRun = restoreRun;\nglobalThis.proposeUndoOf = proposeUndoOf;`,
    context,
  );
  const queued = await context.restoreRun("run-edit");
  assert.equal(queued, 1);
  assert.equal(proposeCalls.length, 1);
  assert.equal(proposeCalls[0].options.reverses, "run-edit");
  assert.equal(state.draft.reverses, "run-edit");
  assert.deepEqual(applyCalls, []);
});

test("session history merges protocol events with published candidates", () => {
  const previous = {
    activeSessionId: getState().activeSessionId,
    events: getState().events,
    candidates: getState().candidates,
    receipts: getState().receipts,
    sessions: getState().sessions,
  };
  try {
    setState({
      activeSessionId: "s",
      events: [
        {
          seq: 0,
          at: "2026-09-16T00:00:00Z",
          kind: "plan.proposed",
          detail: { backend: "preedit", reversesRunId: "run-A", runId: "run-A" },
        },
        {
          seq: 1,
          at: "2026-09-16T00:00:01Z",
          kind: "candidate.published",
          detail: { runId: "run-A", backend: "preedit" },
        },
      ],
      candidates: {
        s: [
          {
            runId: "run-A",
            receipt: "run-A/receipt.json",
            base: { runId: "run-parent", sha256: "aa" },
            createdUtc: "2026-09-16T00:00:01Z",
          },
          {
            runId: "run-B",
            receipt: "run-B/receipt.json",
            base: { runId: "run-A", sha256: "bb" },
            createdUtc: "2026-09-16T00:00:02Z",
          },
        ],
      },
      receipts: {
        "run-A": { backend: "preedit" },
        "run-B": { backend: "preedit" },
      },
    });
    const rows = sessionHistory(getState());
    assert.equal(rows.length, 3);
    const published = rows.find((row) => row.eventKind === "candidate.published");
    assert.equal(published.runId, "run-A");
    assert.equal(published.parent, "run-parent");
    assert.equal(published.backend, "preedit");
    assert.equal(published.receiptPresent, true);
    const proposed = rows.find((row) => row.eventKind === "plan.proposed");
    assert.equal(proposed.runId, "run-A");
    assert.equal(proposed.backend, "preedit");
    const extra = rows.find((row) => row.runId === "run-B");
    assert.equal(extra.parent, "run-A");
    assert.equal(extra.receiptPresent, true);
    assert.equal(extra.backend, "preedit");
  } finally {
    setState(previous);
  }
});

function renderHistory(overrides = {}) {
  const candidate = {
    runId: "run-A",
    createdUtc: "2026-09-16T00:00:00Z",
    acceptance: true,
    opKinds: ["fill_cell"],
    sha256: "deadbeef",
    receipt: "run-A/receipt.json",
    base: { runId: "run-parent", sha256: "aa" },
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
    compareError: null,
    compareResult: null,
    receipts: {
      "run-A": {
        backend: "preedit",
        checks: { acceptance: true },
        steps: [],
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
          compareInspectRefusals: () => ({
            acceptanceRefused: false,
            exit3: false,
            errorRefused: false,
          }),
          exportApplied: () => {},
          loadReceipt: () => {},
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
        };
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
      throw new Error(`unexpected import: ${id}`);
    },
  });
  vm.runInContext(historyCompiled, context);
  return renderToStaticMarkup(React.createElement(module.exports.History));
}

test("history rows show run id, parent, backend, receipt, and a Restore action", () => {
  const html = renderHistory();
  assert.match(html, /data-testid="history-provenance-run-A"/);
  assert.match(html, /run run-A/);
  assert.match(html, /parent run-parent/);
  assert.match(html, /backend preedit/);
  assert.match(html, /영수증 있음/);
  assert.match(html, /data-testid="history-restore-run-A"/);
  assert.match(html, />여기로 되돌리기</);
  assert.match(html, />자세히</);
});
