The style distribution module is enabled: bounded prose humanization
(translationese removal, voice consistency, form-rule compliance — never
AI-detection evasion) is available as the `humanize` CLI.

```
python modules/style/scripts/humanization_ctl.py prepare  ...   # stage a bounded edit plan
python modules/style/scripts/humanization_ctl.py apply    ...   # apply the staged plan
python modules/style/scripts/humanization_ctl.py validate ...   # fidelity gate: facts/numbers/equations unchanged
python modules/style/scripts/humanization_ctl.py rollback ...   # restore the pre-apply state
```

Contract: prepare → apply → validate is the only sanctioned path; edits are
bounded (fact/number/equation/citation content is invariant — the fidelity
audit rejects drift). `check_style` joins the check registry when this
module is enabled and gates style rules deterministically. Rollback is
always available; a validate rejection means rollback + re-prepare, never
hand-patching the applied text.
