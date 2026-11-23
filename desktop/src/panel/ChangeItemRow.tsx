import { memo, useEffect, useRef, useState, type KeyboardEvent } from "react";

import { beginCellEditV2 } from "../canvas/actions";
import { getPublishedChanges } from "../canvas/controller";
import { keymapChord } from "../shell/keymap";
import { isComposingEvent } from "../shell/keys";
import { changeRowTid } from "../shell/testids";
import { editOpValue } from "../actions";
import type { UiLanguage } from "../i18n/vocabulary";
import { hasNewValues, isChangedFact, needsLook, type ChangeItem } from "../model/changes";
import { buttonTitle } from "../ui/Button";
import { decide, select } from "./actions";
import { SourceText } from "./bits";
import { tp } from "./i18n";

/** The hue a change's margin bar and number take: the page's own rule. */
export function stateHue(item: ChangeItem): "fact" | "attn" | "pending" | "decided" | "test" {
  if (isChangedFact(item)) return "fact";
  if (item.hard.length > 0 || needsLook(item)) return "attn";
  if (item.decision !== "pending") return "decided";
  if (item.source === "test") return "test";
  return "pending";
}

interface RowProps {
  item: ChangeItem;
  selected: boolean;
  lang: UiLanguage;
  locked: boolean;
}

