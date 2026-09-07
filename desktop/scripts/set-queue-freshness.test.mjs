import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
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
  });
  vm.runInContext(
    `${stripTypeScriptTypes(implementation)}\nglobalThis.invokeSetQueue = setQueue;`,
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
