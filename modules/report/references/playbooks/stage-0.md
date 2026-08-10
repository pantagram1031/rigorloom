# Stage 0 — Form intake v2 (code, not prose)
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: Turn the form into a machine profile (anchors, cast-off metrics,
table map, break state) and draft build.yaml. Feeds §N cast-off.

ENTRY: `pipeline_ctl resume` → stage 0. request.yaml complete.

T86 is a separate diagnostic branch for a binary HWP that needs an explicit
`rhwp` probe. It is optional and never changes this Stage-0 intake contract:
pre-create `work/stage-0/scratch/hwp-diagnostic`, supply an opaque run id plus
an explicit `--rhwp` binary and mandatory `--rhwp-sha256`, and run
`pipeline/scripts/hwp_diagnostic_candidate.py`. The only allowed result is a
quarantine-relative `<run-id>/candidate.hwpx` with
`rigorloom/hwp-diagnostic-candidate/v1`; comparison is `unknown`, render is
`not_run`, and proof is `none`. Do not copy it to `output/form_copy.hwpx`, do
not create an ingress/backend receipt, and do not call
`new_report --ingress-receipt`. T86 has no pyhwp or LibreOffice fallback; a
refusal leaves no owned candidate or receipt and does not advance this stage.
An unowned empty reservation or raced foreign path may be preserved for safety;
it cannot verify and must never be treated as Stage-0 input.

T87 is a second, separate Java diagnostic quarantine and likewise never enters
Stage 0. Its exact leaf is `work/stage-0/scratch/hwp-java-diagnostic`; require
an explicit rehashed Java launcher and the operator-supplied fat JAR matching
the shipped lock. `rigorloom/hwp-java-diagnostic-candidate/v1` always records
an unbound surrounding runtime, comparison `unknown`, render `not_run`, proof
`none`, and submission false. Do not copy its candidate/receipt into canonical
output, ingress/backend evidence, or `new_report`; the package ships no JAR,
JRE, class, or corpus bytes.

T88 is a third, receipt-only bounded content/object agreement boundary. It may compare only one
current T86 receipt and one current T87 receipt under the exact pre-created
`work/stage-0/scratch/hwp-semantic-oracle` leaf. It captures and verifies all
four producer inputs, requires exact T85 source descriptors plus the T86
allowlist/T87 lock, runs the public T86/T87/T79 gates over captured snapshots,
and emits `rigorloom/hwp-semantic-oracle/v1` agreement evidence only. Its
bounded comparison covers text/story-table topology/equations/referenced
pictures/explicit controls only; styles, numbering, pagination, and metadata
are not compared. Its ceiling is `diagnostic_only`; source fidelity is not established, render is
`not_run`, proof is `none`, submission is false. Do not copy any candidate or
receipt into canonical output, ingress/backend evidence, Stage 0, or
`new_report`; do not substitute `syhwp`.

T89 and T90 are receipt-only source diagnostics and likewise cannot satisfy a
Stage-0 entry condition. T89 inventories bounded BodyText record/control
coverage under `hwp-source-coverage`; T90 binds DocInfo definition cardinality
and zero-based BodyText IDs under `hwp-docinfo-coverage`. Both preserve
comparison unknown, render not run, proof none, submission false, and exit 3
after every analysis/refusal. Do not copy either receipt into canonical output
or reinterpret count/reference coverage as source fidelity or native proof.

For the `conditions-only` alias, the agent first derives a short set of topic
candidates from the recorded constraints and pauses for the human
`topic_pick`; write the selected topic to `request.yaml` before normal form
intake continues. The agent may propose candidates but may not choose for the
human.

EXACT commands (form_inspect v2, CONTRACT §E amended / §T inspect):
```
# cd <REPO_ROOT>/ (all paths below are relative to this, repository-root CWD)
python engine/scripts/form_inspect.py <ABSOLUTE_FORM_PATH> \
  --out <WS>/form_profile.json \
  --base-pt 10 --line-spacing 180 \
  [--baseline <WS>/form_baseline.json]
```
Produces (v0.5 outputs PLUS v2): anchors, placeholders, guide_text,
format_hints, constraints, removal_targets, form_hash **+ page_metrics
(lines/page, chars/line) + table_map (cellSz, shaded cells, fill/delete
targets — locates 요약/초록 box) + break_audit**.

Then draft build.yaml (single declaration source, CONTRACT §4):
- merge precedence: request.yaml > form_profile guide-text constraints >
  skill defaults (§Q).
- v0.6 diet: DO NOT emit `tidy_blank` / `keep_with_next` anchor knobs (now
  built-in via §O). Keep base_pt/caption_pt/line_spacing/binding/abstract/
  title/allow_colors/delete_texts/page_break_before/fill{target_pages,
  min_figures}. Legacy keys honored on read but don't write them.

Load only relevant public/domain guidance, approved operator references, and
this run's conditions. Generated report prose is never private-style evidence.

ROLE BINDINGS: mech-worker runs form inspection; designer interprets the form.

EXIT + gate: selected topic recorded; form_profile.json (with
page_metrics/table_map/break_audit) + build.yaml written. Resolve the human
topic gate before research:
```
python modules/report/scripts/pipeline_ctl.py gate <WS> topic_pick --mode <mode>
# supervised → STOP, request approval and transcribe it to APPROVALS.md.
# autonomous/night → auto_approved (logged).
python modules/report/scripts/pipeline_ctl.py advance <WS> 0 --status done
```

FAILURE table:
| Symptom | Cause | Action |
|---|---|---|
| page_metrics missing | `--base-pt`/`--line-spacing` omitted | rerun with both flags (cast-off needs them) |
| anchors ≠ form headings | form variant | freeze anchors.json from inspect; content.md matches form, not vice-versa |
| guide-text constraint conflicts request | — | §Q precedence: request > form; record in PIPELINE |
| form_inspect throws | corrupt/locked form | work on a copy; if COM-locked, close HWP instances, retry |
