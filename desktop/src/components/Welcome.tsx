/**
 * What the app shows before there is a document. A designed front door, not a
 * blank pane: the mark, one sentence of what this is, a drop target, and the
 * documents you had open last time.
 */
import { openPath, openViaDialog } from "../actions";
import { useWorkspace } from "../store";
import { Logo } from "./Logo";

function ago(iso: string): string {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return "방금";
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}일 전`;
  return iso.slice(0, 10);
}

export function Welcome() {
  const recents = useWorkspace((s) => s.recents);
  const dragOver = useWorkspace((s) => s.dragOver);
  const error = useWorkspace((s) => s.inspectError);

  return (
    <div className="welcome" data-testid="welcome">
      <Logo size={64} className="mark" />
      <div>
        <h1>Rigorloom</h1>
        <p className="lede">
          한글 문서의 서식을 뜯어보고, 값을 넣을 자리와 그 자리에 걸린 문제를 먼저
          보여 줍니다. 원본은 건드리지 않고 사본으로만 작업합니다.
        </p>
      </div>

      <div className={`drop${dragOver ? " over" : ""}`}>
        <button className="action primary big" onClick={() => void openViaDialog()}>
          문서 열기
        </button>
        <p className="hint">
          .hwpx 파일을 창에 끌어다 놓아도 됩니다 · Ctrl+O
        </p>
      </div>

      {error ? (
        <p className="prose" style={{ color: "var(--bad)", textAlign: "center" }}>
          {error.message}
        </p>
      ) : null}

      {recents.length > 0 && (
        <div className="recents" data-testid="recents">
          <h2>최근 문서</h2>
          {recents.map((r) => (
            <button
              key={r.path}
              className="recent"
              data-testid={`recent-${r.sha256.slice(0, 8)}`}
              title={r.path}
              onClick={() => void openPath(r.path)}
            >
              <span className="name">{r.name}</span>
              <span className="meta">
                {r.sha256.slice(0, 8)} · {ago(r.openedUtc)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
