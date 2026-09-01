/**
 * Document view — for working on the document.
 *
 * left: structure · centre: the document · right: contextual agent panel ·
 * bottom: the verification bar, with the findings sheet over it.
 *
 * This component holds no state. Everything it draws comes from the one
 * Workspace store, which is what makes the view switch lossless: there is
 * nothing here to lose.
 */
import { ContextPanel } from "../components/ContextPanel";
import { Findings } from "../components/Findings";
import { PagePreview } from "../components/PagePreview";
import { StructureTree } from "../components/StructureTree";
import { TextView } from "../components/TextView";
import { VerificationBar } from "../components/VerificationBar";
import { Welcome } from "../components/Welcome";
import {
  activeCandidates,
  activeInspect,
  activeSession,
  canRenderPages,
  setCenterMode,
  useWorkspace,
} from "../store";

function CenterHead() {
  const mode = useWorkspace((s) => s.centerMode);
  const canRender = useWorkspace(canRenderPages);
  return (
    <div className="center-head">
      <div className="modeswitch" role="group" aria-label="가운데 화면 모드">
        <button
          aria-pressed={mode === "text"}
          data-testid="mode-text"
          onClick={() => setCenterMode("text")}
        >
          본문 보기
        </button>
        <button
          aria-pressed={mode === "page"}
          data-testid="mode-page"
          disabled={!canRender}
          title={
            canRender
              ? "실제 페이지 그림"
              : "이 런타임에는 문서를 그림으로 그리는 방법이 아직 없습니다"
          }
          onClick={() => setCenterMode("page")}
        >
          페이지 보기
        </button>
      </div>
      <span className="caveat" data-testid="center-caveat">
        {mode === "text"
          ? "본문 보기 — 실제 페이지 배치는 렌더 증명 후 표시됩니다"
          : "페이지 보기 — 렌더된 실제 지면"}
      </span>
    </div>
  );
}

export function DocumentView() {
  const inspect = useWorkspace(activeInspect);
  const session = useWorkspace(activeSession);
  const status = useWorkspace((s) => s.status);
  const capabilities = useWorkspace((s) => s.capabilities);
  const inspectPhase = useWorkspace((s) => s.inspectPhase);
  const inspectError = useWorkspace((s) => s.inspectError);
  const mode = useWorkspace((s) => s.centerMode);
  const candidates = useWorkspace(activeCandidates);

  return (
    <div className="view view-document" data-testid="view-document">
      <div className="columns stagger">
        <nav className="panel" aria-label="문서 구조">
          <div className="panel-head">
            <span className="panel-title">구조</span>
            <span className="count">
              {inspect
                ? `${inspect.graph.paragraphs.length}문단 · ${inspect.graph.tables.length}표`
                : ""}
            </span>
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
          </div>
        </nav>

        <main className="panel center" aria-label="문서">
          {!inspect ? (
            <Welcome />
          ) : (
            <>
              <CenterHead />
              {mode === "text" ? <TextView inspect={inspect} /> : <PagePreview inspect={inspect} />}
            </>
          )}
        </main>

        <ContextPanel inspect={inspect} status={status} />
      </div>

      <VerificationBar session={session} inspect={inspect} candidates={candidates} />
      <Findings />
    </div>
  );
}
