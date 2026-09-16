import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";

const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const queueSource = readFileSync(new URL("../src/components/ReviewQueue.tsx", import.meta.url), "utf8");
const seatSource = readFileSync(new URL("../src/components/SeatEditor.tsx", import.meta.url), "utf8");

const resolveStart = actionsSource.indexOf("export async function resolveApprovalDecision(");
const resolveEnd = actionsSource.indexOf("\n// --- apply", resolveStart);
assert.ok(resolveStart >= 0 && resolveEnd > resolveStart, "approval action boundary changed");
const resolveImplementation = actionsSource.slice(resolveStart, resolveEnd).replace("export ", "");

const applyStart = actionsSource.indexOf('const APPLY_TAG = "apply";', resolveEnd);
const applyEnd = actionsSource.indexOf("/** Cooperative cancel", applyStart);
assert.ok(applyStart >= 0 && applyEnd > applyStart, "apply action boundary changed");
const applyImplementation = actionsSource.slice(applyStart, applyEnd).replace("export ", "");

const editStart = actionsSource.indexOf("export async function editOpValue(");
const editEnd = actionsSource.indexOf("/** Declare the charPr", editStart);
assert.ok(editStart >= 0 && editEnd > editStart, "editOpValue boundary changed");
const editImplementation = actionsSource.slice(editStart, editEnd).replace("export ", "");

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

function approveFixture() {
  let state = {
    isComposing: false,
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

test("mid-composition approve is skipped; post-composition approve records the displayed hash", async () => {
  const mid = approveFixture();
  mid.patch({ isComposing: true });
  await mid.decide("approved");
  assert.equal(mid.runtimeCalls.length, 0);
  assert.equal(mid.read().approval.state, "pending");
  assert.equal(mid.read().approvalPhase, "pending");
  assert.equal(mid.applyCalls(), 0);

  const after = approveFixture();
  after.patch({ isComposing: false });
  const deciding = after.decide("approved");
  assert.equal(after.runtimeCalls.length, 1);
  assert.equal(after.runtimeCalls[0][1], "plan-A");
  assert.equal(after.runtimeCalls[0][2], "hash-A");
  after.pending.resolve(approval("approval-A", "approved"));
  await deciding;
  assert.equal(after.read().approval.state, "approved");
  assert.equal(after.read().approvalPhase, "resolved");
  assert.equal(after.applyCalls(), 0);
});

test("reject and apply are inert while a composition is open", async () => {
  const reject = approveFixture();
  reject.patch({ isComposing: true });
  await reject.decide("rejected");
  assert.equal(reject.runtimeCalls.length, 0);
  assert.equal(reject.read().approval.state, "pending");

  let current = {
    isComposing: true,
    activeSessionId: "session-A",
    draft: {
      sessionId: "session-A",
      plan: { sessionId: "session-A", planId: "plan-A", planHash: "hash-A" },
      ops: [{ opId: "op-A" }],
    },
    approval: approval("approval-A", "approved"),
    applyPhase: "idle",
    applyOutcomes: {},
    recovery: null,
  };
  const applyCalls = [];
  const applyContext = vm.createContext({
    getState: () => current,
    setState: (patch) => {
      current = { ...current, ...patch };
    },
    rt: {
      async applyPlan(...args) {
        applyCalls.push(args);
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
  });
  vm.runInContext(
    stripTypeScriptTypes(`${helperImplementation}\n${applyImplementation}\nglobalThis.applyForTest = applyApproved;`),
    applyContext,
  );
  await applyContext.applyForTest();
  assert.equal(applyCalls.length, 0);

  current = { ...current, isComposing: false };
  await applyContext.applyForTest();
  assert.equal(applyCalls.length, 1);
});

test("queue-value commit is skipped mid-composition and proceeds after", async () => {
  let state = {
    isComposing: true,
    draft: { ops: [{ opId: "op-1", text: "가", origin: "user" }] },
  };
  const commits = [];
  const context = vm.createContext({
    getState: () => state,
    setQueue: async (ops) => {
      commits.push(ops);
    },
    didRewriteAgent: () => false,
  });
  vm.runInContext(
    stripTypeScriptTypes(`${editImplementation}\nglobalThis.edit = editOpValue;`),
    context,
  );
  await context.edit("op-1", "간");
  assert.equal(commits.length, 0);

  state = { ...state, isComposing: false };
  await context.edit("op-1", "간");
  assert.equal(commits.length, 1);
  assert.equal(commits[0][0].text, "간");
});

test("the queue and seat publish composition and freeze the gate", () => {
  assert.match(seatSource, /setState\(\{ isComposing: true \}\)/);
  assert.match(seatSource, /sawComposition: true, isComposing: false/);
  assert.match(queueSource, /setState\(\{ isComposing: true \}\)/);
  assert.match(queueSource, /if \(composing\.current \|\| native\.isComposing\) return/);
  assert.match(queueSource, /if \(getState\(\)\.isComposing\) return/);
  assert.match(queueSource, /disabled=\{!canDecide\}/);
  assert.match(queueSource, /disabled=\{!canApply\}/);
  assert.doesNotMatch(queueSource, /승인하고 적용/);
});
