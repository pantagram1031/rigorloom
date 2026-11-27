import { useSyncExternalStore } from "react";

import type {
  CanvasChangeDecision,
  CanvasChangeRef,
  PageFit,
  PageSource,
  PageViewMode,
} from "../model/page";
import { recordDecision, type DecisionRecord } from "../model/changes";
import type { RasterSource } from "../model/enginePage";
import { defineDocSlice } from "../store";

export interface DecisionUndoEntry {
  itemId: string;
  contentHash: string;
  prev: DecisionRecord | undefined;
}

export interface CanvasDocSlice {
  view: PageViewMode;
  selectedChangeId: string | null;
  selectedSeatKey: string | null;
  hoveredSeatKey: string | null;
  hoveredSeatLabel: string | null;
  decisions: Record<string, DecisionRecord>;
  decisionUndoStack: DecisionUndoEntry[];
  pageFit: PageFit;
  zoom: number;
  effectiveZoomPct: number | null;
  page: number;
  pageCount: number;
  rasterSource: RasterSource | null;
  rasterApprox: boolean;
  fontRefresh: number;
  findRequest: "find" | "replace" | 1 | -1 | null;
  findQuery: string;
  replaceQuery: string;
  activeFindIndex: number;
  activeFindCellKey: string | null;
  drying: boolean;
  statusNotice: string | null;
  narrowReadZoom: boolean;
}

export const INITIAL_CANVAS_SLICE: CanvasDocSlice = {
  view: "marks",
  selectedChangeId: null,
  selectedSeatKey: null,
  hoveredSeatKey: null,
  hoveredSeatLabel: null,
  decisions: {},
  decisionUndoStack: [],
  pageFit: "width",
  zoom: 1,
  effectiveZoomPct: null,
  page: 1,
  pageCount: 1,
  rasterSource: null,
  rasterApprox: false,
  fontRefresh: 0,
  findRequest: null,
  findQuery: "",
  replaceQuery: "",
  activeFindIndex: 0,
  activeFindCellKey: null,
  drying: false,
  statusNotice: null,
  narrowReadZoom: false,
};

export const canvasSlice = defineDocSlice<CanvasDocSlice>(
  "canvas.page",
  INITIAL_CANVAS_SLICE,
);

export function useCanvasSlice(sessionId?: string | null): CanvasDocSlice {
  return canvasSlice.use(sessionId);
}

export function getCanvasSlice(sessionId?: string | null): CanvasDocSlice {
  return canvasSlice.get(sessionId);
}

export function setCanvasSlice(
  patch: Partial<CanvasDocSlice> | ((prev: CanvasDocSlice) => CanvasDocSlice),
  sessionId?: string | null,
): void {
  const previous = canvasSlice.get(sessionId);
  const next = typeof patch === "function" ? patch(previous) : patch;
  if (next !== previous) canvasSlice.set(sessionId, next);
}

type DecidableChange = Pick<CanvasChangeRef, "id" | "contentHash" | "decision">;

export function recordCanvasDecisions(
  changes: readonly DecidableChange[],
  decision: CanvasChangeDecision,
): void {
  const slice = getCanvasSlice();
  let decisions = slice.decisions;
  const undo = slice.decisionUndoStack.slice();
  for (const item of changes) {
    if (item.decision === decision) continue;
    const prev = decisions[item.id];
    undo.push({
      itemId: item.id,
      contentHash: item.contentHash,
      prev: prev?.contentHash === item.contentHash ? prev : undefined,
    });
    decisions = recordDecision(decisions, item, decision);
  }
  if (decisions !== slice.decisions) setCanvasSlice({ decisions, decisionUndoStack: undo.slice(-200) });
}

export function restoreCanvasDecision(changes: readonly DecidableChange[]): string | null {
  const slice = getCanvasSlice();
  const undo = slice.decisionUndoStack.slice();
  while (undo.length > 0) {
    const last = undo.pop()!;
    if (!changes.some((item) => item.id === last.itemId && item.contentHash === last.contentHash)) continue;
    const decisions = { ...slice.decisions };
    if (last.prev) decisions[last.itemId] = last.prev;
    else delete decisions[last.itemId];
    setCanvasSlice({ decisions, decisionUndoStack: undo });
    return last.itemId;
  }
  if (slice.decisionUndoStack.length) setCanvasSlice({ decisionUndoStack: [] });
  return null;
}

// --- Exposed `canvas` controller API (J1 §5) --------------------------------

