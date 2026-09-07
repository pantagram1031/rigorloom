import { draftStaleness, type WorkspaceState } from "../store";

export type ReviewVerificationState = "not_run" | "partial" | "pass" | "fail";

export interface ActiveApprovalBinding {
  sessionId: string;
  planId: string;
  planHash: string;
  approvalId: string;
}

/** The exact active document, draft plan, and approval record binding. */
export function activeApprovalBinding(state: WorkspaceState): ActiveApprovalBinding | null {
  const sessionId = state.activeSessionId;
  const plan = state.draft.plan;
  const approval = state.approval;
  if (
    !sessionId ||
    state.draft.sessionId !== sessionId ||
    !plan ||
    plan.sessionId !== sessionId ||
    !approval ||
    approval.planId !== plan.planId ||
    approval.planHash !== plan.planHash ||
    draftStaleness(state) !== null
  ) {
    return null;
  }
  return {
    sessionId,
    planId: plan.planId,
    planHash: plan.planHash,
    approvalId: approval.approvalId,
  };
}

/** Primitive selector for React; does not return a newly allocated binding. */
export function hasActiveApprovalBinding(state: WorkspaceState): boolean {
  return activeApprovalBinding(state) !== null;
}

/** Re-check a captured binding after an asynchronous runtime decision. */
export function approvalBindingIsCurrent(
  state: WorkspaceState,
  expected: ActiveApprovalBinding,
): boolean {
  const current = activeApprovalBinding(state);
  return (
    current !== null &&
    current.sessionId === expected.sessionId &&
    current.planId === expected.planId &&
    current.planHash === expected.planHash &&
    current.approvalId === expected.approvalId
  );
}

/** Whether the same draft/approval still exists even while another session is active. */
export function approvalBindingStillExists(
  state: WorkspaceState,
  expected: ActiveApprovalBinding,
): boolean {
  const plan = state.draft.plan;
  const approval = state.approval;
  return (
    state.draft.sessionId === expected.sessionId &&
    plan?.sessionId === expected.sessionId &&
    plan.planId === expected.planId &&
    plan.planHash === expected.planHash &&
    approval?.approvalId === expected.approvalId &&
    approval.planId === expected.planId &&
    approval.planHash === expected.planHash
  );
}

/** Pending operations that belong to the document currently on screen. */
export function activeReviewQueueCount(state: WorkspaceState): number {
  if (!state.activeSessionId || state.draft.sessionId !== state.activeSessionId) return 0;
  return state.draft.ops.length;
}

/**
 * Approval state for the exact active-session plan, never a leftover approval
 * whose binding belongs to another queue or document.
 */
export function activeReviewApprovalState(state: WorkspaceState): string | null {
  return activeApprovalBinding(state) ? state.approval?.state ?? null : null;
}

/**
 * Canonical apply-time verification for this session. Candidate listings are
 * deliberately unverified; only the receipt-backed `candidateVerdict` can
 * supply a verdict, and its run must belong to the active session.
 */
export function activeReviewVerificationState(
  state: WorkspaceState,
): ReviewVerificationState {
  const sessionId = state.activeSessionId;
  const verdict = state.candidateVerdict;
  if (!sessionId || !verdict) return "not_run";

  const listedHere = (state.candidates[sessionId] ?? []).some(
    (candidate) => candidate.runId === verdict.runId,
  );
  const justAppliedHere =
    state.applied?.sessionId === sessionId && state.applied.runId === verdict.runId;
  if (!listedHere && !justAppliedHere) return "not_run";

  if (!verdict.report.ranAll) return "partial";
  return verdict.report.acceptance ? "pass" : "fail";
}
