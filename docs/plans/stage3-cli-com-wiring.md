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
- [x] S2+S3 done together (grok-4.6-xhigh, 18 min, 172k in / 54k out / 4.6M cache; 35 + 112 tests green; committed 1bc5ae8). Follow-up f043275: the bounded child env lacked `ProgramData`, which Hancom's COM server needs — found by bisecting the environment against a manual replay; one variable fixes it.
- [x] S5 live smoke recorded 2026-09-16 on this PC (Hancom 13.0.0.2986, pyhwpx): `open` 소논문_기본양식.hwpx (source sha 21ddd062…) → `propose --backend com` (replace_all 논문제목→title, goto_text "I.  서론", insert_text) → `request-approval` → `approve` → `apply` rc 0. Candidate `artifact.hwpx` 54,244 bytes sha256 4309bef10e17102bcd198eb30686e6a92c776c6c464c4d333ea87c637465df52; receipt `backend: com`, `evidence.class: native_com_session` with `post_inspect`; title replaced and sentence present in the candidate; session source hash unchanged; residue checker honestly reports the form anchors still present (partial edit, `acceptance: false`); no Hwp.exe left running.
- [ ] S2 (superseded, see above) COM child adapter: `EngineTools.com_edit_run(argv)` (serialized, bounded, no kill-stale, busy check via
      the existing process probe), ops-file writer for the engine's JSON shape. Owned: `rt_engine.py`,
      `rt_convert.py` (reuse probe), new `tests/test_runtime_com_adapter.py`.
- [ ] S3 COM apply + native receipt: `apply_plan` branches on `plan.payload["backend"] == "com"`: opened copy →
      one `edit` batch → save-as → optional export-pdf → residue checks on bytes → receipt with
      `native_com_session` evidence. Owned: `rt_apply.py`, `rt_apply_once.py`, new `tests/test_runtime_com_apply.py`.
- [x] S4 cross-surface regression: parity/authority/mcp suites (112 tests) green after S2+S3; xml stays unserved.
- [ ] S5 opt-in live smoke: `tests/test_runtime_com_live.py`, default skipped; one recorded run on this PC with
      a `replace_all` + `insert_text` plan on 소논문_기본양식.hwpx; receipt and candidate hashes pasted here.
- [x] S6 README status row flipped (commit below) "Runtime CLI … Hancom backend not yet wired" once S5 is recorded.
- [x] S7 xml backend routed (2026-09-17). Started on Antigravity claude-sonnet-4-6 (24.5 min, quota killed it at
      46/50 tests), finished by cursor-grok-4.6-high-fast S7b (13.5 min, 436k in / 35k out / 3.0M cache): the real gap
      was `RuntimeCore.plan_apply` refusing `xml` before the apply branch ran. First wave = goto_text, insert_text,
      replace_all, insert_blank_before, set_line_spacing, page_binding, insert_table, insert_picture, insert_equation;
      boxed equations surface `equation_box_unsupported_xml` as `backend_refused`. `EngineTools.xml_edit_run` →
      `xml_backend.py --file/--ops/--save-as --json`; capability `backends.xml` = available with `proofGrade:
      structural` when the script resolves. Receipt `backend: xml`, `evidence.class: structural_only`, `evidence.xml
      {proofGrade, wellFormed}`. Fable hardening: the child never asserts well-formedness, so `rt_apply` now parses
      every `*.xml` part of the candidate itself and refuses (`xml_not_well_formed`, nothing published) when one fails;
      test `test_fake_xml_malformed_candidate_is_refused_not_published`. Recorded e2e on this PC without Hancom:
      `open` 소논문_기본양식.hwpx → `propose --backend xml` (replace_all 논문제목→"XML 스모크", goto_text "I.  서론",
      insert_text) → approve → apply rc 0, run 73920efcd67b41b38593a6f86640a703, candidate 48,844 bytes sha256
      7b2f7cd16997e49f63409e71d45dcf6159e322e0639af940481918f361a92c5f, source sha unchanged, residue checker
      honestly `acceptance: false` on the unfilled form. Suites: 128 passed (xml/com/capability/plan/cli/parity/
      authority/mcp/cleanroom), py_compile 140/0. Not done: `runtime/README.md` still says preedit-only.

## Ledger

| When | What | Result |
|---|---|---|
| 2026-09-17 03:50 | S8 core-value loop on the REAL report (Fable, CLI only): `open` reports/report-auralab-classroom/output/out.hwpx (1,268,501 B, sha f95f4f73…) → `propose --backend com` replace_all "교육용 2.5D" → "교육용 2.5D(CLI 편집 확인)" (plan d644b882…, hash e7b70b9c…) → `request-approval` → `approve` → `apply` rc 0 | candidate d386c5fc… `artifact.hwpx` 1,276,215 B sha 60e26aff…, canonical; receipt `backend: com`, `evidence.class: native_com_session`, Hancom post-inspect 20 pages / 8 equations / 12 pictures / 19 tables, text preview shows the edit; source sha unchanged; 2 occurrences in the candidate XML. `render-prepare --run` converted via com_backend (PDF 1,159,410 B) and `render --page 0` rasterised page 1 (grade hancom, proofGrade none as designed): edit visible in the abstract, page number and box intact → docs/demo/cli-com-edit-page1.png. Honest limit found: `check_residue` reports `acceptance: false` on an already-assembled report because ordinary words (이름, 부재, 학번) match form anchors; a residue declaration (`--declares-file keep`) is the intended remedy, not a checker change |
| 2026-09-17 04:15 | S9 bound form profile (cursor-grok-4.6-high-fast, 15.5 min, 195k in / 50k out / 9.2M cache; commit 60166a5): `open --form-profile F | --form FORM` binds the session to the blank form's inventory; inspect forbidden, keep inventory and receipts carry `residue.profileSource` (bound_form | self_derived) + sha256; 132 runtime tests + compile sweep green (Fable) | On the real AURALAB report (xml backend): self-derived 163 hard residues → bound form 2 hard (the real labels 학번/이름 left blank on purpose) → with `--declares-file {"keep": ["학번","이름"]}` **acceptance true**, residue 0, forbidden 13 / kept 12, receipt `residue.profileSource: bound_form`. The gate still bites when guide text survives (tested). Candidate 1,268,356 B sha 1c2c8b59… Follow-up: the receipt does not echo the keep declaration itself (plan carries it); worth surfacing later |
| 2026-09-17 04:35 | S10 (cursor-grok-4.6-high-fast, 18 min, 18k in / 4k out / 1.5M cache): receipts echo `residue.declaration` from the plan (tested); desktop can bind a blank form at open (Home / titlebar / toolbar 양식 연결 → `workspace/openPath` formProfile|form; recents remember the binding with a 양식 tag), 자세히 popover shows 판정 기준 (연결된 양식 sha | 문서 자체 추정), ReceiptPanel shows profileSource + keep list, 검토 hint for finished documents without a bound form (informational). Runtime suites 79 green, desktop 193 → 199, Home recaptured and reviewed | commit below |

