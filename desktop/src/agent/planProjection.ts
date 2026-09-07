/**
 * The review queue is not a generic rendering of Runtime operations. It is an
 * editable model which can currently round-trip only `fill_cell` and
 * `set_run`. Agent plans therefore need an explicit, fail-closed projection:
 * showing a different operation as a cell fill would ask a person to approve
 * something other than the Runtime will execute.
 *
 * This first bounded projector accepts only the `fill_cell` shape the queue
 * can preserve completely. In particular, `lines` and `paraPr` are valid
 * Runtime fields but have no queue representation, so plans carrying them are
 * refused rather than displayed with those semantics silently removed.
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
  charPr?: string;
  overwrite?: boolean;
  before: string;
  origin: "agent";
  proposer: string;
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

const PROJECTABLE_FILL_FIELDS = new Set(["table", "row", "col", "text", "charPr", "overwrite"]);

function refusal(
  op: ProjectablePlanOp,
  reason: string,
  details: Partial<AgentPlanProjectionRefusal["data"]> = {},
): AgentPlanProjectionRefusal {
  return {
    code: "agent_plan_projection_unsupported",
    message: `에이전트 작업 ${op.opId} (${op.kind})을 검토 대기열에 정확히 표시할 수 없습니다: ${reason}`,
    data: { opId: op.opId, kind: op.kind, ...details },
  };
}

function isAddress(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

/**
 * Convert the Runtime's authoritative plan to the exact queue representation.
 * The whole plan is checked before any projected result is returned, so one
 * supported op followed by an unsupported op cannot produce a partial queue.
 */
function validateProjectableAgentPlan(plan: ProjectableAgentPlan): void {
  for (const op of plan.ops) {
    if (op.kind !== "fill_cell") {
      throw refusal(op, "이 작업 종류는 아직 검토 대기열이 지원하지 않습니다.");
    }

    const unsupportedFields = Object.keys(op.params).filter(
      (field) => !PROJECTABLE_FILL_FIELDS.has(field),
    );
    if (unsupportedFields.length > 0) {
      throw refusal(op, "일부 작업 의미를 대기열이 보존할 수 없습니다.", {
        unsupportedFields: unsupportedFields.sort(),
      });
    }

    const invalidFields: string[] = [];
    if (op.params.table !== undefined && !isAddress(op.params.table)) invalidFields.push("table");
    if (!isAddress(op.params.row)) invalidFields.push("row");
    if (!isAddress(op.params.col)) invalidFields.push("col");
    if (typeof op.params.text !== "string") invalidFields.push("text");
    if (op.params.charPr !== undefined && typeof op.params.charPr !== "string") {
      invalidFields.push("charPr");
    }
    if (op.params.overwrite !== undefined && typeof op.params.overwrite !== "boolean") {
      invalidFields.push("overwrite");
    }
    if (invalidFields.length > 0) {
      throw refusal(op, "작업 필드의 형식이 대기열 표현과 맞지 않습니다.", {
        invalidFields,
      });
    }
  }
}

export interface ProjectedCellAddress {
  table: number;
  row: number;
  col: number;
}

/** Addresses to read from the exact document version the plan is bound to. */
export function agentPlanCellAddresses(plan: ProjectableAgentPlan): ProjectedCellAddress[] {
  validateProjectableAgentPlan(plan);
  return plan.ops.map((op) => ({
    table: (op.params.table as number | undefined) ?? 0,
    row: op.params.row as number,
    col: op.params.col as number,
  }));
}

export function projectAgentPlan(
  plan: ProjectableAgentPlan,
  beforeCell: (table: number, row: number, col: number) => string,
): ProjectedAgentFillOp[] {
  validateProjectableAgentPlan(plan);

  return plan.ops.map((op) => {
    // The validation pass above establishes this narrowed shape for every op.
    const table = (op.params.table as number | undefined) ?? 0;
    const row = op.params.row as number;
    const col = op.params.col as number;
    return {
      opId: op.opId,
      kind: "fill_cell",
      table,
      row,
      col,
      text: op.params.text as string,
      ...(op.params.charPr === undefined ? {} : { charPr: op.params.charPr as string }),
      ...(op.params.overwrite === undefined ? {} : { overwrite: op.params.overwrite as boolean }),
      before: beforeCell(table, row, col),
      origin: "agent",
      proposer: plan.proposer,
    };
  });
}
