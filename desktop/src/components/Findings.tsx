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
import { Button } from "../ui/Button";
import { Item } from "../ui/Item";
import { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle } from "../ui/Sheet";

export function Findings() {
  const open = useWorkspace((s) => s.sheetOpen);
  const phase = useWorkspace((s) => s.checkPhase);
  const findings = useWorkspace((s) => s.findings);
  const checkedAt = useWorkspace((s) => s.checkedAt);

  if (!open) return null;

  const hard = findings.filter((f) => f.severity === "hard").length;
  const warn = findings.filter((f) => f.severity === "warn").length;

  return (
    <Sheet open={open} onOpenChange={(next) => setState({ sheetOpen: next })}>
      <SheetContent className="sheet" data-testid="findings-sheet" aria-label="검사 결과">
      <SheetHeader className="sheet-head">
        <SheetTitle>검사 결과</SheetTitle>
        {phase === "starting" ? (
          <Tag tone="none">읽는 중</Tag>
        ) : phase === "failed" ? (
          <Tag tone="bad">검사 불가</Tag>
        ) : phase === "idle" ? (
          <Tag tone="none">실행 안 함</Tag>
        ) : (
          <>
            {hard > 0 ? <Tag tone="bad">막힘 {hard}</Tag> : null}
            {warn > 0 ? <Tag tone="warn">주의 {warn}</Tag> : null}
            {hard === 0 && warn === 0 ? <Tag tone="ok">걸림 없음</Tag> : null}
          </>
        )}
        <span className="count">{checkedAt ?? ""}</span>
        <SheetClose
          className="ghost"
          style={{ color: "var(--fg-muted)" }}
          data-testid="close-findings"
        >
          닫기
        </SheetClose>
      </SheetHeader>

      <div className="sheet-body">
        {phase === "starting" ? (
          <p className="empty">문서를 다시 읽고 있습니다.</p>
        ) : phase === "failed" ? (
          <p className="empty" data-testid="findings-failed">
            검사를 완료하지 못했습니다. 지금은 검사 결과를 확인할 수 없습니다.
          </p>
        ) : phase === "idle" ? (
          <p className="empty" data-testid="findings-idle">
            아직 검사를 실행하지 않았습니다.
          </p>
        ) : findings.length === 0 ? (
          <p className="empty" data-testid="findings-clear">
            검사에서 걸린 항목이 없습니다.
          </p>
        ) : (
          findings.map((f, i) => (
            <Button
              key={`${f.code}-${f.where}-${i}`}
              variant="ghost"
              className="finding"
              data-testid={`finding-${i}`}
              disabled={!f.selection}
              onClick={() => f.selection && locateSelection(f.selection)}
            >
              <Item
                title={<span className="where">{f.where}</span>}
                description={<span className="what">{f.message}</span>}
                trailing={
                  <Tag
                    tone={f.severity === "hard" ? "bad" : f.severity === "warn" ? "warn" : "ok"}
                  >
                    {f.severity === "hard" ? "막힘" : f.severity === "warn" ? "주의" : "확인"}
                  </Tag>
                }
              />
            </Button>
          ))
        )}
        <p className="empty">
          여기 있는 것은 이 빌드가 문서 구조와 서식에서 직접 읽어 낸 검사 결과입니다.
          렌더 증명이나 후보본 적용 시의 제출 검사 결과를 뜻하지 않습니다.
        </p>
      </div>
      </SheetContent>
    </Sheet>
  );
}
