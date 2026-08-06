# Style distribution module

The humanization stack as one optional distribution module (plan
`docs/plans/v0.16-unified-core-and-modules.md` §4.2): the bounded-edit
controller (`humanization_ctl.py`, surfaced as the `humanize` CLI command),
the deterministic fact-invariance gate (`prose_fidelity.py`, imported by the
controller as a sibling), and the deterministic prose/structure style checker
(`check_style.py`, registered in the check registry). Measurement roles follow
the variant-audit verdict recorded in `docs/humanization.md` ("Measurement
roles"): the humanizer persona pass is the transform, `prose_fidelity` is the
hard lock, detector scores are advisory only and never trigger a gate.

## Boundary

This module exists for **translationese removal, voice consistency, and
form-rule compliance — NOT AI-detection evasion.** It makes prose read the
way its author writes and keeps it inside the form's rules, while
`prose_fidelity` proves facts, numbers, citations, and equations survived
untouched. Nothing in this module optimizes against a detector, and detector
scores must never gate (the H2 advisory-only regression guards pin this).

## Rules come from packs, not code

The checker and controller ship neutral defaults only
(`pipeline/references/preference_packs/defaults/`). Any operator-specific
rule set — including the award-corpus-derived rulepack — is a **pack
instance** registered into a private profile root (a report-module /
personalization concern), never content of this module. A non-report user
supplies their own packs; the mechanisms here stay generic.

## Payload

```
scripts/check_style.py          registered checker (prose_rules / report_structure packs)
scripts/humanization_ctl.py     `humanize` CLI: prepare / apply / validate / rollback
scripts/prose_fidelity.py       deterministic fact-invariance audit (library + CLI)
references/agent.humanizer.template.md   humanizer worker template (skill fragment material, later slice)
tests/                          module tests (skipped unless 'style' is enabled)
```

Contract, enablement, and the module-script import mechanism:
`modules/README.md`. Usage of the controller: `docs/humanization.md` and
`pipeline/references/humanization_contract.md`.
