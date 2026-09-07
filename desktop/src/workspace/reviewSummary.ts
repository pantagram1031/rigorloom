import type { WorkspaceState } from "../store";

export type ReviewVerificationState = "not_run" | "partial" | "pass" | "fail";

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
  const plan = state.draft.plan;
  const approval = state.approval;
  if (
    !state.activeSessionId ||
    state.draft.sessionId !== state.activeSessionId ||
    !plan ||
    !approval ||
    approval.planId !== plan.planId ||
    approval.planHash !== plan.planHash
  ) {
    return null;
  }
  return approval.state;
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
