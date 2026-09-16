# A1 — Stage 3 COM wiring analysis

## Executive conclusion

The Runtime does not currently route edit plans to either the XML or COM backend. It only executes `preedit`. COM is reachable through a separate host-only conversion path, `document/renderPrepare`, but that path calls `com_backend.py convert`, not `com_backend.py edit`. The smallest honest implementation is therefore not a new editing engine. It is a backend branch at the existing `OperationPlan`/approval/apply boundary, a bounded child adapter for one stateless `com_backend.py edit` batch, dynamic capability reporting from the existing Hancom probe, and a receipt extension that hash-binds both the saved HWPX and the PDF produced by Hancom.

The first COM slice should expose seven already-implemented operations: `goto_text`, `find_delete`, `move`, `insert_text`, `set_cell`, `set_para_align`, and `set_line_spacing`. This is enough for useful form and prose editing while avoiding the higher-risk native-object families until their schemas, round trips, and visual fixtures are owned. Initial Runtime COM apply should accept HWPX subjects only. Binary HWP ingress and conversion can follow as a separately evidenced expansion.

## 1. Current routing, exactly

### CLI to plan

`runtime/scripts/cli.py:468-552` is the process entry. `main()` creates `RuntimeCore(root, args.engine_root)` at lines 534-535 and calls `dispatch(core, args)`. For `propose`, `dispatch()` calls `RuntimeCore.plan_propose()` at `cli.py:400-405`; for `apply`, it calls `RuntimeCore.plan_apply()` at `cli.py:417-424`. Thus the CLI does not choose an implementation backend itself. Its `--backend` option is declared at `cli.py:274-280`, defaults to `SUPPORTED_BACKENDS[0]`, and is merely passed into the domain layer.

`RuntimeCore.plan_propose()` is at `runtime/scripts/rt_core.py:365-410`. It resolves the session, optional base candidate, optional reversal, and exact bound digest, then calls `rt_plan.build_plan()` at lines 400-403. `build_plan()` refuses before creating a plan if the backend is not in `SUPPORTED_BACKENDS` (`runtime/scripts/rt_plan.py:365-389`). `SUPPORTED_BACKENDS` is currently exactly `("preedit",)` at `runtime/scripts/rt_codes.py:171-176`; `KNOWN_BACKENDS` lists `preedit`, `xml`, and `com`. Consequently a CLI command with `--backend com` is refused during proposal, before validation, approval, or apply.

The operation registries reinforce that boundary. `PREEDIT_OP_KINDS` is the four-operation mapping at `rt_plan.py:55-64`. `XML_OP_KINDS` and `COM_OP_KINDS` are descriptive sets at `rt_plan.py:70-85`, used by `_classify_foreign_kind()` (`rt_plan.py:351-360`) to make the refusal say which unserved backend owns an operation. They are not dispatch tables. In fact the COM set is stale: it claims 22 entries, while the current `engine/scripts/com_backend.py` `OPS` table has 24 entries at lines 1903-1927, including `page_numbers` and `set_header`. That mismatch is another reason not to advertise the whole engine table as Runtime-supported.

`build_plan()` currently validates every accepted operation against the single `_OP_FIELDS` table at `rt_plan.py:94-102` and rejects any kind outside `PREEDIT_OP_KINDS` at lines 400-416. `validate_plan()` (`rt_plan.py:579-721`) is likewise preedit-specific: it checks cell/run profiles, fill anomalies, guide selectors, and preedit’s structural preflight. There is no COM validation branch.

### Approval to apply

`RuntimeCore.plan_apply()` at `rt_core.py:509-553` verifies that the approval binds the exact plan id and plan hash, requires state `approved`, validates again, and then calls `rt_apply.apply_plan()` at lines 538-550. The call is wrapped by `rt_apply_once.apply_once()` so one approved plan publishes at most one candidate and an uncertain prior attempt is not blindly replayed (`runtime/scripts/rt_apply_once.py:74-122`).