type SelectListener = (itemId: string | null) => void;
const selectListeners = new Set<SelectListener>();
const contextListeners = new Set<() => void>();
let activeChangesSnapshot: readonly CanvasChangeRef[] = [];
let activePageSource: PageSource | null = null;
let activeKnownPagesRev: string | null = null;
let activeKnownPages = new Map<string, number>();
let scrollRequestNonce = 0;
let lastSelectOrigin: "canvas" | "external" = "external";

function subscribeCanvasContext(cb: () => void): () => void {
  contextListeners.add(cb);
  return () => {
    contextListeners.delete(cb);
  };
}

export function publishCanvasContext(
  changes: readonly CanvasChangeRef[],
  pageSource: PageSource | null,
): void {
  const prevSource = activePageSource;
  activeChangesSnapshot = changes;
  activePageSource = pageSource;
  let pagesChanged = false;
  if (!pageSource) {
    if (activeKnownPages.size > 0) {
      activeKnownPages = new Map();
      activeKnownPagesRev = null;
      pagesChanged = true;
    }
  } else {
    if (pageSource.rev !== activeKnownPagesRev) {
      activeKnownPages = new Map();
      activeKnownPagesRev = pageSource.rev;
      pagesChanged = true;
    }
    if (pageSource.kind === "engine") {
      let nextMap: Map<string, number> | null = null;
      const record = (k: string | undefined, p: number) => {
        if (!k) return;
        const cur = (nextMap ?? activeKnownPages).get(k);
        if (cur !== p) {
          if (!nextMap) nextMap = new Map(activeKnownPages);
          nextMap.set(k, p);
        }
      };
      for (const s of pageSource.seats()) {
        if (typeof s.page === "number" && Number.isFinite(s.page) && s.page >= 1) {
          record(s.key, s.page);
          record(s.address, s.page);
        }
      }
      const total = Math.max(1, pageSource.pageCount());
      for (let p = 1; p <= total; p += 1) {
        const layer = pageSource.layer(p, "clean");
        if (layer.kind === "engine") {
          for (const box of layer.boxes) {
            if (box.address) record(box.address, p);
          }
        }
      }
      if (nextMap) {
        activeKnownPages = nextMap;
        pagesChanged = true;
      }
    }
  }
  if (prevSource !== pageSource || pagesChanged) {
    for (const cb of contextListeners) {
      cb();
    }
  }
}

export function getPublishedChanges(): readonly CanvasChangeRef[] {
  return activeChangesSnapshot;
}

export function getPublishedPageSource(): PageSource | null {
  return activePageSource;
}

export function getPublishedKnownPages(): ReadonlyMap<string, number> {
  return activeKnownPages;
}

const CELL_KEY = /^c:(\d+):(\d+):(\d+)$/;
let measuredPagesKey: string | null = null;
let measuredPageNumbers = new Set<number>();

/** True when `page` of this revision has already been measured in the background. */
export function isPageMeasured(rev: string, page: number): boolean {
  return measuredPagesKey === rev && measuredPageNumbers.has(page);
}

/**
 * Record the addresses one page's engine geometry holds, measured in the
 * background so that pages the user has not opened are known too. An address
 * keeps the first page it was found on; a revision other than the published
 * one is ignored.
 */
export function publishMeasuredPage(rev: string, page: number, addresses: readonly string[]): void {
  if (rev !== activeKnownPagesRev || !Number.isSafeInteger(page) || page < 1) return;
  if (measuredPagesKey !== rev) {
    measuredPagesKey = rev;
    measuredPageNumbers = new Set();
  }
  measuredPageNumbers.add(page);
  let next: Map<string, number> | null = null;
  for (const address of addresses) {
    if (!address || activeKnownPages.has(address) || next?.has(address)) continue;
    next ??= new Map(activeKnownPages);
    next.set(address, page);
  }
  if (!next) return;
  activeKnownPages = next;
  for (const cb of contextListeners) cb();
}

/**
 * The page a target is known to be on: a cell (`c:t:r:c`), a paragraph, or a
 * change (by its cell or paragraph). Null when no drawn or measured page holds it.
 */
export function knownPageOf(target: {
  cellKey?: string | null;
  atPara?: number | null;
  itemId?: string | null;
}): number | null {
  let cellKey = target.cellKey ?? null;
  let atPara = target.atPara ?? null;
  if (target.itemId) {
    const change = activeChangesSnapshot.find((item) => item.id === target.itemId);
    cellKey ??= change?.cellKey ?? null;
    atPara ??= change?.atPara ?? null;
  }
  const keys: string[] = [];
  if (cellKey) {
    keys.push(cellKey);
    const cell = CELL_KEY.exec(cellKey);
    if (cell) keys.push(`t${cell[1]}/r${cell[2]}/c${cell[3]}`);
  }
  if (atPara !== null && Number.isFinite(atPara)) keys.push(`p${atPara}`);
  for (const key of keys) {
    const page = activeKnownPages.get(key);
    if (typeof page === "number" && Number.isSafeInteger(page) && page >= 1) return page;
  }
  return null;
}

