/**
 * 기록 pane, the integration's minimal version: one line per 수정본, newest
 * first, with the 결재란 line for the approval this session made, down to 원본.
 *
 * WP5 owns history (timeline, compare, 되돌리기 제안, export popover). This
 * registers at a late order, so WP5's `pane:history` replaces it when it lands.
 */
import { useMemo } from "react";

import { E } from "../i18n/v2/editor";
import { Parts, proposerLine } from "../panel/bits";
import { clockTime, tp } from "../panel/i18n";
import { panelSlice } from "../panel/state";
import { headCandidate, useWorkspace } from "../store";
import { ApprovalBox } from "../ui/ApprovalBox";
import { formatAppDateTime } from "../workspace/dates";
import "./editor.css";

export function HistoryPane({ sessionId }: { sessionId: string | null }) {
  const lang = useWorkspace((s) => s.language);
  const rows = useWorkspace((s) => (sessionId ? s.candidates[sessionId] : undefined));
  const head = useWorkspace(headCandidate);
  const applied = panelSlice.use(sessionId, (s) => s.applied);

  const revisions = useMemo(
    () =>
      (rows ?? [])
        .filter((c) => Boolean(c.runId))
        .slice()
        .sort((a, b) => (a.createdUtc ?? "").localeCompare(b.createdUtc ?? ""))
        .map((c, i) => ({ c, n: i + 1 }))
        .reverse(),
    [rows],
  );

  if (!sessionId) return null;

  return (
    <section className="ed-history" aria-label={E.t("editor_history_aria", lang)} data-testid="history-pane">
      {revisions.length === 0 ? (
        <p className="ed-history-none" data-testid="history-none">
          {E.t("editor_history_none", lang)}
        </p>
      ) : null}
      <ol className="ed-history-list">
        {revisions.map(({ c, n }) => {
          const isHead = head?.runId === c.runId;
          const box = applied && applied.runId === c.runId ? applied : null;
          const count = Array.isArray(c.opKinds) ? c.opKinds.length : null;
          return (
            <li key={c.runId} className="ed-history-row" data-testid={`history-row-${n}`} aria-current={isHead ? "true" : undefined}>
              <div className="ed-history-line">
                <span className="ed-history-name">{E.t("editor_history_revision", lang, [n])}</span>
                {isHead ? <span className="ed-history-tag">{E.t("editor_history_current", lang)}</span> : null}
                {c.reverses ? <span className="ed-history-tag">{E.t("editor_history_revert", lang)}</span> : null}
              </div>
              <div className="ed-history-meta">
                {formatAppDateTime(c.createdUtc, lang)}
                {count !== null && !box ? ` · ${E.t("editor_history_ops", lang, [count])}` : null}
              </div>
              {box ? (
                <ApprovalBox
                  compact
                  lang={lang}
                  data-testid={`history-box-${n}`}
                  hasChangedFact={box.checked && box.facts > 0}
                  propose={<Parts text={proposerLine(box.sources, lang)} />}
                  check={box.checked ? tp("wp4_box_check_body", lang, [box.facts, box.attn]) : tp("wp4_box_check_not_run", lang)}
                  approve={tp("wp4_box_approved_direct", lang, [clockTime(box.atUtc, lang)])}
                />
              ) : null}
            </li>
          );
        })}
        <li className="ed-history-row" data-testid="history-row-source" aria-current={!head ? "true" : undefined}>
          <div className="ed-history-line">
            <span className="ed-history-name">{E.t("editor_history_source", lang)}</span>
            {!head ? <span className="ed-history-tag">{E.t("editor_history_current", lang)}</span> : null}
          </div>
        </li>
      </ol>
    </section>
  );
}
