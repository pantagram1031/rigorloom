import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type MutableRefObject,
  type ReactNode,
  type TouchEvent,
  type WheelEvent,
} from "react";

import {
  beginEdit,
  beginStaticCellEdit,
  cancelEdit,
  commitEdit,
  loadGeometry,
  renderCurrentPage,
  setInlineEditMultiline,
  togglePrintView,
  toggleShowOriginal,
} from "../actions";
import {
  cellClassLabel,
  errorCodeMessage,
  renderGradeLabel,
  t,
} from "../i18n/vocabulary";
import {
  cellKey,
  fitScale,
  getState,
  setFittedZoom,
  setPageFit,
  setZoom,
  useWorkspace,
} from "../store";
import type {
  GraphCell,
  GraphParagraph,
  InspectResult,
  RegionText,
  UiLanguage,
} from "../types";
import type { IndexedChange, RowGuardAudit } from "../workspace/guardHelper";
import { SeatEditor } from "./SeatEditor";

/**
 * Align sequential cell runs against `inspect.graph.paragraphs` so runs belonging
 * to distinct `<hp:p>` paragraphs render on separate lines (e.g. `(0,1,0)`),
 * while runs from the same paragraph render inline on one line (e.g. `(0,0,0)`).
 */
export function groupCellRunsIntoParagraphs<R extends { text: string }>(
  runs: readonly R[],
  inspectParagraphs: readonly GraphParagraph[],
): R[][] {
  if (runs.length === 0) return [];
  if (runs.length === 1) return [[runs[0]]];

  const norm = (s: string) => s.replace(/\s+/g, " ").trim();
  const paraTexts = inspectParagraphs.map((p) => norm(p.text));

  let bestGroups: R[][] | null = null;
  let bestMatchedCount = 1;

  for (let startR = 0; startR < runs.length; startR++) {
    const firstNorm = norm(runs[startR].text);
    if (!firstNorm) continue;

    for (let startP = 0; startP < paraTexts.length; startP++) {
      const target0 = paraTexts[startP];
      if (!target0) continue;
      if (target0 !== firstNorm && !target0.startsWith(firstNorm)) continue;

      const groups: R[][] = [];
      let currentGroup: R[] = startR > 0 ? runs.slice(0, startR) : [];
      let matchedCount = 0;
      let pIdx = startP;
      let acc = "";

      for (let r = startR; r < runs.length; r++) {
        const run = runs[r];
        const candidateAcc = norm(acc + run.text);
        const curTarget = pIdx < paraTexts.length ? paraTexts[pIdx] : "";

        if (
          acc.length > 0 &&
          curTarget &&
          (acc === curTarget || !curTarget.startsWith(candidateAcc))
        ) {
          const rNorm = norm(run.text);
          let nextP = -1;
          if (rNorm) {
            for (let scan = pIdx + 1; scan < paraTexts.length; scan++) {
              const cand = paraTexts[scan];
              if (cand && (cand === rNorm || cand.startsWith(rNorm))) {
                nextP = scan;
                break;
              }
            }
          }
          if (nextP !== -1) {
            groups.push(currentGroup);
            currentGroup = [run];
            pIdx = nextP;
            acc = rNorm;
            if (acc === paraTexts[pIdx]) matchedCount++;
            continue;
          }
        }

        currentGroup.push(run);
        acc = candidateAcc;
        if (curTarget && acc === curTarget) {
          matchedCount++;
        }
      }
      if (currentGroup.length > 0) {
        groups.push(currentGroup);
      }

      if (groups.length > 1 && matchedCount > bestMatchedCount) {
        bestMatchedCount = matchedCount;
        bestGroups = groups;
      }
    }
  }

  return bestGroups ?? [runs.slice()];
}

function measureLabelWidthPx(el: HTMLElement, label: string): number {
  try {
    const cs = getComputedStyle(el);
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.font = `${cs.fontWeight || "400"} ${cs.fontSize || "12px"} ${cs.fontFamily || "sans-serif"}`;
      return Math.ceil(ctx.measureText(label).width);
    }
  } catch {
    // Fallback below when canvas is unavailable.
  }
  return label.length * 14;
}

