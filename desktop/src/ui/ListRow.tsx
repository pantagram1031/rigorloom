import {
  forwardRef,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { isImeComposing, principleAttributes, type DataSource } from "./attributes";

export type ListRowDensity = "tree" | "default" | "change";
export type ListRowBarTone = "none" | "agent" | "accepted" | "attn" | "fact" | "rejected";

export interface ListRowProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  /** `tree` = 28 px (`--row-tree`), `default` = 32 px (`--row`), `change` = 52 px (`--row-change`). */
  density?: ListRowDensity;
  /** Tabular row / margin index number (e.g. `5`, `10–12`). */
  index?: string | number;
  /** Primary label (`행정기관명`, `파일 열기`, `서식 머리`). */
  title: ReactNode;
  /** Inline operation / source metadata (`빈칸 채움 · 에이전트`). */
  meta?: ReactNode;
  /** Secondary line (`가온공공기록원`, folder path, diff preview). */
  subtitle?: ReactNode;
  /** Right-aligned status text, tags, or keycaps (`받아들임`, `<Tag>`, `<Keycap>`). */
  trailing?: ReactNode;
  /** Expanded content (e.g. `<DiffLines>` + action buttons on the selected change row). */
  children?: ReactNode;
  /** Neutral `--selected` background (never blue, per J1 §1 Defect 19 & 36). */
  selected?: boolean;
  disabled?: boolean;
  /** Tree indentation level (`0`, `1`, `2`). */
  indent?: 0 | 1 | 2;
  /** 2 px left state rule mirroring the page's margin bar (J1 §1 Defect 19 & 28). */
  barTone?: ListRowBarTone;
  /** Provenance attribute (`agent` | `user` | `test` | `revert`). */
  source?: DataSource;
  /** Marks row as carrying a changed-fact finding (`data-fact=""`). */
  fact?: boolean;
  /** Callback fired on click or IME-safe Enter/Space. */
  onActivate?: () => void;
}

export const ListRow = forwardRef<HTMLDivElement, ListRowProps>(function ListRow(
  {
    density = "default",
    index,
    title,
    meta,
    subtitle,
    trailing,
    children,
    selected = false,
    disabled = false,
    indent = 0,
    barTone = "none",
    source,
    fact = false,
    onActivate,
    onClick,
    onKeyDown,
    className = "",
    ...rest
  },
  ref,
) {
  const interactive = Boolean(onActivate || onClick) && !disabled;
  const resolvedSource: DataSource | undefined =
    source ?? (barTone === "agent" ? "agent" : undefined);
  const resolvedFact = fact || barTone === "fact";

  const classes = [
    "rl-row",
    `rl-row--${density}`,
    indent > 0 ? `rl-row--indent-${indent}` : "",
    barTone !== "none" ? `rl-row--bar-${barTone}` : "",
    selected ? "rl-row--selected" : "",
    interactive ? "rl-row--interactive" : "",
    disabled ? "rl-row--disabled" : "",
    index !== undefined ? "rl-row--indexed" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(event);
    if (event.defaultPrevented || !interactive || isImeComposing(event)) return;
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onActivate?.();
    }
  };

  return (
    <div
      ref={ref}
      role={interactive ? "button" : rest.role}
      tabIndex={interactive ? (rest.tabIndex ?? 0) : rest.tabIndex}
      aria-selected={rest["aria-selected"]}
      aria-disabled={disabled || undefined}
      className={classes}
      {...principleAttributes({
        source: resolvedSource,
        fact: resolvedFact,
      })}
      onClick={(e) => {
        if (disabled) return;
        onClick?.(e);
        if (!e.defaultPrevented) onActivate?.();
      }}
      onKeyDown={handleKeyDown}
      {...rest}
    >
      <div className="rl-row-main">
        {index !== undefined ? <span className="rl-row-index">{index}</span> : null}
        <div className="rl-row-body">
          <div className="rl-row-line1">
            <span className="rl-row-title">{title}</span>
            {meta ? <span className="rl-row-meta">{meta}</span> : null}
          </div>
          {subtitle ? <div className="rl-row-subtitle">{subtitle}</div> : null}
        </div>
        {trailing ? <div className="rl-row-trailing">{trailing}</div> : null}
      </div>
      {children ? <div className="rl-row-expanded">{children}</div> : null}
    </div>
  );
});

export interface DiffLinesProps {
  beforeLabel: string;
  afterLabel: string;
  before?: ReactNode;
  after?: ReactNode;
  className?: string;
}

/**
 * Two flat `변경 전` / `변경 후` lines on `--field` without nested card chrome
 * (J1 §1 Defect 19).
 */
export function DiffLines({
  beforeLabel,
  afterLabel,
  before,
  after,
  className = "",
}: DiffLinesProps) {
  return (
    <div className={`rl-diff-lines ${className}`.trim()}>
      {before !== undefined ? (
        <div className="rl-diff-line rl-diff-line--before">
          <span className="rl-diff-label">{beforeLabel}</span>
          <span className="rl-diff-value">{before}</span>
        </div>
      ) : null}
      {after !== undefined ? (
        <div className="rl-diff-line rl-diff-line--after">
          <span className="rl-diff-label">{afterLabel}</span>
          <span className="rl-diff-value">{after}</span>
        </div>
      ) : null}
    </div>
  );
}
