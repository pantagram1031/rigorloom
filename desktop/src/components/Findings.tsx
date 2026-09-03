/**
 * 검사 결과 — what the last check found, each finding addressed.
 *
 * Selecting a finding navigates the document to the cell it names, which is
 * the whole point of carrying an address on a finding rather than a message.
 *
 * The sheet is explicit about its own boundary: these are the engine's own
 * preflight facts, re-read from the document. The render proof and the
 * submission checkers are not part of it and the verification bar keeps
 * saying so.
 */
import { locateSelection, setState, useWorkspace } from "../store";
import { Tag } from "./Tag";

export function Findings() {
  const open = useWorkspace((s) => s.sheetOpen);
  const phase = useWorkspace((s) => s.checkPhase);
  const findings = useWorkspace((s) => s.findings);
  const checkedAt = useWorkspace((s) => s.checkedAt);

  if (!open) return null;

  const hard = findings.filter((f) => f.severity === "hard").length;
  const warn = findings.filter((f) => f.severity === "warn").length;

  return (
    <section className="sheet" data-testid="findings-sheet" aria-label="검사 결과">
      <header className="sheet-head">
        <h3>검사 결과</h3>
        {phase === "starting" ? (
          <Tag tone="none">읽는 중</Tag>
        ) : (
          <>
            {hard > 0 ? <Tag tone="bad">막힘 {hard}</Tag> : null}
            {warn > 0 ? <Tag tone="warn">주의 {warn}</Tag> : null}
            {hard === 0 && warn === 0 ? <Tag tone="ok">걸림 없음</Tag> : null}
          </>
        )}
        <span className="count">{checkedAt ?? ""}</span>
        <button
          className="ghost"
          style={{ color: "var(--fg-muted)" }}
          onClick={() => setState({ sheetOpen: false })}
          data-testid="close-findings"
        >
          닫기
        </button>
      </header>

      <div className="sheet-body">
        {phase === "starting" ? (
          <p className="empty">문서를 다시 읽고 있습니다.</p>
        ) : (
          findings.map((f, i) => (
            <button
              key={`${f.code}-${f.where}-${i}`}
              className="finding"
              data-testid={`finding-${i}`}
              disabled={!f.selection}
              onClick={() => f.selection && locateSelection(f.selection)}
            >
              <span className="where">{f.where}</span>
              <span className="what">{f.message}</span>
              <Tag
                tone={f.severity === "hard" ? "bad" : f.severity === "warn" ? "warn" : "ok"}
              >
                {f.severity === "hard" ? "막힘" : f.severity === "warn" ? "주의" : "확인"}
              </Tag>
            </button>
          ))
        )}
        <p className="empty">
          여기 있는 것은 이 빌드가 문서에서 직접 읽어 낸 사실입니다. 렌더 증명과 제출
          검사는 아직 실행할 수 없습니다 — 런타임에 그 방법이 없습니다.
        </p>
      </div>
    </section>
  );
}
