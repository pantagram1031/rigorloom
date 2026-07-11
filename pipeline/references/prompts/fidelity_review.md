# Independent semantic fidelity review

You did not write the candidate. Do not delegate and do not rewrite it. Compare
the immutable raw paragraph with the proposed paragraph after the deterministic
controller's protected-token checks.

Check claim/conclusion direction, certainty, causal direction, actor retention
when voice changes, quantifier level, polarity, meaningful order, and factual
omission or addition. A surface-form change such as digits to words is not a
violation when the exact value is preserved, though the local deterministic
controller may apply a stricter project rule.

Return JSON only:

```json
{
  "paragraph_id": "p0004",
  "verdict": "accept|rewrite|rollback",
  "findings": [
    {"item": "causal_direction", "severity": "high", "reason": "..."}
  ]
}
```

Any deterministic failure requires rollback regardless of your verdict.
