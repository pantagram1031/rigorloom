/**
 * Filling a cell under its printed label (`fill_cell.belowLabel`, T271).
 *
 * Many forms print a field label at the top of a tall cell and leave the
 * value to be written below it (정보공개 청구서: 성명, 주소, 전화번호). In the
 * editor that cell's text is the label, a line break, then the value. A queued
 * below-label fill keeps that whole text in `text`, so every view shows the
 * cell as it will read; the plan op gets the value lines only.
 */

export interface BelowLabel {
  /** The cell's first paragraph, exactly as read. */
  label: string;
  /** The value already under the label when the edit started. */
  previous?: string;
}

function valueLines(value: string): string[] {
  const lines = value.split("\n");
  while (lines.length > 1 && lines[lines.length - 1].trim() === "") lines.pop();
  return lines;
}

/**
 * The below-label fill an edit of a printed cell makes, or null.
 *
 * It is one when the cell's first line is a non-empty label, the edit keeps
 * that line exactly and changes only what follows it on new lines. A change to
 * the label itself, or text added on the label's own line, is not.
 */
export function resolveBelowLabelEdit(
  before: string,
  after: string,
): { belowLabel: BelowLabel; text: string } | null {
  const cut = before.indexOf("\n");
  const label = cut < 0 ? before : before.slice(0, cut);
  if (label.trim() === "" || !after.startsWith(`${label}\n`)) return null;
  const previous = cut < 0 ? "" : valueLines(before.slice(cut + 1)).join("\n");
  const value = valueLines(after.slice(label.length + 1)).join("\n");
  if (value === previous) return null;
  return { belowLabel: { label, previous }, text: `${label}\n${value}` };
}

/** The value lines a queued below-label fill writes under its label. */
export function belowLabelLines(op: { text: string; belowLabel?: BelowLabel }): string[] | null {
  if (!op.belowLabel) return null;
  const prefix = `${op.belowLabel.label}\n`;
  return valueLines(op.text.startsWith(prefix) ? op.text.slice(prefix.length) : op.text);
}

/**
 * The value under `label` in a cell's text, or null when the text does not
 * start with that label. Trailing blank lines are dropped, as the engine
 * drops them when it compares `previous`.
 */
export function belowLabelValue(text: string, label: string): string | null {
  if (text === label) return "";
  if (!text.startsWith(`${label}\n`)) return null;
  return valueLines(text.slice(label.length + 1)).join("\n");
}
