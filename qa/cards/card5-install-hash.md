# Card 5 — install-candidate hash verification

Exact source / EXE / sidecar / installer SHA-256 must be **linked** and
verified **outside the checkout**. A renderer score, a mock, or a local
`target/` build inside the clone is not an install candidate.

This script never labels GUI, IME, or Windows install PASS.

## Run entry

```bash
python qa/install_candidate_hash.py
python qa/install_candidate_hash.py --json-out qa/_artifacts/card5-hashes.json
```

```powershell
# evidence dir is required for anything other than an honest NOT_RUN
$env:RIGORLOOM_CARD5_EVIDENCE_DIR = 'D:\rigorloom-card5-evidence'
powershell -ExecutionPolicy Bypass -File qa\install_candidate_hash.ps1
```

There is **no default machine path**. Do not commit a user-profile directory.
Set `--evidence-dir` or `RIGORLOOM_CARD5_EVIDENCE_DIR`.

## What PASS requires

All four roles, collected outside the checkout, bytes still on disk in that
evidence directory, SHA-256 recomputed and equal to the recorded digests,
source git SHA (and/or source-tree SHA-256) equal to the product tip under
test:

1. **source** — `gitSha` of the product tip and/or `sourceTreeSha256`
2. **exe** — packaged `Rigorloom.exe`
3. **sidecar(s)** — at least `rigorloomd.exe` from the PyInstaller one-dir
4. **installer** — NSIS `*setup.exe` from `npx tauri build`

JSON-only hash lists (no bytes to re-hash) stay **NOT_RUN**. Evidence inside
the git checkout stays **NOT_RUN**. Collect mode never PASSes; run verify.

## Evidence directory layout

```text
<evidence-dir>/                 # outside the clone
  card5-evidence.json
  files/
    Rigorloom.exe
    rigorloomd.exe
    Rigorloom_0.1.0_x64-setup.exe
```

`collectedOutsideCheckout` must be `true`. `gui_ime_claimed` / `install_pass`
must stay false.

## Windows / Antigravity bot (still required)

This Linux cloud VM does **not** build the Tauri EXE, sidecar, or NSIS
installer. Those steps are **NOT_RUN** until a Windows machine:

1. Checks out the product tip SHA recorded in the evidence manifest.
2. Runs `desktop/scripts/build-clean.ps1` (sidecar → frontend → `npx tauri build`).
3. Copies `Rigorloom.exe`, `resources/rigorloomd/rigorloomd.exe`, and the NSIS
   `*setup.exe` into an evidence directory **outside** the clone.
4. `python qa/install_candidate_hash.py collect --evidence-dir <dir> --exe ... --sidecar ... --installer ... --outside-checkout --copy-into-evidence`
5. `python qa/install_candidate_hash.py verify --evidence-dir <dir> --json-out <dir>/card5-verify.json`

Card 4 (Hancom COM / Korean IME E2E) is a later device loop on that hashed
install. It is out of scope here and remains NOT_RUN.

## This tip vs other QA PRs

#337 `run_cards.py`, #341 card4 prep, and #347 `mock_approved` are **not** in
this tree. Do not pull those branches. A future restack can add a `c5` arm
that shells out to `qa/install_candidate_hash.py`; `qa/job.card5.example.json`
is the job stub for that.

## Verdicts

| status | when |
| --- | --- |
| PASS | all four roles present, outside checkout, hashes match |
| NOT_RUN | evidence dir missing, bytes missing, or collection still a draft |
| FAIL | hash mismatch, source SHA mismatch, or a GUI/IME/install claim in the manifest |

`installCandidatePass` is true only when `status` is PASS.
