import { opKindLabel, t } from "../i18n/vocabulary";
import type {
  GraphCell,
  InspectResult,
  PlanOp,
  RegionText,
  UiLanguage,
} from "../types";

function cleanLabel(raw: string | undefined | null): string {
  if (!raw) return "";
  return raw
    .replace(/\s+/g, " ")
    .replace(/[:：]\s*$/, "")
    .trim();
}

function readCellText(
  tableIdx: number,
  cell: GraphCell,
  texts?: Record<string, RegionText>,
): string {
  const key = `c:${tableIdx}:${cell.addr.row}:${cell.addr.col}`;
  const live = texts?.[key]?.text;
  if (typeof live === "string" && cleanLabel(live) !== "") {
    return cleanLabel(live);
  }
  return cleanLabel(cell.textPreview);
}

function computeBlankOrdinal(
  inspect: InspectResult | null | undefined,
  tableIdx: number,
  row: number,
  col: number,
): number {
  const tables = inspect?.graph.tables ?? [];
  let count = 0;
  for (const tbl of tables) {
    const ordered = [...tbl.cells].sort((a, b) =>
      a.addr.row !== b.addr.row ? a.addr.row - b.addr.row : a.addr.col - b.addr.col,
    );
    for (const cell of ordered) {
      if (cell.classification !== "fill_target") continue;
      count += 1;
      if (tbl.index === tableIdx && cell.addr.row === row && cell.addr.col === col) {
        return count;
      }
    }
  }
  return Math.max(1, count + 1);
}

/**
 * Derive a human label for a table cell by inspecting adjacent `static` header
 * cells to the left and above. Never exposes coordinate tokens like `R0C14`.
 */
export function deriveCellFieldLabel(
  inspect: InspectResult | null | undefined,
  texts: Record<string, RegionText> | undefined,
  tableIdx: number,
  row: number,
  col: number,
  lang: UiLanguage = "ko",
  blankOrdinal?: number,
): string {
  const table =
    inspect?.graph.tables.find((tbl) => tbl.index === tableIdx) ??
    inspect?.graph.tables[tableIdx];

  if (table) {
    const byPos = new Map<string, GraphCell>();
    for (const cell of table.cells) {
      byPos.set(`${cell.addr.row}:${cell.addr.col}`, cell);
    }

    // 1. Scan left in the same row for the nearest static label cell.
    for (let c = col - 1; c >= 0; c -= 1) {
      const candidate = byPos.get(`${row}:${c}`);
      if (!candidate) continue;
      if (candidate.classification === "fill_target") break;
      if (candidate.classification === "static") {
        const text = readCellText(table.index, candidate, texts);
        if (text) return text;
      }
    }

    // 2. Fall back to scanning directly above in the same column.
    for (let r = row - 1; r >= 0; r -= 1) {
      const candidate = byPos.get(`${r}:${col}`);
      if (!candidate) continue;
      if (candidate.classification === "fill_target") break;
      if (candidate.classification === "static") {
        const text = readCellText(table.index, candidate, texts);
        if (text) return text;
      }
    }
  }

  const ordinal = blankOrdinal ?? computeBlankOrdinal(inspect, tableIdx, row, col);
  return t("field_blank_fallback", lang, [ordinal]);
}

function asInt(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

/**
 * Derive a human label for any queued or planned operation without leaking
 * internal coordinates (`R0C14`, `p:3#0`) or op-kind names onto primary surfaces.
 */
export function deriveOpFieldLabel(
  op:
    | Pick<PlanOp, "kind" | "params">
    | {
        kind: string;
        params?: Record<string, unknown>;
        table?: number;
        row?: number;
        col?: number;
        atPara?: number;
        text?: string;
      },
  inspect: InspectResult | null | undefined,
  texts: Record<string, RegionText> | undefined,
  lang: UiLanguage = "ko",
  blankOrdinal?: number,
): string {
  const params = ("params" in op && op.params ? op.params : {}) as Record<string, unknown>;
  const addr = (params.addr ?? null) as { row?: unknown; col?: unknown } | null;
  const tableIdx =
    ("table" in op ? asInt(op.table) : null) ?? asInt(params.table) ?? 0;
  const row = ("row" in op ? asInt(op.row) : null) ?? asInt(params.row) ?? asInt(addr?.row);
  const col = ("col" in op ? asInt(op.col) : null) ?? asInt(params.col) ?? asInt(addr?.col);

  if (
    row !== null &&
    col !== null &&
    (op.kind === "fill_cell" || op.kind === "replace_at_cell" || op.kind === "set_cell")
  ) {
    return deriveCellFieldLabel(inspect, texts, tableIdx, row, col, lang, blankOrdinal);
  }

  const atPara =
    ("atPara" in op ? asInt(op.atPara) : null) ??
    asInt(params.at_para) ??
    asInt(params.atPara);
  if (atPara !== null) {
    const para = inspect?.graph.paragraphs.find((p) => p.at_para === atPara);
    const snippet = cleanLabel(para?.text);
    if (snippet) {
      return snippet.length > 26 ? `${snippet.slice(0, 26)}…` : snippet;
    }
  }

  const mode = typeof params.mode === "string" ? params.mode : null;
  return opKindLabel(op.kind, lang, mode);
}
