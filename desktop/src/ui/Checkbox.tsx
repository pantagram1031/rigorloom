import { forwardRef, useState, type ButtonHTMLAttributes } from "react";

import { cn } from "./cn";
import { isActivateKey } from "./roving";

export type CheckboxProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange" | "role"> & {
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
};

export const Checkbox = forwardRef<HTMLButtonElement, CheckboxProps>(function Checkbox(
  { checked, defaultChecked = false, onCheckedChange, className, disabled, children, onKeyDown, ...rest },
  ref,
) {
  const controlled = checked !== undefined;
  const [uncontrolled, setUncontrolled] = useState(defaultChecked);
  const on = controlled ? checked : uncontrolled;

  const toggle = () => {
    if (disabled) return;
    const next = !on;
    if (!controlled) setUncontrolled(next);
    onCheckedChange?.(next);
  };

  return (
    <button
      ref={ref}
      type="button"
      role="checkbox"
      aria-checked={on}
      data-state={on ? "checked" : "unchecked"}
      className={cn("ui-check", className)}
      disabled={disabled}
      onClick={toggle}
      onKeyDown={(e) => {
        onKeyDown?.(e);
        if (e.defaultPrevented) return;
        if (isActivateKey(e.key)) {
          e.preventDefault();
          toggle();
        }
      }}
      {...rest}
    >
      <span className="ui-check-box" aria-hidden="true">
        {on ? (
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M3.4 8.3 6.6 11.4 12.6 4.8" />
          </svg>
        ) : null}
      </span>
      {children ? <span className="ui-check-label">{children}</span> : null}
    </button>
  );
});
