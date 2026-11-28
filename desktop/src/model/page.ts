import { wp3t } from "../i18n/v2/wp3";
import { belowLabelValue } from "./belowLabel.ts";
import {
  AGENCY_USE_TOKENS,
  BUNDLED_FACE_NAMES,
  FORM_OUTLINE_TOKENS,
  KOREAN_SUBCLAUSE_LINE_RE,
  SANS_FONT_TOKENS,
  SERIF_FONT_TOKENS,
} from "../i18n/v2/wp3FormTokens";
import type {
  GeometryResult,
  GraphCell,
  InspectResult,
  RegionText,
  RenderGrade,
  RenderResult,
  TypefaceByLang,
  UiLanguage,
} from "../types";
import {
  collapseFormGuideLabel,
  deriveBlankCellLabel,
  deriveCellFieldLabel,
  graphCellAt,
  isPlaceholderSlot,
  labelFromCellText,
  disambiguateBlankLabels,
  extractFormInstructionContext,
  truncateLabel,
} from "../workspace/fieldLabels";

export { deriveBlankCellLabel, graphCellAt, isPlaceholderSlot };

export type PageViewMode = "marks" | "clean" | "base";

export type PageFit = "width" | "page" | "free";

export type CanvasChangeSource = "agent" | "user" | "test" | "revert";

export type CanvasChangeDecision = "pending" | "accepted" | "rejected";

