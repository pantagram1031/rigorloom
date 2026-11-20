import { INSTRUCTION_PHRASES, SLOT_PLACEHOLDER_MARKERS } from "../i18n/formTokens.ts";
import { opKindLabel, t } from "../i18n/vocabulary.ts";
import type {
  GraphCell,
  GraphTable,
  InspectResult,
  PlanOp,
  RegionText,
  UiLanguage,
} from "../types.ts";

const QUOTED_PATTERNS: readonly RegExp[] = [
  /"([^"]+)"/g,
  /“([^”]+)”/g,
  /'([^']+)'/g,
  /「([^」]+)」/g,
  /‘([^’]+)’/g,
];

export interface FormInstructionContext {
  /** Quoted slot terms extracted from guide & form-instruction cells, whitespace-stripped. */
  quotedTerms: Set<string>;
  /** Cell keys (`c:table:row:col`) classified as `guide` or carrying form instructions. */
  instructionCellKeys: Set<string>;
  /** Cell keys (`c:table:row:col`) classified as `guide`. */
  guideCellKeys: Set<string>;
  /** True when `inspect` / `textMap` indicates a fill-in form document. */
  isFormDocument: boolean;
}

/**
 * Normalize whitespace and collapse evenly spaced single Hangul syllables
 * (e.g. `행 정 기 관 명` -> `행정기관명`, `성 명` -> `성명`) without merging
 * real word spaces (`기안자 직위(직급) 서명`, `공개 구분`).
 */
export function collapseFormGuideLabel(raw: string): string {
  const norm = raw.replace(/\s+/g, " ").trim();
  if (!norm) return "";
  if (/^[\uAC00-\uD7A3] [\uAC00-\uD7A3]$/.test(norm)) {
    return norm.replace(/ /g, "");
  }
  return norm.replace(
    /(?:^|(?<=\s))[\uAC00-\uD7A3](?: [\uAC00-\uD7A3]){2,}(?=$|\s)/g,
    (segment) => segment.replace(/ /g, ""),
  );
}

/**
 * The label a form cell's own text gives: empty slots `(   )` and `[ ]` are
 * dropped, the first field of a multi-field line (fields separated by two or
 * more spaces) is kept, and a dangling opening bracket is trimmed.
 * `전화번호(   )` → `전화번호`, `210㎜×297㎜(백상지 80g/㎡)` stays whole.
 */
