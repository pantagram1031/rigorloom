// Regression tests for the UX11 trust fixes, run against the real action code.
// Each test slices one function out of src/actions.ts and runs it in a VM with
// the collaborators stubbed, the same way the other action tests here do.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";

import { errorCodeMessage, opKindLabel, t } from "../src/i18n/vocabulary.ts";
import {
  autoCharPrFor,
  foreignOps,
  planOpsPayload,
  swapSessionDrafts,
  undoBlockReason,
  withoutSignatures,
} from "../src/workspace/trust.ts";
import { opSignature } from "../src/store.ts";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");

function section(start, end) {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, `source boundary: ${start}`);
  return stripTypeScriptTypes(source.slice(a, b).replaceAll("export ", ""));
}

const EMPTY_DRAFT = {
  ops: [], plan: null, validation: null, sessionId: null, boundSha256: null,
  phase: "idle", error: null, rewrittenFromAgent: false, baseRunId: null, reverses: null,
};

function store(initial) {
  let state = initial;
  return {
    getState: () => state,
    setState: (patch) => { state = { ...state, ...patch }; },
    read: () => state,
  };
}

// --- fix 3: drafts are keyed by document ---------------------------------------------

test("switching documents parks the queue; the other document starts clean and the first gets it back", async () => {
  const draftA = { ...EMPTY_DRAFT, sessionId: "A", ops: [{ opId: "o1", kind: "fill_cell", text: "AGENT-HOST-0001" }], phase: "ready", plan: { planId: "pA" } };
  const s = store({
    activeSessionId: "A", draft: draftA, approval: { approvalId: "ap", state: "pending" },
    approvalPhase: "pending", redoStack: [], parkedDrafts: {}, corpusFiles: ["x"],
    editIntentGeneration: 0, applyPhase: "idle", applyOutcomes: {},
  });
  const headLoads = [];
  const ctx = vm.createContext({
    ...s, EMPTY_DRAFT, swapSessionDrafts,
    stopDocumentEvents: () => {},
    applyPresentation: () => ({}),
    rt: { savePrefs: async () => {} },
    loadCorpusFiles: async () => {}, loadInspect: async () => {}, loadText: async () => {},
    loadCandidates: async () => {}, rememberRecent: () => {}, startEvents: async () => {},
    headCandidate: () => ({ runId: "run-1" }),
    loadHeadTexts: async (sessionId, runId) => { headLoads.push([sessionId, runId]); },
    restoreSavedDraft: async () => {},
  });
  vm.runInContext(
    `${section("let eventSelectionGeneration", "export async function refreshSessions(")}\nglobalThis.select = selectSession;`,
    ctx,
  );

  await ctx.select("B");
  assert.equal(s.read().draft.ops.length, 0, "B never sees A's pending change");
  assert.equal(s.read().approval, null);
  assert.equal(s.read().parkedDrafts.A.draft, draftA);
  assert.deepEqual(headLoads, [["B", "run-1"]], "the head 수정본 is read for the page");

  await ctx.select("A");
  assert.equal(s.read().draft, draftA, "A's queue comes back intact");
  assert.equal(s.read().approval.approvalId, "ap");
  assert.equal(s.read().parkedDrafts.A, undefined);
});

test("re-propose refuses ops made for another document and rebases on the head otherwise", async () => {
  const calls = [];
  const s = store({
    activeSessionId: "B", language: "ko",
    draft: { ...EMPTY_DRAFT, sessionId: "A", ops: [{ opId: "o1", kind: "fill_cell", text: "x" }] },
  });
  const ctx = vm.createContext({
    ...s, foreignOps, errorCodeMessage, t,
    headCandidate: () => ({ runId: "run-head" }),
    setQueue: async (ops, options) => { calls.push({ ops, options }); },
  });
  vm.runInContext(
    `${section("export async function reproposeDraft(", "// --- undo, tier two")}\nglobalThis.repropose = reproposeDraft;`,
    ctx,
  );
  await ctx.repropose();
  assert.equal(calls.length, 0, "nothing was proposed onto B");
  assert.equal(s.read().draft.error.code, "foreign_session_ops");
  assert.equal(s.read().draft.phase, "failed");

  s.setState({ activeSessionId: "A" });
  await ctx.repropose();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.baseRunId, "run-head", "a re-propose stands on the head");
});

