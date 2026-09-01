/**
 * The always-visible truth strip, and the only place proof state may appear.
 *
 * The proof-grade vocabulary is the strongest concept in the codebase and is
 * kept verbatim: three states, read from one canonical file, and an advisory
 * render never displayed without its qualification.
 *
 * Phase 4 moved exactly one of these badges and left the rest alone, which is
 * the discipline worth recording:
 *
 * - **제출 검사** now reports a real verdict once a candidate exists, because
 *   one really ran: `check_residue` executes inside `plan/apply`, and
 *   `receipt/read` re-hashes the artifact against its binding before handing
 *   the result over. The badge says 적용 시 검사 rather than 검사됨, because
 *   what it can show is the verdict from the apply, not a fresh re-run.
 *   `verify/*` is still GAP, and a button that pretended to re-run it would be
 *   the exact lie this bar exists to prevent.
 * - **렌더 증명** did NOT move. `document/render` can now produce a raster, and
 *   a raster is still not evidence: `rt_render` stamps every result
 *   `structural_only` / `proofGrade: none`, and this badge repeats that rather
 *   than promoting a picture to a proof.
 * - **원본** and **후보본** sit next to each other with both digests visible,
 *   so "the source is unchanged" is something the user reads off the screen
 *   rather than something the application asserts.
 */
import { exportApplied, openReceipt, reopenExported, runCheck } from "../actions";
import { setState, useWorkspace } from "../store";
import type { Candidate, InspectResult, Session } from "../types";
import { Tag } from "./Tag";

function Fact({
  k,
  v,
  title,
  nonce,
}: {
  k: string;
  v: React.ReactNode;
  title?: string;
  /** Changing this cross-fades the value instead of snapping it. */
  nonce?: string | number;
}) {
  return (
    <div className="fact" title={title}>
      <span className="k">{k}</span>
      <span className="v xfade" key={nonce}>
        {v}
      </span>
    </div>
  );
}

