import {
  approvalHelpers,
  agentPlanCellAddresses,
  opKindLabel,
  projectAgentPlan,
  t,
} from "./action-test-support.mjs";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire, stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { loadTrustModule, trustStoreSelectors } from "./action-test-support.mjs";

const nodeRequire = createRequire(import.meta.url);

function loadTsModule(relPath, stubs = {}) {
  const source = readFileSync(new URL(relPath, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
    fileName: relPath,
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

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

const EMPTY_DRAFT = {
  ops: [],
  plan: null,
  validation: null,
  sessionId: null,
  boundSha256: null,
  phase: "idle",
  error: null,
  rewrittenFromAgent: false,
  baseRunId: null,
  reverses: null,
};

function setupExternalAdoptFixture() {
  const actionsSrc = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
  const between = (startText, endText) => {
    const start = actionsSrc.indexOf(startText);
    const end = endText ? actionsSrc.indexOf(endText, start) : actionsSrc.length;
    assert.ok(start >= 0 && end > start, `source boundary missing: ${startText}`);
    return actionsSrc.slice(start, end);
  };

  const lease = between("interface DraftOwner", "/** Load a session's inspect");
  const adoptAgent = between("async function adoptAgentPlan(", "/** Ids are the shell's");
  const applySlice = between('const APPLY_TAG = "apply"', "/** Cooperative cancel");
  const externalTailAnchor = actionsSrc.includes("let inFlightExternalAdopt")
    ? "let inFlightExternalAdopt"
    : "export async function adoptExternalPlan(";
  const externalTail = between(externalTailAnchor, null);

  const externalPlan = loadTsModule("../src/workspace/externalPlan.ts");

  let state = {
    activeSessionId: "session-A",
    language: "ko",
    draft: { ...EMPTY_DRAFT },
    head: null,
    candidates: { "session-A": [] },
    approval: null,
    approvalPhase: "idle",
    approvalError: null,
    applyPhase: "idle",
    applyError: null,
    applyOutcomes: {},
    recovery: null,
    redoStack: [],
    inspects: {
      "session-A": {
        documentHash: "h",
        sessionId: "session-A",
        summary: { anchors: [], fillTargetCount: 0, spacerCells: [], scriptAnomalyTargets: [], removalTargets: [] },
        graph: { tables: [], paragraphs: [] },
        regions: { regions: [] },
      },
    },
    texts: { "session-A": [] },
  };
  let generation = 1;
  const plans = [];
  const validations = [];
  const approvals = [];
  const applies = [];

  const rt = {
    getPlan(planId) {
      const p = deferred();
      plans.push({ ...p, planId });
      return p.promise;
    },
    validatePlan(planId) {
      const p = deferred();
      validations.push({ ...p, planId });
      return p.promise;
    },
    readRegion: async () => ({ regions: [] }),
    getApproval(approvalId) {
      const p = deferred();
      approvals.push({ ...p, approvalId });
      return p.promise;
    },
    applyPlan(planId, approvalId) {
      const p = deferred();
      applies.push({ ...p, planId, approvalId });
      return p.promise;
    },
    asRuntimeError(err) {
      return { code: "test_err", message: String(err) };
    },
  };

  const implCode = [
    lease,
    approvalHelpers,
    adoptAgent,
    applySlice,
    externalTail,
  ]
    .join("\n")
    .replaceAll("export ", "");

  const context = vm.createContext({
    EMPTY_DRAFT,
    rt,
    agentPlanCellAddresses,
    projectAgentPlan,
    draftStaleness: () => null,
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    currentPlanGeneration: () => generation,
    headCandidate: (current) => (current.head ? { runId: current.head } : null),
    canRequestApproval: () => true,
    loadCandidates: async () => {},
    verifyReversal: async () => true,
    showToast: () => {},
    seatText: () => "",
    markExternalPlanDismissed: externalPlan.markExternalPlanDismissed,
    opKindLabel,
    t,
  });

  vm.runInContext(
    `${stripTypeScriptTypes(implCode)}
globalThis.invokeAdoptExternal = adoptExternalPlan;
globalThis.invokeAttachApproval = typeof attachExternalApproval === "function" ? attachExternalApproval : null;
globalThis.invokeApply = applyApproved;`,
    context,
  );

  return {
    externalPlan,
    read: () => state,
    patch: (p) => {
      state = { ...state, ...p };
    },
    plans,
    validations,
    approvals,
    applies,
    adoptExternal: (sid, pid, aid) => context.invokeAdoptExternal(sid, pid, aid),
    attachApproval: context.invokeAttachApproval,
    apply: () => context.invokeApply(),
    tick: () => new Promise((resolve) => setImmediate(resolve)),
  };
}

test("findAdoptableExternalPlan ignores rigorloom-desktop plans and starting drafts", () => {
  const externalPlan = loadTsModule("../src/workspace/externalPlan.ts");
  const uiProposedEvents = [
    {
      seq: 1,
      kind: "plan.proposed",
      sessionId: "session-ui",
      detail: { planId: "ui-plan-1", proposer: "rigorloom-desktop" },
    },
  ];
  assert.equal(
    externalPlan.findAdoptableExternalPlan("session-ui", uiProposedEvents, EMPTY_DRAFT),
    null,
  );

  const extProposedEvents = [
    {
      seq: 2,
      kind: "plan.proposed",
      sessionId: "session-ext",
      detail: { planId: "ext-plan-1", proposer: "host-client" },
    },
  ];
  assert.equal(
    externalPlan.findAdoptableExternalPlan("session-ext", extProposedEvents, {
      ...EMPTY_DRAFT,
      phase: "starting",
    }),
    null,
  );
});

test("split SSE plan.proposed then approval.requested adopts plan once and preserves approvalId", async () => {
  const f = setupExternalAdoptFixture();
  const planObj = {
    planId: "ext-plan-1",
    planHash: "ext-hash-1",
    boundSha256: "src-hash",
    sessionId: "session-A",
    ops: [{ opId: "op-1", kind: "set_run", params: { atPara: 0, run: 0, text: "next" } }],
    proposer: "host-client",
    base: null,
    reverses: null,
  };

  // Batch 1: plan.proposed arrives before approval.requested
  const p1 = f.adoptExternal("session-A", "ext-plan-1", null);
  await f.tick();
  // Batch 2: approval.requested arrives while batch 1 is still awaiting getPlan
  const p2 = f.adoptExternal("session-A", "ext-plan-1", "ext-approval-1");
  await f.tick();

  assert.equal(f.plans.length, 1, "concurrent SSE batch must not launch duplicate plan/get");
  f.plans[0].resolve(planObj);
  await f.tick();
  assert.equal(f.validations.length, 1, "concurrent SSE batch must not launch duplicate plan/validate");
  f.validations[0].resolve({ ok: true, stale: false, hard: [], warn: [] });
  await f.tick();

  assert.equal(f.approvals.length, 1, "approval/get must be invoked for pendingApprovalId");
  f.approvals[0].resolve({
    approvalId: "ext-approval-1",
    planId: "ext-plan-1",
    planHash: "ext-hash-1",
    state: "pending",
  });
  await Promise.all([p1, p2]);

  assert.equal(f.read().draft.plan?.planId, "ext-plan-1");
  assert.equal(f.read().approval?.approvalId, "ext-approval-1");
});

test("late approval.requested attaches to already-adopted draft without replacing draft reference", async () => {
  const f = setupExternalAdoptFixture();
  assert.equal(typeof f.externalPlan.findPendingExternalApproval, "function");
  assert.equal(typeof f.attachApproval, "function");

  const planObj = {
    planId: "ext-plan-2",
    planHash: "ext-hash-2",
    boundSha256: "src-hash",
    sessionId: "session-A",
    ops: [{ opId: "op-1", kind: "set_run", params: { atPara: 0, run: 0, text: "next" } }],
    proposer: "host-client",
    base: null,
    reverses: null,
  };

  const adoptPromise = f.adoptExternal("session-A", "ext-plan-2", null);
  await f.tick();
  f.plans[0].resolve(planObj);
  await f.tick();
  f.validations[0].resolve({ ok: true, stale: false, hard: [], warn: [] });
  await adoptPromise;

  const draftBefore = f.read().draft;
  const events = [
    { seq: 1, kind: "plan.proposed", sessionId: "session-A", detail: { planId: "ext-plan-2", proposer: "host-client" } },
    { seq: 2, kind: "approval.requested", sessionId: "session-A", detail: { planId: "ext-plan-2", approvalId: "ext-approval-2" } },
  ];

  const pending = f.externalPlan.findPendingExternalApproval(
    "session-A",
    events,
    f.read().draft,
    f.read().approval,
  );
  assert.deepEqual(pending, { planId: "ext-plan-2", approvalId: "ext-approval-2" });

  const attachPromise = f.attachApproval("session-A", pending.planId, pending.approvalId);
  await f.tick();
  f.approvals[0].resolve({
    approvalId: "ext-approval-2",
    planId: "ext-plan-2",
    planHash: "ext-hash-2",
    state: "pending",
  });
  await attachPromise;

  assert.equal(f.read().draft, draftBefore, "attaching approval must preserve draft reference");
  assert.equal(f.read().approval?.approvalId, "ext-approval-2");
});

test("applyApproved dismisses the applied plan so ReviewView cannot re-adopt before plan.applied SSE arrives", async () => {
  const f = setupExternalAdoptFixture();
  const planObj = {
    planId: "ext-plan-3",
    planHash: "ext-hash-3",
    boundSha256: "src-hash",
    sessionId: "session-A",
    ops: [{ opId: "op-1", kind: "set_run", params: { atPara: 0, run: 0, text: "next" } }],
    proposer: "host-client",
    base: null,
    reverses: null,
  };

  const p = f.adoptExternal("session-A", "ext-plan-3", "ext-approval-3");
  await f.tick();
  f.plans[0].resolve(planObj);
  await f.tick();
  f.validations[0].resolve({ ok: true, stale: false, hard: [], warn: [] });
  await f.tick();
  f.approvals[0].resolve({
    approvalId: "ext-approval-3",
    planId: "ext-plan-3",
    planHash: "ext-hash-3",
    state: "approved",
  });
  await p;

  const applyP = f.apply();
  await f.tick();
  f.applies[0].resolve({
    runId: "run-3",
    candidate: { sha256: "b".repeat(64) },
    checks: { ranAll: true, acceptance: true },
  });
  await applyP;

  const eventsWithoutApplied = [
    { seq: 1, kind: "plan.proposed", sessionId: "session-A", detail: { planId: "ext-plan-3", proposer: "host-client" } },
    { seq: 2, kind: "approval.requested", sessionId: "session-A", detail: { planId: "ext-plan-3", approvalId: "ext-approval-3" } },
  ];
  assert.equal(
    f.externalPlan.findAdoptableExternalPlan("session-A", eventsWithoutApplied, f.read().draft),
    null,
  );
});

test("ChangeList exposes data-guard-state and data-guard-plan-id readiness markers", () => {
  const vocabulary = loadTsModule("../src/i18n/vocabulary.ts");
  const actionsStub = {
    exportApplied: () => {},
    navigateScreen: () => {},
    openApprovalDialog: () => {},
    reproposeDraft: () => {},
    resolveRecovery: () => {},
    revisionNumberFor: () => 1,
    setReturnPopoverOpen: () => {},
    declareSuggestedCharPr: () => {},
    editOpValue: () => {},
    undoQueuedOp: () => {},
  };
  const detailStub = {
    DetailDisclosure: ({ children }) => React.createElement("details", null, children),
  };
  const state = {
    activeSessionId: "session-A",
    language: "ko",
    sessions: [],
    inspects: {},
    render: null,
    geometry: null,
    draft: { ...EMPTY_DRAFT, sessionId: "session-A" },
    approval: null,
    approvalPhase: "idle",
    applyPhase: "idle",
    applied: null,
    applyError: null,
    recovery: null,
    applyOutcomes: {},
    reapprovalPrompt: null,
    returnPopoverOpen: false,
    candidates: { "session-A": [] },
    head: null,
  };
  const storeStub = {
    useWorkspace: (sel) => sel(state),
    draftStaleness: () => null,
    headCandidate: () => null,
    ...trustStoreSelectors,
  };
  const trust = loadTrustModule(loadTsModule);
  const changeRowMod = loadTsModule("../src/components/ChangeRow.tsx", {
    react: React,
    "../actions": actionsStub,
    "../i18n/vocabulary": vocabulary,
    "../workspace/trust": trust,
    "./DetailDisclosure": detailStub,
  });
  const { ChangeList } = loadTsModule("../src/components/ChangeList.tsx", {
    react: React,
    "../actions": actionsStub,
    "../i18n/vocabulary": vocabulary,
    "../store": storeStub,
    "../workspace/trust": trust,
    "./ChangeRow": changeRowMod,
    "./DetailDisclosure": detailStub,
  });
  const changes = [
    {
      ordinal: 1,
      originalIndex: 0,
      op: { opId: "op-1", kind: "set_run", atPara: 0, run: 0, text: "b", before: "a", origin: "agent" },
      opId: "op-1",
      fieldLabel: "F",
      opKindText: "K",
      beforeText: "a",
      afterText: "b",
      targetKey: "p:0",
      hardFindings: [],
      warnFindings: [],
      hasHardFailure: false,
      isAuditable: true,
      isEmptyBlankFill: false,
      previewMode: "diff",
      invertible: true,
    },
  ];
  const renderWithSummary = (guardSummary) =>
    renderToStaticMarkup(
      React.createElement(ChangeList, {
        sessionId: "session-A",
        changes,
        guardSummary,
        selectedChangeId: "op-1",
        expandedChangeId: null,
        focusEditNonce: 0,
        language: "ko",
        onSelectChange: () => {},
        onToggleExpand: () => {},
        onJumpNextChangedFact: () => {},
        onConfirmReturn: async () => {},
      }),
    );

  const runningHtml = renderWithSummary({
    state: "running",
    planId: "plan-1",
    documentDiff: null,
    rowAudits: {},
    changedFactOpIds: [],
    needsFixesOpIds: [],
    errorCode: null,
  });
  assert.match(runningHtml, /data-testid="guard-list-header"/);
  assert.match(runningHtml, /data-guard-state="running"/);
  assert.match(runningHtml, /data-guard-plan-id="plan-1"/);

  const readyHtml = renderWithSummary({
    state: "ready",
    planId: "plan-1",
    documentDiff: null,
    rowAudits: { "op-1": { status: "kept", paragraph: { paragraph: 1, pass: true, edited: true, kinds: [], changes: [] }, addedNumbers: [] } },
    changedFactOpIds: [],
    needsFixesOpIds: [],
    errorCode: null,
  });
  assert.match(readyHtml, /data-guard-state="ready"/);
  assert.match(readyHtml, /data-guard-plan-id="plan-1"/);
});

test("ReviewView guard diff effect uses semantic deps instead of raw draft/changes objects and skips already-ready key", () => {
  const reviewSrc = readFileSync(new URL("../src/views/ReviewView.tsx", import.meta.url), "utf8");
  const idx = reviewSrc.indexOf("runAuthoritativeGuardDiff(");
  assert.ok(idx > 0);
  const effectStart = reviewSrc.lastIndexOf("useEffect(() => {", idx);
  const effectEnd = reviewSrc.indexOf("}, [", idx);
  const depsEnd = reviewSrc.indexOf("]);", effectEnd);
  assert.ok(effectStart >= 0 && effectEnd > effectStart && depsEnd > effectEnd);
  const effectBody = reviewSrc.slice(effectStart, depsEnd);
  const depsText = reviewSrc.slice(effectEnd, depsEnd);
  assert.doesNotMatch(depsText, /\bchanges,/);
  assert.doesNotMatch(depsText, /\bdraft\b/);
  assert.match(effectBody, /getReviewGuardKey/);
});
