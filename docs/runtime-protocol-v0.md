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
| `document/renderPrepare` | starts Hancom on the operator's machine | implemented; `rt_convert` — serial, refuses a busy machine, never terminates one |
| `workspace/delete` | irreversible | GAP: no deletion entrypoint exists. Build note: implement as snapshot-then-remove via `ws_snapshot`, host-only, never exposed to an agent connection |

### Agent-safe methods

`capabilities/list`, `session/list`, `document/inspect` (returning `summary`,
`graph` and `regions`), `document/readRegion` (bounded, opt-in), `document/render`,
`plan/propose`,
`plan/validate`, `approval/request`, `candidate/read`, `verify/read`,
`receipt/read`, `event/poll`, `module/list`, `module/check` (§13 — read-only
analysis over a scratch copy, reachable only for a module the operator
enabled), and the protocol-only `event/subscribe` / `event/unsubscribe`.

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
| `workspace/list` | — | — | **WITHDRAWN**, not deferred. A Runtime workspace is not an object: `--root` is the store and a connection has exactly one. `session/list` is the enumeration. See §11 |
| `workspace/openPath` | host | `pipeline/scripts/hwp_ingress.py:1` (bounded ingress) | GAP: no "open arbitrary path into a workspace" entrypoint. Build note: ingress-validate, then copy into the workspace; never operate in place. |
| `workspace/importAttachment` | host | `pipeline/scripts/hwp_ingress.py:40-46`; `pipeline/scripts/privacy_scan.py:1` | GAP: no import command. Build note: bounds + privacy scan before the bytes land. |
| `document/inspect` | agent | `engine/scripts/form_inspect.py:1167`; COM variant `engine/scripts/com_backend.py:1715` | none. **Not three methods.** One call returns `summary`, `graph` and `regions` together, selectable with `include`; the next three rows describe what it RETURNS, not methods you can call |
| `document/inspect` → `graph` | agent | `engine/scripts/form_inspect.py:802` (`_table_map`), `:1051` (`_resolve_at_para`) | none. A RESULT SECTION, not a method — there is no `document/graph` on the wire |
| `document/inspect` → `regions` | agent | `engine/scripts/form_inspect.py:620` (`_fill_preflight`), `:913` (`_run_record`) | none. A RESULT SECTION, not a method |
| `document/readRegion` | agent | `engine/scripts/form_inspect.py:943` (`--full-text`) | implemented, bounded, refuses rather than truncates |
| `document/render` | agent | `rt_render.render_page` over PyMuPDF (optional) | implemented; see §11 for when it can and cannot produce a page |
| `document/pageGeometry` | agent | `rt_geometry.page_geometry` over the same PDF | implemented; real positions + address mapping — §12 |
| `document/renderPrepare` | **host** | `engine/scripts/com_backend.py convert` in a bounded child | implemented; serial, refuses `com_busy`, never kills — §11.1b |
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
| `event/subscribe`, `event/unsubscribe` | agent (protocol-only) | `rt_session.append_event` / `read_events` over the SESSION log | implemented; poll-and-diff, seq-ordered. Not an MCP tool — see §11 |
| `event/poll` | agent | same source, request/response | implemented |
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
| `artifact/exportTo`, `provider/configure`, `policy/set`, `workspace/snapshot`, `workspace/restore`, `workspace/delete`, `verify/*` | GAP | — |
| `document/render`, `document/renderPrepare`, `event/subscribe`, `event/unsubscribe`, `event/poll` | implemented in Phase 3 | §11 |

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

---

## 10. Phase 2 — CLI and MCP parity

The exit criterion is "the same document, target, and proposed operation
produce compatible plan and verification representations through Runtime, CLI
and MCP". `tests/test_runtime_parity.py` measures it against a corpus form;
this section records what "compatible" was made to mean and what changed to
make it measurable.

### One domain layer

`runtime/scripts/rt_core.py` now holds every operation. The three front ends
own only their own concerns:

| Front end | Owns |
| --- | --- |
| `rt_server.py` | JSONL framing, the initialize handshake, the unknown-field policy, cancellation, and which methods a connection can reach |
| `cli.py` | argument parsing and process exit codes |
| `mcp_server.py` | JSON-RPC 2.0 over stdio and the MCP tool envelope |

A plan proposed through the CLI and a plan proposed over the server differ in
exactly two things: the `proposer` string the caller supplies, and the identity
fields every proposal has anyway.

### Two hashes, because one could not do both jobs

`planHash` covers the whole plan object — `planId`, `createdUtc`, `sessionId`,
`proposer` included. That is correct for what it is: the thing an approval
binds to (`resolve_approval` refuses a decision naming a different hash). It
is therefore never equal between two proposals, which makes it useless as a
parity measure.

So `OperationPlan` gained **`opsHash`**: `sha256` over the canonical
`{backend, boundSha256, ops}` — this document, this backend, these operations.
It is identical whenever the document, the target and the operation are
identical, whichever front end proposed it and whenever. Parity is stated
against `opsHash`; the approval binding stays on `planHash`. The parity suite
asserts both directions — same `opsHash`, and three *different* `planHash`es —
so the property cannot degrade into "every plan is the same plan".

### What the parity suite proves

- `opsHash` identical through server, CLI and MCP, and recomputable from first
  principles rather than merely equal;
- the plan objects field-for-field equal once identity fields are removed;
- validation returns the same verdict, hard codes, warn codes, staleness and
  `preflight.deferred` — proven on a clean plan *and* on a T30 anomaly;
- a refusal reads identically through all three doors, `data` included;
- a candidate applied from a CLI-authored plan and one applied from a
  server-authored plan have the same SHA-256;
