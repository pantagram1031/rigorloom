interface PageGuidesProps {
  width: number;
  height: number;
  zoom: number;
  margins: { top: number; right: number; bottom: number; left: number };
}

const pxPerMillimeter = 96 / 25.4;

function Ruler({ length, start, end, vertical = false, zoom }: {
  length: number; start: number; end: number; vertical?: boolean; zoom: number;
}) {
  const scale = pxPerMillimeter * zoom;
  const interval = zoom < 0.65 ? 5 : 2;
  const ticks = Array.from({ length: Math.floor(length / (scale * interval)) + 1 }, (_, i) => i * interval);
  const size = vertical ? { height: length, width: "var(--h-ruler)" } : { width: length, height: "var(--h-ruler)" };
  return (
    <svg className={vertical ? "rl-ruler-v" : "rl-ruler-h"} style={size}>
      <rect className="rl-ruler-body" x={vertical ? 0 : start} y={vertical ? start : 0}
        width={vertical ? "100%" : Math.max(0, end - start)} height={vertical ? Math.max(0, end - start) : "100%"} />
      {ticks.map((mm) => {
        const pos = mm * scale;
        const major = mm % (zoom < 0.65 ? 20 : 10) === 0;
        const tick = major ? 7 : 3;
        return <g key={mm}>
          {vertical
            ? <path d={`M 0 ${pos} h ${tick}`} />
            : <path d={`M ${pos} 0 v ${tick}`} />}
          {major ? <text x={vertical ? 7 : pos + 2} y={vertical ? pos + 10 : 15}>{mm / 10}</text> : null}
        </g>;
      })}
    </svg>
  );
}

export function PageGuides({ width, height, zoom, margins }: PageGuidesProps) {
  const left = margins.left * zoom;
  const right = width - margins.right * zoom;
  const top = margins.top * zoom;
  const bottom = height - margins.bottom * zoom;
  const length = Math.max(5, 13 * zoom);
  return (
    <div className="rl-page-guides" aria-hidden="true">
      <span className="rl-ruler-corner">cm</span>
      <Ruler length={width} start={left} end={right} zoom={zoom} />
      <Ruler length={height} start={top} end={bottom} zoom={zoom} vertical />
      <svg className="rl-cropmarks" width={width} height={height}>
        <path d={`
          M ${left - length} ${top} h ${length} v ${-length}
          M ${right + length} ${top} h ${-length} v ${-length}
          M ${left - length} ${bottom} h ${length} v ${length}
          M ${right + length} ${bottom} h ${-length} v ${length}
        `} />
      </svg>
    </div>
  );
}
