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
import { uiFromImport } from "./kit-load.mjs";

const nodeRequire = createRequire(import.meta.url);
const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const mockSource = readFileSync(new URL("../src/devMock.ts", import.meta.url), "utf8");

const {
  VERIFY_FOOTER,
  checkerVerdict,
  mockVerifyResult,
  verifyTargetLabel,
  worstVerifyVerdict,
} = await import("../src/verifyReport.ts");

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

function renderVerifyPanel(state) {
  const exports = loadCompiled("../src/components/VerifyResults.tsx", "VerifyResults.tsx", (id) => {
    if (id === "react/jsx-runtime") return nodeRequire(id);
    if (id === "react") return nodeRequire(id);
    if (id === "../store") {
      return { useWorkspace: (selector) => selector(state), setState: () => {} };
    }
    if (id === "../verifyReport") {
      return {
        VERIFY_FOOTER,
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
        verifyTargetLabel,
      };
    }
    if (id === "./Icon") return { Icon };
    if (id === "./Tag") {
      return {
        Tag: ({ tone, children }) =>
          React.createElement("span", { "data-tone": tone }, children),
      };
    }
          const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
  });
  return renderToStaticMarkup(React.createElement(exports.VerifyPanel));
}

test("dev-mock answers candidate/verify with one pass, one warn, one unavailable", () => {
  assert.match(mockSource, /case "candidate\/verify"/);
  assert.match(mockSource, /mockVerifyResult/);
  const payload = mockVerifyResult("s1", null);
  const rows = payload.checks.checks;
  assert.equal(rows.length, 3);
  assert.equal(checkerVerdict(rows[0]), "pass");
  assert.equal(checkerVerdict(rows[1]), "warn");
  assert.equal((rows[1].warn ?? []).length, 2);
  assert.equal(checkerVerdict(rows[2]), "unavailable");
  assert.notEqual(checkerVerdict(rows[2]), "pass");
  assert.match(String(rows[2].reason), /Hancom/);
});

test("unavailable is never pass, even with empty findings", () => {
  assert.equal(
    checkerVerdict({ checker: "layout_qa", state: "unavailable", ok: true, hard: [], warn: [] }),
    "unavailable",
  );
  assert.notEqual(
    checkerVerdict({ checker: "layout_qa", state: "unavailable", ok: true }),
    "pass",
  );
  assert.equal(
    worstVerifyVerdict([
      { checker: "check_residue", state: "ran", ok: true, hard: [], warn: [] },
      { checker: "layout_qa", state: "unavailable", reason: "needs pdf" },
    ]),
    "unavailable",
  );
});

test("rows render each verdict and the freeze footer", () => {
  const html = renderVerifyPanel({
    verifyPanelOpen: true,
    checkPhase: "ready",
    verifyResult: mockVerifyResult("s1", null),
  });
  assert.match(html, /data-testid="verify-results"/);
  assert.match(html, /data-testid="verify-checker-check_residue"[^>]*data-verdict="pass"/);
  assert.match(html, /data-testid="verify-checker-verify_format"[^>]*data-verdict="warn"/);
  assert.match(html, /data-testid="verify-checker-layout_qa"[^>]*data-verdict="unavailable"/);
  assert.match(html, /data-testid="verify-unavailable-layout_qa"/);
  assert.match(html, /data-testid="verify-findings-verify_format"/);
  assert.match(html, /header\.xml/);
  assert.match(html, /쪽 1/);
  assert.match(html, /data-testid="verify-footer"/);
  assert.ok(html.includes(VERIFY_FOOTER));
  assert.doesNotMatch(html, /data-testid="verify-checker-layout_qa"[^>]*data-verdict="pass"/);
  assert.doesNotMatch(html, /렌더링 증명입니다/);
});

test("progress state is designed, not a blank dump", () => {
  const html = renderVerifyPanel({
    verifyPanelOpen: true,
    checkPhase: "starting",
    verifyResult: null,
  });
  assert.match(html, /data-testid="verify-progress"/);
  assert.match(html, /검사 중/);
  assert.ok(html.includes(VERIFY_FOOTER));
});

function verifyActions({ headRunId = null } = {}) {
  const start = actionsSource.indexOf("export async function runCheck");
  const end = actionsSource.indexOf("export function verdictFindings");
  assert.ok(start >= 0 && end > start, "runCheck slice moved");
  const code = stripTypeScriptTypes(actionsSource.slice(start, end)).replaceAll("export ", "");
  const calls = [];
  let state = {
    activeSessionId: "s1",
    checkPhase: "idle",
    verifyPanelOpen: false,
    sheetOpen: false,
    verifyResult: null,
    findings: [],
    checkedAt: null,
    candidateVerdict: null,
    candidates: { s1: headRunId ? [{ runId: headRunId }] : [] },
    head: headRunId,
  };
  const ctx = vm.createContext({
    rt: {
      verify: async (sessionId, runId) => {
        calls.push({ sessionId, runId });
        return mockVerifyResult(sessionId, runId ?? null);
      },
      asRuntimeError: (error) => error,
    },
    headCandidate: (s) => (s.head ? { runId: s.head } : null),
    verdictFindings: () => [],
    showToast: () => {},
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
  });
  vm.runInContext(
    `${code}
globalThis.runCheck = runCheck;`,
    ctx,
  );
  return { ctx, calls, read: () => state };
}

test("검사 실행 calls verify on the source when there is no candidate", async () => {
  const { ctx, calls, read } = verifyActions({ headRunId: null });
  await ctx.runCheck();
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], { sessionId: "s1", runId: null });
  assert.equal(read().checkPhase, "ready");
  assert.equal(read().verifyResult.target.source, true);
  assert.equal(read().verifyPanelOpen, true);
});

test("검사 실행 calls verify on the head candidate when one exists", async () => {
  const { ctx, calls, read } = verifyActions({ headRunId: "run-head" });
  await ctx.runCheck();
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], { sessionId: "s1", runId: "run-head" });
  assert.equal(read().candidateVerdict.runId, "run-head");
  assert.equal(verifyTargetLabel(read().verifyResult), "후보본 run-head");
});
