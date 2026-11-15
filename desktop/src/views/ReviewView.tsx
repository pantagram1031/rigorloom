import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import {
  adoptExternalPlan,
  clearQueue,
  navigateScreen,
  openApprovalDialog,
  renderCurrentPage,
  resolveApprovalDecision,
  sendInstruction,
  setExpandedChangeId,
  setMobileReviewPane,
  setReturnPopoverOpen,
  setSelectedChangeId,
} from "../actions";
import { ChangeList } from "../components/ChangeList";
import { PageSheet } from "../components/PageSheet";
import { errorCodeMessage, t } from "../i18n/vocabulary";
import {
  activeInspect,
  activeSession,
  activeText,
  composerBlocker,
  draftStaleness,
  useWorkspace,
} from "../store";
import {
  buildRegionTextMap,
  findAdoptableExternalPlan,
  markExternalPlanDismissed,
} from "../workspace/externalPlan";
import {
  buildIndexedChanges,
  emptyReviewGuardSummary,
  runAuthoritativeGuardDiff,
  setReviewGuardSummary,
  useReviewGuardSummary,
} from "../workspace/guardHelper";
import "./review.css";

interface ReviewKeyDetail {
  code: string;
  key?: string;
  shiftKey?: boolean;
}

function isEditableElement(el: Element | null): boolean {
  if (!el) return false;
  if (
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement ||
    el instanceof HTMLSelectElement
  ) {
    return true;
  }
  return (el as HTMLElement).isContentEditable === true;
}

