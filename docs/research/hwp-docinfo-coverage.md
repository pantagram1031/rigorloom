# T90 HWP DocInfo coverage

T90 is a receipt-only, source-side reference-coverage diagnostic. Its schema is
`rigorloom/hwp-docinfo-coverage/v1`; it is separate from T85 ingress, T86/T87
conversion candidates, T88 paired agreement, T89 BodyText coverage, Stage 0,
canonical output, native execution, rendering, and submission. The exact claim
scope is `docinfo_record_cardinality_and_bodytext_reference_bounds_v1`.

The scanner captures the HWP once, runs the strict T85 CFB/FileHeader gate, and
requires one direct-root nonempty `DocInfo` stream. It checks the complete
record envelope, one 26-byte DocumentProperties record followed by one
72-byte `ID_MAPPINGS` record, closed definition-group order and cardinality,
and bounded aggregate counts. `ID_MAPPINGS` is an 18-element signed count
array. Its indexes describe BinData, seven FaceName languages, BorderFill,
CharShape, TabDef, Numbering, Bullet, ParaShape, Style, MemoShape,
TrackChange, and TrackChangeAuthor. These are zero-based arrays: ID 0 means
the first real definition, not a null or default sentinel.

T90 also rescans the T89 `BodyText ParaHeader` and ParaCharShape surfaces from
the same captured bytes. It checks ParaShape, Style, and CharShape IDs against
the corresponding declared and physically present definition counts.
ParaCharShape records must have an exact eight-byte-pair shape, begin at
position zero, and have strictly increasing positions. The positions are HWP
WCHAR/control-stream units, not visible-character offsets: ordinary WCHARs and
character controls occupy one unit, while inline and extended controls occupy
eight. T90 does not promote this ordering check into layout or text semantics.

## Evidence ceiling

The definition payload semantics remain deliberately outside v1. In
particular, CharShape language-face details, Style redirects, ParaShape
head/level and numbering-or-bullet selection, Numbering formats and sequence
state, Bullet glyph/image branches, generated numbering controls, paragraph
split state, and versioned payload tails are not interpreted. They remain
closed `not_scanned_tokens`. Count and ID-bound completeness therefore cannot
prove the visible text, style, generated prefix, or layout of a paragraph.

Accordingly, `eligibility` remains `unknown`, `comparison` remains `unknown`,
`render` is `not_run`, `proof_grade` is `none`, and `submission_grade` is false.
There is no v1 eligible outcome. T90 is not source fidelity, a semantic oracle,
conversion parity, native execution, render quality, or submission evidence.
Every analyzed or refused CLI result exits 3; help exits 0 and usage errors
exit 2.

## Receipt-only use

Pre-create the canonical schema-owned leaf and use an opaque lowercase
hexadecimal run id. Leaf-name matching is case-insensitive on Windows, while
the documented spelling remains canonical:

```text
mkdir work/stage-0/scratch/hwp-docinfo-coverage
python pipeline/scripts/hwp_docinfo_coverage.py inspect INPUT.hwp --coverage-root work/stage-0/scratch/hwp-docinfo-coverage --run-id HEX
python pipeline/scripts/hwp_docinfo_coverage.py verify INPUT.hwp --coverage-root work/stage-0/scratch/hwp-docinfo-coverage --run-id HEX
```

The only public artifact is
`hwp-docinfo-coverage/<run-id>/receipt.json`. The receipt carries only the
current source hash/byte/version descriptor, closed count keys, aggregate
counts, closed states, and reason tokens (see below). It carries no raw IDs,
source text, style names, numbering formats, bullet glyphs, raw record bytes,
metadata, absolute paths, argv, stdout, or stderr. Verification rereads the
current source and receipt and rejects drift, forged eligibility, noncanonical
JSON, receipt hard links, symlinks/reparse paths, changed roots, and unexpected
run layout. A hardlinked source is permitted because the receipt binds the
captured source bytes rather than claiming exclusive custody of the input.

## Reason tokens

The spelling of a reason is part of the contract, and the two spellings mean
different things.

- **Dotted** (`docinfo.…`, `bodytext.…`) is a claim about the scanned
  document's structure, prefixed by the stream it concerns. These 31 tokens are
  the `blocking_tokens` vocabulary and follow the same convention as
  `supported_tokens`.
- **Underscore** (`input_unavailable`, `receipt_not_canonical`, …) means the
  run could not proceed. These 20 tokens say nothing about the document, which
  is the point: a missing file is not a finding about a form.

The first release of this lane got this wrong in three ways at once, and the
corrections are worth recording because nothing caught them for a whole lane:
23 dotted tokens were declared of which **22 were raised by no code path**
(including `docinfo.version_tail`, so the receipt advertised a version-tail
distinction the scanner cannot actually make); one logical condition was
spelled two ways, `bodytext.paragraph_invalid` at the ParaHeader length check
and `bodytext_paragraph_invalid` three branches later; and
`bodytext.envelope_incomplete` — the only reason the entire public corpus
produces — appeared in no declared set. The root cause is plain in hindsight:
exactly one test asserted a reason string, so the other thirty were free to
drift.

`test_reason_vocabulary_matches_the_source` now parses every reason literal out
of the module and asserts set equality in both directions, plus disjointness,
so a divergence has to announce itself. Representative refusals also assert
their exact reason, anchoring the vocabulary to behaviour rather than only to
source text.

**Stated limit.** `reason` is not validated against these sets at runtime. A
refusal can carry a reason raised upstream by `diagnostic_candidate_core`
(5 literals), `hwp_ingress` (127) or `hwp_source_coverage` (48); closing that
would require a cross-module reason registry of roughly 200 tokens over four
modules, which is its own reviewed slice rather than a change to this lane.
What is verified meanwhile is the property that matters for privacy: every
upstream reason is a fixed literal, with no f-string, `%`, `format` or
concatenation, so no path or filename can reach a receipt through this field.

## Version policy and sources

The Hancom HWP 5.0 revision 1.3 PDF contains stale summary lengths in its
early record table: DocumentProperties 30, IDMappings 32, Bullet 10, and
ParaHeader 22. Its detailed tables specify DocumentProperties 26,
`INT32[18]` IDMappings (72 bytes), Bullet 20, and ParaHeader 24. Hancom's own
technical article independently demonstrates the 26-byte properties and
72-byte IDMappings forms. T90 pins the detailed shapes it actually audits and
fails closed on unsupported tails; it does not silently reinterpret another
version.

Primary source: [Hancom HWP 5.0 revision 1.3](https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf), with
[Hancom DocInfo parsing guidance](https://tech.hancom.com/python-hwp-parsing-1/)
and [Hancom BodyText parsing guidance](https://tech.hancom.com/python-hwp-parsing-2/).
The pinned [pyhwp source tree](https://github.com/mete0r/pyhwp/tree/83239f0d3bdf438b2c9f7dcff455a6e841154a39)
is corroboration only: it is AGPL-3.0, partial for current Numbering/Bullet and
ParaShape tails, and is neither bundled nor executed. Source register checked 2026-08-10.

The 10 public HWP entries in `tests/corpus/forms/manifest.json` were inspected
read-only while defining the boundary. Their BodyText results remain the T89
matrix of eight analyzed ineligible and two analyzed unknown; none becomes
semantically eligible through T90. Corpus bytes, extracted text, raw IDs, and
document-specific definitions are not published.

Against the current T90 scanner, all 10 are refused with the closed reason
`bodytext.envelope_incomplete`; none publishes a T90 receipt or reaches an
analyzed state. This is an expected fail-closed corpus result, not evidence
that the forms are invalid or that T90 understands their unsupported controls.
