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

import { cn } from "./cn";
import { Portal } from "./Portal";
import type { SlotRef } from "./ref";
import { mergeRefs } from "./ref";
import { useLayer, useOpenState } from "./useLayer";

type DialogCtx = {
  open: boolean;
  setOpen: (open: boolean) => void;
  triggerRef: SlotRef<HTMLElement>;
  contentRef: SlotRef<HTMLElement>;
  titleId: string;
  descId: string;
  disablePortal: boolean;
};

const Ctx = createContext<DialogCtx | null>(null);

function useDialog(): DialogCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("Dialog parts must be used inside Dialog");
  return ctx;
}

export type DialogProps = {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  disablePortal?: boolean;
  children?: ReactNode;
};

export function Dialog({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  disablePortal = false,
  children,
}: DialogProps) {
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
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export const DialogTrigger = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement>>(
  function DialogTrigger({ className, children, onClick, ...rest }, ref) {
    const ctx = useDialog();
    return (
      <button
        ref={mergeRefs(ref, ctx.triggerRef)}
        type="button"
        className={cn("ui-btn ui-btn-secondary ui-btn-md", className)}
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

export function DialogOverlay({ className }: { className?: string }) {
  const ctx = useDialog();
  if (!ctx.open) return null;
  return (
    <div
      className={cn("ui-dialog-overlay", className)}
      data-state="open"
      onMouseDown={() => ctx.setOpen(false)}
    />
  );
}

export function DialogContent({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  const ctx = useDialog();
  if (!ctx.open) return null;
  return (
    <Portal disabled={ctx.disablePortal}>
      <div className="ui-dialog-root" data-state="open">
        <DialogOverlay />
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
          className={cn("ui-dialog", className)}
          onMouseDown={(e) => e.stopPropagation()}
          {...rest}
        >
          {children}
        </div>
      </div>
    </Portal>
  );
}

export function DialogHeader({ className, children }: { className?: string; children?: ReactNode }) {
  return <div className={cn("ui-dialog-header", className)}>{children}</div>;
}

export function DialogFooter({ className, children }: { className?: string; children?: ReactNode }) {
  return <div className={cn("ui-dialog-footer", className)}>{children}</div>;
}

export function DialogTitle({ className, children }: { className?: string; children?: ReactNode }) {
  const ctx = useDialog();
  return (
    <h2 id={ctx.titleId} className={cn("ui-dialog-title", className)}>
      {children}
    </h2>
  );
}

export function DialogDescription({ className, children }: { className?: string; children?: ReactNode }) {
  const ctx = useDialog();
  return (
    <p id={ctx.descId} className={cn("ui-dialog-desc", className)}>
      {children}
    </p>
  );
}

export function DialogClose({ className, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  const ctx = useDialog();
  return (
    <button
      type="button"
      className={cn("ui-btn ui-btn-secondary ui-btn-md", className)}
      onClick={() => ctx.setOpen(false)}
      {...rest}
    >
      {children ?? "닫기"}
    </button>
  );
}
