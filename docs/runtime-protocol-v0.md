# Runtime Protocol v0 — design draft

Status: design input for Phase 1. No runtime code exists yet; nothing in this
document is implemented. Every capability claim below cites the file and line
in this checkout that already provides it. Anything the tree does **not**
provide is labelled `GAP` with a one-line build note.

Scope: the wire contract between a client (Desktop shell, CLI, MCP server,
Agent Host) and a single Runtime process that adapts the **existing** engine
and pipeline entrypoints. The Runtime is an adapter, not a second editing
engine: every mutation it exposes must terminate in an operation this repo
already ships.

Non-goals for v0: no localhost control server (Studio's HTTP surface stays
what it is, `studio/main.py:14`), no network of any kind, no new document
model, no new checker vocabulary.

---

## 1. Transport

### 1.1 Framing

One JSON object per line on stdout, UTF-8, `\n`-terminated, no embedded raw
newlines. The engine already writes exactly this shape in two places, and the
Runtime should reuse the idiom rather than invent one:

- `engine/scripts/preedit.py:2412` — `_emit()` writes
  `json.dumps(..., ensure_ascii=False) + "\n"` to `sys.stdout.buffer`.
- `engine/scripts/xml_backend.py:38` — `emit()` does the same and returns the
  process exit code.

Rules:

| Rule | Reuse / GAP |
| --- | --- |
| stdout carries protocol frames only | Precedent: `preedit._emit` and `xml_backend.emit` write to `sys.stdout.buffer` and nothing else does. GAP: no shipped script *forbids* stray prints; the Runtime must own its stdout exclusively. Build note: route all diagnostics through a logger bound to stderr at process start, and assert in tests that a frame-only stdout survives an engine subprocess that prints. |
| stderr carries diagnostics only | `pipeline/scripts/diagnostic_candidate_core.py:1128` (`run_child_capture`) already keeps a child's stdout and stderr as two separately-hashed, separately-counted streams. |
| UTF-8 regardless of console codepage | `engine/scripts/cli_io.py:33` (`utf8_stdio`) and `pipeline/scripts/checker_base.py:19` (`_utf8_stdio`); both run **before** `parse_args`, for the cp949 reason documented at `engine/scripts/cli_io.py:3`. Swept by `tests/test_cli_cp949_help.py`. |
| Bounded frame size | `pipeline/scripts/diagnostic_candidate_core.py:1132` caps child output at `max_output_bytes` (default 8 MiB) and raises an overflow flag; `pipeline/scripts/renderer_runtime_v2.py:64` pins `MAX_CHILD_OUTPUT_BYTES`, `:63` pins `MAX_RECEIPT_BYTES`. Adopt the same style: a named module constant, not a magic number. GAP: no per-frame cap exists because there are no frames yet. Build note: `MAX_FRAME_BYTES` on both read and write; an oversized inbound line is refused with `frame_too_large` **without** being parsed. |
| Strict duplicate-key rejection | `engine/scripts/document_evidence.py:1940` (`_reject_duplicate_json_pairs`, recursive via `object_pairs_hook`), wired at `:1979`. Same pattern in `pipeline/scripts/hwp_ingress.py:1103`, `pipeline/scripts/hwp_semantic_oracle.py:119`, `pipeline/scripts/renderer_certificate_composite_v1.py:97`, `pipeline/scripts/renderer_runtime_v2.py:635`. |
| Non-finite JSON rejection | `engine/scripts/document_evidence.py:1960` (`_reject_nonfinite_json_constant`) plus `:1968` (`_parse_finite_json_float`, which also catches an overflowing literal, not just the three constants). Writer side: `allow_nan=False` at `pipeline/scripts/checker_base.py:168`, `pipeline/scripts/receipt_sign.py:46`, `engine/scripts/document_evidence.py:448`. Decoder-only variant: `pipeline/scripts/doc_backend.py:105`. |
| Deterministic serialization where bytes are hashed | `pipeline/scripts/receipt_sign.py:36` (`canonical_json_bytes`: `sort_keys=True`, `separators=(",",":")`, `allow_nan=False`, top-level integrity fields omitted) and `engine/scripts/document_evidence.py:442` (`_canonical_bytes`). Use `canonical_json_bytes` for anything a `Receipt` hashes; use ordinary compact JSON for ordinary frames. |

The T155/T156 boundary is already documented and doc-tested — see
`docs/trouble-table.md:35` (T156) and `:36` (T155), pinned by
`tests/test_strict_json_docs.py`. **The Runtime must not widen it**: duplicate-key
and finite-JSON rejection are parse-level refusals and carry no
canonical-JSON, HMAC, authentication, routing or promotion meaning.

### 1.2 Frame kinds

`request` (id, method, params) · `response` (id, result) · `error` (id, code,
message, data) · `notification` (method, params — used for `progress` and
`event`) · `cancel` (id).

- Request ids are client-assigned, stable, and never reused within a session.
  A response or error always echoes the id it answers.
- `progress` notifications carry the originating request id. GAP: no engine
  script emits progress today (they are one-shot processes that print one
  object). Build note: progress is Runtime-level only — derived from the
  Runtime's own step boundaries around a subprocess, never from parsing an
  engine script's stdout.
- Cancellation: cooperative. The Runtime may only cancel between engine steps
  or by terminating a bounded child. `pipeline/scripts/diagnostic_candidate_core.py:1128`
  already provides POSIX process-group / Windows Job containment for that
  termination, with the honest limitation stated in its own docstring
  (`:1136`) and mirrored in a receipt field at
  `pipeline/scripts/renderer_runtime_v2.py:56` (`DESCENDANT_CONTAINMENT = "not_established"`).
  A cancelled request answers with `error` code `cancelled`, never a partial
  `response`.

### 1.3 Lifecycle

- `initialize` must be the first request. Any other method before it is
  refused with `not_initialized` and the connection stays open.
