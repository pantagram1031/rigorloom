import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { Icon } from "./icon-stub.mjs";
import { uiFromImport } from "./kit-load.mjs";

const nodeRequire = createRequire(import.meta.url);
const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

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

function innerOfTestId(html, testId) {
  const attr = `data-testid="${testId}"`;
  const i = html.indexOf(attr);
  if (i < 0) return null;
  const open = html.lastIndexOf("<", i);
  const tagEnd = html.indexOf(">", i);
  const tag = html.slice(open, tagEnd + 1);
  const name = tag.match(/^<\/?([a-zA-Z0-9-]+)/)?.[1];
  if (!name) return null;
  if (/\/>$/.test(tag)) return "";
  const close = `</${name}>`;
  let depth = 1;
  let pos = tagEnd + 1;
  while (depth > 0 && pos < html.length) {
    const nextOpen = html.indexOf(`<${name}`, pos);
    const nextClose = html.indexOf(close, pos);
    if (nextClose < 0) return null;
    if (nextOpen >= 0 && nextOpen < nextClose) {
      depth += 1;
      pos = nextOpen + name.length + 1;
    } else {
      depth -= 1;
      if (depth === 0) return html.slice(tagEnd + 1, nextClose);
      pos = nextClose + close.length;
    }
  }
  return null;
}

function renderDocumentView(state) {
  const exports = loadCompiled("../src/views/DocumentView.tsx", "DocumentView.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../actions") {
      return { openViaDialog() {}, selectSession() {}, toggleLeftRail() {} };
    }
    if (id === "../focus") {
      return { focusDocumentSurface: () => false };
    }
    if (id === "../store") {
      return {
        useWorkspace: (selector) => selector(state),
        activeInspect: (s) => s.inspect,
        activeSession: (s) => s.session,
        activeCandidates: (s) => s.candidates ?? [],
        isHome: (s) => !!s.home,
      };
    }
    if (id === "../components/ContextPanel") {
      return { ContextPanel: () => React.createElement("aside", { "data-testid": "context-panel" }) };
    }
    if (id === "../components/Icon") return { Icon };
    if (id === "../components/EditorToolbar") {
      return { EditorToolbar: () => React.createElement("div", { "data-testid": "editor-toolbar" }) };
    }
    if (id === "../components/Findings") return { Findings: () => null };
    if (id === "../components/PagePreview") return { PagePreview: () => null };
    if (id === "../components/ReceiptPanel") return { ReceiptPanel: () => null };
    if (id === "../components/SessionList") {
      return { SessionList: () => React.createElement("div", { "data-testid": "session-list" }) };
    }
    if (id === "../components/Skeleton") {
      return {
        SkeletonRows: () => React.createElement("div", { "data-testid": "tree-skeleton" }),
      };
    }
    if (id === "../components/StructureTree") {
      return {
        StructureTree: () =>
          React.createElement("div", { className: "tree", "data-testid": "structure-tree" }, "tree"),
      };
    }
    if (id === "../components/TextView") return { TextView: () => null };
    if (id === "../components/VerificationBar") {
      return { VerificationBar: () => React.createElement("footer") };
    }
    if (id === "../components/Welcome") {
      return { Home: () => React.createElement("div", { "data-testid": "welcome" }) };
    }
    if (id === "../components/PipelineStatus") {
      return {
        PipelineStrip: () => React.createElement("div", { "data-testid": "pipeline-strip" }),
        PipelinePanel: () => React.createElement("div", { "data-testid": "pipeline-panel" }),
      };
    }
    if (id === "../components/VerifyResults") {
      return { VerifyPanel: () => null };
    }
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  return renderToStaticMarkup(React.createElement(exports.DocumentView));
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
    if (id === "../store") {
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
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  return renderToStaticMarkup(React.createElement(exports.History));
}

function renderVerificationBar(state, props) {
  const exports = loadCompiled(
    "../src/components/VerificationBar.tsx",
    "VerificationBar.tsx",
    (id) => {
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
          Tag: ({ children, title }) => React.createElement("span", { title }, children),
        };
      }
      if (id === "./Icon") return { Icon };
      if (id === "../verifyReport") {
        return { worstVerifyVerdict: () => null, verifyTargetLabel: () => "원본" };
      }
            const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
    },
  );
  return renderToStaticMarkup(React.createElement(exports.VerificationBar, props));
}

