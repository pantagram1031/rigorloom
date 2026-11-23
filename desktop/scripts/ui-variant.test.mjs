// Editor v2 is the default; v1 is reachable via ?ui=v1, the palette command,
// editorVariant: "v1", or legacy devEditorV2: false.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import ts from "typescript";

const require = createRequire(import.meta.url);
const DESKTOP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function loadTsModule(relPath, stubs = {}) {
  const fullPath = path.join(DESKTOP_ROOT, relPath);
  const source = readFileSync(fullPath, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
    fileName: fullPath,
  });
  const module = { exports: {} };
  const req = (id) => {
    if (id in stubs) return stubs[id];
    const stripped = id.replace(/\.tsx?$/, "");
    if (stripped in stubs) return stubs[stripped];
    return require(id);
  };
  vm.runInThisContext(`(function(exports, require, module) {\n${outputText}\n})`)(
    module.exports,
    req,
    module,
  );
  return module.exports;
}

function createHookRunner() {
  return {
    ...React,
    useState(initial) {
      const val = typeof initial === "function" ? initial() : initial;
      return [val, () => {}];
    },
    useMemo(fn) {
      return fn();
    },
    useEffect() {},
  };
}

function findElements(node, predicate, out = []) {
  if (!node || typeof node !== "object") return out;
  if (Array.isArray(node)) {
    for (const child of node) findElements(child, predicate, out);
    return out;
  }
  if (predicate(node)) out.push(node);
  if (node.props && node.props.children !== undefined) {
    findElements(node.props.children, predicate, out);
  }
  return out;
}

function textContent(node) {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textContent).join("");
  if (typeof node === "object" && node.props) return textContent(node.props.children);
  return "";
}

const v = await import("../src/uiVariant.ts");

test("the address names a variant only with ui=v1 or ui=v2", () => {
  assert.equal(v.uiVariantFromQuery(""), null);
  assert.equal(v.uiVariantFromQuery("?ui=v2"), "v2");
  assert.equal(v.uiVariantFromQuery("?token=x&ui=v1"), "v1");
  assert.equal(v.uiVariantFromQuery("?ui=v3"), null);
});

test("precedence: ?ui=v1|v2 > editorVariant > legacy devEditorV2 > default v2", () => {
  // Rung 4: default is v2 when prefs are null, undefined or empty
  assert.equal(v.resolveUiVariant(null, null), "v2");
  assert.equal(v.resolveUiVariant(null, undefined), "v2");
  assert.equal(v.resolveUiVariant(null, {}), "v2");

  // Rung 3: legacy devEditorV2 (false -> v1, true -> v2; other types fall through to v2)
  assert.equal(v.resolveUiVariant(null, { devEditorV2: false }), "v1");
  assert.equal(v.resolveUiVariant(null, { devEditorV2: true }), "v2");
  assert.equal(v.resolveUiVariant(null, { devEditorV2: "false" }), "v2");
  assert.equal(v.resolveUiVariant(null, { devEditorV2: "true" }), "v2");
  assert.equal(v.resolveUiVariant(null, { devEditorV2: 0 }), "v2");

  // Rung 2: editorVariant ("v1" or "v2") wins over devEditorV2
  assert.equal(v.resolveUiVariant(null, { editorVariant: "v1" }), "v1");
  assert.equal(v.resolveUiVariant(null, { editorVariant: "v2" }), "v2");
  assert.equal(v.resolveUiVariant(null, { editorVariant: "v1", devEditorV2: true }), "v1");
  assert.equal(v.resolveUiVariant(null, { editorVariant: "v2", devEditorV2: false }), "v2");

  // A bad editorVariant value or type is ignored and falls through to devEditorV2 / default v2
  assert.equal(v.resolveUiVariant(null, { editorVariant: "v3", devEditorV2: false }), "v1");
  assert.equal(v.resolveUiVariant(null, { editorVariant: "v3", devEditorV2: true }), "v2");
  assert.equal(v.resolveUiVariant(null, { editorVariant: "v3" }), "v2");
  assert.equal(v.resolveUiVariant(null, { editorVariant: true, devEditorV2: false }), "v1");
  assert.equal(v.resolveUiVariant(null, { editorVariant: null, devEditorV2: false }), "v1");

  // Rung 1: query wins over everything
  assert.equal(v.resolveUiVariant("v1", { editorVariant: "v2", devEditorV2: true }), "v1");
  assert.equal(v.resolveUiVariant("v2", { editorVariant: "v1", devEditorV2: false }), "v2");
  assert.equal(v.resolveUiVariant("v1", null), "v1");
  assert.equal(v.resolveUiVariant("v2", null), "v2");
});

