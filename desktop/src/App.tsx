import { useEffect } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";

import {
  boot,
  bindFormAndOpen,
  closeTopmostOverlay,
  copySelection,
  exportApplied,
  openDropped,
  openViaDialog,
  resetUiZoom,
  restartRuntime,
  stepUiZoom,
  toggleFullscreen,
  toggleLeftRail,
  approveAndApply,
} from "./actions";
import { Icon } from "./components/Icon";
import { Logo } from "./components/Logo";
import { CommandPalette, toggleCommandPalette } from "./components/CommandPalette";
import { Settings } from "./components/Settings";
import { Splash } from "./components/Splash";
import { Toast } from "./components/Toast";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "./ui/DropdownMenu";
import { Kbd } from "./ui/Kbd";
import { Tooltip } from "./ui/Tooltip";
import { focusDocumentSurface } from "./focus";
import * as rt from "./runtime";
import { deliverDocumentEvents, stopDocumentEvents } from "./documentEvents";
import { RuntimeSubscriptionScope } from "./runtimeSubscriptions";
import {
  getState,
  goHome,
  leaveHome,
  pushActivity,
  pushHostEvents,
  paintColorTheme,
  setChromeMenu,
  setState,
  setView,
  toggleHome,
  useWorkspace,
  type View,
} from "./store";
import { DocumentView } from "./views/DocumentView";
import { KitGallery } from "./ui/Gallery";

export { CLI_DOCS_PATH, CLI_DOCS_URL } from "./components/Welcome";

let homeTimingScheduled = false;

function Fatal({
  code,
  message,
  onRetry,
}: {
  code: string;
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="boot">
      <div className="fatal" data-testid="fatal">
        <h2>런타임을 시작하지 못했습니다</h2>
        <p className="prose" style={{ color: "var(--fg)" }}>
          {message}
        </p>
        <p className="prose mono" style={{ marginTop: "var(--s3)" }}>
          {code}
        </p>
        <Button variant="primary" style={{ marginTop: "var(--s4)" }} onClick={onRetry}>
          다시 시도
        </Button>
      </div>
    </div>
  );
}

function switchView(next: View) {
  if (getState().view === next) return;
  setView(next);
  void rt.savePrefs({ lastView: next });
}

/** Real Tauri windows expose this; the browser devMock only stubs `invoke`. */
function canBindDragDrop(): boolean {
  const internals = (window as unknown as {
    __TAURI_INTERNALS__?: { metadata?: { currentWebview?: { label?: string } } };
  }).__TAURI_INTERNALS__;
  return typeof internals?.metadata?.currentWebview?.label === "string";
}

export default function App() {
  if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("kit") === "1") {
    return <KitGallery />;
  }
  return <AppShell />;
}

