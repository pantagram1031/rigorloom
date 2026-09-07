# Card 4 — Korean mixed-format E2E on an installed build

**Status: NOT RUN.** This file is the runbook and evidence contract. Nothing in
`qa/` can execute it. A renderer IoU, a `smoke.ps1` phase, a `devMock` replay or
`MOCK-AGENT-0001` output is **not** card-4 evidence. PASS is a human verdict on
the artifacts listed here, produced on a real Windows install of the product
tip.

What PASS requires (from `docs/research/claude-research-vs-completion-cards-20260906.md`):

> Real install; mixed formatting, long paragraphs, tables;
> edit → undo/redo → AI review → save → reopen. Not renderer score / mock-only.

## 0. Product tip and harness tip are different branches

The harness (`qa/`) lives on PR #337 and its descendants. The product under test
is the desktop tip: PR #340 `claude/same-run-offset-range-text` (head `02d8ffe`
on 2026-09-07), stacked on #339 (draft fence) → #336 → #333 → #330 → #221. Put
the product SHA in `job.json` `sha`; the harness records it, it does not check
it out for you.

```powershell
git fetch origin
git rev-parse origin/claude/same-run-offset-range-text   # -> product_sha
```

## 1. Fixture requirements

A card-4 fixture is a Korean `.hwpx` that has, all at once:

| Requirement | Threshold | Why |
| --- | --- | --- |
| tables | ≥ 1 `hp:tbl` | table-cell edit (`own_cell` / fill seat) |
| mixed-format paragraphs | ≥ 1 paragraph with > 1 distinct `charPrIDRef` | run-scoped edit must pick the selected run only |
| long paragraph | ≥ 200 characters in one paragraph | forces ≥ 4 wrapped lines on an A4 body; the edit lands on a wrapped line |
| Hangul | ≥ 200 Hangul characters | IME composition must be exercised on real Korean |

Check any candidate with:

```powershell
python qa/card4_prep.py probe --hwpx <path>     # exit 0 eligible, 3 not, 2 error
```

**Checked-in default:** `tests/corpus/forms/converted/kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx`
(sha256 `8335dc716e7ff4908e3bae07e2a2512345353685fd40819b5429f542a8a80671`).
Probe on 2026-09-07: 752 paragraphs, 42 tables, 243 distinct charPr,
144 mixed paragraphs, longest paragraph 220 chars, 5401 Hangul chars. It is
already the desktop smoke's seated corpus, so the shell is known to open it.
It is a public 창업진흥원 form, so it is safe to keep in the repo.

Other checked-in fixtures that also pass the probe:
`moel-pyojun-geunrogyeyakseo-2013.hwpx`, `saeopja-deungnok-sinchengseo.hwpx`,
`jumin-deungchobon-sinchengseo.hwpx`. `admrul-*`, `gianmun-*`, `jeongbo-*`,
`nrf-*`, `moel-*-2025` fail the long-paragraph threshold.

**Operator-supplied fixture:** if the run must use a private document, do not
commit it. Put its path in `job.json` `metadata.card4_fixture`; the harness
records the sha256 and the probe stats in `c4-fixture-probe.json`, which is
enough to identify the file later without shipping it.

## 2. Run the prep harness

```powershell
# job.json: cards ["c4"], sha = product_sha, evidence_dir = work/qa/c4-<date>
python qa/run_cards.py --job qa/job.card4.example.json --workspace .
# or
pwsh -ExecutionPolicy Bypass -File qa/Run-Cards.ps1 -JobFile qa/job.card4.example.json -WorkspaceRoot .
```

This writes, under `evidence_dir`:

| File | What |
| --- | --- |
| `preflight.json` | OS, disk, tools, harness SHA |
| `c4-fixture-probe.json` | fixture sha256 + structural stats + eligibility |
| `c4-manifest.json` | the evidence skeleton (below). Never overwritten once present |
| `c4-manifest-check.json` | completeness check of the manifest (`EVIDENCE_INCOMPLETE` until filled) |
| `c4.jsonl`, `verdict.json` | verdict `NOT_RUN`, `gui_ime_claimed: false` |

## 3. The GUI steps (operator, on Windows, installed build)

Build and install the product tip first. `desktop/scripts/build-clean.ps1`
produces the installer; the installed EXE — not `npm run tauri dev` — is the
thing under test. Record `install.exe_path`, `install.installer_path`,
`install.sidecar_path` and `hashes.exe` (`Get-FileHash -Algorithm SHA256`) in
the manifest. Write `install-manifest.json` with the same three paths and hashes.

