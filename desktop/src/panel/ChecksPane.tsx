import type { ReactNode } from "react";

import type { UiLanguage } from "../i18n/vocabulary";
import { isChangedFact, needsLook, type ChangeItem, type ChangeSetView } from "../model/changes";
import { keymapChord } from "../shell/keymap";
import { useWorkspace } from "../store";
import { buttonTitle } from "../ui/Button";
import { runStyleCheck, select, setTab } from "./actions";
import { tp } from "./i18n";
import { panelSlice } from "./state";

function Group({ title, count, children, testId }: { title: string; count: number; children: ReactNode; testId: string }) {
  return (
    <section className="rp-group" data-testid={testId}>
      <h3 className="rp-group-title">
        {title} <span className="rp-num">{count}</span>
      </h3>
      {children}
    </section>
  );
}

function ItemLink({ item, children }: { item: ChangeItem; children?: ReactNode; lang?: UiLanguage }) {
  return (
    <li>
      <button
        type="button"
        className="rp-check-row"
        onClick={() => {
          select(item.id);
          setTab("changes");
        }}
      >
        <span className="rp-num">{item.n}</span>
        <span className="rp-check-label">{item.label}</span>
        <span className="rp-check-detail">{children ?? item.opName}</span>
      </button>
    </li>
  );
}

/** How many entries the 점검 tab counts. */
export function checksCount(view: ChangeSetView | null, styleCount: number): number {
  const items = view?.items ?? [];
  return items.filter((it) => it.hard.length > 0 || isChangedFact(it) || needsLook(it)).length + styleCount;
}

export function ChecksPane({ view, lang, guardState }: { view: ChangeSetView | null; lang: UiLanguage; guardState: string }) {
  const doc = useWorkspace((s) => s.activeSessionId);
  const style = panelSlice.use(doc, (s) => s.style);
  const items = view?.items ?? [];
  const hard = items.filter((it) => it.hard.length > 0);
  const facts = items.filter(isChangedFact);
  const attn = items.filter(needsLook);

  return (
    <div className="rp-pane rp-pane--checks" data-testid="checks-pane">
      <p className="rp-scope" data-testid="checks-scope">
        {guardState === "unavailable" ? tp("wp4_sheet_guard_skipped", lang) : tp("wp4_sheet_guard_scope", lang)}
      </p>
      <div className="rp-scroll">
        {guardState === "running" ? <p className="rp-pane-status">{tp("wp4_checks_guard_running", lang)}</p> : null}
        {hard.length > 0 ? (
          <Group title={tp("wp4_checks_group_hard", lang)} count={hard.length} testId="checks-hard">
            <ul className="rp-check-list">
              {hard.map((it) => (
                <ItemLink key={it.id} item={it} lang={lang}>
                  {it.hard[0]}
                </ItemLink>
              ))}
            </ul>
          </Group>
        ) : null}
        {facts.length > 0 ? (
          <div data-fact="">
            <Group title={tp("wp4_checks_group_fact", lang)} count={facts.length} testId="checks-facts">
              <ul className="rp-check-list">
                {facts.map((it) => (
                  <ItemLink key={it.id} item={it} lang={lang}>
                    {it.guard.facts
                      .filter((f) => !f.expected)
                      .map((f) => `${f.before ?? ""} → ${f.after ?? ""}`)
                      .join(", ")}
                  </ItemLink>
                ))}
              </ul>
            </Group>
          </div>
        ) : null}
        {attn.length > 0 ? (
          <Group title={tp("wp4_checks_group_attn", lang)} count={attn.length} testId="checks-attn">
            <ul className="rp-check-list">
              {attn.map((it) => (
                <ItemLink key={it.id} item={it} lang={lang}>
                  {it.guard.status === "not_checked" ? tp("wp4_checks_not_run", lang) : it.opName}
                </ItemLink>
              ))}
            </ul>
          </Group>
        ) : null}
        <Group title={tp("wp4_checks_group_style", lang)} count={style.findings.length} testId="checks-style">
          <div className="rp-check-actions">
            <button
              type="button"
              className="rp-btn"
              onClick={() => void runStyleCheck()}
              disabled={!doc || style.phase === "running"}
              data-testid="style-run"
              title={buttonTitle(
                style.phase === "running" ? tp("wp4_checks_style_running", lang) : tp("wp4_checks_style_run", lang),
                keymapChord("checks.style"),
              )}
            >
              {style.phase === "running" ? tp("wp4_checks_style_running", lang) : tp("wp4_checks_style_run", lang)}
            </button>
            {style.phase === "ready" ? (
              <span className="rp-pane-status">
                {style.findings.length > 0
                  ? tp("wp4_checks_style_result", lang, [style.findings.length])
                  : tp("wp4_checks_style_none", lang)}
              </span>
            ) : null}
            {style.phase === "failed" ? <span className="rp-pane-status rp-attn">{tp("wp4_checks_style_failed", lang)}</span> : null}
          </div>
          {style.findings.length > 0 ? (
            <ul className="rp-check-list" data-testid="style-findings">
              {style.findings.map((f, i) => (
                <li key={`${f.rule}-${i}`} className="rp-style-row">
                  <span className="rp-style-msg">{f.message}</span>
                  <span className="rp-style-excerpt">{f.excerpt}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </Group>
        {hard.length === 0 && facts.length === 0 && attn.length === 0 && style.findings.length === 0 && guardState !== "running" ? (
          <p className="rp-empty">{tp("wp4_checks_empty", lang)}</p>
        ) : null}
      </div>
    </div>
  );
}
