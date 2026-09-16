# Stage 3: wiring the COM backend through the Runtime CLI

This note is a read-only map of how a Runtime plan reaches a document backend today, what is missing for `com`, and the smallest honest change set. Line numbers are from this worktree (`rigorloom-stage1`). Protocol comments that still cite `com_backend.py:1598` / `:1670` are stale: `OPS` now starts at **1902**, `_validate_ops` at **1977**, `main()` at **2016**.

---

## 1. How the Runtime CLI routes a plan to a backend

### 1.1 Front door: CLI to domain

`runtime/scripts/cli.py` is argument parsing and exit codes, not a second applier. After `--root` is created, `main()` constructs `RuntimeCore(root, args.engine_root)` (cli.py:535) and `dispatch()` (351–446).

`propose` loads ops from `--ops-file` / `--op` (`_load_ops`, 103–123), then:

- `dispatch` → `core.plan_propose(session, backend, ops, proposer, …)` (cli.py:400–405)
- default `--backend` is `SUPPORTED_BACKENDS[0]` (cli.py:276), which is `"preedit"` because `rt_codes.py:175` sets `SUPPORTED_BACKENDS = ("preedit",)` and `KNOWN_BACKENDS = ("preedit", "xml", "com")` (176).

`apply` is host-shaped on the wire (`plan/apply` is in `HOST_ONLY_METHODS`, `rt_core.py:121–126`) but the CLI exposes it:

- `dispatch` → `core.plan_apply(plan, approval)` (cli.py:417–424)
- `--require-checks` only maps `candidate.checks.ranAll` to exit 3; it does not choose a backend.

JSONL/MCP use the same `RuntimeCore` methods. Parity is the point of `tests/test_runtime_parity.py`.

### 1.2 Propose: backend is a plan field, then a hard allowlist

`RuntimeCore.plan_propose` (`rt_core.py:365–410`) does not inspect Hancom. It hashes a base candidate if `--base-run` is set, then calls `build_plan(...)`.

`build_plan` (`rt_plan.py:364–465`) is the first routing gate:

1. If `backend not in SUPPORTED_BACKENDS` → `RpcError("unsupported_backend", …)` with `declared`, `supported`, `known` (381–389). **`xml` and `com` always fail here**, even on a machine with pyhwpx and Hancom.
2. Each op `kind` must be in `PREEDIT_OP_KINDS` (fill_cell, replace_at_cell, set_run, delete_guides; `rt_plan.py:58–63`). Foreign kinds are classified by `_classify_foreign_kind` (354–361) against `XML_OP_KINDS` (71–75) and `COM_OP_KINDS` (77–84) and refused as `unsupported_backend` with `servedBy` (`"xml"`, `"com"`, or `"xml or com"`).

So the CLI “routes” at propose time only by **refusing** everything that is not preedit. There is no dispatcher that later picks `xml_backend.py` or `com_backend.py`.

`validate_plan` (`rt_plan.py:578–721`) is preedit-profile preflight (cells, T30/T127, run inventory). It never calls `_validate_ops` in `com_backend.py`.

### 1.3 Apply: always preedit, always a copy

`RuntimeCore.plan_apply` (`rt_core.py:509–554`) checks approval binding, then `apply_once` → `execute` → `apply_plan`.

`apply_plan` (`rt_apply.py:198–340`):

- Subject is `session.source` or a published candidate (`candidate_artifact`); the operator original is never the subject (module docstring, properties 1 and 4).
- For each op: `_argv_for(kind, params, current, target)` (63–112) builds a **preedit** argv (`fill-cells`, `replace`, `set-runs`, `delete-guides`). Unknown kinds raise `unknown_op_kind`.
- `tools.preedit_run(argv)` (`rt_engine.py:436–454`) spawns `engine/scripts/preedit.py`.
- Work files live under `session.work_dir / run_id`; the finished file is `_atomic_move`d to `candidates/<runId>/artifact<suffix>`; `receipt.json` is written last (`_publish_receipt`).
- Receipt `evidence` is hardcoded `class: structural_only` (`rt_apply.py:310–314`): bytes + residue, **no native COM proof**.

