import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const nodeRequire = createRequire(import.meta.url);

const nodeRequireReact = (id) => {
  if (id === "react/jsx-runtime") return nodeRequire(id);
  if (id === "react") return nodeRequire(id);
  return null;
};

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

const label = loadCompiled("../src/label.ts", "label.ts", () => {
  throw new Error("label.ts has no imports");
});

const emptyState = loadCompiled("../src/components/EmptyState.tsx", "EmptyState.tsx", (id) => {
  const known = nodeRequireReact(id);
  if (known) return known;
  if (id === "../label") return label;
  throw new Error(`unexpected import: ${id}`);
});

const diff = loadCompiled("../src/diff.ts", "diff.ts", () => {
  throw new Error("diff.ts has no imports");
});

const reviewHunk = loadCompiled("../src/reviewHunk.ts", "reviewHunk.ts", (id) => {
  if (id === "./diff") return diff;
  if (id === "./store" || id === "./types") return {};
  throw new Error(`unexpected import: ${id}`);
});

const {
  diffText,
  hunkBeforeText,
  hunkKindLabel,
  hunkAddress,
  planOpsJson,
  queueRefusalMessage,
  reviewQueueHotkey,
  shortPlanHash,
} = { ...diff, ...reviewHunk };

const tag = {
  Tag: ({ children, tone, title }) =>
    React.createElement("span", { className: `tag ${tone ?? ""}`, title, "data-tone": tone }, children),
};

function fillOp(overrides = {}) {
  return {
    opId: "op-1",
    kind: "fill_cell",
    table: 0,
    row: 0,
    col: 14,
    text: "가마다",
    before: "가나다",
    origin: "user",
    ...overrides,
  };
}

function draftWith(ops, extra = {}) {
  return {
    ops,
    plan: {
      planId: "plan-A",
      planHash: "a1b2c3def456",
      sessionId: "session-A",
      proposer: "user",
      backend: "preedit",
    },
    validation: {
      ok: true,
      counts: { hard: 0, warn: 0 },
      hard: [],
      warn: [],
      preflight: { note: "n", deferred: [], source: "s" },
    },
    sessionId: "session-A",
    boundSha256: "sha",
    phase: "ready",
    error: null,
    rewrittenFromAgent: false,
    baseRunId: null,
    reverses: null,
    ...extra,
  };
}

function baseState(overrides = {}) {
  return {
    draft: draftWith([fillOp()]),
    approval: {
      approvalId: "ap-1",
      planId: "plan-A",
      planHash: "a1b2c3def456",
      state: "pending",
      requestedBy: "user",
      requestedUtc: "2026-09-17T00:00:00Z",
    },
    approvalPhase: "pending",
    approvalError: null,
    applyPhase: "idle",
    applyError: null,
    recovery: null,
    redoStack: [],
    activeSessionId: "session-A",
    receipts: {},
    head: null,
    isComposing: false,
    texts: {},
    applied: null,
    candidateVerdict: null,
    ...overrides,
  };
}

function renderQueue(state, actions = {}) {
  const store = {
    useWorkspace: (selector) => selector(state),
    getState: () => state,
    locateSelection: () => {},
    setCenterMode: () => {},
    setState: () => {},
    setView: () => {},
    showToast: () => {},
    canRequestApproval: () => false,
    draftStaleness: () => null,
  };
  const hunkCard = loadCompiled("../src/components/HunkCard.tsx", "HunkCard.tsx", (id) => {
    const known = nodeRequireReact(id);
    if (known) return known;
    if (id === "../reviewHunk") return reviewHunk;
    if (id === "../actions") return { declareSuggestedCharPr: () => {}, editOpValue: () => {}, undoQueuedOp: () => {} };
    if (id === "../store") return store;
    if (id === "../types") return {};
    if (id === "./Tag") return tag;
    throw new Error(`unexpected import: ${id}`);
  });
  const exports = loadCompiled("../src/components/ReviewQueue.tsx", "ReviewQueue.tsx", (id) => {
    const known = nodeRequireReact(id);
    if (known) return known;
    if (id === "./EmptyState") return emptyState;
    if (id === "../label") return label;
    if (id === "../actions") {
      return {
        applyApproved: () => {},
        redoQueuedOp: () => {},
        reproposeDraft: () => {},
        requestApprovalForDraft: () => {},
        resolveApprovalDecision: () => {},
        cancelApply: () => {},
        clearQueue: () => {},
        resolveRecovery: () => {},
        ...actions,
      };
    }
    if (id === "../store") return store;
    if (id === "../types") return {};
    if (id === "../workspace/reviewSummary") {
      return {
        hasActiveApprovalBinding: () =>
          state.approval?.state === "pending" &&
          state.approval?.planHash === state.draft?.plan?.planHash,
      };
    }
    if (id === "../reviewHunk") return reviewHunk;
    if (id === "./HunkCard") return hunkCard;
    if (id === "./Tag") return tag;
    throw new Error(`unexpected import: ${id}`);
  });
  return {
    html: renderToStaticMarkup(React.createElement(exports.ReviewQueue)),
    allHtml: renderToStaticMarkup(
      React.createElement(
        React.Fragment,
        null,
        React.createElement(exports.ApproveAllButton),
        React.createElement(exports.ReviewQueue),
      ),
    ),
    exports,
  };
}

