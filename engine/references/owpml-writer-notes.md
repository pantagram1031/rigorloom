# OWPML writer — what was measured (E3.1)

Slice E3.1 of `docs/plans/hangul-editor-endgame.md`: *every element the parser
reads, the writer emits; round-trip test = parse → serialize → byte-model
equality (canonicalized), on the whole corpus plus fuzzed variants*.

Ground truth is `tests/corpus/forms/**/*.hwpx` — 12 files Hancom itself wrote
(10 `converted/`, 2 `grant/`). Every number below comes from
`engine/tests/test_hwpx_roundtrip.py`, which asserts it.

**Not proven here, and not claimable from anything in this document: that
Hancom opens a Rigorloom-authored file without a repair dialog.** That is E3.2,
it needs COM, and this slice had none.

## 1. Inventory — the completeness target

`engine/scripts/hwpx_inventory.py` → `engine/references/owpml-inventory.json`.

| | corpus (12 forms) | blank document |
|---|---|---|
| distinct elements | 161 | 93 |
| element occurrences | 64 536 | 117 |
| distinct element/attribute pairs | 558 | 334 |
| distinct attribute names | 299 | 195 |
| distinct zip members | 12 | 10 |
| XML members | 8 | 8 |

All 161 elements are emitted: the writer is lexical, so "which elements it
supports" is not a list it keeps — the test asserts the emitted qname set
equals the inventory's, and that the blank document's element set is a
**subset** of the corpus surface (a new document must not invent elements
Hancom never showed).

No attribute or text **values** are recorded. `Contents/content.hpf` metadata
in the corpus carries author names, machine names and file paths; an inventory
that sampled values would be a privacy finding, not a reference.

## 2. Package shape Hancom writes

Measured over all 12 forms, 132 members:

- Member order is fixed, with three variants that differ only by which
  optional members exist:
  `mimetype`, `version.xml`, `Contents/header.xml`, (`BinData/image1.png`),
  `Contents/section0.xml`, `Preview/PrvText.txt`, `settings.xml`,
  (`Preview/PrvImage.png`), `META-INF/container.rdf`, `Contents/content.hpf`,
  `META-INF/container.xml`, `META-INF/manifest.xml`.
  8 forms carry `PrvImage` and no `BinData`, 2 carry both, 2 carry neither
  (the `grant/` pair).
- `mimetype` is first and **stored** (`application/hwp+zip`, 19 bytes).
  `version.xml` and every PNG are stored too (36 stored members); the other 96
  are deflated.
- Every one of the 132 members has timestamp `1980-01-01 00:00:00` and
  `create_system` 11.
- All 96 deflated members carry general-purpose flag bits `0x4` — compression
  option `0b10`, "fast" — which is **zlib level 2**. Level 2 reproduces the
  compressed size and CRC of the corpus members; no other level does.
- The archive comment is empty, and across 132 members the total extra-field
  and per-member-comment length is 0.

## 3. XML shape Hancom writes

All 96 XML members agree:

- Declaration, byte for byte, with the space before `?>`:
  `<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>`
- No trailing newline, no whitespace between elements, no indentation.
- Empty elements are self-closing with no space: `<a/>`. Zero occurrences of
  `<a></a>` in the corpus.
- Attribute values are always double-quoted. Only `&amp;` (7), `&lt;` (13) and
  `&gt;` (13) appear as entities; no CDATA, no comments, no PIs after the
  declaration.
- `header.xml`, `section*.xml` and `content.hpf` declare the same 15
  namespaces on their root, in the same order (`HANCOM_ROOT_NS` in
  `hwpx_write.py`) — including several nothing in the document references.
- `META-INF/container.rdf` is the one part that declares a namespace on a
  **non-root** element (`xmlns:ns0` on each `ns0:hasPart`), and Hancom itself
  writes the generated-looking `ns0` prefix there.

## 4. Model, and why it is not ElementTree

