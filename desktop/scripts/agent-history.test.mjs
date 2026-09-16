import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const nodeRequire = createRequire(import.meta.url);

const {
  EMPTY_DRAFT,
  getState,
  inspectorHistoryBadge,
  inspectorReviewBadge,
  markHistoryCandidatesSeen,
  selectInspectorTab,
  setState,
  visibleInspectorTab,
} = await import("../src/store.ts");

const conversationSource = readFileSync(
  new URL("../src/components/Conversation.tsx", import.meta.url),
  "utf8",
);
const historySource = readFileSync(
  new URL("../src/components/History.tsx", import.meta.url),
  "utf8",
);
const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");

function compile(relPath, fileName) {
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

function loadCompiled(relPath, fileName, requireImpl) {
  const module = { exports: {} };
  vm.runInNewContext(compile(relPath, fileName), {
    module,
    exports: module.exports,
    require: requireImpl,
  });
  return module.exports;
}

function fillOp(id, col) {
  return {
    opId: id,
    kind: "fill_cell",
    table: 0,
    row: 0,
    col,
    text: "값",
    before: "",
    origin: "agent",
  };
}

function renderConversation(state) {
  const exports = loadCompiled("../src/components/Conversation.tsx", "Conversation.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../actions") {
      return { runAgentProposal: () => {}, stopInstruction: () => {} };
    }
    if (id === "../store") {
      return {
        useWorkspace: (selector) => selector(state),
        setState: () => {},
        selectInspectorTab: () => {},
      };
    }
    if (id === "../types") return {};
    if (id === "./Tag") {
      return { Tag: ({ children }) => React.createElement("span", null, children) };
    }
    if (id === "./EmptyState") {
      return {
        EmptyState: ({ title, body, testId }) =>
          React.createElement("div", { className: "empty-state", "data-testid": testId }, title, body),
        EmptyIconChat: () => null,
      };
    }
    throw new Error(`unexpected import: ${id}`);
  });
  return renderToStaticMarkup(React.createElement(exports.Conversation));
}

function renderComposer(state) {
  const exports = loadCompiled("../src/components/Composer.tsx", "Composer.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../actions") return { sendInstruction: () => {} };
    if (id === "../label") return { labelOf: (value) => String(value ?? "") };
    if (id === "../workspace/composerDraft") return { submitComposerDraft: () => {} };
    if (id === "../store") {
      return {
        useWorkspace: (selector) => selector(state),
        composerBlocker: (s) => s.blocker ?? null,
        activeStoreKey: () => null,
        getState: () => state,
        setState: () => {},
      };
    }
    throw new Error(`unexpected import: ${id}`);
  });
  return renderToStaticMarkup(React.createElement(exports.Composer));
}

function historyStore(state) {
  return {
    useWorkspace: (selector) => selector(state),
    activeCandidates: (s) => s.candidates[s.activeSessionId] ?? [],
    headCandidate: (s) => {
      const rows = s.candidates[s.activeSessionId] ?? [];
      if (s.head) return rows.find((row) => row.runId === s.head) ?? rows[rows.length - 1] ?? null;
      return rows[rows.length - 1] ?? null;
    },
    lineage: (rows) => rows,
    reversedBy: () => null,
  };
}

function renderHistory(state) {
  const exports = loadCompiled("../src/components/History.tsx", "History.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
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
    if (id === "../store") return historyStore(state);
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
  });
  return renderToStaticMarkup(React.createElement(exports.History));
}

