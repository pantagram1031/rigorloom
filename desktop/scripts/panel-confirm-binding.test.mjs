// The v2 panel's 승인 binds what the person confirmed in the sheet, the same
// way the v1 approval dialog does. confirmApproval is sliced out of
// src/panel/actions.ts and run with the real frozen gate from src/actions.ts
// (approveAndApplyFromDialog), the real trust rules and the real change model;
// only the runtime-facing waits are stubbed, so each test can change the world
// while one of them "waits".
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";

import { errorCodeMessage } from "../src/i18n/vocabulary.ts";
import * as trust from "../src/workspace/trust.ts";
import * as changes from "../src/model/changes.ts";

const gateSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const panelSource = readFileSync(new URL("../src/panel/actions.ts", import.meta.url), "utf8");

function slice(source, start, end) {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a);
  assert.ok(a >= 0 && b > a, `source boundary: ${start}`);
  return stripTypeScriptTypes(source.slice(a, b).replaceAll("export ", ""));
}

const gate = slice(gateSource, "export async function approveAndApplyFromDialog(", "export function openApprovalDialog");
const panel = slice(panelSource, "function matchesRenderedPlan(", "export function openReturn");

const OK = { ok: true, stale: false, hard: [] };

function op(id, value) {
  return { opId: id, kind: "fill_cell", table: 0, row: 1, col: Number(id.slice(-1)), text: value, origin: "user", sessionId: "S" };
}

function planFor(id, extra = {}) {
  return { planId: id, planHash: `h-${id}`, sessionId: "S", boundSha256: "digest-0", base: null, ...extra };
}

function draftFor(plan, ops) {
  return {
    ops, plan, validation: OK, sessionId: plan.sessionId, boundSha256: plan.boundSha256,
    phase: "ready", error: null, rewrittenFromAgent: false, baseRunId: null, reverses: null,
  };
}

function viewFor(plan, ops, decisions = {}) {
  const items = ops.map((o, i) => {
    const base = {
      id: o.opId, n: i + 1, at: `t0/r1/c${i}`, kind: "fill", label: `칸 ${i + 1}`, opName: "빈칸 채움",
      before: "", after: o.text, page: 1, source: o.source ?? "user", guard: { status: "none", facts: [] }, hard: [],
    };
    base.decision = decisions[o.opId] ?? "accepted";
    return { ...base, contentHash: changes.contentHashOf(base) };
  });
  return {
    id: plan.planId, planHash: plan.planHash,
    base: { kind: "source", revision: 0, sha256: plan.boundSha256 },
    stale: null, items, provenance: { agent: null, provider: null, mock: false }, createdUtc: null, checking: false,
  };
}

/**
 * One document "S" with a draft and the sheet open on its plan. Hooks run
 * inside the named wait: prune (after the last 뺌 is removed), validate,
 * request, resolve.
 */
function harness({ ops, decisions = {}, hooks = {}, ticks = [] }) {
  const plan = planFor("p1");
  let state = {
    activeSessionId: "S", language: "ko", draft: draftFor(plan, ops),
    approval: null, approvalPhase: "idle", approvalError: null, applyOutcomes: {},
  };
  let view = viewFor(plan, ops, decisions);
  const slices = new Map();
  const calls = { removed: [], validate: 0, request: [], resolve: [], apply: [], tokens: [] };
  const getState = () => state;
  const setState = (patch) => { state = { ...state, ...patch }; };
  const panelSlice = {
    get: (d) => slices.get(d) ?? { ticks, confirmPhase: "idle", sheetOpen: true, sheetFor: changes.approvalSheetKey(view) },
    set: (d, patch) => { slices.set(d, { ...panelSlice.get(d), ...patch }); },
  };
  const ctx = vm.createContext({
    getState, setState, panelSlice, errorCodeMessage,
    setCanvasSlice: () => {},
    prunedReviewMatches: async () => hooks.prunedReviewMatches?.() ?? true,
    prepareConfirmation: () => {},
    closeApproval: () => panelSlice.set("S", { sheetOpen: false, sheetFor: null, ticks: [] }),
    showToast: () => {},
    doc: () => state.activeSessionId,
    view: () => view,
    lang: () => "ko",
    tp: (key) => key,
    ...changes,
    captureConfirmation: trust.captureConfirmation,
    confirmationBreak: trust.confirmationBreak,
    approvalBindsConfirmation: trust.approvalBindsConfirmation,
    requiredAcknowledgements: trust.requiredAcknowledgements,
    requiredGuardAcks: trust.requiredGuardAcks,
    getReviewGuardSummary: () => null,
    revisionNumberFor: () => 1,
    removeReviewOps: async (source, ids) => {
      if (state.draft !== source) return false;
      calls.removed.push(...ids);
      const left = state.draft.ops.filter((o) => !ids.has(o.opId));
      const next = planFor(`p1-${left.map((o) => o.opId).join("-")}`);
      setState({ draft: draftFor(next, left), approval: null });
      hooks.prune?.({ getState, setState });
      return state.draft.ops === left;
    },
    revalidateActiveDraft: async () => {
      calls.validate += 1;
      hooks.validate?.({ getState, setState });
      return { ok: true, stale: false };
    },
    requestApprovalForDraft: async () => {
      const p = state.draft.plan;
      calls.request.push(p.planId);
      setState({ approval: { approvalId: `a-${p.planId}`, planId: p.planId, planHash: p.planHash, state: "pending" } });
      hooks.request?.({ getState, setState });
    },
    takeSheetConfirmation: async (binding) => `token-${binding.planId}-${binding.planHash}`,
    resolveApprovalDecision: async (_decision, _approver, _reason, options) => {
      calls.resolve.push(state.approval?.planId);
      calls.tokens.push(options?.confirmationToken ?? null);
      setState({ approval: { ...state.approval, state: "approved" } });
      hooks.resolve?.({ getState, setState });
    },
    applyApproved: async (confirmed) => {
      calls.apply.push(confirmed.planId);
      setState({
        draft: draftFor(planFor("none"), []),
        applyOutcomes: { S: { applied: { runId: "run-1" } } },
      });
    },
  });
  vm.runInContext(`${gate}\n${panel}\nglobalThis.confirm = confirmApproval;`, ctx);
  return { calls, confirm: () => ctx.confirm(), panel: () => panelSlice.get("S"), read: () => state };
}

