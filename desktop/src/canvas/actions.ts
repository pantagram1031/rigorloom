import * as legacyActions from "../actions";
import { wp3t } from "../i18n/v2/wp3";
import type { CanvasChangeDecision, PageViewMode } from "../model/page";
import {
  activeHeadTexts,
  cellKey,
  getState,
  queuedCellOpAt,
  queuedRunOpAt,
  setState,
  type QueuedOp,
} from "../store";
import type { InspectResult, RegionText, UiLanguage } from "../types";
import { classifyCellEditMode } from "../workspace/fieldLabels";
import {
  canvas,
  getCanvasSlice,
  getPublishedChanges,
  recordCanvasDecisions,
  restoreCanvasDecision,
  setCanvasSlice,
} from "./controller";

function autoCharPr(
  seat: { scriptAnomaly?: boolean; charPrSuggested?: string } | null | undefined,
  declared: string | undefined,
): string | undefined {
  if (declared) return declared;
  if (seat?.scriptAnomaly && seat.charPrSuggested) {
    return seat.charPrSuggested;
  }
  return undefined;
}

/**
 * Open ANY table cell for in-place typing. Every cell is typable (`D1` Calls):
 * never emits a refusal when a cell already contains text or is `static`/`guide`.
 */
export function beginCellEditV2(
  table: number,
  row: number,
  col: number,
  options?: {
    multiline?: boolean;
    inspect?: InspectResult | null;
    texts?: RegionText[];
  },
): boolean {
  const state = getState();
  const sessionId = state.activeSessionId;
  const inspect = options?.inspect ?? (sessionId ? state.inspects[sessionId] ?? null : null);
  const texts = activeHeadTexts(state) ?? options?.texts ?? (sessionId ? state.texts[sessionId] ?? [] : []);
  const queued = queuedCellOpAt(state, table, row, col);
  const seat = legacyActions.seatAt(inspect, table, row, col);
  const baseText =
    queued?.kind === "replace_at_cell" && queued.run !== undefined
      ? legacyActions.seatText(inspect, texts, table, row, col)
      : queued?.before ?? legacyActions.seatText(inspect, texts, table, row, col);
  const key = cellKey(table, row, col);
  const isStatic = !seat;
  const multiline =
    Boolean(options?.multiline) ||
    (queued?.kind === "fill_cell" && queued.lines !== undefined) ||
    Boolean(queued?.text.includes("\n")) ||
    baseText.includes("\n");

  setCanvasSlice({
    selectedSeatKey: key,
    statusNotice: null,
  });

  setState({
    selection: { kind: "cell", table, row, col },
    inlineEdit: {
      kind: "cell",
      table,
      row,
      col,
      before: baseText,
      charPr: autoCharPr(seat, queued?.charPr),
      opId: queued?.opId ?? null,
      replaceExisting: isStatic || baseText.trim().length > 0,
      multiline,
    },
  });
  return true;
}

export interface CommitCellEditResult {
  committed: boolean;
  op?: QueuedOp;
  modeLabelKey?: "fill_cell" | "replace_at_cell:append" | "replace_at_cell:replace";
  hasFormText?: boolean;
  bodyStyleMatched?: boolean;
}

/**
 * Commit an in-place cell edit. The engine overlay may stay open through
 * its debounced commit while the new raster is still being drawn.
 */
export async function commitCellEditV2(
  nextValue: string,
  options?: {
    inspect?: InspectResult | null;
    keepOpen?: boolean;
  },
): Promise<CommitCellEditResult> {
  const state = getState();
  const edit = state.inlineEdit;
  if (!edit || edit.kind !== "cell") {
    return { committed: false };
  }

  setState({
    ...(options?.keepOpen ? {} : { inlineEdit: null }),
    lastCommit: { value: nextValue, composed: state.sawComposition },
    sawComposition: false,
  });

  const before = edit.before;
  if (nextValue === before || (before.trim().length === 0 && nextValue === "")) {
    const opId = queuedCellOpAt(state, edit.table, edit.row, edit.col)?.opId;
    if (opId) {
      await legacyActions.undoQueuedOp(opId);
    }
    return { committed: false };
  }

  const sessionId = state.activeSessionId;
  const inspect = options?.inspect ?? (sessionId ? state.inspects[sessionId] ?? null : null);
  const seat = legacyActions.seatAt(inspect, edit.table, edit.row, edit.col);
  const resolvedCharPr = autoCharPr(seat, edit.charPr);
  const classification = classifyCellEditMode(before, nextValue);
  const opId =
    edit.opId ?? `op-t${edit.table}r${edit.row}c${edit.col}`;

  let nextOp: QueuedOp;
  let modeLabelKey: CommitCellEditResult["modeLabelKey"];

  if (classification.kind === "fill_cell") {
    modeLabelKey = "fill_cell";
    nextOp = {
      opId,
      kind: "fill_cell",
      table: edit.table,
      row: edit.row,
      col: edit.col,
      text: nextValue,
      ...(nextValue.includes("\n") ? { lines: nextValue.split(/\r?\n/) } : {}),
      ...(resolvedCharPr ? { charPr: resolvedCharPr } : {}),
      before,
      origin: "user",
    };
  } else {
    const isAppend =
      classification.mode === "append" && nextValue.startsWith(before);
    const opMode = isAppend ? "append" : "replace";
    const opText = isAppend ? nextValue.slice(before.length) : nextValue;
    modeLabelKey = isAppend ? "replace_at_cell:append" : "replace_at_cell:replace";
    nextOp = {
      opId,
      kind: "replace_at_cell",
      table: edit.table,
      row: edit.row,
      col: edit.col,
      text: opText,
      mode: opMode,
      ...(before ? { expect: before } : {}),
      ...(resolvedCharPr ? { charPr: resolvedCharPr } : {}),
      before,
      origin: "user",
    };
  }

  const queued = await queueCanvasEdit(nextOp, sessionId);

  return {
    committed: true,
    op: queued,
    modeLabelKey,
    hasFormText: classification.hasFormText,
    bodyStyleMatched: Boolean(resolvedCharPr && seat?.scriptAnomaly),
  };
}

