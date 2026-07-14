# Stage 6 — Return and knowledge distillation

PURPOSE: Deliver the canonical file and preserve reusable, non-personal lessons.

If a private profile root is configured, collect run feedback into its local
candidate queue after delivery. Candidates require human review and generated
report prose is never imported as style evidence.

ENTRY: `pipeline_ctl resume` returns Stage 6; Stage 5.7 is complete and its
`final_panel` script gate is resolved.

EXACT actions:

1. Confirm `canonical_output`, proof verdict, scorecard, sources, and provenance.
   The assembly verdict must record `proof_grade: hancom|advisory|none`.
2. Resolve the Stage 6 `submission_preflight` script gate before delivery. It
   always checks extension, sane size, and file reopen (HWPX ZIP + XML parse;
   PDF PyMuPDF open + nonzero text). When `request.yaml` declares
   `output_filename` and inline `required_fields: [name, id, ...]`, it also
   checks the filename pattern and confirms each named request value appears in
   post-render text. Either absent request key is skipped with a compatibility
   note, but reopen/extension/proof-grade checks never skip.

```sh
python pipeline/scripts/pipeline_ctl.py advance <WS> 6 --status awaiting_gate
python pipeline/scripts/pipeline_ctl.py check <WS> submission_preflight
# exit 0 -> auto_approved; exit 3 -> rejected, repair package and rerun check
```

3. Run the conformance linter after preflight approval and before creating or
   updating the archive. A HARD finding stops delivery until reconciled. In
   particular, `output/out.*` newer than the latest `content_audit` receipt is
   a Stage 4.5 freeze bypass. An `answers_pending` understanding provenance is
   a WARN that must be surfaced as remaining manual work.

```sh
python pipeline/scripts/workflow_lint.py <WS> --json
```

4. Fill `pipeline/references/wiki_entry_template.md` as a local knowledge record
   under `<WS>/archive/knowledge/`.
5. Promote reusable troubleshooting patterns and public sources into that local
   record. Do not copy private report prose or identity data.
6. Report the canonical output path, gate history, `proof_grade`, and any
   remaining manual work to the operator.
7. Close the workflow only after the script gate is approved:

```sh
python pipeline/scripts/pipeline_ctl.py advance <WS> 6 --status done
```

The automatic organizer regenerates `NEXT_TASK.md`, writes the final handoff,
and preserves safe transient files under `<WS>/archive/stages/`.

ROLE BINDINGS: archive/knowledge = agent.worker/low or the orchestrator.

CORPUS HYGIENE: generated report prose is not evidence for a private person's
style. Only explicitly public or operator-approved reusable facts and process
lessons enter shared documentation.

EXIT + script gate: `submission_preflight` approved, canonical output delivered,
knowledge record written, and Stage 6 done.

FAILURE table:

| Symptom | Cause | Action |
|---|---|---|
| external knowledge store unavailable | optional service offline | local record is sufficient |
| private text about to enter public knowledge | hygiene violation | keep it in the ignored workspace |
| `canonical_output` null | Stage 5 incomplete | return to Stage 5; do not close |
| preflight filename/identity mismatch | request contract not reflected in artifact | rename/rebuild or fill required fields, then rerun the gate |
| artifact reopen fails | corrupt/unsupported submission file | rebuild a valid HWPX or text-bearing PDF |
| `proof_grade` missing | renderer evidence not recorded | regenerate the assembly verdict with an explicit proof grade |
| lint H6 stale assembly | output newer than content audit | invalidate from 4.5, rerun audit, and rebuild |
