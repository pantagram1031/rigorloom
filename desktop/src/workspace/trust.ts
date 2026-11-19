/**
 * The trust rules every review surface shares, as plain functions.
 *
 * The UX11 review found that the approval gate itself held, but WHAT was
 * offered for approval could lie: an outdated proposal looked current, a test
 * agent looked like a real one, another document's draft looked like this
 * one's, a returned change came back unannounced, and guard warnings the CLI
 * printed were invisible in the app. Each rule below is the single place one
 * of those answers is computed, so the review list, the approval dialog, Fill
 * and History cannot disagree about it.
 *
 * Nothing here touches the store or the runtime. Callers pass state in and get
 * plain data or vocabulary text back, which is what lets the node tests import
 * this file directly.
 */
import {
  errorCodeMessage,
  guardCategoryLabel,
  t,
  type VocabularyKey,
} from "../i18n/vocabulary.ts";
import { opSignature } from "../store.ts";
import type {
  ApprovalPhase,
  Draft,
  QueuedOp,
} from "../store.ts";
import type {
  ApprovalRecord,
  GuardDiffParagraph,
  OperationPlan,
  PlanFinding,
  PlanValidation,
  RegionText,
  UiLanguage,
} from "../types.ts";
import type { IndexedChange, RowGuardAudit } from "./guardHelper.ts";

// --- hashes -------------------------------------------------------------------

/** How much of a 64-character hash the approval dialog shows. */
export const SHORT_HASH_LENGTH = 12;

export function shortHash(hash: string | null | undefined): string {
  if (!hash) return "—";
  return hash.slice(0, SHORT_HASH_LENGTH);
}

// --- 1. a plan behind the head ---------------------------------------------------

/** The runtime's `plan_behind_head` finding, when the validation carries one. */
export function behindHeadFinding(
  validation: PlanValidation | null | undefined,
): PlanFinding | null {
  return validation?.hard?.find((row) => row.code === "plan_behind_head") ?? null;
}

/**
 * The banner sentence for an outdated plan, naming the revision it would drop.
 *
 * `revisionOf` maps a run id to its 수정본 number; the head's number is the one
 * a person recognises from History and the top bar.
 */
export function behindHeadMessage(
  finding: PlanFinding,
  revisionOf: (runId: string) => number | null,
  lang: UiLanguage,
): string {
  const headRunId = typeof finding.headRunId === "string" ? finding.headRunId : null;
  const revision = headRunId ? revisionOf(headRunId) : null;
  return revision !== null
    ? t("review_behind_head_banner", lang, [revision])
    : errorCodeMessage("plan_behind_head", lang);
}

/** Whether an approval was returned by the runtime because a newer 수정본 exists. */
export function isSupersededApproval(approval: ApprovalRecord | null | undefined): boolean {
  return approval?.state === "rejected" && approval.reasonCode === "superseded_by_newer_candidate";
}

// --- 2. who proposed it ----------------------------------------------------------

export type ProposerKind = "agent" | "user" | "mock";

/** The proposer names of the bundled test agents (`rt_plan.MOCK_PROPOSERS`). */
export const MOCK_PROPOSERS: ReadonlySet<string> = new Set([
  "agenthost-mock",
  "rigorloom-mock-agent",
]);

/** The proposer this shell's own plans carry (`runtime.ts` `proposePlan`). */
export const DESKTOP_PROPOSER = "rigorloom-desktop";

export function proposerKind(
  proposer: string | null | undefined,
  provenance?: string | null,
): ProposerKind {
  if (provenance === "mock" || (proposer && MOCK_PROPOSERS.has(proposer))) return "mock";
  if (!proposer || proposer === DESKTOP_PROPOSER) return "user";
  return "agent";
}

export function proposerLabel(kind: ProposerKind, lang: UiLanguage): string {
  if (kind === "mock") return t("proposer_mock", lang);
  if (kind === "agent") return t("proposer_agent", lang);
  return t("proposer_user", lang);
}

/** The kind one queued op came from. A test agent's op stays a test op. */
export function opProposerKind(op: QueuedOp): ProposerKind {
  if (op.provenance === "mock") return "mock";
  if (op.origin === "agent") return proposerKind(op.proposer ?? "agent", null);
  return "user";
}

