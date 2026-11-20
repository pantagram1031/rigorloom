import { useMemo } from "react";

import type { CanvasChangeDecision, CanvasChangeRef } from "../model/page";
import { activeInspect, useWorkspace, type Draft } from "../store";
import type { RegionText } from "../types";
import {
  buildIndexedChanges,
  useReviewGuardSummary,
  type IndexedChange,
  type RowGuardAudit,
} from "../workspace/guardHelper";
import { useCanvasSlice } from "./controller";

export function useCanvasChanges(
  sessionId: string | null,
  textMap: Record<string, RegionText>,
) {
  const draft = useWorkspace((s) => s.draft);
  const inspect = useWorkspace(activeInspect);
  const language = useWorkspace((s) => s.language);
  const approval = useWorkspace((s) => s.approval);
  const { decisions } = useCanvasSlice(sessionId);
  const { planId, rowAudits } = useReviewGuardSummary();
  const isStale = Boolean(
    draft.validation?.stale ||
      (draft.plan && draft.boundSha256 && draft.plan.boundSha256 !== draft.boundSha256),
  );

  const approvalState =
    approval && approval.planId === draft.plan?.planId && approval.planHash === draft.plan.planHash
      ? approval.state
      : null;
  const approvalDecision: CanvasChangeDecision | undefined =
    approvalState === "approved" ? "accepted" : approvalState === "rejected" ? "rejected" : undefined;

  const changes = useMemo(() => {
    if (!inspect) return [];
    const indexed = buildIndexedChanges(draft, inspect, textMap, language);
    return indexedChangesToCanvasRefs(
      indexed,
      planId === draft.plan?.planId ? rowAudits : {},
      decisions,
      { isStale, reverses: draft.reverses, plan: draft.plan, approvalDecision },
    );
  }, [inspect, draft, textMap, language, planId, rowAudits, decisions, isStale, approvalDecision]);

  return changes;
}

export function indexedChangesToCanvasRefs(
  changes: readonly IndexedChange[],
  rowAudits: Record<string, RowGuardAudit>,
  decisions: Readonly<Record<string, CanvasChangeDecision>>,
  options: {
    isStale?: boolean;
    reverses?: string | null;
    plan?: Draft["plan"];
    approvalDecision?: CanvasChangeDecision;
  },
): CanvasChangeRef[] {
  return changes.map((ch) => {
    const audit = rowAudits[ch.opId];
    const op = ch.op;
    const isTest = op.provenance === "mock" ||
      (options.plan?.provenance === "mock" &&
        (options.plan.mockOps?.includes(op.opId) ?? true));
    const source = isTest ? "test" : options.reverses ? "revert" : op.origin;
    const decision = decisions[ch.opId] ?? options.approvalDecision ??
      (source === "user" ? "accepted" : "pending");
    const isFactChanged = audit?.status === "changed";
    const guard: CanvasChangeRef["guard"] =
      audit?.status === "changed"
        ? "changed"
        : audit?.status === "needs_fixes"
          ? "needs_fixes"
          : audit?.status === "kept"
            ? "kept"
            : "none";

    const cellKey =
      op.kind === "fill_cell" || op.kind === "replace_at_cell"
        ? `c:${op.table}:${op.row}:${op.col}`
        : undefined;
    const at =
      op.kind === "fill_cell" || op.kind === "replace_at_cell"
        ? `t${op.table}/r${op.row}/c${op.col}`
        : op.kind === "set_run"
          ? `p${op.atPara}`
          : "place:guides";

    return {
      id: ch.opId,
      n: ch.ordinal,
      at,
      kind: ch.opKindText,
      opKind: op.kind,
      label: ch.fieldLabel,
      before: ch.beforeText,
      after: ch.afterText,
      page: 1,
      source,
      decision,
      guard,
      hard: ch.hasHardFailure,
      isFactChanged,
      isStale: Boolean(options.isStale),
      cellKey,
      atPara: op.kind === "set_run" ? op.atPara : undefined,
      run:
        op.kind === "replace_at_cell" || op.kind === "set_run"
          ? op.run
          : undefined,
      hasFormText: ch.beforeText.trim().length > 0 && op.kind === "replace_at_cell",
      bodyStyleApplied:
        (op.kind === "fill_cell" || op.kind === "replace_at_cell") &&
        Boolean(op.charPr),
    };
  });
}
