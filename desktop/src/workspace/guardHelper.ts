import { useSyncExternalStore } from "react";
import {
  projectedAfterText,
  projectionInverseSupport,
} from "../agent/planProjection";
import { opKindLabel, t } from "../i18n/vocabulary";
import type { Draft, QueuedOp } from "../store";
import * as rt from "../runtime";
import type {
  GuardDiffParagraph,
  GuardDiffResult,
  InspectResult,
  PlanFinding,
  RegionText,
  UiLanguage,
} from "../types";
import { deriveOpFieldLabel } from "./fieldLabels";

export type GuardAuditState =
  | "idle"
  | "running"
  | "ready"
  | "invalid_plan"
  | "unavailable";

export type RowGuardStatus = "none" | "needs_fixes" | "kept" | "changed";

export interface IndexedChange {
  ordinal: number;
  originalIndex: number;
  op: QueuedOp;
  opId: string;
  fieldLabel: string;
  opKindText: string;
  beforeText: string;
  afterText: string;
  targetKey: string | null;
  hardFindings: PlanFinding[];
  warnFindings: PlanFinding[];
  hasHardFailure: boolean;
  isAuditable: boolean;
  isEmptyBlankFill: boolean;
  invertible: boolean;
  nonInvertibleReason?: string;
}

export interface RowGuardAudit {
  status: RowGuardStatus;
  paragraph: GuardDiffParagraph | null;
  addedNumbers: string[];
}

export interface ReviewGuardSummary {
  state: GuardAuditState;
  planId: string | null;
  documentDiff: GuardDiffResult | null;
  rowAudits: Record<string, RowGuardAudit>;
  changedFactOpIds: string[];
  needsFixesOpIds: string[];
  errorCode: string | null;
}

export function emptyReviewGuardSummary(
  state: GuardAuditState = "idle",
  planId: string | null = null,
): ReviewGuardSummary {
  return {
    state,
    planId,
    documentDiff: null,
    rowAudits: {},
    changedFactOpIds: [],
    needsFixesOpIds: [],
    errorCode: null,
  };
}

function collectTableAnchorParas(
  textMap: Record<string, RegionText>,
): Map<number, number> {
  const tableMinPara = new Map<number, number>();
  for (const region of Object.values(textMap)) {
    if (!region.addr || typeof region.at_para !== "number") continue;
    const tableIdx = region.table ?? 0;
    const prev = tableMinPara.get(tableIdx);
    if (prev === undefined || region.at_para < prev) {
      tableMinPara.set(tableIdx, region.at_para);
    }
  }
  return tableMinPara;
}

interface SortEntry {
  op: QueuedOp;
  originalIndex: number;
}

function compareReadingOrder(
  a: SortEntry,
  b: SortEntry,
  tableMinPara: ReadonlyMap<number, number>,
): number {
  const rank = (entry: SortEntry): [number, number, number, number, number, number, number] => {
    const { op, originalIndex } = entry;
    if (op.kind === "delete_guides") {
      return [2, 0, 0, 0, 0, 0, originalIndex];
    }
    if (op.kind === "set_run") {
      if (tableMinPara.size > 0) {
        return [0, op.atPara, 1, 0, 0, op.run, originalIndex];
      }
      return [1, 0, op.atPara, 0, 0, op.run, originalIndex];
    }
    const minPara = tableMinPara.get(op.table);
    const runOrder = op.kind === "replace_at_cell" ? (op.run ?? -1) : -1;
    if (tableMinPara.size > 0 && minPara !== undefined) {
      return [0, minPara, 0, op.row, op.col, runOrder, originalIndex];
    }
    if (tableMinPara.size > 0) {
      return [1, op.table, 0, op.row, op.col, runOrder, originalIndex];
    }
    return [0, op.table, 0, op.row, op.col, runOrder, originalIndex];
  };

  const ka = rank(a);
  const kb = rank(b);
  for (let i = 0; i < ka.length; i += 1) {
    if (ka[i] !== kb[i]) return ka[i] - kb[i];
  }
  return 0;
}

