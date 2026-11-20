/**
 * The frame under 600 px (D1 §6 390×844). WP9 owns what goes in the bottom
 * sheet (`narrowSheet`); the shell owns the 48 px top bar, the drawer and the
 * page area, which shrinks so the sheet never covers the page.
 */
import { Mark } from "../brand";
import { S } from "../i18n/v2/shell";
import { useWorkspace } from "../store";
import { openSettings, toggleRight } from "./bindings";
import { docTitle, pendingCount } from "./docInfo";
import { Icon } from "./parts";
import { docLayout, LEFT_PANES, type LeftPaneId, setShell, type Tab, useShell, getShell } from "./shellState";
import { FailedCanvas, OpeningCanvas, Strip } from "./Shell";
import { Slot } from "./Slot";
import { StartTab } from "./StartTab";
import { activateTab } from "./tabs";
import { paneTabTid, TID } from "./testids";

const LABEL: Record<LeftPaneId, Parameters<typeof S.t>[0]> = {
  files: "shell_pane_files",
  outline: "shell_pane_outline",
  blanks: "shell_pane_blanks",
  find: "shell_pane_find",
  history: "shell_pane_history",
};

export function NarrowShell({ tab }: { tab: Tab | null }) {
  const lang = useWorkspace((s) => s.language);
  const drawer = useShell((s) => s.narrowDrawerOpen);
  const panelOpen = useShell((s) => s.rightOpen);
  const sessionId = tab?.kind === "doc" ? tab.sessionId : null;
  const title = useWorkspace((s) => {
    if (!tab) return "";
    if (tab.kind === "start") return S.t("shell_tab_start", s.language);
    if (tab.kind === "doc") return docTitle(s, tab.sessionId);
    return tab.name;
  });
  const count = useWorkspace((s) => (sessionId ? pendingCount(s, sessionId) : 0));

  return (
    <div className="sh-narrow">
      <header className="sh-narrow-bar" data-testid={TID.titlebar}>
        <button
          type="button"
          className="sh-iconbtn sh-iconbtn--touch"
          aria-label={S.t("shell_app_menu", lang)}
          aria-expanded={drawer}
          data-testid={TID.appMenu}
          onClick={() => setShell({ narrowDrawerOpen: !getShell().narrowDrawerOpen })}
        >
          <Mark size={20} />
        </button>
        <div className="sh-narrow-title">
          <span className="sh-narrow-name">{title}</span>
        </div>
        {sessionId ? (
          <button
            type="button"
            className="sh-iconbtn sh-iconbtn--touch sh-narrow-panel-toggle"
            aria-controls="sh-narrow-sheet"
            aria-expanded={panelOpen}
            data-testid={TID.toggleRight}
            onClick={toggleRight}
          >
            {S.t(panelOpen ? "shell_narrow_changes_close" : "shell_narrow_changes_open", lang, [count])}
          </button>
        ) : null}
      </header>
      <main className="sh-narrow-main" data-testid={TID.canvasHost}>
        {tab?.kind === "start" ? <StartTab /> : null}
        {tab?.kind === "opening" ? <OpeningCanvas name={tab.name} /> : null}
        {tab?.kind === "failed" ? <FailedCanvas tab={tab} /> : null}
        {sessionId ? (
          <>
            <Strip sessionId={sessionId} />
            <div className="sh-canvas">
              <Slot name="canvas" sessionId={sessionId} fallback={<div className="sh-desk" data-slot-empty="canvas" />} />
            </div>
          </>
        ) : null}
      </main>
      {sessionId ? (
        <div className="sh-narrow-sheet" id="sh-narrow-sheet" hidden={!panelOpen}>
          <Slot name="narrowSheet" sessionId={sessionId} quiet />
        </div>
      ) : null}
      {drawer ? <Drawer sessionId={sessionId} /> : null}
    </div>
  );
}

function Drawer({ sessionId }: { sessionId: string | null }) {
  const lang = useWorkspace((s) => s.language);
  const tabs = useShell((s) => s.tabs);
  const active = useShell((s) => s.activeTab);
  const pane = docLayout.use(sessionId, (l) => l.leftPane);
  const workspace = useWorkspace((s) => s);
  return (
    <div className="sh-scrim" onMouseDown={(e) => e.target === e.currentTarget && setShell({ narrowDrawerOpen: false })}>
      <aside className="sh-drawer" data-testid="narrow-drawer">
        <div className="sh-drawer-head">
          <button type="button" className="sh-iconbtn sh-iconbtn--touch" aria-label={S.t("shell_win_close", lang)} onClick={() => setShell({ narrowDrawerOpen: false })}>
            <Icon name="close" />
          </button>
        </div>
        <div className="sh-drawer-section">
          {tabs.map((t) => (
            <button
              type="button"
              key={t.id}
              className="sh-drawer-row"
              data-selected={t.id === active || undefined}
              onClick={() => {
                activateTab(t.id);
                setShell({ narrowDrawerOpen: false });
              }}
            >
              {t.kind === "start" ? S.t("shell_tab_start", lang) : t.kind === "doc" ? docTitle(workspace, t.sessionId) : t.name}
            </button>
          ))}
        </div>
        {sessionId ? (
          <>
            <div className="sh-pane-tabs" role="tablist">
              {LEFT_PANES.map((id) => (
                <button
                  type="button"
                  key={id}
                  role="tab"
                  data-testid={paneTabTid(id)}
                  aria-selected={pane === id}
                  className="sh-pane-tab sh-pane-tab--touch"
                  onClick={() => docLayout.patch(sessionId, { leftPane: id, landed: true })}
                >
                  {S.t(LABEL[id], lang)}
                </button>
              ))}
            </div>
            <div className="sh-pane-body">
              <Slot name={`pane:${pane}`} sessionId={sessionId} />
            </div>
          </>
        ) : null}
        <div className="sh-drawer-foot">
          <button type="button" className="sh-drawer-row" onClick={() => openSettings()}>
            {S.t("shell_settings_title", lang)}
          </button>
        </div>
      </aside>
    </div>
  );
}
