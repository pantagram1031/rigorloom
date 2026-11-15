import {
  navigateScreen,
  openCommandPalette,
  restartRuntime,
  exportApplied,
} from "../actions";
import { errorCodeMessage, t } from "../i18n/vocabulary";
import { activeSession, headCandidate, setState, useWorkspace } from "../store";
import { Logo } from "./Logo";

export function TopBar() {
  const session = useWorkspace(activeSession);
  const screen = useWorkspace((s) => s.screen);
  const language = useWorkspace((s) => s.language);
  const status = useWorkspace((s) => s.status);
  const applied = useWorkspace((s) => s.applied);
  const head = useWorkspace(headCandidate);

  const sidecarDown = status !== null && !status.running;
  const canExport = Boolean(session && (applied?.runId ?? head?.runId));
  const isMac =
    typeof navigator !== "undefined" && /Mac|iPhone|iPad/i.test(navigator.platform);
  const paletteShortcut = isMac ? "⌘K" : "Ctrl+K";

  return (
    <header className="topbar" data-testid="topbar">
      <div className="topbar-left">
        <div className="topbar-brand">
          <Logo size={18} />
          <span
            className="topbar-doc-title"
            data-testid="doc-name"
            title={session?.source.name ?? t("doc_none_open", language)}
          >
            {session ? session.source.name : t("doc_none_open", language)}
          </span>
        </div>

        <nav className="topbar-nav" aria-label={t("nav_open", language)}>
          <button
            type="button"
            className="topbar-tab"
            aria-current={screen === "open" ? "page" : undefined}
            data-testid="nav-open"
            onClick={() => navigateScreen("open")}
          >
            {t("nav_open", language)}
          </button>
          <button
            type="button"
            className="topbar-tab"
            aria-current={screen === "review" ? "page" : undefined}
            data-testid="nav-review"
            disabled={!session}
            onClick={() => navigateScreen("review")}
          >
            {t("nav_review", language)}
          </button>
          <button
            type="button"
            className="topbar-tab"
            data-testid="nav-fill"
            disabled
            aria-disabled="true"
          >
            {t("nav_fill", language)}
          </button>
          <button
            type="button"
            className="topbar-tab"
            data-testid="nav-history"
            disabled
            aria-disabled="true"
          >
            {t("nav_history", language)}
          </button>
        </nav>
      </div>

      <div className="topbar-right">
        {sidecarDown ? (
          <button
            type="button"
            className="topbar-btn topbar-btn--warn"
            data-testid="sidecar-down"
            title={errorCodeMessage("not_initialized", language)}
            onClick={() => void restartRuntime()}
          >
            {t("error_boundary_retry", language)}
          </button>
        ) : null}

        <button
          type="button"
          className="topbar-btn"
          data-testid="topbar-export"
          disabled={!canExport}
          onClick={() => void exportApplied()}
        >
          {t("action_export", language)}
        </button>

        <button
          type="button"
          className="topbar-btn"
          data-testid="topbar-palette"
          onClick={() => openCommandPalette()}
        >
          <span>{t("action_command_palette", language)}</span>
          <kbd className="topbar-kbd">{paletteShortcut}</kbd>
        </button>

        <button
          type="button"
          className="topbar-btn topbar-btn--subtle"
          data-testid="open-settings"
          onClick={() => setState({ settingsOpen: true })}
        >
          {t("nav_settings", language)}
        </button>
      </div>
    </header>
  );
}
