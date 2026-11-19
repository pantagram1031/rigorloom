/**
 * The editor shell (WP2): title bar with tabs, left pane host, canvas column
 * with the document strip, right panel host, status bar. Packages fill the
 * slots; the shell owns the frame, the breakpoints and the keyboard.
 */
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

import { Logo } from "../components/Logo";
import { errorCodeMessage } from "../i18n/vocabulary";
import { S } from "../i18n/v2/shell";
import * as rt from "../runtime";
import { useWorkspace } from "../store";
import { installShellBindings, openPalette, showRightTab, toggleLeft, toggleRight } from "./bindings";
import { AppMenu } from "./AppMenu";
import { docTitle, engineLabel, engineState, agentStatus, pendingCount } from "./docInfo";
import { NarrowShell } from "./NarrowShell";
import { pickAndOpenFile } from "./open";
import { Palette } from "./Palette";
import { Btn, FileName, Icon, KeyHint } from "./parts";
import { SettingsDialog } from "./SettingsDialog";
import {
  activeTab,
  breakpointFor,
  type Breakpoint,
  docLayout,
  dockedSides,
  LEFT_PANES,
  type LeftPaneId,
  sideWidths,
  type Tab,
  useShell,
  getShell,
  setShell,
} from "./shellState";
import { Slot, useSlotsVersion } from "./Slot";
import { StartTab } from "./StartTab";
import { activateTab, closeTab, installTabSync, openStartTab, pinTab, restoreTabs } from "./tabs";
import { paneTabTid, statusTid, tabCloseTid, TID } from "./testids";
import "./shell.css";

