# Lineseg-on-save check — what does Hancom do to a cached `hp:lineseg` on resave?

2026-09-05, writer worktree `claude/engine-e3-lineseg-on-save` off HEAD
`f01de03` (`claude/engine-e3-roundtrip-render`). Corpus forms:
`tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx`,
`jeongbo-gonggae-cheongguseo.hwpx`,
`kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx` — all three confirmed
(pre-run) to already carry a cached `hp:lineseg` for nearly every paragraph
(69/67, 85/78, 840/798 lineseg/paragraph counts respectively). Aggregate
counts only; these are public government/agency form templates.

Question: when Hancom opens a document that already carries cached
`hp:lineseg` layout and saves it, does it (a) keep the cache byte-identical,
(b) rewrite it from its own layout, or (c) drop it? And what should
`own_render --line-layout auto` do with that cache on a Hancom-saved file?

## Method

Per form, two Automation runs (`pyhwpx`, single serial COM session each,
`tasklist /FI "IMAGENAME eq Hwp.exe"` confirmed empty before and after every
launch, `SetMessageBoxMode` guard against a modal — the same pattern
`engine/scripts/hwpx_accept.py` uses):

1. **no-edit**: open source, `save_as` to a new path, quit.
2. **edit**: open source, `hwp.find(anchor)` → `Cancel()` (deselect) →
   `Run("MoveParaEnd")` → `insert_text("X")` (one character appended to one
   table-cell body paragraph — a form-field label, e.g. "행 정 기 관 명"),
   `save_as` to a new path, quit.

The source is never touched (`hwp.open` only). Both output packages are
then read with the repo's own lexical reader (`hwpx_write.HwpxPackage`), a
flat document-order walk collects every `hp:p`'s `hp:linesegarray/hp:lineseg`
children, and each paragraph's cache is compared source-vs-candidate
field-by-field over all 9 `hp:lineseg` attributes (textpos/vertpos/vertsize/
textheight/baseline/spacing/horzpos/horzsize/flags). `hwpx_lint.py
--section-order` was run over all 6 candidates afterward: clean, 0 warnings.

## (1) Per-paragraph cache table

| form | mode | paragraphs | identical | changed | removed | added | both absent |
|---|---|---|---|---|---|---|---|
| gianmun-byeolji-1ho (67 p) | no-edit | 67 | 67 | 0 | 0 | 0 | 0 |
| gianmun-byeolji-1ho (67 p) | edit | 67 | 67 | 0 | 0 | 0 | 0 |
| jeongbo-gonggae-cheongguseo (78 p) | no-edit | 78 | 78 | 0 | 0 | 0 | 0 |
| jeongbo-gonggae-cheongguseo (78 p) | edit | 78 | 78 | 0 | 0 | 0 | 0 |
| kstartup-jiwon-...-saeopgyehoekseo (798 p) | no-edit | 798 | 795 | 0 | 0 | 0 | 3 |
| kstartup-jiwon-...-saeopgyehoekseo (798 p) | edit | 798 | 794 | 1 | 0 | 2 | 1 |

"both absent" = source has no `hp:lineseg` for that paragraph and neither
does the candidate — not a change, just an untracked-layout paragraph on
both sides (3 such paragraphs in kstartup's source; identical in the
no-edit resave).

**No-edit: 0/223 paragraphs across all three forms show any field
difference.** Every `hp:lineseg` cache — all 9 fields, every paragraph that
had one — comes back byte-identical after an untouched open/save-as. This
holds at every document size tested (67 to 798 paragraphs).

## (2) The edited paragraph itself

None of the three edited paragraphs' own `hp:lineseg` changed:

| form | edited paragraph index | field diff |
|---|---|---|
| gianmun-byeolji-1ho | 3 | none |
| jeongbo-gonggae-cheongguseo | 14 | none |
| kstartup-...-saeopgyehoekseo | 5 | none |

