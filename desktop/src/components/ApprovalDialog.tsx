import { useEffect, useMemo, useRef, useState } from "react";

import {
  approveAndApplyFromDialog,
  closeApprovalDialog,
  rememberApprovedGuard,
  reproposeDraft,
  resolveRecovery,
  revisionNumberFor,
} from "../actions";
import { errorCodeMessage, opKindLabel, t } from "../i18n/vocabulary";
import {
  activeDisplayText,
  activeInspect,
  draftStaleness,
  returnedDraftOps,
  showToast,
  useWorkspace,
} from "../store";
import {
  applyStep,
  applyStepLabel,
  baseLabel,
  behindHeadFinding,
  captureConfirmation,
  draftProposerKind,
  guardWarningFullLines,
  guardWarningLines,
  guardWarningSummary,
  proposerLabel,
  requiredGuardAcks,
  shortHash,
} from "../workspace/trust";
import { buildRegionTextMap } from "../workspace/externalPlan";
import { clearSheetConfirmation, prepareSheetConfirmation } from "../workspace/sheetConfirmation";
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
  const texts = useWorkspace(activeDisplayText);
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
  const returnedOps = useWorkspace(returnedDraftOps);
  const candidatesBySession = useWorkspace((s) => s.candidates);
  const appliedNow = useWorkspace((s) => s.applied);

  const guardSummary = useReviewGuardSummary();

  const [ackChecked, setAckChecked] = useState(false);
  const [mockAckChecked, setMockAckChecked] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);
  const changes = useMemo(
    () => buildIndexedChanges(draft, inspect, textMap, language),
    [draft, inspect, textMap, language],
  );

  const plan = draft.plan;
  const validation = draft.validation;
  const sessionId = activeSessionId ?? draft.sessionId ?? "";
  const latestDraftRef = useRef(draft);
  const latestChangesRef = useRef(changes);
  latestDraftRef.current = draft;
  latestChangesRef.current = changes;

  // Move focus into the modal on open without activating confirm prematurely.
  useEffect(() => {
    if (!open) {
      setSubmitting(false);
      setAckChecked(false);
      setMockAckChecked(false);
      return;
    }
    setAckChecked(false);
    setMockAckChecked(false);
    setSubmitting(false);
    const id = window.setTimeout(() => dialogRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [open, plan?.planId, plan?.planHash]);

  // The sheet as rendered asks the browser bridge for its single-use
  // confirmation token; the confirm spends it on the decision.
  // Only this dialog's own close clears it: the v2 sheet shares the holder
  // while this (closed) dialog stays mounted.
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (!open) {
      if (wasOpenRef.current) clearSheetConfirmation();
      wasOpenRef.current = false;
      return;
    }
    wasOpenRef.current = true;
    const binding = captureConfirmation({ activeSessionId: activeSessionId ?? null, draft }, []);
    if (binding) prepareSheetConfirmation(binding);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, activeSessionId, plan?.planId, plan?.planHash, plan?.boundSha256]);

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
    void runAuthoritativeGuardDiff(
      sessionId,
      latestDraftRef.current,
      latestChangesRef.current,
    ).then((res) => {
      if (!cancelled) {
        setReviewGuardSummary(res);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [
    open,
    sessionId,
    plan?.planId,
    plan?.planHash,
    validation?.ok,
    guardSummary.planId,
    guardSummary.state,
  ]);

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
  const changedFactCount = changedFactItems.length;

  // From the WHOLE guard result: changed facts on rows, plus failing
  // paragraphs no row could be tied to. Either one needs the acknowledgement.
  const guardAcks = guardMatchesPlan
    ? requiredGuardAcks(guardSummary)
    : { changedFacts: 0, unattributed: 0, total: 0 };
  const requiresChangedFactAck = guardAcks.total > 0;
  const unattributedParas = guardMatchesPlan ? guardSummary.unattributedFailing ?? [] : [];

  // Every failing guard paragraph, with the values that moved: one or two
  // lines to scan, and the complete list one click away.
  const warningSummary = guardMatchesPlan
    ? guardWarningSummary(changes, guardSummary.rowAudits, language, {
        paragraphsByOp: guardSummary.paragraphsByOp,
        unattributedFailing: guardSummary.unattributedFailing,
      })
    : null;
  const warningLines = warningSummary ? guardWarningLines(warningSummary, language) : [];
  const warningFullLines = warningSummary ? guardWarningFullLines(warningSummary, language) : [];

  const proposerKind = draftProposerKind(draft);
  const requiresMockAck = proposerKind === "mock";
  const revisionOf = (runId: string) =>
    revisionNumberFor(
      { candidates: candidatesBySession, applied: appliedNow } as Parameters<typeof revisionNumberFor>[0],
      sessionId,
      runId,
    );
  const metaLine = t("approval_meta_line", language, [
    proposerLabel(proposerKind, language),
    baseLabel(plan?.base?.runId ?? draft.baseRunId, revisionOf, language),
  ]);
  const behindHead = behindHeadFinding(validation);

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
    returnedOps.length === 0 &&
    behindHead === null &&
    (!requiresChangedFactAck || ackChecked) &&
    (!requiresMockAck || mockAckChecked);

  const stepLabel = applyStepLabel(
    applyStep({ submitting, approvalPhase, applyPhase }),
    language,
  );

  const handleConfirm = async () => {
    if (!canConfirm) return;
    // The binding is taken from the sheet AS RENDERED — this plan, this
    // document, these boxes — not from whatever the store holds after the
    // waits that follow.
    const acknowledgements = [
      ...(requiresChangedFactAck && ackChecked ? ["changed_facts"] : []),
      ...(requiresMockAck && mockAckChecked ? ["mock"] : []),
    ];
    const confirmed = captureConfirmation(
      { activeSessionId: activeSessionId ?? null, draft },
      acknowledgements,
    );
    if (!confirmed) return;
    setSubmitting(true);
    if (plan && warningSummary) {
      // Kept past the queue, so the applied state still names what was flagged.
      rememberApprovedGuard(plan.planId, warningSummary);
    }
    try {
      const done = await approveAndApplyFromDialog(confirmed, "host-operator");
      if (!done) {
        // A broken binding asks for a fresh confirmation: the boxes clear.
        setAckChecked(false);
        setMockAckChecked(false);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const copyHash = (value: string | null | undefined) => {
    if (!value) return;
    void navigator.clipboard
      ?.writeText(value)
      .then(() => showToast(t("toast_hash_copied", language), 1600))
      .catch(() => undefined);
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

          <p className="approval-meta-line" data-testid="approval-meta-line">
            {metaLine}
          </p>

          {behindHead ? (
            <div
              className="approval-banner approval-banner--warn"
              data-testid="approval-behind-head-banner"
            >
              <p className="approval-banner-text">
                {errorCodeMessage("plan_behind_head", language)}
              </p>
            </div>
          ) : null}

          <section className="approval-summary-box" data-testid="approval-breakdown">
            <ul className="approval-kind-list">
              {kindCounts.map(([label, count]) => (
                <li key={label} className="approval-kind-item">
                  <span>{label}</span>
                  <strong>
                    {t("approval_kind_count", language, [count])}
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
            ) : requiresChangedFactAck ? (
              <div
                className="approval-changed-facts-box"
                data-testid="approval-changed-facts"
              >
                {changedFactCount > 0 ? (
                  <p className="approval-changed-facts-title">
                    {t("review_changed_facts_header", language, [changedFactCount])}
                  </p>
                ) : null}
                {changedFactItems.length > 0 ? (
                  <ul className="approval-changed-facts-list">
                    {changedFactItems.map((item) => (
                      <li key={item.opId}>
                        <span>{`[${item.ordinal}] ${item.fieldLabel}`}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {unattributedParas.length > 0 ? (
                  <>
                    <p className="approval-changed-facts-title">
                      {t("approval_warn_unattributed", language, [unattributedParas.length])}
                    </p>
                    <ul
                      className="approval-changed-facts-list"
                      data-testid="approval-unattributed"
                    >
                      {unattributedParas.map((para) => (
                        <li key={para.paragraph}>
                          <span>{t("addr_paragraph", language, [para.paragraph])}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </div>
            ) : null}

            {warningLines.length > 0 ? (
              <ul className="approval-warn-lines" data-testid="approval-guard-warnings">
                {warningLines.map((line, idx) => (
                  <li key={idx}>{line}</li>
                ))}
              </ul>
            ) : null}

            {warningFullLines.length > 0 ? (
              <details className="approval-warn-all" data-testid="approval-guard-warnings-all">
                <summary>{t("approval_warn_show_all", language, [warningFullLines.length])}</summary>
                <ul className="approval-warn-lines">
                  {warningFullLines.map((line, idx) => (
                    <li key={idx}>{line}</li>
                  ))}
                </ul>
              </details>
            ) : null}

            <p className="approval-effect-note" data-testid="approval-effect-note">
              {t("approve_dialog_effect", language, [changes.length])}
            </p>
          </section>

          {requiresMockAck ? (
            <label className="approval-ack-row">
              <input
                type="checkbox"
                data-testid="approval-mock-ack"
                checked={mockAckChecked}
                disabled={busy}
                onChange={(e) => setMockAckChecked(e.target.checked)}
              />
              <span>{t("approval_mock_ack", language)}</span>
            </label>
          ) : null}

          {stepLabel ? (
            <p className="approval-progress" data-testid="approval-progress" role="status">
              {stepLabel}
            </p>
          ) : null}

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
            <section className="approval-hashes" aria-label={t("review_plan_hash_label", language)}>
              <div className="approval-hash-row">
                <span className="approval-hash-label">
                  {t("review_plan_hash_label", language)}
                </span>
                <code
                  className="approval-hash"
                  data-testid="approval-plan-hash"
                  data-full-hash={plan?.planHash ?? ""}
                  title={plan?.planHash ?? undefined}
                >
                  {shortHash(plan?.planHash)}
                </code>
                <button
                  type="button"
                  className="review-btn review-btn--ghost approval-hash-copy"
                  data-testid="approval-copy-plan-hash"
                  disabled={!plan?.planHash}
                  onClick={() => copyHash(plan?.planHash)}
                >
                  {t("approval_copy_hash", language)}
                </button>
              </div>
              <div className="approval-hash-row">
                <span className="approval-hash-label">
                  {t("review_doc_hash_label", language)}
                </span>
                <code
                  className="approval-hash"
                  data-testid="approval-bound-hash"
                  data-full-hash={plan?.boundSha256 ?? draft.boundSha256 ?? ""}
                  title={plan?.boundSha256 ?? draft.boundSha256 ?? undefined}
                >
                  {shortHash(plan?.boundSha256 ?? draft.boundSha256)}
                </code>
                <button
                  type="button"
                  className="review-btn review-btn--ghost approval-hash-copy"
                  data-testid="approval-copy-bound-hash"
                  disabled={!(plan?.boundSha256 ?? draft.boundSha256)}
                  onClick={() => copyHash(plan?.boundSha256 ?? draft.boundSha256)}
                >
                  {t("approval_copy_hash", language)}
                </button>
              </div>
            </section>
            <div className="approval-tech-details">
              <div>{`planId: ${plan?.planId ?? "none"}`}</div>
              <div>{`proposer: ${plan?.proposer ?? "none"}`}</div>
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