/** An agent proposal adopted while the confirm waits: same document, new plan. */
function adopt({ setState }) {
  const plan = planFor("agent-plan");
  setState({ draft: draftFor(plan, [op("a1", "에이전트 값")]), approval: null });
}

test("the unchanged plan is approved and applied once", async () => {
  const h = harness({ ops: [op("u1", "홍길동")] });
  assert.equal(await h.confirm(), true);
  assert.deepEqual(h.calls.request, ["p1"]);
  // The decision carries the sheet's confirmation token for exactly this plan.
  assert.deepEqual(h.calls.tokens, ["token-p1-h-p1"]);
  assert.deepEqual(h.calls.apply, ["p1"]);
  assert.equal(h.panel().applied.count, 1);
});

test("a plan replaced during revalidation is never approved", async () => {
  const h = harness({ ops: [op("u1", "홍길동")], hooks: { validate: adopt } });
  assert.equal(await h.confirm(), false);
  assert.deepEqual(h.calls.request, []);
  assert.deepEqual(h.calls.apply, []);
  assert.equal(h.panel().confirmPhase, "failed");
  assert.equal(h.panel().ticks.length, 0, "the sheet asks again");
});

test("a plan replaced during the approval request gets no decision", async () => {
  const h = harness({ ops: [op("u1", "홍길동")], hooks: { request: adopt } });
  assert.equal(await h.confirm(), false);
  assert.deepEqual(h.calls.resolve, []);
  assert.deepEqual(h.calls.apply, []);
});

test("a plan replaced during the decision is never applied", async () => {
  const h = harness({ ops: [op("u1", "홍길동")], hooks: { resolve: adopt } });
  assert.equal(await h.confirm(), false);
  assert.deepEqual(h.calls.apply, []);
});

test("a plan replaced while the 뺌 items are pruned is refused before any request", async () => {
  const h = harness({
    ops: [op("u1", "홍길동"), op("u2", "뺄 값")],
    decisions: { u2: "rejected" },
    hooks: { prune: adopt },
  });
  assert.equal(await h.confirm(), false);
  assert.deepEqual(h.calls.removed, ["u2"]);
  assert.equal(h.calls.validate, 0);
  assert.deepEqual(h.calls.request, []);
  assert.deepEqual(h.calls.apply, []);
});

test("an accepted change whose value moved during the prune is refused", async () => {
  const h = harness({
    ops: [op("u1", "홍길동"), op("u2", "뺄 값")],
    decisions: { u2: "rejected" },
    hooks: {
      prune: ({ getState, setState }) => {
        const d = getState().draft;
        setState({ draft: { ...d, ops: [{ ...d.ops[0], text: "다른 값" }] } });
      },
    },
  });
  assert.equal(await h.confirm(), false);
  assert.deepEqual(h.calls.request, []);
  assert.deepEqual(h.calls.apply, []);
});

test("a prune that rebases the plan on another base is refused", async () => {
  const h = harness({
    ops: [op("u1", "홍길동"), op("u2", "뺄 값")],
    decisions: { u2: "rejected" },
    hooks: {
      prune: ({ getState, setState }) => {
        const d = getState().draft;
        setState({ draft: { ...d, plan: { ...d.plan, boundSha256: "digest-1" } } });
      },
    },
  });
  assert.equal(await h.confirm(), false);
  assert.deepEqual(h.calls.apply, []);
});

test("a changed guard result after pruning needs a fresh review", async () => {
  const h = harness({
    ops: [op("u1", "홍길동"), op("u2", "뺄 값")],
    decisions: { u2: "rejected" },
    hooks: { prunedReviewMatches: () => false },
  });
  assert.equal(await h.confirm(), false);
  assert.deepEqual(h.calls.request, []);
  assert.deepEqual(h.calls.apply, []);
});

test("a clean prune binds the re-proposed plan and applies only the accepted change", async () => {
  const h = harness({ ops: [op("u1", "홍길동"), op("u2", "뺄 값")], decisions: { u2: "rejected" } });
  assert.equal(await h.confirm(), true);
  assert.deepEqual(h.calls.removed, ["u2"]);
  assert.deepEqual(h.calls.request, ["p1-u1"]);
  assert.deepEqual(h.calls.apply, ["p1-u1"]);
  assert.deepEqual(h.calls.tokens, ["token-p1-u1-h-p1-u1"], "the token binds the re-proposed plan");
});

test("a sheet opened on another plan closes instead of confirming", async () => {
  const h = harness({ ops: [op("u1", "홍길동")], hooks: {} });
  // The store moved before the click: the draft's plan is no longer the sheet's.
  const { read } = h;
  read().draft.plan = planFor("agent-plan");
  assert.equal(await h.confirm(), false);
  assert.deepEqual(h.calls.request, []);
  assert.equal(h.panel().sheetOpen, false);
});

test("an applied approval records typed and test changes separately", async () => {
  const h = harness({
    ops: [op("u1", "Typed value"), { ...op("t2", "Test value"), source: "test" }],
    ticks: ["test"],
  });
  assert.equal(await h.confirm(), true);
  assert.deepEqual({ ...h.panel().applied.sources }, { user: 1, test: 1 });
});
