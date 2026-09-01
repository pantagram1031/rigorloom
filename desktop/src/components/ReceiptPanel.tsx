/**
 * 영수증 보기 — what the receipt says, in Korean, with the JSON behind it.
 *
 * A receipt is the only artefact in this system that answers "why should I
 * believe this document is what you say it is", so rendering it as a JSON blob
 * would be handing the question back to the reader. It is rendered as four
 * bindings a person can check:
 *
 *   원본 → 후보본   the two digests, and the statement that the source is
 *                   untouched — `plan/apply` reads the session copy and writes
 *                   somewhere else, always;
 *   계획            which operations ran, in order, with their exit codes;
 *   승인            who approved it and which plan hash they were bound to;
 *   검사            what actually ran, and — the part that matters —
 *                   what did NOT.
 *
 * `acceptance` is never shown as a bare tick. It is true only when every
 * required check RAN and was clean, and when it is false the reason is printed
 * beside it, because "nothing failed" and "everything passed" are different
 * claims and this program's whole reason to exist is not confusing them.
 *
 * Reading a receipt is itself a proof step: `receipt/read` re-hashes the
 * artifact against its binding before returning, so an open panel means the
 * bytes on disk still match. When they do not, the refusal is what is shown.
 */
import { openReceipt } from "../actions";
import { useWorkspace } from "../store";
import type { Receipt } from "../types";
import { Tag } from "./Tag";

function Hash({ value }: { value: string }) {
  return (
    <span className="mono hash" title={value}>
      {value.slice(0, 16)}…
    </span>
  );
}

function Checks({ receipt }: { receipt: Receipt }) {
  const report = receipt.checks;
  return (
    <div className="receipt-block">
      <h4>검사</h4>
      <div className="receipt-verdict">
        {report.acceptance ? (
          <Tag tone="ok">받아들일 수 있음</Tag>
        ) : (
          <Tag tone="warn">받아들일 수 없음</Tag>
        )}
        {report.ranAll ? (
          <Tag tone="ok">필수 검사 모두 실행됨</Tag>
        ) : (
          <Tag tone="bad">실행되지 않은 필수 검사 있음</Tag>
        )}
      </div>
      {report.reason ? <p className="prose">{report.reason}</p> : null}
      <ul className="receipt-checks">
        {report.checks.map((row) => (
          <li key={String(row.checker)} data-testid={`receipt-check-${row.checker}`}>
            <span className="mono">{String(row.checker)}</span>
            {row.state === "ran" ? (
              row.ok === true ? (
                <Tag tone="ok">걸림 없음</Tag>
              ) : (
                <Tag tone="bad">걸림 있음</Tag>
              )
            ) : (
              <Tag tone="none">실행 안 됨</Tag>
            )}
            {row.state !== "ran" && row.reason ? (
              <span className="dim">{String(row.reason)}</span>
            ) : null}
          </li>
        ))}
      </ul>
      <p className="prose tiny">{report.note}</p>
      <p className="prose tiny">
        이 판정은 후보본을 만들 때 런타임이 실제로 돌린 오프라인 검사 결과입니다. 지금 다시
        돌린 것이 아닙니다 — <span className="mono">verify/*</span> 는 아직 프로토콜에
        없습니다.
      </p>
    </div>
  );
}

export function ReceiptPanel() {
  const runId = useWorkspace((s) => s.receiptOpen);
  const receipt = useWorkspace((s) => (s.receiptOpen ? s.receipts[s.receiptOpen] : undefined));
  const error = useWorkspace((s) => s.receiptError);

  if (!runId) return null;

  return (
    <section className="sheet receipt" data-testid="receipt-panel" aria-label="영수증">
      <header className="sheet-head">
        <h3>영수증</h3>
        <span className="count mono">{runId.slice(0, 12)}</span>
        <button
          className="ghost"
          style={{ color: "var(--fg-muted)" }}
          data-testid="close-receipt"
          onClick={() => openReceipt(null)}
        >
          닫기
        </button>
      </header>

      <div className="sheet-body">
        {error ? (
          <div className="refusal" data-testid="receipt-error">
            <Tag tone="bad">영수증을 읽지 못했습니다</Tag>
            <p className="prose">{error.message}</p>
            <p className="mono tiny">{error.code}</p>
            <p className="prose tiny">
              영수증은 자기가 묶어 둔 바이트가 그대로일 때만 내용을 내놓습니다. 읽히지 않는다는
              것은 그 자체로 답입니다.
            </p>
          </div>
        ) : !receipt ? (
          <p className="empty">영수증을 읽는 중입니다.</p>
        ) : (
          <>
            <div className="receipt-block">
              <h4>바이트</h4>
              <dl className="kv">
                <dt>원본</dt>
                <dd>
                  {receipt.source.name} · <Hash value={receipt.source.sha256} /> ·{" "}
                  {receipt.source.bytes.toLocaleString()} B
                </dd>
                <dt>후보본</dt>
                <dd>
                  {receipt.candidate.path} · <Hash value={receipt.candidate.sha256} /> ·{" "}
                  {receipt.candidate.bytes.toLocaleString()} B
                </dd>
                <dt>역할</dt>
                <dd className="mono">{receipt.candidate.role}</dd>
              </dl>
              <p className="prose tiny">
                원본은 입력이었을 뿐 결과가 아닙니다. 모든 단계는 파일 하나를 읽고 다른 파일을
                씁니다.
              </p>
            </div>

            <div className="receipt-block">
              <h4>계획</h4>
              <p className="mono tiny">
                {receipt.backend} · plan <Hash value={receipt.planHash} />
              </p>
              <ol className="receipt-steps">
                {receipt.steps.map((step) => (
                  <li key={step.opId}>
                    <span className="mono">{step.subcommand}</span>
                    <span className="dim">{step.kind}</span>
                    <Tag tone={step.exitCode === 0 ? "ok" : "bad"}>exit {step.exitCode}</Tag>
                  </li>
                ))}
              </ol>
            </div>

            <div className="receipt-block">
              <h4>승인</h4>
              <dl className="kv">
                <dt>결정</dt>
                <dd>
                  <Tag tone={receipt.approval.state === "approved" ? "ok" : "bad"}>
                    {receipt.approval.state === "approved" ? "승인" : receipt.approval.state}
                  </Tag>
                </dd>
                <dt>승인한 사람</dt>
                <dd>{receipt.approval.approver ?? "—"}</dd>
                <dt>요청한 쪽</dt>
                <dd>{receipt.approval.requestedBy}</dd>
                <dt>결정 시각</dt>
                <dd className="mono">{receipt.approval.resolvedUtc ?? "—"}</dd>
                <dt>묶인 계획</dt>
                <dd>
                  <Hash value={receipt.approval.planHash} />
                </dd>
              </dl>
            </div>

            <Checks receipt={receipt} />

            <div className="receipt-block">
              <h4>증거 등급</h4>
              <p className="prose">
                <Tag tone="none">{receipt.evidence.class}</Tag> {receipt.evidence.note}
              </p>
            </div>

            <details className="disclosure" data-testid="receipt-raw">
              <summary>자세히</summary>
              <pre>{JSON.stringify(receipt, null, 2)}</pre>
            </details>
          </>
        )}
      </div>
    </section>
  );
}
