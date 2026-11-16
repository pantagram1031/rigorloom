import { useEffect, useMemo, useRef, useState } from "react";

import {
  exportApplied,
  loadCandidates,
  loadReceipt,
  navigateScreen,
  proposeUndoOf,
} from "../actions";
import { DetailDisclosure } from "../components/DetailDisclosure";
import { t } from "../i18n/vocabulary";
import * as rt from "../runtime";
import {
  activeCandidates,
  activeSession,
  headCandidate,
  useWorkspace,
} from "../store";
import type {
  Candidate,
  CandidateCompare,
  GuardDiffResult,
  Receipt,
  UiLanguage,
} from "../types";
import { hasLiveUnappliedPlanInEvents } from "../workspace/externalPlan";
import "./history.css";

interface RevisionItem {
  revNum: number;
  runId: string;
  candidate: Candidate;
  receipt: Receipt | null;
}

// Test-only display override read from the root element during screenshot capture;
// production application code never sets this attribute.
const CAPTURE_FIXED_TIME_ATTR = "data-capture-fixed-time";

function readCaptureFixedTime(): string | null {
  if (typeof document === "undefined") return null;
  const val = document.documentElement?.getAttribute(CAPTURE_FIXED_TIME_ATTR);
  return val && val.trim().length > 0 ? val.trim() : null;
}