function AppShell() {
  const phase = useWorkspace((s) => s.phase);
  const phaseNote = useWorkspace((s) => s.phaseNote);
  const fatal = useWorkspace((s) => s.fatal);
  const status = useWorkspace((s) => s.status);
  const panic = useWorkspace((s) => s.panic);
  const entranceDone = useWorkspace((s) => s.entranceDone);
  const holdEntrance = useWorkspace((s) => s.holdEntrance);
  const dragOver = useWorkspace((s) => s.dragOver);
  const session = useWorkspace(
    (s) => s.sessions.find((x) => x.sessionId === s.activeSessionId) ?? null,
  );
  const homeOpen = useWorkspace((s) => s.homeOpen);
  const chromeMenu = useWorkspace((s) => s.chromeMenu);
  const colorTheme = useWorkspace((s) => s.colorTheme);
  const openMenu = chromeMenu === "open";

  useEffect(() => {
    const subscriptions = new RuntimeSubscriptionScope();

    (async () => {
      // Hold-entrance must win before the splash may dismiss. After that, Home
      // is ready: do not wait for activity subscriptions or the sidecar.
      let smokePhase: string | null = null;
      try {
        const config = await rt.smokeConfig();
        smokePhase = config.phase ?? null;
      } catch {
        smokePhase = null;
      }
      if (subscriptions.isDisposed) return;
      if (smokePhase === "hold-entrance") setState({ holdEntrance: true });
      else setState({ phase: "ready", phaseNote: "" });

      if (!(await subscriptions.add(rt.onActivity(pushActivity)))) return;
      // The document's own history. Arrives as batched `event` notifications,
      // already split from protocol chatter in Rust; the store de-duplicates
      // on `seq`, so a replay after a reconnect is idempotent.
      if (!(await subscriptions.add(rt.onEvents(deliverDocumentEvents)))) return;
      // The Agent Host's own log, live while a turn runs. A third channel
      // rather than a filter on the second: these are the provider's events,
      // not the document's, and the store folds them into the turn that owns
      // them by id.
      if (!(await subscriptions.add(rt.onAgentEvents(pushHostEvents)))) return;
      if (!(await subscriptions.add(rt.onStatus((s) => setState({ status: s }))))) return;
      // A Rust panic must be visible, not a silent disappearance.
      if (!(await subscriptions.add(rt.onPanic((p) => setState({ panic: p }))))) return;

      // Files dropped on the window. The webview owns the event; the runtime
      // owns everything that happens to the bytes afterwards. Browser-mode
      // (devMock) has invoke but no window metadata, so getCurrentWebview()
      // throws — never abort boot, and never leave the drop veil stuck.
      if (canBindDragDrop()) {
        try {
          await subscriptions.add(
            getCurrentWebview().onDragDropEvent((event) => {
              if (event.payload.type === "over" || event.payload.type === "enter") {
                setState({ dragOver: true });
              } else {
                setState({ dragOver: false });
                if (event.payload.type === "drop") void openDropped(event.payload.paths);
              }
            }),
          );
        } catch {
          setState({ dragOver: false });
        }
      }

      await boot();
      if (subscriptions.isDisposed) return;
      if (smokePhase) {
        const { runSmoke } = await import("./smoke");
        await runSmoke();
      }
    })().catch((error) => {
      if (subscriptions.isDisposed) return;
      subscriptions.dispose();
      stopDocumentEvents();
      setState({ phase: "failed", fatal: rt.asRuntimeError(error) });
    });

    return () => {
      subscriptions.dispose();
      stopDocumentEvents();
    };
  }, []);

  useEffect(() => {
    paintColorTheme(colorTheme);
    if (colorTheme !== "auto" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => paintColorTheme("auto");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [colorTheme]);

  useEffect(() => {
    if (homeTimingScheduled) return;
    if (phase !== "ready" || !entranceDone) return;
    if (!document.querySelector('[data-testid="welcome"]')) return;
    homeTimingScheduled = true;
    void rt.timingMark("home");
  }, [phase, entranceDone]);

  // Keyboard. Ctrl+O open · Ctrl+S save/export · Ctrl+Shift+H home · Ctrl+1/2 views · Ctrl+= / - / 0 app zoom ·
  // Ctrl+C copies the selected cell's text.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // F11 and Esc are window-level and reach past a focused field on
      // purpose — every editor's are. Esc while a syllable is composing is the
      // IME's own cancel, though, so it is left alone there.
      if (e.key === "F11") {
        e.preventDefault();
        void toggleFullscreen();
        return;
      }
      if (e.key === "Escape" && !e.isComposing) {
        // One place, one order: innermost overlay first. Handled centrally so
        // two components cannot both decide what Esc meant.
        if (closeTopmostOverlay()) e.preventDefault();
        else {
          e.preventDefault();
          focusDocumentSurface();
        }
        return;
      }
      if ((e.key === "k" || e.key === "K") && (e.ctrlKey || e.metaKey) && !e.altKey) {
        e.preventDefault();
        toggleCommandPalette();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key === "Enter") {
        if (e.isComposing || getState().isComposing) return;
        e.preventDefault();
        void approveAndApply();
        return;
      }
      // A shortcut must never reach past a text field the user is typing in.
      // Ctrl+C inside the inline editor is a copy, not a "copy the selected
      // cell", and Ctrl+O while composing Hangul would throw the edit away.
      const target = e.target as HTMLElement | null;
      const typing =
        target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
      if (typing) return;
      if (!e.ctrlKey || e.altKey) return;
      switch (e.key) {
        case "s":
        case "S":
          e.preventDefault();
          void exportApplied();
          break;
        case "o":
        case "O":
          e.preventDefault();
          void openViaDialog();
          break;
        case "1":
          e.preventDefault();
          switchView("document");
          break;
        case "2":
          e.preventDefault();
          switchView("agent");
          break;
        case "=":
        case "+":
          e.preventDefault();
          stepUiZoom(1);
          break;
        case "-":
        case "_":
          e.preventDefault();
          stepUiZoom(-1);
          break;
        case "0":
          e.preventDefault();
          resetUiZoom();
          break;
        case "c":
        case "C":
          // Only intercept when there is no real text selection to copy.
          void copySelection();
          break;
        case "b":
        case "B":
          e.preventDefault();
          toggleLeftRail();
          break;
        case "h":
        case "H":
          if (e.shiftKey) {
            e.preventDefault();
            toggleHome();
          }
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (phase === "failed" && fatal) {
    return <Fatal code={fatal.code} message={fatal.message} onRetry={() => void boot()} />;
  }

  // Home mounts under the entrance so first paint is not gated on the sidecar.
  // Splash stays until `phase === "ready"` (prefs in, nothing left to restore)
  // or the person clicks through. `hold-entrance` freezes it for screenshots.
  const showSplash = !entranceDone;
  const sidecarDown = status !== null && !status.running;

  return (
    <div className="shell">
      {showSplash ? (
        <Splash
          note={phaseNote}
          frozen={holdEntrance}
          ready={phase === "ready"}
          onDone={() => setState({ entranceDone: true })}
        />
      ) : null}

      <header className="titlebar">
        {session ? (
          <Tooltip content="홈 (Ctrl+Shift+H)">
            <Button
              variant="ghost"
              className="home-btn"
              data-testid="header-home"
              aria-label="홈"
              aria-pressed={homeOpen}
              onClick={() => goHome()}
            >
              <Icon name="home" />
            </Button>
          </Tooltip>
        ) : null}

        <div className="brand">
          <Logo size={19} />
          <span className="wordmark">Rigorloom</span>
        </div>

        {session ? (
          <Tooltip content="문서로 돌아가기">
            <button
              type="button"
              className="docchip"
              data-testid="doc-tab"
              aria-current={homeOpen ? undefined : "page"}
              onClick={() => {
                leaveHome();
                focusDocumentSurface();
              }}
            >
              <span className="name" data-testid="doc-name">
                {session.source.name}
              </span>
              <span className="latin-caps">{session.source.documentKind}</span>
            </button>
          </Tooltip>
        ) : null}

        <span className="spacer" />

        {panic ? (
          <Tooltip content={`${panic.location} · ${panic.logPath}`}>
            <Badge variant="destructive" className="tag point">
              셸 오류 기록됨
            </Badge>
          </Tooltip>
        ) : null}

        {sidecarDown ? (
          <>
            <Badge variant="destructive" className="tag point" data-testid="sidecar-down">
              런타임 끊김
            </Badge>
            <Button variant="ghost" onClick={() => void restartRuntime()}>
              다시 시작
            </Button>
          </>
        ) : null}

        <DropdownMenu
          open={openMenu}
          onOpenChange={(next) => {
            if (next) setChromeMenu("open");
            else if (getState().chromeMenu === "open") setChromeMenu(null);
          }}
        >
          <DropdownMenuTrigger className="ghost btn-icon" data-testid="header-open-menu">
            <Icon name="open" />
            문서 열기
          </DropdownMenuTrigger>
          <DropdownMenuContent className="toolmenu-body">
            <DropdownMenuItem
              onClick={() => {
                setChromeMenu(null);
                void openViaDialog();
              }}
            >
              <Icon name="open" />
              열기
              <DropdownMenuShortcut>
                <Kbd>Ctrl+O</Kbd>
              </DropdownMenuShortcut>
            </DropdownMenuItem>
            <Tooltip content="빈 양식이나 form_profile.json을 연결해 엽니다">
              <DropdownMenuItem
                data-testid="bind-form"
                onClick={() => {
                  setChromeMenu(null);
                  void bindFormAndOpen();
                }}
              >
                <Icon name="link" />
                양식과 함께 열기
              </DropdownMenuItem>
            </Tooltip>
          </DropdownMenuContent>
        </DropdownMenu>
        <Tooltip content="에이전트 제공자 설정">
          <Button
            variant="ghost"
            className="btn-icon"
            data-testid="open-settings"
            onClick={() => setState({ settingsOpen: true })}
          >
            <Icon name="settings" />
            설정
          </Button>
        </Tooltip>
      </header>

      <div className="viewport">
        <DocumentView />
      </div>

      {/* One mount, outside the view switch: the settings pane is chrome, not
          part of either room, and reopening it after Ctrl+2 must not lose what
          the probe found. */}
      <Settings />
      <CommandPalette />

      {dragOver ? (
        <div className="dropveil" data-testid="dropveil">
          <div className="box">여기에 놓으면 문서를 엽니다</div>
        </div>
      ) : null}

      <Toast />
    </div>
  );
}
