import type { UiLanguage } from "../i18n/vocabulary";
import { shortHash, type ChangeSetView } from "../model/changes";
import { useWorkspace } from "../store";
import type { Turn } from "../types";
import { setTab } from "./actions";
import { PlanHash } from "./bits";
import { clockTime, revisionName, tp } from "./i18n";
import { panelSlice } from "./state";

/** The turns that belong to this document. */
export function turnsFor(turns: readonly Turn[], sessionId: string | null, activeTurn: string | null): Turn[] {
  return turns.filter((t) => (t.payload ? t.payload.sessionId === sessionId : t.id === activeTurn));
}

function stepName(turn: Turn, lang: UiLanguage): string {
  const step = [...turn.events].reverse().find((e) => e.kind === "step");
  const name = step?.detail && typeof step.detail.label === "string" ? step.detail.label : null;
  return name ?? tp("wp4_thread_step_fallback", lang);
}

function ProposalLine({ view, lang }: { view: ChangeSetView; lang: UiLanguage }) {
  return (
    <div className="rp-msg-proposal">
      <button type="button" className="rp-link rp-link--plain" onClick={() => setTab("changes")} data-testid="thread-proposal">
        {tp("wp4_thread_proposal", lang, [view.items.length, revisionName(view.base.revision, lang)])}
      </button>
      <details className="rp-details rp-details--inline">
        <summary>{tp("wp4_thread_details", lang)}</summary>
        <PlanHash value={view.planHash} lang={lang} testId="thread-proposal-plan-hash" />
        <div className="rp-kv">
          <span className="rp-kv-k">{tp("wp4_sheet_doc_hash", lang)}</span>
          <code className="rp-mono">{shortHash(view.base.sha256)}</code>
        </div>
      </details>
    </div>
  );
}

export function ThreadPane({
  view,
  lang,
  providerName,
  connected,
}: {
  view: ChangeSetView | null;
  lang: UiLanguage;
  providerName: string | null;
  connected: boolean;
}) {
  const sessionId = useWorkspace((s) => s.activeSessionId);
  const turns = useWorkspace((s) => s.turns);
  const activeTurn = useWorkspace((s) => s.activeTurn);
  const applied = panelSlice.use(sessionId, (s) => s.applied);
  const returned = panelSlice.use(sessionId, (s) => s.returned);
  const mine = turnsFor(turns, sessionId, activeTurn);
  const planInTurns = view ? mine.some((t) => t.payload?.plan?.planId === view.id || t.planId === view.id) : false;
  const agentWho = view?.provenance.mock ? tp("wp4_source_test", lang) : tp("wp4_thread_agent", lang);

  return (
    <div className="rp-pane rp-pane--agent" data-testid="agent-pane">
      {connected && providerName ? (
        <p className="rp-pane-status" data-testid="agent-connected">
          {tp("wp4_thread_connected", lang, [providerName])}
        </p>
      ) : null}
      <div className="rp-scroll">
        {mine.length === 0 && !view && !returned && !applied ? <p className="rp-empty">{tp("wp4_thread_empty", lang)}</p> : null}
        <ol className="rp-thread">
          {mine.map((turn) => {
            const plan = turn.payload?.plan ?? null;
            const working = turn.phase === "starting" || turn.id === activeTurn;
            return (
              <li key={turn.id} className="rp-turn">
                <div className="rp-msg">
                  <div className="rp-msg-who">
                    {tp("wp4_thread_me", lang)} <span className="rp-msg-time">{clockTime(turn.at, lang)}</span>
                  </div>
                  <p className="rp-msg-text">{turn.instruction}</p>
                </div>
                <div className="rp-msg">
                  <div className="rp-msg-who">
                    {turn.provider === "mock" ? tp("wp4_source_test", lang) : tp("wp4_thread_agent", lang)}
                  </div>
                  {working ? (
                    <p className="rp-msg-step" data-testid="thread-step">
                      {stepName(turn, lang)}
                    </p>
                  ) : turn.phase === "failed" ? (
                    <p className="rp-msg-text rp-msg-text--attn">
                      {turn.error?.code === "cancelled" ? tp("wp4_thread_cancelled", lang) : tp("wp4_thread_failed", lang)}
                    </p>
                  ) : (
                    <>
                      {turn.payload?.closingText ? <p className="rp-msg-text">{turn.payload.closingText}</p> : null}
                      {view && plan && plan.planId === view.id ? (
                        <ProposalLine view={view} lang={lang} />
                      ) : !plan ? (
                        <p className="rp-msg-text rp-dim">{tp("wp4_thread_no_proposal", lang)}</p>
                      ) : null}
                    </>
                  )}
                </div>
              </li>
            );
          })}
          {view && !planInTurns ? (
            <li className="rp-turn">
              <div className="rp-msg">
                <div className="rp-msg-who">
                  {agentWho} <span className="rp-msg-time">{clockTime(view.createdUtc, lang)}</span>
                </div>
                {view.stale ? <p className="rp-msg-text rp-dim">{tp("wp4_stale_thread", lang)}</p> : null}
                <ProposalLine view={view} lang={lang} />
              </div>
            </li>
          ) : null}
          {applied ? (
            <li className="rp-turn">
              <div className="rp-msg">
                <p className="rp-msg-text">{tp("wp4_applied_status", lang, [applied.revision])}</p>
                <details className="rp-details rp-details--inline" data-testid="thread-applied-details">
                  <summary>{tp("wp4_thread_details", lang)}</summary>
                  <PlanHash value={applied.planHash} lang={lang} testId="thread-applied-plan-hash" />
                  <div className="rp-kv">
                    <span className="rp-kv-k">{tp("wp4_sheet_doc_hash", lang)}</span>
                    <code className="rp-mono" title={applied.baseDigest}>{shortHash(applied.baseDigest)}</code>
                  </div>
                </details>
              </div>
            </li>
          ) : null}
          {returned ? (
            <li className="rp-turn">
              <div className="rp-msg">
                <p className="rp-msg-text rp-dim" data-testid="thread-returned">
                  {tp("wp4_returned_row", lang, [returned.count])}
                </p>
                {returned.reason ? <p className="rp-msg-text">{returned.reason}</p> : null}
              </div>
            </li>
          ) : null}
        </ol>
      </div>
    </div>
  );
}
