/**
 * Semantic chip. Colour is never the only signal: every tone is accompanied
 * by its own word. Maps onto kit Badge variants; hover copy uses Tooltip.
 */
import type { ReactNode } from "react";

import { Badge, type BadgeVariant } from "../ui/Badge";
import { Tooltip } from "../ui/Tooltip";

export type Tone = "fill" | "guide" | "static" | "spacer" | "ok" | "warn" | "bad" | "none";

const TONE_VARIANT: Record<Tone, BadgeVariant> = {
  fill: "default",
  guide: "secondary",
  static: "outline",
  spacer: "outline",
  ok: "success",
  warn: "warning",
  bad: "destructive",
  none: "outline",
};

export function Tag({
  tone,
  children,
  title,
}: {
  tone: Tone;
  children: ReactNode;
  title?: string;
}) {
  const chip = (
    <Badge variant={TONE_VARIANT[tone]} className={`tag ${tone}`} data-tone={tone}>
      {children}
    </Badge>
  );
  if (!title) return chip;
  return <Tooltip content={title}>{chip}</Tooltip>;
}

/** Korean product labels for the four cell classifications the engine emits
 *  (`engine/scripts/form_inspect.py:29-35`). */
export const CLASSIFICATION_LABEL: Record<string, string> = {
  fill_target: "채움",
  guide: "안내",
  static: "고정",
  spacer: "여백",
};

export const CLASSIFICATION_TONE: Record<string, Tone> = {
  fill_target: "fill",
  guide: "guide",
  static: "static",
  spacer: "spacer",
};