The plan’s `backend` field is copied onto the receipt (`rt_apply.py:274`) but is **not** used to choose a child.

### 1.4 Engine adapter: subprocess, not import

`EngineTools` (`rt_engine.py:279–299`) probes **script files**: `form_inspect`, `preedit`, `check_residue`. It does not list `com_backend.py` or `xml_backend.py`. Children use `run_child` + `child_env()` (allowlist, UTF-8). Residual: no Windows Job / descendant containment (`rt_engine.py:24–32`).

The **only** Runtime COM child today is convert, not edit:

- `EngineTools` has no `com_edit` / `xml_edit`.
- `rt_convert.run_convert` (`rt_convert.py:158–180`) runs `com_backend.py convert --file … --to …`.
- `prepare_pdf` is host-only (`document/renderPrepare`, `rt_core.py:567–594`). Rules: session copy or candidate only; never `--kill-stale`; live `Hwp.exe` → `com_busy`; no Hancom → `needs_hancom`. Tests must not start Hancom (`rt_convert.py:32–36`).

### 1.5 Capability probe: `com.state` and `com.reason`

Produced in **`RuntimeCore.capability_snapshot`** (`rt_core.py:180–217`), not in `cli.py`. CLI `capabilities` returns `core.capability_snapshot(methods=list(METHODS))` (cli.py:353–356).

```python
"com": {"state": "unavailable",
        "reason": "declared by the protocol; not executed by this build",
        "opKinds": sorted(COM_OP_KINDS)},
```

(`rt_core.py:192–194`; `xml` is the same shape at 189–191.)

These strings are **constants**. They do not call `hancom_facts()` (`rt_convert.py:77–110`), which already answers Windows + pyhwpx + ProgID. Render prepare uses that probe (`prepare_capability`, `rt_convert.py:141–155`); plan backends do not.

`tools.preedit.state` *is* a real file probe (`EngineTools.availability`, `rt_engine.py:288–299`). `com` is not.

`COM_OP_KINDS` (`rt_plan.py:77–84`) lists 22 names and comments `com_backend.py:1598`. Live `OPS` (`com_backend.py:1902–1927`) has **24** handlers: the Runtime set omits `page_numbers` and `set_header`. Overlap with XML is `goto_text`, `insert_text`, `insert_equation`, `insert_table`, `page_binding`, `replace_all`, `insert_blank_before`, `insert_picture`, `set_line_spacing`.

### 1.6 How xml_backend is (not) called

`xml_backend.py` is a COM-free HWPX zipper (`SUPPORTED_OPS` at 27–31). `main()` (1123+) requires `edit --file --ops --save-as`, refuses same-path save-as (1132–1133), `load_ops`, then applies. Unsupported names (including COM chrome `page_numbers` / `set_header` via `XML_UNSUPPORTED_REASONS`, 33–36) emit JSON and **exit 4** (1152–1153) — a backend-local code the protocol says must be mapped, not leaked (`docs/runtime-protocol-v0.md` around line 87).

**The Runtime never subprocesses this script.** It only uses the op-name set to classify refusals. Wiring XML is a separate slice; this note does not bundle it.

### 1.7 COM engine edit/save-as/export (what apply must reuse)

`com_backend.main()` subcommands: `inspect`, `edit`, `set-cell`, `convert` (2016–2070).

**edit** (2116–2147):

1. `--save-as` equal to `--file` → `_die` (original overwrite).
2. Load ops JSON; `_validate_ops` **before** `open_hwp` (2120–2125) — unknown `op` / missing required keys / equation preflight / `set_cell` T28 addressing (1977–2009, 1951–1974).
3. `open_hwp(..., visible, kill_stale)`.
4. For each op, `OPS[name](hwp, o)`; results collected.
5. If `--save-as`: `hwp.save_as(resolved)`.
6. If `--export-pdf`: `save_as`/`SaveAs` PDF format.
7. stdout JSON: `{ok, results, saved, pdf, post_inspect}`.

Op payloads use engine key `"op"`, not Runtime `"kind"`. Runtime apply must translate.

