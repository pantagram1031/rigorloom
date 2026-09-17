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
} = await import("../src/pipelineStatus.ts");
const {
  FILL_FOOTER,
  canRunFill,
  mockFillResult,
  proofGradeLabel,
} = await import("../src/fillReport.ts");
const {
  checkerVerdict,
  verdictLabel,
  verdictTone,
} = await import("../src/verifyReport.ts");

const HANCOM = {
  methods: ["workspace/fillRun"],
  backends: { com: { state: "available", reason: null, opKinds: [] } },
  tools: { fill_report: { state: "available", reason: null, path: "engine/scripts/fill_report.py" } },
};

const NO_HANCOM = {
  methods: ["workspace/fillRun"],
  backends: { com: { state: "unavailable", reason: "no Hancom", opKinds: [] } },
  tools: { fill_report: { state: "available", reason: null, path: "engine/scripts/fill_report.py" } },
};

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

function renderFill(state) {
  const exports = loadCompiled("../src/components/FillResults.tsx", "FillResults.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../actions") {
      return { runFill: () => {}, cancelFill: () => {} };
    }
    if (id === "../fillReport") {
      return { FILL_FOOTER, canRunFill, proofGradeLabel };
    }
    if (id === "../store") {
      return { useWorkspace: (selector) => selector(state) };
    }
    if (id === "../verifyReport") {
      return {
        checkerCounts: (row) => ({
          hard: Array.isArray(row.hard) ? row.hard.length : 0,
          warn: Array.isArray(row.warn) ? row.warn.length : 0,
        }),
        checkerFindings: (row) => [...(row.hard ?? []), ...(row.warn ?? [])],
        checkerVerdict,
        verdictLabel,
        verdictTone,
      };
    }
    if (id === "./Tag") {
      return {
        Tag: ({ tone, children }) =>
          React.createElement("span", { "data-tone": tone }, children),
      };
    }
    if (id === "./Icon") return { Icon };
    throw new Error(`unexpected import: ${id}`);
  });
  return renderToStaticMarkup(React.createElement(exports.FillCard));
}

test("채우기 실행 is shown only when the workspace is complete and Hancom is available", () => {
  const shown = renderFill({
    pipelineStatus: AURALAB_PIPELINE_STATUS,
    capabilities: HANCOM,
    fillPhase: "idle",
    fillProgress: null,
    fillResult: null,
    fillError: null,
  });
  assert.match(shown, /data-testid="fill-run"/);
  assert.match(shown, /채우기 실행/);

  const noHancom = renderFill({
    pipelineStatus: AURALAB_PIPELINE_STATUS,
    capabilities: NO_HANCOM,
    fillPhase: "idle",
    fillProgress: null,
    fillResult: null,
    fillError: null,
  });
  assert.doesNotMatch(noHancom, /data-testid="fill-run"/);

  const incomplete = {
    ...AURALAB_PIPELINE_STATUS,
    fillInputs: { ...AURALAB_PIPELINE_STATUS.fillInputs, complete: false, missing: ["build.yaml"] },
  };
  const hidden = renderFill({
    pipelineStatus: incomplete,
    capabilities: HANCOM,
    fillPhase: "idle",
    fillProgress: null,
    fillResult: null,
    fillError: null,
  });
  assert.doesNotMatch(hidden, /data-testid="fill-run"/);

  const empty = renderFill({
    pipelineStatus: PIPELINE_NOT_FOUND,
    capabilities: HANCOM,
    fillPhase: "idle",
    fillProgress: null,
    fillResult: null,
    fillError: null,
  });
  assert.doesNotMatch(empty, /data-testid="fill-run"/);
});

