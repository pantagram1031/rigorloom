# Humanization contract

Humanization is a bounded, reviewable style edit. It is not permission to alter
facts or disguise authorship. Any capable agent or optional service may perform
the rewrite if it follows this contract.

## Fixed order

1. Write and fact-check `bundle/content.md`.
2. Run a level-fit review against the declared academic scope.
3. Run `humanization_ctl.py prepare`; this freezes `bundle/content.raw.md` and
   assigns stable paragraph ids.
4. Run an independent AI-tell/style-pattern review and save
   `bundle/ai_tell_review.json`.
5. Rewrite only paragraphs named by the review, using the lightest sufficient
   change, and return a `changes` JSON object.
6. Run `humanization_ctl.py apply`.
7. Accept only when `bundle/prose_fidelity.json` passes. The controller
   automatically restores the raw content on failure.
8. Re-review edited paragraphs. The operator profile and factual fidelity take
   precedence over any detector score.

## Change schema

```json
{
  "schema": "report-pipeline/humanization-changes-v1",
  "changes": [
    {
      "paragraph_id": "p0004",
      "reasons": ["repetitive transition", "uniform sentence rhythm"],
      "before": "Exact paragraph from humanization_report.json",
      "after": "Minimally revised paragraph",
      "confidence": 0.9
    }
  ]
}
```

The controller rejects unknown paragraph ids, stale `before` text, malformed
payloads, and protected-content drift.

## Protected content

- numbers, units, dates, percentages, and source ids;
- document tags, equations, URLs, Markdown links, and headings;
- uncertainty, bounds, negation, and logical qualifications;
- evidence relationships recorded in provenance.

Fidelity checks are deliberately conservative. If a protected expression needs
to change for a factual reason, revise the verified raw draft first, prepare a
new baseline, and rerun the humanization cycle.

## Review is not an AI detector gate

Detector scores are advisory. The review should cite observable prose patterns:
uniform sentence openings, excessive nominalization, generic transitions,
unsupported growth narratives, needless three-part lists, repeated paragraph
conclusions, unexplained specialist compression, or removal of real choices and
limitations. Formal writing is not itself a defect.

## Provider behavior

Use the first available `humanizer-chain` adapter. A missing optional service
never blocks the run: use another agent with the same prompt and schema. If no
rewrite backend exists, keep the verified raw content and record a skipped
humanization report; never invent a passing review.
