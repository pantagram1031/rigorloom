import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { loadTrustModule, trustStoreSelectors } from "./action-test-support.mjs";

const require = createRequire(import.meta.url);

function loadModule(relPath, stubs = {}) {
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
  const req = (id) => (id in stubs ? stubs[id] : require(id));
  vm.runInThisContext(`(function(exports, require, module) {\n${outputText}\n})`)(
    module.exports,
    req,
    module,
  );
  return module.exports;
}

const vocabulary = loadModule("../src/i18n/vocabulary.ts");
const formTokens = loadModule("../src/i18n/formTokens.ts");
const planProjection = loadModule("../src/agent/planProjection.ts", {
  "../i18n/vocabulary.ts": vocabulary,
  "../i18n/vocabulary": vocabulary,
});
const fieldLabels = loadModule("../src/workspace/fieldLabels.ts", {
  "../uiVariant.ts": { uiVariant: () => "v1" },
  "../i18n/vocabulary.ts": vocabulary,
  "../i18n/vocabulary": vocabulary,
  "../i18n/formTokens.ts": formTokens,
  "../i18n/formTokens": formTokens,
});

function createGuardStub(summary) {
  return {
    useReviewGuardSummary: () => summary,
    setReviewGuardSummary: () => {},
    runAuthoritativeGuardDiff: async () => summary,
    buildIndexedChanges: (draft) =>
      (draft.ops ?? []).map((op, i) => ({
        ordinal: i + 1,
        opId: op.opId,
        op,
        fieldLabel: `Blank ${i + 1}`,
        opKindText: vocabulary.opKindLabel(op.kind, "ko"),
        beforeText: op.before ?? "",
        afterText: op.text ?? "",
        previewMode: "before_after",
        isAuditable: op.kind !== "fill_cell",
        hardFindings: [],
        warnFindings: [],
        targetKey: null,
        groupOrdinals: [],
      })),
    emptyReviewGuardSummary: () => summary,
  };
}

function makeWorkspaceState(overrides = {}) {
  return {
    activeSessionId: "session-A",
    language: "ko",
    sessions: [
      {
        sessionId: "session-A",
        openedUtc: "2026-11-15T00:00:00Z",
        source: { name: "sample.hwpx", sha256: "a".repeat(64), bytes: 1024, documentKind: "hwpx" },
      },
    ],
    inspects: {
      "session-A": {
        documentHash: "a".repeat(64),
        sessionId: "session-A",
        summary: { anchors: [], fillTargetCount: 1, spacerCells: [], scriptAnomalyTargets: [], removalTargets: [] },
        graph: { tables: [], paragraphs: [] },
        regions: { regions: [] },
      },
    },
    texts: { "session-A": [] },
    candidates: { "session-A": [] },
    draft: {
      ops: [{ opId: "op-1", kind: "set_run", atPara: 1, run: 0, text: "2027년", before: "2026년", origin: "user" }],
      plan: {
        schema: "rl-plan-v0",
        planId: "plan-1",
        planHash: "b".repeat(64),
        opsHash: "c".repeat(64),
        sessionId: "session-A",
        backend: "preedit",
        boundSha256: "a".repeat(64),
        base: null,
        reverses: null,
        createdUtc: "2026-11-15T00:00:00Z",
        proposer: "user",
        implVersion: "0",
        ops: [],
        state: "validated",
      },
      validation: {
        planId: "plan-1",
        planHash: "b".repeat(64),
        backend: "preedit",
        boundSha256: "a".repeat(64),
        currentSha256: "a".repeat(64),
        stale: false,
        ok: true,
        verdict: "pass",
        hard: [],
        warn: [],
        counts: { hard: 0, warn: 0, ops: 1 },
        preflight: { level: "standard", source: "python", deferred: [], note: "" },
      },
      sessionId: "session-A",
      boundSha256: "a".repeat(64),
      phase: "ready",
      error: null,
      rewrittenFromAgent: false,
      baseRunId: null,
      reverses: null,
    },
    render: null,
    geometry: null,
    head: null,
    approval: null,
    approvalPhase: "idle",
    approvalError: null,
    applyPhase: "idle",
    applied: null,
    applyError: null,
    recovery: null,
    applyOutcomes: {},
    reapprovalPrompt: null,
    returnPopoverOpen: false,
    approvalDialogOpen: true,
    pipelineWorkspace: "",
    pipelineGatesResult: null,
    pipelineGatesPhase: "idle",
    pipelineGatesError: null,
    ...overrides,
  };
}