test("editor v2 palette command '이전 화면으로 열기 (v1)' saves editorVariant v1 or refuses when work is pending", async () => {
  const previousWindow = globalThis.window;
  const savedPrefs = [];
  let reloadCount = 0;
  const replacedUrls = [];

  globalThis.window = {
    location: {
      pathname: "/",
      search: "?token=t1&ui=v2",
      hash: "",
      reload() {
        reloadCount += 1;
      },
    },
    history: {
      replaceState(_state, _title, url) {
        replacedUrls.push(url);
        const qIdx = String(url).indexOf("?");
        globalThis.window.location.search = qIdx >= 0 ? String(url).slice(qIdx) : "";
      },
    },
    addEventListener() {},
    removeEventListener() {},
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
  };

  try {
    const store = loadTsModule("src/store.ts", { react: React });
    const vocabulary = loadTsModule("src/i18n/vocabulary.ts");
    const v2Index = loadTsModule("src/i18n/v2/index.ts", { "../vocabulary.ts": vocabulary });
    const shellStrings = loadTsModule("src/i18n/v2/shell.ts", { "./index.ts": v2Index });
    const changeModel = loadTsModule("src/model/changes.ts");
    const controller = loadTsModule("src/canvas/controller.ts", {
      "../store": store,
      "../model/changes": changeModel,
    });
    const keys = loadTsModule("src/shell/keys.ts", { react: React });
    const keymap = loadTsModule("src/shell/keymap.ts", { "./keys.ts": keys });
    const shell = loadTsModule("src/shell/shellState.ts", { react: React, "../store.ts": store });
    const commands = loadTsModule("src/shell/commands.ts", { react: React });
    const rtStub = {
      isTauri: () => false,
      savePrefs: async (patch) => {
        savedPrefs.push(patch);
        return patch;
      },
    };
    const bindings = loadTsModule("src/shell/bindings.ts", {
      "../actions": {
        closeTopmostOverlay: () => false,
        toggleFullscreen: async () => {},
        toggleTheme: async () => {},
        setLanguage: async () => {},
      },
      "../i18n/v2/shell": shellStrings,
      "../runtime": rtStub,
      "../store": store,
      "../uiVariant": v,
      "./commands": commands,
      "./keymap": keymap,
      "./keys": keys,
      "./open": { pickAndOpenFile: async () => {}, pickFolder: async () => {} },
      "./shellState": shell,
      "./tabs": {
        activateTabIndex: () => {},
        closeTab: () => {},
        openStartTab: () => {},
        stepTab: () => {},
      },
    });

    const off = bindings.installShellBindings();
    try {
      const cmd = commands
        .allCommands()
        .find((c) => commands.commandTitle(c, "ko") === "이전 화면으로 열기 (v1)");
      assert.ok(cmd, "Expected v2 palette command '이전 화면으로 열기 (v1)' to be registered");
      assert.equal(commands.commandTitle(cmd, "en"), "Open the previous screens (v1)");

      // 1. Refuses and writes nothing when an inline edit is open
      store.setState({
        activeSessionId: "sess-1",
        language: "ko",
        inlineEdit: {
          kind: "cell",
          table: 0,
          row: 5,
          col: 1,
          before: "",
          opId: null,
        },
        draft: { ...store.EMPTY_DRAFT },
        savedDrafts: {},
      });
      controller.setCanvasSlice({ statusNotice: null }, "sess-1");
      await cmd.run();
      assert.deepEqual(savedPrefs, []);
      assert.equal(reloadCount, 0);
      const inlineNotice = controller.getCanvasSlice("sess-1").statusNotice ?? shell.getShell().statusNotice;
      assert.ok(
        typeof inlineNotice === "string" && inlineNotice.length > 0,
        `Expected Korean status-bar note on refusal, got ${JSON.stringify(inlineNotice)}`,
      );

      // 2. Refuses and writes nothing when a queued change is not yet saved to prefs
      store.setState({
        inlineEdit: null,
        draft: {
          ...store.EMPTY_DRAFT,
          sessionId: "sess-1",
          phase: "starting",
          ops: [
            {
              opId: "op-1",
              kind: "fill_cell",
              table: 0,
              row: 5,
              col: 1,
              text: "한글",
              before: "",
              origin: "user",
              sessionId: "sess-1",
            },
          ],
        },
        savedDrafts: {},
      });
      controller.setCanvasSlice({ statusNotice: null }, "sess-1");
      await cmd.run();
      assert.deepEqual(savedPrefs, []);
      assert.equal(reloadCount, 0);
      const unsavedNotice = controller.getCanvasSlice("sess-1").statusNotice ?? shell.getShell().statusNotice;
      assert.ok(
        typeof unsavedNotice === "string" && unsavedNotice.length > 0,
        `Expected Korean status-bar note when queued change is unsaved, got ${JSON.stringify(unsavedNotice)}`,
      );

      // 3. Writes editorVariant: "v1", drops ui= from query, and reloads when nothing is pending
      store.setState({
        inlineEdit: null,
        draft: { ...store.EMPTY_DRAFT },
        savedDrafts: {},
      });
      await cmd.run();
      assert.deepEqual(savedPrefs, [{ editorVariant: "v1" }]);
      assert.equal(globalThis.window.location.search, "?token=t1");
      assert.equal(reloadCount, 1);
    } finally {
      off();
    }
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});

test("v1 palette command '새 편집기로 열기' saves editorVariant v2 or refuses when work is pending", async () => {
  const previousWindow = globalThis.window;
  const savedPrefs = [];
  let reloadCount = 0;

  globalThis.window = {
    location: {
      pathname: "/",
      search: "?ui=v1",
      hash: "",
      reload() {
        reloadCount += 1;
      },
    },
    history: {
      replaceState(_state, _title, url) {
        const qIdx = String(url).indexOf("?");
        globalThis.window.location.search = qIdx >= 0 ? String(url).slice(qIdx) : "";
      },
    },
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
  };

  try {
    const hookReact = createHookRunner();
    const store = loadTsModule("src/store.ts", { react: React });
    const storeWithHook = {
      ...store,
      useWorkspace: (sel) => sel(store.getState()),
    };
    const vocabulary = loadTsModule("src/i18n/vocabulary.ts");
    const rtStub = {
      isTauri: () => false,
      savePrefs: async (patch) => {
        savedPrefs.push(patch);
        return patch;
      },
    };
    const trust = loadTsModule("src/workspace/trust.ts", {
      "../i18n/vocabulary": vocabulary,
      "../store": store,
    });
    const actionsStub = {
      closeCommandPalette: () => store.setState({ commandPaletteOpen: false }),
      exportApplied: async () => true,
      loadCorpusFiles: async () => [],
      navigateScreen: () => {},
      openApprovalDialog: () => {},
      openOperatorModal: () => {},
      openViaDialog: async () => null,
      revisionNumberFor: () => null,
      setReturnPopoverOpen: () => {},
      toggleLanguage: async () => {},
      togglePrintView: () => {},
      toggleTheme: async () => {},
    };
    const paletteMod = loadTsModule("src/components/CommandPalette.tsx", {
      react: hookReact,
      "../actions": actionsStub,
      "../i18n/vocabulary": vocabulary,
      "../runtime": rtStub,
      "../store": storeWithHook,
      "../uiVariant": v,
      "../workspace/trust": trust,
    });

    const renderButtons = (lang = "ko") => {
      store.setState({ commandPaletteOpen: true, language: lang });
      const tree = paletteMod.CommandPalette();
      return findElements(
        tree,
        (el) => el.type === "button" && typeof el.props?.["data-testid"] === "string",
      );
    };

    const koBtn = renderButtons("ko").find((el) => textContent(el).trim() === "새 편집기로 열기");
    assert.ok(koBtn, "Expected v1 palette command '새 편집기로 열기'");
    const enBtn = renderButtons("en").find((el) => textContent(el).trim() === "Open the new editor");
    assert.ok(enBtn, "Expected v1 palette command 'Open the new editor'");

    // 1. Refuses and writes nothing when an inline edit is open
    store.setState({
      activeSessionId: "sess-1",
      language: "ko",
      toast: null,
      inlineEdit: {
        kind: "cell",
        table: 0,
        row: 5,
        col: 1,
        before: "",
        opId: null,
      },
      draft: { ...store.EMPTY_DRAFT },
      savedDrafts: {},
    });
    const btn1 = renderButtons("ko").find((el) => textContent(el).trim() === "새 편집기로 열기");
    await btn1.props.onClick();
    assert.deepEqual(savedPrefs, []);
    assert.equal(reloadCount, 0);
    assert.ok(
      store.getState().toast && store.getState().toast.text.length > 0,
      "Expected toast notice when refusing switch with open inlineEdit",
    );

    // 2. Refuses and writes nothing when a queued change is not yet saved
    store.setState({
      inlineEdit: null,
      toast: null,
      draft: {
        ...store.EMPTY_DRAFT,
        sessionId: "sess-1",
        phase: "starting",
        ops: [
          {
            opId: "op-1",
            kind: "fill_cell",
            table: 0,
            row: 5,
            col: 1,
            text: "한글",
            before: "",
            origin: "user",
            sessionId: "sess-1",
          },
        ],
      },
      savedDrafts: {},
    });
    const btn2 = renderButtons("ko").find((el) => textContent(el).trim() === "새 편집기로 열기");
    await btn2.props.onClick();
    assert.deepEqual(savedPrefs, []);
    assert.equal(reloadCount, 0);
    assert.ok(
      store.getState().toast && store.getState().toast.text.length > 0,
      "Expected toast notice when refusing switch with unsaved queued change",
    );

    // 3. Writes editorVariant: "v2", drops ui= from query, and reloads when nothing is pending
    store.setState({
      inlineEdit: null,
      toast: null,
      draft: { ...store.EMPTY_DRAFT },
      savedDrafts: {},
    });
    const btn3 = renderButtons("ko").find((el) => textContent(el).trim() === "새 편집기로 열기");
    await btn3.props.onClick();
    assert.deepEqual(savedPrefs, [{ editorVariant: "v2" }]);
    assert.equal(globalThis.window.location.search, "");
    assert.equal(reloadCount, 1);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});
