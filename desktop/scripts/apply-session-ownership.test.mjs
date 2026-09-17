import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import vm from "node:vm";
import test from "node:test";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
function section(start, end) {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, `source boundary: ${start}`);
  return source.slice(a, b).replaceAll("export ", "");
}
const implementation = section('const APPLY_TAG = "apply";', "/** Cooperative cancel");
const candidateLoader = section("async function loadCandidates(", "/**\n * Make a session active");
const reversal = section("export async function verifyReversal(", "/** Show an older candidate");
const selection = section("let eventSelectionGeneration", "/** Read-only PIPELINE.md header");
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function fixture() {
  const pending = deferred();
  const calls = { apply: 0, lists: [], toast: 0, reversal: 0 };
  const draft = { sessionId: "A", plan: { planId: "pA", planHash: "hA" }, ops: ["op"] };
  let state = {
    activeSessionId: "A", draft, approval: { approvalId: "aA", state: "approved" },
    applyPhase: "idle", applyError: null, applied: null, recovery: null,
    applyOutcomes: {}, candidates: {}, head: "headA", redoStack: ["redo"],
  };
  let list = async () => [];
  const ctx = vm.createContext({
    getState: () => state,
    setState: (patch) => { state = { ...state, ...patch }; },
    activeApprovalBinding: (s) => s.activeSessionId === s.draft.sessionId ? { approvalId: s.approval?.approvalId } : null,
    approvalBindingStillExists: (s, binding) => s.approval?.approvalId === binding.approvalId,
    EMPTY_DRAFT: { ops: [] },
    rt: {
      applyPlan: () => { calls.apply++; return pending.promise; },
      candidates: (id) => { calls.lists.push(id); return list(); },
      asRuntimeError: (error) => error,
      savePrefs: async () => {},
    },
    stopDocumentEvents: () => {}, loadInspect: async () => {}, loadText: async () => {},
    loadPipelineStatus: async () => {},
    rememberRecent: () => {}, startEvents: async () => {},
    verifyReversal: async () => { calls.reversal++; },
    showToast: () => { calls.toast++; },
  });
  vm.runInContext(stripTypeScriptTypes(`${candidateLoader}\n${implementation}\n${selection}\nglobalThis.apply = applyApproved; globalThis.presentation = applyPresentation; globalThis.select = selectSession;`), ctx);
  const applied = { sessionId: "A", runId: "runA", candidate: { sha256: "shaA" }, checks: { acceptance: true } };
  return {
    apply: () => ctx.apply(), pending, calls, applied,
    read: () => state,
    patch: (patch) => { state = { ...state, ...patch }; },
    list: (fn) => { list = fn; },
    presentation: (id) => ctx.presentation(id),
    select: (id) => ctx.select(id),
  };
}

test("same-document apply records success and consumes only its owning queue", async () => {
  const f = fixture(); const run = f.apply();
  f.pending.resolve(f.applied); await run;
  assert.equal(f.read().head, "runA");
  assert.equal(f.read().draft.ops.length, 0);
  assert.equal(f.read().applyOutcomes.A.applied, f.applied);
  assert.equal(f.read().applyPhase, "ready");
});

test("A completion under B preserves A outcome without replacing B presentation", async () => {
  const f = fixture(); const run = f.apply();
  const bDraft = { sessionId: "B", ops: ["new"] };
  f.patch({ activeSessionId: "B", draft: bDraft, approval: null, head: "headB", historySelected: "historyB" });
  f.pending.resolve(f.applied); await run;
  assert.equal(f.read().draft, bDraft);
  assert.equal(f.read().head, "headB");
  assert.equal(f.read().historySelected, "historyB");
  assert.equal(f.read().applied, null);
  assert.equal(f.read().applyPhase, "idle");
  assert.equal(f.read().applyOutcomes.A.applied, f.applied);
  assert.equal(f.presentation("A").applied, f.applied);
  assert.deepEqual(f.calls.lists, ["A"]);
  assert.equal(f.calls.toast, 0);
});