function formatDisplayTimestamp(
  iso: string | null | undefined,
  language: UiLanguage,
  fixedTime: string | null = null,
): string {
  if (!iso) return t("history_unknown_time", language);
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (fixedTime) return fixedTime;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${y}-${m}-${day} ${hh}:${mm}:${ss}`;
}

function formatApprovalMethod(
  approver: string | null | undefined,
  language: UiLanguage,
): string {
  const raw = (approver ?? "").trim().toLowerCase();
  const directBase = t("history_approval_method_direct", language);
  if (
    !raw ||
    raw === "host-operator" ||
    raw === "rigorloom-desktop" ||
    raw === "operator" ||
    raw === "gongmun-walkthrough"
  ) {
    return directBase;
  }
  return `${directBase} (${approver?.trim()})`;
}

export function HistoryView() {
  const session = useWorkspace(activeSession);
  const candidates = useWorkspace(activeCandidates);
  const receipts = useWorkspace((s) => s.receipts);
  const applied = useWorkspace((s) => s.applied);
  const head = useWorkspace(headCandidate);
  const draft = useWorkspace((s) => s.draft);
  const events = useWorkspace((s) => s.events);
  const undoPhase = useWorkspace((s) => s.undoPhase);
  const undoError = useWorkspace((s) => s.undoError);
  const language = useWorkspace((s) => s.language);

  const sessionId = session?.sessionId ?? null;
  const requestedReceiptsRef = useRef<Set<string>>(new Set());
  const [undoBusyRunId, setUndoBusyRunId] = useState<string | null>(null);
  const [captureFixedTime, setCaptureFixedTime] = useState<string | null>(
    () => readCaptureFixedTime(),
  );

  useEffect(() => {
    if (typeof document === "undefined" || typeof MutationObserver === "undefined") {
      return;
    }
    const rootEl = document.documentElement;
    if (!rootEl) return;
    setCaptureFixedTime(readCaptureFixedTime());
    const observer = new MutationObserver(() => {
      setCaptureFixedTime(readCaptureFixedTime());
    });
    observer.observe(rootEl, {
      attributes: true,
      attributeFilter: [CAPTURE_FIXED_TIME_ATTR],
    });
    return () => observer.disconnect();
  }, []);

  const [baseRunId, setBaseRunId] = useState<string>("__source__");
  const [targetRunId, setTargetRunId] = useState<string>("");
  const [compareBusy, setCompareBusy] = useState(false);
  const [compareResult, setCompareResult] = useState<CandidateCompare | null>(null);
  const [diffResult, setDiffResult] = useState<GuardDiffResult | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);

  // Ensure candidate listing is fresh on view entry.
  useEffect(() => {
    if (!sessionId) return;
    if (
      candidates.length === 0 ||
      (applied?.sessionId === sessionId &&
        applied.runId &&
        !candidates.some((c) => c.runId === applied.runId))
    ) {
      void loadCandidates(sessionId);
    }
  }, [sessionId, applied?.runId, candidates.length]);

  const chronologicalRevisions = useMemo<RevisionItem[]>(() => {
    const valid = candidates
      .filter((c): c is Candidate & { runId: string } => Boolean(c.runId))
      .slice()
      .sort((a, b) => (a.createdUtc ?? "").localeCompare(b.createdUtc ?? ""));
    return valid.map((candidate, idx) => ({
      revNum: idx + 1,
      runId: candidate.runId,
      candidate,
      receipt: receipts[candidate.runId] ?? null,
    }));
  }, [candidates, receipts]);

  const displayRevisions = useMemo(
    () => chronologicalRevisions.slice().reverse(),
    [chronologicalRevisions],
  );

  // Lazy + cached receipt fetching per candidate.
  useEffect(() => {
    if (!sessionId) return;
    for (const rev of chronologicalRevisions) {
      if (receipts[rev.runId]) continue;
      if (requestedReceiptsRef.current.has(rev.runId)) continue;
      requestedReceiptsRef.current.add(rev.runId);
      void loadReceipt(rev.runId);
    }
  }, [sessionId, chronologicalRevisions, receipts]);

  // Seed default comparison pair when revisions arrive.
  useEffect(() => {
    if (chronologicalRevisions.length === 0) {
      setTargetRunId("");
      setBaseRunId("__source__");
      setCompareResult(null);
      setDiffResult(null);
      return;
    }
    const newest = chronologicalRevisions[chronologicalRevisions.length - 1];
    const previous =
      chronologicalRevisions.length >= 2
        ? chronologicalRevisions[chronologicalRevisions.length - 2]
        : null;
    if (!targetRunId || !chronologicalRevisions.some((r) => r.runId === targetRunId)) {
      setTargetRunId(newest.runId);
    }
    if (
      baseRunId !== "__source__" &&
      !chronologicalRevisions.some((r) => r.runId === baseRunId)
    ) {
      setBaseRunId(previous ? previous.runId : "__source__");
    }
  }, [chronologicalRevisions, targetRunId, baseRunId]);

  // Fetch arbitrary two-version comparison (`candidate/compare` + `/api/guard/diff`).
  useEffect(() => {
    if (!sessionId || !targetRunId || targetRunId === baseRunId) {
      setCompareResult(null);
      setDiffResult(null);
      setCompareError(null);
      return;
    }
    let cancelled = false;
    setCompareBusy(true);
    setCompareError(null);

    Promise.all([
      rt
        .compareCandidate(
          sessionId,
          targetRunId,
          baseRunId === "__source__" ? { source: true } : { runId: baseRunId },
        )
        .catch(() => null),
      rt
        .guardDiff({
          sessionId,
          runId: targetRunId,
          againstRunId: baseRunId === "__source__" ? null : baseRunId,
        })
        .catch(() => null),
    ])
      .then(([cmp, diff]) => {
        if (cancelled) return;
        setCompareResult(cmp);
        setDiffResult(diff);
      })
      .catch((err) => {
        if (cancelled) return;
        setCompareError(String(err));
      })
      .finally(() => {
        if (!cancelled) setCompareBusy(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId, baseRunId, targetRunId]);

  const handleProposeUndo = async (runId: string) => {
    setUndoBusyRunId(runId);
    try {
      const count = await proposeUndoOf(runId);
      if (count > 0) {
        navigateScreen("review");
      }
    } finally {
      setUndoBusyRunId(null);
    }
  };

  if (!session) {
    return (
      <main className="history-empty-view" data-testid="history-view">
        <div className="history-placeholder-card">
          <p className="history-note">{t("open_recent_hint", language)}</p>
          <button
            type="button"
            className="history-btn history-btn--primary"
            onClick={() => navigateScreen("open")}
          >
            {t("nav_open", language)}
          </button>
        </div>
      </main>
    );
  }

  const hasPendingProposals =
    draft.ops.length > 0 ||
    draft.plan !== null ||
    hasLiveUnappliedPlanInEvents(events, sessionId);
  const headRunId =
    head?.runId ??
    (chronologicalRevisions.length > 0
      ? chronologicalRevisions[chronologicalRevisions.length - 1].runId
      : null);

  return (
    <main className="history-view" data-testid="history-view">
      <div className="history-container">
        <header className="history-header">
          <div className="history-title-row">
            <h1 className="history-title">{t("history_title", language)}</h1>
            {hasPendingProposals ? (
              <button
                type="button"
                className="history-btn history-btn--link"
                data-testid="history-pending-link"
                onClick={() => navigateScreen("review")}
              >
                {t("history_pending_link", language)}
              </button>
            ) : null}
          </div>
          <p className="history-note" data-testid="history-title-note">
            {t("history_title_note", language)}
          </p>
        </header>

        {undoError ? (
          <div className="history-error-box" role="alert" data-testid="history-undo-error">
            {undoError.message}
          </div>
        ) : null}

        <div
          className={`history-columns${
            chronologicalRevisions.length >= 1 ? " history-columns--split" : ""
          }`}
        >
          <div className="history-timeline-pane">
            {displayRevisions.length === 0 ? (
              <p className="history-note" data-testid="history-empty">
                {t("history_empty", language)}
              </p>
            ) : (
              <ol className="history-timeline" data-testid="history-timeline">
                {displayRevisions.map((item) => {
                  const { revNum, runId, candidate, receipt } = item;
                  const isCurrent = runId === headRunId;
                  const stepKinds =
                    receipt?.steps?.map((s) => s.kind) ?? candidate.opKinds ?? [];
                  const deleteGuideCount = stepKinds.filter(
                    (k) => k === "delete_guides",
                  ).length;
                  const isInvertible = deleteGuideCount === 0;
                  const baseRev =
                    candidate.base?.runId
                      ? chronologicalRevisions.find(
                          (r) => r.runId === candidate.base?.runId,
                        )
                      : revNum > 1
                        ? chronologicalRevisions.find((r) => r.revNum === revNum - 1)
                        : null;

                  const approvedRaw = receipt?.approval?.resolvedUtc ?? null;
                  const appliedRaw = receipt?.createdUtc ?? candidate.createdUtc ?? null;

                  return (
                    <li
                      key={runId}
                      className={`history-node${isCurrent ? " history-node--current" : ""}`}
                      data-testid={`history-node-${revNum}`}
                    >
                      <div className="history-node-head">
                        <div className="history-node-title-group">
                          <h2
                            className="history-node-title"
                            data-testid={`history-revision-title-${revNum}`}
                          >
                            {t("history_revision_label", language, [revNum])}
                          </h2>
                          {isCurrent ? (
                            <span className="history-current-badge">
                              {t("history_revision_current", language)}
                            </span>
                          ) : null}
                        </div>

                        <DetailDisclosure
                          inline
                          testId={`history-detail-${revNum}`}
                          label={t("detail_label", language)}
                        >
                          <dl className="change-detail-dl">
                            <dt>{t("detail_run_id", language)}</dt>
                            <dd>{runId}</dd>
                            {receipt?.planId ?? candidate.planId ? (
                              <>
                                <dt>{t("detail_plan_id", language)}</dt>
                                <dd>{receipt?.planId ?? candidate.planId}</dd>
                              </>
                            ) : null}
                            {receipt?.planHash ? (
                              <>
                                <dt>{t("review_plan_hash_label", language)}</dt>
                                <dd>{receipt.planHash}</dd>
                              </>
                            ) : null}
                            {candidate.sha256 ? (
                              <>
                                <dt>{t("detail_file_hash", language)}</dt>
                                <dd>{candidate.sha256}</dd>
                              </>
                            ) : null}
                            {receipt?.approval?.approver ? (
                              <>
                                <dt>{t("detail_approver_record", language)}</dt>
                                <dd>{receipt.approval.approver}</dd>
                              </>
                            ) : null}
                            {receipt?.base?.runId ? (
                              <>
                                <dt>{t("detail_base_run_id", language)}</dt>
                                <dd>{receipt.base.runId}</dd>
                              </>
                            ) : null}
                            {receipt?.reverses?.runId ? (
                              <>
                                <dt>{t("detail_reversed_run_id", language)}</dt>
                                <dd>{receipt.reverses.runId}</dd>
                              </>
                            ) : null}
                          </dl>
                        </DetailDisclosure>
                      </div>

                      <p className="history-summary-line" data-testid={`history-summary-${revNum}`}>
                        {t("history_changes_count", language, [stepKinds.length])}
                      </p>

                      <dl className="history-meta-dl">
                        <dt>{t("history_approved_at_label", language)}</dt>
                        <dd data-testid={`history-approved-at-${revNum}`}>
                          {receipt
                            ? formatDisplayTimestamp(approvedRaw, language, captureFixedTime)
                            : t("history_receipt_unavailable", language)}
                        </dd>
                        <dt>{t("history_applied_at_label", language)}</dt>
                        <dd data-testid={`history-applied-at-${revNum}`}>
                          {formatDisplayTimestamp(appliedRaw, language, captureFixedTime)}
                        </dd>
                      </dl>

                      <p
                        className="history-approval-method"
                        data-testid={`history-approval-method-${revNum}`}
                      >
                        {formatApprovalMethod(receipt?.approval?.approver, language)}
                      </p>

                      {isInvertible ? (
                        <p
                          className="history-scope-note"
                          data-testid={`history-undo-scope-${revNum}`}
                        >
                          {t("history_undo_scope", language)}
                        </p>
                      ) : (
                        <p
                          className="history-noninvertible-note"
                          data-testid={`history-noninvertible-${revNum}`}
                        >
                          {t("history_undo_noninvertible", language, [deleteGuideCount])}
                        </p>
                      )}

                      <div className="history-node-actions">
                        <button
                          type="button"
                          className="history-btn history-btn--secondary"
                          data-testid={`history-export-${revNum}`}
                          onClick={() => void exportApplied(undefined, runId)}
                        >
                          {t("action_export_revision", language, [revNum])}
                        </button>

                        {isInvertible ? (
                          <button
                            type="button"
                            className="history-btn history-btn--secondary"
                            data-testid={`history-propose-undo-${revNum}`}
                            disabled={undoPhase === "starting" || undoBusyRunId === runId}
                            onClick={() => void handleProposeUndo(runId)}
                          >
                            {undoBusyRunId === runId
                              ? t("history_proposing_undo", language)
                              : t("history_propose_undo", language)}
                          </button>
                        ) : baseRev ? (
                          <button
                            type="button"
                            className="history-btn history-btn--secondary"
                            data-testid={`history-export-prev-${revNum}`}
                            onClick={() => void exportApplied(undefined, baseRev.runId)}
                          >
                            {t("history_export_prev_revision", language, [baseRev.revNum])}
                          </button>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>

          {chronologicalRevisions.length >= 1 ? (
            <section
              className="history-compare-section"
              data-testid="history-compare-section"
              aria-label={t("history_compare_title", language)}
            >
              <h2 className="history-compare-title">{t("history_compare_title", language)}</h2>

              <div className="history-compare-controls">
                <label className="history-select-label">
                  <span>{t("history_compare_base", language)}</span>
                  <select
                    className="history-select"
                    data-testid="history-compare-base"
                    value={baseRunId}
                    onChange={(e) => setBaseRunId(e.target.value)}
                  >
                    <option value="__source__">
                      {t("history_compare_original", language)}
                    </option>
                    {chronologicalRevisions.map((r) => (
                      <option key={r.runId} value={r.runId}>
                        {t("history_revision_label", language, [r.revNum])}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="history-select-label">
                  <span>{t("history_compare_target", language)}</span>
                  <select
                    className="history-select"
                    data-testid="history-compare-target"
                    value={targetRunId}
                    onChange={(e) => setTargetRunId(e.target.value)}
                  >
                    {chronologicalRevisions.map((r) => (
                      <option key={r.runId} value={r.runId}>
                        {t("history_revision_label", language, [r.revNum])}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              {compareBusy ? (
                <p className="history-note">{t("history_compare_loading", language)}</p>
              ) : compareError ? (
                <p className="history-error-box">{compareError}</p>
              ) : baseRunId === targetRunId ? (
                <p className="history-note">{t("history_compare_same", language)}</p>
              ) : diffResult ? (
                <>
                  <p className="history-note" data-testid="history-compare-summary">
                    {diffResult.changed.length > 0
                      ? t("history_compare_changed_count", language, [diffResult.changed.length])
                      : t("history_compare_same", language)}
                    {" · "}
                    {t("history_snapshot_diff_note", language)}
                  </p>
                  {diffResult.changed.length > 0 ? (
                    <ul className="history-diff-list" data-testid="history-compare-list">
                      {diffResult.changed.slice(0, 12).map((row) => (
                        <li key={row.paragraph} className="history-diff-card">
                          {row.before ? (
                            <div className="history-diff-before">{row.before}</div>
                          ) : null}
                          <div className="history-diff-after">{row.after}</div>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {compareResult ? (
                    <DetailDisclosure
                      inline
                      testId="history-compare-detail"
                      label={t("detail_label", language)}
                    >
                      <dl className="change-detail-dl">
                        <dt>{t("detail_regions_equal", language)}</dt>
                        <dd>{String(compareResult.regionsEqual)}</dd>
                        <dt>{t("detail_regions_compared", language)}</dt>
                        <dd>{String(compareResult.regionsCompared)}</dd>
                        <dt>{t("detail_normalizer", language)}</dt>
                        <dd>{compareResult.normalizer}</dd>
                      </dl>
                    </DetailDisclosure>
                  ) : null}
                </>
              ) : null}
            </section>
          ) : null}
        </div>
      </div>
    </main>
  );
}
