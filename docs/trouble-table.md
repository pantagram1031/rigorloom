# Trouble table — promoted anomaly fixes

A signature-matched lookup table of anomalies that recurred during real runs and
now have a known fix. It complements the prose in `troubleshooting.md`: use that
document to reason about a class of problem, use this table to match a concrete
symptom to its cause and remedy quickly.

Format: one row per known issue. `signature` is the observable symptom a detector
or a human matches on; `cause` is the mechanism; `fix` is the durable remedy. The
`origin` column is kept generic on purpose — it names the kind of run that surfaced
the issue, not the report.

| id | signature (symptom) | cause | fix | origin |
|----|---------------------|-------|-----|--------|
| T1 | stray blank paragraphs between subsections (line-spacing histogram outlier, 2–3 line gaps) | pyhwpx `^n` literal find/replace has no traction on empty paragraphs | delete-blank-before op with explicit paragraph targeting; verify via layout-QA gap check | assembly run, 2026-07-06 |
| T2 | dataset file tiny (~14 B) containing "404: Not Found" | download saved an error page silently | assert size + header on every dataset download (Stage 1 rule) | dataset-download incident |
| T3 | multi-row matrix renders broken in the word processor | LaTeX `\\` row separator not converted to HwpEqn `#` | equation adapter converts `\\`→`#` in matrix bodies; sanity check fails on leftover `\\` | equation-heavy run |
| T4 | reference URLs lose exactly the last 8 chars; tails accumulate reverse-ordered as a garbage line | insert-hyperlink op records the end position BEFORE field creation; field markers shift offsets so the cursor set lands short | re-acquire the end position after the hyperlink field is created (or MoveParaEnd) before setting position | assembly run, 2026-07-07 (COM backend) |
| T5 | line-spacing uniformity never passes on record-sheet–type forms | cover/summary pages have designed large whitespace; page-bottom breaks read as gaps | exempt declared cover pages + gaps in the bottom 10% of a page | assembly run, 2026-07-07 |
| T6 | COM find fails on anchor text spanning character-run boundaries (e.g. a heading stored as two runs) | `find()` matches only within a single run | use a single-run substring as the anchor (verify uniqueness in both form and content) | assembly run, 2026-07-07 |
| T7 | paragraph-mark deletion near headings reassigns adjacent character shape (e.g. 16 pt→10 pt) and/or merges a heading into the previous paragraph | Delete across a paragraph boundary inherits the pending character shape; a newline-count progress metric cannot distinguish a blank from a non-blank paragraph-mark | NEVER drain blanks via COM find/delete near headings — do blank cleanup as an offline HWPX XML post-pass | assembly run, 2026-07-07 |
| T8 | body text inserted INTO an in-table anchor-label paragraph | goto-text next-paragraph no-ops when the anchor cell has a single paragraph — the cursor stays in the label paragraph | goto-text runtime guard: after the move, if the current paragraph still contains the anchor text, insert a paragraph break before the body | assembly run, 2026-07-07 |
| T9 | form heading/label paragraphs lose their designed 180–200% line spacing (flattened to body 160%) | a document-wide set-line-spacing op needed for inserted body also hits form-owned paragraphs | capture paragraph formats in the form baseline (Stage 0) + a post-pass that restores form paragraphs; a style-diff paragraph-format check gates it | assembly run, 2026-07-07 |
| T10 | inserted body in a form box renders CENTER-aligned (label paragraph shape inherited after the T8 paragraph split) | the new paragraph from the split inherits the anchor label's centered paragraph shape | the goto-text guard also applies justify alignment after the split | assembly run, 2026-07-08 |
| T11 | section heading pulled onto the previous (summary) page after guide-table deletion + blank tidy | the form used blank-paragraph stacks as page pushers; deleting content above collapses them | page-break-before op on the heading anchor (and exclude that anchor from tidy-blank-before) | assembly run, 2026-07-08 |
| T12 | table caption orphaned at page bottom, table body on the next page | the caption paragraph lacks keep-with-next | a keep-with-next block list in the build config → post-pass sets the keep-with-next paragraph attribute | assembly run, 2026-07-08 |
| T13 | inline equation superscript/subscript over-grabs — a bare script like `x^2)=…` renders with `2)=…` all raised as an exponent | HwpEqn `^`/`_` with no braces takes the WHOLE token up to the next space; a bare `x^2)` has no space, so it eats through to the next space. The equation adapter passed bare scripts through verbatim | equation adapter auto-wraps the next single atom (a brace-scripts step): `x^2`→`x^{2}`, `D_p`→`D_{p}`. Authoring rule: ALWAYS brace multi-adjacent scripts in EQ LaTeX (`x^{2}`, `D_{pq}`), and never put `\,` right after `{` (leaves a stray space). Verify EVERY equation at 300 dpi, not at page-level 90 dpi | equation-heavy run, 2026-07-10 |
| T14 | a body line is justify-stretched with huge word gaps — the text line before a long inline equation spreads across the full width | a wide inline equation (treat-as-char, atomic) cannot fit at the line end → it wraps to the next line → the preceding lead-in becomes a "full" justified line the word processor stretches. Position-dependent, so fragile on reflow | make long multi-step derivation chains a DISPLAY equation (its own centered paragraph, no orphan-stretch) and rephrase so the equation ends its clause (lead-in sentence + display equation + continue). Keep short references inline. This is proper math typography anyway | equation-heavy run, 2026-07-10 |
| T26 | a replaced cell reads `" http://example.krexample.kr"` with `hits: 2` — the value appears twice, concatenated, from a single mapping entry | `preedit replace` ran tier B (raw substring) over the string tier A (whole-run) had just rewritten, so a value containing its own key was applied twice. The same mechanism broke re-run idempotence (2nd run has no tier-A rewrite but tier B still finds the key inside the final value) and let a later key rewrite an earlier key's value. Measured with operations.md's OWN documented example | single-pass semantics: every span a tier writes is protected for the rest of the call, and spans already equal to the value are protected before any tier runs. One value is written once; re-runs report 0 hits | clean-room cross-model run, 2026-08-08 |
| T27 | a form's empty cells cannot be filled offline — `preedit replace` reports 0 hits for every fill target and the skill routes you to COM | an empty form cell is not "a cell with empty text": it is `<hp:run charPrIDRef="N"/>`, a self-closing run with **no `<hp:t>` element at all** (19 of 19 empty cells on the PPS 협업승인신청서). A text-keyed operation has no string to key on, so the offline path was structurally unreachable and both clean-room agents fell through to COM (and then hit T28) | `preedit fill-cells` — address cells by the `cellAddr` that `form_inspect`'s `table_map` reports, create the `<hp:t>` inside the empty run preserving its charPr, refuse a non-empty target unless `--overwrite`, strip the paragraph's stale linesegarray (T24), well-formedness check before writing. `table_map` itself was made nesting-aware so both tools share one table index | clean-room cross-model run, 2026-08-08 |
| T28 | COM `set_cell` silently writes into the WRONG cell — a label cell gets destroyed on the first attempt; separately, `get_into_nth_table(0)` lands somewhere different on repeated calls in one Hancom session | `row`/`col` were **keypress counts**, not addresses: `TableRightCell` wraps across rows and `TableLowerCell` jumps over rowSpans, and merged cells leave holes in the coordinate grid. On the PPS form, targeting cellAddr (2,3) landed on (2,6) `법인등록번호`; (2,7) landed on (4,2) `주 소` | `addr: [row, col]` means cellAddr and is translated by walking `TableRightCell` (which wraps, so it visits every cell and is immune to both rowSpans and entry drift), verifying `get_cell_addr()` after every move and aborting without writing on mismatch. `expect_empty` / `expect TEXT` refuse when the target's content disagrees. Legacy keypress mode only under an explicit `raw_traversal: true`. Mitigate the nth-table drift with `com_backend.py set-cell`: one invocation = one session = one cell, serial, never `--kill-stale` (T21) | clean-room cross-model run, 2026-08-08 (COM-verified: cellAddr (2,3) reached in 4 steps, label cells intact) |

## Notes on T13/T14 (HwpEqn scope)

These two are the most transferable equation-adapter lessons, so they keep full
detail:

- **Brace every adjacent script.** HwpEqn `^`/`_` without braces claims everything
  up to the next whitespace. `x^{2}` is safe; `x^2)` raises `2)` and whatever
  follows until a space. The adapter now auto-braces a single following atom, but
  authored LaTeX should still brace multi-character scripts explicitly.
- **Avoid `\,` immediately after `{`.** It leaves a stray space inside the braced
  group.
- **Proof resolution matters.** Page-level thumbnails (~90 dpi) hide token-scope
  errors. Inspect any page with a newly generated inline equation at 300 dpi.
- **Long derivations belong on their own line.** A wide inline equation forces the
  preceding line to justify-stretch. Promote multi-step chains to display
  equations and end the lead-in clause before them; keep only short references
  inline.
