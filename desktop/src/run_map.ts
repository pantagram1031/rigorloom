/**
 * Run-scoped source map: revision-bound prepare/commit talks in one run
 * and one offset unit.
 *
 * Offsets are UTF-16 code units — the same unit JavaScript string indexes
 * and HWP/OWPML `<hp:t>` text use. They are not Unicode code points and
 * not user-perceived graphemes. A supplementary-plane character is two
 * units (`"😀".length === 2`).
 *
 * A visual line may be a fragment of one run (wrap). A paragraph may hold
 * several runs. The click names one run when the span sits inside exactly
 * one of them. A span that can only be formed by joining neighbour runs is
 * `cross_run` — never flattened into a single plain-text paragraph.
 */

export const OFFSET_UNIT = "utf-16" as const;
export type OffsetUnit = typeof OFFSET_UNIT;

export type RunMapRefusal = "cross_run" | "multi_run" | "run_text_differs" | "no_inventory";

export interface RunRecord {
  index: number;
  text?: string;
}

export type RunLocateResult =
  | {
      kind: "hit";
      run: number;
      runText: string;
      rangeStart: number;
      rangeEnd: number;
      offsetUnit: OffsetUnit;
    }
  | { kind: "refused"; refusal: RunMapRefusal };

export function utf16Length(text: string): number {
  return text.length;
}

export function utf16Slice(text: string, start: number, end: number): string {
  const lo = Math.max(0, start);
  const hi = Math.max(lo, end);
  return text.slice(lo, hi);
}

export function replaceUtf16Range(
  text: string,
  start: number,
  end: number,
  replacement: string,
): string {
  return text.slice(0, start) + replacement + text.slice(end);
}

export function commitRunScopedReplacement(args: {
  runText: string;
  rangeStart: number;
  rangeEnd: number;
  replacement: string;
  offsetUnit?: OffsetUnit;
}): { text: string; offsetUnit: OffsetUnit } {
  if (args.offsetUnit && args.offsetUnit !== OFFSET_UNIT) {
    throw new Error(`unsupported offset unit: ${args.offsetUnit}`);
  }
  return {
    text: replaceUtf16Range(args.runText, args.rangeStart, args.rangeEnd, args.replacement),
    offsetUnit: OFFSET_UNIT,
  };
}

export function looselySameText(a: string, b: string): boolean {
  return a.replace(/\s+/g, " ").trim() === b.replace(/\s+/g, " ").trim();
}

function utf16IndexesOf(haystack: string, needle: string): number[] {
  const hits: number[] = [];
  if (needle.length === 0) return hits;
  let from = 0;
  while (from <= haystack.length - needle.length) {
    const at = haystack.indexOf(needle, from);
    if (at < 0) break;
    hits.push(at);
    from = at + 1;
  }
  return hits;
}

/**
 * Place a visual span inside the paragraph's run inventory.
 *
 * Exact UTF-16 containment wins. A unique whole-run loose match is the
 * single-line fallback the #221 caret already used. Concatenation of
 * neighbour runs is an explicit `cross_run` refusal.
 */
export function locateSpanInRuns(spanText: string, runs: RunRecord[]): RunLocateResult {
  if (!runs.length) return { kind: "refused", refusal: "no_inventory" };

  const exact: Array<{ run: number; runText: string; start: number; end: number }> = [];
  let ambiguousPlacement = false;
  for (const run of runs) {
    const runText = run.text ?? "";
    const hits = utf16IndexesOf(runText, spanText);
    if (hits.length === 1) {
      exact.push({
        run: run.index,
        runText,
        start: hits[0],
        end: hits[0] + spanText.length,
      });
    } else if (hits.length > 1) {
      ambiguousPlacement = true;
    }
  }

  if (exact.length === 1 && !ambiguousPlacement) {
    const hit = exact[0];
    return {
      kind: "hit",
      run: hit.run,
      runText: hit.runText,
      rangeStart: hit.start,
      rangeEnd: hit.end,
      offsetUnit: OFFSET_UNIT,
    };
  }
  if (exact.length > 1 || (ambiguousPlacement && exact.length >= 1)) {
    return { kind: "refused", refusal: "multi_run" };
  }
  if (ambiguousPlacement) {
    return { kind: "refused", refusal: "run_text_differs" };
  }

  const loose = runs.filter((run) => looselySameText(run.text ?? "", spanText));
  if (loose.length === 1) {
    const runText = loose[0].text ?? "";
    return {
      kind: "hit",
      run: loose[0].index,
      runText,
      rangeStart: 0,
      rangeEnd: runText.length,
      offsetUnit: OFFSET_UNIT,
    };
  }
  if (loose.length > 1) {
    return { kind: "refused", refusal: "multi_run" };
  }

  const joined = runs.map((run) => run.text ?? "").join("");
  if (spanText.length > 0 && (joined.includes(spanText) || looselySameText(joined, spanText))) {
    return { kind: "refused", refusal: "cross_run" };
  }
  return { kind: "refused", refusal: "run_text_differs" };
}

export function fieldTextForRunEdit(before: string, rangeStart?: number, rangeEnd?: number): string {
  if (rangeStart == null || rangeEnd == null) return before;
  return utf16Slice(before, rangeStart, rangeEnd);
}
