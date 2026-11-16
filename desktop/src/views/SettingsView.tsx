import { open as openFileDialog } from "@tauri-apps/plugin-dialog";
import { useState, type FormEvent } from "react";

import {
  isWorkspaceFolderLocked,
  setLanguage,
  switchWorkspaceRoot,
  toggleTheme,
} from "../actions";
import { DetailDisclosure } from "../components/DetailDisclosure";
import { errorCodeMessage, t } from "../i18n/vocabulary";
import * as rt from "../runtime";
import { useWorkspace } from "../store";
import type { RuntimeError } from "../types";
import "./settings.css";

function folderBasename(path: string | null | undefined): string {
  if (!path) return "workspace";
  const cleaned = path.replace(/[\\/]+$/, "");
  if (!cleaned) return path;
  const parts = cleaned.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? cleaned;
}

export function SettingsView() {
  const language = useWorkspace((s) => s.language);
  const theme = useWorkspace((s) => s.theme);
  const root = useWorkspace((s) => s.root);
  const status = useWorkspace((s) => s.status);
  const folderLocked = useWorkspace(isWorkspaceFolderLocked);

  const [editingFolder, setEditingFolder] = useState(false);
  const [folderInput, setFolderInput] = useState("");
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<RuntimeError | null>(null);

  const applyRootPath = async (nextPath: string) => {
    setSwitching(true);
    setSwitchError(null);
    try {
      const res = await switchWorkspaceRoot(nextPath);
      if (res.ok) {
        setEditingFolder(false);
        setFolderInput("");
      } else if (res.error) {
        setSwitchError(res.error);
      }
    } finally {
      setSwitching(false);
    }
  };

  const handleChangeFolderClick = async () => {
    if (folderLocked || switching) return;
    setSwitchError(null);
    if (rt.isTauri()) {
      const picked = await openFileDialog({
        directory: true,
        multiple: false,
        defaultPath: root ?? undefined,
      }).catch(() => null);
      if (typeof picked === "string" && picked.trim()) {
        await applyRootPath(picked);
      }
      return;
    }
    setFolderInput(root ?? "");
    setEditingFolder((prev) => !prev);
  };

  const handleFormSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!folderInput.trim() || folderLocked || switching) return;
    await applyRootPath(folderInput);
  };

  const handleUseDefaultFolder = async () => {
    if (folderLocked || switching) return;
    const def = await rt.defaultRoot().catch(() => null);
    if (def) {
      await applyRootPath(def);
    }
  };

  const folderDisplayName = folderBasename(root);

  return (
    <main className="settings-view" data-testid="settings-view">
      <div className="settings-container">
        <h1 className="settings-title">{t("settings_title", language)}</h1>

        {/* Section 1: Language (Korean / English autonyms, one at a time) */}
        <section
          className="settings-card"
          data-testid="settings-section-language"
          aria-label={t("settings_section_language", language)}
        >
          <div className="settings-row-head">
            <h2 className="settings-section-title">
              {t("settings_section_language", language)}
            </h2>
            <div className="settings-segmented" role="group" aria-label={t("settings_section_language", language)}>
              <button
                type="button"
                className={`settings-seg-btn${language === "ko" ? " settings-seg-btn--active" : ""}`}
                data-testid="settings-lang-ko"
                aria-pressed={language === "ko"}
                onClick={() => void setLanguage("ko")}
              >
                {t("lang_ko", "ko")}
              </button>
              <button
                type="button"
                className={`settings-seg-btn${language === "en" ? " settings-seg-btn--active" : ""}`}
                data-testid="settings-lang-en"
                aria-pressed={language === "en"}
                onClick={() => void setLanguage("en")}
              >
                English
              </button>
            </div>
          </div>
          <p className="settings-note" data-testid="settings-language-note">
            {t("settings_language_note", language)}
          </p>
        </section>

        {/* Section 2: Appearance / Theme */}
        <section
          className="settings-card"
          data-testid="settings-section-theme"
          aria-label={t("settings_section_theme", language)}
        >
          <div className="settings-row-head">
            <h2 className="settings-section-title">
              {t("settings_section_theme", language)}
            </h2>
            <div className="settings-segmented" role="group" aria-label={t("settings_section_theme", language)}>
              <button
                type="button"
                className={`settings-seg-btn${theme === "light" ? " settings-seg-btn--active" : ""}`}
                data-testid="settings-theme-light"
                aria-pressed={theme === "light"}
                onClick={() => void toggleTheme("light")}
              >
                {t("theme_light", language)}
              </button>
              <button
                type="button"
                className={`settings-seg-btn${theme === "dark" ? " settings-seg-btn--active" : ""}`}
                data-testid="settings-theme-dark"
                aria-pressed={theme === "dark"}
                onClick={() => void toggleTheme("dark")}
              >
                {t("theme_dark", language)}
              </button>
              <button
                type="button"
                className={`settings-seg-btn${theme === "auto" ? " settings-seg-btn--active" : ""}`}
                data-testid="settings-theme-auto"
                aria-pressed={theme === "auto"}
                onClick={() => void toggleTheme("auto")}
              >
                {t("theme_system", language)}
              </button>
            </div>
          </div>
          <p className="settings-note" data-testid="settings-theme-note">
            {t("settings_theme_note", language)}
          </p>
        </section>

        {/* Section 3: Workspace folder (Ruling M — disabled while any plan/draft live) */}
        <section
          className="settings-card"
          data-testid="settings-section-folder"
          aria-label={t("settings_section_folder", language)}
        >
          <h2 className="settings-section-title">
            {t("settings_section_folder", language)}
          </h2>

          <div className="settings-folder-row" data-testid="settings-folder-current">
            <div className="settings-folder-meta">
              <span className="settings-folder-label">
                {t("settings_folder_current_label", language)}
              </span>
              <span
                className="settings-folder-name"
                data-testid="settings-folder-basename"
              >
                {folderDisplayName}
              </span>
            </div>

            {root ? (
              <DetailDisclosure
                inline
                testId="settings-folder-detail"
                label={t("detail_label", language)}
              >
                <dl className="change-detail-dl">
                  <dt>{t("settings_folder_current_label", language)}</dt>
                  <dd>{root}</dd>
                  {status?.pid ? (
                    <>
                      <dt>{t("detail_pid_process", language)}</dt>
                      <dd>{String(status.pid)}</dd>
                    </>
                  ) : null}
                </dl>
              </DetailDisclosure>
            ) : null}
          </div>

          <div className="settings-folder-controls">
            <button
              type="button"
              className="settings-btn"
              data-testid="settings-folder-change"
              disabled={folderLocked || switching}
              aria-disabled={folderLocked || switching}
              title={folderLocked ? t("settings_folder_locked", language) : undefined}
              onClick={() => void handleChangeFolderClick()}
            >
              {switching
                ? t("settings_folder_changing", language)
                : t("settings_folder_change", language)}
            </button>

            {folderLocked ? (
              <p
                className="settings-lock-reason"
                data-testid="settings-folder-locked-reason"
                role="status"
              >
                {t("settings_folder_locked", language)}
              </p>
            ) : null}

            {editingFolder && !folderLocked ? (
              <form
                className="settings-folder-form"
                data-testid="settings-folder-form"
                onSubmit={(e) => void handleFormSubmit(e)}
              >
                <input
                  type="text"
                  className="settings-folder-input"
                  data-testid="settings-folder-input"
                  value={folderInput}
                  placeholder={t("settings_folder_prompt", language)}
                  aria-label={t("settings_folder_prompt", language)}
                  onChange={(e) => setFolderInput(e.target.value)}
                />
                <button
                  type="submit"
                  className="settings-btn settings-btn--primary"
                  data-testid="settings-folder-apply"
                  disabled={switching || !folderInput.trim()}
                >
                  {t("settings_folder_apply", language)}
                </button>
                <button
                  type="button"
                  className="settings-btn"
                  data-testid="settings-folder-default"
                  disabled={switching}
                  onClick={() => void handleUseDefaultFolder()}
                >
                  {t("settings_folder_reset_default", language)}
                </button>
              </form>
            ) : null}

            {switchError ? (
              <div className="settings-error-msg" data-testid="settings-folder-error" role="alert">
                <span>
                  {errorCodeMessage(switchError.code, language) || switchError.message}
                </span>
                {switchError.detail || switchError.code ? (
                  <DetailDisclosure inline testId="settings-folder-error-detail" label={t("detail_label", language)}>
                    <div>{`${switchError.code}: ${switchError.detail ?? switchError.message}`}</div>
                  </DetailDisclosure>
                ) : null}
              </div>
            ) : null}
          </div>

          <p className="settings-note" data-testid="settings-folder-note">
            {t("settings_folder_note", language)}
          </p>
        </section>
      </div>
    </main>
  );
}
