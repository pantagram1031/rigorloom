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
