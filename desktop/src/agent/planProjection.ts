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

const KNOWN_UNIMPLEMENTED_REASONS: Record<string, string> = {
  normalize_clones:
    "동일 스타일 클론 정리(normalize_clones)는 헤더 재작성 작업이라 검토 대기열이 아직 안전하게 표현할 수 없습니다.",
  goto_text:
    "위치 이동 작업(goto_text)은 프리에딧 검토 대기열이 지원하지 않는 백엔드 작업입니다.",
};

function refusal(
  op: ProjectablePlanOp,
  reason: string,
  details: Partial<AgentPlanProjectionRefusal["data"]> = {},
): AgentPlanProjectionRefusal {
  return {
    code: "agent_plan_projection_unsupported",
    message: `작업 ${op.opId} (${op.kind})을 검토 대기열에 정확히 표시할 수 없습니다: ${reason}`,
    data: { opId: op.opId, kind: op.kind, ...details },
  };
}

function isAddress(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function checkAllowedFields(op: ProjectablePlanOp, allowed: Set<string>): void {
  const unsupportedFields = Object.keys(op.params).filter((field) => !allowed.has(field));
  if (unsupportedFields.length > 0) {
    throw refusal(op, "일부 작업 의미를 대기열이 보존할 수 없습니다.", {
      unsupportedFields: unsupportedFields.sort(),
    });
  }
}

/**
 * Validate every op in a plan atomically before any projection or read happens,
 * so an invalid later op never triggers reads or produces a partial queue.
 */
function validateProjectableAgentPlan(plan: ProjectableAgentPlan): void {
  for (const op of plan.ops) {
    const allowed = SUPPORTED_OP_FIELDS[op.kind];
    if (!allowed) {
      const reason =
        KNOWN_UNIMPLEMENTED_REASONS[op.kind] ??
        `작업 종류 "${op.kind}"는 검토 대기열이 지원하지 않습니다.`;
      throw refusal(op, reason);
    }

    if (!op.params || typeof op.params !== "object" || Array.isArray(op.params)) {
      throw refusal(op, "작업 매개변수 객체가 올바르지 않습니다.", {
        invalidFields: ["params"],
      });
    }

    checkAllowedFields(op, allowed);
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
      throw refusal(op, "작업 필드의 형식이 대기열 표현과 맞지 않습니다.", {
        invalidFields: [...new Set(invalidFields)],
      });
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

function defaultGuideSummary(color?: string, charPrIds?: string[]): string {
  const parts: string[] = [];
  if (color) parts.push(`색상 ${color}`);
  if (charPrIds && charPrIds.length > 0) parts.push(`charPr ${charPrIds.join(", ")}`);
  return parts.length > 0 ? `안내문 (${parts.join(" · ")})` : "대상 안내문";
}

export function projectAgentPlan(
  plan: ProjectableAgentPlan,
  beforeCell: (table: number, row: number, col: number, run?: number) => string,
  context: PlanProjectionContext = {},
): ProjectedAgentOp[] {
  validateProjectableAgentPlan(plan);

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
      : defaultGuideSummary(color, charPrIds);
    return {
      opId: op.opId,
      kind: "delete_guides",
      ...(color === undefined ? {} : { color }),
      ...(charPrIds === undefined ? {} : { charPrIds }),
      text: "(안내문 삭제됨)",
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

export function formatProjectedAddress(op: ReconstructibleOp): string {
  if (op.kind === "fill_cell") return `표 ${op.table} R${op.row}C${op.col}`;
  if (op.kind === "replace_at_cell") {
    return op.run !== undefined
      ? `표 ${op.table} R${op.row}C${op.col} · 덩어리 ${op.run}`
      : `표 ${op.table} R${op.row}C${op.col}`;
  }
  if (op.kind === "set_run") return `문단 ${op.atPara} · 덩어리 ${op.run}`;
  return "안내문 삭제 · Delete guides";
}

export function projectedAfterText(
  op: ReconstructibleOp & { before: string },
): string {
  if (op.kind === "delete_guides") return "(안내문 삭제됨)";
  if (op.kind === "replace_at_cell" && op.mode === "append") {
    return `${op.before}${op.text}`;
  }
  if (op.kind === "fill_cell" && op.lines !== undefined) {
    return op.lines.join("\n");
  }
  return op.text ?? "";
}

export function projectionInverseSupport(op: { kind: string }): {
  invertible: boolean;
  reason?: string;
} {
  if (op.kind === "delete_guides") {
    return {
      invertible: false,
      reason:
        "안내문 삭제(delete_guides)는 삭제된 안내 문단·서식을 런타임에서 복구할 수 없어 역연산(되돌리기)이 지원되지 않습니다.",
    };
  }
  if (op.kind === "fill_cell" || op.kind === "replace_at_cell" || op.kind === "set_run") {
    return { invertible: true };
  }
  return {
    invertible: false,
    reason: `작업 종류(${op.kind})의 역연산을 지원하지 않습니다.`,
  };
}