`apply_plan()` at `runtime/scripts/rt_apply.py:198-340` resolves the origin: the immutable session source copy for a root plan, or a receipt-verified candidate from `candidate_artifact()` for a based plan (`rt_apply.py:205-218`). It then loops over operations. Every operation is translated by `_argv_for()` (`rt_apply.py:63-112`) into a `preedit` subcommand and executed by `EngineTools.preedit_run()` (`rt_apply.py:231-253`). `EngineTools.preedit_run()` in `runtime/scripts/rt_engine.py:435-453` launches `engine/scripts/preedit.py` through the bounded `run_child()` primitive. There is no switch on `plan.payload["backend"]`; the receipt’s backend field at `rt_apply.py:273` currently records the declaration, while execution is unconditionally preedit.

After all steps, `apply_plan()` atomically copies the final work file to the candidate directory, hashes it, runs the residue checker, builds a receipt, and writes the receipt last (`rt_apply.py:255-319`). Receipt presence is publication. Its current evidence is explicitly `structural_only` at lines 310-314.

### XML comparison

`engine/scripts/xml_backend.py` has a real standalone registry, `SUPPORTED_OPS`, at lines 26-31. Its `main()` loads an operations file, rejects unsupported operations before mutation, constructs `HwpxDocument`, dispatches operations, and saves to a distinct path (`xml_backend.py:1124-1228`). However, the Runtime never calls it: `EngineTools.__init__()` only resolves `form_inspect`, `preedit`, and `check_residue` (`rt_engine.py:281-286`), and it has no `xml_backend` adapter. The Runtime merely copies XML operation names into `XML_OP_KINDS`. COM is in the same unserved state for editing.

### `com.state` and `com.reason`

For `rigorloom ... capabilities`, `cli.dispatch()` calls `core.capability_snapshot()` at `cli.py:352-356`. `RuntimeCore.capability_snapshot()` constructs `backends["com"]` directly at `runtime/scripts/rt_core.py:180-217`. The two requested fields are produced at lines 192-194:

* `backends.com.state = "unavailable"`
* `backends.com.reason = "declared by the protocol; not executed by this build"`

These are static build facts, not the result of probing pyhwpx or Hancom. `supportedBackends` is independently produced from `SUPPORTED_BACKENDS` at `rt_core.py:199`, so it also says only `preedit`.

There is already a suitable cheap host probe elsewhere. `rt_convert.hancom_facts()` (`runtime/scripts/rt_convert.py:78-110`) checks Windows, pyhwpx importability, and registered HWP ProgIDs and returns `state`, `reason`, `progid`, and `pyhwpx`. `prepare_capability()` exposes it for render conversion at `rt_convert.py:140-155`. That probe currently feeds `capabilities.render.prepare`, not `backends.com`. The slow `render_probe` in `EngineTools.render_probe()` (`rt_engine.py:456-491`) is a separate opt-in renderer inventory and must not be treated as proof that COM editing is wired.

## 2. Smallest honest COM execution change

### Backend contract and validation

Modify `rt_codes.SUPPORTED_BACKENDS` to include `com`, where “supported” means the build has a dispatch path, not that every host has Hancom. Host availability remains a capability state and apply-time precondition. Do not add all 24 engine operations.

In `rt_plan.py`, replace the preedit-only operation check with backend-specific, closed schemas. Add a `COM_RUNTIME_OP_FIELDS` table for:

1. `goto_text` — deterministic first-occurrence anchor navigation already documented by the backend.
2. `find_delete` — single-occurrence by default, with explicit `all`; useful for guide removal.
3. `move` — bounded cursor movement required to compose insertion plans.
4. `insert_text` — the essential prose mutation, including existing point-size, segments, alignment, and break controls.
5. `set_cell` — the safest useful form mutation because `addr` uses `form_inspect` cellAddr and supports `expect_empty`/`expect`.
6. `set_para_align` — scoped paragraph correction without introducing new objects.
7. `set_line_spacing` — common native paragraph normalization and an M1/M2 layout need.

