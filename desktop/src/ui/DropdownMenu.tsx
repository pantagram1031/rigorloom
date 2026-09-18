import {
  createContext,
  forwardRef,
  useContext,
  useId,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { cn, uiTriggerClass } from "./cn";
import { layerFixedStyle, placeLayer, type LayerAlign, type LayerSide } from "./place";
import { Portal } from "./Portal";
import type { SlotRef } from "./ref";
import { mergeRefs } from "./ref";
import { isPrintableTypeahead, moveRoving, typeaheadIndex } from "./roving";
import { useLayer, useOpenState } from "./useLayer";

type MenuCtx = {
  open: boolean;
  setOpen: (open: boolean) => void;
  triggerRef: SlotRef<HTMLElement>;
  contentRef: SlotRef<HTMLElement>;
  contentId: string;
  disablePortal: boolean;
};

const Ctx = createContext<MenuCtx | null>(null);

function useMenu(): MenuCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("DropdownMenu parts must be used inside DropdownMenu");
  return ctx;
}

export type DropdownMenuProps = {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  disablePortal?: boolean;
  children?: ReactNode;
};

export function DropdownMenu({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  disablePortal = false,
  children,
}: DropdownMenuProps) {
  const [open, setOpen] = useOpenState(openProp, defaultOpen, onOpenChange);
  const triggerRef = useRef<HTMLElement | null>(null);
  const contentRef = useRef<HTMLElement | null>(null);
  const contentId = useId();
  useLayer({ open, onClose: () => setOpen(false), triggerRef, contentRef, modal: false });
  return (
    <Ctx.Provider value={{ open, setOpen, triggerRef, contentRef, contentId, disablePortal }}>
      <span className="ui-menu">{children}</span>
    </Ctx.Provider>
  );
}

export const DropdownMenuTrigger = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement>>(
  function DropdownMenuTrigger({ className, children, onClick, ...rest }, ref) {
    const ctx = useMenu();
    return (
      <button
        ref={mergeRefs(ref, ctx.triggerRef)}
        type="button"
        className={uiTriggerClass(className)}
        aria-haspopup="menu"
        aria-expanded={ctx.open}
        aria-controls={ctx.contentId}
        data-state={ctx.open ? "open" : "closed"}
        onClick={(e) => {
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

export type DropdownMenuContentProps = HTMLAttributes<HTMLDivElement> & {
  side?: LayerSide;
  align?: LayerAlign;
};

export function DropdownMenuContent({
  side = "bottom",
  align = "start",
  className,
  children,
  onKeyDown,
  ...rest
}: DropdownMenuContentProps) {
  const ctx = useMenu();
  const [coords, setCoords] = useState({ top: 0, left: 0, side });
  const buf = useRef("");
  const bufAt = useRef(0);

  useEffect(() => {
    if (!ctx.open || ctx.disablePortal) return;
    const trigger = ctx.triggerRef.current;
    const content = ctx.contentRef.current;
    if (!trigger || !content || typeof window === "undefined") return;
    const update = () => {
      const t = trigger.getBoundingClientRect();
      const c = content.getBoundingClientRect();
      const placed = placeLayer(
        { top: t.top, left: t.left, bottom: t.bottom, right: t.right, width: t.width, height: t.height },
        { width: c.width || 180, height: c.height || 120 },
        side,
        align,
        6,
        { width: window.innerWidth, height: window.innerHeight },
      );
      setCoords(placed);
    };
    update();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(update) : null;
    ro?.observe(content);
    window.addEventListener("resize", update);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [ctx.open, ctx.disablePortal, ctx.triggerRef, ctx.contentRef, side, align]);

  const onMenuKey = (e: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(e);
    if (e.defaultPrevented) return;
    const root = ctx.contentRef.current;
    if (!root) return;
    const items = Array.from(root.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])'));
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      const index = items.indexOf(document.activeElement as HTMLElement);
      const next = moveRoving(items.length, index < 0 ? 0 : index, e.key);
      items[next]?.focus();
      return;
    }
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      (document.activeElement as HTMLElement | null)?.click();
      return;
    }
    if (!isPrintableTypeahead(e.key, e)) return;
    const now = Date.now();
    if (now - bufAt.current > 750) buf.current = "";
    buf.current += e.key;
    bufAt.current = now;
    const labels = items.map((el) => el.textContent ?? "");
    const from = items.indexOf(document.activeElement as HTMLElement);
    const next = typeaheadIndex(labels, Math.max(0, from), buf.current);
    items[next]?.focus();
  };

  if (!ctx.open) return null;

  const style: CSSProperties | undefined = ctx.disablePortal
    ? undefined
    : { ...layerFixedStyle(coords), maxHeight: "calc(100vh - 16px)" };

  return (
    <Portal disabled={ctx.disablePortal}>
      <div
        ref={(node) => {
          ctx.contentRef.current = node;
        }}
        id={ctx.contentId}
        role="menu"
        tabIndex={-1}
        data-state="open"
        className={cn("ui-menu-content", className)}
        style={style}
        onKeyDown={onMenuKey}
        {...rest}
      >
        {children}
      </div>
    </Portal>
  );
}

export const DropdownMenuItem = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement>>(
  function DropdownMenuItem({ className, disabled, children, onClick, ...rest }, ref) {
    const ctx = useMenu();
    return (
      <button
        ref={ref}
        type="button"
        role="menuitem"
        className={cn("ui-menu-item", className)}
        disabled={disabled}
        aria-disabled={disabled || undefined}
        onClick={(e) => {
          onClick?.(e);
          if (!e.defaultPrevented) ctx.setOpen(false);
        }}
        {...rest}
      >
        {children}
      </button>
    );
  },
);

export function DropdownMenuSeparator({ className }: { className?: string }) {
  return <div role="separator" className={cn("ui-menu-sep", className)} />;
}

export function DropdownMenuLabel({ className, children }: { className?: string; children?: ReactNode }) {
  return <div className={cn("ui-menu-label", className)}>{children}</div>;
}

export function DropdownMenuShortcut({ className, children }: { className?: string; children?: ReactNode }) {
  return <span className={cn("ui-menu-shortcut", className)}>{children}</span>;
}