test("rail footer is outside the scrolling tree", () => {
  const html = renderDocumentView({
    home: false,
    inspect: {
      graph: { paragraphs: [{ at_para: 0 }], tables: [] },
      summary: { fillTargetCount: 1 },
    },
    session: { sessionId: "s", source: { name: "양식.hwpx" } },
    candidates: [],
    capabilities: null,
    inspectPhase: "ready",
    inspectError: null,
    centerMode: "text",
    zoom: 1,
    leftRailCollapsed: false,
  });
  assert.match(html, /data-testid="left-rail-scroll"/);
  assert.match(html, /data-testid="work-packs-disclosure"/);
  assert.match(html, /data-testid="structure-tree"/);
  const scrollInner = innerOfTestId(html, "left-rail-scroll");
  assert.ok(scrollInner, "left-rail-scroll rendered");
  assert.match(scrollInner, /data-testid="structure-tree"/);
  assert.doesNotMatch(scrollInner, /work-packs-disclosure/);
  const railInner = innerOfTestId(html, "left-rail");
  assert.ok(railInner, "left-rail rendered");
  assert.match(railInner, /data-testid="work-packs-disclosure"/);
  assert.match(css, /\.work-disclosure\s*\{[^}]*background:\s*var\(--bg-panel\)/);
  assert.match(css, /\.work-disclosure\s*\{[^}]*border-top:\s*1px solid var\(--line\)/);
});

test("기록 header has no glued count", () => {
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
      ],
    },
    head: "run-A",
    historySelected: null,
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
    receipts: { "run-A": { backend: "preedit", checks: { acceptance: true }, steps: [] } },
  });
  assert.doesNotMatch(html, /<h3[^>]*>기록/);
  assert.doesNotMatch(html, /기록1/);
  assert.doesNotMatch(html, /data-testid="history-count"/);
});

test("popover has three groups and a close button", () => {
  const html = renderVerificationBar(
    {
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
    },
    {
      session: {
        sessionId: "s",
        openedUtc: "",
        source: { name: "양식.hwpx", documentKind: "hwpx", bytes: 1, sha256: "abc" },
      },
      inspect: {
        documentHash: "abc",
        summary: { fillTargetCount: 4 },
        regions: { regions: [] },
      },
      candidates: [],
    },
  );
  assert.match(html, /data-testid="verify-group-document"/);
  assert.match(html, /data-testid="verify-group-check"/);
  assert.match(html, /data-testid="verify-group-engine"/);
  assert.match(html, /data-testid="verify-details-close"/);
  assert.match(innerOfTestId(html, "verify-group-document") ?? "", />문서</);
  assert.match(innerOfTestId(html, "verify-group-check") ?? "", />검사</);
  assert.match(innerOfTestId(html, "verify-group-engine") ?? "", />엔진</);
  assert.match(html, /data-testid="verify-details"/);
  assert.match(html, /data-testid="status-where"/);
  assert.match(html, /data-testid="run-check"/);
  assert.match(css, /\.verify-popover-panel\s*\{[^}]*max-width:\s*520px/);
  assert.match(css, /\.toolbar\s*\{[^}]*flex-wrap:\s*nowrap/);
});

function renderHome(state) {
  const exports = loadCompiled("../src/components/Welcome.tsx", "Welcome.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../actions") {
      return { openPath: () => {}, openViaDialog: () => {}, bindFormAndOpen: () => {} };
    }
    if (id === "../store") {
      return {
        useWorkspace: (selector) => selector(state),
        setState: () => {},
        showToast: () => {},
        dismissFirstRunHint: () => {},
      };
    }
    if (id === "../types") return {};
    if (id === "./Logo") {
      return { Logo: () => React.createElement("svg", { "data-testid": "logo" }) };
    }
    if (id === "./Icon") return { Icon };
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  return renderToStaticMarkup(React.createElement(exports.Home));
}

