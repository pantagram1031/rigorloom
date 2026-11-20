/**
 * Maps today's session, plan and approval objects, and later PLATFORM's
 * `ChangeSet`, onto `ChangeSetView` (J1 §5).
 *
 * Pure: every input is passed in, so the mapping is tested in node. The hook
 * that gathers the inputs from the store is `useChangeSet.ts`.
 */
import {
  contentHashOf,
  defaultDecision,
  type ChangeGuard,
  type ChangeItem,
  type ChangeKind,
  type ChangeSetStale,
  type ChangeSetView,
  type ChangeSource,
  type GuardFact,
} from "../model/changes.ts";
import { errorCodeMessage, type UiLanguage } from "../i18n/vocabulary.ts";
import type { GuardDiffParagraph, GuardProtectedToken, OperationPlan, PlanFinding, PlanValidation } from "../types";
import type { QueuedOp } from "../store";
import type { IndexedChange, ReviewGuardSummary } from "../workspace/guardHelper";

// --- addresses and kinds ---------------------------------------------------------

/** The doc-core address of a queued op (`t3/r2/c1`, `p12`). */
export function addressOf(op: QueuedOp): string {
  switch (op.kind) {
    case "fill_cell":
    case "replace_at_cell":
      return `t${op.table}/r${op.row}/c${op.col}`;
    case "set_run":
      return `p${op.atPara}`;
    default:
      return "place:guides";
  }
}

/** Section key for the range digest: the table row, or the paragraph. */
export function groupOf(op: QueuedOp): string {
  switch (op.kind) {
    case "fill_cell":
    case "replace_at_cell":
      return `t${op.table}/r${op.row}`;
    case "set_run":
      return `p${op.atPara}`;
    default:
      return "guides";
  }
}

export function kindOf(change: Pick<IndexedChange, "op" | "beforeText" | "afterText">): ChangeKind {
  const { op } = change;
  if (op.kind === "delete_guides") return "delete";
  const after = change.afterText.trim();
  const before = change.beforeText.trim();
  if (after.length === 0 && before.length > 0) return "delete";
  if (op.kind === "fill_cell") return before.length === 0 ? "fill" : "replace";
  if (op.kind === "replace_at_cell" && op.mode === "append") return "insert";
  return before.length === 0 ? "fill" : "replace";
}

export function sourceOf(op: QueuedOp, ctx: { mock: boolean; reverses: boolean }): ChangeSource {
  if (op.origin === "user") return "user";
  if (ctx.mock) return "test";
  if (ctx.reverses) return "revert";
  return "agent";
}

// --- guard -------------------------------------------------------------------------

const FACT_KIND: Record<string, GuardFact["kind"]> = {
  numbers: "number",
  quantifiers: "number",
  dates: "date",
  direct_quotes: "quote",
  qualifiers: "negation",
  direction_words: "direction",
};

function factKind(kind: string): GuardFact["kind"] {
  return FACT_KIND[kind] ?? "other";
}

/** The clause around a token: from the previous sentence break to the next. */
export function clauseAround(text: string, start: number, end: number): { clause: string; word: string } {
  // A period ends a clause only before a space or the end, and never after a
  // digit: `2016. 7. 11.` is one date, not three clauses.
  const breaks = /[。!?\n;]|\uB2E4\.|(?<!\d)\.(?=\s|$)/g;
  let from = 0;
  let to = text.length;
  let m: RegExpExecArray | null;
  while ((m = breaks.exec(text)) !== null) {
    const stop = m.index + m[0].length;
    if (stop <= start) from = stop;
    else if (m.index >= end) {
      to = stop;
      break;
    }
  }
  const lead = text.slice(from, start).trimStart();
  const commaIdx = Math.max(lead.lastIndexOf(","), lead.lastIndexOf("，"), lead.lastIndexOf("·"));
  const head = commaIdx >= 0 ? lead.slice(commaIdx + 1).trimStart() : lead;
  const prefix = from > 0 || commaIdx >= 0 ? "… " : "";
  return { clause: `${prefix}${head}${text.slice(start, to).trimEnd()}`, word: text.slice(start, end) };
}

/**
 * Facts from one guard paragraph. Removed and added tokens of the same kind
 * pair up as `before → after`; the rest stand alone.
 */
export function factsFrom(para: GuardDiffParagraph | null): Omit<GuardFact, "expected">[] {
  if (!para) return [];
  const removed = (para.beforeProtected ?? []).filter((tok) => tok.status === "removed");
  const added = (para.afterProtected ?? []).filter((tok) => tok.status === "added");
  const facts: Omit<GuardFact, "expected">[] = [];
  const pool = added.slice();
  for (const tok of removed) {
    const idx = pool.findIndex((a) => a.kind === tok.kind);
    const pair: GuardProtectedToken | undefined = idx >= 0 ? pool.splice(idx, 1)[0] : undefined;
    const around = clauseAround(para.before, tok.start, tok.end);
    facts.push({
      kind: factKind(tok.kind),
      before: tok.text,
      after: pair ? pair.text : null,
      sentence: para.before,
      clause: around.clause,
      word: around.word,
    });
  }
  for (const tok of pool) {
    facts.push({ kind: factKind(tok.kind), before: null, after: tok.text, sentence: para.after, clause: null, word: tok.text });
  }
  return facts;
}

