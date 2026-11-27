import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const ownerStart = source.indexOf("interface DraftOwner {");
const ownerEnd = source.indexOf("/** Load a session's inspect", ownerStart);
assert.ok(ownerStart >= 0 && ownerEnd > ownerStart, "draft owner source boundary changed");
const ownerImplementation = source.slice(ownerStart, ownerEnd);

const setQueueStart = source.indexOf("async function setQueue(");
const setQueueEnd = source.indexOf("/** Re-propose the queue", setQueueStart);
assert.ok(setQueueStart >= 0 && setQueueEnd > setQueueStart, "setQueue source boundary changed");
const setQueueImplementation = source.slice(setQueueStart, setQueueEnd);

const revalidateStart = source.indexOf("export async function revalidateActiveDraft(");
const revalidateEnd = source.indexOf("export async function verifyAndApplyApproved", revalidateStart);
assert.ok(revalidateStart >= 0 && revalidateEnd > revalidateStart, "revalidateActiveDraft source boundary changed");
const revalidateImplementation = source
  .slice(revalidateStart, revalidateEnd)
  .replace(/^export /gm, "");

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

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

function fixture({ manualValidate = false } = {}) {
  let state = {
    activeSessionId: "session-A",
    draft: { ...EMPTY_DRAFT },
    head: null,
    approval: null,
    approvalPhase: "idle",
    approvalError: null,
    reapprovalPrompt: null,
    applyPhase: "idle",
    applyError: null,
  };
  let generation = 0;
  let now = 0;
  let nextTimerId = 1;
  let planCounter = 0;
  const timers = new Map();
  const proposals = [];
  const validations = [];
  const persisted = [];
  const draftHistory = [];

  const rt = {
    async proposePlan(sessionId, ops, options) {
      const planId = `plan-${++planCounter}`;
      const plan = {
        planId,
        planHash: `hash-${planId}`,
        boundSha256: "source-A",
        sessionId,
      };
      proposals.push({ planId, sessionId, ops, options, atMs: now });
      return plan;
    },
    validatePlan(planId) {
      const pending = deferred();
      const entry = { ...pending, planId, atMs: now };
      validations.push(entry);
      if (!manualValidate) {
        pending.resolve({
          ok: true,
          stale: false,
          hard: [],
          boundSha256: "source-A",
          currentSha256: "source-A",
          planId,
        });
      }
      return pending.promise;
    },
    asRuntimeError(error) {
      return { code: "test_failure", message: String(error) };
    },
  };

  function fakeSetTimeout(fn, delay = 0, ...args) {
    const id = nextTimerId++;
    const numericDelay = Math.max(0, Number(delay) || 0);
    timers.set(id, {
      id,
      at: now + numericDelay,
      delay: numericDelay,
      run: () => fn(...args),
    });
    return id;
  }

  function fakeClearTimeout(id) {
    timers.delete(id);
  }

  async function advanceTime(ms) {
    const target = now + Math.max(0, ms);
    while (true) {
      let earliest = null;
      for (const entry of timers.values()) {
        if (
          entry.at <= target &&
          (!earliest || entry.at < earliest.at || (entry.at === earliest.at && entry.id < earliest.id))
        ) {
          earliest = entry;
        }
      }
      if (!earliest) break;
      timers.delete(earliest.id);
      now = earliest.at;
      earliest.run();
      await tick();
    }
    now = target;
    await tick();
  }

  const context = vm.createContext({
    rt,
    EMPTY_DRAFT,
    REAPPROVAL_PROMPT: "stale",
    draftStaleness: () => null,
    showToast: () => {},
    persistDraft: (sessionId, draft) => {
      persisted.push({ sessionId, draft });
    },
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
      if ("draft" in patch && state.draft) {
        draftHistory.push({
          phase: state.draft.phase,
          planId: state.draft.plan?.planId ?? null,
          hasPlan: state.draft.plan !== null,
          hasValidation: state.draft.validation !== null,
          validation: state.draft.validation,
        });
      }
    },
    headCandidate: (current) => (current.head ? { runId: current.head } : null),
    bumpPlanGeneration: () => ++generation,
    currentPlanGeneration: () => generation,
    setTimeout: fakeSetTimeout,
    clearTimeout: fakeClearTimeout,
  });

  vm.runInContext(
    `${stripTypeScriptTypes(ownerImplementation)}
${stripTypeScriptTypes(setQueueImplementation)}
${stripTypeScriptTypes(revalidateImplementation)}
globalThis.invokeSetQueue = setQueue;
globalThis.invokeRevalidate = revalidateActiveDraft;
globalThis.settleMs = typeof DRAFT_VALIDATE_SETTLE_MS === "number" ? DRAFT_VALIDATE_SETTLE_MS : 700;`,
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
    set: (text) => context.invokeSetQueue([op(text)]),
    revalidate: () => context.invokeRevalidate(),
    settleMs: context.settleMs,
    proposals,
    validations,
    persisted,
    draftHistory,
    timers,
    advanceTime,
    tick,
  };
}

