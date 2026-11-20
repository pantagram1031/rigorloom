/**
 * Change and decision model for editor v2 (J1 §5, WP4).
 *
 * One pending change set per document, one gate, one sheet. Everything in
 * this file is pure: no store, no runtime, no React. The panel, the canvas
 * (WP3) and the narrow layout read these types; `panel/adapter.ts` builds
 * them from today's session, plan and approval objects, and later from
 * PLATFORM's `ChangeSet.items`.
 *
 * The rules the gate enforces live here so they can be tested without a
 * browser:
 *
 * - A decision belongs to the item's content hash. If the agent changes the
 *   item, the stored decision no longer matches and the item is 대기 again.
 * - 승인 is possible only when nothing is 남음, no hard finding exists, the set
 *   is not stale, and at least one change is 받아들임.
 * - The plan that reaches the runtime is built from 받아들임 items only. A 뺌
 *   item can never be in it.
 * - A stale set disables Y, N and 승인.
 */

// --- vocabulary of states ------------------------------------------------------

/** 대기 · 받아들임 · 뺌. */
export type Decision = "pending" | "accepted" | "rejected";

/** What the change does to the document. PLATFORM `kind`. */
export type ChangeKind = "fill" | "replace" | "insert" | "delete" | "format";

/**
 * Who made the change. Four sources only (J1 §3 IA):
 * `에이전트`, `내 입력`, `시험용`, `되돌리기`.
 */
export type ChangeSource = "agent" | "user" | "test" | "revert";

/** Filters on the 변경 header. Each count is also a filter. */
export type ChangeFilter = "all" | "pending" | "accepted" | "rejected" | "attn";

/**
 * One protected fact the guard looked at in this change's paragraph.
 * `expected` facts are the ones a fill or a guide removal is supposed to
 * produce (a date typed into an empty blank, a negation removed together with
 * the guide text); they are shown as a neutral row with `보기`. A fact that is
 * not expected is 바뀐 사실 and needs a tick in the sheet.
 */
export interface GuardFact {
  kind: "number" | "date" | "quote" | "negation" | "direction" | "other";
  before: string | null;
  after: string | null;
  expected: boolean;
  /** The sentence the fact sits in, for the sheet's `보기`. Optional. */
  sentence?: string | null;
  /** The clause only, with the exact removed word, for the underline. */
  clause?: string | null;
  word?: string | null;
}

export interface ChangeGuard {
  /**
   * none: nothing auditable in this change.
   * not_checked: auditable, but the guard did not run (never a pass).
   * kept: the guard ran and every protected fact is unchanged.
   * expected: only expected facts moved.
   * changed: at least one fact changed that is not expected (바뀐 사실).
   */
  status: "none" | "not_checked" | "kept" | "expected" | "changed";
  facts: GuardFact[];
}

