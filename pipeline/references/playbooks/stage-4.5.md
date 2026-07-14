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
3. Resolve the script gate — this RUNS the bound composite checker
   (`content_audit.py`: `verify_content.py`, then `check_style.py`, then
   `check_numbers.py --require-seed`, then `check_refs.py`); it does not accept a hand-supplied
   verdict:
   ```
   # cd <REPO_ROOT>/
   python pipeline/scripts/pipeline_ctl.py check <WS> content_audit
   # exit 0 → auto_approved (HARD rules all clean) → advance
   # nonzero → rejected (HARD violation) → fix content.md, re-run check
   ```
   HARD rules (fail-closed): no web URLs, no '~습니다' polite endings, every
   `[[FIG]]` file present, 세특 ≤1500 B, no LaTeX/tag leak in any assembled PDF.
   Invalid explicit seed values remain HARD. A missing seed is HARD only when
   canonical `sim/results.json` contains other numeric simulation results; it
   is WARN for empty, boolean-only, compatibility, or otherwise ambiguous
   artifacts.
   WARN rules (괄호-영어 gloss, numbered refs, unmatched in-text cites, and
   body numerals absent from recursively collected `sim/results.json` values)
   never fail the gate; suspect numerals remain visible for human review.
   check_refs.py is fully advisory: caption-number gaps/duplicates, dangling
   figure/table references, and unreferenced figures are WARN suspects for
   human review and never fail the gate.
   Pass report-specific proper nouns via `--allowlist` if the checker is invoked
   directly for triage. Legitimate non-simulation numbers may be listed in
   `<PROFILE_ROOT>/packs/numeral_allowlist.txt` (one exact number per line).
   The operator environment/bootstrap must set
   `RIGORLOOM_PROFILE_ROOT=<PROFILE_ROOT>` before `pipeline_ctl check`; the gate
   then schema-validates every recognized operator pack (including figure
   style) and forwards the applicable prose/structure, gloss, and numeral rules
   automatically. An explicit
   `content_audit.py --profile-root <PROFILE_ROOT>` overrides the environment.
   With neither source set (or with an invalid environment directory), neutral
   defaults remain unchanged. Direct `check_numbers.py` calls likewise derive
   `--allow` from the valid environment root only when `--allow` is absent.
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
| WARN: unbacked_numeral | typed/body value absent from results.json | review against the simulation; return to Stage 3 if it is a simulation claim, or allowlist only a legitimate non-sim value |
| check exit 3: missing_seed | canonical numeric `sim/results.json` lacks RNG provenance | fix the sim spec/code and rerun; never patch the JSON post-hoc |
| WARN: missing_seed | result artifact is populated but not clearly fresh numeric sim output | inspect provenance manually; promote by regenerating canonical results when applicable |
| check exit 3: invalid_seed | the TOP-LEVEL `seed` field of results.json/provenance is not finite numeric JSON (nested `seed` fields are ignored — only the top-level RNG seed is authoritative) | fix the sim spec/code and rerun; never patch the JSON post-hoc |
| tempted to edit a number to pass | — | forbidden (§7) — numbers are frozen at Stage 3; fix the model there and invalidate |
| content edited after gate passed | freeze broken | `invalidate --from 4.5`, re-review, re-check |
