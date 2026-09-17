# Stage 7 — Report pipeline in the GUI

Status: QUEUED 2026-09-17 (after Stage 6). Owner: Fable. Rule: no new document semantics; the GUI drives the same
Runtime verbs the CLI uses; verify_format / layout_qa results are shown as designed states, never as render proof.

## Intent
Open a report workspace (e.g. reports/report-auralab-classroom) from the desktop, see the PIPELINE.md stage machine
(stage 0–6, gate verdicts) as a status strip, run fill / verify from the GUI through the Runtime, show the results
(verify_format findings, layout QA pages, loop state) as designed states, and reach the poster line.

## Slices (to be specified when Stage 6 closes)
- [x] P1 Workspace open: detect PIPELINE.md next to a document; parse the YAML header read-only; status strip.
- [x] P2 Verify from the GUI: a Runtime verb that runs the offline checkers on the current candidate (exists as
      `verify`; wire it) and a results panel (findings per checker, verdict, "what this does not prove").
- [ ] P3 Fill loop from the GUI on Windows with Hancom (com): progress events, proof contact sheets as images.
- [ ] P4 Poster line: build + verify from the GUI; poster preview as an image with its verdict.

## Ledger
| When | What | Result |
|---|---|---|
| 2026-09-18 | P1 read-only `workspace/pipelineStatus` (CLI `pipeline-status`) + desktop strip/panel | Host-only verb walks up ≤4 levels, copies PIPELINE.md gate verdicts via pipeline_ctl parser, no writes. Desktop strip + 파이프라인 disclosure; empty state when no header; refresh re-calls the verb. |
| 2026-09-18 | P2 `candidate/verify` from the desktop on current head | Optional `runId` (omit = source) + `target`/`checkedUtc`. Toolbar 검사 calls the verb; slide-in rows per checker (pass/warn/fail/unavailable); freeze footer; pill and 검사 popover show run time and 원본/후보본. |
