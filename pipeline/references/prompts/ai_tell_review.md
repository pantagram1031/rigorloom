# AI-tell and prose-pattern review prompt

Read the report draft, request, academic-level constraints, and optional local
writing profile. Diagnose observable writing problems without guessing who or
what wrote the text.

Return JSON only:

```json
{
  "schema": "report-pipeline/ai-tell-review-v1",
  "verdict": "pass|revise",
  "findings": [
    {
      "paragraph_id": "p0004",
      "patterns": ["repetitive transition"],
      "evidence": "short excerpt",
      "minimal_direction": "vary the opening while preserving the claim"
    }
  ],
  "advisory_score": null
}
```

Check for repetitive sentence openings, uniform paragraph shape, excessive
nominalization, generic consultant language, unsupported growth narratives,
mechanical three-part lists, repeated conclusions, unnecessary English glosses,
and specialist language beyond the declared level. Do not propose changes to
numbers, equations, sources, uncertainty, scope, or logical direction.