Defer `replace_all` because it is document-wide and has no count or uniqueness precondition; `put_field` because `OP_REQUIRED_KEYS` currently requires `text` while `op_put_field()` reads `value` (`com_backend.py:1931-1948` versus `:424-427`); and equations, tables, pictures, hyperlinks, controls, headers, numbering, page breaks, and page binding because they need family-specific native/round-trip/render fixtures. The deferred set remains visible as implemented-in-engine but not supported-in-Runtime, preserving the vision document’s separate coverage states.

Add `normalise_com_op()` (or an equivalent small helper) that turns Runtime shape `{"opId", "kind", "params"}` into backend shape `{"op": kind, **params}`. Validate unknown and missing fields before plan creation. For `set_cell`, require `addr:[row,col]`, reject `raw_traversal`, and strongly require exactly one of `expect_empty` or `expect` in the first Runtime slice. This is intentionally stricter than the raw engine: the CLI-first contract requires stable targets, not mere access to every legacy escape hatch.

`validate_plan()` should retain exact-byte staleness and profile loading, but report a COM preflight level such as `structural+backend-schema` and list native anchor existence, current-cell state, and Hancom-side behavior as deferred. It must not start Hancom; validation and apply remain separate.

### Capability production

Change `RuntimeCore.capability_snapshot()` to derive `backends.com` from a helper that combines:

* presence of `engine/scripts/com_backend.py`;
* `rt_convert.hancom_facts()` (`state`, `reason`, `progid`, `pyhwpx`);
* the seven Runtime-supported operation kinds;
* an explicit `notImplemented` list for the rest of the engine registry;
* `serial: true`, `documentKinds: ["hwpx"]`, and `nativeSmoke: "not run by capability probe"`.

Map `hancom_facts().state == "yes"` to Runtime’s existing backend vocabulary `available`; otherwise use `unavailable` and preserve the exact reason. Do not report `available` merely because the script exists, and do not use a successful probe as native execution evidence.

### One COM batch, not one Hancom launch per operation

Extend `EngineTools` in `rt_engine.py` with the `com_backend.py` path and a `com_edit()` adapter. It should stage one JSON operations file, then invoke:

`python com_backend.py edit --file <origin> --ops <ops.json> --save-as <work-result.hwpx> --export-pdf <work-native.pdf>`

Use the existing `run_child()` environment, output bound, and timeout. Parse the whole JSON object because `com_backend.py edit` emits pretty-printed multi-line JSON; the reverse-line parser used for preedit is not sufficient. `rt_module._run_one()` at `runtime/scripts/rt_module.py:499-561` is a useful model for bounded child outcome normalization, but `rt_module` itself needs no change.

The COM batch must be serialized with the same Windows named mutex as `pipeline/scripts/hwp_ingress.py:_com_serial_guard()` (`hwp_ingress.py:1190-1241`) and must retain the existing “live Hwp.exe means `com_busy`, never kill it” rule from `rt_convert.py:112-138,229-245`. Put a reusable guard in `rt_convert.py` and use it from both render preparation and COM apply; otherwise the two Runtime COM paths have a check-then-launch race. Never pass `--kill-stale`.

### Open, edit, save, export, and publish

Add a backend branch in `rt_apply.apply_plan()`. The origin remains exactly the current origin: `session.source` or `candidate_artifact()` output. `Session.open_path()` already copied the operator’s original to `<root>/sessions/<id>/source/` at `runtime/scripts/rt_session.py:175-205`, so the user file is never handed to Hancom.

