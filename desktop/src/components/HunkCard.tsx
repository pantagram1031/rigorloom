/**
 * One queued op as a review hunk: kind + address + state, before/after
 * with LCS marks, per-hunk 승인/거부, provenance folded into 출처.
 *
 * Render is display-only. Op params are never written here.
 */
import { useEffect, useRef, useState } from "react";

import { declareSuggestedCharPr, editOpValue, undoQueuedOp } from "../actions";
import {
  hunkAddress,
  hunkBeforeText,
  hunkDiffMarks,
  hunkKindLabel,
  hunkSlug,
  isReplaceOp,
  type HunkProvenance,
  type HunkStateId,
  HUNK_STATE_LABEL,
  HUNK_STATE_TONE,
} from "../reviewHunk";
import { setState, type QueuedOp } from "../store";
import type { PlanFinding, RegionText } from "../types";
import { Tag } from "./Tag";
import { Icon } from "./Icon";

function copyPlanHash(hash: string, showToast: (msg: string, ms: number) => void): void {
  const clip = navigator.clipboard;
  if (!clip) {
    showToast("복사하지 못했습니다", 1400);
    return;
  }
  void clip.writeText(hash).then(
    () => showToast("계획 지문을 복사했습니다", 1400),
    () => showToast("복사하지 못했습니다", 1400),
  );
}

