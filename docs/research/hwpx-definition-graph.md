# T153 HWPX definition/reference graph

T153 is a standalone, read-only diagnostic for one HWPX snapshot.  It is not a
renderer, editor, converter, certificate verifier, or release route.  The
schema is `rigorloom/hwpx-definition-graph/v1` and the only claim scope is
`selected_definition_reference_graph_snapshot_only`.

## Command and result

Run the CLI's `inspect INPUT.hwpx` operation against one input package:

```text
python pipeline/scripts/hwpx_definition_graph.py inspect INPUT.hwpx
```

The importable function is `inspect_path(INPUT.hwpx)`.  An analyzed result is
bounded and pathless.  Its public payload includes the source byte descriptor,
selected scope, counts, blocking/not-scanned token sets, canonical graph
digest, and explicit evidence states:

```text
schema, status, source{sha256,bytes}, scope, counts, graph_sha256,
blocking_tokens, not_scanned_tokens, evidence_ceiling, eligibility, comparison,
render, proof_grade, submission_grade, promotion
```

`status: analyzed` means that the selected graph was captured and validated;
it does not mean that the document is semantically understood.  The result is
pathless: `graph_sha256` is a canonical digest of schema-owned graph tokens,
and counts expose only closed node and edge labels such as `fontface` and
`substFont->BinData`.  No ZIP member names, source text, document identifiers,
binary payloads, URLs, metadata, absolute paths, or raw bytes ever cross the
output boundary.  Archive order and ZIP compression do
not change the graph digest.

The command is intentionally a diagnostic exit contract: help exits `0`,
argument errors exit `2`, and an analyzed or refused package exits `3`.
Diagnostics do not echo the input name or an exception value.  A refusal has a
closed `reason_code`; it is not a best-effort partial graph.

## Selected graph boundary

The scanner reuses the strict HWPX physical envelope and OPF ownership checks,
then follows only the selected definition/reference graph.  It inventories
the header definition groups needed for bounded references: font faces,
character properties, paragraph properties, border fills, numberings, styles,
and tab properties.  Section owners contribute only their closed reference
edges, including character/paragraph/border/numbering references and the
border references on tables, cells, cell zones, and page border fills.

Font-level `hh:font` and `hh:substFont` binary references are typed edges to a
present OPF `BinData` item.  For `hh:font`, `isEmbedded="1"` requires a
nonempty `binaryItemIDRef`, while `isEmbedded="0"` requires no reference.
For `hh:substFont`, a nonempty reference is optional; an empty or absent
reference creates no edge, and a nonempty reference must resolve to the exact
closed embedded-binary manifest shape.  The graph records the edge class (for
example, `substFont->BinData`), not the item name or bytes.  Missing
definitions, duplicate identities, invalid counts, unresolved references,
foreign owners, and malformed selected nodes refuse before a graph digest is
published.

This is a selected graph, not a general HWPX feature inventory.  It does not
interpret text, style meaning, generated numbering or bullets, layout,
equation semantics, or controls.  A selected `img->BinData` reference and its
payload identity (hash and byte count) are bound in the internal graph
aggregate; image semantics, pixels, and rendering remain unscanned.  A valid graph
therefore cannot establish visual fidelity, conversion parity, native
execution, PDF quality, or submission readiness.  In particular, T153 does
not add a document feature and does not change certificate or runtime
behavior.
There is no document feature claim in this lane.

## Evidence ceiling and routing

The diagnostic has no certificate input, no operator key, no renderer child,
and no writable output or receipt lane.  It **does not execute a renderer**,
has no automatic route, does not auto-route, and cannot feed `doc_backend`, Stage 0, Stage 5, Stage 6,
or `new_report`.  It does not change any certified-render switch or legacy
certificate policy.

The payload's frozen evidence fields are:

```text
evidence_ceiling: selected_definition_reference_graph_snapshot_only
eligibility: unknown
comparison: {state: unknown}
render: {state: not_run}
proof_grade: none
submission_grade: false
promotion: not_run
```

The public payload has no source text, no absolute paths, and no raw bytes.
The standalone graph is never a certificate, runtime receipt, feature proof,
or submission artifact.

## Refusal vocabulary

Reason tokens are closed and machine-readable:

```text
input_unavailable input_too_large package_outside_supported_envelope
definition_member_invalid definition_collection_invalid definition_count_mismatch
definition_id_position_mismatch definition_reference_invalid
definition_reference_unresolved section_reference_invalid binary_reference_invalid
unsupported_definition_branch graph_limit_exceeded output_write_failed internal_error
```

The scanner refuses on malformed, aliased, oversized, or ambiguous physical
inputs.  It never downgrades an unscanned feature into a positive claim, and it
never prints source data while explaining a refusal.
