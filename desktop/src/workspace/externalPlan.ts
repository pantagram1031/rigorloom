import type { Draft } from "../store";
import type { ApprovalRecord, RegionText, RuntimeEvent } from "../types";

export interface ExternalPlanCandidate {
  planId: string;
  approvalId: string | null;
}

export interface PendingExternalApproval {
  planId: string;
  approvalId: string;
}

const dismissedPlansBySession = new Map<string, Set<string>>();

export function markExternalPlanDismissed(sessionId: string, planId: string): void {
  if (!sessionId || !planId) return;
  let set = dismissedPlansBySession.get(sessionId);
  if (!set) {
    set = new Set<string>();
    dismissedPlansBySession.set(sessionId, set);
  }
  set.add(planId);
}

export function isExternalPlanDismissed(sessionId: string, planId: string): boolean {
  return dismissedPlansBySession.get(sessionId)?.has(planId) ?? false;
}

export function clearDismissedExternalPlan(sessionId: string, planId: string): void {
  dismissedPlansBySession.get(sessionId)?.delete(planId);
}

function eventPayload(ev: RuntimeEvent): Record<string, unknown> {
  const withData = ev as RuntimeEvent & { data?: Record<string, unknown> };
  if (withData.data && typeof withData.data === "object") {
    return withData.data;
  }
  if (ev.detail && typeof ev.detail === "object") {
    return ev.detail;
  }
  return {};
}

interface PlanLifecycleScan {
  rejectedOrApplied: boolean;
  unresolvedApprovalId: string | null;
}

function scanPlanLifecycle(
  sessionId: string,
  events: readonly RuntimeEvent[],
  planId: string,
  proposedIndex: number,
): PlanLifecycleScan {
  const resolvedApprovals = new Set<string>();
  let unresolvedApprovalId: string | null = null;

  for (let i = 0; i < events.length; i += 1) {
    const ev = events[i];
    if (ev.sessionId && ev.sessionId !== sessionId) continue;
    const payload = eventPayload(ev);
    const evPlanId = typeof payload.planId === "string" ? payload.planId : null;
    if (evPlanId !== planId) continue;

    if (i > proposedIndex && ev.kind === "plan.applied") {
      return { rejectedOrApplied: true, unresolvedApprovalId: null };
    }

    if (ev.kind === "approval.resolved") {
      const approvalId = typeof payload.approvalId === "string" ? payload.approvalId : null;
      const state = typeof payload.state === "string" ? payload.state : null;
      if (approvalId) {
        resolvedApprovals.add(approvalId);
        if (unresolvedApprovalId === approvalId) {
          unresolvedApprovalId = null;
        }
      }
      if (i > proposedIndex && state === "rejected") {
        return { rejectedOrApplied: true, unresolvedApprovalId: null };
      }
    }

    if (ev.kind === "approval.requested") {
      const approvalId = typeof payload.approvalId === "string" ? payload.approvalId : null;
      if (approvalId && !resolvedApprovals.has(approvalId)) {
        unresolvedApprovalId = approvalId;
      }
    }
  }

  return { rejectedOrApplied: false, unresolvedApprovalId };
}

/**
 * Inspect replayed session events for the latest external `plan.proposed`
 * event that should be adopted into the Review workspace automatically.
 */
export function findAdoptableExternalPlan(
  sessionId: string | null | undefined,
  events: readonly RuntimeEvent[] | undefined,
  draft: Draft,
): ExternalPlanCandidate | null {
  if (!sessionId || !events || events.length === 0) return null;
  if (draft.phase === "starting") return null;

  if (draft.sessionId === sessionId && draft.ops.some((op) => op.origin === "user")) {
    return null;
  }

  let latestIndex = -1;
  let latestPlanId: string | null = null;

  for (let i = 0; i < events.length; i += 1) {
    const ev = events[i];
    if (ev.sessionId && ev.sessionId !== sessionId) continue;
    if (ev.kind !== "plan.proposed") continue;
    const payload = eventPayload(ev);
    const proposer = typeof payload.proposer === "string" ? payload.proposer : null;
    if (proposer === "rigorloom-desktop") continue;
    const planId = typeof payload.planId === "string" ? payload.planId : null;
    if (planId) {
      latestIndex = i;
      latestPlanId = planId;
    }
  }

  if (!latestPlanId || latestIndex < 0) return null;
  if (isExternalPlanDismissed(sessionId, latestPlanId)) return null;
  if (draft.sessionId === sessionId && draft.plan?.planId === latestPlanId) {
    return null;
  }

  const scan = scanPlanLifecycle(sessionId, events, latestPlanId, latestIndex);
  if (scan.rejectedOrApplied) return null;

  return {
    planId: latestPlanId,
    approvalId: scan.unresolvedApprovalId,
  };
}

