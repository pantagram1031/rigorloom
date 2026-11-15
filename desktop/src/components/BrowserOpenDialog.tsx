import { useState } from "react";
import {
  closeOpenDialog,
  loadCorpusFiles,
  openPath,
  openUploadedFile,
} from "../actions";
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
            <h2 id="browser-open-title">양식 열기 · Open form</h2>
            <p className="hint">
              한글 문서(.hwpx, .hwp)를 업로드하거나 서버 코퍼스/경로에서 엽니다.
            </p>
          </div>
          <button
            type="button"
            className="ghost"
            data-testid="open-dialog-close"
            onClick={() => closeOpenDialog()}
          >
            닫기 · Close
          </button>
        </div>

        <div className="dialog-body">
          <section className="open-section">
            <label className="open-upload-label">
              <span className="section-label">파일 업로드 · Upload (.hwpx / .hwp)</span>
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
            <span className="section-label">직접 경로 입력 · Open path on host</span>
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
                placeholder="/path/to/form.hwpx"
                data-testid="open-path-input"
                disabled={busy}
              />
              <button
                type="submit"
                data-testid="open-path-submit"
                disabled={busy || manualPath.trim() === ""}
              >
                열기 · Open
              </button>
            </form>
          </section>

          <section className="open-section">
            <div className="open-corpus-head">
              <span className="section-label">서버 문서 목록 · Corpus files</span>
              <button
                type="button"
                className="ghost"
                onClick={() => void loadCorpusFiles()}
                disabled={phase === "starting" || busy}
              >
                {phase === "starting" ? "불러오는 중…" : "새로고침 · Refresh"}
              </button>
            </div>
            <div className="corpus-list" data-testid="corpus-file-list">
              {files.length === 0 ? (
                <div className="hint">
                  {phase === "starting"
                    ? "목록을 확인하는 중…"
                    : "표시할 양식 파일이 없습니다."}
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
                    <span className="corpus-meta mono">
                      {entry.path} · {formatBytes(entry.size)}
                    </span>
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
