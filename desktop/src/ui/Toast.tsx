import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "./cn";

export type ToastVariant = "default" | "destructive" | "success";

export type ToastProps = HTMLAttributes<HTMLDivElement> & {
  variant?: ToastVariant;
  action?: ReactNode;
  onClose?: () => void;
};

/** Presentational toast. The store-connected stack stays in components/Toast.tsx until M2. */
export const Toast = forwardRef<HTMLDivElement, ToastProps>(function Toast(
  { variant = "default", action, onClose, className, children, ...rest },
  ref,
) {
  const assertive = variant === "destructive";
  return (
    <div
      ref={ref}
      role={assertive ? "alert" : "status"}
      aria-live={assertive ? "assertive" : "polite"}
      data-variant={variant}
      className={cn("ui-toast", `ui-toast-${variant}`, className)}
      {...rest}
    >
      <span className="ui-toast-text">{children}</span>
      {action ? <span className="ui-toast-action">{action}</span> : null}
      {onClose ? (
        <button type="button" className="ui-toast-close" aria-label="닫기" onClick={onClose}>
          ×
        </button>
      ) : null}
    </div>
  );
});

export function ToastViewport({ className, children }: { className?: string; children?: ReactNode }) {
  return <div className={cn("ui-toast-stack", className)}>{children}</div>;
}
