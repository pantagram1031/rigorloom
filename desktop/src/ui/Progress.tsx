import { forwardRef, type HTMLAttributes } from "react";

import { cn } from "./cn";

export type ProgressProps = HTMLAttributes<HTMLDivElement> & {
  value?: number | null;
};

export const Progress = forwardRef<HTMLDivElement, ProgressProps>(function Progress(
  { value = null, className, ...rest },
  ref,
) {
  const determinate = typeof value === "number";
  const pct = determinate ? Math.min(100, Math.max(0, value)) : 0;
  return (
    <div
      ref={ref}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={determinate ? Math.round(pct) : undefined}
      data-state={determinate ? "determinate" : "indeterminate"}
      className={cn("ui-progress", className)}
      {...rest}
    >
      <span className="ui-progress-bar" style={determinate ? { width: `${pct}%` } : undefined} />
    </div>
  );
});
