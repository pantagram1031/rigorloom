/**
 * The panel's runtime calls (J1 §5: `runtime.ts` is frozen after trust; new
 * calls are wrapped here).
 */
import * as rt from "../runtime";

export { APPROVER, returnPayload, type ApprovalBindingRef, type ResolvePayload, type ReturnResult } from "./returnCall";
import { resolveReturnWith, type ApprovalBindingRef, type ReturnResult } from "./returnCall";

/** Resolve an approval as returned, with the reason in `reason`. */
export function resolveReturn(binding: ApprovalBindingRef, reason: string): Promise<ReturnResult> {
  return resolveReturnWith(rt.call, binding, reason);
}

export interface StyleCheckFinding {
  rule: string;
  message: string;
  excerpt: string;
  at: string | null;
}

export interface StyleCheckResult {
  ok: boolean;
  docType: string | null;
  findings: StyleCheckFinding[];
}

/** `POST /api/style/check` (runtime/scripts/rt_ui_style.py). Read-only. */
export async function styleCheck(sessionId: string, runId: string | null): Promise<StyleCheckResult> {
  const res = await fetch("/api/style/check", {
    method: "POST",
    headers: rt.tokenHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ sessionId, ...(runId ? { runId } : {}) }),
  });
  const body = (await res.json().catch(() => null)) as
    | (StyleCheckResult & { error?: { code: string; message: string } })
    | null;
  if (!res.ok || !body || body.ok === false) {
    throw body?.error ?? { code: "style_unavailable", message: `HTTP ${res.status}` };
  }
  return body;
}
