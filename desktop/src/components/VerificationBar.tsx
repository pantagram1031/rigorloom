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
  const overlayPick = useWorkspace((s) => s.overlayPick);
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const caret = inlineEdit?.kind === "run" ? inlineEdit : null;

  // The address, spelled the way the runtime addresses it. Never a line and
  // column — the document has no such coordinate — but where a caret IS
  // standing in a line, the character offset it stands at is a measured
  // number and is printed. `null` there means the line carried no per-
  // character boxes, so the offset says 줄 앞 rather than 0: a fallback
  // dressed as a measurement is the failure this whole feature avoids.
  const where = !selection
    ? "선택 없음"
    : selection.kind === "cell"
      ? `표${selection.table} (${selection.row},${selection.col})`
      : selection.kind === "paragraph"
        ? caret
          ? `문단 ${caret.atPara} · 덩어리 ${caret.run} · ${
              caret.caret === null ? "줄 앞" : `${caret.caret}번째 글자 앞`
            }`
          : `문단 ${selection.atPara}`
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
        title={
          caret
            ? "고른 곳의 주소입니다. 지금은 지면의 한 줄 안에 글자 단위 커서가 있습니다."
            : "고른 곳의 주소입니다. 커서가 놓인 줄이 없으면 칸 단위입니다."
        }
        v={
          <span className="mono" data-testid="status-where">
            {where}
          </span>
        }
      />
      {/* 삽입/수정, and it used to be neither.
          The old copy read "이 빌드에는 글자 단위 커서가 없어" and it was
          true: the only editor was a seat, opened whole and replaced whole.
          With a caret standing in a paragraph line there IS a character-level
          cursor, and it is in insert mode because the field is a real `<input>`
          — so the indicator says so while one is open, and goes back to saying
          there is none the moment it closes. It never says 수정: nothing in
          this build overwrites, and an indicator offering a mode that does not
          exist is the same fabrication as a font name nobody declared. */}
      <Fact
        k="입력"
        nonce={caret ? `caret-${caret.atPara}-${caret.run}` : "none"}
        title={
          caret
            ? "지면의 줄 안에 커서가 있습니다. 이 편집기는 삽입만 하며 덮어쓰기 모드는 없습니다."
            : "한글의 삽입/수정 표시에 해당하는 자리입니다. 커서가 놓인 줄이 없으면 둘 중 어느 상태도 아닙니다."
        }
        v={
          caret ? (
            <Tag tone="fill" title="글자 단위 커서가 열려 있습니다">
              삽입
            </Tag>
          ) : (
            <Tag tone="none">삽입/수정 없음</Tag>
          )
        }
      />
      {/* What the last click ON THE PAGE resolved to. Only in 페이지 보기,
          because that is the only mode where a click has a rectangle to have
          landed in — and an ambiguous one says 후보 N개 rather than an
          address, because there is no address yet and there will not be one
          until a person picks. */}
      {mode === "page" && overlayPick ? (
        <Fact
          k="지면 선택"
          nonce={`${overlayPick.kind}-${overlayPick.label}`}
          title={
            overlayPick.kind === "ambiguous"
              ? "같은 글자를 가진 주소가 여럿입니다. 런타임도 이 앱도 그 중 하나를 고르지 않습니다."
              : overlayPick.kind === "caret"
                ? overlayPick.caret === null
                  ? "이 줄은 렌더러가 글자별 위치를 내주지 않아, 커서를 줄 앞에 놓았습니다. 누른 자리에 놓은 것이 아닙니다."
                  : "누른 자리에 커서를 놓았습니다. 몇 번째 글자인지는 런타임이 지면에서 읽어 준 글자별 위치로 정해집니다."
                : overlayPick.kind === "no_caret"
                  ? "이 줄은 주소가 잡혔지만, 고쳐 쓸 글 덩어리를 하나로 특정할 수 없어 커서를 놓지 않았습니다."
                  : overlayPick.derivation
                    ? // The derivation belongs where the address is, not only
                      // in a hover: a seat is one of two overlay classes a
                      // person types into, and how its rectangle was found is
                      // how much to trust it.
                      `지면에서 누른 곳이 가리키는 주소입니다. 이 자리의 위치는 ${overlayPick.derivation} 로 잡혔습니다.`
                    : "지면에서 누른 곳이 가리키는 주소입니다."
          }
          v={
            <span
              className={
                overlayPick.kind === "ambiguous" || overlayPick.kind === "no_caret"
                  ? "mono warnish"
                  : "mono"
              }
              data-testid="status-overlay-pick"
              data-pick-kind={overlayPick.kind}
              data-derivation={overlayPick.derivation ?? ""}
              data-caret={overlayPick.kind === "caret" ? (overlayPick.caret ?? "start") : ""}
              data-refusal={overlayPick.refusal ?? ""}
            >
              {overlayPick.label}
            </span>
          }
        />
      ) : null}
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
