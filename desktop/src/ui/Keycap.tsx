import type { HTMLAttributes, ReactNode } from "react";

export interface KeycapProps extends HTMLAttributes<HTMLElement> {
  /** Single key label (`"Y"`, `"Enter"`) or chord tokens (`["Ctrl", "K"]`). */
  keys?: string | readonly string[];
  children?: ReactNode;
}

function normalizeKeys(keys?: string | readonly string[]): readonly string[] {
  if (!keys) return [];
  if (typeof keys === "string") {
    return keys
      .split("+")
      .map((part) => part.trim())
      .filter(Boolean);
  }
  return keys;
}

/**
 * Point-of-use keyboard hint (D1 §1 P7, J1 §1 Defect 23).
 *
 * Uses `--text-xs` (11 px, tabular numerals), `--radius-sm` (4 px), hairline border.
 */
export function Keycap({ keys, children, className = "", ...rest }: KeycapProps) {
  const tokens = normalizeKeys(keys);
  return (
    <kbd className={`rl-keycap ${className}`.trim()} {...rest}>
      {tokens.length > 0
        ? tokens.map((token, idx) => (
            <span key={`${token}-${idx}`} className="rl-keycap-key">
              {token}
            </span>
          ))
        : children != null && <span className="rl-keycap-key">{children}</span>}
    </kbd>
  );
}