export function ReviewView() {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeText);
  const textsBySession = useWorkspace((s) => s.texts);
  const draft = useWorkspace((s) => s.draft);
  const events = useWorkspace((s) => s.events);
  const approval = useWorkspace((s) => s.approval);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const applyPhase = useWorkspace((s) => s.applyPhase);
  const language = useWorkspace((s) => s.language);
  const selectedChangeId = useWorkspace((s) => s.selectedChangeId);
  const expandedChangeId = useWorkspace((s) => s.expandedChangeId);
  const mobileReviewPane = useWorkspace((s) => s.mobileReviewPane);
  const agentPhase = useWorkspace((s) => s.agentPhase);
  const printViewEnabled = useWorkspace((s) => s.printViewEnabled);
  const page = useWorkspace((s) => s.page);
  const render = useWorkspace((s) => s.render);
  const staleness = useWorkspace(draftStaleness);
  const reapprovalPrompt = useWorkspace((s) => s.reapprovalPrompt);
  const blocker = useWorkspace(composerBlocker);

  const guardSummary = useReviewGuardSummary();
  const [focusEditNonce, setFocusEditNonce] = useState(0);
  const [promptText, setPromptText] = useState("");
  const promptComposingRef = useRef(false);
  const adoptedAttemptRef = useRef<string | null>(null);

  const sessionId = session?.sessionId ?? null;
  const hasTextsLoaded = Boolean(
    sessionId && inspect && Object.prototype.hasOwnProperty.call(textsBySession, sessionId),
  );

  // Auto-adopt external CLI / MCP plan.proposed events when inspect & texts are ready.
  useEffect(() => {
    if (!sessionId || !hasTextsLoaded) return;
    const candidate = findAdoptableExternalPlan(sessionId, events, draft);
    if (!candidate) return;
    const attemptKey = `${sessionId}:${candidate.planId}`;
    if (adoptedAttemptRef.current === attemptKey) return;
    adoptedAttemptRef.current = attemptKey;
    void adoptExternalPlan(sessionId, candidate.planId, candidate.approvalId);
  }, [sessionId, hasTextsLoaded, events, draft]);

  // Reset attempt fence when switching active documents.
  useEffect(() => {
    adoptedAttemptRef.current = null;
  }, [sessionId]);

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);
  const changes = useMemo(
    () => buildIndexedChanges(draft, inspect, textMap, language),
    [draft, inspect, textMap, language],
  );

  // Keep selected & expanded IDs valid across draft/plan updates.
  useEffect(() => {
    if (changes.length === 0) {
      if (selectedChangeId !== null) setSelectedChangeId(null);
      if (expandedChangeId !== null) setExpandedChangeId(null);
      return;
    }
    if (!selectedChangeId || !changes.some((ch) => ch.opId === selectedChangeId)) {
      setSelectedChangeId(changes[0].opId);
    }
    if (expandedChangeId && !changes.some((ch) => ch.opId === expandedChangeId)) {
      setExpandedChangeId(null);
    }
  }, [changes, selectedChangeId, expandedChangeId]);

  // Execute authoritative Python guard diff via /api/guard/diff whenever plan changes.
  const opsSignature = useMemo(
    () => changes.map((c) => `${c.opId}:${c.afterText}`).join("\u0001"),
    [changes],
  );

  useEffect(() => {
    if (!sessionId || changes.length === 0) {
      setReviewGuardSummary(emptyReviewGuardSummary("idle", null));
      return;
    }
    if (draft.phase === "starting") {
      return;
    }
    let cancelled = false;
    if (draft.plan && draft.validation?.ok === true) {
      setReviewGuardSummary(emptyReviewGuardSummary("running", draft.plan.planId));
    }
    void runAuthoritativeGuardDiff(sessionId, draft, changes).then((result) => {
      if (!cancelled) {
        setReviewGuardSummary(result);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [
    sessionId,
    draft.plan?.planId,
    draft.plan?.planHash,
    draft.validation?.ok,
    draft.phase,
    opsSignature,
    changes,
    draft,
  ]);

  const handleSelectChange = useCallback((opId: string) => {
    setSelectedChangeId(opId);
  }, []);

  const handleToggleExpand = useCallback(
    (opId: string) => {
      setExpandedChangeId(expandedChangeId === opId ? null : opId);
    },
    [expandedChangeId],
  );

  const stepSelection = useCallback(
    (delta: -1 | 1) => {
      if (changes.length === 0) return;
      const idx = changes.findIndex((ch) => ch.opId === selectedChangeId);
      const start = idx >= 0 ? idx : 0;
      const next = (start + delta + changes.length) % changes.length;
      setSelectedChangeId(changes[next].opId);
    },
    [changes, selectedChangeId],
  );

  const stepChangedFact = useCallback(
    (delta: -1 | 1) => {
      const ids = guardSummary.changedFactOpIds;
      if (ids.length === 0) return;
      const orderedIds = changes
        .map((ch) => ch.opId)
        .filter((id) => ids.includes(id));
      if (orderedIds.length === 0) return;
      const currIdx = selectedChangeId ? orderedIds.indexOf(selectedChangeId) : -1;
      const nextIdx =
        currIdx < 0
          ? delta > 0
            ? 0
            : orderedIds.length - 1
          : (currIdx + delta + orderedIds.length) % orderedIds.length;
      const targetId = orderedIds[nextIdx];
      setSelectedChangeId(targetId);
      setExpandedChangeId(targetId);
    },
    [guardSummary.changedFactOpIds, changes, selectedChangeId],
  );

  const handleJumpNextChangedFact = useCallback(() => {
    stepChangedFact(1);
  }, [stepChangedFact]);

  const handleConfirmReturn = useCallback(
    async (reason: string) => {
      if (!sessionId) return;
      if (draft.plan?.planId) {
        markExternalPlanDismissed(sessionId, draft.plan.planId);
      }
      if (approval?.state === "pending" && approval.planId === draft.plan?.planId) {
        await resolveApprovalDecision("rejected", reason || "host-operator");
      } else {
        await clearQueue();
      }
      setReturnPopoverOpen(false);
    },
    [sessionId, draft.plan?.planId, approval],
  );

  const isStale = Boolean(
    reapprovalPrompt ||
      staleness !== null ||
      draft.validation?.stale ||
      (draft.plan && draft.boundSha256 && draft.plan.boundSha256 !== draft.boundSha256),
  );

  const busy =
    draft.phase === "starting" ||
    approvalPhase === "requesting" ||
    approvalPhase === "resolving" ||
    applyPhase === "starting";

  const canApprove =
    changes.length > 0 &&
    Boolean(draft.plan) &&
    draft.validation?.ok === true &&
    approval?.state !== "rejected" &&
    !isStale &&
    !busy;

  // Ruling H: listen for App-dispatched review keys, ignoring active editable elements.
  useEffect(() => {
    const onReviewKey = (evt: Event) => {
      if (isEditableElement(document.activeElement)) return;
      const detail = (evt as CustomEvent<ReviewKeyDetail>).detail;
      if (!detail) return;

      switch (detail.code) {
        case "KeyJ":
        case "ArrowDown":
          stepSelection(1);
          break;
        case "KeyK":
        case "ArrowUp":
          stepSelection(-1);
          break;
        case "Enter":
          if (selectedChangeId) {
            setExpandedChangeId(
              expandedChangeId === selectedChangeId ? null : selectedChangeId,
            );
          }
          break;
        case "KeyA":
          if (canApprove) {
            openApprovalDialog();
          }
          break;
        case "KeyR":
          if (changes.length > 0 && !busy) {
            setReturnPopoverOpen(true);
          }
          break;
        case "KeyD":
          if (selectedChangeId) {
            setExpandedChangeId(
              expandedChangeId === selectedChangeId ? null : selectedChangeId,
            );
          }
          break;
        case "KeyE":
          if (selectedChangeId) {
            setExpandedChangeId(selectedChangeId);
            setFocusEditNonce((n) => n + 1);
          }
          break;
        case "BracketLeft":
          if (guardSummary.changedFactOpIds.length > 0) {
            stepChangedFact(-1);
          } else if (printViewEnabled && page > 1) {
            void renderCurrentPage(page - 1);
          }
          break;
        case "BracketRight":
          if (guardSummary.changedFactOpIds.length > 0) {
            stepChangedFact(1);
          } else if (printViewEnabled && page < (render?.pageCount ?? 1)) {
            void renderCurrentPage(page + 1);
          }
          break;
        default:
          break;
      }
    };

    window.addEventListener("rigorloom:review-key", onReviewKey);
    return () => window.removeEventListener("rigorloom:review-key", onReviewKey);
  }, [
    stepSelection,
    stepChangedFact,
    selectedChangeId,
    expandedChangeId,
    canApprove,
    changes.length,
    busy,
    guardSummary.changedFactOpIds.length,
    printViewEnabled,
    page,
    render?.pageCount,
  ]);

  const handlePromptSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = promptText.trim();
    if (!trimmed || blocker !== null) return;
    setPromptText("");
    void sendInstruction(trimmed);
  };

  const handlePromptKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229 || promptComposingRef.current) {
      return;
    }
    e.stopPropagation();
  };

  if (!session || !inspect) {
    return (
      <section className="review-empty-view" data-testid="review-placeholder">
        <div className="review-placeholder-card">
          <p className="review-placeholder-text">
            {t("review_placeholder_ready", language)}
          </p>
          <button
            type="button"
            className="review-btn review-btn--primary"
            data-testid="review-open-doc-btn"
            onClick={() => navigateScreen("open")}
          >
            {t("action_open_doc", language)}
          </button>
        </div>
      </section>
    );
  }

  const selectedIndex = changes.findIndex((ch) => ch.opId === selectedChangeId);
  const currentOrdinal = selectedIndex >= 0 ? selectedIndex + 1 : changes.length > 0 ? 1 : 0;
  const promptBlockedReason = blocker && blocker !== "busy" ? errorCodeMessage(blocker, language) : null;

  return (
    <div
      className="review-view"
      data-testid="review-view"
      data-mobile-pane={mobileReviewPane}
    >
      <div
        className="review-mobile-tabs"
        role="tablist"
        aria-label={t("nav_review", language)}
        data-testid="review-mobile-tabs"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mobileReviewPane === "sheet"}
          className={`review-mobile-tab${
            mobileReviewPane === "sheet" ? " review-mobile-tab--active" : ""
          }`}
          data-testid="review-mobile-tab-sheet"
          onClick={() => setMobileReviewPane("sheet")}
        >
          {t("review_mobile_sheet_tab", language)}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mobileReviewPane === "list"}
          className={`review-mobile-tab${
            mobileReviewPane === "list" ? " review-mobile-tab--active" : ""
          }`}
          data-testid="review-mobile-tab-list"
          onClick={() => setMobileReviewPane("list")}
        >
          {t("review_mobile_list_tab", language, [changes.length])}
        </button>
      </div>

      <div className="review-left">
        <PageSheet
          sessionId={session.sessionId}
          inspect={inspect}
          texts={texts}
          textMap={textMap}
          changes={changes}
          rowAudits={guardSummary.rowAudits}
          selectedChangeId={selectedChangeId}
          language={language}
          onSelectChange={handleSelectChange}
        />
      </div>

      <div className="review-right">
        <ChangeList
          sessionId={session.sessionId}
          changes={changes}
          guardSummary={guardSummary}
          selectedChangeId={selectedChangeId}
          expandedChangeId={expandedChangeId}
          focusEditNonce={focusEditNonce}
          language={language}
          onSelectChange={handleSelectChange}
          onToggleExpand={handleToggleExpand}
          onJumpNextChangedFact={handleJumpNextChangedFact}
          onConfirmReturn={handleConfirmReturn}
        />

        {blocker === null || blocker === "busy" ? (
          <form
            className="review-prompt-bar"
            data-testid="review-prompt-bar"
            onSubmit={handlePromptSubmit}
          >
            <input
              type="text"
              className="review-prompt-input"
              data-testid="review-prompt-input"
              value={promptText}
              disabled={agentPhase === "starting"}
              placeholder={t("review_prompt_placeholder", language)}
              aria-label={t("review_prompt_placeholder", language)}
              onCompositionStart={() => {
                promptComposingRef.current = true;
              }}
              onCompositionEnd={(e) => {
                promptComposingRef.current = false;
                setPromptText(e.currentTarget.value);
              }}
              onChange={(e) => setPromptText(e.target.value)}
              onKeyDown={handlePromptKeyDown}
            />
            <button
              type="submit"
              className="review-btn review-btn--secondary"
              data-testid="review-prompt-submit"
              disabled={!promptText.trim() || agentPhase === "starting" || blocker === "busy"}
              title={promptBlockedReason ?? undefined}
            >
              {t("review_prompt_submit", language)}
            </button>
          </form>
        ) : null}
      </div>

      {changes.length > 0 ? (
        <div
          className="review-mobile-stepper"
          data-testid="review-mobile-stepper"
        >
          <button
            type="button"
            className="review-btn review-btn--secondary"
            data-testid="mobile-step-prev"
            disabled={changes.length <= 1}
            onClick={() => stepSelection(-1)}
          >
            {t("review_prev", language)}
          </button>

          <span className="review-mobile-step-counter" data-testid="mobile-step-counter">
            {`${currentOrdinal} / ${changes.length}`}
          </span>

          <button
            type="button"
            className="review-btn review-btn--secondary"
            data-testid="mobile-step-next"
            disabled={changes.length <= 1}
            onClick={() => stepSelection(1)}
          >
            {t("review_next", language)}
          </button>

          <button
            type="button"
            className="review-btn review-btn--primary"
            data-testid="mobile-step-approve"
            disabled={!canApprove}
            onClick={() => openApprovalDialog()}
          >
            {t("review_approve", language)}
          </button>
        </div>
      ) : null}
    </div>
  );
}
