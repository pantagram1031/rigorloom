/**
 * Status bar: three facts, then 자세히 for the former chip strip.
 *
 * Visible: document · verification pill · runtime connection.
 * Popover keeps every previous testid so honesty and overlay checks still
 * resolve. Glossary labels live on the chips; CLI/JSON keys are unchanged.
 */
import { exportApplied, openReceipt, reopenExported, runCheck } from "../actions";
import { setState, useWorkspace } from "../store";
import type { Candidate, InspectResult, Session } from "../types";
import { Icon } from "./Icon";
import { Tag } from "./Tag";

const GLOSSARY = {
  render:
    "페이지 그림은 보여줄 수 있어도 증거가 아닙니다. 런타임은 모든 렌더에 증명 없음(structural_only)을 붙입니다.",
  applyCheck:
    "후보본을 만들 때 돌린 검사입니다. 지금 다시 돌리는 버튼은 없습니다.",
  seats: "값을 넣도록 열린 칸입니다. 승인 전에는 파일이 바뀌지 않습니다.",
  format:
    "색·글꼴 등 서식 이상을 읽습니다. 제출용 검사가 아닙니다.",
  engine: "문서 엔진 연결 상태입니다. 프로세스 번호는 자세히에서 봅니다.",
  job: "창이 강제 종료돼도 엔진 자식 프로세스를 함께 끝낼 수 있는지입니다.",
  candidate: "승인·적용 후 생긴 사본입니다. 원본 파일은 그대로입니다.",
  source: "연 파일의 해시입니다. 이 앱은 원본을 고치지 않습니다.",
} as const;

const PILL_CAVEAT =
  "서식 점검입니다. 색·글꼴 등 서식 이상을 읽습니다. 제출용 검사가 아니며, 페이지 그림은 증거가 아닙니다.";

function Fact({
  k,
  v,
  title,
  nonce,
}: {
  k: string;
  v: React.ReactNode;
  title?: string;
  nonce?: string | number;
}) {
  return (
    <div className="fact" title={title}>
      <dt className="k">{k}</dt>
      <dd className="v xfade" key={nonce}>
        {v}
      </dd>
    </div>
  );
}

function Group({
  title,
  testId,
  children,
}: {
  title: string;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <section className="verify-group" data-testid={testId}>
      <h4>{title}</h4>
      <dl className="verify-dl">{children}</dl>
    </section>
  );
}

function verificationPill(args: {
  checkPhase: string;
  hard: number;
  warn: number;
  seatWarnings: number;
}): { label: string; tone: "none" | "ok" | "warn" | "bad" } {
  const { checkPhase, hard, warn, seatWarnings } = args;
  if (checkPhase === "starting") return { label: "검사 중", tone: "none" };
  if (checkPhase === "idle") {
    if (seatWarnings > 0) return { label: `주의 ${seatWarnings}`, tone: "warn" };
    return { label: "검사 안 함", tone: "none" };
  }
  if (checkPhase === "failed") return { label: hard > 0 ? `실패 ${hard}` : "실패", tone: "bad" };
  if (hard > 0) return { label: `실패 ${hard}`, tone: "bad" };
  if (warn > 0) return { label: `주의 ${warn}`, tone: "warn" };
  return { label: "통과", tone: "ok" };
}

