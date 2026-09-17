import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { Icon } from "./icon-stub.mjs";

const nodeRequire = createRequire(import.meta.url);
const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const mockSource = readFileSync(new URL("../src/devMock.ts", import.meta.url), "utf8");

const {
  AURALAB_PIPELINE_STATUS,
  PIPELINE_NOT_FOUND,
  stripSummary,
  stagesDone,
} = await import("../src/pipelineStatus.ts");

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

const label = loadCompiled("../src/label.ts", "label.ts", () => {
  throw new Error("label.ts has no imports");
});

const emptyState = loadCompiled("../src/components/EmptyState.tsx", "EmptyState.tsx", (id) => {
  if (id === "react/jsx-runtime") return nodeRequire(id);
  if (id === "react") return nodeRequire(id);
  if (id === "../label") return label;
  if (id === "./Icon") return { Icon };
  throw new Error(`unexpected import: ${id}`);
});

function renderPipeline(state, { refreshCalls } = { refreshCalls: [] }) {
  const exports = loadCompiled("../src/components/PipelineStatus.tsx", "PipelineStatus.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../actions") {
      return {
        refreshPipelineStatus: () => {
          refreshCalls.push("workspace/pipelineStatus");
        },
      };
    }
    if (id === "../pipelineStatus") {
      return {
        PIPELINE_NOT_FOUND,
        gateStateLabel: (gate) => (gate ? String(gate.state) : "없음"),
        gateTone: () => "none",
        stagesDone,
        stripSummary,
      };
    }
    if (id === "../store") {
      return { useWorkspace: (selector) => selector(state) };
    }
    if (id === "./EmptyState") return emptyState;
    if (id === "./Icon") return { Icon };
    if (id === "./Tag") {
      return {
        Tag: ({ children }) => React.createElement("span", { className: "tag" }, children),
      };
    }
    throw new Error(`unexpected import: ${id}`);
  });
  return {
    strip: renderToStaticMarkup(React.createElement(exports.PipelineStrip)),
    panel: renderToStaticMarkup(React.createElement(exports.PipelinePanel)),
    refreshCalls,
  };
}

test("the strip renders slug, mode, progress and next gate from the AURALAB mock", () => {
  const { strip } = renderPipeline({
    pipelineStatus: AURALAB_PIPELINE_STATUS,
    pipelinePhase: "ready",
    pipelineError: null,
  });
  assert.match(strip, /data-testid="pipeline-strip"/);
  assert.match(strip, /report-auralab-classroom/);
  assert.match(strip, /autonomous/);
  assert.match(strip, /12\/12 단계 완료/);
  assert.match(strip, /다음 게이트 없음/);
  assert.match(strip, /data-testid="pipeline-refresh"/);
});

test("the panel lists each AURALAB stage with its copied gate state", () => {
  const { panel } = renderPipeline({
    pipelineStatus: AURALAB_PIPELINE_STATUS,
    pipelinePhase: "ready",
    pipelineError: null,
  });
  assert.match(panel, /data-testid="pipeline-panel"/);
  assert.match(panel, /topic_pick/);
  assert.match(panel, /auto_approved/);
  assert.match(panel, /data-stage="2.5"/);
  assert.match(panel, /2026-09-16T21:38:59/);
});

test("no PIPELINE.md is a designed empty state, not a grey dump", () => {
  const { strip, panel } = renderPipeline({
    pipelineStatus: PIPELINE_NOT_FOUND,
    pipelinePhase: "ready",
    pipelineError: null,
  });
  assert.equal(strip, "");
  assert.match(panel, /data-testid="pipeline-empty"/);
  assert.match(panel, /보고서 작업 폴더가 아닙니다/);
  assert.doesNotMatch(panel, /\[object Object\]/);
});

test("dev-mock answers workspace/pipelineStatus with the AURALAB header shape", () => {
  assert.match(mockSource, /case "workspace\/pipelineStatus"/);
  assert.match(mockSource, /AURALAB_PIPELINE_STATUS/);
  assert.equal(AURALAB_PIPELINE_STATUS.slug, "report-auralab-classroom");
  assert.equal(AURALAB_PIPELINE_STATUS.stages.length, 12);
  assert.equal(AURALAB_PIPELINE_STATUS.stages[0].gate.state, "auto_approved");
  assert.equal(AURALAB_PIPELINE_STATUS.nextGate, null);
});

function pipelineActions() {
  const start = actionsSource.indexOf("/** Read-only PIPELINE.md header");
  const end = actionsSource.indexOf("export async function refreshSessions");
  assert.ok(start >= 0 && end > start, "pipeline status action slice moved");
  const code = stripTypeScriptTypes(actionsSource.slice(start, end)).replaceAll("export ", "");
  const calls = [];
  let state = {
    activeSessionId: "s1",
    openedPaths: { s1: "C:\\\\reports\\\\report-auralab-classroom\\\\output\\\\out.hwpx" },
    pipelineStatus: null,
    pipelinePhase: "idle",
    pipelineError: null,
  };
  const ctx = vm.createContext({
    PIPELINE_NOT_FOUND,
    rt: {
      pipelineStatus: async (path) => {
        calls.push(path);
        return AURALAB_PIPELINE_STATUS;
      },
      asRuntimeError: (error) => error,
    },
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
  });
  vm.runInContext(
    `${code}
globalThis.loadPipelineStatus = loadPipelineStatus;
globalThis.refreshPipelineStatus = refreshPipelineStatus;`,
    ctx,
  );
  return { ctx, calls, read: () => state };
}

test("refresh calls workspace/pipelineStatus for the session's original path", async () => {
  const { ctx, calls, read } = pipelineActions();
  await ctx.refreshPipelineStatus();
  assert.equal(calls.length, 1);
  assert.match(calls[0], /out\.hwpx$/);
  assert.equal(read().pipelineStatus.slug, "report-auralab-classroom");
  assert.equal(read().pipelinePhase, "ready");
});
