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
const treeSource = readFileSync(new URL("../src/components/StructureTree.tsx", import.meta.url), "utf8");
const textSource = readFileSync(new URL("../src/components/TextView.tsx", import.meta.url), "utf8");
const reviewSource = readFileSync(new URL("../src/components/ReviewQueue.tsx", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const docSource = readFileSync(new URL("../src/views/DocumentView.tsx", import.meta.url), "utf8");
const captureSource = readFileSync(
  new URL("../../docs/demo/desktop/capture.mjs", import.meta.url),
  "utf8",
);

const {
  humanTableLabel,
  humanSelectionLabel,
  scrubToastText,
} = await import("../src/label.ts");
const { filterCommands, workspaceCommands } = await import("../src/commands.ts");
const {
  dismissFirstRunHint,
  dismissToast,
  getState,
  selectInspectorTab,
  setState,
  showErrorToast,
  showToast,
} = await import("../src/store.ts");
const { focusFirstHunk, focusHunkAt } = await import("../src/focus.ts");

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

const inspect = {
  documentHash: "abc",
  sessionId: "s",
  summary: { documentHash: "abc", sessionId: "s", fillTargetCount: 1 },
  graph: {
    documentHash: "abc",
    sessionId: "s",
    paragraphs: [],
    tables: [
      {
        index: 0,
        cells: [
          { addr: { row: 0, col: 0 }, classification: "fill_target", textPreview: "값" },
        ],
      },
      {
        index: 1,
        cells: [{ addr: { row: 0, col: 0 }, classification: "guide", textPreview: "안내" }],
      },
    ],
  },
  regions: {
    documentHash: "abc",
    sessionId: "s",
    regions: [{ kind: "cell", table: 0, row: 0, col: 0 }],
  },
};

const label = {
  humanCellAddress: (t, r, c) => `표 ${t + 1} · ${r + 1}행 ${c + 1}열`,
  humanTableLabel: (t) => `표 ${t + 1}`,
  machineTableIndex: (t) => `table ${t}`,
  trimLabel: (text, max = 34) => String(text).slice(0, max),
};

function renderTree() {
  const state = { selection: null, expanded: ["t:0", "t:1"] };
  return loadCompiled("../src/components/StructureTree.tsx", "StructureTree.tsx", (id) => {
    if (id === "react/jsx-runtime" || id === "react") return nodeRequire(id);
    if (id === "../store") {
      return {
        useWorkspace: (selector) => selector(state),
        toggleExpanded: () => {},
        selectionId: () => "none",
      };
    }
    if (id === "../label") return label;
    if (id === "../actions") return { selectStructureNode: () => {} };
    if (id === "../types") return {};
    if (id === "./Icon") return { Icon };
    throw new Error(`unexpected import: ${id}`);
  });
}

function renderPaper() {
  const state = {
    texts: [],
    selectedRegionSource: null,
    selection: null,
    locateNonce: 0,
    inlineEdit: null,
    draft: { ops: [] },
  };
  return loadCompiled("../src/components/TextView.tsx", "TextView.tsx", (id) => {
    if (id === "react/jsx-runtime" || id === "react") return nodeRequire(id);
    if (id === "../actions") return { beginEdit: () => {}, cancelEdit: () => {}, commitEdit: () => {} };
    if (id === "../label") return label;
    if (id === "../store") {
      return {
        useWorkspace: (selector) => selector(state),
        activeText: () => [],
        cellKey: (t, r, c) => `${t}:${r}:${c}`,
        selectionId: () => "none",
        setSelection: () => {},
      };
    }
    if (id === "./SeatEditor") return { SeatEditor: () => null };
    if (id === "../types") return {};
    throw new Error(`unexpected import: ${id}`);
  });
}

test("table numbering is 1-based in the tree and the document caption", () => {
  assert.equal(humanTableLabel(0), "표 1");
  assert.equal(humanTableLabel(1), "표 2");
  assert.match(treeSource, /humanTableLabel\(table\.index\)/);
  assert.match(textSource, /humanTableLabel\(table\.index\)/);
  const treeHtml = renderToStaticMarkup(
    React.createElement(renderTree().StructureTree, { inspect, capabilities: null }),
  );
  const paperHtml = renderToStaticMarkup(
    React.createElement(renderPaper().TextView, { inspect }),
  );
  assert.match(treeHtml, />표 1</);
  assert.match(treeHtml, />표 2</);
  assert.match(paperHtml, /data-testid="table-caption-0"[^>]*>표 1</);
  assert.match(paperHtml, /data-testid="table-caption-1"[^>]*>표 2</);
  assert.doesNotMatch(paperHtml, /<caption[^>]*>표 0</);
  const treeOne = treeHtml.match(/>표 1</g) || [];
  const capOne = paperHtml.match(/>표 1</g) || [];
  assert.ok(treeOne.length >= 1 && capOne.length >= 1);
});

test("palette lists toolbar actions and switches the 검토 tab", () => {
  const commands = workspaceCommands({ recents: [{ path: "C:\\a.hwpx", name: "양식.hwpx" }] });
  const labels = commands.map((row) => row.label);
  for (const need of ["열기", "검사", "승인", "저장/내보내기", "홈", "설정", "검토", "양식.hwpx"]) {
    assert.ok(labels.includes(need), need);
  }
  const filtered = filterCommands(commands, "검");
  assert.ok(filtered.some((row) => row.id === "check" || row.id === "tab-review"));
  const tabs = [];
  const exports = loadCompiled(
    "../src/components/CommandPalette.tsx",
    "CommandPalette.tsx",
    (id) => {
      if (id === "react/jsx-runtime" || id === "react") return nodeRequire(id);
      if (id === "../actions") {
        return {
          approveAndApply: () => {},
          bindFormAndOpen: () => {},
          exportApplied: () => {},
          openPath: () => {},
          openViaDialog: () => {},
          requestApprovalForDraft: () => {},
          runCheck: () => {},
          toggleLeftRail: () => {},
        };
      }
      if (id === "../commands") return { filterCommands, workspaceCommands };
      if (id === "../store") {
        return {
          getState: () => ({ paletteOpen: true, recents: [] }),
          goHome: () => {},
          selectInspectorTab: (tab) => tabs.push(tab),
          setCenterMode: () => {},
          setChromeMenu: () => {},
          setPaletteOpen: () => {},
          setState: () => {},
          useWorkspace: (selector) =>
            selector({ paletteOpen: true, recents: [{ path: "C:\\a.hwpx", name: "양식.hwpx" }] }),
        };
      }
      throw new Error(`unexpected import: ${id}`);
    },
  );
  const html = renderToStaticMarkup(React.createElement(exports.CommandPalette));
  assert.match(html, /data-testid="command-palette"/);
  assert.match(html, /data-testid="palette-item-tab-review"/);
  assert.match(html, /data-testid="palette-item-open"/);
  assert.match(html, /Ctrl\+O/);
  exports.runCommand("tab-review");
  assert.deepEqual(tabs, ["review"]);
  assert.match(appSource, /toggleCommandPalette/);
  assert.match(captureSource, /"palette"/);
  assert.match(captureSource, /"settings"/);
});

test("toast strips hashes and auto-dismisses; errors stay", async () => {
  assert.equal(scrubToastText("계획을 aaaa15deadbeef 에 묶었습니다"), "계획을 에 묶었습니다");
  const before = getState().toasts;
  try {
    setState({ toasts: [] });
    showToast("적용됨 a1b2c3d4e5f60789", 20);
    const shown = getState().toasts[0];
    assert.ok(shown, "toast shown");
    assert.doesNotMatch(shown.text, /[0-9a-fA-F]{8,}/);
    assert.equal(shown.sticky, false);
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.equal(getState().toasts.some((row) => row.id === shown.id), false);
    showErrorToast("실패 deadbeefcafebabe");
    const error = getState().toasts.find((row) => row.sticky);
    assert.ok(error);
    assert.doesNotMatch(error.text, /[0-9a-fA-F]{8,}/);
    await new Promise((resolve) => setTimeout(resolve, 40));
    assert.ok(getState().toasts.some((row) => row.id === error.id));
    dismissToast(error.id);
    assert.equal(getState().toasts.some((row) => row.id === error.id), false);
  } finally {
    for (const row of getState().toasts) dismissToast(row.id);
    setState({ toasts: before });
  }
});

test("switching to 검토 focuses the first hunk; Esc returns to the document", () => {
  assert.match(reviewSource, /focusFirstHunk\(\)/);
  assert.match(reviewSource, /focusHunkAt\(next\)/);
  assert.match(appSource, /focusDocumentSurface\(\)/);
  assert.match(docSource, /focusDocumentSurface\(\)/);
  const cards = [{ focused: false, focus() { this.focused = true; } }];
  const previous = globalThis.document;
  globalThis.document = {
    querySelectorAll: () => cards,
    querySelector: () => null,
    activeElement: null,
  };
  try {
    assert.equal(focusHunkAt(0), true);
    assert.equal(cards[0].focused, true);
    cards[0].focused = false;
    assert.equal(focusFirstHunk(), true);
    assert.equal(cards[0].focused, true);
    selectInspectorTab("review");
    assert.equal(getState().inspectorTab, "review");
  } finally {
    globalThis.document = previous;
    setState({ inspectorTab: "selection", inspectorTabUserSet: false, view: "document" });
  }
});

test("first-run hint shows once and dismisses through prefs", () => {
  const welcome = loadCompiled("../src/components/Welcome.tsx", "Welcome.tsx", (id) => {
    if (id === "react/jsx-runtime" || id === "react") return nodeRequire(id);
    if (id === "../actions") return { openPath: () => {}, openViaDialog: () => {}, bindFormAndOpen: () => {} };
    if (id === "../store") {
      return {
        useWorkspace: (selector) =>
          selector({ recents: [], dragOver: false, inspectError: null, firstRunHintDismissed: false }),
        setState: () => {},
        showToast: () => {},
        dismissFirstRunHint: () => {},
      };
    }
    if (id === "../types") return {};
    if (id === "./Logo") return { Logo: () => React.createElement("svg") };
    if (id === "./Icon") return { Icon };
    throw new Error(`unexpected import: ${id}`);
  });
  const shown = renderToStaticMarkup(React.createElement(welcome.Home));
  assert.match(shown, /data-testid="first-run-hint"/);
  assert.match(shown, />열기</);
  assert.match(shown, />검토</);
  assert.match(shown, />승인</);
  const hidden = loadCompiled("../src/components/Welcome.tsx", "Welcome.tsx", (id) => {
    if (id === "react/jsx-runtime" || id === "react") return nodeRequire(id);
    if (id === "../actions") return { openPath: () => {}, openViaDialog: () => {}, bindFormAndOpen: () => {} };
    if (id === "../store") {
      return {
        useWorkspace: (selector) =>
          selector({ recents: [], dragOver: false, inspectError: null, firstRunHintDismissed: true }),
        setState: () => {},
        showToast: () => {},
        dismissFirstRunHint: () => {},
      };
    }
    if (id === "../types") return {};
    if (id === "./Logo") return { Logo: () => React.createElement("svg") };
    if (id === "./Icon") return { Icon };
    throw new Error(`unexpected import: ${id}`);
  });
  const gone = renderToStaticMarkup(React.createElement(hidden.Home));
  assert.doesNotMatch(gone, /data-testid="first-run-hint"/);
  const before = getState().firstRunHintDismissed;
  try {
    setState({ firstRunHintDismissed: false });
    dismissFirstRunHint();
    assert.equal(getState().firstRunHintDismissed, true);
    dismissFirstRunHint();
    assert.equal(getState().firstRunHintDismissed, true);
  } finally {
    setState({ firstRunHintDismissed: before });
  }
});

test("selection header never prints English none", () => {
  assert.equal(humanSelectionLabel(null), "선택 없음");
  assert.equal(
    humanSelectionLabel({ kind: "cell", table: 0, row: 4, col: 1 }),
    "표 1 · 5행 2열",
  );
});
