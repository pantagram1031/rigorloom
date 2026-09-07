# QA Unattended Evidence Collection Contract (`job.json`)

This directory implements the thin unattended QA contract for **Astra Pro FIRST_72H** evidence collection across completion cards.

The harness executes unattended verification runs against a specific commit SHA without running an administrative daemon, without inventing mock web servers, and without falsely claiming desktop/GUI verification.

## Architecture and Contract

The harness consists of:
1. `qa/job.schema.json` & `qa/job.example.json`: Specification and example for job configuration.
2. `qa/run_cards.py` & `qa/Run-Cards.ps1`: Dual Python / PowerShell sketches for:
   - Read-only environment preflight checks (OS, disk free, tools present).
   - Card execution (c1 export safety, c2 revision coherence, c3 run-scoped edit).
   - Evidence collection (preflight JSON, Junit XML, JSONL stubs, and verdict JSON).
3. `qa/verifier.py`: Deterministic exit-code mapping to `PASS`, `FAIL`, `NOT_RUN`, and `BLOCKED` statuses with zero false claims of GUI or IME success.

---

## `job.json` Fields

A valid `job.json` conforms to `qa/job.schema.json`:

| Field | Type | Description |
| :--- | :--- | :--- |
| `candidate_id` | string | Identifier for candidate artifact or milestone (e.g. `c1`, `c2`, `c3`, `candidate-alpha`). |
| `run_id` | string | Unique run identifier (e.g. `run-20260906-155000`). |
| `sha` | string | Full or abbreviated Git commit SHA under evaluation. |
| `allowed_commands`| array[string] | Explicit whitelist of commands or card identifiers permitted to run in this execution context. |
| `evidence_dir` | string | Path to directory where evidence artifacts (preflight JSON, test results, logs, verifier verdict) are written. |
| `cards` | array[string] | (Optional) List of card IDs targeted for execution (e.g. `["c1", "c2", "c3"]`). |
| `requested_model` | string | (Optional) Model slug for tracking agent orchestrator provenance (`gemini-3.8-flash`). |
| `approval_mode` | string | (Optional) `mock_approved` or `human_approved` (default). In `mock_approved` mode, plan apply gating is resolved for unattended card-4/agent paths without claiming human approval or GUI/IME PASS. |
| `metadata` | object | (Optional) Arbitrary key/value tags for run context. |

### Example `job.json`

```json
{
  "candidate_id": "c1",
  "run_id": "run-20260906-001",
  "sha": "5d955a3",
  "allowed_commands": ["c1", "c2", "c3", "pytest", "rustc"],
  "evidence_dir": "work/qa/evidence-run-20260906-001",
  "cards": ["c1", "c2", "c3"],
  "requested_model": "gemini-3.8-flash"
}
```

---

## How Loom Invokes It

Loom (or any unattended agent / CI runner) invokes the harness as a single standalone command without an ambient server:

### Python Invocation
```bash
python3 qa/run_cards.py --job qa/job.json --workspace .
```

### PowerShell Invocation
```powershell
pwsh -ExecutionPolicy Bypass -File qa/Run-Cards.ps1 -JobFile qa/job.json -WorkspaceRoot .
```

### Execution Flow:
1. **Preflight Probe (Read-Only)**: Collects OS version, disk free space, detected tools (`python3`, `pytest`, `rustc`, `cargo`, `pwsh`, `git`, `node`), and Git commit SHA. Writes `evidence_dir/preflight.json`.
2. **Whitelist & Card Dispatch**: Validates each requested card against `allowed_commands`.
3. **Existing Test Execution**:
   - `c1` (Card 1): Dest-preserving export safety (`tests/test_desktop_export_safety.py`, `engine/tests/test_hwpx_write_export_safety.py`, and `tests/desktop_export_safety_harness.rs`).
   - `c2` (Card 2): Revision coherence (`tests/test_runtime_revision_coherence.py`, `tests/test_desktop_revision_coherence.py`).
   - `c3` (Card 3): Run-scoped edit (`tests/test_desktop_run_scoped_edit.py`, `tests/test_desktop_revision_coherence.py`).
   If tests are absent at the checked-out SHA, status is deterministically recorded as `NOT_RUN`.
4. **Evidence Collection**:
   - Junit XML (`junit-<card>.xml`)
   - Logs (`<card>.log`)
   - JSONL records (`<card>.jsonl`)
   - Aggregate verdict (`verdict.json`)

---

## Deterministic Verifier & GUI/IME/Installer Policy

The verifier strictly maps execution status without claiming interactive success:

| State | Status | Criteria |
| :--- | :--- | :--- |
| **Success** | `PASS` | Process completed with exit code 0; test assertions held. |
| **Failure** | `FAIL` | Process returned non-zero exit code or failed assertions. |
| **Not Run** | `NOT_RUN` | Test files not present in checked-out tree, OR interactive desktop features requiring local environment. |
| **Blocked** | `BLOCKED` | Command not in whitelist, missing prerequisites, or execution errors. |

### Explicit Invariant: Windows GUI / IME / Installer are `NOT_RUN`
**Windows GUI, IME typing, and NSIS installer modes are explicitly classified as `NOT_RUN` until a dedicated local Windows desktop runner exists.**
- Unattended headless CI / Cloud Agent runners do not possess desktop interactive display contexts or Hancom COM/IME bindings.
- Under no circumstances does the verifier report `PASS` or simulate GUI/IME success in unattended mode.
- Any request for interactive cards (`c4`, `c5`, `gui`, `ime`, `installer`) automatically yields `NOT_RUN` with `gui_ime_claimed: false`.

### Card 4 (Korean mixed-format E2E): PREP only

`c4` runs `qa/card4_prep.py` and still yields `NOT_RUN`. The runbook, fixture
requirements and evidence contract are in `qa/cards/card4-korean-e2e.md`.

- `probe`: checks a fixture `.hwpx` for tables, mixed-`charPr` paragraphs, a
  >= 200-char paragraph and >= 200 Hangul chars; records its sha256.
  Default fixture: `tests/corpus/forms/converted/kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx`.
  Override with `metadata.card4_fixture` in `job.json`.
- `scaffold`: writes `c4-manifest.json`, the ten-step evidence skeleton the
  operator fills in on a real Windows install (never overwritten once present).
- `validate`: reports `EVIDENCE_COMPLETE` / `EVIDENCE_INCOMPLETE`. Complete is
  not PASS; PASS is a human verdict on the screenshots, receipt and hashes.

```bash
python qa/run_cards.py --job qa/job.card4.example.json --workspace .
python qa/card4_prep.py probe --hwpx <path>
python qa/card4_prep.py validate --manifest work/qa/<run>/c4-manifest.json
```
