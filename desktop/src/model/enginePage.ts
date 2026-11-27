import type {
  CanvasChangeRef,
  PageBox,
  PageHitResult,
  PageRectPt,
  PageSource,
  PageViewMode,
} from "./page";
import type { QueuedOp } from "../store";

export const MAX_PAGE_SCALE = 3;
export const ENGINE_PX_PER_PT = 96 / 72;

export function pageRasterScale(zoom: number, pixelRatio: number): number {
  return Math.min(MAX_PAGE_SCALE, zoom * pixelRatio);
}

export function engineLineFontSizePx(
  line: Pick<EngineBox, "rect" | "vertical">,
  sizePt?: number | null,
): number {
  if (typeof sizePt === "number" && Number.isFinite(sizePt) && sizePt > 0) {
    return sizePt * ENGINE_PX_PER_PT;
  }
  const { w, h } = rectPt(line.rect);
  return Math.min(18, Math.max(10, (line.vertical ? w : h) * ENGINE_PX_PER_PT));
}

export type RasterSource = "engine" | "hancom" | "pdf" | "own-uncertified";
export type RectTuple = [number, number, number, number];

export interface RenderedPage {
  rev: string;
  seq: number;
  page: number;
  count?: number;
  approx?: boolean;
  widthPt: number;
  heightPt: number;
  source: RasterSource;
  url: string;
  previewId?: string;
  previewRev?: string;
}

export type EngineTextEdit = { at: string; text: string; run?: number; before?: string };

export interface PagePreview {
  rev: string;
  seq: number;
  previewId: string;
  previewRev: string;
  count: number;
  changedPages: number[];
  changed: NonNullable<EngineGeometry["changed"]>;
}

export interface EngineGeometry {
  rev: string;
  page: number;
  width_pt: number;
  height_pt: number;
  boxes: EngineBox[];
  previewId?: string;
  previewRev?: string;
  changed?: Array<{ i: number; page: number; rect: RectTuple | null }>;
}

export interface EngineBox {
  at: string | null;
  queueAddress?: string;
  kind: "para" | "line" | "table" | "cell" | "place";
  rect: RectTuple;
  text?: string;
  xs?: number[];
  ys?: number[];
  vertical?: boolean;
  start?: number;
}

export function engineTextEdit(op: QueuedOp): EngineTextEdit[] {
  if (op.kind === "set_run") {
    return [{ at: `p${op.atPara}`, run: op.run, before: op.before, text: op.text }];
  }
  if (op.kind === "fill_cell" || (op.kind === "replace_at_cell" && op.run === undefined)) {
    const text = op.kind === "fill_cell" ? op.lines?.join("\n") ?? op.text
      : op.mode === "append" ? op.before + op.text : op.text;
    return [{ at: `t${op.table}/r${op.row}/c${op.col}`, text }];
  }
  return [];
}

export function rectPt([x, y, w, h]: RectTuple): PageRectPt {
  return { x, y, w, h };
}

function contains({ x, y, w, h }: PageRectPt, px: number, py: number): boolean {
  return px >= x && px <= x + w && py >= y && py <= y + h;
}

