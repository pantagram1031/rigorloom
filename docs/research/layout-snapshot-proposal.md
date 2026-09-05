# A `LayoutSnapshot` contract — proposal

Status: PROPOSAL, not a protocol change. Nothing in this document is
implemented by this commit; it describes a shape and asks the Desktop/Codex
line to agree it before either side writes code against it. Grade stays
`own-uncertified` throughout — this document does not raise it.

worker: Sonnet; orchestrator: Fable.

## 0. Why this document exists

The renderer (`engine/scripts/own_render.py`) already emits a sidecar per
render and the Desktop already reads geometry back out of it in one mode
(`rt_geometry.own_page_geometry`, tier 3). But the fields the two most recent
renderer slices add — `x1`/`x1_advance`/`x1_ink`/`x1_visible_advance` on every
line box (PR #242, unmerged as `claude/engine-e2-linebox-end`) and
`layout_policy`/`layout_policy_reason`/`layout_provenance` at the document
level (PR #244, unmerged as `claude/engine-e2-cache-policy`) — are not yet in
`docs/checkpoint-13`'s tree and are not yet named as a single versioned
contract anywhere. This proposes that contract: what a `LayoutSnapshot` is,
what each ambiguous-looking field means, and where the line between "the
renderer's own claim" and "a caller's assumption" has to stay drawn.

## 1. The `LayoutSnapshot` contract

A `LayoutSnapshot` is the full answer for one page (or one document) at one
render: the identity a caller needs before trusting that a caret rectangle
and a PNG pixel are talking about the same layout decision.

```
LayoutSnapshot {
  schema_version:        "layout-snapshot/0"      # this proposal's own id;
                                                    # bump on any field add/
                                                    # remove/meaning change
  document_revision: {
    content_digest:      sha256 of the .hwpx package bytes the render read
    edit_lineage_id:      string | null            # in-session edit lineage,
                                                    # e.g. the OperationPlan
                                                    # receipt chain position;
                                                    # NEVER conflated with
                                                    # version.xml@application
                                                    # (see §3) — this is an
                                                    # internal claim, that is
                                                    # an external one
  }
  renderer_build: {
    git_sha:              the renderer's own commit
    own_render_version:   "rigorloom-own/0.1"      # engine/scripts/own_render.py's
                                                    # own renderer id, verbatim
  }
  layout_geometry_schema_id: "own-render-lineboxes/<n>"  # bump when
                                                    # line_boxes/cell_boxes
                                                    # field shapes change,
                                                    # independent of
                                                    # schema_version above
  layout_policy:          "cache" | "computed"      # PR #244 vocabulary
  layout_policy_reason:    string                   # e.g. "policy",
                                                    # "cache_absent",
                                                    # "textpos_past_end",
                                                    # "caller_marked_edited",
                                                    # "stale_cache_contradicts_provenance"
  layout_provenance: {
    writer:  "hancom_untouched" | "rigorloom_written" | "unknown_writer"
  }
  fonts: {
    faces: [{
      declared:            the family the document asked for
      resolved:            the family actually drawn
      source:              "installed" | "bundled" | "system"  # PR from
                                                    # "Bundled Korean fallback
                                                    # faces", already shipped
      family_map:           string | null           # bundled family name,
                                                    # when source == "bundled"
      character_count:      int                     # how many characters on
                                                    # THIS snapshot this face
                                                    # drew — not a document-
                                                    # wide census
    }]
  }
  pages: [{
    page_index:            0-based
    size_px:               [width, height] at this render's dpi
    line_boxes: [{
      address:              GeometryAddress | null   # what exists today in
                                                    # rt_geometry's mapping,
                                                    # carried through rather
                                                    # than re-invented
      char_x:               [float, ...] | null      # per-character left
                                                    # edges + final right
                                                    # edge, i.e. rt_geometry's
                                                    # char_edges contract:
                                                    # present only when the
                                                    # renderer resolved
                                                    # exactly one box per
                                                    # character
      size_pt:              float
      mode:                 "lineseg" | "computed"   # already shipped —
                                                    # which engine broke
                                                    # this line
      x0, x1_advance, x1_ink, x1_visible_advance, x1:
                             float                   # see glossary, §2
    }]
    cell_boxes: [{
      table, row, col:      int
      x0, y0, x1, y1:        float
    }]
    elements_skipped: [string, ...]   # already shipped, forwarded verbatim
  }]
  output_digests: {
    page_png_sha256:        [string, ...]            # one per page
    sidecar_sha256:          string
  }
}
```

**The rule this whole contract exists to state plainly:** a PNG and the
caret/cell geometry drawn over it MUST cite the same `document_revision` +
`renderer_build` + `layout_geometry_schema_id` triple, or a client is
comparing two different renders' claims about the same document and any
agreement is coincidence. `rt_own.any_own_for` already binds a cached render
to `subject_sha256`; this proposal generalizes that one binding into a full
snapshot identity so geometry, PNG, and (later) a diff against a Hancom
render can all be pinned to the same run without re-deriving the binding
per consumer.

Today's sidecar (`own_render.py`'s JSON output) already carries most of the
leaf data — `line_boxes`, `cell_boxes`, `elements_skipped`,
`fonts.faces[].source` — under different top-level shapes and without a
schema id or a document-revision/renderer-build header. This section names
the union that would make it one addressable object; it does not require
restructuring the existing sidecar in place (see §5, ownership).

## 2. Glossary — the four ways a line's right edge can be read

Named and measured in PR #242 (`claude/engine-e2-linebox-end`), on the
evidence that `render_scoreboard`'s own reference boxes are advance boxes,
not ink boxes (a 12.96pt Hangul character in the `nrf` reference PDF measures
exactly 12.96pt wide — its full cell advance, not its narrower ink).

| field | what it is | who needs it |
| --- | --- | --- |
| `x1_advance` | the advance of every glyph piece on the line, a trailing space included | a **caret** — where the next keystroke lands |
| `x1_ink` | where the last glyph's outline stops: the advance minus that glyph's right side bearing | a **containment check** — "does this line fit inside its column" |
| `x1_visible_advance` | the advance of the last piece that draws ink: trailing whitespace dropped from the advance reading | what `own_render.LINE_BOX_END` is currently set to, chosen because on the 34 corpus lines ending in whitespace it beat plain `advance` 0.363 vs 0.371 px median `abs(dx)` against the confident-pair subset |
| `x1` | the geometry box — whichever of the above `own_render.LINE_BOX_END` currently names | the renderer's own declared line end; this is the field a caller reads when it wants "the" box, not a specific convention |

**Never mix them.** The two fixes each convention exists to make possible
are the cautionary examples:

- **#245** (`claude/engine-e2-converge-03`, converging #242/#243/#244)
  inherits the containment test that regressed when trailing-space handling
  first made the advance box visible: `test_a_relaid_out_paragraph_stays_
  inside_its_column` had to give up a one-pixel bound on `x1` because the
  *advance* reading (correctly) hangs past the column on a trailing space.
  The fix was not to loosen the bound on `x1_ink` too — `x1_ink` kept its
  tight bound throughout, because ink is what "stays inside its column"
  actually means. Only `x1_advance` was given the explicit half-cell
  allowance, and the fixture now asserts it actually takes it (7.020px /
  8.667px at 96dpi). Reading `x1_advance` where the test needed `x1_ink`
  would have hidden the exact regression the test exists to catch.
- **#248** (`claude/desktop-on-renderer-245`, the desktop re-merge onto the
  renderer tip) is the consumer-side half of the same rule: a caret placed
  from `x1_ink` on a line ending in a space would land one glyph short of
  where the user actually pressed the key, because ink stops before the
  space's advance does. `rt_geometry.char_edges` already encodes the
  opposite failure mode for the PDF-read path — it returns `None` rather
  than a guessed offset the moment box count and character count disagree —
  and this contract's `char_x` field is meant to inherit exactly that
  refuse-to-guess discipline for the own-render path: a caret request reads
  `x1_advance`, a fit/overflow check reads `x1_ink`, and nothing reads `x1`
  expecting either meaning.

