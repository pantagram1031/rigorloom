import * as legacyActions from "../actions";
import { wp3t } from "../i18n/v2/wp3";
import type { CanvasChangeDecision, PageViewMode } from "../model/page";
import {
  cellKey,
  getState,
  queuedCellOpAt,
  setState,
  type QueuedOp,
} from "../store";
import type { InspectResult, RegionText, UiLanguage } from "../types";
import { classifyCellEditMode } from "../workspace/fieldLabels";
import {
  canvas,
  getCanvasSlice,
  getPublishedChanges,
  setCanvasSlice,
} from "./controller";

export type QueueMutationAdapter = {
  upsertOp: (op: QueuedOp, replaceOpId?: string | null) => Promise<void> | void;
  removeOp: (opId: string) => Promise<void> | void;
};

let customQueueAdapter: QueueMutationAdapter | null = null;

export function setCanvasQueueAdapter(adapter: QueueMutationAdapter | null): void {
  customQueueAdapter = adapter;
}

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
  const texts = options?.texts ?? (sessionId ? state.texts[sessionId] ?? [] : []);
  const queued = queuedCellOpAt(state, table, row, col);
  const seat = legacyActions.seatAt(inspect, table, row, col);
  const baseText =
    queued?.before ?? legacyActions.seatText(inspect, texts, table, row, col);
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
 * Commit an in-place cell edit. Never called on keystroke; fires only on
 * explicit Enter / Tab / Ctrl+Enter / blur commit.
 */
