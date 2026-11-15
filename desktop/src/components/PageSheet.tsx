import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";

import {
  beginEdit,
  cancelEdit,
  commitEdit,
  loadGeometry,
  renderCurrentPage,
  togglePrintView,
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
  InspectResult,
  RegionText,
  UiLanguage,
} from "../types";
import type { IndexedChange, RowGuardAudit } from "../workspace/guardHelper";
import { SeatEditor } from "./SeatEditor";

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
}: PageSheetProps) {
  const zoom = useWorkspace((s) => s.zoom);
  const pageFit = useWorkspace((s) => s.pageFit);
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
  const [boxWidth, setBoxWidth] = useState(0);
  const [naturalHeightMeasure, setNaturalHeightMeasure] = useState(0);

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
      const w = Math.max(0, el.clientWidth - 32);
      const h = Math.max(0, el.clientHeight - 32);
      setBoxWidth(w);
      if (getState().pageFit === "width" && w > 0) {
        const next = fitScale(
          "width",
          { width: naturalWidthPx, height: naturalHeightPx },
          { width: w, height: Math.max(1, h) },
          getState().zoom,
        );
        if (Math.abs(next - getState().zoom) > 0.002) {
          setFittedZoom(next);
        }
      }
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [naturalWidthPx, naturalHeightPx]);

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

  const effectiveZoom = useMemo(() => {
    if (pageFit === "width" && boxWidth > 0) {
      const ratio = boxWidth / naturalWidthPx;
      if (ratio < 0.5) {
        return Math.max(0.32, Math.round(ratio * 1000) / 1000);
      }
    }
    return zoom;
  }, [pageFit, boxWidth, naturalWidthPx, zoom]);

  // If print view is toggled on externally (e.g. command palette), fetch page 1 once.
  useEffect(() => {
    if (!printViewEnabled) return;
    if (!render && renderPhase === "idle") {
      void renderCurrentPage(page);
      void loadGeometry(page);
    }
  }, [printViewEnabled, render, renderPhase, page, sessionId]);

  // Bidirectional scroll sync when a change row is selected from the list or keyboard.
  useEffect(() => {
    if (!selectedChangeId) return;
    if (skipNextAutoScroll.current) {
      skipNextAutoScroll.current = false;
      return;
    }
    const container = viewportRef.current;
    if (!container) return;
    const markerEl = container.querySelector<HTMLElement>(
      `[data-marker-op-id="${CSS.escape(selectedChangeId)}"]`,
    );
    const targetEl =
      markerEl ??
      container.querySelector<HTMLElement>(
        `[data-cell-op-ids~="${CSS.escape(selectedChangeId)}"]`,
      );
    if (!targetEl) return;
    targetEl.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [selectedChangeId, printViewEnabled]);

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
    for (const region of texts) {
      if (!region.addr) continue;
      for (const run of region.runs ?? []) {
        set.add(run.text.trim());
      }
    }
    return set;
  }, [texts]);

  const looseParagraphs = useMemo(
    () =>
      inspect.graph.paragraphs.filter(
        (p) => p.text.trim().length > 0 && !coveredCellStrings.has(p.text.trim()),
      ),
    [inspect, coveredCellStrings],
  );

  const editingCellKey =
    inlineEdit && inlineEdit.kind === "cell"
      ? cellKey(inlineEdit.table, inlineEdit.row, inlineEdit.col)
      : null;

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
  const sheetOuterWidth = Math.round(naturalWidthPx * effectiveZoom);

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
    const isEditing = editingCellKey === key && inlineEdit !== null;
    if (isEditing && inlineEdit) {
      const currentOpText =
        cellChanges.length === 1 ? cellChanges[0].afterText : undefined;
      return (
        <SeatEditor
          value={currentOpText ?? inlineEdit.before}
          onCommit={(next) => void commitEdit(next)}
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

    const activeCellChange =
      cellChanges.find((ch) => ch.opId === selectedChangeId) ??
      (cellChanges.length === 1 ? cellChanges[0] : null);

    const showBeforeCallout =
      activeCellChange !== null &&
      activeCellChange.op.kind === "replace_at_cell" &&
      activeCellChange.beforeText.trim().length > 0;

    return (
      <div className="page-cell-inner">
        {cellChanges.length > 0 ? (
          <div className="page-marker-strip">
            {cellChanges.map((ch) => {
              const status = rowAudits[ch.opId]?.status ?? "none";
              const isSelected = selectedChangeId === ch.opId;
              return (
                <button
                  key={ch.opId}
                  type="button"
                  className={`page-marker-badge page-marker-badge--${status}${
                    isSelected ? " page-marker-badge--selected" : ""
                  }`}
                  data-testid={`page-marker-${ch.ordinal}`}
                  data-marker-op-id={ch.opId}
                  aria-pressed={isSelected}
                  onClick={(e) => handleMarkerClick(e, ch.opId)}
                >
                  [{ch.ordinal}]
                </button>
              );
            })}
          </div>
        ) : null}

        {wholeCellChange ? (
          <div className="page-cell-text page-cell-text--proposed">
            {wholeCellChange.afterText}
          </div>
        ) : runMap.size > 0 && region?.runs?.length ? (
          <div className="page-cell-text">
            {region.runs.map((run) => {
              const hit = runMap.get(run.index);
              if (!hit) {
                return <span key={run.index}>{run.text}</span>;
              }
              const status = rowAudits[hit.opId]?.status ?? "none";
              return (
                <span
                  key={run.index}
                  className={`page-inline-edit page-inline-edit--${status}`}
                  onClick={(e) => handleMarkerClick(e, hit.opId)}
                >
                  {hit.afterText}
                </span>
              );
            })}
          </div>
        ) : cellChanges.length > 0 ? (
          <div className="page-cell-text page-cell-text--proposed">
            {cellChanges.map((ch) => ch.afterText).join("\n")}
          </div>
        ) : (
          <div className="page-cell-text">
            {region?.text ?? cell.textPreview ?? ""}
            {cell.truncated && !region ? "…" : ""}
          </div>
        )}

        {showBeforeCallout && activeCellChange ? (
          <div className="page-before-callout">
            {t("review_before_label", language, [activeCellChange.beforeText])}
          </div>
        ) : null}

        {cellChanges.length === 0 &&
        cell.classification === "fill_target" &&
        !(region?.text ?? cell.textPreview ?? "").trim() ? (
          <span className="page-seat-hint" aria-hidden="true">
            {cellClassLabel("fill_target", language)}
          </span>
        ) : null}
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
        ? "needs_fixes"
        : paraChanges.length > 0
          ? "accent"
          : "none";

    const runMap = new Map<number, IndexedChange>();
    for (const ch of paraChanges) {
      if (ch.op.kind === "set_run") {
        runMap.set(ch.op.run, ch);
      }
    }

    const activeParaChange =
      paraChanges.find((ch) => ch.opId === selectedChangeId) ??
      (paraChanges.length === 1 ? paraChanges[0] : null);

    return (
      <div
        key={`p:${atPara}`}
        className={`page-para${
          paraChanges.length > 0 ? ` page-para--changed page-para--rail-${worstStatus}` : ""
        }${hasSelected ? " page-para--selected" : ""}`}
        onClick={() => {
          if (paraChanges.length > 0) {
            selectFromSheet(paraChanges[0].opId);
          }
        }}
      >
        {paraChanges.length > 0 ? (
          <div className="page-marker-strip">
            {paraChanges.map((ch) => {
              const status = rowAudits[ch.opId]?.status ?? "none";
              const isSelected = selectedChangeId === ch.opId;
              return (
                <button
                  key={ch.opId}
                  type="button"
                  className={`page-marker-badge page-marker-badge--${status}${
                    isSelected ? " page-marker-badge--selected" : ""
                  }`}
                  data-testid={`page-marker-${ch.ordinal}`}
                  data-marker-op-id={ch.opId}
                  aria-pressed={isSelected}
                  onClick={(e) => handleMarkerClick(e, ch.opId)}
                >
                  [{ch.ordinal}]
                </button>
              );
            })}
          </div>
        ) : null}

        <p className="page-para-body">
          {region?.runs?.length ? (
            region.runs.map((run) => {
              const hit = runMap.get(run.index);
              if (!hit) return <span key={run.index}>{run.text}</span>;
              const status = rowAudits[hit.opId]?.status ?? "none";
              return (
                <span
                  key={run.index}
                  className={`page-inline-edit page-inline-edit--${status}`}
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

        {activeParaChange && activeParaChange.beforeText.trim().length > 0 ? (
          <div className="page-before-callout">
            {t("review_before_label", language, [activeParaChange.beforeText])}
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <section className="page-sheet-pane" aria-label={t("review_mobile_sheet_tab", language)}>
      <div className="page-sheet-subbar">
        <p className="page-sheet-disclaimer" data-testid="page-sheet-disclaimer">
          {t("page_label_review", language)}
        </p>

        <div className="page-sheet-controls">
          <div
            className="page-sheet-zoom"
            data-testid="page-sheet-zoom"
            role="group"
            aria-label={t("review_zoom_label", language, [Math.round(effectiveZoom * 100)])}
          >
            <button
              type="button"
              className="page-ctrl-btn"
              disabled={zoom <= 0.5}
              aria-label={t("review_zoom_out", language)}
              onClick={() => setZoom(Math.max(0.5, Number((zoom - 0.1).toFixed(2))))}
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
              disabled={zoom >= 2.0}
              aria-label={t("review_zoom_in", language)}
              onClick={() => setZoom(Math.min(2.0, Number((zoom + 0.1).toFixed(2))))}
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

      <div className="page-sheet-viewport" ref={viewportRef}>
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
                  <colgroup>
                    {Array.from({ length: table.columns }, (_, idx) => (
                      <col key={idx} />
                    ))}
                  </colgroup>
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
                          const isSelected = cellChanges.some(
                            (ch) => ch.opId === selectedChangeId,
                          );
                          const hasChangedFact = cellChanges.some(
                            (ch) => rowAudits[ch.opId]?.status === "changed",
                          );
                          const hasHardFix = cellChanges.some(
                            (ch) => rowAudits[ch.opId]?.status === "needs_fixes",
                          );

                          const cls = [
                            "page-cell",
                            `page-cell--class-${cell.classification}`,
                            isFillTarget ? "page-cell--fill-seat" : "",
                            cellChanges.length > 0 ? "page-cell--changed" : "",
                            hasChangedFact
                              ? "page-cell--rail-changed"
                              : hasHardFix
                                ? "page-cell--rail-needs-fixes"
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
                              data-testid={`page-cell-${table.index}-${cell.addr.row}-${cell.addr.col}`}
                              data-cell-op-ids={cellChanges.map((ch) => ch.opId).join(" ")}
                              onClick={() => {
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

              {deleteGuideChanges.length > 0 ? (
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
                        onClick={() => selectFromSheet(ch.opId)}
                      >
                        <button
                          type="button"
                          className={`page-marker-badge page-marker-badge--${status}${
                            isSelected ? " page-marker-badge--selected" : ""
                          }`}
                          data-testid={`page-marker-${ch.ordinal}`}
                          data-marker-op-id={ch.opId}
                          aria-pressed={isSelected}
                          onClick={(e) => handleMarkerClick(e, ch.opId)}
                        >
                          [{ch.ordinal}]
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
