/**
 * Home. What the app shows when no document is in front of the user: the mark,
 * one sentence of what this is, 문서 열기, a drop hint, recents, and a quiet
 * link row. The three columns stay unmounted until a session is shown.
 */
import { openPath, openViaDialog } from "../actions";
import { setState, useWorkspace } from "../store";
import type { Recent } from "../types";
import { Icon } from "./Icon";
import { Logo } from "./Logo";

export function relativeOpened(iso: string, now = Date.now()): string {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";
  const mins = Math.floor((now - then) / 60000);
  if (mins < 1) return "방금";
  if (mins < 60) return `${mins}분 전`;
  const thenDate = new Date(then);
  const nowDate = new Date(now);
  const startThen = new Date(thenDate.getFullYear(), thenDate.getMonth(), thenDate.getDate()).getTime();
  const startNow = new Date(nowDate.getFullYear(), nowDate.getMonth(), nowDate.getDate()).getTime();
  const dayDiff = Math.round((startNow - startThen) / 86_400_000);
  if (dayDiff === 1) return "어제";
  if (dayDiff === 0) return `${Math.floor(mins / 60)}시간 전`;
  return iso.slice(0, 10);
}

export function folderOf(path: string): string {
  const cut = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return cut <= 0 ? "" : path.slice(0, cut);
}

export function recentBackend(recent: Recent): string {
  const kind =
    recent.documentKind ??
    (/\.hwp$/i.test(recent.path) && !/\.hwpx$/i.test(recent.path) ? "hwp" : "hwpx");
  return String(kind).toUpperCase();
}

function RecentRow({ recent }: { recent: Recent }) {
  const folder = folderOf(recent.path);
  const time = relativeOpened(recent.openedUtc);
  const backend = recentBackend(recent);
  const body = (
    <>
      <span className="name">
        <Icon name="open" />
        {recent.name}
      </span>
      {folder ? (
        <span className="folder" title={folder} dir="rtl">
          <span>{folder}</span>
        </span>
      ) : null}
      <span className="meta">
        <span className="latin-caps">{backend}</span>
        {time ? <span className="when">{time}</span> : null}
        {recent.missing ? (
          <span className="missing-tag" data-testid="recent-missing">
            찾을 수 없음
          </span>
        ) : null}
      </span>
    </>
  );

  if (recent.missing) {
    return (
      <div className="recent missing" data-testid="recent-row" title={recent.path} aria-disabled="true">
        {body}
      </div>
    );
  }

  return (
    <button
      type="button"
      className="recent"
      data-testid="recent-row"
      title={recent.path}
      onClick={() => void openPath(recent.path)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          void openPath(recent.path);
        }
      }}
    >
      {body}
    </button>
  );
}

export function Home() {
  const recents = useWorkspace((s) => s.recents);
  const dragOver = useWorkspace((s) => s.dragOver);
  const error = useWorkspace((s) => s.inspectError);

  return (
    <div className="welcome home" data-testid="welcome">
      <div className="home-inner">
        <Logo size={64} className="mark" />
        <div>
          <h1>Rigorloom</h1>
          <p className="lede">
            문서를 열고, 에이전트가 제안한 편집을 사람이 승인하면, 런타임이 적용하고
            영수증을 남깁니다.
          </p>
        </div>

        <button
          className="action primary big btn-icon"
          data-testid="home-open"
          onClick={() => void openViaDialog()}
        >
          <Icon name="open" />
          문서 열기
        </button>

        <div
          className={`drop${dragOver ? " over" : ""}`}
          data-testid="home-drop"
        >
          <p className="hint">파일을 끌어다 놓으세요</p>
        </div>

        {error ? (
          <p className="prose danger" style={{ textAlign: "center" }}>
            {error.message}
          </p>
        ) : null}

        {recents.length === 0 ? (
          <p className="home-onboarding" data-testid="home-onboarding">
            처음이신가요? 양식 HWPX 파일 하나를 열면 시작됩니다
          </p>
        ) : (
          <div className="recents" data-testid="recents">
            <h2>최근 문서</h2>
            {recents.map((r) => (
              <RecentRow key={r.path} recent={r} />
            ))}
          </div>
        )}

        <div className="home-links">
          <a
            className="home-link"
            data-testid="home-cli-docs"
            href="docs/runtime-protocol-v0.md"
            title="docs/runtime-protocol-v0.md"
            onClick={(e) => e.preventDefault()}
          >
            CLI 문서
          </a>
          <span className="home-link-sep" aria-hidden="true">
            /
          </span>
          <button
            type="button"
            className="home-link btn-icon"
            data-testid="home-settings"
            onClick={() => setState({ settingsOpen: true })}
          >
            <Icon name="settings" />
            설정
          </button>
        </div>
      </div>
    </div>
  );
}

export { Home as Welcome };
