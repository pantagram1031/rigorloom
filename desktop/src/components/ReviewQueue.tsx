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
import { useEffect, useState } from "react";

import {
  approveAndApply,
  approveOnly,
  redoQueuedOp,
  reproposeDraft,
  resolveApprovalDecision,
  cancelApply,
  clearQueue,
  resolveRecovery,
  undoQueuedOp,
} from "../actions";
import {
  hunkReviewState,
  queueRefusalMessage,
  reviewQueueHotkey,
  type HunkProvenance,
} from "../reviewHunk";
import {
  canRequestApproval,
  draftStaleness,
  getState,
  locateSelection,
  setCenterMode,
  setView,
  showToast,
  useWorkspace,
  type Draft,
  type QueuedOp,
} from "../store";
import { relativeWhen } from "../label";
import { focusFirstHunk, focusHunkAt } from "../focus";
import type { PlanFinding } from "../types";
import { hasActiveApprovalBinding } from "../workspace/reviewSummary";
import { EmptyIconInbox, EmptyState } from "./EmptyState";
import { HunkCard } from "./HunkCard";
import { Tag } from "./Tag";
import { Alert } from "../ui/Alert";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/Collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/DropdownMenu";
import { Tooltip } from "../ui/Tooltip";

/** Findings that name one op, keyed the way `validate_plan` writes `at`. */
function findingsFor(op: QueuedOp, rows: PlanFinding[]): PlanFinding[] {
  return rows.filter((row) => row.at === `ops[${op.opId}]`);
}

/** Reveal a queued address only when its owning document is still active. */
export function locateQueuedOp(op: QueuedOp): boolean {
  const state = getState();
  if (
    !state.activeSessionId ||
    state.draft.sessionId !== state.activeSessionId ||
    !state.draft.ops.some((queued) => queued.opId === op.opId)
  ) {
    return false;
  }
  setView("document");
  setCenterMode("text");
  if (op.kind === "fill_cell") {
    locateSelection({ kind: "cell", table: op.table, row: op.row, col: op.col });
    return true;
  }
  if (op.kind === "set_run") {
    locateSelection({ kind: "paragraph", atPara: op.atPara });
    return true;
  }
  return false;
}

export type { HunkProvenance };

/** GitHub-style provenance on every hunk. Plan JSON is unchanged. */
export function hunkProvenance(
  op: Pick<QueuedOp, "origin" | "proposer">,
  draft: Pick<Draft, "sessionId" | "plan" | "baseRunId">,
  receipts: Record<string, unknown>,
  head: string | null,
): HunkProvenance {
  const plan = draft.plan;
  return {
    sessionId: draft.sessionId ?? plan?.sessionId ?? null,
    planId: plan?.planId ?? null,
    planHash: plan?.planHash ?? null,
    proposer: op.proposer ?? plan?.proposer ?? (op.origin === "agent" ? "agent" : "user"),
    backend: plan?.backend ?? null,
    baseRunId: draft.baseRunId ?? plan?.base?.runId ?? null,
    receiptExists: head != null && receipts[head] != null,
  };
}

/** Same path as 승인만: record the displayed hash, do not apply. */
export function approveDisplayedPlan(): void {
  if (getState().isComposing) return;
  void approveOnly();
}

export function rejectDisplayedPlan(): void {
  if (getState().isComposing) return;
  void resolveApprovalDecision("rejected");
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable;
}

function approveAllTitle(
  composing: boolean,
  canRun: boolean,
  recoveryBlocksApply: boolean,
): string {
  if (composing) return "입력 조합이 끝나기 전에는 승인하지 않습니다";
  if (recoveryBlocksApply) return "결과가 불명확하거나 이미 완료된 적용은 반복하지 않습니다";
  if (!canRun) return "확인을 통과한 계획만 승인하고 적용할 수 있습니다";
  return "화면에 보이는 계획을 승인하고 적용합니다";
}

function primaryBusyLabel(approvalPhase: string, applyPhase: string): string {
  if (applyPhase === "starting") return "적용하는 중…";
  if (approvalPhase === "resolving") return "기록하는 중…";
  if (approvalPhase === "requesting") return "요청하는 중…";
  return "승인하고 적용";
}

