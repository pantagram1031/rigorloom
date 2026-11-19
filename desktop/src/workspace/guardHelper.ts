import { useSyncExternalStore } from "react";
import {
  projectedAfterText,
  projectionInverseSupport,
} from "../agent/planProjection";
import { SLOT_PLACEHOLDER_MARKERS } from "../i18n/formTokens.ts";
import { opKindLabel, t } from "../i18n/vocabulary";
import type { Draft, QueuedOp } from "../store";
import * as rt from "../runtime";
import type {
  GraphCell,
  GuardDiffParagraph,
  GuardDiffResult,
  InspectResult,
  PlanFinding,
  RegionText,
  UiLanguage,
} from "../types";
import {
  collapseFormGuideLabel,
  deriveOpFieldLabel,
  deriveSiblingRunFieldLabel,
  extractFormInstructionContext,
  truncateLabel,
  type FormInstructionContext,
} from "./fieldLabels";

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

export type ChangePreviewMode = "diff" | "before_only" | "after_only";

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
  previewMode: ChangePreviewMode;
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
  /** Every paragraph each op was tied to (a guide removal can span several). */
  paragraphsByOp?: Record<string, GuardDiffParagraph[]>;
  /** Failing paragraphs the checker reported that no op could be tied to. */
  unattributedFailing?: GuardDiffParagraph[];
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

function matchesSlotPlaceholder(
  compactBefore: string,
  formCtx: FormInstructionContext,
): boolean {
  if (!compactBefore) return false;
  if (SLOT_PLACEHOLDER_MARKERS.some((marker) => compactBefore.includes(marker))) {
    return true;
  }
  if (Array.from(compactBefore).length > 35) {
    return false;
  }
  for (const term of formCtx.quotedTerms) {
    if (compactBefore === term || compactBefore.includes(term)) {
      return true;
    }
  }
  return false;
}

function isShortNonDigitAnchorFill(
  beforeTrim: string,
  collapsedBefore: string,
  afterTrim: string,
  anchors: readonly string[] | undefined,
): boolean {
  if (!beforeTrim || Array.from(beforeTrim).length > 12 || /\d/.test(beforeTrim)) {
    return false;
  }
  if (!afterTrim.startsWith(`${beforeTrim} `)) {
    return false;
  }
  if (!anchors || anchors.length === 0) return false;
  return anchors.some((a) => {
    const aTrim = a.trim();
    return aTrim === beforeTrim || collapseFormGuideLabel(aTrim) === collapsedBefore;
  });
}

interface ClassificationResult {
  fieldLabel: string;
  opKindText: string;
  isAuditable: boolean;
  previewMode: ChangePreviewMode;
}

