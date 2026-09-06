# Review: #333 (run-scoped edit) against the source-map contract (#332)

Read-only review of PR #333 (`cursor/run-scoped-edit-5851`, three commits
`617b54c`, `067f21a`, `e900c2a`, on the #330 tip `9f59b31`). No product file
is touched by this note. Diff read in full: `desktop/src/run_map.ts` (new),
`revision.ts`, `actions.ts`, `store.ts`, `types.ts`, `PageOverlay.tsx`,
`smoke.ts`, the two harnesses and `tests/test_desktop_run_scoped_edit.py`.

## Matches the contract

- **Revision**: the edit effect and `InlineRunEdit` carry `runId` and
  `documentSha256` from the #330 lease; `revision_mismatch` and the stale
  lease no-op are re-tested. Coordinate 1 holds.
- **Run address**: `run` is the inventory index from `document/readRegion`,
  `set_run(atPara, run, text)` is the only writer, `charPrIDRef` untouched.
  Coordinate 2 holds.
- **Unit**: `OFFSET_UNIT = "utf-16"`, `[rangeStart, rangeEnd)`, a
  supplementary-plane case proves units are not code points. Coordinate 3
  holds for the range.
- **Limits honoured**: a wrapped line is a range of one run; a span that only
  exists across runs is `cross_run`, never a flattened paragraph; a span
  found in two runs is `multi_run` (the contract's narrowed meaning); an
  ambiguous placement is refused, not guessed.
- **File boundary**: `desktop/src` and `tests/` only; no renderer file.

## Departs from the contract

1. **Run is found by text search, not by the source map.**
   `locateSpanInRuns` locates the clicked visual line by `indexOf(spanText)`
   over the runs' texts (plus a whitespace-collapsed whole-run fallback).
   The contract routes a click through the line box (`address`, character
   index) to a run via `run_spans`; that field is on the renderer line and
   frozen, so #333 built a stand-in. The stand-in refuses honestly where it
   cannot decide, which is the right failure mode, but it refuses cases the
   contract would resolve: a visual line whose text occurs twice in its run
   (`ambiguousPlacement` with no other hit → `run_text_differs`, lines
   357-378 of `run_map.ts`), and a line whose text occurs once in two runs
   (`multi_run`) even though the click was on one specific line box. The
   click's own `spanIndex` and line-box `address` are carried through the
   effect and never used to disambiguate.
2. **Caret and range are in different units.** `caret` reaches
   `prepareParagraphEdit` from the geometry click (`caretOffsetAt` over
   `char_x`, one entry per character, which the sidecar defines per
   code point) and is clamped to `rangeLen`, a UTF-16 length. For a line
   with a supplementary-plane character before the caret the two disagree by
   one per such character. The emoji test covers locate and replace, not a
   caret placed after the emoji. The contract's conversion rule has to be
   applied to `caret` (or `char_x` indices declared code-point and converted
   once at the boundary).
3. **A range computed on one text is applied to another.** `commitEdit`
   splices into `queuedRun?.text ?? edit.before`, and `prepareParagraphEdit`
   returns `before: args.queuedBefore ?? located.runText` while
   `rangeStart / rangeEnd` were located in `runText` from `readRegion` (the
   revision's source text). With a queued `set_run` on the same run whose
   length differs, the field shows the wrong slice and the commit splices at
   the wrong offsets. The contract's rule "a map is per revision" covers the
   queue too: a queued op is a pending text the displayed revision does not
   show. Either locate against the queued text or refuse a second range edit
   on a run with a queued op.
4. **Refusals the contract names are absent**: `utf16_split` (cannot arise
   from whole-character span text today, so this is a guard, not a bug),
   `control_in_range`, `no_char_map`.
5. **Controls inside the run are not considered.** `set_run` writes the
   run's whole `hp:t` text; a run holding `hp:lineBreak` or `hp:tab` inside
   its `hp:t` (the corpus has 30 `lineBreak`, 15 `tab`) would lose the
   control on the first edit, and the drawn line text (controls take no
   character) may not be an exact substring of the run text `readRegion`
   returns. No test has a control in the run.

## Missing tests

- A wrapped run whose second visual line repeats text from its first.
- Two runs sharing a line text, clicked on a known line box, expecting the
  clicked run (today: `multi_run`).
- Caret after a supplementary-plane character on the same line.
- Two successive edits on one wrapped run: change line 1's length, then edit
  line 2 (exercises finding 3).
- A run with `hp:lineBreak` or `hp:tab` in its text: edit must preserve the
  control or refuse `control_in_range`.
- Any Hangul text at all: every harness string is Latin or emoji; card 4 is
  Korean mixed, and Hancom source text can carry compatibility jamo or
  NFD sequences that make `indexOf` miss.
- The PR's own unchecked boxes: full suite, privacy scan.

## What remains for card 3 PASS

1. Route the click by geometry: either land `run_spans` on the renderer line
   (contract, frozen) or, interim, use the line box `address` + `spanIndex`
   with the sidecar's `text` to pick among equal text hits before refusing.
2. One unit at the boundary: convert `char_x` indices to UTF-16 once,
   test with an astral character before the caret.
3. Queue coherence: locate against the queued text or refuse; test with two
   edits on one wrapped run.
4. Controls: preserve or refuse, with a corpus paragraph that has one
   (`moel-2025` paragraph 73 holds a `hp:lineBreak` inside a wrapped run).
5. Hangul cases in the harness; full suite and privacy scan run and quoted.
6. Card 3's own PASS wording needs a real install: edit a wrapped Korean run
   on a hashed build, rerender, edit again. Nothing in #333 or here is that.

Reviewer: Fable by hand, no worker. No renderer probe, no IoU, no rematch.
