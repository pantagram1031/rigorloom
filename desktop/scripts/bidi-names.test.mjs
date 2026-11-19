// File names and tab titles show without bidi controls (finding 20): a name
// like `보고서‮gpj.hwpx` must not read as a spoofed `…xpwh.jpg`.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const { plainName } = await import("../src/shell/names.ts");
const nodeRequire = createRequire(import.meta.url);

const SPOOF = "<img src=x onerror=alert(1)>‮gpj.hwpx";

test("plainName drops every bidi control and keeps the rest", () => {
  assert.equal(plainName(SPOOF), "<img src=x onerror=alert(1)>gpj.hwpx");
  for (const ch of ["‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩", "‎", "‏", "؜"]) {
    assert.equal(plainName(`가${ch}나.hwpx`), "가나.hwpx", JSON.stringify(ch));
  }
  assert.equal(plainName("기안문 (별지 제1호서식).hwpx"), "기안문 (별지 제1호서식).hwpx");
});

test("FileName renders an isolated name with no bidi control in it", () => {
  const source = readFileSync(new URL("../src/shell/parts.tsx", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  });
  const module = { exports: {} };
  const stubs = { "./names": { plainName }, "./keys": { chordCaps: () => [], useKeyHint: () => null } };
  const req = (id) => (id in stubs ? stubs[id] : nodeRequire(id));
  vm.runInThisContext(`(function(exports, require, module) {\n${outputText}\n})`)(module.exports, req, module);
  const html = renderToStaticMarkup(React.createElement(module.exports.FileName, { name: SPOOF }));
  assert.match(html, /^<bdi class="sh-fname">/);
  assert.doesNotMatch(html, /[‪-‮⁦-⁩]/);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /gpj<span class="sh-fname-ext">\.hwpx<\/span>/);
});
