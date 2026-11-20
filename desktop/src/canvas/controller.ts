import type {
  CanvasChangeDecision,
  CanvasChangeRef,
  PageFit,
  PageSource,
  PageViewMode,
} from "../model/page";
import { defineDocSlice } from "../store";

export interface DecisionUndoEntry {
  itemId: string;
  prev: CanvasChangeDecision;
  next: CanvasChangeDecision;
}

export interface CanvasDocSlice {
  view: PageViewMode;
  selectedChangeId: string | null;
  selectedSeatKey: string | null;
  hoveredSeatKey: string | null;
  hoveredSeatLabel: string | null;
  decisions: Record<string, CanvasChangeDecision>;
  decisionUndoStack: DecisionUndoEntry[];
  pageFit: PageFit;
  zoom: number;
  effectiveZoomPct: number | null;
  page: number;
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

// --- Exposed `canvas` controller API (J1 §5) --------------------------------

type SelectListener = (itemId: string | null) => void;
const selectListeners = new Set<SelectListener>();
let activeChangesSnapshot: readonly CanvasChangeRef[] = [];
let activePageSource: PageSource | null = null;
let scrollRequestNonce = 0;
let lastSelectOrigin: "canvas" | "external" = "external";

export function publishCanvasContext(
  changes: readonly CanvasChangeRef[],
  pageSource: PageSource | null,
): void {
  activeChangesSnapshot = changes;
  activePageSource = pageSource;
}

export function getPublishedChanges(): readonly CanvasChangeRef[] {
  return activeChangesSnapshot;
}

export function getPublishedPageSource(): PageSource | null {
  return activePageSource;
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

export function scrollCanvasToTarget(opts: {
  cellKey?: string | null;
  atPara?: number | null;
  itemId?: string | null;
}): void {
  if (typeof document === "undefined") return;
  const container = document.querySelector<HTMLElement>('[data-testid="canvas-scroll"]');
  if (!container) return;

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
  if (!targetEl) return;

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