export function HunkCard({
  op,
  hard,
  warn,
  locked,
  locatable,
  provenance,
  focused,
  provenanceOpen,
  onToggleProvenance,
  onLocate,
  onApprove,
  onReject,
  canDecide,
  decideTitle,
  regions,
  stateId,
  showToast,
}: {
  op: QueuedOp;
  hard: PlanFinding[];
  warn: PlanFinding[];
  locked: boolean;
  locatable: boolean;
  provenance: HunkProvenance;
  focused: boolean;
  provenanceOpen: boolean;
  onToggleProvenance: () => void;
  onLocate: () => void;
  onApprove: () => void;
  onReject: () => void;
  canDecide: boolean;
  decideTitle: string;
  regions: RegionText[] | undefined;
  stateId: HunkStateId;
  showToast: (msg: string, ms: number) => void;
}) {
  const anomaly = hard.find((f) => f.code === "fill_charpr_script_anomaly");
  const [text, setText] = useState(op.text);
  const composing = useRef(false);
  useEffect(() => {
    if (!composing.current) setText(op.text);
  }, [op.text]);
  useEffect(() => {
    return () => {
      if (!composing.current) return;
      composing.current = false;
      setState({ isComposing: false });
    };
  }, []);

  const slug = hunkSlug(op);
  const before = hunkBeforeText(op, regions);
  const replace = isReplaceOp(op, before);
  const marks = hunkDiffMarks(before, op.text, replace);
  const valueLocked =
    locked ||
    op.kind === "replace_all" ||
    op.kind === "goto_text" ||
    op.kind === "insert_text";

  return (
    <li
      className={`queue-op hunk-card${focused ? " is-focused" : ""}`}
      data-testid={`queue-op-${slug}`}
      data-kind={op.kind}
      data-focused={focused ? "true" : "false"}
      tabIndex={focused ? 0 : -1}
    >
      <div className="queue-op-head hunk-head">
        <span className="hunk-kind">{hunkKindLabel(op)}</span>
        <button
          className="addr mono"
          disabled={!locatable}
          title={
            locatable
              ? "문서에서 이 자리를 찾습니다"
              : "이 작업은 다른 문서의 대기열에 있어 현재 문서에서는 찾을 수 없습니다"
          }
          onClick={onLocate}
        >
          {hunkAddress(op)}
        </button>
        <Tag tone={HUNK_STATE_TONE[stateId]} title={HUNK_STATE_LABEL[stateId]}>
          <span data-testid={`hunk-state-${slug}`}>{HUNK_STATE_LABEL[stateId]}</span>
        </Tag>
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
          data-testid={`queue-remove-${slug}`}
          disabled={locked}
          title="이 작업을 대기열에서 뺍니다. 문서는 아직 아무것도 바뀌지 않았습니다."
          onClick={() => void undoQueuedOp(op.opId)}
        >
          대기열에서 제거
        </button>
      </div>

      <div className="hunk-diff">
        <div className="hunk-pane hunk-before" data-testid={`queue-before-${op.opId}`}>
          {before == null ? (
            <span className="hunk-missing">원문 없음</span>
          ) : (
            marks
              .filter((mark) => mark.type !== "insert")
              .map((mark, i) =>
                mark.type === "delete" ? (
                  <del className="hunk-del" data-testid="hunk-del" key={`d-${i}`}>
                    {mark.text}
                  </del>
                ) : (
                  <span key={`be-${i}`}>{mark.text}</span>
                ),
              )
          )}
        </div>
        <div className="hunk-pane hunk-after" data-testid={`queue-after-${op.opId}`}>
          {marks
            .filter((mark) => mark.type !== "delete")
            .map((mark, i) =>
              mark.type === "insert" ? (
                <ins className="hunk-ins" data-testid="hunk-ins" key={`i-${i}`}>
                  {mark.text}
                </ins>
              ) : (
                <span key={`ae-${i}`}>{mark.text}</span>
              ),
            )}
          <input
            className="queue-value"
            data-testid={`queue-value-${op.opId}`}
            value={text}
            disabled={valueLocked}
            aria-label="넣을 값"
            onCompositionStart={() => {
              composing.current = true;
              setState({ isComposing: true });
            }}
            onCompositionEnd={(e) => {
              composing.current = false;
              const next = (e.target as HTMLInputElement).value;
              setText(next);
              setState({ isComposing: false });
              void editOpValue(op.opId, next);
            }}
            onChange={(e) => {
              const next = e.target.value;
              setText(next);
              const native = e.nativeEvent as { isComposing?: boolean };
              if (composing.current || native.isComposing) return;
              void editOpValue(op.opId, next);
            }}
          />
        </div>
      </div>

      <div className="hunk-foot">
        <button
          type="button"
          className="action point btn-icon"
          data-testid={`hunk-approve-${slug}`}
          disabled={!canDecide}
          title={decideTitle}
          aria-label="이 항목 승인"
          onClick={onApprove}
        >
          <Icon name="check" />
          승인
        </button>
        <button
          type="button"
          className="action btn-icon"
          data-testid={`hunk-reject-${slug}`}
          disabled={!canDecide}
          title={decideTitle}
          aria-label="이 항목 거부"
          onClick={onReject}
        >
          <Icon name="x" />
          거부
        </button>
        <details
          className="disclosure hunk-provenance"
          data-testid={`queue-provenance-${slug}`}
          open={provenanceOpen}
          onToggle={(e) => {
            const next = (e.target as HTMLDetailsElement).open;
            if (next !== provenanceOpen) onToggleProvenance();
          }}
        >
          <summary>출처</summary>
          <dl className="kv">
            <dt>세션</dt>
            <dd data-testid={`queue-prov-session-${slug}`}>{provenance.sessionId ?? "—"}</dd>
            <dt>계획</dt>
            <dd data-testid={`queue-prov-plan-${slug}`}>{provenance.planId ?? "—"}</dd>
            <dt>지문</dt>
            <dd data-testid={`queue-prov-hash-${slug}`}>
              {provenance.planHash ?? "—"}
              {provenance.planHash ? (
                <button
                  type="button"
                  className="linkish"
                  data-testid={`queue-prov-copy-hash-${slug}`}
                  title="계획 지문 전체 복사"
                  onClick={() => copyPlanHash(provenance.planHash as string, showToast)}
                >
                  복사
                </button>
              ) : null}
            </dd>
            <dt>제안자</dt>
            <dd data-testid={`queue-prov-proposer-${slug}`}>{provenance.proposer}</dd>
            <dt>백엔드</dt>
            <dd data-testid={`queue-prov-backend-${slug}`}>{provenance.backend ?? "—"}</dd>
            <dt>기준 후보</dt>
            <dd data-testid={`queue-prov-base-${slug}`}>{provenance.baseRunId ?? "원본"}</dd>
            <dt>영수증</dt>
            <dd data-testid={`queue-prov-receipt-${slug}`}>
              {provenance.receiptExists ? "있음" : "없음"}
            </dd>
          </dl>
        </details>
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