function renderSettings(state) {
  const exports = loadCompiled("../src/components/Settings.tsx", "Settings.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../actions") {
      return {
        clearRecents: () => {},
        forgetCredential: () => {},
        pickWorkspaceFolder: () => {},
        probeProvider: () => {},
        refreshCredential: () => {},
        saveProviderSettings: () => {},
        storeCredential: () => {},
      };
    }
    if (id === "../runtime") {
      return { agentHostReadConfig: async () => ({ exists: false }) };
    }
    if (id === "../store") {
      return {
        activeStoreKey: () => "k",
        setColorTheme: () => {},
        setState: () => {},
        useWorkspace: (selector) => selector(state),
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
  return renderToStaticMarkup(React.createElement(exports.Settings));
}

function renderSeatPane() {
  const inspect = {
    graph: {
      tables: [
        {
          index: 0,
          cells: [
            {
              addr: { row: 0, col: 14 },
              classification: "fill_target",
              textPreview: "",
            },
          ],
        },
      ],
    },
    regions: {
      regions: [{ kind: "cell", table: 0, row: 0, col: 14, scriptAnomaly: false, colorAnomaly: false }],
    },
  };
  const state = {
    selection: { kind: "cell", table: 0, row: 0, col: 14 },
    selectedRegionSource: { region: { text: "" }, address: { row: 0, col: 14 } },
    inspectorTab: "selection",
    view: "document",
    draft: { ops: [] },
    approvalPhase: "idle",
  };
  const exports = loadCompiled("../src/components/ContextPanel.tsx", "ContextPanel.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../actions") {
      return { beginEdit: () => {}, bindFormToActiveDocument: () => {}, needsBoundFormHint: () => false };
    }
    if (id === "../label") {
      return {
        humanCellAddress: (t, r, c) => `표 ${t + 1} · ${r + 1}행 ${c + 1}열`,
        humanTableLabel: (t) => `표 ${t + 1}`,
        machineTableIndex: (t) => `table ${t}`,
        humanSelectionLabel: () => "표 1 · 1행 15열",
        seatStateLine: ({ text, scriptAnomaly }) =>
          scriptAnomaly ? "글자속성 이상" : text ? "값 있음" : "빈 칸",
      };
    }
    if (id === "../store") {
      return {
        useWorkspace: (selector) => selector(state),
        visibleInspectorTab: () => "selection",
        selectInspectorTab: () => {},
        markAgentTurnsSeen: () => {},
        markHistoryCandidatesSeen: () => {},
        inspectorHistoryBadge: () => 0,
        inspectorAgentUnread: () => 0,
      };
    }
    if (id === "../types") return {};
    if (id === "./History") return { History: () => null };
    if (id === "./ReviewQueue") return { ReviewQueue: () => null, ApproveAllButton: () => null };
    if (id === "./Composer") return { Composer: () => null };
    if (id === "./Conversation") return { Conversation: () => null };
    if (id === "./DocumentContext") return { DocumentContext: () => null };
    if (id === "./Tag") {
      return {
        Tag: ({ children }) => React.createElement("span", null, children),
        CLASSIFICATION_LABEL: { fill_target: "채움" },
      };
    }
    if (id === "./Icon") return { Icon };
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  return renderToStaticMarkup(React.createElement(exports.ContextPanel, { inspect }));
}

test("seat pane uses a title, one state line, 값 넣기, and 기술 정보", () => {
  const html = renderSeatPane();
  assert.match(html, /data-testid="seat-title"/);
  assert.match(html, />표 1 · 1행 15열</);
  assert.match(html, /data-testid="seat-state"/);
  assert.match(html, />빈 칸</);
  assert.match(html, />값 넣기</);
  assert.match(html, />기술 정보</);
  assert.doesNotMatch(html, /칸 표 1/);
  assert.doesNotMatch(html, /쓰기 전 확인/);
  assert.doesNotMatch(html, /분류 채움/);
});

test("recents keep the file name and truncate the folder from the left", () => {
  const html = renderHome({
    recents: [
      {
        path: "C:\\very\\long\\folder\\path\\양식.hwpx",
        name: "양식.hwpx",
        sha256: "ab",
        bytes: 1,
        openedUtc: "2026-09-17T00:00:00Z",
        documentKind: "hwpx",
      },
    ],
    dragOver: false,
    inspectError: null,
    firstRunHintDismissed: true,
  });
  assert.match(html, /양식\.hwpx/);
  assert.match(html, /dir="rtl"/);
  const nameRule = css.match(/\.recent \.name\s*\{[^}]+\}/)?.[0] ?? "";
  assert.doesNotMatch(nameRule, /overflow:\s*hidden/);
  assert.doesNotMatch(nameRule, /max-width:\s*22ch/);
  const folderRule = css.match(/\.recent \.folder\s*\{[^}]+\}/)?.[0] ?? "";
  assert.match(folderRule, /overflow:\s*hidden/);
  assert.match(folderRule, /direction:\s*rtl/);
});

test("Home fits 800 px without a page overflow class", () => {
  const homeRule = css.match(/\.welcome\s*\{[^}]+\}/)?.[0] ?? "";
  assert.match(homeRule, /overflow:\s*hidden/);
  assert.doesNotMatch(homeRule, /overflow:\s*auto/);
  assert.match(css, /\.view-document\.is-home\s*\{[^}]*overflow:\s*hidden/);
});

