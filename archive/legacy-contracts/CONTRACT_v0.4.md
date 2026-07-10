# Report Pipeline v0.4 — Shared Contract (SINGLE SOURCE OF TRUTH)

This file freezes the interfaces that the `report-pipeline` skill, the `studio`
viewer, and `build_report.py` all depend on. It exists so two agent sessions
(and two subagents editing in parallel) cannot diverge. If code and this file
disagree, this file wins — fix the code.

Version 0.4 turns the pipeline from a **discussion-driven** flow into a
**topic-only autonomous** flow: the operator supplies a topic (+ form + subject
+ conditions) and the machine researches, designs, verifies, writes, and fills
the form to completion. Human approval gates become *configurable* (on for
supervised runs, recorded-and-continued for autonomous runs) but their state is
ALWAYS persisted machine-readably — the v0.3 failure was gates as prose.

---

## 1. Stage model (v0.4)

```
0  Setup            load form + subject + conditions, inspect form anchors
1  Research   ★NEW  gather source material (web/RAG), build a cited evidence pack
2  Design           inquiry question, hypothesis, variables, VERIFY gate design
   └─ GATE design    (autonomous: auto-approve+record; supervised: stop)
3  Data/Sim         run code, VERIFY gate (deterministic, code-emitted verdict)
4  Write            content.md in bundle_spec grammar (saenggibu 문체)
   └─ GATE draft     (content quality — human-only judgment)
5  Assemble+Fill    build_report → COM edit → layout_qa FILL LOOP → PDF verify
5.5 Understanding   teacher questions (anti-slop)
   └─ GATE understand
6  Return           wiki + archive + profile update
```

Stage numbers are STABLE STRINGS: `"0","1","2","3","4","5","5.5","6"`. Never
renumber; studio's stage→artifact map keys on these exact strings.

---

## 2. PIPELINE.md machine header (REQUIRED, replaces freeform prose)

Every `PIPELINE.md` MUST begin with a fenced YAML block. This is the checkpoint
that `studio` parses and that resume reads. The human-readable table may follow
below it, but the YAML block is authoritative.

```yaml
# pipeline-state: v0.4
slug: report-hr-classification
mode: autonomous            # autonomous | supervised
subject: earth-science
topic: "별의 HR도 분류"
form: templates/소논문_기본양식.hwpx
updated: 2026-07-06T09:41:00
canonical_output: output/별_HR도_보고서_v5.hwpx   # the ONE final file (null until produced)
stages:
  "0":   {status: done,        gate: null}
  "1":   {status: done,        gate: null}
  "2":   {status: done,        gate: {name: design,      state: auto_approved, by: autonomous, at: 2026-07-06T09:10:00}}
  "3":   {status: done,        gate: null}
  "4":   {status: done,        gate: {name: draft,       state: pending,       by: null, at: null}}
  "5":   {status: done,        gate: null}
  "5.5": {status: awaiting_gate,gate: {name: understand,  state: pending,       by: null, at: null}}
  "6":   {status: pending,     gate: null}
```

### Status enum (the ONLY allowed values)
`pending | in_progress | awaiting_gate | done | blocked`

### Gate state enum
`pending | approved | auto_approved | rejected`
- `approved` requires an out-of-band human token (see §3). An agent writing
  `approved` for itself is a contract violation.
- `auto_approved` is what an autonomous run records when it passes a
  human-judgment gate without a human; it is explicitly NOT `approved`.

### Resume rule (deterministic)
1. Parse the YAML header.
2. First stage whose status ∈ {pending, in_progress} is the resume point.
3. If a stage is `awaiting_gate`: in supervised mode STOP and re-ask the gate;
   in autonomous mode, if its gate.state is a human-only gate still `pending`,
   record `auto_approved` and continue (never silently mark `approved`).
4. A stage MUST NOT start if its declared predecessor gate is `rejected` or a
   supervised `pending`.

---

## 3. Approval token (anti-forge)

Human approval lives in a separate file the agent never writes:
`APPROVALS.md`, one line per granted gate:

```
design: approved by operator at 2026-07-06T09:10
draft:  approved by operator at 2026-07-06T11:30
```

The pipeline may only set a gate to `approved` after reading a matching line in
APPROVALS.md. `auto_approved` (autonomous mode) is written by the agent and is a
distinct, weaker state. studio surfaces `auto_approved` gates as a warning chip
("자동 통과 — 사람 미검토").

