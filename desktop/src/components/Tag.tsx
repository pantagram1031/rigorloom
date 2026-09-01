/**
 * A semantic chip. Colour is never the only signal: every tone here is
 * accompanied by its own word, because the target user reviews documents for
 * hours and may be colour-vision-deficient.
 */
export type Tone = "fill" | "guide" | "static" | "spacer" | "ok" | "warn" | "bad" | "none";

export function Tag({ tone, children, title }: {
  tone: Tone;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <span className={`tag ${tone}`} title={title}>
      {children}
    </span>
  );
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
