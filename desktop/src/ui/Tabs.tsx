import { useRef, type KeyboardEvent, type ReactNode } from "react";

import { Tag } from "./Tag";
import { isImeComposing, principleAttributes } from "./attributes";

export interface TabItem<T extends string = string> {
  id: T;
  label: ReactNode;
  count?: number;
  countTone?: "accent" | "attn" | "neutral";
  disabled?: boolean;
}

export interface TabsProps<T extends string = string> {
  items: readonly TabItem<T>[];
  value: T;
  onChange: (next: T) => void;
  ariaLabel: string;
  className?: string;
}

/**
 * Text tab strip (32 px `--h-tabrow`, 2 px `--ink` active underline, no track, no shadow).
 * Used for the 5 left panes (`파일 · 개요 · 빈칸 · 찾기 · 기록`) and 3 right panel panes
 * (`변경 · 에이전트 · 점검`), per J1 §1 Defects 4 and 15.
 */
export function Tabs<T extends string = string>({
  items,
  value,
  onChange,
  ariaLabel,
  className = "",
}: TabsProps<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  const enabledIndices = items
    .map((item, idx) => (item.disabled ? -1 : idx))
    .filter((idx) => idx >= 0);

  const moveFocus = (nextIdx: number) => {
    const item = items[nextIdx];
    if (!item || item.disabled) return;
    refs.current[nextIdx]?.focus();
    onChange(item.id);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, currentIdx: number) => {
    if (isImeComposing(event) || enabledIndices.length === 0) return;
    const pos = enabledIndices.indexOf(currentIdx);
    if (pos === -1) return;

    if (event.key === "ArrowRight") {
      event.preventDefault();
      moveFocus(enabledIndices[(pos + 1) % enabledIndices.length]!);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      moveFocus(enabledIndices[(pos - 1 + enabledIndices.length) % enabledIndices.length]!);
    } else if (event.key === "Home") {
      event.preventDefault();
      moveFocus(enabledIndices[0]!);
    } else if (event.key === "End") {
      event.preventDefault();
      moveFocus(enabledIndices[enabledIndices.length - 1]!);
    }
  };

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={`rl-tabs ${className}`.trim()}
      {...principleAttributes({ docked: true })}
    >
      {items.map((item, idx) => {
        const selected = item.id === value;
        const showCount = item.count !== undefined && item.count > 0;
        const countTone = item.countTone ?? "neutral";
        return (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[idx] = el;
            }}
            type="button"
            role="tab"
            aria-selected={selected}
            disabled={item.disabled}
            tabIndex={selected ? 0 : -1}
            className={`rl-tab${selected ? " rl-tab--active" : ""}`}
            onClick={() => {
              if (!item.disabled) onChange(item.id);
            }}
            onKeyDown={(e) => handleKeyDown(e, idx)}
          >
            <span className="rl-tab-label">{item.label}</span>
            {showCount ? (
              <Tag
                tone={countTone === "accent" ? "agent" : countTone === "attn" ? "attn" : "neutral"}
                accentCount={countTone === "accent"}
                numeric
              >
                {item.count}
              </Tag>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
