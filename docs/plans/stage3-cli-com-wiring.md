# Stage 3 — make the Hancom COM backend executable from the Runtime CLI

Status: ACTIVE 2026-09-16. Owner: Fable. Source analyses: `scratchpad/a1/stage3-com-wiring-*.md`
(gpt-5.6-sol-high-fast and cursor-grok-4.6-low-fast, read-only A1 task; both agree on the routing facts below).

## Facts (verified by both notes, file:line as of c862943)

- `rt_core.plan_apply()` (`rt_core.py:509–553`) → `rt_apply.apply_plan()` (`rt_apply.py:198–340`): every op is
  translated by `_argv_for()` into a `preedit` subcommand and run through `EngineTools.preedit_run()`
  (`rt_engine.py:435–453`). The plan's `backend` field is copied to the receipt (`rt_apply.py:273`) but never
  selects a child. Receipt evidence is hard-coded `structural_only` (`rt_apply.py:310–314`).
- `capabilities.backends.com` is a constant `{state: unavailable, reason: "declared by the protocol; not executed
  by this build"}`; the honest host probe already exists as `rt_convert.hancom_facts()` (`rt_convert.py:78–110`,
  Windows + pyhwpx + registered ProgID) and feeds only `render.prepare`.
- `engine/scripts/com_backend.py` `edit --file --ops --save-as [--export-pdf]` is the batch entry the fill loop
  uses; `EngineTools` never resolves it. `xml_backend.py` is equally unserved (out of scope here).

## Rules that bind this stage

- No `--kill-stale`; refuse with `com_busy` when an `Hwp.exe` is live. One COM child per apply, one Hancom
  launch per batch. Session source file is never opened by Hancom directly: work on `work/<runId>/opened*`,
  save-as to a different path, atomic move to the candidate.
- Unit tests never import pyhwpx or start COM; they monkeypatch `hancom_facts`, the process probe, and the child
  runner. One opt-in live smoke gated by `RIGORLOOM_LIVE_COM=1`.
- Receipt stays honest: `backend: com`, new closed evidence class `native_com_session` (COM post-inspect is not a
  render certificate), optional exported PDF hashed as export evidence only. Renderer/rematch/certificate freeze
  untouched.
- `capabilities.backends.com.state` may be `available` only when `hancom_facts().state == "yes"` AND
  `engine/scripts/com_backend.py` resolves; `opKinds` then lists the first wave only.

## First-wave ops (7)

`replace_all`, `goto_text`, `insert_text`, `set_cell` (addr only, never raw traversal), `insert_equation`,
`insert_picture` (picture copied into the session work dir), `insert_hyperlink`. Everything else stays in the
known registry for `servedBy` classification but is refused for execution (`deferred`).

## Tasks (bounded, one Cursor session each, Fable runs acceptance)

- [x] S1 capability + plan contract (grok-4.6-xhigh, 17 min, 285k in / 50k out / 6.4M cache; 59 + 55 tests green; committed 80b87b9; `backends.com.state: available` on this PC with the seven first-wave opKinds): `backends.com` produced from `hancom_facts` + script resolution; `propose`
      accepts `backend: com` only when available and only first-wave ops; foreign-op mix refused; `opsHash`
      includes the backend. Owned: `rt_codes.py`, `rt_plan.py`, `rt_core.py`, `rt_engine.py` (capability only),
      `tests/test_runtime_plan.py`, `tests/test_runtime_cli.py`, new `tests/test_runtime_com_capability.py`.
- [ ] S2 COM child adapter: `EngineTools.com_edit_run(argv)` (serialized, bounded, no kill-stale, busy check via
      the existing process probe), ops-file writer for the engine's JSON shape. Owned: `rt_engine.py`,
      `rt_convert.py` (reuse probe), new `tests/test_runtime_com_adapter.py`.
- [ ] S3 COM apply + native receipt: `apply_plan` branches on `plan.payload["backend"] == "com"`: opened copy →
      one `edit` batch → save-as → optional export-pdf → residue checks on bytes → receipt with
      `native_com_session` evidence. Owned: `rt_apply.py`, `rt_apply_once.py`, new `tests/test_runtime_com_apply.py`.
- [ ] S4 cross-surface regression (test-only): parity/authority/mcp suites still pass; xml stays unserved.
- [ ] S5 opt-in live smoke: `tests/test_runtime_com_live.py`, default skipped; one recorded run on this PC with
      a `replace_all` + `insert_text` plan on 소논문_기본양식.hwpx; receipt and candidate hashes pasted here.
- [ ] S6 README status row flips "Runtime CLI … Hancom backend not yet wired" once S5 is recorded.

## Ledger

| When | What | Result |
|---|---|---|