export interface ChangeRect {
  page: number;
  /** Points from the page's top-left (doc-core geometry). */
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * One change. Field names are the J1 §5 contract; `opName`, `group`, `rects`
 * and `stale` are additive.
 */
export interface ChangeItem {
  /** Stable id: the op id today, PLATFORM `item_id` later. */
  id: string;
  /** 1-based number shared with the page margin. */
  n: number;
  /** Address in the doc-core grammar: `p12`, `t3/r2/c1`, `place:<id>`. */
  at: string;
  kind: ChangeKind;
  /** The field or paragraph name a person recognises (`행정기관명`). */
  label: string;
  /** Plain op name (`빈칸 채움`, `안내문 지움`). Already translated. */
  opName: string;
  before: string;
  after: string;
  /** 1-based page, or null when the source is not paginated. */
  page: number | null;
  source: ChangeSource;
  /** Effective decision after content binding. */
  decision: Decision;
  guard: ChangeGuard;
  /** Hard findings that block 승인, already translated. Empty when none. */
  hard: string[];
  contentHash: string;
  /** Section key used to group the sheet's range digest. */
  group?: string;
  rects?: ChangeRect[];
}

export interface ChangeSetBase {
  kind: "source" | "candidate";
  /** 0 for 원본, N for 수정본 N. */
  revision: number;
  sha256: string;
}

export interface ChangeSetStale {
  /** Shared naming with PLATFORM: `superseded_by_newer_candidate`. */
  reason: "superseded_by_newer_candidate" | "plan_behind_head" | "source_changed";
  /** The revision the document is at now. */
  current: number;
}

export interface ChangeSetProvenance {
  agent: string | null;
  provider: string | null;
  /** True means every surface labels the set 시험용. */
  mock: boolean;
}

export interface ChangeSetView {
  /** The plan id today, PLATFORM `ChangeSet.id` later. */
  id: string;
  /** Plan hash: the approval binds to it. Full value; the UI shows 12. */
  planHash: string;
  base: ChangeSetBase;
  /** Status `stale` in PLATFORM terms, or null. */
  stale: ChangeSetStale | null;
  items: ChangeItem[];
  provenance: ChangeSetProvenance;
  /** ISO time the proposal was made. */
  createdUtc: string | null;
  /**
   * The fact check is still running. 승인 waits for it: a sheet confirmed
   * before the guard answers could skip a 바뀐 사실 tick.
   */
  checking?: boolean;
}

/** A stored decision, bound to the content it was made on. */
export interface DecisionRecord {
  decision: Decision;
  contentHash: string;
}

export type DecisionMap = Readonly<Record<string, DecisionRecord>>;

// --- content binding -------------------------------------------------------------

/** FNV-1a over UTF-16 code units, two lanes, 16 hex characters. */
export function hashText(text: string): string {
  let a = 0x811c9dc5;
  let b = 0x01000193 ^ 0x5bd1e995;
  for (let i = 0; i < text.length; i += 1) {
    const c = text.charCodeAt(i);
    a ^= c;
    a = Math.imul(a, 0x01000193) >>> 0;
    b ^= c + i;
    b = Math.imul(b, 0x01000193) >>> 0;
  }
  return a.toString(16).padStart(8, "0") + b.toString(16).padStart(8, "0");
}

/** What a decision is about: where, what kind, from what, to what. */
export function contentHashOf(item: Pick<ChangeItem, "at" | "kind" | "before" | "after">): string {
  return hashText([item.at, item.kind, item.before, item.after].join("\u0000"));
}

/** A person's own typing lands already accepted (D1 §3b). */
export function defaultDecision(source: ChangeSource): Decision {
  return source === "user" ? "accepted" : "pending";
}

/**
 * The decision that counts. A record made on other content is ignored, so an
 * item the agent changed returns to the decision it arrived with: 대기 for an
 * agent change, 받아들임 for a person's own typing, or the status a PLATFORM
 * change set carries.
 */
export function effectiveDecision(
  item: Pick<ChangeItem, "source" | "contentHash"> & { decision?: Decision },
  record: DecisionRecord | undefined,
): Decision {
  if (record && record.contentHash === item.contentHash) return record.decision;
  return item.decision ?? defaultDecision(item.source);
}

export function withDecisions<T extends ChangeItem>(items: readonly T[], records: DecisionMap): T[] {
  return items.map((item) => {
    const decision = effectiveDecision(item, records[item.id]);
    return decision === item.decision ? item : { ...item, decision };
  });
}

/** Record a decision on an item. Returns a new map; never mutates. */
export function recordDecision(
  records: DecisionMap,
  item: Pick<ChangeItem, "id" | "contentHash">,
  decision: Decision,
): Record<string, DecisionRecord> {
  return { ...records, [item.id]: { decision, contentHash: item.contentHash } };
}

/** Drop records whose item is gone or whose content moved. */
export function pruneDecisions(
  records: DecisionMap,
  items: readonly Pick<ChangeItem, "id" | "contentHash">[],
): Record<string, DecisionRecord> {
  const byId = new Map(items.map((item) => [item.id, item.contentHash]));
  const next: Record<string, DecisionRecord> = {};
  for (const [id, rec] of Object.entries(records)) {
    if (byId.get(id) === rec.contentHash) next[id] = rec;
  }
  return next;
}

// --- counts and filters ----------------------------------------------------------

export interface ChangeCounts {
  total: number;
  /** 남음 */
  pending: number;
  /** 받아들임 */
  accepted: number;
  /** 뺌 */
  rejected: number;
  /** 확인: expected guard facts a person should look at. */
  attn: number;
  /** 바뀐 사실 */
  facts: number;
  /** Items with a hard finding. */
  hard: number;
}

/**
 * 확인: a person should look. An expression that went missing (even an
 * expected one, removed with guide text) or a check that did not run. New
 * values put into a blank only get a neutral tag (`hasNewValues`).
 */
export function needsLook(item: ChangeItem): boolean {
  if (item.guard.status === "not_checked") return true;
  return item.guard.status === "expected" && item.guard.facts.some((f) => f.before !== null);
}

/** Expected new numbers or dates, shown as a neutral tag only. */
export function hasNewValues(item: ChangeItem): boolean {
  return item.guard.status === "expected" && !needsLook(item) && item.guard.facts.some((f) => f.after !== null);
}

export function isChangedFact(item: ChangeItem): boolean {
  return item.guard.status === "changed";
}

export function countChanges(items: readonly ChangeItem[]): ChangeCounts {
  const c: ChangeCounts = { total: items.length, pending: 0, accepted: 0, rejected: 0, attn: 0, facts: 0, hard: 0 };
  for (const item of items) {
    if (item.decision === "pending") c.pending += 1;
    else if (item.decision === "accepted") c.accepted += 1;
    else c.rejected += 1;
    if (needsLook(item)) c.attn += 1;
    if (isChangedFact(item)) c.facts += 1;
    if (item.hard.length > 0) c.hard += 1;
  }
  return c;
}

export function filterChanges(items: readonly ChangeItem[], filter: ChangeFilter): ChangeItem[] {
  switch (filter) {
    case "pending":
    case "accepted":
    case "rejected":
      return items.filter((item) => item.decision === filter);
    case "attn":
      return items.filter(needsLook);
    default:
      return items.slice();
  }
}

/** Next 대기 item after `fromId`, wrapping; null when nothing is 남음. */
export function nextPending(items: readonly ChangeItem[], fromId: string | null): ChangeItem | null {
  if (items.length === 0) return null;
  const start = fromId ? items.findIndex((item) => item.id === fromId) : -1;
  for (let step = 1; step <= items.length; step += 1) {
    const item = items[(start + step + items.length) % items.length];
    if (item.decision === "pending") return item;
  }
  return null;
}

/** J/K stepping inside the visible list. */
export function stepSelection(
  items: readonly ChangeItem[],
  fromId: string | null,
  delta: 1 | -1,
): ChangeItem | null {
  if (items.length === 0) return null;
  const idx = fromId ? items.findIndex((item) => item.id === fromId) : -1;
  if (idx < 0) return delta > 0 ? items[0] : items[items.length - 1];
  const next = Math.min(items.length - 1, Math.max(0, idx + delta));
  return items[next];
}

// --- the gate ---------------------------------------------------------------------

export type GateBlock =
  | { kind: "empty" }
  | { kind: "stale" }
  | { kind: "busy" }
  | { kind: "checking" }
  | { kind: "hard"; count: number }
  | { kind: "remaining"; count: number }
  | { kind: "none_accepted" };

export interface GateState {
  canApprove: boolean;
  /** Why 승인 is disabled. Null when it is enabled. */
  block: GateBlock | null;
  counts: ChangeCounts;
}

/**
 * 승인 is enabled only when 남음 is 0 and no hard finding exists (J1 #20),
 * the set is current, and something will actually land.
 */
export function gateState(view: ChangeSetView | null, opts: { busy?: boolean } = {}): GateState {
  const items = view?.items ?? [];
  const counts = countChanges(items);
  let block: GateBlock | null = null;
  if (!view || items.length === 0) block = { kind: "empty" };
  else if (view.stale) block = { kind: "stale" };
  else if (opts.busy) block = { kind: "busy" };
  else if (counts.hard > 0) block = { kind: "hard", count: counts.hard };
  else if (counts.pending > 0) block = { kind: "remaining", count: counts.pending };
  else if (counts.accepted === 0) block = { kind: "none_accepted" };
  else if (view.checking) block = { kind: "checking" };
  return { canApprove: block === null, block, counts };
}

/** Y and N are refused on a stale set (D1 §3d). */
export function canDecide(view: ChangeSetView | null): boolean {
  return Boolean(view && !view.stale && view.items.length > 0);
}

/**
 * The ids that go to the runtime. Only 받아들임; a 뺌 or 대기 item can never be
 * in the applied plan, whatever the caller does with the result.
 */
export function idsForApproval(items: readonly ChangeItem[]): string[] {
  return items.filter((item) => item.decision === "accepted").map((item) => item.id);
}

/** Ids a confirm must take out of the draft before it binds an approval. */
export function idsToDrop(items: readonly ChangeItem[]): string[] {
  return items.filter((item) => item.decision !== "accepted").map((item) => item.id);
}

// --- the sheet --------------------------------------------------------------------

export type TickId = "facts" | "test";

/**
 * Ticks exist only for 바뀐 사실 and 시험용 (J1 #28). An expected finding is a
 * neutral row with no tick.
 */
export function requiredTicks(view: ChangeSetView | null): TickId[] {
  if (!view) return [];
  const accepted = view.items.filter((item) => item.decision === "accepted");
  const ticks: TickId[] = [];
  if (accepted.some(isChangedFact)) ticks.push("facts");
  if (view.provenance.mock || accepted.some((item) => item.source === "test")) ticks.push("test");
  return ticks;
}

/** `Enter` in the sheet confirms only when every required tick is set. */
export function canConfirm(
  view: ChangeSetView | null,
  ticks: ReadonlySet<TickId> | readonly TickId[],
  gate: GateState,
): boolean {
  if (!gate.canApprove) return false;
  const set = ticks instanceof Set ? ticks : new Set(ticks as readonly TickId[]);
  return requiredTicks(view).every((tick) => set.has(tick));
}

export interface OpTally {
  opName: string;
  count: number;
}

/** `빈칸 채움 16 · 안내문 지움 6 · 기호 지움 2`, most frequent first. */
export function tallyByOp(items: readonly ChangeItem[]): OpTally[] {
  const map = new Map<string, number>();
  for (const item of items) map.set(item.opName, (map.get(item.opName) ?? 0) + 1);
  return [...map.entries()]
    .map(([opName, count]) => ({ opName, count }))
    .sort((a, b) => b.count - a.count || a.opName.localeCompare(b.opName));
}

export interface DigestRow {
  /** First and last change number in the row. */
  from: number;
  to: number;
  labels: string[];
  opNames: string[];
  /** The item a click jumps to. */
  firstId: string;
  facts: number;
  attn: number;
}

function digestOf(items: readonly ChangeItem[]): DigestRow {
  const labels: string[] = [];
  const opNames: string[] = [];
  for (const item of items) {
    if (!labels.includes(item.label)) labels.push(item.label);
    if (!opNames.includes(item.opName)) opNames.push(item.opName);
  }
  return {
    from: items[0].n,
    to: items[items.length - 1].n,
    labels,
    opNames,
    firstId: items[0].id,
    facts: items.filter(isChangedFact).length,
    attn: items.filter(needsLook).length,
  };
}

/**
 * The sheet's range digest: consecutive items that share a group, at most
 * `max` rows (J1 #31 keeps seven). Adjacent rows merge from the smallest pair
 * up, so a long form still reads as its sections.
 */
export function rangeDigest(items: readonly ChangeItem[], max = 7): DigestRow[] {
  const sorted = items.slice().sort((a, b) => a.n - b.n);
  const runs: ChangeItem[][] = [];
  for (const item of sorted) {
    const key = item.group ?? item.label;
    const last = runs[runs.length - 1];
    if (last && (last[last.length - 1].group ?? last[last.length - 1].label) === key) last.push(item);
    else runs.push([item]);
  }
  while (runs.length > max) {
    let best = 0;
    let bestSize = Number.POSITIVE_INFINITY;
    for (let i = 0; i < runs.length - 1; i += 1) {
      const size = runs[i].length + runs[i + 1].length;
      if (size < bestSize) {
        best = i;
        bestSize = size;
      }
    }
    runs.splice(best, 2, [...runs[best], ...runs[best + 1]]);
  }
  return runs.map(digestOf);
}

/** `5`, or `10–12` for a range. */
export function rangeText(from: number, to: number): string {
  return from === to ? String(from) : `${from}–${to}`;
}

/** Visible hashes are 12 characters; the full value lives under 자세히. */
export function shortHash(hash: string | null | undefined): string {
  return (hash ?? "").slice(0, 12);
}
