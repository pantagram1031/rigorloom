import { forwardRef, type HTMLAttributes } from "react";

import { cn } from "./cn";

export type BadgeVariant = "default" | "secondary" | "outline" | "success" | "warning" | "destructive";

export type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  variant?: BadgeVariant;
};

/** Chip. Tag in the app chrome maps onto these variants in M2. */
export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { variant = "default", className, ...rest },
  ref,
) {
  return (
    <span
      ref={ref}
      className={cn("ui-badge", `ui-badge-${variant}`, className)}
      data-variant={variant}
      {...rest}
    />
  );
});
