// Regression tests for the S-WP0 attack findings on the trust branch (T2).
//
// Pure rules are imported from src/workspace/trust.ts as a namespace, so a
// rule that does not exist yet fails its own test instead of the whole file.
// Action tests slice one function out of src/actions.ts and run it in a VM
// with its collaborators stubbed, like trust-actions.test.mjs.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";

import { errorCodeMessage, opKindLabel, t } from "../src/i18n/vocabulary.ts";
import * as trust from "../src/workspace/trust.ts";
import { opSignature } from "../src/store.ts";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");

function section(start, end) {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, `source boundary: ${start}`);
  return stripTypeScriptTypes(source.slice(a, b).replaceAll("export ", ""));
}

function store(initial) {
  let state = initial;
  return {
    getState: () => state,
    setState: (patch) => { state = { ...state, ...patch }; },
    read: () => state,
  };
}

const EMPTY_DRAFT = {
  ops: [], plan: null, validation: null, sessionId: null, boundSha256: null,
  phase: "idle", error: null, rewrittenFromAgent: false, baseRunId: null, reverses: null,
};

const OK = { ok: true, stale: false, hard: [] };

function planFor(id, sessionId = "S", extra = {}) {
  return { planId: id, planHash: `h-${id}`, sessionId, boundSha256: "digest-0", base: null, ...extra };
}

function draftFor(plan, extra = {}) {
  return {
    ...EMPTY_DRAFT, sessionId: plan.sessionId, plan, validation: OK, boundSha256: plan.boundSha256,
    phase: "ready", ops: [{ opId: "u1", kind: "fill_cell", table: 0, row: 1, col: 1, text: "값", origin: "user", sessionId: plan.sessionId }],
    ...extra,
  };
}

// --- #1 the approval click binds what the person saw ------------------------------------

test("#1 a confirmation binds session, plan, hash, base digest and acknowledgements", () => {
  const plan = planFor("p1");
  const state = { activeSessionId: "S", draft: draftFor(plan) };
  const binding = trust.captureConfirmation(state, ["changed_facts"]);
  assert.deepEqual(
    { ...binding },
    { sessionId: "S", planId: "p1", planHash: "h-p1", baseDigest: "digest-0", baseRunId: null, acknowledgements: ["changed_facts"] },
  );
  assert.equal(trust.confirmationBreak(binding, state, ["changed_facts"]), null);
  const adopted = { activeSessionId: "S", draft: draftFor(planFor("agent-plan")) };
  assert.equal(trust.confirmationBreak(binding, adopted), "plan_replaced");
  const switched = { activeSessionId: "T", draft: draftFor(planFor("p1", "T")) };
  assert.equal(trust.confirmationBreak(binding, switched), "document_switched");
  const rebased = { activeSessionId: "S", draft: draftFor({ ...plan, boundSha256: "digest-1" }) };
  assert.equal(trust.confirmationBreak(binding, rebased), "base_changed");
  const invalid = { activeSessionId: "S", draft: draftFor(plan, { validation: { ok: false, stale: false, hard: [{ code: "x" }] } }) };
  assert.equal(trust.confirmationBreak(binding, invalid), "validation_failed");
  assert.equal(trust.confirmationBreak(binding, state, ["changed_facts", "mock"]), "acknowledgements_changed");
  assert.equal(trust.approvalBindsConfirmation({ planId: "p1", planHash: "h-p1" }, binding), true);
  assert.equal(trust.approvalBindsConfirmation({ planId: "p1", planHash: "other" }, binding), false);
});

/**
 * Run approveAndApplyFromDialog with steps that can change the world while
 * they "wait". Returns the calls each step saw.
 */