export function labelFromCellText(raw: string): string {
  const noSlots = raw.replace(/[(（]\s*[)）]/g, "  ").replace(/\[\s*\]/g, "  ");
  const first = noSlots.split(/\s{2,}/).map((part) => part.trim()).find(Boolean) ?? "";
  return collapseFormGuideLabel(first.replace(/[(（[]\s*$/, "")).trim();
}

/** A cell that only separates two fields on a form line (`/`, `·`, `-`). */
function isSeparatorText(text: string): boolean {
  return /^[\s/|·\-–—]+$/.test(text);
}

/** Truncate text at `maxCodepoints` Unicode codepoints with `…`. */
export function truncateLabel(text: string, maxCodepoints = 20): string {
  const codepoints = Array.from(text);
  if (codepoints.length <= maxCodepoints) return text;
  return `${codepoints.slice(0, maxCodepoints).join("").trimEnd()}…`;
}

function collectQuotedTerms(text: string, out: Set<string>): void {
  if (!text) return;
  for (const baseRe of QUOTED_PATTERNS) {
    const re = new RegExp(baseRe.source, baseRe.flags);
    let match: RegExpExecArray | null;
    while ((match = re.exec(text)) !== null) {
      const stripped = match[1].replace(/\s+/g, "");
      if (stripped.length > 0) {
        out.add(stripped);
      }
    }
  }
}

function containsInstructionPhrase(text: string): boolean {
  return INSTRUCTION_PHRASES.some((phrase) => text.includes(phrase));
}

/**
 * Scan `guide` cells and form-instruction cells to extract quoted form-slot
 * terms (stripped of whitespace) and mark guide/instruction cell keys.
 */
export function extractFormInstructionContext(
  inspect: InspectResult | null | undefined,
  textMap?: Record<string, RegionText>,
): FormInstructionContext {
  const quotedTerms = new Set<string>();
  const instructionCellKeys = new Set<string>();
  const guideCellKeys = new Set<string>();
  let hasFillOrGuideCell = false;

  for (const tbl of inspect?.graph.tables ?? []) {
    for (const cell of tbl.cells) {
      if (cell.classification === "fill_target" || cell.classification === "guide") {
        hasFillOrGuideCell = true;
      }
      const key = `c:${tbl.index}:${cell.addr.row}:${cell.addr.col}`;
      const region = textMap?.[key];
      const cellText =
        typeof region?.text === "string" && region.text.length > 0
          ? region.text
          : (cell.textPreview ?? "");

      const isGuide = cell.classification === "guide";
      const isInstruction = containsInstructionPhrase(cellText);
      if (isGuide) {
        guideCellKeys.add(key);
        instructionCellKeys.add(key);
      } else if (isInstruction) {
        instructionCellKeys.add(key);
      }
      if (isGuide || isInstruction) {
        collectQuotedTerms(cellText, quotedTerms);
        for (const run of region?.runs ?? []) {
          collectQuotedTerms(run.text, quotedTerms);
        }
      }
    }
  }

  for (const region of Object.values(textMap ?? {})) {
    if (region.table === undefined || !region.addr) continue;
    const cellKey = `c:${region.table}:${region.addr.row}:${region.addr.col}`;
    if (instructionCellKeys.has(cellKey)) continue;
    if (containsInstructionPhrase(region.text)) {
      instructionCellKeys.add(cellKey);
      collectQuotedTerms(region.text, quotedTerms);
      for (const run of region.runs ?? []) {
        collectQuotedTerms(run.text, quotedTerms);
      }
    }
  }

  const isFormDocument =
    (inspect?.summary?.fillTargetCount ?? 0) > 0 ||
    hasFillOrGuideCell ||
    guideCellKeys.size > 0 ||
    instructionCellKeys.size > 0;

  return {
    quotedTerms,
    instructionCellKeys,
    guideCellKeys,
    isFormDocument,
  };
}

/**
 * Derive a concise label from sibling letter/digit runs in the same cell when
 * removing a punctuation/bullet symbol run (e.g. `■ ` -> `[별지 제1호서식]`).
 */
export function deriveSiblingRunFieldLabel(
  tableIdx: number,
  row: number,
  col: number,
  targetRunIdx: number | undefined,
  beforeText: string,
  texts: Record<string, RegionText> | undefined,
  maxCodepoints = 20,
): string {
  const region = texts?.[`c:${tableIdx}:${row}:${col}`];
  const runs = region?.runs ?? [];
  const letterSiblings = runs
    .filter((r) => r.index !== targetRunIdx && /[\p{L}\p{N}]/u.test(r.text))
    .map((r) => ({
      colorAnomaly: Boolean(r.color_anomaly),
      label: collapseFormGuideLabel(r.text),
    }))
    .filter((item) => item.label.length > 0);

  const nonAnomaly = letterSiblings.filter((item) => !item.colorAnomaly);
  const pool = nonAnomaly.length > 0 ? nonAnomaly : letterSiblings;
  if (pool.length > 0) {
    let best = pool[0];
    let bestLen = Array.from(best.label).length;
    for (let i = 1; i < pool.length; i += 1) {
      const candidate = pool[i];
      const len = Array.from(candidate.label).length;
      if (len < bestLen) {
        best = candidate;
        bestLen = len;
      }
    }
    return truncateLabel(best.label, maxCodepoints);
  }

  const collapsed = collapseFormGuideLabel(beforeText);
  return truncateLabel(collapsed || beforeText.trim(), maxCodepoints);
}

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

function isCompositeHeaderCell(
  tableIdx: number,
  cell: GraphCell,
  texts: Record<string, RegionText> | undefined,
  inspect: InspectResult | null | undefined,
): boolean {
  const key = `c:${tableIdx}:${cell.addr.row}:${cell.addr.col}`;
  const region = texts?.[key];
  const raw =
    typeof region?.text === "string" && region.text.trim() !== ""
      ? region.text
      : (cell.textPreview ?? "");

  if (/[\r\n]/.test(raw.trim())) {
    return true;
  }

  const nonEmptyRuns = (region?.runs ?? []).filter((r) => r.text.trim().length > 0);
  const anchors = inspect?.summary?.anchors ?? [];
  if (nonEmptyRuns.length >= 2) {
    if (nonEmptyRuns.length >= 3) {
      return true;
    }
    const anchorHits = nonEmptyRuns.filter((r) => {
      const runNorm = collapseFormGuideLabel(r.text).replace(/\s+/g, "");
      return anchors.some((a) => {
        const anchorNorm = collapseFormGuideLabel(a).replace(/\s+/g, "");
        return anchorNorm.length >= 2 && runNorm.includes(anchorNorm);
      });
    }).length;
    if (anchorHits >= 2) {
      return true;
    }
  }

  // Fallback without `runs`: detect concatenated multi-anchor header cells like
  // `"행 정 기 관 명수신(경유)제목 "`.
  if (anchors.length >= 2) {
    let remaining = raw.replace(/\s+/g, "");
    const sortedAnchors = [...anchors]
      .map((a) => collapseFormGuideLabel(a).replace(/\s+/g, ""))
      .filter((a) => a.length >= 2)
      .sort((a, b) => b.length - a.length);
    let distinctHits = 0;
    for (const anchor of sortedAnchors) {
      if (remaining.includes(anchor)) {
        distinctHits += 1;
        remaining = remaining.replace(anchor, "\u0000");
        if (distinctHits >= 2) return true;
      }
    }
  }

  return false;
}

function isFullWidthBodyCell(
  table: GraphTable,
  row: number,
  col: number,
  targetCell: GraphCell | undefined,
): boolean {
  if (!targetCell || targetCell.classification !== "fill_target" || col !== 0) {
    return false;
  }
  let cellsInRow = 0;
  for (const cell of table.cells) {
    if (cell.addr.row === row) {
      cellsInRow += 1;
      if (cellsInRow > 1) return false;
    }
  }
  return cellsInRow === 1;
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
 * cells to the left and above. Never exposes coordinate tokens like `R0C14` and
 * never inherits concatenated multi-paragraph header blocks onto body blanks.
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

    // 0. A cell that carries its own words (a form line being edited:
    //    `전화번호(   )`, `검토자 직위(직급) 서명`, the paper-size line) is
    //    named by them, never by a neighbour or the row above it.
    const ownCell = byPos.get(`${row}:${col}`);
    const ownText = ownCell ? readCellText(table.index, ownCell, texts) ?? "" : "";
    let ownLabel =
      ownCell && ownCell.classification === "static" && !isCompositeHeaderCell(table.index, ownCell, texts, inspect)
        ? labelFromCellText(ownText)
        : "";
    // A guide or instruction line (`비고(이 난은 …)`) is named by its heading word.
    if (ownCell && !ownLabel && ownCell.classification !== "fill_target" && ownCell.classification !== "spacer") {
      const head = ownText.split(/[(（]/)[0].replace(/\s+/g, " ").trim();
      if (head && Array.from(head).length <= 10) ownLabel = head;
    }
    if (isSeparatorText(ownLabel)) ownLabel = "";
    if (ownLabel) return truncateLabel(ownLabel, 20);

    // 1. Scan left in the same row for the nearest static label cell.
    for (let c = col - 1; c >= 0; c -= 1) {
      const candidate = byPos.get(`${row}:${c}`);
      if (!candidate) continue;
      if (candidate.classification === "fill_target") break;
      if (candidate.classification === "static") {
        if (isCompositeHeaderCell(table.index, candidate, texts, inspect)) continue;
        const text = readCellText(table.index, candidate, texts);
        const label = text ? labelFromCellText(text) : "";
        // A `/` between two fields ends the field to the left.
        if (isSeparatorText(label)) break;
        if (label) return truncateLabel(label, 20);
      }
    }

    // 2. Fall back to scanning directly above in the same column, skipping
    //    multi-field composite header blocks.
    for (let r = row - 1; r >= 0; r -= 1) {
      const candidate = byPos.get(`${r}:${col}`);
      if (!candidate) continue;
      if (candidate.classification === "fill_target") break;
      if (candidate.classification === "static") {
        if (isCompositeHeaderCell(table.index, candidate, texts, inspect)) continue;
        const text = readCellText(table.index, candidate, texts);
        const label = text ? labelFromCellText(text) : "";
        if (label) return truncateLabel(label, 20);
      }
    }

    // 3. Full-width body fill_target (e.g. gongmun table 0 row 2 col 0).
    const targetCell = byPos.get(`${row}:${col}`);
    if (isFullWidthBodyCell(table, row, col, targetCell)) {
      return t("field_body_fallback", lang);
    }

    // 4. Inherit the nearest non-composite static row header to the left,
    //    scanning past sibling fill_target cells on multi-slot rows.
    for (let c = col - 1; c >= 0; c -= 1) {
      const candidate = byPos.get(`${row}:${c}`);
      if (!candidate || candidate.classification !== "static") continue;
      if (isCompositeHeaderCell(table.index, candidate, texts, inspect)) continue;
      const text = readCellText(table.index, candidate, texts);
      if (!text) continue;
      const collapsed = labelFromCellText(text);
      if (!collapsed || Array.from(collapsed).length > 20) continue;
      return truncateLabel(collapsed, 20);
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
      return truncateLabel(collapseFormGuideLabel(snippet), 26);
    }
  }

  const mode = typeof params.mode === "string" ? params.mode : null;
  return opKindLabel(op.kind, lang, mode);
}

/**
 * Determine whether a cell edit fills an empty blank (`fill_cell`), appends
 * to existing form text (`replace_at_cell` with `mode: "append"` -> `칸 문구 덧붙임`),
 * or replaces existing cell text (`replace_at_cell` with `mode: "replace"` -> `칸 문구 바꿈`).
 */
export function classifyCellEditMode(
  beforeText: string,
  afterText: string,
): {
  kind: "fill_cell" | "replace_at_cell";
  mode?: "append" | "replace";
  hasFormText: boolean;
} {
  if (beforeText.trim().length === 0) {
    return { kind: "fill_cell", hasFormText: false };
  }
  const trimmedBefore = beforeText.trim();
  const isAppend =
    afterText.startsWith(beforeText) ||
    (trimmedBefore.length > 0 && afterText.startsWith(trimmedBefore));
  return {
    kind: "replace_at_cell",
    mode: isAppend ? "append" : "replace",
    hasFormText: true,
  };
}

/**
 * Disambiguate repeated blank labels by numbering duplicates `1..N`
 * (e.g. `협조자 1` .. `협조자 7`) while leaving unique labels untouched.
 */
export function disambiguateBlankLabels<T extends { baseLabel: string }>(
  items: readonly T[],
): Array<T & { displayLabel: string; duplicateIndex: number | null; duplicateTotal: number }> {
  const totals = new Map<string, number>();
  for (const item of items) {
    totals.set(item.baseLabel, (totals.get(item.baseLabel) ?? 0) + 1);
  }
  const seen = new Map<string, number>();
  return items.map((item) => {
    const total = totals.get(item.baseLabel) ?? 1;
    if (total <= 1) {
      return {
        ...item,
        displayLabel: item.baseLabel,
        duplicateIndex: null,
        duplicateTotal: 1,
      };
    }
    const idx = (seen.get(item.baseLabel) ?? 0) + 1;
    seen.set(item.baseLabel, idx);
    return {
      ...item,
      displayLabel: `${item.baseLabel} ${idx}`,
      duplicateIndex: idx,
      duplicateTotal: total,
    };
  });
}

/**
 * Check whether a cell text matches a form slot placeholder (used to expose
 * fillable form slots in addition to `fill_target` regions).
 */
export function isSlotPlaceholderText(
  text: string,
  formCtx: FormInstructionContext,
): boolean {
  const collapsed = collapseFormGuideLabel(text);
  const compact = collapsed.replace(/\s+/g, "");
  if (!compact) return false;
  if (SLOT_PLACEHOLDER_MARKERS.some((m) => compact.includes(m))) return true;
  if (/\(\s{2,}\)|\[\s{2,}\]/.test(text)) return true;
  for (const term of formCtx.quotedTerms) {
    if (compact === term) return true;
  }
  return false;
}