For COM, call `tick()` once before native launch and once after completion; do not promise mid-batch cancellation. `com_backend.main()` already validates the full batch before `open_hwp`, opens once, applies `OPS` in order, calls `hwp.save_as`, exports PDF via `SaveAs(...,"PDF")`, emits results, and quits in `finally` (`com_backend.py:2116-2147,2256-2262`). That is the right transaction-sized boundary. Running one process per operation would multiply COM startup, weaken cursor semantics, and create intermediate native files with no user value.

Write both outputs under `work/<runId>/`. Only after the edit succeeds, run a second bounded `com_backend.py inspect --privacy-safe` against the saved work HWPX. This is the reopen check: it proves Hancom can open the persisted candidate and records only text SHA-256 and aggregate counts, not document text or field names. Then atomically move the HWPX and PDF into the run directory, run existing offline residue checks against the HWPX, and publish the receipt last. A failed reopen publishes nothing.

### Native evidence in the receipt

Keep the existing `candidate` descriptor for compatibility, but add a hash-bound `native` block containing:

* backend `native_hancom_windows`;
* command `engine/scripts/com_backend.py edit`;
* child exit code `0`;
* exact input digest and whether it was session source or a base candidate;
* ordered per-operation results associated with Runtime `opId`s;
* saved HWPX descriptor (`assembled_hwpx`, relative path, SHA-256, bytes);
* exported PDF descriptor (`rendered_pdf`, relative path, SHA-256, bytes);
* privacy-safe reopen fingerprint and aggregate control/page counts;
* `serialGuard`, timeout, and `descendantContainment: "not_established"`.

Set `evidence.class` to the existing closed value `native_render`, not a new word. `engine/scripts/document_evidence.py:32-59` already maps `native_hancom_windows` to `native_render`. State plainly that this proves native save/export/reopen provenance for these exact bytes, not visual correctness, no-dialog GUI behavior, or release acceptance. Extend `read_receipt()` to re-hash the PDF as well as the candidate; otherwise the native claim can drift while receipt reading still succeeds.

Timeout is special. `run_child()` kills only the direct Python child and descendant containment is not established (`rt_engine.py:23-31,146-213`). A COM timeout can leave Hwp.exe or an uncertain save. It must raise `apply_outcome_unknown`, leave the durable apply journal non-retryable, and require recovery; it must never be converted into an ordinary retryable backend refusal. Modify `rt_apply_once.apply_once()` so an `apply_outcome_unknown` exception cannot write journal state `not_applied`, even if private directories were cleaned.

## 3. Tests

All default tests must avoid importing or launching pyhwpx.

* Capability tests monkeypatch `hancom_facts()` for Windows-present, pyhwpx-missing, ProgID-missing, and script-missing cases. Assert exact `backends.com.state`, `reason`, op list, and `supportedBackends`.
* Plan tests accept only the seven COM schemas, preserve `opsHash`/`planHash` behavior, reject engine-only COM operations by name, reject `raw_traversal`, and validate without touching the COM adapter.
* Adapter tests replace `run_child()` with a fake result, inspect the staged ops JSON, assert one `edit` process for a multi-op plan, and fake the privacy-safe reopen result. They also cover malformed stdout, nonzero exits, missing output, timeout, and bounded error data.
* Apply tests use a fake `EngineTools.com_edit()` that copies a real corpus HWPX and writes a tiny PDF. Assert the original is byte-identical, the adapter receives the session copy or verified base candidate, receipt publication remains last, both artifacts are hash-bound, PDF drift is refused, and failures leave no canonical candidate.
* Serialization tests fake the named mutex and task list: busy/unknown refuses before launch; concurrent render-prepare and edit cannot both enter; no executable kill/terminate/taskkill path exists.
* Retry tests assert a pre-launch refusal is retryable, while timeout or ambiguous post-launch failure leaves `apply_outcome_unknown` and a second apply does not launch COM again.

