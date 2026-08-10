# T89 HWP source coverage

T89 is a receipt-only, source-side coverage diagnostic. Its schema is
`rigorloom/hwp-source-coverage/v1`; it is separate from ingress, Stage 0,
candidate output, semantic comparison, rendering, and submission evidence.

The scanner captures a bounded `.hwp` byte snapshot once, applies the strict
T85 CFB/FileHeader preflight in memory, and then examines only direct
`BodyText/Section0..N` streams. Compressed sections use raw deflate with exact
EOF and no unconsumed data; HWP's optional eight-byte little-endian CRC32/ISIZE
trailer is accepted only when it matches the decompressed bytes, and every
other trailing byte is refused. HWP records use the exact 32-bit header fields
and extended-size form. The reviewed v1 paragraph shape requires an exact
24-byte ParaHeader and canonical header/text/character-shape/line-segment
child order; other header sizes refuse, while the high count flag and declared
child/count mismatches make coverage incomplete. Section names, record
hierarchy, paragraph counts, UTF-16 scalar structure, and availability limits
are fail-closed. The source
descriptor binds format/version/size/SHA-256 and the scanner pin identifies syhwp `0.0.7` commit
`d4aa0abf8405f5b33d7b35b96b6bf3cf96aee7ed` as a target only: syhwp is not
installed, executed, or downloaded by T89.

## Source register (checked 2026-08-10)

The record/tag and control-unit boundary is cross-checked against Hancom's
published HWP 5.0 revision 1.3 specification:
<https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D_5.0_revision1.3.pdf>.
The pinned syhwp source tree is a comparison target only:
<https://github.com/sysphere/syhwp/tree/d4aa0abf8405f5b33d7b35b96b6bf3cf96aee7ed>.
Neither source is executed by this scanner.

Use a pre-created leaf and an opaque run id:

```text
python pipeline/scripts/hwp_source_coverage.py inspect INPUT.hwp --coverage-root work/stage-0/scratch/hwp-source-coverage --run-id HEX
python pipeline/scripts/hwp_source_coverage.py verify INPUT.hwp --coverage-root work/stage-0/scratch/hwp-source-coverage --run-id HEX
```

Only `<root>/<run-id>/receipt.json` is published. T89 currently makes no
semantic `eligible` claim: analyzed ineligible or unknown coverage exits 3 but
still publishes its privacy-safe receipt. Malformed, protected, empty, aliased, or
otherwise refused input publishes no run. Input symlink/reparse ancestry is
refused; the same strictly resolved regular path is used for overlap, capture,
and the pre-commit rebind. Owner-token publication detaches the staged hard
link before commit, so later scratch-cleanup failure cannot turn a committed,
one-link receipt into a false refusal. The receipt contains no source text,
raw record tags, raw control IDs, filenames, absolute paths, argv, or process
output. `comparison` remains `unknown`, `render` is `not_run`, `proof_grade`
is `none`, and `submission_grade` is false.
The receipt's closed coverage scope is `bodytext_record_envelope_v1`, with
`bodytext.paragraph_header_auxiliary_fields`, `docinfo.reference_graph`,
`docinfo.numbering_bullets`, and `docinfo.styles` listed as not scanned.

The reviewed BodyText envelope covers only complete paragraph
header/text/character-shape/line-segment records. Tables, equations, pictures,
stories, fields, objects, controls (including tabs and line/paragraph breaks),
range tags, unknown records, unsupported whitespace, and other surfaces are
inventory-only blockers. Current public forms contain real controls and
tables: the checked manifest currently yields eight analyzed ineligible and
two analyzed unknown receipts, with no semantic pass. A clean BodyText
envelope is still `unknown`, because paragraph-shape/style/numbering
references (including zero-based IDs) live in DocInfo definitions that T89
deliberately does not scan. Nonzero split/divide flags are likewise marked
unscanned, and opaque paragraph instance/change-tracking fields are bounded by
the exact header size but not interpreted. There is no v1 `eligible` outcome
in this slice.

This slice does not establish general HWP validity, source fidelity,
conversion parity, native execution, render quality, or submission readiness.
It is an independently implemented bounded BodyText wire-coverage inventory,
not a replacement for Hancom or a general-purpose HWP parser.
