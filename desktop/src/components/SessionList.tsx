/**
 * Agent view, left: the open documents.
 *
 * A list, not a card grid. Studio's `minmax(285px,1fr)` grid of hover-lifting
 * KPI cards is the shape the program rules out: a desktop editor opens a
 * document, it does not present a gallery.
 *
 * These are Runtime *sessions*, not Workspaces. `workspace/list` is not
 * implemented — the Runtime keys sessions on disk under `--root` and
 * `session/list` is the only enumeration there is. The header says "문서" so
 * the UI does not claim a concept the runtime lacks.
 */
import { bindFormAndOpen } from "../actions";
import { useWorkspace } from "../store";
import type { Session } from "../types";
import { Icon } from "./Icon";
import { EmptyIconDoc, EmptyState } from "./EmptyState";
import { TaskPacks } from "./TaskPacks";

export function SessionList({
  onSelect,
  onOpen,
  embedded = false,
}: {
  onSelect: (sessionId: string) => void;
  onOpen: () => void;
  embedded?: boolean;
}) {
  const sessions = useWorkspace((s) => s.sessions);
  const active = useWorkspace((s) => s.activeSessionId);
  const root = useWorkspace((s) => s.root);

  const body = (
    <div className="panel-body">
      <div className="rows" data-testid="session-list">
        {sessions.length === 0 ? (
          <EmptyState
            icon={<EmptyIconDoc />}
            title="연 문서가 없습니다"
            body="문서를 열면 이 목록에 나타납니다."
          />
        ) : (
          sessions.map((s: Session) => (
            <button
              key={s.sessionId}
              className="row"
              aria-selected={s.sessionId === active}
              data-testid={`session-${s.sessionId}`}
              onClick={() => onSelect(s.sessionId)}
            >
              <span className="primary">{s.source.name}</span>
              <span className="secondary">
                {s.source.sha256.slice(0, 12)} · {(s.source.bytes / 1024).toFixed(1)} KiB
              </span>
              <span className="secondary">{s.openedUtc}</span>
            </button>
          ))
        )}
      </div>
      <div className="section">
        <button className="action primary" onClick={onOpen} style={{ width: "100%" }}>
          문서 열기
        </button>
        <button
          type="button"
          className="action btn-icon"
          data-testid="bind-form"
          title="빈 양식이나 form_profile.json을 연결해 엽니다"
          onClick={() => void bindFormAndOpen()}
          style={{ width: "100%", marginTop: "var(--s2)" }}
        >
          <Icon name="link" />
          양식 연결
        </button>
      </div>
      <TaskPacks />
      <div className="section">
        <h3>작업 폴더</h3>
        <p className="prose mono" style={{ overflowWrap: "anywhere", userSelect: "text" }}>
          {root ?? "—"}
        </p>
        <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
          연 문서는 이 폴더에 남습니다. 앱을 닫았다 열면 여기서 다시 찾습니다.
        </p>
      </div>
    </div>
  );

  if (embedded) return body;

  return (
    <nav className="panel" aria-label="문서 목록">
      <div className="panel-head">
        <span className="panel-title">문서</span>
        <span className="count">{sessions.length}</span>
      </div>
      {body}
    </nav>
  );
}
