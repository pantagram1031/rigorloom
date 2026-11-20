/**
 * The right panel: text tabs `변경 n · 에이전트 · 점검 n`, each pane at full
 * height, the composer docked under all three. The approval sheet takes the
 * whole panel while it is open, so the page stays visible.
 */
import { useEffect } from "react";

import { composerBlocker, composerDraftOf, useWorkspace } from "../store";
import { ApprovalSheet } from "./ApprovalSheet";
import { approvalSheetKey } from "../model/changes";
import { docLayout } from "../shell/shellState";
import { closeApproval, setTab } from "./actions";
import { ChangesPane } from "./ChangesPane";
import { ChecksPane, checksCount } from "./ChecksPane";
import { Composer, composerMode } from "./Composer";
import { tp } from "./i18n";
import { panelSlice, type PanelTab } from "./state";
import { ThreadPane } from "./ThreadPane";
import { useChangeSet } from "./useChangeSet";

export function RightPanel({ sessionId }: { sessionId: string }) {
  const { view, guard } = useChangeSet(sessionId);
  const lang = useWorkspace((s) => s.language);
  const blocker = useWorkspace(composerBlocker);
  const provider = useWorkspace((s) => s.provider.provider);
  const tab = docLayout.use(sessionId, (s) => s.rightTab);
  const sheetOpen = panelSlice.use(sessionId, (s) => s.sheetOpen);
  const confirmPhase = panelSlice.use(sessionId, (s) => s.confirmPhase);
  const styleCount = panelSlice.use(sessionId, (s) => s.style.findings.length);
  const mode = composerMode(blocker, provider, Boolean(sessionId));
  const connected = mode === "ready" || mode === "test" || mode === "working";

  // A proposal arriving moves the panel to 변경 only if the composer is empty.
  const viewId = view?.id ?? null;
  useEffect(() => {
    if (!viewId) return;
    if (docLayout.get(sessionId).rightTab === "agent" && !composerDraftOf(sessionId).text) {
      setTab("changes");
    }
  }, [viewId, sessionId]);

  // The sheet can only stay open on the plan it was opened for. While a
  // confirm is pruning and re-proposing, the confirm itself owns that check.
  useEffect(() => {
    if (!sheetOpen) return;
    const st = panelSlice.get(sessionId);
    const confirming = st.confirmPhase !== "idle" && st.confirmPhase !== "failed";
    if (!confirming && (!view || view.stale || approvalSheetKey(view) !== st.sheetFor)) {
      closeApproval();
    }
  }, [sheetOpen, view, sessionId, confirmPhase]);

  const changeCount = view?.items.length ?? 0;
  const checkCount = checksCount(view, styleCount);
  const tabs: Array<[PanelTab, string, number | null]> = [
    ["changes", tp("wp4_panel_tab_changes", lang), changeCount],
    ["agent", tp("wp4_panel_tab_agent", lang), null],
    ["checks", tp("wp4_panel_tab_checks", lang), checkCount > 0 ? checkCount : null],
  ];

  return (
    <aside className="rp" data-docked="" data-testid="right-panel" aria-label={tp("wp4_panel_aria", lang)}>
      {sheetOpen && view ? (
        <ApprovalSheet view={view} lang={lang} guardState={guard.state} />
      ) : (
        <>
          <div className="rp-tabs" role="tablist">
            {tabs.map(([id, label, n]) => (
              <button
                key={id}
                type="button"
                role="tab"
                className="rp-tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                data-testid={`panel-tab-${id}`}
              >
                {label}
                {n !== null ? <span className="rp-num"> {n}</span> : null}
              </button>
            ))}
          </div>
          <div className="rp-body" role="tabpanel">
            {tab === "changes" ? (
              <ChangesPane view={view} lang={lang} guardState={guard.state} connected={connected} />
            ) : tab === "agent" ? (
              <ThreadPane view={view} lang={lang} connected={connected} providerName={mode === "test" ? null : tp("wp4_thread_agent", lang)} />
            ) : (
              <ChecksPane view={view} lang={lang} guardState={guard.state} />
            )}
          </div>
          <Composer lang={lang} />
        </>
      )}
    </aside>
  );
}
