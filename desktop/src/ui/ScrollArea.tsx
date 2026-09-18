import { forwardRef, type HTMLAttributes } from "react";

import { cn } from "./cn";

/** Custom thin scrollbar. Overflow only — no JS. */
export const ScrollArea = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function ScrollArea(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={cn("ui-scroll", className)} {...rest}>
      {children}
    </div>
  );
});