Every step: one screenshot, saved into `evidence_dir` under the exact artifact
name from the manifest. Queue snapshots (`queue-NN.json`) are the review-queue
state; copy it from the app's report or the sidecar log for the same run.

| Step | Do | Evidence | Fails if |
| --- | --- | --- | --- |
| s0_install | Launch installed EXE. Entrance screen | `shot-00-entrance.png`, `install-manifest.json`, `hashes.exe` | dev build, or hash not recorded |
| s1_open | Open the fixture. 구조 tree counts equal runtime counts | `shot-01-open.png`, `hashes.fixture` | counts differ; fixture hash ≠ probe hash |
| s2_edit_mixed | In a paragraph the probe calls mixed (> 1 charPr), click ONE run, type Korean through the IME with scan codes (`desktop/scripts/ime.ps1` style, never Unicode injection), Enter | `shot-02-edit-mixed.png`, `queue-02.json` | shell refuses `multi_run` / `run_text_differs`; op targets more than the selected run |
| s3_edit_long | In the ≥ 200-char paragraph, place the caret on a wrapped (non-first) line, type, Enter | `shot-03-edit-long.png`, `queue-03.json` | refusal, or op offsets do not match the displayed text (#340 finding 1) |
| s4_edit_table | Click a table cell seat, type, Enter | `shot-04-edit-table.png`, `queue-04.json` | op does not name the cell |
| s5_undo | Undo tier one (remove last queued op). Then approve + apply one op and undo tier two (되돌리기 제안 appears in the queue) | `shot-05-undo.png`, `queue-05.json` | redo stack empty after tier one; tier two produces no proposal or reports `undoError` |
| s6_redo | Redo. Queue equals `queue-04.json` again | `shot-06-redo.png`, `queue-06.json` | queue differs |
| s7_ai_review | Type an instruction in the composer with a REAL provider configured (not `MOCK`). Agent Host proposal lands in the same review queue. Human approves one op and rejects one (or `mock_approved` artifact in unattended QA test runs) | `shot-07-ai-proposal.png`, `shot-07-ai-decision.png` (or `c4-mock-approval.json`), `agenthost-events.jsonl` | agent could approve its own plan; proposal lands anywhere but the queue; provider was MOCK without mock_approved mode |
| s8_save | Apply, export candidate. Receipt shows source sha256 unmoved and candidate sha256 | `shot-08-receipt.png`, `receipt.json`, `hashes.saved`, `files.saved` | source hash moved; candidate hash ≠ file on disk |
| s9_reopen | Quit the process (check Task Manager: no `rigorloom-desktop.exe`, no sidecar). Relaunch cold. Open the saved file. All three edits and the approved AI op visible | `shot-09-reopen.png`, `hashes.saved_reopened` | reopen hash ≠ save hash; an edit missing |

Draft-fence check (card 2, rides along): during s7, while the agent is still
streaming, type into a seat. The typed draft must survive the agent's plan
arriving. Note the outcome in `steps[s7].note`.

### 3.1 Unattended QA Harness: `mock_approved` mode (W0 Item 8)

For unattended CI / Cloud Agent evidence runs where no human operator is at the console:
- `job.json` may specify `"approval_mode": "mock_approved"`.
- The harness wires `approval/resolve` into plan apply gating using a deterministic mock resolution.
- Step `s7` accepts `c4-mock-approval.json` created by `qa/approval.py` (which strictly records `is_mock_approved: true`, `is_human_approved: false`, and `gui_claimed: false`).
- **Strict Invariant**: `mock_approved` mode is exclusively for plan apply gating in tests/harness. It **never** claims GUI/IME PASS, and card-4 verdicts remain `NOT_RUN` with clear notes: real human operator approval and an installed Windows desktop runner are required for certified completion.

## 4. After the run

```powershell
python qa/card4_prep.py validate --manifest work/qa/c4-<date>/c4-manifest.json
```

`EVIDENCE_COMPLETE` means every step is `DONE`, every artifact exists, every
recorded hash matches disk, and reopen hash == save hash. It is still not PASS.
The coordinator reads the screenshots and the receipt and writes the verdict
into the card ledger by hand, citing `evidence_dir` and `product_sha`.

Anything that shortcuts a step — a mock provider, a `tauri dev` build, a
screenshot from `smoke.ps1`, a renderer score — leaves the card at NOT_RUN.