/**
 * Who a whole queue came from, for the dialog's one-line summary.
 *
 * Any test op makes the queue a test proposal: approving it is approving a
 * test value, and that must be the first thing the line says.
 */
export function draftProposerKind(draft: Pick<Draft, "ops">): ProposerKind {
  const kinds = draft.ops.map(opProposerKind);
  if (kinds.includes("mock")) return "mock";
  if (kinds.includes("agent")) return "agent";
  return "user";
}

// --- 3. drafts belong to one document ---------------------------------------------

export interface ParkedDraft {
  draft: Draft;
  approval: ApprovalRecord | null;
  approvalPhase: ApprovalPhase;
  redoStack: QueuedOp[];
}

export interface DraftSlot {
  draft: Draft;
  approval: ApprovalRecord | null;
  approvalPhase: ApprovalPhase;
  redoStack: QueuedOp[];
}

/**
 * Put the outgoing document's queue aside and bring the incoming one's back.
 *
 * The queue used to be one global value that followed the person to the next
 * document, where it showed up as pending changes for a file it was never
 * proposed against (UX11 finding 3). Each document now has its own slot. The
 * outgoing draft is parked under the session IT names — not under whichever
 * document happened to be active — so a draft that had already leaked cannot
 * leak again.
 */
export function swapSessionDrafts(
  parked: Record<string, ParkedDraft>,
  current: DraftSlot,
  toSessionId: string,
  emptyDraft: Draft,
): { parked: Record<string, ParkedDraft>; slot: DraftSlot } {
  const next: Record<string, ParkedDraft> = { ...parked };
  const owner = current.draft.sessionId;
  if (owner && owner !== toSessionId) {
    if (current.draft.ops.length > 0) {
      next[owner] = {
        draft: current.draft,
        approval: current.approval,
        approvalPhase: current.approvalPhase,
        redoStack: current.redoStack,
      };
    } else {
      delete next[owner];
    }
  }
  if (owner === toSessionId) {
    return { parked: next, slot: current };
  }
  const incoming = next[toSessionId];
  delete next[toSessionId];
  if (incoming) {
    return { parked: next, slot: { ...incoming } };
  }
  return {
    parked: next,
    slot: { draft: emptyDraft, approval: null, approvalPhase: "idle", redoStack: [] },
  };
}

/** The ops a re-propose must refuse: anything that came from another document. */
export function foreignOps(
  draft: Pick<Draft, "ops" | "sessionId">,
  sessionId: string | null,
): QueuedOp[] {
  if (!sessionId) return [];
  return draft.ops.filter((op) => (op.sessionId ?? draft.sessionId ?? sessionId) !== sessionId);
}

// --- 4. the head is what the person sees ---------------------------------------------

export function headTextsKey(sessionId: string, runId: string): string {
  return `${sessionId}:${runId}`;
}

/** Which text the page shows: the head's, unless the person asked for the original. */
export function displayTextsFor(
  sourceTexts: RegionText[],
  headTexts: RegionText[] | undefined,
  showingOriginal: boolean,
): { texts: RegionText[]; subject: "head" | "source" } {
  if (headTexts && !showingOriginal) return { texts: headTexts, subject: "head" };
  return { texts: sourceTexts, subject: "source" };
}

/** The sub-bar sentence above the page: what is drawn, then the preview caveat. */
export function sheetSubjectLabel(
  options: {
    mode: "review" | "fill";
    hasChanges: boolean;
    headRevision: number | null;
    showingOriginal: boolean;
  },
  lang: UiLanguage,
): string {
  const { mode, hasChanges, headRevision, showingOriginal } = options;
  if (headRevision === null) {
    return t(mode === "fill" || !hasChanges ? "page_label_fill" : "page_label_review", lang);
  }
  if (showingOriginal) return t("page_label_original", lang);
  if (mode === "review" && hasChanges) {
    return t("page_label_review_on_revision", lang, [headRevision]);
  }
  return t("page_label_revision", lang, [headRevision]);
}

function cellTextByKey(texts: readonly RegionText[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const region of texts) {
    if (!region.addr) continue;
    map.set(`c:${region.table ?? 0}:${region.addr.row}:${region.addr.col}`, region.text ?? "");
  }
  return map;
}

