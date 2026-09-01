/**
 * 검토 대기열 — every pending edit, and what the Runtime says about it.
 *
 * This panel is the product. Everything else in the application either gets a
 * person here or shows them the result of what they decided here, and the one
 * property it must never lose is that **what is approved is exactly what is
 * shown**: one plan, one hash, every operation listed with its address and its
 * before → after, and the validator's own verdict beside it.
 *
 * Four things are stated rather than implied, because each of them is a place
 * a document tool can quietly lie:
 *
 * 1. **Who proposed each op.** A user's edit and an agent's proposal are
 *    approved by the same gate, but they are not the same thing, and a
 *    reviewer must be able to see which is which without asking.
 * 2. **The verdict is the Runtime's**, passed through with its codes and its
 *    payload. `fill_charpr_script_anomaly` carries the charPr the engine
 *    suggests; the fix button uses that value and nothing else.
 * 3. **A clean validation is not a promise.** `preflight.deferred` lists the
 *    refusals only the engine can raise, and it is on screen — a green queue
 *    that turned out to be refusable at apply would otherwise read as a bug in
 *    the approval rather than as the documented boundary it is.
 * 4. **Staleness is a refusal, not a warning.** A queue bound to other bytes
 *    cannot be approved at all, and the panel offers the one thing that fixes
 *    it: propose again against what is open now.
 */
import {
  declareSuggestedCharPr,
  editOpValue,
  removeOp,
  reproposeDraft,
  requestApprovalForDraft,
  resolveApprovalDecision,
  cancelApply,
  clearQueue,
  resolveRecovery,
} from "../actions";
import {
  canRequestApproval,
  draftStaleness,
  locateSelection,
  useWorkspace,
  type QueuedOp,
} from "../store";
import type { PlanFinding } from "../types";
import { Tag } from "./Tag";

/** Findings that name one op, keyed the way `validate_plan` writes `at`. */
function findingsFor(op: QueuedOp, rows: PlanFinding[]): PlanFinding[] {
  return rows.filter((row) => row.at === `ops[${op.opId}]`);
}

function OpRow({
  op,
  hard,
  warn,
  locked,
}: {
  op: QueuedOp;
  hard: PlanFinding[];
  warn: PlanFinding[];
  locked: boolean;
}) {
  const anomaly = hard.find((f) => f.code === "fill_charpr_script_anomaly");
  return (
    <li className="queue-op" data-testid={`queue-op-${op.table}-${op.row}-${op.col}`}>
      <div className="queue-op-head">
        <button
          className="addr mono"
          title="문서에서 이 자리를 찾습니다"
          onClick={() =>
            locateSelection({ kind: "cell", table: op.table, row: op.row, col: op.col })
          }
        >
          표 {op.table} R{op.row}C{op.col}
        </button>
        {op.origin === "agent" ? (
          <Tag tone="none" title={`제안: ${op.proposer ?? "에이전트"}`}>
            에이전트 제안
          </Tag>
        ) : (
          <Tag tone="fill">내가 입력</Tag>
        )}
        {op.charPr ? (
          <Tag tone="ok" title="이 자리에 쓸 글자 속성을 지정했습니다">
            charPr {op.charPr}
          </Tag>
        ) : null}
        <button
          className="ghost dark-safe"
          data-testid={`queue-remove-${op.table}-${op.row}-${op.col}`}
          disabled={locked}
          title="이 작업을 대기열에서 뺍니다"
          onClick={() => void removeOp(op.opId)}
        >
          빼기
        </button>
      </div>

      <div className="queue-diff">
        <span className="was" data-testid={`queue-before-${op.opId}`}>
          {op.before.trim().length > 0 ? op.before : "(빈 자리)"}
        </span>
        <span className="arrow" aria-hidden="true">
          →
        </span>
        <input
          className="queue-value"
          data-testid={`queue-value-${op.opId}`}
          value={op.text}
          disabled={locked}
          aria-label="넣을 값"
          onChange={(e) => void editOpValue(op.opId, e.target.value)}
        />
      </div>

      {hard.map((row) => (
        <p className="queue-finding hard" key={`${row.code}-${row.at}`}>
          <Tag tone="bad">막힘</Tag>
          <span>{row.msg}</span>
          <code className="mono">{row.code}</code>
        </p>
      ))}
      {warn.map((row) => (
        <p className="queue-finding warn" key={`${row.code}-${row.at}`}>
          <Tag tone="warn">주의</Tag>
          <span>{row.msg}</span>
          <code className="mono">{row.code}</code>
        </p>
      ))}

      {anomaly && !op.charPr ? (
        <button
          className="action"
          data-testid={`queue-fix-charpr-${op.opId}`}
          disabled={locked}
          onClick={() => void declareSuggestedCharPr(op.opId)}
        >
          권장 charPr {String(anomaly.charPrSuggested ?? "")} 지정
        </button>
      ) : null}
    </li>
  );
}

