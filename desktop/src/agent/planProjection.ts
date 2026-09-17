/**
 * The review queue is not a generic rendering of Runtime operations. It is an
 * The queue round-trips `fill_cell` and `set_run` from the seats. Agent plans
 * also project the xml first-wave trio (`replace_all`, `goto_text`,
 * `insert_text`) as themselves — never as a cell fill.
 * different operation as a cell fill would ask a person to approve something
 * other than the Runtime will execute.
 *
 * `fill_cell` keeps its original bound: `lines` and `paraPr` are valid
 * Runtime fields but have no queue representation, so plans carrying them are
 * refused rather than displayed with those semantics silently removed. Xml
 * ops keep every Runtime param so a later propose cannot drop a meaning.
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

export interface ProjectedAgentXmlOp {
  opId: string;
  kind: "replace_all" | "goto_text" | "insert_text";
  text: string;
  before: string;
  origin: "agent";
  proposer: string;
  params: Record<string, unknown>;
}

export type ProjectedAgentOp = ProjectedAgentFillOp | ProjectedAgentXmlOp;

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
const XML_KIND_FIELDS: Record<ProjectedAgentXmlOp["kind"], Set<string>> = {
  replace_all: new Set(["find", "replace", "regex"]),
  goto_text: new Set(["text", "after", "line_end", "cell_below", "next_para"]),
  insert_text: new Set(["text", "pt", "segments", "break_after", "align"]),
};

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
function isXmlKind(kind: string): kind is ProjectedAgentXmlOp["kind"] {
  return kind === "replace_all" || kind === "goto_text" || kind === "insert_text";
}

function validateFillOp(op: ProjectablePlanOp): void {
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

function validateXmlOp(op: ProjectablePlanOp): void {
  if (!isXmlKind(op.kind)) return;
  const allowed = XML_KIND_FIELDS[op.kind];
  const unsupportedFields = Object.keys(op.params).filter((field) => !allowed.has(field));
  if (unsupportedFields.length > 0) {
    throw refusal(op, "일부 작업 의미를 대기열이 보존할 수 없습니다.", {
      unsupportedFields: unsupportedFields.sort(),
    });
  }
  const invalidFields: string[] = [];
  if (op.kind === "replace_all") {
    if (typeof op.params.find !== "string") invalidFields.push("find");
    if (typeof op.params.replace !== "string") invalidFields.push("replace");
    if (op.params.regex !== undefined && typeof op.params.regex !== "boolean") {
      invalidFields.push("regex");
    }
  } else if (typeof op.params.text !== "string") {
    invalidFields.push("text");
  }
  if (invalidFields.length > 0) {
    throw refusal(op, "작업 필드의 형식이 대기열 표현과 맞지 않습니다.", {
      invalidFields,
    });
  }
}

function validateProjectableAgentPlan(plan: ProjectableAgentPlan): void {
  for (const op of plan.ops) {
    if (op.kind === "fill_cell") {
      validateFillOp(op);
      continue;
    }
    if (isXmlKind(op.kind)) {
      validateXmlOp(op);
      continue;
    }
    throw refusal(op, "이 작업 종류는 아직 검토 대기열이 지원하지 않습니다.");
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
  return plan.ops
    .filter((op) => op.kind === "fill_cell")
    .map((op) => ({
      table: (op.params.table as number | undefined) ?? 0,
      row: op.params.row as number,
      col: op.params.col as number,
    }));
}

function xmlDisplay(op: ProjectablePlanOp): { text: string; before: string } {
  if (op.kind === "replace_all") {
    return { before: String(op.params.find ?? ""), text: String(op.params.replace ?? "") };
  }
  if (op.kind === "goto_text") {
    const anchor = String(op.params.text ?? "");
    return { before: anchor, text: anchor };
  }
  return { before: "", text: String(op.params.text ?? "") };
}

export function projectAgentPlan(
  plan: ProjectableAgentPlan,
  beforeCell: (table: number, row: number, col: number) => string,
): ProjectedAgentOp[] {
  validateProjectableAgentPlan(plan);

  return plan.ops.map((op) => {
    if (isXmlKind(op.kind)) {
      const shown = xmlDisplay(op);
      return {
        opId: op.opId,
        kind: op.kind,
        text: shown.text,
        before: shown.before,
        origin: "agent",
        proposer: plan.proposer,
        params: { ...op.params },
      };
    }
    // The validation pass above establishes this narrowed shape for fill ops.
    const table = (op.params.table as number | undefined) ?? 0;
    const row = op.params.row as number;
    const col = op.params.col as number;
    return {
      opId: op.opId,
      kind: "fill_cell" as const,
      table,
      row,
      col,
      text: op.params.text as string,
      ...(op.params.charPr === undefined ? {} : { charPr: op.params.charPr as string }),
      ...(op.params.overwrite === undefined ? {} : { overwrite: op.params.overwrite as boolean }),
      before: beforeCell(table, row, col),
      origin: "agent" as const,
      proposer: plan.proposer,
    };
  });
}
