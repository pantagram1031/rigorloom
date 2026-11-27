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

import { cancelEdit, setInlineEditMultiline } from "../actions";
import { wp3t } from "../i18n/v2/wp3";
import { rectPt, type EngineGeometry, type EngineTextEdit } from "../model/enginePage";
import {
  formatCellAddress,
  formatSeatLocation,
  legacyCellKey,
  resolvePageFontCategory,
  type CanvasChangeRef,
  type PageFit,
  type PageHitResult,
  type PageRectPt,
  type PageSource,
  type PageViewMode,
} from "../model/page";
import { cellKey, useWorkspace } from "../store";
import { deriveBlankCellLabel } from "../workspace/fieldLabels";
import type {
  GraphCell,
  GraphParagraph,
  InspectResult,
  RegionText,
  UiLanguage,
} from "../types";
import {
  beginCellEditV2,
  commitCellEditV2,
  findTextPattern,
  notifyParagraphNotEditable,
  setCanvasZoom,
  stepCanvasZoom,
  toggleNarrowReadZoom,
} from "./actions";
import { PageCropMarks } from "./PageGuides";
import { ReviewMark } from "./ReviewMark";
import type { MarkToolbarAnchor } from "./MarkToolbar";
import type { ScrollMapTick } from "./ScrollMap";
import { useEngineEditOverlay } from "./EngineEditOverlay";
import { SeatEditor } from "./SeatEditor";

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

const NOWRAP_TOKEN_RE = /(\(\d+(?:-\d+)+\)|\d+(?:-\d+)+)/g;

function renderTextWithNowrapTokens(
  text: string,
  findQuery = "",
  activeHighlight = false,
): ReactNode {
  if (!text) return text;
  const matches = findQuery.trim() ? [...text.matchAll(findTextPattern(findQuery))] : [];
  if (matches.length > 0) {
    const out: ReactNode[] = [];
    let cursor = 0;
    for (const match of matches) {
      const index = match.index ?? cursor;
      const segment = text.slice(cursor, index);
      if (segment) out.push(<span key={`s-${index}`}>{renderTextWithNowrapTokens(segment)}</span>);
      out.push(
        <mark
          key={`f-${index}`}
          className={`rl-find-hit${activeHighlight ? " rl-find-hit--active" : ""}`}
        >
          {match[0]}
        </mark>,
      );
      cursor = index + match[0].length;
    }
    if (cursor < text.length) out.push(<span key="tail">{renderTextWithNowrapTokens(text.slice(cursor))}</span>);
    return out;
  }

  const parts = text.split(NOWRAP_TOKEN_RE);
  if (parts.length === 1) return text;
  return parts.map((part, idx) =>
    idx % 2 === 1 ? (
      <span key={idx} className="rl-nowrap-token">
        {part}
      </span>
    ) : (
      part
    ),
  );
}

const HWPUNIT_PER_INCH = 7200;
const PX_PER_INCH = 96;
const PX_PER_PT = PX_PER_INCH / 72;

function rectStyle(rect: PageRectPt) {
  return {
    left: rect.x * PX_PER_PT, top: rect.y * PX_PER_PT,
    width: rect.w * PX_PER_PT, height: rect.h * PX_PER_PT,
  };
}

function hwpunitToPx(units: number | undefined, fallbackMm: number): number {
  if (typeof units === "number" && Number.isFinite(units) && units > 0) {
    return Math.round((units / HWPUNIT_PER_INCH) * PX_PER_INCH);
  }
  return Math.round((fallbackMm / 25.4) * PX_PER_INCH);
}

function clampMarginPx(units: number | undefined, fallbackMm: number): number {
  const px = hwpunitToPx(units, fallbackMm);
  return Math.max(54, Math.min(96, px));
}

export interface SheetZoomInput {
  isNarrow: boolean;
  narrowReadZoom: boolean;
  pageFit: PageFit;
  boxWidth: number;
  boxHeight: number;
  naturalWidthPx: number;
  naturalHeightPx: number;
  zoom: number;
  hasSelectionOnNarrow?: boolean;
}

export function computeEffectiveSheetZoomV2({
  isNarrow,
  narrowReadZoom,
  pageFit,
  boxWidth,
  boxHeight,
  naturalWidthPx,
  naturalHeightPx,
  zoom,
  hasSelectionOnNarrow = false,
}: SheetZoomInput): number {
  const widthFitZoom =
    boxWidth > 0 && naturalWidthPx > 0
      ? Math.max(0.25, Math.min(1.25, Math.floor((boxWidth / naturalWidthPx) * 1000) / 1000))
      : null;

  if (isNarrow) {
    if (narrowReadZoom || hasSelectionOnNarrow) {
      return 1;
    }
    if (pageFit === "free") {
      return Math.min(1.25, Math.max(0.35, zoom));
    }
    return widthFitZoom !== null ? Math.min(1.0, widthFitZoom) : 1;
  }

  if (pageFit === "width" && widthFitZoom !== null) {
    return widthFitZoom;
  }
  if (pageFit === "page" && boxWidth > 0 && boxHeight > 0 && naturalWidthPx > 0 && naturalHeightPx > 0) {
    const byW = boxWidth / naturalWidthPx;
    const byH = boxHeight / naturalHeightPx;
    return Math.max(0.25, Math.min(1.25, Math.floor(Math.min(byW, byH) * 1000) / 1000));
  }
  return Math.min(2.0, Math.max(0.5, zoom));
}

