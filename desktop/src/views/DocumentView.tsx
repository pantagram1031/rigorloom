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
import { useEffect } from "react";
import { openViaDialog, selectSession, toggleLeftRail } from "../actions";
import { ContextPanel } from "../components/ContextPanel";
import { Icon } from "../components/Icon";
import { EditorToolbar } from "../components/EditorToolbar";
import { Findings } from "../components/Findings";
import { PagePreview } from "../components/PagePreview";
import { PipelinePanel, PipelineStrip } from "../components/PipelineStatus";
import { ReceiptPanel } from "../components/ReceiptPanel";
import { SessionList } from "../components/SessionList";
import { SkeletonRows } from "../components/Skeleton";
import { StructureTree } from "../components/StructureTree";
import { TextView } from "../components/TextView";
import { VerificationBar } from "../components/VerificationBar";
import { VerifyPanel } from "../components/VerifyResults";
import { Home } from "../components/Welcome";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/Collapsible";
import { Button } from "../ui/Button";
import { Tooltip } from "../ui/Tooltip";
import { focusDocumentSurface } from "../focus";
import {
  activeCandidates,
  activeInspect,
  activeSession,
  isHome,
  useWorkspace,
} from "../store";

export function DocumentView() {
  const inspect = useWorkspace(activeInspect);
  const session = useWorkspace(activeSession);
  const capabilities = useWorkspace((s) => s.capabilities);
  const inspectPhase = useWorkspace((s) => s.inspectPhase);
  const inspectError = useWorkspace((s) => s.inspectError);
  const fillPhase = useWorkspace((s) => s.fillPhase);
  const posterPhase = useWorkspace((s) => s.posterPhase);
  const checkPhase = useWorkspace((s) => s.checkPhase);
  const loadingDoc = inspectPhase === "starting";
  const runBusy =
    checkPhase === "starting" || fillPhase === "starting" || posterPhase === "starting";
  const mode = useWorkspace((s) => s.centerMode);
  const zoom = useWorkspace((s) => s.zoom);
  const candidates = useWorkspace(activeCandidates);
  const collapsed = useWorkspace((s) => s.leftRailCollapsed);
  const home = useWorkspace(isHome);
  const paraCount = inspect?.graph.paragraphs.length ?? 0;
  const tableCount = inspect?.graph.tables.length ?? 0;
  const fillCount = inspect?.summary.fillTargetCount ?? 0;
  const sessionId = session?.sessionId ?? null;
  const railTitle = inspect
    ? `문단 ${paraCount} · 표 ${tableCount} · 입력 칸 ${fillCount}`
    : "구조";

  useEffect(() => {
    if (home || inspectPhase !== "ready" || !inspect) return;
    focusDocumentSurface();
  }, [home, inspectPhase, sessionId]);

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
              <Tooltip content={`${railTitle} (Ctrl+B)`}>
                <Button
                  variant="ghost"
                  className="icon-rail-btn"
                  data-testid="toggle-left-rail"
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
                </Button>
              </Tooltip>
            </div>
          ) : (
            <>
              <div className="panel-head">
                <span className="panel-title">구조</span>
                <span className="count">
                  {inspect ? `${paraCount}문단 · ${tableCount}표` : ""}
                </span>
                <Tooltip content="구조 레일 접기 (Ctrl+B)">
                  <Button
                    variant="ghost"
                    className="rail-toggle"
                    data-testid="toggle-left-rail-panel"
                    aria-label="구조 레일 접기"
                    onClick={() => toggleLeftRail()}
                  >
                    <Icon name="chevron-left" />
                  </Button>
                </Tooltip>
              </div>
              <div className="panel-body" data-testid="left-rail-scroll">
                {inspectPhase === "starting" ? (
                  <SkeletonRows testId="tree-skeleton" />
                ) : inspectError && inspect ? (
                  <div className="section">
                    <h3 style={{ color: "var(--bad)" }}>문서를 다시 읽지 못했습니다</h3>
                    <p className="prose">{inspectError.message}</p>
                  </div>
                ) : inspect ? (
                  <StructureTree inspect={inspect} capabilities={capabilities} />
                ) : (
                  <p className="empty">문서를 열면 구역, 표, 입력 칸이 여기에 펼쳐집니다.</p>
                )}
              </div>
              <Collapsible className="work-disclosure" data-testid="pipeline-disclosure">
        <CollapsibleTrigger>파이프라인</CollapsibleTrigger>
        <CollapsibleContent>
<PipelinePanel />
      </CollapsibleContent>
      </Collapsible>
              <Collapsible className="work-disclosure" data-testid="work-packs-disclosure">
        <CollapsibleTrigger>문서 / 작업 팩</CollapsibleTrigger>
        <CollapsibleContent>
<SessionList
                  embedded
                  onSelect={(id) => void selectSession(id)}
                  onOpen={() => void openViaDialog()}
                />
      </CollapsibleContent>
      </Collapsible>
            </>
          )}
        </nav>

        <main className="panel center" aria-label="문서">
          <PipelineStrip />
          <VerifyPanel />
          <div className="center-toolbar">
            <EditorToolbar inspect={inspect} />
            {runBusy ? <div className="run-progress" data-testid="run-progress" /> : null}
          </div>
          {mode === "text" ? (
            <div className="doc-zoom" style={{ zoom }}>
              {inspect ? (
                <TextView inspect={inspect} />
              ) : loadingDoc ? (
                <SkeletonRows rows={10} testId="document-skeleton" />
              ) : null}
            </div>
          ) : inspect ? (
            <PagePreview inspect={inspect} />
          ) : loadingDoc ? (
            <SkeletonRows rows={8} testId="document-skeleton" />
          ) : null}
        </main>

        <ContextPanel inspect={inspect} />
      </div>

      <VerificationBar session={session} inspect={inspect} candidates={candidates} />
      <Findings />
      <ReceiptPanel />
    </div>
  );
}