test("LCS marks replace a middle character without rewriting neighbours", () => {
  const round = (value) => JSON.parse(JSON.stringify(value));
  assert.deepEqual(round(diffText("가나다", "가마다")), [
    { type: "equal", text: "가" },
    { type: "delete", text: "나" },
    { type: "insert", text: "마" },
    { type: "equal", text: "다" },
  ]);
  assert.deepEqual(round(diffText("", "넣기")), [{ type: "insert", text: "넣기" }]);
  assert.deepEqual(round(diffText("지움", "")), [{ type: "delete", text: "지움" }]);
});

test("missing before is null; cache and captured before are used as-is", () => {
  assert.equal(hunkBeforeText({ kind: "fill_cell", table: 0, row: 0, col: 14 }, []), null);
  assert.equal(hunkBeforeText({ kind: "fill_cell", table: 0, row: 0, col: 14, before: "원" }, []), "원");
  assert.equal(
    hunkBeforeText(
      { kind: "fill_cell", table: 0, row: 0, col: 14, before: "기억" },
      [{ table: 0, addr: { row: 0, col: 14 }, text: "캐시" }],
    ),
    "캐시",
  );
  assert.equal(hunkBeforeText({ kind: "set_run", atPara: 12, before: "문" }, []), "문");
});

test("kind labels and addresses match the review chrome", () => {
  assert.equal(hunkKindLabel(fillOp({ before: "" })), "값 넣기");
  assert.equal(hunkKindLabel(fillOp()), "바꾸기");
  assert.equal(hunkKindLabel({ kind: "set_run", atPara: 12, run: 0, before: "x" }), "바꾸기");
  assert.equal(hunkAddress(fillOp()), "표 0 R0C14");
  assert.equal(hunkAddress({ kind: "set_run", atPara: 12, run: 1, opId: "r", text: "", before: "", origin: "user" }), "문단 12");
});

test("j/k/a/r/Enter and Shift+A map to hunk motion and the shared approve path", () => {
  const ctx = { focused: 1, count: 3, composing: false, inEditable: false };
  const hit = (e, extra = {}) =>
    JSON.parse(JSON.stringify(reviewQueueHotkey(e, { ...ctx, ...extra })));
  assert.deepEqual(hit({ key: "j", shiftKey: false }), { type: "focus", index: 2 });
  assert.deepEqual(hit({ key: "k", shiftKey: false }), { type: "focus", index: 0 });
  assert.deepEqual(hit({ key: "a", shiftKey: false }), { type: "approve-hunk", index: 1 });
  assert.deepEqual(hit({ key: "r", shiftKey: false }), { type: "reject-hunk", index: 1 });
  assert.deepEqual(hit({ key: "Enter", shiftKey: false }), { type: "toggle-provenance", index: 1 });
  assert.deepEqual(hit({ key: "A", shiftKey: true }), { type: "approve-all" });
  assert.deepEqual(hit({ key: "a", shiftKey: false }, { composing: true }), { type: "none" });
  assert.deepEqual(hit({ key: "j", shiftKey: false }, { inEditable: true }), { type: "none" });
  assert.deepEqual(hit({ key: "A", shiftKey: true }, { inEditable: true }), { type: "approve-all" });
});

test("hunk card renders before/after and LCS marks; missing before is 원문 없음", () => {
  const present = renderQueue(baseState()).html;
  assert.match(present, /data-testid="queue-op-0-0-14"/);
  assert.match(present, /바꾸기/);
  assert.match(present, /표 0 R0C14/);
  assert.match(present, /대기/);
  assert.match(present, /data-testid="queue-before-op-1"/);
  assert.match(present, /data-testid="queue-after-op-1"/);
  assert.match(present, /data-testid="hunk-del"/);
  assert.match(present, /data-testid="hunk-ins"/);
  assert.match(present, />나</);
  assert.match(present, />마</);
  assert.doesNotMatch(present, /원문 없음/);

  const missingOp = fillOp({ before: undefined });
  delete missingOp.before;
  const missing = renderQueue(baseState({ draft: draftWith([missingOp]) })).html;
  assert.match(missing, /원문 없음/);
  assert.match(missing, /hunk-missing/);
});