// --- fix 6 / gpt 5: the return reason is the reason -----------------------------------------

test("돌려보내기 stores the reason as the reason, keeps the approver, and empties the queue", async () => {
  const resolves = [];
  const dismissed = [];
  let cleared = 0;
  const agentOp = { opId: "m1", kind: "fill_cell", table: 0, row: 1, col: 4, text: "AGENT-HOST-0001", origin: "agent" };
  const draft = { ...EMPTY_DRAFT, sessionId: "S", ops: [agentOp], plan: { planId: "p1" } };
  const s = store({
    activeSessionId: "S", language: "ko", draft,
    approval: { approvalId: "a1", planId: "p1", state: "pending" },
    returnedOps: {},
  });
  const ctx = vm.createContext({
    ...s, opSignature, withoutSignatures, t,
    markExternalPlanDismissed: (sessionId, planId) => dismissed.push([sessionId, planId]),
    resolveApprovalDecision: async (...args) => { resolves.push(args); },
    showToast: () => {},
    clearQueue: async () => { cleared += 1; s.setState({ draft: EMPTY_DRAFT, approval: null }); },
  });
  vm.runInContext(
    `${section("function markReturned(", "// --- recents")}\nglobalThis.returnDraft = returnDraft;`,
    ctx,
  );
  await ctx.returnDraft("수신을 기획조정실로 고쳐 주세요");
  assert.deepEqual(resolves, [["rejected", "host-operator", "수신을 기획조정실로 고쳐 주세요"]]);
  assert.equal(cleared, 1, "the returned proposal leaves the queue");
  assert.deepEqual(JSON.parse(JSON.stringify(s.read().returnedOps.S)), ["c:0:1:4#*~fill=AGENT-HOST-0001"]);
  assert.deepEqual(dismissed, [["S", "p1"]]);
});

test("the decision call carries the reason to the runtime as its own field", async () => {
  const calls = [];
  const draft = { sessionId: "S" };
  const s = store({ activeSessionId: "S", language: "ko", draft, head: null, approval: { approvalId: "a1", state: "pending" }, approvalPhase: "pending" });
  const ctx = vm.createContext({
    ...s, t,
    activeApprovalBinding: () => ({ approvalId: "a1", planId: "p1", planHash: "h1" }),
    approvalBindingStillExists: () => true,
    approvalBindingIsCurrent: () => true,
    showToast: () => {},
    applyApproved: async () => {},
    rt: {
      resolveApproval: async (...args) => { calls.push(args); return { approvalId: "a1", state: "rejected" }; },
      asRuntimeError: (e) => e,
    },
  });
  vm.runInContext(
    `${section("export async function resolveApprovalDecision(", "\n// --- apply")}\nglobalThis.decide = resolveApprovalDecision;`,
    ctx,
  );
  await ctx.decide("rejected", "host-operator", "날짜가 틀렸습니다");
  assert.deepEqual(calls, [["a1", "p1", "h1", "rejected", "host-operator", "날짜가 틀렸습니다"]]);
});

// --- fix 8: the body character shape is applied for the person --------------------------------

test("typing into a superscript blank declares the suggested body shape and says so", async () => {
  const queued = [];
  const s = store({
    activeSessionId: "S",
    inspects: { S: {} },
    texts: { S: [] },
    sawComposition: false,
    draft: { ops: [] },
    inlineEdit: { kind: "cell", table: 0, row: 2, col: 0, before: "", opId: null },
  });
  const ctx = vm.createContext({
    ...s, autoCharPrFor,
    queuedRunOpAt: () => null,
    runTextAfterEdit: (_e, v) => v,
    undoQueuedOp: async () => {},
    didRewriteAgent: () => false,
    seatAt: () => ({ scriptAnomaly: true, charPrSuggested: "12" }),
    activeHeadTexts: () => null,
    seatText: () => "",
    clearReturned: () => {},
    setQueue: async (ops) => { queued.push(ops); },
  });
  vm.runInContext(
    `${section("export async function commitEdit(", "/** Change a queued op's value")}\nglobalThis.commit = commitEdit;`,
    ctx,
  );
  await ctx.commit("홍");
  const op = queued[0][0];
  assert.equal(op.kind, "fill_cell");
  assert.equal(op.charPr, "12");
  assert.equal(op.autoCharPr, true);
  assert.equal(op.sessionId, "S");
  assert.equal(op.overwrite, undefined);
});

