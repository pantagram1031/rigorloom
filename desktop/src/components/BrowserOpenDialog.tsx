import { useState } from "react";
import {
  closeOpenDialog,
  loadCorpusFiles,
  openPath,
  openUploadedFile,
} from "../actions";
import { t } from "../i18n/vocabulary";
import { useWorkspace } from "../store";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function BrowserOpenDialog() {
  const open = useWorkspace((s) => s.openDialogOpen);
  const files = useWorkspace((s) => s.corpusFiles);
  const phase = useWorkspace((s) => s.corpusFilesPhase);
  const language = useWorkspace((s) => s.language);
  const [manualPath, setManualPath] = useState("");
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  async function pickServerPath(path: string) {
    const trimmed = path.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      closeOpenDialog();
      await openPath(trimmed);
    } finally {
      setBusy(false);
    }
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || busy) return;
    setBusy(true);
    try {
      await openUploadedFile(file);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) closeOpenDialog();
      }}
    >
      <div
        className="dialog dialog--open"
        role="dialog"
        aria-modal="true"
        aria-labelledby="browser-open-title"
        data-testid="browser-open-dialog"
      >
        <div className="dialog-head">
          <div>
            <h2 id="browser-open-title">{t("browser_open_title", language)}</h2>
            <p className="hint">{t("open_drop_sub", language)}</p>
          </div>
          <button
            type="button"
            className="ghost"
            data-testid="open-dialog-close"
            onClick={() => closeOpenDialog()}
          >
            {t("close", language)}
          </button>
        </div>

        <div className="dialog-body">
          <section className="open-section">
            <label className="open-upload-label">
              <span className="section-label">{t("open_choose_file", language)}</span>
              <input
                type="file"
                accept=".hwpx,.hwp"
                data-testid="upload-form-input"
                disabled={busy}
                onChange={(e) => void handleFileChange(e)}
              />
            </label>
          </section>

          <section className="open-section">
            <span className="section-label">{t("browser_open_path_label", language)}</span>
            <form
              className="open-path-form"
              onSubmit={(e) => {
                e.preventDefault();
                void pickServerPath(manualPath);
              }}
            >
              <input
                type="text"
                value={manualPath}
                onChange={(e) => setManualPath(e.target.value)}
                placeholder={t("browser_open_path_placeholder", language)}
                data-testid="open-path-input"
                disabled={busy}
              />
              <button
                type="submit"
                data-testid="open-path-submit"
                disabled={busy || manualPath.trim() === ""}
              >
                {t("browser_open_submit", language)}
              </button>
            </form>
          </section>

          <section className="open-section">
            <div className="open-corpus-head">
              <span className="section-label">{t("open_sample_form_label", language)}</span>
              <button
                type="button"
                className="ghost"
                onClick={() => void loadCorpusFiles()}
                disabled={phase === "starting" || busy}
              >
                {phase === "starting"
                  ? t("browser_open_loading", language)
                  : t("error_boundary_retry", language)}
              </button>
            </div>
            <div className="corpus-list" data-testid="corpus-file-list">
              {files.length === 0 ? (
                <div className="hint">
                  {phase === "starting"
                    ? t("browser_open_loading", language)
                    : t("browser_open_empty_corpus", language)}
                </div>
              ) : (
                files.map((entry) => (
                  <button
                    key={entry.path}
                    type="button"
                    className="corpus-row"
                    data-testid={`corpus-file-${entry.name}`}
                    disabled={busy}
                    onClick={() => void pickServerPath(entry.path)}
                  >
                    <span className="corpus-name">{entry.name}</span>
                    <span className="corpus-meta">{formatBytes(entry.size)}</span>
                  </button>
                ))
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
