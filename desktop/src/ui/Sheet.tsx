import {
  useEffect,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { tWp1b } from "../i18n/v2/wp1b";
import type { UiLanguage } from "../i18n/vocabulary";
import { isImeComposing, principleAttributes } from "./attributes";
import { Icon } from "./icons";

export type SheetPlacement = "right" | "bottom" | "dialog";

export interface SheetProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  open: boolean;
  onClose?: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  footer?: ReactNode;
  /**
   * `right` (default): docked approval sheet inside the right panel (`data-docked=""`, zero shadow).
   * `bottom`: narrow layout bottom sheet (`data-docked=""`, part of layout, never covers paper).
   * `dialog`: centered floating dialog (`설정`, `data-floating=""`, `--raised`, `--shadow-float`).
   */
  placement?: SheetPlacement;
  lang?: UiLanguage;
  closeLabel?: string;
  children: ReactNode;
}

/**
 * Docked sheet or floating dialog surface (D1 §3c9, §6; J1 §1 Defects 25–32).
 *
 * Docked placements (`right`, `bottom`) emit `data-docked=""` and carry zero box-shadow;
 * only `dialog` emits `data-floating=""` over `--scrim`.
 */
export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  footer,
  placement = "right",
  lang = "ko",
  closeLabel,
  className = "",
  children,
  ...rest
}: SheetProps) {
  const isDocked = placement !== "dialog";
  const resolvedCloseLabel = closeLabel ?? tWp1b("sheet_close", lang);

  useEffect(() => {
    if (!open || !onClose || placement !== "dialog") return;
    const onEscape = (event: globalThis.KeyboardEvent) => {
      if (isImeComposing(event)) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onEscape);
    return () => document.removeEventListener("keydown", onEscape);
  }, [open, onClose, placement]);

  if (!open) return null;

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    rest.onKeyDown?.(event);
    if (event.defaultPrevented || isImeComposing(event)) return;
    if (event.key === "Escape" && onClose) {
      event.preventDefault();
      onClose();
    }
  };

  const sheetSurface = (
    <section
      role={placement === "dialog" ? "dialog" : "region"}
      aria-modal={placement === "dialog" ? true : undefined}
      aria-label={typeof title === "string" ? title : resolvedCloseLabel}
      className={`rl-sheet rl-sheet--${placement} ${className}`.trim()}
      {...principleAttributes({ docked: isDocked, floating: !isDocked })}
      {...rest}
      onKeyDown={handleKeyDown}
    >
      <header className="rl-sheet-header">
        <div className="rl-sheet-titles">
          <h2 className="rl-sheet-title">{title}</h2>
          {subtitle ? <div className="rl-sheet-subtitle">{subtitle}</div> : null}
        </div>
        {onClose ? (
          <button
            type="button"
            className="rl-sheet-close" title="Esc"
            aria-label={resolvedCloseLabel}
            onClick={onClose}
          >
            <Icon name="close" size={16} />
          </button>
        ) : null}
      </header>
      <div className="rl-sheet-body">{children}</div>
      {footer ? <footer className="rl-sheet-footer">{footer}</footer> : null}
    </section>
  );

  if (placement === "dialog") {
    return (
      <div
        className="rl-sheet-scrim"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose?.();
        }}
      >
        {sheetSurface}
      </div>
    );
  }

  return sheetSurface;
}
