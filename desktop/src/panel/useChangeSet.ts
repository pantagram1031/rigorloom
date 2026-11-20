/**
 * Gathers today's store state into a `ChangeSetView`, with decisions applied,
 * and drives the two things the old ReviewView drove: adopting a plan an
 * agent or the CLI proposed over the wire, and running the authoritative
 * guard diff whenever the plan's content changes.
 */
import { useEffect, useMemo, useRef } from "react";

import { adoptExternalPlan, attachExternalApproval, revisionNumberFor } from "../actions";
import { pruneDecisions, withDecisions, type ChangeSetView } from "../model/changes";
import { activeInspect, activeText, draftStaleness, headCandidate, useWorkspace } from "../store";
import {
  findAdoptableExternalPlan,
  findPendingExternalApproval,
  buildRegionTextMap,
} from "../workspace/externalPlan";
import {
  buildIndexedChanges,
  emptyReviewGuardSummary,
  getReviewGuardKey,
  getReviewGuardSummary,
  runAuthoritativeGuardDiff,
  setReviewGuardSummary,
  useReviewGuardSummary,
  type IndexedChange,
  type ReviewGuardSummary,
} from "../workspace/guardHelper";
import { fromWorkspace, planIsMock, staleFromValidation } from "./adapter";
import { panelSlice, setLatestView } from "./state";

export interface ChangeSetContext {
  view: ChangeSetView | null;
  changes: readonly IndexedChange[];
  guard: ReviewGuardSummary;
  sessionId: string | null;
  currentRevision: number;
}

