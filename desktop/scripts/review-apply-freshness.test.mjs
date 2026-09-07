import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");

function between(startText, endText) {
  const start = source.indexOf(startText);
  const end = source.indexOf(endText, start);
  assert.ok(start >= 0 && end > start, `source boundary changed: ${startText}`);
  return source.slice(start, end);
}

const implementation = [
  between("interface DraftFence", "/** The seat's current text"),
  between("export async function requestApprovalForDraft", "// --- apply"),
  between('const APPLY_TAG = "apply"', "/** Cooperative cancel"),
  between("async function adoptAgentPlan(", "/** Ids are the shell's"),
].join("\n");

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
  const oldPlan = { planId: "plan-old", planHash: "hash-old", boundSha256: "source-old" };
  const oldDraft = {
    ops: [{ opId: "old-op", text: "old" }],
    plan: oldPlan,
    validation: { ok: true },
    sessionId: "session-A",
    boundSha256: "source-old",
    phase: "ready",
    error: null,
    rewrittenFromAgent: false,
    baseRunId: null,
    reverses: null,
  };
  const oldApproval = {
    approvalId: "approval-old",
    planId: oldPlan.planId,
    planHash: oldPlan.planHash,
    state: "pending",
  };
  let state = {
    activeSessionId: "session-A",
    draft: oldDraft,
    head: null,
    approval: oldApproval,
    approvalPhase: "idle",
    approvalError: null,
    applyPhase: "idle",
    applyError: null,
    recovery: null,
    redoStack: [],
    inspects: {},
    texts: {},
  };
  let generation = 1;
  let candidateRefreshes = 0;
  const requests = [];
  const decisions = [];
  const applies = [];
  const plans = [];
  const validations = [];
  const approvals = [];

  const rt = {
    requestApproval() {
      const pending = deferred();
      requests.push(pending);
      return pending.promise;
    },
    resolveApproval() {
      const pending = deferred();
      decisions.push(pending);
      return pending.promise;
    },
    applyPlan() {
      const pending = deferred();
      applies.push(pending);
      return pending.promise;
    },
    getPlan() {
      const pending = deferred();
      plans.push(pending);
      return pending.promise;
    },
    validatePlan() {
      const pending = deferred();
      validations.push(pending);
      return pending.promise;
    },
    getApproval() {
      const pending = deferred();
      approvals.push(pending);
      return pending.promise;
    },
    asRuntimeError(error) {
      return { code: "test_rejection", message: String(error) };
    },
  };

  const context = vm.createContext({
    rt,
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    currentPlanGeneration: () => generation,
    headCandidate: (current) => (current.head ? { runId: current.head } : null),
    canRequestApproval: () => true,
    loadCandidates: async () => {
      candidateRefreshes += 1;
    },
    verifyReversal: async () => true,
    showToast: () => {},
    seatText: () => "",
  });
  vm.runInContext(
    `${stripTypeScriptTypes(implementation)}
globalThis.invokeRequest = requestApprovalForDraft;
globalThis.invokeResolve = resolveApprovalDecision;
globalThis.invokeApply = applyApproved;
globalThis.invokeAdopt = adoptAgentPlan;`,
    context,
  );

  return {
    read: () => state,
    replace(text = "newer") {
      generation += 1;
      state = {
        ...state,
        draft: {
          ...oldDraft,
          ops: [{ opId: `op-${text}`, text }],
          plan: { planId: `plan-${text}`, planHash: `hash-${text}`, boundSha256: "source-new" },
          validation: { ok: true },
          boundSha256: "source-new",
        },
        approval: null,
        approvalPhase: "idle",
        applyPhase: "idle",
        applyError: null,
      };
    },
    request: () => context.invokeRequest(),
    resolve: (decision) => context.invokeResolve(decision),
    apply: () => context.invokeApply(),
    adopt: () => context.invokeAdopt("session-A", "agent-plan", "agent-approval"),
    requests,
    decisions,
    applies,
    plans,
    validations,
    approvals,
    tick: () => new Promise((resolve) => setImmediate(resolve)),
    candidateRefreshes: () => candidateRefreshes,
  };
}

test("late approval request cannot bind a replacement draft", async () => {
  const f = fixture();
  const pending = f.request();
  f.replace();
  f.requests[0].resolve({ approvalId: "stale", state: "pending" });
  await pending;
  assert.equal(f.read().approval, null);
  assert.equal(f.read().draft.plan.planId, "plan-newer");
});

test("late approval decision cannot publish over a replacement draft", async () => {
  const f = fixture();
  const pending = f.resolve("rejected");
  f.replace();
  f.decisions[0].reject(new Error("late decision rejection"));
  await pending;
  assert.equal(f.read().approvalError, null);
  assert.equal(f.read().draft.plan.planId, "plan-newer");
});

test("late apply rejection cannot mark a replacement draft failed", async () => {
  const f = fixture();
  const pending = f.apply();
  f.replace();
  f.applies[0].reject(new Error("old apply rejected"));
  await pending;
  assert.equal(f.read().applyPhase, "idle");
  assert.equal(f.read().applyError, null);
  assert.equal(f.read().draft.plan.planId, "plan-newer");
});

test("late apply success cannot clear a replacement draft", async () => {
  const f = fixture();
  const pending = f.apply();
  f.replace();
  f.applies[0].resolve({
    runId: "run-old",
    candidate: { sha256: "abcdef0123456789" },
    checks: {},
  });
  await pending;
  assert.equal(f.read().draft.plan.planId, "plan-newer");
  assert.equal(f.candidateRefreshes(), 1);
});

test("agent validation cannot replace typing that won during its await", async () => {
  const f = fixture();
  const pending = f.adopt();
  f.plans[0].resolve({
    planId: "agent-plan",
    planHash: "agent-hash",
    boundSha256: "agent-source",
    ops: [],
    proposer: "agent",
    base: null,
    reverses: null,
  });
  await f.tick();
  f.replace();
  f.validations[0].resolve({ ok: true });
  assert.equal(await pending, null);
  assert.equal(f.read().draft.plan.planId, "plan-newer");
  assert.equal(f.approvals.length, 0);
});

test("agent approval lookup cannot replace typing that won during its await", async () => {
  const f = fixture();
  const pending = f.adopt();
  f.plans[0].resolve({
    planId: "agent-plan",
    planHash: "agent-hash",
    boundSha256: "agent-source",
    ops: [],
    proposer: "agent",
    base: null,
    reverses: null,
  });
  await f.tick();
  f.validations[0].resolve({ ok: true });
  await f.tick();
  f.replace();
  f.approvals[0].resolve({ approvalId: "agent-approval", state: "pending" });
  assert.equal(await pending, null);
  assert.equal(f.read().draft.plan.planId, "plan-newer");
  assert.equal(f.read().approval, null);
});
