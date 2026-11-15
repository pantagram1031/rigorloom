import { useEffect, useMemo, useRef, useState } from "react";

import {
  approveAndApplyFromDialog,
  closeApprovalDialog,
  loadPipelineGates,
  reproposeDraft,
  resolvePipelineGateAction,
  resolveRecovery,
} from "../actions";
import { errorCodeMessage, opKindLabel, t } from "../i18n/vocabulary";
import {
  activeInspect,
  activeText,
  draftStaleness,
  useWorkspace,
} from "../store";
import { buildRegionTextMap } from "../workspace/externalPlan";
import {
  buildIndexedChanges,
  runAuthoritativeGuardDiff,
  setReviewGuardSummary,
  useReviewGuardSummary,
} from "../workspace/guardHelper";
import { DetailDisclosure } from "./DetailDisclosure";

export function ApprovalDialog() {
  const open = useWorkspace((s) => s.approvalDialogOpen);
  const language = useWorkspace((s) => s.language);
  const activeSessionId = useWorkspace((s) => s.activeSessionId);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeText);
  const draft = useWorkspace((s) => s.draft);
  const approval = useWorkspace((s) => s.approval);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const approvalError = useWorkspace((s) => s.approvalError);
  const applyPhase = useWorkspace((s) => s.applyPhase);
  const applyError = useWorkspace((s) => s.applyError);
  const recovery = useWorkspace((s) => s.recovery);
  const applyOutcomes = useWorkspace((s) => s.applyOutcomes);
  const staleness = useWorkspace(draftStaleness);
  const reapprovalPrompt = useWorkspace((s) => s.reapprovalPrompt);

  const pipelineWorkspace = useWorkspace((s) => s.pipelineWorkspace);
  const pipelineGatesResult = useWorkspace((s) => s.pipelineGatesResult);
  const pipelineGatesPhase = useWorkspace((s) => s.pipelineGatesPhase);
  const pipelineGatesError = useWorkspace((s) => s.pipelineGatesError);

  const guardSummary = useReviewGuardSummary();

  const [ackChecked, setAckChecked] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [wsInput, setWsInput] = useState(pipelineWorkspace);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);
  const changes = useMemo(
    () => buildIndexedChanges(draft, inspect, textMap, language),
    [draft, inspect, textMap, language],
  );

  const plan = draft.plan;
  const validation = draft.validation;
  const sessionId = activeSessionId ?? draft.sessionId ?? "";

  useEffect(() => {
    setWsInput(pipelineWorkspace);
  }, [pipelineWorkspace]);

  // Move focus into the modal on open without activating confirm prematurely.
  useEffect(() => {
    if (!open) {
      setSubmitting(false);
      setAckChecked(false);
      return;
    }
    setAckChecked(false);
    setSubmitting(false);
    const id = window.setTimeout(() => dialogRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [open, plan?.planId, plan?.planHash]);

  // If ApprovalDialog opened via command palette before ReviewView audited this plan,
  // run the authoritative Python guard diff so changed-fact gating is always active.
  useEffect(() => {
    if (!open || !sessionId || !plan || validation?.ok !== true) return;
    if (
      guardSummary.planId === plan.planId &&
      (guardSummary.state === "ready" || guardSummary.state === "unavailable")
    ) {
      return;
    }
    let cancelled = false;
    void runAuthoritativeGuardDiff(sessionId, draft, changes).then((res) => {
      if (!cancelled) {
        setReviewGuardSummary(res);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [open, sessionId, plan, validation?.ok, draft, changes, guardSummary.planId, guardSummary.state]);

  const kindCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const ch of changes) {
      const key = ch.opKindText;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()];
  }, [changes]);

  if (!open) return null;

  const sessionOutcome = sessionId ? applyOutcomes?.[sessionId] : undefined;
  const activeRecovery =
    sessionOutcome?.recovery ??
    (recovery && (!sessionId || draft.sessionId === sessionId) ? recovery : null);
  const activeApplyError =
    sessionOutcome?.error ??
    (recovery && sessionId && draft.sessionId !== sessionId ? null : applyError);

  const isStale = Boolean(
    reapprovalPrompt ||
      staleness !== null ||
      validation?.stale ||
      (plan && draft.boundSha256 && plan.boundSha256 !== draft.boundSha256),
  );

  const guardMatchesPlan = Boolean(plan && guardSummary.planId === plan.planId);
  const guardChecking = Boolean(
    plan &&
      validation?.ok === true &&
      (!guardMatchesPlan || guardSummary.state === "running"),
  );
  const guardUnavailable =
    guardMatchesPlan && guardSummary.state === "unavailable";

  const changedFactItems = guardMatchesPlan
    ? changes.filter((ch) => guardSummary.changedFactOpIds.includes(ch.opId))
    : [];
  const changedFactCount =
    changedFactItems.length > 0
      ? changedFactItems.length
      : guardMatchesPlan &&
          guardSummary.state === "ready" &&
          guardSummary.documentDiff &&
          !guardSummary.documentDiff.pass
        ? Math.max(1, guardSummary.documentDiff.changed.filter((r) => !r.pass).length)
        : 0;

  const requiresChangedFactAck = changedFactCount > 0;

  const busy =
    submitting ||
    draft.phase === "starting" ||
    approvalPhase === "requesting" ||
    approvalPhase === "resolving" ||
    applyPhase === "starting";

  // Ruling B, C, F: valid plan required, not stale, guard resolved (ready or unavailable),
  // and changed-fact acknowledgement checked whenever changedFactCount > 0.
  const canConfirm =
    Boolean(plan) &&
    validation?.ok === true &&
    changes.length > 0 &&
    !isStale &&
    !busy &&
    !guardChecking &&
    approval?.state !== "rejected" &&
    (!requiresChangedFactAck || ackChecked);

  const handleConfirm = async () => {
    if (!canConfirm) return;
    setSubmitting(true);
    try {
      await approveAndApplyFromDialog("host-operator");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="dialog-backdrop approval-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) {
          closeApprovalDialog();
        }
      }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="dialog dialog--approval approval-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-dialog-title"
        data-testid="approval-dialog"
      >
        <div className="dialog-head approval-dialog-head">
          <h2 id="approval-dialog-title">
            {t("review_approve_dialog_title", language, [changes.length])}
          </h2>
          <button
            type="button"
            className="review-btn review-btn--ghost"
            data-testid="approval-close-btn"
            disabled={busy}
            onClick={() => closeApprovalDialog()}
          >
            {t("review_cancel", language)}
          </button>
        </div>

        <div className="dialog-body approval-dialog-body">
          {isStale ? (
            <div
              className="approval-banner approval-banner--warn"
              data-testid="approval-stale-banner"
            >
              <p className="approval-banner-text">
                {errorCodeMessage("plan_stale", language)}
              </p>
              <button
                type="button"
                className="review-btn review-btn--secondary"
                data-testid="approval-repropose-btn"
                disabled={draft.ops.length === 0 || busy}
                onClick={() => void reproposeDraft()}
              >
                {t("review_repropose", language)}
              </button>
            </div>
          ) : null}

          {activeRecovery ? (
            <div
              className="approval-banner approval-banner--warn"
              data-testid="approval-recovery-banner"
            >
              <p className="approval-banner-text">
                {activeRecovery.outcome === "unknown"
                  ? errorCodeMessage("apply_outcome_unknown", language)
                  : activeRecovery.outcome === "applied"
                    ? t("review_applied_ok", language)
                    : t("review_empty_changes", language)}
              </p>
              {activeRecovery.outcome === "unknown" ? (
                <button
                  type="button"
                  className="review-btn review-btn--primary"
                  data-testid="approval-recovery-check-btn"
                  onClick={() => void resolveRecovery()}
                >
                  {t("review_check_status", language)}
                </button>
              ) : null}
            </div>
          ) : null}

          {approvalError || activeApplyError ? (
            <div
              className="approval-banner approval-banner--danger"
              data-testid="approval-error-banner"
            >
              <p className="approval-banner-text">
                {errorCodeMessage(
                  (approvalError ?? activeApplyError)!.code,
                  language,
                )}
              </p>
            </div>
          ) : null}

          <section className="approval-summary-box" data-testid="approval-breakdown">
            <ul className="approval-kind-list">
              {kindCounts.map(([label, count]) => (
                <li key={label} className="approval-kind-item">
                  <span>{label}</span>
                  <strong>
                    {language === "en" ? `${count}` : `${count}건`}
                  </strong>
                </li>
              ))}
            </ul>

            {guardChecking ? (
              <p className="approval-guard-note">
                {t("review_guard_checking", language)}
              </p>
            ) : guardUnavailable ? (
              <p
                className="approval-guard-note approval-guard-note--warn"
                data-testid="approval-guard-skipped"
              >
                {t("approve_dialog_guard_skipped", language)}
              </p>
            ) : changedFactCount > 0 ? (
              <div
                className="approval-changed-facts-box"
                data-testid="approval-changed-facts"
              >
                <p className="approval-changed-facts-title">
                  {t("review_changed_facts_header", language, [changedFactCount])}
                </p>
                {changedFactItems.length > 0 ? (
                  <ul className="approval-changed-facts-list">
                    {changedFactItems.map((item) => (
                      <li key={item.opId}>
                        <span>{`[${item.ordinal}] ${item.fieldLabel}`}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}

            <p className="approval-effect-note" data-testid="approval-effect-note">
              {t("approve_dialog_effect", language, [changes.length])}
            </p>
          </section>

          <section className="approval-hashes" aria-label={t("review_plan_hash_label", language)}>
            <div className="approval-hash-row">
              <span className="approval-hash-label">
                {t("review_plan_hash_label", language)}
              </span>
              <code
                className="approval-hash"
                data-testid="approval-plan-hash"
              >
                {plan?.planHash ?? "—"}
              </code>
            </div>
            <div className="approval-hash-row">
              <span className="approval-hash-label">
                {t("review_doc_hash_label", language)}
              </span>
              <code
                className="approval-hash"
                data-testid="approval-bound-hash"
              >
                {plan?.boundSha256 ?? draft.boundSha256 ?? "—"}
              </code>
            </div>
          </section>

          {requiresChangedFactAck ? (
            <label className="approval-ack-row">
              <input
                type="checkbox"
                data-testid="approval-changed-facts-ack"
                checked={ackChecked}
                disabled={busy}
                onChange={(e) => setAckChecked(e.target.checked)}
              />
              <span>{t("review_confirm_changed_fact", language)}</span>
            </label>
          ) : null}

          <DetailDisclosure testId="approval-details">
            <div className="approval-tech-details">
              <div>{`planId: ${plan?.planId ?? "none"}`}</div>
              <div>
                {`approval: ${
                  approval ? `${approval.approvalId} (${approval.state})` : "none"
                }`}
              </div>
              <div>{`guardState: ${guardSummary.state}${guardSummary.errorCode ? ` (${guardSummary.errorCode})` : ""}`}</div>
              {approvalError ? (
                <div>{`approvalError: ${approvalError.code} — ${approvalError.message}`}</div>
              ) : null}
              {activeApplyError ? (
                <div>{`applyError: ${activeApplyError.code} — ${activeApplyError.message}`}</div>
              ) : null}
              {changes.map((ch) => (
                <div key={ch.opId}>
                  {`[${ch.ordinal}] ${ch.opId} (${opKindLabel(ch.op.kind, language)})`}
                </div>
              ))}

              <div className="approval-gates-subpanel" data-testid="pipeline-gates-section">
                <div className="approval-gates-row">
                  <input
                    type="text"
                    value={wsInput}
                    onChange={(e) => setWsInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (!e.nativeEvent.isComposing && e.keyCode !== 229) {
                        e.stopPropagation();
                      }
                    }}
                    placeholder="/abs/path/to/workspace"
                    data-testid="pipeline-workspace-input"
                  />
                  <button
                    type="button"
                    className="review-btn review-btn--secondary"
                    data-testid="pipeline-load-gates"
                    disabled={pipelineGatesPhase === "starting"}
                    onClick={() => void loadPipelineGates(wsInput)}
                  >
                    {pipelineGatesPhase === "starting"
                      ? t("pipeline_checking_gates", language)
                      : t("pipeline_load_gates", language)}
                  </button>
                </div>
                {pipelineGatesError ? (
                  <div>{`${pipelineGatesError.code}: ${pipelineGatesError.message}`}</div>
                ) : null}
                {pipelineGatesResult ? (
                  <div>
                    <div>{`nextStage: ${pipelineGatesResult.nextStage} · mode: ${pipelineGatesResult.mode}`}</div>
                    {pipelineGatesResult.gates.map((g) => (
                      <div key={`${g.stage}-${g.gate}`} className="approval-gate-item">
                        <span>{`${g.gate} · ${g.stage} (${g.state})`}</span>
                        {g.resolvable && g.state !== "approved" ? (
                          <span className="approval-gate-btns">
                            <button
                              type="button"
                              className="review-btn review-btn--secondary"
                              onClick={() =>
                                void resolvePipelineGateAction(
                                  pipelineGatesResult.workspace,
                                  g.gate,
                                  "approved",
                                )
                              }
                            >
                              {t("review_approve", language)}
                            </button>
                            <button
                              type="button"
                              className="review-btn review-btn--secondary"
                              onClick={() =>
                                void resolvePipelineGateAction(
                                  pipelineGatesResult.workspace,
                                  g.gate,
                                  "rejected",
                                )
                              }
                            >
                              {t("review_return", language)}
                            </button>
                          </span>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </DetailDisclosure>
        </div>

        <div className="dialog-foot approval-dialog-foot">
          <button
            type="button"
            className="review-btn review-btn--secondary"
            data-testid="approval-cancel-btn"
            disabled={busy}
            onClick={() => closeApprovalDialog()}
          >
            {t("review_cancel", language)}
          </button>
          <button
            type="button"
            className="review-btn review-btn--primary"
            data-testid="approval-confirm-btn"
            disabled={!canConfirm}
            onClick={() => void handleConfirm()}
          >
            {busy
              ? t("review_applying", language)
              : t("review_approve", language)}
          </button>
        </div>
      </div>
    </div>
  );
}
