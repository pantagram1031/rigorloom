/**
 * Home. What the app shows when no document is in front of the user: the mark,
 * one sentence of what this is, 문서 열기, a drop hint, recents, and a quiet
 * link row. The three columns stay unmounted until a session is shown.
 */
import { bindFormAndOpen, openPath, openViaDialog } from "../actions";
import { dismissFirstRunHint, setState, showToast, useWorkspace } from "../store";
import type { Recent } from "../types";
import { Icon } from "./Icon";
import { Logo } from "./Logo";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Item } from "../ui/Item";
import { Tooltip } from "../ui/Tooltip";

/** Repo-relative CLI walkthrough. No opener/shell plugin is wired. */
export const CLI_DOCS_PATH = "docs/QUICKSTART.md";
export const CLI_DOCS_URL =
  "https://github.com/pantagram1031/rigorloom/blob/main/docs/QUICKSTART.md";

function copyCliDocsPath() {
  const clip = navigator.clipboard;
  if (!clip) {
    showToast("복사하지 못했습니다", 1400);
    return;
  }
  void clip.writeText(CLI_DOCS_PATH).then(
    () => showToast("경로를 복사했습니다", 1400),
    () => showToast("복사하지 못했습니다", 1400),
  );
}

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
  const trailing = (
    <span className="meta">
      <Badge variant="outline" className="latin-caps">
        {backend}
      </Badge>
      {recent.formBinding ? (
        <Tooltip content={recent.formBinding.path}>
          <span className="form-tag" data-testid="recent-form-tag">
            양식
          </span>
        </Tooltip>
      ) : null}
      {time ? <span className="when">{time}</span> : null}
      {recent.missing ? (
        <span className="missing-tag" data-testid="recent-missing">
          찾을 수 없음
        </span>
      ) : null}
    </span>
  );
  const description = folder ? (
    <Tooltip content={folder}>
      <span className="folder" dir="rtl">
        <span>{folder}</span>
      </span>
    </Tooltip>
  ) : undefined;

  if (recent.missing) {
    return (
      <Tooltip content={recent.path}>
        <div className="recent missing" data-testid="recent-row" aria-disabled="true">
          <Item
            icon={<Icon name="open" />}
            title={<span className="name">{recent.name}</span>}
            description={description}
            trailing={trailing}
          />
        </div>
      </Tooltip>
    );
  }

  return (
    <Tooltip content={recent.path}>
      <button
        type="button"
        className="recent"
        data-testid="recent-row"
        onClick={() => void openPath(recent.path, recent.formBinding)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void openPath(recent.path, recent.formBinding);
          }
        }}
      >
        <Item
          icon={<Icon name="open" />}
          title={<span className="name">{recent.name}</span>}
          description={description}
          trailing={trailing}
        />
      </button>
    </Tooltip>
  );
}

export function Home() {
  const recents = useWorkspace((s) => s.recents);
  const dragOver = useWorkspace((s) => s.dragOver);
  const error = useWorkspace((s) => s.inspectError);
  const firstRunHintDismissed = useWorkspace((s) => s.firstRunHintDismissed);

  return (
    <div className="welcome home" data-testid="welcome">
      <div className="home-inner">
        <Logo size={48} className="mark" />
        <div>
          <h1>Rigorloom</h1>
          <p className="lede">
            문서를 열고, 에이전트가 제안한 편집을 사람이 승인하면, 런타임이 적용하고
            영수증을 남깁니다.
          </p>
        </div>

        {!firstRunHintDismissed ? (
          <div className="first-run" data-testid="first-run-hint">
            <span className="first-run-kicker">처음이신가요</span>
            <ol>
              <li>열기</li>
              <li>검토</li>
              <li>승인</li>
            </ol>
            <Button
              variant="ghost"
              className="first-run-dismiss ui-icon-btn"
              data-testid="first-run-dismiss"
              aria-label="닫기"
              onClick={() => dismissFirstRunHint()}
            >
              <Icon name="x" />
            </Button>
          </div>
        ) : null}

        <div className="home-open-row">
          <Button
            variant="primary"
            className="btn-icon"
            data-testid="home-open"
            onClick={() => void openViaDialog()}
          >
            <Icon name="open" />
            문서 열기
          </Button>
          <Tooltip content="빈 양식이나 form_profile.json을 연결해 엽니다">
            <Button
              variant="secondary"
              className="btn-icon"
              data-testid="home-bind-form"
              onClick={() => void bindFormAndOpen()}
            >
              <Icon name="link" />
              양식 연결
            </Button>
          </Tooltip>
        </div>

        <Card
          className={`drop${dragOver ? " over" : ""}`}
          data-testid="home-drop"
        >
          <CardContent>
            <p className="hint">파일을 끌어다 놓으세요</p>
          </CardContent>
        </Card>

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
          <span className="home-cli-docs" data-testid="home-cli-docs">
            <span className="home-link">CLI 문서</span>
            <Tooltip content={CLI_DOCS_URL}>
              <code className="mono">{CLI_DOCS_PATH}</code>
            </Tooltip>
            <Tooltip content={`${CLI_DOCS_PATH} 복사`}>
              <Button
                variant="link"
                className="home-link"
                data-testid="home-cli-docs-copy"
                onClick={() => copyCliDocsPath()}
              >
                복사
              </Button>
            </Tooltip>
          </span>
          <span className="home-link-sep" aria-hidden="true">
            /
          </span>
          <Button
            variant="link"
            className="home-link btn-icon"
            data-testid="home-settings"
            onClick={() => setState({ settingsOpen: true })}
          >
            <Icon name="settings" />
            설정
          </Button>
        </div>
      </div>
    </div>
  );
}

export { Home as Welcome };