/** Primary 검토 action. Request → approve → apply, each still a Runtime step. */
export function ApproveAllButton() {
  const draft = useWorkspace((s) => s.draft);
  const composing = useWorkspace((s) => s.isComposing);
  const approval = useWorkspace((s) => s.approval);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const applyPhase = useWorkspace((s) => s.applyPhase);
  const recovery = useWorkspace((s) => s.recovery);
  const approvalBound = useWorkspace(hasActiveApprovalBinding);
  const approvable = useWorkspace(canRequestApproval);
  const locked =
    approvalPhase === "requesting" ||
    approvalPhase === "resolving" ||
    applyPhase === "starting";
  const recoveryBlocksApply =
    !!recovery &&
    recovery.outcome !== "not_applied" &&
    recovery.planId === draft.plan?.planId &&
    recovery.approvalId === approval?.approvalId;
  const canRun =
    draft.ops.length > 0 &&
    !locked &&
    !composing &&
    !recoveryBlocksApply &&
    (((!approval || approval.state === "rejected") &&
      (approvable || approval?.state === "rejected")) ||
      (approval?.state === "pending" && approvalBound) ||
      (approval?.state === "approved" && approvalBound));
  const canApproveOnly = canRun && approval?.state !== "approved";
  const count = draft.ops.length;
  const label = primaryBusyLabel(approvalPhase, applyPhase);
  const tip = approveAllTitle(composing, canRun, recoveryBlocksApply);
  return (
    <div className="approve-split approve-all">
      <Tooltip content={tip}>
        <Button
          variant="primary"
          className="point"
          data-testid="approve-and-apply"
          disabled={!canRun}
          aria-label="승인하고 적용"
          onClick={() => {
            if (getState().isComposing) return;
            void approveAndApply();
          }}
        >
          {label}
          {count > 0 ? (
            <Badge variant="secondary" className="tab-badge" data-testid="approve-all-count">
              {count}
            </Badge>
          ) : null}
        </Button>
      </Tooltip>
      <DropdownMenu>
        <Tooltip content="승인만">
          <DropdownMenuTrigger
            className="action point split-caret"
            data-testid="approve-only-menu"
            disabled={!canApproveOnly}
            aria-label="승인만"
          >
            ▾
          </DropdownMenuTrigger>
        </Tooltip>
        <DropdownMenuContent align="end">
          <Tooltip content="화면에 보이는 계획에 승인을 기록합니다. 적용은 하지 않습니다.">
            <DropdownMenuItem
              data-testid="approve-only"
              disabled={!canApproveOnly}
              onClick={() => {
                if (getState().isComposing) return;
                void approveOnly();
              }}
            >
              승인만
            </DropdownMenuItem>
          </Tooltip>
        </DropdownMenuContent>
      </DropdownMenu>
      {applyPhase === "starting" ? (
        <Button variant="ghost" data-testid="cancel-apply" onClick={() => void cancelApply()}>
          멈추기
        </Button>
      ) : null}
    </div>
  );
}

