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

/**
 * The proposer names the bundled test agents use. Shown under 자세히 only: a
 * name is a label any caller can write, so it never decides the 시험용 제안
 * tag. That comes from the plan's `provenance`, which the runtime sets from
 * the identity of the provider it launched.
 */
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
  if (provenance === "mock") return "mock";
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
export function draftProposerKind(draft: Pick<Draft, "ops"> & { plan?: Draft["plan"] }): ProposerKind {
  // The runtime's own answer first: a rebuilt plan that repeats a test
  // agent's op keeps provenance "mock" even if the client lost the flag.
  if (draft.plan?.provenance === "mock") return "mock";
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
  max = 2,
): string {
  const parts: string[] = [];
  for (const d of deltas) {
    const label = guardNoun(d.category, lang);
    if (pick === "both") {
      if (d.removed.length > 0 && d.added.length > 0) {
        parts.push(`${label} ${quoteValues(d.removed, max)} → ${quoteValues(d.added, max)}`);
      } else if (d.removed.length > 0) {
        parts.push(`${label} ${quoteValues(d.removed, max)} → ${t("guard_value_gone", lang)}`);
      } else if (d.added.length > 0) {
        parts.push(`${label} ${quoteValues(d.added, max)}`);
      }
    } else {
      const values = pick === "added" ? d.added : d.removed;
      if (values.length > 0) parts.push(`${label} ${quoteValues(values, max)}`);
    }
  }
  return parts.join(", ");
}

/** Every value delta of several paragraphs, merged per category. */
function mergedDeltas(paras: readonly (GuardDiffParagraph | null | undefined)[]): GuardValueDelta[] {
  const byCategory = new Map<string, GuardValueDelta>();
  for (const para of paras) {
    for (const d of guardValueDeltas(para)) {
      const into = byCategory.get(d.category) ?? { category: d.category, added: [], removed: [] };
      for (const v of d.added) if (!into.added.includes(v)) into.added.push(v);
      for (const v of d.removed) if (!into.removed.includes(v)) into.removed.push(v);
      byCategory.set(d.category, into);
    }
  }
  return [...byCategory.values()];
}

export interface GuardWarningItem {
  ordinal: number;
  field: string;
  /** The short form for the two-line summary (at most two values per side). */
  detail: string;
  /** Every value, for the full list under the summary. */
  fullDetail?: string;
}

export interface GuardWarningSummary {
  changed: GuardWarningItem[];
  removed: GuardWarningItem[];
  added: GuardWarningItem[];
  /** Failing paragraphs the checker reported that no row could be tied to. */
  unattributed?: Array<{ paragraph: number; detail: string }>;
}

/** The guard facts the sheet needs beyond the per-row audits. */
export interface GuardCoverage {
  /** Every paragraph each op was tied to, not just the first one. */
  paragraphsByOp?: Record<string, GuardDiffParagraph[]>;
  /** Failing paragraphs no op could be tied to. */
  unattributedFailing?: GuardDiffParagraph[];
}

/**
 * Every failing row, grouped by tag kind, with the values that moved.
 *
 * A row's values come from EVERY paragraph its op was tied to (one fill can
 * touch several), and failing paragraphs no row claims are listed by
 * paragraph number rather than dropped.
 */
export function guardWarningSummary(
  changes: readonly Pick<IndexedChange, "op" | "opId" | "ordinal" | "fieldLabel">[],
  audits: Record<string, Pick<RowGuardAudit, "status" | "paragraph">>,
  lang: UiLanguage,
  coverage: GuardCoverage = {},
): GuardWarningSummary {
  const out: GuardWarningSummary = { changed: [], removed: [], added: [], unattributed: [] };
  for (const ch of changes) {
    const audit = audits[ch.opId];
    const extra = (coverage.paragraphsByOp?.[ch.opId] ?? []).filter((p) => p.pass === false);
    const primary = audit?.paragraph && audit.paragraph.pass === false ? audit.paragraph : extra[0] ?? null;
    const tag = guardTagFor(ch, primary ? { status: audit?.status ?? "kept", paragraph: primary } : audit);
    if (!tag) continue;
    const all = [primary, ...extra.filter((p) => p.paragraph !== primary?.paragraph)];
    const deltas = mergedDeltas(all);
    const pick = tag.kind === "changed" ? "both" : tag.kind === "removed_with_guide" ? "removed" : "added";
    const item: GuardWarningItem = {
      ordinal: ch.ordinal,
      field: ch.fieldLabel,
      detail: describeDeltas(deltas, pick, lang),
      fullDetail: describeDeltas(deltas, pick, lang, Number.POSITIVE_INFINITY),
    };
    if (tag.kind === "changed") out.changed.push(item);
    else if (tag.kind === "removed_with_guide") out.removed.push(item);
    else out.added.push(item);
  }
  for (const para of coverage.unattributedFailing ?? []) {
    out.unattributed!.push({
      paragraph: para.paragraph,
      detail: describeDeltas(guardValueDeltas(para), "both", lang, Number.POSITIVE_INFINITY),
    });
  }
  return out;
}