/** Coordinates in points from the page's top-left corner (`J1 §3`). */
export interface PageRectPt {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PageSizePt {
  widthPt: number;
  heightPt: number;
  marginPt: {
    top: number;
    right: number;
    bottom: number;
    left: number;
  };
}

export interface PageFontEntry {
  declared: string;
  resolved: string;
  substituted: boolean;
  category: "serif" | "sans" | "mono" | "other";
  count: number;
  slots: string[];
}

export interface PageFontsSummary {
  state: "read" | "unavailable";
  total: number;
  substitutedCount: number;
  entries: PageFontEntry[];
  reason?: string | null;
}

export interface PageBox {
  id: string;
  itemId?: string;
  address?: string;
  kind: "cell" | "para" | "table" | "seat" | "mark" | "guide" | "object";
  rect: PageRectPt;
  label?: string;
  /** kind "object": what the engine's renderer left undrawn there ("chart"). */
  object?: string;
  fontCategory?: "serif" | "sans";
}

export interface PageSeat {
  id: string;
  key: string;
  address: string;
  table: number;
  row: number;
  col: number;
  page: number | null;
  baseLabel: string;
  displayLabel: string;
  cellLocationLabel: string;
  locationLabel: string;
  duplicateIndex: number | null;
  duplicateTotal: number;
  group: "primary" | "agency";
  filled: boolean;
  hasFormText: boolean;
  isFillTarget: boolean;
  beforeText: string;
  currentText: string;
  charPr?: string;
  charPrSuggested?: string;
  scriptAnomaly?: boolean;
  colorAnomaly?: boolean;
  fontCategory: "serif" | "sans";
  fontFace?: string | null;
  rect: PageRectPt;
}

export interface OutlineNode {
  id: string;
  title: string;
  depth: 1 | 2 | 3;
  page: number;
  address?: string;
  cellKey?: string;
  kind: "heading" | "table" | "form" | "section";
  itemIds: string[];
  markRange: string | null;
  hasFact: boolean;
  hasWarning: boolean;
  allDecided: boolean;
}

export interface CanvasChangeRef {
  id: string;
  n: number;
  at: string;
  kind: string;
  opKind?: string;
  label: string;
  before: string;
  after: string;
  page: number;
  source: CanvasChangeSource;
  decision: CanvasChangeDecision;
  contentHash: string;
  guard: "changed" | "kept" | "expected" | "none" | "needs_fixes";
  hard: boolean;
  isFactChanged: boolean;
  isStale?: boolean;
  cellKey?: string;
  atPara?: number;
  run?: number;
  rects?: Array<{ page: number; rect: PageRectPt }>;
  hasFormText?: boolean;
  bodyStyleApplied?: boolean;
}

export interface PageMarkItem {
  itemId: string;
  n: number;
  address: string;
  source: CanvasChangeSource;
  decision: CanvasChangeDecision;
  isFactChanged: boolean;
  isStale: boolean;
  rect: PageRectPt;
}

export interface PageLayer {
  page: number;
  view: PageViewMode;
  kind: "projection" | "engine";
  rev: string;
  sizePt: PageSizePt;
  marks: PageMarkItem[];
  boxes: PageBox[];
  rasterUrl?: string;
}

export interface PageHitResult {
  kind: "seat" | "para" | "mark" | "static" | "none";
  page: number;
  pointPt: { x: number; y: number };
  address?: string;
  seatKey?: string;
  itemId?: string;
  caretOffset?: number | null;
  lineAddress?: string;
  lineOffset?: number;
}

export interface PageSource {
  readonly kind: "projection" | "engine";
  readonly grade: RenderGrade | string;
  readonly rev: string;
  pageCount(): number;
  size(page: number): PageSizePt;
  layer(page: number, view: PageViewMode): PageLayer;
  boxes(page: number): PageBox[];
  changedRects(itemId: string): Array<{ page: number; rect: PageRectPt }>;
  hitTest(page: number, xPt: number, yPt: number): PageHitResult;
  caretRect(page: number, address: string, offset: number): PageRectPt | null;
  seats(): PageSeat[];
  outline(): OutlineNode[];
  fonts(): PageFontsSummary;
}

// --- Doc-core address grammar (`p12`, `t3/r2/c1`, `place:<id>`) --------------

export type ParsedDocAddress =
  | { kind: "cell"; table: number; row: number; col: number }
  | { kind: "para"; atPara: number }
  | { kind: "place"; id: string };

export function formatCellAddress(table: number, row: number, col: number): string {
  return `t${table}/r${row}/c${col}`;
}

export function formatParaAddress(atPara: number): string {
  return `p${atPara}`;
}

export function formatPlaceAddress(id: string): string {
  return `place:${id}`;
}

export function legacyCellKey(table: number, row: number, col: number): string {
  return `c:${table}:${row}:${col}`;
}

export function parseDocAddress(raw: string): ParsedDocAddress | null {
  const s = raw.trim();
  const cellNew = /^t(\d+)\/r(\d+)\/c(\d+)$/.exec(s);
  if (cellNew) {
    return {
      kind: "cell",
      table: Number(cellNew[1]),
      row: Number(cellNew[2]),
      col: Number(cellNew[3]),
    };
  }
  const cellLegacy = /^c:(\d+):(\d+):(\d+)$/.exec(s);
  if (cellLegacy) {
    return {
      kind: "cell",
      table: Number(cellLegacy[1]),
      row: Number(cellLegacy[2]),
      col: Number(cellLegacy[3]),
    };
  }
  const paraNew = /^p(\d+)$/.exec(s);
  if (paraNew) {
    return { kind: "para", atPara: Number(paraNew[1]) };
  }
  const paraLegacy = /^p:(\d+)(?:#\d+)?$/.exec(s);
  if (paraLegacy) {
    return { kind: "para", atPara: Number(paraLegacy[1]) };
  }
  if (s.startsWith("place:") && s.length > 6) {
    return { kind: "place", id: s.slice(6) };
  }
  return null;
}

// --- Unit conversions --------------------------------------------------------

const HWPUNIT_PER_PT = 100;
const DEFAULT_A4_WIDTH_PT = 595.28;
const DEFAULT_A4_HEIGHT_PT = 841.89;

export function hwpunitToPt(units: number | undefined, fallbackPt: number): number {
  if (typeof units === "number" && Number.isFinite(units) && units > 0) {
    return Math.round((units / HWPUNIT_PER_PT) * 100) / 100;
  }
  return fallbackPt;
}

export function ptToPx(pt: number, zoom = 1): number {
  return pt * (96 / 72) * zoom;
}

export function pxToPt(px: number, zoom = 1): number {
  return (px / (zoom || 1)) * (72 / 96);
}

// --- Font category & substitution -------------------------------------------

export function resolvePageFontCategory(
  faceName: string | null | undefined,
): "serif" | "sans" {
  if (!faceName) return "serif";
  const norm = faceName.trim();
  if (SANS_FONT_TOKENS.some((tok) => norm.includes(tok))) return "sans";
  if (SERIF_FONT_TOKENS.some((tok) => norm.includes(tok))) return "serif";
  return "serif";
}

export function resolveFontSubstitution(
  declaredFace: string,
  lang: UiLanguage = "ko",
): { resolved: string; substituted: boolean; category: "serif" | "sans" } {
  const trimmed = declaredFace.trim();
  const category = resolvePageFontCategory(trimmed);
  if (BUNDLED_FACE_NAMES.has(trimmed)) {
    return { resolved: trimmed, substituted: false, category };
  }
  const resolved =
    category === "sans"
      ? wp3t("font_nanum_gothic", lang)
      : wp3t("font_nanum_myeongjo", lang);
  return {
    resolved,
    substituted: trimmed.length > 0 && trimmed !== resolved,
    category,
  };
}

function collectFaceNames(
  face: TypefaceByLang | null | undefined,
  slot: string,
  acc: Map<string, Set<string>>,
): void {
  if (!face) return;
  const primary = face.hangul || face.latin || face.other;
  if (!primary || !primary.trim()) return;
  const name = primary.trim();
  const slots = acc.get(name) ?? new Set<string>();
  slots.add(slot);
  acc.set(name, slots);
}

export function collectPageFonts(
  inspect: InspectResult | null | undefined,
  render: RenderResult | null | undefined,
  lang: UiLanguage = "ko",
): PageFontsSummary {
  if (render?.fonts?.substituted && render.fonts.substituted.length > 0) {
    const entries: PageFontEntry[] = render.fonts.substituted.map((s) => {
      const declared = s.declared ?? "";
      const fallback = resolveFontSubstitution(declared, lang);
      const resolved = s.drawnWith ?? fallback.resolved;
      return {
        declared,
        resolved,
        substituted: declared !== resolved,
        category: fallback.category,
        count: s.characters ?? 1,
        slots: s.slot ? [s.slot] : [],
      };
    });
    const subCount =
      render.fonts.facesSubstituted ??
      entries.filter((e) => e.substituted).length;
    return {
      state: "read",
      total: render.fonts.facesTotal ?? entries.length,
      substitutedCount: subCount,
      entries,
    };
  }

  if (!inspect) {
    return { state: "unavailable", total: 0, substitutedCount: 0, entries: [] };
  }

  const acc = new Map<string, Set<string>>();
  collectFaceNames(inspect.summary?.baselineCharPr?.face, "baseline", acc);
  collectFaceNames(inspect.summary?.blackCharPr?.face, "black", acc);
  for (const reg of inspect.regions?.regions ?? []) {
    if (reg.charPrFace) {
      const slot =
        reg.table !== undefined && reg.row !== undefined && reg.col !== undefined
          ? formatCellAddress(reg.table, reg.row, reg.col)
          : "region";
      collectFaceNames(reg.charPrFace, slot, acc);
    }
    if (reg.charPrSuggestedFace) {
      collectFaceNames(reg.charPrSuggestedFace, "suggested", acc);
    }
  }

  const tfState = inspect.summary?.typefaces as
    | { state?: string; reason?: string | null; faces?: Array<{ name?: string; role?: string; slot?: string }> }
    | undefined;
  if (Array.isArray(tfState?.faces)) {
    for (const faceEntry of tfState.faces) {
      if (faceEntry?.name && faceEntry.name.trim()) {
        const name = faceEntry.name.trim();
        const slots = acc.get(name) ?? new Set<string>();
        slots.add(faceEntry.slot ?? faceEntry.role ?? "face");
        acc.set(name, slots);
      }
    }
  }
  if (acc.size === 0 && tfState?.state === "unavailable") {
    return {
      state: "unavailable",
      total: 0,
      substitutedCount: 0,
      entries: [],
      reason: tfState.reason ?? null,
    };
  }

  const entries: PageFontEntry[] = [];
  for (const [declared, slots] of acc.entries()) {
    const sub = resolveFontSubstitution(declared, lang);
    entries.push({
      declared,
      resolved: sub.resolved,
      substituted: sub.substituted,
      category: sub.category,
      count: slots.size,
      slots: [...slots],
    });
  }

  return {
    state: tfState?.state === "read" || entries.length > 0 ? "read" : "unavailable",
    total: entries.length,
    substitutedCount: entries.filter((e) => e.substituted).length,
    entries,
    reason: tfState?.reason ?? null,
  };
}

// --- Seat & Outline detection ------------------------------------------------

export function isAgencyUseLabelOrText(label: string, rawText: string): boolean {
  const combined = `${label} ${rawText}`.replace(/\s+/g, "");
  return AGENCY_USE_TOKENS.some((tok) =>
    combined.includes(tok.replace(/\s+/g, "")),
  );
}

function isKnownPage(page: number | null | undefined): page is number {
  return typeof page === "number" && Number.isFinite(page) && page >= 1;
}

export function formatSeatCellLocation(
  row: number,
  col: number,
  lang: UiLanguage = "ko",
): string {
  return wp3t("seat_location_cell", lang, [row + 1, col + 1]);
}

export function formatSeatGroupHeading(
  page: number | null | undefined,
  table: number,
  lang: UiLanguage = "ko",
): string {
  if (isKnownPage(page)) {
    return wp3t("seat_group_page_table", lang, [page, table + 1]);
  }
  return wp3t("seat_group_table", lang, [table + 1]);
}

export interface CharShape {
  face: string | null;
  sizePt: number | null;
}

/** The character shape a cell's text is set in: the cell region's own charPr
 * face and size, else the graph cell's text charPr, else the document's body
 * baseline. Outside a cell, the baseline. */
export function cellCharShape(
  inspect: Pick<InspectResult, "graph" | "regions" | "summary"> | null | undefined,
  table: number | null,
  row?: number,
  col?: number,
): CharShape {
  const baseline = inspect?.summary?.baselineCharPr;
  const region = table === null || !inspect
    ? undefined
    : inspect.regions?.regions?.find((r) => r.table === table && r.row === row && r.col === col);
  const graphCell = table === null ? undefined : graphCellAt(inspect, table, row, col);
  const face =
    region?.charPrFace?.hangul ??
    graphCell?.textCharPrFace?.hangul ??
    baseline?.face?.hangul ??
    null;
  const size =
    region?.charPrHeightPt ??
    graphCell?.textCharPrHeightPt ??
    baseline?.height_pt ??
    null;
  return {
    face: face && face.trim() ? face.trim() : null,
    sizePt: typeof size === "number" && Number.isFinite(size) && size > 0 ? size : null,
  };
}

/** Status-bar text for a character shape, as the 서식 도구 bar shows it:
 * face then size with one decimal (`함초롬바탕 10.0pt`). Null when neither is known. */
export function formatCharShape(shape: CharShape): string | null {
  const size = shape.sizePt === null ? null : `${shape.sizePt.toFixed(1)}pt`;
  const parts = [shape.face, size].filter((part): part is string => !!part);
  return parts.length > 0 ? parts.join(" ") : null;
}

export function formatSeatLocation(
  page: number | null | undefined,
  table: number,
  row: number,
  col: number,
  lang: UiLanguage = "ko",
): string {
  if (isKnownPage(page)) {
    return wp3t("seat_location_short", lang, [page, table + 1, row + 1, col + 1]);
  }
  return wp3t("seat_location_no_page", lang, [table + 1, row + 1, col + 1]);
}

export interface SeatLocationGroup<
  S extends Pick<PageSeat, "page" | "table"> = PageSeat,
> {
  key: string;
  page: number | null;
  table: number;
  heading: string;
  seats: S[];
}

export function groupSeatsByLocation<
  S extends Pick<PageSeat, "page" | "table">,
>(
  seats: readonly S[],
  lang: UiLanguage = "ko",
): SeatLocationGroup<S>[] {
  const groups = new Map<string, SeatLocationGroup<S>>();
  for (const seat of seats) {
    const page = isKnownPage(seat.page) ? seat.page : null;
    const table = seat.table;
    const key = `${page ?? "unknown"}:t${table}`;
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        page,
        table,
        heading: formatSeatGroupHeading(page, table, lang),
        seats: [],
      };
      groups.set(key, group);
    }
    group.seats.push(seat);
  }
  return [...groups.values()];
}