test("모두 승인 shows count and short hash and is gated like the existing approve", () => {
  const { allHtml } = renderQueue(baseState());
  assert.match(allHtml, /data-testid="approve-all"/);
  assert.match(allHtml, /모두 승인 · 1 · a1b2c3/);
  assert.match(allHtml, /aria-label="모두 승인 · 1 · a1b2c3"/);

  const composing = renderQueue(baseState({ isComposing: true })).allHtml;
  assert.match(composing, /입력 조합이 끝나기 전에는 승인하지 않습니다/);

  const staleBound = renderQueue(
    baseState({
      approval: {
        approvalId: "ap-1",
        planId: "plan-A",
        planHash: "other",
        state: "pending",
        requestedBy: "user",
        requestedUtc: "2026-09-17T00:00:00Z",
      },
    }),
  ).allHtml;
  assert.match(staleBound, /현재 문서와 정확히 일치하는 승인만 기록할 수 있습니다/);
});

test("keyboard approve and the button path leave plan JSON byte-identical", () => {
  const ops = Object.freeze([
    Object.freeze(fillOp()),
    Object.freeze(fillOp({ opId: "op-2", col: 1, text: "둘", before: "하나" })),
  ]);
  const plan = Object.freeze({
    planId: "plan-A",
    planHash: "a1b2c3def456",
    ops: JSON.parse(planOpsJson(ops)),
  });
  const fromButton = planOpsJson(ops);
  const hotkey = reviewQueueHotkey(
    { key: "A", shiftKey: true },
    { focused: 0, count: ops.length, composing: false, inEditable: false },
  );
  assert.equal(hotkey.type, "approve-all");
  const fromKeyboard = planOpsJson(ops);
  assert.equal(fromKeyboard, fromButton);
  assert.equal(fromKeyboard, JSON.stringify(plan.ops));
  assert.equal(JSON.stringify(ops[0]), JSON.stringify(fillOp()));
});

test("Shift+A and 모두 승인 call approveDisplayedPlan with the on-screen hash", () => {
  const source = readFileSync(new URL("../src/components/ReviewQueue.tsx", import.meta.url), "utf8");
  assert.match(source, /export function approveDisplayedPlan\(/);
  assert.match(source, /resolveApprovalDecision\("approved"\)/);
  assert.match(source, /action\.type === "approve-all" \|\| action\.type === "approve-hunk"/);
  assert.match(source, /approveDisplayedPlan\(\)/);
  assert.match(source, /data-testid="approve-all"/);
  assert.equal(shortPlanHash("a1b2c3def456"), "a1b2c3");
});

test("error empty uses EmptyState; acceptance false / exit 3 is a refusal card", () => {
  const errored = renderQueue(
    baseState({
      draft: draftWith([], {
        ops: [],
        phase: "failed",
        error: { code: "boom", message: "런타임이 거절했습니다" },
        plan: null,
        validation: null,
      }),
    }),
  ).html;
  assert.match(errored, /data-testid="review-queue-error"/);
  assert.match(errored, /class="empty-state"/);
  assert.match(errored, /런타임이 거절했습니다/);

  assert.equal(
    queueRefusalMessage({
      verdict: { acceptance: false, reason: "검사 미통과", note: "n", ranAll: true, required: [], checks: [] },
      applyError: null,
      draftError: null,
      exitCodes: [],
    }),
    "검사 미통과",
  );
  const refused = renderQueue(
    baseState({
      candidateVerdict: {
        runId: "run-A",
        report: { acceptance: false, reason: "검사 미통과", note: "n", ranAll: true, required: [], checks: [] },
      },
    }),
  ).html;
  assert.match(refused, /data-testid="queue-refusal"/);
  assert.match(refused, /class="refusal"/);
  assert.match(refused, /검사 미통과/);
  const refusalBlock = refused.match(/data-testid="queue-refusal"[\s\S]*?<\/div>/)[0];
  assert.doesNotMatch(refusalBlock, /data-tone="ok"|tag ok/);
});

test("per-hunk 승인/거부 keep screen-reader names and existing queue testids", () => {
  const html = renderQueue(baseState()).html;
  assert.match(html, /aria-label="이 항목 승인"/);
  assert.match(html, /aria-label="이 항목 거부"/);
  assert.match(html, /data-testid="hunk-approve-0-0-14"/);
  assert.match(html, /data-testid="hunk-reject-0-0-14"/);
  assert.match(html, /data-testid="queue-value-op-1"/);
  assert.match(html, /data-testid="queue-provenance-0-0-14"/);
  assert.match(html, />출처</);
});