export function ReviewQueue() {
  const draft = useWorkspace((s) => s.draft);
  const validation = draft.validation;
  const staleness = useWorkspace(draftStaleness);
  const approvable = useWorkspace(canRequestApproval);
  const approval = useWorkspace((s) => s.approval);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const approvalError = useWorkspace((s) => s.approvalError);
  const applyPhase = useWorkspace((s) => s.applyPhase);
  const applyError = useWorkspace((s) => s.applyError);
  const recovery = useWorkspace((s) => s.recovery);

  const locked = approvalPhase === "resolving" || applyPhase === "starting";

  if (draft.ops.length === 0) {
    return (
      <div className="section" data-testid="review-queue-empty">
        <h3>검토 대기열</h3>
        <p className="prose">
          비어 있습니다. 가운데 문서에서 <strong>채움 자리</strong>를 누르고 값을 쓰면 여기에
          쌓입니다. 승인하기 전까지 문서는 아무것도 바뀌지 않습니다.
        </p>
      </div>
    );
  }

  return (
    <div className="section queue" data-testid="review-queue">
      <h3>
        검토 대기열
        <span className="count" data-testid="queue-count">
          {draft.ops.length}
        </span>
      </h3>

      {draft.rewrittenFromAgent ? (
        <p className="prose note-rewrite">
          에이전트가 낸 계획을 고쳤습니다. 그래서 이 계획은 이제 <strong>이 셸이 낸 것</strong>이고,
          에이전트가 받아 둔 승인은 더 이상 쓰이지 않습니다. 승인은 지금 보이는 계획에만 묶입니다.
        </p>
      ) : null}

      {staleness ? (
        <div className="refusal" data-testid="queue-stale">
          <Tag tone="bad">계획이 낡음</Tag>
          <p className="prose">
            {staleness.kind === "other_session"
              ? "이 대기열은 지금 열려 있는 문서가 아니라 다른 문서의 바이트에 묶여 있습니다. 그대로 승인할 수 없습니다."
              : "계획을 낸 뒤 원본이 바뀌었습니다. 런타임이 승인을 거절합니다."}
          </p>
          <p className="mono tiny">
            묶인 해시 {staleness.boundSha256.slice(0, 16)} · 지금{" "}
            {staleness.currentSha256?.slice(0, 16) ?? "알 수 없음"}
          </p>
          <button
            className="action primary"
            data-testid="queue-repropose"
            onClick={() => void reproposeDraft()}
          >
            지금 문서로 다시 제안
          </button>
        </div>
      ) : null}

      {draft.phase === "failed" && draft.error ? (
        <div className="refusal" data-testid="queue-propose-error">
          <Tag tone="bad">거절됨</Tag>
          <p className="prose">{draft.error.message}</p>
          <p className="mono tiny">{draft.error.code}</p>
        </div>
      ) : null}

      <ul className="queue-ops">
        {draft.ops.map((op) => (
          <OpRow
            key={op.opId}
            op={op}
            hard={findingsFor(op, validation?.hard ?? [])}
            warn={findingsFor(op, validation?.warn ?? [])}
            locked={locked}
          />
        ))}
      </ul>

      {validation ? (
        <div className="queue-verdict" data-testid="queue-verdict">
          <div className="queue-verdict-head">
            {validation.ok ? (
              <Tag tone="ok">쓰기 전 확인 통과</Tag>
            ) : (
              <Tag tone="bad">막힘 {validation.counts.hard}</Tag>
            )}
            {validation.counts.warn > 0 ? (
              <Tag tone="warn">주의 {validation.counts.warn}</Tag>
            ) : null}
            <span className="count mono" title="이 계획의 지문">
              {draft.plan?.planHash.slice(0, 12)}
            </span>
          </div>
          {/* Findings that name the plan rather than an op — plan_stale is the
              one that matters, and it must not disappear into a row. */}
          {[...validation.hard, ...validation.warn]
            .filter((row) => row.at === "plan")
            .map((row) => (
              <p className="queue-finding hard" key={row.code}>
                <Tag tone="bad">막힘</Tag>
                <span>{row.msg}</span>
              </p>
            ))}
          <details className="disclosure">
            <summary>이 확인이 닿지 못하는 것</summary>
            <p className="prose">{validation.preflight.note}</p>
            <ul className="deferred">
              {validation.preflight.deferred.map((code) => (
                <li key={code} className="mono">
                  {code}
                </li>
              ))}
            </ul>
            <p className="prose tiny">근거: {validation.preflight.source}</p>
          </details>
          <details className="disclosure">
            <summary>계획 원본</summary>
            <pre>{JSON.stringify(draft.plan, null, 2)}</pre>
          </details>
        </div>
      ) : draft.phase === "starting" ? (
        <p className="empty">계획을 확인하는 중입니다.</p>
      ) : null}

      {/* ── the approval gate ─────────────────────────────────────────────
          The one place 단청 vermilion is spent. Everything above is teal. */}
      {approval && approval.state === "pending" ? (
        <div className="approval-gate" data-testid="approval-gate">
          <div className="gate-head">
            <span className="gate-dot" aria-hidden="true" />
            <strong>승인을 기다리는 중</strong>
          </div>
          <p className="prose">
            승인하면 이 계획 그대로 문서 사본에 적용되고, 원본은 손대지 않습니다. 승인 기록은{" "}
            <span className="mono">{approval.planHash.slice(0, 12)}</span> 이 계획 하나에만
            묶입니다.
          </p>
          <dl className="kv">
            <dt>요청자</dt>
            <dd>{approval.requestedBy}</dd>
            <dt>요청 시각</dt>
            <dd className="mono">{approval.requestedUtc}</dd>
            <dt>작업 수</dt>
            <dd>{draft.ops.length}</dd>
          </dl>
          <div className="gate-actions">
            <button
              className="action point"
              data-testid="approve"
              disabled={locked}
              onClick={() => void resolveApprovalDecision("approved")}
            >
              {locked ? "적용하는 중…" : "승인하고 적용"}
            </button>
            <button
              className="action"
              data-testid="reject"
              disabled={locked}
              onClick={() => void resolveApprovalDecision("rejected")}
            >
              거절
            </button>
            {applyPhase === "starting" ? (
              <button className="ghost dark-safe" data-testid="cancel-apply" onClick={() => void cancelApply()}>
                멈추기
              </button>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="gate-actions">
          <button
            className="action primary"
            data-testid="request-approval"
            disabled={!approvable}
            title={
              approvable
                ? "사람이 승인해야 문서가 바뀝니다"
                : "확인을 통과한 계획만 승인을 요청할 수 있습니다"
            }
            onClick={() => void requestApprovalForDraft()}
          >
            {approvalPhase === "requesting" ? "요청하는 중…" : "승인 요청"}
          </button>
          <button className="ghost dark-safe" disabled={locked} onClick={() => void clearQueue()}>
            대기열 비우기
          </button>
        </div>
      )}

      {approvalError ? (
        <div className="refusal" data-testid="approval-error">
          <Tag tone="bad">승인 거절됨</Tag>
          <p className="prose">{approvalError.message}</p>
          <p className="mono tiny">{approvalError.code}</p>
          {approvalError.code === "plan_stale" ? (
            <button className="action" onClick={() => void reproposeDraft()}>
              지금 문서로 다시 제안
            </button>
          ) : null}
        </div>
      ) : null}

      {applyError && !recovery ? (
        <div className="refusal" data-testid="apply-error">
          <Tag tone="bad">적용하지 못했습니다</Tag>
          <p className="prose">{applyError.message}</p>
          <p className="mono tiny">{applyError.code}</p>
          {/* preedit's own refusal payload, verbatim. §3.7: the caller must
              never have to open section.xml to interpret a refusal. */}
          {applyError.data ? (
            <details className="disclosure">
              <summary>런타임이 보낸 그대로</summary>
              <pre>{JSON.stringify(applyError.data, null, 2)}</pre>
            </details>
          ) : null}
        </div>
      ) : null}

      {recovery ? (
        <div className="refusal" data-testid="apply-recovery">
          <Tag tone="bad">적용 중에 런타임이 멈췄습니다</Tag>
          <p className="prose">
            {recovery.outcome === "unknown"
              ? "적용이 끝나기 전에 연결이 끊겼습니다. 후보본이 만들어졌는지는 목록을 다시 읽어야 알 수 있습니다 — 짐작하지 않습니다."
              : recovery.outcome === "applied"
                ? "확인했습니다. 후보본은 만들어졌고 영수증도 남아 있습니다."
                : "확인했습니다. 후보본은 만들어지지 않았습니다. 문서는 그대로입니다."}
          </p>
          <p className="mono tiny">
            {recovery.atUtc} · plan {recovery.planId.slice(0, 12)}
            {recovery.runId ? ` · run ${recovery.runId.slice(0, 12)}` : ""}
          </p>
          {recovery.outcome === "unknown" ? (
            <button
              className="action primary"
              data-testid="recovery-check"
              onClick={() => void resolveRecovery()}
            >
              후보본이 생겼는지 확인
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
