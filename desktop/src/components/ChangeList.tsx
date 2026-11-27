import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import {
  exportApplied,
  navigateScreen,
  openApprovalDialog,
  reproposeDraft,
  resolveRecovery,
  revisionNumberFor,
  setReturnPopoverOpen,
} from "../actions";
import { errorCodeMessage, t } from "../i18n/vocabulary";
import {
  draftStaleness,
  draftValidationPending,
  headCandidate,
  returnedDraftOps,
  useWorkspace,
} from "../store";
import {
  approveBlockedReason,
  behindHeadFinding,
  behindHeadMessage,
  guardWarningCount,
  isSupersededApproval,
} from "../workspace/trust";
import type { UiLanguage } from "../types";
import type {
  IndexedChange,
  ReviewGuardSummary,
  RowGuardAudit,
} from "../workspace/guardHelper";
import { ChangeRow } from "./ChangeRow";
import { DetailDisclosure } from "./DetailDisclosure";

const DEFAULT_ROW_AUDIT: RowGuardAudit = {
  status: "none",
  paragraph: null,
  addedNumbers: [],
};

interface ChangeListProps {
  sessionId: string;
  changes: readonly IndexedChange[];
  guardSummary: ReviewGuardSummary;
  selectedChangeId: string | null;
  expandedChangeId: string | null;
  focusEditNonce: number;
  language: UiLanguage;
  onSelectChange: (opId: string) => void;
  onToggleExpand: (opId: string) => void;
  onJumpNextChangedFact: () => void;
  onConfirmReturn: (reason: string) => Promise<void>;
}

