import { useEffect } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";

import {
  boot,
  closeTopmostOverlay,
  copySelection,
  exportApplied,
  navigateScreen,
  openDropped,
  openDroppedFiles,
  openViaDialog,
  resetUiZoom,
  stepUiZoom,
  toggleCommandPalette,
  toggleFullscreen,
} from "./actions";
import { ApprovalDialog } from "./components/ApprovalDialog";
import { BrowserOpenDialog } from "./components/BrowserOpenDialog";
import { CommandPalette } from "./components/CommandPalette";
import { DetailDisclosure } from "./components/DetailDisclosure";
import { Logo } from "./components/Logo";
import { OperatorAgentModal } from "./components/OperatorAgentModal";
import { Settings } from "./components/Settings";
import { Splash } from "./components/Splash";
import { Toast } from "./components/Toast";
import { TopBar } from "./components/TopBar";
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
import { runSmoke, smokeIntent } from "./smoke";
import { OpenView } from "./views/OpenView";
import { ReviewView } from "./views/ReviewView";

const REVIEW_KEY_CODES = new Set([
  "KeyJ",
  "KeyK",
  "KeyA",
  "KeyR",
  "KeyD",
  "KeyE",
  "ArrowDown",
  "ArrowUp",
  "Enter",
  "Backspace",
  "Delete",
  "BracketLeft",
  "BracketRight",
]);

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
  const screen = useWorkspace((s) => s.screen);
  const language = useWorkspace((s) => s.language);
  const phase = useWorkspace((s) => s.phase);
  const phaseNote = useWorkspace((s) => s.phaseNote);
  const fatal = useWorkspace((s) => s.fatal);
  const entranceDone = useWorkspace((s) => s.entranceDone);
  const holdEntrance = useWorkspace((s) => s.holdEntrance);
  const dragOver = useWorkspace((s) => s.dragOver);
  const lastCommit = useWorkspace((s) => s.lastCommit);
  const session = useWorkspace(activeSession);

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
                else if (event.payload.type === "drop") void openDropped(event.payload.paths);
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
          if (files.length > 0) void openDroppedFiles(files);
          else setState({ dragOver: false });
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

  // Global keyboard & Korean IME guard (Ruling H).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing || e.keyCode === 229) {
        return;
      }

      if (e.key === "F11") {
        e.preventDefault();
        void toggleFullscreen();
        return;
      }

      const mod = e.ctrlKey || e.metaKey;
      if (mod && !e.altKey && (e.code === "KeyK" || e.key.toLowerCase() === "k")) {
        e.preventDefault();
        toggleCommandPalette();
        return;
      }

      if (e.key === "Escape") {
        if (closeTopmostOverlay()) e.preventDefault();
        return;
      }

      const target = e.target as HTMLElement | null;
      const isEditable =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        Boolean(target?.isContentEditable);
      if (isEditable) return;

      if (mod && !e.altKey) {
        switch (e.code) {
          case "KeyO":
            e.preventDefault();
            navigateScreen("open");
            void openViaDialog();
            return;
          case "Digit1":
            if (getState().activeSessionId) {
              e.preventDefault();
              navigateScreen("review");
            }
            return;
          case "Comma":
            e.preventDefault();
            setState({ settingsOpen: true });
            return;
          case "KeyE":
            if (getState().activeSessionId) {
              e.preventDefault();
              void exportApplied();
            }
            return;
          case "Equal":
            e.preventDefault();
            stepUiZoom(1);
            return;
          case "Minus":
            e.preventDefault();
            stepUiZoom(-1);
            return;
          case "Digit0":
            e.preventDefault();
            resetUiZoom();
            return;
          case "KeyC":
            void copySelection();
            return;
          default:
            break;
        }
        return;
      }

      if (!mod && !e.altKey) {
        const current = getState();
        const modalOpen =
          current.commandPaletteOpen ||
          current.operatorModalOpen ||
          current.settingsOpen ||
          current.openDialogOpen ||
          current.approvalDialogOpen ||
          current.returnPopoverOpen;
        if (current.screen === "review" && !modalOpen && REVIEW_KEY_CODES.has(e.code)) {
          e.preventDefault();
          window.dispatchEvent(
            new CustomEvent("rigorloom:review-key", {
              detail: { code: e.code, key: e.key, shiftKey: e.shiftKey },
            }),
          );
        }
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (phase === "failed" && fatal) {
    return <Fatal code={fatal.code} message={fatal.message} onRetry={() => void boot()} />;
  }

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

  const activeScreen = screen === "review" && session ? "review" : "open";

  return (
    <div
      className="shell"
      data-session={session?.sessionId ?? ""}
      data-last-composed={lastCommit ? String(lastCommit.composed) : ""}
      data-last-commit={lastCommit ? lastCommit.value : ""}
    >
      <TopBar />

      <div className="viewport">
        {activeScreen === "review" ? <ReviewView /> : <OpenView />}
      </div>

      <Settings />
      <BrowserOpenDialog />
      <ApprovalDialog />
      <CommandPalette />
      <OperatorAgentModal />

      {dragOver ? (
        <div className="dropveil" data-testid="dropveil">
          <div className="box">{t("open_drop_prompt", language)}</div>
        </div>
      ) : null}

      <Toast />
    </div>
  );
}
