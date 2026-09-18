import {
  createContext,
  forwardRef,
  useContext,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";

import { cn, uiTriggerClass } from "./cn";
import { Portal } from "./Portal";
import type { SlotRef } from "./ref";
import { mergeRefs } from "./ref";
import { Tooltip } from "./Tooltip";
import { useLayer, useOpenState } from "./useLayer";

function CloseGlyph() {
  return (
    <svg
      className="icon"
      width={16}
      height={16}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M4.2 4.2 11.8 11.8M11.8 4.2 4.2 11.8" />
    </svg>
  );
}

export type SheetSide = "right" | "left" | "bottom";

type SheetCtx = {
  open: boolean;
  setOpen: (open: boolean) => void;
  triggerRef: SlotRef<HTMLElement>;
  contentRef: SlotRef<HTMLElement>;
  titleId: string;
  descId: string;
  disablePortal: boolean;
  side: SheetSide;
};

const Ctx = createContext<SheetCtx | null>(null);

function useSheet(): SheetCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("Sheet parts must be used inside Sheet");
  return ctx;
}

export type SheetProps = {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  disablePortal?: boolean;
  side?: SheetSide;
  children?: ReactNode;
};

/** Side-panel variant of Dialog. */
export function Sheet({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  disablePortal = false,
  side = "right",
  children,
}: SheetProps) {
  const [open, setOpen] = useOpenState(openProp, defaultOpen, onOpenChange);
  const triggerRef = useRef<HTMLElement | null>(null);
  const contentRef = useRef<HTMLElement | null>(null);
  const uid = useId();
  useLayer({ open, onClose: () => setOpen(false), triggerRef, contentRef, modal: true });
  return (
    <Ctx.Provider
      value={{
        open,
        setOpen,
        triggerRef,
        contentRef,
        titleId: `${uid}-title`,
        descId: `${uid}-desc`,
        disablePortal,
        side,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export const SheetTrigger = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement>>(
  function SheetTrigger({ className, children, onClick, ...rest }, ref) {
    const ctx = useSheet();
    return (
      <button
        ref={mergeRefs(ref, ctx.triggerRef)}
        type="button"
        className={uiTriggerClass(className)}
        aria-haspopup="dialog"
        aria-expanded={ctx.open}
        data-state={ctx.open ? "open" : "closed"}
        onClick={(e) => {
          onClick?.(e);
          ctx.setOpen(true);
        }}
        {...rest}
      >
        {children}
      </button>
    );
  },
);

export function SheetContent({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  const ctx = useSheet();
  if (!ctx.open) return null;
  return (
    <Portal disabled={ctx.disablePortal}>
      <div className="ui-sheet-root" data-state="open" data-side={ctx.side}>
        <div className="ui-dialog-overlay" data-state="open" onMouseDown={() => ctx.setOpen(false)} />
        <div
          ref={(node) => {
            ctx.contentRef.current = node;
          }}
          role="dialog"
          aria-modal="true"
          aria-labelledby={ctx.titleId}
          aria-describedby={ctx.descId}
          tabIndex={-1}
          data-state="open"
          data-side={ctx.side}
          className={cn("ui-sheet", className)}
          onMouseDown={(e) => e.stopPropagation()}
          {...rest}
        >
          {children}
        </div>
      </div>
    </Portal>
  );
}

export function SheetHeader({ className, children }: { className?: string; children?: ReactNode }) {
  return <div className={cn("ui-sheet-header", className)}>{children}</div>;
}

export function SheetFooter({ className, children }: { className?: string; children?: ReactNode }) {
  return <div className={cn("ui-dialog-footer", className)}>{children}</div>;
}

export function SheetTitle({ className, children }: { className?: string; children?: ReactNode }) {
  const ctx = useSheet();
  return (
    <h2 id={ctx.titleId} className={cn("ui-dialog-title", className)}>
      {children}
    </h2>
  );
}

export function SheetDescription({ className, children }: { className?: string; children?: ReactNode }) {
  const ctx = useSheet();
  return (
    <p id={ctx.descId} className={cn("ui-dialog-desc", className)}>
      {children}
    </p>
  );
}

export function SheetClose({ className, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  const ctx = useSheet();
  return (
    <Tooltip content="닫기 (Esc)">
      <button
        type="button"
        className={cn("ui-btn", "ui-btn-ghost", "ui-btn-md", "ui-icon-btn", className)}
        aria-label="닫기 (Esc)"
        {...rest}
        onClick={(e) => {
          rest.onClick?.(e);
          ctx.setOpen(false);
        }}
      >
        {children ?? <CloseGlyph />}
      </button>
    </Tooltip>
  );
}