function classifyQueuedOp(
  op: QueuedOp,
  beforeText: string,
  afterText: string,
  defaultFieldLabel: string,
  defaultOpKindText: string,
  inspect: InspectResult | null,
  textMap: Record<string, RegionText>,
  cellByKey: ReadonlyMap<string, GraphCell>,
  regionCellKeys: ReadonlySet<string>,
  formCtx: FormInstructionContext,
  language: UiLanguage,
): ClassificationResult {
  const beforeTrim = beforeText.trim();
  const afterTrim = afterText.trim();

  if (op.kind === "fill_cell") {
    const isContentOverwrite = Boolean(op.overwrite) && beforeTrim.length > 0;
    if (!isContentOverwrite) {
      const collapsed = collapseFormGuideLabel(beforeText);
      return {
        fieldLabel:
          beforeTrim.length > 0 && collapsed.length > 0
            ? truncateLabel(collapsed, 20)
            : defaultFieldLabel,
        opKindText: opKindLabel("fill_cell", language),
        isAuditable: false,
        previewMode: "after_only",
      };
    }
    return {
      fieldLabel: defaultFieldLabel,
      opKindText: defaultOpKindText,
      isAuditable: true,
      previewMode: "diff",
    };
  }

  if (op.kind === "delete_guides") {
    return {
      fieldLabel: defaultFieldLabel,
      opKindText: defaultOpKindText,
      isAuditable: isAuditableOp(op),
      previewMode: "before_only",
    };
  }

  if (op.kind !== "replace_at_cell") {
    return {
      fieldLabel: defaultFieldLabel,
      opKindText: defaultOpKindText,
      isAuditable: isAuditableOp(op),
      previewMode: "diff",
    };
  }

  const key = `c:${op.table}:${op.row}:${op.col}`;
  const cell = cellByKey.get(key);
  const region = textMap[key];
  const isGuideCell = cell?.classification === "guide" || formCtx.guideCellKeys.has(key);
  const isFillTargetCell = cell?.classification === "fill_target";
  const isInstructionCell = formCtx.instructionCellKeys.has(key);
  const inRegions = regionCellKeys.has(key);

  const hasRunColorAnomaly = Boolean(
    region?.runs?.some(
      (r) => (op.run === undefined || r.index === op.run) && r.color_anomaly === true,
    ),
  );
  const hasRegionColorAnomaly = Boolean(
    inspect?.regions?.regions?.some(
      (r) =>
        r.table === op.table &&
        r.row === op.row &&
        r.col === op.col &&
        (op.run === undefined || r.run === undefined || r.run === op.run) &&
        r.colorAnomaly === true,
    ),
  );
  const hasColorAnomaly =
    Boolean(cell?.colorAnomaly) || hasRunColorAnomaly || hasRegionColorAnomaly;

  const collapsedBefore = collapseFormGuideLabel(beforeText);
  const compactBefore = collapsedBefore.replace(/\s+/g, "");

  // 1. Clearing operations (`afterText` empty while `beforeText` is non-empty).
  if (afterTrim === "" && beforeTrim.length > 0) {
    const hasLettersOrDigits = /[\p{L}\p{N}]/u.test(beforeTrim);
    if (!hasLettersOrDigits) {
      return {
        fieldLabel: deriveSiblingRunFieldLabel(
          op.table,
          op.row,
          op.col,
          op.run,
          beforeText,
          textMap,
          20,
        ),
        opKindText: t("op_clear_symbol", language),
        isAuditable: !(isGuideCell || isInstructionCell),
        previewMode: "before_only",
      };
    }

    if (
      isGuideCell ||
      hasColorAnomaly ||
      isInstructionCell ||
      matchesSlotPlaceholder(compactBefore, formCtx)
    ) {
      return {
        fieldLabel:
          collapsedBefore.length > 0
            ? truncateLabel(collapsedBefore, 20)
            : defaultFieldLabel,
        opKindText: opKindLabel("delete_guides", language),
        isAuditable: false,
        previewMode: "before_only",
      };
    }

    return {
      fieldLabel: defaultFieldLabel,
      opKindText: defaultOpKindText,
      isAuditable: true,
      previewMode: "diff",
    };
  }

  // 2. Guide-text / form-slot blank-fill operations (`afterText` non-empty).
  if (afterTrim.length > 0) {
    const hasSlotBlankParens = /\(\s{2,}\)|\[\s{2,}\]/.test(beforeText);
    const isShortAnchorPrefix =
      formCtx.isFormDocument &&
      isShortNonDigitAnchorFill(
        beforeTrim,
        collapsedBefore,
        afterTrim,
        inspect?.summary?.anchors,
      );

    if (
      isGuideCell ||
      isFillTargetCell ||
      inRegions ||
      hasColorAnomaly ||
      matchesSlotPlaceholder(compactBefore, formCtx) ||
      hasSlotBlankParens ||
      isShortAnchorPrefix
    ) {
      return {
        fieldLabel:
          beforeTrim.length > 0 && collapsedBefore.length > 0
            ? truncateLabel(collapsedBefore, 20)
            : defaultFieldLabel,
        opKindText: opKindLabel("fill_cell", language),
        isAuditable: false,
        previewMode: "after_only",
      };
    }
  }

  // 3. Genuine content cell edits stay auditable.
  return {
    fieldLabel: defaultFieldLabel,
    opKindText: defaultOpKindText,
    isAuditable: true,
    previewMode: "diff",
  };
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

  const formCtx = extractFormInstructionContext(inspect, textMap);
  const cellByKey = new Map<string, GraphCell>();
  for (const tbl of inspect?.graph.tables ?? []) {
    for (const cell of tbl.cells) {
      cellByKey.set(`c:${tbl.index}:${cell.addr.row}:${cell.addr.col}`, cell);
    }
  }
  const regionCellKeys = new Set<string>();
  for (const reg of inspect?.regions?.regions ?? []) {
    if (reg.table !== undefined && reg.row !== undefined && reg.col !== undefined) {
      regionCellKeys.add(`c:${reg.table}:${reg.row}:${reg.col}`);
    }
  }

  return sorted.map(({ op, originalIndex }, idx) => {
    const ordinal = idx + 1;
    const matchTargets = new Set([`ops[${op.opId}]`, `ops[${originalIndex}]`]);
    const hardFindings = hardAll.filter((f) => matchTargets.has(f.at));
    const warnFindings = warnAll.filter((f) => matchTargets.has(f.at));

    const derived = deriveOpFieldLabel(op, inspect, textMap, language, ordinal);
    const looksLikeRawCoord = /^R\d+C\d+$/i.test(derived.trim());
    const defaultFieldLabel =
      derived.trim().length > 0 && !looksLikeRawCoord
        ? derived
        : t("field_blank_fallback", language, [ordinal]);

    const defaultOpKindText = opKindLabel(
      op.kind,
      language,
      op.kind === "replace_at_cell" ? (op.mode ?? null) : null,
    );

    const deleteBeforeFallback =
      op.kind === "delete_guides" &&
      !(op.before ?? "").trim() &&
      inspect?.summary?.removalTargets?.length
        ? inspect.summary.removalTargets
            .map(
              (rt) =>
                inspect.graph.paragraphs
                  .find((p) => p.para_idx === rt.para_idx)
                  ?.text?.trim() ?? "",
            )
            .filter(Boolean)
            .slice(0, 3)
            .join(" / ")
        : "";
    const beforeText = (op.before ?? "") || deleteBeforeFallback;
    const afterText =
      op.kind === "delete_guides" ? "" : projectedAfterText(op);

    const classification = classifyQueuedOp(
      op,
      beforeText,
      afterText,
      defaultFieldLabel,
      defaultOpKindText,
      inspect,
      textMap,
      cellByKey,
      regionCellKeys,
      formCtx,
      language,
    );

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
      fieldLabel: classification.fieldLabel,
      opKindText: classification.opKindText,
      beforeText,
      afterText,
      targetKey: opTargetKey(op),
      hardFindings,
      warnFindings,
      hasHardFailure: hardFindings.length > 0,
      isAuditable: classification.isAuditable,
      isEmptyBlankFill: op.kind === "fill_cell" && beforeText.trim().length === 0,
      previewMode: classification.previewMode,
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

export function extractAddedNumbers(para: GuardDiffParagraph | null): string[] {
  if (!para) return [];
  const seenText = new Set<string>();
  const addedNumbers: string[] = [];
  for (const tok of para.afterProtected ?? []) {
    if (tok.status !== "added" || tok.kind !== "numbers") continue;
    if (seenText.has(tok.text)) continue;
    seenText.add(tok.text);
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

/** The non-blank lines of a fill that writes more than one line, normalized. */
function multiLineFillLines(op: QueuedOp): string[] {
  if (op.kind !== "fill_cell") return [];
  const raw = op.lines !== undefined ? op.lines : (op.text ?? "").split("\n");
  if (raw.length < 2) return [];
  return raw.map(normalizeForMatch).filter((line) => line.length > 0);
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
  if (beforeOverlap && opAfter.length === 0 && pAfter.length === 0) return 2;
  if (afterExact || (opText.length >= 2 && afterContainsOpText)) return 3;
  if (
    beforeOverlap &&
    opAfter.length === 0 &&
    opBefore.length >= 2 &&
    pBefore !== pAfter &&
    !pAfter.includes(opBefore)
  ) {
    return 3;
  }
  if (
    opAfter.length >= 2 &&
    pAfter.length >= 2 &&
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

export type GuardDiffInvoker = (req: {
  sessionId: string;
  planId: string;
}) => Promise<GuardDiffResult>;

/**
 * Execute authoritative Python prose-fidelity diff via `/api/guard/diff`.
 * Never calls `/api/guard/diff` on TS-projected text or runs JS pass/fail regexes.
 */
export async function runAuthoritativeGuardDiff(
  sessionId: string,
  draft: Draft,
  changes: readonly IndexedChange[],
  guardDiffFn: GuardDiffInvoker = rt.guardDiff,
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
    const documentDiff = await guardDiffFn({ sessionId, planId });

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

    // Match ALL non-delete changes (both auditable and non-auditable) against
    // `changedParas` so raw guard paragraphs stay available for every row's
    // detail disclosure and non-auditable rows claim their own paragraphs.
    const nonDeleteChanges = changes.filter(
      (c) => c.op.kind !== "delete_guides",
    );

    for (const ch of nonDeleteChanges) {
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

      if (bestPara && bestTier <= 2) {
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
          continue;
        }
      }

      if (bestPara) {
        claimedChangedNums.add(bestPara.paragraph);
        if (ch.targetKey && !targetSharedPara.has(ch.targetKey)) {
          targetSharedPara.set(ch.targetKey, bestPara);
        }
        matchedParaByOp.set(ch.opId, bestPara);
        attributedParaNums.set(ch.opId, [bestPara.paragraph]);
      }
    }

    // A multi-line fill into a blank writes one paragraph per line, and the
    // checker reports each of them. The loop above ties one; the others are
    // that same change's typing, not differences nobody can account for. They
    // are tied to the fill only when the paragraph was blank, its text is one
    // of the fill's lines (each line once), and it sits within the fill's
    // own run of paragraphs. A fill over existing text stays with the
    // ordinary matching, so a fact it changes is still reported.
    for (const ch of nonDeleteChanges) {
      if (ch.isAuditable) continue;
      const lines = multiLineFillLines(ch.op);
      if (lines.length < 2) continue;
      const remaining = new Map<string, number>();
      for (const line of lines) remaining.set(line, (remaining.get(line) ?? 0) + 1);
      const take = (text: string): boolean => {
        const left = remaining.get(text) ?? 0;
        if (left <= 0) return false;
        remaining.set(text, left - 1);
        return true;
      };
      const fromBlank = (p: GuardDiffParagraph) =>
        normalizeForMatch(p.before).length === 0 && normalizeForMatch(p.after).length > 0;
      let anchor = matchedParaByOp.get(ch.opId) ?? null;
      if (anchor && !(fromBlank(anchor) && take(normalizeForMatch(anchor.after)))) {
        // The tied paragraph is not one of the lines; leave the rest alone.
        continue;
      }
      if (!anchor) {
        anchor =
          changedParas.find(
            (p) => !claimedChangedNums.has(p.paragraph) && fromBlank(p) && remaining.has(normalizeForMatch(p.after)),
          ) ?? null;
        if (!anchor) continue;
        take(normalizeForMatch(anchor.after));
        claimedChangedNums.add(anchor.paragraph);
        matchedParaByOp.set(ch.opId, anchor);
        if (ch.targetKey && !targetSharedPara.has(ch.targetKey)) targetSharedPara.set(ch.targetKey, anchor);
      }
      const span = ((ch.op.kind === "fill_cell" && ch.op.lines?.length) || lines.length) + 1;
      const tied = [anchor.paragraph];
      for (const para of changedParas) {
        if (claimedChangedNums.has(para.paragraph)) continue;
        if (Math.abs(para.paragraph - anchor.paragraph) > span) continue;
        if (!fromBlank(para) || !take(normalizeForMatch(para.after))) continue;
        claimedChangedNums.add(para.paragraph);
        tied.push(para.paragraph);
      }
      attributedParaNums.set(ch.opId, tied);
    }

    for (const ch of nonDeleteChanges) {
      if (matchedParaByOp.has(ch.opId)) continue;
      const opText = normalizeForMatch(opTargetText(ch.op));
      const opAfter = normalizeForMatch(ch.afterText);
      const opBefore = normalizeForMatch(ch.beforeText);
      if (opText.length === 0 && opAfter.length === 0 && opBefore.length === 0) continue;

      const remainingEdited = changedParas.filter(
        (p) =>
          !claimedChangedNums.has(p.paragraph) &&
          (normalizeForMatch(p.after).length > 0 ||
            normalizeForMatch(p.before).length > 0),
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
    const targetSharedEqualPara = new Map<string, GuardDiffParagraph>();
    const nonAuditableParaNums = new Set<number>();

    for (const ch of changes) {
      const matched = matchedParaByOp.get(ch.opId) ?? null;

      let resolvedPara: GuardDiffParagraph | null = matched;
      if (!resolvedPara) {
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
          if (ch.targetKey && !targetSharedEqualPara.has(ch.targetKey)) {
            targetSharedEqualPara.set(ch.targetKey, equalPara);
          }
          resolvedPara = equalPara;
        } else if (ch.targetKey) {
          resolvedPara = targetSharedEqualPara.get(ch.targetKey) ?? null;
        }
      }

      if (!ch.isAuditable) {
        if (resolvedPara) {
          nonAuditableParaNums.add(resolvedPara.paragraph);
        }
        for (const extra of attributedParaNums.get(ch.opId) ?? []) {
          nonAuditableParaNums.add(extra);
        }
        rowAudits[ch.opId] = {
          status: "none",
          paragraph: resolvedPara,
          addedNumbers: [],
        };
        continue;
      }

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

      rowAudits[ch.opId] = {
        status: "kept",
        paragraph: resolvedPara,
        addedNumbers: extractAddedNumbers(resolvedPara),
      };
    }

    if (documentDiff.pass === false && audited.length > 0) {
      const failingParas = changedParas.filter((p) => p.pass === false);
      const coveredParaNums = new Set<number>(nonAuditableParaNums);
      for (const opId of changedSet) {
        const paraNum = rowAudits[opId]?.paragraph?.paragraph;
        if (typeof paraNum === "number") coveredParaNums.add(paraNum);
        for (const extra of attributedParaNums.get(opId) ?? []) {
          coveredParaNums.add(extra);
        }
      }

      for (const failPara of failingParas) {
        if (coveredParaNums.has(failPara.paragraph)) continue;
        const targetRow = audited.find(
          (c) => !changedSet.has(c.opId) && hasTextContainment(c, failPara),
        );
        if (!targetRow) continue;
        changedSet.add(targetRow.opId);
        coveredParaNums.add(failPara.paragraph);
        rowAudits[targetRow.opId] = {
          status: "changed",
          paragraph: failPara,
          addedNumbers: extractAddedNumbers(failPara),
        };
      }
    }

    const changedFactOpIds = changes
      .filter((c) => rowAudits[c.opId]?.status === "changed")
      .map((c) => c.opId);

    // The full answer, not just one paragraph per row: every paragraph an op
    // was tied to, and every failing paragraph nothing was tied to. The sheet
    // computes its acknowledgements from these (trust.requiredGuardAcks).
    const byNum = new Map<number, GuardDiffParagraph>();
    for (const para of [...allParas, ...changedParas]) byNum.set(para.paragraph, para);
    const paragraphsByOp: Record<string, GuardDiffParagraph[]> = {};
    const attributed = new Set<number>(nonAuditableParaNums);
    for (const ch of changes) {
      const nums = new Set<number>(attributedParaNums.get(ch.opId) ?? []);
      const own = rowAudits[ch.opId]?.paragraph?.paragraph;
      if (typeof own === "number") nums.add(own);
      const paras = [...nums]
        .map((n) => byNum.get(n))
        .filter((para): para is GuardDiffParagraph => Boolean(para));
      if (paras.length > 0) paragraphsByOp[ch.opId] = paras;
      for (const n of nums) attributed.add(n);
    }
    const unattributedFailing = changedParas.filter(
      (p) => p.pass === false && !attributed.has(p.paragraph),
    );

    return {
      state: "ready",
      planId,
      documentDiff,
      rowAudits,
      changedFactOpIds,
      needsFixesOpIds: [],
      errorCode: null,
      paragraphsByOp,
      unattributedFailing,
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
let currentGuardKey: string | null = null;
const guardListeners = new Set<() => void>();

export function setReviewGuardSummary(
  next: ReviewGuardSummary,
  key: string | null = null,
): void {
  currentGuardSummary = next;
  currentGuardKey = key;
  for (const listener of guardListeners) {
    listener();
  }
}

export function getReviewGuardSummary(): ReviewGuardSummary {
  return currentGuardSummary;
}

export function getReviewGuardKey(): string | null {
  return currentGuardKey;
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
