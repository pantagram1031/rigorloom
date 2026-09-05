# Desktop architecture — design draft

Status: design input for Phase 1. Nothing here is implemented. Companion to
`docs/runtime-protocol-v0.md`, which defines the wire contract; this document
defines the processes that speak it, the boundaries between them, and who owns
recovery when one dies. Every claim about existing behaviour carries a
file:line or a test file name from this checkout.

---

## 1. Process model

Four process roles. Only the first two are long-lived.

```
  ┌──────────────────────┐
  │ Desktop shell        │  UI, file dialogs, approvals surface.
  │ (host authority)     │  Owns the user's consent.
  └──────────┬───────────┘
             │ JSONL over stdio  (Runtime Protocol v0)
  ┌──────────▼───────────┐
  │ Runtime sidecar      │  One process. Owns the workspace, the plan
  │ (protocol + policy)  │  registry, receipts, path containment.
  └───┬──────────────┬───┘
      │ spawn        │ spawn
  ┌───▼────────┐ ┌───▼───────────────┐
  │ Parser     │ │ Renderer worker   │
  │ worker     │ │ (COM / rhwp /     │
  │ (offline)  │ │  LibreOffice)     │
  └────────────┘ └───────────────────┘
```

An **Agent Host** (or the CLI, or an MCP server) is a fifth participant. It
connects to the Runtime the same way the Desktop shell does, but on an
*agent-authority* connection (`docs/runtime-protocol-v0.md` §4). It is not a
child of the Runtime.

### 1.1 Desktop shell

Owns: window, file pickers, the approvals UI, provider configuration UI. Holds
host authority because it is the only process the user is actually looking at.

It must not read or write documents directly. The one existing precedent for a
UI that operates the pipeline is Studio, and Studio already routes every
mutating action through a subprocess call to a repository script rather than
doing the work in-process (`studio/main.py:73`, `_ACTION_KINDS` =
`check-gate, approve-human-gate, run-checker, build-bundle, build-hwpx`).

### 1.2 Runtime sidecar

One process per Desktop session. Speaks the protocol on stdio, owns:

- workspace resolution and containment (§3.1);
- the plan registry and exact-byte bindings;
- receipt writing (`engine/scripts/document_evidence.py:1998`);
- spawning and bounding every worker;
- the machine-wide COM serialization decision (§3.2).

It holds **no** document state between requests. Every engine script in this
tree is a one-shot process that reads a file and writes a file; the Runtime
adds a protocol, not a document server.

GAP: no such process exists. Build note: a new top-level package (sibling of
`engine/` and `pipeline/`), stdlib-only for the framing layer so it inherits
the core-install-has-no-dependencies property that
`pipeline/scripts/module_registry.py:30` already states.

### 1.3 Parser worker (offline, no Hancom)

Short-lived subprocess per request. This is where the existing offline
entrypoints run:

| Job | Script |
| --- | --- |
| profile / graph / regions | `engine/scripts/form_inspect.py:1530` |
| typed offline edits | `engine/scripts/preedit.py:2417` |
| structured build ops | `engine/scripts/xml_backend.py:1116` |
| ingress validation of untrusted bytes | `pipeline/scripts/hwp_ingress.py:1` |
| residue / expected-text gate | `pipeline/scripts/check_residue.py:770` |

These are safe to run concurrently with each other: they take no global lock,
they never launch Hancom, and each writes to its own `--out`.

### 1.4 Renderer worker (Hancom / rhwp / LibreOffice)

Short-lived, **serialized machine-wide**, and the only role that may touch
COM. Existing entrypoints:

| Job | Script |
| --- | --- |
| COM edit batch / convert | `engine/scripts/com_backend.py:1723` / `:1751` |
| capability probe (never launches Hancom) | `pipeline/scripts/render_probe.py:4` |
| quarantined rhwp candidate render | `pipeline/scripts/renderer_runtime_v2.py:1` |
| render-and-judge loop, deterministic half | `pipeline/scripts/visual_verify.py:2980` |

`visual_verify` already states the rule the Runtime must inherit: an
`.hwpx`/`.hwp` artifact with no `--pdf` is converted through **one serial**
`com_backend.py convert` subprocess, and never with `--kill-stale` — "killing a
live Hancom belongs to an operator, not to a verification loop"
(`pipeline/scripts/visual_verify.py:57-63`, implementation at `:397`).

---

## 2. Trust boundaries

Five boundaries. Each is a place where data crosses from a less-trusted
producer to a more-trusted consumer, and each needs an explicit check.