function EmptyBlankSlot({ label }: { label: string }) {
  const slotRef = useRef<HTMLDivElement | null>(null);
  const [showLabel, setShowLabel] = useState(false);

  useLayoutEffect(() => {
    const el = slotRef.current;
    if (!el) return;
    const measure = () => {
      const needed = Math.max(88, measureLabelWidthPx(el, label) + 18);
      setShowLabel(el.clientWidth >= needed);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [label]);

  return (
    <div ref={slotRef} className="page-empty-blank" aria-hidden="true">
      {showLabel ? <span className="page-seat-hint">{label}</span> : null}
    </div>
  );
}

function renderGroupMarker(
  groupChanges: readonly IndexedChange[],
  rowAudits: Record<string, RowGuardAudit>,
  selectedChangeId: string | null,
  onClickMarker: (e: MouseEvent, opId: string) => void,
) {
  if (groupChanges.length === 0) return null;
  const first = groupChanges[0];
  const last = groupChanges[groupChanges.length - 1];
  const label =
    groupChanges.length === 1
      ? String(first.ordinal)
      : `${first.ordinal}-${last.ordinal}`;
  const status = groupChanges.some(
    (ch) => rowAudits[ch.opId]?.status === "changed",
  )
    ? "changed"
    : groupChanges.some((ch) => rowAudits[ch.opId]?.status === "needs_fixes")
      ? "needs_fixes"
      : groupChanges.some((ch) => rowAudits[ch.opId]?.status === "kept")
        ? "kept"
        : "none";
  const isSelected = groupChanges.some((ch) => ch.opId === selectedChangeId);

  return (
    <div className="page-marker-strip">
      <button
        type="button"
        className={`page-marker-badge page-marker-badge--${status}${
          isSelected ? " page-marker-badge--selected" : ""
        }`}
        data-testid={`page-marker-${first.ordinal}`}
        data-marker-ordinals={groupChanges.map((c) => c.ordinal).join(",")}
        data-marker-op-id={first.opId}
        data-marker-op-ids={groupChanges.map((c) => c.opId).join(" ")}
        aria-pressed={isSelected}
        onClick={(e) => onClickMarker(e, first.opId)}
      >
        {label}
      </button>
    </div>
  );
}

const NOWRAP_TOKEN_RE = /(\(\d+(?:-\d+)+\)|\d+(?:-\d+)+)/g;

function renderTextWithNowrapTokens(text: string): ReactNode {
  if (!text) return text;
  const parts = text.split(NOWRAP_TOKEN_RE);
  if (parts.length === 1) return text;
  return parts.map((part, idx) =>
    idx % 2 === 1 ? (
      <span key={idx} className="page-nowrap-token">
        {part}
      </span>
    ) : (
      part
    ),
  );
}

const HWPUNIT_PER_INCH = 7200;
const PX_PER_INCH = 96;

function hwpunitToPx(units: number | undefined, fallbackMm: number): number {
  if (typeof units === "number" && Number.isFinite(units) && units > 0) {
    return Math.round((units / HWPUNIT_PER_INCH) * PX_PER_INCH);
  }
  return Math.round((fallbackMm / 25.4) * PX_PER_INCH);
}

function clampMarginPx(units: number | undefined, fallbackMm: number): number {
  const px = hwpunitToPx(units, fallbackMm);
  return Math.max(20, Math.min(120, px));
}

export const FILL_MIN_TAPPABLE_BLANK_PX = 32;

export interface SheetZoomInput {
  isFillMode: boolean;
  isCompactMobile: boolean;
  mobileExplicitFit: boolean;
  pageFit: "width" | "page" | "free";
  boxWidth: number;
  naturalWidthPx: number;
  zoom: number;
  isBlankFocused: boolean;
  minBlankHeightPx: number | null;
}

export function computeEffectiveSheetZoom({
  isFillMode,
  isCompactMobile,
  mobileExplicitFit,
  pageFit,
  boxWidth,
  naturalWidthPx,
  zoom,
  isBlankFocused,
  minBlankHeightPx,
}: SheetZoomInput): number {
  const widthFitZoom =
    boxWidth > 0 && naturalWidthPx > 0
      ? Math.max(0.25, Math.min(2, Math.floor((boxWidth / naturalWidthPx) * 1000) / 1000))
      : null;

  let baseZoom: number;
  if (isCompactMobile) {
    if ((isFillMode || mobileExplicitFit) && pageFit === "width" && widthFitZoom !== null) {
      baseZoom = widthFitZoom;
    } else {
      baseZoom = pageFit === "free" ? zoom : 1;
    }
  } else if (pageFit === "width" && widthFitZoom !== null) {
    baseZoom = widthFitZoom;
  } else {
    baseZoom = zoom;
  }

  if (
    isFillMode &&
    isBlankFocused &&
    pageFit === "width" &&
    widthFitZoom !== null &&
    minBlankHeightPx !== null &&
    minBlankHeightPx > 0 &&
    minBlankHeightPx * baseZoom < FILL_MIN_TAPPABLE_BLANK_PX &&
    baseZoom < 1
  ) {
    return 1;
  }

  return baseZoom;
}

interface PageSheetProps {
  sessionId: string;
  inspect: InspectResult;
  texts: readonly RegionText[];
  textMap: Record<string, RegionText>;
  changes: readonly IndexedChange[];
  rowAudits: Record<string, RowGuardAudit>;
  selectedChangeId: string | null;
  language: UiLanguage;
  onSelectChange: (opId: string) => void;
  /** Optional mode selector ("review" default, or "fill" for blank form entry). */
  mode?: "review" | "fill";
  /** Fill mode: ref attached to `.page-sheet-viewport` (`data-testid="fill-sheet-anchor"`). */
  sheetAnchorRef?: MutableRefObject<HTMLDivElement | null>;
  /** Fill mode: currently highlighted cell key (`t{table}r{row}c{col}`). */
  selectedCellKey?: string | null;
  /** Fill mode: localized label map by cell key for blank slot hints. */
  blankFieldLabels?: Record<string, string>;
  /** Fill mode: blank cell click handler. */
  onSelectBlankCell?: (table: number, row: number, col: number) => void;
  /** Fill mode: non-blank static cell click handler (shows static notice + escape hatch). */
  onSelectStaticCell?: (cell: GraphCell, tableIdx: number) => void;
  /** Fill mode: Tab / Shift+Tab cycling between blanks. */
  onCycleBlank?: (
    table: number,
    row: number,
    col: number,
    direction: 1 | -1,
    currentValue: string,
  ) => void;
  /** Fill mode: Esc handler to return focus to `.page-sheet-viewport` (`fill-sheet-anchor`). */
  onEscapeBlank?: () => void;
  /** Fill mode: Enter commit handler that advances to next blank cleanly. */
  onAdvanceBlankAfterEnter?: (
    table: number,
    row: number,
    col: number,
    committedValue: string,
  ) => void;
  /**
   * What the page is drawn from, as the sub-bar sentence: the head 수정본,
   * the original, or a proposal on one of them. Defaults to the plain preview
   * caveat for a document with no 수정본.
   */
  subjectLabel?: string;
  /** Present once a head 수정본 exists: offers 원본 보기 / 수정본 보기. */
  originalToggle?: { showingOriginal: boolean };
  /**
   * The source's own cell texts, when `texts` are a 수정본's. Body paragraphs
   * come from the source graph, so the source's cell strings are what decide
   * which of them live inside a cell; without this a header cell whose text
   * the 수정본 changed would also be drawn again as loose paragraphs.
   */
  sourceTexts?: readonly RegionText[];
}

export function PageSheet({
  sessionId,
  inspect,
  texts,
  textMap,
  changes,
  rowAudits,
  selectedChangeId,
  language,
  onSelectChange,
  mode = "review",
  sheetAnchorRef,
  selectedCellKey = null,
  blankFieldLabels,
  onSelectBlankCell,
  onSelectStaticCell,
  onCycleBlank,
  onEscapeBlank,
  onAdvanceBlankAfterEnter,
  subjectLabel,
  originalToggle,
  sourceTexts,
}: PageSheetProps) {
  const isFillMode = mode === "fill";
  const zoom = useWorkspace((s) => s.zoom);
  const pageFit = useWorkspace((s) => s.pageFit);
  const mobileReviewPane = useWorkspace((s) => s.mobileReviewPane);
  const mobileExplicitFit = useWorkspace((s) => s.mobileExplicitFit);
  const page = useWorkspace((s) => s.page);
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const printViewEnabled = useWorkspace((s) => s.printViewEnabled);
  const capabilities = useWorkspace((s) => s.capabilities);
  const render = useWorkspace((s) => s.render);
  const renderPhase = useWorkspace((s) => s.renderPhase);
  const renderError = useWorkspace((s) => s.renderError);

  const viewportRef = useRef<HTMLDivElement | null>(null);
  const sheetRef = useRef<HTMLElement | null>(null);
  const skipNextAutoScroll = useRef(false);
  const pinchRef = useRef<{ dist: number; startZoom: number } | null>(null);
  const [boxWidth, setBoxWidth] = useState(0);
  const [naturalHeightMeasure, setNaturalHeightMeasure] = useState(0);
  const [restingSeatHeights, setRestingSeatHeights] = useState<{
    min: number | null;
    byKey: Record<string, number>;
  }>({ min: null, byKey: {} });
  const editingCellKey =
    inlineEdit && inlineEdit.kind === "cell"
      ? cellKey(inlineEdit.table, inlineEdit.row, inlineEdit.col)
      : null;
  const [isCompactMobile, setIsCompactMobile] = useState<boolean>(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(max-width: 640px)").matches
      : false,
  );

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(max-width: 640px)");
    const sync = () => setIsCompactMobile(mq.matches);
    sync();
    mq.addEventListener?.("change", sync);
    return () => mq.removeEventListener?.("change", sync);
  }, []);

  const metrics = inspect.summary?.pageMetrics;
  const naturalWidthPx = useMemo(
    () => hwpunitToPx(metrics?.width, 210),
    [metrics?.width],
  );
  const naturalHeightPx = useMemo(
    () => hwpunitToPx(metrics?.height, 297),
    [metrics?.height],
  );
  const padTopPx = useMemo(
    () => clampMarginPx(metrics?.margin?.top, 20),
    [metrics?.margin?.top],
  );
  const padRightPx = useMemo(
    () => clampMarginPx(metrics?.margin?.right, 20),
    [metrics?.margin?.right],
  );
  const padBottomPx = useMemo(
    () => clampMarginPx(metrics?.margin?.bottom, 15),
    [metrics?.margin?.bottom],
  );
  const padLeftPx = useMemo(
    () => clampMarginPx(metrics?.margin?.left, 20),
    [metrics?.margin?.left],
  );

  // Measure viewport to maintain fit-to-width cleanly at desktop & 390px mobile.
  useLayoutEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const update = () => {
      const cs = getComputedStyle(el);
      const padH =
        (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
      const padV =
        (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
      const w = Math.max(0, el.clientWidth - padH);
      const h = Math.max(0, el.clientHeight - padV);
      setBoxWidth(w);
      const cur = getState();
      const compact =
        typeof window !== "undefined" && typeof window.matchMedia === "function"
          ? window.matchMedia("(max-width: 640px)").matches
          : false;
      const allowFit = !compact || isFillMode || cur.mobileExplicitFit;
      if (allowFit && cur.pageFit === "width" && w > 0) {
        const next = fitScale(
          "width",
          { width: naturalWidthPx, height: naturalHeightPx },
          { width: w, height: Math.max(1, h) },
          cur.zoom,
        );
        if (Math.abs(next - cur.zoom) > 0.002) {
          setFittedZoom(next);
        }
      }
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [naturalWidthPx, naturalHeightPx, isFillMode]);

  useLayoutEffect(() => {
    const sheet = sheetRef.current;
    if (!sheet) return;
    const measure = () => {
      setNaturalHeightMeasure(Math.max(naturalHeightPx, sheet.scrollHeight));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(sheet);
    return () => ro.disconnect();
  }, [naturalHeightPx, inspect, changes, printViewEnabled]);

  useLayoutEffect(() => {
    if (!isFillMode) {
      setRestingSeatHeights({ min: null, byKey: {} });
      return;
    }
    const sheet = sheetRef.current;
    if (!sheet) return;
    const measureSeats = () => {
      const seats = sheet.querySelectorAll<HTMLElement>(
        editingCellKey === null
          ? ".page-cell--fill-seat"
          : ".page-cell--fill-seat:not(.page-cell--editing)",
      );
      if (seats.length === 0) return;
      let minH: number | null = null;
      const nextByKey: Record<string, number> = {};
      for (const seat of seats) {
        const h = seat.offsetHeight;
        if (h > 0) {
          const cellId = seat.getAttribute("data-cell-key");
          if (cellId) nextByKey[cellId] = h;
          if (minH === null || h < minH) minH = h;
        }
      }
      if (minH === null) return;
      setRestingSeatHeights((prev) => {
        if (editingCellKey !== null && prev.min !== null) {
          return prev;
        }
        return { min: minH, byKey: nextByKey };
      });
    };
    measureSeats();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measureSeats);
    ro.observe(sheet);
    return () => ro.disconnect();
  }, [isFillMode, editingCellKey, inspect, texts, changes, printViewEnabled, sessionId, naturalWidthPx]);

  const targetBlankHeight =
    (editingCellKey ? restingSeatHeights.byKey[editingCellKey] : undefined) ??
    restingSeatHeights.min;

  const effectiveZoom = useMemo(
    () =>
      computeEffectiveSheetZoom({
        isFillMode,
        isCompactMobile,
        mobileExplicitFit,
        pageFit,
        boxWidth,
        naturalWidthPx,
        zoom,
        isBlankFocused: isFillMode && editingCellKey !== null,
        minBlankHeightPx: targetBlankHeight,
      }),
    [
      isFillMode,
      isCompactMobile,
      mobileExplicitFit,
      pageFit,
      boxWidth,
      naturalWidthPx,
      zoom,
      editingCellKey,
      targetBlankHeight,
    ],
  );

  // If print view is toggled on externally (e.g. command palette), fetch page 1 once.
  useEffect(() => {
    if (!printViewEnabled) return;
    if (!render && renderPhase === "idle") {
      void renderCurrentPage(page);
      void loadGeometry(page);
    }
  }, [printViewEnabled, render, renderPhase, page, sessionId]);

  // Bidirectional scroll sync when a change row is selected from the list, stepper, or keyboard.
  useEffect(() => {
    if (!selectedChangeId) return;
    if (isCompactMobile && mobileReviewPane !== "sheet") return;
    if (skipNextAutoScroll.current) {
      skipNextAutoScroll.current = false;
      return;
    }
    const container = viewportRef.current;
    if (!container || container.clientWidth === 0) return;
    const esc = CSS.escape(selectedChangeId);
    const targetEl =
      container.querySelector<HTMLElement>('[data-selected-anchor="true"]') ??
      container.querySelector<HTMLElement>(`[data-marker-op-ids~="${esc}"]`) ??
      container.querySelector<HTMLElement>(`[data-marker-op-id="${esc}"]`) ??
      container.querySelector<HTMLElement>(`[data-cell-op-ids~="${esc}"]`);
    if (!targetEl) return;
    if (isCompactMobile) {
      const cRect = container.getBoundingClientRect();
      const tRect = targetEl.getBoundingClientRect();
      const left =
        container.scrollLeft + (tRect.left - cRect.left) + tRect.width / 2 - container.clientWidth / 2;
      const top =
        container.scrollTop + (tRect.top - cRect.top) + tRect.height / 2 - container.clientHeight / 2;
      container.scrollTo({
        left: Math.max(0, left),
        top: Math.max(0, top),
        behavior: "auto",
      });
      return;
    }
    targetEl.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [selectedChangeId, printViewEnabled, mobileReviewPane, isCompactMobile, effectiveZoom]);

  // Fill mode: keep keyboard-cycled blank cells visible inside the scrollable sheet viewport.
  useEffect(() => {
    if (!isFillMode || !selectedCellKey) return;
    const container = viewportRef.current;
    if (!container || container.clientWidth === 0) return;
    const targetEl = container.querySelector<HTMLElement>('[data-selected-anchor="true"]');
    if (!targetEl) return;
    targetEl.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [isFillMode, selectedCellKey, effectiveZoom]);

  const handleTouchStart = (e: TouchEvent<HTMLDivElement>) => {
    if (e.touches.length === 2) {
      const [a, b] = [e.touches[0], e.touches[1]];
      pinchRef.current = {
        dist: Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY),
        startZoom: effectiveZoom,
      };
    }
  };

  const handleTouchMove = (e: TouchEvent<HTMLDivElement>) => {
    if (e.touches.length === 2 && pinchRef.current && pinchRef.current.dist > 0) {
      const [a, b] = [e.touches[0], e.touches[1]];
      const dist = Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY);
      const next = Math.min(2.0, Math.max(0.5, Number(((pinchRef.current.startZoom * dist) / pinchRef.current.dist).toFixed(2))));
      setZoom(next);
    }
  };

  const handleTouchEnd = (e: TouchEvent<HTMLDivElement>) => {
    if (e.touches.length < 2) {
      pinchRef.current = null;
    }
  };

  const handleWheel = (e: WheelEvent<HTMLDivElement>) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.1 : -0.1;
      const next = Math.min(2.0, Math.max(0.5, Number((effectiveZoom + delta).toFixed(2))));
      setZoom(next);
    }
  };

  const canTryPrintView = Boolean(
    capabilities?.render?.rasterizer?.state === "yes" || render?.available,
  );

  const handleTogglePrintView = () => {
    const turningOn = !printViewEnabled;
    togglePrintView(turningOn);
    if (turningOn) {
      void renderCurrentPage(page);
      void loadGeometry(page);
    }
  };

  // Multi-op mappings: every cell and paragraph retains ALL queued changes affecting it.
  const changesByCell = useMemo(() => {
    const map = new Map<string, IndexedChange[]>();
    for (const ch of changes) {
      if (ch.op.kind === "fill_cell" || ch.op.kind === "replace_at_cell") {
        const key = cellKey(ch.op.table, ch.op.row, ch.op.col);
        const list = map.get(key) ?? [];
        list.push(ch);
        map.set(key, list);
      }
    }
    return map;
  }, [changes]);

  const changesByPara = useMemo(() => {
    const map = new Map<number, IndexedChange[]>();
    for (const ch of changes) {
      if (ch.op.kind === "set_run") {
        const list = map.get(ch.op.atPara) ?? [];
        list.push(ch);
        map.set(ch.op.atPara, list);
      }
    }
    return map;
  }, [changes]);

  const deleteGuideChanges = useMemo(
    () => changes.filter((ch) => ch.op.kind === "delete_guides"),
    [changes],
  );

  // Table colSpan reconstruction matching TextView.tsx algorithm cleanly.
  const tables = useMemo(
    () =>
      inspect.graph.tables.map((table) => {
        const axis = [...new Set(table.cells.map((c) => c.addr.col))].sort((a, b) => a - b);
        const at = new Map(axis.map((col, i) => [col, i]));

        const grouped = new Map<number, GraphCell[]>();
        for (const cell of table.cells) {
          const list = grouped.get(cell.addr.row) ?? [];
          list.push(cell);
          grouped.set(cell.addr.row, list);
        }

        const rows = [...grouped.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([row, unsorted]) => {
            const cells = unsorted.sort((a, b) => a.addr.col - b.addr.col);
            const spans = cells.map((cell, i) => {
              const start = at.get(cell.addr.col) ?? 0;
              const next = cells[i + 1];
              const end = next ? (at.get(next.addr.col) ?? axis.length) : axis.length;
              return { cell, colSpan: Math.max(1, end - start) };
            });
            const lead = cells.length ? (at.get(cells[0].addr.col) ?? 0) : 0;
            return { row, lead, spans };
          });

        return { index: table.index, columns: axis.length, rows };
      }),
    [inspect],
  );

  // Exclude cell paragraph strings from loose body paragraphs.
  const coveredCellStrings = useMemo(() => {
    const set = new Set<string>();
    for (const region of sourceTexts && sourceTexts !== texts ? [...texts, ...sourceTexts] : texts) {
      if (!region.addr) continue;
      if (region.text) {
        set.add(region.text.trim());
      }
      if (region.runs?.length) {
        for (const run of region.runs) {
          set.add(run.text.trim());
        }
        const groups = groupCellRunsIntoParagraphs(
          region.runs,
          inspect.graph.paragraphs,
        );
        for (const group of groups) {
          set.add(group.map((r) => r.text).join("").trim());
        }
      }
    }
    return set;
  }, [texts, sourceTexts, inspect.graph.paragraphs]);

  const looseParagraphs = useMemo(
    () =>
      inspect.graph.paragraphs.filter(
        (p) => p.text.trim().length > 0 && !coveredCellStrings.has(p.text.trim()),
      ),
    [inspect, coveredCellStrings],
  );

  const selectFromSheet = (opId: string) => {
    skipNextAutoScroll.current = true;
    onSelectChange(opId);
  };

  const handleMarkerClick = (e: MouseEvent, opId: string) => {
    e.stopPropagation();
    selectFromSheet(opId);
  };

  const sheetOuterHeight = Math.round(
    Math.max(naturalHeightPx, naturalHeightMeasure) * effectiveZoom,
  );
  const sheetOuterWidth = Math.floor(naturalWidthPx * effectiveZoom);

  const hasRenderImage = Boolean(
    printViewEnabled &&
      render?.available &&
      render.image?.data &&
      render.image.mediaType,
  );

  const renderFallbackNotice =
    printViewEnabled &&
    renderPhase !== "starting" &&
    (!render?.available || !render?.image?.data);

  const pageCount = render?.pageCount ?? 1;
  const skippedCount =
    render?.elementsSkipped?.reduce((sum, entry) => sum + (entry.count || 0), 0) ?? 0;

  const showOmittedObjectBox = Boolean(
    inspect.summary?.formatHints?.has_eq_placeholder ||
      (render?.elementsSkipped && render.elementsSkipped.length > 0),
  );

  const renderCellContent = (
    cell: GraphCell,
    key: string,
    cellChanges: readonly IndexedChange[],
    region: RegionText | undefined,
  ) => {
    const isEditing = editingCellKey === key && inlineEdit?.kind === "cell";
    if (isEditing && inlineEdit && inlineEdit.kind === "cell") {
      const currentOpText =
        cellChanges.length === 1 ? cellChanges[0].afterText : undefined;
      return (
        <SeatEditor
          key={key}
          value={currentOpText ?? inlineEdit.before}
          multiline={inlineEdit.multiline}
          allowMultiline={isFillMode}
          placeholder={
            isFillMode
              ? (blankFieldLabels?.[key] ?? cellClassLabel("fill_target", language))
              : undefined
          }
          onMultilineChange={(multi) => setInlineEditMultiline(multi)}
          onCycleBlank={
            isFillMode && onCycleBlank
              ? (dir, cur) =>
                  onCycleBlank(inlineEdit.table, inlineEdit.row, inlineEdit.col, dir, cur)
              : undefined
          }
          onEscapeExit={isFillMode ? onEscapeBlank : undefined}
          onCommit={(next, reason) => {
            if (isFillMode && reason === "enter" && onAdvanceBlankAfterEnter) {
              onAdvanceBlankAfterEnter(
                inlineEdit.table,
                inlineEdit.row,
                inlineEdit.col,
                next,
              );
            } else {
              void commitEdit(next);
            }
          }}
          onCancel={cancelEdit}
        />
      );
    }

    const wholeCellChange = [...cellChanges]
      .reverse()
      .find(
        (ch) =>
          ch.op.kind === "fill_cell" ||
          (ch.op.kind === "replace_at_cell" && ch.op.run === undefined),
      );

    const runMap = new Map<number, IndexedChange>();
    for (const ch of cellChanges) {
      if (ch.op.kind === "replace_at_cell" && ch.op.run !== undefined) {
        runMap.set(ch.op.run, ch);
      }
    }

    const isEmptyBlank =
      cellChanges.length === 0 &&
      cell.classification === "fill_target" &&
      !(region?.text ?? cell.textPreview ?? "").trim();

    const paraGroups =
      !wholeCellChange && region?.runs?.length && !isEmptyBlank
        ? groupCellRunsIntoParagraphs(region.runs, inspect.graph.paragraphs)
        : null;

    const visibleParas = paraGroups
      ? paraGroups
          .map((paraRuns, pIdx) => {
            const allCleared = paraRuns.every((run) => {
              const hit = runMap.get(run.index);
              return (hit ? hit.afterText : run.text) === "";
            });
            if (allCleared) return null;
            return (
              <div key={pIdx} className="page-cell-para">
                {paraRuns.map((run) => {
                  const hit = runMap.get(run.index);
                  if (!hit) {
                    return <span key={run.index}>{renderTextWithNowrapTokens(run.text)}</span>;
                  }
                  if (hit.afterText === "") {
                    return null;
                  }
                  const status = rowAudits[hit.opId]?.status ?? "none";
                  const isSelectedRun = hit.opId === selectedChangeId;
                  return (
                    <span
                      key={run.index}
                      className={`page-inline-edit page-inline-edit--${status}${
                        isSelectedRun ? " page-inline-edit--selected" : ""
                      }`}
                      data-selected-anchor={isSelectedRun ? "true" : undefined}
                      onClick={(e) => handleMarkerClick(e, hit.opId)}
                    >
                      {renderTextWithNowrapTokens(hit.afterText)}
                    </span>
                  );
                })}
              </div>
            );
          })
          .filter(Boolean)
      : null;

    const blankHintLabel = isFillMode
      ? (blankFieldLabels?.[key] ?? cellClassLabel("fill_target", language))
      : cellClassLabel("fill_target", language);

    return (
      <div className="page-cell-inner">
        {!isFillMode
          ? renderGroupMarker(
              cellChanges,
              rowAudits,
              selectedChangeId,
              handleMarkerClick,
            )
          : null}

        {wholeCellChange ? (
          <div className="page-cell-text page-cell-text--proposed">
            {renderTextWithNowrapTokens(wholeCellChange.afterText)}
          </div>
        ) : isEmptyBlank ? (
          <EmptyBlankSlot label={blankHintLabel} />
        ) : isFillMode && cell.classification === "fill_target" ? (
          <div className="page-empty-blank page-empty-blank--guided">
            <span className="page-cell-text">
              {renderTextWithNowrapTokens(region?.text ?? cell.textPreview ?? "")}
              {cell.truncated && !region ? "…" : ""}
            </span>
          </div>
        ) : visibleParas ? (
          visibleParas.length > 0 ? (
            <div className="page-cell-text">{visibleParas}</div>
          ) : null
        ) : cellChanges.length > 0 ? (
          <div className="page-cell-text page-cell-text--proposed">
            {renderTextWithNowrapTokens(cellChanges.map((ch) => ch.afterText).join("\n"))}
          </div>
        ) : (
          <div className="page-cell-text">
            {renderTextWithNowrapTokens(region?.text ?? cell.textPreview ?? "")}
            {cell.truncated && !region ? "…" : ""}
          </div>
        )}
      </div>
    );
  };

  const renderLoosePara = (atPara: number, fallbackText: string) => {
    const paraChanges = changesByPara.get(atPara) ?? [];
    const region = textMap[`p:${atPara}`];
    const hasSelected = paraChanges.some((ch) => ch.opId === selectedChangeId);
    const worstStatus = paraChanges.some((ch) => rowAudits[ch.opId]?.status === "changed")
      ? "changed"
      : paraChanges.some((ch) => rowAudits[ch.opId]?.status === "needs_fixes")
        ? "needs-fixes"
        : paraChanges.some((ch) => rowAudits[ch.opId]?.status === "kept")
          ? "kept"
          : paraChanges.length > 0
            ? "accent"
            : "none";

    const runMap = new Map<number, IndexedChange>();
    for (const ch of paraChanges) {
      if (ch.op.kind === "set_run") {
        runMap.set(ch.op.run, ch);
      }
    }

    return (
      <div
        key={`p:${atPara}`}
        className={`page-para${
          paraChanges.length > 0 ? ` page-para--changed page-para--rail-${worstStatus}` : ""
        }${hasSelected ? " page-para--selected" : ""}`}
        data-selected-anchor={hasSelected ? "true" : undefined}
        onClick={() => {
          if (paraChanges.length > 0) {
            selectFromSheet(paraChanges[0].opId);
          }
        }}
      >
        {renderGroupMarker(
          paraChanges,
          rowAudits,
          selectedChangeId,
          handleMarkerClick,
        )}

        <p className="page-para-body">
          {region?.runs?.length ? (
            region.runs.map((run) => {
              const hit = runMap.get(run.index);
              if (!hit) return <span key={run.index}>{run.text}</span>;
              const status = rowAudits[hit.opId]?.status ?? "none";
              const isSelectedRun = hit.opId === selectedChangeId;
              return (
                <span
                  key={run.index}
                  className={`page-inline-edit page-inline-edit--${status}${
                    isSelectedRun ? " page-inline-edit--selected" : ""
                  }`}
                  data-selected-anchor={isSelectedRun ? "true" : undefined}
                  onClick={(e) => handleMarkerClick(e, hit.opId)}
                >
                  {hit.afterText}
                </span>
              );
            })
          ) : paraChanges.length > 0 ? (
            paraChanges.map((ch) => ch.afterText).join(" ")
          ) : (
            region?.text ?? fallbackText
          )}
        </p>
      </div>
    );
  };

  return (
    <section className="page-sheet-pane" aria-label={t("review_mobile_sheet_tab", language)}>
      <div className="page-sheet-subbar">
        <p className="page-sheet-disclaimer" data-testid="page-sheet-disclaimer">
          {subjectLabel ?? t(isFillMode ? "page_label_fill" : "page_label_review", language)}
        </p>

        <div className="page-sheet-controls">
          {originalToggle ? (
            <button
              type="button"
              className={`page-ctrl-btn${originalToggle.showingOriginal ? " page-ctrl-btn--active" : ""}`}
              data-testid="toggle-original"
              aria-pressed={originalToggle.showingOriginal}
              onClick={() => toggleShowOriginal()}
            >
              {originalToggle.showingOriginal
                ? t("page_show_revision", language)
                : t("page_show_original", language)}
            </button>
          ) : null}
          <div
            className="page-sheet-zoom"
            data-testid="page-sheet-zoom"
            role="group"
            aria-label={t("review_zoom_label", language, [Math.round(effectiveZoom * 100)])}
          >
            <button
              type="button"
              className="page-ctrl-btn"
              disabled={effectiveZoom <= 0.5}
              aria-label={t("review_zoom_out", language)}
              onClick={() => setZoom(Math.max(0.5, Number((effectiveZoom - 0.1).toFixed(2))))}
            >
              −
            </button>
            <button
              type="button"
              className={`page-ctrl-btn${pageFit === "width" ? " page-ctrl-btn--active" : ""}`}
              onClick={() => setPageFit("width")}
            >
              {t("review_zoom_fit", language)}
            </button>
            <span className="page-zoom-readout">
              {t("review_zoom_label", language, [Math.round(effectiveZoom * 100)])}
            </span>
            <button
              type="button"
              className="page-ctrl-btn"
              disabled={effectiveZoom >= 2.0}
              aria-label={t("review_zoom_in", language)}
              onClick={() => setZoom(Math.min(2.0, Number((effectiveZoom + 0.1).toFixed(2))))}
            >
              +
            </button>
          </div>

          <button
            type="button"
            className={`page-ctrl-btn page-print-toggle${
              printViewEnabled ? " page-ctrl-btn--active" : ""
            }`}
            data-testid="toggle-print-view"
            disabled={!canTryPrintView && !printViewEnabled}
            title={
              !canTryPrintView && !printViewEnabled
                ? errorCodeMessage("render_unavailable", language)
                : undefined
            }
            onClick={handleTogglePrintView}
          >
            {printViewEnabled
              ? t("review_mode_document", language)
              : t("review_mode_print", language)}
          </button>
        </div>
      </div>

      {printViewEnabled && render?.available ? (
        <div className="page-print-meta" data-testid="print-view-meta">
          <span className="page-grade-badge">
            {renderGradeLabel(render.grade ?? "own-uncertified", language)}
          </span>
          {render.elementsSkipped !== undefined ? (
            <span className="page-skipped-summary">
              {t("page_omitted_object", language)} ({skippedCount})
            </span>
          ) : null}
          {pageCount > 1 ? (
            <div className="page-pager">
              <button
                type="button"
                className="page-ctrl-btn"
                disabled={page <= 1}
                onClick={() => {
                  void renderCurrentPage(page - 1);
                  void loadGeometry(page - 1);
                }}
              >
                {t("review_prev", language)}
              </button>
              <span className="page-zoom-readout">
                {t("review_page_counter", language, [page, pageCount])}
              </span>
              <button
                type="button"
                className="page-ctrl-btn"
                disabled={page >= pageCount}
                onClick={() => {
                  void renderCurrentPage(page + 1);
                  void loadGeometry(page + 1);
                }}
              >
                {t("review_next", language)}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {renderFallbackNotice ? (
        <div className="page-print-fallback" role="status" data-testid="print-view-fallback">
          <span>
            {renderError
              ? errorCodeMessage(renderError.code, language)
              : errorCodeMessage("render_unavailable", language)}
          </span>
        </div>
      ) : null}

      <div
        className="page-sheet-viewport"
        ref={(el) => {
          viewportRef.current = el;
          if (sheetAnchorRef) {
            sheetAnchorRef.current = el;
          }
        }}
        tabIndex={isFillMode ? -1 : undefined}
        data-testid={isFillMode ? "fill-sheet-anchor" : undefined}
        data-zoom-pct={String(Math.round(effectiveZoom * 100))}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onTouchCancel={handleTouchEnd}
        onWheel={handleWheel}
      >
        {hasRenderImage && render?.image ? (
          <div
            className="page-raster-stage"
            style={{
              width: `${Math.round(((render.image.widthPx / (render.dpi ?? 96)) * PX_PER_INCH) * effectiveZoom)}px`,
            }}
          >
            <img
              className="page-raster-img"
              data-testid="page-raster-sheet"
              src={`data:${render.image.mediaType};base64,${render.image.data}`}
              alt={t("review_page_counter", language, [render.page ?? page, pageCount])}
            />
          </div>
        ) : (
          <div
            className="page-sheet-scale-frame"
            style={{
              width: `${sheetOuterWidth}px`,
              minHeight: `${sheetOuterHeight}px`,
            }}
          >
            <article
              ref={sheetRef}
              className="page-sheet"
              data-testid="page-sheet"
              style={{
                width: `${naturalWidthPx}px`,
                minHeight: `${naturalHeightPx}px`,
                padding: `${padTopPx}px ${padRightPx}px ${padBottomPx}px ${padLeftPx}px`,
                transform: `scale(${effectiveZoom})`,
                transformOrigin: "top left",
              }}
            >
              {tables.map((table) => (
                <table
                  key={table.index}
                  className="page-doc-table"
                  data-testid={`page-table-${table.index}`}
                >
                  <tbody>
                    {table.rows.map((row) => (
                      <tr key={row.row}>
                        {row.lead > 0 ? (
                          <td className="page-cell-spacer" colSpan={row.lead} />
                        ) : null}
                        {row.spans.map(({ cell, colSpan }) => {
                          const key = cellKey(table.index, cell.addr.row, cell.addr.col);
                          const region = textMap[key];
                          const cellChanges = changesByCell.get(key) ?? [];
                          const isEditing = editingCellKey === key;
                          const isFillTarget = cell.classification === "fill_target";
                          const isSelected = isFillMode
                            ? selectedCellKey === key || isEditing
                            : cellChanges.some((ch) => ch.opId === selectedChangeId);
                          const isSpacerCell = cell.classification === "spacer";
                          const hasChangedFact = cellChanges.some(
                            (ch) => rowAudits[ch.opId]?.status === "changed",
                          );
                          const hasHardFix = cellChanges.some(
                            (ch) => rowAudits[ch.opId]?.status === "needs_fixes",
                          );
                          const hasKept = cellChanges.some(
                            (ch) => rowAudits[ch.opId]?.status === "kept",
                          );
                          const wholeCellSelected = cellChanges.some(
                            (ch) =>
                              ch.opId === selectedChangeId &&
                              (ch.op.kind === "fill_cell" ||
                                (ch.op.kind === "replace_at_cell" &&
                                  ch.op.run === undefined)),
                          );
                          const hasRunAnchor = cellChanges.some(
                            (ch) =>
                              ch.opId === selectedChangeId &&
                              ch.op.kind === "replace_at_cell" &&
                              ch.op.run !== undefined,
                          );
                          const displaySample = (region?.text ?? cell.textPreview ?? "")
                            .replace(/\s+/g, " ")
                            .trim();
                          const isSingleShortLabel =
                            cellChanges.length === 0 &&
                            displaySample.length > 0 &&
                            displaySample.length <= 8 &&
                            !(region?.text ?? cell.textPreview ?? "").includes("\n");

                          const cls = [
                            "page-cell",
                            `page-cell--class-${cell.classification}`,
                            isFillTarget && !isSpacerCell ? "page-cell--fill-seat" : "",
                            isFillMode && isSpacerCell ? "page-cell--spacer-inert" : "",
                            isFillMode && !isFillTarget && !isSpacerCell ? "page-cell--static-inspectable" : "",
                            isSingleShortLabel ? "page-cell--nowrap-label" : "",
                            colSpan >= 8 ? "page-cell--wide" : "",
                            cellChanges.length > 0 ? "page-cell--changed" : "",
                            hasChangedFact
                              ? "page-cell--rail-changed"
                              : hasHardFix
                                ? "page-cell--rail-needs-fixes"
                                : hasKept
                                  ? "page-cell--rail-kept"
                                  : cellChanges.length > 0
                                    ? "page-cell--rail-accent"
                                    : "",
                            isSelected ? "page-cell--selected" : "",
                            isEditing ? "page-cell--editing" : "",
                          ]
                            .filter(Boolean)
                            .join(" ");

                          return (
                            <td
                              key={key}
                              colSpan={colSpan}
                              className={cls}
                              data-cell-key={key}
                              data-testid={`page-cell-${table.index}-${cell.addr.row}-${cell.addr.col}`}
                              data-cell-op-ids={cellChanges.map((ch) => ch.opId).join(" ")}
                              data-selected-anchor={
                                wholeCellSelected || (isSelected && !hasRunAnchor)
                                  ? "true"
                                  : undefined
                              }
                              onClick={() => {
                                if (isFillMode) {
                                  if (isSpacerCell || isEditing) return;
                                  if (isFillTarget) {
                                    if (onSelectBlankCell) {
                                      onSelectBlankCell(table.index, cell.addr.row, cell.addr.col);
                                    } else {
                                      beginEdit(table.index, cell.addr.row, cell.addr.col);
                                    }
                                    return;
                                  }
                                  if (cellChanges.some((ch) => ch.op.kind === "replace_at_cell")) {
                                    onSelectStaticCell?.(cell, table.index);
                                    beginStaticCellEdit(table.index, cell.addr.row, cell.addr.col);
                                    return;
                                  }
                                  onSelectStaticCell?.(cell, table.index);
                                  return;
                                }
                                if (isFillTarget && !isEditing) {
                                  if (cellChanges.length > 0) {
                                    selectFromSheet(cellChanges[0].opId);
                                  }
                                  beginEdit(table.index, cell.addr.row, cell.addr.col);
                                } else if (cellChanges.length > 0) {
                                  selectFromSheet(cellChanges[0].opId);
                                }
                              }}
                            >
                              {renderCellContent(cell, key, cellChanges, region)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ))}

              {looseParagraphs.map((para) => renderLoosePara(para.at_para, para.text))}

              {!isFillMode && deleteGuideChanges.length > 0 ? (
                <div
                  className="page-delete-guides-box"
                  data-testid="page-delete-guides-banner"
                >
                  {deleteGuideChanges.map((ch) => {
                    const status = rowAudits[ch.opId]?.status ?? "none";
                    const isSelected = selectedChangeId === ch.opId;
                    return (
                      <div
                        key={ch.opId}
                        className={`page-delete-guide-item${
                          isSelected ? " page-delete-guide-item--selected" : ""
                        }`}
                        data-selected-anchor={isSelected ? "true" : undefined}
                        onClick={() => selectFromSheet(ch.opId)}
                      >
                        <button
                          type="button"
                          className={`page-marker-badge page-marker-badge--${status}${
                            isSelected ? " page-marker-badge--selected" : ""
                          }`}
                          data-testid={`page-marker-${ch.ordinal}`}
                          data-marker-ordinals={String(ch.ordinal)}
                          data-marker-op-id={ch.opId}
                          data-marker-op-ids={ch.opId}
                          aria-pressed={isSelected}
                          onClick={(e) => handleMarkerClick(e, ch.opId)}
                        >
                          {ch.ordinal}
                        </button>
                        <span className="page-delete-guide-label">{ch.opKindText}</span>
                        {ch.beforeText.trim() ? (
                          <del className="page-delete-guide-before">{ch.beforeText}</del>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}

              {showOmittedObjectBox ? (
                <div className="page-omitted-object" data-testid="page-omitted-object">
                  <span>{t("page_omitted_object", language)}</span>
                </div>
              ) : null}
            </article>
          </div>
        )}
      </div>
    </section>
  );
}
