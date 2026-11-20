import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { cancelEdit } from "../actions";
import { wp3t } from "../i18n/v2/wp3";
import {
  createProjectionPageSource,
  detectDocumentSeats,
  formatSeatLocation,
  type CanvasChangeRef,
  type PageSource,
} from "../model/page";
import {
  activeInspect,
  activeSession,
  activeText,
  cellKey,
  headCandidate,
  useWorkspace,
} from "../store";
import { buildRegionTextMap } from "../workspace/externalPlan";
import { deriveCellFieldLabel } from "../workspace/fieldLabels";
import {
  buildIndexedChanges,
  useReviewGuardSummary,
} from "../workspace/guardHelper";
import { indexedChangesToCanvasRefs } from "./_shim";
import {
  commitCellEditV2,
  decideCanvasItem,
  fitCanvasWidth,
  stepCanvasChange,
  stepCanvasZoom,
} from "./actions";
import {
  canvas,
  getScrollRequestState,
  publishCanvasContext,
  setCanvasSlice,
  useCanvasSlice,
} from "./controller";
import { DocumentStrip } from "./DocumentStrip";
import { MarginMarks, type MeasuredMarkPos } from "./MarginMarks";
import { MarkToolbar, type MarkToolbarAnchor } from "./MarkToolbar";
import { PageSheet } from "./PageSheet";
import { ScrollMap, type ScrollMapTick } from "./ScrollMap";
import { SeatEditor } from "./SeatEditor";
import "./canvas.css";

export interface CanvasPaneProps {
  /** Optional external changes (e.g. from WP4 `ChangeItem[]` or harness). */
  changesOverride?: readonly CanvasChangeRef[];
  /** Optional base document label (`원본` or `수정본 1`). */
  baseNameOverride?: string;
  /** Optional stale flag override. */
  isStaleOverride?: boolean;
  /** Optional read-only flag (history revision viewing). */
  readOnly?: boolean;
  /** Optional callback when a user decides an item (`Y`/`N`/`U`). */
  onDecideItem?: (itemId: string, decision: "pending" | "accepted" | "rejected") => void;
  /** Optional callback when user wants to jump to edit via MarkToolbar `E`. */
  onEditItem?: (item: CanvasChangeRef) => void;
  /** Optional slot renderers for stripStart / stripEnd. */
  stripStart?: ReactNode;
  stripEnd?: ReactNode;
  /** Optional callback exposing active PageSource. */
  onPageSourceReady?: (source: PageSource | null) => void;
}

