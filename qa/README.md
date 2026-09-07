# QA harnesses on the green tip-stack

Card 1 export-safety matrix and Card 5 install-hash verification live here.
They are script-owned: PASS / FAIL / NOT_RUN come from the script, not from
prose. Scripts never claim GUI, IME, or Windows-install PASS.

## Card 1

```bash
python qa/export_safety_card1_matrix.py --json-out qa/_artifacts/card1-matrix.json
```

Native force-quit is NOT_RUN on Linux. Windows:

```powershell
powershell -ExecutionPolicy Bypass -File qa\native_force_quit_export.ps1
python qa\export_safety_card1_matrix.py --json-out qa\_artifacts\card1-matrix.json
```

## Card 5

```bash
python qa/install_candidate_hash.py --json-out qa/_artifacts/card5-hashes.json
```

A checkout without `RIGORLOOM_CARD5_EVIDENCE_DIR` is **NOT_RUN**. See
[`cards/card5-install-hash.md`](cards/card5-install-hash.md).

## Cards 2–4

Product tests for cards 2–3 are under `tests/test_desktop_*.py`. Card 4 Korean
E2E prep (#341 / #347) is not in this tree. Runbook index:
[`cards/README.md`](cards/README.md).