/**
 * Blanks that hold a value: typed into the queue, or already filled in the head.
 *
 * Counting only the queue made Fill say `9개 중 0개 입력` right after the
 * person's values were approved (UX11 finding 4). A value already in the head
 * counts when it differs from the source's own text for that blank, so a
 * placeholder the form shipped with is never counted as an entry.
 */
export function filledBlankCount(
  blankKeys: readonly string[],
  ops: readonly QueuedOp[],
  sourceTexts: readonly RegionText[],
  headTexts: readonly RegionText[] | null,
): number {
  const queued = new Set<string>();
  for (const op of ops) {
    if ((op.kind === "fill_cell" || op.kind === "replace_at_cell") && op.text.trim().length > 0) {
      queued.add(`c:${op.table}:${op.row}:${op.col}`);
    }
  }
  const source = cellTextByKey(sourceTexts);
  const head = headTexts ? cellTextByKey(headTexts) : new Map<string, string>();
  let count = 0;
  for (const key of blankKeys) {
    if (queued.has(key)) {
      count += 1;
      continue;
    }
    const after = (head.get(key) ?? "").trim();
    if (after.length > 0 && after !== (source.get(key) ?? "").trim()) count += 1;
  }
  return count;
}

// --- 5. guard warnings stay visible ---------------------------------------------------

export type GuardTagKind = "changed" | "new_values" | "removed_with_guide";

export interface GuardValueDelta {
  category: string;
  added: string[];
  removed: string[];
}

export interface GuardTag {
  kind: GuardTagKind;
  deltas: GuardValueDelta[];
}

function countMap(value: unknown): Map<string, number> {
  const out = new Map<string, number>();
  if (Array.isArray(value)) {
    for (const item of value) {
      const key = typeof item === "string" ? item : JSON.stringify(item);
      out.set(key, (out.get(key) ?? 0) + 1);
    }
  } else if (value && typeof value === "object") {
    for (const [key, n] of Object.entries(value as Record<string, unknown>)) {
      const count = typeof n === "number" ? n : 1;
      if (count > 0) out.set(key, count);
    }
  }
  return out;
}

/**
 * The values a guard paragraph gained and lost, per category.
 *
 * `changes` rows are the prose-fidelity checker's own counts
 * (`{kind, before, after}`), so the values shown are the ones the checker
 * counted, not a second guess made here.
 */
export function guardValueDeltas(para: GuardDiffParagraph | null | undefined): GuardValueDelta[] {
  if (!para) return [];
  const out: GuardValueDelta[] = [];
  for (const raw of para.changes as unknown[]) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as { kind?: unknown; before?: unknown; after?: unknown };
    const category = typeof row.kind === "string" ? row.kind : "";
    if (!category) continue;
    const before = countMap(row.before);
    const after = countMap(row.after);
    const added: string[] = [];
    const removed: string[] = [];
    for (const key of new Set([...before.keys(), ...after.keys()])) {
      const delta = (after.get(key) ?? 0) - (before.get(key) ?? 0);
      if (delta > 0) added.push(key);
      if (delta < 0) removed.push(key);
    }
    if (added.length > 0 || removed.length > 0) out.push({ category, added, removed });
  }
  return out;
}

/**
 * The tag a collapsed row carries when its paragraph failed the guard.
 *
 * `changed` is the existing 바뀐 사실 verdict and keeps its pill. The other two
 * are the expected outcomes of filling a form — a number or date typed into a
 * blank, or an expression that disappears together with the guide text it was
 * part of — and get a neutral tag. Before this, those rows showed nothing at
 * all, while `rigorloom guard` printed CHANGED for the same paragraphs.
 */
export function guardTagFor(
  change: Pick<IndexedChange, "op">,
  audit: Pick<RowGuardAudit, "status" | "paragraph"> | null | undefined,
): GuardTag | null {
  const para = audit?.paragraph ?? null;
  if (!para || para.pass !== false) return null;
  const deltas = guardValueDeltas(para);
  if (audit?.status === "changed") return { kind: "changed", deltas };
  const removedAny = deltas.some((d) => d.removed.length > 0);
  if (!removedAny) return { kind: "new_values", deltas };
  void change;
  return { kind: "removed_with_guide", deltas };
}

