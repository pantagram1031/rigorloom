import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const ownerStart = source.indexOf("interface DraftOwner {");
const ownerEnd = source.indexOf("/** Load a session's inspect", ownerStart);
assert.ok(ownerStart >= 0 && ownerEnd > ownerStart, "draft owner source boundary changed");
const ownerImplementation = source.slice(ownerStart, ownerEnd);
const fenceStart = source.indexOf("interface DraftFence {");
const fenceEnd = source.indexOf("/** The seat's current text", fenceStart);
assert.ok(fenceStart >= 0 && fenceEnd > fenceStart, "draft fence source boundary changed");
const fenceImplementation = source.slice(fenceStart, fenceEnd);
const start = source.indexOf("async function setQueue(");
const end = source.indexOf("/** Re-propose the queue", start);
assert.ok(start >= 0 && end > start, "setQueue source boundary changed");
const implementation = source.slice(start, end);

const EMPTY_DRAFT = {
  ops: [],
  plan: null,
  validation: null,
  sessionId: null,
  boundSha256: null,
  phase: "idle",
  error: null,
  rewrittenFromAgent: false,
  baseRunId: null,
  reverses: null,
};

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
  let state = {
    activeSessionId: "session-A",
    draft: { ...EMPTY_DRAFT },
    head: null,
    approval: null,
    approvalPhase: "idle",
    approvalError: null,
    applyError: null,
  };
  let generation = 0;
  const proposals = [];
  const validations = [];
  const rt = {
    proposePlan(sessionId, ops, options) {
      const pending = deferred();
      proposals.push({ ...pending, sessionId, ops, options });
      return pending.promise;
    },
    validatePlan(planId) {
      const pending = deferred();
      validations.push({ ...pending, planId });
      return pending.promise;
    },
    asRuntimeError(error) {
      return { code: "test_failure", message: String(error) };
    },
  };
  const context = vm.createContext({
    rt,
    EMPTY_DRAFT,
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    headCandidate: (current) =>
      current.head ? { runId: current.head } : null,
    bumpPlanGeneration: () => ++generation,
    currentPlanGeneration: () => generation,
  });
  vm.runInContext(
    `${stripTypeScriptTypes(ownerImplementation)}
${stripTypeScriptTypes(implementation)}
globalThis.invokeSetQueue = setQueue;`,
    context,
  );

  const op = (text) => ({
    opId: `op-${text}`,
    kind: "set_run",
    atPara: 0,
    run: 0,
    text,
    before: "",
    origin: "user",
  });
  return {
    read: () => state,
    patch: (patch) => {
      state = { ...state, ...patch };
    },
    clear: () => {
      state = { ...state, draft: EMPTY_DRAFT };
    },
    set: (text) => context.invokeSetQueue([op(text)]),
    proposals,
    validations,
    tick: () => new Promise((resolve) => setImmediate(resolve)),
    plan: (planId) => ({ planId, planHash: `hash-${planId}`, boundSha256: "source-A" }),
  };
}

test("a replacement queue hides the preceding validated plan immediately", async () => {
  const f = fixture();
  f.patch({
    draft: {
      ...EMPTY_DRAFT,
      plan: f.plan("old"),
      validation: { ok: true },
      boundSha256: "old-source",
    },
  });

  const pending = f.set("new");
  assert.equal(f.read().draft.plan, null);
  assert.equal(f.read().draft.validation, null);
  assert.equal(f.read().draft.boundSha256, null);
  f.proposals[0].reject(new Error("finish"));
  await pending;
});

test("an older completion cannot overwrite a newer queue", async () => {
  const f = fixture();
  const older = f.set("older");
  const newer = f.set("newer");

  f.proposals[1].resolve(f.plan("newer"));
  await f.tick();
  f.validations[0].resolve({ ok: true });
  await newer;

  f.proposals[0].resolve(f.plan("older"));
  await f.tick();
  if (f.validations[1]) f.validations[1].resolve({ ok: true });
  await older;

  assert.equal(f.read().draft.ops[0].text, "newer");
  assert.equal(f.read().draft.plan.planId, "newer");
});

test("clearing during validation cannot resurrect the queue", async () => {
  const f = fixture();
  const pending = f.set("withdrawn");
  f.proposals[0].resolve(f.plan("withdrawn"));
  await f.tick();
  f.clear();
  f.validations[0].resolve({ ok: true });
  await pending;
  assert.equal(f.read().draft.ops.length, 0);
  assert.equal(f.read().draft.plan, null);
});

test("a completion from a non-active session is ignored", async () => {
  const f = fixture();
  const pending = f.set("session-A-value");
  f.proposals[0].resolve(f.plan("session-A-plan"));
  await f.tick();
  f.patch({ activeSessionId: "session-B" });
  f.validations[0].resolve({ ok: true });
  await pending;
  assert.notEqual(f.read().draft.phase, "ready");
});

