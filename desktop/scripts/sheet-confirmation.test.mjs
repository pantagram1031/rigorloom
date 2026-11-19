// The approval sheet's single-use confirmation token, client side
// (src/workspace/sheetConfirmation.ts). The bridge refuses an approval
// without it (tests/test_ui_approval_confirmation.py); here: the sheet asks
// for it when it renders, the confirm spends it once, and only for the
// document and base the sheet showed.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function load() {
  const source = readFileSync(new URL("../src/workspace/sheetConfirmation.ts", import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText;
  const module = { exports: {} };
  const req = (id) => {
    if (id === "../runtime") return { approvalConfirmation: async () => null };
    throw new Error(`Unexpected require(${id})`);
  };
  vm.runInThisContext(`(function(exports, require, module) {\n${code}\n})`)(module.exports, req, module);
  return module.exports;
}

const { createSheetConfirmations } = load();

const A = { sessionId: "S", planId: "p1", planHash: "h1", baseDigest: "d0" };

function setup(ttl = 120_000) {
  const asked = [];
  let clock = 1_000;
  let n = 0;
  const holder = createSheetConfirmations(
    async (binding) => {
      asked.push({ ...binding });
      n += 1;
      return { token: `t${n}`, expiresInMs: ttl };
    },
    () => clock,
  );
  return { holder, asked, advance: (ms) => (clock += ms) };
}

test("the token asked for at render is spent once on that plan", async () => {
  const { holder, asked } = setup();
  holder.prepare(A);
  holder.prepare({ ...A }); // a re-render asks nothing new
  assert.equal(asked.length, 1);
  assert.equal(await holder.take(A), "t1");
  assert.equal(await holder.take(A), null, "spent");
  assert.equal(asked.length, 1);
});

test("no sheet, no token", async () => {
  const { holder, asked } = setup();
  assert.equal(await holder.take(A), null);
  holder.prepare(A);
  holder.clear();
  assert.equal(await holder.take(A), null);
  assert.equal(asked.length, 1);
});

test("a confirm on another document or base gets nothing", async () => {
  const { holder, asked } = setup();
  holder.prepare(A);
  assert.equal(await holder.take({ ...A, sessionId: "T" }), null);
  holder.prepare(A);
  assert.equal(await holder.take({ ...A, baseDigest: "d9" }), null);
  assert.equal(asked.length, 2);
});

test("a plan re-proposed by the confirm (뺌 pruned) gets a token for the new plan", async () => {
  const { holder, asked } = setup();
  holder.prepare(A);
  const pruned = { ...A, planId: "p2", planHash: "h2" };
  assert.equal(await holder.take(pruned), "t2");
  assert.deepEqual(asked[1], pruned);
});

test("a token close to its expiry is replaced", async () => {
  const { holder, asked, advance } = setup(20_000);
  holder.prepare(A);
  advance(10_000);
  assert.equal(await holder.take(A), "t2");
  assert.equal(asked.length, 2);
});
