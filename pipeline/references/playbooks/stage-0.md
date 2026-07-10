# Stage 0 — Form intake v2 (code, not prose)
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: Turn the form into a machine profile (anchors, cast-off metrics,
table map, break state) and draft build.yaml. Feeds §N cast-off.

ENTRY: `pipeline_ctl resume` → stage 0. request.yaml complete.

EXACT commands (form_inspect v2, CONTRACT §E amended / §T inspect):
```
# cd <REPO_ROOT>/ (all paths below are relative to this, repository-root CWD)
python <HWP_MASTER_ROOT>/scripts/form_inspect.py <ABSOLUTE_FORM_PATH> \
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

EXIT + gate: form_profile.json (with page_metrics/table_map/break_audit) +
build.yaml written. No human gate. Advance → stage 1:
```
python pipeline/scripts/pipeline_ctl.py advance <WS> 0 --status done
```

FAILURE table:
| Symptom | Cause | Action |
|---|---|---|
| page_metrics missing | `--base-pt`/`--line-spacing` omitted | rerun with both flags (cast-off needs them) |
| anchors ≠ form headings | form variant | freeze anchors.json from inspect; content.md matches form, not vice-versa |
| guide-text constraint conflicts request | — | §Q precedence: request > form; record in PIPELINE |
| form_inspect throws | corrupt/locked form | work on a copy; if COM-locked, close HWP instances, retry |