function dialogHarness({ initial, onValidate, onRequest, onResolve, validation }) {
  const s = store(initial);
  const calls = { validate: 0, request: [], resolve: [], apply: [] };
  const ctx = vm.createContext({
    ...s,
    errorCodeMessage,
    showToast: () => {},
    confirmationBreak: trust.confirmationBreak,
    approvalBindsConfirmation: trust.approvalBindsConfirmation,
    requiredAcknowledgements: trust.requiredAcknowledgements,
    requiredGuardAcks: trust.requiredGuardAcks,
    getReviewGuardSummary: () => ({ planId: null, changedFactOpIds: [] }),
    revalidateActiveDraft: async () => {
      calls.validate += 1;
      onValidate?.(s);
      if (validation) s.setState({ draft: { ...s.read().draft, validation } });
      return { ok: true, stale: false };
    },
    requestApprovalForDraft: async () => {
      const plan = s.read().draft.plan;
      calls.request.push(plan.planId);
      s.setState({ approval: { approvalId: `a-${plan.planId}`, planId: plan.planId, planHash: plan.planHash, state: "pending" } });
      onRequest?.(s);
    },
    takeSheetConfirmation: async (binding) => `token-${binding.planId}`,
    resolveApprovalDecision: async (decision, approver, reason, options) => {
      calls.resolve.push({ planId: s.read().approval?.planId, confirmed: options?.confirmed?.planId, autoApply: options?.autoApply });
      calls.tokens = [...(calls.tokens ?? []), options?.confirmationToken ?? null];
      s.setState({ approval: { ...s.read().approval, state: "approved" } });
      onResolve?.(s);
    },
    applyApproved: async (confirmed) => { calls.apply.push({ planId: s.read().draft.plan?.planId, confirmed: confirmed?.planId }); },
  });
  vm.runInContext(
    `${section("export async function approveAndApplyFromDialog(", "export function openApprovalDialog")}\nglobalThis.confirm = approveAndApplyFromDialog;`,
    ctx,
  );
  return { s, calls, confirm: (binding) => ctx.confirm(binding, "host-operator") };
}

function adopt(s, planId) {
  // ReviewView auto-adopts an external proposal while the sheet waits.
  s.setState({ draft: draftFor(planFor(planId)), approval: null, approvalPhase: "idle" });
}

test("#1 an agent proposal adopted during revalidation is never approved", async () => {
  const plan = planFor("p1");
  const initial = { activeSessionId: "S", language: "ko", draft: draftFor(plan), approval: null };
  const h = dialogHarness({ initial, onValidate: (s) => adopt(s, "agent-plan") });
  const binding = trust.captureConfirmation(initial, []);
  const done = await h.confirm(binding);
  assert.equal(done, false);
  assert.deepEqual(h.calls.request, [], "no approval is requested for the adopted plan");
  assert.deepEqual(h.calls.resolve, []);
  assert.deepEqual(h.calls.apply, []);
  assert.equal(h.s.read().approvalError.code, "confirmation_changed");
});

test("#1 a proposal adopted during the approval request gets no decision", async () => {
  const plan = planFor("p1");
  const initial = { activeSessionId: "S", language: "ko", draft: draftFor(plan), approval: null };
  const h = dialogHarness({ initial, onRequest: (s) => adopt(s, "agent-plan") });
  const done = await h.confirm(trust.captureConfirmation(initial, []));
  assert.equal(done, false);
  assert.deepEqual(h.calls.request, ["p1"], "the request was for the confirmed plan");
  assert.deepEqual(h.calls.resolve, [], "nothing is decided after the queue moved");
  assert.deepEqual(h.calls.apply, []);
});

test("#1 a proposal adopted during the decision is never applied", async () => {
  const plan = planFor("p1");
  const initial = { activeSessionId: "S", language: "ko", draft: draftFor(plan), approval: null };
  const h = dialogHarness({ initial, onResolve: (s) => adopt(s, "agent-plan") });
  const done = await h.confirm(trust.captureConfirmation(initial, []));
  assert.equal(done, false);
  assert.deepEqual(h.calls.resolve, [{ planId: "p1", confirmed: "p1", autoApply: false }],
    "the decision is bound to the confirmed plan and does not chain an apply");
  assert.deepEqual(h.calls.apply, [], "the apply wait never starts for a replaced queue");
  assert.equal(h.s.read().approvalError.code, "confirmation_changed");
});

test("#1 a document switch during a wait stops the flow", async () => {
  const plan = planFor("p1");
  const initial = { activeSessionId: "S", language: "ko", draft: draftFor(plan), approval: null };
  const h = dialogHarness({
    initial,
    onValidate: (s) => s.setState({ activeSessionId: "T", draft: draftFor(planFor("p1", "T")) }),
  });
  const done = await h.confirm(trust.captureConfirmation(initial, []));
  assert.equal(done, false);
  assert.deepEqual(h.calls.request, []);
  assert.deepEqual(h.calls.apply, []);
});

test("#1 a failed revalidation that is not stale still stops the flow", async () => {
  const plan = planFor("p1");
  const initial = { activeSessionId: "S", language: "ko", draft: draftFor(plan), approval: null };
  const h = dialogHarness({ initial, validation: { ok: false, stale: false, hard: [{ code: "cell_address_unknown" }] } });
  const done = await h.confirm(trust.captureConfirmation(initial, []));
  assert.equal(done, false);
  assert.deepEqual(h.calls.request, []);
  assert.equal(h.s.read().approvalError.data.reason, "validation_failed");
});

