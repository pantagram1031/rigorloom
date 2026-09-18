/** Merge class names. Falsy parts are dropped. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

const BTN_TONE =
  /\b(ui-btn-primary|ui-btn-secondary|ui-btn-ghost|ui-btn-destructive|ui-btn-link|ghost)\b/;

/** Kit trigger buttons default to secondary unless a tone is already in className. */
export function uiTriggerClass(className?: string): string {
  return cn("ui-btn", "ui-btn-md", !BTN_TONE.test(className ?? "") && "ui-btn-secondary", className);
}