export function guardTagLabel(tag: GuardTag, lang: UiLanguage): string {
  if (tag.kind === "changed") return t("guard_pill_changed", lang);
  if (tag.kind === "new_values") return t("guard_tag_new_values", lang);
  return t("guard_tag_removed_with_guide", lang);
}

function quoteValues(values: readonly string[], max = 2): string {
  const shown = values.slice(0, max).map((v) => `‘${v}’`);
  return values.length > max ? `${shown.join(", ")} …` : shown.join(", ");
}

/** The category as a plain noun (숫자, 날짜, 인용문 …) for value lists. */
const GUARD_NOUN_ALIASES: Record<string, string> = {
  markdown_links: "urls",
  source_ids: "citations",
  tags: "headings",
  protected_spans: "headings",
};

function guardNoun(category: string, lang: UiLanguage): string {
  const key = `guard_noun_${GUARD_NOUN_ALIASES[category] ?? category}`;
  try {
    return t(key as VocabularyKey, lang);
  } catch {
    return guardCategoryLabel(category, lang);
  }
}

function describeDeltas(
  deltas: readonly GuardValueDelta[],
  pick: "added" | "removed" | "both",
  lang: UiLanguage,
): string {
  const parts: string[] = [];
  for (const d of deltas) {
    const label = guardNoun(d.category, lang);
    if (pick === "both") {
      if (d.removed.length > 0 && d.added.length > 0) {
        parts.push(`${label} ${quoteValues(d.removed)} → ${quoteValues(d.added)}`);
      } else if (d.removed.length > 0) {
        parts.push(`${label} ${quoteValues(d.removed)} → ${t("guard_value_gone", lang)}`);
      } else if (d.added.length > 0) {
        parts.push(`${label} ${quoteValues(d.added)}`);
      }
    } else {
      const values = pick === "added" ? d.added : d.removed;
      if (values.length > 0) parts.push(`${label} ${quoteValues(values)}`);
    }
  }
  return parts.join(", ");
}

export interface GuardWarningSummary {
  changed: Array<{ ordinal: number; field: string; detail: string }>;
  removed: Array<{ ordinal: number; field: string; detail: string }>;
  added: Array<{ ordinal: number; field: string; detail: string }>;
}

/** Every failing row, grouped by tag kind, with the values that moved. */
export function guardWarningSummary(
  changes: readonly Pick<IndexedChange, "op" | "opId" | "ordinal" | "fieldLabel">[],
  audits: Record<string, Pick<RowGuardAudit, "status" | "paragraph">>,
  lang: UiLanguage,
): GuardWarningSummary {
  const out: GuardWarningSummary = { changed: [], removed: [], added: [] };
  for (const ch of changes) {
    const tag = guardTagFor(ch, audits[ch.opId]);
    if (!tag) continue;
    if (tag.kind === "changed") {
      out.changed.push({ ordinal: ch.ordinal, field: ch.fieldLabel, detail: describeDeltas(tag.deltas, "both", lang) });
    } else if (tag.kind === "removed_with_guide") {
      out.removed.push({ ordinal: ch.ordinal, field: ch.fieldLabel, detail: describeDeltas(tag.deltas, "removed", lang) });
    } else {
      out.added.push({ ordinal: ch.ordinal, field: ch.fieldLabel, detail: describeDeltas(tag.deltas, "added", lang) });
    }
  }
  return out;
}

function joinItems(items: GuardWarningSummary["changed"], max = 2): string {
  const shown = items
    .slice(0, max)
    .map((it) => (it.detail ? `[${it.ordinal}] ${it.field} ${it.detail}` : `[${it.ordinal}] ${it.field}`));
  return items.length > max ? `${shown.join("; ")} …` : shown.join("; ");
}

/**
 * At most two lines for the approval dialog, with the actual values.
 *
 * True changes come first because they are the ones a person must confirm;
 * the expected kinds share the second line. A dialog that asked for
 * confirmation of "바뀐 사실 1건 · [1] 빈칸 1" without the date that changed was
 * a formality, not a check (GPT review finding 6).
 */
