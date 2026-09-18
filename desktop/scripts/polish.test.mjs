import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import { uiFromImport } from "./kit-load.mjs";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const nodeRequire = createRequire(import.meta.url);
const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

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

const icon = loadCompiled("../src/components/Icon.tsx", "Icon.tsx", (id) => {
  if (id === "react/jsx-runtime") return nodeRequire(id);
  if (id === "react") return nodeRequire(id);
        const ui = uiFromImport(id);
      if (ui) return ui;
      throw new Error(`unexpected import: ${id}`);
});

test("every Icon name renders an svg", () => {
  assert.ok(Array.isArray(icon.ICON_NAMES) && icon.ICON_NAMES.length >= 16);
  for (const name of icon.ICON_NAMES) {
    const html = renderToStaticMarkup(React.createElement(icon.Icon, { name }));
    assert.match(html, /<svg\b/);
    assert.match(html, new RegExp(`data-icon="${name}"`));
    assert.match(html, /stroke-width="1.5"|strokeWidth="1.5"/);
    assert.match(html, /currentColor/);
  }
});

test("focus-visible rings exist for button, tab, and treeitem", () => {
  assert.match(css, /button:focus-visible/);
  assert.match(css, /\[role="tab"\]:focus-visible/);
  assert.match(css, /\[role="treeitem"\]:focus-visible/);
  assert.match(css, /outline:\s*2px solid var\(--accent\)/);
  assert.match(css, /outline-offset:\s*2px/);
});

test("R1–R5 classes that set a color use tokens or a dark override", () => {
  const classes = [
    "empty-state",
    "empty-state-icon",
    "empty-state-title",
    "empty-state-body",
    "icon-rail",
    "icon-rail-btn",
    "icon-rail-count",
    "inspector-tabs",
    "tab-badge",
    "tab-badge-dot",
    "inspector-body",
    "verify-pill",
    "verify-engine",
    "verify-popover",
    "verify-popover-panel",
    "verify-details-head",
    "verify-group",
    "work-disclosure",
    "hunk-card",
    "hunk-pane",
    "hunk-missing",
    "hunk-del",
    "hunk-ins",
    "home-onboarding",
    "home-link",
    "home-btn",
    "bubble",
    "bubble-user",
    "bubble-agent",
    "system-row",
    "plan-arrival",
    "checkpoint-dot",
    "checkpoint-row",
    "composer-ime",
  ];
  const colorProp =
    /(?:^|[\s{;])(?:color|background(?:-color)?|border(?:-color)?|fill|stroke|outline-color|box-shadow)\s*:/i;
  const tokenOrVar = /var\(--|color-mix\(|transparent|none|inherit|currentColor/;
  const rawColor = /#|rgb\(|rgba\(|hsl\(/;
  const missing = [];
  for (const name of classes) {
    const re = new RegExp(`\\.${name}(?:[^{.\\s]|\\.[a-z-]+)*\\s*\\{([^}]*)\\}`, "g");
    let match;
    while ((match = re.exec(css))) {
      const body = match[1];
      if (!colorProp.test(body)) continue;
      if (tokenOrVar.test(body) && !rawColor.test(body)) continue;
      if (rawColor.test(body) && !css.includes(`prefers-color-scheme: dark`)) {
        missing.push(name);
      } else if (rawColor.test(body) && !tokenOrVar.test(body)) {
        missing.push(name);
      }
    }
  }
  assert.deepEqual(missing, [], `hardcoded colors without tokens: ${missing.join(", ")}`);
  assert.match(css, /@media \(prefers-color-scheme: dark\)/);
});