`ElementTree` cannot hold what byte fidelity needs: it discards the prefix a
qname was written with, the namespace declarations nothing uses, per-element
declarations, and the difference between `<a/>` and `<a></a>`.

So `hwpx_write.XmlNode` is a **lexical** DOM built with expat in
non-namespace mode: the qname keeps its prefix, attributes are an ordered list
that includes `xmlns:*` declarations, and `explicit_end` records the empty-tag
form. Namespace *meaning* is still available — `iter_with_scope`,
`namespace_scope`, `qualified_name`.

One trap worth recording: expat cannot distinguish `<a/>` from `<a></a>` — it
fires the same handler pair for both, and on this corpus reports
`CurrentByteIndex` **past** the tag for the empty case, so the naive "does the
byte at the index start `</`" test reports `<a/>` as explicit for every empty
element whose next sibling closes its parent. The source start tag is scanned
instead (`_start_tag_self_closes`).

## 5. Round-trip results

Corpus, 12 forms, 96 XML members:

| claim | result |
|---|---|
| byte-identical | **93 / 96** (96.9%) |
| canonical-equal (re-parse ⇒ same model) | 96 / 96 |
| idempotent (emit ∘ parse is a fixed point) | 96 / 96 |
| member list + per-member zip metadata preserved | 12 / 12 |
| repo readers (`form_inspect`, `xml_backend`) see the same document | 12 / 12 |
| source sha256 unchanged after write | 12 / 12 |

Per form (byte-identical XML members / XML members):

| form | ratio |
|---|---|
| admrul-gajokdolbom-hyuga-sinchengseo | 8/8 |
| gianmun-byeolji-1ho | 8/8 |
| gianmun-byeolji-2ho | 8/8 |
| jeongbo-gonggae-cheongguseo | 7/8 |
| jumin-deungchobon-sinchengseo | 7/8 |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | 8/8 |
| moel-pyojun-geunrogyeyakseo-2013 | 8/8 |
| moel-pyojun-geunrogyeyakseo-2025 | 8/8 |
| nrf-gyeolgwa-bogoseo-yangsik | 7/8 |
| pps-hyeopeop-seungin-sinchengseo | 8/8 |
| pps-jeongbogonggae-donguiseo | 8/8 |
| saeopja-deungnok-sinchengseo | 8/8 |

### The one canonicalization

Three members are canonical-equal but not byte-identical, and they are one
cause, not three:

- `jeongbo-gonggae-cheongguseo` / `Contents/section0.xml`
- `jumin-deungchobon-sinchengseo` / `Contents/section0.xml`
- `nrf-gyeolgwa-bogoseo-yangsik` / `Contents/content.hpf`

Each carries a literal `CR` inside character data (a picture's
`hp:shapeComment`, and a `<opf:meta xml:space="preserve">` block). XML 1.0
§2.11 requires every conforming parser to normalize `CRLF` and lone `CR` to
`LF` before the application sees it, so this information is destroyed at parse
time by *any* XML reader — it is not recoverable by a better writer. The
writer emits `LF`, re-parsing gives the identical model, and emitting again is
a fixed point.

These are **named** in the test (`CR_PARTS`), not counted: a newly
non-byte-identical member fails the suite instead of disappearing into 93/96.

### Archive level

7 of 12 archives reproduce byte-for-byte. Of the other 5:

- 3 are the CR members above (member CRC differs, because the content does).
- 2 (`kstartup-…`, `saeopja-…`) differ **only in the deflate encoding**: the
  member CRC matches exactly, the compressed length differs by 17 and 3 bytes
  on one large section. Deflate output is not specified to be reproducible
  across implementations, so per-member CRC — not archive bytes — is the
  honest archive-level claim, and that is what the test asserts.

Reproducing even 7 needed two things `zipfile` does not offer: per-member
`compresslevel` recovered from the source's flag bits, and stamping the
recorded general-purpose flag word back into the local headers and central
directory after assembly (`_restore_flag_bits`) — `zipfile` zeroes the
compression-option bits on write with no API to keep them.

