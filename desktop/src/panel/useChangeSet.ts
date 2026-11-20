/**
 * Gathers today's store state into a `ChangeSetView`, with decisions applied,
 * and drives the two things the old ReviewView drove: adopting a plan an
 * agent or the CLI proposed over the wire, and running the authoritative
 * guard diff whenever the plan's content changes.
 */
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";

import { adoptExternalPlan, attachExternalApproval, revisionNumberFor } from "../actions";
import { useIndexedCanvasChanges } from "../canvas/changes";
import { canvasSlice } from "../canvas/controller";
import { pruneDecisions, type ChangeSetView } from "../model/changes";
import { activeDisplayText, activeInspect, draftStaleness, headCandidate, useWorkspace } from "../store";
import {
  findAdoptableExternalPlan,
  findPendingExternalApproval,
  buildRegionTextMap,
} from "../workspace/externalPlan";
import {
  emptyReviewGuardSummary,
  getReviewGuardKey,
  getReviewGuardSummary,
  runAuthoritativeGuardDiff,
  setReviewGuardSummary,
  useReviewGuardSummary,
  type IndexedChange,
  type ReviewGuardSummary,
} from "../workspace/guardHelper";
import { fromWorkspace, staleFromValidation } from "./adapter";
import { setLatestView } from "./state";

export interface ChangeSetContext {
  view: ChangeSetView | null;
  guard: ReviewGuardSummary;
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

export function useChangeSet(sessionId: string): ChangeSetContext {
  const session = useWorkspace((s) => s.sessions.find((x) => x.sessionId === sessionId) ?? null);
  const draft = useWorkspace((s) => s.draft);
  const texts = useWorkspace(activeDisplayText);
  const language = useWorkspace((s) => s.language);
  const staleness = useWorkspace(draftStaleness);
  const reapproval = useWorkspace((s) => s.reapprovalPrompt);
  const head = useWorkspace(headCandidate);
  const candidates = useWorkspace((s) => (s.activeSessionId ? s.candidates[s.activeSessionId] : undefined));
  const appliedState = useWorkspace((s) => s.applied);
  const guard = useReviewGuardSummary();

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);
  const { indexed, changes } = useIndexedCanvasChanges(sessionId, textMap);
  useReviewDriver(sessionId, indexed);

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

  const view = useMemo(() => {
    const stale =
      staleFromValidation(draft.validation) ??
      (staleness?.kind === "source_changed" || reapproval ? "source_changed" : null) ??
      (draft.plan && currentRevision > baseRevision ? "plan_behind_head" : null);
    return fromWorkspace({
      language,
      indexed,
      changes,
      guard,
      plan: draft.plan,
      validation: draft.validation,
      failureCode: draft.phase === "failed" ? draft.error?.code : undefined,
      baseRevision,
      baseSha256: session?.source.sha256 ?? "",
      currentRevision,
      stale,
    });
  }, [indexed, changes, guard, draft.plan, draft.validation, draft.phase, draft.error, staleness, reapproval, baseRevision, currentRevision, language, session]);

  useLayoutEffect(() => {
    setLatestView(sessionId, view);
    return () => setLatestView(sessionId, null);
  }, [sessionId, view]);

  useEffect(() => {
    if (draft.phase === "starting" || (draft.sessionId && draft.sessionId !== sessionId)) return;
    if (!view && draft.ops.length > 0) return;
    const { decisions } = canvasSlice.get(sessionId);
    const pruned = pruneDecisions(decisions, view?.items ?? []);
    if (Object.keys(pruned).length !== Object.keys(decisions).length) {
      canvasSlice.patch(sessionId, { decisions: pruned });
    }
  }, [view, draft, sessionId]);

  return { view, guard };
}