export async function commitCellEditV2(
  nextValue: string,
  options?: {
    inspect?: InspectResult | null;
  },
): Promise<CommitCellEditResult> {
  const state = getState();
  const edit = state.inlineEdit;
  if (!edit || edit.kind !== "cell") {
    return { committed: false };
  }

  setState({
    inlineEdit: null,
    lastCommit: { value: nextValue, composed: state.sawComposition },
    sawComposition: false,
  });

  const before = edit.before;
  if (nextValue === before || (before.trim().length === 0 && nextValue === "")) {
    if (edit.opId) {
      if (customQueueAdapter) {
        await customQueueAdapter.removeOp(edit.opId);
      } else {
        await legacyActions.undoQueuedOp(edit.opId);
      }
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

  if (customQueueAdapter) {
    await customQueueAdapter.upsertOp(nextOp, edit.opId);
  } else {
    if (edit.opId) {
      await legacyActions.removeOp(edit.opId);
    }
    await legacyActions.addQueueOp(nextOp);
  }

  // User's own edit is immediately accepted (`내 입력`).
  setCanvasSlice((prev) => ({
    ...prev,
    decisions: { ...prev.decisions, [nextOp.opId]: "accepted" },
    selectedChangeId: nextOp.opId,
  }));

  return {
    committed: true,
    op: nextOp,
    modeLabelKey,
    hasFormText: classification.hasFormText,
    bodyStyleMatched: Boolean(resolvedCharPr && seat?.scriptAnomaly),
  };
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
  if (target?.isStale && decision !== "pending") {
    return;
  }

  const slice = getCanvasSlice();
  const prev = slice.decisions[itemId] ?? target?.decision ?? "pending";
  if (prev === decision) return;

  const nextDecisions = { ...slice.decisions, [itemId]: decision };
  const nextUndo = [
    ...slice.decisionUndoStack,
    { itemId, prev, next: decision },
  ];

  let nextSelected = slice.selectedChangeId;
  if (decision === "accepted" && changes.length > 0) {
    const idx = changes.findIndex((c) => c.id === itemId);
    const after = changes
      .slice(idx + 1)
      .find((c) => (nextDecisions[c.id] ?? c.decision) === "pending");
    const before = changes
      .slice(0, Math.max(0, idx))
      .find((c) => (nextDecisions[c.id] ?? c.decision) === "pending");
    nextSelected = after?.id ?? before?.id ?? itemId;
  }

  setCanvasSlice({
    decisions: nextDecisions,
    decisionUndoStack: nextUndo,
    selectedChangeId: nextSelected,
  });

  if (nextSelected && nextSelected !== slice.selectedChangeId) {
    canvas.select(nextSelected);
  }
}

export function undoCanvasDecision(): boolean {
  const slice = getCanvasSlice();
  if (slice.decisionUndoStack.length === 0) return false;
  const last = slice.decisionUndoStack[slice.decisionUndoStack.length - 1];
  setCanvasSlice({
    decisions: { ...slice.decisions, [last.itemId]: last.prev },
    decisionUndoStack: slice.decisionUndoStack.slice(0, -1),
    selectedChangeId: last.itemId,
  });
  canvas.select(last.itemId);
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

export async function replaceFindMatch(
  match: FindMatchItem,
  query: string,
  replacement: string,
): Promise<boolean> {
  if (!query) return false;
  const before = match.text;
  const idx = before.indexOf(query);
  if (idx < 0) return false;
  const after = before.slice(0, idx) + replacement + before.slice(idx + query.length);

  if (match.targetType === "cell" && match.table !== undefined && match.row !== undefined && match.col !== undefined) {
    const opId = `op-find-t${match.table}r${match.row}c${match.col}`;
    const op: QueuedOp = {
      opId,
      kind: "replace_at_cell",
      table: match.table,
      row: match.row,
      col: match.col,
      ...(match.run !== undefined ? { run: match.run } : {}),
      text: after,
      mode: "replace",
      expect: before,
      before,
      origin: "user",
    };
    if (customQueueAdapter) {
      await customQueueAdapter.upsertOp(op, opId);
    } else {
      await legacyActions.addQueueOp(op);
    }
    setCanvasSlice((prev) => ({
      ...prev,
      decisions: { ...prev.decisions, [opId]: "accepted" },
      selectedChangeId: opId,
    }));
    return true;
  }

  if (match.targetType === "para" && match.atPara !== undefined) {
    const opId = `op-find-p${match.atPara}r${match.run ?? 0}`;
    const op: QueuedOp = {
      opId,
      kind: "set_run",
      atPara: match.atPara,
      run: match.run ?? 0,
      text: after,
      before,
      origin: "user",
    };
    if (customQueueAdapter) {
      await customQueueAdapter.upsertOp(op, opId);
    } else {
      await legacyActions.addQueueOp(op);
    }
    setCanvasSlice((prev) => ({
      ...prev,
      decisions: { ...prev.decisions, [opId]: "accepted" },
      selectedChangeId: opId,
    }));
    return true;
  }

  return false;
}

export async function replaceAllFindMatches(
  matches: readonly FindMatchItem[],
  query: string,
  replacement: string,
): Promise<number> {
  if (!query || matches.length === 0) return 0;
  const seenTargets = new Set<string>();
  let count = 0;

  for (const match of matches) {
    const targetId =
      match.targetType === "cell"
        ? `${match.table}:${match.row}:${match.col}:${match.run ?? "all"}`
        : `p:${match.atPara}:${match.run ?? 0}`;
    if (seenTargets.has(targetId)) continue;
    seenTargets.add(targetId);

    const after = match.text.split(query).join(replacement);
    if (after === match.text) continue;

    if (match.targetType === "cell" && match.table !== undefined && match.row !== undefined && match.col !== undefined) {
      const opId = `op-find-t${match.table}r${match.row}c${match.col}`;
      const op: QueuedOp = {
        opId,
        kind: "replace_at_cell",
        table: match.table,
        row: match.row,
        col: match.col,
        ...(match.run !== undefined ? { run: match.run } : {}),
        text: after,
        mode: "replace",
        expect: match.text,
        before: match.text,
        origin: "user",
      };
      if (customQueueAdapter) {
        await customQueueAdapter.upsertOp(op, opId);
      } else {
        await legacyActions.addQueueOp(op);
      }
      setCanvasSlice((prev) => ({
        ...prev,
        decisions: { ...prev.decisions, [opId]: "accepted" },
      }));
      count += 1;
    } else if (match.targetType === "para" && match.atPara !== undefined) {
      const opId = `op-find-p${match.atPara}r${match.run ?? 0}`;
      const op: QueuedOp = {
        opId,
        kind: "set_run",
        atPara: match.atPara,
        run: match.run ?? 0,
        text: after,
        before: match.text,
        origin: "user",
      };
      if (customQueueAdapter) {
        await customQueueAdapter.upsertOp(op, opId);
      } else {
        await legacyActions.addQueueOp(op);
      }
      setCanvasSlice((prev) => ({
        ...prev,
        decisions: { ...prev.decisions, [opId]: "accepted" },
      }));
      count += 1;
    }
  }
  return count;
}
