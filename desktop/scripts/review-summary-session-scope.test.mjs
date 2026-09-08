import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

const source = readFileSync(new URL("../src/workspace/reviewSummary.ts", import.meta.url), "utf8");
const implementation = stripTypeScriptTypes(source)
  .replace(/^import .*?;\s*$/gm, "")
  .replace(/export /g, "");
const context = vm.createContext({
  draftStaleness: () => null,
  headCandidate: () => null,
});
vm.runInContext(
  `${implementation}\nglobalThis.summary = { activeReviewQueueCount, activeReviewApprovalState, activeReviewVerificationState };`,
  context,
);
const summary = context.summary;

function state(overrides = {}) {
  return {
    activeSessionId: "session-A",
    draft: {
      sessionId: "session-A",
      ops: [{ opId: "op-1" }],
      plan: { sessionId: "session-A", planId: "plan-A", planHash: "hash-A" },
    },
    approval: {
      approvalId: "approval-A",
      planId: "plan-A",
      planHash: "hash-A",
      state: "pending",
    },
    candidates: {
      "session-A": [{ runId: "run-A" }],
      "session-B": [{ runId: "run-B" }],
    },
    applied: null,
    candidateVerdict: {
      runId: "run-A",
      report: { ranAll: true, acceptance: true },
    },
    ...overrides,
  };
}

test("active session summary exposes its queue, exact approval binding, and receipt verdict", () => {
  const current = state();
  assert.equal(summary.activeReviewQueueCount(current), 1);
  assert.equal(summary.activeReviewApprovalState(current), "pending");
  assert.equal(summary.activeReviewVerificationState(current), "pass");
});

test("switching sessions does not expose another session's queue, approval, or verdict", () => {
  const current = state({ activeSessionId: "session-B" });
  assert.equal(summary.activeReviewQueueCount(current), 0);
  assert.equal(summary.activeReviewApprovalState(current), null);
  assert.equal(summary.activeReviewVerificationState(current), "not_run");
});

test("an approval with the wrong plan hash is not presented as this queue's approval", () => {
  const current = state({
    approval: {
      approvalId: "approval-A",
      planId: "plan-A",
      planHash: "older-hash",
      state: "approved",
    },
  });
  assert.equal(summary.activeReviewApprovalState(current), null);
});

test("verification preserves partial and failed apply-time outcomes", () => {
  assert.equal(
    summary.activeReviewVerificationState(
      state({ candidateVerdict: { runId: "run-A", report: { ranAll: false, acceptance: false } } }),
    ),
    "partial",
  );
  assert.equal(
    summary.activeReviewVerificationState(
      state({ candidateVerdict: { runId: "run-A", report: { ranAll: true, acceptance: false } } }),
    ),
    "fail",
  );
});

test("a just-applied candidate is scoped by its session before the list refreshes", () => {
  const current = state({
    candidates: { "session-A": [] },
    applied: { sessionId: "session-A", runId: "run-new" },
    candidateVerdict: {
      runId: "run-new",
      report: { ranAll: true, acceptance: true },
    },
  });
  assert.equal(summary.activeReviewVerificationState(current), "pass");

  current.applied.sessionId = "session-B";
  assert.equal(summary.activeReviewVerificationState(current), "not_run");
});


test("approval cannot authorize the old base during a head switch before rebase finishes", () => {
  assert.equal(summary.activeReviewApprovalState(state({head: "run-A"})), null);
  const rebased = state({head: "run-A"});
  rebased.draft.plan.base = {runId: "run-A"};
  assert.equal(summary.activeReviewApprovalState(rebased), "pending");
});


test("a previous document's head hint cannot block this document's valid approval", () => {
  assert.equal(summary.activeReviewApprovalState(state({head: "run-B"})), "pending");
});