export function ChangeList({
  sessionId,
  changes,
  guardSummary,
  selectedChangeId,
  expandedChangeId,
  focusEditNonce,
  language,
  onSelectChange,
  onToggleExpand,
  onJumpNextChangedFact,
  onConfirmReturn,
}: ChangeListProps) {
  const draft = useWorkspace((s) => s.draft);
  const session = useWorkspace(
    (s) => s.sessions.find((x) => x.sessionId === sessionId) ?? null,
  );
  const inspect = useWorkspace((s) => s.inspects[sessionId] ?? null);
  const render = useWorkspace((s) => s.render);
  const geometry = useWorkspace((s) => s.geometry);
  const head = useWorkspace(headCandidate);
  const approval = useWorkspace((s) => s.approval);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const applyPhase = useWorkspace((s) => s.applyPhase);
  const applied = useWorkspace((s) => s.applied);
  const applyError = useWorkspace((s) => s.applyError);
  const recovery = useWorkspace((s) => s.recovery);
  const applyOutcomes = useWorkspace((s) => s.applyOutcomes);
  const staleness = useWorkspace(draftStaleness);
  const reapprovalPrompt = useWorkspace((s) => s.reapprovalPrompt);
  const returnPopoverOpen = useWorkspace((s) => s.returnPopoverOpen);
  const returnedOps = useWorkspace(returnedDraftOps);
  const approvedGuard = useWorkspace((s) => s.approvedGuard);

  const [returnReason, setReturnReason] = useState("");
  const [returning, setReturning] = useState(false);
  const returnInputRef = useRef<HTMLInputElement | null>(null);
  const isComposingRef = useRef(false);
  const listRef = useRef<HTMLUListElement | null>(null);

  const sessionOutcome = applyOutcomes?.[sessionId];
  const activeApplied = sessionOutcome?.applied ?? (applied?.sessionId === sessionId ? applied : null);
  const activeRecovery = sessionOutcome?.recovery ?? (draft.sessionId === sessionId ? recovery : null);
  const activeApplyError = sessionOutcome?.error ?? (draft.sessionId === sessionId ? applyError : null);
  const workspaceState = useWorkspace((s) => s);
  const exportRunId = activeApplied?.runId ?? head?.runId ?? null;
  const exportRevNum = revisionNumberFor(workspaceState, sessionId, exportRunId) ?? 1;

  const isStale = Boolean(
    reapprovalPrompt ||
      staleness !== null ||
      draft.validation?.stale ||
      (draft.plan && draft.boundSha256 && draft.plan.boundSha256 !== draft.boundSha256),
  );

  const validationPending = draftValidationPending(draft);

  const busy =
    (draft.phase === "starting" && !validationPending) ||
    approvalPhase === "requesting" ||
    approvalPhase === "resolving" ||
    applyPhase === "starting" ||
    returning;

  // Ruling B & C: Approve stays enabled when valid (even if guard is unavailable),
  // and stays disabled when !draft.plan or validation failed or stale.
  const canApprove =
    changes.length > 0 &&
    Boolean(draft.plan) &&
    (draft.validation?.ok === true || validationPending) &&
    approval?.state !== "rejected" &&
    returnedOps.length === 0 &&
    !isStale &&
    !busy;

  // An outdated plan: it was made before the head 수정본 and would drop it.
  const behindHead = behindHeadFinding(draft.validation);
  const revisionOf = (runId: string) => revisionNumberFor(workspaceState, sessionId, runId);
  const headRevision = head?.runId ? revisionOf(head.runId) : null;
  const returnedIds = new Set(returnedOps.map((op) => op.opId));
  const hardCount = changes.filter((ch) => ch.hasHardFailure).length;
  const blockedReason =
    changes.length > 0 && !canApprove && !busy && !isStale
      ? approveBlockedReason(
          {
            hardCount: hardCount > 0 ? hardCount : (draft.validation?.hard.length ?? 0) - (behindHead ? 1 : 0),
            returnedCount: returnedOps.length,
            behindHead: behindHead !== null,
          },
          language,
        )
      : null;

  const changedFactCount = guardSummary.changedFactOpIds.length;
  const selectedChange = selectedChangeId
    ? (changes.find((ch) => ch.opId === selectedChangeId) ?? null)
    : null;
  const selectedTargetKey = selectedChange?.targetKey ?? null;
  const selectedGroupCount =
    selectedTargetKey !== null
      ? changes.filter((ch) => ch.targetKey === selectedTargetKey).length
      : 0;

  useEffect(() => {
    if (!selectedChangeId || !listRef.current) return;
    const item = listRef.current.querySelector<HTMLElement>(
      `[data-op-id="${CSS.escape(selectedChangeId)}"]`,
    );
    item?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedChangeId]);

  useEffect(() => {
    if (returnPopoverOpen) {
      const id = window.setTimeout(() => returnInputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
    setReturnReason("");
  }, [returnPopoverOpen]);

  const submitReturn = async (e?: FormEvent) => {
    e?.preventDefault();
    if (returning) return;
    setReturning(true);
    try {
      await onConfirmReturn(returnReason.trim());
      setReturnReason("");
    } finally {
      setReturning(false);
    }
  };

  const handleReturnKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229 || isComposingRef.current) {
      return;
    }
    e.stopPropagation();
    if (e.key === "Escape") {
      e.preventDefault();
      setReturnPopoverOpen(false);
    }
  };

  // After an approval — including after a reload — the empty queue stands on
  // the head 수정본, so the pane offers its export rather than an empty state.
  const appliedAndEmpty = changes.length === 0 && (activeApplied !== null || head !== null);
  const appliedPlanId = activeApplied?.planId ?? (head?.planId as string | undefined) ?? null;
  const appliedGuard = appliedPlanId ? (approvedGuard[appliedPlanId] ?? null) : null;
  const appliedGuardCount = appliedGuard ? guardWarningCount(appliedGuard) : 0;
  const appliedChecksOpen =
    activeApplied?.checks?.acceptance === false ||
    (!activeApplied && head?.acceptance === false);

  return (
    <aside
      className="change-list-pane"
      aria-label={t("review_changes_header", language, [changes.length])}
    >
      <header className="change-list-header">
        <div className="change-list-title-row">
          <h2 className="change-list-title" data-testid="review-changes-header">
            {appliedAndEmpty
              ? t("review_applied_ok", language)
              : t("review_changes_header", language, [changes.length])}
          </h2>

          {session ? (
            <DetailDisclosure inline testId="review-source-detail">
              <div className="change-source-detail-meta">
                <div>{`file: ${session.source.name}`}</div>
                <div>{`sessionId: ${session.sessionId}`}</div>
                <div>{`sourceSha256: ${session.source.sha256}`}</div>
                <div>{`bytes: ${session.source.bytes} · format: ${session.source.name.split(".").pop() ?? "hwpx"}`}</div>
                {head ? (
                  <div>{`headCandidate: runId=${head.runId ?? "-"} sha256=${head.sha256 ?? "-"} bytes=${head.bytes ?? "-"}`}</div>
                ) : null}
                {inspect ? (
                  <div>
                    {`inspect: tables=${inspect.graph.tables.length} paragraphs=${inspect.graph.paragraphs.length} regions=${inspect.regions.regions.length} fillTargets=${inspect.summary.fillTargetCount}`}
                  </div>
                ) : null}
                {render ? (
                  <div>
                    {`render: ${
                      render.available
                        ? `grade=${render.grade ?? "-"} dpi=${render.dpi ?? "-"} skipped=${render.elementsSkipped?.length ?? 0}`
                        : `unavailable (${render.unavailable?.reason ?? "unknown"})`
                    }`}
                  </div>
                ) : null}
                {geometry ? (
                  <div>
                    {`geometry: ${
                      geometry.available
                        ? `source=${geometry.geometrySource ?? "-"} grade=${geometry.grade ?? "-"} spans=${geometry.spans?.length ?? 0} seats=${geometry.seats?.length ?? 0}`
                        : `unavailable (${geometry.unavailable?.reason ?? "unknown"})`
                    }`}
                  </div>
                ) : null}
              </div>
            </DetailDisclosure>
          ) : null}

          <div className="change-list-actions">
            {appliedAndEmpty ? (
              <button
                type="button"
                className="review-btn review-btn--primary"
                data-testid="review-export-btn"
                onClick={() => void exportApplied(undefined, exportRunId ?? undefined)}
              >
                {t("action_export_revision", language, [exportRevNum])}
              </button>
            ) : (
              <>
                <div className="return-popover-anchor">
                  <button
                    type="button"
                    className="review-btn review-btn--secondary"
                    data-testid="review-return-btn"
                    disabled={changes.length === 0 || busy}
                    aria-expanded={returnPopoverOpen}
                    onClick={() => setReturnPopoverOpen(!returnPopoverOpen)}
                  >
                    {t("review_return", language)}
                  </button>

                  {returnPopoverOpen ? (
                    <form
                      className="return-popover"
                      data-testid="return-popover"
                      onSubmit={(e) => void submitReturn(e)}
                    >
                      <input
                        ref={returnInputRef}
                        type="text"
                        className="return-reason-input"
                        data-testid="return-reason-input"
                        value={returnReason}
                        disabled={returning}
                        placeholder={t("review_return_reason_placeholder", language)}
                        aria-label={t("review_return_reason_placeholder", language)}
                        onCompositionStart={() => {
                          isComposingRef.current = true;
                        }}
                        onCompositionEnd={(e) => {
                          isComposingRef.current = false;
                          setReturnReason(e.currentTarget.value);
                        }}
                        onChange={(e) => setReturnReason(e.target.value)}
                        onKeyDown={handleReturnKeyDown}
                      />
                      <div className="return-popover-buttons">
                        <button
                          type="submit"
                          className="review-btn review-btn--danger"
                          data-testid="return-confirm-btn"
                          disabled={returning}
                        >
                          {t("review_return", language)}
                        </button>
                        <button
                          type="button"
                          className="review-btn review-btn--secondary"
                          data-testid="return-cancel-btn"
                          disabled={returning}
                          onClick={() => setReturnPopoverOpen(false)}
                        >
                          {t("review_cancel", language)}
                        </button>
                      </div>
                    </form>
                  ) : null}
                </div>

                <button
                  type="button"
                  className="review-btn review-btn--primary"
                  data-testid="review-approve-btn"
                  disabled={!canApprove}
                  title={blockedReason ?? undefined}
                  onClick={() => openApprovalDialog()}
                >
                  {t("review_approve", language)}
                </button>
              </>
            )}
          </div>
        </div>

        {blockedReason ? (
          <p className="review-approve-blocked" data-testid="review-approve-blocked">
            {blockedReason}
          </p>
        ) : null}

        {behindHead && changes.length > 0 ? (
          <div className="change-banner change-banner--warn" data-testid="review-behind-head-banner">
            <p className="change-banner-text">
              {behindHeadMessage(behindHead, revisionOf, language)}
            </p>
            <button
              type="button"
              className="review-btn review-btn--secondary"
              data-testid="review-repropose-head-btn"
              disabled={busy}
              onClick={() => void reproposeDraft()}
            >
              {headRevision !== null
                ? t("review_repropose_on_head", language, [headRevision])
                : t("review_repropose_on_latest", language)}
            </button>
            <button
              type="button"
              className="review-btn review-btn--secondary"
              data-testid="review-behind-head-return-btn"
              disabled={busy}
              onClick={() => setReturnPopoverOpen(true)}
            >
              {t("review_return", language)}
            </button>
          </div>
        ) : null}

        {isSupersededApproval(approval) ? (
          <p className="change-list-notice" data-testid="review-superseded-notice">
            {errorCodeMessage("superseded_by_newer_candidate", language)}
          </p>
        ) : null}

        {isStale && changes.length > 0 ? (
          <div className="change-banner change-banner--warn" data-testid="review-stale-banner">
            <p className="change-banner-text">{errorCodeMessage("plan_stale", language)}</p>
            <button
              type="button"
              className="review-btn review-btn--secondary"
              data-testid="review-repropose-btn"
              disabled={busy}
              onClick={() => void reproposeDraft()}
            >
              {t("review_repropose", language)}
            </button>
          </div>
        ) : null}

        {activeRecovery ? (
          <div className="change-banner change-banner--warn" data-testid="review-recovery-banner">
            <p className="change-banner-text">
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
                data-testid="review-recovery-check-btn"
                onClick={() => void resolveRecovery()}
              >
                {t("review_check_status", language)}
              </button>
            ) : null}
          </div>
        ) : null}

        {activeApplyError && !activeRecovery ? (
          <div className="change-banner change-banner--danger" data-testid="review-apply-error">
            <p className="change-banner-text">
              {errorCodeMessage(activeApplyError.code, language)}
            </p>
            <DetailDisclosure>
              <div>{`${activeApplyError.code}: ${activeApplyError.message}`}</div>
            </DetailDisclosure>
          </div>
        ) : null}

        {changes.length > 0 ? (
          <div className="change-guard-strip">
            {guardSummary.state === "invalid_plan" ? (
              <p
                className="guard-status-notice guard-status-notice--warn"
                data-testid="guard-not-run-notice"
                data-guard-state={guardSummary.state}
                data-guard-plan-id={guardSummary.planId ?? ""}
              >
                {t("guard_not_run_invalid", language)}
              </p>
            ) : guardSummary.state === "unavailable" ? (
              <p
                className="guard-status-notice guard-status-notice--warn"
                data-testid="guard-unavailable-notice"
                data-guard-state={guardSummary.state}
                data-guard-plan-id={guardSummary.planId ?? ""}
              >
                {errorCodeMessage("guard_unavailable", language)}
              </p>
            ) : (
              <p
                className="guard-list-header"
                data-testid="guard-list-header"
                data-guard-state={guardSummary.state}
                data-guard-plan-id={guardSummary.planId ?? ""}
              >
                {t("guard_list_header", language)}
              </p>
            )}

            {changedFactCount > 0 ? (
              <button
                type="button"
                className="changed-facts-jumper"
                data-testid="changed-facts-jumper"
                onClick={onJumpNextChangedFact}
              >
                {t("review_changed_facts_header", language, [changedFactCount])}
              </button>
            ) : null}
          </div>
        ) : null}
      </header>

      <div className="change-list-scroll">
        {changes.length === 0 ? (
          <div
            className="change-empty-state"
            data-testid={appliedAndEmpty ? "review-applied-state" : "review-empty-state"}
          >
            <p className="change-empty-text">
              {appliedAndEmpty
                ? t("review_applied_ok", language)
                : t("review_empty_changes", language)}
            </p>
            {appliedAndEmpty && appliedGuardCount > 0 ? (
              <p className="change-list-notice" data-testid="review-applied-guard">
                {t("review_applied_guard_line", language, [appliedGuardCount])}
              </p>
            ) : null}
            {appliedAndEmpty && appliedChecksOpen ? (
              <p className="change-list-notice" data-testid="review-applied-checks">
                {t("history_checks_open", language)}
              </p>
            ) : null}
            <div className="change-empty-actions">
              {appliedAndEmpty ? (
                <button
                  type="button"
                  className="review-btn review-btn--primary"
                  onClick={() => void exportApplied()}
                >
                  {t("action_export", language)}
                </button>
              ) : null}
              <button
                type="button"
                className="review-btn review-btn--secondary"
                data-testid="review-to-fill-btn"
                onClick={() => navigateScreen("fill")}
              >
                {t("review_return_to_fill", language)}
              </button>
            </div>
          </div>
        ) : (
          <ul className="change-list-rows" ref={listRef} data-testid="change-list-rows">
            {changes.map((change) => (
              <ChangeRow
                key={change.opId}
                change={change}
                audit={guardSummary.rowAudits[change.opId] ?? DEFAULT_ROW_AUDIT}
                isSelected={selectedChangeId === change.opId}
                isGroupHighlighted={
                  selectedGroupCount > 1 &&
                  change.targetKey === selectedTargetKey &&
                  change.opId !== selectedChangeId
                }
                isExpanded={expandedChangeId === change.opId}
                focusEditNonce={focusEditNonce}
                disabled={busy}
                returned={returnedIds.has(change.opId)}
                language={language}
                onSelect={onSelectChange}
                onToggleExpand={onToggleExpand}
              />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