/**
 * Expected facts are the ones the change is supposed to produce: values put
 * into a blank or a guide-text seat, and expressions removed together with
 * guide text. A value that turned into another value is never expected, and
 * neither is an expression removed from text a person wrote.
 */
export function classifyFacts(
  raw: Omit<GuardFact, "expected">[],
  change: Pick<IndexedChange, "isAuditable" | "isEmptyBlankFill" | "op">,
  kind: ChangeKind,
): GuardFact[] {
  const removal = kind === "delete" || change.op.kind === "delete_guides";
  const fillLike = !change.isAuditable || change.isEmptyBlankFill || kind === "fill";
  return raw.map((f) => {
    const pureAdd = f.before === null && f.after !== null;
    const pureRemove = f.before !== null && f.after === null;
    const expected = (pureAdd && fillLike) || (pureRemove && (removal || !change.isAuditable));
    return { ...f, expected };
  });
}

export function guardOf(
  change: Pick<IndexedChange, "opId" | "isAuditable" | "isEmptyBlankFill" | "op">,
  kind: ChangeKind,
  summary: ReviewGuardSummary | null,
  /** Paragraphs an earlier change already reported; facts are shown once. */
  claimed?: Set<number>,
): ChangeGuard {
  if (!summary || summary.state === "idle" || summary.state === "running") return { status: "none", facts: [] };
  const audit = summary.rowAudits[change.opId];
  if (summary.state === "unavailable" || summary.state === "invalid_plan" || !audit) {
    return { status: change.isAuditable ? "not_checked" : "none", facts: [] };
  }
  if (audit.status === "not_checked" || audit.status === "needs_fixes") return { status: "not_checked", facts: [] };
  const para = audit.paragraph;
  if (!para || para.pass !== false) {
    return { status: audit.status === "kept" ? "kept" : "none", facts: [] };
  }
  if (claimed) {
    if (claimed.has(para.paragraph)) return { status: change.isAuditable ? "kept" : "none", facts: [] };
    claimed.add(para.paragraph);
  }
  const facts = classifyFacts(factsFrom(para), change, kind);
  if (facts.length === 0) {
    // The guard failed the paragraph without a token we can show (for
    // example a paragraph count change): an auditable row stays changed.
    return audit.status === "changed" ? { status: "changed", facts } : { status: "none", facts };
  }
  return { status: facts.every((f) => f.expected) ? "expected" : "changed", facts };
}

// --- the change set -------------------------------------------------------------------

export interface WorkspaceAdapterInput {
  language: UiLanguage;
  changes: readonly IndexedChange[];
  guard: ReviewGuardSummary | null;
  plan: OperationPlan | null;
  validation: PlanValidation | null;
  /** Revision the plan is based on: 0 for 원본. */
  baseRevision: number;
  baseSha256: string;
  /** Revision the document is at now. */
  currentRevision: number;
  /** Why the set no longer applies, or null. */
  stale: ChangeSetStale["reason"] | null;
  /** The plan comes from a test provider. */
  mock: boolean;
  provider: string | null;
}

function findingText(f: PlanFinding, lang: UiLanguage): string {
  return errorCodeMessage(f.code, lang);
}

/** Plan-level findings that make the set stale rather than an item hard. */
const STALE_CODES = new Set(["plan_behind_head", "plan_stale"]);

export function staleFromValidation(validation: PlanValidation | null): ChangeSetStale["reason"] | null {
  if (!validation) return null;
  if (validation.hard.some((f) => f.code === "plan_behind_head")) return "plan_behind_head";
  if (validation.stale) return "source_changed";
  return null;
}

/** Whether a plan came from a test provider (trust: `provenance.mock`). */
export function planIsMock(plan: OperationPlan | null): boolean {
  if (!plan) return false;
  // Trust writes `provenance: "mock"`; PLATFORM writes `provenance.mock`.
  const prov = (plan as unknown as { provenance?: unknown }).provenance;
  if (prov === "mock") return true;
  if (prov && typeof prov === "object" && (prov as { mock?: unknown }).mock === true) return true;
  return /(^|[-_.:])mock([-_.:]|$)/i.test(plan.proposer ?? "");
}

