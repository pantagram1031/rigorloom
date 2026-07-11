# Independent naturalness and overcorrection review

You did not write the candidate. Do not delegate and do not edit it. Compare the
raw and proposed paragraph in its section and resolved writing profile.

Check only observable residual problems and overcorrection: forced literary
metaphors, fake informality, unnecessary hedging, erased formal precision,
uniform rhythm that remains unresolved, or a rewrite much broader than the
stated reason.

Return JSON only:

```json
{
  "paragraph_id": "p0004",
  "verdict": "accept|rewrite|rollback",
  "naturalness": "high|med|low",
  "over_polish": false,
  "signals": [],
  "reason": "..."
}
```

Use `rollback` for severe over-polish, `rewrite` for a bounded second attempt,
and `accept` only when the change is both necessary and proportionate.
