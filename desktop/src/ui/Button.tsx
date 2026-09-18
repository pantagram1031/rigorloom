import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "./cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive" | "link";
export type ButtonSize = "sm" | "md";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "md",
    loading = false,
    className,
    disabled,
    children,
    type = "button",
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn("ui-btn", `ui-btn-${variant}`, `ui-btn-${size}`, loading && "is-loading", className)}
      data-variant={variant}
      data-size={size}
      data-state={loading ? "loading" : "idle"}
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading ? <span className="ui-btn-spin" aria-hidden="true" /> : null}
      <span className="ui-btn-label">{children}</span>
    </button>
  );
});
