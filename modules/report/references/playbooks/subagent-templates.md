# Worker task templates

These templates work with subagents, CLI workers, API workers, or sequential
passes in the orchestrator. Replace angle-bracket placeholders; do not delegate
again unless the orchestrator explicitly allows it.

## Research worker

```text
Do not delegate. Role: research lane <R1|R2|R3>.
Read <request> and <design if present>. Produce only <evidence-path> and
<sources-path>. Every factual claim must map to a source id. Return a concise
artifact summary, not raw search logs.
```

## Design reviewer

```text
Do not delegate. Review <design-path> against the request, evidence pack, target
curriculum, and measurable gate requirements. Return blockers, corrections, and
a pass/fail recommendation. Do not approve the human design gate.
```

## Writer

```text
Do not delegate. Write <content-path> to the exact layout budget in
<layout-plan>. Preserve source ids and distinguish sourced facts from analysis.
Use the form's section anchors. Do not modify gate results or document styles.
```

## Logic or numeric reviewer

```text
Do not delegate. Independently verify claims in <artifact-path> against source
records and machine verdicts. List each issue with location, evidence, severity,
and minimal correction. Never replace a failing machine verdict with prose.
```

## Humanization advisory reviewer

```text
Do not delegate. You are not the rewriter. Read <raw-draft>, <request>,
<academic-scope>, and the resolved local profile. Diagnose observable prose
patterns using prompts/ai_tell_review.md. Formal register is not itself a
defect. Return the advisory review artifact; do not select an allow-list of
paragraphs and do not edit prose.
```

## Humanizer rewriter

```text
Do not delegate. You did not produce the advisory review and may not judge your
own result. Follow prompts/humanize.md and inspect every prose paragraph after
REWORK. Return only humanization-changes-v2 JSON for paragraphs actually
changed. Preserve all protected spans. Do not write files or approve gates.
```

## Humanization fidelity or naturalness reviewer

```text
Do not delegate. You are independent from the rewriter. Compare <raw> and
<proposal> using prompts/<fidelity_review|naturalness_review>. Return only the
review JSON with accept, rewrite, or rollback. Do not repair the proposal and
never override a deterministic controller failure.
```

## Vision judge

```text
Do not delegate. Inspect <contact-sheet> using the composition rubric. Request
high-resolution pages only for visible anomalies. Return the four binary rubric
results and bounded content/layout needs. Do not infer unreadable body text.
```

## Mechanical worker

```text
Do not delegate. Run the exact supplied commands. Validate exit codes and output
schemas. Return command, exit status, and artifact paths. Do not reinterpret or
edit deterministic verdict files.
```
