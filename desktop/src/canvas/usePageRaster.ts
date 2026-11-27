import { useEffect, useRef, useState } from "react";

import {
  pageRasterScale, type EngineGeometry, type EngineTextEdit, type PagePreview,
  type RenderedPage, type RasterSource,
} from "../model/enginePage";
import { browserToken, call, isTauri, tokenHeaders } from "../runtime";
import type { FontCheckRow } from "../model/fontInstall";
import { isPageMeasured, publishMeasuredPage } from "./controller";

type RenderInfo = Omit<RenderedPage, "url">;
type PageReply =
  | (RenderInfo & { blob?: Blob })
  | { source: "projection"; rev: string; seq: number; page: number };
type PageIdentity = { sessionId: string; rev: string };
const STORED_SOURCES = new Set<string>(["engine", "hancom", "pdf", "own-uncertified"]);
const RENDER_TIMEOUT_MS = 12_000;

function hasCode(error: unknown, code: string): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === code;
}

async function requestPage<T>(
  operation: string,
  params: PageIdentity & {
    page?: number; scale?: number; previewId?: string; ops?: EngineTextEdit[];
    faces?: string[]; source?: RasterSource | "projection"; refresh?: boolean; refreshFonts?: "1";
  },
  signal: AbortSignal,
): Promise<T> {
  if (isTauri()) {
    const result = await call<T & { imageId?: string; imageBytes?: number; seq?: number }>(
      "document/pageView", { operation, ...params },
    );
    if (!result.imageId || !result.imageBytes) return result;
    const chunks: Uint8Array<ArrayBuffer>[] = [];
    let offset = 0;
    while (offset < result.imageBytes) {
      signal.throwIfAborted();
      const chunk = await call<{ png: string; rev: string; seq: number; offset: number }>("document/pageView", {
        operation: "image", sessionId: params.sessionId, rev: params.rev, imageId: result.imageId, offset,
      });
      if (chunk.rev !== params.rev || chunk.seq !== result.seq || chunk.offset !== offset) {
        throw new Error("Unexpected page image chunk");
      }
      const bytes = Uint8Array.from(atob(chunk.png), (ch) => ch.charCodeAt(0));
      if (!bytes.length || offset + bytes.length > result.imageBytes) throw new Error("Invalid page image chunk");
      chunks.push(bytes);
      offset += bytes.length;
    }
    return { ...result, blob: new Blob(chunks, { type: "image/png" }) };
  }
  const options: RequestInit = { headers: tokenHeaders(), signal };
  let path = `/api/doc/${operation}`;
  if (operation === "preview" || operation === "fonts") {
    options.method = "POST";
    options.headers = tokenHeaders({ "Content-Type": "application/json" });
    options.body = JSON.stringify(params);
  } else {
    path += `?${new URLSearchParams(Object.entries(params).map(([key, value]) => [key, String(value)]))}`;
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw body?.error ?? new Error(String(response.status));
  }
  if (operation === "render" && response.headers.get("Content-Type") === "image/png") {
    const header = (name: string) => response.headers.get(`X-Rigorloom-${name}`);
    const info: RenderInfo = {
      rev: header("Rev") ?? "",
      seq: Number(header("Seq")),
      page: Number(header("Page")),
      count: Number(header("Page-Count")) || undefined,
      approx: header("Approx") === "1",
      widthPt: Number(header("Width-Pt")),
      heightPt: Number(header("Height-Pt")),
      source: header("Source") as RasterSource,
      previewId: header("Preview-Id") ?? undefined,
      previewRev: header("Preview-Rev") ?? undefined,
    };
    return { ...info, blob: await response.blob() } as T;
  }
  return response.json();
}

export function requestPageFonts(
  params: PageIdentity & { faces: string[]; source: RasterSource | "projection"; refresh: boolean },
  signal: AbortSignal,
) {
  return requestPage<{ rev: string; faces: FontCheckRow[] }>("fonts", params, signal);
}

async function retrySuperseded<T>(request: () => Promise<T>, signal: AbortSignal): Promise<T> {
  try {
    return await request();
  } catch (error) {
    if (!hasCode(error, "render_superseded")) throw error;
    signal.throwIfAborted();
    return request();
  }
}

type HeldRaster = {
  sessionId: string; frame: RenderedPage; geometry: EngineGeometry | null; scale: number;
  edits: EngineTextEdit[];
  fontRefresh: number;
};
type PreviewRects = NonNullable<EngineGeometry["changed"]>;