export function resolveSeatPages(
  seats: readonly PageSeat[],
  pageSource?: Pick<PageSource, "kind" | "seats"> | null,
  lang: UiLanguage = "ko",
  knownPages?: ReadonlyMap<string, number>,
): PageSeat[] {
  const byKey = new Map<string, number>();
  const byAddress = new Map<string, number>();
  if (knownPages) {
    for (const [k, p] of knownPages.entries()) {
      if (isKnownPage(p)) {
        byKey.set(k, p);
        byAddress.set(k, p);
      }
    }
  }
  if (pageSource) {
    for (const s of pageSource.seats()) {
      if (isKnownPage(s.page)) {
        if (s.key) byKey.set(s.key, s.page);
        if (s.address) byAddress.set(s.address, s.page);
      }
    }
  }
  return seats.map((seat) => {
    const rawPage =
      byKey.get(seat.key) ??
      byAddress.get(seat.address) ??
      (isKnownPage(seat.page) ? seat.page : null);
    const page = isKnownPage(rawPage) ? rawPage : null;
    const locationLabel = formatSeatLocation(
      page,
      seat.table,
      seat.row,
      seat.col,
      lang,
    );
    const cellLocationLabel = formatSeatCellLocation(
      seat.row,
      seat.col,
      lang,
    );
    if (
      seat.page === page &&
      seat.locationLabel === locationLabel &&
      seat.cellLocationLabel === cellLocationLabel
    ) {
      return seat;
    }
    return {
      ...seat,
      page,
      locationLabel,
      cellLocationLabel,
    };
  });
}