test("plan-arrival card names the queued edits, switches to 검토, and the review badge shows the count", () => {
  const html = renderConversation({
    turns: [
      {
        id: "turn-1",
        instruction: "세 칸을 채워 주세요",
        at: "2026-09-17T00:00:00Z",
        phase: "ready",
        provider: "mock",
        events: [{ seq: 1, kind: "tool.compiled", detail: { method: "plan/propose" } }],
        payload: {
          plan: {
            planId: "plan-arrival-1",
            ops: [fillOp("op-1", 0), fillOp("op-2", 1), fillOp("op-3", 2)],
          },
          neverCompiled: ["approval/resolve", "plan/apply"],
          provider: { model: "mock" },
          turns: 1,
        },
        exitCode: 0,
        error: null,
        planId: "plan-arrival-1",
      },
    ],
    activeTurn: null,
    agentTool: { available: false },
    agentPhase: "idle",
    agentError: null,
    agentRun: null,
    activeSessionId: "s",
    agentHost: { available: true },
    draft: { ops: [fillOp("op-1", 0), fillOp("op-2", 1), fillOp("op-3", 2)] },
  });
  assert.match(html, /data-testid="plan-arrival-turn-1"/);
  assert.match(html, /계획 3개 편집 도착 → 검토 탭에서 승인/);
  assert.match(html, /class="bubble bubble-user"/);
  assert.match(html, /class="system-row"/);
  assert.match(conversationSource, /selectInspectorTab\("review"\)/);

  const before = getState();
  try {
    setState({
      view: "agent",
      inspectorTab: "agent",
      inspectorTabUserSet: true,
      approvalPhase: "idle",
      draft: { ...EMPTY_DRAFT, ops: [fillOp("op-1", 0), fillOp("op-2", 1), fillOp("op-3", 2)] },
    });
    assert.equal(inspectorReviewBadge(getState()).count, 3);
    selectInspectorTab("review");
    assert.equal(visibleInspectorTab(getState()), "review");
    assert.equal(inspectorReviewBadge(getState()).count, 3);
  } finally {
    setState({
      view: before.view,
      inspectorTab: before.inspectorTab,
      inspectorTabUserSet: before.inspectorTabUserSet,
      lastNonAgentInspectorTab: before.lastNonAgentInspectorTab,
      approvalPhase: before.approvalPhase,
      draft: before.draft,
      editIntentGeneration: before.editIntentGeneration,
    });
  }
});

test("composer send is inert while composing and shows 입력 중", () => {
  const composing = renderComposer({
    blocker: null,
    provider: { provider: "mock" },
    activeTurn: null,
    composerDraft: { text: "안녕하세요" },
    isComposing: true,
  });
  assert.match(composing, /data-testid="composer-ime"/);
  assert.match(composing, /입력 중 …/);
  assert.match(composing, /data-testid="composer-send"[^>]*disabled/);

  const idle = renderComposer({
    blocker: null,
    provider: { provider: "mock" },
    activeTurn: null,
    composerDraft: { text: "안녕하세요" },
    isComposing: false,
  });
  assert.doesNotMatch(idle, /data-testid="composer-ime"/);
  assert.doesNotMatch(idle, /data-testid="composer-send"[^>]*disabled/);

  const disconnected = renderComposer({
    blocker: "no_host",
    provider: { provider: "mock" },
    activeTurn: null,
    composerDraft: { text: "안녕하세요" },
    isComposing: false,
  });
  assert.match(disconnected, /data-testid="composer-send"[^>]*disabled/);
});

