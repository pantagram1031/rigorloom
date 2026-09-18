import {
  createContext,
  forwardRef,
  useContext,
  useId,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type HTMLAttributes,
  type ReactNode,
} from "react";

import { cn } from "./cn";
import { placeLayer, type LayerAlign, type LayerSide } from "./place";
import { Portal } from "./Portal";
import type { SlotRef } from "./ref";
import { mergeRefs } from "./ref";
import { useLayer, useOpenState } from "./useLayer";

type PopoverCtx = {
  open: boolean;
  setOpen: (open: boolean) => void;
  triggerRef: SlotRef<HTMLElement>;
  contentRef: SlotRef<HTMLElement>;
  contentId: string;
  disablePortal: boolean;
};

const Ctx = createContext<PopoverCtx | null>(null);

function usePopover(): PopoverCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("Popover parts must be used inside Popover");
  return ctx;
}

export type PopoverProps = {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  disablePortal?: boolean;
  children?: ReactNode;
};

export function Popover({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  disablePortal = false,
  children,
}: PopoverProps) {
  const [open, setOpen] = useOpenState(openProp, defaultOpen, onOpenChange);
  const triggerRef = useRef<HTMLElement | null>(null);
  const contentRef = useRef<HTMLElement | null>(null);
  const contentId = useId();
  useLayer({ open, onClose: () => setOpen(false), triggerRef, contentRef, modal: false });
  return (
    <Ctx.Provider value={{ open, setOpen, triggerRef, contentRef, contentId, disablePortal }}>
      <span className="ui-popover">{children}</span>
    </Ctx.Provider>
  );
}

export const PopoverTrigger = forwardRef<HTMLButtonElement, HTMLAttributes<HTMLButtonElement>>(
  function PopoverTrigger({ className, children, onClick, ...rest }, ref) {
    const ctx = usePopover();
    return (
      <button
        ref={mergeRefs(ref, ctx.triggerRef)}
        type="button"
        className={cn("ui-btn ui-btn-secondary ui-btn-md", className)}
        aria-haspopup="dialog"
        aria-expanded={ctx.open}
        aria-controls={ctx.contentId}
        data-state={ctx.open ? "open" : "closed"}
        onClick={(e) => {
          e.stopPropagation();
          onClick?.(e);
          ctx.setOpen(!ctx.open);
        }}
        {...rest}
      >
        {children}
      </button>
    );
  },
);

export type PopoverContentProps = HTMLAttributes<HTMLDivElement> & {
  side?: LayerSide;
  align?: LayerAlign;
  forceMount?: boolean;
};

export function PopoverContent({
  side = "bottom",
  align = "center",
  className,
  children,
  forceMount,
  ...rest
}: PopoverContentProps) {
  const ctx = usePopover();
  const [coords, setCoords] = useState({ top: 0, left: 0, side });

  useEffect(() => {
    if (!ctx.open || ctx.disablePortal) return;
    const trigger = ctx.triggerRef.current;
    const content = ctx.contentRef.current;
    if (!trigger || !content || typeof window === "undefined") return;
    const t = trigger.getBoundingClientRect();
    const c = content.getBoundingClientRect();
    const placed = placeLayer(
      { top: t.top, left: t.left, bottom: t.bottom, right: t.right, width: t.width, height: t.height },
      { width: c.width || 200, height: c.height || 80 },
      side,
      align,
      10,
      { width: window.innerWidth, height: window.innerHeight },
    );
    setCoords(placed);
  }, [ctx.open, ctx.disablePortal, ctx.triggerRef, ctx.contentRef, side, align]);

  if (!ctx.open && !forceMount) return null;

  const style: CSSProperties | undefined = ctx.disablePortal
    ? undefined
    : { position: "fixed", top: coords.top, left: coords.left };

  return (
    <Portal disabled={ctx.disablePortal}>
      <div
        ref={(node) => {
          ctx.contentRef.current = node;
        }}
        id={ctx.contentId}
        role="dialog"
        tabIndex={-1}
        hidden={!ctx.open || undefined}
        data-state={ctx.open ? "open" : "closed"}
        data-side={coords.side}
        className={cn(className, "ui-popover-content")}
        style={style}
        {...rest}
      >
        <span className="ui-layer-arrow" data-side={coords.side} aria-hidden="true" />
        {children}
      </div>
    </Portal>
  );
}
