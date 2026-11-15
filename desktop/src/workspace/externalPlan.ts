import type { Draft } from "../store";
import type { RegionText, RuntimeEvent } from "../types";

export interface ExternalPlanCandidate {
  planId: string;
  approvalId: string | null;
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

/**
 * Inspect replayed session events for the latest `plan.proposed` event that
 * should be adopted into the Review workspace automatically.
 */
export function findAdoptableExternalPlan(
  sessionId: string | null | undefined,
  events: readonly RuntimeEvent[] | undefined,
  draft: Draft,
): ExternalPlanCandidate | null {
  if (!sessionId || !events || events.length === 0) return null;

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

  const resolvedApprovals = new Set<string>();
  let unresolvedApprovalId: string | null = null;

  for (let i = 0; i < events.length; i += 1) {
    const ev = events[i];
    if (ev.sessionId && ev.sessionId !== sessionId) continue;
    const payload = eventPayload(ev);
    const evPlanId = typeof payload.planId === "string" ? payload.planId : null;
    if (evPlanId !== latestPlanId) continue;

    if (i > latestIndex && ev.kind === "plan.applied") {
      return null;
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
      if (i > latestIndex && state === "rejected") {
        return null;
      }
    }

    if (ev.kind === "approval.requested") {
      const approvalId = typeof payload.approvalId === "string" ? payload.approvalId : null;
      if (approvalId && !resolvedApprovals.has(approvalId)) {
        unresolvedApprovalId = approvalId;
      }
    }
  }

  return {
    planId: latestPlanId,
    approvalId: unresolvedApprovalId,
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