/**
 * Which acknowledgements the sheet must collect, from the WHOLE guard result.
 *
 * A changed fact on a row, and any failing paragraph no row could be tied to:
 * the person cannot be told it is an expected fill, so they confirm it like a
 * changed fact. Before, an unattributed failing paragraph produced no
 * acknowledgement at all.
 */
export function requiredGuardAcks(
  summary: { changedFactOpIds: readonly string[] } & GuardCoverage,
): { changedFacts: number; unattributed: number; total: number } {
  const changedFacts = summary.changedFactOpIds.length;
  const unattributed = (summary.unattributedFailing ?? []).length;
  return { changedFacts, unattributed, total: changedFacts + unattributed };
}

function joinItems(items: GuardWarningSummary["changed"], max = 2): string {
  const shown = items
    .slice(0, max)
    .map((it) => (it.detail ? `[${it.ordinal}] ${it.field} ${it.detail}` : `[${it.ordinal}] ${it.field}`));
  return items.length > max ? `${shown.join("; ")} …` : shown.join("; ");
}

/**
 * Every warning, one line each, nothing cut: the expandable list under the
 * two-line summary. What the person approves must be readable in full from
 * the sheet itself.
 */
export function guardWarningFullLines(summary: GuardWarningSummary, lang: UiLanguage): string[] {
  const item = (it: GuardWarningItem) => {
    const detail = it.fullDetail ?? it.detail;
    return detail ? `[${it.ordinal}] ${it.field} ${detail}` : `[${it.ordinal}] ${it.field}`;
  };
  const lines: string[] = [];
  for (const it of summary.changed) lines.push(t("approval_warn_full_changed", lang, [item(it)]));
  for (const it of summary.removed) lines.push(t("approval_warn_full_removed", lang, [item(it)]));
  for (const it of summary.added) lines.push(t("approval_warn_full_added", lang, [item(it)]));
  for (const row of summary.unattributed ?? []) {
    lines.push(t("approval_warn_full_unattributed", lang, [row.paragraph, row.detail]));
  }
  return lines;
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
  // Unattributed differences outrank the expected kinds: nobody can say
  // which change made them.
  const loose = summary.unattributed ?? [];
  if (loose.length > 0) {
    lines.splice(summary.changed.length > 0 ? 1 : 0, 0,
      t("approval_warn_unattributed", lang, [loose.length]));
  }
  return lines.slice(0, 2);
}

/** How many failing paragraphs a summary counts, for the applied-state line. */
export function guardWarningCount(summary: GuardWarningSummary): number {
  return summary.changed.length + summary.removed.length + summary.added.length
    + (summary.unattributed?.length ?? 0);
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
  /** 2: bound to the session and its source digest. Absent on older entries. */
  version?: 2;
  sessionId?: string;
  sourceSha256?: string;
  ops: QueuedOp[];
  savedUtc: string;
}

export const SAVED_DRAFT_VERSION = 2 as const;

