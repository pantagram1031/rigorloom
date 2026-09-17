# Stage 5 — Newcomer path (Linux/macOS, no Hancom)

Status: ACTIVE 2026-09-17. Owner: Fable. Goal: a stranger on Linux without Hancom succeeds in five minutes:
wheel build → `pip install` in a clean venv → `rigorloom open --path any.hwpx` on every corpus form → propose /
approve / apply on the xml backend → readable receipt. QUICKSTART.md (English + Korean) is written from what
actually ran, not from intent. Installer and xml gaps are fixed at the cause. Home's CLI 문서 link points at a real
page in the repo.

Environment for verification: WSL Ubuntu (`~/rigorloom-ci`, Python 3.12; no `ensurepip`, so clean venvs come from
`virtualenv`), fetched from the Windows repo (`git fetch /mnt/c/Users/user/dev/rigorloom <branch>`).

## Slices
- [ ] N5a Wheel + clean venv + all 10 corpus forms through `open`/`inspect`; one xml edit loop per form kind;
      record every refusal verbatim; fix causes in runtime/ or packaging; QUICKSTART.md draft.
- [ ] N5b QUICKSTART verified by replaying it line by line in a second fresh venv; Korean section; README link;
      Home CLI 문서 link → docs/QUICKSTART.md.
- [ ] N5c macOS notes (untestable here: say so) and a `rigorloom doctor` line that tells a newcomer what is missing.

## Ledger
| When | What | Result |
|---|---|---|
