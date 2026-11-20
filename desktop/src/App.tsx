import { useEffect, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";

import { boot } from "./actions";
import { ApprovalDialog } from "./components/ApprovalDialog";
import { DetailDisclosure } from "./components/DetailDisclosure";
import { Logo } from "./components/Logo";
import { Splash } from "./components/Splash";
import { Toast } from "./components/Toast";
import { deliverDocumentEvents, stopDocumentEvents } from "./documentEvents";
import { errorCodeMessage, t } from "./i18n/vocabulary";
import * as rt from "./runtime";
import { RuntimeSubscriptionScope } from "./runtimeSubscriptions";
import {
  activeSession,
  getState,
  pushActivity,
  pushHostEvents,
  setState,
  useWorkspace,
} from "./store";
import { runSmoke, smokeIntent, smokeNeedsLegacy } from "./smoke";
import "./shell/registrations";
import { engineState } from "./shell/docInfo";
import { isLegacyUi, LegacyApp } from "./shell/LegacyApp";
import { openDroppedFileList, openDroppedPaths } from "./shell/open";
import { Shell } from "./shell/Shell";
import { setUiVariant } from "./uiVariant";


function Boot({ note }: { note: string }) {
  const language = useWorkspace((s) => s.language);
  return (
    <div className="boot" data-testid="boot">
      <Logo size={48} className="mark" />
      <div className="bar">
        <i />
      </div>
      <p className="note">{note || t("splash_loading", language)}</p>
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
  const language = useWorkspace((s) => s.language);
  return (
    <div className="boot">
      <div className="fatal" data-testid="fatal">
        <h2>{t("fatal_title", language)}</h2>
        <p className="prose">{errorCodeMessage(code, language)}</p>
        <div style={{ marginTop: "var(--space-2)" }}>
          <DetailDisclosure>
            <div>
              {code}
              {message ? ` · ${message}` : ""}
            </div>
          </DetailDisclosure>
        </div>
        <button className="action primary" style={{ marginTop: "var(--space-2)" }} onClick={onRetry}>
          {t("error_boundary_retry", language)}
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const [legacy, setLegacy] = useState(isLegacyUi);
  const language = useWorkspace((s) => s.language);
  const phase = useWorkspace((s) => s.phase);
  const phaseNote = useWorkspace((s) => s.phaseNote);
  const fatal = useWorkspace((s) => s.fatal);
  const entranceDone = useWorkspace((s) => s.entranceDone);
  const holdEntrance = useWorkspace((s) => s.holdEntrance);
  const lastCommit = useWorkspace((s) => s.lastCommit);
  const session = useWorkspace(activeSession);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = language;
    }
  }, [language]);

  useEffect(() => {
    const subscriptions = new RuntimeSubscriptionScope();

    (async () => {
      if (!(await subscriptions.add(rt.onActivity(pushActivity)))) return;
      if (!(await subscriptions.add(rt.onEvents(deliverDocumentEvents)))) return;
      if (!(await subscriptions.add(rt.onAgentEvents(pushHostEvents)))) return;
      if (!(await subscriptions.add(rt.onStatus((s) => setState({ status: s }))))) return;
      if (!(await subscriptions.add(rt.onPanic((p) => setState({ panic: p }))))) return;

      if (rt.isTauri()) {
        try {
          if (
            !(await subscriptions.add(
              getCurrentWebview().onDragDropEvent((event) => {
                if (event.payload.type === "over") setState({ dragOver: true });
                else if (event.payload.type === "drop") {
                  setState({ dragOver: false });
                  void openDroppedPaths(event.payload.paths);
                }
                else setState({ dragOver: false });
              }),
            ))
          ) {
            return;
          }
        } catch {
          // Drag-drop is an affordance; file dialog remains available.
        }
      } else if (typeof window !== "undefined") {
        const onDragOver = (e: DragEvent) => {
          if (e.dataTransfer?.types?.includes("Files")) {
            e.preventDefault();
            if (!getState().dragOver) setState({ dragOver: true });
          }
        };
        const onDragLeave = (e: DragEvent) => {
          if (e.relatedTarget === null) setState({ dragOver: false });
        };
        const onDrop = (e: DragEvent) => {
          e.preventDefault();
          const files = Array.from(e.dataTransfer?.files ?? []);
          setState({ dragOver: false });
          if (files.length > 0) void openDroppedFileList(files);
        };
        window.addEventListener("dragover", onDragOver);
        window.addEventListener("dragleave", onDragLeave);
        window.addEventListener("drop", onDrop);
        subscriptions
          .add(
            Promise.resolve(() => {
              window.removeEventListener("dragover", onDragOver);
              window.removeEventListener("dragleave", onDragLeave);
              window.removeEventListener("drop", onDrop);
            }),
          )
          .catch(() => {});
      }

      const intent = await smokeIntent();
      if (subscriptions.isDisposed) return;
      // `open` and `edit` drive the v2 editor; the smoke phases not yet ported
      // still run on the v1 screens. v1 is the default, so each phase picks.
      if (intent) {
        const legacyPhase = smokeNeedsLegacy(intent);
        setUiVariant(legacyPhase ? "v1" : "v2");
        setLegacy(legacyPhase);
      }
      if (intent?.phase === "hold-entrance") setState({ holdEntrance: true });

      await boot();
      if (subscriptions.isDisposed) return;
      await runSmoke();
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

  if (phase === "failed" && fatal && engineState(getState()) !== "missing") {
    return <Fatal code={fatal.code} message={fatal.message} onRetry={() => void boot()} />;
  }

  const showSplash = !entranceDone;
  if (phase !== "ready" && !(phase === "failed" && fatal)) {
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

  if (legacy) return <LegacyApp />;

  return (
    <div
      className="shell-v2"
      data-session={session?.sessionId ?? ""}
      data-last-composed={lastCommit ? String(lastCommit.composed) : ""}
      data-last-commit={lastCommit ? lastCommit.value : ""}
    >
      <Shell />
      <ApprovalDialog />
      <Toast />
    </div>
  );
}