/** The envelope a typed queue is saved in: its session, its source, its ops. */
export function savedDraftEnvelope(
  sessionId: string,
  sourceSha256: string | null,
  ops: readonly QueuedOp[],
  savedUtc: string,
): SavedDraft {
  return {
    version: SAVED_DRAFT_VERSION,
    sessionId,
    ...(sourceSha256 ? { sourceSha256 } : {}),
    ops: ops.map((op) => ({ ...op, sessionId })),
    savedUtc,
  };
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

/**
 * The saved entries that may come back into THIS document's queue.
 *
 * All or nothing. The envelope must name this session and, when the caller
 * knows it, this source digest; every op must be well formed, typed by the
 * person and owned by this session. An older entry without an envelope is
 * migrated only when each op already names this session — missing ownership
 * is not read as "probably mine". Anything else restores nothing, so a
 * mislabelled or edited prefs entry never reaches `plan/propose`.
 */
export function restorableOps(
  saved: unknown,
  expect?: { sessionId: string; sourceSha256?: string | null },
): QueuedOp[] {
  if (!saved || typeof saved !== "object") return [];
  const envelope = saved as SavedDraft;
  const ops = (envelope as { ops?: unknown }).ops;
  if (!Array.isArray(ops) || ops.length === 0) return [];
  if (expect) {
    if (envelope.version === SAVED_DRAFT_VERSION) {
      if (envelope.sessionId !== expect.sessionId) return [];
      if (expect.sourceSha256 && envelope.sourceSha256 !== expect.sourceSha256) return [];
    } else if (envelope.version !== undefined) {
      return [];
    }
  }
  const owner = expect?.sessionId ?? null;
  const admitted = ops.filter(
    (op): op is QueuedOp =>
      isWellFormedOp(op) &&
      (op as QueuedOp).origin === "user" &&
      (owner === null || (op as QueuedOp).sessionId === owner),
  );
  return admitted.length === ops.length ? admitted : [];
}

/** Integer-valued and non-negative, as every address the engine returns is. */
function isIndex(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

/** The shape `planOpsPayload` relies on, per kind. Nothing else is proposed. */
export function isWellFormedOp(op: unknown): op is QueuedOp {
  if (!op || typeof op !== "object") return false;
  const o = op as Record<string, unknown>;
  if (typeof o.opId !== "string" || o.opId.length === 0) return false;
  if (typeof o.text !== "string") return false;
  if (o.origin !== "user" && o.origin !== "agent") return false;
  if (o.sessionId !== undefined && typeof o.sessionId !== "string") return false;
  switch (o.kind) {
    case "fill_cell":
      return (
        isIndex(o.table) && isIndex(o.row) && isIndex(o.col) &&
        (o.lines === undefined || (Array.isArray(o.lines) && o.lines.every((l) => typeof l === "string")))
      );
    case "replace_at_cell":
      return (
        isIndex(o.table) && isIndex(o.row) && isIndex(o.col) &&
        (o.run === undefined || isIndex(o.run)) &&
        (o.mode === undefined || o.mode === "replace" || o.mode === "append")
      );
    case "set_run":
      return isIndex(o.atPara) && isIndex(o.run);
    case "delete_guides":
      return (
        (o.color === undefined || typeof o.color === "string") &&
        (o.charPrIds === undefined || (Array.isArray(o.charPrIds) && o.charPrIds.every((c) => typeof c === "string")))
      );
    default:
      return false;
  }
}

/**
 * Why a queue may not be proposed for `sessionId`, or null when it may.
 *
 * The one admission check every path into the queue goes through (`setQueue`,
 * restore, re-propose, adoption): an op that is not well formed, or that
 * names another document, stops the whole queue before anything is proposed
 * or saved. An op that names no document is stamped with this one by the
 * caller; that is the explicit migration, not a guess.
 */
export function queueAdmission(
  ops: readonly unknown[],
  sessionId: string | null,
): { code: "invalid_queue_ops" | "foreign_session_ops"; opIds: string[] } | null {
  const malformed = ops.filter((op) => !isWellFormedOp(op));
  if (malformed.length > 0) {
    return {
      code: "invalid_queue_ops",
      opIds: malformed.map((op) =>
        op && typeof op === "object" && typeof (op as QueuedOp).opId === "string" ? (op as QueuedOp).opId : "?",
      ),
    };
  }
  // No open document: nothing will be proposed, the caller empties the queue.
  if (!sessionId) return null;
  const foreign = (ops as QueuedOp[]).filter(
    (op) => op.sessionId !== undefined && op.sessionId !== sessionId,
  );
  if (foreign.length > 0) {
    return { code: "foreign_session_ops", opIds: foreign.map((op) => op.opId) };
  }
  return null;
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

/** The returned-change memory as prefs hold it, cleaned: session → signatures. */
export function returnedFromPrefs(value: unknown): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) return out;
  for (const [sessionId, sigs] of Object.entries(value as Record<string, unknown>)) {
    if (!Array.isArray(sigs)) continue;
    const clean = sigs.filter((x): x is string => typeof x === "string");
    if (clean.length > 0) out[sessionId] = clean;
  }
  return out;
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

// --- T2-1. the approval click binds what the person saw ---------------------------

/**
 * What a person confirmed in the approval sheet, captured at the click.
 *
 * Every wait after the click — revalidation, the approval request, the
 * decision, the apply — ends by checking this against the live state. If the
 * queue was replaced (an agent's proposal adopted), the document switched,
 * validation failed or the acknowledgements the plan needs changed, the flow
 * stops and the sheet asks again. Re-reading "the current draft" after an
 * await is how a confirmation used to move to a plan nobody had seen.
 */
export interface ConfirmationBinding {
  sessionId: string;
  planId: string;
  planHash: string;
  /** The digest of the document the plan was computed against. */
  baseDigest: string;
  baseRunId: string | null;
  /** The acknowledgement boxes ticked, by key (`changed_facts`, `mock`). */
  acknowledgements: string[];
}

export function captureConfirmation(
  state: { activeSessionId: string | null; draft: Pick<Draft, "plan" | "sessionId"> },
  acknowledgements: readonly string[],
): ConfirmationBinding | null {
  const plan = state.draft.plan;
  const sessionId = state.activeSessionId;
  if (!plan || !sessionId || state.draft.sessionId !== sessionId || plan.sessionId !== sessionId) return null;
  return {
    sessionId,
    planId: plan.planId,
    planHash: plan.planHash,
    baseDigest: plan.boundSha256,
    baseRunId: plan.base?.runId ?? null,
    acknowledgements: [...acknowledgements].sort(),
  };
}

/** The acknowledgement keys a draft requires, given the guard's full answer. */
export function requiredAcknowledgements(
  draft: Pick<Draft, "ops"> & { plan?: Draft["plan"] },
  guardAckCount: number,
): string[] {
  const keys: string[] = [];
  if (guardAckCount > 0) keys.push("changed_facts");
  if (draftProposerKind(draft) === "mock") keys.push("mock");
  return keys;
}

export type ConfirmationBreak =
  | "document_switched"
  | "plan_replaced"
  | "base_changed"
  | "acknowledgements_changed"
  | "validation_failed"
  | "diff_mismatch";

/**
 * The review diff for the confirmed plan was read from bytes that are not the
 * plan's base (`beforeSha256` against `boundSha256`): what the person looked
 * at is not what would change. False when the check stated no digest.
 */
export function diffDigestBreaks(
  guard: { planId: string | null; state: string; documentDiff: { beforeSha256?: string | null } | null } | null | undefined,
  binding: Pick<ConfirmationBinding, "planId" | "baseDigest">,
): boolean {
  if (!guard || guard.planId !== binding.planId || guard.state !== "ready") return false;
  const read = guard.documentDiff?.beforeSha256;
  return typeof read === "string" && read.length > 0 && read !== binding.baseDigest;
}

/**
 * Why the live state no longer matches the confirmation, or null if it does.
 *
 * `requiredAcks`, when given, are the acknowledgements the CURRENT draft
 * needs; one the person did not tick breaks the binding.
 */
export function confirmationBreak(
  binding: ConfirmationBinding,
  state: { activeSessionId: string | null; draft: Pick<Draft, "plan" | "sessionId" | "validation"> },
  requiredAcks?: readonly string[],
): ConfirmationBreak | null {
  if (state.activeSessionId !== binding.sessionId || state.draft.sessionId !== binding.sessionId) {
    return "document_switched";
  }
  const plan = state.draft.plan;
  if (!plan || plan.planId !== binding.planId || plan.planHash !== binding.planHash) return "plan_replaced";
  if (plan.boundSha256 !== binding.baseDigest || (plan.base?.runId ?? null) !== binding.baseRunId) {
    return "base_changed";
  }
  if (requiredAcks && requiredAcks.some((key) => !binding.acknowledgements.includes(key))) {
    return "acknowledgements_changed";
  }
  if (state.draft.validation && state.draft.validation.ok !== true) return "validation_failed";
  return null;
}

/** Does an approval record bind exactly the confirmed plan? */
export function approvalBindsConfirmation(
  approval: Pick<ApprovalRecord, "planId" | "planHash"> | null | undefined,
  binding: ConfirmationBinding,
): boolean {
  return Boolean(approval && approval.planId === binding.planId && approval.planHash === binding.planHash);
}
