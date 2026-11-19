import { Logo } from "../components/Logo";

export interface MarkProps {
  /** Pixel square edge length (default 16 for title bar, 20 for touch, 72 for splash). */
  size?: number;
  /** Play the entrance stroke animation when true. */
  draw?: boolean;
  className?: string;
}

/**
 * Product mark wrapper exposed for v2 shell, start tab, and narrow header.
 *
 * Per the advisor ruling (ADVISOR-RULING §F), the shipped weave mark stays
 * untouched everywhere until the user selects a replacement from the WP1b
 * candidate sheet. Centralizing `<Mark size>` here lets every v2 package consume
 * the final contract today without changing brand assets prematurely.
 */
export function Mark({ size = 16, draw = false, className = "" }: MarkProps) {
  return <Logo size={size} draw={draw} className={className} />;
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
