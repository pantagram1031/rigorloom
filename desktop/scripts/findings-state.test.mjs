import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const source = readFileSync(new URL("../src/components/Findings.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2021,
    jsx: ts.JsxEmit.ReactJSX,
  },
  fileName: "Findings.tsx",
}).outputText;

function render(overrides = {}) {
  const state = {
    sheetOpen: true,
    checkPhase: "idle",
    findings: [],
    checkedAt: null,
    ...overrides,
  };
  const module = { exports: {} };
  const context = vm.createContext({
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return require(id);
      if (id === "../store") {
        return {
          useWorkspace: (selector) => selector(state),
          locateSelection: () => {},
          setState: () => {},
        };
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
  vm.runInContext(compiled, context);
  return renderToStaticMarkup(React.createElement(module.exports.Findings));
}

test("idle findings sheet says not run and never shows a green clear verdict", () => {
  const html = render({ checkPhase: "idle" });
  assert.match(html, /실행 안 함/);
  assert.match(html, /아직 검사를 실행하지 않았습니다/);
  assert.doesNotMatch(html, /걸림 없음/);
});

test("failed findings sheet is unavailable and hides stale findings", () => {
  const html = render({
    checkPhase: "failed",
    findings: [
      {
        code: "old-finding",
        where: "표 1",
        message: "이전 검사의 결과",
        severity: "hard",
        selection: null,
      },
    ],
  });
  assert.match(html, /검사 불가/);
  assert.match(html, /검사를 완료하지 못했습니다/);
  assert.doesNotMatch(html, /이전 검사의 결과/);
  assert.doesNotMatch(html, /걸림 없음/);
});

test("successful ready check with no findings is the only green clear state", () => {
  const html = render({ checkPhase: "ready", checkedAt: "2026-09-08T00:00:00Z" });
  assert.match(html, /걸림 없음/);
  assert.match(html, /검사에서 걸린 항목이 없습니다/);
  assert.match(html, /2026-09-08T00:00:00Z/);
});

test("evidence boundary does not claim rendering or submission checks are unavailable", () => {
  const html = render({ checkPhase: "ready" });
  assert.match(html, /렌더 증명이나 후보본 적용 시의 제출 검사 결과를 뜻하지 않습니다/);
  assert.doesNotMatch(html, /런타임에 그 방법이 없습니다/);
});
