import type { HTMLAttributes, ReactNode } from "react";

import { principleAttributes, type DataSource } from "./attributes";

export type TagTone = "neutral" | "agent" | "attn" | "fact" | "outline";

export interface TagProps extends HTMLAttributes<HTMLSpanElement> {
  /**
   * Semantic tone:
   * - `neutral`: expected guard category / prefilled cell note (`--expected-tint`)
   * - `agent`: agent proposal badge (`[data-source="agent"]` or `[data-accent]`)
   * - `attn`: 확인 / 시험용 / stale / blocked (`--attn`, `--attn-tint`, `--attn-line`)
   * - `fact`: 바뀐 사실 ONLY (`[data-fact]`, crimson `--fact`, `--fact-tint`)
   * - `outline`: quiet hairline tag
   */
  tone?: TagTone;
  /** Explicit provenance attribute (`agent` | `user` | `test` | `revert`). */
  source?: DataSource;
  /** Tab count badge mode (`data-accent=""`, 11 px tabular numerals). */
  accentCount?: boolean;
  /** Tabular numeric styling for counters. */
  numeric?: boolean;
  children: ReactNode;
}

export function Tag({
  tone = "neutral",
  source,
  accentCount = false,
  numeric = false,
  className = "",
  children,
  ...rest
}: TagProps) {
  const resolvedSource: DataSource | undefined =
    source ?? (tone === "agent" && !accentCount ? "agent" : undefined);
  const isFact = tone === "fact";
  const isAccent = accentCount;

  const classes = [
    "rl-tag",
    `rl-tag--${tone}`,
    numeric || accentCount ? "rl-tag--num" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span
      className={classes}
      {...principleAttributes({
        source: resolvedSource,
        fact: isFact,
        accent: isAccent,
      })}
      {...rest}
    >
      {children}
    </span>
  );
}