test("settings sections 일반 and 에이전트 render", () => {
  const html = renderSettings({
    settingsOpen: true,
    provider: { provider: "mock", scenario: "propose-one", router: {}, anthropic: {} },
    providerProfile: null,
    probePhase: "idle",
    probeError: null,
    credential: null,
    agentHost: { available: true, mode: "mock", script: "x", program: "py" },
    colorTheme: "auto",
    root: "C:\\dev-fixture\\runtime-root",
    recents: [{ path: "a.hwpx" }],
  });
  assert.match(html, />설정</);
  assert.match(html, /data-testid="settings-general"/);
  assert.match(html, />일반</);
  assert.match(html, /data-testid="settings-agent"/);
  assert.match(html, />에이전트</);
  assert.match(html, /data-testid="theme-auto"/);
  assert.match(html, /data-testid="theme-light"/);
  assert.match(html, /data-testid="theme-dark"/);
  assert.match(html, /기본 작업 폴더/);
  assert.match(html, /최근 문서 지우기/);
  const general = innerOfTestId(html, "settings-general") ?? "";
  assert.match(general, /theme-switch/);
  assert.doesNotMatch(general, /class="radios"/);
  assert.match(html, /data-testid="agent-host-status"[^>]*>\s*연결됨 · 내장\s*</);
  assert.match(html, /data-testid="agent-host-tech"/);
  assert.match(html, />기술 정보</);
  assert.doesNotMatch(html, />찾음</);
  const status = innerOfTestId(html, "agent-host-status") ?? "";
  assert.match(status, /연결됨 · 내장/);
  assert.doesNotMatch(status, /[\\/]|py\.exe|\.py\b/);
  assert.match(html, /data-tip="네트워크도 시계도 없는 결정론 제공자\."/);
  assert.match(html, /data-tip="OpenAI 호환 엔드포인트\."/);
  assert.match(html, /data-tip="공식 Messages API\."/);
  assert.match(html, /같은 문서면 같은 요청을 냅니다/);
  const closeRule = css.match(/\.settings-close\s*\{[^}]+\}/)?.[0] ?? "";
  assert.match(closeRule, /color:\s*var\(--fg\)/);
});

test("settings agent-host missing state is 찾을 수 없음", () => {
  const html = renderSettings({
    settingsOpen: true,
    provider: { provider: "mock", scenario: "propose-one", router: {}, anthropic: {} },
    providerProfile: null,
    probePhase: "idle",
    probeError: null,
    credential: null,
    agentHost: { available: false, mode: null, script: null, program: null, reason: "not bundled" },
    colorTheme: "auto",
    root: "C:\\dev-fixture\\runtime-root",
    recents: [],
  });
  assert.match(html, /data-testid="agent-host-status"[^>]*>\s*찾을 수 없음\s*</);
  const tech = innerOfTestId(html, "agent-host-tech") ?? "";
  assert.match(tech, /not bundled/);
});

test("기록 compare is a compact popover and receipt is a labelled action", () => {
  const html = renderHistory({
    activeSessionId: "s",
    sessions: [
      { sessionId: "s", source: { name: "양식.hwpx", sha256: "abcdef1234567890", bytes: 12 } },
    ],
    candidates: {
      s: [
        {
          runId: "run-demo0000",
          createdUtc: "2026-09-16T00:00:00Z",
          acceptance: true,
          opKinds: ["fill_cell"],
          sha256: "deadbeef0001",
          receipt: "run-demo0000/receipt.json",
          base: null,
        },
      ],
    },
    head: "run-demo0000",
    historySelected: null,
    undoPhase: "idle",
    undoError: null,
    inverseProof: null,
    events: [],
    compareLeftRunId: "run-demo0000",
    compareAgainst: { source: true },
    compareUseSelection: false,
    comparePhase: "idle",
    compareError: null,
    compareResult: null,
    receipts: { "run-demo0000": { backend: "preedit", checks: { acceptance: true }, steps: [] } },
  });
  assert.match(html, /compare-popover/);
  assert.match(html, /이 후보본을 원본과 비교/);
  assert.match(html, /다른 후보본과/);
  assert.match(html, /선택한 자리만/);
  assert.doesNotMatch(html, /왼쪽 후보본/);
  assert.match(html, />영수증 보기</);
});
