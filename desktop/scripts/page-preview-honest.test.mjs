import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const previewSource = readFileSync(
  new URL("../src/components/PagePreview.tsx", import.meta.url),
  "utf8",
);
const runtimeSource = readFileSync(new URL("../src/runtime.ts", import.meta.url), "utf8");

const renderStart = actionsSource.indexOf("const RENDER_DPI = 110;");
const renderEnd = actionsSource.indexOf("export function geometryKey(", renderStart);
assert.ok(renderStart >= 0 && renderEnd > renderStart, "renderCurrentPage source boundary changed");
const renderImplementation = stripTypeScriptTypes(
  actionsSource.slice(renderStart, renderEnd),
).replaceAll("export ", "");

const prepareStart = actionsSource.indexOf("export async function preparePages(");
const prepareEnd = actionsSource.indexOf("export interface LayoutEcho", prepareStart);
assert.ok(prepareStart >= 0 && prepareEnd > prepareStart, "preparePages source boundary changed");
const prepareImplementation = stripTypeScriptTypes(
  actionsSource.slice(prepareStart, prepareEnd),
).replaceAll("export ", "");

function compileComponent(relPath, fileName) {
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

const previewCompiled = compileComponent("../src/components/PagePreview.tsx", "PagePreview.tsx");

function inspectFixture() {
  return {
    documentHash: "abc",
    sessionId: "s",
    summary: {
      pageMetrics: {
        width: 59528,
        height: 84188,
        margin: { left: 0, right: 0, top: 0, bottom: 0, header: 0, footer: 0 },
      },
    },
  };
}

function goodRender(runId = "run-good") {
  return {
    available: true,
    source: { kind: "candidate", runId, sha256: "aa".repeat(32) },
    pageCount: 1,
    dpi: 110,
    image: {
      mediaType: "image/png",
      widthPx: 100,
      heightPx: 140,
      bytes: 12,
      sha256: "bb".repeat(32),
      path: "page.png",
      inline: true,
      inlineLimit: 1,
      data: "aaaa",
    },
  };
}

test("preview is requested by an explicit button, never on idle mount or keystroke", () => {
  assert.match(previewSource, /data-testid="request-preview"/);
  assert.doesNotMatch(
    previewSource,
    /renderPhase === ["']idle["'][\s\S]{0,80}renderCurrentPage/,
  );
  assert.doesNotMatch(previewSource, /onChange=\{[^}]*renderCurrentPage/);
});

test("runtime.ts exposes event/poll for the events command", () => {
  assert.match(runtimeSource, /["']event\/poll["']/);
});

test("unavailable render keeps the last good image and stores the JSON reason", async () => {
  let state = {
    activeSessionId: "s",
    page: 1,
    render: goodRender("run-1"),
    lastGoodRender: goodRender("run-1"),
    renderUnavailable: null,
    renderAtHead: "run-1",
    head: "run-1",
    candidates: { s: [{ runId: "run-2" }] },
  };
  const answers = [
    { available: false, unavailable: { reason: "needs_conversion", detail: "no pdf" } },
  ];
  const context = vm.createContext({
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    headCandidate: () => ({ runId: "run-2" }),
    rt: {
      renderPage: async () => answers.shift(),
      asRuntimeError: (error) => ({ code: "shell_error", message: String(error) }),
    },
  });
  vm.runInContext(
    `${renderImplementation}\nglobalThis.renderCurrentPage = renderCurrentPage;`,
    context,
  );
  await context.renderCurrentPage(1);
  assert.equal(state.render.available, true);
  assert.equal(state.render.source.runId, "run-1");
  assert.equal(state.lastGoodRender.source.runId, "run-1");
  assert.equal(state.renderUnavailable.available, false);
  assert.equal(state.renderUnavailable.unavailable.reason, "needs_conversion");
  assert.equal(state.renderAtHead, "run-1");
});

test("prepare is inert while composing and records com_busy as a refusal", async () => {
  let composing = {
    isComposing: true,
    activeSessionId: "s",
    preparePhase: "idle",
    prepareError: null,
    prepareNote: "stale-success",
  };
  const calls = [];
  const composingContext = vm.createContext({
    getState: () => composing,
    setState: (patch) => {
      composing = { ...composing, ...patch };
    },
    isPrepareRefusalCode: (code) => code === "com_busy" || code === "needs_hancom",
    renderCurrentPage: async () => {
      calls.push("render");
    },
    rt: {
      renderPrepare: async () => {
        calls.push("prepare");
        return { prepared: true };
      },
      asRuntimeError: (error) => error,
    },
  });
  vm.runInContext(
    `${prepareImplementation}\nglobalThis.preparePages = preparePages;`,
    composingContext,
  );
  await composingContext.preparePages();
  assert.deepEqual(calls, []);
  assert.equal(composing.preparePhase, "idle");

  let refused = {
    isComposing: false,
    activeSessionId: "s",
    preparePhase: "idle",
    prepareError: null,
    prepareNote: null,
  };
  const refusedContext = vm.createContext({
    getState: () => refused,
    setState: (patch) => {
      refused = { ...refused, ...patch };
    },
    isPrepareRefusalCode: (code) => code === "com_busy" || code === "needs_hancom",
    renderCurrentPage: async () => {
      calls.push("render");
    },
    rt: {
      renderPrepare: async () => {
        throw { code: "com_busy", message: "Hancom is already running" };
      },
      asRuntimeError: (error) => error,
    },
  });
  vm.runInContext(
    `${prepareImplementation}\nglobalThis.preparePages = preparePages;`,
    refusedContext,
  );
  await refusedContext.preparePages();
  assert.equal(refused.preparePhase, "failed");
  assert.equal(refused.prepareError.code, "com_busy");
  assert.equal(refused.prepareNote, null);
  assert.equal(calls.includes("render"), false);
});

function renderPreview(statePatch = {}) {
  const state = {
    zoom: 1,
    pageFit: "free",
    page: 1,
    render: goodRender("run-old"),
    lastGoodRender: goodRender("run-old"),
    renderUnavailable: {
      available: false,
      unavailable: { reason: "needs_conversion", detail: "convert first" },
    },
    renderPhase: "ready",
    renderError: null,
    preparePhase: "idle",
    prepareError: { code: "com_busy", message: "Hancom is already running" },
    prepareNote: null,
    isComposing: true,
    capabilities: { methods: ["document/renderPrepare"] },
    activeSessionId: "s",
    geometry: null,
    sessions: [{ sessionId: "s", source: { sha256: "cc".repeat(32) } }],
    candidates: { s: [{ runId: "run-new" }] },
    head: "run-new",
    renderAtHead: "run-old",
    changedByRun: {},
    ...statePatch,
  };
  const module = { exports: {} };
  const context = vm.createContext({
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return require(id);
      if (id === "react") return require(id);
      if (id === "../actions") {
        return {
          layoutEcho: () => null,
          loadChangedAddresses: () => {},
          loadGeometry: () => {},
          preparePages: () => {},
          renderCurrentPage: () => {},
        };
      }
      if (id === "../store") {
        return {
          useWorkspace: (selector) => selector(state),
          canPreparePages: (s) =>
            (s.capabilities?.methods ?? []).includes("document/renderPrepare"),
          fitScale: () => 1,
          getState: () => state,
          headCandidate: (s) =>
            (s.candidates[s.activeSessionId] ?? []).find((row) => row.runId === s.head) ?? null,
          previewIsStale: (s) => (s.renderAtHead ?? null) !== (s.head ?? null),
          previewRevisionText: (s) => s.render?.source?.runId ?? "",
          setFittedZoom: () => {},
          setPageFit: () => {},
          setZoom: () => {},
        };
      }
      if (id === "../types") return {};
      if (id === "./PageOverlay") {
        return { GeometryLegend: () => null, PageOverlay: () => null };
      }
      if (id === "./Tag") {
        return {
          Tag: ({ tone, children }) =>
            React.createElement("span", { "data-tone": tone }, children),
        };
      }
      throw new Error(`unexpected import: ${id}`);
    },
  });
  vm.runInContext(previewCompiled, context);
  return renderToStaticMarkup(
    React.createElement(module.exports.PagePreview, { inspect: inspectFixture() }),
  );
}

test("page preview labels the raster, marks it stale, keeps it on unavailable, and styles prepare as a refusal", () => {
  const html = renderPreview();
  assert.match(html, /data-testid="request-preview"/);
  assert.match(html, /data-testid="preview-revision"/);
  assert.match(html, /run-old/);
  assert.match(html, /data-testid="preview-stale"/);
  assert.match(html, /data-testid="page-raster"/);
  assert.match(html, /data-testid="render-unavailable-json"/);
  assert.match(html, /needs_conversion/);
  assert.match(html, /data-testid="prepare-pages"[^>]*disabled/);
  assert.match(
    html,
    /class="refusal"[^>]*data-testid="prepare-refusal"|data-testid="prepare-refusal"[^>]*class="refusal"/,
  );
  assert.doesNotMatch(
    html.match(/data-testid="prepare-refusal"[\s\S]*?<\/div>/)[0],
    /data-tone="ok"/,
  );
});
