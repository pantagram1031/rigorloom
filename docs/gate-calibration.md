# Gate calibration from the W5 real-report campaign

This document records aggregate calibration evidence from 39 checker runs:
13 real report workspaces times three gates. It intentionally contains no
report titles, names, paths, prose, citations, or other workspace-level data.
Counts describe this one corpus and are not population estimates.

## Findings and decisions

| Finding code | Gate | Default severity | Aggregate real-corpus behavior | Calibration decision |
|---|---|---:|---|---|
| P0 request.yaml missing/unusable | submission_preflight | HARD | 11 of 13 legacy workspaces | Keep fail-closed for current workspaces. Classify as expected INFRA on pre-W3 workspaces. |
| P1 canonical artifact missing/ambiguous | submission_preflight | HARD | 10 of 13; largely cascaded from missing request metadata | Keep. Treat the pre-W3 cascade as expected INFRA, not a checker bug. |
| P3 unsupported submission extension | submission_preflight | HARD | 1 legacy-format request | Keep. This is a real supported-format scope gap, not a false positive fixed in W5. |
| P5 proof_grade must be hancom/advisory | submission_preflight | HARD | 13 of 13 lacked the later verdict schema | Keep for current workspaces. Classify absence on pre-W3 workspaces as expected INFRA. |
| H1 | verify_content | HARD | 12 hits across 3 workspaces; all were bibliography URLs | Exempt only lines in the shared recognized reference section. URLs in body prose remain HARD. |
| missing_seed | check_numbers | Conditional HARD/WARN | 7 genuine legacy reproducibility gaps | Keep. Canonical numeric results without a top-level numeric seed remain HARD; ambiguous or legacy artifacts remain WARN. |
| BAN:gloss-english | check_style | HARD in the measured operator pack | 4 false positives on unit/software terms | Exempt shared unit-dictionary symbols and additive neutral software names. Unknown glosses still trigger the ban. |
| BAN:author-year-citation | check_style | HARD in the measured operator pack | 2 genuine body-citation violations | Keep unchanged. |
| CITE | check_style | HARD | 2 genuine parenthetical citations under narrative style | Keep unchanged. |
| extraction_infidelity | content_extract | HARD | 6 findings across 2 workspaces; equation gaps were 3 and 1 | Reproduced as a quote-parsing bug for bracketed HwpEqn scripts and fixed symmetrically. Saved-content tampering and real count/script drift remain HARD. |
| unbacked_numeral | check_numbers | WARN | 200 hits, mostly textbook constants and specification values | Accept matching evidenced/resolvable ledger claims and validated constants. Ledgerless unmatched numerals remain WARN. |
| figure_unverified | check_figdata | WARN | 33 hits on workspaces predating checksum manifests | Keep. Classify the legacy absence as INFRA context. |
| unreferenced_figure | check_refs | WARN | 23 hits; sampled behavior was genuine missing prose callouts | Keep unchanged. |
| ledger_missing | check_claims | WARN by default; HARD in strict mode | 13 of 13 pre-W3 workspaces | Keep. Missing ledgers are expected on legacy workspaces, not evidence that the checker failed. |
| form_baseline_absent | submission_preflight | WARN | 13 of 13 pre-W3 workspaces | Keep. Expected legacy INFRA. |
| dangling_xref | check_refs | WARN | 12 hits; sampled messages were consistent with numbering mismatches | Keep unchanged pending a dedicated corpus review. |
| references_unparsed | check_sources | WARN | 7 false positives on numbered or SECTION-prefixed bibliography headings | Recognize the observed structural prefixes while retaining the citation-like-content warning for unknown headings. |
| TITLE | check_style | WARN | 4 false positives where title lived in an activity-topic metadata line | Public recognition is limited to documented front-matter keys (`title:` / `제목:`). Corpus-specific formats extend those defaults through `report_structure.title_metadata_keys`; mismatching recognized metadata still warns. |
| BAN:ai-stock-phrase-soft | check_style | WARN | 5 hits | Keep unchanged as an intentional flag-not-block policy. |

## C5 equation investigation

The source-side fingerprint and extracted Markdown were compared by normalized
equation-script hashes and XML ancestor types. Every missing equation was an
ordinary equation under run/paragraph/section, not a header, footer, textbox,
caption, or skipped table-cell branch. Every missed HwpEqn script contained a
literal square-bracket pair.

The extractor had emitted those equations, but its Markdown fingerprint regex
treated the first closing bracket inside the quoted hwpeqn attribute as the end
of the EQ tag. A quote-aware parser now treats brackets inside quoted
attributes as content. A synthetic bracketed-equation round-trip test verifies
source count, extracted count, script list, and verify mode together.

## Legacy-workspace INFRA expectations

Pre-W3 workspaces legitimately may lack request.yaml, verdict_v06.json, a
signed form-structure baseline, and claims.yaml. Therefore P0/P1/P5,
form_baseline_absent, and ledger_missing can be expected compatibility findings
when current gates are run retrospectively. They are not, by themselves, gate
bugs and do not justify weakening fail-closed behavior for workspaces created
under the current contract.

The calibration invariant is narrow: reference-section URLs, properly
evidenced ledger numerals, universal constants, recognized unit/software
glosses, metadata titles, and observed bibliography heading shapes stop
creating noise. Body URLs, unbacked non-constants, unknown glosses, real title
mismatches, malformed sources, and extraction drift remain detectable.
