import {
  useEffect,
  useRef,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { isImeComposing, principleAttributes } from "./attributes";

export interface PopoverProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  ariaLabel: string;
  trigger?: ReactNode;
  align?: "start" | "center" | "end";
  side?: "bottom" | "top";
  /** Render popover surface inline without absolute positioning (for static inspection/tests). */
  inline?: boolean;
  children: ReactNode;
}

/**
 * Anchored floating popover (`돌려보내기`, `내보내기`, version switcher — D1 §3c/e).
 *
 * Uses `--raised`, `--shadow-float`, `--radius-md` (6 px), and 120 ms `--dur-pop` transition.
 */
export function Popover({
  open,
  onOpenChange,
  ariaLabel,
  trigger,
  align = "end",
  side = "bottom",
  inline = false,
  className = "",
  children,
  ...rest
}: PopoverProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open || inline) return;
    const onPointerDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        onOpenChange(false);
      }
    };
    const onEscape = (event: globalThis.KeyboardEvent) => {
      if (isImeComposing(event)) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        onOpenChange(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open, inline, onOpenChange]);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    rest.onKeyDown?.(event);
    if (event.defaultPrevented || isImeComposing(event)) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onOpenChange(false);
    }
  };

  return (
    <div ref={wrapRef} className="rl-popover-anchor">
      {trigger}
      {open ? (
        <div
          role="dialog"
          aria-modal={false}
          aria-label={ariaLabel}
          className={[
            "rl-popover",
            `rl-popover--${align}`,
            `rl-popover--${side}`,
            inline ? "rl-popover--inline" : "",
            className,
          ]
            .filter(Boolean)
            .join(" ")}
          {...principleAttributes({ floating: true })}
          {...rest}
          onKeyDown={handleKeyDown}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}