export function opTargetKey(op: QueuedOp): string | null {
  if (op.kind === "fill_cell" || op.kind === "replace_at_cell") {
    return `c:${op.table}:${op.row}:${op.col}`;
  }
  if (op.kind === "set_run") {
    return `p:${op.atPara}`;
  }
  return null;
}

export function isAuditableOp(op: QueuedOp): boolean {
  if (op.kind === "replace_at_cell" || op.kind === "set_run" || op.kind === "delete_guides") {
    return true;
  }
  if (op.kind === "fill_cell") {
    return Boolean(op.overwrite) && (op.before ?? "").trim().length > 0;
  }
  return false;
}

export function buildIndexedChanges(
  draft: Draft,
  inspect: InspectResult | null,
  textMap: Record<string, RegionText>,
  language: UiLanguage,
): IndexedChange[] {
  if (draft.ops.length === 0) return [];

  const tableMinPara = collectTableAnchorParas(textMap);
  const sorted: SortEntry[] = draft.ops
    .map((op, originalIndex) => ({ op, originalIndex }))
    .sort((a, b) => compareReadingOrder(a, b, tableMinPara));

  const hardAll = draft.validation?.hard ?? [];
  const warnAll = draft.validation?.warn ?? [];

  return sorted.map(({ op, originalIndex }, idx) => {
    const ordinal = idx + 1;
    const matchTargets = new Set([`ops[${op.opId}]`, `ops[${originalIndex}]`]);
    const hardFindings = hardAll.filter((f) => matchTargets.has(f.at));
    const warnFindings = warnAll.filter((f) => matchTargets.has(f.at));

    const derived = deriveOpFieldLabel(op, inspect, textMap, language, ordinal);
    const looksLikeRawCoord = /^R\d+C\d+$/i.test(derived.trim());
    const fieldLabel =
      derived.trim().length > 0 && !looksLikeRawCoord
        ? derived
        : t("field_blank_fallback", language, [ordinal]);

    const opKindText = opKindLabel(
      op.kind,
      language,
      op.kind === "replace_at_cell" ? (op.mode ?? null) : null,
    );

    const beforeText = op.before ?? "";
    const afterText =
      op.kind === "delete_guides"
        ? opKindText
        : projectedAfterText(op);

    const inv = projectionInverseSupport(op);
    const nonInvertibleReason = !inv.invertible
      ? language === "en"
        ? "Removing form instructions cannot be undone automatically because removed paragraph formatting cannot be restored."
        : inv.reason
      : undefined;

    return {
      ordinal,
      originalIndex,
      op,
      opId: op.opId,
      fieldLabel,
      opKindText,
      beforeText,
      afterText,
      targetKey: opTargetKey(op),
      hardFindings,
      warnFindings,
      hasHardFailure: hardFindings.length > 0,
      isAuditable: isAuditableOp(op),
      isEmptyBlankFill: op.kind === "fill_cell" && beforeText.trim().length === 0,
      invertible: inv.invertible,
      nonInvertibleReason,
    };
  });
}

function buildInvalidPlanSummary(
  draft: Draft,
  changes: readonly IndexedChange[],
): ReviewGuardSummary {
  const rowAudits: Record<string, RowGuardAudit> = {};
  const needsFixesOpIds: string[] = [];

  for (const ch of changes) {
    if (ch.hasHardFailure) {
      rowAudits[ch.opId] = {
        status: "needs_fixes",
        paragraph: null,
        addedNumbers: [],
      };
      needsFixesOpIds.push(ch.opId);
    } else {
      rowAudits[ch.opId] = {
        status: "none",
        paragraph: null,
        addedNumbers: [],
      };
    }
  }

  return {
    state: "invalid_plan",
    planId: draft.plan?.planId ?? null,
    documentDiff: null,
    rowAudits,
    changedFactOpIds: [],
    needsFixesOpIds,
    errorCode: null,
  };
}

function singleLineForGuard(text: string): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > 0 ? collapsed : " ";
}

