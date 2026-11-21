import {
  useEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { isImeComposing, principleAttributes } from "./attributes";

export type MenuEntry =
  | {
      kind?: "item";
      id: string;
      label: ReactNode;
      shortcut?: string | readonly string[];
      disabled?: boolean;
      onSelect?: () => void;
    }
  | {
      kind: "separator";
      id: string;
    }
  | {
      kind: "header";
      id: string;
      label: ReactNode;
    };

export interface MenuProps {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  items: readonly MenuEntry[];
  ariaLabel: string;
  trigger?: ReactNode;
  align?: "start" | "end";
  /** Render the menu list inline without absolute positioning (useful for static layout/tests). */
  inline?: boolean;
  className?: string;
}

/**
 * Floating menu (`--raised`, `--shadow-float`, `--radius-md` 6 px, 32 px `--row` items).
 *
 * Keyboard navigation (`ArrowDown`, `ArrowUp`, `Home`, `End`, `Enter`, `Escape`)
 * is IME-safe via `isImeComposing`.
 */
export function Menu({
  open,
  onOpenChange,
  items,
  ariaLabel,
  trigger,
  align = "start",
  inline = false,
  className = "",
}: MenuProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const actionableIndices = items
    .map((entry, idx) =>
      (entry.kind === undefined || entry.kind === "item") && !entry.disabled ? idx : -1,
    )
    .filter((idx) => idx >= 0);

  useEffect(() => {
    if (!open || inline) return;
    const onPointerDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        onOpenChange(false);
      }
    };
    const onEscape = (event: globalThis.KeyboardEvent) => {
      if (isImeComposing(event)) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        onOpenChange(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open, inline, onOpenChange]);

  const focusItem = (idx: number) => {
    itemRefs.current[idx]?.focus();
  };

  const handleMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (isImeComposing(event)) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onOpenChange(false);
      return;
    }
    if (actionableIndices.length === 0) return;
    const activeEl = document.activeElement;
    const currentIdx = itemRefs.current.findIndex((el) => el === activeEl);
    const pos = actionableIndices.indexOf(currentIdx);

    if (event.key === "ArrowDown") {
      event.preventDefault();
      const nextPos = pos === -1 ? 0 : (pos + 1) % actionableIndices.length;
      focusItem(actionableIndices[nextPos]!);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const prevPos =
        pos === -1
          ? actionableIndices.length - 1
          : (pos - 1 + actionableIndices.length) % actionableIndices.length;
      focusItem(actionableIndices[prevPos]!);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusItem(actionableIndices[0]!);
    } else if (event.key === "End") {
      event.preventDefault();
      focusItem(actionableIndices[actionableIndices.length - 1]!);
    }
  };

  return (
    <div ref={wrapRef} className={`rl-menu-anchor ${className}`.trim()}>
      {trigger}
      {open ? (
        <div
          role="menu"
          aria-label={ariaLabel}
          className={`rl-menu rl-menu--${align}${inline ? " rl-menu--inline" : ""}`}
          {...principleAttributes({ floating: true })}
          onKeyDown={handleMenuKeyDown}
        >
          {items.map((entry, idx) => {
            if (entry.kind === "separator") {
              return <div key={entry.id} role="separator" className="rl-menu-sep" />;
            }
            if (entry.kind === "header") {
              return (
                <div key={entry.id} role="presentation" className="rl-menu-header">
                  {entry.label}
                </div>
              );
            }
            const shortcut = typeof entry.shortcut === "string" ? entry.shortcut : entry.shortcut?.join("+");
            return (
              <button
                key={entry.id}
                ref={(el) => {
                  itemRefs.current[idx] = el;
                }}
                type="button"
                role="menuitem"
                disabled={entry.disabled}
                className="rl-menu-item"
                onClick={() => {
                  if (entry.disabled) return;
                  entry.onSelect?.();
                  if (!inline) onOpenChange(false);
                }}
              >
                <span className="rl-menu-item-label">{entry.label}</span>
                {shortcut ? <span className="rl-menu-shortcut">{shortcut}</span> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
