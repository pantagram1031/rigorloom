/**
 * One inline SVG set for the shell. currentColor, 16/20 px, stroke 1.5.
 * Icons accompany labels except on the collapsed rail.
 */
export const ICON_NAMES = [
  "home",
  "open",
  "save",
  "undo",
  "check",
  "warn",
  "x",
  "chevron-down",
  "chevron-right",
  "chevron-left",
  "search",
  "list",
  "table",
  "cell",
  "bot",
  "receipt",
  "compare",
  "history",
  "settings",
] as const;

export type IconName = (typeof ICON_NAMES)[number];

type Stroke = { d: string; fill?: undefined };
type Fill = { d: string; fill: true };
type Circle = { cx: number; cy: number; r: number; fill?: true };
type Glyph = Array<Stroke | Fill | Circle>;

const GLYPHS: Record<IconName, Glyph> = {
  home: [
    { d: "M2.75 7.2 8 2.8l5.25 4.4V13.2H9.4V9.7H6.6v3.5H2.75Z" },
  ],
  open: [
    { d: "M2.6 4.4h4.1l1.4 1.5h5.3v7.6H2.6Z" },
    { d: "M2.6 7.4h10.8" },
  ],
  save: [
    { d: "M8 2.6v7.2" },
    { d: "M5.2 7.4 8 10.2l2.8-2.8" },
    { d: "M3.2 13.4h9.6" },
  ],
  undo: [
    { d: "M4.6 6.8H10a3.2 3.2 0 0 1 0 6.4H8.2" },
    { d: "M4.6 6.8 2.6 4.9M4.6 6.8 2.6 8.7" },
  ],
  check: [{ d: "M3.4 8.3 6.6 11.4 12.6 4.8" }],
  warn: [
    { d: "M8 2.8 13.7 13.2H2.3Z" },
    { d: "M8 6.6v3.2" },
    { d: "M8 11.5h.01" },
  ],
  x: [{ d: "M4.2 4.2 11.8 11.8M11.8 4.2 4.2 11.8" }],
  "chevron-down": [{ d: "M4.2 6.4 8 10.2l3.8-3.8" }],
  "chevron-right": [{ d: "M6.4 4.2 10.2 8 6.4 11.8" }],
  "chevron-left": [{ d: "M9.6 4.2 5.8 8l3.8 3.8" }],
  search: [
    { cx: 7, cy: 7, r: 4.1 },
    { d: "M10.2 10.2 13.4 13.4" },
  ],
  list: [
    { d: "M3.2 4.4h9.6M3.2 8h9.6M3.2 11.6h9.6" },
  ],
  table: [
    { d: "M2.8 3.2h10.4v9.6H2.8Z" },
    { d: "M2.8 7.2h10.4M8 3.2v9.6" },
  ],
  cell: [
    { d: "M2.8 3.2h10.4v9.6H2.8Z" },
    { d: "M2.8 7.2h10.4M8 3.2v9.6" },
    { d: "M8 7.2h5.2v5.6H8Z", fill: true },
  ],
  bot: [
    { d: "M4 5.6h8v6.4H4Z" },
    { d: "M8 3.2v2.4" },
    { cx: 6.2, cy: 8.1, r: 0.7, fill: true },
    { cx: 9.8, cy: 8.1, r: 0.7, fill: true },
    { d: "M6.4 10.6h3.2" },
  ],
  receipt: [
    { d: "M5 2.6h5.2L12.8 5.2v8.2H5Z" },
    { d: "M10.2 2.6v2.6h2.6" },
    { d: "M6.6 8h4.2M6.6 10.2h4.2" },
  ],
  compare: [
    { d: "M3.2 3.6h4v8.8h-4Z" },
    { d: "M8.8 3.6h4v8.8h-4Z" },
    { d: "M5.2 7.2h5.6M9.4 5.6 11.2 7.2 9.4 8.8" },
  ],
  history: [
    { cx: 8, cy: 8.2, r: 5.2 },
    { d: "M8 5.6v3.1l2.2 1.3" },
    { d: "M5.2 3.4 3.8 5" },
  ],
  settings: [
    { cx: 8, cy: 8, r: 2.1 },
    { d: "M8 2.6v1.8M8 11.6v1.8M2.6 8h1.8M11.6 8h1.8M4.2 4.2l1.3 1.3M10.5 10.5l1.3 1.3M11.8 4.2l-1.3 1.3M5.5 10.5 4.2 11.8" },
  ],
};

export function Icon({
  name,
  size = 16,
  className = "",
}: {
  name: IconName;
  size?: 16 | 20;
  className?: string;
}) {
  const glyph = GLYPHS[name];
  return (
    <svg
      className={`icon${className ? ` ${className}` : ""}`}
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      data-icon={name}
    >
      {glyph.map((part, i) =>
        "cx" in part ? (
          <circle
            key={i}
            cx={part.cx}
            cy={part.cy}
            r={part.r}
            fill={part.fill ? "currentColor" : "none"}
          />
        ) : (
          <path key={i} d={part.d} fill={part.fill ? "currentColor" : "none"} />
        ),
      )}
    </svg>
  );
}
