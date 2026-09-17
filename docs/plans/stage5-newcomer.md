# Stage 5 — Newcomer path (Linux/macOS, no Hancom)

Status: ACTIVE 2026-09-17. Owner: Fable. Goal: a stranger on Linux without Hancom succeeds in five minutes:
wheel build → `pip install` in a clean venv → `rigorloom open --path any.hwpx` on every corpus form → propose /
approve / apply on the xml backend → readable receipt. QUICKSTART.md (English + Korean) is written from what
actually ran, not from intent. Installer and xml gaps are fixed at the cause. Home's CLI 문서 link points at a real
page in the repo.

Environment for verification: WSL Ubuntu (`~/rigorloom-ci`, Python 3.12; no `ensurepip`, so clean venvs come from
`virtualenv`), fetched from the Windows repo (`git fetch /mnt/c/Users/user/dev/rigorloom <branch>`).

## Slices
- [x] N5a (2026-09-17 22:05, run by Fable's own WSL script after the Cursor lane could not reach WSL): wheel
      (`pip wheel --no-deps --no-build-isolation --no-index`) + three bundles (`package_module.py --module core|style|report`)
      + virtualenv + `pip install` + `rigorloom install --engine-root --bundles-dir` (must run from outside the checkout:
      the containment probe refuses a checkout cwd) → capabilities xml/preedit available, com unavailable (win32 only)
      → all 10 corpus forms: open → inspect → propose xml (goto_text anchor + insert_text) → request-approval → approve
      → apply, 1.9–3.9 s each, edit verified in the candidate XML, `acceptance: false` (blank forms keep their
      placeholders; honest). docs/QUICKSTART.md written from these commands (EN + KO).
- [ ] N5b QUICKSTART verified by replaying it line by line in a second fresh venv; Korean section; README link;
      Home CLI 문서 link → docs/QUICKSTART.md.
- [ ] N5c macOS notes (untestable here: say so) and a `rigorloom doctor` line that tells a newcomer what is missing.

## Ledger
| When | What | Result |
|---|---|---|
| 2026-09-17 22:05 | N5a Linux path 10/10 forms applied; QUICKSTART.md | Cursor lane (grok-high, 20 min) could not run `wsl` from its shell and looped on file reads; Fable ran the loop as a script. Rough edges → T19: installer message should say to leave the checkout; Home CLI 문서 link target |