test("checkpoint timeline lists 원본 then candidates with the head marked", () => {
  const html = renderHistory({
    activeSessionId: "s",
    sessions: [
      { sessionId: "s", source: { name: "양식.hwpx", sha256: "abcdef1234567890", bytes: 12 } },
    ],
    candidates: {
      s: [
        {
          runId: "run-A",
          createdUtc: "2026-09-16T00:00:00Z",
          acceptance: true,
          opKinds: ["fill_cell"],
          sha256: "deadbeef0001",
          receipt: "run-A/receipt.json",
          base: null,
        },
        {
          runId: "run-B",
          createdUtc: "2026-09-16T00:01:00Z",
          acceptance: false,
          opKinds: ["fill_cell"],
          sha256: "deadbeef0002",
          receipt: "run-B/receipt.json",
          base: { runId: "run-A", sha256: "deadbeef0001" },
        },
      ],
    },
    head: "run-B",
    historySelected: null,
    undoPhase: "idle",
    undoError: null,
    inverseProof: null,
    events: [{ seq: 0, kind: "session.opened" }],
    compareLeftRunId: "run-B",
    compareAgainst: { source: true },
    compareUseSelection: false,
    comparePhase: "idle",
    compareError: null,
    compareResult: null,
    receipts: {
      "run-A": { backend: "preedit", checks: { acceptance: true }, steps: [] },
      "run-B": { backend: "preedit", checks: { acceptance: false }, steps: [] },
    },
  });
  const sourceAt = html.indexOf('data-testid="history-source"');
  const firstCandidate = html.indexOf('data-testid="history-run-A"');
  const secondCandidate = html.indexOf('data-testid="history-run-B"');
  assert.ok(sourceAt >= 0 && firstCandidate > sourceAt && secondCandidate > firstCandidate);
  assert.match(html, /원본/);
  assert.match(html, /abcdef123456/);
  assert.match(html, /class="[^"]*is-head[^"]*" data-testid="history-run-B"/);
  assert.match(html, /영수증 있음/);
  assert.match(html, /preedit/);
  assert.match(html, />여기로 되돌리기</);
  assert.match(html, />자세히</);
  assert.match(html, /data-testid="history-compare-run-B"/);
});

test("여기로 되돌리기 is the reverse-plan propose path and never apply", () => {
  assert.match(historySource, /여기로 되돌리기/);
  assert.match(historySource, /restoreRun/);
  assert.match(historySource, /data-testid=\{`history-restore-\$\{runId\}`\}/);
  assert.doesNotMatch(historySource, /rt\.applyPlan/);
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

test("history events disclosure is collapsed by default and shows the count", () => {
  const html = renderHistory({
    activeSessionId: "s",
    sessions: [
      { sessionId: "s", source: { name: "양식.hwpx", sha256: "abcdef1234567890", bytes: 12 } },
    ],
    candidates: {
      s: [
        {
          runId: "run-A",
          createdUtc: "2026-09-16T00:00:00Z",
          acceptance: true,
          sha256: "deadbeef0001",
          receipt: "run-A/receipt.json",
          base: null,
        },
      ],
    },
    head: "run-A",
    historySelected: null,
    undoPhase: "idle",
    undoError: null,
    inverseProof: null,
    events: [{ seq: 0 }, { seq: 1 }, { seq: 2 }],
    compareLeftRunId: "run-A",
    compareAgainst: { source: true },
    compareUseSelection: false,
    comparePhase: "idle",
    compareError: null,
    compareResult: null,
    receipts: { "run-A": { backend: "preedit", checks: { acceptance: true }, steps: [] } },
  });
  assert.match(html, /data-testid="history-events"/);
  assert.match(html, />이벤트 \(3\)</);
  assert.doesNotMatch(html, /data-testid="history-events"[^>]*\sopen/);
  assert.match(html, /data-testid="timeline"/);
});

test("기록 badge counts candidates created since last viewed and clears when the tab is shown", () => {
  const before = getState();
  try {
    setState({
      activeSessionId: "sess-a",
      candidates: { "sess-a": [{ runId: "r1" }, { runId: "r2" }] },
      historyCandidatesSeen: {},
    });
    assert.equal(inspectorHistoryBadge(getState()), 2);
    markHistoryCandidatesSeen();
    assert.equal(inspectorHistoryBadge(getState()), 0);
    setState({
      candidates: { "sess-a": [{ runId: "r1" }, { runId: "r2" }, { runId: "r3" }] },
    });
    assert.equal(inspectorHistoryBadge(getState()), 1);
    selectInspectorTab("history");
    assert.equal(inspectorHistoryBadge(getState()), 0);
  } finally {
    setState({
      activeSessionId: before.activeSessionId,
      candidates: before.candidates,
      historyCandidatesSeen: before.historyCandidatesSeen,
      view: before.view,
      inspectorTab: before.inspectorTab,
      inspectorTabUserSet: before.inspectorTabUserSet,
      lastNonAgentInspectorTab: before.lastNonAgentInspectorTab,
      editIntentGeneration: before.editIntentGeneration,
    });
  }
});