test("#1 an acknowledgement the plan now needs but the person did not tick stops the flow", async () => {
  const plan = planFor("p1", "S", { provenance: "mock" });
  const initial = { activeSessionId: "S", language: "ko", draft: draftFor(plan), approval: null };
  const h = dialogHarness({ initial });
  const done = await h.confirm(trust.captureConfirmation(initial, []));
  assert.equal(done, false);
  assert.deepEqual(h.calls.request, []);
  assert.equal(h.s.read().approvalError.data.reason, "acknowledgements_changed");
});

test("#1 an unchanged binding goes through every step to apply, bound throughout", async () => {
  const plan = planFor("p1");
  const initial = { activeSessionId: "S", language: "ko", draft: draftFor(plan), approval: null };
  const h = dialogHarness({ initial });
  const done = await h.confirm(trust.captureConfirmation(initial, []));
  assert.equal(done, true);
  assert.deepEqual(h.calls.apply, [{ planId: "p1", confirmed: "p1" }]);
});

// --- #5 an explicit replacement names the plan it replaces -------------------------------

function setQueueHarness(initial) {
  const s = store(initial);
  const proposals = [];
  let gen = 0;
  const ctx = vm.createContext({
    ...s, EMPTY_DRAFT, errorCodeMessage,
    queueAdmission: trust.queueAdmission,
    bumpPlanGeneration: () => ++gen,
    currentPlanGeneration: () => gen,
    markExternalPlanDismissed: () => {},
    headCandidate: () => null,
    captureDraftOwner: () => s.read().draft,
    ownsDraft: (owner) => s.read().draft === owner,
    persistDraft: () => {},
    rt: {
      proposePlan: async (sessionId, ops, options) => {
        proposals.push({ sessionId, ops, options });
        return planFor("new", sessionId);
      },
      validatePlan: async () => OK,
      asRuntimeError: (e) => e,
    },
  });
  vm.runInContext(
    `${section("async function setQueue(", "/** Re-propose the queue against")}\nglobalThis.setQueue = setQueue;`,
    ctx,
  );
  return { s, proposals, setQueue: (ops, options) => ctx.setQueue(ops, options) };
}

test("#5 re-proposing a queued plan tells the runtime which plan it replaces", async () => {
  const old = planFor("old");
  const h = setQueueHarness({ activeSessionId: "S", language: "ko", draft: draftFor(old), approval: { planId: "old", state: "pending" } });
  await h.setQueue([{ opId: "u2", kind: "fill_cell", table: 0, row: 1, col: 2, text: "새 값", origin: "user", sessionId: "S" }]);
  assert.equal(h.proposals.length, 1);
  assert.equal(h.proposals[0].options.replaces, "old");
});

// --- #7 ownership and shape in the common queue path ---------------------------------------

test("#7 setQueue proposes nothing when an op belongs to another document", async () => {
  const h = setQueueHarness({ activeSessionId: "S", language: "ko", draft: { ...EMPTY_DRAFT }, approval: null });
  await h.setQueue([
    { opId: "u1", kind: "fill_cell", table: 0, row: 1, col: 1, text: "내 값", origin: "user", sessionId: "S" },
    { opId: "x1", kind: "fill_cell", table: 0, row: 1, col: 2, text: "남의 값", origin: "user", sessionId: "OTHER" },
  ]);
  assert.equal(h.proposals.length, 0);
  assert.equal(h.s.read().draft.error.code, "foreign_session_ops");
  assert.deepEqual([...h.s.read().draft.error.data.opIds], ["x1"]);
});

test("#7 setQueue proposes nothing when an op is malformed", async () => {
  const h = setQueueHarness({ activeSessionId: "S", language: "ko", draft: { ...EMPTY_DRAFT }, approval: null });
  await h.setQueue([{ opId: "u1", kind: "fill_cell", table: "0; drop", row: 1, col: 1, text: "값", origin: "user" }]);
  assert.equal(h.proposals.length, 0);
  assert.equal(h.s.read().draft.error.code, "invalid_queue_ops");
});