## 3. The `version.xml@application` caveat

`layout_provenance.writer` is read from `version.xml@application`, the only
writer signature an HWPX container carries (PR #244). Stated as plainly as
the source material states it:

**`version.xml@application` is the external file's CLAIMED writer. It is
neither proof of an untouched state nor a certificate of the last writer.**
It says which program wrote the package; it cannot detect a third program
that edited a Hancom-saved file while leaving Hancom's signature in place.
The one detector layered on top of it, `stale_line_width`, catches such an
edit only when it makes some line overflow its own box — sound (fires on no
paragraph of any of the ten corpus forms) but incomplete (an edit that
leaves every line still fitting is invisible to it). And whether Hancom
itself preserves this repo's own `Rigorloom` stamp across a resave is **NOT
MEASURED** — if it does, an edited-then-Hancom-resaved package would stay
pinned to `computed` forever, which is the safe direction but not the
accurate one.

The cache policy PR #244 builds on this claim (`hancom_untouched` → `cache`,
everything else → `computed`) inherits that same uncertainty by construction,
and does not resolve it — it is a decision under uncertainty, declared as
one, not a proof.

**How `document_revision.edit_lineage_id` differs.** `version.xml@application`
is a claim the *external file* makes about itself, readable by anyone who
opens the package, and it is exactly as trustworthy as whatever last wrote
that one attribute. `edit_lineage_id` is an *internal* session claim — this
proposal's placeholder for something like the OperationPlan receipt chain
position already used for undo — and is never a substitute for the file's
own signature: a snapshot can carry a real `edit_lineage_id` while
`layout_provenance.writer` is `unknown_writer`, if the session edited a file
whose own writer signature nobody trusts. Conflating the two would let an
internal session claim launder an external file's unverifiable one; keeping
them as separate contract fields is the point of listing both under
`document_revision` rather than folding `edit_lineage_id` into
`layout_provenance`.