export type MarkVisualState =
  | "fact"
  | "stale"
  | "test"
  | "pending"
  | "accepted"
  | "rejected";

export function resolveMarkVisualState(ch: CanvasChangeRef): MarkVisualState {
  if (ch.isFactChanged) return "fact";
  if (ch.isStale) return "stale";
  if (ch.source === "test") return "test";
  if (ch.decision === "rejected") return "rejected";
  if (ch.decision === "accepted") return "accepted";
  return "pending";
}

function renderInlineMarkDiff(
  ch: CanvasChangeRef,
  view: PageViewMode,
  isSelected: boolean,
  onClickMark: (e: MouseEvent, item: CanvasChangeRef) => void,
  findQuery: string,
  activeFindMatch = false,
): ReactNode {
  const state = resolveMarkVisualState(ch);
  const sourceAttr = ch.source;

  if (view === "base") {
    return renderTextWithNowrapTokens(ch.before, findQuery, activeFindMatch);
  }

  if (view === "clean") {
    const text = ch.decision === "rejected" ? ch.before : ch.after;
    return text ? renderTextWithNowrapTokens(text, findQuery, activeFindMatch) : null;
  }

  // `marks` view: rejected reverts visually to base text cleanly (margin bar keeps dotted mark)
  if (ch.decision === "rejected") {
    return (
      <span
        className={`rl-mark rl-mark--rejected${isSelected ? " rl-mark--selected" : ""}`}
        data-testid={`page-mark-${ch.id}`}
        data-mark-item={ch.id}
        data-mark-n={String(ch.n)}
        data-mark-state="rejected"
        data-source={sourceAttr}
        data-selected={isSelected ? "true" : undefined}
        data-selected-anchor={isSelected ? "true" : undefined}
        onClick={(e) => onClickMark(e, ch)}
      >
        {renderTextWithNowrapTokens(ch.before, findQuery, activeFindMatch)}
      </span>
    );
  }

  const wrapperProps = {
    className: `rl-mark rl-mark--${state}${isSelected ? " rl-mark--selected" : ""}`,
    "data-testid": `page-mark-${ch.id}`,
    "data-mark-item": ch.id,
    "data-mark-n": String(ch.n),
    "data-mark-state": state,
    "data-source": sourceAttr,
    "data-fact": ch.isFactChanged ? "true" : undefined,
    "data-selected": isSelected ? "true" : undefined,
    "data-selected-anchor": isSelected ? "true" : undefined,
    onClick: (e: MouseEvent) => onClickMark(e, ch),
  };

  const before = ch.before;
  const after = ch.after;
  const lines = after.split(/\r?\n/);

  if (after === "") {
    return (
      <span {...wrapperProps}>
        <del className="rl-del">{renderTextWithNowrapTokens(before, findQuery, activeFindMatch)}</del>
      </span>
    );
  }

  if (before.trim() === "") {
    return (
      <span {...wrapperProps}>
        {lines.length > 1 ? (
          <span className="rl-ins-block">
            {lines.map((line, i) => (
              <span key={i} className="rl-ins-line">
                {line ? (
                  <ins className="rl-ins">
                    {renderTextWithNowrapTokens(line, findQuery, activeFindMatch)}
                  </ins>
                ) : (
                  "\u00A0"
                )}
              </span>
            ))}
          </span>
        ) : (
          <ins className="rl-ins">
            {renderTextWithNowrapTokens(after, findQuery, activeFindMatch)}
          </ins>
        )}
      </span>
    );
  }

  if (after.startsWith(before) && before.length > 0) {
    const suffix = after.slice(before.length);
    return (
      <span {...wrapperProps}>
        <span>{renderTextWithNowrapTokens(before, findQuery, activeFindMatch)}</span>
        <ins className="rl-ins">
          {renderTextWithNowrapTokens(suffix, findQuery, activeFindMatch)}
        </ins>
      </span>
    );
  }

  return (
    <span {...wrapperProps}>
      <del className="rl-del">{renderTextWithNowrapTokens(before, findQuery, activeFindMatch)}</del>{" "}
      <ins className="rl-ins">{renderTextWithNowrapTokens(after, findQuery, activeFindMatch)}</ins>
    </span>
  );
}

export interface PageSheetProps {
  sessionId: string;
  inspect: InspectResult;
  texts: readonly RegionText[];
  textMap: Record<string, RegionText>;
  changes: readonly CanvasChangeRef[];
  selectedChangeId: string | null;
  selectedSeatKey: string | null;
  hoveredSeatKey: string | null;
  view: PageViewMode;
  pageFit: PageFit;
  zoom: number;
  narrowReadZoom: boolean;
  pageSource: PageSource | null;
  page: number;
  engineGeometry: EngineGeometry | null;
  engineEditable: boolean;
  previewSettled: boolean;
  previewRects: NonNullable<EngineGeometry["changed"]>;
  displayedEdits: readonly EngineTextEdit[];
  drying?: boolean;
  findQuery?: string;
  activeFindCellKey?: string | null;
  language: UiLanguage;
  scrollContainerRef: MutableRefObject<HTMLDivElement | null>;
  scrollRequestNonce: number;
  scrollRequestOrigin: "canvas" | "external";
  onSelectChange: (itemId: string, options?: { fromCanvas?: boolean }) => void;
  onSelectSeat: (key: string | null, seatLabel: string | null) => void;
  onMeasurementsChange: (data: {
    toolbarAnchor: MarkToolbarAnchor | null;
    scrollTicks: ScrollMapTick[];
    effectiveZoom: number;
    sheetWidth: number;
    sheetHeight: number;
    margins: { top: number; right: number; bottom: number; left: number };
  }) => void;
}

