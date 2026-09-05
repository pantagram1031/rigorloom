# Revision coherence: a correctly approved edit can name the wrong paragraph

Status: executable counterexamples and a proposed boundary contract, **not a product fix**.
Observed source: Desktop PR #248, `8a56ada79391a577c02319d0e2efffd6a7968a67`.
Date: 2026-09-05. No Claude/Codex worktree, renderer algorithm, release Epoch,
existing PR, or production source file was changed by this work.

## Decision

Preserve the common Runtime, immutable candidates and hash-bound approvals.
Add the missing invariant **before** those checks: the page, its address map,
the region read for editing, and the plan base must name the same document
revision. Also bind the asynchronous UI effect to the user's still-current edit
intent. Hashing an already misaddressed plan faithfully does not repair it.

This is distinct from the already assigned export rollback, render-cache-key,
installer and layout-fidelity work. Do not restart either active program.

## What was actually executed

The probes execute the inspected Python routing/mapping function bodies via AST
selection, and the inspected TypeScript helper **and public click handler** after
TypeScript transpilation. Filesystem/engine profiling, rendered line extraction,
Runtime replies and UI state are controlled collaborators. Synthetic text only.
The mapper and action algorithms themselves are not rewritten in the baseline.

Direct Git network access was unavailable in the audit container. Source function
excerpts were captured from the GitHub connector, preserving their bodies. The
local run was against that function-only fixture, **not a complete checkout**.
On a normal checkout the supplied probes select those same functions directly
from the real source files; no fixture copying is required. Their fingerprints
are recorded in `revision-coherence-01.results.json` so a rerun can establish
whether it tested the same functions.

No Hancom, real HWPX apply/export, PDF renderer, Tauri window, IME, full repository
suite or repository privacy scanner ran here. The findings establish wrong
routing, false-unique mapping, and wrong/stale UI target acceptance under the
specified inputs. They do **not** claim an installed-app file corruption exploit.

## R1: the candidate page is matched against the source profile

`RuntimeCore.document_page_geometry` accepts `run_id` and forwards it to
`page_geometry`, but obtains `profile = load_profile(..., tag="base")` without a
candidate subject. `build_targets` and `map_spans` therefore compare the
candidate page's text against the original document's addresses.

A two-paragraph counterexample, zero special characters or normalization tricks:

| Address | Source | Candidate after editing paragraph 0 |
| --- | --- | --- |
| paragraph 0 | ALPHA | BETA |
| paragraph 1 | BETA | BETA |

On the candidate's first line, the old profile contains exactly one BETA, at
paragraph 1. The production mapper returns `confidence=unique, atPara=1` for a
line actually originating at paragraph 0. A profile of the candidate instead
returns ambiguity, which is the current mapper's correct conservative response.

A second case, ALPHA -> GAMMA, becomes `unmapped` even though the candidate has
one uniquely addressable GAMMA. Changing one of two identical source paragraphs
also leaves an obsolete ambiguity. All three follow from one wrong revision.

The false-unique case applies to the PDF-style mapping path. The own-render
path has an additional renderer-address cross-check that can demote a mismatch;
this probe does not bypass it and does not claim every tier silently misaddresses.
The wrong profile still matters for candidate text/seat availability there.

## R2: the next edit reads the source again

`beginParagraphEdit` calls `rt.readRegion(sessionId, [{ atPara }])` without the
existing third `runId` argument, then ignores `answer.subject`. Two consequences:

* Fixing R1 alone does not reopen newly changed GAMMA for editing: the helper
  reads source ALPHA and returns `run_text_differs`.
* Feed the false-unique BETA/paragraph-1 result from R1 to the actual helper. It
  reads source BETA at paragraph 1, its text check passes, and it opens a run edit
  targeting paragraph 1. The second check corroborates the first mistake because
  both consult the same old revision.

Even routing the frontend read to the candidate alone is insufficient: BETA
also exists at candidate paragraph 1, so the misaddressed read still agrees.
Equal text is not evidence that two answers name the same revision or location.

## R3: a helper-level stale guard is not enough

While `beginParagraphEdit` awaits `readRegion`, the active session or view may
change, or a later click may complete first. Its continuation currently writes
`selection`/`inlineEdit` without validating that context.

The subtle second boundary is `clickOverlaySpan`. Even when a counterfactual
helper returns a stale-context refusal without writing, the real public handler
treats the refusal as an ordinary failure, sets an overlay, and calls
`setSelection` with the old address. A helper-only regression suite would miss
that caller reintroducing the stale state.

The probe controls Promise resolution directly (no timing sleeps): launch the
old click, switch sessions or replace the view, then release its reply; and
launch two clicks, complete the second before the first. This is a UI boundary
schedule test, not proof of the installed application's event reachability.

## Causal interventions: what must be repaired together