/** Turn the canvas to a target's known page; true when the page changed. */
export function turnToTargetPage(target: Parameters<typeof knownPageOf>[0]): boolean {
  const page = knownPageOf(target);
  const slice = getCanvasSlice();
  if (page === null || page === slice.page || page > Math.max(1, slice.pageCount)) return false;
  setCanvasSlice({ page });
  return true;
}

/** The known-pages map; a new map whenever a page is drawn or measured. */
export function usePublishedKnownPages(): ReadonlyMap<string, number> {
  return useSyncExternalStore(
    subscribeCanvasContext,
    getPublishedKnownPages,
    getPublishedKnownPages,
  );
}

export function usePublishedPageSource(): PageSource | null {
  return useSyncExternalStore(
    subscribeCanvasContext,
    getPublishedPageSource,
    getPublishedPageSource,
  );
}

export function getScrollRequestState(): { nonce: number; origin: "canvas" | "external" } {
  return { nonce: scrollRequestNonce, origin: lastSelectOrigin };
}

export interface CanvasController {
  select(itemId: string | null, options?: { fromCanvas?: boolean }): void;
  onSelect(cb: SelectListener): () => void;
  setView(view: PageViewMode): void;
  getView(): PageViewMode;
}

export const canvas: CanvasController = {
  select(itemId, options) {
    lastSelectOrigin = options?.fromCanvas ? "canvas" : "external";
    if (!options?.fromCanvas) {
      scrollRequestNonce += 1;
    }
    setCanvasSlice({ selectedChangeId: itemId });
    // A change picked outside the canvas may be on a page not drawn yet.
    if (itemId && !options?.fromCanvas) turnToTargetPage({ itemId });
    for (const cb of selectListeners) {
      cb(itemId);
    }
  },
  onSelect(cb) {
    selectListeners.add(cb);
    return () => {
      selectListeners.delete(cb);
    };
  },
  setView(view) {
    setCanvasSlice({ view });
  },
  getView() {
    return getCanvasSlice().view;
  },
};

type ScrollTarget = { cellKey?: string | null; atPara?: number | null; itemId?: string | null };
const PAGE_TURN_SCROLL_WAIT_MS = 3000;
let pageTurnScrollRequest = 0;

function findTarget(container: HTMLElement, opts: ScrollTarget): HTMLElement | null {
  const esc = (v: string) =>
    typeof CSS !== "undefined" && typeof CSS.escape === "function" ? CSS.escape(v) : v;

  let targetEl: HTMLElement | null = null;
  if (opts.itemId) {
    targetEl = container.querySelector<HTMLElement>(`[data-mark-item="${esc(opts.itemId)}"]`);
  }
  if (!targetEl && opts.cellKey) {
    targetEl = container.querySelector<HTMLElement>(`[data-cell-key="${esc(opts.cellKey)}"]`);
  }
  if (!targetEl && opts.atPara !== undefined && opts.atPara !== null) {
    targetEl = container.querySelector<HTMLElement>(`[data-para-key="${opts.atPara}"]`);
  }
  return targetEl;
}

export function scrollCanvasToTarget(opts: ScrollTarget): void {
  if (typeof document === "undefined") return;
  const container = document.querySelector<HTMLElement>('[data-testid="canvas-scroll"]');
  if (!container) return;

  const targetEl = findTarget(container, opts);
  if (!targetEl) {
    // The target is on another page: turn to it, then scroll once it is drawn.
    if (!turnToTargetPage(opts)) return;
    const request = ++pageTurnScrollRequest;
    const deadline = Date.now() + PAGE_TURN_SCROLL_WAIT_MS;
    const retry = () => {
      if (request !== pageTurnScrollRequest) return;
      const live = document.querySelector<HTMLElement>('[data-testid="canvas-scroll"]');
      if (live && findTarget(live, opts)) {
        scrollCanvasToTarget(opts);
      } else if (Date.now() < deadline && typeof requestAnimationFrame === "function") {
        requestAnimationFrame(retry);
      }
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(retry);
    return;
  }

  const cRect = container.getBoundingClientRect();
  const tRect = targetEl.getBoundingClientRect();
  const targetTop = container.scrollTop + (tRect.top - cRect.top) - container.clientHeight / 3;
  const reduced =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  container.scrollTo({
    top: Math.max(0, targetTop),
    behavior: reduced ? "auto" : "smooth",
  });
}
