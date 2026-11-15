# Report Pipeline v0.5 — Shared Contract (SINGLE SOURCE OF TRUTH)

Supersedes CONTRACT_v0.4.md. Everything in v0.4 remains in force unless
amended below. If code and this file disagree, this file wins — fix the code.
Design rationale lives in `docs/plans/pipeline-v0.5.md` (repo).

v0.5 theme: **enforcement moves from prose to code.** The state machine, gate
records, fill loop, and anomaly checks are now executed by scripts that refuse
illegal transitions; agents call the scripts instead of narrating compliance.

---

## A. pipeline_ctl.py is the state machine (replaces manual YAML editing)

`report-pipeline/scripts/pipeline_ctl.py` — stdlib CLI, one JSON object per
call, exit 0 ok / 1 refusal / 2 usage. Agents MUST use it for all state
changes; hand-editing the PIPELINE.md YAML header is a contract violation.

```
init <ws> --slug --mode --subject --topic --form   create v0.4-format header
resume <ws>                                        next stage / blocked info
gate <ws> <name> --mode <supervised|autonomous|night>
advance <ws> <stage> --status <in_progress|done|awaiting_gate|blocked> [--reason]
invalidate <ws> --from <stage> [--reason]          downstream reset (condition changes)
trouble <ws> --stage --role --model --failure-class --evidence [--kb-root]
heartbeat <ws>
```

- `gate` sets `approved` ONLY after reading a matching `^<name>: approved`
  line in APPROVALS.md. Otherwise: supervised → refusal; autonomous/night →
  `auto_approved`.
- **Chat approval (v0.5.1 amendment, operator-requested 2026-07-07):** in a
  SUPERVISED interactive session, the operator saying "approve <gate>" (or
  equivalent) in chat is a valid approval. The orchestrator then transcribes
  it to APPROVALS.md as `<gate>: approved by operator (chat) at <ISO>` —
  quoting the operator's message in a comment line — and runs `gate`. This
  transcription right exists ONLY for supervised interactive sessions where
  the operator is demonstrably present (their message is the trigger).
  Autonomous/night runs never self-approve; unattended sessions never
  transcribe. Anti-forge intent is preserved: the forgeable path was an agent
  approving WITHOUT a human utterance, not transcription OF one.
- `advance` refuses to start a stage whose predecessor gate is `rejected`, or
  `pending` in supervised mode.
- Every state change appends `{ts,type,stage,detail}` to `<ws>/events.jsonl`
  and refreshes `<ws>/heartbeat` — studio's live feed reads these.
- `trouble` appends to `<ws>/TROUBLES.md` AND `kb/model-log.md`.

## B. Run modes

`supervised` / `autonomous` as v0.4. NEW `night`: autonomous plus (a) never
ask the operator — missing input → default + entry in a YAML `assumptions:`
list; (b) token-budget check at stage boundaries → degrade (research fan-out
3→2, skip optional panels) instead of dying; (c) PushNotification on
gate-wait/blocked/done; (d) morning summary block at top of PIPELINE.md.

## C. Entry (no headless)

Headless `claude -p` is banned (operator policy 2026-07-07). The interactive
Claude Code session is the orchestrator. First action of a run (Stage -1):
start studio via `.claude/launch.json` (`studio`, port 8765), open browser,
create/complete `request.yaml`, `pipeline_ctl init`. Cowork is a secondary
entry with identical checkpoints.

## D. request.yaml (job ticket — the only start input)

```yaml
topic: "..."                 # required
subject: 지구과학             # required
form: templates/<file>.hwpx  # default: 소논문_기본양식.hwpx
mode: autonomous             # supervised | autonomous | night
length: standard             # short | standard | long — or explicit pages
constraints:
  pages: [4, 6]              # overrides length preset
  min_figures: 4
  must_include: ["수식 유도 1개 이상"]
  scope: "주계열성만, 거성 제외"   # becomes gate declared-input
  avoid: []
  bibliography_style: null   # null = precedence rule (§G)
```
Merge precedence into build.yaml: request.yaml > form_profile (guide-text
constraints) > skill defaults. Conflicts recorded in PIPELINE.md.

## E. Stage 0 form intake (code, not prose)

`hwp-master/scripts/form_inspect.py FORM.hwpx --out form_profile.json
[--baseline form_baseline.json]`:
- anchors, placeholders, guide_text (colored/example/instruction classified),
  format_hints (citation_example, table style), constraints parsed from guide
  text, removal_targets, form_hash.