test("a completion from an older candidate head is ignored", async () => {
  const f = fixture();
  const pending = f.set("source-value");
  f.proposals[0].resolve(f.plan("source-plan"));
  await f.tick();
  f.patch({ head: "candidate-new" });
  f.validations[0].resolve({ ok: true });
  await pending;
  assert.notEqual(f.read().draft.phase, "ready");
});

test("an old error cannot replace a newer successful plan", async () => {
  const f = fixture();
  const older = f.set("older");
  const newer = f.set("newer");
  f.proposals[1].resolve(f.plan("newer"));
  await f.tick();
  f.validations[0].resolve({ ok: true });
  await newer;
  f.proposals[0].reject(new Error("late old failure"));
  await older;
  assert.equal(f.read().draft.phase, "ready");
  assert.equal(f.read().draft.plan.planId, "newer");
});

test("the owning request publishes its original fields", async () => {
  const f = fixture();
  f.patch({ head: "candidate-base" });
  const pending = f.set("한글");
  assert.equal(f.proposals[0].options.baseRunId, "candidate-base");
  f.proposals[0].resolve(f.plan("normal"));
  await f.tick();
  f.validations[0].resolve({ ok: true });
  await pending;
  assert.equal(f.read().draft.phase, "ready");
  assert.equal(f.read().draft.plan.planId, "normal");
  assert.equal(f.read().draft.ops[0].text, "한글");
});

function adoptionFixture() {
  let state = {
    activeSessionId: "session-A",
    draft: { ...EMPTY_DRAFT },
    head: null,
    inspects: {},
    texts: {},
    approval: null,
    approvalPhase: "idle",
    approvalError: null,
  };
  const plans = [];
  const validations = [];
  const approvals = [];
  const rt = {
    getPlan(planId) {
      const pending = deferred();
      plans.push({ ...pending, planId });
      return pending.promise;
    },
    validatePlan(planId) {
      const pending = deferred();
      validations.push({ ...pending, planId });
      return pending.promise;
    },
    getApproval(approvalId) {
      const pending = deferred();
      approvals.push({ ...pending, approvalId });
      return pending.promise;
    },
  };
  const adoptStart = source.indexOf("async function adoptAgentPlan(");
  const adoptEnd = source.indexOf("/** Ids are the shell's", adoptStart);
  assert.ok(adoptStart >= 0 && adoptEnd > adoptStart, "agent adoption source boundary changed");
  const adoptImplementation = source.slice(adoptStart, adoptEnd);
  const context = vm.createContext({
    rt,
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    headCandidate: (current) =>
      current.head ? { runId: current.head } : null,
    currentPlanGeneration: () => 1,
    seatText: () => "",
  });
  vm.runInContext(
    `${stripTypeScriptTypes(ownerImplementation)}
${stripTypeScriptTypes(fenceImplementation)}
${stripTypeScriptTypes(adoptImplementation)}
globalThis.captureOwner = captureDraftOwner;
globalThis.invokeAdopt = adoptAgentPlan;`,
    context,
  );
  const plan = (planId) => ({
    planId,
    planHash: `hash-${planId}`,
    boundSha256: "source-A",
    proposer: "test-agent",
    ops: [],
    base: null,
    reverses: null,
  });
  return {
    read: () => state,
    patch: (patch) => {
      state = { ...state, ...patch };
    },
    adopt: (approvalId = null) => {
      const owner = context.captureOwner();
      return context.invokeAdopt("session-A", "agent-plan", approvalId, owner);
    },
    plans,
    validations,
    approvals,
    plan,
    tick: () => new Promise((resolve) => setImmediate(resolve)),
  };
}

test("agent adoption publishes when its draft owner is unchanged", async () => {
  const f = adoptionFixture();
  const pending = f.adopt();
  f.plans[0].resolve(f.plan("agent-plan"));
  await f.tick();
  f.validations[0].resolve({ ok: true });
  const result = await pending;

  assert.equal(result.plan.planId, "agent-plan");
  assert.equal(f.read().draft.plan.planId, "agent-plan");
  assert.equal(f.read().draft.sessionId, "session-A");
});

test("agent adoption cannot replace a draft changed during validation", async () => {
  const f = adoptionFixture();
  const pending = f.adopt();
  f.plans[0].resolve(f.plan("agent-plan"));
  await f.tick();
  const userDraft = { ...EMPTY_DRAFT, ops: [{ opId: "new-user-op" }] };
  f.patch({ draft: userDraft });
  f.validations[0].resolve({ ok: true });

  assert.equal(await pending, null);
  assert.equal(f.read().draft, userDraft);
});

test("agent adoption cannot cross a session or candidate-head change", async () => {
  for (const patch of [{ activeSessionId: "session-B" }, { head: "new-head" }]) {
    const f = adoptionFixture();
    const pending = f.adopt();
    f.patch(patch);
    f.plans[0].resolve(f.plan("agent-plan"));
    await f.tick();
    f.validations[0].resolve({ ok: true });

    assert.equal(await pending, null);
    assert.equal(f.read().draft.plan, null);
  }
});

