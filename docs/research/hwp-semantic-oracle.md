# T88: paired bounded content/object agreement oracle

T88 is a receipt-only diagnostic comparison between one T86 `rhwp` candidate
and one T87 Java candidate. It is not an HWP ingress adapter, a Hancom/native
render result, a Stage-0 input, or a submission claim. Its only publication is
an agreement receipt below a pre-created exact leaf:

`work/stage-0/scratch/hwp-semantic-oracle/<opaque-run-id>/receipt.json`
The producer-side `candidate.hwpx` files remain in their own T86/T87
quarantines and are never copied into this oracle run.

The schema is `rigorloom/hwp-semantic-oracle/v1`. A successful receipt has
`status: diagnostic_agreement`, `ceiling: diagnostic_only`, comparison method
`paired_converter_bounded_content_object_v1`, `source_fidelity: not_established`,
`independence: converter_code_distinct_java_runtime_unbound`, render
`not_run`, proof `none`, and submission grade `false`. It contains only
closed match booleans plus role-labelled opaque input-binding hashes and an
explicit coverage declaration; it never carries text, equation content,
picture digests, IDs, names, paths, argv, or child output. Coverage compares
`text`, `story_table_topology`, `equations`, `referenced_pictures`, and
`explicit_controls`; it does not compare `style_definitions`,
`paragraph_numbering`, `layout_pagination`, or `metadata`.

## Inputs and boundary

The caller supplies both current receipt paths to `compare`, and supplies them
again to `verify`. The oracle captures each receipt and candidate with the
shared bounded no-follow regular-file reader, validates the complete T85 source
descriptor for equality, binds the release-owned T86 `rhwp` v0.8.2 SHA-256
allowlist, and binds the T87 toolchain lock/bridge/JAR digests. It then runs the
public T86 and T87 verifiers over private copies of those captured bytes before
performing its own bounded content/object agreement. A path replacement, source/candidate
drift, role collision, lock mismatch, unsupported control, or publication race
refuses with exit 3; unequal compared axes refuse with
`bounded_content_object_mismatch`.

The bounded content/object comparison follows OPF spine order and preserves NFC text, CRLF/CR line
ending normalization, ordinary spaces/tabs, paragraph/story/table/row/cell/
span/control boundaries, cell row/column addresses, equation scripts, and
referenced nested `hc:img` BinData payload bytes. Future or unknown controls
refuse. T88 deliberately
does not call `content_extract.semantic_fingerprint`; that extractor remains a
separate T85/T87 implementation detail exercised through the public verifier
boundary.

## Commands

Pre-create the exact leaf and use opaque lower-case 16/32-hex run IDs:

```text
python pipeline/scripts/hwp_semantic_oracle.py compare \
  <t86-receipt.json> <t87-receipt.json> \
  --diagnostic-root work/stage-0/scratch/hwp-semantic-oracle \
  --run-id 0123456789abcdef0123456789abcdef

python pipeline/scripts/hwp_semantic_oracle.py verify \
  --diagnostic-root work/stage-0/scratch/hwp-semantic-oracle \
  --run-id 0123456789abcdef0123456789abcdef \
  --rhwp-receipt <current-t86-receipt.json> \
  --java-receipt <current-t87-receipt.json>
```

Exit 0 means the current four producer inputs still agree. Usage is 2;
unsupported, stale, mismatched, malformed, or raced inputs are 3. `new_report`
has a defense-in-depth guard that rejects a forged/reserved candidate path under
`hwp-semantic-oracle` before creating a workspace, just as it rejects the
T86/T87 diagnostic lanes. An oracle run contains exactly `receipt.json`;
producer `candidate.hwpx` files stay in their own lanes. The result never
becomes `output/form_copy.hwpx` or an ingress/backend receipt.

T86's official operator references remain the [v0.8.2 source tree](https://github.com/edwardkim/rhwp/tree/v0.8.2),
[v0.8.2 release and assets](https://github.com/edwardkim/rhwp/releases/tag/v0.8.2),
[v0.8.2 English README](https://github.com/edwardkim/rhwp/blob/v0.8.2/README_EN.md),
and [CLI usage](https://github.com/edwardkim/rhwp/blob/v0.8.2/README_EN.md#cli-usage). They describe the
independent converter lane; they do not turn T88 agreement into native or
canonical proof. `syhwp` and any future converter are deferred and cannot enter
the T88 pair without a new receipt schema and review.

No binary, JAR, JRE, HWP/HWPX corpus, downloaded archive, or private runtime
artifact is shipped. Operator-local execution evidence, if recorded, remains
non-reproducible probe evidence and never changes the receipt grade.
