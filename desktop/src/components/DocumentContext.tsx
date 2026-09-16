/**
 * Document facts for the 에이전트 inspector tab.
 *
 * Collapsed by default. Approvals stay in 검토 — this component must never
 * mount ReviewQueue or an approval/resolve control.
 */
import {
  activeCandidates,
  activeInspect,
  activeSession,
  selectionId,
  useWorkspace,
} from "../store";
import {
  activeReviewApprovalState,
  activeReviewQueueCount,
  activeReviewVerificationState,
  type ReviewVerificationState,
} from "../workspace/reviewSummary";
import { Tag } from "./Tag";

function Fact({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </>
  );
}

function ApprovalTag({ state }: { state: string | null }) {
  if (state === "pending") return <Tag tone="fill">대기</Tag>;
  if (state === "approved") return <Tag tone="ok">승인됨</Tag>;
  if (state === "rejected") return <Tag tone="warn">거절됨</Tag>;
  return <Tag tone="none">{state ?? "없음"}</Tag>;
}

function VerificationTag({ state }: { state: ReviewVerificationState }) {
  if (state === "partial") return <Tag tone="bad">일부 미실행</Tag>;
  if (state === "pass") return <Tag tone="ok">적용 시 검사 통과</Tag>;
  if (state === "fail") return <Tag tone="warn">적용 시 검사 걸림</Tag>;
  return <Tag tone="none">실행 안 함</Tag>;
}

export function DocumentContext() {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const candidates = useWorkspace(activeCandidates);
  const selection = useWorkspace((s) => s.selection);
  const zoom = useWorkspace((s) => s.zoom);
  const page = useWorkspace((s) => s.page);
  const queued = useWorkspace(activeReviewQueueCount);
  const approvalState = useWorkspace(activeReviewApprovalState);
  const verificationState = useWorkspace(activeReviewVerificationState);

  return (
    <details className="disclosure document-facts" data-testid="document-facts">
      <summary>문서 정보</summary>
      {!session ? (
        <p className="empty">문서를 열면 여기에 문서의 상태가 모입니다.</p>
      ) : (
        <>
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
          </div>

          <div className="section">
            <h3>작업과 증명</h3>
            <dl className="kv">
              <Fact
                k="이 문서 작업"
                v={queued > 0 ? <Tag tone="fill">{queued}건</Tag> : <Tag tone="none">0건</Tag>}
              />
              <Fact k="승인" v={<ApprovalTag state={approvalState} />} />
              <Fact
                k="후보본"
                v={
                  candidates.length ? (
                    <Tag tone="ok">{candidates.length}</Tag>
                  ) : (
                    <Tag tone="none">0</Tag>
                  )
                }
              />
              <Fact k="제출 검사" v={<VerificationTag state={verificationState} />} />
              <Fact k="렌더 증명" v={<Tag tone="none">증명 없음</Tag>} />
            </dl>
            <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
              승인은 검토 탭에서만 합니다. 에이전트 연결에는 그 기능이 없습니다.
            </p>
          </div>
        </>
      )}
    </details>
  );
}
