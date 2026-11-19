/**
 * The approval sheet's single-use confirmation token (browser bridge only).
 *
 * The loopback bridge records an approval only when `approval/resolve`
 * carries a token it issued for exactly that (session, plan id, plan hash,
 * base digest). The sheet asks for one when it renders a plan (`prepare`),
 * and the confirm hands it over right before the decision (`take`). Holding
 * the bridge's host credential is therefore not enough to approve: the token
 * comes from the sheet path, works once and expires.
 *
 * The native shell talks to the runtime directly, not through the bridge;
 * there `fetch` answers null and no token is sent.
 */
import * as rt from "../runtime";
import type { ConfirmationBinding } from "./trust";

export type SheetBinding = Pick<ConfirmationBinding, "sessionId" | "planId" | "planHash" | "baseDigest">;

export type ConfirmationFetcher = (binding: SheetBinding) => Promise<{ token: string; expiresInMs: number } | null>;

interface Held {
  binding: SheetBinding;
  pending: Promise<{ token: string; expiresAt: number } | null>;
}

/** Ask again this long before the bridge's expiry, so a slow click still works. */
const REFRESH_MARGIN_MS = 15_000;

function sameBinding(a: SheetBinding, b: SheetBinding): boolean {
  return a.sessionId === b.sessionId && a.planId === b.planId && a.planHash === b.planHash && a.baseDigest === b.baseDigest;
}

export function createSheetConfirmations(fetch: ConfirmationFetcher, now: () => number = Date.now) {
  let held: Held | null = null;

  const request = (binding: SheetBinding): Held => {
    const asked = now();
    return {
      binding,
      pending: fetch(binding).then(
        (r) => (r ? { token: r.token, expiresAt: asked + r.expiresInMs } : null),
        () => null,
      ),
    };
  };

  return {
    /** The sheet rendered `binding`: ask the bridge for its token now. */
    prepare(binding: SheetBinding): void {
      if (held && sameBinding(held.binding, binding)) return;
      held = request({ ...binding });
    },

    /**
     * The token for the plan being approved, spent from the holder.
     *
     * The sheet must have prepared one for this document and base. When the
     * confirm re-proposed the plan (뺌 items pruned) or the token is about to
     * expire, a fresh one is asked for the confirmed binding; a confirm with
     * no sheet behind it gets nothing.
     */
    async take(confirmed: SheetBinding): Promise<string | null> {
      const current = held;
      held = null;
      if (!current) return null;
      if (current.binding.sessionId !== confirmed.sessionId || current.binding.baseDigest !== confirmed.baseDigest) {
        return null;
      }
      const got = sameBinding(current.binding, confirmed) ? await current.pending : null;
      if (got && got.expiresAt - REFRESH_MARGIN_MS > now()) return got.token;
      const fresh = await request({ ...confirmed }).pending;
      return fresh?.token ?? null;
    },

    /** The sheet closed. */
    clear(): void {
      held = null;
    },
  };
}

const sheetConfirmations = createSheetConfirmations((binding) => rt.approvalConfirmation(binding));

export const prepareSheetConfirmation = sheetConfirmations.prepare;
export const takeSheetConfirmation = sheetConfirmations.take;
export const clearSheetConfirmation = sheetConfirmations.clear;
