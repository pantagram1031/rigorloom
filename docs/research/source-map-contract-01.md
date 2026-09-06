# Source map for run-scoped edits: the minimal contract (card 3 handoff)

One page. Renderer research line to product line. No code in this PR. The
product files this contract lands in belong to Cursor's #330 line
(`desktop/src/*`, `runtime/scripts/rt_core.py`); this document does not touch
them and must not be rematched onto any renderer tip.

## What the product needs, in the audit's words

Card 3 (#329): edit one plain-text run, including a run that wraps onto two
visual lines; in a multi-run paragraph edit the selected run only; a source
map of **revision / run / UTF-16**. The shipping desktop refuses `multi_run`
and `run_text_differs` (`desktop/src/actions.ts`). #330 binds the displayed
revision to geometry and region reads and adds `revision_mismatch`; it does
not add a run-level map.

## Tip SHAs this contract is written against

| what | SHA | why it matters here |
|---|---|---|
| product desktop tip (#221 lineage) | `0211c1888ad5` (last product commit `bf80c73c3383`) | carries the line-box fields below (desktop commit `30778e44`, an ancestor) |
| revision binding (#330 head, on the tip above) | `9f59b31c5039` | `displayedRevision` = `{sessionId, runId | null, documentSha256}`; geometry `subject` (document SHA) separate from `source.sha256` (raster SHA); `readRegion` and `pageGeometry` take `runId` |
| renderer research tip (parked, #323) | `eda8f60a7f94` | not required by this contract; nothing below depends on it |

The minimal tip for card 3 is therefore **`9f59b31c5039`**: it already has
the revision half. What is missing is one additive sidecar field and the
offset rule below.

## The three coordinates

1. **Revision** (exists, #330): `(sessionId, runId | null, documentSha256)`.
   `runId` null means the session source; otherwise the candidate artifact of
   that run. Every map, every geometry read, every edit plan cites the same
   triple. A raster or PDF hash is not a revision.
2. **Run address** (exists, `set_run` in `rt_plan.py`): `(atPara, run)` where
   `atPara` is the global `hp:p` document-order index and `run` is the ordinal
   of the `hp:run` child inside that paragraph, both 0-based. Inside a table
   cell the sidecar's `address` is `{kind: cell, table, row, col, atPara}`;
   `atPara` is still the global index, so `(atPara, run)` is enough to name
   the run and the cell fields are provenance only.
3. **Text range**: `[start, end)` in **UTF-16 code units** over the run's own
   text, defined as the concatenation, in document order, of every `hp:t`
   text node inside that `hp:run` (text, then each child control's tail),
   controls excluded. This is the string a JavaScript consumer holds. The
   engine indexes `Paragraph.chars` by code point; the conversion is exact:
   every character outside the BMP is 2 units and 1 point, everything else
   is 1 and 1. Hangul syllables, Hangul jamo, Latin, digits and every
   punctuation the corpus uses are BMP. A range that starts or ends between
   the two units of a surrogate pair is refused (`utf16_split`), never
   rounded.

## The one missing field: `run_spans` on a line box

Today a line box carries `text` (what was drawn, draw order), `char_x` (one
left edge per character plus the last right edge, device pixels at the
sidecar's dpi, present only where every character was measured), `size_pt`
(only when the whole line is one size) and `address`. A click resolves to
`(line box, character index)`. Nothing says which run that character came
from, so the desktop cannot name the run without re-reading the source and
comparing text, which is exactly the `run_text_differs` path.

Add, additively and optionally, to each line box that carries `text`:

```
"run_spans": [[run, start, end], ...]
```

`run` is the run ordinal above; `start` and `end` are code-point offsets into
this box's `text` (`[start, end)`, ascending, non-overlapping, covering every
character of `text`); a run that wraps appears in two boxes with two spans.
The engine has the information at draw time: `Paragraph.__init__` walks
`hp:run` children in order and appends to `chars` per run (`before =
len(self.chars)` per run), so the run ordinal of every char index is known
and only needs to be kept. The sidecar rule stays: absent where not measured,
never guessed; a box with `text` but no `run_spans` is an older sidecar and
the desktop reports that instead of falling back to text comparison.

With `run_spans` the click path is: box + character index → run ordinal and
code-point offset within the run (sum the box's preceding spans of that run
across earlier boxes of the same `address`) → UTF-16 offset by the conversion
above → `set_run(atPara, run, text)` under the displayed revision's lease.

## Limits, stated so they are not rediscovered

- **Multi-run paragraphs**: a range never crosses a run. `multi_run` stops
  being a refusal for "the paragraph has several runs" and becomes a refusal
  only for "the selection spans two runs". Sibling runs are not read or
  written.
- **Wrapped lines**: one run over N line boxes is one edit target; the
  caret may sit in any of the N boxes; the edit replaces the run's whole
  text or a range of it, and the candidate is re-laid out by the renderer
  under the computed policy, so line boxes of the candidate revision differ
  from the source's. The map is per revision; a map from one revision is
  never applied to another (`revision_mismatch`, #330).
- **Controls**: `hp:lineBreak`, `hp:tab` and the other cell-taking controls
  occupy a `textpos` cell but no character in `text` and no code unit in the
  range. A range cannot insert or delete a control; an edit whose text would
  need one is refused (`control_in_range`). Object slots (`OBJECT_SLOT` in
  `chars`: inline tables, pictures, notes) are the same: a run holding one is
  editable only in the text on either side of it, as two ranges.
- **Unmeasured boxes**: no `char_x` (a right-to-left or unmeasured line) or
  no single `size_pt` (a line set in two sizes) leaves the box clickable for
  selection but not for a caret offset; refuse `no_char_map` with the box
  named. Do not interpolate.
- **Empty runs** (`empty_runs` in `Paragraph`): a run with no text has no
  span in any box; it is addressable by `(atPara, run)` for a whole-run
  `set_run` only, and the insertion point is the run, not a box.
- **Layout policy**: the sidecar names `layout_policy` (cache or computed,
  #244). Under the cache policy the source's boxes follow cached `hp:lineseg`
  positions; the candidate never has a usable cache and is computed. Offsets
  are unaffected; pixel positions are not comparable across policies.
- **What this does not do**: it does not make any own render certified,
  does not prove Hancom would break the candidate the same way (path C is
  not run anywhere), and does not require LayoutSnapshot (#253 stays parked;
  `run_spans` is one field on the existing sidecar, versioned by the
  sidecar's existing schema id).

## Ownership and file boundary

- Renderer line (this line, when unfrozen): `run_spans` in
  `engine/scripts/own_render.py` `_annotate_line_box`, its sidecar schema
  note, and a test pinning one wrapped run and one multi-run paragraph from
  the public corpus.
- Product line (#330 owner): reading `run_spans` in `rt_geometry.py` /
  `rt_own.py`, the click path in `desktop/src/actions.ts`, dropping the
  `run_text_differs` text comparison, the `utf16_split` / `control_in_range`
  / `no_char_map` refusals. No renderer file.
- Neither side edits the other's files in the same PR. This document is the
  agreement; amend it by PR comment on this PR.
