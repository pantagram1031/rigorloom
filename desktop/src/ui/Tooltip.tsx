import { useId, useState, type KeyboardEvent, type ReactNode } from "react";

import { Keycap } from "./Keycap";
import { isImeComposing, principleAttributes } from "./attributes";

export interface TooltipProps {
  label: ReactNode;
  shortcut?: string | readonly string[];
  side?: "top" | "bottom";
  /** Force open state (useful for deterministic screenshot testing). */
  open?: boolean;
  children: ReactNode;
  className?: string;
}

/**
 * Compact tooltip (`--raised`, `--shadow-float`, `--radius-md` 6 px, `--text-sm` 12 px)
 * for icon-only controls such as panel toggles `◧ ◨` and close buttons.
 */
export function Tooltip({
  label,
  shortcut,
  side = "bottom",
  open: controlledOpen,
  children,
  className = "",
}: TooltipProps) {
  const tooltipId = useId();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const visible = controlledOpen ?? (hovered || focused);

  const handleKeyDown = (event: KeyboardEvent<HTMLSpanElement>) => {
    if (isImeComposing(event)) return;
    if (event.key === "Escape" && (hovered || focused)) {
      setHovered(false);
      setFocused(false);
    }
  };

  return (
    <span
      className={`rl-tooltip-anchor ${className}`.trim()}
      aria-describedby={visible ? tooltipId : undefined}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      onKeyDown={handleKeyDown}
    >
      {children}
      {visible ? (
        <span
          id={tooltipId}
          role="tooltip"
          className={`rl-tooltip rl-tooltip--${side}`}
          {...principleAttributes({ floating: true })}
        >
          <span className="rl-tooltip-label">{label}</span>
          {shortcut ? <Keycap keys={shortcut} /> : null}
        </span>
      ) : null}
    </span>
  );
}
