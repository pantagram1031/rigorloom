import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const resolveStart = actionsSource.indexOf("export async function resolveApprovalDecision(");
const resolveEnd = actionsSource.indexOf("\n// --- apply", resolveStart);
assert.ok(resolveStart >= 0 && resolveEnd > resolveStart, "approval action boundary changed");
const resolveImplementation = actionsSource.slice(resolveStart, resolveEnd).replace("export ", "");
const requestStart = actionsSource.indexOf("let approvalRequestGeneration");
const requestEnd = actionsSource.indexOf("/**\n * The human gate", requestStart);
assert.ok(requestStart >= 0 && requestEnd > requestStart, "approval request boundary changed");
const requestImplementation = actionsSource.slice(requestStart, requestEnd).replace("export ", "");
const applyStart = actionsSource.indexOf('const APPLY_TAG = "apply";', resolveEnd);
const applyEnd = actionsSource.indexOf("/** Cooperative cancel", applyStart);
assert.ok(applyStart >= 0 && applyEnd > applyStart, "apply action boundary changed");
const applyImplementation = actionsSource.slice(applyStart, applyEnd).replace("export ", "");

const helperSource = readFileSync(
  new URL("../src/workspace/reviewSummary.ts", import.meta.url),
  "utf8",
);
const helperStart = helperSource.indexOf("export function activeApprovalBinding(");
const helperEnd = helperSource.indexOf("/** Pending operations", helperStart);
assert.ok(helperStart >= 0 && helperEnd > helperStart, "approval helper boundary changed");
const helperImplementation = helperSource.slice(helperStart, helperEnd).replaceAll("export ", "");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function approval(id = "approval-A", state = "pending") {
  return {
    approvalId: id,
    planId: "plan-A",
    planHash: "hash-A",
    state,
  };
}

function initialState() {
  return {
    activeSessionId: "session-A",
    draft: {
      sessionId: "session-A",
      plan: { sessionId: "session-A", planId: "plan-A", planHash: "hash-A" },
      ops: [{ opId: "op-A" }],
    },
    approval: approval(),
    approvalPhase: "pending",
    approvalError: null,
  };
}

function fixture() {
  let state = initialState();
  const pending = deferred();
  const runtimeCalls = [];
  let applyCalls = 0;
  const context = vm.createContext({
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    rt: {
      resolveApproval(...args) {
        runtimeCalls.push(args);
        return pending.promise;
      },
      asRuntimeError(error) {
        return { code: "test-error", message: String(error) };
      },
    },
    applyApproved: async () => {
      applyCalls += 1;
    },
    showToast: () => {},
    draftStaleness: () => null,
    headCandidate: () => null,
  });
  vm.runInContext(
    stripTypeScriptTypes(`${helperImplementation}\n${resolveImplementation}\nglobalThis.decide = resolveApprovalDecision;`),
    context,
  );
  return {
    decide: (decision) => context.decide(decision),
    pending,
    read: () => state,
    patch: (patch) => {
      state = { ...state, ...patch };
    },
    runtimeCalls,
    applyCalls: () => applyCalls,
  };
}

test("resolve action refuses an approval whose plan hash does not match the draft", async () => {
  const f = fixture();
  f.patch({ approval: { ...approval(), planHash: "old-hash" } });
  await f.decide("approved");
  assert.equal(f.runtimeCalls.length, 0);
  assert.equal(f.applyCalls(), 0);
});

test("A to B session switch retains A's resolved approval but invokes no apply", async () => {
  const f = fixture();
  const deciding = f.decide("approved");
  assert.equal(f.runtimeCalls.length, 1);
  assert.equal(f.read().approvalPhase, "resolving");

  f.patch({ activeSessionId: "session-B" });
  f.pending.resolve(approval("approval-A", "approved"));
  await deciding;

  assert.equal(f.read().approval.state, "approved");
  assert.equal(f.read().approvalPhase, "resolved");
  assert.equal(f.applyCalls(), 0);
});

test("a newer exact-plan approval cannot be overwritten by an older resolution", async () => {
  const f = fixture();
  const deciding = f.decide("approved");
  f.patch({ approval: approval("approval-new", "pending"), approvalPhase: "pending" });
  f.pending.resolve(approval("approval-A", "approved"));
  await deciding;

  assert.equal(f.read().approval.approvalId, "approval-new");
  assert.equal(f.read().approval.state, "pending");
  assert.equal(f.applyCalls(), 0);
});

