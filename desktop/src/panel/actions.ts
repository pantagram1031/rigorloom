/**
 * Panel behaviour (J1 §5: new behaviour goes in `<dir>/actions.ts`).
 *
 * Exposes `decide(itemId, decision)` and `openApproval()`. Everything that
 * reaches the runtime still goes through the frozen `actions.ts` gate
 * (revalidate → approval/request → approval/resolve → plan/apply); this file
 * decides WHAT is in the plan when it gets there.
 */
import {
  approveAndApplyFromDialog,
  removeOp,
  reproposeDraft,
  revisionNumberFor,
  sendInstruction,
  setExpandedChangeId,
  setSelectedChangeId,
  stopInstruction,
  clearQueue,
} from "../actions";
import {
  canConfirm,
  canDecide,
  countChanges,
  filterChanges,
  gateState,
  idsForApproval,
  idsToDrop,
  nextPending,
  recordDecision,
  stepSelection as stepIn,
  type ChangeSetView,
  type Decision,
  type TickId,
} from "../model/changes";
import { getState, headCandidate, opSignature, showToast } from "../store";
import { markExternalPlanDismissed } from "../workspace/externalPlan";
import { activeApprovalBinding } from "../workspace/reviewSummary";
import { captureConfirmation } from "../workspace/trust";
import { clearSheetConfirmation, prepareSheetConfirmation } from "../workspace/sheetConfirmation";
import { tp } from "./i18n";
import { resolveReturn, styleCheck } from "./rpc";
import { latestView, panelSlice, type PanelTab } from "./state";

function doc(): string | null {
  return getState().activeSessionId;
}

function view(): ChangeSetView | null {
  return latestView(doc());
}

function lang() {
  return getState().language;
}

/** Select a change on the panel and the page. */
export function select(itemId: string | null): void {
  setSelectedChangeId(itemId);
  setExpandedChangeId(itemId);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("rigorloom:select-change", { detail: { itemId } }));
  }
}

export function selectedId(): string | null {
  return getState().selectedChangeId;
}

/** J / K inside the visible (filtered) list. */
export function step(delta: 1 | -1): void {
  const v = view();
  if (!v) return;
  const visible = filterChanges(v.items, panelSlice.get(doc()).filter);
  const next = stepIn(visible, selectedId(), delta);
  if (next) select(next.id);
}

/**
 * Record a decision on one change. Refused on a stale set (Y and N are
 * disabled there). After 받아들이기 or 빼기 the selection moves to the next
 * undecided change.
 */
export function decide(itemId: string, decision: Decision): boolean {
  const d = doc();
  const v = view();
  if (!canDecide(v)) return false;
  const item = v!.items.find((it) => it.id === itemId);
  if (!item) return false;
  panelSlice.set(d, (prev) => ({
    decisions: recordDecision(prev.decisions, item, decision),
    undo: [...prev.undo, { id: item.id, prev: prev.decisions[item.id] ?? null }].slice(-200),
  }));
  if (decision !== "pending") {
    const after = latestView(d);
    const items = after ? after.items.map((it) => (it.id === itemId ? { ...it, decision } : it)) : [];
    const next = nextPending(items, itemId);
    if (next) select(next.id);
  }
  return true;
}

/** `U`: undo the last decision. */
export function undoDecision(): boolean {
  const d = doc();
  if (!canDecide(view())) return false;
  const stack = panelSlice.get(d).undo;
  const last = stack[stack.length - 1];
  if (!last) return false;
  panelSlice.set(d, (prev) => {
    const decisions = { ...prev.decisions };
    if (last.prev) decisions[last.id] = last.prev;
    else delete decisions[last.id];
    return { decisions, undo: prev.undo.slice(0, -1) };
  });
  select(last.id);
  return true;
}

/** `Ctrl+Shift+Y`: accept every change that is still 대기. */
export function acceptAll(): boolean {
  const d = doc();
  const v = view();
  if (!canDecide(v)) return false;
  panelSlice.set(d, (prev) => {
    let decisions = prev.decisions;
    const undo = prev.undo.slice();
    for (const item of v!.items) {
      if (item.decision !== "pending") continue;
      undo.push({ id: item.id, prev: decisions[item.id] ?? null });
      decisions = recordDecision(decisions, item, "accepted");
    }
    return { decisions, undo: undo.slice(-200) };
  });
  return true;
}

export function setFilter(filter: Parameters<typeof filterChanges>[1]): void {
  panelSlice.set(doc(), { filter });
}

export function setTab(tab: PanelTab): void {
  panelSlice.set(doc(), { tab });
}

/**
 * `Ctrl+Shift+Enter`. Opens the sheet only when the gate is open; otherwise
 * the footer reason pulses and nothing opens.
 */
