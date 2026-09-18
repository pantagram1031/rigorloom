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
const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const toolbarSource = readFileSync(
  new URL("../src/components/EditorToolbar.tsx", import.meta.url),
  "utf8",
);
const docSource = readFileSync(new URL("../src/views/DocumentView.tsx", import.meta.url), "utf8");
const contextSource = readFileSync(
  new URL("../src/components/ContextPanel.tsx", import.meta.url),
  "utf8",
);

const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const { getState, setChromeMenu, setState } = await import("../src/store.ts");

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

function renderToolbar(state) {
  const module = { exports: {} };
  vm.runInNewContext(compile("../src/components/EditorToolbar.tsx", "EditorToolbar.tsx"), {
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return nodeRequire(id);
      if (id === "react") return nodeRequire(id);
      if (id === "../actions") {
        return {
          applyUiZoom: () => {},
          bindFormAndOpen: () => {},
          exportApplied: () => {},
          openViaDialog: () => {},
          requestApprovalForDraft: () => {},
          runCheck: () => {},
          stepUiZoom: () => {},
          toggleLeftRail: () => {},
        };
      }
      if (id === "../store") {
        return {
          activeText: (s) => s.texts ?? [],
          canRenderPages: () => true,
          canRequestApproval: (s) => (s.draft?.ops?.length ?? 0) > 0,
          cellKey: (t, r, c) => `${t}:${r}:${c}`,
          getState: () => state,
          selectInspectorTab: () => {},
          setCenterMode: () => {},
          setChromeMenu: () => {},
          setZoom: () => {},
          useWorkspace: (selector) => selector(state),
        };
      }
      if (id === "../types") return {};
      if (id === "./Icon") return { Icon };
      if (id === "./Tag") {
        return {
          Tag: ({ children, title }) => React.createElement("span", { title }, children),
        };
      }
      throw new Error(`unexpected import: ${id}`);
    },
  });
  return renderToStaticMarkup(
    React.createElement(module.exports.EditorToolbar, {
      inspect: {
        summary: { baselineCharPr: { id: "11", height_pt: 10, face: { hangul: "돋움체" } } },
        graph: { tables: [], paragraphs: [] },
        regions: { regions: [] },
      },
    }),
  );
}

const toolbarState = {
  centerMode: "text",
  zoom: 1,
  uiZoom: 1,
  selection: null,
  texts: [],
  inlineEdit: null,
  draft: { ops: [{ opId: "op-1" }] },
  approvalPhase: "idle",
  applied: null,
  checkPhase: "idle",
  findings: [],
  exportPhase: "idle",
  leftRailCollapsed: false,
  chromeMenu: null,
};

test("overflow menu keeps 저장/내보내기, 되돌리기, 양식 연결, 서식 behind one control", () => {
  const html = renderToolbar(toolbarState);
  assert.match(html, /data-testid="tool-overflow"/);
  const overflowAt = html.indexOf('data-testid="tool-overflow"');
  const overflow = html.slice(overflowAt);
  assert.match(overflow, /data-testid="act-export"/);
  assert.match(overflow, /저장\/내보내기/);
  assert.match(overflow, /data-testid="act-undo"/);
  assert.match(overflow, /되돌리기/);
  assert.match(overflow, /data-testid="act-bind-form"/);
  assert.match(overflow, /양식 연결/);
  assert.match(overflow, /data-testid="tool-format"/);
  assert.match(overflow, /data-testid="tool-typeface"/);
  assert.match(overflow, /data-testid="tool-charpr"/);
  assert.match(overflow, /data-testid="tool-size"/);
  assert.match(html, /data-testid="act-open"/);
  assert.match(html, />열기</);
  assert.match(html, /data-testid="toolbar-check"/);
  assert.match(html, />검사</);
  assert.match(html, /data-testid="act-approve"/);
  assert.match(html, /class="[^"]*primary[^"]*"/);
  assert.match(html, /data-testid="tool-state"/);
  assert.match(html, /data-testid="mode-text"/);
  assert.match(html, />본문</);
  assert.match(html, />페이지</);
  assert.doesNotMatch(html, />본문 보기</);
  assert.match(html, /data-testid="tool-zoom"/);
  assert.match(html, /data-testid="tool-uizoom"/);
  assert.match(html, /data-testid="zoom-value"/);
  assert.match(html, /data-testid="uizoom-value"/);
  assert.match(html, />문서</);
  assert.match(html, />화면</);
  assert.match(toolbarSource, /aria-haspopup="menu"/);
  assert.match(toolbarSource, /role="menu"/);
  assert.match(toolbarSource, /role="menuitem"/);
});

test("toolbar is a single nowrap row at 1024 and 1280", () => {
  assert.match(css, /\.toolbar\s*\{[^}]*flex-wrap:\s*nowrap/);
  assert.doesNotMatch(css, /\.toolbar\s*\{[^}]*flex-wrap:\s*wrap/);
  const rule1024 = /@media \(min-width:\s*1024px\)\s*\{[^}]*\.toolbar\s*\{[^}]*flex-wrap:\s*nowrap/;
  const rule1280 = /@media \(min-width:\s*1280px\)\s*\{[^}]*\.toolbar\s*\{[^}]*flex-wrap:\s*nowrap/;
  assert.match(css, rule1024);
  assert.match(css, rule1280);
  assert.match(css, /\.toolbar\s*\{[^}]*display:\s*grid/);
  assert.match(css, /\.pipeline-strip\s*\{[^}]*height:\s*28px/);
});

test("home header is 문서 열기 menu + 설정; 양식과 함께 열기 is a menu item", () => {
  assert.match(appSource, /data-testid="header-open-menu"/);
  assert.match(appSource, /양식과 함께 열기/);
  assert.match(appSource, /data-testid="bind-form"/);
  assert.match(appSource, /data-testid="open-settings"/);
  const header = appSource.slice(appSource.indexOf("<header"), appSource.indexOf("</header>"));
  assert.match(header, /문서 열기/);
  assert.match(header, /설정/);
  assert.doesNotMatch(header, />양식 연결</);
  assert.match(appSource, /case "s":/);
  assert.match(appSource, /exportApplied\(\)/);
});

test("the toolbar hint becomes the 선택 empty state; Esc closes chrome menus", () => {
  assert.doesNotMatch(docSource, /center-caveat/);
  assert.doesNotMatch(docSource, /CenterCaveat/);
  assert.match(contextSource, /data-testid="center-caveat"/);
  assert.match(contextSource, /입력 칸을 누르면 값을 넣을 수 있습니다/);
  assert.match(actionsSource, /if \(state\.chromeMenu\)/);
  assert.match(actionsSource, /chromeMenu: null/);
  const before = getState().chromeMenu;
  try {
    setChromeMenu("overflow");
    assert.equal(getState().chromeMenu, "overflow");
    setChromeMenu(null);
    assert.equal(getState().chromeMenu, null);
  } finally {
    setState({ chromeMenu: before });
  }
});