function useBreakpoint(): Breakpoint {
  const [bp, setBp] = useState<Breakpoint>(() => breakpointFor(window.innerWidth));
  useEffect(() => {
    setShell({ breakpoint: bp });
  }, [bp]);
  useEffect(() => {
    const onResize = () => setBp(breakpointFor(window.innerWidth));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return bp;
}

function useWindowTitle(tab: Tab | null) {
  const title = useWorkspace((s) => {
    if (!tab) return "";
    if (tab.kind === "doc") return docTitle(s, tab.sessionId);
    if (tab.kind === "opening" || tab.kind === "failed") return tab.name;
    return "";
  });
  const lang = useWorkspace((s) => s.language);
  useEffect(() => {
    document.title = title ? S.t("shell_window_title_doc", lang, [title]) : S.t("shell_app_name", lang);
  }, [title, lang]);
}

export function Shell() {
  const bp = useBreakpoint();
  const tab = useShell((s) => activeTab(s));
  const leftOpen = useShell((s) => s.leftOpen);
  const rightOpen = useShell((s) => s.rightOpen);
  const lastOpened = useShell((s) => s.lastOpened);
  const dragOver = useWorkspace((s) => s.dragOver);
  const lang = useWorkspace((s) => s.language);
  useSlotsVersion();
  useWindowTitle(tab);

  useEffect(() => {
    const offKeys = installShellBindings();
    const offSync = installTabSync();
    void restoreTabs();
    return () => {
      offSync();
      offKeys();
    };
  }, []);

  // Budget measure: a cached tab switch, click to committed frame.
  useLayoutEffect(() => {
    try {
      if (performance.getEntriesByName("tab-switch-start", "mark").length > 0) {
        performance.measure("tab-switch", "tab-switch-start");
        performance.clearMarks("tab-switch-start");
      }
    } catch {
      // no performance API
    }
  }, [tab?.id]);

  const sessionId = tab?.kind === "doc" ? tab.sessionId : null;
  const isDoc = sessionId !== null;
  const docked = dockedSides(bp, { leftOpen, rightOpen, lastOpened }, isDoc);
  const widths = sideWidths(bp);
  const overlay = bp === "overlay";

  if (bp === "narrow") {
    return (
      <div className="sh-root" data-testid={TID.shell} data-breakpoint={bp}>
        <NarrowShell tab={tab} />
        <Palette />
        <SettingsDialog />
        {dragOver ? <DropOutline lang={lang} /> : null}
      </div>
    );
  }

  const style = {
    "--sh-left": `${widths.left}px`,
    "--sh-right": `${widths.right}px`,
  } as CSSProperties;

  return (
    <div
      className="sh-root"
      data-testid={TID.shell}
      data-breakpoint={bp}
      data-left={docked.left && isDoc ? "open" : "closed"}
      data-right={docked.right ? "open" : "closed"}
      style={style}
    >
      <TitleBar bp={bp} isDoc={isDoc} docked={docked} />
      <div className="sh-body">
        {isDoc && docked.left ? <LeftPane sessionId={sessionId} overlay={overlay} /> : null}
        <main className="sh-center" data-testid={TID.canvasHost}>
          {tab?.kind === "start" ? <StartTab /> : null}
          {tab?.kind === "opening" ? <OpeningCanvas name={tab.name} /> : null}
          {tab?.kind === "failed" ? <FailedCanvas tab={tab} /> : null}
          {tab?.kind === "doc" ? (
            <>
              <Strip sessionId={tab.sessionId} />
              <div className="sh-canvas">
                <Slot name="canvas" sessionId={tab.sessionId} fallback={<div className="sh-desk" data-slot-empty="canvas" />} />
              </div>
            </>
          ) : null}
        </main>
        {isDoc && docked.right ? <RightPanel sessionId={sessionId} overlay={overlay} /> : null}
      </div>
      <StatusBar sessionId={sessionId} rightDocked={docked.right} />
      <Palette />
      <SettingsDialog />
      {dragOver ? <DropOutline lang={lang} /> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Title bar

function TitleBar({ bp, isDoc, docked }: { bp: Breakpoint; isDoc: boolean; docked: { left: boolean; right: boolean } }) {
  const tabs = useShell((s) => s.tabs);
  const active = useShell((s) => s.activeTab);
  const appMenuOpen = useShell((s) => s.appMenuOpen);
  const tabListOpen = useShell((s) => s.tabListOpen);
  const leftOpen = docked.left;
  const rightOpen = docked.right;
  const lang = useWorkspace((s) => s.language);
  const stripRef = useRef<HTMLDivElement>(null);
  const [overflow, setOverflow] = useState(false);
  const tauri = rt.isTauri();

  useLayoutEffect(() => {
    const el = stripRef.current;
    if (!el) return;
    const check = () => setOverflow(el.scrollWidth > el.clientWidth + 1);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [tabs.length]);

  // Keep the active tab in view when it changes.
  useEffect(() => {
    const el = stripRef.current?.querySelector<HTMLElement>(`[data-tab-id="${CSS.escape(active)}"]`);
    el?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [active]);

  return (
    <header className="sh-titlebar" data-testid={TID.titlebar} data-tauri-drag-region>
      <div className="sh-menu-anchor">
        <button
          type="button"
          className="sh-iconbtn sh-mark"
          aria-label={S.t("shell_app_menu", lang)}
          aria-haspopup="menu"
          aria-expanded={appMenuOpen}
          data-testid={TID.appMenu}
          onClick={() => setShell({ appMenuOpen: !getShell().appMenuOpen, tabListOpen: false })}
        >
          <Logo size={16} />
        </button>
        {appMenuOpen ? <AppMenu /> : null}
      </div>
      <div className="sh-tabs" role="tablist" aria-label={S.t("shell_tab_list", lang)} data-testid={TID.tabbar} ref={stripRef}>
        {tabs.map((tab, i) => (
          <TabItem key={tab.id} tab={tab} active={tab.id === active} index={i} />
        ))}
      </div>
      <button
        type="button"
        className="sh-iconbtn sh-tab-add"
        aria-label={S.t("shell_tab_add", lang)}
        title={S.t("shell_tab_add", lang)}
        data-testid={TID.tabAdd}
        onClick={() => openStartTab()}
      >
        <span aria-hidden="true">+</span>
      </button>
      {overflow ? (
        <div className="sh-menu-anchor">
          <button
            type="button"
            className="sh-iconbtn"
            aria-label={S.t("shell_tab_list", lang)}
            aria-haspopup="menu"
            aria-expanded={tabListOpen}
            data-testid={TID.tabList}
            onClick={() => setShell({ tabListOpen: !getShell().tabListOpen, appMenuOpen: false })}
          >
            <Icon name="chevronDown" />
          </button>
          {tabListOpen ? <TabListMenu /> : null}
        </div>
      ) : null}
      <div className="sh-drag" data-tauri-drag-region />
      <button
        type="button"
        className="sh-cmdfield"
        data-testid={TID.paletteField}
        onClick={() => openPalette()}
        aria-label={S.t("shell_palette_label", lang)}
      >
        <span className="sh-cmdfield-text">{S.t("shell_palette_field", lang)}</span>
        <KeyHint id="shell.palette" />
      </button>
      {isDoc && bp !== "narrow" ? (
        <div className="sh-toggles">
          <button
            type="button"
            className="sh-iconbtn"
            aria-pressed={leftOpen}
            aria-label={S.t("shell_toggle_left", lang)}
            title={S.t("shell_toggle_left", lang)}
            data-testid={TID.toggleLeft}
            onClick={() => toggleLeft()}
          >
            <Icon name="paneLeft" />
          </button>
          <button
            type="button"
            className="sh-iconbtn"
            aria-pressed={rightOpen}
            aria-label={S.t("shell_toggle_right", lang)}
            title={S.t("shell_toggle_right", lang)}
            data-testid={TID.toggleRight}
            onClick={() => toggleRight()}
          >
            <Icon name="paneRight" />
          </button>
        </div>
      ) : null}
      {tauri ? <WindowControls /> : null}
    </header>
  );
}

function TabItem({ tab, active, index }: { tab: Tab; active: boolean; index: number }) {
  const lang = useWorkspace((s) => s.language);
  const title = useWorkspace((s) => {
    if (tab.kind === "start") return S.t("shell_tab_start", s.language);
    if (tab.kind === "doc") return docTitle(s, tab.sessionId);
    return tab.name;
  });
  const count = useWorkspace((s) => (tab.kind === "doc" ? pendingCount(s, tab.sessionId) : 0));
  const lone = useShell((s) => s.tabs.length === 1);
  const sample = useWorkspace((s) => (tab.kind === "doc" ? title !== s.sessions.find((x) => x.sessionId === tab.sessionId)?.source.name : false));
  const testId = tab.kind === "start" ? TID.tabStart : tab.kind === "doc" ? `tab-${tab.sessionId}` : `tab-${tab.id.replace(":", "-")}`;
  return (
    <div
      className="sh-tab"
      role="tab"
      aria-selected={active}
      data-active={active || undefined}
      data-kind={tab.kind}
      data-preview={tab.kind === "doc" && tab.preview ? "true" : undefined}
      data-tab-id={tab.id}
      data-testid={testId}
      data-index={index}
      tabIndex={active ? 0 : -1}
      onClick={() => activateTab(tab.id)}
      onDoubleClick={() => pinTab(tab.id)}
      onAuxClick={(e) => {
        if (e.button === 1) closeTab(tab.id);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          activateTab(tab.id);
        }
      }}
    >
      <span className="sh-tab-title">{sample || tab.kind !== "doc" ? title : <FileName name={title} />}</span>
      {tab.kind === "failed" ? <span className="sh-tab-state" data-attn>{S.t("shell_tab_failed", lang)}</span> : null}
      {count > 0 ? (
        <span className="sh-tab-count" data-accent aria-label={S.t("shell_tab_changes_count", lang, [count])}>
          {count}
        </span>
      ) : null}
      {tab.kind === "start" && lone ? null : (
      <button
        type="button"
        className="sh-tab-close"
        aria-label={S.t("shell_tab_close", lang, [title])}
        data-testid={tab.kind === "doc" ? tabCloseTid(tab.sessionId) : `tab-close-${tab.id.replace(":", "-")}`}
        tabIndex={-1}
        onClick={(e) => {
          e.stopPropagation();
          closeTab(tab.id);
        }}
      >
        <Icon name="close" />
      </button>
      )}
    </div>
  );
}

function TabListMenu() {
  const tabs = useShell((s) => s.tabs);
  const active = useShell((s) => s.activeTab);
  const workspace = useWorkspace((s) => s);
  return (
    <div className="sh-menu" role="menu" data-testid="tab-list-menu">
      {tabs.map((tab) => {
        const title =
          tab.kind === "start"
            ? S.t("shell_tab_start", workspace.language)
            : tab.kind === "doc"
              ? docTitle(workspace, tab.sessionId)
              : tab.name;
        return (
          <button
            type="button"
            key={tab.id}
            role="menuitem"
            className="sh-menu-row"
            data-selected={tab.id === active || undefined}
            onClick={() => activateTab(tab.id)}
          >
            <span className="sh-menu-label">{title}</span>
          </button>
        );
      })}
    </div>
  );
}

function WindowControls() {
  const lang = useWorkspace((s) => s.language);
  const run = (fn: (w: ReturnType<typeof getCurrentWindow>) => Promise<void>) => () => {
    try {
      void fn(getCurrentWindow()).catch(() => {});
    } catch {
      // not in a Tauri window
    }
  };
  return (
    <div className="sh-winctl">
      <button type="button" className="sh-winbtn" aria-label={S.t("shell_win_minimize", lang)} onClick={run((w) => w.minimize())}>
        <Icon name="minimize" />
      </button>
      <button type="button" className="sh-winbtn" aria-label={S.t("shell_win_maximize", lang)} onClick={run((w) => w.toggleMaximize())}>
        <Icon name="maximize" />
      </button>
      <button type="button" className="sh-winbtn sh-winbtn--close" aria-label={S.t("shell_win_close", lang)} onClick={run((w) => w.close())}>
        <Icon name="close" />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Left pane host

const PANE_LABEL: Record<LeftPaneId, Parameters<typeof S.t>[0]> = {
  files: "shell_pane_files",
  outline: "shell_pane_outline",
  blanks: "shell_pane_blanks",
  find: "shell_pane_find",
  history: "shell_pane_history",
};

function LeftPane({ sessionId, overlay }: { sessionId: string; overlay: boolean }) {
  const pane = docLayout.use(sessionId, (l) => l.leftPane);
  const lang = useWorkspace((s) => s.language);
  return (
    <aside
      className="sh-left"
      data-testid={TID.leftPane}
      data-docked={overlay ? undefined : "true"}
      data-overlay={overlay || undefined}
      aria-label={S.t("shell_panes_label", lang)}
    >
      <div className="sh-pane-tabs" role="tablist" data-testid={TID.paneTabs}>
        {LEFT_PANES.map((id) => (
          <button
            type="button"
            key={id}
            role="tab"
            aria-selected={pane === id}
            className="sh-pane-tab"
            data-testid={paneTabTid(id)}
            onClick={() => docLayout.patch(sessionId, { leftPane: id, landed: true })}
          >
            {S.t(PANE_LABEL[id], lang)}
          </button>
        ))}
      </div>
      <div className="sh-pane-body" role="tabpanel">
        <Slot name={`pane:${pane}`} sessionId={sessionId} />
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Right panel host

function RightPanel({ sessionId, overlay }: { sessionId: string; overlay: boolean }) {
  return (
    <aside
      className="sh-right"
      data-testid={TID.rightPanelHost}
      data-docked={overlay ? undefined : "true"}
      data-overlay={overlay || undefined}
    >
      <Slot name="rightPanel" sessionId={sessionId} />
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Document strip frame

function Strip({ sessionId }: { sessionId: string }) {
  return (
    <div className="sh-strip" data-testid={TID.stripHost} data-docked="true">
      <div className="sh-strip-start">
        <Slot name="stripStart" sessionId={sessionId} quiet />
      </div>
      <div className="sh-strip-end">
        <Slot name="stripEnd" sessionId={sessionId} quiet />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Canvas states without a document

function OpeningCanvas({ name }: { name: string }) {
  const lang = useWorkspace((s) => s.language);
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const id = window.setTimeout(() => setSlow(true), 400);
    return () => window.clearTimeout(id);
  }, []);
  return (
    <div className="sh-canvas sh-canvas--state" data-testid={TID.docOpening} aria-busy="true">
      {slow ? <div className="sh-progress" role="progressbar" aria-label={S.t("shell_doc_opening", lang)} /> : null}
      <div className="sh-desk">
        <div className="sh-blank-paper" aria-label={name} />
      </div>
    </div>
  );
}

function FailedCanvas({ tab }: { tab: Extract<Tab, { kind: "failed" }> }) {
  const lang = useWorkspace((s) => s.language);
  const [open, setOpen] = useState(false);
  const isHwp = /\.hwp$/i.test(tab.name);
  const code = tab.error?.code ?? "";
  const known = code ? errorCodeMessage(code, lang) : "";
  return (
    <div className="sh-canvas sh-canvas--state" data-testid={TID.docFailed}>
      <div className="sh-desk sh-desk--message">
        <div className="sh-message">
          <p className="sh-message-text">{S.t("shell_doc_failed", lang)}</p>
          {isHwp ? <p className="sh-message-sub">{S.t("shell_doc_failed_hwp", lang)}</p> : null}
          <div className="sh-message-actions">
            <Btn
              testId="doc-failed-open-other"
              onClick={() => {
                closeTab(tab.id);
                void pickAndOpenFile();
              }}
            >
              {S.t("shell_doc_open_other", lang)}
            </Btn>
            <Btn variant="quiet" onClick={() => setOpen((v) => !v)} testId="doc-failed-details">
              {S.t("shell_details", lang)}
            </Btn>
          </div>
          {open ? (
            <dl className="sh-details" data-testid="doc-failed-detail">
              <dt>{tab.name}</dt>
              {known && known !== code ? <dd>{known}</dd> : null}
              {code ? <dd className="sh-mono">{code}</dd> : null}
              {tab.error?.message ? <dd className="sh-mono">{tab.error.message}</dd> : null}
            </dl>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function DropOutline({ lang }: { lang: "ko" | "en" }) {
  return (
    <div className="sh-drop" data-testid={TID.dropOutline}>
      <div className="sh-drop-paper">{S.t("shell_start_drop", lang)}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status bar (text only)

function StatusBar({ sessionId, rightDocked }: { sessionId: string | null; rightDocked: boolean }) {
  const lang = useWorkspace((s) => s.language);
  const engine = useWorkspace((s) => engineState(s));
  const agentText = useWorkspace((s) => agentStatus(s).text);
  const agentAttn = useWorkspace((s) => agentStatus(s).attn);
  const count = useWorkspace((s) => (sessionId ? pendingCount(s, sessionId) : 0));
  const docFolder = useShell((s) => s.docFolder);
  const pulse = useShell((s) => s.savedPulse);
  const tabKind = useShell((s) => activeTab(s)?.kind);
  const [pulsing, setPulsing] = useState(false);
  useEffect(() => {
    if (pulse === 0) return;
    setPulsing(true);
    const id = window.setTimeout(() => setPulsing(false), 600);
    return () => window.clearTimeout(id);
  }, [pulse]);

  return (
    <footer className="sh-status" data-testid={TID.statusbar} data-docked="true">
      <div className="sh-status-side">
        {sessionId ? <Slot name="statusLeft" sessionId={sessionId} quiet /> : null}
      </div>
      <div className="sh-status-side sh-status-side--end">
        {sessionId ? <Slot name="statusRight" sessionId={sessionId} quiet /> : null}
        {sessionId && !rightDocked && count > 0 ? (
          <button type="button" className="sh-status-item sh-status-link" data-testid={statusTid("changes")} onClick={() => showRightTab("changes")}>
            {S.t("shell_status_changes", lang, [count])}
          </button>
        ) : null}
        {tabKind === "doc" ? (
          <span className="sh-status-item" data-attn={agentAttn || undefined} data-testid={statusTid("agent")}>
            {agentText}
          </span>
        ) : null}
        <span className="sh-status-item" data-attn={engine !== "ready" && engine !== "checking" ? true : undefined} data-testid={statusTid("engine")}>
          {engineLabel(engine, lang)}
        </span>
        {tabKind === "doc" ? (
          <span className="sh-status-item" data-pulse={pulsing || undefined} data-testid={statusTid("saved")}>
            {S.t("shell_status_saved", lang)}
          </span>
        ) : null}
        {tabKind === "start" && docFolder ? (
          <span className="sh-status-item" data-testid={statusTid("folder")}>
            {S.t("shell_status_doc_folder", lang, [shortPath(docFolder)])}
          </span>
        ) : null}
      </div>
    </footer>
  );
}

function shortPath(p: string): string {
  if (!p) return "";
  const home = /^(\/home\/[^/]+|\/Users\/[^/]+|[A-Za-z]:\\Users\\[^\\]+)/;
  return p.replace(home, "~");
}

export { LeftPane, StatusBar, shortPath, FailedCanvas, OpeningCanvas, DropOutline };