## 4. Support levels — kept separate, and not interchangeable evidence

| level | what it is | current status |
| --- | --- | --- |
| **A** | View of the **original**, unedited document, laid out from the **cached** `hp:lineseg` (`layout_policy: "cache"`) | Measured extensively — this is what "byte-identical unedited render" already means across the ten-form corpus and the private report-class holdout (checkpoint-13's own-render-notes.md, throughout) |
| **B** | Re-layout of the **same original**, with the cache bypassed (`--layout-policy computed` / `layout_policy: "computed"`), measured against the corpus's own Hancom reference PDFs | Measured — PR #244's own table: corpus mean `text_line_iou` cache→computed −0.0550, page-count-exact 9/10 (cache) vs 10/10 (computed); PR #242's line-box-end measurement (`text_line_iou_mean` −0.00177 for `visible_advance` vs `advance`) is layered on top of this level |
| **C** | An **edited** candidate, re-laid out, compared to a **licensed Hancom output of the same edit** | **NOT RUN.** Checked `engine/references/hancom-acceptance-01.md` and `-02.md` (E3.2, the only "Hancom acceptance" evidence in the tree): both measure the **writer round-trip** — does Hancom open a Rigorloom-authored/edited `.hwpx` without a repair dialog, and is the edit marker preserved on reopen. Neither compares own_render's *layout* of an edit against a Hancom *render* of that same edit. No such comparison exists anywhere in this repo's history as of this commit. |

**Level A's success is not evidence for Level C.** An unedited render being
byte-identical to a cached-layout reference proves the renderer can *play
back* a layout Hancom already computed; it says nothing about whether the
renderer's *own* line breaker and flow pass — the parts that only run once
something is edited — agree with what Hancom would compute for that same
edit. Level B is the closest existing evidence for that question, and it is
explicitly worse than Level A on the geometry channels that matter for a
caret (`text_line_iou` down on eight of ten corpus forms). Level C is the
only level that would actually answer it, and it has not been attempted.

Every level stays `own-uncertified` under `render_cert.py`'s existing
per-document-class promotion path — nothing here proposes a promotion.

## 5. Ownership / handoff

This document is written from the renderer side and does not commit the
Desktop/Codex line to anything by itself.

**Renderer side (this line) would own:**
- `engine/scripts/own_render.py` — emitting `x1`/`x1_advance`/`x1_ink`/
  `x1_visible_advance` per line box (already in #242), `layout_policy`/
  `layout_policy_reason`/`layout_provenance` (already in #244), and — new
  in this proposal, not yet in either PR — `schema_version`,
  `layout_geometry_schema_id`, `document_revision.content_digest`, and
  `output_digests`.
- `engine/references/own-render-notes.md` and `docs/research/*.md` — the
  measurement record this contract is built from.
- `render_scoreboard.py` / `render_cert.py` — measuring any of the above
  against Hancom references, and the certification gate itself.

**Desktop/Codex line would own, separately, and only by agreement reached
through this document or its PR thread (no direct messaging assumed):**
- `runtime/scripts/rt_own.py` — the `rt_own` cache keyed on
  `subject_sha256`; extending that key to a full `LayoutSnapshot` identity
  (§1) so a cached render and its geometry answer cannot drift apart is a
  Desktop-side change to that cache's key shape.
- `runtime/scripts/rt_geometry.py` — `own_page_geometry`, `derive_own_seats`,
  `char_edges`; consuming the new `x1_advance`/`x1_ink`/`x1_visible_advance`
  fields (§2) in place of whatever single convention the caret path reads
  from today is a Desktop-side change to that consumption, not a renderer
  change.
- `desktop/src/runtime.ts`, `desktop/src/types.ts`, `desktop/src/store.ts`,
  `desktop/src/components/PagePreview.tsx` — any UI or IPC surface that
  would expose `layout_policy`/`layout_provenance`/the new digest fields to
  a user or an agent.

Nothing above is executed by this commit. It is the boundary this document
proposes; the Desktop/Codex line either accepts it, counter-proposes on the
PR, or leaves it for a later slice.

## 6. What this does NOT do

- Does not change any renderer or Desktop code. This commit is docs-only.
- Does not merge #242, #244, #245 or #248 to `main`, and does not merge this
  branch to `main` either — it targets the PR this task was handed on
  (`claude/docs-checkpoint-13`, PR #251).
- Does not raise `own_render`'s grade above `own-uncertified`, and does not
  run or promise `render_cert` certification for any document class.
- Does not perform the Level C measurement §4 names as missing. Running it
  is future work this document only scopes.
- Does not unilaterally fix or restructure the existing sidecar shape —
  §1's union is a proposal for what a future sidecar/geometry-answer pair
  could look like, not an instruction to rewrite either today.
- Does not open any private or licensed document, and reports no numbers
  beyond what the cited public-corpus and aggregate-only holdout sources
  already state in the tree.

---

Sources read for this proposal: `engine/references/own-render-notes.md`
(checkpoint-13, `claude/docs-checkpoint-13`); the unmerged `x1`/`x1_advance`/
`x1_ink`/`x1_visible_advance` section of the same file on
`claude/engine-e2-linebox-end` (PR #242); the unmerged `layout_policy`/
`layout_policy_reason`/`layout_provenance` section of the same file on
`claude/engine-e2-cache-policy` (PR #244); `docs/research/
residual-advance-and-ink.md` (`docs/research-residual`); `docs/plans/
hangul-editor-endgame.md` (`docs/hangul-editor-endgame`); `runtime/scripts/
rt_geometry.py` and `runtime/scripts/rt_own.py` on `claude/
desktop-on-renderer-245` (PR #248), for the Desktop's current consumption
(`document/pageGeometry` → `rt_geometry.own_page_geometry` reads
`line_boxes`/`cell_boxes` out of the tier-3 sidecar via `rt_own`, maps them
through the same `map_spans` a Hancom-PDF-read page uses, and derives
`own_cell` seats straight from drawn cell rectangles); and
`engine/references/hancom-acceptance-01.md` / `-02.md` for the Level C check
in §4.