test("three setQueue calls within the settle window give 3 proposes and 1 validate, on the last plan", async () => {
  const f = fixture();

  await f.set("first");
  await f.advanceTime(200);
  await f.set("second");
  await f.advanceTime(200);
  await f.set("third");
  await f.tick();

  assert.equal(f.proposals.length, 3);
  assert.equal(f.validations.length, 0);
  assert.equal(f.read().draft.plan?.planId, "plan-3");
  assert.equal(f.read().draft.validation, null);

  await f.advanceTime(f.settleMs);

  assert.equal(f.proposals.length, 3);
  assert.equal(f.validations.length, 1);
  assert.equal(f.validations[0].planId, "plan-3");
  assert.equal(f.read().draft.phase, "ready");
  assert.equal(f.read().draft.plan?.planId, "plan-3");
  assert.equal(f.read().draft.validation?.ok, true);
});

test("a single setQueue validates once after the delay", async () => {
  const f = fixture();

  await f.set("single");
  await f.tick();

  assert.equal(f.proposals.length, 1);
  assert.equal(f.validations.length, 0);
  assert.equal(f.read().draft.plan?.planId, "plan-1");
  assert.equal(f.read().draft.validation, null);
  assert.equal(f.read().draft.phase, "starting");

  await f.advanceTime(f.settleMs - 1);
  assert.equal(f.validations.length, 0);
  assert.equal(f.read().draft.phase, "starting");

  await f.advanceTime(1);
  assert.equal(f.validations.length, 1);
  assert.equal(f.validations[0].planId, "plan-1");
  assert.equal(f.read().draft.phase, "ready");
  assert.equal(f.read().draft.validation?.ok, true);

  await f.advanceTime(f.settleMs * 2);
  assert.equal(f.validations.length, 1);
});

test("a setQueue started while a validate is in flight drops that answer", async () => {
  const f = fixture({ manualValidate: true });

  void f.set("first");
  await f.tick();
  await f.advanceTime(f.settleMs);
  assert.equal(f.validations.length, 1);
  assert.equal(f.validations[0].planId, "plan-1");

  // Start a newer setQueue while plan-1's validatePlan is still in flight.
  void f.set("second");
  await f.tick();

  // Resolve the in-flight validatePlan for plan-1; it must be dropped.
  f.validations[0].resolve({
    ok: true,
    stale: false,
    hard: [],
    boundSha256: "source-A",
    planId: "plan-1",
  });
  await f.tick();

  assert.equal(f.read().draft.plan?.planId, "plan-2");
  assert.equal(f.read().draft.validation, null);
  assert.equal(f.read().draft.phase, "starting");
  assert.equal(f.validations.length, 1);

  await f.advanceTime(f.settleMs);
  assert.equal(f.validations.length, 2);
  assert.equal(f.validations[1].planId, "plan-2");

  f.validations[1].resolve({
    ok: true,
    stale: false,
    hard: [],
    boundSha256: "source-A",
    planId: "plan-2",
  });
  await f.tick();

  assert.equal(f.read().draft.phase, "ready");
  assert.equal(f.read().draft.plan?.planId, "plan-2");
  assert.equal(f.read().draft.validation?.planId, "plan-2");
});

test("the draft never shows phase ready with validation null and revalidate flushes pending validation", async () => {
  const f = fixture();

  await f.set("flush-target");
  await f.tick();

  assert.equal(f.read().draft.plan?.planId, "plan-1");
  assert.equal(f.read().draft.validation, null);
  assert.equal(f.read().draft.phase, "starting");
  assert.equal(f.validations.length, 0);

  // Approval dialog / gate triggers revalidateActiveDraft before the settle timer fires.
  const revResult = await f.revalidate();
  assert.equal(revResult.ok, true);
  assert.equal(revResult.stale, false);
  assert.equal(f.validations.length, 1);
  assert.equal(f.validations[0].planId, "plan-1");
  assert.equal(f.read().draft.phase, "ready");
  assert.equal(f.read().draft.validation?.ok, true);

  // The cancelled settle timer must not validate a second time when the window elapses.
  await f.advanceTime(f.settleMs * 2);
  assert.equal(f.validations.length, 1);

  for (const snap of f.draftHistory) {
    assert.ok(
      !(snap.phase === "ready" && !snap.hasValidation),
      `draft showed phase="ready" with validation=null: ${JSON.stringify(snap)}`,
    );
  }
});