export function PageSheet({
  sessionId,
  inspect,
  texts,
  textMap,
  changes,
  selectedChangeId,
  selectedSeatKey,
  hoveredSeatKey,
  view,
  pageFit,
  zoom,
  narrowReadZoom,
  pageSource,
  page,
  engineGeometry,
  engineEditable,
  previewSettled,
  previewRects,
  displayedEdits,
  drying = false,
  findQuery = "",
  activeFindCellKey = null,
  language,
  scrollContainerRef,
  scrollRequestNonce,
  scrollRequestOrigin,
  onSelectChange,
  onSelectSeat,
  onMeasurementsChange,
}: PageSheetProps) {
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const sheetRef = useRef<HTMLElement | null>(null);
  const pinchRef = useRef<{ dist: number; startZoom: number } | null>(null);
  const lastTapRef = useRef<number>(0);

  const [boxSize, setBoxSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const [naturalHeightMeasure, setNaturalHeightMeasure] = useState(0);
  const [caret, setCaret] = useState<{ page: number; rasterUrl?: string; address: string; offset: number } | null>(null);
  const [engineHit, setEngineHit] = useState<PageHitResult | null>(null);
  const hasEngineGeometry = Boolean(engineGeometry);

  const layer = pageSource?.layer(page, view);
  const rasterUrl = layer?.rasterUrl;
  const drawnWidth = rasterUrl ? layer.sizePt.widthPt * PX_PER_PT : null;
  const drawnHeight = rasterUrl ? layer.sizePt.heightPt * PX_PER_PT : null;
  const positioned = useMemo(() => {
    const rects = new Map<string, PageRectPt>();
    if (hasEngineGeometry && pageSource) {
      for (const box of pageSource.boxes(page)) {
        if (box.address && (box.kind === "cell" || box.kind === "para") && !box.address.includes("#")) {
          if (!rects.has(box.address)) rects.set(box.address, box.rect);
        }
      }
    }
    return rects;
  }, [hasEngineGeometry, pageSource, page]);
  const caretRect = hasEngineGeometry && caret && caret.page === page && caret.rasterUrl === rasterUrl
    ? pageSource?.caretRect(page, caret.address, caret.offset) : null;

  const editingCellKey =
    inlineEdit && inlineEdit.kind === "cell"
      ? cellKey(inlineEdit.table, inlineEdit.row, inlineEdit.col)
      : null;

  const [isNarrow, setIsNarrow] = useState<boolean>(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(max-width: 599px)").matches
      : false,
  );

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(max-width: 599px)");
    const sync = () => setIsNarrow(mq.matches);
    sync();
    mq.addEventListener?.("change", sync);
    return () => mq.removeEventListener?.("change", sync);
  }, []);

  const metrics = inspect.summary?.pageMetrics;
  const naturalWidthPx = drawnWidth ?? hwpunitToPx(metrics?.width, 210);
  const naturalHeightPx = drawnHeight ?? hwpunitToPx(metrics?.height, 297);
  const padTopPx = useMemo(
    () => clampMarginPx(metrics?.margin?.top, 16),
    [metrics?.margin?.top],
  );
  const padRightPx = useMemo(
    () => clampMarginPx(metrics?.margin?.right, 16),
    [metrics?.margin?.right],
  );
  const padBottomPx = useMemo(
    () => clampMarginPx(metrics?.margin?.bottom, 14),
    [metrics?.margin?.bottom],
  );
  const padLeftPx = useMemo(
    () => clampMarginPx(metrics?.margin?.left, 18),
    [metrics?.margin?.left],
  );

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const update = () => {
      const cs = getComputedStyle(el);
      const padH = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
      const padV = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
      setBoxSize({
        w: Math.max(0, el.clientWidth - padH),
        h: Math.max(0, el.clientHeight - padV),
      });
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [scrollContainerRef]);

  const effectiveZoom = useMemo(
    () =>
      computeEffectiveSheetZoomV2({
        isNarrow,
        narrowReadZoom,
        pageFit,
        boxWidth: boxSize.w,
        boxHeight: boxSize.h,
        naturalWidthPx,
        naturalHeightPx,
        zoom,
        hasSelectionOnNarrow: isNarrow && selectedChangeId !== null && narrowReadZoom,
      }),
    [
      isNarrow,
      narrowReadZoom,
      pageFit,
      boxSize.w,
      boxSize.h,
      naturalWidthPx,
      naturalHeightPx,
      zoom,
      selectedChangeId,
    ],
  );

  // Measure mark positions, toolbar anchor, and scrollmap ticks after layout
  useLayoutEffect(() => {
    const sheet = sheetRef.current;
    const margins = {
      top: padTopPx,
      right: padRightPx,
      bottom: padBottomPx,
      left: padLeftPx,
    };
    const outerWidth = Math.floor(naturalWidthPx * effectiveZoom);
    if (!sheet) {
      onMeasurementsChange({
        toolbarAnchor: null,
        scrollTicks: [],
        effectiveZoom,
        sheetWidth: outerWidth,
        sheetHeight: Math.round(naturalHeightPx * effectiveZoom),
        margins,
      });
      return;
    }

    const measure = () => {
      const totalH = rasterUrl ? naturalHeightPx : Math.max(naturalHeightPx, sheet.scrollHeight);
      setNaturalHeightMeasure(totalH);

      const sheetRect = sheet.getBoundingClientRect();
      const scale = effectiveZoom || 1;
      const positions = new Map<string, number>();
      const markEls = sheet.querySelectorAll<HTMLElement>("[data-mark-item]");

      let toolbarAnchor: MarkToolbarAnchor | null = null;
      const ticks: ScrollMapTick[] = [];

      for (const el of markEls) {
        const itemId = el.getAttribute("data-mark-item");
        if (!itemId) continue;
        const block = el.closest<HTMLElement>("[data-cell-key], td, p") ?? el;
        const r = rasterUrl ? block.getBoundingClientRect() : el.getBoundingClientRect();
        const centerPx = (r.top - sheetRect.top + Math.max(16 * scale, r.height) / 2) / scale;
        positions.set(itemId, centerPx);

        if (itemId === selectedChangeId) {
          // The toolbar floats outside the block's top-right corner (J1 §1
          // Borrow): anchored to the cell or paragraph that holds the mark,
          // never to the changed text itself, so it does not cover it.
          const br = block.getBoundingClientRect();
          const markRightInStage = br.right - sheetRect.left;
          const stageVisibleW = sheetRect.width;
          const estimatedToolbarW = 140;
          const minLeftPx = Math.max(8, Math.round(padLeftPx * scale));
          const maxLeftPx = Math.max(minLeftPx, stageVisibleW - estimatedToolbarW - 8);
          const leftPx = Math.min(maxLeftPx, Math.max(minLeftPx, markRightInStage - estimatedToolbarW));
          const toolbarHeight = 22;
          let topPx = br.top - sheetRect.top - toolbarHeight - 4;
          const pointsToScreen = PX_PER_PT * scale;
          // Move the toolbar above any printed lines it would cover.
          const lines = (engineGeometry?.boxes ?? []).filter((box) => {
            const text = box.text?.trim();
            // The engine emits the enclosing table as a single control
            // glyph whose geometry spans the entire table.
            return box.kind === "line" && text && text !== "▣" && box.xs?.length;
          });
          lines.sort((a, b) => b.rect[1] - a.rect[1]);
          for (const line of lines) {
            const [x, y, , h] = line.rect;
            const glyphs = line.xs ?? [];
            const inkLeft = (glyphs[0] ?? x) * pointsToScreen;
            const inkRight = (glyphs[glyphs.length - 1] ?? x) * pointsToScreen;
            const inkTop = y * pointsToScreen;
            const inkBottom = (y + h) * pointsToScreen;
            if (inkLeft < leftPx + estimatedToolbarW && inkRight > leftPx &&
                inkTop < topPx + toolbarHeight && inkBottom > topPx) {
              topPx = inkTop - toolbarHeight - 18;
            }
          }
          toolbarAnchor = { topPx: Math.max(4, topPx), leftPx };
        }
      }

      for (const ch of changes) {
        const top = positions.get(ch.id);
        if (top === undefined) continue;
        ticks.push({
          item: ch,
          topPct: (top / totalH) * 100,
        });
      }

      onMeasurementsChange({
        toolbarAnchor,
        scrollTicks: ticks,
        effectiveZoom,
        sheetWidth: outerWidth,
        sheetHeight: Math.round(totalH * effectiveZoom),
        margins,
      });
    };

    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(sheet);
    return () => ro.disconnect();
  }, [
    changes,
    selectedChangeId,
    view,
    effectiveZoom,
    naturalWidthPx,
    naturalHeightPx,
    padTopPx,
    padRightPx,
    padBottomPx,
    padLeftPx,
    inspect,
    texts,
    rasterUrl,
    engineGeometry,
    positioned,
    onMeasurementsChange,
  ]);

  // 180 ms smooth scroll putting the selected mark at one-third viewport height (`D1 §3(c) 6`)
  useEffect(() => {
    if (!selectedChangeId) return;
    if (scrollRequestOrigin === "canvas") return;
    const container = scrollContainerRef.current;
    if (!container || container.clientHeight === 0) return;

    const esc = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(selectedChangeId) : selectedChangeId;
    const targetEl =
      container.querySelector<HTMLElement>(`[data-mark-item="${esc}"]`) ??
      container.querySelector<HTMLElement>('[data-selected-anchor="true"]');
    if (!targetEl) return;

    const cRect = container.getBoundingClientRect();
    const tRect = targetEl.getBoundingClientRect();
    const targetTop =
      container.scrollTop + (tRect.top - cRect.top) - container.clientHeight / 3;
    const reduced =
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    container.scrollTo({
      top: Math.max(0, targetTop),
      left: isNarrow ? Math.max(0, container.scrollLeft + (tRect.left - cRect.left) - 24) : container.scrollLeft,
      behavior: reduced ? "auto" : "smooth",
    });
  }, [selectedChangeId, scrollRequestNonce, scrollRequestOrigin, scrollContainerRef, isNarrow]);

  const changesByCell = useMemo(() => {
    const map = new Map<string, CanvasChangeRef[]>();
    for (const ch of changes) {
      if (ch.cellKey) {
        const list = map.get(ch.cellKey) ?? [];
        list.push(ch);
        map.set(ch.cellKey, list);
      }
    }
    return map;
  }, [changes]);

  const changesByPara = useMemo(() => {
    const map = new Map<number, CanvasChangeRef[]>();
    for (const ch of changes) {
      if (ch.atPara !== undefined) {
        const list = map.get(ch.atPara) ?? [];
        list.push(ch);
        map.set(ch.atPara, list);
      }
    }
    return map;
  }, [changes]);

  const guideChanges = useMemo(
    () => changes.filter((ch) => ch.opKind === "delete_guides"),
    [changes],
  );

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

  const coveredCellStrings = useMemo(() => {
    const set = new Set<string>();
    for (const region of texts) {
      if (!region.addr) continue;
      if (region.text) set.add(region.text.trim());
      if (region.runs?.length) {
        for (const run of region.runs) set.add(run.text.trim());
        const groups = groupCellRunsIntoParagraphs(region.runs, inspect.graph.paragraphs);
        for (const g of groups) set.add(g.map((r) => r.text).join("").trim());
      }
    }
    return set;
  }, [texts, inspect.graph.paragraphs]);

  const looseParagraphs = useMemo(
    () =>
      inspect.graph.paragraphs.filter(
        (p) => p.text.trim().length > 0 && !coveredCellStrings.has(p.text.trim()),
      ),
    [inspect, coveredCellStrings],
  );

  // Ordered fillable seats for Tab / Shift+Tab cycling
  const orderedEditableSeats = useMemo(() => {
    const seats: Array<{ table: number; row: number; col: number }> = [];
    for (const tbl of inspect.graph.tables) {
      const sorted = [...tbl.cells]
        .filter((c) => c.classification !== "spacer")
        .sort((a, b) => a.addr.row - b.addr.row || a.addr.col - b.addr.col);
      for (const c of sorted) {
        seats.push({ table: tbl.index, row: c.addr.row, col: c.addr.col });
      }
    }
    return seats;
  }, [inspect.graph.tables]);

  const baselineFace = inspect.summary?.baselineCharPr?.face?.hangul ?? null;
  const baselineFontCategory = resolvePageFontCategory(baselineFace);
  const paperFontFamily = baselineFace
    ? `"${baselineFace.replace(/"/g, "")}", ${
        baselineFontCategory === "sans" ? "var(--font-page-sans)" : "var(--font-page-serif)"
      }`
    : baselineFontCategory === "sans"
      ? "var(--font-page-sans)"
      : "var(--font-page-serif)";

  const regionFaceByCell = useMemo(() => {
    const map = new Map<string, { category: "serif" | "sans"; face: string | null }>();
    for (const reg of inspect.regions.regions) {
      if (reg.table !== undefined && reg.row !== undefined && reg.col !== undefined) {
        const face = reg.charPrFace?.hangul ?? baselineFace;
        map.set(legacyCellKey(reg.table, reg.row, reg.col), {
          category: resolvePageFontCategory(face),
          face,
        });
      }
    }
    return map;
  }, [inspect.regions.regions, baselineFace]);

  const handleMarkClick = (e: MouseEvent, item: CanvasChangeRef) => {
    e.stopPropagation();
    if (selectedChangeId === item.id && item.cellKey && item.opKind !== "delete_guides") {
      // Second click on already-selected cell mark opens inline editor
      const match = /^c:(\d+):(\d+):(\d+)$/.exec(item.cellKey);
      if (match) {
        beginCellEditV2(Number(match[1]), Number(match[2]), Number(match[3]), {
          inspect,
          texts: [...texts],
        });
        return;
      }
    }
    onSelectChange(item.id, { fromCanvas: true });
  };

  const cycleCell = (
    table: number,
    row: number,
    col: number,
    dir: 1 | -1,
  ) => {
    if (orderedEditableSeats.length === 0) return;
    const idx = orderedEditableSeats.findIndex(
      (s) => s.table === table && s.row === row && s.col === col,
    );
    const nextIdx =
      idx >= 0
        ? (idx + dir + orderedEditableSeats.length) % orderedEditableSeats.length
        : 0;
    const next = orderedEditableSeats[nextIdx];
    beginCellEditV2(next.table, next.row, next.col, {
      inspect,
      texts: [...texts],
    });
  };

  const engineOverlay = useEngineEditOverlay({
    sessionId, geometry: engineGeometry, editable: engineEditable, isNarrow, settled: previewSettled,
    displayedEdits, inspect, hit: engineHit?.page === page ? engineHit : null, onCycleCell: cycleCell,
  });

  const handleTouchStart = (e: TouchEvent<HTMLDivElement>) => {
    if (e.touches.length === 2) {
      const [a, b] = [e.touches[0], e.touches[1]];
      pinchRef.current = {
        dist: Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY),
        startZoom: effectiveZoom,
      };
    } else if (e.touches.length === 1 && isNarrow) {
      const now = Date.now();
      if (now - lastTapRef.current < 280) {
        toggleNarrowReadZoom();
      }
      lastTapRef.current = now;
    }
  };

  const handleTouchMove = (e: TouchEvent<HTMLDivElement>) => {
    if (e.touches.length === 2 && pinchRef.current && pinchRef.current.dist > 0) {
      const [a, b] = [e.touches[0], e.touches[1]];
      const dist = Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY);
      const next = Math.min(2.0, Math.max(0.5, (pinchRef.current.startZoom * dist) / pinchRef.current.dist));
      setCanvasZoom(next);
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
      stepCanvasZoom(e.deltaY < 0 ? 0.1 : -0.1);
    }
  };

  const sheetOuterWidth = Math.floor(naturalWidthPx * effectiveZoom);
  const sheetOuterHeight = Math.round(
    (rasterUrl ? naturalHeightPx : Math.max(naturalHeightPx, naturalHeightMeasure)) * effectiveZoom,
  );

  const renderCellContent = (
    cell: GraphCell,
    key: string,
    cellChanges: readonly CanvasChangeRef[],
    region: RegionText | undefined,
  ) => {
    const isEditing = editingCellKey === key && inlineEdit?.kind === "cell";
    const fontInfo = regionFaceByCell.get(key) ?? {
      category: baselineFontCategory,
      face: baselineFace,
    };

    if (isEditing && inlineEdit && inlineEdit.kind === "cell" && !isNarrow && !engineOverlay.activeCell) {
      const activeChange =
        cellChanges.length === 1 && cellChanges[0].decision !== "rejected"
          ? cellChanges[0]
          : null;
      const editVal =
        inlineEdit.readOnly && inlineEdit.readOnlyMessage
          ? inlineEdit.readOnlyMessage
          : activeChange
            ? activeChange.after
            : inlineEdit.before;
      return (
        <SeatEditor
          key={`${sessionId}-${key}`}
          value={editVal}
          caret={editVal.trim().length > 0 ? "end" : "select"}
          multiline={inlineEdit.multiline}
          allowMultiline={!inlineEdit.readOnly}
          readOnly={Boolean(inlineEdit.readOnly)}
          readOnlyMessage={inlineEdit.readOnlyMessage}
          fontCategory={fontInfo.category}
          fontFace={fontInfo.face}
          onMultilineChange={(multi) => setInlineEditMultiline(multi)}
          onCycleBlank={(dir, cur) => {
            if (!inlineEdit.readOnly) {
              void commitCellEditV2(cur, { inspect });
            }
            cycleCell(inlineEdit.table, inlineEdit.row, inlineEdit.col, dir);
          }}
          onCommit={(next) => {
            void commitCellEditV2(next, { inspect });
          }}
          onCancel={cancelEdit}
        />
      );
    }

    const wholeCellChange = [...cellChanges]
      .reverse()
      .find(
        (ch) =>
          ch.opKind === "fill_cell" ||
          (ch.opKind === "replace_at_cell" && ch.run === undefined),
      );

    const runMap = new Map<number, CanvasChangeRef>();
    for (const ch of cellChanges) {
      if (ch.opKind === "replace_at_cell" && ch.run !== undefined) {
        runMap.set(ch.run, ch);
      }
    }

    const baseText = region?.text ?? cell.textPreview ?? "";
    const isEmptyBlank =
      cellChanges.length === 0 &&
      cell.classification === "fill_target" &&
      baseText.trim() === "";

    if (wholeCellChange) {
      return (
        <div className="rl-cell-inner">
          <div className="rl-cell-text">
            {renderInlineMarkDiff(
              wholeCellChange,
              view,
              wholeCellChange.id === selectedChangeId,
              handleMarkClick,
              findQuery,
              activeFindCellKey === key,
            )}
          </div>
        </div>
      );
    }

    if (isEmptyBlank) {
      return <div className="rl-blank-seat-fill" aria-hidden="true" />;
    }

    const paraGroups = region?.runs?.length
      ? groupCellRunsIntoParagraphs(region.runs, inspect.graph.paragraphs)
      : null;

    if (paraGroups) {
      const renderedParas = paraGroups
        .map((paraRuns, pIdx) => {
          const isAllEmptyInClean =
            view === "clean" &&
            paraRuns.every((run) => {
              const hit = runMap.get(run.index);
              if (!hit || hit.decision === "rejected") return run.text === "";
              return hit.after === "";
            });
          if (isAllEmptyInClean) return null;

          return (
            <div key={pIdx} className="rl-cell-para">
              {paraRuns.map((run) => {
                const hit = runMap.get(run.index);
                if (!hit) {
                  return (
                    <span key={run.index}>
                      {renderTextWithNowrapTokens(
                        run.text,
                        findQuery,
                        activeFindCellKey === key,
                      )}
                    </span>
                  );
                }
                return (
                  <span key={run.index}>
                    {renderInlineMarkDiff(
                      hit,
                      view,
                      hit.id === selectedChangeId,
                      handleMarkClick,
                      findQuery,
                      activeFindCellKey === key,
                    )}
                  </span>
                );
              })}
            </div>
          );
        })
        .filter(Boolean);

      return (
        <div className="rl-cell-inner">
          <div className="rl-cell-text">{renderedParas}</div>
        </div>
      );
    }

    return (
      <div className="rl-cell-inner">
        <div className="rl-cell-text">
          {renderTextWithNowrapTokens(
            baseText,
            findQuery,
            activeFindCellKey === key,
          )}
        </div>
      </div>
    );
  };

  return (
    <div
      className="rl-paper-scale-frame"
      style={{
        width: `${sheetOuterWidth}px`,
        minHeight: `${sheetOuterHeight}px`,
      }}
    >
      <article
        ref={sheetRef}
        className={`rl-paper${drying ? " rl-paper--drying" : ""}`}
        data-testid="paper"
        data-paper="true"
        data-raster={rasterUrl ? "true" : undefined}
        data-engine-geometry={hasEngineGeometry ? "true" : undefined}
        aria-label={wp3t("paper_aria_label", language)}
        onMouseLeave={() => onSelectSeat(null, null)}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onTouchCancel={handleTouchEnd}
        onWheel={handleWheel}
        onClick={(event) => {
          if (!engineEditable || !engineHit?.lineAddress ||
              (event.target as HTMLElement).closest("td, .rl-mark, input, textarea, button")) return;
          void engineOverlay.beginParagraph(engineHit).then((started) => {
            if (started === false) notifyParagraphNotEditable(language);
          });
        }}
        onPointerDownCapture={(event) => {
          if (!pageSource || !hasEngineGeometry || event.button !== 0 ||
              (event.target as HTMLElement).closest("input, textarea, button")) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          const scale = effectiveZoom * PX_PER_PT;
          const hit = pageSource.hitTest(page, (event.clientX - bounds.left) / scale,
                                        (event.clientY - bounds.top) / scale);
          setEngineHit(hit);
          setCaret(hit.lineAddress && hit.lineOffset != null
            ? { page, rasterUrl, address: hit.lineAddress, offset: hit.lineOffset }
            : null);
        }}
        style={{
          width: `${naturalWidthPx}px`,
          minHeight: `${naturalHeightPx}px`,
          height: rasterUrl ? `${naturalHeightPx}px` : undefined,
          padding: hasEngineGeometry ? 0 : `${padTopPx}px ${padRightPx}px ${padBottomPx}px ${padLeftPx}px`,
          fontFamily: paperFontFamily,
          transform: `scale(${effectiveZoom})`,
          transformOrigin: "top left",
        }}
      >
        {rasterUrl ? <img className="rl-paper-raster" data-testid="page-raster" src={rasterUrl} alt="" draggable={false} /> : null}
        {caretRect ? <span className="rl-raster-caret" style={rectStyle(caretRect)} aria-hidden="true" /> : null}
        {previewRects.flatMap(({ i, page: changedPage, rect }, index) => changedPage === page && rect
          ? [<span key={`${i}-${index}`} className="rl-engine-changed-rect" data-testid="engine-changed-rect"
              style={rectStyle(rectPt(rect))} aria-hidden="true" />]
          : [])}
        {engineOverlay.pending}
        {engineOverlay.editor}
        {tables.map((table) => (
          <table
            key={table.index}
            className="rl-doc-table"
            data-testid={`page-table-${table.index}`}
          >
            <tbody>
              {table.rows.map((row) => (
                <tr key={row.row}>
                  {row.lead > 0 ? (
                    <td className="rl-cell-spacer" colSpan={row.lead} />
                  ) : null}
                  {row.spans.map(({ cell, colSpan }) => {
                    const key = legacyCellKey(table.index, cell.addr.row, cell.addr.col);
                    const region = textMap[key];
                    const cellChanges = changesByCell.get(key) ?? [];
                    const address = formatCellAddress(table.index, cell.addr.row, cell.addr.col);
                    const rect = positioned.get(address);
                    if (hasEngineGeometry && !rect) return null;
                    const isEditing = editingCellKey === key;
                    const isSpacerCell = cell.classification === "spacer";
                    const baseText = region?.text ?? cell.textPreview ?? "";
                    const isEmptyBlank =
                      cellChanges.length === 0 &&
                      cell.classification === "fill_target" &&
                      baseText.trim() === "";
                    const isHovered = hoveredSeatKey === key;
                    const isSelectedSeat = selectedSeatKey === key;
                    const hasSelectedMark = cellChanges.some(
                      (ch) => ch.id === selectedChangeId,
                    );
                    const reviewChange = view === "marks" && !isEditing
                      ? cellChanges.find((change) => change.id === selectedChangeId) ?? cellChanges[0]
                      : undefined;
                    const fontInfo = regionFaceByCell.get(key);
                    const cellFontFamily = fontInfo
                      ? `${fontInfo.face ? `"${fontInfo.face.replace(/"/g, "")}", ` : ""}${
                          fontInfo.category === "sans"
                            ? "var(--font-page-sans)"
                            : "var(--font-page-serif)"
                        }`
                      : undefined;

                    const displaySample = baseText.replace(/\s+/g, " ").trim();
                    const isSingleShortLabel =
                      cellChanges.length === 0 &&
                      displaySample.length > 0 &&
                      displaySample.length <= 5 &&
                      !baseText.includes("\n");

                    const cls = [
                      "rl-cell",
                      `rl-cell--${cell.classification}`,
                      !isSpacerCell ? "rl-cell--typable" : "",
                      isEmptyBlank ? "rl-cell--blank" : "",
                      isHovered ? "rl-cell--hovered" : "",
                      isSelectedSeat ? "rl-cell--seat-selected" : "",
                      hasSelectedMark ? "rl-cell--mark-selected" : "",
                      isEditing ? "rl-cell--editing" : "",
                      isSingleShortLabel ? "rl-cell--nowrap" : "",
                    ]
                      .filter(Boolean)
                      .join(" ");

                    return (
                      <td
                        key={key}
                        colSpan={colSpan}
                        className={cls}
                        style={{ fontFamily: cellFontFamily, ...(rect ? rectStyle(rect) : undefined) }}
                        data-cell-key={key}
                        data-address={address}
                        data-testid={`page-cell-${table.index}-${cell.addr.row}-${cell.addr.col}`}
                        onMouseEnter={() => {
                          if (!isSpacerCell) {
                            const label = deriveBlankCellLabel(
                              inspect,
                              textMap,
                              table.index,
                              cell.addr.row,
                              cell.addr.col,
                              language,
                            );
                            const location = formatSeatLocation(
                              hasEngineGeometry ? page : null,
                              table.index,
                              cell.addr.row,
                              cell.addr.col,
                              language,
                            );
                            onSelectSeat(
                              key,
                              label ? `${label} · ${location}` : location,
                            );
                          }
                        }}
                        onClick={() => {
                          if (isSpacerCell || isEditing) return;
                          if (cellChanges.length > 0 && cellChanges.every((c) => c.id !== selectedChangeId)) {
                            onSelectChange(cellChanges[0].id, { fromCanvas: true });
                            return;
                          }
                          beginCellEditV2(table.index, cell.addr.row, cell.addr.col, {
                            inspect,
                            texts: [...texts],
                          });
                        }}
                      >
                        {renderCellContent(cell, key, cellChanges, region)}
                        {reviewChange ? <ReviewMark change={reviewChange} zoom={effectiveZoom} selected={hasSelectedMark} /> : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        ))}

        {looseParagraphs.map((para) => {
          const rect = positioned.get(`p${para.at_para}`);
          if (hasEngineGeometry && !rect) return null;
          const paraChanges = changesByPara.get(para.at_para) ?? [];
          const reviewChange = rasterUrl && view === "marks"
            ? paraChanges.find((change) => change.id === selectedChangeId) ?? paraChanges[0]
            : undefined;
          const region = textMap[`p:${para.at_para}`];
          const runMap = new Map<number, CanvasChangeRef>();
          for (const ch of paraChanges) {
            if (ch.run !== undefined) runMap.set(ch.run, ch);
          }

          return (
            <div
              key={`p:${para.at_para}`}
              className="rl-para"
              style={rect ? rectStyle(rect) : undefined}
              data-para-key={`p:${para.at_para}`}
              data-testid={`page-para-${para.at_para}`}
              onClick={(event) => {
                if (paraChanges.length > 0) {
                  onSelectChange(paraChanges[0].id, { fromCanvas: true });
                  if (!engineEditable || paraChanges.every((change) => change.id !== selectedChangeId)) {
                    event.stopPropagation();
                    return;
                  }
                } else if (!engineEditable || !engineHit?.lineAddress) {
                  notifyParagraphNotEditable(language);
                }
              }}
            >
              <p className="rl-para-body">
                {region?.runs?.length ? (
                  region.runs.map((run) => {
                    const hit = runMap.get(run.index);
                    if (!hit) {
                      return (
                        <span key={run.index}>
                          {renderTextWithNowrapTokens(
                            run.text,
                            findQuery,
                            activeFindCellKey === `p:${para.at_para}`,
                          )}
                        </span>
                      );
                    }
                    return (
                      <span key={run.index}>
                        {renderInlineMarkDiff(
                          hit,
                          view,
                          hit.id === selectedChangeId,
                          handleMarkClick,
                          findQuery,
                          activeFindCellKey === `p:${para.at_para}`,
                        )}
                      </span>
                    );
                  })
                ) : (
                  renderTextWithNowrapTokens(
                    region?.text ?? para.text,
                    findQuery,
                    activeFindCellKey === `p:${para.at_para}`,
                  )
                )}
              </p>
              {reviewChange ? <ReviewMark change={reviewChange} zoom={effectiveZoom}
                selected={reviewChange.id === selectedChangeId} /> : null}
            </div>
          );
        })}

        {view === "marks" && guideChanges.length > 0 ? (
          <div className="rl-guide-delete-strip" data-testid="page-delete-guides-strip">
            {guideChanges.map((ch) => (
              <div key={ch.id} className="rl-guide-delete-item">
                {renderInlineMarkDiff(
                  ch,
                  view,
                  ch.id === selectedChangeId,
                  handleMarkClick,
                  findQuery,
                )}
              </div>
            ))}
          </div>
        ) : null}

        <div className="rl-paper-veil" aria-hidden="true" />
      </article>
      <PageCropMarks width={sheetOuterWidth} height={sheetOuterHeight} zoom={effectiveZoom}
        margins={{ top: padTopPx, right: padRightPx, bottom: padBottomPx, left: padLeftPx }} />
    </div>
  );
}