- Guide/example text: absorbed as format hints, then REMOVED in assembly —
  the working copy keeps only real report content. layout_qa asserts zero
  guide remnants in the final render.
- `form_baseline.json` (fonts/sizes/colors/line-spacings + usage histograms)
  is the fingerprint for style_diff. Cache by form_hash.

## F. Anomaly detection (3 layers, replaces eyeballing)

1. Deterministic, every fill iteration: `style_diff.py` (charPr/paraPr vs
   baseline + build.yaml allowances → unintended font/size/color/line-spacing
   with locations) + extended `layout_qa.py` (line-spacing uniformity
   histogram, figure width/caption/overlap, table regularity, `[n]` citation
   markers, guide remnants, LaTeX leaks, bottom white, gaps).
2. Trouble-table auto-match: signatures from `kb/trouble-table.md`; known
   fixes annotated in the verdict; hit/miss autologged via `pipeline_ctl trouble`.
3. Visual diagnosis: only when 1–2 can't explain — a vision agent READS the
   rendered PDF page image (standing rule: HWP misbehavior → look at the PDF),
   names cause+fix; the row is saved so next run resolves at layer 2.

## G. Clean body + bibliography (Stage 4/5)

- ZERO citation markers/footnotes in the body — enforced by layout_qa.
- Provenance lives in `bundle/provenance.json` (paragraph → source ids),
  never rendered; 5.7 citation audit reads the sidecar.
- Natural-language attribution allowed where a student would use it.
- 참고문헌 (last page) auto-generated from sources.json ∩ provenance.
  Style precedence: request.yaml condition > form's example citation
  (format_hint) > Korean standard (책: 저자, 『서명』, 출판사, 연도. /
  논문: 저자, 「제목」, 『게재지』 권(호), 연도. / 웹: 기관, "제목", URL
  (접속일: YYYY.MM.DD.)). Raw URLs never in the body.

## H. Fill loop (Stage 5) — code drives, writer only fills "needs"

`fill_report.py --loop` per iteration: assemble → layout_qa(all checks) →
style_diff → preview PDF to `output/preview/iter_N.pdf` (studio live view) +
line to `output/fill_events.jsonl`. Converged = pass ∧ pages∈window ∧
figs≥min. Otherwise emits ordered machine-readable `needs`
(`expand_section/add_figure/trim_section` + reason); the WRITER applies needs
to content.md and re-invokes — code never fabricates body text. Max 4
iterations then blocked+reason.

## I. Agent/model routing (defaults; kb/model-log.md may override)

| Role | Model | Effort |
|---|---|---|
| Orchestrator / design judge / writer | main session (fable/opus) | high; max for judging+writing |
| Researchers R1(concepts) R2(data+images) R3(books+curriculum) | sonnet ×3 parallel | medium |
| Cross-exam verifier | opus | high |
| Design panel | sonnet ×2 + Codex | high |
| Sim executor / figure line / fill shepherd | sonnet | medium / medium / low |
| Sim-code review / AI-tell hunt / 5.7 logic | Codex | high |
| Visual diagnosis / 5.7 visual | sonnet (vision, fresh) | high |
| 5.7 value·subject-fit·human-feel | opus (fresh) | high |
| Stage 6 | sonnet | low–medium |

Swap ladder on severe failure (gate fail traced to agent, fabrication, or 2
consecutive rejections): record via `pipeline_ctl trouble`, then retry with a
DIFFERENT model: sonnet→opus→fable/Codex; Codex→opus; opus→fable+Codex second
opinion. Never silently retry the same model more than once.
Codex sandbox rule: Codex cannot write outside repo roots — give it repo-path
tasks or have a Claude agent apply its patch.

## J. Research (Stage 1) additions to v0.4 §6

- Three parallel researchers (lenses above), then ONE structured cross-exam
  round: verifier challenges top claims; unresolved → flagged, cannot become
  body facts. No open-ended debate.
- sources.json `kind` gains `book` (author/title/publisher/year/ISBN when
  findable). R3 also drafts the curriculum tie-in (성취기준, 핵심역량,
  3학년 연계·심화 여지) into `research/curriculum.md` from
  `kb/curriculum/과목-<subject>.md` (built once per subject, cached).
- Downloaded images: CC/public-license only, license + source recorded.

## K. Humanization (Stage 4 order is fixed — v0.5.1: Codex FIRST, scorer LAST)

