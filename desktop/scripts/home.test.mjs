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
  getState,
  goHome,
  isHome,
  leaveHome,
  setState,
  toggleHome,
} = await import("../src/store.ts");

const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const docSource = readFileSync(new URL("../src/views/DocumentView.tsx", import.meta.url), "utf8");
const splashSource = readFileSync(new URL("../src/components/Splash.tsx", import.meta.url), "utf8");
const mockSource = readFileSync(new URL("../src/devMock.ts", import.meta.url), "utf8");
const welcomeSource = readFileSync(new URL("../src/components/Welcome.tsx", import.meta.url), "utf8");
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

function renderHome(state) {
  const module = { exports: {} };
  vm.runInNewContext(compile("../src/components/Welcome.tsx", "Welcome.tsx"), {
    module,
    exports: module.exports,
    require: (id) => {
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
        };
      }
      if (id === "../types") return {};
      if (id === "./Logo") {
        return {
          Logo: () => React.createElement("svg", { "data-testid": "logo" }),
        };
      }
      if (id === "./Icon") return { Icon };
      throw new Error(`unexpected import: ${id}`);
    },
  });
  return renderToStaticMarkup(React.createElement(module.exports.Home));
}

const present = {
  path: "C:\\forms\\양식.hwpx",
  name: "양식.hwpx",
  sha256: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
  bytes: 12,
  openedUtc: "2026-09-17T00:04:00Z",
  documentKind: "hwpx",
};
const missing = {
  path: "C:\\gone\\lost.hwp",
  name: "lost.hwp",
  sha256: "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  bytes: 0,
  openedUtc: "2026-09-16T12:00:00Z",
  documentKind: "hwp",
  missing: true,
};

test("Home renders recents from prefs-shaped workspace state, without hashes", () => {
  const html = renderHome({
    recents: [present, missing],
    dragOver: false,
    inspectError: null,
  });
  assert.match(html, /data-testid="welcome"/);
  assert.match(html, /data-testid="recents"/);
  assert.match(html, /양식\.hwpx/);
  assert.match(html, /lost\.hwp/);
  assert.match(html, /C:\\forms/);
  assert.match(html, /HWPX/);
  assert.match(html, /HWP/);
  assert.match(html, /파일을 끌어다 놓으세요/);
  assert.match(html, /CLI 문서/);
  assert.match(html, />설정</);
  assert.doesNotMatch(html, /abcdef01/);
  assert.doesNotMatch(html, /ffffffff/);
  assert.match(html, /문서를 열고, 에이전트가 제안한 편집을 사람이 승인하면/);
});

test("a missing recent is not clickable and shows 찾을 수 없음", () => {
  const html = renderHome({
    recents: [present, missing],
    dragOver: false,
    inspectError: null,
  });
  assert.match(html, /data-testid="recent-missing"/);
  assert.match(html, /찾을 수 없음/);
  const missingBlock = html.slice(html.indexOf("lost.hwp") - 80);
  assert.match(missingBlock, /aria-disabled="true"/);
  assert.doesNotMatch(missingBlock.slice(0, 160), /<button/);
});

test("first-run line shows when there are no recents", () => {
  const html = renderHome({ recents: [], dragOver: false, inspectError: null });
  assert.match(html, /data-testid="home-onboarding"/);
  assert.match(html, /처음이신가요\? 양식 HWPX 파일 하나를 열면 시작됩니다/);
  assert.doesNotMatch(html, /data-testid="recents"/);
});