Protocol D9 (`docs/runtime-protocol-v0.md` §9, ~658–660): this slice executes **preedit only**; xml/com plans are `unsupported_backend`. Decision 8.1 (plan declares backend; Runtime does not guess) is already implemented as D9.

---

## 2. Smallest honest change set (COM executable when pyhwpx + Hancom exist)

Honesty: do not mark `com.state` available unless the same three facts `hancom_facts()` uses are true **and** `engine/scripts/com_backend.py` exists. Do not execute COM from tests. Do not pass `--kill-stale`. Do not start Hancom when `Hwp.exe` is live. Do not mix backends in one plan. Do not claim render/certificate proof because COM ran.

### 2.1 Functions to add or modify

| Path | Change |
| --- | --- |
| `rt_codes.py` | Keep `KNOWN_BACKENDS`. Either expand `SUPPORTED_BACKENDS` dynamically (dangerous for tests on Linux CI) **or** keep the tuple as “always-on-this-build” and introduce **runtime-executable** backends: e.g. `executable_backends()` = `("preedit",)` plus `"com"` iff probe says yes. `build_plan` should accept a declared known backend that is executable **now**, and refuse `com` with `capability_unavailable` (not “this build never executes com”) when the probe is no. |
| `rt_core.capability_snapshot` | Replace the constant `com` block. Fields: `state` (`available` / `unavailable` / optionally `busy` if you probe processes — prefer **not** to tasklist on every `capabilities` call; busy is an apply-time refusal). `reason` from `hancom_facts()["reason"]` or `"script not found"` / `"not Windows"`. `opKinds`: first-wave subset, not the full 24. `notImplemented` / `deferred`: remaining COM ops. `serial` / `authority`: host apply, one Hancom. Reuse `prepare_capability` language. |
| `rt_plan.build_plan` | If `backend == "com"`: require kinds ⊆ first-wave set; map Runtime `kind` ↔ engine `op` (same strings for this wave). Validate required params against `OP_REQUIRED_KEYS` **without importing** `com_backend` (duplicate the small table, or spawn `python com_backend.py` only if a `--dry-validate` exists — it does not; copy the key table and T28 `set_cell` rules). Keep mixed-kind refusal: a `fill_cell` on a `com` plan is `invalid_params` / `unknown_op_kind`. |
| `rt_plan.validate_plan` | For `backend == "com"`, do **not** pretend preedit cell preflight is COM validation. First wave: schema + stale hash only; `preflight.deferred` must list COM-only refusals (equation preflight, `set_cell` expect, find miss). Optionally: if `com_backend` can be imported in a child with `--help` only, do not open Hancom. |
| `rt_apply._argv_for` | Split: `_argv_for_preedit` (current) vs `_com_edit_invocation`. COM should be **one child per plan**, not one child per op: `com_backend edit` is already a batch, and N Hancom round-trips fight the machine mutex (protocol Q4, ~627–631). |
| `rt_apply.apply_plan` | Branch on `plan.payload["backend"]`. COM path: copy origin → work input (never in-place on session source: COM `edit` without `--save-as` does not overwrite, but opening the session copy in Hancom still risks side effects — **always** copy to `work/<runId>/input.*` then `--file` that copy `--save-as` `stepN`). Write `ops.json` with engine shape `[{"op": kind, ...params}]`. Call new `EngineTools.com_edit_run`. Publish artifact from `--save-as`. Optional `--export-pdf` to `run_dir` **only if** the product wants native PDF evidence in the same COM session (cheaper than a later `convert`); if omitted, receipt stays structural + `post_inspect`. |
| `rt_engine.EngineTools` | Add `self.com_backend` path; `availability()` row `com_backend`. Add `com_edit_run` wrapping `run_child` like `run_convert`. Parse last JSON object from stdout (same as `preedit_run`). Map non-zero / timeout → `backend_refused` / `capability_unavailable`. **Never** add `--kill-stale` or `--visible` in production argv. |
| `rt_apply` apply-time COM gate | Before spawn: reuse `running_hancom_processes()`; if busy → `com_busy` (same as convert). If `hancom_facts()["state"] != "yes"` → `needs_hancom`. Cooperative `checkpoint` between preedit steps does **not** apply mid-COM; once the child starts, treat as non-cancellable (protocol Q5 / T21). |
| Receipt | See §2.4. |
| Tests that assert `supported == ["preedit"]` | `tests/test_runtime_plan.py:74`, CLI/MCP/parity equivalents: update to “preedit, and com only when probe is yes” **or** keep CI probe always-no so those tests stay green. Prefer injecting `hancom_facts` so CI never depends on a developer’s Office install. |

