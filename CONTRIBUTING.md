# Contributing to Rigorloom

Thanks for considering a contribution. This document covers dev setup, the
review discipline this repo follows, and what a PR is expected to include.

## Dev setup

```sh
git clone https://github.com/pantagram1031/rigorloom.git
cd rigorloom
python3 scripts/bootstrap.py
python -m pytest pipeline/tests tests -q
```

`bootstrap.py` uses only the standard library and proves a fresh clone is
wired correctly (interpreter check, private profile setup, an end-to-end
smoke test). No Hancom, no Windows, and no model account are needed for this
step or for the test suite. Optional extras (`docx`, `studio`, `hwp`) are
listed with install hints at the end of `bootstrap.py`'s output; only install
what you need for the area you're changing.

## Review discipline

This repo treats its gates as the product, not scaffolding around it. That
shapes how changes get reviewed:

- **Adversarial review before merge.** Changes to gates, checkers, or the
  stage machine are expected to be reviewed looking for ways the new logic
  could be bypassed, fail open, or produce a false pass — not just whether it
  works on the happy path. Several changelog entries exist specifically
  because an adversarial pass found a fail-open or false-block bug after the
  initial implementation (see [CHANGELOG.md](CHANGELOG.md)).
- **Deterministic-gate philosophy.** Every gate in this pipeline is expected
  to resolve one of three ways:
  - A **provable break** (a fabricated citation, a mutated form, a missing
    required file) is **HARD** — it fails the gate, unconditionally.
  - An **uncertain** case (a reference that can't be verified offline, a
    render path with unmeasured fidelity) is **WARN** or an explicit,
    logged exception — never silently accepted as if it were verified.
  - Nothing passes silently. A gate's verdict is always visible in its
    output (exit code, JSON verdict, or both), never inferred from the
    absence of an error.
- **A false-blocking gate is worse than none.** A gate that HARD-fails valid
  work erodes trust and gets bypassed or disabled — which is worse than not
  having the check at all. If you're adding or tightening a HARD condition,
  show it doesn't fire on legitimate content (a test fixture, an existing
  workspace, or both), not just that it fires on the bad case it targets.

## PR expectations

- **Tests for every fix.** A bug fix without a regression test that would
  have caught it is not considered complete. New checkers or gate logic need
  both a positive (passes on good input) and negative (HARD/WARN on bad
  input) test case.
- **Full suite green.** `python -m pytest pipeline/tests tests -q` must pass
  before requesting review.
- **Privacy scan clean.** Run the privacy scanner over your changes and the
  repo as a whole; it must report 0 HARD findings:

  ```sh
  python pipeline/scripts/privacy_scan.py .
  ```

- **Docs updated.** If behavior, a gate contract, or a CLI flag changes,
  update the relevant doc under `docs/` (and `CHANGELOG.md`) in the same PR.

## Code style

Match the conventions of the file you're editing rather than introducing a
new style. In general:

- Standard-library-only for anything in the pipeline kernel path; optional
  dependencies belong behind the extras declared in `pyproject.toml`.
- Scripts fail closed and print an explicit, actionable error rather than
  guessing or silently defaulting.
- No personal data, credentials, private forms, or generated reports in
  commits — see [AGENTS.md](AGENTS.md) for what's intentionally excluded
  from this repository.

## Questions

Open an issue using the bug report or feature request template under
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/), or start with
[docs/golden-path.md](docs/golden-path.md) if you're not sure where a change
belongs in the stage graph.