function estimateCellRectPt(
  size: PageSizePt,
  tableIndex: number,
  row: number,
  col: number,
  totalRows: number,
  maxCols: number,
): PageRectPt {
  const usableW = Math.max(100, size.widthPt - size.marginPt.left - size.marginPt.right);
  const usableH = Math.max(100, size.heightPt - size.marginPt.top - size.marginPt.bottom);
  const rowH = Math.max(20, Math.min(44, usableH / Math.max(1, totalRows + 2)));
  const colW = Math.max(24, usableW / Math.max(1, maxCols));
  const y = Math.min(
    size.heightPt - size.marginPt.bottom - rowH,
    size.marginPt.top + (tableIndex * 40 + row * rowH),
  );
  const x = Math.min(size.widthPt - size.marginPt.right - colW, size.marginPt.left + col * colW);
  return { x, y, w: colW, h: rowH };
}

export function detectDocumentSeats(
  inspect: InspectResult | null | undefined,
  textMap: Record<string, RegionText>,
  changes: readonly CanvasChangeRef[],
  lang: UiLanguage = "ko",
  sizePt?: PageSizePt,
  measuredRects?: ReadonlyMap<string, PageRectPt>,
  seatPages?: ReadonlyMap<string, number>,
): PageSeat[] {
  if (!inspect) return [];
  const size = sizePt ?? sizeFromInspect(inspect);
  const formCtx = extractFormInstructionContext(inspect, textMap);

  const regionByKey = new Map<
    string,
    (typeof inspect.regions.regions)[number]
  >();
  for (const reg of inspect.regions.regions) {
    if (
      reg.kind === "cell" &&
      typeof reg.row === "number" &&
      typeof reg.col === "number"
    ) {
      regionByKey.set(legacyCellKey(reg.table ?? 0, reg.row, reg.col), reg);
    }
  }

  const changeByCell = new Map<string, CanvasChangeRef>();
  for (const ch of changes) {
    if (ch.cellKey && ch.decision !== "rejected") {
      changeByCell.set(ch.cellKey, ch);
    }
  }

  interface RawSeat {
    key: string;
    table: number;
    row: number;
    col: number;
    baseLabel: string;
    group: "primary" | "agency";
    isFillTarget: boolean;
    beforeText: string;
    currentText: string;
    filled: boolean;
    hasFormText: boolean;
    charPr?: string;
    charPrSuggested?: string;
    scriptAnomaly?: boolean;
    colorAnomaly?: boolean;
    fontCategory: "serif" | "sans";
    fontFace?: string | null;
    rect: PageRectPt;
  }

  const rawSeats: RawSeat[] = [];
  const seenKeys = new Set<string>();

  for (const tbl of inspect.graph.tables) {
    const maxRow = tbl.cells.reduce((m, c) => Math.max(m, c.addr.row), 0) + 1;
    const maxCol = tbl.cells.reduce((m, c) => Math.max(m, c.addr.col), 0) + 1;
    const sortedCells = [...tbl.cells].sort(
      (a, b) => a.addr.row - b.addr.row || a.addr.col - b.addr.col,
    );

    for (const cell of sortedCells) {
      if (cell.classification === "spacer") continue;
      const key = legacyCellKey(tbl.index, cell.addr.row, cell.addr.col);
      if (seenKeys.has(key)) continue;

      const reg = regionByKey.get(key);
      const isRow0CornerSpacer =
        tbl.index === 0 &&
        cell.addr.row === 0 &&
        cell.classification === "fill_target" &&
        tbl.cells.some((c) => c.addr.row === 0 && c.classification === "guide");
      const regionText = textMap[key]?.text ?? cell.textPreview ?? "";
      const isFillTarget = cell.classification === "fill_target" && !isRow0CornerSpacer;
      const placeholderSlot =
        !isFillTarget && isPlaceholderSlot(cell, key, regionText, formCtx);
      // A printed label at the top of the cell with room for the value under
      // it (T273): the blank is under the label, and the label names it.
      const underLabel =
        !isFillTarget && !placeholderSlot && cell.labelTop
          ? regionText.split("\n").slice(0, cell.labelTop.paras).join("\n")
          : null;

      if (!isFillTarget && !placeholderSlot && !underLabel?.trim()) continue;
      seenKeys.add(key);

      const fallbackOrd = rawSeats.length + 1;
      const derivedFallback = deriveCellFieldLabel(
        inspect,
        textMap,
        tbl.index,
        cell.addr.row,
        cell.addr.col,
        lang,
        fallbackOrd,
      );
      let baseLabel = derivedFallback;
      if (underLabel) {
        const leadToken = labelFromCellText(underLabel.replace(/\n/g, " ").trim());
        baseLabel = truncateLabel(leadToken || underLabel.trim(), 20);
      } else if (placeholderSlot && regionText.trim().length > 0) {
        // `전화번호(   )` → `전화번호`: the empty slot goes before the field split.
        const leadToken = labelFromCellText(regionText.trim());
        if (leadToken.length > 0) {
          baseLabel = truncateLabel(leadToken, 20);
        }
      }

      const change = changeByCell.get(key);
      const beforeText = regionText;
      const currentText = change ? change.after : beforeText;
      const isAgency = isAgencyUseLabelOrText(baseLabel, regionText);
      // A bracket the form printed under the label (`(    )`) is not a value.
      const filled = underLabel
        ? (belowLabelValue(currentText, underLabel) ?? "").replace(/[\s()（）[\]]/g, "").length > 0
        : change
          ? change.after.trim().length > 0 && change.after.trim() !== beforeText.trim()
          : isFillTarget && beforeText.trim().length > 0;

      const faceName =
        reg?.charPrFace?.hangul ??
        inspect.summary?.baselineCharPr?.face?.hangul ??
        null;

      const rect =
        measuredRects?.get(key) ??
        estimateCellRectPt(
          size,
          tbl.index,
          cell.addr.row,
          cell.addr.col,
          maxRow,
          maxCol,
        );

      rawSeats.push({
        key,
        table: tbl.index,
        row: cell.addr.row,
        col: cell.addr.col,
        baseLabel,
        group: isAgency ? "agency" : "primary",
        isFillTarget,
        beforeText,
        currentText,
        filled,
        hasFormText: beforeText.trim().length > 0,
        charPr: reg?.charPr ?? cell.charPr,
        charPrSuggested: reg?.charPrSuggested ?? cell.charPrSuggested,
        scriptAnomaly: reg?.scriptAnomaly ?? cell.scriptAnomaly,
        colorAnomaly: reg?.colorAnomaly ?? cell.colorAnomaly,
        fontCategory: resolvePageFontCategory(faceName),
        fontFace: faceName,
        rect,
      });
    }
  }

  const disambiguated = disambiguateBlankLabels(rawSeats);
  return disambiguated.map((seat) => {
    const address = formatCellAddress(seat.table, seat.row, seat.col);
    const rawPage = seatPages?.get(seat.key) ?? seatPages?.get(address) ?? null;
    const page = isKnownPage(rawPage) ? rawPage : null;
    return {
      id: seat.key,
      key: seat.key,
      address,
      table: seat.table,
      row: seat.row,
      col: seat.col,
      page,
      baseLabel: seat.baseLabel,
      displayLabel: seat.displayLabel,
      cellLocationLabel: formatSeatCellLocation(seat.row, seat.col, lang),
      locationLabel: formatSeatLocation(page, seat.table, seat.row, seat.col, lang),
      duplicateIndex: seat.duplicateIndex,
      duplicateTotal: seat.duplicateTotal,
      group: seat.group,
      filled: seat.filled,
      hasFormText: seat.hasFormText,
      isFillTarget: seat.isFillTarget,
      beforeText: seat.beforeText,
      currentText: seat.currentText,
      charPr: seat.charPr,
      charPrSuggested: seat.charPrSuggested,
      scriptAnomaly: seat.scriptAnomaly,
      colorAnomaly: seat.colorAnomaly,
      fontCategory: seat.fontCategory,
      fontFace: seat.fontFace,
      rect: seat.rect,
    };
  });
}