test("the unchanged exact binding publishes the decision and does not apply", async () => {
  const f = fixture();
  const deciding = f.decide("approved");
  f.pending.resolve(approval("approval-A", "approved"));
  await deciding;

  assert.equal(f.read().approval.state, "approved");
  assert.equal(f.read().approvalPhase, "resolved");
  assert.equal(f.applyCalls(), 0);
  assert.equal(f.runtimeCalls[0][2], "hash-A");
  assert.equal(f.runtimeCalls[0][3], "approved");
});

test("a valid fork or root-bound pending approval remains rejectable", async () => {
  const f = fixture();
  f.patch({ draft: { ...f.read().draft, baseRunId: "fork-base" } });
  const deciding = f.decide("rejected");
  assert.equal(f.runtimeCalls.length, 1);
  f.pending.resolve(approval("approval-A", "rejected"));
  await deciding;

  assert.equal(f.read().approval.state, "rejected");
  assert.equal(f.read().approvalPhase, "resolved");
  assert.equal(f.applyCalls(), 0);
});

async function applyRuntimeCalls(state) {
  let current = state;
  const calls = [];
  const context = vm.createContext({
    getState: () => current,
    setState: (patch) => {
      current = { ...current, ...patch };
    },
    rt: {
      async applyPlan(...args) {
        calls.push(args);
        throw new Error("stop after entry assertion");
      },
      asRuntimeError(error) {
        return { code: "test-stop", message: String(error) };
      },
    },
    EMPTY_DRAFT: { ops: [] },
    loadCandidates: async () => {},
    verifyReversal: async () => {},
    showToast: () => {},
    draftStaleness: () => null,
    headCandidate: () => null,
    selectInspectorTab: () => {},
    dismissFirstRunHint: () => {},
  });
  vm.runInContext(
    stripTypeScriptTypes(`${helperImplementation}\n${applyImplementation}\nglobalThis.applyForTest = applyApproved;`),
    context,
  );
  await context.applyForTest();
  return calls;
}

test("apply action enters the runtime only for an approved exact active binding", async () => {
  const valid = initialState();
  valid.approval = approval("approval-A", "approved");
  assert.equal((await applyRuntimeCalls(valid)).length, 1);

  const wrongHash = initialState();
  wrongHash.approval = { ...approval("approval-A", "approved"), planHash: "old-hash" };
  assert.equal((await applyRuntimeCalls(wrongHash)).length, 0);

  const otherSession = initialState();
  otherSession.approval = approval("approval-A", "approved");
  otherSession.activeSessionId = "session-B";
  assert.equal((await applyRuntimeCalls(otherSession)).length, 0);
});

function requestFixture() {
  let state = { ...initialState(), approval: null, approvalPhase: "idle" };
  const requests = [];
  const context = vm.createContext({
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    canRequestApproval: () => true,
    rt: {
      requestApproval(planId) {
        const pending = deferred();
        requests.push({ ...pending, planId });
        return pending.promise;
      },
      asRuntimeError(error) {
        return { code: "test-error", message: String(error) };
      },
    },
  });
  vm.runInContext(
    stripTypeScriptTypes(`${requestImplementation}\nglobalThis.requestForTest = requestApprovalForDraft;`),
    context,
  );
  return {
    request: () => context.requestForTest(),
    requests,
    read: () => state,
    patch: (patch) => {
      state = { ...state, ...patch };
    },
  };
}

test("request response remains attached to an unchanged A draft after switching to B", async () => {
  const f = requestFixture();
  const pending = f.request();
  f.patch({ activeSessionId: "session-B" });
  f.requests[0].resolve(approval("approval-A", "pending"));
  await pending;

  assert.equal(f.read().approval.approvalId, "approval-A");
  assert.equal(f.read().approvalPhase, "pending");
});

test("a late request cannot overwrite a rewritten draft or its newer approval", async () => {
  const f = requestFixture();
  const older = f.request();
  const newerDraft = {
    ...f.read().draft,
    plan: { sessionId: "session-A", planId: "plan-new", planHash: "hash-new" },
  };
  f.patch({ draft: newerDraft, approvalPhase: "idle" });
  const newer = f.request();

  f.requests[1].resolve({
    ...approval("approval-new", "pending"),
    planId: "plan-new",
    planHash: "hash-new",
  });
  await newer;
  f.requests[0].resolve(approval("approval-old", "pending"));
  await older;

  assert.equal(f.read().approval.approvalId, "approval-new");
  assert.equal(f.read().approval.planId, "plan-new");
});
