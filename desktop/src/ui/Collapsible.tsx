import {
  createContext,
  useContext,
  useId,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
} from "react";

import { cn } from "./cn";
import { useOpenState } from "./useLayer";

type CollapseCtx = {
  open: boolean;
  setOpen: (open: boolean) => void;
  contentId: string;
};

const Ctx = createContext<CollapseCtx | null>(null);

function useCollapse(): CollapseCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("Collapsible parts must be used inside Collapsible");
  return ctx;
}

export type CollapsibleProps = HTMLAttributes<HTMLDivElement> & {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

export function Collapsible({
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  className,
  children,
  ...rest
}: CollapsibleProps) {
  const [open, setOpen] = useOpenState(openProp, defaultOpen, onOpenChange);
  const contentId = useId();
  return (
    <Ctx.Provider value={{ open, setOpen, contentId }}>
      <div className={cn("ui-collapse", className)} data-state={open ? "open" : "closed"} {...rest}>
        {children}
      </div>
    </Ctx.Provider>
  );
}

export function CollapsibleTrigger({
  className,
  children,
  onClick,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  const ctx = useCollapse();
  return (
    <button
      type="button"
      className={cn("ui-collapse-trigger", className)}
      aria-expanded={ctx.open}
      aria-controls={ctx.contentId}
      data-state={ctx.open ? "open" : "closed"}
      onClick={(e) => {
        onClick?.(e);
        ctx.setOpen(!ctx.open);
      }}
      {...rest}
    >
      <span className="ui-collapse-chevron" aria-hidden="true">
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M4.2 6.4 8 10.2l3.8-3.8" />
        </svg>
      </span>
      {children}
    </button>
  );
}

export function CollapsibleContent({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  const ctx = useCollapse();
  return (
    <div
      id={ctx.contentId}
      className={cn("ui-collapse-root", className)}
      data-state={ctx.open ? "open" : "closed"}
      hidden={false}
      {...rest}
    >
      <div className="ui-collapse-inner">{children}</div>
    </div>
  );
}