test("progress card shows iteration and state", () => {
  const html = renderFill({
    pipelineStatus: AURALAB_PIPELINE_STATUS,
    capabilities: HANCOM,
    fillPhase: "starting",
    fillProgress: { iteration: 2, state: "gappy", proofGrade: "hancom" },
    fillResult: null,
    fillError: null,
  });
  assert.match(html, /data-testid="fill-progress"/);
  assert.match(html, /반복 2/);
  assert.match(html, /상태 gappy/);
  assert.match(html, /증명 등급: hancom/);
  assert.match(html, /data-testid="fill-cancel"/);
  assert.doesNotMatch(html, /data-testid="fill-run"/);
});

test("result card shows proof grade, P2 checker rows, hashes, and no render certificate", () => {
  const result = mockFillResult(AURALAB_PIPELINE_STATUS.workspacePath, "s1");
  const html = renderFill({
    pipelineStatus: AURALAB_PIPELINE_STATUS,
    capabilities: HANCOM,
    fillPhase: "ready",
    fillProgress: null,
    fillResult: result,
    fillError: null,
  });
  assert.match(html, /data-testid="fill-result"/);
  assert.match(html, /data-testid="fill-proof-grade"/);
  assert.match(html, /증명 등급: hancom/);
  assert.match(html, /data-testid="fill-sheet-0"[^>]*data-proof-grade="hancom"/);
  assert.match(html, /data:image\/png;base64,/);
  assert.match(html, /data-testid="fill-checker-layout_qa"[^>]*data-verdict="pass"/);
  assert.match(html, /data-testid="fill-checker-verify_format"[^>]*data-verdict="pass"/);
  assert.match(html, /data-testid="fill-output-hwpx"/);
  assert.match(html, /aa0{62}/);
  assert.ok(html.includes(FILL_FOOTER));
  assert.doesNotMatch(html, /렌더링 증명입니다/);
  assert.equal(proofGradeLabel("none"), "증명 등급: none");
  assert.equal(checkerVerdict(result.layoutQa), "pass");
});

test("dev-mock answers workspace/fillRun with the AURALAB loop shape", () => {
  assert.match(mockSource, /case "workspace\/fillRun"/);
  assert.match(mockSource, /mockFillResult/);
  const payload = mockFillResult("C:\\\\ws", "s1");
  assert.equal(payload.state, "converged");
  assert.equal(payload.proofGrade, "hancom");
  assert.equal(payload.contactSheets.length, 1);
  assert.equal(payload.layoutQa.checker, "layout_qa");
  assert.equal(payload.verifyFormat.checker, "verify_format");
});

function fillActions() {
  const start = actionsSource.indexOf("const FILL_TAG = \"fill-run\"");
  const end = actionsSource.indexOf("// --- recents");
  assert.ok(start >= 0 && end > start, "runFill slice moved");
  const code = stripTypeScriptTypes(actionsSource.slice(start, end)).replaceAll("export ", "");
  const calls = [];
  let state = {
    activeSessionId: "s1",
    pipelineStatus: AURALAB_PIPELINE_STATUS,
    capabilities: HANCOM,
    fillPhase: "idle",
    fillProgress: null,
    fillResult: null,
    fillError: null,
  };
  const ctx = vm.createContext({
    canRunFill,
    rt: {
      fillRun: async (params) => {
        calls.push(params);
        return mockFillResult(params.workspace, params.sessionId);
      },
      cancel: async (tag) => {
        calls.push({ cancel: tag });
        return true;
      },
      asRuntimeError: (error) => error,
    },
    showToast: () => {},
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
  });
  vm.runInContext(
    `${code}
globalThis.runFill = runFill;
globalThis.cancelFill = cancelFill;`,
    ctx,
  );
  return { ctx, calls, read: () => state };
}

test("채우기 실행 calls workspace/fillRun on the pipeline workspace", async () => {
  const { ctx, calls, read } = fillActions();
  await ctx.runFill();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].workspace, AURALAB_PIPELINE_STATUS.workspacePath);
  assert.equal(calls[0].sessionId, "s1");
  assert.equal(read().fillPhase, "ready");
  assert.equal(read().fillResult.state, "converged");
  assert.equal(read().fillResult.proofGrade, "hancom");
});