export async function commitEngineRunEdit(value: string, text: string, keepOpen: boolean): Promise<void> {
  const state = getState();
  const edit = state.inlineEdit;
  if (edit?.kind !== "run") return;
  setState({
    ...(keepOpen ? {} : { inlineEdit: null }),
    lastCommit: { value, composed: state.sawComposition },
    sawComposition: false,
  });
  const queued = queuedRunOpAt(state, edit.atPara, edit.run);
  if (text === edit.before) {
    if (queued) await legacyActions.undoQueuedOp(queued.opId);
    return;
  }
  await queueCanvasEdit({
    kind: "set_run", opId: queued?.opId ?? `op-p${edit.atPara}r${edit.run}`,
    atPara: edit.atPara, run: edit.run, text, before: edit.before, origin: "user",
  }, state.activeSessionId);
}

/**
 * Show honest status-bar notice when a user clicks an uneditable paragraph
 * (`D1 §3(b) 3`: `이 문단은 아직 화면에서 고칠 수 없습니다`).
 */
export function notifyParagraphNotEditable(language: UiLanguage = getState().language): void {
  setCanvasSlice({ statusNotice: wp3t("para_not_editable_status", language) });
}

export function clearCanvasStatusNotice(): void {
  setCanvasSlice({ statusNotice: null });
}

/**
 * Decide a pending change (`accepted` | `rejected` | `pending`), pushing onto
 * the per-document decision undo stack. Accepting advances selection to the next
 * undecided change (`D1 §3(c) 7`).
 */
export function decideCanvasItem(
  itemId: string,
  decision: CanvasChangeDecision,
): void {
  const changes = getPublishedChanges();
  const target = changes.find((c) => c.id === itemId);
  if (!target || (target.isStale && decision !== "pending") || target.decision === decision) return;

  recordCanvasDecisions([target], decision);
  if (decision === "accepted") {
    const idx = changes.indexOf(target);
    const next = changes.slice(idx + 1).find((c) => c.decision === "pending") ??
      changes.slice(0, idx).find((c) => c.decision === "pending");
    if (next) canvas.select(next.id);
  }
}

export function undoCanvasDecision(): boolean {
  const changes = getPublishedChanges();
  if (changes.some((change) => change.isStale)) return false;
  const id = restoreCanvasDecision(changes);
  if (!id) return false;
  canvas.select(id);
  return true;
}

const VIEW_CYCLE: readonly PageViewMode[] = ["marks", "clean", "base"];

export function cycleCanvasView(): PageViewMode {
  const cur = getCanvasSlice().view;
  const next = VIEW_CYCLE[(VIEW_CYCLE.indexOf(cur) + 1) % VIEW_CYCLE.length];
  canvas.setView(next);
  return next;
}

export function stepCanvasChange(delta: -1 | 1): string | null {
  const changes = getPublishedChanges();
  if (changes.length === 0) return null;
  const slice = getCanvasSlice();
  const idx = changes.findIndex((c) => c.id === slice.selectedChangeId);
  const start = idx >= 0 ? idx : 0;
  const nextIdx = (start + delta + changes.length) % changes.length;
  const nextId = changes[nextIdx].id;
  canvas.select(nextId);
  return nextId;
}

export function fitCanvasWidth(): void {
  setCanvasSlice({ pageFit: "width", narrowReadZoom: false });
}

export function fitCanvasPage(): void {
  setCanvasSlice({ pageFit: "page", narrowReadZoom: false });
}

export function stepCanvasZoom(delta: number): void {
  const slice = getCanvasSlice();
  const next = Math.min(2.0, Math.max(0.5, Math.round((slice.zoom + delta) * 100) / 100));
  setCanvasSlice({ pageFit: "free", zoom: next });
}

