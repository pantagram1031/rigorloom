import { useEffect, useRef, useState } from "react";
import {
  exportApplied,
  loadGeometry,
  navigateScreen,
  openCommandPalette,
  renderCurrentPage,
  restartRuntime,
  revisionNumberFor,
  togglePrintView,
} from "../actions";
import { errorCodeMessage, t } from "../i18n/vocabulary";
import {
  activeSession,
  headCandidate,
  setPageFit,
  setZoom,
  useWorkspace,
} from "../store";
import { getSessionDisplayTitle } from "../workspace/openHelpers";
import { Logo } from "./Logo";

export function TopBar() {
  const session = useWorkspace(activeSession);
  const screen = useWorkspace((s) => s.screen);
  const language = useWorkspace((s) => s.language);
  const status = useWorkspace((s) => s.status);
  const applied = useWorkspace((s) => s.applied);
  const head = useWorkspace(headCandidate);
  const openedPaths = useWorkspace((s) => s.openedPaths);
  const corpusFiles = useWorkspace((s) => s.corpusFiles);
  const zoom = useWorkspace((s) => s.zoom);
  const pageFit = useWorkspace((s) => s.pageFit);
  const mobileExplicitFit = useWorkspace((s) => s.mobileExplicitFit);
  const page = useWorkspace((s) => s.page);
  const printViewEnabled = useWorkspace((s) => s.printViewEnabled);
  const capabilities = useWorkspace((s) => s.capabilities);
  const render = useWorkspace((s) => s.render);
  const workspaceState = useWorkspace((s) => s);

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  const sidecarDown = status !== null && !status.running;
  const exportRunId =
    session && applied?.sessionId === session.sessionId
      ? applied.runId
      : session
        ? (head?.runId ?? null)
        : null;
  const canExport = Boolean(session && exportRunId);
  const exportRevNum = revisionNumberFor(workspaceState, session?.sessionId, exportRunId);
  const exportLabel = exportRevNum
    ? t("action_export_revision", language, [exportRevNum])
    : t("action_export", language);
  const showSheetMenuControls = Boolean(session && (screen === "review" || screen === "fill"));
  const canTryPrintView = Boolean(
    capabilities?.render?.rasterizer?.state === "yes" || render?.available,
  );
  const isMobileWidthFit =
    pageFit === "width" && (screen === "fill" || mobileExplicitFit);
  const effectiveMenuZoom = !isMobileWidthFit && pageFit === "width" ? 1 : zoom;
  const displayZoomPct = Math.round(effectiveMenuZoom * 100);
  const docTitle = session
    ? getSessionDisplayTitle(session, openedPaths, corpusFiles, language)
    : t("doc_none_open", language);
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
            title={docTitle}
          >
            {docTitle}
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
            aria-current={screen === "fill" ? "page" : undefined}
            data-testid="nav-fill"
            disabled={!session}
            onClick={() => navigateScreen("fill")}
          >
            {t("nav_fill", language)}
          </button>
          <button
            type="button"
            className="topbar-tab"
            aria-current={screen === "history" ? "page" : undefined}
            data-testid="nav-history"
            disabled={!session}
            onClick={() => navigateScreen("history")}
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

        <div className="topbar-desktop-actions">
          {canExport ? (
            <button
              type="button"
              className="topbar-btn topbar-btn--primary"
              data-testid="topbar-export"
              onClick={() => void exportApplied(undefined, exportRunId ?? undefined)}
            >
              {exportLabel}
            </button>
          ) : null}

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
            aria-current={screen === "settings" ? "page" : undefined}
            data-testid="open-settings"
            onClick={() => navigateScreen("settings")}
          >
            {t("nav_settings", language)}
          </button>
        </div>

        <div className="topbar-mobile-menu" ref={menuRef}>
          <button
            type="button"
            className={`topbar-btn topbar-menu-trigger${
              screen === "settings" ? " topbar-menu-trigger--active" : ""
            }`}
            data-testid="topbar-menu-btn"
            aria-current={screen === "settings" ? "page" : undefined}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            onClick={() => setMenuOpen((prev) => !prev)}
          >
            {t("topbar_more_menu", language)}
          </button>

          {menuOpen ? (
            <div
              className="topbar-menu-popover"
              role="menu"
              data-testid="topbar-menu-popover"
            >
              {session ? (
                <>
                  <button
                    type="button"
                    role="menuitem"
                    className="topbar-menu-item"
                    aria-current={screen === "fill" ? "page" : undefined}
                    data-testid="topbar-menu-fill"
                    onClick={() => {
                      setMenuOpen(false);
                      navigateScreen("fill");
                    }}
                  >
                    {t("nav_fill", language)}
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="topbar-menu-item"
                    aria-current={screen === "history" ? "page" : undefined}
                    data-testid="topbar-menu-history"
                    onClick={() => {
                      setMenuOpen(false);
                      navigateScreen("history");
                    }}
                  >
                    {t("nav_history", language)}
                  </button>
                  <div className="topbar-menu-divider" role="separator" />
                </>
              ) : null}
              {showSheetMenuControls ? (
                <>
                  <button
                    type="button"
                    role="menuitem"
                    className="topbar-menu-item"
                    data-testid="topbar-menu-print-view"
                    disabled={!canTryPrintView && !printViewEnabled}
                    title={
                      !canTryPrintView && !printViewEnabled
                        ? errorCodeMessage("render_unavailable", language)
                        : undefined
                    }
                    onClick={() => {
                      const turningOn = !printViewEnabled;
                      togglePrintView(turningOn);
                      if (turningOn) {
                        void renderCurrentPage(page);
                        void loadGeometry(page);
                      }
                      setMenuOpen(false);
                    }}
                  >
                    {printViewEnabled
                      ? t("review_mode_document", language)
                      : t("review_mode_print", language)}
                  </button>
                  <div
                    className="topbar-menu-zoom-row"
                    data-testid="topbar-menu-zoom"
                    role="group"
                    aria-label={t("review_zoom_label", language, [displayZoomPct])}
                  >
                    <button
                      type="button"
                      className="topbar-menu-zoom-btn"
                      data-testid="topbar-menu-zoom-out"
                      disabled={effectiveMenuZoom <= 0.5}
                      aria-label={t("review_zoom_out", language)}
                      onClick={() =>
                        setZoom(Math.max(0.5, Number((effectiveMenuZoom - 0.1).toFixed(2))))
                      }
                    >
                      −
                    </button>
                    <button
                      type="button"
                      className="topbar-menu-zoom-btn"
                      data-testid="topbar-menu-zoom-fit"
                      onClick={() =>
                        isMobileWidthFit ? setZoom(1) : setPageFit("width")
                      }
                    >
                      {isMobileWidthFit
                        ? t("review_zoom_label", language, [100])
                        : t("review_zoom_fit", language)}
                    </button>
                    <button
                      type="button"
                      className="topbar-menu-zoom-btn"
                      data-testid="topbar-menu-zoom-in"
                      disabled={effectiveMenuZoom >= 2.0}
                      aria-label={t("review_zoom_in", language)}
                      onClick={() =>
                        setZoom(Math.min(2.0, Number((effectiveMenuZoom + 0.1).toFixed(2))))
                      }
                    >
                      +
                    </button>
                  </div>
                  <div className="topbar-menu-divider" role="separator" />
                </>
              ) : null}
              {canExport ? (
                <button
                  type="button"
                  role="menuitem"
                  className="topbar-menu-item topbar-menu-item--primary"
                  data-testid="topbar-menu-export"
                  onClick={() => {
                    setMenuOpen(false);
                    void exportApplied(undefined, exportRunId ?? undefined);
                  }}
                >
                  {exportLabel}
                </button>
              ) : null}
              <button
                type="button"
                role="menuitem"
                className="topbar-menu-item"
                data-testid="topbar-menu-palette"
                onClick={() => {
                  setMenuOpen(false);
                  openCommandPalette();
                }}
              >
                {t("action_command_palette", language)}
              </button>
              <button
                type="button"
                role="menuitem"
                className="topbar-menu-item"
                aria-current={screen === "settings" ? "page" : undefined}
                data-testid="topbar-menu-settings"
                onClick={() => {
                  setMenuOpen(false);
                  navigateScreen("settings");
                }}
              >
                {t("nav_settings", language)}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
