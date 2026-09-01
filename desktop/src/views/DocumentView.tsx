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
import { EditorToolbar } from "../components/EditorToolbar";
import { Findings } from "../components/Findings";
import { PagePreview } from "../components/PagePreview";
import { ReceiptPanel } from "../components/ReceiptPanel";
import { StructureTree } from "../components/StructureTree";
import { TextView } from "../components/TextView";
import { VerificationBar } from "../components/VerificationBar";
import { Welcome } from "../components/Welcome";
import {
  activeCandidates,
  activeInspect,
  activeSession,
  useWorkspace,
} from "../store";

/**
 * The one line under the toolbar that says what this mode is and is not.
 *
 * The mode switch itself moved up into `EditorToolbar` in Phase 5 — a Hangul
 * editor puts it in the band, not over the paper — and what stays here is the
 * caveat, which is the part that must never move: it is the sentence that keeps
 * 본문 보기 from being mistaken for a page and 페이지 보기 from being mistaken
 * for evidence.
 */
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
  const status = useWorkspace((s) => s.status);
  const capabilities = useWorkspace((s) => s.capabilities);
  const inspectPhase = useWorkspace((s) => s.inspectPhase);
  const inspectError = useWorkspace((s) => s.inspectError);
  const mode = useWorkspace((s) => s.centerMode);
  const zoom = useWorkspace((s) => s.zoom);
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
              <EditorToolbar inspect={inspect} />
              <CenterCaveat />
              {mode === "text" ? (
                // One zoom number, meaning the same thing in both modes: how
                // big the document is drawn. `zoom` on the container scales
                // layout rather than resampling, so glyphs re-rasterise.
                <div className="doc-zoom" style={{ zoom }}>
                  <TextView inspect={inspect} />
                </div>
              ) : (
                <PagePreview inspect={inspect} />
              )}
            </>
          )}
        </main>

        <ContextPanel inspect={inspect} status={status} />
      </div>

      <VerificationBar session={session} inspect={inspect} candidates={candidates} />
      <Findings />
      <ReceiptPanel />
    </div>
  );
}