function renderChangeList(guardSummary, stateOverrides = {}) {
  const state = makeWorkspaceState(stateOverrides);
  const storeStub = {
    useWorkspace: (sel) => sel(state),
    draftStaleness: () => null,
    headCandidate: () => null,
    ...trustStoreSelectors,
  };
  const trust = loadTrustModule(loadModule);
  const detailStub = {
    DetailDisclosure: ({ children }) => React.createElement("details", null, children),
  };
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
  const changeRowMod = loadModule("../src/components/ChangeRow.tsx", {
    react: React,
    "../actions": actionsStub,
    "../i18n/vocabulary": vocabulary,
    "../workspace/trust": trust,
    "./DetailDisclosure": detailStub,
  });
  const { ChangeList } = loadModule("../src/components/ChangeList.tsx", {
    react: React,
    "../actions": actionsStub,
    "../i18n/vocabulary": vocabulary,
    "../store": storeStub,
    "../workspace/trust": trust,
    "./ChangeRow": changeRowMod,
    "./DetailDisclosure": detailStub,
  });
  const changes = createGuardStub(guardSummary).buildIndexedChanges(state.draft);
  return renderToStaticMarkup(
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
}

function renderApprovalDialog(guardSummary, stateOverrides = {}) {
  const state = makeWorkspaceState(stateOverrides);
  const storeStub = {
    useWorkspace: (sel) => sel(state),
    activeInspect: (s) => s.inspects[s.activeSessionId] ?? null,
    activeText: (s) => s.texts[s.activeSessionId] ?? [],
    draftStaleness: () => null,
    ...trustStoreSelectors,
  };
  const actionsStub = {
    approveAndApplyFromDialog: () => {},
    closeApprovalDialog: () => {},
    rememberApprovedGuard: () => {},
    reproposeDraft: () => {},
    resolveRecovery: () => {},
    revisionNumberFor: () => 1,
  };
  const { ApprovalDialog } = loadModule("../src/components/ApprovalDialog.tsx", {
    react: React,
    "../actions": actionsStub,
    "../i18n/vocabulary": vocabulary,
    "../store": storeStub,
    "../workspace/externalPlan": { buildRegionTextMap: () => ({}) },
    "../workspace/guardHelper": createGuardStub(guardSummary),
    "../workspace/sheetConfirmation": { prepareSheetConfirmation: () => {}, clearSheetConfirmation: () => {} },
    "../workspace/trust": loadTrustModule(loadModule),
    "./DetailDisclosure": {
      DetailDisclosure: ({ children }) => React.createElement("details", null, children),
    },
  });
  return renderToStaticMarkup(React.createElement(ApprovalDialog));
}

test("invalid plan guard summary refuses to show pass header and renders guard-not-run-notice", () => {
  const html = renderChangeList({
    planId: "plan-1",
    state: "invalid_plan",
    error: null,
    changedFactOpIds: [],
    rowAudits: {},
  });
  assert.match(html, /data-testid="guard-not-run-notice"/);
  assert.doesNotMatch(html, /data-testid="guard-list-header"/);
});

test("unavailable guard summary renders guard-unavailable-notice and hides changed-facts-jumper", () => {
  const html = renderChangeList({
    planId: "plan-1",
    state: "unavailable",
    error: "guard unavailable",
    changedFactOpIds: ["op-1"],
    rowAudits: { "op-1": { status: "not_checked", paragraph: null, addedNumbers: [] } },
  });
  assert.match(html, /data-testid="guard-unavailable-notice"/);
  assert.doesNotMatch(html, /data-testid="guard-list-header"/);
});

test("ready guard summary with zero changed facts renders clean guard-list-header without jumper", () => {
  const html = renderChangeList({
    planId: "plan-1",
    state: "ready",
    error: null,
    changedFactOpIds: [],
    rowAudits: { "op-1": { status: "kept", paragraph: null, addedNumbers: [] } },
  });
  assert.match(html, /data-testid="guard-list-header"/);
  assert.doesNotMatch(html, /data-testid="changed-facts-jumper"/);
});

test("ApprovalDialog surfaces guard_skipped notice on unavailable guard and gates confirm on changed-fact ack", () => {
  const skippedHtml = renderApprovalDialog({
    planId: "plan-1",
    state: "unavailable",
    error: "guard unavailable",
    changedFactOpIds: [],
    rowAudits: {},
  });
  assert.match(skippedHtml, /data-testid="approval-guard-skipped"/);

  const changedHtml = renderApprovalDialog({
    planId: "plan-1",
    state: "ready",
    error: null,
    changedFactOpIds: ["op-1"],
    rowAudits: {
      "op-1": { status: "changed", paragraph: { kinds: ["numbers"], before: "2026", after: "2027" }, addedNumbers: [] },
    },
  });
  assert.match(changedHtml, /data-testid="approval-changed-facts-ack"/);
  assert.match(changedHtml, /data-testid="approval-confirm-btn"[^>]*disabled/);
});