function paragraphAddress(address: string): string {
  return address.replace(/#L\d+$/, "");
}

interface Line {
  id: string;
  address: string;
  rect: PageRectPt;
  vertical: boolean;
  positions: number[];
  start: number;
  /** A line holding only an object's control glyph (a table, say); its box spans the whole object. */
  object: boolean;
}

// The engine emits a table or other object anchored in a paragraph as one
// control glyph whose line box spans the whole object.
const OBJECT_GLYPH = "\u25a3";

function linesFromGeometry(geometry: EngineGeometry): Line[] {
  const offsets = new Map<string, number>();
  return geometry.boxes.flatMap((box) => {
    if (box.kind !== "line" || !box.at) return [];
    const address = paragraphAddress(box.at);
    const positions = (box.vertical ? box.ys : box.xs) ?? [];
    const length = box.text === undefined ? Math.max(0, positions.length - 1) : [...box.text].length;
    const start = box.start ?? offsets.get(address) ?? 0;
    offsets.set(address, start + length);
    if (!positions.length) return [];
    return [{
      id: box.at, address, rect: rectPt(box.rect), vertical: Boolean(box.vertical), positions, start,
      object: box.text !== undefined && box.text.trim() === OBJECT_GLYPH,
    }];
  });
}

export interface EnginePageSourceOptions {
  projection: PageSource;
  raster: RenderedPage;
  geometry: EngineGeometry | null;
  count: number;
  changes: readonly CanvasChangeRef[];
}

export function createEnginePageSource({
  projection, raster, geometry, count, changes,
}: EnginePageSourceOptions): PageSource {
  const pageNumber = raster.page;
  // PDF and own-render layers share the projection's existing interaction
  // model. Only engine coordinates can supply character positions.
  const byAddress = new Map<string, PageBox>();
  const boxes: PageBox[] = [];
  for (const [index, box] of (geometry?.boxes ?? []).entries()) {
    const kind = box.kind === "line" ? "para" : box.kind === "place" ? "seat" : box.kind;
    const mapped: PageBox = {
      id: `geometry-${index}`, address: box.queueAddress ?? box.at ?? undefined,
      kind, rect: rectPt(box.rect), label: box.text,
    };
    boxes.push(mapped);
    if (mapped.address && box.kind !== "line" && !byAddress.has(mapped.address)) byAddress.set(mapped.address, mapped);
  }

  const lines = geometry ? linesFromGeometry(geometry) : [];
  const seats = geometry
    ? projection.seats().flatMap((seat) => {
      const box = byAddress.get(seat.address);
      return box ? [{ ...seat, page: pageNumber, rect: box.rect }] : [];
    })
    : projection.seats();
  const marks = projection.layer(pageNumber, "marks").marks.flatMap((mark) => {
    if (!geometry) return [mark];
    const change = changes.find((item) => item.id === mark.itemId);
    const cell = change?.cellKey?.match(/^c:(\d+):(\d+):(\d+)$/);
    const address = cell ? `t${cell[1]}/r${cell[2]}/c${cell[3]}`
      : change?.atPara !== undefined ? `p${change.atPara}` : mark.address;
    const measured = byAddress.get(address);
    return measured ? [{ ...mark, rect: measured.rect }] : [];
  });

  function size(page: number) {
    const base = projection.size(page);
    return page === pageNumber
      ? { ...base, widthPt: raster.widthPt, heightPt: raster.heightPt }
      : base;
  }

  function layer(page: number, view: PageViewMode) {
    if (page !== pageNumber) return projection.layer(page, view);
    return {
      ...projection.layer(page, view),
      kind: "engine" as const,
      rev: raster.rev,
      sizePt: size(page),
      rasterUrl: raster.url,
      marks: view === "marks" ? marks : [],
      boxes: geometry ? boxes : projection.boxes(page),
    };
  }

  function changedRects(itemId: string): ReturnType<PageSource["changedRects"]> {
    if (!geometry) return projection.changedRects(itemId);
    const item = changes.find((change) => change.id === itemId);
    if (geometry.changed && item) {
      return geometry.changed.flatMap(({ i, page, rect }) => (
        i === item.n - 1 && rect ? [{ page, rect: rectPt(rect) }] : []
      ));
    }
    return marks.filter((mark) => mark.itemId === itemId)
      .map((mark) => ({ page: pageNumber, rect: mark.rect }));
  }

  function hitTest(page: number, xPt: number, yPt: number): PageHitResult {
    if (!geometry || page !== pageNumber) return projection.hitTest(page, xPt, yPt);
    const pointPt = { x: xPt, y: yPt };
    const seat = seats.find((entry) => contains(entry.rect, xPt, yPt));
    const mark = marks.find((entry) => contains(entry.rect, xPt, yPt));
    // An object's control glyph is not text to put a caret in: a click in a
    // table cell below its text would otherwise land on the table's left edge.
    const line = lines.filter((entry) => !entry.object && contains(entry.rect, xPt, yPt))
      .sort((a, b) => a.rect.w * a.rect.h - b.rect.w * b.rect.h)[0];
    const para = boxes.find((entry) => entry.kind === "para" && contains(entry.rect, xPt, yPt));
    if (!line && !seat && !mark && !para) return { kind: "none", page, pointPt };
    let lineOffset: number | undefined;
    if (line) {
      const coordinate = line.vertical ? yPt : xPt;
      lineOffset = line.positions.reduce((best, position, i, positions) => (
        Math.abs(position - coordinate) <= Math.abs(positions[best] - coordinate) ? i : best
      ), 0);
    }
    return {
      kind: mark ? "mark" : seat ? "seat" : "para",
      page, pointPt, address: line?.address ?? seat?.address ?? mark?.address ?? para?.address,
      seatKey: seat?.key, itemId: mark?.itemId, lineAddress: line?.id, lineOffset,
      caretOffset: line && lineOffset !== undefined ? line.start + lineOffset : undefined,
    };
  }

  function caretRect(page: number, address: string, offset: number): PageRectPt | null {
    if (!geometry || page !== pageNumber) return projection.caretRect(page, address, offset);
    const line = [...lines].reverse().find((entry) => (
      entry.id === address || (entry.address === address &&
        offset >= entry.start && offset < entry.start + entry.positions.length)
    ));
    if (!line) return null;
    const position = line.positions[line.id === address ? offset : offset - line.start];
    if (position === undefined) return null;
    return line.vertical
      ? { x: line.rect.x, y: position, w: line.rect.w, h: 1 }
      : { x: position, y: line.rect.y, w: 1, h: line.rect.h };
  }

  return {
    ...projection, kind: "engine", rev: raster.rev, grade: raster.source,
    pageCount: () => count,
    size, layer, changedRects, hitTest, caretRect,
    boxes: (page) => page === pageNumber && geometry ? boxes : projection.boxes(page),
    seats: () => seats,
  };
}