- an MCP-authored plan, approved on the CLI and applied over the server, lands
  on that same SHA-256 — the cross-front-end handoff;
- the MCP tool surface equals a live agent registry minus `initialize`,
  derived from `RuntimeServer(entry="agent")` rather than from a list.

### CLI exit codes

`0` succeeded · `2` usage · `3` refusal · `4` internal. The fourth extends the
repository's 0/2/3 contract (`pipeline/scripts/checker_base.py:13-16`)
deliberately: an automation must be able to tell a refusal from a crash, and
collapsing them hides the crash. A successful exit does not imply verification
ran — `apply` reports `checks.ranAll` and `checks.acceptance` separately, and
`--require-checks` / `verify` are the fail-closed readings.

### MCP framing

Newline-delimited JSON-RPC 2.0, per the MCP stdio transport: messages are
newline-delimited and must not contain embedded newlines. `Content-Length`
header framing belongs to the Language Server Protocol, not to MCP, whose
second transport is HTTP rather than a header-framed pipe. The adapter
therefore reuses `rt_jsonl.read_raw_frame` unchanged, inheriting its size cap
and its duplicate-key and non-finite refusals. Implemented methods:
`initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`.
Nothing else is claimed — no resources, prompts, sampling or logging.

A domain refusal comes back as a tool result with `isError: true` carrying the
full structured payload, not as a JSON-RPC error: the model needs the escape
hatch the engine put in it.

### Method roster

`rt_core.AGENT_METHODS` and `rt_core.HOST_ONLY_METHODS` are the one roster.
`rt_server` asserts its handler maps match them at construction; `mcp_server`
derives its tool surface from `AGENT_METHODS` and fails at import if a method
has no schema or a schema names a host-only method. Adding an agent method
therefore surfaces it on the CLI and in MCP, or breaks loudly.

`RuntimeCore.candidate_verify` is domain but deliberately NOT in `METHODS`: the
CLI's `verify` composes it, and the wire does not grow a tool for it.

### Still GAP after Phase 2

`artifact/exportTo`, `provider/configure`, `policy/set`, `workspace/snapshot`,
`workspace/restore`, `workspace/delete` and `verify/*` as protocol methods, and
descendant containment for child processes. `document/render`, the event stream
and renderer capability reporting closed in Phase 3 (§11).

---

## 11. Phase 3 — rendering, events, and the child interpreter

