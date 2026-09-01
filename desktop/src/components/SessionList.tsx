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
import { useWorkspace } from "../store";
import type { Session } from "../types";

export function SessionList({
  onSelect,
  onOpen,
}: {
  onSelect: (sessionId: string) => void;
  onOpen: () => void;
}) {
  const sessions = useWorkspace((s) => s.sessions);
  const active = useWorkspace((s) => s.activeSessionId);
  const root = useWorkspace((s) => s.root);

  return (
    <nav className="panel" aria-label="문서 목록">
      <div className="panel-head">
        <span className="panel-title">문서</span>
        <span className="count">{sessions.length}</span>
      </div>
      <div className="panel-body">
        <div className="rows" data-testid="session-list">
          {sessions.length === 0 ? (
            <p className="empty">아직 연 문서가 없습니다.</p>
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
        </div>
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
    </nav>
  );
}
