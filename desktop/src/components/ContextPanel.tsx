/**
 * Document view, right column: what is true about the current selection.
 *
 * The agent panel proper is the next slice. This phase shows the honest
 * precursor — the selection's own facts, and a statement of what the agent
 * surface will be and is not yet. It does not mock a conversation.
 */
import { beginEdit } from "../actions";
import { selectionId, useWorkspace, type Selection } from "../store";
import type { InspectResult, SidecarStatus } from "../types";
import { History } from "./History";
import { ReviewQueue } from "./ReviewQueue";
import { CLASSIFICATION_LABEL, Tag } from "./Tag";

function Fact({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </>
  );
}

function CellDetail({ inspect, sel }: { inspect: InspectResult; sel: Extract<Selection, { kind: "cell" }> }) {
  const table = inspect.graph.tables.find((t) => t.index === sel.table);
  const cell = table?.cells.find((c) => c.addr.row === sel.row && c.addr.col === sel.col);
  if (!cell) {
    return <p className="empty">이 주소의 칸을 문서 그래프에서 찾지 못했습니다.</p>;
  }
  const seat = inspect.regions.regions.find(
    (r) => r.kind === "cell" && r.table === sel.table && r.row === sel.row && r.col === sel.col,
  );
  return (
    <>
      <div className="section">
        <h3>칸 {`표 ${sel.table} R${sel.row}C${sel.col}`}</h3>
        <dl className="kv">
          <Fact
            k="분류"
            v={
              <Tag tone={cell.classification === "fill_target" ? "fill" : "none"}>
                {CLASSIFICATION_LABEL[cell.classification] ?? cell.classification}
              </Tag>
            }
          />
          {cell.spacerPattern ? <Fact k="여백 형태" v={cell.spacerPattern} /> : null}
          {cell.charPr ? <Fact k="charPr" v={cell.charPr} /> : null}
          {cell.charPrSuggested ? <Fact k="권장 charPr" v={cell.charPrSuggested} /> : null}
        </dl>
      </div>

      {cell.textPreview ? (
        <div className="section">
          <h3>미리보기{cell.truncated ? " (잘림)" : ""}</h3>
          <p className="prose" style={{ userSelect: "text" }}>
            {cell.textPreview}
          </p>
          {cell.truncated ? (
            <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
              전체 글자는 요청해야 옵니다. 구조만 보내는 것이 기본값입니다.
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="section">
        <h3>쓰기 전 확인</h3>
        {seat ? (
          <dl className="kv">
            <Fact
              k="색 이상"
              v={
                seat.colorAnomaly ? (
                  <Tag tone="bad">있음</Tag>
                ) : seat.colorAnomaly === false ? (
                  <Tag tone="ok">없음</Tag>
                ) : (
                  <Tag tone="none">판단 불가</Tag>
                )
              }
            />
            <Fact
              k="글자속성 이상"
              v={
                seat.scriptAnomaly ? (
                  <Tag tone="warn">있음</Tag>
                ) : seat.scriptAnomaly === false ? (
                  <Tag tone="ok">없음</Tag>
                ) : (
                  <Tag tone="none">판단 불가</Tag>
                )
              }
            />
          </dl>
        ) : (
          <p className="prose">
            이 칸은 값을 넣는 자리가 아닙니다. 쓰기 전 확인은 채움 자리에만 붙습니다.
          </p>
        )}
        {seat?.colorAnomaly ? (
          <p className="prose" style={{ color: "var(--bad)", marginTop: "var(--s2)" }}>
            글자색이 본문 기준과 다릅니다. 이대로 채우면 색이 남습니다.
          </p>
        ) : null}
        {seat ? (
          <button
            className="action primary"
            data-testid="edit-seat"
            style={{ marginTop: "var(--s3)" }}
            onClick={() => beginEdit(sel.table, sel.row, sel.col)}
          >
            이 자리에 값 넣기
          </button>
        ) : null}
      </div>
    </>
  );
}

function ParagraphDetail({ inspect, atPara }: { inspect: InspectResult; atPara: number }) {
  const para = inspect.graph.paragraphs.find((p) => p.at_para === atPara);
  if (!para) return <p className="empty">이 문단을 찾지 못했습니다.</p>;
  const removal = inspect.summary.removalTargets.find((t) => t.para_idx === para.para_idx);
  return (
    <>
      <div className="section">
        <h3>문단 at_para {para.at_para}</h3>
        <dl className="kv">
          <Fact k="구역" v={para.section} />
          <Fact k="para_idx" v={String(para.para_idx)} />
          {removal ? <Fact k="삭제 후보" v={`확신도 ${removal.confidence}`} /> : null}
        </dl>
      </div>
      <div className="section">
        <h3>본문</h3>
        <p className="prose" style={{ userSelect: "text", color: "var(--fg)" }}>
          {para.text || "(빈 문단)"}
        </p>
      </div>
    </>
  );
}

export function ContextPanel({
  inspect,
  status,
}: {
  inspect: InspectResult | null;
  status: SidecarStatus | null;
}) {
  const selection = useWorkspace((s) => s.selection);
  const id = selectionId(selection);

  return (
    <aside className="panel" aria-label="선택 항목">
      <div className="panel-head">
        <span className="panel-title">선택 항목</span>
        <span className="count" data-testid="selection-id">
          {id}
        </span>
      </div>
      <div className="panel-body">
        {!inspect || !selection ? (
          <p className="empty">
            왼쪽에서 문단이나 표의 칸을 고르면 그 자리에 대해 아는 것을 여기에 모아
            보여 줍니다.
          </p>
        ) : selection.kind === "cell" ? (
          <CellDetail inspect={inspect} sel={selection} />
        ) : selection.kind === "paragraph" ? (
          <ParagraphDetail inspect={inspect} atPara={selection.atPara} />
        ) : (
          <div className="section">
            <h3>표 {selection.table}</h3>
            <dl className="kv">
              <Fact
                k="칸"
                v={String(
                  inspect.graph.tables.find((t) => t.index === selection.table)?.cells.length ?? 0,
                )}
              />
            </dl>
          </div>
        )}

        {/* The queue is the reason this column exists in Phase 4. It sits
            below the selection's facts because the order of work is: look at
            the seat, decide, then review what you decided. */}
        <ReviewQueue />

        {/* 기록 sits under the queue for the same reason the queue sits under
            the selection: the order of work is decide, review, then look at
            what has already been decided — and undo is reached from what has
            already been decided, never from the queue. */}
        <History />

        <div className="section">
          <h3>연결</h3>
          <dl className="kv">
            <Fact
              k="세션"
              v={
                status?.initialized ? (
                  <Tag tone="ok">연결됨</Tag>
                ) : status?.running ? (
                  <Tag tone="warn">준비 중</Tag>
                ) : (
                  <Tag tone="bad">끊김</Tag>
                )
              }
            />
            <Fact k="권한" v={<Tag tone="ok">호스트</Tag>} />
          </dl>
          <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
            이 창은 호스트 권한으로 붙어 있습니다. 승인은 여기에서만 할 수 있고, 에이전트
            연결에는 그 기능 자체가 없습니다.
          </p>
        </div>
      </div>
    </aside>
  );
}
