import { useEffect, useRef, useState } from "react";

import { pageRasterScale, type EngineGeometry, type RenderedPage, type RasterSource } from "../model/enginePage";
import { browserToken, call, isTauri, tokenHeaders } from "../runtime";

type RenderInfo = Omit<RenderedPage, "url">;
type PageReply =
  | (RenderInfo & { png?: string; blob?: Blob })
  | { source: "projection"; rev: string; seq: number; page: number };
const STORED_SOURCES = new Set<string>(["engine", "hancom", "pdf", "own-uncertified"]);
const RENDER_TIMEOUT_MS = 12_000;

async function requestPage<T>(
  operation: string,
  params: Record<string, string | number>,
  signal: AbortSignal,
): Promise<T> {
  if (isTauri()) return call<T>("document/pageView", { operation, ...params });
  const query = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
  const response = await fetch(`/api/doc/${operation}?${query}`, { headers: tokenHeaders(), signal });
  if (!response.ok) throw new Error(String(response.status));
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
    };
    return { ...info, blob: await response.blob() } as T;
  }
  return response.json();
}

type HeldRaster = { sessionId: string; frame: RenderedPage; geometry: EngineGeometry | null };

export function usePageRaster(
  sessionId: string | undefined, rev: string | undefined, page: number, zoom: number | null,
) {
  const [held, setHeld] = useState<HeldRaster | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const measured = useRef<{ key: string; value: EngineGeometry | null } | null>(null);
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
  const requestKey = `${sessionId}:${rev}:${page}:${scale}`;
  useEffect(() => {
    if (!enabled || !sessionId || !rev || scale === null) return;
    const pending = new AbortController();
    const accept = (seq: number) => !pending.signal.aborted && Number.isSafeInteger(seq) &&
      seq > (lastSequence.current.sessionId === sessionId ? lastSequence.current.seq : 0);

    const measure = async (): Promise<EngineGeometry | null> => {
      const key = `${sessionId}:${rev}:${page}`;
      if (measured.current?.key === key) return measured.current.value;
      const result = await requestPage<EngineGeometry>("geometry", { sessionId, rev, page }, pending.signal)
        .catch(() => null);
      const value = result?.rev === rev && result.page === page ? result : null;
      if (!pending.signal.aborted) measured.current = { key, value };
      return value;
    };

    // Collapse continuous zoom gestures before they reach the renderer.
    const debounce = window.setTimeout(() => {
      const deadline = window.setTimeout(() => {
        pending.abort();
        setFailure(requestKey);
      }, RENDER_TIMEOUT_MS);

      void (async () => {
        const result = await requestPage<PageReply>(
          "render", { sessionId, rev, page, scale }, pending.signal,
        );
        if (result.rev !== rev || result.page !== page || !accept(result.seq)) return;
        if (result.source === "projection") {
          lastSequence.current = { sessionId, seq: result.seq };
          setHeld(null);
          setFailure(null);
          return;
        }
        if (!STORED_SOURCES.has(result.source) || !(result.widthPt > 0 && result.heightPt > 0)) throw new Error();
        const blob = result.blob;
        const url = blob ? URL.createObjectURL(blob) : `data:image/png;base64,${result.png ?? ""}`;
        let adopted = false;
        try {
          const image = new Image();
          image.src = url;
          const [geometry] = await Promise.all([
            result.source === "engine" ? measure() : null,
            image.decode(),
          ]);
          if (!accept(result.seq)) return;
          lastSequence.current = { sessionId, seq: result.seq };
          adopted = true;
          const { source, seq, page, count, approx, widthPt, heightPt } = result;
          setHeld({ sessionId, geometry, frame: { rev, source, seq, page, count, approx, widthPt, heightPt, url } });
          setFailure(null);
        } finally {
          if (!adopted && blob) URL.revokeObjectURL(url);
        }
      })().catch(() => {
        if (!pending.signal.aborted) setFailure(requestKey);
      }).finally(() => window.clearTimeout(deadline));
      // Native calls cannot be aborted by the browser's AbortController.
      pending.signal.addEventListener("abort", () => window.clearTimeout(deadline), { once: true });
    }, 100);
    return () => {
      window.clearTimeout(debounce);
      pending.abort();
    };
  }, [enabled, sessionId, rev, page, scale, requestKey]);

  const url = held?.frame.url;
  useEffect(() => () => {
    if (url?.startsWith("blob:")) URL.revokeObjectURL(url);
  }, [url]);

  const current = held?.sessionId === sessionId ? held : null;
  const raster = current?.frame ?? null;
  return {
    raster, geometry: current?.geometry ?? null,
    count: raster?.count ?? 1,
    approx: Boolean(raster?.approx),
    failed: failure === requestKey,
  };
}
