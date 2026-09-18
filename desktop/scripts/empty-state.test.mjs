import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const nodeRequire = createRequire(import.meta.url);
const corpus = JSON.parse(
  readFileSync(new URL("../src/fixtures/corpus.json", import.meta.url), "utf8"),
);

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

import { Icon } from "./icon-stub.mjs";
import { uiFromImport } from "./kit-load.mjs";

const label = loadCompiled("../src/label.ts", "label.ts", () => {
  throw new Error("label.ts has no imports");
});

const emptyState = loadCompiled("../src/components/EmptyState.tsx", "EmptyState.tsx", (id) => {
  if (id === "react/jsx-runtime") return nodeRequire(id);
  if (id === "react") return nodeRequire(id);
  if (id === "../label") return label;
  if (id === "./Icon") return { Icon };
        const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
});

function jsxRequire(id) {
  if (id === "react/jsx-runtime") return nodeRequire(id);
  if (id === "react") return nodeRequire(id);
  if (id === "./EmptyState") return emptyState;
  if (id === "./Icon") return { Icon };
  if (id === "../label") return label;
  const ui = uiFromImport(id);
  if (ui) return ui;
  return null;
}

function assertNoObjectObject(html) {
  assert.doesNotMatch(html, /\[object Object\]/);
}

test("labelOf never stringifies an error object as [object Object]", () => {
  assert.equal(label.labelOf({ code: "dev_mock", message: "no fixture for task_packs" }), "no fixture for task_packs");
  assert.equal(label.labelOf("브라우저 미리보기에는 작업 팩 등록기가 없습니다."), "브라우저 미리보기에는 작업 팩 등록기가 없습니다.");
  assert.equal(label.labelOf(null, "없음"), "없음");
});

function renderTaskPacks(state) {
  const exports = loadCompiled("../src/components/TaskPacks.tsx", "TaskPacks.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../label") return label;
    if (id === "../store") {
      return { useWorkspace: (selector) => selector(state) };
    }
    if (id === "../actions") {
      return {
        locateFindingAddress: () => {},
        openPack: () => {},
        packEnablementDisagrees: () => [],
        runModuleCheck: () => {},
        runtimeEnabledModules: () => null,
      };
    }
    if (id === "../types") return {};
    if (id === "./Tag") {
      return {
        Tag: ({ children }) => React.createElement("span", null, children),
      };
    }
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  return renderToStaticMarkup(React.createElement(exports.TaskPacks));
}

test("TaskPacks with the devMock fixture does not print [object Object]", () => {
  const html = renderTaskPacks({
    taskPacks: {
      available: false,
      mode: "browser",
      reason: "브라우저 미리보기에는 작업 팩 등록기가 없습니다.",
      packs: [],
    },
    packOpen: null,
    packRun: null,
    activeSessionId: "devfixture0000000000000000000000",
    source: corpus.source,
  });
  assert.match(html, /data-testid="task-packs"/);
  assert.match(html, /작업 팩/);
  assert.match(html, /브라우저 미리보기에는 작업 팩 등록기가 없습니다/);
  assertNoObjectObject(html);
  assert.ok(corpus.source?.name, "devMock corpus fixture is present");
});

test("TaskPacks labels an object reason instead of [object Object]", () => {
  const html = renderTaskPacks({
    taskPacks: {
      available: false,
      mode: null,
      reason: { code: "dev_mock", message: "no fixture for task_packs" },
      packs: [],
    },
    packOpen: null,
    packRun: null,
    activeSessionId: null,
  });
  assert.match(html, /no fixture for task_packs/);
  assertNoObjectObject(html);
});

test("TaskPacks pack rows label an object blurb instead of [object Object]", () => {
  const html = renderTaskPacks({
    taskPacks: {
      available: true,
      mode: "browser",
      reason: null,
      packs: [
        {
          name: "report",
          title: "탐구·보고서",
          blurb: { nested: "should not render as object" },
          named: true,
          enabled: true,
          requiresModules: null,
          checkers: [],
          cli: [],
        },
      ],
    },
    packOpen: null,
    packRun: null,
    activeSessionId: null,
  });
  assert.match(html, /탐구·보고서/);
  assert.match(html, /should not render as object/);
  assertNoObjectObject(html);
});

