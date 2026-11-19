/**
 * The Rigorloom mark (리을R) for the v2 shell, start tab and narrow header.
 *
 * Drawn inline so it inherits `currentColor` and can draw itself. The drawing
 * of record is `src/assets/logo.svg`; its 16-px cut is `logo-16.svg`. Both are
 * one centre line, so the same path serves the still mark and the entrance
 * stroke. At 20 px and below the 16-px cut is used: stroke 2 on whole units,
 * which keeps the stem and the inner leg apart at title-bar size.
 *
 * The v1 screens keep `components/Logo` until the switch to v2.
 */
const FULL = "M3.25 14.5V2.25H9A2.75 2.75 0 0 1 11.75 5V5.5A2.75 2.75 0 0 1 9 8.25H6.75V13.75H13.5";
const CUT16 = "M3 15V2H10A2 2 0 0 1 12 4V6A2 2 0 0 1 10 8H7V14H14";

export interface MarkProps {
  /** Pixel square edge length (16 title bar, 20 touch, 40 start tab, 72 splash). */
  size?: number;
  /** Draw the thread in once, stem first, instead of showing it already drawn. */
  draw?: boolean;
  className?: string;
}

export function Mark({ size = 16, draw = false, className = "" }: MarkProps) {
  const small = size <= 20;
  return (
    <svg
      className={`rl-mark ${draw ? "rl-mark-draw" : ""} ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={small ? 2 : 1.5}
      strokeLinecap="butt"
      strokeLinejoin="miter"
      shapeRendering={small ? "crispEdges" : undefined}
      role="img"
      aria-label="Rigorloom"
      data-testid="logo"
    >
      <path className="rl-thread" pathLength={100} d={small ? CUT16 : FULL} />
    </svg>
  );
}

export interface WordmarkProps {
  className?: string;
}

/** Text wordmark aligned to Pretendard SemiBold chrome metrics. */
export function Wordmark({ className = "" }: WordmarkProps) {
  return (
    <span className={`rl-brand-wordmark ${className}`.trim()} data-testid="brand-wordmark">
      Rigorloom
    </span>
  );
}