test("re-typing a blank the head already filled writes over it on purpose", async () => {
  const queued = [];
  const s = store({
    activeSessionId: "S",
    inspects: { S: {} },
    texts: { S: [] },
    sawComposition: false,
    draft: { ops: [] },
    inlineEdit: { kind: "cell", table: 0, row: 5, col: 1, before: "기획조정실", opId: null },
  });
  const ctx = vm.createContext({
    ...s, autoCharPrFor,
    queuedRunOpAt: () => null,
    runTextAfterEdit: (_e, v) => v,
    undoQueuedOp: async () => {},
    didRewriteAgent: () => false,
    seatAt: () => ({}),
    activeHeadTexts: () => [{ table: 0, addr: { row: 5, col: 1 }, text: "기획조정실" }],
    seatText: () => "",
    clearReturned: () => {},
    setQueue: async (ops) => { queued.push(ops); },
  });
  vm.runInContext(
    `${section("export async function commitEdit(", "/** Change a queued op's value")}\nglobalThis.commit = commitEdit;`,
    ctx,
  );
  await ctx.commit("운영지원과");
  assert.equal(queued[0][0].overwrite, true);
});

// --- fix 10: an unfixable 되돌리기 제안 is not queued ---------------------------------------

test("a 되돌리기 제안 whose dry run fails validation never reaches the queue", async () => {
  const queued = [];
  const dismissed = [];
  const s = store({
    activeSessionId: "S", language: "ko", receipts: {},
    draft: { ops: [] }, undoPhase: "idle", undoError: null,
  });
  const ctx = vm.createContext({
    ...s, t, opKindLabel, planOpsPayload, undoBlockReason, Number, String, Array,
    captureDraftFence: () => ({}),
    ownsDraftFence: () => true,
    headCandidate: () => ({ runId: "run-1" }),
    markExternalPlanDismissed: (sessionId, planId) => dismissed.push(planId),
    showToast: () => {},
    setQueue: async (ops) => { queued.push(ops); },
    rt: {
      readReceipt: async () => ({ planId: "p1", base: null }),
      getPlan: async () => ({
        ops: [{ opId: "f1", kind: "fill_cell", params: { table: 0, row: 2, col: 0, text: "값" } }],
      }),
      readRegion: async () => ({
        subject: { kind: "source" },
        regions: [{ table: 0, addr: { row: 2, col: 0 }, text: "작성 요령" }],
      }),
      proposePlan: async () => ({ planId: "dry-1" }),
      validatePlan: async () => ({ ok: false, hard: [{ code: "fill_charpr_script_anomaly" }] }),
      asRuntimeError: (e) => e,
    },
  });
  vm.runInContext(
    `${section("const INVERTIBLE_KINDS", "/**\n * Ask the runtime whether")}\nglobalThis.undo = proposeUndoOf;`,
    ctx,
  );
  const count = await ctx.undo("run-1");
  assert.equal(count, 0);
  assert.equal(queued.length, 0, "the queue is untouched");
  assert.equal(s.read().undoError.code, "undo_unfixable");
  assert.match(s.read().undoError.message, /위첨자나 아래첨자/);
  assert.deepEqual(dismissed, ["dry-1"], "the dry-run plan is never adopted");
});

// --- fix 4 / fix 7: after apply the head is read and the saved entries are cleared ---------