function formatMarkRange(items: readonly CanvasChangeRef[]): string | null {
  if (items.length === 0) return null;
  const sorted = [...items].sort((a, b) => a.n - b.n);
  if (sorted.length === 1) return String(sorted[0].n);
  const first = sorted[0].n;
  const last = sorted[sorted.length - 1].n;
  if (last - first + 1 === sorted.length) {
    return `${first}–${last}`;
  }
  return sorted.map((c) => c.n).join(", ");
}

function summarizeOutlineChanges(items: readonly CanvasChangeRef[]): {
  itemIds: string[];
  markRange: string | null;
  hasFact: boolean;
  hasWarning: boolean;
  allDecided: boolean;
} {
  return {
    itemIds: items.map((c) => c.id),
    markRange: formatMarkRange(items),
    hasFact: items.some((c) => c.isFactChanged),
    hasWarning: items.some(
      (c) =>
        c.hard ||
        c.guard === "needs_fixes" ||
        c.source === "test" ||
        c.isStale,
    ),
    allDecided: items.length > 0 && items.every((c) => c.decision !== "pending"),
  };
}

function matchFormSectionKey(
  cellText: string,
  cell: GraphCell,
  tableIndex: number,
): keyof typeof FORM_SECTION_LABEL_KEYS | null {
  const collapsed = collapseFormGuideLabel(cellText).replace(/\s+/g, "");
  if (tableIndex === 2 || collapsed.includes(FORM_OUTLINE_TOKENS.sender)) {
    return "closing";
  }
  if (
    cell.classification === "guide" &&
    (collapsed.includes(FORM_OUTLINE_TOKENS.rulePrefix) ||
      collapsed.includes(FORM_OUTLINE_TOKENS.formNumberPrefix))
  ) {
    return "head";
  }
  if (
    collapsed.includes(FORM_OUTLINE_TOKENS.orgName) &&
    collapsed.includes(FORM_OUTLINE_TOKENS.recipient)
  ) {
    return "opening";
  }
  if (
    collapsed.includes(FORM_OUTLINE_TOKENS.drafter) ||
    collapsed.includes(FORM_OUTLINE_TOKENS.reviewer) ||
    collapsed.includes(FORM_OUTLINE_TOKENS.approver)
  ) {
    return "signers";
  }
  if (collapsed === FORM_OUTLINE_TOKENS.coop) return "coop";
  if (
    collapsed === FORM_OUTLINE_TOKENS.dispatch ||
    collapsed === FORM_OUTLINE_TOKENS.receipt
  ) {
    return "dispatch";
  }
  if (
    collapsed.includes(FORM_OUTLINE_TOKENS.postal) ||
    collapsed.includes(FORM_OUTLINE_TOKENS.phone) ||
    collapsed.includes(FORM_OUTLINE_TOKENS.email)
  ) {
    return "contact";
  }
  if (collapsed.startsWith(FORM_OUTLINE_TOKENS.note)) return "note";
  return null;
}

