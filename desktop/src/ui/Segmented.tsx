import { useRef, type KeyboardEvent, type ReactNode } from "react";

import { isImeComposing, principleAttributes } from "./attributes";

export interface SegmentedOption<T extends string = string> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
}

export interface SegmentedProps<T extends string = string> {
  options: readonly SegmentedOption<T>[];
  value: T;
  onChange: (next: T) => void;
  ariaLabel: string;
  className?: string;
}

/**
 * Flat segmented view switch (`변경 표시 · 표시 없이 · {기준 이름}`, J1 §1 Defect 8).
 *
 * Selected segment uses `--field` with a 1 px `--line-strong` rule and zero shadow.
 */
export function Segmented<T extends string = string>({
  options,
  value,
  onChange,
  ariaLabel,
  className = "",
}: SegmentedProps<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const enabledIndices = options
    .map((opt, idx) => (opt.disabled ? -1 : idx))
    .filter((idx) => idx >= 0);

  const moveFocus = (nextIdx: number) => {
    const opt = options[nextIdx];
    if (!opt || opt.disabled) return;
    refs.current[nextIdx]?.focus();
    onChange(opt.value);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, currentIdx: number) => {
    if (isImeComposing(event) || enabledIndices.length === 0) return;
    const pos = enabledIndices.indexOf(currentIdx);
    if (pos === -1) return;

    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      moveFocus(enabledIndices[(pos + 1) % enabledIndices.length]!);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
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
      role="radiogroup"
      aria-label={ariaLabel}
      className={`rl-segmented ${className}`.trim()}
      {...principleAttributes({ docked: true })}
    >
      {options.map((opt, idx) => {
        const checked = opt.value === value;
        return (
          <button
            key={opt.value}
            ref={(el) => {
              refs.current[idx] = el;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            disabled={opt.disabled}
            tabIndex={checked ? 0 : -1}
            className={`rl-segmented-btn${checked ? " rl-segmented-btn--active" : ""}`}
            onClick={() => {
              if (!opt.disabled) onChange(opt.value);
            }}
            onKeyDown={(e) => handleKeyDown(e, idx)}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
