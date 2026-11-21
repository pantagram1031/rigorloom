import { SOURCE_COPY } from "./sourceCopy";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { cancelEdit } from "../actions";
import { wp3t } from "../i18n/v2/wp3";
import { createEnginePageSource, engineTextEdit } from "../model/enginePage";
import {
  createProjectionPageSource,
  detectDocumentSeats,
  parseDocAddress,
  type CanvasChangeRef,
  type PageSource,
} from "../model/page";
import {
  activeInspect,
  activeSession,
  activeDisplayText,
  cellKey,
  headCandidate,
  useWorkspace,
} from "../store";
import { buildRegionTextMap } from "../workspace/externalPlan";
import { deriveCellFieldLabel } from "../workspace/fieldLabels";
import { useCanvasChanges } from "./changes";
import {
  beginCellEditV2,
  commitCellEditV2,
  decideCanvasItem,
  fitCanvasWidth,
  stepCanvasZoom,
} from "./actions";
import {
  canvas,
  getScrollRequestState,
  publishCanvasContext,
  setCanvasSlice,
  useCanvasSlice,
} from "./controller";
import { FontStatus } from "./FontStatus";
import { MarkToolbar, type MarkToolbarAnchor } from "./MarkToolbar";
import { PageSheet } from "./PageSheet";
import { ScrollMap, type ScrollMapTick } from "./ScrollMap";
import { SeatEditor } from "./SeatEditor";
import { usePageRaster } from "./usePageRaster";
import "./canvas.css";

