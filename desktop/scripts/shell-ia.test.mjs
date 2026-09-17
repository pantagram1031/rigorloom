import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { Icon } from "./icon-stub.mjs";

const nodeRequire = createRequire(import.meta.url);

const {
  EMPTY_DRAFT,
  defaultInspectorTab,
  getState,
  inspectorAgentUnread,
  inspectorHistoryBadge,
  inspectorReviewBadge,
  selectInspectorTab,
  setLeftRailCollapsed,
  setState,
  setView,
  visibleInspectorTab,
} = await import("../src/store.ts");

const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const contextSource = readFileSync(
  new URL("../src/components/ContextPanel.tsx", import.meta.url),
  "utf8",
);

function fakeOp() {
  return {
    opId: "op-1",
    kind: "fill_cell",
    table: 0,
    row: 0,
    col: 0,
    text: "값",
    before: "",
    origin: "user",
  };
}

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

test("default inspector tab is 검토 when the draft has queued ops or a pending approval", () => {
  const before = getState();
  try {
    setState({
      view: "document",
      inspectorTab: "selection",
      inspectorTabUserSet: false,
      approvalPhase: "idle",
      draft: { ...EMPTY_DRAFT },
    });
    assert.equal(defaultInspectorTab(getState()), "selection");
    assert.equal(visibleInspectorTab(getState()), "selection");

    setState({ draft: { ...EMPTY_DRAFT, ops: [fakeOp()] } });
    assert.equal(defaultInspectorTab(getState()), "review");
    assert.equal(visibleInspectorTab(getState()), "review");

    setState({ draft: { ...EMPTY_DRAFT }, approvalPhase: "pending" });
    assert.equal(defaultInspectorTab(getState()), "review");
    assert.equal(visibleInspectorTab(getState()), "review");
  } finally {
    setState({
      view: before.view,
      inspectorTab: before.inspectorTab,
      inspectorTabUserSet: before.inspectorTabUserSet,
      approvalPhase: before.approvalPhase,
      draft: before.draft,
    });
  }
});

test("a remembered inspector tab survives the default-tab rule until Ctrl+2", () => {
  const before = getState();
  try {
    setState({
      view: "document",
      inspectorTab: "history",
      inspectorTabUserSet: true,
      lastNonAgentInspectorTab: "history",
      approvalPhase: "idle",
      draft: { ...EMPTY_DRAFT, ops: [fakeOp()] },
    });
    assert.equal(visibleInspectorTab(getState()), "history");
    selectInspectorTab("selection");
    assert.equal(getState().inspectorTab, "selection");
    assert.equal(visibleInspectorTab(getState()), "selection");
  } finally {
    setState({
      view: before.view,
      inspectorTab: before.inspectorTab,
      inspectorTabUserSet: before.inspectorTabUserSet,
      lastNonAgentInspectorTab: before.lastNonAgentInspectorTab,
      approvalPhase: before.approvalPhase,
      draft: before.draft,
    });
  }
});

test("badge counts: 검토 ops + pending marker, 기록 candidates, 에이전트 unread turns", () => {
  const before = getState();
  try {
    setState({
      draft: { ...EMPTY_DRAFT, ops: [fakeOp(), { ...fakeOp(), opId: "op-2", col: 1 }] },
      approvalPhase: "pending",
      activeSessionId: "sess-a",
      candidates: { "sess-a": [{ runId: "r1" }, { runId: "r2" }, { runId: "r3" }] },
      turns: [{ id: "t1" }, { id: "t2" }, { id: "t3" }, { id: "t4" }],
      agentTurnsSeen: 1,
    });
    const review = inspectorReviewBadge(getState());
    assert.equal(review.count, 2);
    assert.equal(review.pending, true);
    assert.equal(inspectorHistoryBadge(getState()), 3);
    assert.equal(inspectorAgentUnread(getState()), 3);
  } finally {
    setState({
      draft: before.draft,
      approvalPhase: before.approvalPhase,
      activeSessionId: before.activeSessionId,
      candidates: before.candidates,
      turns: before.turns,
      agentTurnsSeen: before.agentTurnsSeen,
    });
  }
});

test("setView('agent') and Ctrl+2 select the 에이전트 inspector tab without a second layout", () => {
  const before = getState();
  try {
    setState({
      view: "document",
      inspectorTab: "selection",
      inspectorTabUserSet: false,
    });
    setView("agent");
    assert.equal(getState().view, "agent");
    assert.equal(visibleInspectorTab(getState()), "agent");
    assert.match(appSource, /case "2":/);
    assert.match(appSource, /switchView\("agent"\)/);
    assert.match(appSource, /<DocumentView \/>/);
    assert.doesNotMatch(appSource, /viewswitch/);
    assert.doesNotMatch(appSource, /data-testid="view-agent"/);
    assert.match(contextSource, /data-testid=\{`inspector-tab-\$\{row\.id\}`\}/);
    assert.match(contextSource, /tab === "review" \? <ReviewQueue/);
    const agentHost = contextSource.slice(contextSource.lastIndexOf('tab === "agent"'));
    assert.doesNotMatch(agentHost, /<ReviewQueue/);
  } finally {
    setState({
      view: before.view,
      inspectorTab: before.inspectorTab,
      inspectorTabUserSet: before.inspectorTabUserSet,
      lastNonAgentInspectorTab: before.lastNonAgentInspectorTab,
      editIntentGeneration: before.editIntentGeneration,
    });
  }
});