export function openApproval(): boolean {
  const d = doc();
  const v = view();
  const st = panelSlice.get(d);
  const gate = gateState(v, { busy: st.confirmPhase !== "idle" && st.confirmPhase !== "failed" });
  if (!gate.canApprove) {
    panelSlice.set(d, (prev) => ({ pulse: prev.pulse + 1, tab: "changes" }));
    return false;
  }
  panelSlice.set(d, {
    sheetOpen: true,
    sheetFor: v!.planHash,
    ticks: [],
    tab: "changes",
    returnOpen: false,
    confirmError: null,
    confirmPhase: "idle",
  });
  return true;
}

export function closeApproval(): void {
  const d = doc();
  const phase = panelSlice.get(d).confirmPhase;
  if (phase !== "idle" && phase !== "failed") return;
  clearSheetConfirmation();
  panelSlice.set(d, { sheetOpen: false, sheetFor: null, ticks: [], confirmPhase: "idle", confirmError: null });
}

/**
 * The sheet rendered a plan: ask the browser bridge for the single-use
 * confirmation token bound to this document, plan and base. Only the plan
 * the sheet was opened for, and only while it is still the live one.
 */
export function prepareConfirmation(): void {
  const d = doc();
  const v = view();
  if (!d || !v || panelSlice.get(d).sheetFor !== v.planHash) return;
  const shown = captureConfirmation(getState(), []);
  if (!shown || shown.sessionId !== d || shown.planHash !== v.planHash) return;
  prepareSheetConfirmation(shown);
}

export function toggleTick(tick: TickId): void {
  panelSlice.set(doc(), (prev) => ({
    ticks: prev.ticks.includes(tick) ? prev.ticks.filter((x) => x !== tick) : [...prev.ticks, tick],
  }));
}

function waitFor(predicate: () => boolean, ms = 15000): Promise<boolean> {
  return new Promise((resolve) => {
    const started = Date.now();
    const tick = () => {
      if (predicate()) resolve(true);
      else if (Date.now() - started > ms) resolve(false);
      else setTimeout(tick, 40);
    };
    tick();
  });
}

/** The acknowledgement keys the trust gate knows, from the sheet's ticks. */
function acknowledgementsFor(ticks: readonly TickId[]): string[] {
  return [...(ticks.includes("facts") ? ["changed_facts"] : []), ...(ticks.includes("test") ? ["mock"] : [])];
}

/**
 * `승인` in the sheet. The plan that reaches the runtime holds the 받아들임
 * changes and nothing else: any 뺌 (or, defensively, 대기) op is taken out of
 * the draft first, the plan is re-proposed, and the confirm refuses to go on
 * unless the re-proposed plan holds exactly the accepted ops, unchanged, on
 * the same document and the same base.
 *
 * Trust: the confirmation is captured at the click from the sheet as
 * rendered (this document, this plan, this base, these ticks), the same way
 * the v1 approval dialog does it. Every wait after the click ends with a
 * check against it; the frozen gate in `actions.ts` re-checks after each of
 * its own waits. A plan that changed under the sheet is never applied.
 */
export async function confirmApproval(): Promise<boolean> {
  const d = doc();
  const v = view();
  const st = panelSlice.get(d);
  const gate = gateState(v, { busy: st.confirmPhase !== "idle" && st.confirmPhase !== "failed" });
  if (!d || !v || !canConfirm(v, st.ticks, gate)) return false;
  // The person reviewed one plan; a different one under the sheet is refused.
  if (st.sheetFor !== v.planHash) {
    panelSlice.set(d, { sheetOpen: false, sheetFor: null, ticks: [] });
    return false;
  }
  const acknowledgements = acknowledgementsFor(st.ticks);
  const live = getState();
  const shown = captureConfirmation(live, acknowledgements);
  if (!shown || shown.sessionId !== d || shown.planHash !== st.sheetFor) {
    panelSlice.set(d, { sheetOpen: false, sheetFor: null, ticks: [] });
    return false;
  }
  const accepted = new Set(idsForApproval(v.items));
  const drop = idsToDrop(v.items);
  // What each accepted change does, as the person saw it.
  const seen = new Map(live.draft.ops.filter((op) => accepted.has(op.opId)).map((op) => [op.opId, opSignature(op)]));
  const counts = countChanges(v.items);
  const proposerKinds = new Set(v.items.filter((it) => accepted.has(it.id)).map((it) => it.source));
  const record = {
    count: accepted.size,
    facts: v.items.filter((it) => accepted.has(it.id) && it.guard.status === "changed").length,
    attn: counts.attn,
    checked: v.items.every((it) => it.guard.status !== "not_checked"),
    proposer:
      proposerKinds.size === 1
        ? ([...proposerKinds][0] === "user" ? "user" : [...proposerKinds][0] === "test" ? "test" : "agent")
        : ("mixed" as const),
  } as const;
  const fail = (): false => {
    // A broken binding asks for a fresh confirmation: the ticks clear.
    panelSlice.set(d, { confirmPhase: "failed", confirmError: tp("apply_failed", lang()), ticks: [] });
    return false;
  };
  if (seen.size !== accepted.size) return fail();

  try {
    let confirmed = shown;
    if (drop.length > 0) {
      panelSlice.set(d, { confirmPhase: "pruning", confirmError: null });
      for (const id of drop) await removeOp(id);
      const settled = await waitFor(() => {
        const s = getState();
        return s.draft.phase !== "starting" && Boolean(s.draft.plan);
      });
      if (!settled) return fail();
      // The re-proposed plan has a new hash; it is bound again only if it is
      // the same document on the same base holding exactly what was accepted.
      const next = captureConfirmation(getState(), acknowledgements);
      if (
        !next ||
        next.sessionId !== shown.sessionId ||
        next.baseDigest !== shown.baseDigest ||
        next.baseRunId !== shown.baseRunId
      ) {
        return fail();
      }
      confirmed = next;
    }
    const s = getState();
    const exact =
      s.draft.ops.length === seen.size && s.draft.ops.every((op) => seen.get(op.opId) === opSignature(op));
    if (
      !exact ||
      !s.draft.plan ||
      s.draft.plan.planId !== confirmed.planId ||
      s.draft.plan.planHash !== confirmed.planHash ||
      s.draft.validation?.ok !== true
    ) {
      return fail();
    }
    panelSlice.set(d, { confirmPhase: "applying" });
    const done = await approveAndApplyFromDialog(confirmed, "host-operator");
    if (!done) return fail();
    const after = getState();
    const outcome = after.applyOutcomes?.[d];
    if (outcome?.applied && after.draft.ops.length === 0) {
      const revision = revisionNumberFor(after, d, outcome.applied.runId) ?? 1;
      panelSlice.set(d, {
        confirmPhase: "idle",
        sheetOpen: false,
        ticks: [],
        decisions: {},
        undo: [],
        filter: "all",
        applied: { revision, atUtc: new Date().toISOString(), ...record },
        returned: null,
      });
      return true;
    }
    return fail();
  } catch {
    return fail();
  }
}

