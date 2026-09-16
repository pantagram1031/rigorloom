/**
 * Pure review-hunk helpers. Display only: nothing here mutates op params
 * or the plan JSON the queue will send.
 */
import type { DiffMark } from "./diff";
import { diffText } from "./diff";
import type { QueuedOp } from "./store";
import type { RegionText, RuntimeError, VerificationReport } from "./types";

/** GitHub-style provenance on every hunk. Plan JSON is unchanged. */
export interface HunkProvenance {
  sessionId: string | null;
  planId: string | null;
  planHash: string | null;
  proposer: string;
  backend: string | null;
  baseRunId: string | null;
  receiptExists: boolean;
}

export type HunkStateId = "queued" | "approved" | "rejected" | "applied" | "stale";

export const HUNK_STATE_LABEL: Record<HunkStateId, string> = {
  queued: "대기",
  approved: "승인됨",
  rejected: "거부됨",
  applied: "적용됨",
  stale: "오래됨",
};

export const HUNK_STATE_TONE: Record<HunkStateId, "none" | "ok" | "bad" | "fill" | "warn"> = {
  queued: "none",
  approved: "ok",
  rejected: "bad",
  applied: "fill",
  stale: "warn",
};

export function hunkSlug(op: Pick<QueuedOp, "kind"> & Partial<QueuedOp>): string {
  return op.kind === "fill_cell"
    ? `${op.table}-${op.row}-${op.col}`
    : `p${op.atPara}-r${op.run}`;
}

export function hunkKindLabel(op: Pick<QueuedOp, "kind"> & Partial<QueuedOp>): string {
  if (op.kind === "fill_cell") {
    const before = typeof op.before === "string" ? op.before : null;
    if (op.overwrite || (before != null && before.length > 0)) return "바꾸기";
    return "값 넣기";
  }
  if (op.kind === "set_run") return "바꾸기";
  return "삽입";
}

export function hunkAddress(op: QueuedOp): string {
  return op.kind === "fill_cell"
    ? `표 ${op.table} R${op.row}C${op.col}`
    : `문단 ${op.atPara}`;
}

export function hunkReviewState(input: {
  stale: boolean;
  approvalState: string | null | undefined;
  applied: boolean;
}): HunkStateId {
  if (input.stale) return "stale";
  if (input.applied) return "applied";
  if (input.approvalState === "rejected") return "rejected";
  if (input.approvalState === "approved") return "approved";
  return "queued";
}

type RegionLookup = Pick<QueuedOp, "kind"> & Partial<QueuedOp>;

/** Region cache first; then the op's captured before. Missing → null (원문 없음). */
export function hunkBeforeText(
  op: RegionLookup,
  regions: RegionText[] | null | undefined,
): string | null {
  if (regions && regions.length > 0) {
    const hit =
      op.kind === "fill_cell"
        ? regions.find(
            (row) =>
              (row.table ?? 0) === op.table &&
              row.addr?.row === op.row &&
              row.addr?.col === op.col,
          )
        : regions.find((row) => row.at_para === op.atPara);
    if (hit) return hit.text;
  }
  if (typeof op.before === "string") return op.before;
  return null;
}

export function isReplaceOp(op: RegionLookup, before: string | null): boolean {
  if (op.kind === "set_run") return true;
  return typeof before === "string" && before.length > 0;
}

export function hunkDiffMarks(before: string | null, after: string, replace: boolean): DiffMark[] {
  if (!replace || before == null) {
    return after ? [{ type: "insert", text: after }] : [];
  }
  return diffText(before, after);
}

/** Same shape `setQueue` sends to `plan/propose`. Display must not change this. */
export function planOpsJson(ops: readonly QueuedOp[]): string {
  return JSON.stringify(
    ops.map((op) =>
      op.kind === "fill_cell"
        ? {
            opId: op.opId,
            kind: op.kind,
            table: op.table,
            row: op.row,
            col: op.col,
            text: op.text,
            ...(op.charPr ? { charPr: op.charPr } : {}),
            ...(op.overwrite ? { overwrite: true } : {}),
          }
        : {
            opId: op.opId,
            kind: op.kind,
            atPara: op.atPara,
            run: op.run,
            text: op.text,
          },
    ),
  );
}

export function shortPlanHash(hash: string | null | undefined): string | null {
  if (!hash) return null;
  return hash.slice(0, 6);
}

export type ReviewHotkey =
  | { type: "none" }
  | { type: "focus"; index: number }
  | { type: "approve-hunk"; index: number }
  | { type: "reject-hunk"; index: number }
  | { type: "toggle-provenance"; index: number }
  | { type: "approve-all" };

export function reviewQueueHotkey(
  e: {
    key: string;
    shiftKey: boolean;
    isComposing?: boolean;
    ctrlKey?: boolean;
    metaKey?: boolean;
    altKey?: boolean;
  },
  ctx: { focused: number; count: number; composing: boolean; inEditable: boolean },
): ReviewHotkey {
  if (ctx.composing || e.isComposing) return { type: "none" };
  if (e.ctrlKey || e.metaKey || e.altKey) return { type: "none" };
  if (ctx.count <= 0) return { type: "none" };
  if (e.shiftKey && (e.key === "A" || e.key === "a")) return { type: "approve-all" };
  if (ctx.inEditable) return { type: "none" };
  const focused = Math.min(Math.max(ctx.focused, 0), ctx.count - 1);
  switch (e.key) {
    case "j":
      return { type: "focus", index: Math.min(focused + 1, ctx.count - 1) };
    case "k":
      return { type: "focus", index: Math.max(focused - 1, 0) };
    case "a":
      return { type: "approve-hunk", index: focused };
    case "r":
      return { type: "reject-hunk", index: focused };
    case "Enter":
      return { type: "toggle-provenance", index: focused };
    default:
      return { type: "none" };
  }
}

export function queueRefusalMessage(input: {
  verdict: VerificationReport | null | undefined;
  applyError: RuntimeError | null | undefined;
  draftError: RuntimeError | null | undefined;
  exitCodes: number[] | null | undefined;
}): string | null {
  if (input.verdict && input.verdict.acceptance === false) {
    return input.verdict.reason ?? input.verdict.note ?? null;
  }
  if ((input.exitCodes ?? []).includes(3)) {
    return input.applyError?.message ?? input.draftError?.message ?? null;
  }
  const data = input.applyError?.data ?? input.draftError?.data;
  if (data && typeof data === "object" && data !== null && "exitCode" in data) {
    const n = (data as { exitCode: unknown }).exitCode;
    if (n === 3) return (input.applyError ?? input.draftError)?.message ?? null;
  }
  return null;
}
