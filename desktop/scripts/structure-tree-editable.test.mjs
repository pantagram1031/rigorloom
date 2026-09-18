import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { Icon } from "./icon-stub.mjs";

const require = createRequire(import.meta.url);
const source = readFileSync(new URL("../src/components/StructureTree.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2021,
    jsx: ts.JsxEmit.ReactJSX,
  },
  fileName: "StructureTree.tsx",
}).outputText;

const runtimeSource = readFileSync(new URL("../src/runtime.ts", import.meta.url), "utf8");

function inspectFixture(overrides = {}) {
  return {
    documentHash: "abc",
    sessionId: "s",
    summary: { documentHash: "abc", sessionId: "s" },
    graph: {
      documentHash: "abc",
      sessionId: "s",
      paragraphs: [{ section: "본문", at_para: 0, para_idx: 0, text: "hello" }],
      tables: [
        {
          index: 0,
          cells: [
            { addr: { row: 0, col: 0 }, classification: "fill_target", textPreview: "값" },
            { addr: { row: 0, col: 1 }, classification: "guide", textPreview: "안내" },
          ],
        },
      ],
    },
    regions: {
      documentHash: "abc",
      sessionId: "s",
      regions: [{ kind: "cell", table: 0, row: 0, col: 0 }],
    },
    ...overrides,
  };
}

function render(inspect, expanded = ["t:0"]) {
  const state = {
    selection: null,
    expanded,
  };
  const module = { exports: {} };
  const context = vm.createContext({
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime") return require(id);
      if (id === "react") return require(id);
      if (id === "../store") {
        return {
          useWorkspace: (selector) => selector(state),
          locateSelection: () => {},
          toggleExpanded: () => {},
          selectionId: (s) => (s ? JSON.stringify(s) : "none"),
        };
      }
      if (id === "../label") {
        return {
          humanCellAddress: (t, r, c) => `표 ${t + 1} · ${r + 1}행 ${c + 1}열`,
          trimLabel: (text, max = 34) => {
            const flat = String(text).replace(/\s+/g, " ").trim();
            return flat.length > max ? `${flat.slice(0, max)}…` : flat;
          },
        };
      }
      if (id === "../actions") {
        return { selectStructureNode: () => {} };
      }
      if (id === "../types") return {};
      if (id === "./Tag") {
        return {
          Tag: ({ tone, children }) =>
            React.createElement("span", { "data-tone": tone }, children),
          CLASSIFICATION_LABEL: {
            fill_target: "채움",
            guide: "안내",
            static: "고정",
            spacer: "여백",
          },
          CLASSIFICATION_TONE: {
            fill_target: "fill",
            guide: "guide",
            static: "static",
            spacer: "spacer",
          },
        };
      }
      if (id === "./Icon") return { Icon };
      throw new Error(`unexpected import: ${id}`);
    },
  });
  vm.runInContext(compiled, context);
  return renderToStaticMarkup(
    React.createElement(module.exports.StructureTree, { inspect, capabilities: null }),
  );
}

function editableIds(html) {
  return [...html.matchAll(/data-testid="([^"]+)"[^>]*data-editable="true"/g)].map((m) => m[1]);
}

test("inspect asks the runtime for the opt-in forbidden section", () => {
  assert.match(runtimeSource, /INSPECT_INCLUDE/);
  assert.match(runtimeSource, /"forbidden"/);
  assert.match(runtimeSource, /document\/inspect/);
});

test("without a forbidden payload the tree notes the protocol gap and does not invent anchors", () => {
  const html = render(inspectFixture());
  assert.match(html, /data-testid="forbidden-protocol-gap"/);
  assert.doesNotMatch(html, /data-testid="forbidden-anchor-/);
  assert.doesNotMatch(html, /data-testid="forbidden-group"/);
});

test("fill seats and fill_target cells are the only editable regions", () => {
  const html = render(inspectFixture());
  const ids = editableIds(html);
  assert.deepEqual([...ids].sort(), ["cell-0-0-0", "seat-0"]);
  assert.match(html, /data-testid="cell-0-0-1"[^>]*data-editable="false"/);
  assert.match(html, /data-testid="seat-0"[^>]*data-editable="true"/);
});

test("forbidden inventory rows use a distinct testid and are never editable", () => {
  const html = render(
    inspectFixture({
      forbidden: {
        sessionId: "s",
        documentHash: "abc",
        anchors: [{ kind: "anchor", text: "양식 앵커", atPara: 2, keepable: true }],
        placeholders: [{ kind: "placeholder", text: "[이름]", keepable: true }],
        removalTargets: [
          { kind: "removalTarget", text: "지울 안내", atPara: 9, keepable: false },
        ],
        counts: { anchors: 1, placeholders: 1, removalTargets: 1 },
        note: "residue inventory",
      },
    }),
  );
  assert.doesNotMatch(html, /data-testid="forbidden-protocol-gap"/);
  assert.match(html, /data-testid="forbidden-group"/);
  assert.match(html, /data-testid="forbidden-anchor-0"[^>]*data-editable="false"/);
  assert.match(html, /data-testid="forbidden-placeholder-0"[^>]*data-editable="false"/);
  assert.match(html, /data-testid="forbidden-removal-0"[^>]*data-editable="false"/);
  assert.equal(
    [...html.matchAll(/data-testid="forbidden-[^"]+"[^>]*data-editable="true"/g)].length,
    0,
  );
  const ids = editableIds(html);
  assert.ok(ids.every((id) => id === "seat-0" || id === "cell-0-0-0"));
});

test("tree rows use 1-based human addresses and keep charPr off the row text", () => {
  const html = render(
    inspectFixture({
      graph: {
        documentHash: "abc",
        sessionId: "s",
        paragraphs: [{ section: "본문", at_para: 0, para_idx: 0, text: "hello" }],
        tables: [
          {
            index: 0,
            cells: [
              {
                addr: { row: 4, col: 1 },
                classification: "fill_target",
                textPreview: "값",
                charPr: "11",
                charPrSuggested: "23",
              },
            ],
          },
        ],
      },
      regions: {
        documentHash: "abc",
        sessionId: "s",
        regions: [{ kind: "cell", table: 0, row: 4, col: 1, charPr: "11" }],
      },
    }),
  );
  assert.match(html, /표 1 · 5행 2열/);
  assert.match(html, /title="charPr 11 → 23"/);
  const withoutTitles = html.replace(/\stitle="[^"]*"/g, "");
  assert.doesNotMatch(withoutTitles, /charPr/);
});
