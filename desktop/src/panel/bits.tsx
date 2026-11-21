/**
 * Small pieces the review panel draws.
 */
import { Fragment, useLayoutEffect, useRef } from "react";

import type { UiLanguage } from "../i18n/vocabulary";
import { shortHash, type ChangeSource, type SourceTally } from "../model/changes";
import { tp } from "./i18n";

export function sourceLabel(source: ChangeSource, lang: UiLanguage): string {
  switch (source) {
    case "user":
      return tp("wp4_source_user", lang);
    case "test":
      return tp("wp4_source_test", lang);
    case "revert":
      return tp("wp4_source_revert", lang);
    default:
      return tp("wp4_source_agent", lang);
  }
}

const SOURCE_ORDER: readonly ChangeSource[] = ["user", "agent", "test", "revert"];

export function proposerLine(tally: SourceTally, lang: UiLanguage): string {
  const present = SOURCE_ORDER.filter((source) => tally[source]);
  const key = present.length > 1 ? "wp4_box_propose_part" : "wp4_box_propose_body";
  const sources = present.length ? present : ["agent" as const];
  return sources.map((source) => tp(key, lang, [sourceLabel(source, lang), tally[source] ?? 0])).join(" · ");
}

export function PlanHash({ value, lang, testId }: { value: string; lang: UiLanguage; testId: string }) {
  return (
    <div className="rp-kv">
      <span className="rp-kv-k">{tp("wp4_sheet_plan_hash", lang)}</span>
      <code className="rp-mono" title={value} data-testid={testId}>{shortHash(value)}</code>
    </div>
  );
}

/** The source as text, never colour alone. 시험용 carries the amber tag. */
export function SourceText({ source, lang }: { source: ChangeSource; lang: UiLanguage }) {
  if (source === "test") {
    return (
      <span className="rp-tag rp-tag--test" data-source="test">
        {sourceLabel(source, lang)}
      </span>
    );
  }
  return (
    <span className="rp-source" data-source={source}>
      {sourceLabel(source, lang)}
    </span>
  );
}

/**
 * `바뀐 사실 0 · 확인 3`, wrapping only between the parts. One wrapper span,
 * so a flex cell (the 결재란 body) keeps the spaces between the parts. When a
 * narrow cell wraps the parts onto two lines, the separator at the end of a
 * line is faded out (it keeps its width, so the wrap does not flip
 * back, and it stays in the text, so copy and screen readers read one line).
 */
export function Parts({ text }: { text: string }) {
  const parts = text.split(" \u00b7 ");
  const ref = useRef<HTMLSpanElement | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || parts.length < 2) return;
    const measure = () => {
      const items = el.querySelectorAll<HTMLElement>(".rp-part");
      items.forEach((item, index) => {
        item.toggleAttribute("data-line-end", index + 1 < items.length && items[index + 1].offsetTop > item.offsetTop);
      });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el.parentElement ?? el);
    return () => ro.disconnect();
  }, [text, parts.length]);
  return (
    <span className="rp-parts" ref={ref}>
      {parts.map((part, i) => (
        <Fragment key={i}>
          <span className="rp-part">
            {part}
            {i < parts.length - 1 ? <span className="rp-part-sep">{" \u00b7"}</span> : null}
          </span>
          {i < parts.length - 1 ? " " : null}
        </Fragment>
      ))}
    </span>
  );
}