export function guardWarningLines(summary: GuardWarningSummary, lang: UiLanguage): string[] {
  const lines: string[] = [];
  if (summary.changed.length > 0) {
    lines.push(t("approval_warn_changed", lang, [summary.changed.length, joinItems(summary.changed)]));
  }
  if (summary.removed.length > 0) {
    lines.push(t("approval_warn_removed", lang, [summary.removed.length, joinItems(summary.removed)]));
  }
  if (summary.added.length > 0) {
    lines.push(t("approval_warn_added", lang, [summary.added.length, joinItems(summary.added)]));
  }
  return lines.slice(0, 2);
}

/** How many failing paragraphs a summary counts, for the applied-state line. */
export function guardWarningCount(summary: GuardWarningSummary): number {
  return summary.changed.length + summary.removed.length + summary.added.length;
}

// --- 6. the approval dialog ---------------------------------------------------------

/** `원본` or `수정본 N`, for the dialog's base line. */
export function baseLabel(
  baseRunId: string | null | undefined,
  revisionOf: (runId: string) => number | null,
  lang: UiLanguage,
): string {
  if (!baseRunId) return t("base_source", lang);
  const n = revisionOf(baseRunId);
  return n !== null ? t("base_revision", lang, [n]) : t("base_revision_unknown", lang);
}

export type ApplyStep = "checking" | "recording" | "applying" | null;

/** Which step the dialog is on while it is busy, so the wait has a name. */
export function applyStep(phases: {
  submitting: boolean;
  approvalPhase: ApprovalPhase;
  applyPhase: string;
}): ApplyStep {
  if (phases.applyPhase === "starting") return "applying";
  if (phases.approvalPhase === "requesting" || phases.approvalPhase === "resolving") return "recording";
  if (phases.submitting) return "checking";
  return null;
}

export function applyStepLabel(step: ApplyStep, lang: UiLanguage): string | null {
  if (step === "applying") return t("approval_step_applying", lang);
  if (step === "recording") return t("approval_step_recording", lang);
  if (step === "checking") return t("approval_step_checking", lang);
  return null;
}

// --- 7. typed entries survive a reload ------------------------------------------------

export interface SavedDraft {
  ops: QueuedOp[];
  savedUtc: string;
}

/**
 * What of a queue is worth keeping across a reload: the person's own entries.
 *
 * An agent's plan is a runtime record and comes back through the session's
 * event log; a typed value exists nowhere but here until it is proposed, and
 * a reload used to throw it away (UX11 finding 7).
 */
export function savableOps(draft: Pick<Draft, "ops">): QueuedOp[] {
  return draft.ops.filter((op) => op.origin === "user");
}

export function restorableOps(saved: unknown): QueuedOp[] {
  if (!saved || typeof saved !== "object") return [];
  const ops = (saved as { ops?: unknown }).ops;
  if (!Array.isArray(ops)) return [];
  return ops.filter(
    (op): op is QueuedOp =>
      Boolean(op) &&
      typeof op === "object" &&
      typeof (op as QueuedOp).opId === "string" &&
      typeof (op as QueuedOp).kind === "string" &&
      typeof (op as QueuedOp).text === "string" &&
      (op as QueuedOp).origin === "user",
  );
}

// --- 8. the character shape of a typed blank ------------------------------------------

/**
 * The charPr a person's typed value should carry, when the seat demands one.
 *
 * A blank whose own run is superscript or subscript would print the typed
 * value small (T30). The engine already names the body shape it should use;
 * applying it for the person is the fix they would have clicked anyway, and
 * it is said in the row rather than done silently.
 */
export function autoCharPrFor(
  seat: { scriptAnomaly?: boolean; charPrSuggested?: string } | null | undefined,
  declared: string | undefined,
): string | null {
  if (declared) return null;
  if (!seat?.scriptAnomaly || !seat.charPrSuggested) return null;
  return seat.charPrSuggested;
}

/** The first hard finding's sentence, for the collapsed row. */
export function hardReason(findings: readonly PlanFinding[], lang: UiLanguage): string | null {
  const first = findings[0];
  return first ? errorCodeMessage(first.code, lang) : null;
}

/** The one line next to a disabled 승인 that says how many rows block it. */
export function approveBlockedReason(
  input: { hardCount: number; returnedCount: number; behindHead: boolean },
  lang: UiLanguage,
): string | null {
  if (input.behindHead) return t("review_blocked_behind_head", lang);
  if (input.returnedCount > 0) return t("review_blocked_returned", lang, [input.returnedCount]);
  if (input.hardCount > 0) return t("review_blocked_hard", lang, [input.hardCount]);
  return null;
}

