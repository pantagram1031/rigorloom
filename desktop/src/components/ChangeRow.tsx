import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import {
  declareSuggestedCharPr,
  editOpValue,
  undoQueuedOp,
} from "../actions";
import {
  checkStateLabel,
  errorCodeMessage,
  guardCategoryLabel,
  planStateLabel,
  t,
} from "../i18n/vocabulary";
import type { PlanFinding, UiLanguage } from "../types";
import type { IndexedChange, RowGuardAudit } from "../workspace/guardHelper";
import { DetailDisclosure } from "./DetailDisclosure";

function collapseOneLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function findSuggestedCharPr(
  findings: readonly PlanFinding[],
): string | number | null {
  for (const f of findings) {
    if (
      typeof f.charPrSuggested === "string" ||
      typeof f.charPrSuggested === "number"
    ) {
      return f.charPrSuggested;
    }
  }
  return null;
}

interface ChangeRowProps {
  change: IndexedChange;
  audit: RowGuardAudit;
  isSelected: boolean;
  isGroupHighlighted?: boolean;
  isExpanded: boolean;
  focusEditNonce: number;
  disabled?: boolean;
  language: UiLanguage;
  onSelect: (opId: string) => void;
  onToggleExpand: (opId: string) => void;
}

export function ChangeRow({
  change,
  audit,
  isSelected,
  isGroupHighlighted = false,
  isExpanded,
  focusEditNonce,
  disabled = false,
  language,
  onSelect,
  onToggleExpand,
}: ChangeRowProps) {
  const { op } = change;
  const isEditableValue = op.kind !== "delete_guides";

  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState(change.afterText);
  const isComposingRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!editing) {
      setEditDraft(change.afterText);
    }
  }, [change.afterText, editing]);

  useEffect(() => {
    if (isExpanded && isEditableValue && focusEditNonce > 0 && isSelected) {
      setEditing(true);
      setEditDraft(change.afterText);
      const id = window.setTimeout(() => {
        textareaRef.current?.focus();
      }, 0);
      return () => window.clearTimeout(id);
    }
  }, [focusEditNonce, isExpanded, isEditableValue, isSelected, change.afterText]);

  const commitInlineEdit = async () => {
    setEditing(false);
    if (editDraft !== change.afterText) {
      await editOpValue(change.opId, editDraft);
    }
  };

  const handleTextareaKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229 || isComposingRef.current) {
      return;
    }
    e.stopPropagation();
    if (e.key === "Escape") {
      e.preventDefault();
      setEditDraft(change.afterText);
      setEditing(false);
      return;
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey || op.kind !== "fill_cell")) {
      if (!e.shiftKey) {
        e.preventDefault();
        void commitInlineEdit();
      }
    }
  };

  const beforeSingle = collapseOneLine(change.beforeText);
  const afterSingle = collapseOneLine(change.afterText);
  const previewText =
    change.previewMode === "before_only"
      ? beforeSingle
      : change.previewMode === "after_only"
        ? afterSingle
        : beforeSingle.length > 0
          ? `${beforeSingle} → ${afterSingle}`
          : afterSingle;

  const showAddedNumbers = change.isAuditable && audit.addedNumbers.length > 0;
  const visibleAddedNumbers = showAddedNumbers
    ? audit.addedNumbers.slice(0, 3)
    : [];
  const extraAddedNumbers = showAddedNumbers
    ? Math.max(0, audit.addedNumbers.length - visibleAddedNumbers.length)
    : 0;
  const addedNumbersLabel = showAddedNumbers
    ? `${t("guard_added_numbers", language)} ${visibleAddedNumbers.join(", ")}${
        extraAddedNumbers > 0
          ? ` ${t("guard_added_numbers_more", language, [extraAddedNumbers])}`
          : ""
      }`
    : null;

  const allFindings = [...change.hardFindings, ...change.warnFindings];
  const suggestedCharPr = findSuggestedCharPr(allFindings);
  const canFixCharPr =
    (op.kind === "fill_cell" || op.kind === "replace_at_cell") &&
    !op.charPr &&
    suggestedCharPr !== null;

  const pill =
    audit.status === "needs_fixes"
      ? {
          cls: "change-pill change-pill--needs-fixes",
          text: planStateLabel("invalid", language),
        }
      : audit.status === "changed"
        ? {
            cls: "change-pill change-pill--changed",
            text: t("guard_pill_changed", language),
          }
        : audit.status === "kept"
          ? {
              cls: "change-pill change-pill--kept",
              text: t("guard_pill_kept", language),
            }
          : audit.status === "not_checked"
            ? {
                cls: "change-pill change-pill--not-checked",
                text: checkStateLabel("not_run", language),
              }
            : null;

  const rowClasses = [
    "change-row",
    isSelected ? "change-row--selected" : "",
    isGroupHighlighted ? "change-row--group-peer" : "",
    isExpanded ? "change-row--expanded" : "change-row--collapsed",
    audit.status === "changed"
      ? "change-row--changed"
      : audit.status === "needs_fixes"
        ? "change-row--needs-fixes"
        : audit.status === "kept"
          ? "change-row--kept"
          : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <li
      className={rowClasses}
      data-testid={`change-row-${change.ordinal}`}
      data-op-id={change.opId}
      aria-selected={isSelected}
    >
      <button
        type="button"
        className="change-row-summary"
        data-testid={`change-summary-${change.ordinal}`}
        aria-expanded={isExpanded}
        onClick={() => {
          onSelect(change.opId);
          onToggleExpand(change.opId);
        }}
      >
        <div className="change-row-line1">
          <span
            className="change-row-ordinal"
            data-testid={`change-ordinal-${change.ordinal}`}
          >
            [{change.ordinal}]
          </span>
          <span className="change-row-field">{change.fieldLabel}</span>
          <span className="change-row-kind">{change.opKindText}</span>
          {pill ? (
            <span
              className={pill.cls}
              data-testid={`change-pill-${change.ordinal}`}
            >
              {pill.text}
            </span>
          ) : null}
        </div>

        <div className="change-row-line2">
          {change.previewMode === "before_only" ? (
            <del
              className="change-row-preview change-row-before-only"
              data-testid={`change-before-only-${change.ordinal}`}
            >
              {previewText}
            </del>
          ) : (
            <span className="change-row-preview">{previewText}</span>
          )}
          {change.previewMode === "after_only" &&
          isSelected &&
          !isExpanded &&
          beforeSingle.length > 0 ? (
            <span
              className="change-row-before-inline"
              data-testid={`change-before-inline-${change.ordinal}`}
            >
              {t("review_before_label", language, [beforeSingle])}
            </span>
          ) : null}
          {addedNumbersLabel ? (
            <span
              className="change-row-added-numbers"
              data-testid={`change-added-numbers-${change.ordinal}`}
            >
              {addedNumbersLabel}
            </span>
          ) : null}
        </div>
      </button>

      {isExpanded ? (
        <div
          className="change-row-detail"
          data-testid={`change-detail-${change.ordinal}`}
        >
          <div className="change-expanded-diff">
            {change.beforeText.trim().length > 0 ? (
              <p className="change-expanded-before">
                {t("review_before_label", language, [change.beforeText])}
              </p>
            ) : null}
            {change.previewMode !== "before_only" || change.afterText.trim().length > 0 ? (
              <p className="change-expanded-after">
                {t("review_after_label", language, [change.afterText])}
              </p>
            ) : null}
            {op.origin === "agent" ? (
              <p className="change-origin-note">
                {t("review_agent_suggestion", language)}
              </p>
            ) : null}
          </div>

          {allFindings.length > 0 ? (
            <ul className="change-findings-list">
              {allFindings.map((finding, idx) => (
                <li
                  key={`${finding.code}-${idx}`}
                  className="change-finding-item"
                >
                  {errorCodeMessage(finding.code, language)}
                </li>
              ))}
            </ul>
          ) : null}

          {canFixCharPr ? (
            <div className="change-fix-bar">
              <button
                type="button"
                className="review-btn review-btn--secondary"
                data-testid={`change-fix-charpr-${change.opId}`}
                disabled={disabled}
                onClick={() => void declareSuggestedCharPr(change.opId)}
              >
                {t("review_suggest_body_style", language)}
              </button>
            </div>
          ) : null}

          {audit.paragraph && audit.paragraph.kinds.length > 0 ? (
            <p className="change-guard-categories">
              {audit.paragraph.kinds
                .map((k) => guardCategoryLabel(k, language))
                .join(", ")}
            </p>
          ) : null}

          {!change.invertible && change.nonInvertibleReason ? (
            <p className="change-noninvertible-note">{change.nonInvertibleReason}</p>
          ) : null}

          {editing && isEditableValue ? (
            <div className="change-inline-editor">
              <textarea
                ref={textareaRef}
                className="change-inline-textarea"
                data-testid={`change-edit-input-${change.opId}`}
                value={editDraft}
                rows={Math.min(5, Math.max(2, editDraft.split("\n").length))}
                disabled={disabled}
                aria-label={t("review_direct_edit", language)}
                onCompositionStart={() => {
                  isComposingRef.current = true;
                }}
                onCompositionEnd={(e) => {
                  isComposingRef.current = false;
                  setEditDraft(e.currentTarget.value);
                }}
                onChange={(e) => setEditDraft(e.target.value)}
                onKeyDown={handleTextareaKeyDown}
              />
              <div className="change-inline-editor-actions">
                <button
                  type="button"
                  className="review-btn review-btn--primary"
                  data-testid={`change-edit-save-${change.opId}`}
                  disabled={disabled}
                  onClick={() => void commitInlineEdit()}
                >
                  {t("review_save_edit", language)}
                </button>
                <button
                  type="button"
                  className="review-btn review-btn--secondary"
                  disabled={disabled}
                  onClick={() => {
                    setEditDraft(change.afterText);
                    setEditing(false);
                  }}
                >
                  {t("review_cancel", language)}
                </button>
              </div>
            </div>
          ) : null}

          <div className="change-expanded-actions">
            {isEditableValue && !editing ? (
              <button
                type="button"
                className="review-btn review-btn--secondary"
                data-testid={`change-edit-btn-${change.opId}`}
                disabled={disabled}
                onClick={() => {
                  setEditDraft(change.afterText);
                  setEditing(true);
                  window.setTimeout(() => textareaRef.current?.focus(), 0);
                }}
              >
                {t("review_direct_edit", language)}
              </button>
            ) : null}

            <button
              type="button"
              className="review-btn review-btn--danger"
              data-testid={`change-remove-${change.opId}`}
              disabled={disabled}
              onClick={() => void undoQueuedOp(change.opId)}
            >
              {t("review_remove_item", language)}
            </button>

            <button
              type="button"
              className="review-btn review-btn--ghost"
              onClick={() => onToggleExpand(change.opId)}
            >
              {t("review_collapse", language)}
            </button>
          </div>

          <DetailDisclosure testId={`change-details-${change.ordinal}`}>
            <div className="change-tech-meta">
              <div>{`opId: ${change.opId} · kind: ${op.kind}`}</div>
              {op.kind === "fill_cell" || op.kind === "replace_at_cell" ? (
                <div>
                  {`table=${op.table}, row=${op.row}, col=${op.col}${
                    op.kind === "replace_at_cell" && op.run !== undefined
                      ? `, run=${op.run}`
                      : ""
                  }${op.charPr !== undefined ? `, charPr=${op.charPr}` : ""}`}
                </div>
              ) : op.kind === "set_run" ? (
                <div>{`atPara=${op.atPara}, run=${op.run}`}</div>
              ) : (
                <div>
                  {`color=${op.color ?? "none"}, charPrIds=${
                    op.charPrIds?.join(",") ?? "none"
                  }`}
                </div>
              )}
              {allFindings.map((f, idx) => (
                <div key={`raw-${idx}`}>
                  {`${f.code} @ ${f.at}: ${f.msg}`}
                </div>
              ))}
              {audit.paragraph ? (
                <div>
                  {`guard: paragraph=${audit.paragraph.paragraph}, pass=${String(
                    audit.paragraph.pass,
                  )}, kinds=[${audit.paragraph.kinds.join(", ")}], changes=[${audit.paragraph.changes.join(", ")}]`}
                </div>
              ) : null}
            </div>
          </DetailDisclosure>
        </div>
      ) : null}
    </li>
  );
}
