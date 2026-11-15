import { useState } from "react";
import {
  approveAndApplyFromDialog,
  clearQueue,
  closeApprovalDialog,
  loadPipelineGates,
  reproposeDraft,
  resolvePipelineGateAction,
  revalidateActiveDraft,
  revalidateAndResolveApproval,
} from "../actions";
import {
  formatProjectedAddress,
  projectedAfterText,
  projectionInverseSupport,
} from "../agent/planProjection";
import { draftStaleness, useWorkspace } from "../store";

const OP_KIND_LABEL: Record<string, string> = {
  fill_cell: "채움 · fill_cell",
  replace_at_cell: "치환 · replace_at_cell",
  set_run: "문단 런 · set_run",
  delete_guides: "안내문 삭제 · delete_guides",
};

export function ApprovalDialog() {
  const open = useWorkspace((s) => s.approvalDialogOpen);
  const draft = useWorkspace((s) => s.draft);
  const approval = useWorkspace((s) => s.approval);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const approvalError = useWorkspace((s) => s.approvalError);
  const applyPhase = useWorkspace((s) => s.applyPhase);
  const staleness = useWorkspace(draftStaleness);
  const reapprovalPrompt = useWorkspace((s) => s.reapprovalPrompt);

  const pipelineWorkspace = useWorkspace((s) => s.pipelineWorkspace);
  const pipelineGatesResult = useWorkspace((s) => s.pipelineGatesResult);
  const pipelineGatesPhase = useWorkspace((s) => s.pipelineGatesPhase);
  const pipelineGatesError = useWorkspace((s) => s.pipelineGatesError);

  const [wsInput, setWsInput] = useState(pipelineWorkspace);
  const [approver, setApprover] = useState("host-operator");

  if (!open) return null;

  const plan = draft.plan;
  const validation = draft.validation;
  const isStale = Boolean(
    reapprovalPrompt ||
      staleness !== null ||
      validation?.stale ||
      (plan && draft.boundSha256 && plan.boundSha256 !== draft.boundSha256),
  );
  const busy =
    approvalPhase === "requesting" ||
    approvalPhase === "resolving" ||
    applyPhase === "starting";
  const canApplyFromDialog =
    Boolean(plan) &&
    validation?.ok === true &&
    !isStale &&
    !busy &&
    approval?.state !== "rejected";

  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) closeApprovalDialog();
      }}
    >
      <div
        className="dialog dialog--approval"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-dialog-title"
        data-testid="approval-dialog"
      >
        <div className="dialog-head">
          <div>
            <h2 id="approval-dialog-title">승인 검토 · Approval review</h2>
            <p className="hint">
              계획 해시와 결합된 문서 해시, 모든 작업 내역을 확인한 뒤 적용합니다.
            </p>
          </div>
          <button
            type="button"
            className="ghost"
            data-testid="dialog-close"
            onClick={() => closeApprovalDialog()}
          >
            닫기 · Close
          </button>
        </div>

        <div className="dialog-body">
          {(reapprovalPrompt || isStale) && (
            <div className="reapproval-banner" data-testid="reapproval-prompt">
              <strong>재승인 필요 · Re-approval required</strong>
              <p>
                {reapprovalPrompt ??
                  "문서 또는 후보본이 변경되어 기존 승인이 무효화되었습니다. 다시 계획을 확인하고 승인해 주세요."}
              </p>
              <button
                type="button"
                onClick={() => void reproposeDraft()}
                disabled={draft.ops.length === 0 || busy}
              >
                계획 다시 제안 · Re-propose
              </button>
            </div>
          )}

          {approvalError && (
            <div className="error-box">
              <strong>{approvalError.code}</strong>
              <span>{approvalError.message}</span>
            </div>
          )}

          <section className="dialog-bindings">
            <div className="binding-row">
              <span className="binding-k">계획 ID · planId</span>
              <span className="binding-v mono" data-testid="dialog-plan-id">
                {plan?.planId ?? "—"}
              </span>
            </div>
            <div className="binding-row">
              <span className="binding-k">계획 해시 · planHash</span>
              <span className="binding-v mono" data-testid="dialog-plan-hash">
                {plan?.planHash ?? "—"}
              </span>
            </div>
            <div className="binding-row">
              <span className="binding-k">결합 해시 · boundSha256</span>
              <span className="binding-v mono" data-testid="dialog-bound-sha">
                {plan?.boundSha256 ?? draft.boundSha256 ?? "—"}
              </span>
            </div>
            <div className="binding-row">
              <span className="binding-k">승인 상태 · State</span>
              <span className="binding-v">
                {approval ? `${approval.state} (${approval.approvalId})` : "미요청 · not requested"}
              </span>
            </div>
          </section>

          <section className="dialog-ops">
            <h3>작업 내역 · Queued operations ({draft.ops.length})</h3>
            <ul className="dialog-op-list">
              {draft.ops.map((op) => {
                const inv = projectionInverseSupport(op);
                return (
                  <li key={op.opId} className="dialog-op-row">
                    <div className="dialog-op-head">
                      <span className="op-kind-tag">{OP_KIND_LABEL[op.kind] ?? op.kind}</span>
                      <span className="mono">{formatProjectedAddress(op)}</span>
                      {!inv.invertible && (
                        <span className="pill-warn">되돌리기 불가</span>
                      )}
                    </div>
                    <div className="diff">
                      <div className="diff-before">
                        <span className="diff-tag">전</span>
                        <span className="diff-text">{op.before || "(비어 있음)"}</span>
                      </div>
                      <div className="diff-after">
                        <span className="diff-tag">후</span>
                        <span className="diff-text">{projectedAfterText(op)}</span>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>

          <section className="dialog-gates" data-testid="pipeline-gates-section">
            <h3>보고서 파이프라인 게이트 · Pipeline gates</h3>
            <div className="gate-lookup-row">
              <input
                type="text"
                value={wsInput}
                onChange={(e) => setWsInput(e.target.value)}
                placeholder="/abs/path/to/report-workspace"
                data-testid="pipeline-workspace-input"
              />
              <button
                type="button"
                className="ghost"
                data-testid="pipeline-load-gates"
                disabled={pipelineGatesPhase === "starting"}
                onClick={() => void loadPipelineGates(wsInput)}
              >
                {pipelineGatesPhase === "starting" ? "조회 중…" : "게이트 조회 · Load"}
              </button>
            </div>
            {pipelineGatesError && (
              <div className="error-box">
                <strong>{pipelineGatesError.code}</strong>
                <span>{pipelineGatesError.message}</span>
              </div>
            )}
            {pipelineGatesResult && (
              <div className="gate-list">
                <div className="hint mono">
                  nextStage: {pipelineGatesResult.nextStage} · mode: {pipelineGatesResult.mode}
                </div>
                {pipelineGatesResult.gates.map((g) => (
                  <div key={`${g.stage}-${g.gate}`} className="gate-row">
                    <div>
                      <strong className="mono">{g.gate}</strong>
                      <span className="hint">
                        {" "}
                        · {g.stage} ({g.state})
                      </span>
                    </div>
                    {g.resolvable && g.state !== "approved" && (
                      <div className="row-actions">
                        <button
                          type="button"
                          onClick={() =>
                            void resolvePipelineGateAction(
                              pipelineGatesResult.workspace,
                              g.gate,
                              "approved",
                            )
                          }
                        >
                          게이트 승인 · Approve
                        </button>
                        <button
                          type="button"
                          className="ghost"
                          onClick={() =>
                            void resolvePipelineGateAction(
                              pipelineGatesResult.workspace,
                              g.gate,
                              "rejected",
                            )
                          }
                        >
                          게이트 거절 · Reject
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          <label className="approver-row">
            <span className="section-label">승인자 · Approver</span>
            <input
              type="text"
              value={approver}
              onChange={(e) => setApprover(e.target.value)}
              data-testid="dialog-approver-input"
            />
          </label>
        </div>

        <div className="dialog-foot">
          <button
            type="button"
            className="ghost"
            data-testid="dialog-revalidate"
            disabled={!plan || busy}
            onClick={() => void revalidateActiveDraft()}
          >
            다시 검증 · Revalidate
          </button>
          <button
            type="button"
            className="ghost"
            data-testid="dialog-discard"
            disabled={busy}
            onClick={() => void clearQueue()}
          >
            되돌리기(비우기) · Discard
          </button>
          {approval?.state === "pending" && (
            <button
              type="button"
              className="ghost"
              data-testid="dialog-reject"
              disabled={busy}
              onClick={() => void revalidateAndResolveApproval("rejected", approver)}
            >
              거절 · Reject
            </button>
          )}
          <button
            type="button"
            className="vermilion"
            data-testid="dialog-approve-apply"
            disabled={!canApplyFromDialog}
            onClick={() => void approveAndApplyFromDialog(approver.trim() || "host-operator")}
          >
            {applyPhase === "starting" ? "적용 중…" : "승인하고 적용 · Approve & apply"}
          </button>
        </div>
      </div>
    </div>
  );
}