test("header 홈 toggles Home without dropping the session", () => {
  const before = getState();
  try {
    setState({
      activeSessionId: "sess-home",
      sessions: [
        {
          sessionId: "sess-home",
          openedUtc: "2026-09-17T00:00:00Z",
          source: { name: "양식.hwpx", documentKind: "hwpx", bytes: 1, sha256: "aa" },
        },
      ],
      homeOpen: false,
    });
    assert.equal(isHome(getState()), false);
    goHome();
    assert.equal(getState().homeOpen, true);
    assert.equal(getState().activeSessionId, "sess-home");
    assert.equal(isHome(getState()), true);
    leaveHome();
    assert.equal(getState().homeOpen, false);
    assert.equal(getState().activeSessionId, "sess-home");
    toggleHome();
    assert.equal(getState().homeOpen, true);
    assert.equal(getState().activeSessionId, "sess-home");
    assert.match(appSource, /data-testid="header-home"/);
    assert.match(appSource, /toggleHome\(\)/);
    assert.match(appSource, /case "H":/);
    assert.match(appSource, /data-testid="doc-tab"/);
  } finally {
    setState({
      activeSessionId: before.activeSessionId,
      sessions: before.sessions,
      homeOpen: before.homeOpen,
    });
  }
});

test("DocumentView mounts Home in place of the three columns", () => {
  assert.match(docSource, /const home = useWorkspace\(isHome\)/);
  assert.match(docSource, /<Home \/>/);
  assert.match(docSource, /is-home/);
  assert.match(docSource, /VerificationBar home/);
  const start = docSource.indexOf("if (home)");
  const workspaceReturn = docSource.indexOf("return (", docSource.indexOf("return (", start) + 1);
  const homeBranch = docSource.slice(start, workspaceReturn);
  assert.doesNotMatch(homeBranch, /StructureTree/);
  assert.doesNotMatch(homeBranch, /ContextPanel/);
  assert.doesNotMatch(homeBranch, /className=\{`columns/);
});

test("VerificationBar on Home shows only the engine connection", () => {
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
    selection: null,
    overlayPick: null,
    geometry: null,
    inlineEdit: null,
    verifyDetailsOpen: false,
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
        return { useWorkspace: (selector) => selector(state), setState: () => {} };
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
  });
  const html = renderToStaticMarkup(
    React.createElement(module.exports.VerificationBar, {
      home: true,
      session: {
        sessionId: "s",
        openedUtc: "",
        source: { name: "양식.hwpx", documentKind: "hwpx", bytes: 1, sha256: "abc" },
      },
      inspect: null,
      candidates: [],
    }),
  );
  assert.match(html, /data-testid="verify-engine"/);
  assert.match(html, /엔진 연결됨/);
  assert.match(html, /is-home/);
  assert.doesNotMatch(html, /verify-details-toggle/);
  assert.doesNotMatch(html, /verify-pill/);
  assert.doesNotMatch(html, /원본/);
});

test("Home CLI 문서 points at docs/QUICKSTART.md with a copy control", () => {
  const html = renderHome({ recents: [], dragOver: false, inspectError: null });
  assert.match(html, /data-testid="home-cli-docs"/);
  assert.match(html, /docs\/QUICKSTART\.md/);
  assert.match(html, /data-testid="home-cli-docs-copy"/);
  assert.match(
    html,
    /https:\/\/github.com\/pantagram1031\/rigorloom\/blob\/main\/docs\/QUICKSTART\.md/,
  );
  assert.doesNotMatch(html, /runtime-protocol-v0/);
  assert.match(welcomeSource, /export const CLI_DOCS_PATH = "docs\/QUICKSTART\.md"/);
  assert.match(appSource, /CLI_DOCS_PATH/);
  assert.match(appSource, /CLI_DOCS_URL/);
});

test("splash is ≤ 400 ms unless smoke holds it, and recents fallback exists", () => {
  const total = Number(/const TOTAL_MS = (\d+)/.exec(splashSource)?.[1]);
  const fade = Number(/const FADE_MS = (\d+)/.exec(splashSource)?.[1]);
  assert.ok(Number.isFinite(total) && Number.isFinite(fade));
  assert.ok(total + fade <= 400, `entrance ${total}+${fade}ms`);
  assert.match(splashSource, /frozen/);
  assert.match(actionsSource, /export function recentsFromSessions/);
  assert.match(welcomeSource, /return "어제"/);
  assert.match(welcomeSource, /return "방금"/);
  assert.match(welcomeSource, /toUpperCase/);
  assert.match(mockSource, /missing: true/);
  assert.match(mockSource, /gianmun-byeolji-1ho\.hwpx/);
});
