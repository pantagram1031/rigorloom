/**
 * The v1 weave mark, inline so it can inherit `currentColor` and be animated.
 *
 * The v1 screens (top bar, splash, boot) keep this mark until the switch to
 * editor v2; it is no longer the drawing of record and no longer the source of
 * the icon set. The product mark is now 리을R: `brand/Mark.tsx`, drawn from
 * `src/assets/logo.svg`, and `desktop/scripts/make_icons.py` generates the
 * Tauri icons and the favicon from its 16-px cut. This component only adds the
 * class hooks the entrance animation drives (`.rl-warp-a` … `.rl-leg`, drawn in
 * the order a loom is dressed) and `pathLength="100"` so stroke-dashoffset
 * needs no measurement.
 */
export function Logo({
  size = 20,
  draw = false,
  className = "",
}: {
  size?: number;
  /** Weave the strokes in rather than showing them already drawn. */
  draw?: boolean;
  className?: string;
}) {
  return (
    <svg
      className={`mark ${draw ? "mark-draw" : ""} ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth={3}
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label="Rigorloom"
      data-testid="logo"
    >
      <path className="rl-warp-a" pathLength={100} d="M11 4 V18.25" />
      <path className="rl-warp-a" pathLength={100} d="M11 23.75 V28" />
      <path className="rl-warp-b" pathLength={100} d="M21 4 V8.25" />
      <path className="rl-warp-b" pathLength={100} d="M21 13.75 V21" />
      <path className="rl-weft-a" pathLength={100} d="M4 11 H8.25" />
      <path className="rl-weft-a" pathLength={100} d="M13.75 11 H28" />
      <path className="rl-weft-b" pathLength={100} d="M4 21 H21" />
      <path className="rl-leg" pathLength={100} d="M21 21 L28 28" />
    </svg>
  );
}