export function ReviewQueue() {
  const draft = useWorkspace((s) => s.draft);
  const validation = draft.validation;
  const staleness = useWorkspace(draftStaleness);
  const approval = useWorkspace((s) => s.approval);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const approvalError = useWorkspace((s) => s.approvalError);
  const applyPhase = useWorkspace((s) => s.applyPhase);
  const applyError = useWorkspace((s) => s.applyError);
  const recovery = useWorkspace((s) => s.recovery);
  const redoCount = useWorkspace((s) => s.redoStack.length);
  const activeSessionId = useWorkspace((s) => s.activeSessionId);
  const approvalBound = useWorkspace(hasActiveApprovalBinding);
  const receipts = useWorkspace((s) => s.receipts);
  const head = useWorkspace((s) => s.head);
  const composing = useWorkspace((s) => s.isComposing);
  const texts = useWorkspace((s) =>
    s.activeSessionId ? s.texts?.[s.activeSessionId] : undefined,
  );
  const applied = useWorkspace((s) => s.applied);
  const verdict = useWorkspace((s) => s.candidateVerdict);

  const [focused, setFocused] = useState(0);
  const [openProvenance, setOpenProvenance] = useState<Record<string, boolean>>({});

  const locked =
    approvalPhase === "requesting" ||
    approvalPhase === "resolving" ||
    applyPhase === "starting";
  const locatable = !!activeSessionId && draft.sessionId === activeSessionId;
  const canDecide = approvalBound && !locked && !composing;

  const appliedForPlan = !!applied && !!draft.plan && applied.planId === draft.plan.planId;
  const stateId = hunkReviewState({
    stale: !!staleness,
    approvalState: approval?.state,
    applied: appliedForPlan,
  });

  const receipt = head ? receipts[head] : undefined;
  const refusalMessage = queueRefusalMessage({
    verdict: verdict?.report,
    applyError,
    draftError: draft.error,
    exitCodes: receipt?.steps.map((step) => step.exitCode),
  });

  useEffect(() => {
    if (focused >= draft.ops.length) setFocused(Math.max(0, draft.ops.length - 1));
  }, [draft.ops.length, focused]);

  useEffect(() => {
    if (draft.ops.length === 0) return;
    const id = window.requestAnimationFrame(() => focusFirstHunk());
    return () => window.cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const action = reviewQueueHotkey(e, {
        focused,
        count: draft.ops.length,
        composing: composing || e.isComposing,
        inEditable: isEditableTarget(e.target),
      });
      if (action.type === "none") return;
      e.preventDefault();
      if (action.type === "focus") {
        setFocused(action.index);
        return;
      }
      if (action.type === "approve-and-apply") {
        void approveAndApply();
        return;
      }
      if (action.type === "approve-all") {
        void approveOnly();
        return;
      }
      if (action.type === "approve-hunk") {
        return;
      }
      if (action.type === "reject-hunk") {
        const op = draft.ops[action.index];
        if (op) void undoQueuedOp(op.opId);
        return;
      }
      const op = draft.ops[action.index];
      if (!op) return;
      setOpenProvenance((prev) => ({ ...prev, [op.opId]: !prev[op.opId] }));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focused, draft.ops, composing]);

  /** Put the last removed row back — the same target, the same value. */
      const redo =
    redoCount > 0 ? (
      <Tooltip content="방금 대기열에서 뺀 작업을 그대로 다시 넣습니다">
        <Button
          variant="ghost"
          className="dark-safe"
          data-testid="queue-redo"
          disabled={locked}
          onClick={() => void redoQueuedOp()}
        >
          다시 넣기 {redoCount}
        </Button>
      </Tooltip>
    ) : null;

  if (draft.ops.length === 0) {
    if (draft.phase === "failed" && draft.error) {
      return (
        <div className="section" data-testid="review-queue-error">
          <EmptyState
            icon={<EmptyIconInbox />}
            title={"검토할 수 없습니다"}
            body={draft.error.message}
          />
          {redo ? <div className="gate-actions">{redo}</div> : null}
        </div>
      );
    }
    return (
      <div className="section" data-testid="review-queue-empty">
        <EmptyState
          icon={<EmptyIconInbox />}
          title={"검토할 것이 없습니다"}
          body="문서에서 입력 칸을 누르면 값이 여기에 쌓입니다."
        />
        {redo ? <div className="gate-actions">{redo}</div> : null}
      </div>
    );
  }

  return (
    <div className="section queue" data-testid="review-queue" tabIndex={0} aria-label="검토 대기열">
      <h3>
        검토 대기열
        <span className="count" data-testid="queue-count">
          {draft.ops.length}
        </span>
        {approval?.state === "pending" ? (
          <span className="tiny dim" data-testid="queue-requested">
            {approval.requestedBy} · {relativeWhen(approval.requestedUtc)}
          </span>
        ) : null}
      </h3>

      {refusalMessage ? (
        <Alert variant="destructive" className="refusal" data-testid="queue-refusal">
          <Tag tone="bad">거절됨</Tag>
          <p className="prose">{refusalMessage}</p>
        </Alert>
      ) : null}

      {/* TIER TWO UNDO, in the queue where every other proposal lives. An
          applied candidate is immutable and receipted, so this is not an
          edit of it — it is the inverse, proposed, waiting for the same
          approval as anything else, and it will produce one MORE candidate. */}
      {draft.reverses ? (
        <div className="refusal" data-testid="queue-reversal">
          <Tag tone="warn">되돌리기 제안</Tag>
          <p className="prose">되돌리는 계획입니다. 그 후보본은 지워지지 않습니다.</p>
          {draft.baseRunId ? (
            <Collapsible className="disclosure">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
<p className="mono tiny">이어 붙일 후보본 {draft.baseRunId.slice(0, 12)}</p>
      </CollapsibleContent>
      </Collapsible>
          ) : null}
        </div>
      ) : draft.baseRunId ? (
        <p className="prose tiny" data-testid="queue-base">
          이 대기열은 후보본{" "}
          <span className="mono">{draft.baseRunId.slice(0, 12)}</span> 위에 이어 붙습니다.
          앞서 승인한 편집은 그대로 남습니다.
        </p>
      ) : null}

      {draft.rewrittenFromAgent ? (
        <p className="prose note-rewrite">
          에이전트가 낸 계획을 고쳤습니다. 승인은 지금 보이는 계획에만 묶입니다.
        </p>
      ) : null}

      {staleness ? (
        <div className="refusal" data-testid="queue-stale">
          <Tag tone="bad">계획이 낡음</Tag>
          <p className="prose">
            {staleness.kind === "other_session"
              ? "이 대기열은 다른 문서에 묶여 있어 승인할 수 없습니다."
              : "계획을 낸 뒤 원본이 바뀌었습니다."}
          </p>
          <Collapsible className="disclosure">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
<p className="mono tiny">
              묶인 해시 {staleness.boundSha256.slice(0, 16)} · 지금{" "}
              {staleness.currentSha256?.slice(0, 16) ?? "알 수 없음"}
            </p>
      </CollapsibleContent>
      </Collapsible>
          <Button
            variant="primary"
            data-testid="queue-repropose"
            onClick={() => void reproposeDraft()}
          >
            지금 문서로 다시 제안
          </Button>
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
        {draft.ops.map((op, index) => (
          <HunkCard
            key={op.opId}
            op={op}
            hard={findingsFor(op, validation?.hard ?? [])}
            warn={findingsFor(op, validation?.warn ?? [])}
            locked={locked}
            locatable={locatable && (op.kind === "fill_cell" || op.kind === "set_run")}
            provenance={hunkProvenance(op, draft, receipts, head)}
            focused={index === focused}
            provenanceOpen={!!openProvenance[op.opId]}
            onToggleProvenance={() =>
              setOpenProvenance((prev) => ({ ...prev, [op.opId]: !prev[op.opId] }))
            }
            onLocate={() => locateQueuedOp(op)}
            onApprove={() => {
              if (getState().isComposing) return;
              const next = Math.min(index + 1, Math.max(0, draft.ops.length - 1));
              setFocused(next);
              window.requestAnimationFrame(() => focusHunkAt(next));
            }}
            onReject={() => {
              if (getState().isComposing) return;
              void undoQueuedOp(op.opId);
            }}
            canDecide={!locked && !composing}
            regions={texts}
            stateId={stateId}
            showToast={showToast}
          />
        ))}
      </ul>

      {validation ? (
        <div className="queue-verdict" data-testid="queue-verdict">
          <div className="queue-verdict-head">
            {validation.ok ? (
              <Tag tone="ok" title={"쓰기 전 확인 통과"}>
                검사 통과
              </Tag>
            ) : (
              <Tag tone="bad">막힘 {validation.counts.hard}</Tag>
            )}
            {validation.counts.warn > 0 ? (
              <Tag tone="warn">주의 {validation.counts.warn}</Tag>
            ) : null}
            {draft.plan?.planHash ? (
              <Collapsible className="disclosure">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
<p className="mono tiny">{draft.plan.planHash}</p>
                {approval ? (
                  <dl className="kv">
                    <dt>요청자</dt>
                    <dd>{approval.requestedBy}</dd>
                    <dt>요청 시각</dt>
                    <dd className="mono">{approval.requestedUtc}</dd>
                    <dt>계획</dt>
                    <dd className="mono">{approval.planId}</dd>
                    <dt>해시</dt>
                    <dd className="mono">{approval.planHash}</dd>
                  </dl>
                ) : null}
      </CollapsibleContent>
      </Collapsible>
            ) : null}
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
          <Collapsible className="disclosure">
        <CollapsibleTrigger>검사가 보지 않는 것</CollapsibleTrigger>
        <CollapsibleContent>
<p className="prose">{validation.preflight.note}</p>
            <ul className="deferred">
              {validation.preflight.deferred.map((code) => (
                <li key={code} className="mono">
                  {code}
                </li>
              ))}
            </ul>
            <p className="prose tiny">근거: {validation.preflight.source}</p>
      </CollapsibleContent>
      </Collapsible>
          <Collapsible className="disclosure">
        <CollapsibleTrigger>계획 원본</CollapsibleTrigger>
        <CollapsibleContent>
<pre>{JSON.stringify(draft.plan, null, 2)}</pre>
      </CollapsibleContent>
      </Collapsible>
        </div>
      ) : draft.phase === "starting" ? (
        <p className="empty">계획을 확인하는 중입니다.</p>
      ) : null}

      <div className="gate-actions">
        {approval?.state === "pending" ? (
          <Tooltip
            content={
              composing
                ? "입력 조합이 끝나기 전에는 거절하지 않습니다"
                : approvalBound
                  ? "이 승인 요청을 거절합니다"
                  : "현재 문서와 정확히 일치하는 승인만 거절할 수 있습니다"
            }
          >
            <Button
              variant="secondary"
              data-testid="reject"
              disabled={!canDecide}
              onClick={() => {
                if (getState().isComposing) return;
                rejectDisplayedPlan();
              }}
            >
              거절
            </Button>
          </Tooltip>
        ) : null}
        {redo}
        <Button variant="ghost" className="dark-safe" disabled={locked} onClick={() => void clearQueue()}>
          대기열 비우기
        </Button>
      </div>

      {approvalError ? (
        <div className="refusal" data-testid="approval-error">
          <Tag tone="bad">승인 거절됨</Tag>
          <p className="prose">{approvalError.message}</p>
          <p className="mono tiny">{approvalError.code}</p>
          {approvalError.code === "plan_stale" ? (
            <Button variant="secondary" onClick={() => void reproposeDraft()}>
              지금 문서로 다시 제안
            </Button>
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
            <Collapsible className="disclosure">
        <CollapsibleTrigger>엔진이 보낸 그대로</CollapsibleTrigger>
        <CollapsibleContent>
<pre>{JSON.stringify(applyError.data, null, 2)}</pre>
      </CollapsibleContent>
      </Collapsible>
          ) : null}
        </div>
      ) : null}

      {recovery ? (
        <div className="refusal" data-testid="apply-recovery">
          <Tag tone="bad">적용 중에 엔진이 멈췄습니다</Tag>
          <p className="prose">
            {recovery.outcome === "unknown"
              ? "적용이 끝나기 전에 연결이 끊겼습니다. 후보본이 생겼는지는 목록을 다시 읽습니다."
              : recovery.outcome === "applied"
                ? "확인했습니다. 후보본은 만들어졌고 영수증도 남아 있습니다."
                : "확인했습니다. 후보본은 만들어지지 않았습니다. 문서는 그대로입니다."}
          </p>
          <Collapsible className="disclosure">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
<p className="mono tiny">
              {recovery.atUtc} · plan {recovery.planId.slice(0, 12)}
              {recovery.runId ? ` · run ${recovery.runId.slice(0, 12)}` : ""}
            </p>
      </CollapsibleContent>
      </Collapsible>
          {recovery.outcome === "unknown" ? (
            <Button
              variant="primary"
              data-testid="recovery-check"
              onClick={() => void resolveRecovery()}
            >
              후보본이 생겼는지 확인
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