The `--intervention` modes change function bodies **only in memory**. They are
controls for diagnosis, not patches or a substitute for implementation review.

| Intervention | Contract passes | Violations |
| --- | ---: | ---: |
| none: inspected production bodies | 8 | 13 |
| route only the Runtime profile to candidate | 13 | 8 |
| route only the frontend read to candidate | 10 | 11 |
| both routes + stale guard inside helper | 18 | 3 |
| also guard the public click effect and latest request | 21 | 0 |

These are 21 scenarios of three related fault classes, not 13 separate security
vulnerabilities. Positive controls require real source edits to work; duplicate
and missing-inventory controls require refusals. An always-refuse implementation
cannot satisfy the suite. The last result is finite test coverage, not a proof
that the application is fixed or race-free.

### Rerun on the real checkout

With the existing Desktop TypeScript dependency installed:

```sh
python scripts/revision_coherence/probe.py --repo-root . --out /tmp/revision-probe.json --source-label YOUR_HEAD
```

Use an equivalent private scratch destination on Windows. `--typescript DIR`
can name an existing TypeScript installation; the probe never installs packages.
`--runtime-only` explicitly marks the TypeScript leg NOT RUN. Exit 0: observed
contracts pass; 1: observed violations; 2: probe could not complete. Do not
reinterpret exit 1 as a build/engine failure. These standalone probes are not
silently added to the ordinary pytest gate.

Re-run with `--intervention runtime-only`, `frontend-routing-only`,
`coherent-guard`, or `public-guard` to inspect the ablation. After production
functions change, an intervention may correctly refuse to apply; rebase the
probe deliberately rather than weakening it.

## Proposed minimal implementation contract

Define a document revision separately from a render artifact:

```text
R = (sessionId, source-or-candidate, runId-or-null, documentSha256)
L = (R, rendererBuild, geometrySchema, fontManifest, layoutOptions)
E = (R, L, targetAddress, monotonically increasing editIntentGeneration)

R_page = R_geometry = R_regionRead = R_planBase
L_page = L_geometry
approval.planHash = hash(plan actually reviewed)
```

A prepared PDF hash and its HWPX document hash inhabit different domains. Never
make them equal by relabelling a field. `GeometrySpan` text alone cannot carry R.
Older envelopes without a proven binding may remain viewable; do not silently
promote their targets into editable ones.

Implement in a small coordinated slice, without redesigning the renderer:

1. **Runtime subject selection.** Resolve/verify a named candidate before
   profiling it, as `document_read_region` already does. Invalid/missing
   candidate identity must not fall back to source. Only a genuine profile
   failure may produce unmapped geometry. Expose the mapping's document subject.
2. **Frontend read.** Capture the displayed revision, pass its runId, compare the
   returned document subject, and key region data by revision, not session alone.
   Editing an older candidate can be an explicit fork; do not silently reinterpret
   it as editing whichever head happens to be latest.
3. **Prepare then commit.** Let asynchronous preparation return a typed result
   with E, without mutating editor selection. The public action checks E and
   applies one synchronous state update. Superseded work is a silent no-op, not
   a normal refusal that an outer handler can turn back into an old selection.
   Validate both successful and failed replies at this same boundary.
4. **Intent generation.** Advance it for another edit, cancellation, session/view
   replacement or revision selection. Session-id equality alone misses A->B->A;
   object identity alone misses selecting another target on the same page.
   The probe's separate counters are instrumentation, not a suggested public API.
5. **Plan binding.** Carry the same R into the plan base and reviewed before-value.
   If it no longer matches the chosen edit context, rebase with explicit review
   or refuse; do not reconstruct the base from ambient UI state after an await.

No change to approval authority, renderer metrics, export paths, or main is
needed to make this contract explicit. Codex/Claude should agree on the small
Runtime/Desktop boundary, keep their current worktrees, and integrate only the
relevant fix commits. The next closure is baseline mode passing on the actual
modified checkout plus one real edit->rerender->edit installed-app scenario.

## Source and local evidence identifiers

Repository blobs at the observed commit:

| File | Git blob |
| --- | --- |
| runtime/scripts/rt_core.py | 584eaf1fe6afa4ab6c2af4844c7c368967735603 |
| runtime/scripts/rt_geometry.py | 25dee640d55f146642c2e4d1aa7a002c86cc9011 |
| desktop/src/actions.ts | 988cef43a841b6b22f3b899efcc6389817f5e9c2 |
| desktop/src/runtime.ts | a3aaf256db54dc779e0f0c9b1a8be3a1df11b28a |

The complete local reports include the selected-function fingerprints, observed
read arguments, mappings, UI writes and intervention results. The source label
is a human-supplied label, not a build attestation. The comparison above was
executed with Python 3.13.5, Node 22.16.0 and TypeScript 5.8.3. No GUI or full-suite result is inferred from these reports.
