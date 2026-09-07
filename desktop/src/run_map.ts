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
 * one of them, or when a caret offset lands inside exactly one run of a
 * line that concatenates neighbours. A span that can only be formed by
 * joining neighbour runs, with no caret that picks one, is `cross_run` —
 * never flattened into a single plain-text paragraph. `multi_run` means
 * the selection cannot be named as one run, not "the paragraph has several
 * runs".
 *
 * Product-side source map (PR #332 contract): revision lease +
 * `(atPara, run)` + UTF-16 `[rangeStart, rangeEnd)` on that run's own
 * text. Renderer `run_spans` are not required.
 */

export const OFFSET_UNIT = "utf-16" as const;
export type OffsetUnit = typeof OFFSET_UNIT;

export type RunMapRefusal =
  | "cross_run"
  | "multi_run"
  | "run_text_differs"
  | "no_inventory"
  | "utf16_split";

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
      /**
       * UTF-16 offset of `rangeStart` inside the visual span. The overlay
       * field shows the run intersection; a span-relative caret minus this
       * is the field caret. Zero when the field is the whole span.
       */
      spanOffset: number;
    }
  | { kind: "refused"; refusal: RunMapRefusal };

interface RunCover {
  run: number;
  runText: string;
  joinedStart: number;
  joinedEnd: number;
}

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

/**
 * True when `offset` sits between the two UTF-16 units of one supplementary
 * character. A range or caret that would split a surrogate pair is refused
 * (`utf16_split`), never rounded.
 */
export function isUtf16Split(text: string, offset: number): boolean {
  if (offset <= 0 || offset >= text.length) return false;
  const prev = text.charCodeAt(offset - 1);
  const next = text.charCodeAt(offset);
  return prev >= 0xd800 && prev <= 0xdbff && next >= 0xdc00 && next <= 0xdfff;
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

function coverRuns(runs: RunRecord[]): RunCover[] {
  const covers: RunCover[] = [];
  let at = 0;
  for (const run of runs) {
    const runText = run.text ?? "";
    covers.push({
      run: run.index,
      runText,
      joinedStart: at,
      joinedEnd: at + runText.length,
    });
    at += runText.length;
  }
  return covers;
}

function hitOnCover(
  cover: RunCover,
  spanStart: number,
  spanEnd: number,
): RunLocateResult {
  const rangeStart = Math.max(0, spanStart - cover.joinedStart);
  const rangeEnd = Math.min(cover.runText.length, spanEnd - cover.joinedStart);
  if (isUtf16Split(cover.runText, rangeStart) || isUtf16Split(cover.runText, rangeEnd)) {
    return { kind: "refused", refusal: "utf16_split" };
  }
  return {
    kind: "hit",
    run: cover.run,
    runText: cover.runText,
    rangeStart,
    rangeEnd,
    offsetUnit: OFFSET_UNIT,
    spanOffset: Math.max(0, cover.joinedStart + rangeStart - spanStart),
  };
}

function hitInRun(
  run: number,
  runText: string,
  rangeStart: number,
  rangeEnd: number,
): RunLocateResult {
  if (isUtf16Split(runText, rangeStart) || isUtf16Split(runText, rangeEnd)) {
    return { kind: "refused", refusal: "utf16_split" };
  }
  return {
    kind: "hit",
    run,
    runText,
    rangeStart,
    rangeEnd,
    offsetUnit: OFFSET_UNIT,
    spanOffset: 0,
  };
}

/**
 * Place a visual span inside the paragraph's run inventory.
 *
 * Exact UTF-16 containment in one run wins. A unique whole-run loose match
 * is the single-line fallback the #221 caret already used.
 *
 * When the visual line is the concatenation of neighbour runs (the usual
 * multi-run paragraph), a caret offset inside the line names the one run
 * that owns that code unit. No caret, or a caret that cannot name exactly
 * one run, is an explicit refusal — never a silent pick of the first run
 * and never a flattened paragraph rewrite.
 */
export function locateSpanInRuns(
  spanText: string,
  runs: RunRecord[],
  caret?: number | null,
): RunLocateResult {
  if (!runs.length) return { kind: "refused", refusal: "no_inventory" };
  if (caret != null && isUtf16Split(spanText, caret)) {
    return { kind: "refused", refusal: "utf16_split" };
  }

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
    return hitInRun(hit.run, hit.runText, hit.start, hit.end);
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
    return hitInRun(loose[0].index, runText, 0, runText.length);
  }
  if (loose.length > 1) {
    return { kind: "refused", refusal: "multi_run" };
  }

  const covers = coverRuns(runs);
  const joined = covers.map((cover) => cover.runText).join("");
  const joinedHits = utf16IndexesOf(joined, spanText);

  if (joinedHits.length > 1) {
    return { kind: "refused", refusal: "multi_run" };
  }

  if (joinedHits.length === 1) {
    const spanStart = joinedHits[0];
    const spanEnd = spanStart + spanText.length;
    const intersecting = covers.filter(
      (cover) => cover.joinedStart < spanEnd && cover.joinedEnd > spanStart,
    );
    if (intersecting.length === 1) {
      return hitOnCover(intersecting[0], spanStart, spanEnd);
    }
    if (intersecting.length > 1) {
      const picked = pickCoverAtCaret(intersecting, spanStart, spanText, caret);
      if (picked.kind === "refused") return picked;
      return hitOnCover(picked.cover, spanStart, spanEnd);
    }
  }

  if (spanText.length > 0 && (joined.includes(spanText) || looselySameText(joined, spanText))) {
    return { kind: "refused", refusal: "cross_run" };
  }
  return { kind: "refused", refusal: "run_text_differs" };
}

function pickCoverAtCaret(
  intersecting: RunCover[],
  spanStart: number,
  spanText: string,
  caret: number | null | undefined,
): { kind: "hit"; cover: RunCover } | { kind: "refused"; refusal: RunMapRefusal } {
  // A null caret is a snap-to-start with no measured character. Guessing
  // the first run would silently edit the wrong formatting island.
  if (caret == null) {
    return { kind: "refused", refusal: "cross_run" };
  }
  if (caret < 0 || caret > spanText.length) {
    return { kind: "refused", refusal: "multi_run" };
  }
  const caretInJoined = spanStart + caret;
  const cover =
    caret === spanText.length
      ? intersecting[intersecting.length - 1]
      : intersecting.find(
          (item) => item.joinedStart <= caretInJoined && caretInJoined < item.joinedEnd,
        );
  if (!cover) {
    return { kind: "refused", refusal: "multi_run" };
  }
  return { kind: "hit", cover };
}

export function fieldTextForRunEdit(before: string, rangeStart?: number, rangeEnd?: number): string {
  if (rangeStart == null || rangeEnd == null) return before;
  return utf16Slice(before, rangeStart, rangeEnd);
}
