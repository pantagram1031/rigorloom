import { forwardRef, useEffect, useState, type ButtonHTMLAttributes } from "react";

import { cn } from "./cn";
import { isActivateKey } from "./roving";

export type SwitchProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange" | "role"> & {
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
};

export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  { checked, defaultChecked = false, onCheckedChange, className, disabled, onKeyDown, ...rest },
  ref,
) {
  const controlled = checked !== undefined;
  const [uncontrolled, setUncontrolled] = useState(defaultChecked);
  const on = controlled ? checked : uncontrolled;

  useEffect(() => {
    if (!controlled) return;
    setUncontrolled(checked);
  }, [checked, controlled]);

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
      role="switch"
      aria-checked={on}
      data-state={on ? "checked" : "unchecked"}
      className={cn("ui-switch", className)}
      disabled={disabled}
      onClick={toggle}
      onKeyDown={(e) => {
        onKeyDown?.(e);
        if (e.defaultPrevented) return;
        if (isActivateKey(e.key) || e.key === " ") {
          e.preventDefault();
          toggle();
        }
      }}
      {...rest}
    >
      <span className="ui-switch-thumb" aria-hidden="true" />
    </button>
  );
});