## 6. Defects found in the existing paths

1. **`xml_backend.save` emitted non-Hancom XML** (fixed in this slice). It
   handed the tree to `ET.tostring(..., xml_declaration=True)`, which on the
   same corpus document produced:
   - `<?xml version='1.0' encoding='utf-8'?>` + newline instead of Hancom's
     declaration;
   - a root missing every namespace declaration no qname referenced — 13 of 15
     on a section root, 14 of 15 on `content.hpf`, shrinking that member from
     2038 to 1260 bytes (38%);
   - `<a />` with a space for every empty element — 862 in one header.

   None changes meaning; all three make an edited file trivially
   distinguishable from a Hancom-edited one. `save` now re-reads ElementTree's
   output into the lexical model and re-emits it, restoring the root
   declarations captured from the source bytes at open time.

   Result on the 48 members `xml_backend` can write: **45/48 byte-identical**
   when nothing changed; the 3 misses are the CR members.

2. **`ElementTree` cannot round-trip `container.rdf`.** Across all 96 members
   the ElementTree bridge reaches 81 byte-identical; the 12 extra misses are
   all `META-INF/container.rdf`, whose per-element `xmlns:ns0` declarations
   ElementTree hoists to the root and renames `ns1`. `xml_backend` never
   parses that member, so this does not reach production output — but any
   future path that edits `container.rdf` must use the lexical model, not
   ElementTree.

3. **`namespace_scope` was quadratic.** Resolving a prefix by walking to the
   root per node made a 500 KB section take minutes. `iter_with_scope` carries
   the scope down the walk; a test asserts the two agree.

4. Was true through this document's §8 pending item, now closed: `tidy_hwpx.py`
   and `preedit.py` used to rewrite archives with `zipfile.ZIP_DEFLATED` at the
   default level and let `zipfile` recompute flag bits (deflate-level-6, flag
   bits `0`, where Hancom writes level 2 with `0x4`). Both now route through
   `hwpx_write.write_members` (`tidy_hwpx._write_hwpx`,
   `preedit._write_zip`), covered by `engine/tests/test_hwpx_archive_routing.py`:
   132/132 members byte-identical and CRC-equal on an unchanged write, on both
   writers; archive-container bytes match source on 10/12 corpus forms — the
   other 2 are the same non-reproducible-deflate-encoding case as §5's archive
   level (member CRC still matches).

## 7. New-document path

`hwpx_write.blank_package()` builds the smallest package the model can express:
one section, one paragraph, ten members (the corpus layout minus
`Preview/PrvImage.png`, which a blank document has no render to embed).

Proven: member order and stored/deflated split match the OCF layout; every XML
member opens with the Hancom declaration; it round-trips byte-for-byte (8/8);
two builds are byte-equal; `form_inspect.analyze` and
`xml_backend.HwpxDocument` both read it; its element set is a subset of the
corpus surface. Its inventory is committed as
`engine/references/owpml-blank-inventory.json`.

It ships as a **deterministic builder plus per-member sha256 pins in the
test**, not as a committed `.hwpx`: `pipeline/scripts/privacy_scan.py` makes
every `.hwpx` a HARD finding unless sha256-pinned in
`tests/corpus/forms/manifest.json`, and that manifest documents provenance and
licence for official government forms — a Rigorloom-authored blank does not
belong in it. The pins are on **uncompressed** member bytes, since deflate
output can vary with the zlib build while member content cannot.

## 8. What is not written yet

- **Hancom acceptance (E3.2).** Nothing here says Hancom opens these files.
  Needs COM; no COM in this slice.
- **Archive bytes for large deflated members.** 2 of 12 archives differ only in
  deflate encoding of identical content. Closing that would mean shipping a
  deflate implementation matched to Hancom's, which is not worth it — CRC
  equality is the right claim.
- **A schema.** The inventory says what the corpus *uses*, not what KS X 6101
  *permits*. An element the corpus never showed is not in the 161, and the
  writer will emit it fine (it is lexical) but nothing here validates it.