---

## 4. build.yaml — the applied build config (NEW, drives studio Options + assembly)

`report-<slug>/build.yaml` is the single declared source of layout/build knobs.
build_report.py meta and studio's Options panel both read it. Keys:

```yaml
base_pt: 10
caption_pt: 9
line_spacing: 160          # percent; overrides form default
binding: submit            # submit | book
abstract: false
title: "별의 스펙트럼-광도 분류 탐구"
title_anchor: "[논문제목]"
fill:                      # ★ form-fill loop targets (see §5)
  min_figures: 4
  target_pages: [4, 6]     # inclusive page-count window the report must land in
  bottom_white_max: 25     # percent (last page exempt) — from layout_qa
  max_gap_lines: 3         # from layout_qa
```

When present, build_report.py derives its `meta` from build.yaml (build.yaml
wins over content.md front-matter for these keys). content.md keeps only text +
[[EQ]]/[[FIG]]/[[TABLE]]/[[URL]] tags.

---

## 5. Form-fill loop (Stage 5) — the "no empty space, many figures" objective

Goal: the assembled report fills the given form completely — no large bottom
whitespace, no oversized inter-paragraph gaps, ≥ `min_figures`, and lands inside
`target_pages`. This is a DETERMINISTIC loop, not eyeballing.

```
build → COM edit → render PDF → layout_qa.py --file verify.pdf
        --bottom {bottom_white_max} --gap {max_gap_lines}
  read layout_qa JSON:
    if pass AND page_count in target_pages AND fig_count >= min_figures:
        DONE
    elif page_count < target_pages[0] OR bottom_white too high on non-last pages:
        UNDERFILLED → expand: add a figure, deepen a section, add a worked
        example/derivation. Re-draft content.md (Stage 4 delta), rebuild.
    elif page_count > target_pages[1]:
        OVERFILLED → tighten: merge/trim, move detail to a figure/table.
    loop, max 4 iterations; if not converged, record blocked + reason.
```

`fill_report.py` (NEW, in hwp-master/scripts/) orchestrates this loop headlessly
and returns a JSON verdict `{converged, iterations, page_count, fig_count,
bottom_white_worst, gaps_worst, reason}`. It calls build_report + com_backend +
layout_qa; it does NOT invent numbers — content expansion is emitted as a
"needs" list for the writer stage, it does not fabricate body text.

---

## 6. Research stage (Stage 1) — evidence pack

Output: `report-<slug>/research/evidence.md` + `research/sources.json`.

- `sources.json`: list of `{id, title, url, accessed, kind: web|dataset|paper,
  claim_ids: [...]}`.
- `evidence.md`: numbered claims, each tagged with source id(s). Claims that
  will become body facts MUST carry ≥1 source id. Uncited claims are flagged and
  may not become asserted facts in content.md (they can become the student's own
  reasoning, marked as such).
- Datasets discovered here (e.g. a public CSV) are recorded with their real URL
  and a size/header assertion so Stage 3 can't silently ingest a 404 stub.

studio gets a Research panel that renders evidence.md + a sources table.

---

## 7. Verdict integrity (fixes the v0.3 gate-flip)

- The code that runs a gate writes ITS OWN verdict file and never edits it after.
  Stage 3 writes `sim/gate_result.json` (machine truth, immutable).
- Any scope narrowing (e.g. "valid regime = AFGKM, exclude O/B") must be a
  DECLARED INPUT to the gate code and the gate re-run — not a post-hoc edit of
  the output JSON. `VERIFY.md` must show the raw verdict AND any
  declared-scope-adjusted verdict side by side, never just "전부 통과".
- A gate's measured side must be independent of its expected side (no measuring
  the injected noise and comparing to itself).

---

## 8. studio scope (v0.4 — trim to essentials)

KEEP: workspace list, PIPELINE.md YAML-header parse → progress + gate chips,
research panel, content structure panel, PDF page render, fill-loop status.
REMOVE: the "start prompt builder / copy button" form (dead in autonomous mode),
buildconfig mock when no build.yaml, any endpoint not backing a kept panel.
SECURITY: `safe_workspace(slug)` — regex `^report-[A-Za-z0-9_-]+$` then resolve
+ containment under WORKSPACE_ROOT, applied to EVERY slug handler. PDF page
bounds checked (404 not 500). Remove startup mkdir (read-only).
