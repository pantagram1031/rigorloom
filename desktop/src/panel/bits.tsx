/**
 * Small pieces the panel draws. Keycaps and the 결재란 box come from WP1b's
 * primitives (`ui/Keycap`, `ui/ApprovalBox`).
 */
import { Fragment } from "react";

import type { UiLanguage } from "../i18n/vocabulary";
import type { ChangeSource } from "../model/changes";
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

/** `바뀐 사실 0 · 확인 3`, wrapping only between the parts. */
export function Parts({ text }: { text: string }) {
  const parts = text.split(" \u00b7 ");
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          <span className="rp-part">
            {part}
            {i < parts.length - 1 ? " \u00b7" : null}
          </span>
          {i < parts.length - 1 ? " " : null}
        </Fragment>
      ))}
    </>
  );
}