test("a rewritten queue in A is not consumed or made the head of the old apply", async () => {
  const f = fixture(); const run = f.apply();
  const newer = { ...f.read().draft, ops: ["new"] };
  f.patch({ draft: newer, head: "newerHead" });
  f.pending.resolve(f.applied); await run;
  assert.equal(f.read().draft, newer);
  assert.equal(f.read().head, "newerHead");
  assert.equal(f.calls.toast, 0);
});

test("session selection restores terminal facts but preserves a global in-flight lock", async () => {
  const f = fixture(); const run = f.apply();
  await f.select("B");
  assert.equal(f.read().applyPhase, "starting");
  f.pending.resolve(f.applied); await run;
  assert.equal(f.read().applied, null);
  await f.select("A");
  assert.equal(f.read().applied, f.applied);
  assert.equal(f.read().applyPhase, "ready");
  assert.equal(f.read().applyError, null);
});

test("a timeout under B retains A's unknown outcome without tainting B", async () => {
  const f = fixture(); const run = f.apply();
  f.patch({ activeSessionId: "B", head: "headB" });
  f.pending.reject({ code: "timeout", message: "lost response" }); await run;
  assert.equal(f.read().applyError, null);
  assert.equal(f.read().recovery, null);
  assert.equal(f.read().applyOutcomes.A.recovery.outcome, "unknown");
  assert.equal(f.presentation("A").recovery.planId, "pA");
  await f.select("A");
  await f.apply();
  assert.equal(f.calls.apply, 1, "lost reply must not permit a duplicate apply");
});

test("apply is serial even when invoked twice before React rerenders", async () => {
  const f = fixture(); const first = f.apply(); await f.apply();
  assert.equal(f.calls.apply, 1);
  f.pending.resolve(f.applied); await first;
});

test("an ambiguous apply cannot be retried before its bound recovery is resolved", async () => {
  const f = fixture();
  f.patch({ recovery: { planId: "pA", approvalId: "aA", outcome: "unknown" } });
  await f.apply(); assert.equal(f.calls.apply, 0);
});

test("a recovered already-applied record also refuses duplicate execution", async () => {
  const f = fixture();
  f.patch({ applyOutcomes: { A: { recovery: { planId: "pA", approvalId: "aA", outcome: "applied" } } } });
  await f.apply(); assert.equal(f.calls.apply, 0);
});

test("candidate refresh failure does not relabel a successful apply", async () => {
  const f = fixture(); f.list(async () => { throw new Error("refresh down"); });
  const run = f.apply(); f.pending.resolve(f.applied); await run;
  assert.equal(f.read().applyPhase, "ready");
  assert.equal(f.read().applyError, null);
  assert.equal(f.read().applyOutcomes.A.applied, f.applied);
});

test("switch during candidate refresh skips reversal work and toast", async () => {
  const f = fixture(); const refresh = deferred(); f.list(() => refresh.promise);
  f.patch({ draft: { ...f.read().draft, reverses: "prior" } });
  const run = f.apply(); f.pending.resolve(f.applied);
  await new Promise((resolve) => setImmediate(resolve));
  f.patch({ activeSessionId: "B", head: "headB" }); refresh.resolve([]); await run;
  assert.equal(f.calls.reversal, 0); assert.equal(f.calls.toast, 0);
});

test("reversal completion after session switch cannot publish A proof under B", async () => {
  const pending = deferred();
  let state = { activeSessionId: "A", head: "runA", receipts: { prior: { planId: "priorPlan" } }, inverseProof: null };
  const ctx = vm.createContext({
    getState: () => state, setState: (patch) => { state = { ...state, ...patch }; },
    opAddress: () => ({ row: 0 }),
    rt: { getPlan: async () => ({ ops: [{}] }), compareCandidate: () => pending.promise, asRuntimeError: (e) => e },
  });
  vm.runInContext(stripTypeScriptTypes(`${reversal}\nglobalThis.verify = verifyReversal;`), ctx);
  const run = ctx.verify("runA", "prior"); await new Promise((resolve) => setImmediate(resolve));
  state = { ...state, activeSessionId: "B", head: "runB" };
  pending.resolve({ regionsEqual: true }); assert.equal(await run, false);
  assert.equal(state.inverseProof, null);
});
