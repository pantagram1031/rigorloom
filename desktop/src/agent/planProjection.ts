/**
 * Authoritative multi-op projection between Runtime `OperationPlan` ops and the
 * shell's editable review queue (`QueuedOp`).
 *
 * Fail-closed guarantee: unknown op kinds (`goto_text`, `normalize_clones`,
 * `replace_all`, etc.) and unsupported or malformed fields are rejected
 * atomically with `agent_plan_projection_unsupported` rather than silently
 * dropped or coerced into another shape. Every supported preedit op kind
 * (`fill_cell`, `replace_at_cell`, `set_run`, `delete_guides`) round-trips
 * faithfully through `rebuildPlanOpFromProjection`.
 */

import { opKindLabel, t, type VocabularyKey } from "../i18n/vocabulary.ts";
import type { UiLanguage } from "../types.ts";

export interface ProjectablePlanOp {
  opId: string;
  kind: string;
  params: Record<string, unknown>;
}

export interface ProjectableAgentPlan {
  proposer: string;
  ops: ProjectablePlanOp[];
}

export interface ProjectedAgentFillOp {
  opId: string;
  kind: "fill_cell";
  table: number;
  row: number;
  col: number;
  text: string;
  lines?: string[];
  charPr?: string;
  paraPr?: string;
  overwrite?: boolean;
  before: string;
  origin: "agent";
  proposer: string;
}

export interface ProjectedAgentReplaceAtCellOp {
  opId: string;
  kind: "replace_at_cell";
  table: number;
  row: number;
  col: number;
  run?: number;
  text: string;
  mode?: "replace" | "append";
  expect?: string;
  charPr?: string;
  before: string;
  origin: "agent";
  proposer: string;
}

export interface ProjectedAgentSetRunOp {
  opId: string;
  kind: "set_run";
  atPara: number;
  run: number;
  text: string;
  before: string;
  origin: "agent";
  proposer: string;
}

export interface ProjectedAgentDeleteGuidesOp {
  opId: string;
  kind: "delete_guides";
  color?: string;
  charPrIds?: string[];
  text: string;
  before: string;
  origin: "agent";
  proposer: string;
}

export type ProjectedAgentOp =
  | ProjectedAgentFillOp
  | ProjectedAgentReplaceAtCellOp
  | ProjectedAgentSetRunOp
  | ProjectedAgentDeleteGuidesOp;

export interface PlanProjectionContext {
  beforeCellRun?: (table: number, row: number, col: number, run: number) => string;
  beforeParaRun?: (atPara: number, run: number) => string;
  guideSummary?: (color?: string, charPrIds?: string[]) => string;
}

export interface AgentPlanProjectionRefusal {
  code: "agent_plan_projection_unsupported";
  message: string;
  data: {
    opId: string;
    kind: string;
    unsupportedFields?: string[];
    invalidFields?: string[];
  };
}

const SUPPORTED_OP_FIELDS: Record<string, Set<string>> = {
  fill_cell: new Set(["table", "row", "col", "text", "lines", "charPr", "paraPr", "overwrite"]),
  replace_at_cell: new Set(["table", "row", "col", "run", "text", "mode", "expect", "charPr"]),
  set_run: new Set(["atPara", "run", "text"]),
  delete_guides: new Set(["color", "charPrIds"]),
};

const KNOWN_UNIMPLEMENTED_REASONS: Record<string, VocabularyKey> = {
  normalize_clones: "proj_unimpl_normalize_clones",
  goto_text: "proj_unimpl_goto_text",
};

function refusal(
  op: ProjectablePlanOp,
  reason: string,
  details: Partial<AgentPlanProjectionRefusal["data"]> = {},
  lang: UiLanguage = "ko",
): AgentPlanProjectionRefusal {
  return {
    code: "agent_plan_projection_unsupported",
    message: t("proj_refuse_op_unrepresentable", lang, [op.opId, op.kind, reason]),
    data: { opId: op.opId, kind: op.kind, ...details },
  };
}

