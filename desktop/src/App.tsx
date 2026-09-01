import { useEffect } from "react";

import { boot, openViaDialog, restartRuntime, selectSession } from "./actions";
import * as rt from "./runtime";
import { pushActivity, setState, setView, useWorkspace } from "./store";
import { AgentView } from "./views/AgentView";
import { DocumentView } from "./views/DocumentView";
import { runSmoke } from "./smoke";

/** The designed loading state. ~1.5 s to first usable paint is measured, not
 *  hoped for (spike finding 4), so it is a state with words in it. */
function Boot({ note }: { note: string }) {
  return (
    <div className="boot" data-testid="boot">
      <div className="mark">리고룸</div>
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

export default function App() {
  const view = useWorkspace((s) => s.view);
  const phase = useWorkspace((s) => s.phase);
  const phaseNote = useWorkspace((s) => s.phaseNote);
  const fatal = useWorkspace((s) => s.fatal);
  const status = useWorkspace((s) => s.status);
  const panic = useWorkspace((s) => s.panic);
  const session = useWorkspace((s) =>
    s.sessions.find((x) => x.sessionId === s.activeSessionId) ?? null,
  );

  useEffect(() => {
    const unlisteners: Array<() => void> = [];
    let cancelled = false;

    (async () => {
      unlisteners.push(await rt.onActivity(pushActivity));
      unlisteners.push(await rt.onStatus((s) => setState({ status: s })));
      // M17: a Rust panic must be visible, not a silent disappearance.
      unlisteners.push(await rt.onPanic((p) => setState({ panic: p })));
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

  if (phase === "failed" && fatal) {
    return <Fatal code={fatal.code} message={fatal.message} onRetry={() => void boot()} />;
  }
  if (phase !== "ready") {
    return <Boot note={phaseNote} />;
  }

  const sidecarDown = status !== null && !status.running;

  return (
    <div className="shell">
      <header className="titlebar">
        <span className="wordmark">리고룸</span>

        <div className="viewswitch" role="group" aria-label="화면 전환">
          <button
            aria-pressed={view === "document"}
            data-testid="switch-document"
            onClick={() => {
              setView("document");
              void rt.savePrefs({ lastView: "document" });
            }}
          >
            문서
          </button>
          <button
            aria-pressed={view === "agent"}
            data-testid="switch-agent"
            onClick={() => {
              setView("agent");
              void rt.savePrefs({ lastView: "agent" });
            }}
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
          <span className="tag bad" title={`${panic.location} · ${panic.logPath}`}>
            셸 오류 기록됨
          </span>
        ) : null}

        {sidecarDown ? (
          <>
            <span className="tag bad" data-testid="sidecar-down">
              런타임 끊김
            </span>
            <button className="action" onClick={() => void restartRuntime()}>
              다시 시작
            </button>
          </>
        ) : null}

        <button className="action" onClick={() => void openViaDialog()}>
          문서 열기
        </button>
      </header>

      {view === "document" ? (
        <DocumentView onOpen={() => void openViaDialog()} />
      ) : (
        <AgentView
          onOpen={() => void openViaDialog()}
          onSelectSession={(id) => void selectSession(id)}
        />
      )}
    </div>
  );
}