export function CanvasPane({
  changesOverride,
  baseNameOverride,
  isStaleOverride,
  readOnly = false,
  onDecideItem,
  onEditItem,
  stripStart,
  stripEnd,
  onPageSourceReady,
}: CanvasPaneProps) {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeText);
  const draft = useWorkspace((s) => s.draft);
  const render = useWorkspace((s) => s.render);
  const geometry = useWorkspace((s) => s.geometry);
  const head = useWorkspace(headCandidate);
  const candidatesBySession = useWorkspace((s) => s.candidates);
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const language = useWorkspace((s) => s.language);
  const guardSummary = useReviewGuardSummary();

  const slice = useCanvasSlice(session?.sessionId);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const [measured, setMeasured] = useState<{
    positions: Map<string, MeasuredMarkPos>;
    toolbarAnchor: MarkToolbarAnchor | null;
    scrollTicks: ScrollMapTick[];
    gutterWidthPx: number;
    effectiveZoom: number;
  }>({
    positions: new Map(),
    toolbarAnchor: null,
    scrollTicks: [],
    gutterWidthPx: 54,
    effectiveZoom: 1,
  });

  const [scrollThumb, setScrollThumb] = useState<{ topPct: number; heightPct: number }>({
    topPct: 0,
    heightPct: 100,
  });

  const [hoveredStatusLabel, setHoveredStatusLabel] = useState<string | null>(null);
  const [narrowEditDraft, setNarrowEditDraft] = useState("");
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

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);

  const indexedChanges = useMemo(
    () => (inspect ? buildIndexedChanges(draft, inspect, textMap, language) : []),
    [draft, inspect, textMap, language],
  );

  const isStale = Boolean(
    isStaleOverride ??
      (draft.validation?.stale ||
        (draft.plan && draft.boundSha256 && draft.plan.boundSha256 !== draft.boundSha256)),
  );

  const changes = useMemo<CanvasChangeRef[]>(() => {
    if (changesOverride) {
      return changesOverride.map((ch) => ({
        ...ch,
        decision: slice.decisions[ch.id] ?? ch.decision,
        isStale: ch.isStale ?? isStale,
      }));
    }
    return indexedChangesToCanvasRefs(indexedChanges, guardSummary.rowAudits, slice.decisions, {
      isStale,
      reverses: draft.reverses,
      planProvenance: (draft.plan as { provenance?: string | null } | null)?.provenance,
    });
  }, [
    changesOverride,
    indexedChanges,
    guardSummary.rowAudits,
    slice.decisions,
    isStale,
    draft.reverses,
    draft.plan,
  ]);

  const baseName = useMemo(() => {
    if (baseNameOverride) return baseNameOverride;
    if (head) {
      const candidates = candidatesBySession[session?.sessionId ?? ""] ?? [];
      const idx = candidates.findIndex((c) => c.runId === head.runId);
      if (idx >= 0) return wp3t("canvas_view_base_revision", language, [idx + 1]);
    }
    return wp3t("canvas_view_base_source", language);
  }, [baseNameOverride, head, candidatesBySession, session?.sessionId, language]);

  const pageSource = useMemo<PageSource | null>(() => {
    if (!inspect) return null;
    return createProjectionPageSource({
      inspect,
      texts,
      textMap,
      changes,
      render,
      geometry,
      rev: baseName,
      language,
    });
  }, [inspect, texts, textMap, changes, render, geometry, baseName, language]);

  useEffect(() => {
    publishCanvasContext(changes, pageSource);
    onPageSourceReady?.(pageSource);
  }, [changes, pageSource, onPageSourceReady]);

  // Keep selectedChangeId valid
  useEffect(() => {
    if (changes.length === 0) return;
    if (!slice.selectedChangeId || !changes.some((c) => c.id === slice.selectedChangeId)) {
      canvas.select(changes[0].id, { fromCanvas: true });
    }
  }, [changes, slice.selectedChangeId]);

  const updateScrollThumb = useCallback(() => {
    const el = scrollRef.current;
    if (!el || el.scrollHeight <= 0) return;
    const topPct = (el.scrollTop / el.scrollHeight) * 100;
    const heightPct = (el.clientHeight / el.scrollHeight) * 100;
    setScrollThumb({ topPct, heightPct });
  }, []);

  useEffect(() => {
    updateScrollThumb();
  }, [updateScrollThumb, measured]);

  const handleMeasurementsChange = useCallback(
    (data: {
      positions: Map<string, MeasuredMarkPos>;
      toolbarAnchor: MarkToolbarAnchor | null;
      scrollTicks: ScrollMapTick[];
      gutterWidthPx: number;
      effectiveZoom: number;
    }) => {
      setMeasured(data);
      const nextPct = Math.round(data.effectiveZoom * 100);
      setCanvasSlice((prev) =>
        prev.effectiveZoomPct === nextPct ? prev : { ...prev, effectiveZoomPct: nextPct },
      );
    },
    [],
  );

  const selectedItem = useMemo(
    () => changes.find((c) => c.id === slice.selectedChangeId) ?? null,
    [changes, slice.selectedChangeId],
  );

  const handleDecide = useCallback(
    (itemId: string, decision: "pending" | "accepted" | "rejected") => {
      decideCanvasItem(itemId, decision);
      onDecideItem?.(itemId, decision);
    },
    [onDecideItem],
  );

  const handleEditSelected = useCallback(
    (item: CanvasChangeRef) => {
      if (onEditItem) {
        onEditItem(item);
        return;
      }
      if (!inspect || !item.cellKey) return;
      const m = /^c:(\d+):(\d+):(\d+)$/.exec(item.cellKey);
      if (!m) return;
      import("./actions").then(({ beginCellEditV2 }) => {
        beginCellEditV2(Number(m[1]), Number(m[2]), Number(m[3]), {
          inspect,
          texts: [...texts],
        });
      });
    },
    [onEditItem, inspect, texts],
  );

  useEffect(() => {
    if (inlineEdit?.kind === "cell") {
      setNarrowEditDraft(inlineEdit.before);
    }
  }, [inlineEdit]);

  if (!session || !inspect) {
    return null;
  }

  const scrollReq = getScrollRequestState();
  const activeSeatLabel =
    inlineEdit?.kind === "cell"
      ? deriveCellFieldLabel(
          inspect,
          textMap,
          inlineEdit.table,
          inlineEdit.row,
          inlineEdit.col,
          language,
        )
      : hoveredStatusLabel;

  return (
    <section
      className="rl-canvas-col"
      data-testid="canvas-pane"
      data-effective-zoom={String(Math.round(measured.effectiveZoom * 100))}
      data-seat-status={activeSeatLabel ?? ""}
    >
      <DocumentStrip
        baseName={baseName}
        changes={changes}
        selectedChangeId={slice.selectedChangeId}
        view={slice.view}
        isStale={isStale}
        readOnly={readOnly}
        language={language}
        onSetView={(v) => canvas.setView(v)}
        onStepChange={(d) => stepCanvasChange(d)}
        stripStart={stripStart}
        stripEnd={stripEnd}
      />

      <div className="rl-desk">
        <div
          ref={scrollRef}
          className="rl-desk-scroll"
          data-testid="canvas-scroll"
          onScroll={updateScrollThumb}
        >
          <div className="rl-paper-stage">
            <PageSheet
              sessionId={session.sessionId}
              inspect={inspect}
              texts={texts}
              textMap={textMap}
              changes={changes}
              selectedChangeId={slice.selectedChangeId}
              selectedSeatKey={slice.selectedSeatKey}
              hoveredSeatKey={slice.hoveredSeatKey}
              view={slice.view}
              pageFit={slice.pageFit}
              zoom={slice.zoom}
              narrowReadZoom={slice.narrowReadZoom}
              drying={slice.drying}
              findQuery={slice.findQuery}
              activeFindCellKey={slice.activeFindCellKey}
              language={language}
              scrollContainerRef={scrollRef}
              scrollRequestNonce={scrollReq.nonce}
              scrollRequestOrigin={scrollReq.origin}
              onSelectChange={(id, opts) => canvas.select(id, opts)}
              onSelectSeat={(key, label) => {
                setHoveredStatusLabel(label);
                setCanvasSlice({ hoveredSeatKey: key, hoveredSeatLabel: label });
              }}
              onMeasurementsChange={handleMeasurementsChange}
            />

            {slice.view === "marks" ? (
              <MarginMarks
                changes={changes}
                positions={measured.positions}
                selectedChangeId={slice.selectedChangeId}
                zoom={measured.effectiveZoom}
                gutterWidthPx={measured.gutterWidthPx}
                drying={slice.drying}
                language={language}
                onSelect={(id) => canvas.select(id, { fromCanvas: false })}
              />
            ) : null}

            {!isNarrow &&
            !readOnly &&
            slice.view === "marks" &&
            selectedItem &&
            measured.toolbarAnchor ? (
              <MarkToolbar
                item={selectedItem}
                anchor={measured.toolbarAnchor}
                canEdit={Boolean(selectedItem.cellKey && selectedItem.opKind !== "delete_guides")}
                language={language}
                onDecide={handleDecide}
                onEdit={handleEditSelected}
              />
            ) : null}
          </div>
        </div>

        {slice.view === "marks" && changes.length > 0 ? (
          <ScrollMap
            ticks={measured.scrollTicks}
            selectedChangeId={slice.selectedChangeId}
            thumbTopPct={scrollThumb.topPct}
            thumbHeightPct={scrollThumb.heightPct}
            language={language}
            onSelect={(id) => canvas.select(id, { fromCanvas: false })}
          />
        ) : null}
      </div>

      {isNarrow && inlineEdit?.kind === "cell" ? (
        <div className="rl-narrow-seat-bar" data-testid="narrow-seat-bar">
          <span className="rl-narrow-seat-label">
            {deriveCellFieldLabel(
              inspect,
              textMap,
              inlineEdit.table,
              inlineEdit.row,
              inlineEdit.col,
              language,
            )}
          </span>
          <div className="rl-narrow-seat-controls">
            <SeatEditor
              key={`narrow-${cellKey(inlineEdit.table, inlineEdit.row, inlineEdit.col)}`}
              value={narrowEditDraft}
              caret="end"
              className="rl-narrow-seat-input"
              onCommit={(val) => {
                void commitCellEditV2(val, { inspect });
              }}
              onCancel={cancelEdit}
            />
            <button
              type="button"
              className="rl-narrow-seat-btn"
              onClick={() => cancelEdit()}
            >
              {wp3t("seat_narrow_cancel", language)}
            </button>
            <button
              type="button"
              className="rl-narrow-seat-btn rl-narrow-seat-btn--commit"
              onClick={() => {
                const el = document.querySelector<HTMLInputElement | HTMLTextAreaElement>(
                  '[data-testid="seat-input"]',
                );
                void commitCellEditV2(el?.value ?? narrowEditDraft, { inspect });
              }}
            >
              {wp3t("seat_narrow_commit", language)}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

// --- Status bar slots (`statusLeft` / `statusRight`) ------------------------

export function CanvasStatusLeft() {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeText);
  const render = useWorkspace((s) => s.render);
  const page = useWorkspace((s) => s.page);
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const language = useWorkspace((s) => s.language);
  const slice = useCanvasSlice(session?.sessionId);

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);

  const charCount = useMemo(() => {
    if (!inspect) return 0;
    let total = 0;
    const seen = new Set<string>();
    for (const r of texts) {
      total += r.text.replace(/\s+/g, "").length;
      if (r.addr) seen.add(`c:${r.table ?? 0}:${r.addr.row}:${r.addr.col}`);
    }
    for (const tbl of inspect.graph.tables) {
      for (const c of tbl.cells) {
        const k = `c:${tbl.index}:${c.addr.row}:${c.addr.col}`;
        if (!seen.has(k) && c.textPreview) {
          total += c.textPreview.replace(/\s+/g, "").length;
        }
      }
    }
    return total;
  }, [inspect, texts]);

  const seatLabelByKey = useMemo(() => {
    const map = new Map<string, string>();
    if (!inspect) return map;
    for (const s of detectDocumentSeats(inspect, textMap, [], language)) {
      map.set(s.key, s.displayLabel);
    }
    return map;
  }, [inspect, textMap, language]);

  const seatText = useMemo(() => {
    if (!inspect) return null;
    if (inlineEdit?.kind === "cell") {
      const k = cellKey(inlineEdit.table, inlineEdit.row, inlineEdit.col);
      const label =
        seatLabelByKey.get(k) ??
        deriveCellFieldLabel(
          inspect,
          textMap,
          inlineEdit.table,
          inlineEdit.row,
          inlineEdit.col,
          language,
        );
      return `${label} · ${formatSeatLocation(
        page,
        inlineEdit.table,
        inlineEdit.row,
        inlineEdit.col,
        language,
      )}`;
    }
    if (slice.hoveredSeatLabel) {
      return slice.hoveredSeatLabel;
    }
    if (slice.selectedSeatKey) {
      const m = /^c:(\d+):(\d+):(\d+)$/.exec(slice.selectedSeatKey);
      if (m) {
        const tIdx = Number(m[1]);
        const rIdx = Number(m[2]);
        const cIdx = Number(m[3]);
        const label =
          seatLabelByKey.get(slice.selectedSeatKey) ??
          deriveCellFieldLabel(inspect, textMap, tIdx, rIdx, cIdx, language);
        return `${label} · ${formatSeatLocation(page, tIdx, rIdx, cIdx, language)}`;
      }
    }
    return null;
  }, [
    inspect,
    seatLabelByKey,
    inlineEdit,
    slice.selectedSeatKey,
    slice.hoveredSeatLabel,
    textMap,
    page,
    language,
  ]);

  const isPaginated = Boolean(render?.available && (render.pageCount ?? 0) > 0);
  const pageCount = render?.pageCount ?? 1;

  return (
    <div className="rl-status-left" data-testid="status-canvas-left">
      {isPaginated ? (
        <span className="rl-status-item rl-num" data-testid="status-page-pos">
          {wp3t("status_page_pos", language, [page, pageCount])}
        </span>
      ) : null}
      {seatText ? (
        <span className="rl-status-item" data-testid="status-seat">
          {seatText}
        </span>
      ) : null}
      <span className="rl-status-item rl-num" data-testid="status-char-count">
        {wp3t("status_char_count", language, [charCount.toLocaleString()])}
      </span>
      {slice.statusNotice ? (
        <span className="rl-status-notice" data-testid="status-canvas-notice" role="status">
          {slice.statusNotice}
        </span>
      ) : null}
    </div>
  );
}

export function CanvasStatusRight({
  effectiveZoomPct,
}: {
  effectiveZoomPct?: number;
}) {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const render = useWorkspace((s) => s.render);
  const language = useWorkspace((s) => s.language);
  const slice = useCanvasSlice(session?.sessionId);

  const fonts = useMemo(() => {
    if (!inspect) return null;
    const src = createProjectionPageSource({
      inspect,
      texts: [],
      textMap: {},
      changes: [],
      render,
      language,
    });
    return src.fonts();
  }, [inspect, render, language]);

  const subCount = fonts?.substitutedCount ?? 0;
  const pct = effectiveZoomPct ?? slice.effectiveZoomPct ?? Math.round(slice.zoom * 100);

  return (
    <div className="rl-status-right" data-testid="status-canvas-right">
      {subCount > 0 ? (
        <span
          className="rl-status-item rl-status-item--attn"
          data-testid="status-font-sub"
          title={fonts?.entries
            .filter((e) => e.substituted)
            .map((e) => wp3t("status_font_sub_detail", language, [e.declared, e.resolved]))
            .join(", ")}
        >
          {wp3t("status_font_sub", language, [subCount])}
        </span>
      ) : null}

      <div className="rl-zoom-ctl" data-testid="status-zoom">
        <button
          type="button"
          className="rl-zoom-btn"
          data-testid="zoom-out"
          aria-label={wp3t("zoom_out", language)}
          onClick={() => stepCanvasZoom(-0.1)}
        >
          −
        </button>
        <button
          type="button"
          className="rl-zoom-pct rl-num"
          data-testid="zoom-fit-reset"
          title={wp3t("zoom_fit_width", language)}
          onClick={() => fitCanvasWidth()}
        >
          {`${pct}%`}
        </button>
        <button
          type="button"
          className="rl-zoom-btn"
          data-testid="zoom-in"
          aria-label={wp3t("zoom_in", language)}
          onClick={() => stepCanvasZoom(0.1)}
        >
          +
        </button>
      </div>
    </div>
  );
}