test("agent adoption rechecks ownership after approval lookup", async () => {
  const f = adoptionFixture();
  const pending = f.adopt("approval-1");
  f.plans[0].resolve(f.plan("agent-plan"));
  await f.tick();
  f.validations[0].resolve({ ok: true });
  await f.tick();
  const userDraft = { ...EMPTY_DRAFT, ops: [{ opId: "new-user-op" }] };
  f.patch({ draft: userDraft });
  f.approvals[0].resolve({ approvalId: "approval-1", state: "pending" });

  assert.equal(await pending, null);
  assert.equal(f.read().draft, userDraft);
  assert.equal(f.read().approval, null);
});

function approvalFixture() {
  const plan = { planId: "plan-A", planHash: "hash-A" };
  const approval = { approvalId: "approval-A", planId: "plan-A", state: "pending" };
  let state = {
    activeSessionId: "session-A",
    draft: { ...EMPTY_DRAFT, plan },
    head: null,
    approval: null,
    approvalPhase: "idle",
    approvalError: null,
  };
  const requests = [];
  const resolutions = [];
  let applies = 0;
  const rt = {
    requestApproval(planId) {
      const pending = deferred();
      requests.push({ ...pending, planId });
      return pending.promise;
    },
    resolveApproval(approvalId, planId, planHash, decision, approver) {
      const pending = deferred();
      resolutions.push({
        ...pending,
        approvalId,
        planId,
        planHash,
        decision,
        approver,
      });
      return pending.promise;
    },
    asRuntimeError(error) {
      return { code: "test_failure", message: String(error) };
    },
  };
  const approvalStart = source.indexOf("export async function requestApprovalForDraft");
  const approvalEnd = source.indexOf("// --- apply", approvalStart);
  assert.ok(
    approvalStart >= 0 && approvalEnd > approvalStart,
    "approval action source boundary changed",
  );
  const approvalImplementation = source
    .slice(approvalStart, approvalEnd)
    .replace(/^export /gm, "");
  const context = vm.createContext({
    rt,
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    headCandidate: (current) =>
      current.head ? { runId: current.head } : null,
    currentPlanGeneration: () => 1,
    canRequestApproval: () => true,
    applyApproved: async () => {
      applies += 1;
    },
    showToast: () => {},
  });
  vm.runInContext(
    `${stripTypeScriptTypes(ownerImplementation)}
${stripTypeScriptTypes(fenceImplementation)}
${stripTypeScriptTypes(approvalImplementation)}
globalThis.requestDraftApproval = requestApprovalForDraft;
globalThis.resolveDraftApproval = resolveApprovalDecision;`,
    context,
  );
  return {
    read: () => state,
    patch: (patch) => {
      state = { ...state, ...patch };
    },
    request: () => context.requestDraftApproval(),
    resolve: (decision = "approved") =>
      context.resolveDraftApproval(decision),
    requests,
    resolutions,
    plan,
    approval,
    applies: () => applies,
  };
}

test("late approval request cannot attach to a replacement draft", async () => {
  const f = approvalFixture();
  const pending = f.request();
  const replacement = { ...EMPTY_DRAFT, plan: { planId: "plan-B" } };
  f.patch({ draft: replacement, approval: null, approvalPhase: "idle" });
  f.requests[0].resolve(f.approval);

  await pending;
  assert.equal(f.read().draft, replacement);
  assert.equal(f.read().approval, null);
  assert.equal(f.read().approvalPhase, "idle");
});

test("approval request publishes while its draft owner is unchanged", async () => {
  const f = approvalFixture();
  const pending = f.request();
  f.requests[0].resolve(f.approval);

  await pending;
  assert.equal(f.read().approval, f.approval);
  assert.equal(f.read().approvalPhase, "pending");
});

test("late approval resolution cannot reattach to a replacement draft", async () => {
  const f = approvalFixture();
  f.patch({ approval: f.approval });
  const pending = f.resolve();
  const replacement = { ...EMPTY_DRAFT, plan: { planId: "plan-B" } };
  f.patch({ draft: replacement, approval: null, approvalPhase: "idle" });
  f.resolutions[0].resolve({ ...f.approval, state: "approved" });

  await pending;
  assert.equal(f.read().draft, replacement);
  assert.equal(f.read().approval, null);
  assert.equal(f.read().approvalPhase, "idle");
  assert.equal(f.applies(), 0);
});

test("approval resolution applies while its draft owner is unchanged", async () => {
  const f = approvalFixture();
  f.patch({ approval: f.approval });
  const pending = f.resolve();
  f.resolutions[0].resolve({ ...f.approval, state: "approved" });

  await pending;
  assert.equal(f.read().approval.state, "approved");
  assert.equal(f.read().approvalPhase, "resolved");
  assert.equal(f.applies(), 1);
});
