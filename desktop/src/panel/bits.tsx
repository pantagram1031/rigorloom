/**
 * Small pieces the panel draws. Keycap and the 결재란 box are WP1b
 * primitives (`ui/Keycap`, `ui/ApprovalBox`); until they land these local
 * versions use the same attributes, and the panel switches imports then.
 */
import { Fragment, type ReactNode } from "react";

import type { UiLanguage } from "../i18n/vocabulary";
import type { ChangeSource } from "../model/changes";
import { tp } from "./i18n";

export function Keycaps({ keys }: { keys: readonly string[] }) {
  if (keys.length === 0) return null;
  return (
    <span className="rp-keys" aria-hidden="true">
      {keys.map((k) => (
        <kbd key={k} className="rp-kbd">
          {k}
        </kbd>
      ))}
    </span>
  );
}

export function sourceLabel(source: ChangeSource, lang: UiLanguage): string {
  switch (source) {
    case "user":
      return tp("source_user", lang);
    case "test":
      return tp("source_test", lang);
    case "revert":
      return tp("source_revert", lang);
    default:
      return tp("source_agent", lang);
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

export interface GateBoxCells {
  propose: ReactNode;
  check: ReactNode;
  approve: ReactNode;
}

/**
 * The 결재란: three equal cells `제안 · 점검 · 승인`, a 20 px header and a
 * 36 px body, hairline rules, radius 0. No seal, no placeholder, no hover.
 */
export function GateBox({ cells, lang, testId }: { cells: GateBoxCells; lang: UiLanguage; testId?: string }) {
  return (
    <table className="rp-box" aria-label={tp("box_aria", lang)} data-testid={testId}>
      <thead>
        <tr>
          <th scope="col">{tp("box_propose", lang)}</th>
          <th scope="col">{tp("box_check", lang)}</th>
          <th scope="col">{tp("box_approve", lang)}</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td data-cell="propose">{cells.propose}</td>
          <td data-cell="check">{cells.check}</td>
          <td data-cell="approve">{cells.approve}</td>
        </tr>
      </tbody>
    </table>
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