function isAddress(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function checkAllowedFields(
  op: ProjectablePlanOp,
  allowed: Set<string>,
  lang: UiLanguage = "ko",
): void {
  const unsupportedFields = Object.keys(op.params).filter((field) => !allowed.has(field));
  if (unsupportedFields.length > 0) {
    throw refusal(op, t("proj_refuse_partial_unrepresentable", lang), {
      unsupportedFields: unsupportedFields.sort(),
    }, lang);
  }
}

/**
 * Validate every op in a plan atomically before any projection or read happens,
 * so an invalid later op never triggers reads or produces a partial queue.
 */
function validateProjectableAgentPlan(
  plan: ProjectableAgentPlan,
  lang: UiLanguage = "ko",
): void {
  for (const op of plan.ops) {
    const allowed = SUPPORTED_OP_FIELDS[op.kind];
    if (!allowed) {
      const reasonKey = KNOWN_UNIMPLEMENTED_REASONS[op.kind];
      const reason = reasonKey
        ? t(reasonKey, lang)
        : t("proj_refuse_kind_unsupported", lang, [op.kind]);
      throw refusal(op, reason, {}, lang);
    }

    if (!op.params || typeof op.params !== "object" || Array.isArray(op.params)) {
      throw refusal(op, t("proj_refuse_invalid_params", lang), {
        invalidFields: ["params"],
      }, lang);
    }

    checkAllowedFields(op, allowed, lang);
    const invalidFields: string[] = [];

    if (op.kind === "fill_cell") {
      if (op.params.table !== undefined && !isAddress(op.params.table)) {
        invalidFields.push("table");
      }
      if (!isAddress(op.params.row)) invalidFields.push("row");
      if (!isAddress(op.params.col)) invalidFields.push("col");

      const hasTextProp = op.params.text !== undefined;
      const hasLinesProp = op.params.lines !== undefined;
      const validText = typeof op.params.text === "string";
      const validLines = isStringArray(op.params.lines);

      if (hasTextProp && !validText) invalidFields.push("text");
      if (hasLinesProp && !validLines) invalidFields.push("lines");
      if (validText === validLines) {
        if (!hasTextProp && !hasLinesProp) invalidFields.push("text");
        if (validText && validLines) {
          invalidFields.push("text", "lines");
        }
      }
      if (op.params.charPr !== undefined && typeof op.params.charPr !== "string") {
        invalidFields.push("charPr");
      }
      if (op.params.paraPr !== undefined && typeof op.params.paraPr !== "string") {
        invalidFields.push("paraPr");
      }
      if (op.params.overwrite !== undefined && typeof op.params.overwrite !== "boolean") {
        invalidFields.push("overwrite");
      }
    } else if (op.kind === "replace_at_cell") {
      if (op.params.table !== undefined && !isAddress(op.params.table)) {
        invalidFields.push("table");
      }
      if (!isAddress(op.params.row)) invalidFields.push("row");
      if (!isAddress(op.params.col)) invalidFields.push("col");
      if (op.params.run !== undefined && !isAddress(op.params.run)) {
        invalidFields.push("run");
      }
      if (typeof op.params.text !== "string") invalidFields.push("text");
      if (
        op.params.mode !== undefined &&
        op.params.mode !== "replace" &&
        op.params.mode !== "append"
      ) {
        invalidFields.push("mode");
      }
      if (op.params.expect !== undefined && typeof op.params.expect !== "string") {
        invalidFields.push("expect");
      }
      if (op.params.charPr !== undefined && typeof op.params.charPr !== "string") {
        invalidFields.push("charPr");
      }
    } else if (op.kind === "set_run") {
      if (!isAddress(op.params.atPara)) invalidFields.push("atPara");
      if (!isAddress(op.params.run)) invalidFields.push("run");
      if (typeof op.params.text !== "string") invalidFields.push("text");
    } else if (op.kind === "delete_guides") {
      const hasColor = typeof op.params.color === "string" && op.params.color.trim().length > 0;
      const validCharPrIds =
        op.params.charPrIds === undefined ||
        (isStringArray(op.params.charPrIds) && op.params.charPrIds.length > 0);
      const hasCharPrIds =
        Array.isArray(op.params.charPrIds) &&
        op.params.charPrIds.length > 0 &&
        isStringArray(op.params.charPrIds);

      if (op.params.color !== undefined && !hasColor) {
        invalidFields.push("color");
      }
      if (op.params.charPrIds !== undefined && !validCharPrIds) {
        invalidFields.push("charPrIds");
      }
      if (!hasColor && !hasCharPrIds && invalidFields.length === 0) {
        invalidFields.push("color", "charPrIds");
      }
    }

    if (invalidFields.length > 0) {
      throw refusal(op, t("proj_refuse_invalid_fields", lang), {
        invalidFields: [...new Set(invalidFields)],
      }, lang);
    }
  }
}

export interface ProjectedCellAddress {
  table: number;
  row: number;
  col: number;
}

export interface ProjectedReadAddress {
  table?: number;
  row?: number;
  col?: number;
  atPara?: number;
}

/** Cell addresses to read from the exact document version the plan is bound to. */
export function agentPlanCellAddresses(plan: ProjectableAgentPlan): ProjectedCellAddress[] {
  validateProjectableAgentPlan(plan);
  const out: ProjectedCellAddress[] = [];
  for (const op of plan.ops) {
    if (op.kind !== "fill_cell" && op.kind !== "replace_at_cell") continue;
    out.push({
      table: (op.params.table as number | undefined) ?? 0,
      row: op.params.row as number,
      col: op.params.col as number,
    });
  }
  return out;
}

/** All document regions (cells + paragraphs) needed to display honest before values. */
export function agentPlanReadAddresses(plan: ProjectableAgentPlan): ProjectedReadAddress[] {
  validateProjectableAgentPlan(plan);
  const seen = new Set<string>();
  const out: ProjectedReadAddress[] = [];
  for (const op of plan.ops) {
    if (op.kind === "fill_cell" || op.kind === "replace_at_cell") {
      const addr = {
        table: (op.params.table as number | undefined) ?? 0,
        row: op.params.row as number,
        col: op.params.col as number,
      };
      const key = `c:${addr.table}:${addr.row}:${addr.col}`;
      if (!seen.has(key)) {
        seen.add(key);
        out.push(addr);
      }
    } else if (op.kind === "set_run") {
      const addr = { atPara: op.params.atPara as number };
      const key = `p:${addr.atPara}`;
      if (!seen.has(key)) {
        seen.add(key);
        out.push(addr);
      }
    }
  }
  return out;
}

function attachTableExplicit(target: ProjectedAgentOp, explicit: boolean): void {
  Object.defineProperty(target, "_tableExplicit", {
    value: explicit,
    enumerable: false,
    configurable: true,
  });
}

function defaultGuideSummary(
  color?: string,
  charPrIds?: string[],
  lang: UiLanguage = "ko",
): string {
  const parts: string[] = [];
  if (color) parts.push(t("proj_guide_color_prefix", lang, [color]));
  if (charPrIds && charPrIds.length > 0) {
    parts.push(t("proj_guide_charpr_prefix", lang, [charPrIds.join(", ")]));
  }
  return parts.length > 0
    ? t("proj_guide_target_with_parts", lang, [parts.join(" · ")])
    : t("proj_guide_target_default", lang);
}

export function projectAgentPlan(
  plan: ProjectableAgentPlan,
  beforeCell: (table: number, row: number, col: number, run?: number) => string,
  context: PlanProjectionContext = {},
  lang: UiLanguage = "ko",
): ProjectedAgentOp[] {
  validateProjectableAgentPlan(plan, lang);

  return plan.ops.map((op) => {
    if (op.kind === "fill_cell") {
      const explicitTable = op.params.table !== undefined;
      const table = (op.params.table as number | undefined) ?? 0;
      const row = op.params.row as number;
      const col = op.params.col as number;
      const lines = isStringArray(op.params.lines) ? [...op.params.lines] : undefined;
      const text = lines !== undefined ? lines.join("\n") : (op.params.text as string);
      const projected: ProjectedAgentFillOp = {
        opId: op.opId,
        kind: "fill_cell",
        table,
        row,
        col,
        text,
        ...(lines === undefined ? {} : { lines }),
        ...(op.params.charPr === undefined ? {} : { charPr: op.params.charPr as string }),
        ...(op.params.paraPr === undefined ? {} : { paraPr: op.params.paraPr as string }),
        ...(op.params.overwrite === undefined ? {} : { overwrite: op.params.overwrite as boolean }),
        before: beforeCell(table, row, col),
        origin: "agent",
        proposer: plan.proposer,
      };
      attachTableExplicit(projected, explicitTable);
      return projected;
    }

    if (op.kind === "replace_at_cell") {
      const explicitTable = op.params.table !== undefined;
      const table = (op.params.table as number | undefined) ?? 0;
      const row = op.params.row as number;
      const col = op.params.col as number;
      const run = op.params.run as number | undefined;
      const before =
        run !== undefined && context.beforeCellRun
          ? context.beforeCellRun(table, row, col, run)
          : beforeCell(table, row, col, run);
      const projected: ProjectedAgentReplaceAtCellOp = {
        opId: op.opId,
        kind: "replace_at_cell",
        table,
        row,
        col,
        ...(run === undefined ? {} : { run }),
        text: op.params.text as string,
        ...(op.params.mode === undefined ? {} : { mode: op.params.mode as "replace" | "append" }),
        ...(op.params.expect === undefined ? {} : { expect: op.params.expect as string }),
        ...(op.params.charPr === undefined ? {} : { charPr: op.params.charPr as string }),
        before,
        origin: "agent",
        proposer: plan.proposer,
      };
      attachTableExplicit(projected, explicitTable);
      return projected;
    }

    if (op.kind === "set_run") {
      const atPara = op.params.atPara as number;
      const run = op.params.run as number;
      const before = context.beforeParaRun ? context.beforeParaRun(atPara, run) : "";
      return {
        opId: op.opId,
        kind: "set_run",
        atPara,
        run,
        text: op.params.text as string,
        before,
        origin: "agent",
        proposer: plan.proposer,
      };
    }

    // delete_guides (validated above)
    const color = op.params.color as string | undefined;
    const charPrIds = isStringArray(op.params.charPrIds) ? [...op.params.charPrIds] : undefined;
    const before = context.guideSummary
      ? context.guideSummary(color, charPrIds)
      : defaultGuideSummary(color, charPrIds, lang);
    return {
      opId: op.opId,
      kind: "delete_guides",
      ...(color === undefined ? {} : { color }),
      ...(charPrIds === undefined ? {} : { charPrIds }),
      text: t("proj_guides_deleted", lang),
      before,
      origin: "agent",
      proposer: plan.proposer,
    };
  });
}

export type ReconstructibleOp =
  | {
      opId: string;
      kind: "fill_cell";
      table: number;
      row: number;
      col: number;
      text: string;
      lines?: string[];
      charPr?: string;
      paraPr?: string;
      overwrite?: boolean;
    }
  | {
      opId: string;
      kind: "replace_at_cell";
      table: number;
      row: number;
      col: number;
      run?: number;
      text: string;
      mode?: "replace" | "append";
      expect?: string;
      charPr?: string;
    }
  | {
      opId: string;
      kind: "set_run";
      atPara: number;
      run: number;
      text: string;
    }
  | {
      opId: string;
      kind: "delete_guides";
      color?: string;
      charPrIds?: string[];
      text?: string;
    };

/**
 * Reconstruct the exact `{ opId, kind, params }` Runtime operation that a
 * projected queue item represents, preserving every Runtime parameter cleanly.
 */
export function rebuildPlanOpFromProjection(projected: ReconstructibleOp): ProjectablePlanOp {
  const tableExplicit = (projected as { _tableExplicit?: boolean })._tableExplicit;
  if (projected.kind === "fill_cell") {
    const params: Record<string, unknown> = {
      ...(tableExplicit === false ? {} : { table: projected.table }),
      row: projected.row,
      col: projected.col,
      ...(projected.lines !== undefined ? { lines: [...projected.lines] } : { text: projected.text }),
      ...(projected.charPr !== undefined ? { charPr: projected.charPr } : {}),
      ...(projected.paraPr !== undefined ? { paraPr: projected.paraPr } : {}),
      ...(projected.overwrite !== undefined ? { overwrite: projected.overwrite } : {}),
    };
    return { opId: projected.opId, kind: "fill_cell", params };
  }

  if (projected.kind === "replace_at_cell") {
    const params: Record<string, unknown> = {
      ...(tableExplicit === false ? {} : { table: projected.table }),
      row: projected.row,
      col: projected.col,
      ...(projected.run !== undefined ? { run: projected.run } : {}),
      text: projected.text,
      ...(projected.mode !== undefined ? { mode: projected.mode } : {}),
      ...(projected.expect !== undefined ? { expect: projected.expect } : {}),
      ...(projected.charPr !== undefined ? { charPr: projected.charPr } : {}),
    };
    return { opId: projected.opId, kind: "replace_at_cell", params };
  }

  if (projected.kind === "set_run") {
    return {
      opId: projected.opId,
      kind: "set_run",
      params: {
        atPara: projected.atPara,
        run: projected.run,
        text: projected.text,
      },
    };
  }

  if (projected.kind === "delete_guides") {
    return {
      opId: projected.opId,
      kind: "delete_guides",
      params: {
        ...(projected.color !== undefined ? { color: projected.color } : {}),
        ...(projected.charPrIds !== undefined ? { charPrIds: [...projected.charPrIds] } : {}),
      },
    };
  }

  throw new Error(`Unsupported projected op kind: ${(projected as { kind: string }).kind}`);
}

export function formatProjectedAddress(
  op: ReconstructibleOp,
  lang: UiLanguage = "ko",
): string {
  if (op.kind === "fill_cell") {
    return t("proj_addr_table_cell", lang, [op.table, op.row, op.col]);
  }
  if (op.kind === "replace_at_cell") {
    const base = t("proj_addr_table_cell", lang, [op.table, op.row, op.col]);
    return op.run !== undefined
      ? `${base} ${t("proj_addr_run_suffix", lang, [op.run])}`
      : base;
  }
  if (op.kind === "set_run") {
    return t("proj_addr_para_run", lang, [op.atPara, op.run]);
  }
  return lang === "ko"
    ? `${t("proj_addr_delete_guides", "ko")} · ${t("proj_addr_delete_guides", "en")}`
    : t("proj_addr_delete_guides", lang);
}

export function projectedAfterText(
  op: ReconstructibleOp & { before: string },
  lang: UiLanguage = "ko",
): string {
  if (op.kind === "delete_guides") return t("proj_guides_deleted", lang);
  if (op.kind === "replace_at_cell" && op.mode === "append") {
    return `${op.before}${op.text}`;
  }
  if (op.kind === "fill_cell" && op.lines !== undefined) {
    return op.lines.join("\n");
  }
  return op.text ?? "";
}

export function projectionInverseSupport(
  op: { kind: string },
  lang: UiLanguage = "ko",
): {
  invertible: boolean;
  reason?: string;
} {
  if (op.kind === "delete_guides") {
    return {
      invertible: false,
      reason: t("proj_inverse_delete_guides", lang),
    };
  }
  if (op.kind === "fill_cell" || op.kind === "replace_at_cell" || op.kind === "set_run") {
    return { invertible: true };
  }
  return {
    invertible: false,
    reason: t("proj_inverse_unsupported_kind", lang, [opKindLabel(op.kind, lang)]),
  };
}