/**
 * Execute authoritative Python prose-fidelity diff via `/api/guard/diff`.
 * Never runs any TypeScript regex heuristic for pass/fail decisions.
 */
export async function runAuthoritativeGuardDiff(
  sessionId: string,
  draft: Draft,
  changes: readonly IndexedChange[],
): Promise<ReviewGuardSummary> {
  if (changes.length === 0) {
    return emptyReviewGuardSummary("idle", null);
  }

  if (draft.phase === "starting") {
    return emptyReviewGuardSummary("idle", draft.plan?.planId ?? null);
  }

  if (!draft.plan || draft.validation?.ok === false) {
    return buildInvalidPlanSummary(draft, changes);
  }

  if (draft.validation?.ok !== true) {
    return emptyReviewGuardSummary("idle", draft.plan.planId);
  }

  const planId = draft.plan.planId;
  const audited = changes.filter((c) => c.isAuditable);

  try {
    const docPromise = rt.guardDiff({ sessionId, planId });
    const rowPromise =
      audited.length > 0
        ? rt.guardDiff({
            beforeText: audited.map((c) => singleLineForGuard(c.beforeText)).join("\n"),
            afterText: audited
              .map((c) =>
                singleLineForGuard(c.op.kind === "delete_guides" ? "" : c.afterText),
              )
              .join("\n"),
          })
        : Promise.resolve<GuardDiffResult | null>(null);

    const [documentDiff, pairDiff] = await Promise.all([docPromise, rowPromise]);

    const rowAudits: Record<string, RowGuardAudit> = {};
    const changedFactOpIds: string[] = [];

    for (const ch of changes) {
      rowAudits[ch.opId] = {
        status: "none",
        paragraph: null,
        addedNumbers: [],
      };
    }

    if (pairDiff) {
      for (let i = 0; i < audited.length; i += 1) {
        const ch = audited[i];
        const para =
          pairDiff.allParagraphs[i] ??
          pairDiff.changed.find((row) => row.paragraph === i + 1) ??
          null;
        if (!para) continue;

        const status: RowGuardStatus = para.pass === false ? "changed" : "kept";
        if (status === "changed") {
          changedFactOpIds.push(ch.opId);
        }

        const seenSpans = new Set<string>();
        const addedNumbers: string[] = [];
        for (const tok of para.afterProtected ?? []) {
          if (tok.status !== "added") continue;
          if (!(tok.kind === "numbers" || /\d/.test(tok.text))) continue;
          const spanKey = `${tok.start}:${tok.end}:${tok.text}`;
          if (seenSpans.has(spanKey)) continue;
          seenSpans.add(spanKey);
          addedNumbers.push(tok.text);
        }

        rowAudits[ch.opId] = {
          status,
          paragraph: para,
          addedNumbers,
        };
      }
    }

    return {
      state: "ready",
      planId,
      documentDiff,
      rowAudits,
      changedFactOpIds,
      needsFixesOpIds: [],
      errorCode: null,
    };
  } catch (err) {
    const rtErr = rt.asRuntimeError(err);
    return {
      state: "unavailable",
      planId,
      documentDiff: null,
      rowAudits: {},
      changedFactOpIds: [],
      needsFixesOpIds: [],
      errorCode: rtErr.code || "guard_unavailable",
    };
  }
}

let currentGuardSummary: ReviewGuardSummary = emptyReviewGuardSummary("idle", null);
const guardListeners = new Set<() => void>();

export function setReviewGuardSummary(next: ReviewGuardSummary): void {
  currentGuardSummary = next;
  for (const listener of guardListeners) {
    listener();
  }
}

export function getReviewGuardSummary(): ReviewGuardSummary {
  return currentGuardSummary;
}

function subscribeReviewGuard(listener: () => void): () => void {
  guardListeners.add(listener);
  return () => {
    guardListeners.delete(listener);
  };
}

export function useReviewGuardSummary(): ReviewGuardSummary {
  return useSyncExternalStore(
    subscribeReviewGuard,
    getReviewGuardSummary,
    getReviewGuardSummary,
  );
}