export function VerificationBar({
  session,
  inspect,
  candidates,
  home = false,
}: {
  session: Session | null;
  inspect: InspectResult | null;
  candidates: Candidate[];
  home?: boolean;
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
  const geometry = useWorkspace((s) => s.geometry);
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const detailsOpen = useWorkspace((s) => s.verifyDetailsOpen);
  const caret = inlineEdit?.kind === "run" ? inlineEdit : null;

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
  const pill = verificationPill({ checkPhase, hard, warn, seatWarnings });
  const engineUp = Boolean(status?.running);
  const docName = session?.source.name ?? "문서 없음";
  const backendTag = session?.source.documentKind ?? "—";

  const chips = (
    <div className="verify-details-body" data-testid="verify-details">
      <div className="verify-details-head">
        <span>자세히</span>
        <button
          type="button"
          className="ghost btn-icon"
          data-testid="verify-details-close"
          aria-label="닫기"
          title="닫기"
          onClick={() => setState({ verifyDetailsOpen: false })}
        >
          <Icon name="x" />
        </button>
      </div>
      <Group title="문서" testId="verify-group-document">
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
        <Fact
          k="입력"
          nonce={caret ? `caret-${caret.atPara}-${caret.run}` : "none"}
          title={
            caret
              ? "지면의 줄 안에 커서가 있습니다. 이 편집기는 삽입만 하며 덮어쓰기 모드는 없습니다."
              : "한글의 삽입/수정 표시에 해당하는 자리입니다. 커서가 놓인 줄이 없으면 표시하지 않습니다."
          }
          v={
            caret ? (
              <Tag tone="fill" title="글자 단위 커서가 열려 있습니다">
                삽입
              </Tag>
            ) : (
              <span className="mono">—</span>
            )
          }
        />
        <Fact
          k="지면 출처"
          nonce={geometry?.geometrySource ?? "none"}
          title={
            geometry?.available && geometry.geometrySource === "own"
              ? "이 지면은 자체 렌더러가 그렸습니다. 자리와 커서는 서식 스캔으로 같은 규칙에 따라 맞춘 것이고, 렌더러가 스스로 밝힌 주소는 그 스캔과 맞을 때만 확정으로 칩니다. 그림 자체는 검증되지 않았습니다."
              : geometry?.available
                ? "이 지면은 한컴이 만든 PDF에서 읽은 것입니다. 글자 위치는 그 PDF 자신의 것입니다."
                : "본문 보기이거나 지면 좌표가 아직 없습니다."
          }
          v={
            mode === "page" && geometry?.available ? (
              <span
                className={geometry.geometrySource === "own" ? "mono warnish" : "mono"}
                data-testid="status-geometry-source"
                data-geometry-source={geometry.geometrySource ?? "pdf"}
              >
                {geometry.geometrySource === "own" ? "자체 렌더 · 미검증" : "한컴 PDF"}
              </span>
            ) : (
              <span className="mono" data-testid="status-geometry-source" data-geometry-source="">
                —
              </span>
            )
          }
        />
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
                      ? `지면에서 누른 곳이 가리키는 주소입니다. 이 자리의 위치는 ${overlayPick.derivation} 로 잡혔습니다.`
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
        <Fact
          k="원본"
          v={hash ? <span title={hash}>{hash.slice(0, 12)}</span> : "—"}
          title={hash ? `${GLOSSARY.source} ${hash}` : GLOSSARY.source}
          nonce={hash ?? "none"}
        />
        <Fact
          k="후보본"
          nonce={applied?.candidate.sha256 ?? candidates.length}
          title={
            applied ? `${GLOSSARY.candidate} ${applied.candidate.sha256}` : GLOSSARY.candidate
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
        <Fact
          k="그림 증명"
          v={<Tag tone="none">증명 없음</Tag>}
          title={GLOSSARY.render}
        />
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
      </Group>
      <Group title="검사" testId="verify-group-check">
        <Fact
          k="적용 시 검사"
          nonce={verdict ? `${verdict.runId}-${verdict.report.acceptance}` : "none"}
          title={
            verdict
              ? `${verdict.report.note}${verdict.report.reason ? ` — ${verdict.report.reason}` : ""}`
              : GLOSSARY.applyCheck
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
        {queued > 0 ? (
          <Fact
            k="검토 대기"
            nonce={queued}
            title="승인을 기다리는 작업. 아직 문서는 바뀌지 않았습니다."
            v={<Tag tone="fill">{queued}건</Tag>}
          />
        ) : null}
        <Fact k="입력 칸" v={inspect ? String(inspect.summary.fillTargetCount) : "—"} title={GLOSSARY.seats} />
        <Fact
          k="서식 점검"
          nonce={`${checkPhase}-${findings.length}`}
          title={checkedAt ? `${GLOSSARY.format} 마지막 검사 ${checkedAt}` : GLOSSARY.format}
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
      </Group>
      <Group title="엔진" testId="verify-group-engine">
        <Fact
          k="엔진"
          nonce={`${status?.running}-${status?.pid}`}
          title={GLOSSARY.engine}
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
          k="종료 시 정리"
          v={
            status?.jobConfined === true ? (
              <Tag tone="ok">보장됨</Tag>
            ) : status?.jobConfined === false ? (
              <Tag tone="bad">실패</Tag>
            ) : (
              <Tag tone="none">확인 안 됨</Tag>
            )
          }
          title={status?.jobError ?? GLOSSARY.job}
        />
      </Group>
      <div className="verify-details-actions">
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
      </div>
    </div>
  );

  if (home) {
    return (
      <footer className="verifybar is-home" data-testid="verification-bar">
        <span
          className="verify-engine"
          data-testid="verify-engine"
          title={GLOSSARY.engine}
        >
          {engineUp ? "엔진 연결됨" : "끊김"}
        </span>
      </footer>
    );
  }

  return (
    <footer className="verifybar" data-testid="verification-bar">
      <div className="verify-summary" data-testid="verify-summary">
        <span className="verify-doc" title={hash ?? undefined}>
          <span className="name" data-testid="verify-doc-name">
            {docName}
          </span>
          <span className="latin-caps" data-testid="verify-backend">
            {backendTag}
          </span>
        </span>
        <span className="sep" />
        <span className="verify-pill" data-testid="verify-pill" title={PILL_CAVEAT}>
          <Icon
            name={pill.tone === "ok" ? "check" : pill.tone === "bad" ? "x" : pill.tone === "warn" ? "warn" : "search"}
          />
          <Tag tone={pill.tone}>{pill.label}</Tag>
        </span>
        <span className="sep" />
        <span
          className="verify-engine"
          data-testid="verify-engine"
          title={GLOSSARY.engine}
        >
          {engineUp ? "엔진 연결됨" : "끊김"}
        </span>
      </div>
      <div className="right">
        <div className={`verify-popover${detailsOpen ? " is-open" : ""}`}>
          <button
            type="button"
            className="action btn-icon"
            data-testid="verify-details-toggle"
            aria-expanded={detailsOpen}
            aria-controls="verify-details-popover"
            title="쪽, 위치, 원본, 후보본 등 자세한 상태"
            onClick={() => setState({ verifyDetailsOpen: !detailsOpen })}
          >
            <Icon name="list" />
            자세히
          </button>
          <div
            id="verify-details-popover"
            className="verify-popover-panel"
            hidden={!detailsOpen}
            role="dialog"
            aria-label="검사 자세히"
          >
            {chips}
          </div>
        </div>
      </div>
    </footer>
  );
}