Do **not** in this slice: enable `xml` apply; widen `PREEDIT_OP_KINDS`; import pyhwpx into the Runtime process; auto-choose backend from op kind; kill Hancom; unfreeze renderer/certificate.

### 2.2 First-wave ops (7)

Recommended concrete list:

1. **`replace_all`** — required `find`/`replace`; no cursor; high value for templates.
2. **`goto_text`** — required `text`; establishes COM cursor for the rest of the batch.
3. **`insert_text`** — required `text`; needs a prior `goto_text` in the same plan (document that as a plan invariant; missing goto is a COM-time failure listed in `deferred`).
4. **`set_cell`** — form fill with `addr:[row,col]` (T28); Runtime params should be `addr` or `row`/`col` translated to `addr`, **never** silent `raw_traversal`.
5. **`insert_equation`** — COM-unique native equation; preflight already exists before Hancom (`_checked_equation_script`). This is the product reason to wire COM at all.
6. **`insert_picture`** — required `path`; COM-unique embed. Runtime must copy the picture into the session work dir and pass that path (no operator home paths in receipts if avoidable).
7. **`insert_hyperlink`** — required `url`; COM-only vs preedit/xml; small surface.

Why not 8: adding `find_delete` or `insert_blank_before` is cheap but increases destructive surface without proving native insert. Defer `insert_table`, `move`, `edit_equation`, `put_field`, chrome (`page_numbers`, `set_header`), and `delete_ctrls`.

Keep `COM_OP_KINDS` as the **full known registry** for `servedBy` classification; first-wave is `COM_FIRST_WAVE` used for execute + capabilities `opKinds`.

### 2.3 Session copy: open, edit, save, export

Existing session open (`SessionStore.open_path`) already copies the user file under `sessions/<id>/source/`. Apply must:

1. Copy that source (or candidate artifact) to `work/<runId>/opened<suffix>` so Hancom never holds the canonical session file as `--file` if `--save-as` is omitted by a bug.
2. `--file` = opened copy, `--save-as` = `work/<runId>/edited<suffix>` (must differ).
3. Optional `--export-pdf` = `work/<runId>/native.pdf` or `candidates/<runId>/export.pdf` written **before** receipt so both files can be hashed.
4. `_atomic_move` edited file to `artifact<suffix>`.
5. Delete work dir on success; rmtree run dir on failure (existing `apply_plan` try/except).

`set-cell` CLI in com_backend is a **one cell = one session** workaround (T28). First-wave `set_cell` inside `edit` is acceptable if the plan has a single `set_cell`, or if engine `op_set_cell` is documented as safe in-batch. If live smoke shows table-entry drift, the Runtime should spawn `com_backend set-cell` once per op instead of one `edit` batch — that is a follow-up, not a silent mix.

### 2.4 Receipt native evidence

Today `evidence.class = structural_only` is correct for preedit. After COM apply, do **not** upgrade that to a renderer certificate.

Honest COM receipt additions:

- `backend: "com"`
- `steps`: one row (or one per op if you split children) with `subcommand: "edit"`, `exitCode`, parsed `results` from stdout (strip equation source if the engine already avoids echoing LaTeX in errors).
- `candidate` sha256/bytes of `--save-as` output (existing).
- `evidence.class`: `"native_com_session"` (new closed token) **or** keep `structural_only` plus `native: { postInspect: …, pdf: {sha256, bytes, path} | null }`. Prefer an explicit class so clients do not read COM as “no native contact”.
- `evidence.note`: COM `post_inspect` is Hancom’s inspect of the open document, not `visual_verify`, not a rematch certificate, not page rasters.
- If PDF exported: hash the PDF; `producedBy: engine/scripts/com_backend.py edit --export-pdf`. This is export evidence, not M5 frontend fidelity.
- Residue `checks` still run offline on the HWPX/HWP bytes. A COM edit of `.hwp` may not be zip-profileable; `check_residue` unavailable must remain `unavailable`, never a pass (`verification_report`).