test("#7 an op that names no document is stamped with this one before it is proposed", async () => {
  const h = setQueueHarness({ activeSessionId: "S", language: "ko", draft: { ...EMPTY_DRAFT }, approval: null });
  await h.setQueue([{ opId: "u1", kind: "fill_cell", table: 0, row: 1, col: 1, text: "값", origin: "user" }]);
  assert.equal(h.proposals.length, 1);
  assert.equal(h.s.read().draft.ops[0].sessionId, "S");
});

test("#7 saved drafts carry the session and source digest, and a mismatch restores nothing", () => {
  const op = { opId: "u1", kind: "fill_cell", table: 0, row: 1, col: 1, text: "값", origin: "user", before: "" };
  const env = trust.savedDraftEnvelope("S", "digest-0", [op], "2026-11-19T00:00:00Z");
  assert.equal(env.version, 2);
  assert.equal(env.sessionId, "S");
  assert.equal(env.sourceSha256, "digest-0");
  assert.equal(env.ops[0].sessionId, "S");
  assert.equal(trust.restorableOps(env, { sessionId: "S", sourceSha256: "digest-0" }).length, 1);
  assert.equal(trust.restorableOps(env, { sessionId: "T", sourceSha256: "digest-0" }).length, 0, "another session");
  assert.equal(trust.restorableOps(env, { sessionId: "S", sourceSha256: "digest-9" }).length, 0, "another source");
  const relabelled = { ...env, ops: [{ ...env.ops[0], sessionId: "T" }] };
  assert.equal(trust.restorableOps(relabelled, { sessionId: "S", sourceSha256: "digest-0" }).length, 0);
  const legacy = { ops: [op], savedUtc: "x" };
  assert.equal(trust.restorableOps(legacy, { sessionId: "S" }).length, 0, "missing ownership is not mine");
  const legacyOwned = { ops: [{ ...op, sessionId: "S" }], savedUtc: "x" };
  assert.equal(trust.restorableOps(legacyOwned, { sessionId: "S" }).length, 1);
});

test("#7 a mismatched saved entry produces no proposal on restore", async () => {
  const queued = [];
  const op = { opId: "u1", kind: "fill_cell", table: 0, row: 1, col: 1, text: "값", origin: "user", before: "", sessionId: "OTHER" };
  const s = store({
    activeSessionId: "S", draft: { ...EMPTY_DRAFT },
    savedDrafts: { S: { version: 2, sessionId: "OTHER", sourceSha256: "digest-0", ops: [op], savedUtc: "x" } },
  });
  const ctx = vm.createContext({
    ...s,
    restorableOps: trust.restorableOps,
    sessionSourceDigest: () => "digest-0",
    headCandidate: () => null,
    setQueue: async (ops) => { queued.push(ops); },
  });
  vm.runInContext(
    `${section("async function restoreSavedDraft(", "/** The session source's digest")}\nglobalThis.restore = restoreSavedDraft;`,
    ctx,
  );
  await ctx.restore("S");
  assert.equal(queued.length, 0);
});

// --- #8 returned changes survive a reload, identity includes run and mode -----------------

test("#8 the returned-change signature includes the target run and the op mode", () => {
  const base = { opId: "a", kind: "replace_at_cell", table: 0, row: 1, col: 1, text: "X", origin: "agent" };
  assert.notEqual(opSignature({ ...base, run: 0 }), opSignature({ ...base, run: 2 }));
  assert.notEqual(opSignature({ ...base, mode: "replace" }), opSignature({ ...base, mode: "append" }));
  assert.notEqual(
    opSignature({ ...base, kind: "fill_cell" }),
    opSignature({ ...base, mode: "replace" }),
    "a whole-cell fill is not a run replacement",
  );
  assert.equal(
    opSignature({ opId: "g", kind: "delete_guides", text: "", origin: "agent", color: "#FF0000", charPrIds: ["7", "3"] }),
    opSignature({ opId: "h", kind: "delete_guides", text: "", origin: "agent", color: "#ff0000", charPrIds: ["3", "7"] }),
  );
});

