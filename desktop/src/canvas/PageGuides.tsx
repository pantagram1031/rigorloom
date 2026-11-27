import {
  useEffect,
  useLayoutEffect,
  useRef,
  type MutableRefObject,
} from "react";

export interface PageGuidesProps {
  width: number;
  height: number;
  zoom: number;
  margins: { top: number; right: number; bottom: number; left: number };
  scrollContainerRef?: MutableRefObject<HTMLDivElement | null>;
}

const pxPerMillimeter = 96 / 25.4;

function Ruler({
  length,
  start,
  end,
  vertical = false,
  zoom,
  svgRef,
  trackRef,
}: {
  length: number;
  start: number;
  end: number;
  vertical?: boolean;
  zoom: number;
  svgRef: MutableRefObject<SVGSVGElement | null>;
  trackRef: MutableRefObject<SVGGElement | null>;
}) {
  const scale = pxPerMillimeter * zoom;
  const interval = zoom < 0.65 ? 5 : 2;
  const ticks = Array.from(
    { length: Math.floor(length / (scale * interval)) + 1 },
    (_, i) => i * interval,
  );
  return (
    <svg ref={svgRef} className={vertical ? "rl-ruler-v" : "rl-ruler-h"}>
      <g ref={trackRef} className="rl-ruler-track">
        <rect
          className="rl-ruler-body"
          x={vertical ? 0 : start}
          y={vertical ? start : 0}
          width={vertical ? "100%" : Math.max(0, end - start)}
          height={vertical ? Math.max(0, end - start) : "100%"}
        />
        {ticks.map((mm) => {
          const pos = mm * scale;
          const major = mm % (zoom < 0.65 ? 20 : 10) === 0;
          const tick = major ? 7 : 3;
          return (
            <g key={mm}>
              {vertical ? (
                <path d={`M 0 ${pos} h ${tick}`} />
              ) : (
                <path d={`M ${pos} 0 v ${tick}`} />
              )}
              {major ? (
                <text x={vertical ? 7 : pos + 2} y={vertical ? pos + 10 : 15}>
                  {mm / 10}
                </text>
              ) : null}
            </g>
          );
        })}
      </g>
    </svg>
  );
}

export function PageCropMarks({ width, height, zoom, margins }: PageGuidesProps) {
  const left = margins.left * zoom;
  const right = width - margins.right * zoom;
  const top = margins.top * zoom;
  const bottom = height - margins.bottom * zoom;
  const length = Math.max(5, 13 * zoom);
  return (
    <svg className="rl-cropmarks" width={width} height={height} aria-hidden="true">
      <path
        d={`
          M ${left - length} ${top} h ${length} v ${-length}
          M ${right + length} ${top} h ${-length} v ${-length}
          M ${left - length} ${bottom} h ${length} v ${length}
          M ${right + length} ${bottom} h ${-length} v ${length}
        `}
      />
    </svg>
  );
}

export function PageGuides({
  width,
  height,
  zoom,
  margins,
  scrollContainerRef,
}: PageGuidesProps) {
  const hSvgRef = useRef<SVGSVGElement | null>(null);
  const vSvgRef = useRef<SVGSVGElement | null>(null);
  const hTrackRef = useRef<SVGGElement | null>(null);
  const vTrackRef = useRef<SVGGElement | null>(null);

  const left = margins.left * zoom;
  const right = width - margins.right * zoom;
  const top = margins.top * zoom;
  const bottom = height - margins.bottom * zoom;

  const syncRulerOffsets = () => {
    const scroller = scrollContainerRef?.current;
    const hSvg = hSvgRef.current;
    const vSvg = vSvgRef.current;
    const hTrack = hTrackRef.current;
    const vTrack = vTrackRef.current;
    if (!scroller || !hSvg || !vSvg || !hTrack || !vTrack) return;
    const paper = scroller.querySelector<HTMLElement>('[data-testid="paper"]');
    if (!paper) return;
    const paperRect = paper.getBoundingClientRect();
    const hRect = hSvg.getBoundingClientRect();
    const vRect = vSvg.getBoundingClientRect();
    const offsetX = paperRect.left - hRect.left;
    const offsetY = paperRect.top - vRect.top;
    hTrack.style.transform = `translate3d(${offsetX}px, 0, 0)`;
    vTrack.style.transform = `translate3d(0, ${offsetY}px, 0)`;
  };

  useLayoutEffect(() => {
    syncRulerOffsets();
  });

  useEffect(() => {
    const scroller = scrollContainerRef?.current;
    if (!scroller) return;

    let rafId: number | null = null;
    const flush = () => {
      rafId = null;
      syncRulerOffsets();
    };
    const schedule = () => {
      if (rafId !== null) return;
      if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
        rafId = window.requestAnimationFrame(flush);
      } else {
        flush();
      }
    };

    syncRulerOffsets();
    scroller.addEventListener("scroll", schedule, { passive: true });
    if (typeof window !== "undefined") {
      window.addEventListener("resize", schedule);
    }
    const ro =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            syncRulerOffsets();
          })
        : null;
    ro?.observe(scroller);
    const paper = scroller.querySelector<HTMLElement>('[data-testid="paper"]');
    if (paper) ro?.observe(paper);

    return () => {
      scroller.removeEventListener("scroll", schedule);
      if (typeof window !== "undefined") {
        window.removeEventListener("resize", schedule);
      }
      ro?.disconnect();
      if (
        rafId !== null &&
        typeof window !== "undefined" &&
        typeof window.cancelAnimationFrame === "function"
      ) {
        window.cancelAnimationFrame(rafId);
      }
    };
  }, [scrollContainerRef, width, height, zoom]);

  return (
    <div className="rl-page-guides" aria-hidden="true">
      <span className="rl-ruler-corner">cm</span>
      <Ruler
        length={width}
        start={left}
        end={right}
        zoom={zoom}
        svgRef={hSvgRef}
        trackRef={hTrackRef}
      />
      <Ruler
        length={height}
        start={top}
        end={bottom}
        zoom={zoom}
        vertical
        svgRef={vSvgRef}
        trackRef={vTrackRef}
      />
    </div>
  );
}