`read_receipt` already re-hashes the candidate; extend it to re-hash optional PDF sidecar if the receipt binds one.

---

## 3. Tests without Hancom, and one live smoke

### 3.1 Fakes (CI, no Office)

Mirror `tests/test_runtime_render.py` / convert plumbing: monkeypatch `rt_convert.hancom_facts`, `running_hancom_processes`, and `EngineTools.com_edit_run` / `run_child`.

Minimum cases:

1. **Capabilities:** on fake `hancom_facts state=no`, `backends.com.state == unavailable` and `reason` is the probe string, not “not executed by this build”. On fake `state=yes` plus script present, `state == available` and `opKinds` == first wave.
2. **Propose refused when unavailable:** `backend: com` → `capability_unavailable` or `unsupported_backend` with data naming the missing fact (pyhwpx / ProgID / not Windows).
3. **Propose accepted when fake-available:** first-wave op; plan `backend == "com"`; `opsHash` includes backend so the same ops on preedit hash differently.
4. **Foreign mix:** `com` plan with `fill_cell` refused.
5. **Apply fake child:** stub writes `--save-as` bytes and prints `{ok:true, results, saved, pdf:null, post_inspect:{}}`. Assert session source hash unchanged, candidate published, receipt `backend=com`, `evidence` native fields present, `kill-stale` absent from argv.
6. **Busy:** fake `Hwp.exe` → apply `com_busy`, no candidate dir.
7. **Timeout / non-zero:** `backend_refused`; no receipt.
8. **Save-as equal to file:** if the Runtime ever generated it, refuse before spawn (engine would `_die`; better not to start COM).
9. **xml still unserved:** `backend: xml` unchanged.
10. **preedit regression:** existing `test_runtime_plan.py` / apply / parity still pass with probe=no.

Do not import `pyhwpx` in unit tests. Do not call real `com_backend.py edit`.

### 3.2 One live smoke (Hancom required)

Operator machine: Windows, pyhwpx, registered ProgID, **no other Hwp.exe**.

Procedure (manual or `@pytest.mark.live_hancom` skipped by default):

1. Copy a tiny corpus `.hwpx` into a temp `--root` via `cli.py open` (session copy).
2. Record source sha256.
3. `propose --backend com` with a single `replace_all` (or one `set_cell` on a known empty addr) that cannot hit protected form chrome.
4. Host `approve` + `apply`.
5. Assert original user path (outside session) unchanged; session source sha256 unchanged; candidate artifact exists; receipt binds sha256; `post_inspect` or grep of unzipped XML shows the new text.
6. Optional: reopen candidate in Hancom by hand. Do **not** require `visual_verify` or certificates.

If Hancom is busy, the smoke must refuse, not kill.

---

## 4. Risks and freeze rules

**Product / vision (`docs/plans/cli-first-product-vision.md` §4, §7):**

- Five interfaces stay coherent: addresses, **declared** backend capabilities, versioned CLI, skills on public tools, frontend must not bypass gates. COM apply stays **host** (`plan/apply`), same as convert.
- Capabilities must distinguish invalid args, unsupported, failed validation, and success-with-rejected-gate (CLI 0/2/3/4 already). Do not collapse “Hancom missing” into “plan invalid”.
- Preserve unknown content or refuse with detail. First-wave is a support boundary, not “all OPS”.
- M3 is catalog + native fixtures; this slice is **not** M3 completion. M5 frontend follows a stable CLI contract. **Renderer / rematch / certificate freezes remain:** “M5 may require a narrowly defined, evidence-backed unfreeze… do not … violate the freeze now” (§7). COM `post_inspect` and optional PDF export are not an unfreeze of `visual_verify` two-pass or certificate composite.