test("left rail collapse state is remembered in workspace state", () => {
  const before = getState();
  try {
    assert.equal(getState().leftRailCollapsed, false);
    setLeftRailCollapsed(true);
    assert.equal(getState().leftRailCollapsed, true);
    setLeftRailCollapsed(false);
    assert.equal(getState().leftRailCollapsed, false);
    assert.match(appSource, /case "b":/);
    assert.match(appSource, /toggleLeftRail\(\)/);
  } finally {
    setState({ leftRailCollapsed: before.leftRailCollapsed });
  }
});

test("the 자세히 popover lists every former verification chip", () => {
  const state = {
    status: { running: true, initialized: true, pid: 12, mode: "dev", jobConfined: true },
    checkPhase: "idle",
    findings: [],
    checkedAt: null,
    sheetOpen: false,
    applied: null,
    candidateVerdict: null,
    exportPhase: "idle",
    exportResult: null,
    exportError: null,
    reopened: null,
    draft: { ops: [] },
    centerMode: "text",
    page: 1,
    render: null,
    selection: { kind: "cell", table: 0, row: 1, col: 2 },
    overlayPick: null,
    geometry: null,
    inlineEdit: null,
    verifyDetailsOpen: true,
  };
  const compiled = compile("../src/components/VerificationBar.tsx", "VerificationBar.tsx");
  const module = { exports: {} };
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return nodeRequire(id);
      if (id === "react") return nodeRequire(id);
      if (id === "../actions") {
        return {
          exportApplied: () => {},
          openReceipt: () => {},
          reopenExported: () => {},
          runCheck: () => {},
        };
      }
      if (id === "../store") {
        return {
          useWorkspace: (selector) => selector(state),
          setState: () => {},
        };
      }
      if (id === "../types") return {};
      if (id === "./Tag") {
        return {
          Tag: ({ children, title }) =>
            React.createElement("span", { title }, children),
        };
      }
      if (id === "./Icon") return { Icon };
      if (id === "../verifyReport") {
        return { worstVerifyVerdict: () => null, verifyTargetLabel: () => "원본" };
      }
      throw new Error(`unexpected import: ${id}`);
    },
  });
  const html = renderToStaticMarkup(
    React.createElement(module.exports.VerificationBar, {
      session: { sessionId: "s", openedUtc: "", source: { name: "양식.hwpx", documentKind: "hwpx", bytes: 1, sha256: "abc" } },
      inspect: {
        documentHash: "abc",
        summary: { fillTargetCount: 4 },
        regions: { regions: [] },
      },
      candidates: [],
    }),
  );
  assert.match(html, /data-testid="verify-details-toggle"/);
  assert.match(html, /자세히/);
  assert.match(html, /data-testid="verify-details"/);
  for (const chip of [
    "쪽",
    "위치",
    "입력",
    "원본",
    "후보본",
    "그림 증명",
    "적용 시 검사",
    "입력 칸",
    "서식 점검",
    "엔진",
    "종료 시 정리",
    "지면 출처",
  ]) {
    assert.match(html, new RegExp(chip));
  }
  assert.match(html, /data-testid="status-where"/);
  assert.match(html, /data-testid="run-check"/);
  assert.match(html, /증명 없음/);
  assert.match(html, /페이지 그림은 보여줄 수 있어도 증거가 아닙니다/);
  assert.match(html, /data-testid="verify-pill"/);
  assert.match(html, /검사 안 함/);
  assert.match(html, /엔진 연결됨/);
});

test("ContextPanel tab strip is keyboard-labelled and keeps approvals in 검토", () => {
  assert.match(contextSource, /role="tablist"/);
  assert.match(contextSource, /ArrowRight/);
  assert.match(contextSource, /inspector-tabs/);
  assert.match(contextSource, /tab === "review" \? <ReviewQueue/);
  const agentSlice = contextSource.slice(contextSource.lastIndexOf('tab === "agent"'));
  assert.doesNotMatch(agentSlice, /<ReviewQueue/);
  assert.match(agentSlice, /<Conversation/);
  assert.match(agentSlice, /<Composer/);
  const docs = readFileSync(new URL("../src/components/DocumentContext.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(docs, /<ReviewQueue/);
  assert.match(docs, /승인은 검토 탭에서만 합니다/);
});
