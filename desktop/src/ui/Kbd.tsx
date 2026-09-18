import { forwardRef, type HTMLAttributes } from "react";

import { cn } from "./cn";

export const Kbd = forwardRef<HTMLElement, HTMLAttributes<HTMLElement>>(function Kbd(
  { className, ...rest },
  ref,
) {
  return <kbd ref={ref} className={cn("ui-kbd", className)} {...rest} />;
});
