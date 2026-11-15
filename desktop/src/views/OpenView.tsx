import {
  loadCorpusFiles,
  openPath,
  openViaDialog,
  selectSession,
} from "../actions";
import { t } from "../i18n/vocabulary";
import { setState, useWorkspace } from "../store";
import "./open.css";

export function OpenView() {
  const language = useWorkspace((s) => s.language);
  const sessions = useWorkspace((s) => s.sessions);
  const recents = useWorkspace((s) => s.recents);
  const openedPaths = useWorkspace((s) => s.openedPaths);
  const draft = useWorkspace((s) => s.draft);

  interface OpenItem {
    key: string;
    name: string;
    sessionId: string | null;
    path: string | null;
    pendingCount: number;
  }

  const items: OpenItem[] = [];
  const seenPaths = new Set<string>();
  const seenShas = new Set<string>();
  const sessionByPath = new Map<string, string>();
  for (const s of sessions) {
    const path = openedPaths[s.sessionId] ?? null;
    if (path) sessionByPath.set(path, s.sessionId);
    if (path) seenPaths.add(path);
    seenShas.add(s.source.sha256);
    const pendingCount = draft.sessionId === s.sessionId ? draft.ops.length : 0;
    items.push({
      key: `session:${s.sessionId}`,
      name: s.source.name,
      sessionId: s.sessionId,
      path,
      pendingCount,
    });
  }

  for (const r of recents) {
    if (seenPaths.has(r.path) || seenShas.has(r.sha256)) continue;
    seenPaths.add(r.path);
    const liveSessionId = sessionByPath.get(r.path) ?? null;
    items.push({
      key: `recent:${r.path}`,
      name: r.name,
      sessionId: liveSessionId,
      path: r.path,
      pendingCount:
        liveSessionId && draft.sessionId === liveSessionId ? draft.ops.length : 0,
    });
  }

  return (
    <main className="open-view" data-testid="open-view">
      <div className="open-container">
        <header className="open-header">
          <h1>{t("open_title", language)}</h1>
          <p className="open-subtitle">{t("open_subtitle", language)}</p>
        </header>

        <section className="open-dropzone" aria-label={t("open_title", language)}>
          <p className="open-dropzone-title">{t("open_drop_prompt", language)}</p>
          <p className="open-dropzone-sub">{t("open_drop_sub", language)}</p>
          <div className="open-dropzone-actions">
            <button
              type="button"
              className="open-btn-primary"
              data-testid="open-choose-file"
              onClick={() => void openViaDialog()}
            >
              {t("open_choose_file", language)}
            </button>
            <button
              type="button"
              className="open-btn-secondary"
              data-testid="welcome-open-form"
              onClick={() => {
                setState({ openDialogOpen: true });
                void loadCorpusFiles();
              }}
            >
              {t("open_builtin_forms", language)}
            </button>
          </div>
        </section>

        <section className="open-recents" aria-label={t("open_recent_title", language)}>
          <div className="open-recents-head">
            <h2>{t("open_recent_title", language)}</h2>
            <p className="open-recents-hint">{t("open_recent_hint", language)}</p>
          </div>

          {items.length === 0 ? (
            <div className="open-empty" data-testid="open-empty-recent">
              {t("open_empty_recent", language)}
            </div>
          ) : (
            <div className="open-recent-list" data-testid="open-recent-list">
              {items.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className="open-recent-row"
                  data-testid={`open-recent-item-${item.name}`}
                  onClick={() => {
                    if (item.sessionId) {
                      void selectSession(item.sessionId);
                    } else if (item.path) {
                      void openPath(item.path);
                    }
                  }}
                >
                  <span className="open-recent-name">{item.name}</span>
                  <span className="open-recent-meta">
                    {item.pendingCount > 0 ? (
                      <span className="open-badge">
                        {t("open_pending_badge", language, [item.pendingCount])}
                      </span>
                    ) : (
                      <span className="open-badge open-badge--neutral">
                        {t("open_no_changes", language)}
                      </span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