test("#8 returned changes are written to prefs and read back after a reload", async () => {
  const saved = [];
  const s = store({ activeSessionId: "S", draft: { ...EMPTY_DRAFT, sessionId: "S" }, returnedOps: {}, sessions: [] });
  const ctx = vm.createContext({
    ...s, opSignature,
    withoutSignatures: trust.withoutSignatures,
    rt: { savePrefs: async (patch) => { saved.push(patch); } },
  });
  vm.runInContext(
    `${section("function sessionSourceDigest(", "/** 다시 넣기")}\nglobalThis.mark = markReturned;`,
    ctx,
  );
  const op = { opId: "a", kind: "fill_cell", table: 0, row: 1, col: 4, text: "AGENT", origin: "agent" };
  ctx.mark([op]);
  assert.equal(saved.length, 1);
  const written = JSON.parse(JSON.stringify(saved[0].returned));
  assert.deepEqual(written, { S: [opSignature(op)] });
  // The reload: prefs come back through the same parser the boot uses.
  const reloaded = trust.returnedFromPrefs(written);
  assert.equal(trust.isReturnedOp({ ...op, opId: "again" }, reloaded.S), true);
  assert.equal(trust.isReturnedOp({ ...op, run: 1, kind: "replace_at_cell" }, reloaded.S), false);
});

// --- #9 되돌리기 refuses an intervening edit and shows the real before -------------------

function undoHarness({ reads, plan, head = "run-2" }) {
  const queued = [];
  const proposed = [];
  const s = store({ activeSessionId: "S", language: "ko", receipts: {}, draft: { ops: [] }, undoPhase: "idle", undoError: null });
  const ctx = vm.createContext({
    ...s, t, errorCodeMessage, opKindLabel,
    planOpsPayload: trust.planOpsPayload,
    undoBlockReason: trust.undoBlockReason,
    Number, String, Array, Map,
    captureDraftFence: () => ({}),
    ownsDraftFence: () => true,
    headCandidate: () => ({ runId: head }),
    markExternalPlanDismissed: () => {},
    showToast: () => {},
    setQueue: async (ops) => { queued.push(ops); s.setState({ draft: { ops } }); },
    rt: {
      readReceipt: async () => ({ planId: "p1", base: { runId: "run-0" } }),
      getPlan: async () => plan,
      readRegion: async (sessionId, regions, runId) => ({ subject: { runId }, regions: [reads[runId]] }),
      proposePlan: async () => { proposed.push(1); return { planId: "dry" }; },
      validatePlan: async () => ({ ok: true, hard: [] }),
      asRuntimeError: (e) => e,
    },
  });
  vm.runInContext(
    `${section("const INVERTIBLE_KINDS", "/**\n * Ask the runtime whether")}\nglobalThis.undo = proposeUndoOf;`,
    ctx,
  );
  return { s, queued, proposed, undo: (runId) => ctx.undo(runId) };
}

const cellAt = (text, runs) => ({ table: 0, addr: { row: 2, col: 1 }, text, ...(runs ? { runs } : {}) });

test("#9 an undo whose target was edited again later is refused with the conflict", async () => {
  const h = undoHarness({
    plan: { ops: [{ opId: "f1", kind: "fill_cell", params: { table: 0, row: 2, col: 1, text: "홍길순" } }] },
    reads: { "run-0": cellAt(""), "run-1": cellAt("홍길순"), "run-2": cellAt("김철수") },
  });
  const count = await h.undo("run-1");
  assert.equal(count, 0);
  assert.equal(h.queued.length, 0, "nothing reaches the queue");
  assert.equal(h.proposed.length, 0, "not even a dry run");
  const err = h.s.read().undoError;
  assert.equal(err.code, "undo_conflict");
  assert.match(err.message, /김철수/);
  assert.match(err.message, /홍길순/);
});

test("#9 the inverse shows the value it actually replaces, not the op's input", async () => {
  const runs = (text) => [{ index: 0, text }];
  const h = undoHarness({
    head: "run-1",
    plan: { ops: [{ opId: "r1", kind: "replace_at_cell", params: { table: 0, row: 2, col: 1, run: 0, mode: "append", text: "(서명)" } }] },
    reads: {
      "run-0": cellAt("담당자", runs("담당자")),
      "run-1": cellAt("담당자(서명)", runs("담당자(서명)")),
    },
  });
  const count = await h.undo("run-1");
  assert.equal(count, 1);
  const op = h.queued[0][0];
  assert.equal(op.before, "담당자(서명)", "before is what the head holds there");
  assert.equal(op.text, "담당자");
});

