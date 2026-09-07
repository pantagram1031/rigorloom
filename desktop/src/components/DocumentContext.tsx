/**
 * Agent view, right: the document as context.
 *
 * The mirror of Document view's ContextPanel. Same Workspace, same selection —
 * selecting a cell in Document view and switching here shows that cell, because
 * there is only one selection in the app.
 */
import {
  activeCandidates,
  activeInspect,
  activeSession,
  selectionId,
  useWorkspace,
} from "../store";
import { Tag } from "./Tag";

function Fact({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </>
  );
}

export function DocumentContext() {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const candidates = useWorkspace(activeCandidates);
  const selection = useWorkspace((s) => s.selection);
  const zoom = useWorkspace((s) => s.zoom);
  const page = useWorkspace((s) => s.page);
  const draft = useWorkspace((s) => s.draft);
  const approval = useWorkspace((s) => s.approval);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const candidateVerdict = useWorkspace((s) => s.candidateVerdict);

  const approvalStatus =
    approvalPhase === "requesting" || approvalPhase === "resolving"
      ? <Tag tone="warn">처리 중</Tag>
      : approval?.state === "approved"
        ? <Tag tone="ok">승인됨</Tag>
        : approval?.state === "rejected"
          ? <Tag tone="bad">거절됨</Tag>
          : approval
            ? <Tag tone="warn">승인 대기</Tag>
            : <Tag tone="none">없음</Tag>;

  const verificationStatus =
    draft.phase === "starting"
      ? <Tag tone="warn">계획 확인 중</Tag>
      : draft.validation
        ? draft.validation.ok
          ? <Tag tone="ok">계획 통과</Tag>
          : <Tag tone="bad">계획 막힘</Tag>
        : candidateVerdict
          ? candidateVerdict.report.acceptance
            ? <Tag tone="ok">적용 시 통과</Tag>
            : <Tag tone="bad">적용 시 미통과</Tag>
          : <Tag tone="none">실행 안 함</Tag>;

  if (!session) {
    return (
      <aside className="panel" aria-label="문서 정보">
        <div className="panel-head">
          <span className="panel-title">문서 정보</span>
        </div>
        <div className="panel-body">
          <p className="empty">문서를 열면 여기에 문서의 상태가 모입니다.</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="panel" aria-label="문서 정보">
      <div className="panel-head">
        <span className="panel-title">문서 정보</span>
      </div>
      <div className="panel-body">
        <div className="section">
          <h3>원본</h3>
          <dl className="kv">
            <Fact k="이름" v={session.source.name} />
            <Fact k="종류" v={session.source.documentKind} />
            <Fact k="크기" v={`${session.source.bytes.toLocaleString()} B`} />
            <Fact k="sha256" v={session.source.sha256} />
            <Fact k="연 시각" v={session.openedUtc} />
          </dl>
        </div>

        {inspect ? (
          <div className="section">
            <h3>구조</h3>
            <dl className="kv">
              <Fact k="표" v={String(inspect.summary.formatHints.table_count)} />
              <Fact k="문단" v={String(inspect.graph.paragraphs.length)} />
              <Fact k="채움 자리" v={String(inspect.summary.fillTargetCount)} />
              <Fact k="여백 칸" v={String(inspect.summary.spacerCells.length)} />
              <Fact
                k="수식 자리"
                v={inspect.summary.formatHints.has_eq_placeholder ? "있음" : "없음"}
              />
              <Fact
                k="쪽 크기"
                v={`${inspect.summary.pageMetrics.width} × ${inspect.summary.pageMetrics.height}`}
              />
              <Fact
                k="한 줄 글자"
                v={`${inspect.summary.pageMetrics.chars_per_line}자 · ${inspect.summary.pageMetrics.lines_per_page}줄`}
              />
            </dl>
          </div>
        ) : null}

        <div className="section">
          <h3>선택</h3>
          <dl className="kv">
            <Fact k="위치" v={selectionId(selection)} />
            <Fact k="쪽" v={String(page)} />
            <Fact k="배율" v={`${Math.round(zoom * 100)}%`} />
          </dl>
          <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
            두 화면은 같은 선택을 봅니다. 화면을 바꿔도 고른 자리는 그대로입니다.
          </p>
        </div>

        <div className="section">
          <h3>작업과 증명</h3>
          <dl className="kv">
            <Fact
              k="제안된 작업"
              v={
                draft.ops.length > 0
                  ? <Tag tone="fill">{draft.ops.length}</Tag>
                  : <Tag tone="none">0</Tag>
              }
            />
            <Fact k="승인" v={approvalStatus} />
            <Fact
              k="후보본"
              v={candidates.length ? <Tag tone="ok">{candidates.length}</Tag> : <Tag tone="none">0</Tag>}
            />
            <Fact k="검증" v={verificationStatus} />
            <Fact k="렌더 증명" v={<Tag tone="none">증명 없음</Tag>} />
          </dl>
          <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
            문서 화면과 같은 검토 대기열, 승인, 후보본 상태를 그대로 읽습니다.
          </p>
        </div>
      </div>
    </aside>
  );
}
