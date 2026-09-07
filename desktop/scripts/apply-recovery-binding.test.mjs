import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const start = source.indexOf("export async function resolveRecovery(");
const end = source.indexOf("// --- receipts", start);
assert.ok(start >= 0 && end > start, "resolveRecovery source boundary changed");
const implementation = stripTypeScriptTypes(source.slice(start, end)).replace(
  "export async function resolveRecovery",
  "async function resolveRecovery",
);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

const recovery = (planId = "plan-A", approvalId = "approval-A") => ({
  planId,
  approvalId,
  atUtc: "2026-09-08T00:00:00Z",
  reason: "runtime stopped",
  outcome: "unknown",
  runId: null,
});

function receipt(overrides = {}) {
  return {
    runId: "run-A",
    sessionId: "A",
    planId: "plan-A",
    approval: { approvalId: "approval-A", planId: "plan-A" },
    candidate: { sha256: "candidate-sha", bytes: 12 },
    base: null,
    reverses: null,
    checks: { acceptance: true },
    ...overrides,
  };
}

function fixture() {
  const original = recovery();
  const draft = {
    sessionId: "A",
    plan: { planId: "plan-A" },
    ops: [{ opId: "old-op" }],
  };
  const approval = {
    approvalId: "approval-A",
    planId: "plan-A",
    state: "approved",
  };
  const emptyDraft = { sessionId: null, plan: null, ops: [] };
  let state = {
    activeSessionId: "A",
    recovery: original,
    applied: null,
    applyError: null,
    applyPhase: "failed",
    applyOutcomes: {
      A: { applied: null, error: { code: "timeout", message: "timed out" }, recovery: original },
    },
    receipts: {},
    receiptError: null,
    candidateVerdict: null,
    head: null,
    historySelected: null,
    candidates: { A: [] },
    draft,
    redoStack: [{ opId: "redo-old" }],
    approval,
    approvalPhase: "resolved",
  };
  const candidateRequests = [];
  const receiptRequests = [];
  const rt = {
    candidates(sessionId) {
      const request = deferred();
      candidateRequests.push({ ...request, sessionId });
      return request.promise;
    },
    readReceipt(sessionId, runId) {
      const request = deferred();
      receiptRequests.push({ ...request, sessionId, runId });
      return request.promise;
    },
    asRuntimeError(error) {
      return { code: "lookup_failed", message: String(error) };
    },
  };
  const context = vm.createContext({
    rt,
    EMPTY_DRAFT: emptyDraft,
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
  });
  vm.runInContext(`${implementation}\nglobalThis.invokeResolveRecovery = resolveRecovery;`, context);
  return {
    original,
    draft,
    approval,
    emptyDraft,
    candidateRequests,
    receiptRequests,
    resolve: context.invokeResolveRecovery,
    read: () => state,
    patch: (patch) => {
      state = { ...state, ...patch };
    },
    tick: () => new Promise((done) => setImmediate(done)),
  };
}

test("a plan-matched, fully bound receipt is the only path to applied", async () => {
  const f = fixture();
  const newerVerdict = { runId: "newer-run", report: { acceptance: false } };
  f.patch({
    head: "newer-run",
    historySelected: "newer-run",
    candidateVerdict: newerVerdict,
  });
  const pending = f.resolve();
  f.candidateRequests[0].resolve([
    { runId: "unrelated", planId: "plan-other" },
    { runId: "run-A", planId: "plan-A", receipt: "run-A/receipt.json" },
  ]);
  await f.tick();
  f.receiptRequests[0].resolve(receipt());
  await pending;

  assert.equal(f.read().applied.runId, "run-A");
  assert.equal(f.read().applied.planId, "plan-A");
  assert.equal(f.read().recovery.outcome, "applied");
  assert.equal(f.read().applyOutcomes.A.applied.runId, "run-A");
  assert.equal(f.read().applyOutcomes.A.recovery.outcome, "applied");
  assert.equal(f.read().receipts["run-A"].approval.approvalId, "approval-A");
  assert.equal(f.read().candidates.A[1].runId, "run-A");
  assert.equal(f.read().draft, f.emptyDraft);
  assert.equal(f.read().redoStack.length, 0);
  assert.equal(f.read().approval, null);
  assert.equal(f.read().approvalPhase, "idle");
  assert.equal(f.read().head, "newer-run");
  assert.equal(f.read().historySelected, "newer-run");
  assert.equal(f.read().candidateVerdict, newerVerdict);
});