export function openReturn(): boolean {
  const v = view();
  if (!v || v.items.length === 0) return false;
  panelSlice.set(doc(), { returnOpen: true, sheetOpen: false });
  return true;
}

export function closeReturn(): void {
  panelSlice.set(doc(), { returnOpen: false });
}

/**
 * 돌려보내기. Agent changes leave the active set; the reason is stored as the
 * reason (rpc.returnPayload), never as the approver.
 */
export async function returnProposal(reason: string, requestAgain = false): Promise<boolean> {
  const d = doc();
  const s = getState();
  const v = view();
  if (!d || !v) return false;
  const count = v.items.filter((it) => it.source !== "user").length;
  if (s.draft.plan?.planId) markExternalPlanDismissed(d, s.draft.plan.planId);
  const binding = activeApprovalBinding(s);
  if (binding && s.approval?.state === "pending") {
    await resolveReturn(binding, reason);
  }
  // 내 입력 rows stay; agent rows leave the active set.
  const keep = s.draft.ops.filter((op) => op.origin === "user").map((op) => op.opId);
  if (keep.length === 0) await clearQueue();
  else for (const op of s.draft.ops) if (op.origin !== "user") await removeOp(op.opId);
  panelSlice.set(d, {
    returnOpen: false,
    decisions: {},
    undo: [],
    returned: { count, reason: reason.trim(), atUtc: new Date().toISOString(), requested: requestAgain },
  });
  if (requestAgain && reason.trim()) {
    await sendInstruction(reason.trim());
    showToast(tp("return_done", lang()), 2000);
  } else {
    showToast(tp("return_done_no_request", lang()), 2400);
  }
  return true;
}

/** Stale banner: propose the same ops again on the current revision. */
export async function proposeAgainOnHead(): Promise<void> {
  await reproposeDraft();
}

export async function sendRequest(text: string): Promise<boolean> {
  return sendInstruction(text);
}

export async function cancelRequest(): Promise<boolean> {
  return stopInstruction();
}

export function focusComposer(): void {
  panelSlice.set(doc(), (prev) => ({ tab: prev.tab === "checks" ? "agent" : prev.tab }));
  if (typeof document === "undefined") return;
  setTimeout(() => document.querySelector<HTMLTextAreaElement>('[data-testid="composer-input"]')?.focus(), 0);
}

export function clearContext(): void {
  panelSlice.set(doc(), { context: null });
}

/** F8 / `문체 점검`: run the read-only style check on what the page shows. */
export async function runStyleCheck(): Promise<void> {
  const d = doc();
  if (!d) return;
  panelSlice.set(d, (prev) => ({ tab: "checks", style: { ...prev.style, phase: "running", error: null } }));
  try {
    // The head of THIS document; the store's `head` may name another tab's run.
    const result = await styleCheck(d, headCandidate(getState())?.runId ?? null);
    panelSlice.set(d, { style: { phase: "ready", findings: result.findings, error: null } });
  } catch (e) {
    const err = e as { code?: string };
    panelSlice.set(d, { style: { phase: "failed", findings: [], error: err?.code ?? "style_unavailable" } });
  }
}