export function setCanvasZoom(zoom: number): void {
  const next = Math.min(2.0, Math.max(0.5, Math.round(zoom * 100) / 100));
  setCanvasSlice({ pageFit: "free", zoom: next });
}

export function toggleNarrowReadZoom(): void {
  setCanvasSlice((prev) => ({
    ...prev,
    narrowReadZoom: !prev.narrowReadZoom,
  }));
}

export function triggerApprovalDryAnimation(durationMs = 400): void {
  setCanvasSlice({ drying: true });
  if (typeof window !== "undefined") {
    window.setTimeout(() => {
      setCanvasSlice({ drying: false });
    }, durationMs);
  }
}

export interface FindMatchItem {
  id: string;
  targetType: "cell" | "para";
  cellKey?: string;
  table?: number;
  row?: number;
  col?: number;
  atPara?: number;
  run?: number;
  label: string;
  locationLabel: string;
  text: string;
  matchStart: number;
  matchEnd: number;
}

async function queueCanvasEdit(op: QueuedOp, sessionId: string | null): Promise<QueuedOp> {
  const saved = legacyActions.upsertQueueOp(op);
  // The runtime proposal settles asynchronously. The store publishes the queue
  // before that request, so selection and its decision stay with this edit.
  const state = getState();
  const queued = op.kind === "fill_cell" || op.kind === "replace_at_cell"
    ? queuedCellOpAt(state, op.table, op.row, op.col)
    : op.kind === "set_run" ? queuedRunOpAt(state, op.atPara, op.run) : null;
  if (sessionId && queued) {
    setCanvasSlice({ selectedChangeId: queued.opId }, sessionId);
  }
  return saved;
}

async function replaceMatchText(match: FindMatchItem, after: string): Promise<boolean> {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId || after === match.text) return false;

  if (match.targetType === "cell" && match.table !== undefined && match.row !== undefined && match.col !== undefined) {
    const { table, row, col } = match;
    const queued = queuedCellOpAt(state, table, row, col);
    const inspect = state.inspects[sessionId] ?? null;
    const texts = activeHeadTexts(state) ?? state.texts[sessionId] ?? [];
    const before =
      queued && !(queued.kind === "replace_at_cell" && queued.run !== undefined)
        ? queued.before
        : legacyActions.seatText(inspect, texts, table, row, col);
    const seat = legacyActions.seatAt(inspect, table, row, col);
    const charPr = autoCharPr(seat, queued?.charPr);
    if (after === before && queued) {
      await legacyActions.undoQueuedOp(queued.opId);
      return true;
    }
    await queueCanvasEdit({
      opId: `op-find-t${table}r${row}c${col}`,
      table, row, col, text: after, before,
      origin: "user",
      ...(charPr ? { charPr } : {}),
      ...(before
        ? { kind: "replace_at_cell", mode: "replace", expect: before }
        : { kind: "fill_cell", ...(after.includes("\n") ? { lines: after.split(/\r?\n/) } : {}) }),
    }, sessionId);
    return true;
  }

  if (match.targetType === "para" && match.atPara !== undefined) {
    const run = match.run ?? 0;
    const queued = queuedRunOpAt(state, match.atPara, run);
    await queueCanvasEdit({
      opId: `op-find-p${match.atPara}r${run}`,
      kind: "set_run",
      atPara: match.atPara,
      run,
      text: after,
      before: queued?.before ?? match.text,
      origin: "user",
    }, sessionId);
    return true;
  }

  return false;
}

export function findTextPattern(query: string): RegExp {
  return new RegExp(query.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "giu");
}

export function replaceFindMatch(
  match: FindMatchItem,
  query: string,
  replacement: string,
): Promise<boolean> {
  const matched = match.text.slice(match.matchStart, match.matchEnd);
  if (!query.trim() || !matched || findTextPattern(query).exec(matched)?.[0] !== matched) {
    return Promise.resolve(false);
  }
  return replaceMatchText(
    match,
    match.text.slice(0, match.matchStart) + replacement + match.text.slice(match.matchEnd),
  );
}

export async function replaceAllFindMatches(
  matches: readonly FindMatchItem[],
  query: string,
  replacement: string,
): Promise<number> {
  const needle = query.trim();
  if (!needle) return 0;
  const pattern = findTextPattern(needle);
  const sessionId = getState().activeSessionId;
  const seen = new Set<string>();
  let count = 0;

  for (const match of matches) {
    if (getState().activeSessionId !== sessionId) break;
    const target = match.targetType === "cell"
      ? cellKey(match.table ?? 0, match.row ?? 0, match.col ?? 0)
      : `p:${match.atPara}#${match.run ?? 0}`;
    if (seen.has(target)) continue;
    seen.add(target);
    if (await replaceMatchText(match, match.text.replace(pattern, () => replacement))) count += 1;
  }
  return count;
}
