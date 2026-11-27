/**
 * The previous v1 screens (열기/검토/채우기/기록/설정). Editor v2 is now the
 * default window; v1 stays reachable with `?ui=v1`, Settings, the palette
 * command, or `"editorVariant": "v1"` in prefs.json (uiVariant.ts).
 */
import { useEffect } from "react";

import {
  closeTopmostOverlay,
  copySelection,
  exportApplied,
  navigateScreen,
  openViaDialog,
  resetUiZoom,
  stepUiZoom,
  toggleCommandPalette,
  toggleFullscreen,
} from "../actions";
import { ApprovalDialog } from "../components/ApprovalDialog";
import { BrowserOpenDialog } from "../components/BrowserOpenDialog";
import { CommandPalette } from "../components/CommandPalette";
import { OperatorAgentModal } from "../components/OperatorAgentModal";
import { Toast } from "../components/Toast";
import { TopBar } from "../components/TopBar";
import { t } from "../i18n/vocabulary";
import { activeSession, getState, useWorkspace } from "../store";
import { uiVariant } from "../uiVariant";
import { FillView } from "../views/FillView";
import { HistoryView } from "../views/HistoryView";
import { OpenView } from "../views/OpenView";
import { ReviewView } from "../views/ReviewView";
import { SettingsView } from "../views/SettingsView";
import "../styles.css";

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

/** Editor v2 is the default; true when the previous v1 screens were chosen (uiVariant.ts). */
export function isLegacyUi(): boolean {
  return uiVariant() === "v1";
}

export function LegacyApp() {
  const screen = useWorkspace((s) => s.screen);
  const language = useWorkspace((s) => s.language);
  const dragOver = useWorkspace((s) => s.dragOver);
  const lastCommit = useWorkspace((s) => s.lastCommit);
  const session = useWorkspace(activeSession);

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
          case "Digit2":
            if (getState().activeSessionId) {
              e.preventDefault();
              navigateScreen("fill");
            }
            return;
          case "Digit3":
            if (getState().activeSessionId) {
              e.preventDefault();
              navigateScreen("history");
            }
            return;
          case "Comma":
            e.preventDefault();
            navigateScreen("settings");
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

  const activeScreen =
    screen === "settings"
      ? "settings"
      : screen === "history" && session
        ? "history"
        : screen === "fill" && session
          ? "fill"
          : screen === "review" && session
            ? "review"
            : "open";

  return (
    <div
      className="shell"
      data-session={session?.sessionId ?? ""}
      data-last-composed={lastCommit ? String(lastCommit.composed) : ""}
      data-last-commit={lastCommit ? lastCommit.value : ""}
    >
      <TopBar />

      <div className="viewport">
        {activeScreen === "settings" ? (
          <SettingsView />
        ) : activeScreen === "history" ? (
          <HistoryView />
        ) : activeScreen === "review" ? (
          <ReviewView />
        ) : activeScreen === "fill" ? (
          <FillView />
        ) : (
          <OpenView />
        )}
      </div>

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
