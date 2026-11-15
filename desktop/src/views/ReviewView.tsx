import { togglePrintView } from "../actions";
import { t } from "../i18n/vocabulary";
import { activeSession, useWorkspace } from "../store";
import "./review.css";

export function ReviewView() {
  const session = useWorkspace(activeSession);
  const language = useWorkspace((s) => s.language);
  const draft = useWorkspace((s) => s.draft);
  const printViewEnabled = useWorkspace((s) => s.printViewEnabled);

  const changeCount =
    session && draft.sessionId === session.sessionId ? draft.ops.length : 0;

  return (
    <main className="review-view" data-testid="review-view">
      <section className="review-canvas-pane">
        <div className="review-subbar">
          <span className="review-page-notice" data-testid="review-page-label">
            {t("page_label_review", language)}
          </span>
          <button
            type="button"
            className="review-mode-btn"
            data-testid="review-toggle-print"
            onClick={() => togglePrintView()}
          >
            {printViewEnabled
              ? t("review_mode_document", language)
              : t("review_mode_print", language)}
          </button>
        </div>

        <div className="review-sheet-scroll">
          <article className="review-paper-card">
            <h2>{session?.source.name ?? t("doc_none_open", language)}</h2>
            <p>{t("review_placeholder_ready", language)}</p>
          </article>
        </div>
      </section>

      <aside className="review-side-pane">
        <div className="review-side-head">
          <h2>{t("review_changes_header", language, [changeCount])}</h2>
          <p className="review-guard-note">{t("guard_list_header", language)}</p>
        </div>
        <div className="review-side-body">
          <div className="review-empty" data-testid="review-empty-changes">
            {t("review_empty_changes", language)}
          </div>
        </div>
      </aside>
    </main>
  );
}