test("a successful apply reads the head 수정본 for the page and forgets the saved entries", async () => {
  const persisted = [];
  const headLoads = [];
  const applied = { sessionId: "A", runId: "runA", planId: "pA", candidate: { sha256: "s" }, checks: { acceptance: true } };
  const draft = { sessionId: "A", plan: { planId: "pA", planHash: "hA" }, ops: ["op"] };
  const s = store({
    activeSessionId: "A", draft, approval: { approvalId: "aA", planId: "pA", planHash: "hA", state: "approved" },
    applyPhase: "idle", applyError: null, applied: null, recovery: null, applyOutcomes: {},
    candidates: {}, head: "headA", redoStack: [], language: "ko", showOriginal: true,
    parkedDrafts: {},
  });
  const ctx = vm.createContext({
    ...s, t, EMPTY_DRAFT,
    activeApprovalBinding: () => ({ approvalId: "aA" }),
    approvalBindingStillExists: () => true,
    draftStaleness: () => null,
    markExternalPlanDismissed: () => {},
    verifyReversal: async () => {},
    showToast: () => {},
    persistDraft: (sessionId, value) => persisted.push([sessionId, value]),
    loadHeadTexts: async (sessionId, runId) => { headLoads.push([sessionId, runId]); },
    rt: {
      applyPlan: async () => applied,
      candidates: async () => [],
      asRuntimeError: (e) => e,
    },
  });
  vm.runInContext(
    `${section("async function loadCandidates(", "/**\n * Make a session active")}\n${section('const APPLY_TAG = "apply";', "/** Cooperative cancel")}\nglobalThis.apply = applyApproved;`,
    ctx,
  );
  await ctx.apply();
  assert.equal(s.read().head, "runA");
  assert.equal(s.read().showOriginal, false, "the page lands on the new 수정본");
  assert.deepEqual(headLoads, [["A", "runA"]]);
  assert.deepEqual(persisted, [["A", null]]);
});

// --- fix 2: a test agent's plan is marked on every op -----------------------------------------

test("ops adopted from a bundled test agent carry provenance mock", async () => {
  const projection = readFileSync(new URL("../src/agent/planProjection.ts", import.meta.url), "utf8");
  const authoritative = {
    planId: "plan-mock", proposer: "agenthost-mock", provenance: "mock", base: null,
    boundSha256: "b", ops: [{ opId: "o1", kind: "fill_cell", params: { table: 0, row: 1, col: 4, text: "AGENT-HOST-0001" } }],
  };
  const s = store({
    activeSessionId: "S", head: null, language: "ko",
    inspects: { S: {} }, texts: { S: [] },
    draft: { marker: "existing" }, approval: null, approvalPhase: "idle",
  });
  const ctx = vm.createContext({ Set, Number, Object, opKindLabel, t });
  vm.runInContext(
    stripTypeScriptTypes(projection)
      .replace(/^\s*import\s+[\s\S]*?from\s+["'][^"']+["'];?\s*$/gm, "")
      .replaceAll("export ", ""),
    ctx,
  );
  Object.assign(ctx, {
    ...s,
    rt: {
      getPlan: async () => authoritative,
      validatePlan: async () => ({ ok: true, hard: [] }),
      readRegion: async () => ({ regions: [] }),
      getApproval: async () => null,
    },
    headCandidate: () => null,
    currentPlanGeneration: () => 1,
    seatText: () => "",
    regionTextAt: () => null,
  });
  const adoptStart = source.indexOf("async function adoptAgentPlan(");
  const adoptEnd = source.indexOf("\n}\n\n/** Ids are the shell's", adoptStart);
  vm.runInContext(
    `${stripTypeScriptTypes(source.slice(source.indexOf("interface DraftOwner {"), source.indexOf("/** Load a session's inspect")))}
${stripTypeScriptTypes(source.slice(adoptStart, adoptEnd + 2))}\nglobalThis.adopt = adoptAgentPlan;`,
    ctx,
  );
  const adopted = await ctx.adopt("S", "plan-mock", null);
  assert.ok(adopted);
  assert.equal(s.read().draft.ops.length, 1);
  assert.equal(s.read().draft.ops[0].provenance, "mock");
  assert.equal(s.read().draft.ops[0].origin, "agent");
});
