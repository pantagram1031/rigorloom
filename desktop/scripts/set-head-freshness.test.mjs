import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const headStart = source.indexOf("interface HeadSelectionLease {");
const headEnd = source.indexOf("// --- approval", headStart);
assert.ok(headStart >= 0 && headEnd > headStart, "setHead source boundary changed");
const headImplementation = source.slice(headStart, headEnd).replace(/^export /gm, "");

const receiptStart = source.indexOf("export async function loadReceipt(");
const receiptEnd = source.indexOf("export function openReceipt", receiptStart);
assert.ok(receiptStart >= 0 && receiptEnd > receiptStart, "loadReceipt source boundary changed");
const receiptImplementation = source
  .slice(receiptStart, receiptEnd)
  .replace(/^export /gm, "");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function fixture() {
  const queuedOps = [{ opId: "queued-op", kind: "set_run", text: "new" }];
  let state = {
    activeSessionId: "session-A",
    head: null,
    applied: { runId: "previous-applied" },
    candidateVerdict: {
      runId: "previous-head",
      report: { marker: "previous" },
    },
    editIntentGeneration: 4,
    draft: { ops: queuedOps },
    receipts: {},
    receiptError: null,
  };
  const reads = [];
  const rebases = [];
  const rt = {
    readReceipt(sessionId, runId) {
      const pending = deferred();
      reads.push({ ...pending, sessionId, runId });
      return pending.promise;
    },
    asRuntimeError(error) {
      return { code: "receipt_failed", message: String(error) };
    },
  };
  const context = vm.createContext({
    rt,
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    setQueue: async (ops, options) => {
      rebases.push({ ops, options });
    },
  });
  vm.runInContext(
    `${stripTypeScriptTypes(receiptImplementation)}
${stripTypeScriptTypes(headImplementation)}
globalThis.invokeSetHead = setHead;`,
    context,
  );

  return {
    read: () => state,
    patch: (patch) => {
      state = { ...state, ...patch };
    },
    select: (runId) => context.invokeSetHead(runId),
    reads,
    rebases,
    receipt: (runId, marker = runId) => ({
      runId,
      sessionId: "session-A",
      checks: { marker },
    }),
  };
}

test("the current head choice publishes its receipt and rebases the queue", async () => {
  const f = fixture();
  const pending = f.select("run-A");

  assert.equal(f.read().head, "run-A");
  assert.equal(f.read().applied, null);
  assert.equal(f.read().candidateVerdict, null);
  assert.equal(f.read().editIntentGeneration, 5);

  f.reads[0].resolve(f.receipt("run-A"));
  await pending;

  assert.equal(f.read().candidateVerdict.runId, "run-A");
  assert.equal(f.read().receipts["run-A"].runId, "run-A");
  assert.equal(f.rebases.length, 1);
  assert.equal(f.rebases[0].options.baseRunId, "run-A");
  assert.equal(f.rebases[0].ops, f.read().draft.ops);
});

test("an older receipt completion cannot replace a newer head or queue base", async () => {
  const f = fixture();
  const older = f.select("run-A");
  const newer = f.select("run-B");

  f.reads[1].resolve(f.receipt("run-B"));
  await newer;
  f.reads[0].resolve(f.receipt("run-A"));
  await older;

  assert.equal(f.read().head, "run-B");
  assert.equal(f.read().candidateVerdict.runId, "run-B");
  assert.equal(f.read().receipts["run-A"], undefined);
  assert.deepEqual(f.rebases.map((row) => row.options.baseRunId), ["run-B"]);
});

test("invocation order fences an A-B-A selection with the same final run id", async () => {
  const f = fixture();
  const firstA = f.select("run-A");
  const middleB = f.select("run-B");
  const latestA = f.select("run-A");

  f.reads[2].resolve(f.receipt("run-A", "latest-A"));
  await latestA;
  f.reads[0].resolve(f.receipt("run-A", "first-A"));
  await firstA;
  f.reads[1].resolve(f.receipt("run-B", "middle-B"));
  await middleB;

  assert.equal(f.read().candidateVerdict.report.marker, "latest-A");
  assert.equal(f.read().receipts["run-A"].checks.marker, "latest-A");
  assert.equal(f.read().receipts["run-B"], undefined);
  assert.deepEqual(f.rebases.map((row) => row.options.baseRunId), ["run-A"]);
});

test("a receipt completion from the previous session publishes nothing", async () => {
  const f = fixture();
  const pending = f.select("run-A");
  f.patch({ activeSessionId: "session-B" });
  f.reads[0].resolve(f.receipt("run-A"));
  await pending;

  assert.equal(f.read().candidateVerdict, null);
  assert.equal(f.read().receipts["run-A"], undefined);
  assert.equal(f.read().receiptError, null);
  assert.equal(f.rebases.length, 0);
});

test("a stale receipt failure cannot cover a newer successful selection", async () => {
  const f = fixture();
  const older = f.select("run-A");
  const newer = f.select("run-B");

  f.reads[1].resolve(f.receipt("run-B"));
  await newer;
  f.reads[0].reject(new Error("late A failure"));
  await older;

  assert.equal(f.read().candidateVerdict.runId, "run-B");
  assert.equal(f.read().receiptError, null);
  assert.deepEqual(f.rebases.map((row) => row.options.baseRunId), ["run-B"]);
});

test("the current receipt failure remains visible and preserves rebase behavior", async () => {
  const f = fixture();
  const pending = f.select("run-A");
  f.reads[0].reject(new Error("current A failure"));
  await pending;

  assert.equal(f.read().candidateVerdict, null);
  assert.equal(f.read().receiptError.code, "receipt_failed");
  assert.deepEqual(f.rebases.map((row) => row.options.baseRunId), ["run-A"]);
});