- **Preview regeneration.** A written document keeps whatever `PrvText.txt` /
  `PrvImage.png` it was opened with; after an edit those are stale. E1/E2 own
  the render that would refresh them.
- **BinData round-trip beyond bytes.** `BinData/*.png` members pass through
  byte-identical, which is all the corpus needs; nothing parses or re-encodes
  them.

## 9. Section head control order

Measured on the writer line's own render-check evidence
(`docs/research/render-check-01.md` note 4 and
`engine/tests/test_column_ctrl_order.py`,
`origin/claude/engine-e2-columns-f49`, `gh pr view 222`): the OWPML schema
(`ParaList XML schema.xml`) lets the section-head paragraph carry its
`hp:ctrl` children in any order — `colCount="2"` survives a Hancom
round-trip whatever the order is — but **Hancom only lays a section out in
columns when the `hp:colPr` control is not preceded by a header or footer
control in that same paragraph.** No attribute changes this: `type`
(NEWSPAPER / BALANCED_NEWSPAPER), `layout`, `sameSz`, `sameGap` and explicit
`hp:colSz` children all move nothing across the line.

Ten probe documents, one section per case, official Automation (Hwp 2024
13.0.0.2986), PDF export read back for the x-extent of the text
(`colCount="2"` declared in every case):

| case | section-head control order | Hancom renders |
|---|---|---|
| `P1` | `secPr`, header, footer, `colPr` `sameGap=0` | one column |
| `P2` | `secPr`, header, footer, `colPr` `sameGap=1134` | one column |
| `P3` | `secPr`, header, footer, `colPr` `sameSz=0` + 2×`colSz` | one column |
| `P6` | `secPr`, header, footer, `colPr` `BALANCED_NEWSPAPER` | one column |
| `P7` | `secPr`, header, footer, `colPr` `sameSz="true"` | one column |
| `Q1` | `secPr`, header, `colPr`, footer | one column |
| `Q3` | `secPr`, footer, `colPr` | one column |
| `Q2` | `secPr`, `colPr` | **two columns** |
| `P4`/`Q4` | `secPr`, `colPr`, header, footer | **two columns** |
| `P5` | `secPr`, header, footer; `colPr` in the *next* paragraph | **two columns** |

The rule: Hancom honours an `hp:colPr` that comes straight after `hp:secPr`
(`Q2`, `Q4`), and it honours one carried by a later paragraph (`P5`) — but a
header or footer control anywhere between `hp:secPr` and `hp:colPr` in the
*same* paragraph shadows it, silently. There is no repair dialog and no
warning; the document opens fine and simply renders full width. Valid
orders for a section that wants columns are therefore `secPr, colPr, …`
(furniture after) or `colPr` deferred to the paragraph following the
section head.

**Consequence for any emitter, this one included:** `blank_package()`'s
`_BLANK_SECTION` template already emits `secPr` then `colPr` with no
furniture in between, so it is not exposed to this — but it carries no
header/footer today and nothing here assembles a section head from parts
(see §7). Any future path that adds header/footer controls to a section
that also wants `hp:colPr` must place `colPr` immediately after `secPr` and
put the furniture after it, never between. `engine/scripts/hwpx_lint.py
--section-order` checks this over a built `.hwpx` (read-only — it warns, it
never reorders a document handed to it) and is covered by
`engine/tests/test_hwpx_lint.py`, including a run against both sides of the
F49 fix (`origin/claude/engine-e2-columns-f49`, commit `350ee56` and its
parent) via `git show`.

## 10. Reproducing the numbers

```
python -m pytest engine/tests/test_hwpx_roundtrip.py -q      # 104 tests
python engine/scripts/hwpx_write.py verify <form.hwpx>       # per-part report
python engine/scripts/hwpx_inventory.py tests/corpus/forms \
    --out engine/references/owpml-inventory.json             # regenerates in place
python engine/scripts/hwpx_write.py blank out.hwpx           # new document
```
