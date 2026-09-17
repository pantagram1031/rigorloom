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
  assert.match(html, /data-testid="history-heading"/);
  const heading = innerOfTestId(html, "history-heading");
  assert.equal(heading, "기록");
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
  assert.match(css, /\.toolbar\s*\{[^}]*flex-wrap:\s*wrap/);
});
