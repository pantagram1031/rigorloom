import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import {
  addQueueOp,
  beginEdit,
  beginStaticCellEdit,
  cancelEdit,
  commitEdit,
  navigateScreen,
  redoQueuedOp,
  reproposeDraft,
  seatAt,
  seatText,
  setInlineEditMultiline,
  undoQueuedOp,
} from "../actions";
import { DetailDisclosure } from "../components/DetailDisclosure";
import { PageSheet } from "../components/PageSheet";
import { t } from "../i18n/vocabulary";
import {
  activeInspect,
  activeSession,
  activeText,
  cellKey,
  queuedCellOpAt,
  useWorkspace,
} from "../store";
import type { GraphCell } from "../types";
import { buildRegionTextMap } from "../workspace/externalPlan";
import { deriveCellFieldLabel } from "../workspace/fieldLabels";
import { buildIndexedChanges, type RowGuardAudit } from "../workspace/guardHelper";
import "./fill.css";

interface BlankSlot {
  key: string;
  table: number;
  row: number;
  col: number;
  ordinal: number;
  label: string;
  formBefore: string;
  charPrSuggested?: string;
}

const EMPTY_AUDITS: Record<string, RowGuardAudit> = {};

export function FillView() {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeText);
  const draft = useWorkspace((s) => s.draft);
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const redoStack = useWorkspace((s) => s.redoStack);
  const language = useWorkspace((s) => s.language);
  const state = useWorkspace((s) => s);

  const sheetAnchorRef = useRef<HTMLDivElement | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [selectedStatic, setSelectedStatic] = useState<{
    cell: GraphCell;
    table: number;
  } | null>(null);
  const [inspectorValue, setInspectorValue] = useState("");
  const [inspectorMultiline, setInspectorMultiline] = useState(false);
  const [navigatingToReview, setNavigatingToReview] = useState(false);
  const [undoDismissed, setUndoDismissed] = useState(false);
  const [lastUndoReason, setLastUndoReason] = useState<"removed" | "cleared">("removed");
  const prevRedoLenRef = useRef(redoStack.length);

  const sessionId = session?.sessionId ?? null;
  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);

  const blanks = useMemo<BlankSlot[]>(() => {
    if (!inspect) return [];
    const seats = inspect.regions.regions
      .filter(
        (r): r is typeof r & { row: number; col: number } =>
          r.kind === "cell" && typeof r.row === "number" && typeof r.col === "number",
      )
      .slice()
      .sort((a, b) => (a.table ?? 0) - (b.table ?? 0) || a.row - b.row || a.col - b.col);
    return seats.map((r, idx) => {
      const tbl = r.table ?? 0;
      return {
        key: cellKey(tbl, r.row, r.col),
        table: tbl,
        row: r.row,
        col: r.col,
        ordinal: idx + 1,
        label: deriveCellFieldLabel(inspect, textMap, tbl, r.row, r.col, language, idx + 1),
        formBefore: seatText(inspect, texts, tbl, r.row, r.col),
        charPrSuggested: r.charPrSuggested,
      };
    });
  }, [inspect, texts, textMap, language]);

  const blankFieldLabels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const slot of blanks) {
      out[slot.key] = slot.label;
    }
    return out;
  }, [blanks]);

  const duplicateGroups = useMemo(() => {
    const map = new Map<string, BlankSlot[]>();
    for (const slot of blanks) {
      const list = map.get(slot.label) ?? [];
      list.push(slot);
      map.set(slot.label, list);
    }
    return map;
  }, [blanks]);

  const indexedChanges = useMemo(() => {
    if (!inspect) return [];
    return buildIndexedChanges(draft, inspect, textMap, language);
  }, [draft, inspect, textMap, language]);

  const doneCount = useMemo(() => {
    const filledKeys = new Set<string>();
    for (const op of draft.ops) {
      if (op.kind === "fill_cell" && op.text.length > 0) {
        filledKeys.add(cellKey(op.table, op.row, op.col));
      }
    }
    return blanks.filter((b) => filledKeys.has(b.key)).length;
  }, [draft.ops, blanks]);

  const removalTargets = inspect?.summary?.removalTargets ?? [];
  const hasDeleteGuidesQueued = draft.ops.some((op) => op.kind === "delete_guides");

  const activeCellKey = useMemo(() => {
    if (inlineEdit?.kind === "cell") {
      return cellKey(inlineEdit.table, inlineEdit.row, inlineEdit.col);
    }
    return selectedKey;
  }, [inlineEdit, selectedKey]);

  const selectedBlank = useMemo(
    () => blanks.find((b) => b.key === activeCellKey) ?? null,
    [blanks, activeCellKey],
  );

  // Detect any newly pushed undo item so the Ruling J 1-click undo banner appears.
  useEffect(() => {
    if (redoStack.length > prevRedoLenRef.current) {
      setUndoDismissed(false);
    }
    prevRedoLenRef.current = redoStack.length;
  }, [redoStack.length]);

  // Keep inspector text input synced when changing blank selection or queue ops.
  useEffect(() => {
    if (!selectedBlank) {
      setInspectorValue("");
      setInspectorMultiline(false);
      return;
    }
    const queued = queuedCellOpAt(
      state,
      selectedBlank.table,
      selectedBlank.row,
      selectedBlank.col,
    );
    const nextVal = queued?.text ?? "";
    setInspectorValue(nextVal);
    setInspectorMultiline(
      Boolean(
        (inlineEdit?.kind === "cell" &&
          cellKey(inlineEdit.table, inlineEdit.row, inlineEdit.col) === selectedBlank.key &&
          inlineEdit.multiline) ||
          (queued?.kind === "fill_cell" && queued.lines !== undefined) ||
          nextVal.includes("\n"),
      ),
    );
  }, [selectedBlank?.key, draft.ops, inlineEdit, state]);

  // Reset static selection if document switches.
  useEffect(() => {
    setSelectedKey(null);
    setSelectedStatic(null);
  }, [sessionId]);

  const openBlankAt = useCallback((slot: BlankSlot, focusInPlace = true) => {
    setSelectedStatic(null);
    setSelectedKey(slot.key);
    if (focusInPlace) {
      beginEdit(slot.table, slot.row, slot.col);
    }
  }, []);

  const handleSelectBlankCell = useCallback(
    (table: number, row: number, col: number) => {
      const key = cellKey(table, row, col);
      setSelectedStatic(null);
      setSelectedKey(key);
      beginEdit(table, row, col);
    },
    [],
  );

  const handleSelectStaticCell = useCallback((cell: GraphCell, tableIdx: number) => {
    cancelEdit();
    setSelectedKey(cellKey(tableIdx, cell.addr.row, cell.addr.col));
    setSelectedStatic({ cell, table: tableIdx });
  }, []);

  const commitCellValue = useCallback(
    async (table: number, row: number, col: number, value: string, focusEmptyUndo = false) => {
      const hadQueued = Boolean(queuedCellOpAt(state, table, row, col));
      if (hadQueued && value === "") {
        setLastUndoReason(focusEmptyUndo ? "cleared" : "removed");
      }
      await commitEdit(value);
    },
    [state],
  );

  const handleCycleBlank = useCallback(
    async (
      table: number,
      row: number,
      col: number,
      direction: 1 | -1,
      currentValue: string,
    ) => {
      if (blanks.length === 0) return;
      const curKey = cellKey(table, row, col);
      const curIdx = blanks.findIndex((b) => b.key === curKey);
      await commitCellValue(table, row, col, currentValue, true);
      if (curIdx === -1) return;
      const nextIdx = (curIdx + direction + blanks.length) % blanks.length;
      const next = blanks[nextIdx];
      setSelectedStatic(null);
      setSelectedKey(next.key);
      beginEdit(next.table, next.row, next.col);
    },
    [blanks, commitCellValue],
  );

  const handleAdvanceAfterEnter = useCallback(
    async (table: number, row: number, col: number, committedValue: string) => {
      const curKey = cellKey(table, row, col);
      const curIdx = blanks.findIndex((b) => b.key === curKey);
      await commitCellValue(table, row, col, committedValue, true);
      if (curIdx >= 0 && curIdx + 1 < blanks.length) {
        const next = blanks[curIdx + 1];
        setSelectedStatic(null);
        setSelectedKey(next.key);
        beginEdit(next.table, next.row, next.col);
        return;
      }
      sheetAnchorRef.current?.focus();
    },
    [blanks, commitCellValue],
  );

  const handleEscapeBlank = useCallback(() => {
    cancelEdit();
    const el = sheetAnchorRef.current;
    if (el) {
      el.focus();
      requestAnimationFrame(() => el.focus());
    }
  }, []);

  const commitInspectorValue = useCallback(
    async (blank: BlankSlot, nextValue: string) => {
      const queued = queuedCellOpAt(state, blank.table, blank.row, blank.col);
      if (nextValue === "" && queued) {
        setLastUndoReason("cleared");
        await undoQueuedOp(queued.opId);
        return;
      }
      if (nextValue === "" && !queued) {
        return;
      }
      if (!beginEdit(blank.table, blank.row, blank.col, { multiline: inspectorMultiline })) {
        return;
      }
      await commitEdit(nextValue);
    },
    [state, inspectorMultiline],
  );

  const handleQueueDeleteGuides = async () => {
    if (!inspect || hasDeleteGuidesQueued || removalTargets.length === 0) return;
    const beforeSample = removalTargets
      .map(
        (target) =>
          inspect.graph.paragraphs.find((p) => p.para_idx === target.para_idx)?.text?.trim() ??
          "",
      )
      .filter(Boolean)
      .slice(0, 3)
      .join(" / ");
    await addQueueOp({
      opId: "op-delete-guides",
      kind: "delete_guides",
      text: "",
      before: beforeSample,
      origin: "user",
    });
  };

  const handleRemoveEntry = async (opId: string) => {
    setLastUndoReason("removed");
    await undoQueuedOp(opId);
  };

  const handleGoToReview = async () => {
    setNavigatingToReview(true);
    try {
      if (inlineEdit?.kind === "cell" && selectedBlank && inspectorValue !== inlineEdit.before) {
        await commitCellValue(inlineEdit.table, inlineEdit.row, inlineEdit.col, inspectorValue);
      } else if (inlineEdit) {
        cancelEdit();
      }
      if (draft.ops.length > 0 && (draft.phase !== "ready" || !draft.plan)) {
        await reproposeDraft();
      }
    } finally {
      setNavigatingToReview(false);
    }
    navigateScreen("review");
  };

  if (!session || !inspect) {
    return (
      <main className="fill-empty-view" data-testid="fill-view">
        <div className="fill-placeholder-card">
          <p className="fill-placeholder-text">{t("open_recent_hint", language)}</p>
          <button
            type="button"
            className="fill-btn fill-btn--primary"
            onClick={() => navigateScreen("open")}
          >
            {t("nav_open", language)}
          </button>
        </div>
      </main>
    );
  }

  const lastRedoOp = redoStack.length > 0 ? redoStack[redoStack.length - 1] : null;
  const lastRedoLabel = lastRedoOp
    ? lastRedoOp.kind === "fill_cell" || lastRedoOp.kind === "replace_at_cell"
      ? blankFieldLabels[cellKey(lastRedoOp.table, lastRedoOp.row, lastRedoOp.col)] ??
        lastRedoOp.before ??
        t("fill_title", language)
      : t("fill_delete_guides_btn", language)
    : "";

  const duplicateSlots = selectedBlank ? (duplicateGroups.get(selectedBlank.label) ?? []) : [];
  const selectedStaticText = selectedStatic
    ? seatText(
        inspect,
        texts,
        selectedStatic.table,
        selectedStatic.cell.addr.row,
        selectedStatic.cell.addr.col,
      )
    : "";
  const isLongValue = inspectorValue.length >= 40 || inspectorValue.includes("\n");
  const isEditingInPlace =
    inlineEdit?.kind === "cell" && selectedBlank !== null &&
    cellKey(inlineEdit.table, inlineEdit.row, inlineEdit.col) === selectedBlank.key;

  const entryList = indexedChanges.filter(
    (ch) =>
      ch.op.kind === "fill_cell" ||
      ch.op.kind === "replace_at_cell" ||
      ch.op.kind === "delete_guides",
  );

  return (
    <main className="fill-view" data-testid="fill-view">
      <section className="fill-left" aria-label={t("review_mobile_sheet_tab", language)}>
        <PageSheet
          mode="fill"
          sessionId={session.sessionId}
          inspect={inspect}
          texts={texts}
          textMap={textMap}
          changes={indexedChanges}
          rowAudits={EMPTY_AUDITS}
          selectedChangeId={null}
          selectedCellKey={activeCellKey}
          blankFieldLabels={blankFieldLabels}
          sheetAnchorRef={sheetAnchorRef}
          language={language}
          onSelectChange={() => {}}
          onSelectBlankCell={handleSelectBlankCell}
          onSelectStaticCell={handleSelectStaticCell}
          onCycleBlank={(tbl, r, c, dir, cur) => void handleCycleBlank(tbl, r, c, dir, cur)}
          onEscapeBlank={handleEscapeBlank}
          onAdvanceBlankAfterEnter={(tbl, r, c, cur) =>
            void handleAdvanceAfterEnter(tbl, r, c, cur)
          }
        />
      </section>

      <aside
        className="fill-right"
        data-testid="fill-right-pane"
        aria-label={t("fill_title", language)}
      >
        <div className="fill-header">
          <div className="fill-header-title-wrap">
            <h1 className="fill-title">{t("fill_title", language)}</h1>
            <p className="fill-counter" data-testid="fill-counter">
              {t("fill_counter", language, [doneCount, blanks.length])}
            </p>
          </div>

          <div className="fill-header-actions">
            {removalTargets.length > 0 ? (
              hasDeleteGuidesQueued ? (
                <span className="fill-guide-badge" data-testid="fill-delete-guides-queued">
                  {t("fill_delete_guides_queued", language, [removalTargets.length])}
                </span>
              ) : (
                <button
                  type="button"
                  className="fill-btn fill-btn--secondary"
                  data-testid="fill-delete-guides-btn"
                  onClick={() => void handleQueueDeleteGuides()}
                >
                  {t("fill_delete_guides_btn", language)}
                </button>
              )
            ) : null}

            <button
              type="button"
              className="fill-btn fill-btn--primary"
              data-testid="fill-to-review"
              disabled={navigatingToReview}
              onClick={() => void handleGoToReview()}
            >
              {navigatingToReview
                ? t("fill_reproposing", language)
                : t("fill_to_review", language)}
            </button>
          </div>
        </div>

        <div className="fill-scroll">
          {lastRedoOp && !undoDismissed ? (
            <div className="fill-undo-banner" role="status" data-testid="fill-undo-banner">
              <span>
                {t(
                  lastUndoReason === "cleared" ? "fill_undo_empty" : "fill_undo_removed",
                  language,
                  [lastRedoLabel],
                )}
              </span>
              <button
                type="button"
                className="fill-btn fill-btn--ghost fill-btn--small"
                data-testid="fill-undo-restore"
                onClick={() => {
                  setUndoDismissed(true);
                  void redoQueuedOp();
                }}
              >
                {t("fill_undo_restore", language)}
              </button>
            </div>
          ) : null}

          {selectedStatic ? (
            <section className="fill-card" data-testid="fill-active-card">
              <div className="fill-card-head">
                <h2 className="fill-card-title">
                  {deriveCellFieldLabel(
                    inspect,
                    textMap,
                    selectedStatic.table,
                    selectedStatic.cell.addr.row,
                    selectedStatic.cell.addr.col,
                    language,
                    1,
                  )}
                </h2>
                <DetailDisclosure
                  inline
                  testId="fill-cell-detail"
                  label={t("detail_label", language)}
                >
                  <dl className="change-detail-dl">
                    <dt>셀 주소</dt>
                    <dd>
                      {cellKey(
                        selectedStatic.table,
                        selectedStatic.cell.addr.row,
                        selectedStatic.cell.addr.col,
                      )}
                    </dd>
                    <dt>셀 분류</dt>
                    <dd>{selectedStatic.cell.classification}</dd>
                  </dl>
                </DetailDisclosure>
              </div>
              <p className="fill-static-notice" data-testid="fill-static-notice" role="status">
                {t("fill_static_notice", language)}
              </p>
              <p className="fill-hint">{t("fill_static_current_label", language)}</p>
              <div className="fill-static-preview">
                {selectedStaticText.trim() ? selectedStaticText : t("fill_previous_blank", language)}
              </div>
              <div className="fill-inspector-actions">
                <button
                  type="button"
                  className="fill-btn fill-btn--secondary"
                  data-testid="fill-static-replace-btn"
                  onClick={() =>
                    beginStaticCellEdit(
                      selectedStatic.table,
                      selectedStatic.cell.addr.row,
                      selectedStatic.cell.addr.col,
                    )
                  }
                >
                  {t("fill_static_replace", language)}
                </button>
              </div>
            </section>
          ) : selectedBlank ? (
            <section className="fill-card" data-testid="fill-active-card">
              <div className="fill-card-head">
                <h2 className="fill-card-title">{selectedBlank.label}</h2>
                <DetailDisclosure
                  inline
                  testId="fill-cell-detail"
                  label={t("detail_label", language)}
                >
                  <dl className="change-detail-dl">
                    <dt>셀 주소</dt>
                    <dd>{selectedBlank.key}</dd>
                    {seatAt(inspect, selectedBlank.table, selectedBlank.row, selectedBlank.col)
                      ?.charPrSuggested ? (
                      <>
                        <dt>권장 글자 모양</dt>
                        <dd>
                          {
                            seatAt(
                              inspect,
                              selectedBlank.table,
                              selectedBlank.row,
                              selectedBlank.col,
                            )?.charPrSuggested
                          }
                        </dd>
                      </>
                    ) : null}
                  </dl>
                </DetailDisclosure>
              </div>

              {duplicateSlots.length > 1 ? (
                <div
                  className="fill-ambiguous-warning"
                  data-testid="fill-ambiguous-warning"
                  role="alert"
                >
                  <span>
                    {t("fill_ambiguous_warning", language, [
                      selectedBlank.label,
                      duplicateSlots.length,
                    ])}
                  </span>
                  <div className="fill-ambiguous-slots">
                    {duplicateSlots.map((slot, slotIdx) => (
                      <button
                        key={slot.key}
                        type="button"
                        className={`fill-slot-pill${
                          slot.key === selectedBlank.key ? " fill-slot-pill--active" : ""
                        }`}
                        data-testid={`fill-ambiguous-slot-${slot.ordinal}`}
                        onClick={() => openBlankAt(slot, true)}
                      >
                        {t("fill_ambiguous_slot_option", language, [
                          slotIdx + 1,
                          language === "ko" ? `${slot.row + 1}번째 줄` : `Row ${slot.row + 1}`,
                        ])}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {selectedBlank.formBefore.trim() ? (
                <div className="fill-guide-caption">
                  {t("fill_guide_caption", language, [selectedBlank.formBefore])}
                </div>
              ) : null}

              {inspectorMultiline ? (
                <textarea
                  className="fill-inspector-input"
                  data-testid="fill-inspector-input"
                  rows={3}
                  value={inspectorValue}
                  placeholder={t("fill_field_placeholder", language)}
                  aria-label={selectedBlank.label}
                  onChange={(e) => setInspectorValue(e.target.value)}
                  onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => {
                    if (e.nativeEvent.isComposing) return;
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                      e.preventDefault();
                      void commitInspectorValue(selectedBlank, inspectorValue);
                    }
                  }}
                />
              ) : (
                <input
                  type="text"
                  className="fill-inspector-input"
                  data-testid="fill-inspector-input"
                  value={inspectorValue}
                  placeholder={t("fill_field_placeholder", language)}
                  aria-label={selectedBlank.label}
                  onChange={(e) => setInspectorValue(e.target.value)}
                  onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
                    if (e.nativeEvent.isComposing) return;
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void commitInspectorValue(selectedBlank, inspectorValue);
                    }
                  }}
                />
              )}

              {isLongValue ? (
                <p className="fill-long-notice" data-testid="fill-long-value-notice" role="status">
                  {t("fill_long_value", language)}
                </p>
              ) : null}

              <p className="fill-hint">
                {t(
                  inspectorMultiline ? "fill_multiline_hint" : "fill_singleline_hint",
                  language,
                )}{" "}
                {t("fill_escape_hint", language)}
              </p>

              <div className="fill-inspector-actions">
                <button
                  type="button"
                  className="fill-btn fill-btn--ghost fill-btn--small"
                  data-testid="fill-toggle-multiline"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    const nextMulti = !inspectorMultiline;
                    setInspectorMultiline(nextMulti);
                    if (isEditingInPlace) {
                      setInlineEditMultiline(nextMulti);
                    }
                  }}
                >
                  {t(
                    inspectorMultiline ? "fill_multiline_disable" : "fill_multiline_enable",
                    language,
                  )}
                </button>

                <div className="fill-header-actions">
                  {queuedCellOpAt(
                    state,
                    selectedBlank.table,
                    selectedBlank.row,
                    selectedBlank.col,
                  ) ? (
                    <button
                      type="button"
                      className="fill-btn fill-btn--secondary fill-btn--small"
                      data-testid="fill-clear-entry-btn"
                      onClick={() => void commitInspectorValue(selectedBlank, "")}
                    >
                      {t("fill_clear_value", language)}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="fill-btn fill-btn--primary fill-btn--small"
                    data-testid="fill-inspector-save"
                    onClick={() => void commitInspectorValue(selectedBlank, inspectorValue)}
                  >
                    {t("fill_save_entry", language)}
                  </button>
                </div>
              </div>
            </section>
          ) : (
            <section className="fill-card" data-testid="fill-active-card">
              <p className="fill-hint">
                {blanks.length > 0
                  ? t("fill_select_prompt", language)
                  : t("fill_empty_fields", language)}
              </p>
              {blanks.length > 0 ? (
                <div className="fill-chip-grid">
                  {blanks.map((slot) => {
                    const queued = queuedCellOpAt(state, slot.table, slot.row, slot.col);
                    return (
                      <button
                        key={slot.key}
                        type="button"
                        className={`fill-chip-btn${queued ? " fill-chip-btn--done" : ""}`}
                        data-testid={`fill-blank-chip-${slot.ordinal}`}
                        onClick={() => openBlankAt(slot, true)}
                      >
                        <span>{slot.label}</span>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </section>
          )}

          <section className="fill-entries-section" aria-label={t("fill_filled_list_header", language)}>
            <div className="fill-entries-head">
              <h2 className="fill-card-title">{t("fill_filled_list_header", language)}</h2>
              <span className="fill-hint">{entryList.length}</span>
            </div>

            {entryList.length === 0 ? (
              <p className="fill-hint" data-testid="fill-entries-empty">
                {t("fill_filled_list_empty", language)}
              </p>
            ) : (
              <ul className="fill-entries-list" data-testid="fill-entries-list">
                {entryList.map((entry) => {
                  const prevDisplay = entry.beforeText.trim()
                    ? entry.beforeText
                    : t("fill_previous_blank", language);
                  const op = entry.op;
                  const longEntry =
                    entry.afterText.length >= 40 || entry.afterText.includes("\n");
                  return (
                    <li
                      key={entry.opId}
                      className="fill-entry-row"
                      data-testid={`fill-entry-row-${entry.opId}`}
                    >
                      <div className="fill-entry-top">
                        <span className="fill-entry-label">{entry.fieldLabel}</span>
                        <span className="fill-entry-label">{entry.opKindText}</span>
                      </div>

                      {entry.afterText ? (
                        <div className="fill-entry-value">{entry.afterText}</div>
                      ) : null}

                      <p className="fill-entry-before" data-testid="fill-entry-before">
                        {t("fill_previous_form_text", language, [prevDisplay])}
                      </p>

                      {longEntry ? (
                        <p className="fill-long-notice">{t("fill_long_value", language)}</p>
                      ) : null}

                      <div className="fill-entry-actions">
                        {op.kind === "fill_cell" || op.kind === "replace_at_cell" ? (
                          <button
                            type="button"
                            className="fill-btn fill-btn--ghost fill-btn--small"
                            data-testid={`fill-edit-entry-${entry.opId}`}
                            onClick={() => {
                              setSelectedStatic(null);
                              setSelectedKey(cellKey(op.table, op.row, op.col));
                              if (op.kind === "replace_at_cell") {
                                beginStaticCellEdit(op.table, op.row, op.col);
                              } else {
                                beginEdit(op.table, op.row, op.col);
                              }
                            }}
                          >
                            {t("fill_edit_entry", language)}
                          </button>
                        ) : null}

                        <button
                          type="button"
                          className="fill-btn fill-btn--secondary fill-btn--small"
                          data-testid={`fill-remove-entry-${entry.opId}`}
                          onClick={() => void handleRemoveEntry(entry.opId)}
                        >
                          {t("review_remove_item", language)}
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      </aside>
    </main>
  );
}