**Master plan / AGENTS:** one explicit Hancom COM owner; uncertain native side effect is recovery-required, not blindly replayed. Native edits on copies only. No `--kill-stale`.

**Protocol:** no second editing engine; mutations terminate in shipped scripts. One plan, one backend. Source immutability (`--save-as` ≠ `--file`). Fail closed. Explicit unavailable. COM batch is one subprocess; cancellation mid-edit is T21. Descendant containment still `not_established`.

**Catalog drift:** Runtime `COM_OP_KINDS` missing `page_numbers`/`set_header` — fix classification when touching `rt_plan.py`, even if those ops stay unimplemented.

**`.hwp` binding:** protocol Q3 — `form_hash` is zip-oriented; whole-file sha256 already binds plans (`boundSha256`). Residue may be unavailable; do not fake it.

**Picture paths / hyperlinks:** COM can reach the filesystem; keep argv under session work.

**CI lying:** a constant `available` on Windows developer laptops would break Linux CI propose tests if `SUPPORTED_BACKENDS` grows unconditionally. Probe injection is part of the change set.

---

## 5. Ordered Cursor tasks (≤6)

Each task: owned paths, acceptance command. No Hancom in 1–5.

**T1 — Honest COM capability probe**  
Owned: `runtime/scripts/rt_core.py`, `runtime/scripts/rt_engine.py`, `runtime/scripts/rt_convert.py` (reuse `hancom_facts` only; no convert behavior change).  
Acceptance: `python -m pytest tests/test_runtime_cli.py tests/test_runtime_module_check.py -q -k "capabilit or doctor or module"` plus a new `tests/test_runtime_com_probe.py` asserting `backends.com.state/reason` follow a patched `hancom_facts`.

**T2 — Propose/validate first-wave `com` plans**  
Owned: `runtime/scripts/rt_plan.py`, `runtime/scripts/rt_codes.py`, `tests/test_runtime_plan.py`.  
Acceptance: `python -m pytest tests/test_runtime_plan.py tests/test_runtime_parity.py tests/test_runtime_mcp.py -q` with probe patched so CI still refuses execute; new cases for first-wave propose when `RIGORLOOM_TEST_COM=1` fake-available helper.

**T3 — Apply dispatcher: one `com_backend edit` child on work copies**  
Owned: `runtime/scripts/rt_apply.py`, `runtime/scripts/rt_engine.py`.  
Acceptance: `python -m pytest tests/test_runtime_apply_retry.py tests/new_test_runtime_com_apply_fake.py -q` — fake child writes save-as; argv has `edit`, `--save-as`, no `--kill-stale`; source bytes unchanged.

**T4 — Receipt native evidence + busy/timeout refusals**  
Owned: `runtime/scripts/rt_apply.py` (receipt `evidence`), maybe `rt_codes.py` if new error tokens.  
Acceptance: fake tests for `com_busy`, timeout, receipt `bodySha256` still matches; `python -m pytest tests/test_runtime_com_apply_fake.py -q`.

**T5 — CLI exit mapping + docs comment sync in code only if tests require**  
Owned: `runtime/scripts/cli.py` (only if new error codes need USAGE vs REFUSED), `tests/test_runtime_cli.py`.  
Acceptance: `python runtime/scripts/cli.py --root <tmp> capabilities` JSON shows `backends.com`; propose com when unavailable → exit 3.

**T6 — Live smoke (operator machine, not CI)**  
Owned: `tests/live/test_com_edit_smoke.py` (skip unless `RIGORLOOM_LIVE_HANCOM=1`) and a one-page operator note **outside this repo if policy forbids committing live tests** — if the test cannot land, the task is a documented command line using existing CLI against a corpus copy.  
Acceptance: `RIGORLOOM_LIVE_HANCOM=1 python -m pytest tests/live/test_com_edit_smoke.py -q` **or** the documented `cli.py open/propose/approve/apply/receipt` sequence; original file hash unchanged.

---

End of A1. No repository files were modified.
