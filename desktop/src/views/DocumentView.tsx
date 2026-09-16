/**
 * One workspace. The document is the hero.
 *
 * Home replaces the three columns when no session is in front of the user.
 * left: collapsible structure rail · centre: the document ·
 * right: tabbed inspector · bottom: the verification bar.
 *
 * This component holds no state. Everything it draws comes from the one
 * Workspace store.
 */
import { openViaDialog, selectSession, toggleLeftRail } from "../actions";
import { ContextPanel } from "../components/ContextPanel";
import { Icon } from "../components/Icon";
import { EditorToolbar } from "../components/EditorToolbar";
import { Findings } from "../components/Findings";
import { PagePreview } from "../components/PagePreview";
import { ReceiptPanel } from "../components/ReceiptPanel";
import { SessionList } from "../components/SessionList";
import { StructureTree } from "../components/StructureTree";
import { TextView } from "../components/TextView";
import { VerificationBar } from "../components/VerificationBar";
import { Home } from "../components/Welcome";
import {
  activeCandidates,
  activeInspect,
  activeSession,
  isHome,
  useWorkspace,
} from "../store";

function CenterCaveat() {
  const mode = useWorkspace((s) => s.centerMode);
  return (
    <div className="center-head">
      <span className="caveat" data-testid="center-caveat">
        {mode === "text"
          ? "본문 보기 — 채움 자리를 눌러 값을 넣습니다. 승인 전에는 문서가 바뀌지 않습니다"
          : "페이지 보기 — 실제로 그려진 지면입니다. 그림은 증거가 아닙니다"}
      </span>
    </div>
  );
}

export function DocumentView() {
  const inspect = useWorkspace(activeInspect);
  const session = useWorkspace(activeSession);
  const capabilities = useWorkspace((s) => s.capabilities);
  const inspectPhase = useWorkspace((s) => s.inspectPhase);
  const inspectError = useWorkspace((s) => s.inspectError);
  const mode = useWorkspace((s) => s.centerMode);
  const zoom = useWorkspace((s) => s.zoom);
  const candidates = useWorkspace(activeCandidates);
  const collapsed = useWorkspace((s) => s.leftRailCollapsed);
  const home = useWorkspace(isHome);
  const paraCount = inspect?.graph.paragraphs.length ?? 0;
  const tableCount = inspect?.graph.tables.length ?? 0;
  const fillCount = inspect?.summary.fillTargetCount ?? 0;
  const railTitle = inspect
    ? `문단 ${paraCount} · 표 ${tableCount} · 입력 칸 ${fillCount}`
    : "구조";

  if (home) {
    return (
      <div className="view view-document is-home" data-testid="view-document">
        <Home />
        <VerificationBar home session={session} inspect={null} candidates={[]} />
        <Findings />
        <ReceiptPanel />
      </div>
    );
  }

  return (
    <div className="view view-document" data-testid="view-document">
      <div className={`columns stagger${collapsed ? " is-rail-collapsed" : ""}`}>
        <nav
          className={`panel rail${collapsed ? " is-collapsed" : ""}`}
          aria-label="문서 구조"
          data-testid="left-rail"
          data-collapsed={collapsed ? "true" : "false"}
        >
          {collapsed ? (
            <div className="icon-rail" data-testid="left-rail-collapsed">
              <button
                type="button"
                className="icon-rail-btn"
                data-testid="toggle-left-rail"
                title={`${railTitle} (Ctrl+B)`}
                aria-label="구조 레일 펼치기"
                aria-pressed="true"
                onClick={() => toggleLeftRail()}
              >
                <Icon name="list" />
                {inspect ? (
                  <span className="icon-rail-count" aria-hidden="true">
                    {paraCount}
                  </span>
                ) : null}
              </button>
            </div>
          ) : (
            <>
              <div className="panel-head">
                <span className="panel-title">구조</span>
                <span className="count">
                  {inspect ? `${paraCount}문단 · ${tableCount}표` : ""}
                </span>
                <button
                  type="button"
                  className="ghost rail-toggle"
                  data-testid="toggle-left-rail-panel"
                  title="구조 레일 접기 (Ctrl+B)"
                  aria-label="구조 레일 접기"
                  onClick={() => toggleLeftRail()}
                >
                  <Icon name="chevron-left" />
                </button>
              </div>
              <div className="panel-body">
                {inspectPhase === "starting" ? (
                  <p className="empty">문서를 읽는 중입니다. 서식을 뜯어보는 데 몇 초 걸립니다.</p>
                ) : inspectError && inspect ? (
                  <div className="section">
                    <h3 style={{ color: "var(--bad)" }}>문서를 다시 읽지 못했습니다</h3>
                    <p className="prose">{inspectError.message}</p>
                  </div>
                ) : inspect ? (
                  <StructureTree inspect={inspect} capabilities={capabilities} />
                ) : (
                  <p className="empty">문서를 열면 구역, 표, 채움 자리가 여기에 펼쳐집니다.</p>
                )}
                <details className="work-disclosure" data-testid="work-packs-disclosure">
                  <summary>문서 / 작업 팩</summary>
                  <SessionList
                    embedded
                    onSelect={(id) => void selectSession(id)}
                    onOpen={() => void openViaDialog()}
                  />
                </details>
              </div>
            </>
          )}
        </nav>

        <main className="panel center" aria-label="문서">
          <EditorToolbar inspect={inspect} />
          <CenterCaveat />
          {mode === "text" ? (
            <div className="doc-zoom" style={{ zoom }}>
              {inspect ? <TextView inspect={inspect} /> : null}
            </div>
          ) : (
            inspect ? <PagePreview inspect={inspect} /> : null
          )}
        </main>

        <ContextPanel inspect={inspect} />
      </div>

      <VerificationBar session={session} inspect={inspect} candidates={candidates} />
      <Findings />
      <ReceiptPanel />
    </div>
  );
}