const FORM_SECTION_LABEL_KEYS = {
  head: "outline_form_head",
  opening: "outline_form_opening",
  body: "outline_form_body",
  closing: "outline_form_closing",
  signers: "outline_form_signers",
  coop: "outline_form_coop",
  dispatch: "outline_form_dispatch",
  contact: "outline_form_contact",
  note: "outline_form_note",
} as const;

export function extractDocumentOutline(
  inspect: InspectResult | null | undefined,
  textMap: Record<string, RegionText>,
  changes: readonly CanvasChangeRef[],
  lang: UiLanguage = "ko",
): OutlineNode[] {
  if (!inspect) return [];
  const nodes: OutlineNode[] = [];
  const formCtx = extractFormInstructionContext(inspect, textMap);

  if (formCtx.isFormDocument && inspect.graph.tables.length > 0) {
    const t0 = inspect.graph.tables[0];
    const rowSections = new Map<number, keyof typeof FORM_SECTION_LABEL_KEYS>();
    const rowFirstKey = new Map<number, string>();
    const rowFirstAddr = new Map<number, string>();

    for (const cell of t0.cells) {
      const k = legacyCellKey(t0.index, cell.addr.row, cell.addr.col);
      if (!rowFirstKey.has(cell.addr.row)) {
        rowFirstKey.set(cell.addr.row, k);
        rowFirstAddr.set(cell.addr.row, formatCellAddress(t0.index, cell.addr.row, cell.addr.col));
      }
      const txt = textMap[k]?.text ?? cell.textPreview ?? "";
      const sec = matchFormSectionKey(txt, cell, t0.index);
      if (sec && !rowSections.has(cell.addr.row)) {
        rowSections.set(cell.addr.row, sec);
      }
      if (cell.classification === "fill_target" && cell.addr.row === 2 && cell.addr.col === 0) {
        rowSections.set(cell.addr.row, "body");
      }
    }

    const rowNumbers = [...new Set(t0.cells.map((c) => c.addr.row))].sort((a, b) => a - b);
    const seenSections = new Set<string>();

    for (const r of rowNumbers) {
      const sec = rowSections.get(r);
      if (!sec || seenSections.has(sec)) continue;
      seenSections.add(sec);

      const cellKeysInRow = t0.cells
        .filter((c) => c.addr.row === r)
        .map((c) => legacyCellKey(t0.index, c.addr.row, c.addr.col));

      if (sec === "opening") {
        const openingKey = legacyCellKey(t0.index, r, 0);
        const openingChanges = changes.filter((c) => c.cellKey === openingKey);
        nodes.push({
          id: `outline-sec-opening`,
          title: wp3t("outline_form_opening", lang),
          depth: 1,
          page: 1,
          address: rowFirstAddr.get(r),
          cellKey: openingKey,
          kind: "section",
          ...summarizeOutlineChanges([]),
        });
        const runs = textMap[openingKey]?.runs ?? [];
        const subItems: Array<{ title: string; runIdx: number }> = [
          { title: FORM_OUTLINE_TOKENS.orgName, runIdx: 0 },
          { title: FORM_OUTLINE_TOKENS.recipient, runIdx: 1 },
          { title: FORM_OUTLINE_TOKENS.subject, runIdx: 3 },
        ];
        for (const sub of subItems) {
          if (runs.some((rn) => rn.index === sub.runIdx) || openingChanges.some((c) => c.run === sub.runIdx)) {
            const subChanges = openingChanges.filter((c) => c.run === sub.runIdx);
            nodes.push({
              id: `outline-opening-${sub.runIdx}`,
              title: sub.title,
              depth: 2,
              page: 1,
              address: rowFirstAddr.get(r),
              cellKey: openingKey,
              kind: "form",
              ...summarizeOutlineChanges(subChanges),
            });
          }
        }
        continue;
      }

      if (sec === "body") {
        const bodyKey = legacyCellKey(t0.index, r, 0);
        const bodyChanges = changes.filter((c) => c.cellKey === bodyKey);
        nodes.push({
          id: "outline-sec-body",
          title: wp3t("outline_form_body", lang),
          depth: 1,
          page: 1,
          address: rowFirstAddr.get(r),
          cellKey: bodyKey,
          kind: "section",
          ...summarizeOutlineChanges(bodyChanges),
        });
        const bodyText =
          bodyChanges.find((c) => c.decision !== "rejected")?.after ??
          textMap[bodyKey]?.text ??
          "";
        for (const [lineIdx, rawLine] of bodyText.split(/\r?\n/).entries()) {
          const line = rawLine.trim();
          if (!line) continue;
          if (/^\d+\.\s+/.test(line)) {
            nodes.push({
              id: `outline-body-l${lineIdx}`,
              title: truncateLabel(line.split(":")[0].slice(0, 22), 20),
              depth: 2,
              page: 1,
              address: rowFirstAddr.get(r),
              cellKey: bodyKey,
              kind: "heading",
              ...summarizeOutlineChanges([]),
            });
          } else if (KOREAN_SUBCLAUSE_LINE_RE.test(line)) {
            nodes.push({
              id: `outline-body-l${lineIdx}`,
              title: truncateLabel(line.split(":")[0], 20),
              depth: 3,
              page: 1,
              address: rowFirstAddr.get(r),
              cellKey: bodyKey,
              kind: "heading",
              ...summarizeOutlineChanges([]),
            });
          } else if (line.startsWith(FORM_OUTLINE_TOKENS.attachment)) {
            nodes.push({
              id: `outline-body-attach`,
              title: FORM_OUTLINE_TOKENS.attachment,
              depth: 2,
              page: 1,
              address: rowFirstAddr.get(r),
              cellKey: bodyKey,
              kind: "heading",
              ...summarizeOutlineChanges([]),
            });
          }
        }

        // Insert closing/sender table right after body if table 2 exists (matches the base mockup's order)
        const closingTable = inspect.graph.tables.find((t) => t.index === 2);
        if (closingTable) {
          const ck = legacyCellKey(closingTable.index, 0, 0);
          const closingChanges = changes.filter((c) => c.cellKey === ck);
          nodes.push({
            id: "outline-sec-closing",
            title: wp3t("outline_form_closing", lang),
            depth: 1,
            page: 1,
            address: formatCellAddress(closingTable.index, 0, 0),
            cellKey: ck,
            kind: "section",
            ...summarizeOutlineChanges(closingChanges),
          });
        }
        continue;
      }

      const rowChanges = changes.filter((c) => c.cellKey && cellKeysInRow.includes(c.cellKey));
      nodes.push({
        id: `outline-sec-${sec}`,
        title: wp3t(FORM_SECTION_LABEL_KEYS[sec], lang),
        depth: 1,
        page: 1,
        address: rowFirstAddr.get(r),
        cellKey: rowFirstKey.get(r),
        kind: "section",
        ...summarizeOutlineChanges(rowChanges),
      });
    }
  } else {
    // Non-form documents: extract headings from paragraphs and tables from graph
    for (const para of inspect.graph.paragraphs) {
      const txt = para.text.trim();
      if (!txt) continue;
      const mdMatch = /^(#{1,3})\s+(.+)$/.exec(txt);
      const numMatch = /^(\d+\.\s+.+)$/.exec(txt);
      const subMatch = KOREAN_SUBCLAUSE_LINE_RE.exec(txt);
      if (mdMatch || numMatch || subMatch) {
        const depth = (mdMatch ? Math.min(3, mdMatch[1].length) : subMatch ? 3 : 1) as 1 | 2 | 3;
        const title = mdMatch ? mdMatch[2] : txt;
        const pChanges = changes.filter((c) => c.atPara === para.at_para);
        nodes.push({
          id: `outline-p-${para.at_para}`,
          title: truncateLabel(title, 26),
          depth,
          page: 1,
          address: formatParaAddress(para.at_para),
          kind: "heading",
          ...summarizeOutlineChanges(pChanges),
        });
      }
    }
  }

  // Always include table summary entries when not already represented as form blocks
  if (!formCtx.isFormDocument && inspect.graph.tables.length > 0) {
    for (const tbl of inspect.graph.tables) {
      const prefix = `c:${tbl.index}:`;
      const tblChanges = changes.filter((c) => c.cellKey?.startsWith(prefix));
      nodes.push({
        id: `outline-tbl-${tbl.index}`,
        title: wp3t("outline_table_item", lang, [tbl.index + 1]),
        depth: 1,
        page: 1,
        address: formatCellAddress(tbl.index, 0, 0),
        cellKey: legacyCellKey(tbl.index, 0, 0),
        kind: "table",
        ...summarizeOutlineChanges(tblChanges),
      });
    }
  }

  return nodes;
}

export function sizeFromInspect(inspect: InspectResult | null | undefined): PageSizePt {
  const pm = inspect?.summary?.pageMetrics;
  return {
    widthPt: hwpunitToPt(pm?.width, DEFAULT_A4_WIDTH_PT),
    heightPt: hwpunitToPt(pm?.height, DEFAULT_A4_HEIGHT_PT),
    marginPt: {
      top: hwpunitToPt(pm?.margin?.top, 56.69),
      right: hwpunitToPt(pm?.margin?.right, 56.69),
      bottom: hwpunitToPt(pm?.margin?.bottom, 28.35),
      left: hwpunitToPt(pm?.margin?.left, 56.69),
    },
  };
}

export interface ProjectionPageSourceOptions {
  inspect: InspectResult | null;
  texts: readonly RegionText[];
  textMap: Record<string, RegionText>;
  changes: readonly CanvasChangeRef[];
  render?: RenderResult | null;
  geometry?: GeometryResult | null;
  rev?: string;
  language?: UiLanguage;
  measuredRects?: ReadonlyMap<string, PageRectPt>;
}

export function createProjectionPageSource({
  inspect,
  textMap,
  changes,
  render = null,
  geometry = null,
  rev = "base",
  language = "ko",
  measuredRects,
}: ProjectionPageSourceOptions): PageSource {
  const pageSize = sizeFromInspect(inspect);
  const totalPages = Math.max(1, render?.pageCount ?? geometry?.pageCount ?? 1);
  const cachedSeats = detectDocumentSeats(
    inspect,
    textMap,
    changes,
    language,
    pageSize,
    measuredRects,
  );
  const cachedOutline = extractDocumentOutline(inspect, textMap, changes, language);
  const cachedFonts = collectPageFonts(inspect, render, language);

  const seatRectByKey = new Map<string, PageRectPt>();
  for (const s of cachedSeats) {
    seatRectByKey.set(s.key, s.rect);
  }

  const resolveChangeRect = (ch: CanvasChangeRef): PageRectPt => {
    if (ch.rects && ch.rects.length > 0) {
      return ch.rects[0].rect;
    }
    if (ch.cellKey && measuredRects?.has(ch.cellKey)) {
      return measuredRects.get(ch.cellKey)!;
    }
    if (ch.cellKey && seatRectByKey.has(ch.cellKey)) {
      return seatRectByKey.get(ch.cellKey)!;
    }
    const parsed = parseDocAddress(ch.at);
    if (parsed?.kind === "cell") {
      return estimateCellRectPt(size(1), parsed.table, parsed.row, parsed.col, 11, 14);
    }
    if (parsed?.kind === "para") {
      const idx = Math.max(0, parsed.atPara);
      return {
        x: pageSize.marginPt.left,
        y: Math.min(pageSize.heightPt - pageSize.marginPt.bottom - 20, pageSize.marginPt.top + idx * 18),
        w: pageSize.widthPt - pageSize.marginPt.left - pageSize.marginPt.right,
        h: 18,
      };
    }
    return {
      x: pageSize.marginPt.left,
      y: pageSize.marginPt.top,
      w: pageSize.widthPt - pageSize.marginPt.left - pageSize.marginPt.right,
      h: 20,
    };
  };

  function size(_page: number): PageSizePt {
    return pageSize;
  }

  function boxes(page: number): PageBox[] {
    if (page < 1 || page > totalPages) return [];
    const out: PageBox[] = [];
    for (const s of cachedSeats) {
      out.push({
        id: `seat-${s.key}`,
        address: s.address,
        kind: "seat",
        rect: s.rect,
        label: s.displayLabel,
        fontCategory: s.fontCategory,
      });
    }
    for (const ch of changes) {
      if (ch.page !== page) continue;
      out.push({
        id: `mark-${ch.id}`,
        itemId: ch.id,
        address: ch.at,
        kind: "mark",
        rect: resolveChangeRect(ch),
        label: ch.label,
      });
    }
    return out;
  }

  function layer(page: number, view: PageViewMode): PageLayer {
    const marks: PageMarkItem[] =
      view === "marks"
        ? changes
            .filter((ch) => ch.page === page)
            .map((ch) => ({
              itemId: ch.id,
              n: ch.n,
              address: ch.at,
              source: ch.source,
              decision: ch.decision,
              isFactChanged: ch.isFactChanged,
              isStale: Boolean(ch.isStale),
              rect: resolveChangeRect(ch),
            }))
        : [];
    return {
      page,
      view,
      kind: "projection",
      rev,
      sizePt: pageSize,
      marks,
      boxes: boxes(page),
    };
  }

  function changedRects(itemId: string): Array<{ page: number; rect: PageRectPt }> {
    const ch = changes.find((c) => c.id === itemId);
    if (!ch) return [];
    if (ch.rects && ch.rects.length > 0) return ch.rects;
    return [{ page: ch.page, rect: resolveChangeRect(ch) }];
  }

  function hitTest(page: number, xPt: number, yPt: number): PageHitResult {
    const contains = (r: PageRectPt) =>
      xPt >= r.x && xPt <= r.x + r.w && yPt >= r.y && yPt <= r.y + r.h;

    for (const ch of changes) {
      if (ch.page !== page) continue;
      const r = resolveChangeRect(ch);
      if (contains(r)) {
        return {
          kind: "mark",
          page,
          pointPt: { x: xPt, y: yPt },
          address: ch.at,
          seatKey: ch.cellKey,
          itemId: ch.id,
        };
      }
    }
    for (const seat of cachedSeats) {
      if (seat.page !== null && seat.page !== page) continue;
      if (contains(seat.rect)) {
        return {
          kind: "seat",
          page,
          pointPt: { x: xPt, y: yPt },
          address: seat.address,
          seatKey: seat.key,
        };
      }
    }
    return { kind: "none", page, pointPt: { x: xPt, y: yPt } };
  }

  function caretRect(page: number, address: string, offset: number): PageRectPt | null {
    const parsed = parseDocAddress(address);
    if (!parsed || page < 1 || page > totalPages) return null;
    if (parsed.kind === "cell") {
      const key = legacyCellKey(parsed.table, parsed.row, parsed.col);
      const rect = measuredRects?.get(key) ?? seatRectByKey.get(key);
      if (!rect) return null;
      const clampedX = Math.min(rect.x + rect.w - 2, rect.x + Math.max(0, offset) * 5);
      return { x: clampedX, y: rect.y + 2, w: 1.5, h: Math.max(10, rect.h - 4) };
    }
    return null;
  }

  return {
    kind: "projection",
    grade: render?.grade ?? "own-uncertified",
    rev,
    pageCount: () => totalPages,
    size,
    layer,
    boxes,
    changedRects,
    hitTest,
    caretRect,
    seats: () => cachedSeats,
    outline: () => cachedOutline,
    fonts: () => cachedFonts,
  };
}
