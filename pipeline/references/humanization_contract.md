# Humanization contract v2

Humanization is a bounded, reviewable style edit. It is not detector evasion,
authorship disguise, or permission to alter facts. The default implementation
uses independent local workers; Pantadex is an optional adapter and comparison
judge. Every backend returns the same portable artifacts.

## Safety findings behind v2

Formal-report scorers often measure register rather than authorship. Normal
nominalization and consistent formal endings can therefore produce false
REWORK results. A score is advisory: it may support review, but it may not
select paragraphs, force rewriting, or override a human writing profile.

When a pre-review returns PASS, preserve the entire draft. When it returns
REWORK, the rewriter inspects every prose paragraph, but returns entries only
for paragraphs it actually changes. This differs from detector-targeted v1
rewriting and prevents a noisy detector from deciding what must be edited.

## Fixed local-first order

1. Write and fact-check `bundle/content.md`.
2. Run a level-fit and logic review.
3. Run `humanization_ctl.py prepare`; this freezes `bundle/content.raw.md`,
   assigns stable paragraph ids, derives sections, and lists protected spans.
4. Run an independent prose-pattern reviewer. Its verdict and signals are
   advisory and must not become paragraph selectors.
5. PASS: return an empty v2 changes file with `gate.skipped=true` and apply it.
6. REWORK: spawn a separate `humanizer-rewriter` worker. Give it every prose
   paragraph, the resolved local profile, section, and protected spans.
7. Have a worker other than the rewriter review fidelity and naturalness.
   Annotate each proposal with `reviewer_verdict`.
8. Run `humanization_ctl.py apply`. The deterministic controller rejects stale
   text, rolls back only unsafe paragraphs, emits retry ids, and performs a
   whole-document audit.
9. Retry rejected or over-polished paragraphs only. Use at most three rounds.
   Exhaustion returns `hold_and_report`; the protected original remains.
10. Human approval and factual fidelity always outrank a style score.

If independent workers are unavailable, the orchestrator may run sequential
passes but must record reduced independence in `events.jsonl` or `TROUBLES.md`.
The rewriter must never judge its own rewrite.

## Backward-compatible changes schema

The controller still accepts a v1 object containing only `changes`. New runs
should use v2:

```json
{
  "schema": "report-pipeline/humanization-changes-v2",
  "gate": {
    "verdict": "PASS|REWORK",
    "skipped": false,
    "advisory_score": null
  },
  "strength": "light|standard|strong",
  "round": 1,
  "changes": [
    {
      "paragraph_id": "p0004",
      "section": "motivation|theory|method|results|conclusion|body",
      "detected_patterns": ["repetitive transition"],
      "severity": "low|med|high",
      "protected_spans": [{"text": "72개", "type": "numbers"}],
      "academic_level_risk": "none|low|high",
      "style_profile_rules": ["concrete functional explanation"],
      "before": "Exact paragraph from humanization_report.json",
      "after": "Minimally revised paragraph",
      "alternative_candidates": [],
      "selection_reason": "observable prose issue",
      "fidelity_evidence": {
        "numbers_preserved": true,
        "polarity_preserved": true,
        "causality_preserved": true
      },
      "reviewer_verdict": "accept|rewrite|rollback",
      "confidence": 0.9
    }
  ],
  "extreme_hedge_warnings": []
}
```

`gate.skipped=true` is valid only with `gate.verdict=PASS` and an empty changes
array. `after` may not introduce a blank-line paragraph boundary. Duplicate or
unknown paragraph ids, stale `before` text, malformed protected spans, and
unsupported schemas are rejected.

## Deterministic protected content

The local controller compares the original and candidate at paragraph and
document scope. It protects:

- numbers, units, dates, percentages, and source ids;
- citations, direct quotations, URLs, links, document tags, and inline math;
- headings and declared protected spans;
- negation, uncertainty, bounds, quantifiers, and causal markers.

The independent fidelity reviewer additionally checks claim direction,
agent preservation, causal direction, meaningful sequence, and information
omission/addition. Those semantic checks cannot be replaced reliably by a
regex, but an external PASS can never override a deterministic failure.

## Change-rate and hedge warnings

The controller warns, but does not auto-edit, when total change exceeds 0.15
for light, 0.30 for standard, or 0.45 for strong mode. Report runs should start
with light mode.

Two extreme patterns are warnings only:

- a measured result softened into vague tendency language;
- an inference context strengthened into always/must/required language.

Context belongs to the independent reviewer. The controller never rewrites
these expressions automatically.

## Convergence states

```text
prepared
  -> skipped                     PASS, unchanged, fidelity pass
  -> accepted                    all proposed edits pass
  -> needs_retry                 unsafe/over-polished paragraphs rolled back
  -> hold_and_report             retry ids remain after round 3
  -> rolled_back                 whole-document invariant failed
```

Pantadex operations such as scoring, full humanization, style polish, fidelity
audit, and naturalness review remain independent optional tools. Tool discovery
happens at runtime; no private endpoint, credential, corpus, or provider model
name belongs in this repository.
