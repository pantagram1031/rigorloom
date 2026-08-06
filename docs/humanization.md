# Humanization workflow

The pipeline treats humanization as conservative editing, not detector evasion.
It is portable across agents and optional services. Local independent workers
are the default; Pantadex is an optional adapter or comparison judge.

## One-time local setup

Run `python scripts/setup_profile.py`. This creates
`.local/user-profile/writing_preferences.json`, which is ignored by Git. Do not
place private examples or identity data in repository-tracked files.

## Stage 4 commands

```sh
python modules/style/scripts/humanization_ctl.py prepare <WS>
# Spawn a local advisory reviewer. PASS writes an empty skipped proposal.
# On REWORK, spawn a separate local rewriter, then independent reviewers.
python modules/style/scripts/humanization_ctl.py apply <WS> \
  --changes <WS>/work/stage-4/scratch/humanization_changes.json
```

`prepare` creates the immutable raw draft, stable paragraph ids, section labels,
and protected spans. A detector or scorer is advisory: it cannot select
paragraphs or force edits. On REWORK the rewriter inspects every prose paragraph
and returns only actual changes.

`apply` accepts v1 and v2 proposals. It rejects stale text, applies safe edits,
restores unsafe paragraphs individually, and emits `retry_paragraph_ids`. A
whole-document invariant failure restores the immutable raw draft. Light mode
warns above a 15% change rate; standard and strong warn above 30% and 45%.
Round 3 with unresolved paragraphs returns `hold_and_report`.

Manual validation and rollback are also available:

```sh
python modules/style/scripts/humanization_ctl.py validate <WS>
python modules/style/scripts/humanization_ctl.py rollback <WS>
```

Canonical reports are `bundle/ai_tell_review.json`,
`bundle/humanization_report.json`, and `bundle/prose_fidelity.json`. Proposed
changes remain stage scratch and are archived after completion.

## Measurement roles (variant-audit outcome)

Audited 2026-08-06; evidence and bench data in
`docs/research/variant-audit.md` ("Humanization measurement" row).

- **H1 humanizer transform — unchanged.** The humanizer subagent remains the
  transformation (operator-approved, fact-invariant). Real judgment stays with
  humanize_review / the humanizer persona pass, not with any score.
- **H2 detector scores — advisory only, never a gate trigger.** On the
  most-changed windpath section (similarity 0.747 pre→post, ~25% changed) the
  score read 0.1 both before and after: zero discrimination. No code path
  gates on it; `pipeline/tests/test_h2_advisory_only.py` pins that as a
  regression guard on the check registry.
- **H4 tone rulepack — pack-based regression check.** Its rules provably
  track real humanizer edits (bench 2b: conclusion_pivot 1→0).
  `modules/report/scripts/check_tone_rules.py` runs a tone-rulepack over
  `bundle/content.md` (WARN-only by default; a pack may escalate). The repo
  ships only the neutral default pack; the corpus-derived rulepack is a
  private profile pack instance (`personalization_ctl.py register-pack
  --type tone_rules`).
- **H3 humanize_metrics v2.0 — NOT adoptable** until its generator is
  located. The metric files exist only as snapshots; no generator is present
  in either repository (a server-side pantadex snapshot is suspected).
  Follow-up: locate the generator before considering adoption.

## Independence rules

- The prose-pattern reviewer and rewriter must be separate agent turns.
- The fidelity and naturalness reviewer must not be the rewriter.
- External audits are advisory; deterministic local failures always win.
- If the environment cannot spawn workers, record reduced independence and run
  the same roles sequentially.
- Human gates remain human-only.