The one live smoke belongs in `tests/test_runtime_com_live.py`, default-skipped unless `RIGORLOOM_LIVE_COM=1`. Run it serially on Windows with Hancom and pyhwpx, with no Hwp.exe already open. It should copy a corpus HWPX, drive the real CLI through open → propose COM `set_cell` with `expect_empty` → validate → request/approve → apply, then assert: original hash unchanged; addressed cell changed and a nearby label did not; candidate, PDF, and receipt hashes agree; privacy-safe reopen succeeded; receipt evidence is `native_render`; and candidate PDF page count equals reopened document page count. It must never use `--kill-stale`.

## 4. Risks and freeze constraints

COM is stateful, modal, and machine-global. A batch can hang on dialogs, pyhwpx APIs vary, cursor state composes across operations, and save/export can partially occur before a process failure is observed. The named mutex, pre-launch task check, one batch, work-directory outputs, receipt-last publication, and unknown-outcome journal are mandatory, not polish.

Native provenance is not native acceptance. A PDF hash proves which bytes Hancom exported; it does not prove every page is readable, unclipped, or semantically correct. Offline residue can also be clean while visual layout is wrong. Those evidence classes must remain separate.

The CLI-first vision section 4 requires one document model, typed operations, stale-target detection, declared prerequisites, actionable unsupported results, versioned structured I/O, deterministic exits, receipts, safe paths, and the same semantics in any future frontend. This change may adapt `com_backend.py`; it must not duplicate its editing logic in Runtime or introduce a parallel wrapper contract.

Vision section 7 permits M3 catalog work and M4 packaging investigation alongside M1/M2, but forbids presenting that as native parity. Frontend work follows a stable CLI contract. Renderer, rematch, and certificate work remains frozen: this COM edit wiring must not alter `own_render`, geometry rematching, renderer thresholds, or certificate code. A native PDF may be stored and later rasterized through existing paths, but no renderer behavior or proof-grade rule may be changed without the owner’s narrow, evidence-backed unfreeze decision. Unsupported operation families must remain explicit rather than being counted as covered.

## 5. Ordered bounded Cursor tasks

1. **COM plan contract and capability.** Owned paths: `runtime/scripts/rt_codes.py`, `runtime/scripts/rt_plan.py`, `runtime/scripts/rt_core.py`, `tests/test_runtime_plan.py`, `tests/test_runtime_cli.py`. Accept with `python -m pytest -q tests/test_runtime_plan.py tests/test_runtime_cli.py`.
2. **Serialized COM child adapter.** Owned paths: `runtime/scripts/rt_engine.py`, `runtime/scripts/rt_convert.py`, new `tests/test_runtime_com_adapter.py`, existing `tests/test_runtime_render_prepare.py`. Accept with `python -m pytest -q tests/test_runtime_com_adapter.py tests/test_runtime_render_prepare.py`.
3. **COM apply and native receipt publication.** Owned paths: `runtime/scripts/rt_apply.py`, `runtime/scripts/rt_apply_once.py`, new `tests/test_runtime_com_apply.py`, `tests/test_runtime_apply_retry.py`. Accept with `python -m pytest -q tests/test_runtime_com_apply.py tests/test_runtime_apply_retry.py tests/test_runtime_apply.py`.
4. **Cross-surface regression.** Owned paths: test-only changes in `tests/test_runtime_parity.py`, `tests/test_runtime_authority.py`, and `tests/test_runtime_mcp.py`. Confirm COM remains host-applied while proposal/validation representations stay shared. Accept with `python -m pytest -q tests/test_runtime_parity.py tests/test_runtime_authority.py tests/test_runtime_mcp.py`.
5. **Opt-in native smoke.** Owned path: new `tests/test_runtime_com_live.py`; no production edits. First accept default behavior with `python -m pytest -q tests/test_runtime_com_live.py`, then on the sole-COM Windows host run `RIGORLOOM_LIVE_COM=1 python -m pytest -q -s tests/test_runtime_com_live.py`. Stop after one recorded run; do not broaden operations or start renderer/rematch work.

