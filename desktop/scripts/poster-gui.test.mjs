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
  POSTER_FOOTER,
  POSTER_PREVIEW_LABEL,
  canRunPoster,
  mockPosterResult,
} = await import("../src/posterReport.ts");
const {
  checkerVerdict,
} = await import("../src/verifyReport.ts");

const CAPABLE = {
  methods: ["workspace/posterRun"],
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

function renderPoster(state) {
  const exports = loadCompiled("../src/components/PosterResults.tsx", "PosterResults.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../actions") {
      return { runPoster: () => {} };
    }
    if (id === "../posterReport") {
      return { POSTER_FOOTER, POSTER_PREVIEW_LABEL, canRunPoster };
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
        verdictLabel: (v) =>
          v === "pass" ? "통과" : v === "warn" ? "주의" : v === "fail" ? "실패" : "미실행",
        verdictTone: (v) =>
          v === "pass" ? "ok" : v === "warn" ? "warn" : v === "fail" ? "bad" : "none",
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
  return renderToStaticMarkup(React.createElement(exports.PosterCard));
}

test("포스터 만들기 is shown only when poster inputs exist", () => {
  const shown = renderPoster({
    pipelineStatus: AURALAB_PIPELINE_STATUS,
    capabilities: CAPABLE,
    posterPhase: "idle",
    posterResult: null,
    posterError: null,
  });
  assert.match(shown, /data-testid="poster-run"/);
  assert.match(shown, /포스터 만들기/);

  const incomplete = {
    ...AURALAB_PIPELINE_STATUS,
    posterInputs: { ...AURALAB_PIPELINE_STATUS.posterInputs, complete: false, missing: ["poster/form.pptx"] },
  };
  const hidden = renderPoster({
    pipelineStatus: incomplete,
    capabilities: CAPABLE,
    posterPhase: "idle",
    posterResult: null,
    posterError: null,
  });
  assert.doesNotMatch(hidden, /data-testid="poster-run"/);

  const empty = renderPoster({
    pipelineStatus: PIPELINE_NOT_FOUND,
    capabilities: CAPABLE,
    posterPhase: "idle",
    posterResult: null,
    posterError: null,
  });
  assert.doesNotMatch(empty, /data-testid="poster-run"/);
});

test("result card shows PNG preview, P2 rows, hashes, and not-a-proof label", () => {
  const result = mockPosterResult(AURALAB_PIPELINE_STATUS.workspacePath, "s1");
  const html = renderPoster({
    pipelineStatus: AURALAB_PIPELINE_STATUS,
    capabilities: CAPABLE,
    posterPhase: "ready",
    posterResult: result,
    posterError: null,
  });
  assert.match(html, /data-testid="poster-result"/);
  assert.match(html, /data-testid="poster-preview"/);
  assert.match(html, /data:image\/png;base64,/);
  assert.match(html, /미리보기 이미지, 증명 아님/);
  assert.match(html, /data-testid="poster-checker-form mtime unchanged"[^>]*data-verdict="pass"/);
  assert.match(html, /data-verdict="warn"/);
  assert.match(html, /poster-checker-pictures/);
  assert.match(html, /data-testid="poster-output-pptx"/);
  assert.match(html, /data-testid="poster-output-png"/);
  assert.match(html, /ee0{62}/);
  assert.ok(html.includes(POSTER_FOOTER));
  assert.doesNotMatch(html, /렌더링 증명입니다/);
  assert.equal(checkerVerdict(result.verify[0]), "pass");
  assert.equal(checkerVerdict(result.verify[1]), "warn");
});

test("dev-mock answers workspace/posterRun with a PNG data URL and pass+warn", () => {
  assert.match(mockSource, /case "workspace\/posterRun"/);
  assert.match(mockSource, /mockPosterResult/);
  const payload = mockPosterResult("C:\\\\ws", "s1");
  assert.equal(payload.state, "warn");
  assert.ok(payload.preview?.data);
  assert.equal(payload.verify.length, 2);
  assert.equal(checkerVerdict(payload.verify[0]), "pass");
  assert.equal(checkerVerdict(payload.verify[1]), "warn");
});

function posterActions() {
  const start = actionsSource.indexOf("export async function runPoster");
  const end = actionsSource.indexOf("// --- recents");
  assert.ok(start >= 0 && end > start, "runPoster slice moved");
  const code = stripTypeScriptTypes(actionsSource.slice(start, end)).replaceAll("export ", "");
  const calls = [];
  let state = {
    activeSessionId: "s1",
    pipelineStatus: AURALAB_PIPELINE_STATUS,
    capabilities: CAPABLE,
    posterPhase: "idle",
    posterResult: null,
    posterError: null,
  };
  const ctx = vm.createContext({
    canRunPoster,
    rt: {
      posterRun: async (params) => {
        calls.push(params);
        return mockPosterResult(params.workspace, params.sessionId);
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
globalThis.runPoster = runPoster;`,
    ctx,
  );
  return { ctx, calls, read: () => state };
}

test("포스터 만들기 calls workspace/posterRun on the pipeline workspace", async () => {
  const { ctx, calls, read } = posterActions();
  await ctx.runPoster();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].workspace, AURALAB_PIPELINE_STATUS.workspacePath);
  assert.equal(calls[0].sessionId, "s1");
  assert.equal(read().posterPhase, "ready");
  assert.equal(read().posterResult.state, "warn");
});
