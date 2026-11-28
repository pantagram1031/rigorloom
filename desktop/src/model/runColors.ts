/**
 * Coloured text segments for an inline editor opened on a multi-run region.
 *
 * When a table cell or paragraph mixes character colours (for instance, a
 * black title followed by a blue revision note), the inline editor draws a
 * mirror layer under the text control so each run keeps its own colour while
 * the person types. Common prefix and suffix with the initial text keep the
 * colours of the runs they came from; the changed middle takes the colour of
 * the run at the start of the change (or the run on the left at a run
 * boundary, matching how Hangul continues the preceding run's shape).
 */

export interface ColoredRun {
  text: string;
  color?: string | null;
}

export interface RunColorSegment {
  text: string;
  color: string;
}

export function normalizeRunColor(color?: string | null): string {
  const trimmed = typeof color === "string" ? color.trim() : "";
  // The header may declare a colour as bare hex digits; CSS needs the "#".
  if (/^[0-9a-f]{6}$/i.test(trimmed)) return `#${trimmed}`;
  return trimmed.length > 0 ? trimmed : "inherit";
}

/**
 * Prepare the `runs` prop for `SeatEditor` only when the runs' joined text
 * equals the editor's initial value exactly.
 */
export function editorRunsForInitial(
  runs:
    | ReadonlyArray<{
        text: string;
        color?: string | null;
        charpr_color?: string | null;
      }>
    | null
    | undefined,
  initialValue: string,
): ColoredRun[] | undefined {
  if (!runs || runs.length < 2) return undefined;
  if (runs.map((run) => run.text).join("") !== initialValue) return undefined;
  return runs.map((run) => ({
    text: run.text,
    color: run.color ?? run.charpr_color ?? null,
  }));
}

function pushSegment(segments: RunColorSegment[], text: string, color: string): void {
  if (!text) return;
  const last = segments[segments.length - 1];
  if (last && last.color.toLowerCase() === color.toLowerCase()) {
    last.text += text;
  } else {
    segments.push({ text, color });
  }
}

/**
 * Split `currentValue` into coloured segments from the initial `runs`, or
 * return `null` when all runs share one colour (so no mirror layer is used).
 */
export function runColorSegments(
  runs: readonly ColoredRun[] | null | undefined,
  currentValue: string,
): RunColorSegment[] | null {
  if (!runs || runs.length < 2) return null;
  const nonEmpty = runs
    .filter((run) => typeof run.text === "string" && run.text.length > 0)
    .map((run) => ({
      text: run.text,
      color: normalizeRunColor(run.color),
    }));
  if (nonEmpty.length < 2) return null;

  const distinctColors = new Set(nonEmpty.map((run) => run.color.toLowerCase()));
  if (distinctColors.size < 2) return null;

  if (currentValue.length === 0) return [];

  const before = nonEmpty.map((run) => run.text).join("");
  const max = Math.min(before.length, currentValue.length);
  let prefix = 0;
  while (prefix < max && before[prefix] === currentValue[prefix]) {
    prefix += 1;
  }
  let suffix = 0;
  while (
    suffix < max - prefix &&
    before[before.length - 1 - suffix] === currentValue[currentValue.length - 1 - suffix]
  ) {
    suffix += 1;
  }

  let offset = 0;
  const bounds = nonEmpty.map((run) => {
    const bound = {
      start: offset,
      end: offset + run.text.length,
      color: run.color,
    };
    offset += run.text.length;
    return bound;
  });

  const segments: RunColorSegment[] = [];

  for (const bound of bounds) {
    const start = Math.max(0, bound.start);
    const end = Math.min(prefix, bound.end);
    if (start < end) {
      pushSegment(segments, before.slice(start, end), bound.color);
    }
  }

  const middle = currentValue.slice(prefix, currentValue.length - suffix);
  if (middle.length > 0) {
    const carrier =
      bounds.find((bound) => bound.start < prefix && prefix <= bound.end) ?? bounds[0];
    pushSegment(segments, middle, carrier.color);
  }

  const suffixStart = before.length - suffix;
  for (const bound of bounds) {
    const start = Math.max(suffixStart, bound.start);
    const end = Math.min(before.length, bound.end);
    if (start < end) {
      pushSegment(segments, before.slice(start, end), bound.color);
    }
  }

  return segments;
}