`horzsize` (the line box's available width) and the other cached fields
describe line-box geometry, not consumed text length — a single appended
character that does not push the line past its wrap point leaves the cache
untouched for that paragraph, in all three forms.

## (3) Cascading effect elsewhere (kstartup only)

The two smaller forms (67, 78 paragraphs) show **zero** knock-on effect from
the edit anywhere in the document. The 798-paragraph kstartup form does:

- **Paragraph 539** (534 paragraphs after the edit site, same section):
  `vertpos` `0` → `70884`; all other fields on that lineseg unchanged. The
  edit shifted this paragraph's vertical position — consistent with a
  downstream reflow cascade, not a local effect.
- **Paragraphs 11 and 12** (guide-text/placeholder cells, e.g. "기술이전완료
  : 계약체결 완료 기술명 기재"): had **no** `hp:lineseg` in the source and
  none in the no-edit resave (both-absent, unlaid-out on both sides), but
  **gained** one in the edit resave (`flags` `2490368`, distinct from the
  `393216` seen on every other measured paragraph in this corpus — a
  different line-type/visibility bit). These paragraphs went from
  "never laid out" to "laid out" purely as a side effect of the edit
  elsewhere in the document.

## (4) `hp:sz`, `hp:outMargin`, header.xml catalog

- `hp:sz` (object width/height): count and value identical, index-by-index,
  in all 6 runs (47/47 kstartup; 3/3 gianmun and jeongbo).
- `hp:outMargin`: identical, index-by-index, in all 6 runs.
- `Contents/header.xml` qname-count delta: **empty (`{}`) in all 6 runs** —
  no style/reference-catalog consolidation at all. This is the opposite of
  `docs/research/roundtrip-render-01.md`'s finding on the Rigorloom-authored
  51-feature document (which saw a substantial `hh:*`/`hp:default`/
  `hp:switch` churn on an untouched resave). Not a contradiction: these three
  corpus forms are themselves Hancom-native — official templates already
  saved by Hancom at least once — so their header catalog is already in
  Hancom's own canonical/deduplicated shape and a resave has nothing left to
  consolidate. The consolidation is a one-time normalization of a
  non-Hancom-shaped catalog, not a thing every save repeats.

## The rule Hancom applies

Not a passive "keep": Hancom recomputes line layout on every save, it does
not copy the stored `hp:lineseg` bytes forward. But the recomputation is
**deterministic and idempotent** — given unchanged content and structure it
reproduces byte-identical values, which is why an untouched resave measures
as 100% cache-preserving (0/223 changed above). The moment anything changes
the document's text flow — even one appended character, given a large enough
document for the effect to have somewhere to go — the recompute can diverge
from the stored cache in three ways, all observed here: the edited
paragraph itself (not necessarily — only if the edit changes wrapping),
unrelated *downstream* paragraphs whose position depends on cumulative flow
above them (§3, paragraph 539), and paragraphs that had no computed geometry
at all before (§3, paragraphs 11/12). This is closest to **(b) rewrite from
its own layout** — never a literal keep, never an unconditional drop; it
just converges back onto the same numbers whenever nothing about the flow
actually changed.

## Consequence for `own_render --line-layout auto` on Hancom-saved files

- Trusting the cache is safe on a file that is provably the direct,
  untouched output of Hancom's own most recent save — recomputation being
  idempotent means there is no cache-vs-render divergence to guard against
  in that case (measured: 0/223).
- **"Trust the cache only for untouched paragraphs" is not a safe local
  rule.** This run shows a one-character edit perturbing a paragraph 534
  positions later (`vertpos` shift) and un-blanking two other paragraphs
  elsewhere — a per-paragraph "did this paragraph's own text change" check
  cannot predict which *other* paragraphs Hancom's layout pass will also
  touch.
- Practical rule for `auto` mode: trust `hp:lineseg` wholesale only when the
  HWPX is provably Hancom's own most-recent save of its *current* XML
  content (no edits applied to the package since that save — the case for
  this repo's own edit-then-Hancom-resave pipeline, where Hancom is always
  the last writer). The instant any edit is applied to a Hancom-saved
  package *without* routing it back through Hancom (e.g. a Rigorloom
  XML-only patch on top of a Hancom-saved file), the cache must be treated
  as stale for the **whole document**, not just the touched paragraph, and
  `own_render` should fall back to its CJK-aware greedy-wrap path.

## Not proven

- Whether the cascade is always strictly downstream in document order, or
  can ever perturb a paragraph *before* the edit site — this run's one
  cascading paragraph (539) sits after the edit (paragraph 5); not tested
  with an edit placed later in the document.
- Behavior for edits larger than one character, or edits that do push a line
  past its wrap point in a small document — not tested; gianmun/jeongbo
  (67/78 paragraphs) may simply have been too small/simple for any
  cascading effect to appear, independent of edit size.
- Root cause of paragraphs 11/12 gaining a lineseg — plausible as a
  reflow side effect of the edit, not traced through Hancom's internal
  layout engine.

## Evidence

- `python scripts/py_compile_sweep.py` — clean.
- `hwpx_lint.py --section-order` over all 6 candidates — `ok: 6 file(s), 1
  check(s), no warnings`.
- Privacy gate: `git archive HEAD | tar -x` into scratch,
  `pipeline/scripts/privacy_scan.py` — 0 HARD findings. This document
  reports only aggregate paragraph-index counts and public form-template
  field labels; no personal data.