function emptyDraft() {
  return {
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
}

test("ReviewQueue empty state keeps review-queue-empty and is not a prose wall", () => {
  const state = {
    draft: emptyDraft(),
    approval: null,
    approvalPhase: "idle",
    approvalError: null,
    applyPhase: "idle",
    applyError: null,
    recovery: null,
    redoStack: [],
    activeSessionId: null,
    receipts: {},
    head: null,
    isComposing: false,
  };
  const exports = loadCompiled("../src/components/ReviewQueue.tsx", "ReviewQueue.tsx", (id) => {
    const known = jsxRequire(id);
    if (known) return known;
    if (id === "../actions") {
      return new Proxy({}, { get: () => () => {} });
    }
    if (id === "../store") {
      return {
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
    }
    if (id === "../types") return {};
    if (id === "../workspace/reviewSummary") {
      return { hasActiveApprovalBinding: () => false };
    }
    if (id === "../reviewHunk") {
      return {
        hunkReviewState: () => "queued",
        queueRefusalMessage: () => null,
        reviewQueueHotkey: () => ({ type: "none" }),
        shortPlanHash: (hash) => (hash ? String(hash).slice(0, 6) : null),
      };
    }
    if (id === "../focus") {
      return { focusFirstHunk: () => false, focusHunkAt: () => false };
    }
    if (id === "./HunkCard") {
      return { HunkCard: () => null };
    }
    if (id === "./Tag") {
      return { Tag: ({ children }) => React.createElement("span", null, children) };
    }
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  const html = renderToStaticMarkup(React.createElement(exports.ReviewQueue));
  assert.match(html, /data-testid="review-queue-empty"/);
  assert.match(html, /class="empty-state/);
  assert.match(html, /검토할 것이 없습니다/);
  assert.doesNotMatch(html, /비어 있습니다\. 문서 화면에서/);
});

test("History empty state keeps history-empty and uses EmptyState", () => {
  const state = {
    activeSessionId: "s",
    candidates: {},
    historySelected: null,
    undoError: null,
    inverseProof: null,
    receipts: {},
    head: null,
    events: [],
    compareLeftRunId: null,
    compareAgainst: { source: true },
    compareUseSelection: false,
    comparePhase: "idle",
    compareError: null,
    compareResult: null,
  };
  const exports = loadCompiled("../src/components/History.tsx", "History.tsx", (id) => {
    const known = jsxRequire(id);
    if (known) return known;
    if (id === "../actions") {
      return new Proxy({}, { get: () => () => {} });
    }
    if (id === "../store") {
      return {
        useWorkspace: (selector) => selector(state),
        activeCandidates: () => [],
        headCandidate: () => null,
        lineage: (rows) => rows,
        reversedBy: () => null,
        sessionHistory: () => [],
      };
    }
    if (id === "../types") return {};
    if (id === "./Tag") {
      return { Tag: ({ children }) => React.createElement("span", null, children) };
    }
    if (id === "./Timeline") {
      return { Timeline: () => React.createElement("div", { "data-testid": "timeline" }) };
    }
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  const html = renderToStaticMarkup(React.createElement(exports.History));
  assert.match(html, /data-testid="history-empty"/);
  assert.match(html, /class="empty-state/);
  assert.match(html, /아직 후보본이 없습니다/);
  assert.doesNotMatch(html, /아직 만들어진 후보본이 없습니다/);
});

test("Conversation empty keeps conversation-empty and names the disconnected host", () => {
  const state = {
    turns: [],
    activeTurn: null,
    agentTool: { available: false, script: null, reason: "브라우저 미리보기" },
    agentPhase: "idle",
    agentError: null,
    agentRun: null,
    activeSessionId: "devfixture0000000000000000000000",
    agentHost: {
      available: false,
      mode: null,
      script: null,
      program: null,
      reason: "브라우저 미리보기에는 에이전트 호스트가 없습니다.",
    },
  };
  const exports = loadCompiled("../src/components/Conversation.tsx", "Conversation.tsx", (id) => {
    const known = jsxRequire(id);
    if (known) return known;
    if (id === "../actions") {
      return { runAgentProposal: () => {}, stopInstruction: () => {} };
    }
    if (id === "../store") {
      return {
        useWorkspace: (selector) => selector(state),
        setState: () => {},
      };
    }
    if (id === "../types") return {};
    if (id === "./Tag") {
      return { Tag: ({ children }) => React.createElement("span", null, children) };
    }
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  const html = renderToStaticMarkup(React.createElement(exports.Conversation));
  assert.match(html, /data-testid="conversation-empty"/);
  assert.match(html, /class="empty-state/);
  assert.match(html, /에이전트가 연결되어 있지 않습니다/);
  assert.match(html, /설정 열기/);
  assertNoObjectObject(html);
});

test("ready conversation empty relocates composer-note onto the honesty line", () => {
  const state = {
    turns: [],
    activeTurn: null,
    agentTool: { available: false, script: null, reason: null },
    agentPhase: "idle",
    agentError: null,
    agentRun: null,
    activeSessionId: "s",
    agentHost: { available: true, mode: "mock", script: null, program: null, reason: null },
  };
  const exports = loadCompiled("../src/components/Conversation.tsx", "Conversation.tsx", (id) => {
    const known = jsxRequire(id);
    if (known) return known;
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
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  const html = renderToStaticMarkup(React.createElement(exports.Conversation));
  assert.match(html, /data-testid="composer-note"/);
  assert.match(html, /data-testid="conversation-empty"/);
  assert.match(html, /승인은 사람이 합니다/);
});

test("SessionList empty uses EmptyState and keeps session-list", () => {
  const state = {
    sessions: [],
    activeSessionId: null,
    root: "C:\\dev-fixture\\runtime-root",
    taskPacks: {
      available: false,
      mode: "browser",
      reason: "브라우저 미리보기에는 작업 팩 등록기가 없습니다.",
      packs: [],
    },
    packOpen: null,
  };
  const exports = loadCompiled("../src/components/SessionList.tsx", "SessionList.tsx", (id) => {
    const known = jsxRequire(id);
    if (known) return known;
    if (id === "../store") {
      return { useWorkspace: (selector) => selector(state) };
    }
    if (id === "../types") return {};
    if (id === "../actions") return { bindFormAndOpen: () => {} };
    if (id === "./TaskPacks") {
      return { TaskPacks: () => React.createElement("div", { "data-testid": "task-packs" }) };
    }
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  const html = renderToStaticMarkup(
    React.createElement(exports.SessionList, { onSelect: () => {}, onOpen: () => {} }),
  );
  assert.match(html, /data-testid="session-list"/);
  assert.match(html, /class="empty-state/);
  assert.match(html, /연 문서가 없습니다/);
  assert.doesNotMatch(html, /아직 연 문서가 없습니다/);
});
