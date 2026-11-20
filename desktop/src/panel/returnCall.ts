/**
 * The 돌려보내기 call, pure so the payload can be tested without a runtime.
 */
import type { ApprovalRecord } from "../types";

/** The person approving or returning from this app. Never a reason. */
export const APPROVER = "host-operator";

export interface ApprovalBindingRef {
  approvalId: string;
  planId: string;
  planHash: string;
}

export interface ResolvePayload extends ApprovalBindingRef {
  decision: "approved" | "rejected";
  approver: string;
  reason?: string;
}

/**
 * The 돌려보내기 payload. The person's words go in `reason`; `approver` is
 * always the app's operator name, whatever the reason says (D1 §3c-12,
 * advisor D).
 */
export function returnPayload(binding: ApprovalBindingRef, reason: string): ResolvePayload {
  const trimmed = reason.trim();
  return {
    approvalId: binding.approvalId,
    planId: binding.planId,
    planHash: binding.planHash,
    decision: "rejected",
    approver: APPROVER,
    ...(trimmed ? { reason: trimmed } : {}),
  };
}

export interface ReturnResult {
  approval: ApprovalRecord;
  /** False when the runtime predates `reason` and refused the field. */
  reasonStored: boolean;
}

type Call = <T>(method: string, params?: Record<string, unknown>) => Promise<T>;

function errorCode(e: unknown): string | null {
  return e && typeof e === "object" && typeof (e as { code?: unknown }).code === "string" ? (e as { code: string }).code : null;
}

/**
 * Resolve an approval as returned. A runtime without the `reason` field
 * (before WP0 merges) refuses it as `unknown_field`; the return then goes
 * through without it, and the reason is never moved into `approver`.
 */
export async function resolveReturnWith(call: Call, binding: ApprovalBindingRef, reason: string): Promise<ReturnResult> {
  const payload = returnPayload(binding, reason);
  try {
    const r = await call<{ approval: ApprovalRecord }>("approval/resolve", { ...payload });
    return { approval: r.approval, reasonStored: payload.reason !== undefined };
  } catch (e) {
    if (errorCode(e) !== "unknown_field" || payload.reason === undefined) throw e;
    const { reason: _dropped, ...without } = payload;
    void _dropped;
    const r = await call<{ approval: ApprovalRecord }>("approval/resolve", { ...without });
    return { approval: r.approval, reasonStored: false };
  }
}