test("#9 a reversal proof needs every requested region readable", async () => {
  const s = store({ activeSessionId: "S", head: "run-3", receipts: {} });
  const ctx = vm.createContext({
    ...s,
    rt: {
      readReceipt: async () => ({ planId: "p1", base: { runId: "run-1" } }),
      getPlan: async () => ({ ops: [
        { opId: "a", kind: "fill_cell", params: { table: 0, row: 1, col: 1, text: "x" } },
        { opId: "b", kind: "fill_cell", params: { table: 0, row: 1, col: 2, text: "y" } },
      ] }),
      // An older runtime said "equal" over the readable subset.
      compareCandidate: async () => ({
        regionsEqual: true, regionsUnreadable: ["0:1,2"],
        regions: [{ address: "0:1,1", equal: true }, { address: "0:1,2", equal: null }],
      }),
      asRuntimeError: (e) => e,
    },
    Number,
  });
  vm.runInContext(
    `${section("function opAddress(", "/**\n * Propose the inverse")}\n${section("export async function verifyReversal(", "/** Show an older candidate")}\nglobalThis.verify = verifyReversal;`,
    ctx,
  );
  assert.equal(await ctx.verify("run-3", "run-2"), false);
});

// --- #10 provenance is the runtime's, not a label ----------------------------------------

test("#10 a proposer name alone never makes a test proposal; the runtime's provenance does", () => {
  assert.equal(trust.proposerKind("agenthost-mock", null), "agent");
  assert.equal(trust.proposerKind("rigorloom-desktop", "mock"), "mock");
  // A rewritten queue whose op flags were lost still reads as a test proposal
  // when the runtime kept provenance on the new plan.
  const rewritten = { ops: [{ origin: "user" }], plan: { provenance: "mock" } };
  assert.equal(trust.draftProposerKind(rewritten), "mock");
  const adoptSrc = source.slice(source.indexOf("// A bundled test agent's ops say so"), source.indexOf("const draft: Draft = {", source.indexOf("// A bundled test agent's ops say so")));
  assert.doesNotMatch(adoptSrc, /proposer ===/, "adoption reads provenance, not the proposer name");
});

// --- #11 acknowledgements come from the whole guard result --------------------------------

const para = (paragraph, changes, pass = false) => ({ paragraph, pass, kinds: [], changes, before: "", after: "" });

test("#11 a failing paragraph no row is tied to requires the acknowledgement and is listed", () => {
  const loose = para(7, [{ kind: "numbers", before: ["30"], after: ["40"] }]);
  const acks = trust.requiredGuardAcks({ changedFactOpIds: [], unattributedFailing: [loose] });
  assert.equal(acks.total, 1, "before, no row matched and no box was required");
  const summary = trust.guardWarningSummary([], {}, "ko", { unattributedFailing: [loose] });
  const full = trust.guardWarningFullLines(summary, "ko");
  assert.equal(full.length, 1);
  assert.match(full[0], /문단 7/);
  assert.match(full[0], /30/);
  assert.match(full[0], /40/);
});

test("#11 a change spanning several paragraphs keeps every protected delta", () => {
  const ch = { opId: "g1", ordinal: 1, fieldLabel: "안내문", op: { kind: "delete_guides" } };
  const first = para(2, [{ kind: "dates", before: ["2026. 1. 1."], after: [] }]);
  const second = para(3, [{ kind: "quotes", before: ["“행정기관명”"], after: [] }]);
  const summary = trust.guardWarningSummary(
    [ch],
    { g1: { status: "none", paragraph: first } },
    "ko",
    { paragraphsByOp: { g1: [first, second] } },
  );
  const line = trust.guardWarningFullLines(summary, "ko").join("\n");
  assert.match(line, /2026\. 1\. 1\./);
  assert.match(line, /행정기관명/);
});

test("#11 the full warning list in the sheet is complete, not cut at two", () => {
  const changes = [1, 2, 3, 4].map((n) => ({ opId: `o${n}`, ordinal: n, fieldLabel: `칸 ${n}`, op: { kind: "fill_cell" } }));
  const audits = Object.fromEntries(changes.map((c, i) => [c.opId, {
    status: i === 0 ? "changed" : "kept",
    paragraph: para(10 + i, i === 3
      ? [{ kind: "quotes", before: ["“가”"], after: [] }]
      : [{ kind: "numbers", before: i === 0 ? ["1"] : [], after: ["1", "2", "3"] }]),
  }]));
  const summary = trust.guardWarningSummary(changes, audits, "ko");
  const short = trust.guardWarningLines(summary, "ko");
  assert.ok(short.length <= 2, "the scan summary stays short");
  const full = trust.guardWarningFullLines(summary, "ko");
  assert.equal(full.length, 4, "every row, including the third group, is reachable");
  assert.ok(full.some((l) => l.includes("‘3’")), "values past the second are not cut");
});
