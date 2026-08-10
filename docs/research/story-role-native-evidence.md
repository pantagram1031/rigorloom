# Story-role Windows Hancom evidence

Checked on 2026-08-10. This note separates three evidence classes that must
not be collapsed:

1. T79/T80 deterministic structure and preservation,
2. Windows Hancom execution plus PDF rendering, and
3. native-authored control semantics.

The public corpus contains one real `header` owner and no `footer`,
`footNote`, or `endNote` owners. To exercise the remaining bounded editor
roles without publishing a derived form, a disposable probe cloned only the
public form's existing package/style/section settings and inserted one
text-only owner at a time. The probes, edited HWPX files, PDFs, operation JSON,
and vision files remained outside the repository. They are synthetic-donor
fixtures, not Hancom-authored note controls.

## Contract sources

Hancom's Apache-2.0 OWPML model is the primary implementation reference:

- [`HeaderFooterType`](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/HeaderFooterType.cpp)
  owns one paragraph `subList` and serializes `id` plus
  `applyPageType` (`BOTH`, `EVEN`, or `ODD`).
- [`NoteType`](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/NoteType.cpp)
  owns one paragraph `subList` and serializes the note fields including
  `number`, `suffixChar`, and `instId`.
- [`SectionDefinitionType`](https://github.com/hancom-io/hwpx-owpml-model/blob/main/OWPML/Class/Para/SectionDefinitionType.cpp)
  owns `footNotePr` and `endNotePr`; those are presentation settings, not
  evidence that a note owner or body anchor exists.

T79 deliberately requires non-empty, scoped `id`/`instId` values even where
the vendor model permits zero, and it requires exactly one direct `subList`
even though the cited model source alone is not used as a cardinality proof.
Those are closed product rules, not claims about every OWPML document.

Hancom's [format page](https://store.hancom.com/etc/hwpDownload.do) links the
official
[HWPML 3.0 specification](https://cdn.hancom.com/link/docs/%ED%95%9C%EA%B8%80%EB%AC%B8%EC%84%9C%ED%8C%8C%EC%9D%BC%ED%98%95%EC%8B%9D3.0_HWPML_revision1.2.pdf).
That legacy document uses title-case `HEADER`/`FOOTER`/`FOOTNOTE`/`ENDNOTE`
and `ApplyPageType`; current HWPX and the vendor model use lower-camel element
names and `applyPageType`. The implementation follows the current HWPX model,
not a casing guess from the legacy PDF. Preserve Hancom's attribution and
reuse notice when using the specification itself.

## Operator-local evidence boundary

This is a non-reproducible operator-local audit record, not a CI fixture or a
redistributable corpus result. The artifacts were deliberately not committed,
so another checkout cannot independently recompute the hashes or pixel deltas
from this repository alone. The exact values below identify the local run and
prevent it from being generalized; they do not substitute for a future public
sanitized fixture.

Each disposable source passed T79 with exactly one target role and no unknown
finding. T80 changed the sole target paragraph from a `before` marker to an
`after` marker, emitted the seven-key closed receipt with
`render: "not_run"`, and reproduced the identical T79 topology. Windows
Hancom conversions were serialized; the exact `tasklist | findstr /i hwp`
precheck returned 1 before every COM call, every conversion returned 0, and
every `rigorloom/conversion-record/v1` record matched both current artifact
hashes and document/PDF page counts.
No `--kill-stale` recovery was used; a non-1 precheck would have stopped the
run instead of terminating an external Hancom process.

The host reported Hancom Office 2024 registry version `13.0.0.1352`; the
executed `Hwp.exe` file/product version was `13.0.0.2986`. Conversion records
were created at `2026-08-10T05:02:44Z`, `2026-08-10T05:03:11Z`,
`2026-08-10T05:04:51Z`, `2026-08-10T05:05:02Z`,
`2026-08-10T05:06:03Z`, and `2026-08-10T05:06:14Z` in footer-before/after,
footnote-before/after, and endnote-before/after order. All six recorded
`source_print_method: null`, `print_method_normalized: null`, and the page
counts shown in the table. These fields are the full conversion-record facts
used here; no unstored Hancom build or PrintMethod claim is inferred.

| role | source HWPX SHA-256 | edited HWPX SHA-256 | before PDF SHA-256 | after PDF SHA-256 | pages | 200-dpi raster delta |
|---|---|---|---|---|---:|---|
| footer | `3590debf217fc957cbc5d1ac1ebf5e9e330b68c3f8a63f153e80784e4df13856` | `6e885d16287caaf775e8a9804a1014fe7b416628974865f70e03bc0632a87b45` | `fc892d040a63a796d4e3b6ecb995bbb2238265ae9aaa93d241ef5f0494c3454c` | `1cbbdf4daa51350f2a2ffe2ecfb787517e03efdfd5dc0981fc2f440ad331cdf7` | 1 | only the final marker glyph, bbox `(369,2259,402,2293)`, 597 pixels |
| footnote | `2875d6cb8c35f8774dc03286a36887cdf3978b72c69f2fd6b7a1a94c898995a4` | `342b4c3f1fc822ca8e8d83d10859d4f55a0c16bae1bbb2b5e2d1c2f2a1606474` | `1d2b8b7f7701def72451821b182de913540c330a5141fb3a5f371404e4f1d93f` | `d3bed97841c61032b8f990529ef7515444492bd64f889d7858cc6d4fe7b0d64c` | 2 | page 1 identical; page 2 bottom bbox `(257,2238,278,2258)`, 258 pixels |
| endnote | `a2d72ecebcb1e436439150bf4cfa9a4b6ee569d73eb100ebb2ecd61f86537333` | `ebf63fae9b66654e462471fc87e7ff428ffd57390965483def3ff576b7c0b269` | `092c8474ba05695589f5218cbbc257859ab68f4d80f7a4d187cb2fdd863aa9b4` | `2bd757dd97100cf06b6c97b5289dc96cae1fca7689554c3ee3f3e9f3e02361be` | 2 | page 1 identical; page 2 document-end bbox `(257,158,278,178)`, 258 pixels |

For all three roles, T82 pass 1 returned 3 with `vision_pending`, hard 0,
and no blocker or waiver. An all-page vision verdict returned 0 with
`acceptance: true`, hard 0, and no blocker or waiver. The independent quality
checker nevertheless returned `unknown/unsupported_graphics_state` for all
six PDFs. None is a quality `passed` result.

## What this proves and does not prove

The operator-local evidence proves that the bounded T79 address, the T80 byte-preserving
paragraph edit, Windows Hancom open/render execution, current hash-bound
conversion records, and the T82 story visual scope work for all four public
supported roles (the earlier public header plus these three disposable roles).

The footer renders in its expected page-bottom location. The synthetic-donor
footnote renders in a foot area and the synthetic-donor endnote renders at the
document end, but neither probe contains a Hancom-authored body anchor/number
relationship. Therefore this does **not** prove native note insertion,
renumbering, continuation, section numbering variants, ODD/EVEN footer
semantics, LibreOffice parity, or macOS/Linux behavior. Those claims require a
sanitized Hancom-authored control fixture and separate native/render evidence.

Do not commit the disposable HWPX/PDF artifacts or use this note to promote
`unknown` render quality. The hashes make the local run auditable without
shipping document content, paths, IDs, metadata, or raw ZIP members.
