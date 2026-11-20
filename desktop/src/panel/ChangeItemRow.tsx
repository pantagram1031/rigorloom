import { memo, useEffect, useRef, useState, type KeyboardEvent } from "react";

import { editOpValue } from "../actions";
import type { UiLanguage } from "../i18n/vocabulary";
import { hasNewValues, isChangedFact, needsLook, type ChangeItem } from "../model/changes";
import { decide, select } from "./actions";
import { Keycaps, SourceText } from "./bits";
import { tp } from "./i18n";
import { eventIsComposing } from "./keys";

/** The hue a change's margin bar and number take: the page's own rule. */
export function stateHue(item: ChangeItem): "fact" | "attn" | "pending" | "decided" | "test" {
  if (isChangedFact(item)) return "fact";
  if (item.hard.length > 0 || needsLook(item)) return "attn";
  if (item.decision !== "pending") return "decided";
  if (item.source === "test") return "test";
  return "pending";
}

function DiffLine({ item, lang }: { item: ChangeItem; lang: UiLanguage }) {
  if (item.hard.length > 0) {
    return <span className="rp-row-reason">{item.hard[0]}</span>;
  }
  if (item.kind === "delete") {
    return <del className="rp-row-del">{item.before || tp("row_removed_value", lang)}</del>;
  }
  return <span className="rp-row-after">{item.after}</span>;
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
      const id = (e as CustomEvent<{ itemId: string; handled?: boolean }>).detail?.itemId;
      if (id !== item.id || (e as CustomEvent<{ handled?: boolean }>).detail?.handled) return;
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
    if (eventIsComposing(e)) return;
    e.stopPropagation();
    if (e.key === "Escape") {
      e.preventDefault();
      setEditing(false);
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void commit();
    }
  };

  const stateText =
    item.decision === "accepted" ? tp("decision_accepted", lang) : item.decision === "rejected" ? tp("decision_rejected", lang) : null;

  return (
    <li
      ref={rowRef}
      className="rp-row"
      data-testid={`change-row-${item.n}`}
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
          <span className="rp-row-n">{item.n}</span>
          <span className="rp-row-label">{item.label}</span>
          <span className="rp-row-meta">
            <span className="rp-sep">·</span>
            {item.opName}
            <span className="rp-sep">·</span>
            <SourceText source={item.source} lang={lang} />
          </span>
          <span className="rp-row-right">
            {isChangedFact(item) ? (
              <span className="rp-tag rp-tag--fact" data-fact="">
                {tp("tag_fact", lang)}
              </span>
            ) : null}
            {item.hard.length > 0 ? <span className="rp-tag rp-tag--attn">{tp("tag_hard", lang)}</span> : null}
            {needsLook(item) && item.guard.status === "expected" ? <span className="rp-tag">{tp("tag_attn", lang)}</span> : null}
            {hasNewValues(item) ? <span className="rp-tag">{tp("tag_new_values", lang)}</span> : null}
            {item.guard.status === "not_checked" ? <span className="rp-tag">{tp("tag_not_checked", lang)}</span> : null}
            {stateText ? <span className="rp-row-state">{stateText}</span> : null}
          </span>
        </span>
        {!selected ? (
          <span className="rp-row-line2">
            <DiffLine item={item} lang={lang} />
          </span>
        ) : null}
      </button>
      {selected ? (
        <div className="rp-row-body">
          <dl className="rp-diff">
            <div className="rp-diff-line">
              <dt>{tp("row_before", lang)}</dt>
              <dd>{item.before.trim() ? item.before : <span className="rp-dim">{tp("row_empty_value", lang)}</span>}</dd>
            </div>
            <div className="rp-diff-line">
              <dt>{tp("row_after", lang)}</dt>
              <dd>
                {editing ? (
                  <textarea
                    ref={inputRef}
                    className="rp-edit"
                    value={value}
                    rows={Math.min(6, Math.max(1, value.split("\n").length))}
                    onChange={(e) => setValue(e.target.value)}
                    onKeyDown={onEditKey}
                    onBlur={() => void commit()}
                    aria-label={tp("row_after", lang)}
                    data-testid="change-edit-input"
                  />
                ) : item.kind === "delete" ? (
                  <span className="rp-dim">{tp("row_removed_value", lang)}</span>
                ) : (
                  item.after
                )}
              </dd>
            </div>
          </dl>
          {item.hard.length > 0 ? <p className="rp-row-reason rp-row-reason--full">{item.hard.join(" ")}</p> : null}
          <div className="rp-row-actions">
            {item.decision === "rejected" ? (
              <button type="button" className="rp-btn" disabled={locked} onClick={() => decide(item.id, "pending")} data-testid="act-add-back">
                {tp("act_add_back", lang)}
                <Keycaps keys={["U"]} />
              </button>
            ) : (
              <>
                {item.decision !== "accepted" ? (
                  <button type="button" className="rp-btn" disabled={locked} onClick={() => decide(item.id, "accepted")} data-testid="act-accept">
                    {tp("act_accept", lang)}
                    <Keycaps keys={["Y"]} />
                  </button>
                ) : null}
                <button type="button" className="rp-btn" disabled={locked} onClick={() => decide(item.id, "rejected")} data-testid="act-reject">
                  {tp("act_reject", lang)}
                  <Keycaps keys={["N"]} />
                </button>
                <button
                  type="button"
                  className="rp-btn"
                  disabled={locked || item.kind === "delete"}
                  onClick={() => requestEdit(item.id)}
                  data-testid="act-edit"
                >
                  {tp("act_edit", lang)}
                  <Keycaps keys={["E"]} />
                </button>
                {item.decision === "accepted" ? (
                  <button type="button" className="rp-btn rp-btn--quiet" disabled={locked} onClick={() => decide(item.id, "pending")}>
                    {tp("act_undo", lang)}
                    <Keycaps keys={["U"]} />
                  </button>
                ) : null}
              </>
            )}
          </div>
        </div>
      ) : null}
    </li>
  );
}

export const ChangeItemRow = memo(RowImpl);

/**
 * `E`: the page's in-place editor takes it when the canvas is mounted (WP3);
 * otherwise the selected row edits the value itself.
 */
export function requestEdit(itemId: string): void {
  const detail: { itemId: string; handled: boolean } = { itemId, handled: false };
  window.dispatchEvent(new CustomEvent("rigorloom:edit-change", { detail }));
  if (!detail.handled) window.dispatchEvent(new CustomEvent("rigorloom:edit-change-fallback", { detail }));
}