Three gaps the Desktop foundation recorded (`desktop/README.md`, "Runtime gaps
this phase hit"), closed in the order they block the product surface.

### 11.1 `document/render` — and when there is no page

```
document/render {sessionId, page?=0, dpi?=96, runId?, inline?=true}
```

**What can produce a page image today, without COM.** Only a PDF. PyMuPDF can
rasterise one and is importable in most installs, but it is an OPTIONAL
dependency (`pyproject.toml` extras `studio`, `engine`), so it is imported
lazily inside the call and its absence is a reported state rather than a
startup error. An HWPX cannot become a PDF here: conversion is Hancom COM
(`engine/scripts/com_backend.py convert`) or LibreOffice, and this build runs
neither.

So the method renders when the session already HAS a PDF — because the opened
document is one, or because `runId` names a candidate that is one — and
otherwise returns a structured unavailable state. **There is no fabricated
layout.** A form scan knows a page's margins (`page_metrics`); it does not know
what the page looks like, and drawing a box from the one and calling it the
other would be a lie the Desktop would faithfully render.

`available: false` is a RESULT, not an error, because "there is no page image
for this document" is an answer the UI must draw. The reason comes from a
closed set:

| reason | means |
| --- | --- |
| `needs_conversion` | an HWPX; a converter would be required, and this build calls none |
| `no_rasterizable_artifact` | nothing here is a PDF |
| `rasterizer_missing` | a PDF is present but PyMuPDF is not importable |
| `artifact_missing` | a `runId` was named and its bytes are gone |

On success the response carries `pageCount`, `pageSize` in points, the dpi
used, and an `image` that ALWAYS has a session-relative `path` and inlines
base64 only when it fits under `MAX_INLINE_IMAGE_BYTES` (512 KiB, well under
the 1 MiB frame cap because base64 costs a third on top). Above that it says
`inline: false` with a reason rather than blowing the frame.

Naming a `runId` reads the receipt first, so a raster is never taken from a
candidate whose bytes drifted after publication.

**A raster is not evidence.** Every result carries
`evidence.class = "structural_only"` and `proofGrade: "none"`, using
`engine/scripts/document_evidence.py`'s closed vocabularies (`:40`, `:780`).
Rendering bytes tells you what they draw, not that they are the right bytes.

**Capability reporting.** `capabilities.render` has two rows.
`rasterizer` is a `find_spec` — cheap enough for the hot path.
`converter` is flatly `no` with a reason, whatever the machine has installed,
because a converter this build does not call is not a capability this build
has. The machine's actual inventory is opt-in:
`capabilities/list {probeRenderers: true}` runs
`pipeline/scripts/render_probe.py` in a bounded child and caches it for the
process. It is opt-in because it costs about eight seconds on the bench —
fine for a button, ruinous for `initialize`.

### 11.1b `document/renderPrepare` — making the PDF

```
document/renderPrepare {sessionId, timeoutSeconds?}      HOST ONLY
```

The step that turns an HWPX session into something `document/render` can
raster, and the only place in the Runtime that can reach Hancom. A human
clicks; a bounded child runs `engine/scripts/com_backend.py convert`; the PDF
lands at `<session>/derived/source.pdf` and is recorded against the source's
SHA-256 so it can never be served for a document it does not describe.

Four rules, each with a scar behind it:

1. **The user's original is never the input.** The conversion runs against the
   session copy. Hancom opens and re-saves documents; pointing it at the file
   the operator picked would put the one irreplaceable artifact under an
   automated editor.
2. **COM is serial and we never make room.** `tasklist` is checked for a live
   Hancom image name and a hit is `com_busy` — not a queue, and never a kill.
   `engine/scripts/guards.py:234-240` records what `--kill-stale` did the last
   time two sessions shared a machine: each one's `taskkill /F /IM Hwp.exe`
   killed the other's in-progress instance, four RPC crashes in a row.
   `pipeline/scripts/visual_verify.py:57-63` states the same rule. There is no
   kill path in `rt_convert`, and a test asserts that structurally (by AST, so
   the docstring may still explain the danger).
   An unreadable `tasklist` counts as busy, not as free.
3. **The child is bounded like every other child.** Same `run_child`, same
   environment allowlist, its own 30–900 s timeout. A hang is
   `convert_failed {timedOut: true}`, never a hung request.
4. **Absence is reported.** No Hancom is `needs_hancom` with the reason, and
   `capabilities.render.prepare` says so before anyone clicks.

Refusals: `needs_hancom`, `com_busy`, `not_convertible`, `convert_failed`.
Preparing twice is a no-op that reports `prepared: false`. Success appends a
`pdf.prepared` event.

**The live COM leg is not tested.** The suite may not start Hancom, so the
tests cover the ProgID probe, the tasklist parse, all four refusals, the
source-binding rule, the authority split, and the whole prepare → render chain
with `rt_convert.run_convert` substituted by a prebuilt PDF. One live smoke on
an operator machine is owed.

### 11.2 Events

Sessions now keep their own log at `<session>/events.jsonl`, appended on every
mutation: `session.opened`, `plan.proposed`, `plan.validated`,
`approval.requested`, `approval.resolved`, `plan.applied`,
`candidate.published`. This is a RUNTIME log; the report pipeline's own
`events.jsonl` (`modules/report/scripts/pipeline_ctl.py:857`) is a different
file about a different thing, and the two are deliberately not merged.

**The sequence is the line index, not a stored field.** Storing a sequence
number means allocating one, and an allocator is a second thing to keep
consistent. A line's position in the file is monotonic, gap-free and
duplicate-free by construction, so a cursor is safe across processes. A torn
trailing line (a crash mid-write) keeps its index and is skipped — indexes are
never reused, which is the property that makes `after: N` mean something.

Two surfaces, because two transports:

```
event/subscribe {sessionId, after?=-1, intervalMs?=250}   protocol-only
   -> {subscriptionId, ...} then notification "event" {subscriptionId,
      sessionId, event:{seq, at, kind, sessionId, detail}}
event/unsubscribe {subscriptionId}                        protocol-only
event/poll {sessionId, after?=-1, limit?}                 agent-safe, MCP tool
```

`event/subscribe` pushes notifications, which an MCP tool call has nowhere to
put — so `rt_core` gained a third roster, `PROTOCOL_ONLY_METHODS`: agent-safe
by authority, registered on both JSONL entries, absent from the MCP tool
surface. `event/poll` is the tool-shaped equivalent, so an MCP client is not
left without the events.

Delivery is poll-and-diff on a bounded interval (50–5000 ms), capped at 500
events per tick and 32 subscriptions per connection. The replay and every later
event are written AFTER the subscribe response, so a client always learns its
subscription id before the first event on it.

**A measured correction to §1 of this document.** The earlier claim that a
single `write` of one line to a handle opened `ab` is atomic is FALSE on
Windows: CPython's `O_APPEND` goes through the CRT, which emulates it by
seeking to the end and then writing. Four threads appending fifty lines each
produced 167 of 200 lines on this bench, silently, with no error raised. Event
appends therefore take a process-local mutex plus a real byte-range lock on a
sibling `.lock` file (`flock` on POSIX, `msvcrt.locking` on Windows). Anything
else in this program that appends to a shared file has the same bug.

### 11.3 `RIGORLOOM_CHILD_PYTHON`

`rt_engine` spawns every engine child under `child_python()`, which is the
environment variable when set and `sys.executable` otherwise. `sys.executable`
is the wrong default for a packaged host: in a frozen executable it IS the
host, so each child re-launches the application — the recursion the desktop
sidecar worked around with an argv convention.

A SET override that names no file is refused at `initialize` with
`child_python_invalid`, because the operator should meet a misconfiguration
there rather than twenty seconds into the first inspect. An unset or blank
value is not an override. `capabilities.childPython` reports the path, the
source (`override` or `sys.executable`) and the variable name.

### 11.4 `workspace/list` — withdrawn, not deferred

The desktop foundation asked whether a Workspace is a runtime object or a
shell-side grouping. It is neither, and §3.1 of this document is where the
confusion started: the "Workspace" described there is the REPORT PIPELINE's
workspace — `PIPELINE.md`, `APPROVALS.md`, `bundle/`, `output/` — which the
Runtime does not manage and has no method for.

What the Runtime has is `--root`: a store, one per connection, holding
sessions, plans, approvals and candidates. `session/list` enumerates it.
A `workspace/list` returning a single row for the root the caller already
passed would be surface without a concept, so it is withdrawn from the method
table rather than left as a GAP implying someone should build it. If a Desktop
Workspace turns out to be a grouping of sessions, that grouping is shell state
and should live in the shell.

### 11.5 Still GAP after Phase 3

`verify/*` as protocol methods (the domain has `RuntimeCore.candidate_verify`
and the CLI exposes it; the wire does not), `artifact/exportTo`,
`provider/configure`, `policy/set`, `workspace/snapshot`, `workspace/restore`,
`workspace/delete`, section and heading structure (desktop gap 6), descendant
containment for child processes, and last-writer-wins on plan and approval
records under one root — the event log is now locked, those records are not.

---

## 12. Page geometry — editing ON the page

The product has to become an editor that works on the rendered page, not beside
it. That needs two things the Runtime did not have: where the text IS, and
which editable address each piece of it corresponds to.

### 12.1 Why a separate method

`document/pageGeometry {sessionId, page?=0, runId?}`, agent-safe, not a field
on `document/render`. Three reasons, recorded because the alternative was
tempting:

- **render is per-zoom, geometry is not.** A raster is bytes at one dpi;
  normalized rects are the same at every dpi. Bundling them would re-extract
  every glyph position each time the user zooms.
- **The frame budget.** `document/render` already caps an inline image at
  512 KiB against a 1 MiB frame. A page of spans on top of that would not fit.
- **They cache differently.** Geometry is cached on the PDF's sha256; a raster
  is not cached at all.

### 12.2 It is the renderer's layout, never ours

Every rect comes from PyMuPDF reading a PDF that Hancom laid out. Nothing is
synthesized from `page_metrics`, and there is no approximate page box. Where
there is no PDF there is no geometry, reported through the SAME closed reason
set `document/render` uses (`needs_conversion`, `no_rasterizable_artifact`,
`rasterizer_missing`, `artifact_missing`) — so the Desktop's existing
unavailable state renders it with no new branch.

**Coordinates: normalized.** Every rect is `[x0, y0, x1, y1]` as fractions of
the page, origin **top-left**, y increasing downward — PyMuPDF's convention and
the one a raster is drawn in, so the client multiplies by its pixel size and is
done. `pageSize` carries the points if anyone wants them back.

**The unit is a line.** PyMuPDF splits a line at every font run, so a label set
in two weights would arrive as two fragments and match neither. Lines are what
a label occupies and what mapping matches on; `spanUnit: "line"` says so.

### 12.3 Address mapping, and what it refuses to do

Span text is matched against the session's form scan — anchor records and table
cells — after normalization by
**`pipeline/scripts/check_residue.normalize_text`**, imported rather than
re-derived. That function is the residue gate's own; a second whitespace rule
here would be a second vocabulary, and the two would drift the first time
either was tuned. A test asserts identity, not equivalence.

| outcome | meaning |
| --- | --- |
| `confidence: "unique"` | exactly one address matched; `address` is set |
| `confidence: "ambiguous"` | several matched; `address` is **null** and `candidates` lists them all |
| `confidence: "unmapped"` | nothing matched; `address` is null and the span still renders as non-editable text |

**Ambiguity is never resolved by picking one.** That is T41 exactly
(`engine/scripts/preedit.py:221`): one unscoped key overwrote five sibling
contracts in a six-contract pack, and every offline gate passed because the
label survived as a prefix. A click on an ambiguous label must ask, not guess.

A cell whose `text_preview` is truncated is **excluded** from the target set and
counted in `mapping.excluded.truncatedCells` — a 30-character prefix is a guess,
not a match.

### 12.4 Empty seats, which are the point

An empty fill seat has no text to match, and it is exactly the thing a user
wants to click. Each seat carries the method its rect was derived by, so the
Desktop can style certainty instead of implying it:

| `derivation` | how |
| --- | --- |
| `matched_text` | the seat already has text, and that text matched a span |
| `cell_borders` | the rules drawn on the page enclose a box alignment tied to this seat |
| `interpolated` | inferred from a uniquely-matched label in the same table row |

Interpolation places **only the seat immediately after a label**. With one
label and seven seats in a row we know where the first one starts and nothing
about the rest, and giving all seven the same rectangle would be six wrong
answers wearing a right one's clothes. The rest are **absent** from `seats`,
and the Desktop edits them in the tree — which is honest, where a guessed box
would put a caret where the text is not.

A drawn rect is only believed when it is neither a hairline nor most of the
page; the page frame is not a cell.

#### `cell_borders`: the grid Hancom actually draws

Text-based derivation placed **0 of 473** editable fill regions across the
whole corpus — 10 forms, 51 pages. An empty cell has no text, so nothing can
match it, and interpolation only ever reached a seat immediately right of a
mapped label in the same table row, which real Hancom layouts do not provide.
`cell_borders` is what makes on-page editing have a target at all.

**Hancom never emits a cell as a rectangle.** Every ruling arrives as a
stroked line segment, so each drawing's `rect` is a hairline and the sanity
floor discarded all of them. The grid is rebuilt from the segments:

1. **Segments → rules.** Axis-parallel segments are clustered on the cross
   axis (a border drawn twice is one border) and joined along it. Length is
   judged on the **joined** rule, never on the pieces: 12,045 of 13,972
   horizontal segments in the corpus are under 3pt with collinear gaps at
   0.4–0.8pt, because they are dashes. A dashed border encloses a cell.
2. **Rules → cells.** A cell is a **minimal** rectangle whose four sides are
   all actually drawn. Minimality is load-bearing: a page carries several
   independent tables, and a plain product of the x and y rule positions lets
   a lower table's vertical slice the upper table's columns into cells nobody
   drew. Each candidate therefore grows to its *nearest* closing partners.
3. **Cells → seats,** by alignment that has to be earned — below.

**Alignment is anchored, walked, and checked at every step.**

An **anchor** is a span that names exactly one table cell *and* whose drawn
cell carries that cell's text. The first half is a weaker reading of the
mapping than `span.address`, and it is deliberate: a form label is routinely
registered twice in the target set, once as an `anchor_record` and once as the
table cell it sits in, so `map_spans` correctly reports `ambiguous`. It is
ambiguous about what to **call** the span, not about where it is. A candidate
list naming one anchor and one cell names one place, so nothing is picked —
**two distinct cells still refuse, T41 untouched.** Across the corpus this is
the difference between 11 anchors and 336. It never writes to `span.address`
or `span.confidence`; the wire contract is unchanged.

From each anchor the drawn grid is **walked outward in all four directions**,
in lockstep with the declared table. Every step must land on an **unambiguous**
drawn neighbour and must **agree with the text the page itself shows** in that
box: a labelled cell must show its label, and an empty fill cell must be empty.
A step that fails is not taken and the walk does not continue through it. An
empty seat is trusted only because the labelled cells walked to reach it were
confirmed by the render.

The first version of this walked one row band, left and right. That reached
the seats *beside* a label and nothing else, and measured against the corpus
**252 fill regions sat in tables that were anchored on the page and still got
no box** — their own row simply held no label. A form's labels are as often a
header *above* a column as a caption beside it, which is why the walk is 2D.

The two axes ask different questions, and the asymmetry comes from how HWPX
declares merges rather than from convenience:

- **Sideways** stays inside one declared row, so the neighbour must share the
  whole row band — top *and* bottom edges. The declared neighbour is the next
  cell in that row's own ordering.
- **Vertically** stays inside one declared column, whose `colspan` may change
  from row to row (a label spanning two columns above a pair of narrow ones),
  so only the **left edge** is shared and the width is free. The declared
  neighbour is `(row + rowspan, col)` — the scan's own statement about itself,
  never a guess from position.

Where a direction **forks** — two drawn boxes both qualify — there is no
neighbour and no step. A fork is exactly where a walk would drift.

Gating the *anchor* on its own cell text is what made this trustworthy: it
removed the last 31 wrong correspondences. An anchor that cannot verify itself
vouches for nothing. Where two anchors reach the same declared cell and
disagree about which box it is, that cell is refused rather than averaged.

**The drift gate.** Every step is checked against the page's text, but two
*empty* cells agree with each other trivially — a run of empty cells is the
one place the text gate says nothing, and walking in 2D makes those runs
longer. Reach is therefore paid for with a structural check the whole table
must pass on that page. The correspondence has to be an **order-preserving
injection**:

- no drawn box is claimed by two declared cells (which is what a walk that
  slipped a row or a column produces), and
- declared cells left to right in a row take drawn boxes left to right, and
  declared cells top to bottom in a column take drawn boxes top to bottom.

A table failing either has **every** seat refused on that page
(`lattice_inconsistent`), not just the suspect ones: the evidence that an
alignment is sound is the alignment being sound as a whole. On the corpus the
gate fires nowhere, which is the result it should have where the audit below
passes — it is a guard against the form this corpus does not contain, and it
costs 0 of the 229.

**Measured result: 229 of 473 seats, all `cell_borders`.** Per form:

| form | pages | fill regions | seats | `cell_borders` |
| --- | ---: | ---: | ---: | ---: |
| admrul-gajokdolbom-hyuga-sinchengseo | 1 | 7 | 6 | 6 |
| gianmun-byeolji-1ho | 1 | 9 | 0 | 0 |
| gianmun-byeolji-2ho | 1 | 35 | 13 | 13 |
| jeongbo-gonggae-cheongguseo | 1 | 13 | 0 | 0 |
| jumin-deungchobon-sinchengseo | 3 | 5 | 1 | 1 |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | 22 | 125 | 123 | 123 |
| moel-pyojun-geunrogyeyakseo-2013 | 7 | 3 | 0 | 0 |
| moel-pyojun-geunrogyeyakseo-2025 | 7 | 0 | 0 | 0 |
| nrf-gyeolgwa-bogoseo-yangsik | 2 | 5 | 5 | 5 |
| saeopja-deungnok-sinchengseo | 6 | 271 | 81 | 81 |
| **total** | **51** | **473** | **229** | **229** |

`matched_text` and `interpolated` place **0** across the corpus, and that is
asserted rather than assumed: an empty fill cell never holds text for the
first to match, and no corpus row puts a mapped label immediately beside a
seat for the second.

Audited on those same renders: every placed seat **is** one of the
reconstructed cells, every one of them is empty in the render, and no two
overlap. The ground truth is real Hancom output — `com_backend.py` driving
Hancom Office 13.0.0.2986, `docs/research/xc1-conversion-bench.md` §4. Where
those renders are absent the corpus tests **skip with a named reason** rather
than validating a border-finder against a fixture this repo drew itself.

#### Why a seat is absent, per page

`seatAbsences` counts a closed reason set, so the Desktop can say why a seat
has no box instead of implying one:

| reason | meaning |
| --- | --- |
| `no_drawn_grid` | the page draws no closed cell at all |
| `no_anchor_on_page` | nothing of this table was identified here (it may be on another page) |
| `no_anchor_in_row` | the table is anchored on this page, but the walk never reached this cell |
| `grid_gap` | no unambiguous drawn cell adjacent where the next declared cell should be |
| `cell_mismatch` | the drawn cell there carries text contradicting the declared cell |
| `alignment_failed` | two anchors disagree, or an anchor failed its own text check |
| `lattice_inconsistent` | the table's correspondence is not an order-preserving injection, so all of it is refused here |

`no_anchor_in_row` keeps its name from the one-dimensional walk and is now
read as *the walk never reached this cell*; renaming a value the Desktop
already switches on buys nothing this document cannot say instead.

`drawnCells` reports how many closed cells the page yielded, which separates
"this form is not ruled" from "this form is ruled and we could not align it".

### 12.5 Cache

Keyed on `(pdf sha256, page)`, held per `RuntimeCore`, bounded at 64 entries
with FIFO eviction. The answer reports `cache.hit` and `cache.key`. New PDF
bytes are a new key, so a re-prepared document never serves stale positions.

### 12.6 Still GAP here

`cell_borders` closed the "seats not adjacent to a label" gap and then the
"label is a header, not a caption" gap, both validated against real Hancom
renders. **244 of 473 fill regions still get no seat**, and the reasons are
structural, not tuning:

- **148 fill regions sit in tables with no anchor anywhere**, 138 of them in
  the two 부표 sheets of `saeopja-deungnok-sinchengseo`. The cause measured
  there is not a label one table over: each sheet is **the same sub-block
  repeated five times down one table**, so every label in it matches five
  distinct declared cells and refuses to anchor — T41, working as designed.
  Pairing the five drawn copies with the five declared copies in reading order
  is an assumption about ordering that no text on the page can confirm, so it
  is not made. This is the largest single block and it is where the next real
  gain would have to come from.

  **Anchoring such a table from a neighbouring one was measured too, at 1 of
  473.** Borrowing an adjacent table's grid needs an anchored table on the
  same page, and there are four anchorless tables holding fills:

  | form | table | fills | renders on | anchored tables there |
  | --- | ---: | ---: | ---: | --- |
  | admrul-gajokdolbom-hyuga-sinchengseo | 0 | 1 | page 0 | table 1 |
  | gianmun-byeolji-1ho | 0 | 9 | page 0 | none |
  | saeopja-deungnok-sinchengseo | 5 | 64 | pages 4–5 | none |
  | saeopja-deungnok-sinchengseo | 6 | 74 | pages 4–5 | none |

  147 of the 148 have nothing on their page to borrow from, so no cross-table
  method reaches them; the 148th is one seat, which does not pay for a
  cross-table geometry mechanism and the verification gate it would need. A
  table is located here by its declared cell texts appearing as rendered
  lines — ambiguous texts still locate a *page*, because that does not require
  deciding *which* cell. Pinned by a test.
- **Truncated previews cannot anchor, and untruncating them buys nothing.** A
  cell whose `text_preview` is a 30-character prefix is excluded from the
  target set; the prefix can still *refute* a correspondence during the walk,
  and it does, but it cannot establish one. Whether the truncation was the
  blocker is now measured rather than supposed. `form_inspect --full-text`
  already returns a named cell's exact string, so all **145** truncated cells
  in the corpus were fetched in full and spliced into the target set:

  | | |
  | --- | ---: |
  | truncated cells recovered in full | 145 |
  | equal to exactly one rendered line | 34 |
  | wrapping over several rendered lines (mean 135 chars) | 111 |
  | anchors gained / lost | 8 / 0 |
  | **extra seats placed** | **0** |

  The span unit is a **line**, so a cell that wraps can never match one at any
  preview length, and the 34 that do match land where the walk already
  reaches. Carrying full cell text as a new profile field would therefore buy
  zero seats at the cost of the structure-only contract `form_inspect` keeps
  on purpose (`_full_text`'s own docstring: the profile does not carry body
  text, and the escape hatch is opt-in and cell-scoped). Not done.
- **Forms the renderer does not enclose place nothing, correctly** — and the
  two of them fail in different ways, which the earlier reading of this list
  ran together. `gianmun-byeolji-1ho` is barely ruled *at all*: 6 horizontal
  rules and 4 verticals on the whole page, and its fields (수신 / 참조 / 제목 /
  기안자 …) carry none, so there is nothing under them either.
  `jeongbo-gonggae-cheongguseo` is genuinely ruled — 26 horizontal rules and 9
  verticals — but the outer frame is stroked only across the header and footer
  bands, so its body cells are **three-sided**: top, bottom and left drawn,
  right absent. Three sides is not an enclosure and does not become one.
- **`underline_rule` as a separate derivation class: measured at zero, not
  built.** The shape it was to be defined for is `라벨 ______` — a rule with
  no enclosing box, on a uniquely-anchorable label's own line band, starting
  after it. Across the 10 renders there are 1,141 joined horizontal rules,
  **549** of them not an edge of any closed cell, and **exactly one** has that
  shape; that one's label is followed by a `static` cell, not a fill target.
  The class would place **0 seats** and would exist only to fire on the other
  548, which are section separators and row borders running the full text
  width — precisely the boxes-in-the-wrong-place this section refuses. The
  census is pinned by a test so the number cannot rot.
- **The walk does not cross a gap or a fork.** A direction with no
  unambiguous adjacent box is not stepped, so an unruled middle stretch or a
  place where the drawn grid branches bounds the region the walk verifies.
  Propagating a constant row offset down the table was tried and measured: it
  added 4 seats and could not be checked as tightly, so it is not in.
- **Alignment is per page.** A table continued onto another page is anchored
  again there or not at all; `no_anchor_on_page` covers both that and a table
  simply living elsewhere, and does not distinguish them.
- **Sub-line addressing.** A span is a line; a click resolves to the line's
  address, not to a character offset within it.
- **Multi-page seats.** Geometry is per page; a seat is looked up on the page
  it is asked for.

**Not proven:** whether a *filled* document (rather than a blank form) still
aligns — every corpus render is a blank form, and a filled cell changes what
`cell_agrees` sees. Whether the tolerances hold for renderers other than
Hancom Office 13.0.0.2986; there is one Hancom install on the measuring
machine, so renderer-version sensitivity is untested.

---

## 13. Distribution-module checkers on the wire (gap 17)

Six distribution modules declare eighteen checkers on disk. The Runtime knew
about none of them: there was no method that named a module contribution, so
the Desktop's 작업 팩 panel was a declaration viewer with a 준비 중 label and
the whole report-pipeline product sat behind one missing wire
(`desktop/README.md` runtime gap 17). Two methods close it.

```
module/list  {}                                                    -> the installation
module/check {sessionId, module, checkers?, runId?, timeoutSeconds?} -> a report
```

### 13.1 Both are agent-safe, and why that was the harder answer

Host-only was the safe default and would have been wrong. The argument, in the
order it was actually checked:

1. **The checker contract is a verdict producer.** One JSON object on stdout,
   exit in {0, 2, 3} (`pipeline/scripts/checker_base.py:13-16`). Measured
   across all eighteen declared checkers rather than assumed: the only write
   path any of them has is `--out`, and this caller never passes it.
2. **The subject is a copy anyway.** Every call materialises the document into
   `<session>/checks/<callId>/subject/`, runs the child with that directory as
   its cwd, and deletes the directory in a `finally`. The session copy, the
   published candidate and the operator's original are unreachable *by
   construction*, which is what turns "read-only" from a hope into a property.
   A future module whose checker does write is contained to scratch.
3. **It decides nothing.** No candidate, no plan state, no approval. One
   `module.checked` event, exactly as agent-safe `plan/propose` appends
   `plan.proposed`.
4. **Spawning a repo script on an agent call is already the norm.**
   `document/inspect` runs `form_inspect`. What is new is that the script is
   module *payload* — and the authority for that is **enablement**, an
   install-time operator act recorded in `modules/enabled.yaml` that no wire
   call can change. A module nobody enabled cannot be run by anybody, and
   `module/check` on one is `capability_unavailable` naming what is enabled.

The value is on the same side: the point of an agent proposing an edit is that
it can check its own work before asking a human to approve it. A host-only
checker would put the only quality signal on the far side of the gate it is
supposed to inform.

**Residual, not glossed.** A child is bounded (wall clock, captured output,
environment allowlist) and killed on timeout; it is not *contained* — no
process group, no Windows Job, the same gap `rt_engine` records and
`capabilities.unavailable.descendantContainment` reports. A checker that writes
to an absolute path outside its cwd is not stopped by anything here. It is only
kept away from the session's own bytes.

### 13.2 What may be run: a declaration, never an inference

A session holds a **document**; half the shipped checkers take a report
**workspace** directory. Core may not tell them apart by name — rule 1 of
`modules/README.md` — and inferring it from a checker's argparse would be a
second reader of a contract that already has one. So the declaration carries
it: `provides.checkers[].subject` is `document` or `workspace`, and
`enabled_checkers()` reports `None` when a module has not said.

| `subject` | `module/check` |
| --- | --- |
| `document` | runs it: `python <script> <scratch copy> [--baseline <copy>]` |
| `workspace` | `skipped`, reason `needs_workspace` |
| absent | `skipped`, reason `subject_undeclared` |

Guessing was the alternative and it is worse than either skip: handing an
`.hwpx` path to a workspace checker yields a verdict about an empty directory
that reads exactly like a finding about the user's document.

### 13.3 Baseline, supplied where it is true and only there

A checker declaring `wants: [baseline]` is comparing the artifact against the
blank form it came from. With `runId`, that form is the **session source** by
construction — `rt_apply` reads it and writes the candidate — so the Runtime
supplies it as `--baseline` and the row is complete.

Without `runId` the subject *is* the source, and a document is never its own
baseline. The checker still runs, and the row says so: `wantsUnsatisfied:
["baseline"]`, `partial: true`, and `acceptance` is false. This diverges from
the evals harness, which skips such a check outright (`evals/cleanroom.py`),
and the reason for the divergence is the difference in what the two return: the
harness sees an exit code, where a thin verdict really is a silent pass, while
this returns the checker's own rules including its `skipped` rows, where the
thinness is the most visible thing in the answer. Refusing to run would leave
the Desktop with nothing to show for a document that has no candidate yet,
which is every document at the moment a person opens one.

### 13.4 The result: VerificationReport-shaped, and never a fabricated pass

`checks[]` carries one row per selected checker with `state` in
`ran` / `skipped` / `unavailable` (`rt_codes.CHECK_STATES`), a `reason` from a
closed set when it is not `ran`, and for a run: `ok`, `verdict`, the checker's
own `counts`, and `findings[]` normalized to `{severity, code, message,
location, address}`. `severity` is `hard`, `warn`, or `skipped` — a rule the
checker itself could not decide is kept as a finding, because "this rule did
not decide" is the fact a reader needs most and the one a bare pass hides.
`address` is the finding's place translated into the Runtime's own addressing
(`{table,row,col}` or `{atPara}`) when a translation exists, and `null` when it
does not: never a half-address that would select the wrong cell.

| not-`ran` reason | meaning |
| --- | --- |
| `subject_undeclared` | the declaration does not say what its input is |
| `needs_workspace` | it takes a report workspace; a session is a document |
| `spawn_failed` | the interpreter or the script would not start |
| `timed_out` | exceeded its bound and was killed |
| `missing_dependency` | the child died on an import this machine lacks |
| `usage_error` | exit 2 — we called the checker wrongly |
| `no_verdict` | exited, but printed nothing this is willing to read as one |

`acceptance` is true only when every selected checker **ran**, reported clean,
**and** had every input it declares it needs — `visual_verify`'s rule
(`pipeline/scripts/visual_verify.py:42-47`) applied one level up, the same way
`rt_apply.verification_report` applies it to the offline gate. `ranAll` is the
separate fact, so a caller can tell "nothing ran" from "something failed".

### 13.5 Bounds

`timeoutSeconds` bounds **each** checker (default 120s = `CHILD_TIMEOUT_SECONDS`,
clamped to [1, 600]); a hung checker is killed and reported `timed_out` while
the rest of the pack still runs. A call may select at most 64 checkers and a
row carries at most 200 findings per severity, with the overflow counted rather
than dropped silently. `bounds.worstCaseSeconds` publishes the composite so a
caller never has to multiply for itself.

### 13.6 Where modules are read from

`RIGORLOOM_MODULES_ROOT` overrides the modules directory (precedent:
`pipeline/scripts/personalization_ctl.py:128`) and `RIGORLOOM_MODULES_ENABLED`
overrides the enablement file — a packaged host installs modules beside the
application rather than inside a checkout, and a test needs an enablement that
is not the operator's own. Both default to this checkout.
`capabilities.modules` reports which was used, and reports a malformed
`module.yaml` as a *reason* rather than raising: one broken declaration in
someone's install must not make the connection unopenable.

`module/list` returns script paths **relative to the modules root**. An
absolute path is the operator's directory layout, and there is no reason for it
to cross a wire an agent reads.

### 13.7 Still GAP here

- **Workspace checkers have no session.** Twelve of the eighteen are skipped by
  construction, because the Runtime has no workspace concept at all. The honest
  fix is a workspace session kind, not a directory guessed from a document.
- **`--pack`, `--vocabulary`, `--mode`.** Every checker gets its own defaults;
  the Runtime passes none of them. A pack instance is operator state
  (`personalization_ctl`) and there is no wire surface for it (`policy/set` is
  still GAP), so passing one would mean inventing that surface here.
- **Containment.** As above: bounded, killed, not contained.

---

## 14. The typeface name (gap 16)

`document/inspect` reported a seat's shape as a charPr **ID** and reported a
height only for the two document-level shapes. No name for the face was on the
wire anywhere, so the Desktop editor toolbar showed an integer where a 글꼴
control belongs and could not become a real one even read-only: a dropdown
reading 맑은 고딕 because that is what toolbars usually say would be a
fabrication in the one place this application must not fabricate.

The header already carried both halves. `charPr/fontRef` names a font id per
language; the `fontface` tables name the face for that id. Nothing joined them
except `form_inspect --baseline`, whose answer is a document-wide **set** of
font names and therefore can never say what *this* run is set in.

`form_inspect` now publishes the join as `charpr_faces` — `charPr id -> {lang:
face}` — and three fields carry it:

| field | on |
| --- | --- |
| `summary.baselineCharPr.face`, `summary.blackCharPr.face` | the document-level shapes |
| `regions[].charPrFace` | the shape a fill seat inherits |
| `regions[].charPrSuggestedFace` | the shape the T30 preflight suggests instead |

**Per language, because the document is.** Hangul's own font dialog has
separate 한글 and 영문 faces and a 기안문 declares different ones — the corpus
form sets `hangul` to 한양중고딕 and `other` to 한양신명조. Collapsing them to
one name would be a guess about which of two declared truths the reader meant.
A language whose id resolves to no face is **absent** from the map: the header
did not say.

**Two absences, kept apart.** A `face` of `null` means *this document declares
no resolvable face for that charPr id*. `summary.typefaces.state` is the other
fact: `read` when the profile carries a mapping at all, `unavailable` with a
reason when it does not — a profile written by an older scan, for instance.
One null cannot carry both, and a UI that conflated them would tell a user
their document names no fonts when the truth is that nothing looked.

Nothing is inferred and nothing is defaulted; a test reads the corpus form's
own `header.xml` and asserts every name that reaches the wire appears in it.

The field is not decoration. On the corpus 기안문 a fill seat inherits charPr
11 (돋움체) while the preflight suggests charPr 23 (한양중고딕) — before this
the two were two integers, and no caller could see that filling the seat as-is
would print in something other than the body face.

### 14.1 Still GAP here

- **Size and weight are still partial.** A height is reported for the two
  document-level shapes only; a seat's charPr carries an id and now a name, but
  no point size of its own.
- **No writing.** This is a read. Setting a face means a charPr the document
  does not have, which is a `preedit` question, not a protocol one.

---

## 15. The Agent Host session boundary (E4.3)

The Agent Host is not a Runtime entry and its methods are not Runtime methods —
`rt_core.METHODS` does not, and must not, contain any of them. Its own wire
contract lives in **`docs/agenthost-session-protocol-v0.md`**: streamed chunk
events, the long-lived JSONL host, reattach semantics, and the
operator-granted document-context events.

Three facts belong in *this* document, because they touch the Runtime:

- **`document/readRegion` stays agent-safe, unchanged.** The Agent Host's
  `--read-scope granted` narrows what the AGENT may reach *at the Agent Host's
  own compile gate*; the Runtime still serves any address to an agent
  connection. A reader of §4 must not conclude that a grant mechanism exists
  down here. It does not, and the Agent Host says so in its own doc.
- **`rt_session.append_line`** is now the named primitive behind every
  append-only JSONL log in the repository, the Agent Host's turn log included;
  `append_event` is one caller of it. The Windows non-atomic-append defence
  (`_append_lock`, §the measured 167-of-200 bench) therefore has exactly one
  implementation rather than one per log.
- **The Agent Host's session state lives outside the session store**, at
  `<root>/agenthost/<sessionId>/`. `<root>/sessions/` remains the Runtime's
  alone, so neither side can corrupt the other's idea of what a directory
  contains.