/** Adopt wire-proposed plans and keep the guard summary current. */
function useReviewDriver(sessionId: string | null, changes: readonly IndexedChange[]): void {
  const draft = useWorkspace((s) => s.draft);
  const events = useWorkspace((s) => s.events);
  const approval = useWorkspace((s) => s.approval);
  const inspect = useWorkspace(activeInspect);
  const textsBySession = useWorkspace((s) => s.texts);
  const adoptedRef = useRef<string | null>(null);
  const attachedRef = useRef<string | null>(null);
  const hasTexts = Boolean(sessionId && inspect && Object.prototype.hasOwnProperty.call(textsBySession, sessionId));

  useEffect(() => {
    adoptedRef.current = null;
    attachedRef.current = null;
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !hasTexts) return;
    const candidate = findAdoptableExternalPlan(sessionId, events, draft);
    if (candidate) {
      const key = `${sessionId}:${candidate.planId}`;
      const attachKey = candidate.approvalId ? `${key}:${candidate.approvalId}` : null;
      if (adoptedRef.current !== key || (attachKey && attachedRef.current !== attachKey)) {
        adoptedRef.current = key;
        if (attachKey) attachedRef.current = attachKey;
        void adoptExternalPlan(sessionId, candidate.planId, candidate.approvalId);
      }
      return;
    }
    const pending = findPendingExternalApproval(sessionId, events, draft, approval);
    if (pending) {
      const key = `${sessionId}:${pending.planId}:${pending.approvalId}`;
      if (attachedRef.current !== key) {
        attachedRef.current = key;
        void attachExternalApproval(sessionId, pending.planId, pending.approvalId);
      }
    }
  }, [sessionId, hasTexts, events, draft, approval]);

  const signature = useMemo(
    () => changes.map((c) => `${c.opId}:${c.beforeText}:${c.afterText}:${c.isAuditable ? 1 : 0}`).join("\u0001"),
    [changes],
  );
  const hardSig = (draft.validation?.hard ?? []).map((f) => `${f.code}@${f.at}`).join("\u0001");
  const key =
    sessionId && changes.length > 0
      ? [sessionId, draft.plan?.planId ?? "", draft.plan?.planHash ?? "", String(draft.validation?.ok ?? null), draft.phase, hardSig, signature].join("\u0000")
      : null;
  const latest = useRef({ draft, changes });
  latest.current = { draft, changes };

  useEffect(() => {
    if (!sessionId || !key) {
      setReviewGuardSummary(emptyReviewGuardSummary("idle", null), null);
      return;
    }
    if (draft.phase === "starting") return;
    const existing = getReviewGuardSummary();
    if (getReviewGuardKey() === key && ["ready", "invalid_plan", "unavailable"].includes(existing.state)) return;
    let cancelled = false;
    const { draft: d, changes: c } = latest.current;
    if (d.plan && d.validation?.ok === true) {
      setReviewGuardSummary(emptyReviewGuardSummary("running", d.plan.planId), key);
    }
    void runAuthoritativeGuardDiff(sessionId, d, c).then((result) => {
      if (!cancelled) setReviewGuardSummary(result, key);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, draft.phase, key]);
}

export function useChangeSet(): ChangeSetContext {
  const sessionId = useWorkspace((s) => s.activeSessionId);
  const session = useWorkspace((s) => s.sessions.find((x) => x.sessionId === s.activeSessionId) ?? null);
  const draft = useWorkspace((s) => s.draft);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeText);
  const language = useWorkspace((s) => s.language);
  const staleness = useWorkspace(draftStaleness);
  const reapproval = useWorkspace((s) => s.reapprovalPrompt);
  const provider = useWorkspace((s) => s.provider.provider);
  const turns = useWorkspace((s) => s.turns);
  const head = useWorkspace(headCandidate);
  const candidates = useWorkspace((s) => (s.activeSessionId ? s.candidates[s.activeSessionId] : undefined));
  const appliedState = useWorkspace((s) => s.applied);
  const guard = useReviewGuardSummary();
  const decisions = panelSlice.use(sessionId, (s) => s.decisions);

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);
  const ownDraft = draft.sessionId === null || draft.sessionId === sessionId;
  const changes = useMemo(
    () => (ownDraft ? buildIndexedChanges(draft, inspect, textMap, language) : []),
    [ownDraft, draft, inspect, textMap, language],
  );
  useReviewDriver(sessionId, changes);

  const revisionOf = (runId: string | null | undefined): number => {
    if (!runId || !sessionId) return 0;
    return (
      revisionNumberFor(
        { candidates: { [sessionId]: candidates ?? [] }, applied: appliedState } as unknown as Parameters<typeof revisionNumberFor>[0],
        sessionId,
        runId,
      ) ?? 0
    );
  };
  const baseRevision = revisionOf(draft.plan?.base?.runId ?? draft.baseRunId);
  const currentRevision = revisionOf(head?.runId ?? null);

  const mockTurn = draft.plan ? turns.some((t) => t.planId === draft.plan?.planId && t.provider === "mock") : false;
  const mock = planIsMock(draft.plan) || mockTurn;

  const view = useMemo(() => {
    const stale =
      staleFromValidation(draft.validation) ??
      (staleness?.kind === "source_changed" || reapproval ? "source_changed" : null) ??
      (draft.plan && currentRevision > baseRevision ? "plan_behind_head" : null);
    const base = fromWorkspace({
      language,
      changes,
      guard,
      plan: draft.plan,
      validation: draft.validation,
      baseRevision,
      baseSha256: session?.source.sha256 ?? "",
      currentRevision,
      stale,
      mock,
      provider: mock ? "mock" : provider === "mock" ? null : provider,
    });
    if (!base) return null;
    return { ...base, items: withDecisions(base.items, decisions) };
  }, [changes, guard, draft.plan, draft.validation, staleness, reapproval, baseRevision, currentRevision, mock, provider, language, decisions, session]);

  setLatestView(sessionId, view);

  // Forget decisions whose item is gone or changed, so a returned item can
  // never come back already decided.
  useEffect(() => {
    if (!view) return;
    const pruned = pruneDecisions(decisions, view.items);
    if (Object.keys(pruned).length !== Object.keys(decisions).length) {
      panelSlice.set(sessionId, { decisions: pruned });
    }
  }, [view, decisions, sessionId]);

  return { view, changes, guard, sessionId, currentRevision };
}