test("recovery cannot release the global lock of an apply running in another document", async () => {
  const f = fixture();
  const running = f.resolve();
  f.candidateRequests[0].resolve([{ runId: "run-A", planId: "plan-A" }]);
  await f.tick();
  // B began applying, then the user returned to A while B was still running.
  f.patch({ applyPhase: "starting" });
  f.receiptRequests[0].resolve(receipt());
  await running;
  assert.equal(f.read().applyPhase, "starting");
  assert.equal(f.read().applyOutcomes.A.recovery.outcome, "applied");
});

test("a newer queue and chosen head survive proof of the older apply", async () => {
  const f = fixture();
  const newerDraft = { ops: [{ opId: "newer-op" }], plan: { planId: "newer-plan" } };
  const newerVerdict = { runId: "newer-run", report: { acceptance: false } };
  f.patch({
    draft: newerDraft,
    head: "newer-run",
    historySelected: "newer-run",
    candidateVerdict: newerVerdict,
  });
  const pending = f.resolve();
  f.candidateRequests[0].resolve([{ runId: "run-A", planId: "plan-A" }]);
  await f.tick();
  f.receiptRequests[0].resolve(receipt());
  await pending;

  assert.equal(f.read().applied.runId, "run-A");
  assert.equal(f.read().draft, newerDraft);
  assert.equal(f.read().approval, f.approval);
  assert.equal(f.read().redoStack.length, 1);
  assert.equal(f.read().head, "newer-run");
  assert.equal(f.read().historySelected, "newer-run");
  assert.equal(f.read().candidateVerdict, newerVerdict);
});

test("an arbitrary new candidate is not treated as the interrupted apply", async () => {
  const f = fixture();
  const pending = f.resolve();
  f.candidateRequests[0].resolve([{ runId: "new-run", planId: "different-plan" }]);
  await pending;
  assert.equal(f.receiptRequests.length, 0);
  assert.equal(f.read().recovery, f.original);
  assert.equal(f.read().applyOutcomes.A.recovery.outcome, "unknown");
});

test("an empty successful list remains unknown because publication may be in flight", async () => {
  const f = fixture();
  const pending = f.resolve();
  f.candidateRequests[0].resolve([]);
  await pending;
  assert.equal(f.read().recovery.outcome, "unknown");
  assert.equal(f.read().recovery.runId, null);
});

test("a refused candidate listing keeps recovery unknown and scopes its error", async () => {
  const f = fixture();
  const pending = f.resolve();
  f.candidateRequests[0].reject(new Error("list refused"));
  await pending;
  assert.equal(f.read().recovery.outcome, "unknown");
  assert.equal(f.read().applyOutcomes.A.recovery, f.original);
  assert.equal(f.read().applyOutcomes.A.error.code, "lookup_failed");
  assert.equal(f.read().applyError.code, "lookup_failed");
});

test("a malformed receipt remains unknown", async () => {
  const f = fixture();
  const pending = f.resolve();
  f.candidateRequests[0].resolve([{ runId: "run-A", planId: "plan-A" }]);
  await f.tick();
  f.receiptRequests[0].resolve(receipt({ sessionId: "B" }));
  await pending;
  assert.equal(f.read().recovery.outcome, "unknown");
  assert.equal(f.read().applyOutcomes.A.applied, null);
  assert.equal(f.read().applyOutcomes.A.error.code, "recovery_receipt_mismatch");
});

test("a refused receipt remains unknown", async () => {
  const f = fixture();
  const pending = f.resolve();
  f.candidateRequests[0].resolve([{ runId: "run-A", planId: "plan-A" }]);
  await f.tick();
  f.receiptRequests[0].reject(new Error("receipt refused"));
  await pending;
  assert.equal(f.read().recovery.outcome, "unknown");
  assert.equal(f.read().applyOutcomes.A.applied, null);
  assert.equal(f.read().applyOutcomes.A.error.code, "lookup_failed");
});

test("a late receipt cannot update another session or a newer recovery", async () => {
  const f = fixture();
  const pending = f.resolve();
  f.candidateRequests[0].resolve([{ runId: "run-A", planId: "plan-A" }]);
  await f.tick();

  const newer = recovery("plan-new", "approval-new");
  const bRecovery = recovery("plan-B", "approval-B");
  f.patch({
    activeSessionId: "B",
    recovery: bRecovery,
    applyOutcomes: {
      ...f.read().applyOutcomes,
      A: { applied: null, error: null, recovery: newer },
      B: { applied: null, error: null, recovery: bRecovery },
    },
  });
  f.receiptRequests[0].resolve(receipt());
  await pending;

  assert.equal(f.read().recovery, bRecovery);
  assert.equal(f.read().applyOutcomes.A.recovery, newer);
  assert.equal(f.read().applyOutcomes.A.applied, null);
  assert.equal(f.read().applyOutcomes.B.recovery, bRecovery);
});