### B1 — Agent Host → Runtime

The strongest boundary. An agent connection may inspect, propose and validate;
it may not open arbitrary paths, resolve approvals, export outside the
workspace, configure providers, change policy, or delete a workspace
(`docs/runtime-protocol-v0.md` §4).

Authority is a property of how the connection was created, never a field in a
payload. The existing analogue is Studio's action gate: actions are off unless
`STUDIO_ALLOW_ACTIONS=1` was set in the environment that launched the server
(`studio/main.py:86`), and the per-request check is a token plus a Host-header
check, not a claim in the body (`studio/main.py:993`, `_require_action_auth`).

### B2 — Desktop shell → Runtime

Host authority, but not unlimited trust: the shell is still a separate process
whose input must be validated. Everything §4 lists as host-only still goes
through the same validation as an agent request — the difference is
permission, not parsing. Unknown methods and unknown operation kinds are
refused for the host too
(`engine/scripts/com_backend.py:1689`, `engine/scripts/xml_backend.py:27`).

### B3 — Runtime → worker subprocess

The Runtime is the parent; the worker is untrusted output. Existing
enforcement, all reusable:

- Bounded, contained child execution: `pipeline/scripts/diagnostic_candidate_core.py:1128`
  (`run_child_capture`) — POSIX `start_new_session` + process group, Windows
  Job object with kill-on-close, stdin `DEVNULL`, stdout/stderr drained into
  size-bounded hashes.
- The containment limitation is stated, not hidden: a descendant that creates
  its own session is *not* proven contained
  (`pipeline/scripts/diagnostic_candidate_core.py:1136`), and the receipt
  records `DESCENDANT_CONTAINMENT = "not_established"`
  (`pipeline/scripts/renderer_runtime_v2.py:56`).
- Environment is an allowlist, not inheritance:
  `pipeline/scripts/renderer_runtime_v2.py:47` (`ENV_POLICY =
  "minimal_allowlist_v1"`), cwd is a private stage (`:58`).
- Adapter stdout is parsed with a hardened decoder:
  `pipeline/scripts/doc_backend.py:105` (`_ADAPTER_JSON_DECODER`, non-finite
  constants rejected) and `:108` (`_parse_adapter_stdout`).
- Timeouts are bounded and the bounds are *measured*, not guessed —
  `tests/test_subprocess_bounds.py:1` documents the measurement (loaded median
  9.00s, worst observed 36.46s) and pins a floor so the next sub-median bound
  has to announce itself.

### B4 — Untrusted document bytes → engine

Any file the user opens or an agent imports is hostile until proven otherwise.

- Every input dimension is bounded before parsing:
  `pipeline/scripts/hwp_ingress.py:40-46` (`MAX_INPUT_BYTES`,
  `MAX_HWPX_MEMBERS`, `MAX_HWPX_ARCHIVE_BYTES`, `MAX_HWPX_MEMBER_BYTES`,
  `MAX_HWPX_TOTAL_UNCOMPRESSED`, `MAX_HWPX_COMPRESSION_RATIO`) — that last one
  is the zip-bomb guard.
- HWP5 is walked structurally through FAT/mini-FAT/directory, never by
  byte-scanning for a signature (`pipeline/scripts/hwp_ingress.py:3-6`).
- The public JSON surface of ingress carries no paths, document text, stream
  names, or command output (`pipeline/scripts/hwp_ingress.py:7-9`). The same
  discipline exists for COM inspect: `--privacy-safe`
  (`engine/scripts/com_backend.py:1719`) and a two-token refusal vocabulary
  whose ordering is load-bearing (`engine/scripts/com_backend.py:1783` —
  input shape decided before host capability, so one input never gets two
  answers).
- Structural validity precedes text scanning: `check_residue` XML-parses every
  `Contents/section*.xml` and `header.xml` **before** any residue scan, because
  a malformed section renders blank in Hancom and scanning its bytes would
  certify an unopenable document (`pipeline/scripts/check_residue.py:34-41`,
  member set at `:83`).
- Snapshot restore refuses zip-slip, symlink members and symlink parents
  member-by-member (`pipeline/scripts/ws_snapshot.py:6`, `:238`, `:254`).

### B5 — Runtime → published artifact

Publication is the point where a claim becomes evidence. It is the
best-defended boundary in the tree and needs no redesign:

- Atomic publication with an fd-bound destination directory:
  `engine/scripts/document_evidence.py:1573`
  (`_DestinationDirectoryBinding`), `os.fsync` at `:1737`, `os.replace` with
  `src_dir_fd` at `:1766`, entry point `write_receipt` at `:1998`.
- Hash-and-identity rebinding after the write, so the receipt describes the
  bytes that are actually on disk (`engine/scripts/document_evidence.py:2004`).
- Candidate publication is owner-token-based with rollback:
  `publish_owner_token_pair`, `publish_owner_token_receipt`,
  `rollback_publication` (`pipeline/scripts/diagnostic_candidate_core.py:26`),
  and a duplicate run id is `run_exists` (`:758`) rather than an overwrite.
- Capability is never proof: `derive_proof_grade`
  (`engine/scripts/document_evidence.py:780`) takes no probe input and fails
  closed to `none`.

---

## 3. Where the existing rules live

### 3.1 Path containment

Two independent implementations exist, for two different threat models. The
Runtime should use both, not merge them.

**Workspace-relative receipt paths — `engine/scripts/document_evidence.py`**

| Check | Line |
| --- | --- |
| relative, traversal-free, resolves inside the workspace | `:558` (`_safe_relative_path`), refusals at `:589`, `:594`, `:603` |
| bound artifact exists and is not a symlink | `:606` |
| every existing parent is a real directory, no symlink/reparse component | `:611` (`_check_directory_chain`), refusals at `:639`, `:646` |
| reparse-point detection (Windows) | `:176` (`_is_reparse`) |
| no-follow open of a single-link regular file | `:264` (`_open_regular`) |
| second custody binding via the kernel-resolved path of an open fd | `:209` (`_opened_real_path`) — this is the interior-parent race defence: a parent swapped to a symlink after the lexical walk and restored before the next capture |
| Windows 8.3-vs-long-name aliasing handled without resolving away an interior junction | `:558`–`:592` |

**Generic quarantine primitives — `pipeline/scripts/diagnostic_candidate_core.py`**

`DirectoryBinding` (`:51`) holds a directory identity: POSIX
`O_DIRECTORY|O_NOFOLLOW` + `dir_fd` operations; Windows a backup-semantics
handle with delete sharing disabled, plus a final identity check on return
(`:56`). Every operation through it re-verifies identity and refuses with
`directory_binding_changed` (`:226`).

**UI-level containment — `studio/main.py:100`** (`safe_workspace`): slug regex
then a resolved-parent check. Narrower than the two above and appropriate for
its layer; the Runtime should lift this into a shared module rather than
duplicating it a third time (GAP; see `docs/runtime-protocol-v0.md` §6,
`workspace/list`).

### 3.2 COM serialization

Three mechanisms exist, at three scopes. They do not currently know about each
other, and the Runtime is the first component in a position to unify them.

| Scope | Mechanism | Location |
| --- | --- | --- |
| Machine-wide, crash-safe | Windows named mutex `Local\Rigorloom-HwpIngress-T85`, auto-released on process death | `pipeline/scripts/hwp_ingress.py:1186` (`_com_serial_guard`); refusals `hancom_mutex_unavailable` (`:1221`), `hancom_mutex_busy` (`:1225`) |
| Machine-wide, advisory | `HwpInstanceLock` — a `%TEMP%` JSON lock whose purpose is to make `--kill-stale` refuse when a *live* other session holds it | `engine/scripts/guards.py:231`, decision at `:270` (`can_kill_stale`) |
| Per-call discipline | one serial `com_backend convert`, never `--kill-stale` | `pipeline/scripts/visual_verify.py:397` |

Two things the Runtime must respect:

1. `HwpInstanceLock` is deliberately **not yet wired** into
   `com_backend --kill-stale` (`engine/scripts/guards.py:245-246`: "아직
   com_backend --kill-stale에는 배선하지 않는다"). It is a primitive with
   regression tests, not an active guard. GAP. Build note: the Runtime is the
   right place to wire it, because it is the first component that knows
   whether *it* started the Hancom instance.
2. Windows' `os.kill(pid, 0)` is destructive and is never used;
   liveness goes through `OpenProcess` + `GetExitCodeProcess`
   (`engine/scripts/guards.py:189-228`). Any Runtime liveness check must reuse
   `guards._pid_alive`, not reimplement it.

The failure this prevents is recorded: two concurrent sessions each running
`taskkill /F /IM Hwp.exe` killed each other's in-progress instance, producing
four consecutive RPC crashes (`engine/scripts/guards.py:234-240`, T21).

### 3.3 Privacy

`pipeline/scripts/privacy_scan.py:1` is the gate: binary office documents,
denylisted strings, Windows user-profile paths, and email addresses are HARD.
Two properties matter for the Runtime:

- A gate may not claim more than it checked: an unreadable path is an
  `unreadable_file` HARD finding, never a silent skip, and the summary carries
  `summary.incomplete` (`pipeline/scripts/privacy_scan.py:16-25`).
- It runs over every distribution bundle before the bundle is written
  (`scripts/package_module.py:457`, `_run_privacy_gate`; contract stated at
  `scripts/package_module.py:25-28`).

Runtime consequence: log lines, error payloads and event frames are
distribution-adjacent. The refusal vocabulary already models this — COM
privacy-safe inspect never echoes the source path
(`engine/scripts/com_backend.py:1794`), equation preflight failures never echo
the LaTeX (`engine/scripts/com_backend.py:1699`), and node identity is never
serialized into a receipt (`engine/scripts/document_evidence.py:182`).

---

## 4. Crash and recovery

Responsibility is split by who owns the durable state.

| Failure | Who notices | Recovery |
| --- | --- | --- |
| Worker subprocess crashes or hangs | Runtime | Bounded child returns a failure tuple rather than raising (`pipeline/scripts/diagnostic_candidate_core.py:1145`, `failed_result`); Job/process-group teardown kills descendants (`:1167`). The plan is marked failed; nothing is published. |
| Worker leaves a partial output | Runtime | Never possible for the offline path by construction: `preedit` parses every modified XML member before writing the output zip and writes nothing on failure (`engine/scripts/preedit.py:26-31`); `xml_backend` requires `--save-as` to differ from `--file` (`:1126`); `com_backend` validates the whole op batch before Hancom starts (`:1670`). |
| Candidate publication interrupted | Runtime | `rollback_publication` / `remove_owned` / `remove_owned_dir` (`pipeline/scripts/diagnostic_candidate_core.py:26`); a duplicate run id refuses with `run_exists` (`:758`). |
| Receipt write interrupted | Runtime | The temporary name is consumed atomically and is not touched afterwards (`engine/scripts/document_evidence.py:2037`); a receipt that does not validate against current bytes is not a receipt (`:1356`). |
| Desktop export interrupted | Desktop shell | Private-preview policy is new-name-only. Artifact and receipt are staged and verified, then published separately with no-replace links, artifact first and receipt last. This is not a two-file atomic transaction: a hard stop may leave a new orphan artifact, but no path that existed before export is overwritten or deleted. The hidden staging directory is retained on success too as a hard-link custody record (no duplicate content bytes); automatic deletion remains GAP until cleanup can bind directory/file identity. |
| Runtime crashes mid-plan | Desktop shell | GAP — nothing records "a plan was in flight". Build note: write a RecoveryManifest before the first mutation, remove it after the last; on next start, offer `ws_snapshot restore` and never auto-restore. |
| Hancom left running after a crash | Operator, today | `HwpInstanceLock` exists but is unwired (§3.2). The Windows named mutex *is* crash-safe and needs no cleanup (`pipeline/scripts/hwp_ingress.py:1188-1191`). |
| Desktop shell crashes | Runtime | EOF on stdin ⇒ finish or terminate the in-flight step, kill owned children, exit 0. GAP: no implementation. |
| Workspace corrupted by an operator | Operator | `pipeline/scripts/ws_snapshot.py:1` — snapshots cover `bundle/`, `output/`, `PIPELINE.md`, `.pipeline/` (`:29`) with a required `.sha256` sidecar; `restore` at `:477`. |
| Skill install drifts / a sync is interrupted | `sync_local` | Atomic swap via rename with a tested rollback (`scripts/sync_local.py:991`, `_atomic_install`; `:1028`, `apply_plan`); a sibling lock survives the swap (`:54`), stale after 30 min (`:58`); hand-edited install files are refused, not overwritten (`scripts/sync_local.py:15-20`). |

Two recovery *non*-responsibilities, stated so they do not drift into the
Runtime:

- The Runtime never resolves an approval on recovery. A human gate is resolved
  only by a matching line in `APPROVALS.md`
  (`modules/report/scripts/pipeline_ctl.py:1112-1159`), and a script gate only
  by `check`, never by `gate` (`:1066`).
- The Runtime never promotes a candidate to proof after a crash.
  `derive_proof_grade` fails closed on any non-success terminal state
  (`engine/scripts/document_evidence.py:786`).

---

## 5. Which existing tests pin each boundary

Cited by test file; each already exists in this checkout.

| Boundary / rule | Pinned by |
| --- | --- |
| Bounded child, evidence is hash-and-count only, grandchild cleanup, POSIX group has no live escape | `pipeline/tests/test_diagnostic_candidate_core.py` |
| Quarantined renderer lane: staged adapter, owned publication, no promotion | `pipeline/tests/test_renderer_runtime_v2.py`, `tests/test_renderer_runtime_v2_docs.py` |
| Ingress bounds, HWP5 structural walk, privacy-safe JSON surface | `pipeline/tests/test_hwp_ingress.py`, `tests/test_hwp_ingress_docs.py` |
| Receipt custody: path escape, symlink/reparse parents, duplicate keys, non-finite values, atomic publication | `engine/tests/test_document_evidence.py`, `pipeline/tests/test_document_evidence_preflight.py`, `tests/test_document_evidence_docs.py` |
| Render-certificate custody and reproduction | `pipeline/tests/test_render_cert_custody_reproduction.py`, `pipeline/tests/test_render_cert_envelope_v2.py` |
| Strict-JSON boundary (T155/T156) stays duplicate-key + finite-JSON only | `tests/test_strict_json_docs.py` |
| Checker verdict shape, exit contract, `rule_states` vocabulary | `pipeline/tests/test_checker_base.py` |
| Declared mode contradicting derived state is a WARN that names both | `pipeline/tests/test_state_declaration_conflict.py` |
| Verdict self-contradiction (`converged` + `escalate_human`) | `pipeline/tests/test_verdict_schema.py` |
| Residue gate: keep-list, fill attribution, malformed artifact, pinned target | `pipeline/tests/test_check_residue.py` |
| `--expect-text` is a text-level claim (T130) | `pipeline/tests/test_expect_text.py` |
| Visual verify exit-code matrix, safety-check completeness, waiver auditability | `pipeline/tests/test_visual_verify.py` |
| Snapshot integrity, zip-slip and symlink refusal on restore | `pipeline/tests/test_ws_snapshot.py` |
| Offline typed edits, idempotence, ambiguity refusals | `engine/tests/test_preedit.py` |
| T30 charPr preflight refusal | `engine/tests/test_t30_preflight.py`, `engine/tests/test_charpr_colour_preflight.py` |
| Form profile shape: table map, seat colour, `at_para` addressing | `engine/tests/test_form_inspect.py`, `engine/tests/test_form_inspect_tables.py`, `engine/tests/test_form_inspect_post_v017.py`, `engine/tests/test_charpr_seat_addressing.py` |
| COM op validation without launching Hancom | `engine/tests/test_com_backend_offline.py`; live path `engine/tests/test_com_backend_live_cell.py` |
| Document-shape refusal ordering for privacy-safe inspect | `engine/tests/test_ingress_document_shape.py` |
| XML backend op support set and refusal codes | `engine/tests/test_xml_backend.py` |
| T18/T21/T22 guard primitives (protected paragraphs, instance lock, dangling charPr) | `engine/tests/test_guards.py` |
| cp949 `--help` safety across every shipped CLI | `tests/test_cli_cp949_help.py` |
| Child-process bounds are above the measured loaded median | `tests/test_subprocess_bounds.py` |
| Studio localhost surface: token, Host guard, workspace containment | `tests/test_studio.py` |
| Skill install: drift refusal, atomic swap, rollback, lock | `tests/test_sync_local.py` |
| Bundle: reproducibility, privacy gate, manifest verification | `tests/test_package_module.py` |
| Clean-room reproducibility of the shipped surface | `tests/test_cleanroom_evals.py`, `tests/test_bundled_skill_says_which_copy.py` |
| Module registry: absence is not failure, presence is integration, loud invalidity | `pipeline/tests/test_module_registry.py` |

GAP: no test pins a stdio boundary, because there is no stdio boundary yet.
Build note: the first three Runtime tests should be (1) an ordinary call
before `initialize` is refused and the connection survives, (2) an oversized
frame is refused unparsed, (3) stdout contains only frames while a noisy
worker writes to stderr.

---

## 6. Packaging implications

The Runtime is a new top-level surface, so both packaging paths must learn
about it.

**`scripts/package_module.py`** — `--module core` currently stages
`engine/`, the pipeline core (`pipeline/scripts`, `pipeline/adapters_impl`,
`pipeline/references`), `studio/`, the router skill surface, the skill
installer, `modules/README.md`, `pyproject.toml` and `LICENSE`
(`scripts/package_module.py:11-18`, `_stage_core` at `:681`). Adding a
`runtime/` tree means:

- staging it in `_stage_core`;
- accepting the reproducibility contract — same tree ⇒ same bundle bytes, via
  the pinned `ZIP_EPOCH` (`scripts/package_module.py:105`) and
  `_write_bundle_zip` (`:439`);
- passing `_run_privacy_gate` (`:457`) with zero HARD findings;
- keeping every doc path the shipped skill surface names resolvable **inside**
  the bundle (`scripts/package_module.py:243`,
  `_assert_skill_surface_references`) — a dangling reference is exit 3, and
  it is derived rather than a filename list, so a new `docs/runtime-*.md`
  referenced from `SKILL.md` is checked automatically;
- `verify_bundle` (`:804`) then re-hashes it as tamper detection.

**`scripts/sync_local.py`** — the base+overlay installer
(`scripts/sync_local.py:1-27`). If the Runtime ships as part of the skill
install, it becomes *base* content: hand-editing it in the install is refused
as drift ("edit upstream or move to overlay", `:20`), and a file that stops
being produced is deleted on the next sync (`:21`). Local operator
customization of Runtime behaviour therefore belongs in the overlay or in the
profile store (`pipeline/scripts/personalization_ctl.py:1`), never in an
edited install file.

**Sidecar shape.** The Runtime is launched by the Desktop shell as a child
process, so it needs a stable console entrypoint. The existing pattern is a
script invoked as `python <path> ...` with `PYTHONIOENCODING=utf-8` on Windows
(`scripts/sync_local.py:27`) and `utf8_stdio()` called before `parse_args`
(`engine/scripts/cli_io.py:33`). GAP: `pyproject.toml` declares no console
scripts today. Build note: decide early whether the Desktop shell spawns
`python -m rigorloom.runtime` or a packaged executable, because the answer
changes what `package_module.py --module core` has to ship.

---

## 7. Open questions

1. **Does Studio become a Runtime client, or stay a peer?** Studio is already
   a localhost control server with an action token, a Host-header guard and
   workspace containment (`studio/main.py:993`, `:100`). v0 says the Runtime
   gets no localhost server. Two servers with two authority models on one
   machine is the kind of thing that is fine until it is not. Unresolved from
   code.
2. **One Runtime per Desktop window, or one per machine?** The COM mutex is
   machine-wide (`pipeline/scripts/hwp_ingress.py:1188`), so a second Runtime
   is not a correctness problem for Hancom — but it is for workspace locking,
   which has no machine-wide equivalent (`sync_local`'s lock covers the skill
   install, not a workspace: `scripts/sync_local.py:54`).
3. **Who owns `HwpInstanceLock` wiring?** It is a tested primitive that
   nothing calls (`engine/scripts/guards.py:245-246`). Wiring it in the
   Runtime changes `com_backend --kill-stale` behaviour for CLI users too,
   which is a product decision, not a refactor.
4. **Is the parser worker a subprocess at all?** `form_inspect`, `preedit` and
   `xml_backend` are importable modules with `main()` wrappers, and
   `form_inspect` already imports `preedit` directly
   (`engine/scripts/form_inspect.py:92`). In-process is faster and loses the
   crash isolation and the bounded-child containment
   (`pipeline/scripts/diagnostic_candidate_core.py:1128`). Which matters more
   for a desktop editor's latency budget is not answerable from the code.
5. **Where do renderer workers get their environment?** `ENV_POLICY =
   "minimal_allowlist_v1"` (`pipeline/scripts/renderer_runtime_v2.py:47`) is
   declared for the quarantined lane only; `com_backend` inherits the parent
   environment. Should the Runtime impose the allowlist on COM too, given
   Hancom reads user profile state?
6. **What is the Desktop shell written in, and does that change the trust
   model?** If the shell is Electron or another web-tech shell, B2 acquires a
   renderer-process boundary the Runtime cannot see, and the "host authority"
   assumption in §1.1 needs a second look. Not decidable from this repo.
7. **Multi-window / multi-workspace concurrency.** Offline parser workers are
   independently safe (§1.3), but two plans against the *same* document have
   no arbitration anywhere in the tree. Is exclusivity a Runtime lease, or is
   the exact-byte binding (`plan_stale`) considered sufficient?
