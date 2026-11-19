# `rigorloom guard --mode block-diff`

This page defines the output before the code exists. The implementation and
`tests/test_guard_block_diff.py` must match it. Changing the format means
changing this page first.

## Why

The default guard output names the paragraphs that changed a protected fact
and lists the expressions involved. A reviewer then has to open both files to
see the edit. `block-diff` puts each edited paragraph's old and new text next
to each other, so the whole review fits in one terminal screen.

## Command

```sh
rigorloom guard BEFORE AFTER --mode block-diff
```

`--mode` takes `verdict` (the default, today's behaviour) or `block-diff`.
`block-diff` always prints text, and `--format` is ignored. Inputs, limits and
paragraph splitting are the same as in the default mode.

## Output

One header line, then one block per **edited** paragraph in document order,
then one closing line. An edited paragraph is one whose text differs at all.
That includes edits that kept every protected fact, so the reviewer sees
everything that moved, not only what failed.

```text
paragraphs: 295, edited: 3, changed a protected fact: 2

¶3 kept
- ... 다음과 같이 근로계약을 체결한다.
+ ... 다음과 같이 근로계약을 맺는다.

¶4 CHANGED: number/unit
- 1. 근로계약기간 : ...
+ 2. 근로계약기간 : ...
  lost   number/unit  1
  added  number/unit  2

CHANGED: restore or review the paragraphs above.
```

The `...` above is shortened for this page only. The real output for this
pair, with nothing shortened, is `examples/guard/block-diff.txt`.

Rules:

1. The header line is the same as the default text output's first line.
2. A block starts with `¶N`, the paragraph number counted from 1, then `kept`
   or `CHANGED:` followed by the labels of the kinds that changed, joined with
   `, `. The labels are the ones the default text output uses.
3. The next two lines are `- ` plus the old text and `+ ` plus the new text,
   exactly as guard read them. Text is not wrapped or shortened. A line break
   inside a paragraph is printed as `⏎`, so each side stays one line.
4. For a `CHANGED` block, each kind adds a `lost` line for expressions that
   appear fewer times after the edit and an `added` line for expressions that
   appear more times. An expression that appears more than once is shown as
   `text×count`, where the count is how many fewer (lost) or how many more
   (added). A kind with nothing lost (or nothing added) omits that line.
   When every number is still there but two numbers traded the words they
   follow (`기본급은 300만원, 수당은 50만원` → `기본급은 50만원, 수당은 300만원`), the
   label is `swapped numbers` and each value is shown with its word:
   `lost   swapped numbers  기본급 300만원, 수당 50만원`.
5. Blocks are separated by one blank line. The closing line is the same as
   the default text output's last line: `OK: every protected fact is
   unchanged.` or `CHANGED: restore or review the paragraphs above.`
6. When the paragraph counts differ, the output is the same two-line refusal
   as the default text output, and no blocks are printed.

## Exit codes

The same as the default mode: 0 when every protected fact is unchanged
(kept blocks may exist), 3 when at least one paragraph changed one or the
paragraph counts differ, 2 when the files cannot be compared. Exit 2 prints
the same one-document JSON usage error as the default mode, not text, because
there is no comparison to show.

## Acceptance

- `examples/guard/block-diff.txt` is committed, and the test regenerates it
  from `examples/guard/before.hwpx` and `after.hwpx` and compares byte for
  byte.
- A pair where every edit keeps its facts prints only `kept` blocks and exits 0.
- A pair with different paragraph counts prints the refusal and exits 3.
- A multi-line Markdown paragraph prints on one line per side with `⏎`.
- The default mode's JSON output and `examples/guard/verdict.json` do not
  change.
