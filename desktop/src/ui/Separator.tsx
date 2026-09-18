import { forwardRef, type HTMLAttributes } from "react";

import { cn } from "./cn";

export type SeparatorProps = HTMLAttributes<HTMLDivElement> & {
  orientation?: "horizontal" | "vertical";
  decorative?: boolean;
};

export const Separator = forwardRef<HTMLDivElement, SeparatorProps>(function Separator(
  { orientation = "horizontal", decorative = true, className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      role="separator"
      aria-orientation={orientation}
      aria-hidden={decorative || undefined}
      data-orientation={orientation}
      className={cn("ui-sep", className)}
      {...rest}
    />
  );
});