export function usePageRaster(
  sessionId: string | undefined, rev: string | undefined, page: number, zoom: number | null,
  edits: readonly EngineTextEdit[], fontRefresh: number,
) {
  const [held, setHeld] = useState<HeldRaster | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [changed, setChanged] = useState<{ key: string; rects: PreviewRects } | null>(null);
  const [settled, setSettled] = useState<{ key: string; count?: number } | null>(null);
  const shown = useRef<HeldRaster | null>(null);
  const measured = useRef<{ key: string; value: EngineGeometry | null } | null>(null);
  const cachedPreview = useRef<{ key: string; value: PagePreview } | null>(null);
  const lastSequence = useRef({ sessionId: "", seq: 0 });
  const [pixelRatio, setPixelRatio] = useState(() => window.devicePixelRatio || 1);

  useEffect(() => {
    const query = window.matchMedia(`(resolution: ${pixelRatio}dppx)`);
    const update = () => setPixelRatio(window.devicePixelRatio || 1);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, [pixelRatio]);

  const enabled = Boolean(browserToken() || isTauri());
  const scale = zoom === null ? null : pageRasterScale(zoom, pixelRatio);
  const editKey = edits.length ? JSON.stringify(edits) : "";
  const previewKey = `${sessionId}:${rev}:${fontRefresh}:${editKey}`;
  const requestKey = `${previewKey}:${page}:${scale}`;
  useEffect(() => {
    if (!enabled || !sessionId || !rev || scale === null) return;
    const pending = new AbortController();
    const { signal } = pending;
    const accept = (seq: number) => !signal.aborted && Number.isSafeInteger(seq) &&
      seq > (lastSequence.current.sessionId === sessionId ? lastSequence.current.seq : 0);
    const settle = (count?: number) => {
      setSettled({ key: requestKey, count });
      setFailure(null);
    };
    const preparePreview = async () => {
      if (!editKey) return null;
      if (cachedPreview.current?.key === previewKey) return cachedPreview.current.value;
      const ops: EngineTextEdit[] = JSON.parse(editKey);
      const value = await retrySuperseded(
        () => requestPage<PagePreview>("preview", { sessionId, rev, ops }, signal), signal,
      );
      signal.throwIfAborted();
      if (value.rev !== rev) throw new Error("Unexpected preview revision");
      cachedPreview.current = { key: previewKey, value };
      return value;
    };

    const draw = async () => {
      const preview = await preparePreview();
      if (preview && page > preview.count) {
        settle(preview.count);
        return;
      }
      const previewId = preview?.changedPages.includes(page) ? preview.previewId : undefined;
      const previewRev = previewId ? preview?.previewRev : undefined;
      const params = { sessionId, rev, page, ...(previewId ? { previewId } : {}) };
      const current = shown.current;
      if (preview && !previewId && current?.sessionId === sessionId && current.frame.rev === rev &&
          current.frame.page === page && current.scale === scale && !current.frame.previewId && current.fontRefresh === fontRefresh) {
        settle(preview.count);
        return;
      }

      const measure = async (): Promise<EngineGeometry | null> => {
        const key = `${sessionId}:${rev}:${fontRefresh}:${page}:${previewId ?? ""}`;
        if (measured.current?.key === key) return measured.current.value;
        const result = await requestPage<EngineGeometry>("geometry", params, signal).catch(() => null);
        const value = result?.rev === rev && result.page === page &&
          result.previewId === previewId && result.previewRev === previewRev ? result : null;
        if (!signal.aborted && value) measured.current = { key, value };
        return value;
      };

      // Resolve the preview's marks while the old PNG is still displayed.
      const previewGeometry = previewId ? measure().then((geometry) => {
        if (!signal.aborted) {
          setChanged({ key: requestKey, rects: geometry?.changed ?? preview?.changed ?? [] });
        }
        return geometry;
      }) : null;
      if (previewId) setChanged({ key: requestKey, rects: preview?.changed ?? [] });

      const result = await retrySuperseded(
        () => requestPage<PageReply>("render", {
          ...params, scale, ...(fontRefresh ? { refreshFonts: "1" } : {}),
        }, signal), signal,
      );
      if (result.rev !== rev || result.page !== page || !accept(result.seq)) return;
      if (result.source === "projection") {
        if (previewId) throw new Error("Expected an engine preview raster");
        lastSequence.current = { sessionId, seq: result.seq };
        shown.current = null;
        setHeld(null);
        settle();
        return;
      }
      if (result.previewId !== previewId || result.previewRev !== previewRev ||
          !STORED_SOURCES.has(result.source) || !(result.widthPt > 0 && result.heightPt > 0) ||
          !result.blob) throw new Error("Unexpected page raster");
      const url = URL.createObjectURL(result.blob);
      let adopted = false;
      try {
        const image = new Image();
        image.src = url;
        const [geometry] = await Promise.all([
          previewGeometry ?? (result.source === "engine" ? measure() : null),
          image.decode(),
        ]);
        if (!accept(result.seq)) return;
        lastSequence.current = { sessionId, seq: result.seq };
        const { source, seq, page, count, approx, widthPt, heightPt } = result;
        const next = { sessionId, geometry, scale, fontRefresh, edits: previewId ? JSON.parse(editKey) as EngineTextEdit[] : [],
          frame: { rev, source, seq, page, count, approx, widthPt, heightPt, url, previewId, previewRev } };
        shown.current = next;
        adopted = true;
        setHeld(next);
        settle(preview?.count ?? count);
      } finally {
        if (!adopted) URL.revokeObjectURL(url);
      }
    };

    // Continuous zoom gestures reach the renderer as one request. Edits were
    // already debounced by the text control.
    const debounce = window.setTimeout(() => {
      const deadline = window.setTimeout(() => {
        pending.abort();
        setFailure(requestKey);
      }, RENDER_TIMEOUT_MS);
      void draw().catch((error) => {
        if (!signal.aborted && hasCode(error, "preview_expired")) {
          cachedPreview.current = null;
          return draw();
        }
        throw error;
      }).catch((error) => {
        if (!signal.aborted && !hasCode(error, "render_superseded")) setFailure(requestKey);
      }).finally(() => window.clearTimeout(deadline));
      signal.addEventListener("abort", () => window.clearTimeout(deadline), { once: true });
    }, editKey ? 0 : 100);
    return () => {
      window.clearTimeout(debounce);
      pending.abort();
    };
  }, [enabled, sessionId, rev, page, scale, editKey, previewKey, requestKey, fontRefresh]);

  const url = held?.frame.url;
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  const current = held?.sessionId === sessionId ? held : null;
  const raster = current?.frame ?? null;
  const isSettled = settled?.key === requestKey;
  return {
    raster, geometry: current?.geometry ?? null,
    count: (isSettled ? settled.count : undefined) ?? raster?.count ?? 1,
    approx: Boolean(raster?.approx),
    failed: failure === requestKey,
    settled: isSettled,
    displayedEdits: current?.edits ?? [],
    changed: !isSettled && changed?.key === requestKey ? changed.rects : [],
  };
}

const MEASURED_PAGE_LIMIT = 60;

/** The addresses an engine geometry reply places on its page (lines excluded). */
export function geometryAddresses(geometry: Pick<EngineGeometry, "boxes">): string[] {
  const out: string[] = [];
  for (const box of geometry.boxes ?? []) {
    if (box.kind === "line") continue;
    const address = box.queueAddress ?? box.at;
    if (address) out.push(address);
  }
  return out;
}

/**
 * Once the drawn page has settled as an engine raster, measure the other pages
 * of this revision one at a time so that finding, the blanks list and the
 * change list know which page holds what, before the user opens those pages.
 * Failed pages stay unknown.
 */
export function useMeasureOtherPages(
  sessionId: string | undefined, rev: string | undefined, count: number,
  drawnPage: number | null,
) {
  const enabled = Boolean(browserToken() || isTauri());
  useEffect(() => {
    if (!enabled || drawnPage === null || !sessionId || !rev || count < 2) return;
    // The drawn page's own boxes reach the known pages through its layer.
    publishMeasuredPage(rev, drawnPage, []);
    const pending = new AbortController();
    const { signal } = pending;
    const last = Math.min(count, MEASURED_PAGE_LIMIT);
    void (async () => {
      for (let page = 1; page <= last; page += 1) {
        if (signal.aborted) return;
        if (isPageMeasured(rev, page)) continue;
        const geometry: EngineGeometry | null = await requestPage<EngineGeometry>("geometry", { sessionId, rev, page }, signal)
          .catch(() => null);
        if (signal.aborted) return;
        if (geometry?.rev === rev && geometry.page === page && !geometry.previewId) {
          publishMeasuredPage(rev, page, geometryAddresses(geometry));
        }
      }
    })();
    return () => pending.abort();
  }, [enabled, drawnPage, sessionId, rev, count]);
}