export function CanvasPane() {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeDisplayText);
  const render = useWorkspace((s) => s.render);
  const geometry = useWorkspace((s) => s.geometry);
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const language = useWorkspace((s) => s.language);
  const rev = useWorkspace((s) => headCandidate(s)?.sha256 ?? activeSession(s)?.source.sha256);
  const headRunId = useWorkspace((s) => headCandidate(s)?.runId ?? null);
  const draft = useWorkspace((s) => s.draft);

  const slice = useCanvasSlice(session?.sessionId);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const [measured, setMeasured] = useState<{
    toolbarAnchor: MarkToolbarAnchor | null;
    scrollTicks: ScrollMapTick[];
    effectiveZoom: number;
  }>({
    toolbarAnchor: null,
    scrollTicks: [],
    effectiveZoom: 1,
  });

  const [scrollThumb, setScrollThumb] = useState<{ topPct: number; heightPct: number }>({
    topPct: 0,
    heightPct: 100,
  });

  const [hoveredStatusLabel, setHoveredStatusLabel] = useState<string | null>(null);
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

  const changes = useCanvasChanges(session?.sessionId ?? null, textMap);
  const previewEdits = useMemo(() => {
    if (slice.rasterSource !== "engine" || slice.view === "base" ||
        draft.sessionId !== session?.sessionId || draft.baseRunId !== headRunId) return [];
    const rejected = new Set(changes.filter((change) => change.decision === "rejected").map((change) => change.id));
    return draft.ops.flatMap((op) => op.origin === "user" && !rejected.has(op.opId) ? engineTextEdit(op) : []);
  }, [changes, draft, headRunId, session?.sessionId, slice.rasterSource, slice.view]);
  const pageRaster = usePageRaster(
    session?.sessionId, rev, slice.page,
    slice.effectiveZoomPct === null ? null : measured.effectiveZoom, previewEdits, slice.fontRefresh,
  );
  const pageSource = useMemo<PageSource | null>(() => {
    if (!inspect) return null;
    const projection = createProjectionPageSource({
      inspect,
      texts,
      textMap,
      changes,
      render,
      geometry,
      rev,
      language,
    });
    if (!pageRaster.raster) return projection;
    return createEnginePageSource({
      projection, raster: pageRaster.raster, geometry: pageRaster.geometry,
      count: pageRaster.count, changes,
    });
  }, [inspect, texts, textMap, changes, render, geometry, rev, language,
    pageRaster.raster, pageRaster.geometry, pageRaster.count]);

  const source = pageRaster.raster?.source ?? null;
  useEffect(() => {
    if (!session) return;
    setCanvasSlice((prev) => ({
      ...prev,
      page: pageRaster.settled ? Math.min(prev.page, pageRaster.count) : prev.page,
      pageCount: pageRaster.count, rasterSource: source,
      rasterApprox: pageRaster.approx,
    }), session.sessionId);
  }, [session, source, pageRaster.count, pageRaster.approx, pageRaster.settled]);

  useEffect(() => {
    publishCanvasContext(changes, pageSource);
    return () => publishCanvasContext([], null);
  }, [changes, pageSource]);

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
      toolbarAnchor: MarkToolbarAnchor | null;
      scrollTicks: ScrollMapTick[];
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

  const handleEditSelected = (item: CanvasChangeRef) => {
    const target = item.cellKey?.match(/^c:(\d+):(\d+):(\d+)$/);
    if (target) beginCellEditV2(Number(target[1]), Number(target[2]), Number(target[3]));
  };

  if (!session || !inspect) {
    return null;
  }

  const scrollReq = getScrollRequestState();
  const visiblePage = pageRaster.raster?.page ?? slice.page;
  const narrowEditDraft = inlineEdit?.kind === "cell"
    ? changes.find((change) => change.id === inlineEdit.opId && change.decision !== "rejected")?.after ??
      inlineEdit.before
    : "";
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
      <div className="rl-desk">
        {pageRaster.failed ? (
          <div className="rl-redraw-notice" data-testid="page-render-failed" role="status">
            {wp3t("page_render_failed", language)}
          </div>
        ) : null}
        <div
          ref={scrollRef}
          className="rl-desk-scroll"
          data-testid="canvas-scroll"
          onScroll={updateScrollThumb}
        >
          <div className="rl-paper-stage">
            <PageSheet
              key={session.sessionId}
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
              pageSource={pageSource}
              page={visiblePage}
              engineGeometry={pageRaster.geometry}
              engineEditable={Boolean(pageRaster.geometry && pageRaster.raster?.rev === rev && visiblePage === slice.page && slice.view !== "base")}
              previewRects={pageRaster.changed}
              previewSettled={pageRaster.settled}
              displayedEdits={pageRaster.displayedEdits}
            />

            {!isNarrow &&
            slice.view === "marks" &&
            selectedItem &&
            measured.toolbarAnchor ? (
              <MarkToolbar
                item={selectedItem}
                anchor={measured.toolbarAnchor}
                canEdit={Boolean(selectedItem.cellKey && selectedItem.opKind !== "delete_guides")}
                language={language}
                onDecide={decideCanvasItem}
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

      {isNarrow && rev ? (
        <FontStatus key={`${session.sessionId}:${rev}`} sessionId={session.sessionId} rev={rev}
          language={language} source={source ?? "projection"} narrow />
      ) : null}

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
              multiline={inlineEdit.multiline}
              className="rl-narrow-seat-input"
              onCommit={(val) => {
                void commitCellEditV2(val, { inspect });
              }}
              onCancel={cancelEdit}
            />
            <button
              type="button"
              className="rl-narrow-seat-btn"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => cancelEdit()}
            >
              {wp3t("seat_narrow_cancel", language)}
            </button>
            <button
              type="button"
              className="rl-narrow-seat-btn rl-narrow-seat-btn--commit"
              onMouseDown={(e) => e.preventDefault()}
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
  const texts = useWorkspace(activeDisplayText);
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const language = useWorkspace((s) => s.language);
  const slice = useCanvasSlice(session?.sessionId);
  const { page, pageCount, rasterSource, rasterApprox } = slice;

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

  const changes = useCanvasChanges(session?.sessionId ?? null, textMap);
  const selectedCellKey = changes.find((change) => change.id === slice.selectedChangeId)?.cellKey;
  const statusKey = inlineEdit?.kind === "cell"
    ? cellKey(inlineEdit.table, inlineEdit.row, inlineEdit.col)
    : slice.hoveredSeatKey ?? selectedCellKey ?? slice.selectedSeatKey;
  const address = statusKey ? parseDocAddress(statusKey) : null;
  const position = address?.kind === "cell"
    ? wp3t("status_cell_position", language, [page, address.row + 1, address.col + 1])
    : wp3t("status_page_position", language, [page]);

  const seatText = inspect && statusKey && address?.kind === "cell"
    ? seatLabelByKey.get(statusKey) ??
      deriveCellFieldLabel(inspect, textMap, address.table, address.row, address.col, language)
    : null;

  return (
    <div className="rl-status-left" data-testid="status-canvas-left">
      {pageCount > 1 ? (
        <span className="rl-zoom-ctl">
          <button type="button" className="rl-zoom-btn" disabled={page <= 1}
            aria-label={wp3t("page_previous", language)}
            onClick={() => setCanvasSlice({ page: page - 1 })}>‹</button>
          <span className="rl-status-item rl-num" data-testid="status-page-pos">
            {wp3t("status_page_pos", language, [page, pageCount])}
          </span>
          <button type="button" className="rl-zoom-btn" disabled={page >= pageCount}
            aria-label={wp3t("page_next", language)}
            onClick={() => setCanvasSlice({ page: page + 1 })}>›</button>
        </span>
      ) : null}
      <span className="rl-status-item" data-testid="status-page-source"
        data-page-source={rasterSource ?? "projection"}>
        {wp3t(rasterSource ? SOURCE_COPY[rasterSource] : "page_source_projection", language)}
        {rasterApprox ? ` · ${wp3t("page_source_approx", language)}` : null}
      </span>
      <span className="rl-status-item rl-num" data-testid="status-cell-position">{position}</span>
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

export function CanvasStatusRight() {
  const session = useWorkspace(activeSession);
  const language = useWorkspace((s) => s.language);
  const rev = useWorkspace((s) => headCandidate(s)?.sha256 ?? activeSession(s)?.source.sha256);
  const slice = useCanvasSlice(session?.sessionId);

  const pct = slice.effectiveZoomPct ?? Math.round(slice.zoom * 100);

  return (
    <div className="rl-status-right" data-testid="status-canvas-right">
      {session && rev ? (
        <FontStatus key={`${session.sessionId}:${rev}`} sessionId={session.sessionId} rev={rev}
          language={language} source={slice.rasterSource ?? "projection"} />
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
          {`${(pct / 100).toFixed(2)}×`}
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
