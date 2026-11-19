import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { Keycap } from "./Keycap";
import { principleAttributes, type DataSource, type DataVariant } from "./attributes";

export type ButtonSize = "sm" | "md" | "lg" | "touch";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /**
   * Visual hierarchy (`outline` default).
   * At most ONE visible `primary` button (`--ink` fill) may appear per window (D1 §1 P2, J1 §4).
   */
  variant?: DataVariant;
  /** `sm`/`md` = 28 px (`--ctl`), `lg` = 32 px (`--ctl-lg`), `touch` = 44 px (`--ctl-touch`). */
  size?: ButtonSize;
  /** Optional shortcut rendered via `<Keycap>` at the right edge of the button. */
  shortcut?: string | readonly string[];
  /** Optional icon-only mode (requires `aria-label` or `title`). */
  iconOnly?: boolean;
  /** Stretch across container width (e.g. narrow sheet primary action). */
  fullWidth?: boolean;
  /** Optional provenance attribute when needed. */
  source?: DataSource;
  children?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "outline",
    size = "md",
    shortcut,
    iconOnly = false,
    fullWidth = false,
    source,
    type = "button",
    className = "",
    children,
    ...rest
  },
  ref,
) {
  const classes = [
    "rl-btn",
    `rl-btn--${size}`,
    iconOnly ? "rl-btn--icon" : "",
    fullWidth ? "rl-btn--full" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      ref={ref}
      type={type}
      className={classes}
      {...principleAttributes({ variant, source })}
      {...rest}
    >
      <span className="rl-btn-label">{children}</span>
      {shortcut ? <Keycap keys={shortcut} /> : null}
    </button>
  );
});