// --- 9. a returned change stays returned -----------------------------------------------

export { opSignature };

export function returnedSignatures(ops: readonly QueuedOp[]): string[] {
  return ops.map(opSignature);
}

export function isReturnedOp(op: QueuedOp, returned: readonly string[] | undefined): boolean {
  return Boolean(returned && returned.length > 0 && returned.includes(opSignature(op)));
}

/** Forget the signatures a person just re-added by typing or 다시 넣기. */
export function withoutSignatures(
  returned: readonly string[] | undefined,
  ops: readonly QueuedOp[],
): string[] {
  const drop = new Set(ops.map(opSignature));
  return (returned ?? []).filter((sig) => !drop.has(sig));
}

// --- 10. a 되돌리기 제안 that cannot be fixed is not offered ----------------------------

/** The reasons a dry-run inverse plan failed validation, as one sentence. */
export function undoBlockReason(
  validation: PlanValidation | null | undefined,
  lang: UiLanguage,
): string | null {
  if (!validation || validation.ok) return null;
  const reasons = [...new Set(validation.hard.map((row) => errorCodeMessage(row.code, lang)))];
  return t("err_undo_unfixable", lang, [reasons.slice(0, 2).join(" ")]);
}

/**
 * The op list `plan/propose` takes, built exactly as `setQueue` builds it.
 *
 * Each kind carries the fields its own op declares and no others, because
 * `plan/propose` refuses an op with a field its kind does not define.
 */
export function planOpsPayload(ops: readonly QueuedOp[]): Array<Record<string, unknown>> {
  return ops.map((op) =>
    op.kind === "fill_cell"
      ? {
          opId: op.opId,
          kind: op.kind,
          table: op.table,
          row: op.row,
          col: op.col,
          ...(op.lines !== undefined ? { lines: op.lines } : { text: op.text }),
          ...(op.charPr ? { charPr: op.charPr } : {}),
          ...(op.paraPr ? { paraPr: op.paraPr } : {}),
          ...(op.overwrite ? { overwrite: true } : {}),
        }
      : op.kind === "replace_at_cell"
        ? {
            opId: op.opId,
            kind: op.kind,
            table: op.table,
            row: op.row,
            col: op.col,
            text: op.text,
            ...(op.run !== undefined ? { run: op.run } : {}),
            ...(op.mode !== undefined ? { mode: op.mode } : {}),
            ...(op.expect !== undefined ? { expect: op.expect } : {}),
            ...(op.charPr ? { charPr: op.charPr } : {}),
          }
        : op.kind === "delete_guides"
          ? {
              opId: op.opId,
              kind: op.kind,
              ...(op.color ? { color: op.color } : {}),
              ...(op.charPrIds !== undefined ? { charPrIds: op.charPrIds } : {}),
            }
          : { opId: op.opId, kind: op.kind, atPara: op.atPara, run: op.run, text: op.text },
  );
}

// --- 11. history says who and whether the receipt holds ------------------------------

export type ReceiptCheck = "verified" | "failed" | "pending";

export function historyProvenanceLine(
  input: {
    proposer: string | null | undefined;
    provenance: string | null | undefined;
    receiptCheck: ReceiptCheck;
    acceptance: boolean | null | undefined;
  },
  lang: UiLanguage,
): string {
  const who = proposerLabel(proposerKind(input.proposer, input.provenance), lang);
  const receipt =
    input.receiptCheck === "verified"
      ? t("history_receipt_verified", lang)
      : input.receiptCheck === "failed"
        ? t("history_receipt_failed", lang)
        : t("history_receipt_checking", lang);
  const parts = [t("history_proposer_line", lang, [who]), receipt];
  if (input.acceptance === false) parts.push(t("history_checks_open", lang));
  return parts.join(" · ");
}

/** The approval mode, without raw approver names on the surface. */
export function approvalModeLabel(lang: UiLanguage): string {
  return t("history_approval_method_direct", lang);
}

/** Re-export for callers that only need the plan's own provenance. */
export function planProposerKind(plan: Pick<OperationPlan, "proposer" | "provenance"> | null | undefined): ProposerKind {
  return proposerKind(plan?.proposer ?? null, plan?.provenance ?? null);
}