export function fromWorkspace(raw: WorkspaceAdapterInput): ChangeSetView | null {
  const { changes, plan } = raw;
  if (changes.length === 0) return null;
  // The guard summary is for one plan; another plan's result is no result.
  const foreign = Boolean(raw.guard && plan && raw.guard.planId && raw.guard.planId !== plan.planId);
  const input = foreign ? { ...raw, guard: null } : raw;
  const reverses = Boolean(plan?.reverses);
  const claimed = new Set<number>();
  const items: ChangeItem[] = changes.map((ch) => {
    const kind = kindOf(ch);
    const source = sourceOf(ch.op, { mock: input.mock, reverses });
    const hard = ch.hardFindings.filter((f) => !STALE_CODES.has(f.code)).map((f) => findingText(f, input.language));
    const base = {
      id: ch.opId,
      n: ch.ordinal,
      at: addressOf(ch.op),
      kind,
      label: ch.fieldLabel,
      opName: ch.opKindText,
      before: ch.beforeText,
      after: ch.afterText,
      page: null,
      source,
      decision: defaultDecision(source),
      guard: guardOf(ch, kind, input.guard, claimed),
      hard,
      group: groupOf(ch.op),
    };
    return { ...base, contentHash: contentHashOf(base) };
  });
  return {
    id: plan?.planId ?? "draft",
    planHash: plan?.planHash ?? "",
    base: {
      kind: input.baseRevision > 0 ? "candidate" : "source",
      revision: input.baseRevision,
      sha256: plan?.boundSha256 ?? input.baseSha256,
    },
    stale: input.stale ? { reason: input.stale, current: input.currentRevision } : null,
    items,
    provenance: { agent: plan?.proposer ?? null, provider: input.provider, mock: input.mock },
    createdUtc: plan?.createdUtc ?? null,
    checking:
      foreign ||
      input.guard?.state === "running" ||
      ((!input.guard || input.guard.state === "idle") && Boolean(plan) && input.validation?.ok === true),
  };
}

// --- PLATFORM change sets (platform-design §5, "UI 요구") ---------------------------------

/** The field list agreed with PLATFORM. The schema lands in runtime/schemas. */
export interface PlatformChangeSet {
  id: string;
  created?: string;
  author?: string;
  base: { kind: "source" | "candidate"; revision: number; sha256: string; path?: string };
  status: "proposed" | "accepted" | "rejected" | "applied" | "stale";
  reason?: string | null;
  provenance?: { agent?: string | null; provider?: string | null; mock?: boolean };
  plan_hash?: string;
  head_revision?: number;
  items: Array<{
    item_id: string;
    address: string;
    kind: ChangeKind;
    before: string;
    after: string;
    page?: number | null;
    rects?: Array<[number, number, number, number]> | null;
    status?: "pending" | "accepted" | "rejected";
    note?: string | null;
    label?: string;
    op_name?: string;
    origin?: "agent" | "user" | "revert";
  }>;
  checks?: {
    guard?: {
      items?: Array<{
        item_id: string;
        pass: boolean;
        category: "changed" | "expected";
        values?: Array<{ kind?: string; before?: string | null; after?: string | null }>;
      }>;
    };
    hard?: Array<{ item_id: string; message: string }>;
  };
}

export function fromPlatformChangeSet(cs: PlatformChangeSet): ChangeSetView {
  const mock = cs.provenance?.mock === true;
  const guardBy = new Map((cs.checks?.guard?.items ?? []).map((g) => [g.item_id, g]));
  const hardBy = new Map<string, string[]>();
  for (const h of cs.checks?.hard ?? []) hardBy.set(h.item_id, [...(hardBy.get(h.item_id) ?? []), h.message]);
  const items: ChangeItem[] = cs.items.map((it, idx) => {
    const source: ChangeSource = it.origin === "user" ? "user" : mock ? "test" : it.origin === "revert" ? "revert" : "agent";
    const g = guardBy.get(it.item_id);
    const guard: ChangeGuard = !g
      ? { status: "none", facts: [] }
      : g.pass
        ? { status: "kept", facts: [] }
        : {
            status: g.category === "expected" ? "expected" : "changed",
            facts: (g.values ?? []).map((v) => ({
              kind: factKind(v.kind ?? ""),
              before: v.before ?? null,
              after: v.after ?? null,
              expected: g.category === "expected",
            })),
          };
    const base = {
      id: it.item_id,
      n: idx + 1,
      at: it.address,
      kind: it.kind,
      label: it.label ?? it.address,
      opName: it.op_name ?? it.kind,
      before: it.before,
      after: it.after,
      page: it.page ?? null,
      source,
      decision: it.status ?? defaultDecision(source),
      guard,
      hard: hardBy.get(it.item_id) ?? [],
      rects: (it.rects ?? []).map(([x, y, w, h]) => ({ page: it.page ?? 1, x, y, w, h })),
    };
    return { ...base, contentHash: contentHashOf(base) };
  });
  return {
    id: cs.id,
    planHash: cs.plan_hash ?? "",
    base: { kind: cs.base.kind, revision: cs.base.revision, sha256: cs.base.sha256 },
    stale:
      cs.status === "stale"
        ? {
            reason: cs.reason === "superseded_by_newer_candidate" ? "superseded_by_newer_candidate" : "plan_behind_head",
            current: cs.head_revision ?? cs.base.revision + 1,
          }
        : null,
    items,
    provenance: { agent: cs.author ?? cs.provenance?.agent ?? null, provider: cs.provenance?.provider ?? null, mock },
    createdUtc: cs.created ?? null,
  };
}
