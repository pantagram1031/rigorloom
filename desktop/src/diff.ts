/**
 * Character-level LCS diff for review hunks. No dependency.
 *
 * Used only for display. Callers must not feed the marks back into op params.
 */

export type DiffMark = {
  type: "equal" | "insert" | "delete";
  text: string;
};

const DP_BUDGET = 250_000;

function coalesce(marks: DiffMark[]): DiffMark[] {
  const out: DiffMark[] = [];
  for (const mark of marks) {
    if (!mark.text) continue;
    const last = out[out.length - 1];
    if (last && last.type === mark.type) last.text += mark.text;
    else out.push({ type: mark.type, text: mark.text });
  }
  return out;
}

function affixDiff(before: string, after: string): DiffMark[] {
  let start = 0;
  const maxPrefix = Math.min(before.length, after.length);
  while (start < maxPrefix && before[start] === after[start]) start += 1;
  let endBefore = before.length;
  let endAfter = after.length;
  while (
    endBefore > start &&
    endAfter > start &&
    before[endBefore - 1] === after[endAfter - 1]
  ) {
    endBefore -= 1;
    endAfter -= 1;
  }
  const marks: DiffMark[] = [];
  if (start > 0) marks.push({ type: "equal", text: before.slice(0, start) });
  if (endBefore > start) marks.push({ type: "delete", text: before.slice(start, endBefore) });
  if (endAfter > start) marks.push({ type: "insert", text: after.slice(start, endAfter) });
  if (endBefore < before.length) marks.push({ type: "equal", text: before.slice(endBefore) });
  return coalesce(marks);
}

/** Character-level LCS. Falls back to a prefix/suffix split on huge strings. */
export function diffText(before: string, after: string): DiffMark[] {
  if (before === after) return before ? [{ type: "equal", text: before }] : [];
  if (!before) return after ? [{ type: "insert", text: after }] : [];
  if (!after) return [{ type: "delete", text: before }];

  const a = Array.from(before);
  const b = Array.from(after);
  const n = a.length;
  const m = b.length;
  if (n * m > DP_BUDGET) return affixDiff(before, after);

  const dp: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = 1; i <= n; i++) {
    const ai = a[i - 1];
    const row = dp[i]!;
    const prev = dp[i - 1]!;
    for (let j = 1; j <= m; j++) {
      row[j] = ai === b[j - 1] ? prev[j - 1]! + 1 : Math.max(prev[j]!, row[j - 1]!);
    }
  }

  const raw: DiffMark[] = [];
  let i = n;
  let j = m;
  while (i > 0 && j > 0) {
    if (a[i - 1] === b[j - 1]) {
      raw.push({ type: "equal", text: a[i - 1]! });
      i -= 1;
      j -= 1;
    } else if (dp[i - 1]![j]! > dp[i]![j - 1]!) {
      raw.push({ type: "delete", text: a[i - 1]! });
      i -= 1;
    } else {
      raw.push({ type: "insert", text: b[j - 1]! });
      j -= 1;
    }
  }
  while (i > 0) {
    i -= 1;
    raw.push({ type: "delete", text: a[i]! });
  }
  while (j > 0) {
    j -= 1;
    raw.push({ type: "insert", text: b[j]! });
  }
  raw.reverse();
  return coalesce(raw);
}
