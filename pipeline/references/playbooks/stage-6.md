# Stage 6 — Return and knowledge distillation

PURPOSE: Deliver the canonical file and preserve reusable, non-personal lessons.

If a private profile root is configured, collect run feedback into its local
candidate queue after delivery. Candidates require human review and generated
report prose is never imported as style evidence.

ENTRY: `pipeline_ctl resume` returns Stage 6; Stage 5.7 is complete and its
`final_panel` script gate is resolved.

EXACT actions:

1. Confirm `canonical_output`, proof verdict, scorecard, sources, and provenance.
   The assembly verdict must record
   `proof_grade: hancom|certified|advisory|experimental-rhwp|none`.
   `certified` is accepted only with explicit `build.yaml` opt-in, a passing
   live document-envelope check, and full certificate re-verification;
   `experimental-rhwp` remains diagnostic-only.
2. Resolve the Stage 6 `submission_preflight` script gate before delivery. It
   always checks extension, sane size, and file reopen (HWPX ZIP + XML parse;
   PDF PyMuPDF open + nonzero text). When `request.yaml` declares
   `output_filename` and inline `required_fields: [name, id, ...]`, it also
   checks the filename pattern and confirms each named request value appears in
   post-render text. It also enforces the non-destructive-form rule when Stage 0
   recorded a form-structure SHA-256 in `form_baseline.json` or
   `build.yaml`: the assembled HWPX style/section plus `tbl`/`tc` table-cell and
   `ctrl` form-control skeleton hash must equal that baseline. Body text and
   tails are deliberately excluded from this hash. A mismatch is HARD
   `form_mutated`; a legacy workspace with no recorded structure hash emits
   WARN `form_baseline_absent`. The baseline is trusted-on-record: if it is
   written after a mutation, that mutation is undetectable. A signed external
   baseline is deferred.
   Either absent request key is skipped with a compatibility note, but
   reopen/extension/proof-grade checks never skip. The registered preflight
   also composes `check_saeteuk.py` with full HARD enforcement (the Stage 4.5
   mirror is early-discovery WARN-only): it compares UTF-8 `.txt` and `.md`
   artifacts under the workspace-local `_saeteuk/` directory with
   `bundle/content.md`. Parent directories are never consulted. A single
   distinct same-subject, compatible-unit numeric conflict beyond the
   precision-aware tolerance is HARD `saeteuk_number_contradiction`;
   unsupported or ambiguous numeric/entity anchors are WARN. With no local
   `_saeteuk/` directory, this sub-check is a zero-finding no-op PASS; an
   existing directory with no readable artifact is WARN `saeteuk_missing`.

```sh
python pipeline/scripts/pipeline_ctl.py advance <WS> 6 --status awaiting_gate
python pipeline/scripts/pipeline_ctl.py check <WS> submission_preflight
# exit 0 -> auto_approved; exit 3 -> rejected, repair package and rerun check
# exit 2 -> rejected usage/input; repair UTF-8/input readability and rerun check
```

3. Run the conformance linter after preflight approval and before creating or
   updating the archive. A HARD finding stops delivery until reconciled. In
   particular, `output/out.*` newer than the latest `content_audit` receipt is
   a Stage 4.5 freeze bypass. An `answers_pending` understanding provenance is
   a WARN that must be surfaced as remaining manual work.

```sh
python pipeline/scripts/workflow_lint.py <WS> --json
```

4. OPTIONAL advisory corpus check before the wiki return. Configure a private
   corpus root containing prior reports for one student only; the checker also
   requires each compared workspace's recorded `student_id` (or fallback
   `student_name`) to match the current workspace. A WARN is surfaced to the
   operator but does not block delivery. Omit this step when no private corpus
   is configured.

```sh
python pipeline/scripts/check_corpus.py <WS> --corpus-root <root>
# or set RIGORLOOM_CORPUS_ROOT and omit --corpus-root
```

5. Fill `pipeline/references/wiki_entry_template.md` as a local knowledge record
   under `<WS>/archive/knowledge/`.
6. Promote reusable troubleshooting patterns and public sources into that local
   record. Do not copy private report prose or identity data.
7. Report the canonical output path, gate history, `proof_grade`, and any
   remaining manual work to the operator.
8. Close the workflow only after the script gate is approved:

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
| preflight exit 2 / non-UTF-8 saeteuk | input artifact cannot be decoded or read | convert the local `_saeteuk/` artifact to valid UTF-8, repair permissions/input, and rerun the gate |
| `proof_grade` missing | renderer evidence not recorded | regenerate the assembly verdict with an explicit proof grade |
| `form_mutated` | assembled form-owned style/section skeleton differs from the pristine baseline | rebuild from the untouched form copy; do not replace the baseline with the mutated output hash |
| `form_baseline_absent` WARN | legacy workspace did not record a structure digest | surface the warning; for a new run, record the pristine Stage 0 digest before assembly |
| lint H6 stale assembly | output newer than content audit | invalidate from 4.5, rerun audit, and rebuild |
