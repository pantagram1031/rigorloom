# Humanization workflow

The pipeline treats humanization as conservative editing, not detector evasion.
It is portable across agents and optional services.

## One-time local setup

Run `python scripts/setup_profile.py`. This creates
`.local/user-profile/writing_preferences.json`, which is ignored by Git. Do not
place private examples or identity data in repository-tracked files.

## Stage 4 commands

```sh
python pipeline/scripts/humanization_ctl.py prepare <WS>
# Run ai_tell_review.md and humanize.md with an available agent or Pantadex.
python pipeline/scripts/humanization_ctl.py apply <WS> \
  --changes <WS>/work/stage-4/scratch/humanization_changes.json
```

`prepare` creates the immutable raw draft and stable paragraph ids. `apply`
rejects stale paragraph text, writes the candidate, runs deterministic fidelity,
and restores the raw draft when protected content changes.

Manual validation and rollback are also available:

```sh
python pipeline/scripts/humanization_ctl.py validate <WS>
python pipeline/scripts/humanization_ctl.py rollback <WS>
```

Canonical reports are `bundle/ai_tell_review.json`,
`bundle/humanization_report.json`, and `bundle/prose_fidelity.json`. Proposed
changes remain stage scratch and are archived after completion.