export function VerificationBar({
  session,
  inspect,
  candidates,
}: {
  session: Session | null;
  inspect: InspectResult | null;
  candidates: Candidate[];
}) {
  const status = useWorkspace((s) => s.status);
  const checkPhase = useWorkspace((s) => s.checkPhase);
  const findings = useWorkspace((s) => s.findings);
  const checkedAt = useWorkspace((s) => s.checkedAt);
  const sheetOpen = useWorkspace((s) => s.sheetOpen);
  const applied = useWorkspace((s) => s.applied);
  const verdict = useWorkspace((s) => s.candidateVerdict);
  const exportPhase = useWorkspace((s) => s.exportPhase);
  const exportResult = useWorkspace((s) => s.exportResult);
  const exportError = useWorkspace((s) => s.exportError);
  const reopened = useWorkspace((s) => s.reopened);
  const queued = useWorkspace((s) => s.draft.ops.length);
  const mode = useWorkspace((s) => s.centerMode);
  const page = useWorkspace((s) => s.page);
  const pageCount = useWorkspace((s) => s.render?.pageCount ?? 1);
  const selection = useWorkspace((s) => s.selection);

  // The address, spelled the way the runtime addresses it. Never a line and
  // column: this build has no caret and inventing one would be a lie about
  // where the user is standing.
  const where = !selection
    ? "선택 없음"
    : selection.kind === "cell"
      ? `표${selection.table} (${selection.row},${selection.col})`
      : selection.kind === "paragraph"
        ? `문단 ${selection.atPara}`
        : `표${selection.table}`;

  const hash = inspect?.documentHash ?? session?.source.sha256 ?? null;
  const hard = findings.filter((f) => f.severity === "hard").length;
  const warn = findings.filter((f) => f.severity === "warn").length;
  const seatWarnings = inspect
    ? inspect.regions.regions.filter((r) => r.colorAnomaly || r.scriptAnomaly).length
    : 0;

  return (
    <footer className="verifybar" data-testid="verification-bar">
      {/* Hangul-editor status conventions, and only where there is a real
          answer. 쪽 is the renderer's own page number and reads — in 본문 보기,
          where the runtime maps no text to any page; 위치 is the selection's
          address, which is the only cursor this build has; and the insert /
          overwrite indicator every Hangul editor carries says NEITHER, because
          there is no caret to be in a mode — editing happens per seat. An
          indicator that said 삽입 would be inventing a caret. */}
      <Fact
        k="쪽"
        nonce={`${mode}-${page}-${pageCount}`}
        title={
          mode === "page"
            ? "그려진 지면의 쪽 번호입니다."
            : "본문 보기에는 쪽이 없습니다. 런타임은 글이 몇 쪽에 놓이는지 알려주지 않습니다."
        }
        v={
          mode === "page" ? (
            <span className="mono">
              {page} / {pageCount}
            </span>
          ) : (
            <span className="mono">—</span>
          )
        }
      />
      <Fact
        k="위치"
        nonce={where}
        title="고른 곳의 주소입니다. 이 편집기의 커서는 칸 단위입니다."
        v={
          <span className="mono" data-testid="status-where">
            {where}
          </span>
        }
      />
      <Fact
        k="입력"
        title="한글의 삽입/수정 표시에 해당하는 자리입니다. 이 빌드에는 글자 단위 커서가 없어 둘 중 어느 상태도 아닙니다."
        v={<Tag tone="none">삽입/수정 없음</Tag>}
      />
      <div className="sep" />
      <Fact
        k="원본"
        v={hash ? <span title={hash}>{hash.slice(0, 12)}</span> : "—"}
        title={hash ?? undefined}
        nonce={hash ?? "none"}
      />
      <div className="sep" />
      <Fact
        k="후보본"
        nonce={applied?.candidate.sha256 ?? candidates.length}
        title={
          applied
            ? `후보본 ${applied.candidate.sha256}`
            : "승인된 계획을 적용하면 후보본이 생깁니다."
        }
        v={
          applied ? (
            <button
              className="linkish mono"
              data-testid="candidate-hash"
              title="영수증을 엽니다"
              onClick={() => openReceipt(applied.runId)}
            >
              {applied.candidate.sha256.slice(0, 12)}
            </button>
          ) : candidates.length === 0 ? (
            <Tag tone="none">없음</Tag>
          ) : (
            <button
              className="linkish"
              data-testid="candidate-count"
              onClick={() => openReceipt(candidates[candidates.length - 1]?.runId ?? null)}
            >
              {candidates.length}개
            </button>
          )
        }
      />
      <div className="sep" />
      {/* Never a bare colour: the label is the signal, the tone is support. */}
      <Fact
        k="렌더 증명"
        v={<Tag tone="none">증명 없음</Tag>}
        title="페이지를 그릴 수는 있어도 그림은 증거가 아닙니다. 런타임은 모든 렌더 결과에 structural_only / proofGrade none 을 붙입니다."
      />
      <Fact
        k="제출 검사"
        nonce={verdict ? `${verdict.runId}-${verdict.report.acceptance}` : "none"}
        title={
          verdict
            ? `${verdict.report.note}${verdict.report.reason ? ` — ${verdict.report.reason}` : ""}`
            : "후보본이 있어야 검사 결과가 있습니다. verify/* 로 지금 다시 돌리는 방법은 아직 없습니다."
        }
        v={
          !verdict ? (
            <Tag tone="none">실행 안 함</Tag>
          ) : !verdict.report.ranAll ? (
            <Tag tone="bad">일부 미실행</Tag>
          ) : verdict.report.acceptance ? (
            <Tag tone="ok">적용 시 검사 통과</Tag>
          ) : (
            <Tag tone="warn">적용 시 검사 걸림</Tag>
          )
        }
      />
      <div className="sep" />
      {queued > 0 ? (
        <>
          <Fact
            k="대기"
            nonce={queued}
            title="승인을 기다리는 작업. 아직 문서는 바뀌지 않았습니다."
            v={<Tag tone="fill">{queued}건</Tag>}
          />
          <div className="sep" />
        </>
      ) : null}
      <Fact k="채움 자리" v={inspect ? String(inspect.summary.fillTargetCount) : "—"} />
      <Fact
        k="서식 검사"
        nonce={`${checkPhase}-${findings.length}`}
        title={checkedAt ? `마지막 검사 ${checkedAt}` : "아직 검사하지 않았습니다"}
        v={
          checkPhase === "starting" ? (
            <Tag tone="none">읽는 중</Tag>
          ) : checkPhase === "idle" ? (
            seatWarnings > 0 ? (
              <Tag tone="warn">주의 {seatWarnings}</Tag>
            ) : (
              <Tag tone="none">미실행</Tag>
            )
          ) : hard > 0 ? (
            <Tag tone="bad">막힘 {hard}</Tag>
          ) : warn > 0 ? (
            <Tag tone="warn">주의 {warn}</Tag>
          ) : (
            <Tag tone="ok">걸림 없음</Tag>
          )
        }
      />

      <div className="right">
        {applied ? (
          <>
            <button
              className="action"
              data-testid="open-receipt"
              onClick={() => openReceipt(applied.runId)}
            >
              영수증 보기
            </button>
            <button
              className="action"
              data-testid="export-candidate"
              disabled={exportPhase === "starting"}
              title="후보본과 영수증을 함께 저장합니다"
              onClick={() => void exportApplied()}
            >
              {exportPhase === "starting" ? "내보내는 중…" : "내보내기"}
            </button>
          </>
        ) : null}
        {exportResult && !reopened ? (
          <button
            className="action"
            data-testid="reopen-export"
            title={exportResult.path}
            onClick={() => void reopenExported()}
          >
            내보낸 파일 열어 확인
          </button>
        ) : null}
        {reopened ? (
          <Fact
            k="내보냄"
            nonce={reopened.sha256}
            title={`${reopened.path}\n${reopened.sha256}`}
            v={<Tag tone="ok">다시 열림</Tag>}
          />
        ) : null}
        {exportError ? (
          <Fact
            k="내보내기"
            nonce={exportError.code}
            title={exportError.message}
            v={<Tag tone="bad">실패</Tag>}
          />
        ) : null}
        {findings.length > 0 && !sheetOpen ? (
          <button
            className="action"
            data-testid="open-findings"
            onClick={() => setState({ sheetOpen: true })}
          >
            결과 보기
          </button>
        ) : null}
        <button
          className="action"
          data-testid="run-check"
          disabled={!inspect || checkPhase === "starting"}
          onClick={() => void runCheck()}
        >
          {checkPhase === "starting" ? "검사 중…" : "검사 실행"}
        </button>
        <div className="sep" />
        <Fact
          k="런타임"
          nonce={`${status?.running}-${status?.pid}`}
          v={
            !status?.running ? (
              <Tag tone="bad">끊김</Tag>
            ) : !status.initialized ? (
              <Tag tone="warn">준비 중</Tag>
            ) : (
              <span>
                pid {status.pid} · {status.mode === "packaged" ? "패키지" : "개발"}
              </span>
            )
          }
        />
        <Fact
          k="자식 정리"
          v={
            status?.jobConfined === true ? (
              <Tag tone="ok">보장됨</Tag>
            ) : status?.jobConfined === false ? (
              <Tag tone="bad">실패</Tag>
            ) : (
              <Tag tone="none">확인 안 됨</Tag>
            )
          }
          title={
            status?.jobError ??
            "작업 개체로 사이드카를 묶어 두었습니다. 셸이 강제 종료되어도 함께 정리됩니다."
          }
        />
      </div>
    </footer>
  );
}
