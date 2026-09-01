/**
 * Document view — for working on the document.
 *
 * left: structure · centre: the page or an honest unavailable state ·
 * right: contextual agent panel · bottom: the verification bar.
 *
 * This component holds no state. Everything it draws comes from the one
 * Workspace store, which is what makes the view switch lossless: there is
 * nothing here to lose.
 */
import { ContextPanel } from "../components/ContextPanel";
import { PagePreview } from "../components/PagePreview";
import { StructureTree } from "../components/StructureTree";
import { VerificationBar } from "../components/VerificationBar";
import { activeCandidates, activeInspect, activeSession, useWorkspace } from "../store";

export function DocumentView({ onOpen }: { onOpen: () => void }) {
  const inspect = useWorkspace(activeInspect);
  const session = useWorkspace(activeSession);
  const status = useWorkspace((s) => s.status);
  const capabilities = useWorkspace((s) => s.capabilities);
  const inspectPhase = useWorkspace((s) => s.inspectPhase);
  const inspectError = useWorkspace((s) => s.inspectError);
  const candidates = useWorkspace(activeCandidates);

  return (
    <div className="view view-document" data-testid="view-document">
      <div className="columns">
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
            ) : inspectError ? (
              <div className="section">
                <h3 style={{ color: "var(--bad)" }}>문서를 읽지 못했습니다</h3>
                <p className="prose">{inspectError.message}</p>
                <p className="prose mono" style={{ marginTop: "var(--s2)" }}>
                  {inspectError.code}
                </p>
              </div>
            ) : inspect ? (
              <StructureTree inspect={inspect} capabilities={capabilities} />
            ) : (
              <p className="empty">문서를 열면 구역, 표, 채움 자리가 여기에 펼쳐집니다.</p>
            )}
          </div>
        </nav>

        <main className="panel center" aria-label="쪽 미리보기">
          {inspect ? (
            <PagePreview inspect={inspect} />
          ) : (
            <div className="center-scroll">
              <div className="unavailable">
                <h2>문서를 여세요</h2>
                <p>
                  한글 문서(.hwpx)를 열면 서식의 뼈대와 값을 넣을 자리를 읽어 옵니다. 원본은
                  건드리지 않고 사본으로만 작업합니다.
                </p>
                <button className="action primary" onClick={onOpen}>
                  문서 열기
                </button>
              </div>
            </div>
          )}
        </main>

        <ContextPanel inspect={inspect} status={status} />
      </div>

      <VerificationBar session={session} inspect={inspect} candidates={candidates} />
    </div>
  );
}