function RowImpl({ item, selected, lang, locked }: RowProps) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(item.after);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const rowRef = useRef<HTMLLIElement | null>(null);
  const hue = stateHue(item);

  useEffect(() => {
    if (!selected) setEditing(false);
    else rowRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [selected]);

  useEffect(() => {
    const onEdit = (e: Event) => {
      if ((e as CustomEvent<{ itemId: string }>).detail.itemId !== item.id) return;
      setValue(item.after);
      setEditing(true);
      setTimeout(() => inputRef.current?.focus(), 0);
    };
    window.addEventListener("rigorloom:edit-change-fallback", onEdit);
    return () => window.removeEventListener("rigorloom:edit-change-fallback", onEdit);
  }, [item.id, item.after]);

  const commit = async () => {
    setEditing(false);
    if (value !== item.after) await editOpValue(item.id, value);
  };

  const onEditKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (isComposingEvent(e.nativeEvent)) return;
    if (e.key === "Escape") {
      e.stopPropagation();
      e.preventDefault();
      setEditing(false);
    } else if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
      e.stopPropagation();
      e.preventDefault();
      void commit();
    }
  };

  const stateText =
    item.decision === "accepted" ? tp("wp4_decision_accepted", lang) : item.decision === "rejected" ? tp("wp4_decision_rejected", lang) : null;

  return (
    <li
      ref={rowRef}
      className="rp-row"
      data-testid={changeRowTid(item.n)}
      data-item-id={item.id}
      data-decision={item.decision}
      data-hue={hue}
      data-locked={locked || undefined}
      aria-selected={selected}
      {...(isChangedFact(item) ? { "data-fact": "" } : {})}
      {...(item.source === "agent" && item.decision === "pending" ? { "data-source": "agent" } : {})}
    >
      <button type="button" className="rp-row-head" onClick={() => select(item.id)} data-testid={`change-summary-${item.n}`}>
        <span className="rp-row-line1">
          <span className="rp-row-n">{String(item.n).padStart(2, "0")}</span>
          <span className="rp-row-label">{item.label}</span>
          <span className="rp-row-meta">
            <span className="rp-sep">·</span>
            {item.opName}
            {item.source !== "agent" ? (
              <>
                <span className="rp-sep">·</span>
                <SourceText source={item.source} lang={lang} />
              </>
            ) : null}
          </span>
          <span className="rp-row-right">
            {isChangedFact(item) ? (
              <span className="rp-tag rp-tag--fact" data-fact="">
                {tp("wp4_tag_fact", lang)}
              </span>
            ) : null}
            {item.hard.length > 0 ? <span className="rp-tag rp-tag--attn">{tp("wp4_tag_hard", lang)}</span> : null}
            {needsLook(item) && item.guard.status === "expected" ? <span className="rp-tag">{tp("wp4_tag_attn", lang)}</span> : null}
            {hasNewValues(item) ? <span className="rp-tag">{tp("wp4_tag_new_values", lang)}</span> : null}
            {item.guard.status === "not_checked" ? <span className="rp-tag">{tp("wp4_tag_not_checked", lang)}</span> : null}
            {stateText ? <span className="rp-row-state">{stateText}</span> : null}
          </span>
        </span>
      </button>
      <div className="rp-row-body">
        <table className="rp-diff" aria-label={item.label}>
          <tbody>
            <tr className="rp-diff-line rp-diff-line--before">
              <th scope="row">
                <span aria-hidden="true">−</span>
                <span className="rp-diff-label">{tp("wp4_row_before", lang)}</span>
              </th>
              <td>{item.before.trim() ? item.before : <span className="rp-dim">{tp("wp4_row_empty_value", lang)}</span>}</td>
            </tr>
            <tr className="rp-diff-line rp-diff-line--after">
              <th scope="row">
                <span aria-hidden="true">+</span>
                <span className="rp-diff-label">{tp("wp4_row_after", lang)}</span>
              </th>
              <td>
                {editing ? (
                  <textarea
                    ref={inputRef}
                    className="rp-edit"
                    value={value}
                    rows={Math.min(6, Math.max(1, value.split("\n").length))}
                    onChange={(e) => setValue(e.target.value)}
                    onKeyDown={onEditKey}
                    onBlur={() => void commit()}
                    aria-label={tp("wp4_row_after", lang)}
                    data-testid="change-edit-input" title="Enter · Esc"
                  />
                ) : item.kind === "delete" ? (
                  <span className="rp-dim">{tp("wp4_row_removed_value", lang)}</span>
                ) : (
                  item.after
                )}
              </td>
            </tr>
          </tbody>
        </table>
        {selected && item.hard.length > 0 ? <p className="rp-row-reason rp-row-reason--full">{item.hard.join(" ")}</p> : null}
        <div className="rp-row-actions">
          {item.decision === "rejected" ? (
            <button
              type="button"
              className="rp-btn"
              disabled={locked}
              onClick={() => decide(item.id, "pending")}
              data-testid="act-add-back"
              title={buttonTitle(tp("wp4_act_add_back", lang), keymapChord("change.undo"))}
            >
              {tp("wp4_act_add_back", lang)}
            </button>
          ) : (
            <>
              {item.decision !== "accepted" ? (
                <button
                  type="button"
                  className="rp-btn"
                  disabled={locked}
                  onClick={() => decide(item.id, "accepted")}
                  data-testid="act-accept"
                  title={buttonTitle(tp("wp4_act_accept", lang), keymapChord("change.accept"))}
                >
                  {tp("wp4_act_accept", lang)}
                </button>
              ) : null}
              <button
                type="button"
                className="rp-btn"
                disabled={locked}
                onClick={() => decide(item.id, "rejected")}
                data-testid="act-reject"
                title={buttonTitle(tp("wp4_act_reject", lang), keymapChord("change.reject"))}
              >
                {tp("wp4_act_reject", lang)}
              </button>
              <button
                type="button"
                className="rp-btn"
                disabled={locked || item.kind === "delete"}
                onClick={() => {
                  if (!selected) select(item.id);
                  requestEdit(item.id);
                }}
                data-testid="act-edit"
                title={buttonTitle(tp("wp4_act_edit", lang), keymapChord("change.edit"))}
              >
                {tp("wp4_act_edit", lang)}
              </button>
              {item.decision === "accepted" ? (
                <button
                  type="button"
                  className="rp-btn rp-btn--quiet"
                  disabled={locked}
                  onClick={() => decide(item.id, "pending")}
                  title={buttonTitle(tp("wp4_act_undo", lang), keymapChord("change.undo"))}
                >
                  {tp("wp4_act_undo", lang)}
                </button>
              ) : null}
            </>
          )}
        </div>
      </div>
    </li>
  );
}

export const ChangeItemRow = memo(RowImpl);

/**
 * `E`: the page's in-place editor takes it when the canvas is mounted (WP3);
 * otherwise the selected row edits the value itself.
 */
export function requestEdit(itemId: string): void {
  const item = getPublishedChanges().find((change) => change.id === itemId);
  const cell = item?.cellKey?.match(/^c:(\d+):(\d+):(\d+)$/);
  if (cell && item?.run === undefined && beginCellEditV2(Number(cell[1]), Number(cell[2]), Number(cell[3]))) return;
  window.dispatchEvent(new CustomEvent("rigorloom:edit-change-fallback", { detail: { itemId } }));
}