/**
 * Find an unresolved external `approval.requested` event belonging to the
 * currently adopted external draft when SSE delivered it after `plan.proposed`.
 */
export function findPendingExternalApproval(
  sessionId: string | null | undefined,
  events: readonly RuntimeEvent[] | undefined,
  draft: Draft,
  approval: ApprovalRecord | null | undefined,
): PendingExternalApproval | null {
  const planId = draft.plan?.planId ?? null;
  if (!sessionId || !events || events.length === 0 || !planId) return null;
  if (draft.sessionId !== sessionId || draft.phase !== "ready") return null;
  if (isExternalPlanDismissed(sessionId, planId)) return null;
  if (draft.ops.some((op) => op.origin === "user")) return null;

  let proposedIndex = -1;
  let proposer: string | null = null;
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    if (ev.sessionId && ev.sessionId !== sessionId) continue;
    if (ev.kind !== "plan.proposed") continue;
    const payload = eventPayload(ev);
    if (payload.planId === planId) {
      proposedIndex = i;
      proposer = typeof payload.proposer === "string" ? payload.proposer : null;
      break;
    }
  }
  if (proposedIndex < 0 || proposer === "rigorloom-desktop") return null;

  const scan = scanPlanLifecycle(sessionId, events, planId, proposedIndex);
  if (scan.rejectedOrApplied || !scan.unresolvedApprovalId) return null;
  if (
    approval &&
    approval.planId === planId &&
    approval.approvalId === scan.unresolvedApprovalId
  ) {
    return null;
  }

  return {
    planId,
    approvalId: scan.unresolvedApprovalId,
  };
}

/**
 * True when session events record a `plan.proposed` that has not yet been
 * resolved as `rejected` or applied via `plan.applied`.
 */
export function hasLiveUnappliedPlanInEvents(
  events: readonly RuntimeEvent[] | undefined,
  sessionId?: string | null,
): boolean {
  if (!events || events.length === 0) return false;
  const live = new Set<string>();
  for (const ev of events) {
    if (sessionId && ev.sessionId && ev.sessionId !== sessionId) continue;
    const payload = eventPayload(ev);
    const planId = typeof payload.planId === "string" ? payload.planId : null;
    if (!planId) continue;
    const evSessionId = ev.sessionId ?? sessionId ?? null;
    if (ev.kind === "plan.proposed") {
      if (evSessionId && isExternalPlanDismissed(evSessionId, planId)) continue;
      live.add(planId);
    } else if (ev.kind === "plan.applied") {
      live.delete(planId);
    } else if (ev.kind === "approval.resolved") {
      const state = typeof payload.state === "string" ? payload.state : null;
      const decision = typeof payload.decision === "string" ? payload.decision : null;
      if (state === "rejected" || decision === "rejected") {
        live.delete(planId);
      }
    }
  }
  return live.size > 0;
}

/**
 * Convert the flat `RegionText[]` array held in store.ts into the keyed lookup
 * map expected by `deriveOpFieldLabel`.
 */
export function buildRegionTextMap(
  regions: readonly RegionText[] | undefined,
): Record<string, RegionText> {
  const map: Record<string, RegionText> = {};
  if (!regions) return map;
  for (const r of regions) {
    if (r.addr && typeof r.addr.row === "number" && typeof r.addr.col === "number") {
      map[`c:${r.table ?? 0}:${r.addr.row}:${r.addr.col}`] = r;
    }
    if (typeof r.at_para === "number") {
      map[`p:${r.at_para}`] = r;
    }
  }
  return map;
}
