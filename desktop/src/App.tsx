import { useEffect, useRef } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";

import {
  boot,
  copySelection,
  openDropped,
  openViaDialog,
  resetUiZoom,
  restartRuntime,
  selectSession,
  stepUiZoom,
} from "./actions";
import { Logo } from "./components/Logo";
import { Splash } from "./components/Splash";
import { Toast } from "./components/Toast";
import * as rt from "./runtime";
import {
  getState,
  pushActivity,
  pushEvents,
  setState,
  setView,
  useWorkspace,
  type View,
} from "./store";
import { AgentView } from "./views/AgentView";
import { DocumentView } from "./views/DocumentView";
import { runSmoke, smokeIntent } from "./smoke";

/** Fallback for the window between React mounting and the entrance ending. */
function Boot({ note }: { note: string }) {
  return (
    <div className="boot" data-testid="boot">
      <Logo size={48} className="mark" />
      <div className="bar">
        <i />
      </div>
      <p className="note">{note || "여는 중"}</p>
    </div>
  );
}

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
        <button className="action primary" style={{ marginTop: "var(--s4)" }} onClick={onRetry}>
          다시 시도
        </button>
      </div>
    </div>
  );
}

/** Document sits left of Agent on one axis, so the slide direction has meaning. */
const AXIS: Record<View, number> = { document: 0, agent: 1 };

function switchView(next: View) {
  if (getState().view === next) return;
  setView(next);
  void rt.savePrefs({ lastView: next });
}

export default function App() {
  const view = useWorkspace((s) => s.view);
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

  // Which way the incoming view travels. Held in a ref so a re-render for any
  // other reason does not replay the transition.
  const previousAxis = useRef(AXIS[view]);
  const direction = AXIS[view] >= previousAxis.current ? "right" : "left";
  useEffect(() => {
    previousAxis.current = AXIS[view];
  }, [view]);

  useEffect(() => {
    const unlisteners: Array<() => void> = [];
    let cancelled = false;

    (async () => {
      unlisteners.push(await rt.onActivity(pushActivity));
      // The document's own history. Arrives as batched `event` notifications,
      // already split from protocol chatter in Rust; the store de-duplicates
      // on `seq`, so a replay after a reconnect is idempotent.
      unlisteners.push(
        await rt.onEvents((batch) => pushEvents(batch.map((row) => row.event))),
      );
      unlisteners.push(await rt.onStatus((s) => setState({ status: s })));
      // A Rust panic must be visible, not a silent disappearance.
      unlisteners.push(await rt.onPanic((p) => setState({ panic: p })));

      // Files dropped on the window. The webview owns the event; the runtime
      // owns everything that happens to the bytes afterwards.
      try {
        const off = await getCurrentWebview().onDragDropEvent((event) => {
          if (event.payload.type === "over") setState({ dragOver: true });
          else if (event.payload.type === "drop") void openDropped(event.payload.paths);
          else setState({ dragOver: false });
        });
        unlisteners.push(off);
      } catch {
        // Drag-drop is an affordance, not a dependency: the dialog still works.
      }

      // Read the launcher's intent before boot: the entrance screenshot needs
      // the splash pinned open, and it is gone 960 ms after mount otherwise.
      const intent = await smokeIntent();
      if (intent?.phase === "hold-entrance") setState({ holdEntrance: true });

      if (cancelled) return;
      await boot();
      // Scripted evidence runs against the built app, through the same
      // actions a click uses. No-op unless the launcher asked for it.
      await runSmoke();
    })();

    return () => {
      cancelled = true;
      for (const off of unlisteners) off();
    };
  }, []);

  // Keyboard. Ctrl+O open · Ctrl+1/2 views · Ctrl+= / - / 0 app zoom ·
  // Ctrl+C copies the selected cell's text.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // A shortcut must never reach past a text field the user is typing in.
      // Ctrl+C inside the inline editor is a copy, not a "copy the selected
      // cell", and Ctrl+O while composing Hangul would throw the edit away.
      const target = e.target as HTMLElement | null;
      const typing =
        target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
      if (typing) return;
      if (!e.ctrlKey || e.altKey) return;
      switch (e.key) {
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

  // The entrance covers the cold start; underneath, the app boots for real.
  const showSplash = !entranceDone;
  if (phase !== "ready") {
    return (
      <>
        {showSplash ? (
          <Splash
            note={phaseNote}
            frozen={holdEntrance}
            onDone={() => setState({ entranceDone: true })}
          />
        ) : (
          <Boot note={phaseNote} />
        )}
      </>
    );
  }

  const sidecarDown = status !== null && !status.running;

  return (
    <div className="shell">
      {showSplash ? (
        <Splash note={phaseNote} onDone={() => setState({ entranceDone: true })} />
      ) : null}

      <header className="titlebar">
        <div className="brand">
          <Logo size={19} />
          <span className="wordmark">Rigorloom</span>
        </div>

        <div className="viewswitch" role="group" aria-label="화면 전환">
          <button
            aria-pressed={view === "document"}
            data-testid="switch-document"
            title="문서 (Ctrl+1)"
            onClick={() => switchView("document")}
          >
            문서
          </button>
          <button
            aria-pressed={view === "agent"}
            data-testid="switch-agent"
            title="작업 (Ctrl+2)"
            onClick={() => switchView("agent")}
          >
            작업
          </button>
        </div>

        {session ? (
          <div className="docchip">
            <span className="name" data-testid="doc-name">
              {session.source.name}
            </span>
            <span className="latin-caps">{session.source.documentKind}</span>
          </div>
        ) : null}

        <span className="spacer" />

        {panic ? (
          <span className="tag point" title={`${panic.location} · ${panic.logPath}`}>
            셸 오류 기록됨
          </span>
        ) : null}

        {sidecarDown ? (
          <>
            <span className="tag point" data-testid="sidecar-down">
              런타임 끊김
            </span>
            <button className="ghost" onClick={() => void restartRuntime()}>
              다시 시작
            </button>
          </>
        ) : null}

        <button className="ghost" title="Ctrl+O" onClick={() => void openViaDialog()}>
          문서 열기
        </button>
      </header>

      <div className="viewport">
        <div key={view} className={`view-enter-from-${direction}`} style={{ height: "100%" }}>
          {view === "document" ? (
            <DocumentView />
          ) : (
            <AgentView
              onOpen={() => void openViaDialog()}
              onSelectSession={(id) => void selectSession(id)}
            />
          )}
        </div>
      </div>

      {dragOver ? (
        <div className="dropveil" data-testid="dropveil">
          <div className="box">여기에 놓으면 문서를 엽니다</div>
        </div>
      ) : null}

      <Toast />
    </div>
  );
}
