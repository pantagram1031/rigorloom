import {
  cloneElement,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
} from "react";

import { cn } from "./cn";
import { layerFixedStyle, placeLayer } from "./place";
import { Portal } from "./Portal";

type TriggerProps = {
  onMouseEnter?: (e: MouseEvent) => void;
  onMouseLeave?: (e: MouseEvent) => void;
  onFocus?: (e: FocusEvent) => void;
  onBlur?: (e: FocusEvent) => void;
  className?: string;
};

export type TooltipProps = {
  content: ReactNode;
  children: ReactElement<TriggerProps>;
  delay?: number;
  open?: boolean;
  defaultOpen?: boolean;
  disablePortal?: boolean;
  className?: string;
  anchorClassName?: string;
  anchorStyle?: CSSProperties;
};

/**
 * `<Tooltip content="…"><button/></Tooltip>`
 * Delay 400 ms on hover, immediate on focus. Adds aria-describedby while open.
 */
export function Tooltip({
  content,
  children,
  delay = 400,
  open: openProp,
  defaultOpen = false,
  disablePortal = false,
  className,
  anchorClassName,
  anchorStyle,
}: TooltipProps) {
  const id = useId();
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const tipRef = useRef<HTMLSpanElement | null>(null);
  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const controlled = openProp !== undefined;
  const open = controlled ? openProp : uncontrolled;
  const [coords, setCoords] = useState<{ top: number; left: number; side: "top" | "bottom" }>({
    top: 0,
    left: 0,
    side: "top",
  });
  const hoverTimer = useRef(0);

  const setOpen = (next: boolean) => {
    if (!controlled) setUncontrolled(next);
  };

  useEffect(() => {
    if (!open || disablePortal) return;
    const trigger = triggerRef.current;
    const tip = tipRef.current;
    if (!trigger || !tip || typeof window === "undefined") return;
    const t = trigger.getBoundingClientRect();
    const c = tip.getBoundingClientRect();
    const placed = placeLayer(
      { top: t.top, left: t.left, bottom: t.bottom, right: t.right, width: t.width, height: t.height },
      { width: c.width || 120, height: c.height || 28 },
      "top",
      "center",
      8,
      { width: window.innerWidth, height: window.innerHeight },
    );
    setCoords({ top: placed.top, left: placed.left, side: placed.side === "bottom" ? "bottom" : "top" });
  }, [open, disablePortal, content]);

  useEffect(() => () => window.clearTimeout(hoverTimer.current), []);

  const child = children;
  const trigger = cloneElement(child, {
    "aria-describedby": open ? id : undefined,
    "data-tip": typeof content === "string" ? content : undefined,
    onMouseEnter: (e: MouseEvent) => {
      child.props.onMouseEnter?.(e);
      window.clearTimeout(hoverTimer.current);
      hoverTimer.current = window.setTimeout(() => setOpen(true), delay) as unknown as number;
    },
    onMouseLeave: (e: MouseEvent) => {
      child.props.onMouseLeave?.(e);
      window.clearTimeout(hoverTimer.current);
      setOpen(false);
    },
    onFocus: (e: FocusEvent) => {
      child.props.onFocus?.(e);
      window.clearTimeout(hoverTimer.current);
      setOpen(true);
    },
    onBlur: (e: FocusEvent) => {
      child.props.onBlur?.(e);
      setOpen(false);
    },
  } as Partial<TriggerProps> & { "aria-describedby"?: string; "data-tip"?: string });

  const style: CSSProperties | undefined = disablePortal
    ? undefined
    : layerFixedStyle(coords);

  return (
    <span className={cn("ui-tooltip-anchor", anchorClassName)} style={anchorStyle} ref={triggerRef}>
      {trigger}
      {open ? (
        <Portal disabled={disablePortal}>
          <span
            ref={tipRef}
            id={id}
            role="tooltip"
            data-state="open"
            data-side={coords.side}
            className={cn("ui-tooltip", className)}
            style={style}
          >
            {content}
          </span>
        </Portal>
      ) : null}
    </span>
  );
}
