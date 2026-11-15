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

export type RowGuardStatus =
  | "none"
  | "needs_fixes"
  | "not_checked"
  | "kept"
  | "changed";

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
      ? op.kind === "delete_guides"
        ? t("delete_guides_noninvertible", language)
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
    } else if (ch.isAuditable) {
      rowAudits[ch.opId] = {
        status: "not_checked",
        paragraph: null,
        addedNumbers: [],
      };
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

function normalizeForMatch(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function extractAddedNumbers(para: GuardDiffParagraph | null): string[] {
  if (!para) return [];
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
  return addedNumbers;
}

function opTargetText(op: QueuedOp): string {
  if (op.kind === "fill_cell") {
    if (op.lines !== undefined) return op.lines.join("\n");
    return op.text ?? "";
  }
  if (op.kind === "replace_at_cell" || op.kind === "set_run") {
    return op.text;
  }
  return "";
}

function matchParagraphTier(ch: IndexedChange, para: GuardDiffParagraph): number {
  const opBefore = normalizeForMatch(ch.beforeText);
  const opAfter = normalizeForMatch(ch.afterText);
  const opText = normalizeForMatch(opTargetText(ch.op));
  const pBefore = normalizeForMatch(para.before);
  const pAfter = normalizeForMatch(para.after);

  const beforeExact = opBefore.length > 0 && pBefore === opBefore;
  const beforeOverlap =
    opBefore.length > 0 &&
    pBefore.length > 0 &&
    (pBefore === opBefore ||
      pBefore.includes(opBefore) ||
      opBefore.includes(pBefore));

  const afterExact = opAfter.length > 0 && pAfter === opAfter;
  const afterContainsOpText =
    opText.length > 0 && pAfter.length > 0 && pAfter.includes(opText);
  const afterOverlap =
    (opAfter.length > 0 &&
      pAfter.length > 0 &&
      (pAfter === opAfter ||
        pAfter.includes(opAfter) ||
        opAfter.includes(pAfter))) ||
    afterContainsOpText;

  if (beforeExact && (afterExact || afterOverlap)) return 1;
  if (beforeOverlap && afterOverlap) return 2;
  if (afterExact || (opText.length >= 2 && afterContainsOpText)) return 3;
  if (
    opAfter.length >= 2 &&
    (pAfter.includes(opAfter) || opAfter.includes(pAfter))
  ) {
    return 4;
  }
  if (beforeExact && pBefore !== pAfter) return 5;
  return 0;
}

function hasTextContainment(ch: IndexedChange, para: GuardDiffParagraph): boolean {
  const opBefore = normalizeForMatch(ch.beforeText);
  const opAfter = normalizeForMatch(ch.afterText);
  const opText = normalizeForMatch(opTargetText(ch.op));
  const pBefore = normalizeForMatch(para.before);
  const pAfter = normalizeForMatch(para.after);

  if (
    opBefore.length > 0 &&
    pBefore.length > 0 &&
    (pBefore.includes(opBefore) || opBefore.includes(pBefore))
  ) {
    return true;
  }
  if (
    opAfter.length > 0 &&
    pAfter.length > 0 &&
    (pAfter.includes(opAfter) || opAfter.includes(pAfter))
  ) {
    return true;
  }
  if (opText.length > 0 && pAfter.length > 0 && pAfter.includes(opText)) {
    return true;
  }
  return false;
}

/**
 * Execute authoritative Python prose-fidelity diff via `/api/guard/diff`.
 * Never calls `/api/guard/diff` on TS-projected text or runs JS pass/fail regexes.
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
    const documentDiff = await rt.guardDiff({ sessionId, planId });

    const rowAudits: Record<string, RowGuardAudit> = {};
    for (const ch of changes) {
      rowAudits[ch.opId] = {
        status: ch.isAuditable ? "kept" : "none",
        paragraph: null,
        addedNumbers: [],
      };
    }

    const changedParas = documentDiff.changed ?? [];
    const allParas = documentDiff.allParagraphs ?? [];
    const claimedChangedNums = new Set<number>();
    const targetSharedPara = new Map<string, GuardDiffParagraph>();
    const matchedParaByOp = new Map<string, GuardDiffParagraph>();
    const attributedParaNums = new Map<string, number[]>();

    const nonDeleteAudited = audited.filter(
      (c) => c.op.kind !== "delete_guides",
    );

    for (const ch of nonDeleteAudited) {
      let bestPara: GuardDiffParagraph | null = null;
      let bestTier = 99;
      for (const para of changedParas) {
        if (claimedChangedNums.has(para.paragraph)) continue;
        const tier = matchParagraphTier(ch, para);
        if (tier > 0 && tier < bestTier) {
          bestTier = tier;
          bestPara = para;
          if (tier === 1) break;
        }
      }

      if (bestPara) {
        claimedChangedNums.add(bestPara.paragraph);
        if (ch.targetKey && !targetSharedPara.has(ch.targetKey)) {
          targetSharedPara.set(ch.targetKey, bestPara);
        }
        matchedParaByOp.set(ch.opId, bestPara);
        attributedParaNums.set(ch.opId, [bestPara.paragraph]);
        continue;
      }

      if (ch.targetKey) {
        const shared = targetSharedPara.get(ch.targetKey);
        if (shared) {
          matchedParaByOp.set(ch.opId, shared);
          attributedParaNums.set(ch.opId, [shared.paragraph]);
        }
      }
    }

    for (const ch of nonDeleteAudited) {
      if (matchedParaByOp.has(ch.opId)) continue;
      const opText = normalizeForMatch(opTargetText(ch.op));
      const opAfter = normalizeForMatch(ch.afterText);
      if (opText.length === 0 && opAfter.length === 0) continue;

      const remainingEdited = changedParas.filter(
        (p) =>
          !claimedChangedNums.has(p.paragraph) &&
          normalizeForMatch(p.after).length > 0,
      );
      if (
        remainingEdited.length === 1 &&
        hasTextContainment(ch, remainingEdited[0])
      ) {
        const lone = remainingEdited[0];
        claimedChangedNums.add(lone.paragraph);
        if (ch.targetKey && !targetSharedPara.has(ch.targetKey)) {
          targetSharedPara.set(ch.targetKey, lone);
        }
        matchedParaByOp.set(ch.opId, lone);
        attributedParaNums.set(ch.opId, [lone.paragraph]);
      }
    }

    const deleteAudited = audited.filter((c) => c.op.kind === "delete_guides");
    if (deleteAudited.length > 0) {
      const shortened = changedParas.filter(
        (p) =>
          !claimedChangedNums.has(p.paragraph) &&
          (normalizeForMatch(p.after).length < normalizeForMatch(p.before).length ||
            p.before.length > p.after.length),
      );
      if (shortened.length > 0) {
        if (deleteAudited.length === 1) {
          const picked = shortened.find((p) => p.pass === false) ?? shortened[0];
          matchedParaByOp.set(deleteAudited[0].opId, picked);
          attributedParaNums.set(
            deleteAudited[0].opId,
            shortened.map((p) => p.paragraph),
          );
          for (const p of shortened) {
            claimedChangedNums.add(p.paragraph);
          }
        } else {
          for (let i = 0; i < deleteAudited.length; i += 1) {
            const picked = shortened[i] ?? shortened[shortened.length - 1];
            matchedParaByOp.set(deleteAudited[i].opId, picked);
            attributedParaNums.set(deleteAudited[i].opId, [picked.paragraph]);
            claimedChangedNums.add(picked.paragraph);
          }
        }
      }
    }

    const changedSet = new Set<string>();
    const claimedEqualNums = new Set<number>();

    for (const ch of audited) {
      const matched = matchedParaByOp.get(ch.opId) ?? null;
      if (matched) {
        const status: RowGuardStatus =
          matched.pass === false ? "changed" : "kept";
        if (status === "changed") {
          changedSet.add(ch.opId);
        }
        rowAudits[ch.opId] = {
          status,
          paragraph: matched,
          addedNumbers: extractAddedNumbers(matched),
        };
        continue;
      }

      const opAfter = normalizeForMatch(ch.afterText);
      const opBefore = normalizeForMatch(ch.beforeText);
      const equalPara =
        allParas.find((p) => {
          if (
            claimedChangedNums.has(p.paragraph) ||
            claimedEqualNums.has(p.paragraph)
          ) {
            return false;
          }
          const pb = normalizeForMatch(p.before);
          const pa = normalizeForMatch(p.after);
          return (
            (opAfter.length > 0 && (pa === opAfter || pa.includes(opAfter))) ||
            (opBefore.length > 0 && pb === opBefore && pa === opBefore)
          );
        }) ?? null;

      if (equalPara) {
        claimedEqualNums.add(equalPara.paragraph);
      }
      rowAudits[ch.opId] = {
        status: "kept",
        paragraph: equalPara,
        addedNumbers: extractAddedNumbers(equalPara),
      };
    }

    if (documentDiff.pass === false && audited.length > 0) {
      const failingParas = changedParas.filter((p) => p.pass === false);
      const coveredParaNums = new Set<number>();
      for (const opId of changedSet) {
        const paraNum = rowAudits[opId]?.paragraph?.paragraph;
        if (typeof paraNum === "number") coveredParaNums.add(paraNum);
        for (const extra of attributedParaNums.get(opId) ?? []) {
          coveredParaNums.add(extra);
        }
      }

      for (const failPara of failingParas) {
        if (coveredParaNums.has(failPara.paragraph)) continue;
        const targetRow =
          audited.find(
            (c) => !changedSet.has(c.opId) && hasTextContainment(c, failPara),
          ) ??
          audited.find((c) => !changedSet.has(c.opId)) ??
          audited[0];
        changedSet.add(targetRow.opId);
        coveredParaNums.add(failPara.paragraph);
        rowAudits[targetRow.opId] = {
          status: "changed",
          paragraph: failPara,
          addedNumbers: extractAddedNumbers(failPara),
        };
      }

      if (changedSet.size === 0) {
        const fallbackRow = audited[0];
        const fallbackPara =
          failingParas[0] ??
          changedParas[0] ??
          rowAudits[fallbackRow.opId]?.paragraph ??
          null;
        changedSet.add(fallbackRow.opId);
        rowAudits[fallbackRow.opId] = {
          status: "changed",
          paragraph: fallbackPara,
          addedNumbers: extractAddedNumbers(fallbackPara),
        };
      }
    }

    const changedFactOpIds = changes
      .filter((c) => changedSet.has(c.opId))
      .map((c) => c.opId);

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
