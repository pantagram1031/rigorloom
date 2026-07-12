# Stage 4.5 — Content audit → script gate: `content_audit`
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: FREEZE the content BEFORE assembly. Content edits are allowed HERE and
only HERE after the draft gate; once `content_audit` passes, `bundle/content.md`
is the immutable input to Stage 5 assembly.

RATIONALE: COM re-assembly is the expensive step. Reviewing prose AFTER an
assembly means every AI-tell/framing fix forces a full re-assemble. Auditing
before assembly turns ~4 assemblies into 1 (audit) + 1 (assemble).

ENTRY: `pipeline_ctl resume` → stage 4.5. Stage 4 done (gate draft ok),
`bundle/content.md` and `bundle/provenance.json` exist.

EXACT actions:

1. NUMBERS ARE ALREADY FROZEN at Stage 3. Do NOT touch `sim/` results, figures,
   or any datum. This stage reviews PROSE and FRAMING only — never numbers,
   equations, tags, or qualifiers.
2. Run an AI-tell + framing review on `bundle/content.md` (roles per
   `agents.yaml`). Content edits ARE allowed here: fix AI-tell patterns,
   register/level slips, and framing, keeping every fact/number/tag identical.
   Re-run `prose_fidelity` if you invoke the humanization controller, exactly as
   in Stage 4 (facts never change to make a style proposal pass).
3. Resolve the script gate — this RUNS the bound checker (`verify_content.py`),
   it does not accept a hand-supplied verdict:
   ```
   # cd <REPO_ROOT>/
   python pipeline/scripts/pipeline_ctl.py check <WS> content_audit
   # exit 0 → auto_approved (HARD rules all clean) → advance
   # nonzero → rejected (HARD violation) → fix content.md, re-run check
   ```
   HARD rules (fail-closed): no web URLs, no '~습니다' polite endings, every
   `[[FIG]]` file present, 세특 ≤1500 B, no LaTeX/tag leak in any assembled PDF.
   WARN rules (괄호-영어 gloss, numbered refs, unmatched in-text cites) never
   fail the gate; pass report-specific proper nouns via `--allowlist` if the
   checker is invoked directly for triage.
4. Any content edit made AFTER this gate passes → invalidate from 4.5 so the
   frozen input and downstream assembly are rebuilt from the corrected prose:
   ```
   python pipeline/scripts/pipeline_ctl.py invalidate <WS> --from 4.5 --reason "post-freeze content edit"
   ```

ROLE BINDINGS (§R): reviewer-ai-tell = agent.worker/high (fresh, independent);
writer = agent.worker/high (applies prose deltas only); mech-worker =
agent.worker/medium may run the `check` command. Pantadex is an optional
comparison judge and can never bypass the local checker verdict.

EXIT + gate: `content_audit` auto_approved (checker exit 0), THEN advance → 5:
```
python pipeline/scripts/pipeline_ctl.py advance <WS> 4.5 --status done
```

FAILURE table:
| Symptom | Cause | Action |
|---|---|---|
| check exit 3: H1 web URL | raw link in body | move source detail to provenance/endnote, re-check |
| check exit 3: H2 '~습니다' | polite ending leaked | rewrite to the report register, re-check |
| check exit 3: H3 FIG missing | tag references absent file | fix filename or add the figure to bundle/figures, re-check |
| check exit 2: content.md not found | wrong workspace / draft not written | verify <WS>; Stage 4 must have produced bundle/content.md |
| tempted to edit a number to pass | — | forbidden (§7) — numbers are frozen at Stage 3; fix the model there and invalidate |
| content edited after gate passed | freeze broken | `invalidate --from 4.5`, re-review, re-check |