Rationale (operator, 2026-07-07): any rewriting — including fixes driven by
review — can itself add AI-tells, so the deterministic scorer must run AFTER
all rewriting, not before it.

1. Write per saenggibu spec.
2. **Codex AI-tell hunt FIRST** (independent eye; catches too-polished
   sentences, consultant-speak, generic growth narrative). Apply its findings.
3. THEN `score_ai_tells` (genre=news — closest formal-register proxy; the
   scorer has no report genre, so ending-monotony/nominalization flags are
   advisory in this register).
4. Below threshold → `humanize_full(strength=light)` on failing sections only
   (light = minimal-correction mode, preserves the report register; never
   standard/strong on report prose).
5. Deterministic invariant check: numerals, source ids, [[EQ]]/[[FIG]]/
   [[TABLE]] tags, section anchors byte-identical — humanizer touches prose
   only. Re-score. Final score recorded in PIPELINE.md.
6. saenggibu spec wins over the scorer on register conflicts. Scorer down in
   night mode → log + continue with the Codex pass only.
Tool inventory note: pantadex exposes exactly score_ai_tells / humanize_full /
humanize_scorer_health — no report-specific humanizer exists; humanize_full
genre options are essay/news/blog/qa/dialogue (use news for reports).

## K2. Level-fit gate (v0.5.2, operator-requested 2026-07-07 — "이론이 대학 수준")

The report must read like THIS student at THIS point in the curriculum wrote
it — not like a compressed undergraduate text.

1. **Stage 2 — concept budget.** `01_design.md` MUST include a 개념 예산:
   - allowed: concepts the student has learned / is learning (from
     request.scope + kb/curriculum profile achievement standards + prior
     inquiries), each with the naming the TEXTBOOK uses;
   - forbidden: college/discipline jargon (with the HS-level substitute to
     use instead). Background theory (e.g. citing a theorem by name) is
     allowed ONLY with a one-line plain-language gloss and no derivation
     beyond budget.
2. **Stage 4 — level-fit review (BEFORE Codex AI-tell hunt).** A fresh
   reviewer (opus, high; persona: 해당 과목 고교 교사 who knows exactly what
   the class covered) audits the draft against the concept budget: flags
   every term/concept/notation/explanation-density beyond level, suggests
   HS-level replacement. Writer fixes, reviewer re-checks changed parts.
   Full Stage-4 order (v0.5.2): write → level-fit → fix → Codex AI-tell hunt
   → fix → humanize gate (§K order preserved after level-fit).
3. **Stage 5.7** — the value/subject-fit panelist scores level-fit against
   the same concept budget (dimension: 수준 정합).
Anti-pattern: do NOT dumb down the verified math itself — lower the
TERMINOLOGY and explanation style, keep the derivation. If a concept can't
be expressed within budget, that content moves to "후속 탐구" instead.

## L. Stage 5.7 — final evaluation panel (new stage, before 5.5 hand-off)

Fresh contexts, rubric scorecard written to `output/scorecard.json`:
sonnet-vision (form fidelity "does it look like a human filled THIS form",
figure human-ness/accuracy, table cleanliness, residual visual anomalies) ·
Codex (rigor, logic, numbers vs gate_result, citation coverage via sidecar) ·
opus-fresh (inquiry value, subject/curriculum fit, human-writing feel) ·
code (pages/figures/must_include/scope compliance). Weighted score below
threshold → targeted loopback to the owning stage (max 2), else blocked.
studio renders the scorecard.

## M. kb/ (repo) — accumulation loop

`kb/curriculum/`, `kb/source-registry.md`, `kb/figure-recipes/`,
`kb/trouble-table.md`, `kb/model-log.md`, `kb/style/` (R+H only; P banned).
Stage 0 reads; Stage 6 distills (recurring TROUBLES rows promoted, reusable
sources registered, curriculum profile updated, model win/fail appended).
PantaDex wiki sync at Stage 6.

## N. studio v0.5 scope

Read-only, no subprocess, no network, localhost — unchanged. Adds: events
timeline, heartbeat staleness banner, Your-move panel (exact APPROVALS.md
line / blocked reason + resume command), live fill-iteration PDF + iteration
selector, draft HTML preview (pre-COM) with provenance click-through,
scorecard panel, gate audit strip (auto_approved = amber warning), progress
chips with build.yaml targets, New-Report helper (generates request.yaml text
+ start prompt, copy only). Legacy non-YAML fallback kept but tagged 구형.
