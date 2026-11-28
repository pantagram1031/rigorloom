/**
 * The frame under 600 px (D1 §6 390×844). WP9 owns what goes in the bottom
 * sheet (`narrowSheet`); the shell owns the 48 px top bar, the drawer and the
 * page area, which shrinks so the sheet never covers the page.
 */
import { useRef, type PointerEvent as ReactPointerEvent } from "react";
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
import { activateTab, closeTab, openStartTab } from "./tabs";
import { paneTabTid, TID } from "./testids";

const LABEL: Record<LeftPaneId, Parameters<typeof S.t>[0]> = {
  files: "shell_pane_files",
  outline: "shell_pane_outline",
  blanks: "shell_pane_blanks",
  find: "shell_pane_find",
  history: "shell_pane_history",
};

const HANDLE_SWIPE_THRESHOLD_PX = 32;

export function NarrowShell({ tab }: { tab: Tab | null }) {
  const lang = useWorkspace((s) => s.language);
  const drawer = useShell((s) => s.narrowDrawerOpen);
  const panelOpen = useShell((s) => s.rightOpen);
  const sheetExpanded = useShell((s) => s.narrowSheetExpanded);
  const sessionId = tab?.kind === "doc" ? tab.sessionId : null;
  const title = useWorkspace((s) => {
    if (!tab) return "";
    if (tab.kind === "start") return S.t("shell_tab_start", s.language);
    if (tab.kind === "doc") return docTitle(s, tab.sessionId);
    return tab.name;
  });
  const count = useWorkspace((s) => (sessionId ? pendingCount(s, sessionId) : 0));
  const sheetHandleLabel = S.t(
    sheetExpanded ? "shell_narrow_sheet_shrink" : "shell_narrow_sheet_expand",
    lang,
  );
  const dragRef = useRef<{ pointerId: number; startY: number; lastY: number } | null>(null);
  const suppressClickRef = useRef(false);

  const onHandlePointerDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0) return;
    suppressClickRef.current = false;
    dragRef.current = { pointerId: e.pointerId, startY: e.clientY, lastY: e.clientY };
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // Synthetic pointer events without an active browser pointer id.
    }
  };

  const onHandlePointerMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    drag.lastY = e.clientY;
  };

  const onHandlePointerUp = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    dragRef.current = null;
    const endY = Number.isFinite(e.clientY) ? e.clientY : drag.lastY;
    const dy = endY - drag.startY;
    if (Math.abs(dy) > HANDLE_SWIPE_THRESHOLD_PX) {
      suppressClickRef.current = true;
      setShell({ narrowSheetExpanded: dy < 0 });
    }
  };

  const onHandlePointerCancel = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    dragRef.current = null;
  };

  return (
    <div className="sh-narrow" data-merged={sessionId ? true : undefined}>
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
        {sessionId ? <Strip sessionId={sessionId} /> : null}
      </header>
      <main className="sh-narrow-main" data-testid={TID.canvasHost}>
        {tab?.kind === "start" ? <StartTab /> : null}
        {tab?.kind === "opening" ? <OpeningCanvas name={tab.name} /> : null}
        {tab?.kind === "failed" ? <FailedCanvas tab={tab} /> : null}
        {sessionId ? (
          <div className="sh-canvas">
            <Slot name="canvas" sessionId={sessionId} fallback={<div className="sh-desk" data-slot-empty="canvas" />} />
          </div>
        ) : null}
      </main>
      {sessionId ? (
        <div
          className="sh-narrow-sheet"
          id="sh-narrow-sheet"
          data-expanded={sheetExpanded || undefined}
          hidden={!panelOpen}
        >
          <button
            type="button"
            className="sh-narrow-sheet-handle"
            aria-expanded={sheetExpanded}
            aria-controls="sh-narrow-sheet"
            aria-label={sheetHandleLabel}
            title={sheetHandleLabel}
            data-testid={TID.narrowSheetHandle}
            onPointerDown={onHandlePointerDown}
            onPointerMove={onHandlePointerMove}
            onPointerUp={onHandlePointerUp}
            onPointerCancel={onHandlePointerCancel}
            onKeyDown={() => {
              suppressClickRef.current = false;
            }}
            onClick={() => {
              if (suppressClickRef.current) {
                suppressClickRef.current = false;
                return;
              }
              setShell({ narrowSheetExpanded: !getShell().narrowSheetExpanded });
            }}
          >
            <span className="sh-narrow-sheet-grip" aria-hidden="true" />
          </button>
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
          {tabs.map((t) => {
            const name = t.kind === "start" ? S.t("shell_tab_start", lang) : t.kind === "doc" ? docTitle(workspace, t.sessionId) : t.name;
            return (
              <div key={t.id} className="sh-drawer-tab">
                <button
                  type="button"
                  className="sh-drawer-row"
                  data-selected={t.id === active || undefined}
                  onClick={() => {
                    activateTab(t.id);
                    setShell({ narrowDrawerOpen: false });
                  }}
                >
                  {name}
                </button>
                <button
                  type="button"
                  className="sh-iconbtn sh-iconbtn--touch sh-drawer-tab-close"
                  aria-label={S.t("shell_tab_close", lang, [name])}
                  data-testid={`narrow-tab-close-${t.id.replace(":", "-")}`}
                  onClick={() => closeTab(t.id)}
                >
                  <Icon name="close" />
                </button>
              </div>
            );
          })}
          <button
            type="button"
            className="sh-drawer-row sh-drawer-add"
            data-testid="narrow-tab-add"
            onClick={() => {
              openStartTab();
              setShell({ narrowDrawerOpen: false });
            }}
          >
            <span aria-hidden="true" className="sh-drawer-add-mark">+</span>
            {S.t("shell_tab_add", lang)}
          </button>
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
