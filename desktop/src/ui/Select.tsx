import { forwardRef, type SelectHTMLAttributes } from "react";

import { cn } from "./cn";

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

/** Native select with a styled trigger and chevron. */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, children, ...rest },
  ref,
) {
  return (
    <div className={cn("ui-select", className)} data-disabled={rest.disabled ? "true" : undefined}>
      <select ref={ref} className="ui-select-el" {...rest}>
        {children}
      </select>
      <span className="ui-select-chevron" aria-hidden="true">
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M4.2 6.4 8 10.2l3.8-3.8" />
        </svg>
      </span>
    </div>
  );
});