- A second `initialize` is refused with `already_initialized`.
- EOF on stdin: the Runtime stops accepting work, lets the in-flight engine
  step finish or be terminated within its bound, and exits 0. Owned children
  are killed on the way out; the containment primitive is
  `pipeline/scripts/diagnostic_candidate_core.py:1128` and the Windows Job is
  configured at `configure_windows_job` (exported at `:26`).
- Exit codes follow the repository's existing three-value contract —
  `0` ok, `2` usage, `3` refusal/finding — declared at
  `pipeline/scripts/checker_base.py:13-16` and repeated verbatim at
  `pipeline/scripts/renderer_runtime_v2.py:67-69`. Do not add a fourth.
  (`engine/scripts/xml_backend.py:1138` uses `4` for "unsupported op"; that is
  a backend-local code and must be mapped, not propagated.)

---

## 2. Initialize handshake

```
--> {"kind":"request","id":"1","method":"initialize",
     "params":{"protocolVersion":"0","client":{"name":"...","version":"..."},
               "unknownFieldPolicy":"reject"}}
<-- {"kind":"response","id":"1",
     "result":{"protocolVersion":"0","runtime":{...},"capabilities":{...},
               "authority":"host"|"agent"}}
```

### ProtocolVersion

A single string, exact match in v0. No range negotiation: a mismatch is
refused with `protocol_version_unsupported` and the process exits 2. The
precedent for a hard version gate is `pipeline/scripts/module_registry.py:23`
(`requires.rigorloom` is checked against the project version and an
unsatisfied range is a load refusal, implemented in `ModuleRegistry`,
`pipeline/scripts/module_registry.py:509`).

### Unknown-field policy

Declared by the client at initialize and fixed for the session:

- `reject` (default, and the only value a host client should send): an unknown
  member anywhere in a request's `params` is `unknown_field`, exit-3-class
  refusal.
- `ignore`: unknown members are dropped. Only legitimate where two tools share
  one file and each interprets its own members — that situation already exists
  and is documented at `engine/scripts/preedit.py:210-218` (`MAP_SCOPE_MEMBERS`
  is the *union* of what `preedit replace --map` and `check_residue --fill-map`
  understand, and the pipeline half is `FILL_SCOPE_MEMBERS` in
  `pipeline/scripts/check_residue.py`). Anywhere else, silently ignoring a
  field is how a caller's intent disappears.

Unknown **methods** and unknown **operation kinds** are always rejected,
never ignored. Precedent, verbatim: `engine/scripts/com_backend.py:1689`
(`ops[i]: 알 수 없는 op` — refused **before** Hancom starts, for the reason
given at `engine/scripts/com_backend.py:1670`: a bad op in the middle of a
batch leaves a half-edited document) and `engine/scripts/xml_backend.py:27`
(`SUPPORTED_OPS`, unsupported names collected and refused at `:1138`).

### CapabilitySet

Not invented. It is the existing probe output, re-shaped:

- `engine/scripts/probe.py:1` already merges three sources into one compact
  JSON document: `render` (from `pipeline/scripts/render_probe.py`), `modules`
  (from `ModuleRegistry().summary()`, `pipeline/scripts/module_registry.py:509`)
  and `backends` (`pipeline/scripts/backend_precheck.py:1`).
- The render half's schema is documented at `pipeline/scripts/render_probe.py:20-28`:
  `hancom_com`, `soffice_path`, `soffice_wsl`, `h2orestart`, `rhwp_*`,
  `render_certificate_configured`, plus a `renderers[]` list.
- Module contributions come through typed accessors only — `enabled_checkers()`
  (`pipeline/scripts/module_registry.py:694`), `enabled_cli()` (`:706`),
  `enabled_studio_panels()` (`:727`), `enabled_preflight()` (`:745`). Core
  never learns a module's name (`pipeline/scripts/module_registry.py:15`); the
  Runtime must keep that property.

Three-state honesty is mandatory and already the house style: a capability is
`available`, `unavailable` with a reason, or `unknown` — never absent-as-false.
`render_probe` uses `"yes"|"no"|"unknown"` for `h2orestart` and carries
`rhwp_reason` / `render_certificate_reason` alongside the booleans
(`pipeline/scripts/render_probe.py:22-28`); `form_inspect._run_record`
(`engine/scripts/form_inspect.py:913`) keeps the same three states for
`color_anomaly` by **omitting the key** when the colour cannot be read.

GAP: `probe.py` has no notion of *authority*, and no shipped script reports
which methods a caller may invoke. Build note: `capabilities.methods` is
computed by the Runtime from its own authority surface (§4), not read from a
probe.

---

## 3. Domain objects

Each object below names the existing producer it is derived from. Where there
is no producer, the row is a GAP.

### 3.1 Workspace

The unit the whole pipeline already addresses: a directory holding
`PIPELINE.md` (authoritative stage/gate state, `docs/architecture.md:12`),
`bundle/`, `output/`, `.pipeline/`, `events.jsonl`, `APPROVALS.md`. The
canonical root set is enumerated at `pipeline/scripts/ws_snapshot.py:29`
(`ARCHIVE_ROOTS`). Slug validation and traversal refusal already exist at
`studio/main.py:98` (`_SLUG_RE`) and `studio/main.py:100` (`safe_workspace`).

### 3.2 Session

GAP. Nothing in the tree holds cross-call state — every script is a one-shot
process. Build note: a Session is Runtime-local, holds the negotiated
protocol version, the unknown-field policy, the authority surface, and the
set of open Workspaces; it owns no document handle, because the engine has no
document handles either.

### 3.3 DocumentSummary

Producer: `engine/scripts/form_inspect.py:1167` (`analyze`), whose returned
`profile` dict is assembled at `engine/scripts/form_inspect.py:1415`. The
summary-level members map directly:

| DocumentSummary field | Source |
| --- | --- |
| `documentHash` | `profile["form_hash"]` (`engine/scripts/form_inspect.py:1418`) |
| `anchors` | `profile["anchors"]` (`:1419`) |
| `pageMetrics` | `profile["page_metrics"]`, computed at `engine/scripts/form_inspect.py:512` |
| `constraints` | `profile["constraints"]`, parsed at `engine/scripts/form_inspect.py:1143` |
| `tableCount`, `citationExample`, `hasEqPlaceholder` | `profile["format_hints"]` (`:1429`) |
| `fillTargetCount`, `spacerCells` | `:1450` / `:1444` |
| `baselineCharPr`, `blackCharPr` | `profile["body_baseline_charpr"]` / `["body_black_charpr"]` (`:1436`) |

For a COM-reachable document there is a second, coarser producer:
`engine/scripts/com_backend.py:1715` (`inspect`), including a
`--privacy-safe` mode (`:1719`) that omits preview text, field names and
equation scripts. Its refusal vocabulary is two tokens only:
`source_not_a_document` (`engine/scripts/com_backend.py:111`) and
`inspect_failed`, and the order is load-bearing — input shape is decided
before host capability, so a broken upload gets the same answer whether or not
pyhwpx is installed (`engine/scripts/com_backend.py:1783`).

### 3.4 DocumentGraph / DocumentNode

Producer: the same profile, at two addressing levels.

- Paragraph nodes: `anchor_records`, which preserve the legacy `para_idx`
  while adding the depth-first `at_para` address that `preedit` uses
  (`engine/scripts/form_inspect.py:1051`, `_resolve_at_para`; contract stated
  at `engine/scripts/form_inspect.py:39-43`).
- Table/cell nodes: `table_map`, built at `engine/scripts/form_inspect.py:802`,
  with per-cell `addr`, `size`, `borderFill`, shading and a four-value
  `classification` — `guide | static | fill_target | spacer`
  (`engine/scripts/form_inspect.py:29-35`).
- Run nodes: `_run_record` at `engine/scripts/form_inspect.py:913`, whose run
  index is deliberately the **same enumeration** `preedit replace --at-cell
  ROW,COL#RUN` edits (stated at `engine/scripts/form_inspect.py:122-125`).

There is no separate graph structure to build: `DocumentGraph` is a
presentation of these three, and the Runtime must not renumber anything.

### 3.5 EditableRegion

Producer: `table_map` cells classified `fill_target`, plus the T30/T127
preflight attached to them at `engine/scripts/form_inspect.py:620`
(`_fill_preflight`): `charpr`, `script_anomaly`, `color_anomaly`,
`charpr_suggested`. Paragraph seats carry the same `color_anomaly` predicate
via `_run_record` (`engine/scripts/form_inspect.py:913`) and `ruled`, which is
the marker that says "this run is where the value goes" (T112).

An EditableRegion is therefore: an address (cell `row,col[#run]` or
`at_para,run`), a classification, the charPr it will inherit, and any anomaly
that must be resolved before writing. `spacer` cells are excluded by
construction (`engine/scripts/form_inspect.py:1444`).

Exact text of a region is **opt-in**, and must stay so: `--full-text`
(`engine/scripts/form_inspect.py:943`) emits only named cells/paragraphs, and
the structure-only default is a deliberate contract
(`engine/scripts/form_inspect.py:17-27`). GAP: no size cap on `--full-text`
output. Build note: the Runtime bounds a `document/readRegion` response the
way `run_child_capture` bounds child output, and refuses rather than truncates
silently — `text_preview` already learned that lesson and reports
`truncated: true` (`engine/scripts/form_inspect.py:32-35`).

### 3.6 Operation / OperationPlan

An Operation is one of the typed operations that already exist. There are
three registries, and they are not the same set:

**Offline (no COM, no Hancom) — `engine/scripts/preedit.py`**

| Operation | Entrypoint | Notes |
| --- | --- | --- |
| `replace` (string keys) | `engine/scripts/preedit.py:2425` | `--map`; 0-hit is an error unless `--allow-missing` |
| `replace` (cell address) | `engine/scripts/preedit.py:2439` / `:2446` | `--at-cell` / `--at-cell-append`; `--at-cell-expect` (`:2454`) is the exact-byte precondition |
| `set-runs` | `engine/scripts/preedit.py:2464` | `(at_para, run)` addressing; preserves the run's charPrIDRef |
| `fill-cells` | `engine/scripts/preedit.py:2479` | `--cell` / `--cell-line` / `--map`; per-cell charPr and paraPr overrides at `:2507` / `:2511` |
| `delete-guides` | `engine/scripts/preedit.py:2520` | guarded by `guards.is_protected_para` (`engine/scripts/guards.py:90`) |
| `normalize-clones` | `engine/scripts/preedit.py:2526` | post-checked by `guards.assert_no_dangling_charpr` (`engine/scripts/guards.py:142`) |

**Offline (structured build) — `engine/scripts/xml_backend.py:27`**
`goto_text, insert_text, insert_equation, insert_table, page_binding,
replace_all, insert_blank_before, insert_picture, set_line_spacing`.

**COM (Windows + Hancom only) — `engine/scripts/com_backend.py:1598`**
22 ops in `OPS`, required keys in `OP_REQUIRED_KEYS` (`:1626`), validated
before Hancom launches by `_validate_ops` (`:1670`).

Only the COM registry can insert native equations, pictures, hyperlinks and
tables into an arbitrary position; only the offline registries run on a machine
with no Hancom. The Runtime must report which registry a given operation kind
came from, because that determines whether the operation is even reachable on
this host (`pipeline/scripts/render_probe.py:20`).

An **OperationPlan** is an ordered list of Operations plus the exact-byte
binding of the document they were computed against. GAP: no plan object exists
today; each script takes its ops file and runs. Build note: the plan is the
Runtime's own object, and the batch-validate-then-execute discipline is already
proven at `engine/scripts/com_backend.py:1670` — validate the whole plan before
the first mutation, so a bad step cannot leave a half-edited document.

### 3.7 PlanValidation

Composed from checks that already exist, run **before** anything is written:

| Check | Existing implementation |
| --- | --- |
| unknown operation kind | `engine/scripts/com_backend.py:1689`; `engine/scripts/xml_backend.py:1138` |
| required key missing | `engine/scripts/com_backend.py:1626` + `:1685` |
| address schema (cellAddr vs traversal count) | `engine/scripts/com_backend.py:1644` (`_validate_set_cell`, refuses the T28 traversal reading unless `raw_traversal: true`) |
| ambiguous cell run | `engine/scripts/preedit.py:180` (`AmbiguousCellRunError`, exit 2, returns every run's exact text) |
| ambiguous replace key | `engine/scripts/preedit.py:221` (`AmbiguousReplaceKeyError`, exit 2, returns every occurrence with `at_para` and preceding context) |
| charPr script anomaly (T30) | `engine/scripts/preedit.py:136` (`ScriptAnomalyError`, exit 3, carries `suggested_flags`) |
| equation preflight | `engine/scripts/com_backend.py:1693-1699` (`_checked_equation_script`, refuses before COM and never echoes the LaTeX into the error) |
| well-formed XML after edit | `engine/scripts/preedit.py:26-31` — every modified member is parsed before the output zip is written; failure writes nothing |

Every one of these refusals already carries the information needed to fix the
call — the whole point stated at `engine/scripts/preedit.py:2694-2701`: the
caller must never have to open `section.xml` to interpret a refusal. The
Runtime must pass that payload through intact, not flatten it to a message.

### 3.8 ApprovalRequest / ApprovalRecord

Producer: `modules/report/scripts/pipeline_ctl.py`. The state vocabulary is
`pending | approved | auto_approved | rejected`
(`modules/report/scripts/pipeline_ctl.py:90`), with
`GREEN_GATE_STATES = {approved, auto_approved}` at `:109`.

The critical existing invariant: **`gate` never fabricates human approval.** A
human gate is resolved only by reading a matching line out of the workspace's
`APPROVALS.md` (`modules/report/scripts/pipeline_ctl.py:1112-1146`); with no
such line the command fails with "gate pending; human must edit APPROVALS.md"
(`:1159`). A script gate must be resolved by `check`, never by `gate`
(`:1066`, `:2059`). Approvals are appended to the event stream at
`modules/report/scripts/pipeline_ctl.py:857` (`append_event`).

Runtime mapping: `approval/request` (agent-safe) creates an ApprovalRequest and
returns its id; `approval/resolve` is **host-only** and writes the
`APPROVALS.md` line. The Runtime must not gain a way to approve that
`pipeline_ctl` does not already have.

### 3.9 CandidateArtifact

Producer: the quarantined diagnostic-candidate lane.
`pipeline/scripts/renderer_runtime_v2.py:1-10` states the contract: a staged,
hash-pinned adapter publishes an owned `artifact.pdf` plus a privacy-safe
receipt under a pre-created
`<workspace>/output/proof/renderer-runtime-v2/<run-id>` leaf, and the receipt
is *diagnostic evidence only* — no certificate validated, no proof claimed, no
grade promoted. Publication uses `publish_owner_token_pair` /
`publish_owner_token_receipt` and `rollback_publication`
(`pipeline/scripts/diagnostic_candidate_core.py:26`).

A CandidateArtifact therefore carries: run id, artifact hash, the receipt, and
the explicit statement that it is not proof. The Runtime must never promote a
candidate; promotion is `derive_proof_grade`'s business (§3.12).

### 3.10 Finding

Existing shape, unchanged: `{code, msg, at?, ...}` inside `hard[]` / `warn[]`
(`pipeline/scripts/checker_base.py:106`, `verdict_skeleton`). Per-rule outcome
vocabulary is fixed at `pipeline/scripts/checker_base.py:41`:
`hard | warn | skipped | clean`, with `rule_states()` at `:44` guaranteeing
every declared rule gets a row — "absent means it passed" was explicitly
retired (T118, docstring at `:45-55`), and severity wins over a skip
elsewhere.

The Runtime's `Finding` is that object verbatim. Do not rename `msg`.

### 3.11 VerificationReport

Producers, in the order a caller would use them:

| Report | Entrypoint | Verdict / exit |
| --- | --- | --- |
| Residue + expected text | `pipeline/scripts/check_residue.py:566` (`check`), CLI at `:769` | `pass`/`fail`; codes `form_residue` (`:687`), `pinned_target_missing` (`:610`), `artifact_malformed` (`:646`), `expected_text_missing` (`:724`) |
| Visual (two-pass) | `pipeline/scripts/visual_verify.py:2980` | `pass`(0) · `deterministic_pass`(0) · `vision_pending`(3) · `fail`(3) · `safety_incomplete`(3) · `usage_error`(2) — the whole table at `pipeline/scripts/visual_verify.py:22-40` |
| Submission preflight | `pipeline/scripts/submission_preflight.py:1` | fail-closed Stage 6 gate; 0/2/3 |
| Verdict self-consistency | `pipeline/scripts/verdict_schema.py:26` | `verdict_contradiction` when `converged:true` meets `status:escalate_human` |

Two properties of `visual_verify` the protocol must preserve rather than
paper over:

1. **Acceptance is not "nothing failed."** `acceptance: true` claims that every
   check in `SAFETY_CHECKS` (`pipeline/scripts/visual_verify.py:179`) actually
   ran; a run that could not run one reports `safety_incomplete` and exits 3.
   The only way past is `--accept-without CHECK`, recorded as
   `acceptance_waivers` in the verdict (`:2865`). A Runtime
   `verify/visual` response must surface `acceptance`, `acceptance_waivers`
   and `deterministic.skipped` as first-class fields — a bare `ok: true` would
   be a lie.
2. **The vision half is a separate turn.** Pass 1 exits 3 with
   `vision_pending` and a `vision_required[]` list; a model reads the PNGs
   against `skill/references/visual-rubric.md`; pass 2 merges the vision
   verdict. The script never calls a model
   (`pipeline/scripts/visual_verify.py:5-8`). The protocol must model this as
   two requests with an artifact handoff, not as one long call — and the
   Runtime must never acquire the ability to fill in the vision half itself.

`--expect-text` (T130, `pipeline/scripts/check_residue.py:812`) is a
**text-level** claim and its verdict says so in-band:
`expected_text.evidence_level = "text"` (`:748`). Carry that field through;
it is the difference between "the string is in the document" and "the reader
can see it."

### 3.12 Receipt / ArtifactRef

Producer: `engine/scripts/document_evidence.py`.

- Schema id `rigorloom/document-evidence/v1` at `:29`; canonical location
  `output/proof/backend/receipt.json` at `:30`.
- Closed vocabularies: `BACKEND_IDS` (`:32`), `EVIDENCE_CLASSES` (`:40`),
  `ARTIFACT_ROLES` (`:47` — `source_form`, `assembled_hwpx`, `rendered_pdf`,
  `diagnostic_svg`). An unknown value is a validation error
  (`_validate_enum`, `:824`).
- Build / validate / load: `build_receipt` (`:1125`), `validate_receipt`
  (`:1356`), `load_and_validate_receipt` (`:2106`).
- Grade derivation: `derive_proof_grade` (`:780`) — fails closed to `none` on
  any unknown value or non-success terminal state, and takes **no**
  renderer-probe input. Capability is not proof; that separation is stated at
  `engine/scripts/document_evidence.py:4-8`.
- Atomic publication: `write_receipt` (`:1998`) validates, publishes and
  rebinds identity; the directory binding is `_DestinationDirectoryBinding`
  (`:1573`) with `os.fsync` at `:1737` and `os.replace(..., src_dir_fd=...)`
  at `:1766`.

An **ArtifactRef** is the receipt's artifact descriptor: a workspace-relative
POSIX path, a role, a sha256 and a byte count (`_capture_file`, `:457`;
`_artifact_descriptor`, `:652`). Absolute paths never appear in a receipt
(`:1146`), and local node identity is never serialized (`:182`).

### 3.13 Event

Producer: the append-only workspace stream `events.jsonl`, described at
`docs/pipeline-master-v0.6.md:81` and written by
`modules/report/scripts/pipeline_ctl.py:857`. Studio already tails it
(`studio/main.py:1005`).

Runtime mapping: an `event` notification is a projection of an appended line,
not a second source of truth. The Runtime may push; the file remains
authoritative.

### 3.14 RecoveryManifest

Producer: `pipeline/scripts/ws_snapshot.py`. Snapshots cover
`bundle/`, `output/`, `PIPELINE.md`, `.pipeline/`
(`pipeline/scripts/ws_snapshot.py:29`), archives carry a required `.sha256`
sidecar (`:51`), and restore is member-by-member with zip-slip, symlink-member
and symlink-parent refusals (`:238`, `:254`, `:290`). Exit contract 0/2/3
(`:32`, `:36`).

GAP: there is no crash-time manifest — snapshots are taken deliberately, and
nothing records "a plan was in flight when the process died." Build note: the
RecoveryManifest is written by the Runtime before the first mutation of a
plan and removed after the last, naming the snapshot id, the plan hash and the
bound document hash; recovery offers `ws_snapshot restore` and never
auto-restores.

---

## 4. Authority

Authority is a property of the **connection**, established at initialize by
how the Runtime was launched — never a field a client sets in a request. A
`params.authority` member is an `unknown_field` refusal, and an
`authority`-shaped claim anywhere in a payload is ignored and logged.

### Host-only methods

| Method | Why host-only | Existing enforcement to reuse |
| --- | --- | --- |
| `workspace/openPath` (arbitrary filesystem path) | escapes any containment the workspace root provides | `studio/main.py:100` (`safe_workspace`) refuses out-of-root today; agent-side opens must go through a slug, not a path |
| `workspace/importAttachment` | brings unvetted bytes into the tree | `pipeline/scripts/hwp_ingress.py:40-46` bounds every input dimension; `pipeline/scripts/privacy_scan.py:1` is the content gate |
| `approval/resolve` | this *is* the human gate | `modules/report/scripts/pipeline_ctl.py:1112-1159` — never fabricates approval |
| `artifact/exportTo` (user-chosen path) | writes outside the workspace | `engine/scripts/document_evidence.py:558` (`_safe_relative_path`) refuses escapes for everything inside |
| `provider/configure` | credentials and model endpoints | `pipeline/scripts/backend_precheck.py:9-12` keeps all backend specifics in an operator-private config, never in the repo |
| `policy/set` | changes what the gates mean | `pipeline/scripts/personalization_ctl.py:1-6` — profile roots are local operator state |
| `workspace/delete` | irreversible | GAP: no deletion entrypoint exists. Build note: implement as snapshot-then-remove via `ws_snapshot`, host-only, never exposed to an agent connection |

### Agent-safe methods

`capabilities/list`, `workspace/list`, `document/summary`, `document/graph`,
`document/regions`, `document/readRegion` (bounded, opt-in), `plan/propose`,
`plan/validate`, `approval/request`, `candidate/read`, `verify/read`,
`receipt/read`, `event/subscribe`.

Note what is *not* on the agent list: `plan/apply`. In v0 an agent proposes and
validates; the host applies. This is the conservative reading of "one
OperationPlan path for human and agent edits" — the path is shared, the
authority to run it is not.

Refusal for an authority violation is `authority_denied`, exit-3-class,
naming the method and the authority the connection actually has. It must be
distinguishable from `unknown_method`, so that a client can tell "this build
cannot do that" from "you may not do that."

---

## 5. Error and refusal codes

The repository already has a refusal vocabulary. The table below reuses it and
marks the genuinely new codes.

### 5.1 Reused verbatim

| Code | Origin | Meaning kept |
| --- | --- | --- |
| `receipt_duplicate_key` | `engine/scripts/document_evidence.py:1952` | a JSON object repeats a member, at any nesting level |
| `receipt_nonfinite_value` | `engine/scripts/document_evidence.py:1962` | `NaN`/`Infinity`/`-Infinity` or an overflowing float literal |
| `receipt_malformed` | `engine/scripts/document_evidence.py:1985` | not valid UTF-8 JSON |
| `invalid_receipt` | `engine/scripts/document_evidence.py:1991` | valid JSON, wrong top-level type |
| `path_escape` | `engine/scripts/document_evidence.py:589`, `:594`, `:603` | path leaves the workspace, lexically or after resolution |
| `artifact_missing` | `engine/scripts/document_evidence.py:606` | bound artifact absent or symlinked |
| `artifact_parent_not_directory` | `engine/scripts/document_evidence.py:646` | a parent component is a symlink/reparse point |
| `artifact_parent_unreadable` | `engine/scripts/document_evidence.py:639` | a parent could not be stat'd |
| `file_too_large` | `pipeline/scripts/diagnostic_candidate_core.py:308` | input exceeds its declared bound |
| `directory_binding_changed` | `pipeline/scripts/diagnostic_candidate_core.py:226` | the bound directory is no longer the same node |
| `hancom_mutex_busy` | `pipeline/scripts/hwp_ingress.py:1225` | another COM operation holds the machine-wide mutex |
| `at_cell_run_ambiguous` | `engine/scripts/preedit.py:2699` | cell has >1 text run; payload lists them all |
| `replace_key_ambiguous` | `engine/scripts/preedit.py:2708` | key matches >1 location; payload lists all occurrences |
| `fill_charpr_script_anomaly` | `engine/scripts/preedit.py:2715` | T30 preflight refusal; payload carries `suggested_flags` |
| `form_residue` | `pipeline/scripts/check_residue.py:687` | scan inventory survived into the final |
| `pinned_target_missing` | `pipeline/scripts/check_residue.py:610` | a pinned artifact is absent (loud, never a silent pass) |
| `artifact_malformed` | `pipeline/scripts/check_residue.py:646` | a critical XML member does not parse |
| `expected_text_missing` | `pipeline/scripts/check_residue.py:724` | `--expect-text` string absent |
| `verdict_contradiction` | `pipeline/scripts/verdict_schema.py:43` | `converged:true` with `status:escalate_human` |
| `document_state_declared_against_evidence` | `pipeline/scripts/checker_base.py:93` | a declared mode contradicts the derived state (WARN, not HARD) |
| `source_not_a_document` | `engine/scripts/com_backend.py:111` | privacy-safe inspect refusal, one token, path never echoed |
| `certificate_invalid_json` / `operation_failed` | `pipeline/scripts/render_cert.py:1597` / `:637` | legacy v1 certificate boundary — do not repurpose |

### 5.2 New transport codes (GAP — all of them)

`protocol_version_unsupported` · `not_initialized` · `already_initialized` ·
`frame_too_large` · `frame_malformed` · `unknown_method` · `unknown_field` ·
`invalid_params` · `authority_denied` · `cancelled` · `plan_stale` ·
`capability_unavailable`.

Build note (one line each): they are the protocol's own failure modes and have
no engine counterpart; put them in one module beside the framing code, with a
test asserting the set is closed — the same discipline `BACKEND_IDS`
(`engine/scripts/document_evidence.py:32`) and `RULE_STATES`
(`pipeline/scripts/checker_base.py:41`) already apply to their vocabularies.

`plan_stale` deserves its own note: it is the exact-byte binding refusal. The
engine's nearest existing relative is `--at-cell-expect`
(`engine/scripts/preedit.py:2454`), a per-run precondition that writes nothing
on mismatch, and `form_hash` (`engine/scripts/form_inspect.py:1418`) is the
document-level hash a plan should bind to.

### 5.3 Severity mapping

`hard` → error frame, exit-3-class · `warn` → carried in the response, never
promoted or dropped · `skipped` → carried with its reason · `clean` → present
with no finding. Same four values as `pipeline/scripts/checker_base.py:41`;
adding a fifth would fork the vocabulary the whole repo shares (T101).

---

## 6. Method → engine entrypoint map

Every row cites a real entrypoint. `GAP` rows have no implementation today.

| Runtime method | Authority | Existing entrypoint | Gap |
| --- | --- | --- | --- |
| `initialize` | either | — | GAP: new. Build note: version string equality + capability snapshot from `engine/scripts/probe.py:1`. |
| `capabilities/list` | agent | `engine/scripts/probe.py:1`; `pipeline/scripts/render_probe.py:20`; `pipeline/scripts/module_registry.py:509` | none for content; GAP for the `methods` list (computed by the Runtime) |
| `workspace/list` | agent | `studio/main.py:100` (`safe_workspace`) + `WORKSPACE_ROOT` (`studio/main.py:91-96`) | GAP: enumeration lives in Studio's HTTP layer, not a library. Build note: lift slug resolution into a shared module both Studio and Runtime import. |
| `workspace/openPath` | host | `pipeline/scripts/hwp_ingress.py:1` (bounded ingress) | GAP: no "open arbitrary path into a workspace" entrypoint. Build note: ingress-validate, then copy into the workspace; never operate in place. |
| `workspace/importAttachment` | host | `pipeline/scripts/hwp_ingress.py:40-46`; `pipeline/scripts/privacy_scan.py:1` | GAP: no import command. Build note: bounds + privacy scan before the bytes land. |
| `document/summary` | agent | `engine/scripts/form_inspect.py:1167`; COM variant `engine/scripts/com_backend.py:1715` | none |
| `document/graph` | agent | `engine/scripts/form_inspect.py:802` (`_table_map`), `:1051` (`_resolve_at_para`) | none |
| `document/regions` | agent | `engine/scripts/form_inspect.py:620` (`_fill_preflight`), `:913` (`_run_record`) | none |
| `document/readRegion` | agent | `engine/scripts/form_inspect.py:943` (`--full-text`) | GAP: no response size bound. Build note: cap and refuse, do not truncate. |
| `plan/propose` | agent | — | GAP: new object over existing op registries (`engine/scripts/preedit.py:2425`+, `engine/scripts/xml_backend.py:27`, `engine/scripts/com_backend.py:1598`). |
| `plan/validate` | agent | `engine/scripts/com_backend.py:1670`; `engine/scripts/preedit.py:136`/`:180`/`:221` | GAP: validation is per-script today. Build note: one dispatcher that routes each op kind to its owning backend's validator without executing. |
| `plan/apply` | host | `engine/scripts/preedit.py:2417`; `engine/scripts/xml_backend.py:1116`; `engine/scripts/com_backend.py:1723` | GAP: no cross-backend applier. Build note: one plan = one backend; a mixed plan is `invalid_params`, because `preedit` already refuses to mix its own two addressing modes in one call for the same reason (`engine/scripts/preedit.py:2552-2555`). |
| `approval/request` | agent | `modules/report/scripts/pipeline_ctl.py:1050` (`cmd_gate`) | GAP: gates are declared per-stage, not requested ad hoc. |
| `approval/resolve` | host | `modules/report/scripts/pipeline_ctl.py:1112` | none — reuse `APPROVALS.md` reading exactly |
| `verify/residue` | agent (read) / host (run) | `pipeline/scripts/check_residue.py:566` | none |
| `verify/visual` | host | `pipeline/scripts/visual_verify.py:2980` | none; two-turn shape is already the contract |
| `verify/preflight` | host | `pipeline/scripts/submission_preflight.py:1` | none |
| `candidate/read` | agent | `pipeline/scripts/renderer_runtime_v2.py:1` | none |
| `receipt/read` | agent | `engine/scripts/document_evidence.py:2106` | none |
| `receipt/write` | host | `engine/scripts/document_evidence.py:1998` | none |
| `artifact/exportTo` | host | — | GAP: everything today writes inside the workspace. Build note: copy out with an explicit host-confirmed destination; the receipt keeps the workspace-relative path (`engine/scripts/document_evidence.py:1146`). |
| `provider/configure` | host | `pipeline/scripts/backend_precheck.py:1` | GAP: config is a file the operator edits. Build note: the Runtime may validate, not write, in v0. |
| `policy/set` | host | `pipeline/scripts/personalization_ctl.py:1` | GAP: no protocol surface. |
| `workspace/snapshot` | host | `pipeline/scripts/ws_snapshot.py:1` | none |
| `workspace/restore` | host | `pipeline/scripts/ws_snapshot.py:477` | none |
| `workspace/delete` | host | — | GAP (see §4) |
| `event/subscribe` | agent | `modules/report/scripts/pipeline_ctl.py:857` (`append_event`) | GAP: no watcher. Build note: poll-and-diff the tail, as Studio does at `studio/main.py:1005`. |
| `$/cancel` | either | `pipeline/scripts/diagnostic_candidate_core.py:1128` | GAP: cooperative cancellation between steps only. |

---

## 7. Invariants and where they already live

| Invariant | Already enforced at |
| --- | --- |
| Source immutability | `engine/scripts/preedit.py:2335` (`--out` required; "원본 비파괴"); `engine/scripts/xml_backend.py:1126` (`--save-as must differ from --file`); `engine/scripts/com_backend.py:1726` (no `--save-as` means the original is not overwritten) |
| One plan path, human and agent | GAP by construction — the path must be built once. The nearest precedent is `engine/scripts/com_backend.py:1670`: validate the whole batch before the first mutation. |
| Exact-byte binding, stale plans refuse | `engine/scripts/preedit.py:2454` (`--at-cell-expect`, writes nothing on mismatch); `engine/scripts/form_inspect.py:1418` (`form_hash`); `engine/scripts/document_evidence.py:1356` (`validate_receipt` re-checks bytes) |
| Fail closed | `engine/scripts/document_evidence.py:780` (`derive_proof_grade` → `none` on anything unknown); `pipeline/scripts/check_residue.py:99` (an untrustworthy removal policy falls back to the strict legacy mode); `pipeline/scripts/submission_preflight.py:1` |
| Explicit unavailable / unknown | `pipeline/scripts/render_probe.py:22` (`"yes"|"no"|"unknown"` + reason strings); `engine/scripts/form_inspect.py:913` (key omitted when undecidable); `pipeline/scripts/checker_base.py:41` (`skipped` is a reported state) |
| No ambient network | `studio/README.md:6` ("no CDN or network dependency"); `pipeline/scripts/render_probe.py:4` (probes, never launches); `pipeline/scripts/renderer_runtime_v2.py:47` (`ENV_POLICY = "minimal_allowlist_v1"`). The Runtime inherits this: no socket, no HTTP client, no DNS. |
| Core stays module-agnostic | `pipeline/scripts/module_registry.py:15` (core never learns a module's name); typed accessors at `:694`–`:751`; `studio/main.py:20` follows the same rule |
| No second editing engine | this document: every mutating method routes to `preedit`, `xml_backend` or `com_backend` |

---

## 8. Open questions

1. **Which backend owns a plan.** `preedit`, `xml_backend` and `com_backend`
   have three overlapping and non-identical op sets, with different
   addressing (`row,col#run` vs `at_para,run` vs anchor text) and different
   availability. Nothing in the tree decides, for a given intent, which
   backend should run it — `pipeline/scripts/doc_backend.py:7` resolves a
   backend from a flag or `build.yaml`, not from the operation. Does the plan
   declare its backend, or does the Runtime choose?
2. **Whether `plan/apply` ever becomes agent-safe.** v0 says no. The
   invariant "one OperationPlan path for human and agent edits" is satisfiable
   either way, and the answer determines whether the approval object is a gate
   in front of apply or merely a record beside it.
3. **What binds a plan when the source is `.hwp`, not `.hwpx`.** `form_hash`
   comes from the zip (`engine/scripts/form_inspect.py:1418`); a binary HWP5
   goes through `pipeline/scripts/hwp_ingress.py:1` instead. Is the binding a
   whole-file sha256 for that case, and does that make every COM edit a
   full-document rebind?
4. **Progress granularity for COM operations.** A `com_backend edit` batch is
   one subprocess and one JSON object; the Runtime can only report "started"
   and "finished" unless the batch is split into per-op invocations, which the
   machine-wide mutex (`pipeline/scripts/hwp_ingress.py:1186`) makes expensive.
   Is per-op progress worth N Hancom round-trips?
5. **Cancellation semantics mid-COM.** Terminating Hancom mid-edit is exactly
   the failure T21 exists to prevent (`engine/scripts/guards.py:231`). Is a
   COM plan simply non-cancellable once started, and is that acceptable to
   the Desktop UI?
6. **Where the vision half runs.** `visual_verify` deliberately never calls a
   model (`pipeline/scripts/visual_verify.py:5`). If the Agent Host supplies
   the vision verdict over this protocol, the Runtime becomes the thing
   handing PNGs to a model — does that violate the separation, or is the
   Runtime merely a courier?
7. **Studio's HTTP surface versus the Runtime.** Studio is already a localhost
   control server with actions, a CSRF token and a Host guard
   (`studio/main.py:993`). v0 says no localhost control server for the
   Runtime. Do the two coexist, does Studio become a Runtime client, or is
   Studio's action mode retired? This is a program-level decision, not a
   protocol one.
8. **Event ordering across a restart.** `events.jsonl` is append-only but has
   no sequence number; Studio finds the newest by reading the tail
   (`studio/main.py:1005`). A subscriber that reconnects cannot say "resume
   after event N". Does the Event object gain a monotonic id, and who assigns
   it?

---

## 9. Implementation status (Phase 1 slice)

Implemented in `runtime/` on this branch. Everything not listed is still GAP.
The slice serves the offline `preedit` backend only (orchestrator decision D9);
`xml` and `com` plans, and op kinds those backends own, are refused with
`unsupported_backend` naming the backend that would serve them.

### Methods

| Method | Status | Where |
| --- | --- | --- |
| `initialize` | implemented | `runtime/scripts/rt_server.py` `_m_initialize` |
| `capabilities/list` | implemented (no render probe) | `_m_capabilities` |
| `session/list` | implemented | `_m_session_list` |
| `workspace/openPath` (host) | implemented — size + zip sanity; no HWP5 CFB walk | `runtime/scripts/rt_session.py` `validate_source` |
| `document/inspect` | implemented — summary + graph + regions | `_m_document_inspect` |
| `document/readRegion` | implemented, bounded, refuses rather than truncates | `_m_document_read_region` |
| `plan/propose` | implemented | `runtime/scripts/rt_plan.py` `build_plan` |
| `plan/validate` | implemented, profile-derived (see below) | `rt_plan.validate_plan` |
| `plan/get`, `approval/get` | implemented | `rt_server` |
| `approval/request` (agent) | implemented | `rt_plan.request_approval` |
| `approval/resolve` (host) | implemented, binds plan id + plan hash | `rt_plan.resolve_approval` |
| `plan/apply` (host) | implemented | `runtime/scripts/rt_apply.py` `apply_plan` |
| `candidate/list`, `receipt/read` | implemented; the receipt refuses on drift | `rt_apply` |
| cancellation | implemented, cooperative between ops | `rt_server._checkpoint` |
| `artifact/exportTo`, `provider/configure`, `policy/set`, `workspace/snapshot`, `workspace/restore`, `workspace/delete`, `event/subscribe`, `verify/*` | GAP | — |

Cancellation is spelled `{"kind":"cancel","id":...}` rather than a `$/cancel`
method: a cancel is not a request, it takes no response, and the reader thread
must act on it while a request is still in flight.

### Codes

All twelve transport codes from §5.2 are implemented and closed
(`runtime/scripts/rt_codes.py`), plus `unsupported_backend`,
`unknown_op_kind`, `plan_invalid`, `approval_binding_mismatch`,
`approval_already_resolved`, `region_too_large`, `source_rejected`,
`candidate_hash_mismatch`, `receipt_body_mismatch`, `backend_refused`,
`publication_failed`. `authority_denied` is NOT implemented and should be
dropped from v0: authority is registry membership, so a host-only method is
`unknown_method` on an agent connection, with `knownOnHostEntry: true` carrying
the diagnostic §4 wanted.

### Three corrections to this document, found by implementing it

1. **§5.1 was wrong about the receipt codes.** `receipt_duplicate_key` and
   `receipt_nonfinite_value` cannot be "reused verbatim" for the transport:
   they name a *receipt* and carry `path: output/proof/backend/receipt.json`
   (`engine/scripts/document_evidence.py:1952`). A duplicate member in a
   request frame is not a receipt defect. Frames use `duplicate_key` /
   `nonfinite_number`; the receipt-reading path keeps the `receipt_*` spelling
   where it is true.
2. **§3.7's "route to the preedit validator without executing" is not
   reachable.** `preedit` raises its refusals from inside its edit path
   (`engine/scripts/preedit.py:136`, `:180`, `:221`) and ships no dry run.
   Validation is therefore derived from the same facts via `form_inspect`'s
   preflight fields — which does reproduce the T30 anomaly and the ambiguous
   cell run under preedit's own code names — and everything it cannot reach is
   listed in `preflight.deferred` instead of being assumed clean.
3. **Sessions cannot be per-connection.** `workspace/openPath` is host-only and
   `plan/propose` is agent-safe, so with per-connection state an agent
   connection could never reach a document and the whole agent surface would be
   decorative. Sessions, plans and approvals are keyed on disk under `--root`,
   the way a report workspace already is
   (`modules/report/scripts/pipeline_ctl.py:1112`). Concurrency across
   processes is last-writer-wins, which is the slice's largest unresolved risk.
