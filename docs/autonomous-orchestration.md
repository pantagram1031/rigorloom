# Autonomous report orchestration — AUTO-mode playbook

The subject-agnostic layer that sits ON TOP of the pipeline master document. The
master document owns the pipeline mechanics; this document owns the *orchestration
principles* that actually produced human-passable reports in unattended runs. When
the two disagree on mechanics, the master document wins.

Trigger: an operator supplies a subject (or a form) and asks for an unattended
build. No human gate blocks the run — human gates are recorded as an autonomous
acknowledgement, never forged as a human approval. The deliverable is the assembled
document plus an exported PDF (plus a short summary deliverable), submit-ready.

---

## 0. Non-negotiables (every subject)

- **Non-destructive.** Never edit the original form or a prior submission. Work on
  copies. Assert the form hash before and after when filling a real form.
- **No fabrication.** Independent variables and results must come from a real,
  re-runnable computation the author could own. Numbers in prose are verbatim from
  the frozen results file. Fidelity is preserved through every later edit — style
  and AI-tell fixes never change facts.
- **Citations.** Papers and books only, one consistent standard format. No website
  citations.
- **Style.** Follow the resolved prose-rules preference pack: plain declarative
  prose, first person only where reflection is expected, no parenthetical-English
  gloss of ordinary translated terms (symbols and proper nouns are fine), no
  advanced-terminology name-drop, tense split between present (theory, model,
  figure) and past (actions actually taken), signature phrasing kept rare.
- **Curriculum anchor.** State or weave the subject-unit concept up front, before
  the body.
- **Log every trial-and-error step** to the run log, and update durable memory at
  the end.

---

## 1. The loop (phases) — run in order, parallelize within a phase

```
ORIENT → DECIDE → FAN-OUT(research ∥ sim ∥ figures) → SIM-REVIEW(freeze numbers) →
DESIGN → WRITE → CONTENT-REVIEW(AI-tell + framing council, on content) →
ASSEMBLE(COM, serial, ONCE) → VISUAL QA → FINAL ADVERSARIAL → (blocking → re-assemble) → DELIVER
```

**The ordering rule — the single biggest lesson: freeze everything textual and
numeric BEFORE the first COM assembly.** COM is slow and single-instance; every
content change forces a full re-normalize and re-assemble. Run the sim review
(freeze method and numbers), then write, then run the AI-tell and framing review
**on the content, not on the assembled document** — only then assemble. Target one
assembly plus at most one blocking-fix re-assembly per report. The first
unattended run did roughly three to four assemblies per report because reviews ran
*after* assembly; that is the anti-pattern this rule kills.

### 1.1 ORIENT (own it, do not delegate)

Read the master document, the resolved style/preference packs, the direction
context, the form structure, and any prior related report. **Verify hard
dependencies before spawning a fleet:** the numeric/plotting stack imports, the
document backend and its host application are present, and each external CLI
reviewer is on PATH. If the console encoding is not UTF-8 (a common Windows
default), prefix every script call with `PYTHONIOENCODING=utf-8` so non-ASCII
prints and `--help` output do not crash.

- **Precheck backends with the script, not by hand.** Run the backend precheck to
  produce a run-capabilities file; council seating reads THAT file, not a static
  status field. A degraded mode (an external reviewer down) means running multiple
  strong-model critics with distinct lenses and requiring unanimity — never a
  one-voice "council". One early run wasted a council and two review agents because
  a reviewer model silently required a newer CLI than was installed.
- **Prove risky COM primitives inline before delegating** (blank base create, seed
  doc, one build-and-edit to PDF). An assembly subagent once stalled for 15 minutes
  with zero output because a from-scratch base-doc step was never proven. Prove it,
  then hand off mechanical iteration — or just do the assembly inline, since it is
  serial anyway.

### 1.2 DECIDE (topic gate — council on judgment)

Gate the topic through the direction criteria. For an unattended run, prefer a
topic executable with NO human or physical step (a software/simulation deliverable
beats a topic that needs a physical measurement). For any real judgment call, hold
a **multi-agent council** — do not decide solo. Ratify or change, and record why.
Seats:

- **critic** — a strong-reasoning model at high effort, with an adversarial
  "no flattery" prompt. This is the primary critical voice for topic, framing, and
  risk.
- **second opinion** — an independent external reviewer. If it is unavailable, add
  a second strong-model critic with a *different* lens rather than running a
  one-voice council.

### 1.3 FAN-OUT (parallel background subagents)

- **researcher** (×N): real papers and books, each citation verified, one standard
  format, key numbers captured. Writes an evidence file plus a sources file. No web
  citations in the list.
- **sim-executor** (precise spec from the orchestrator): a real deterministic
  computation that self-verifies against a known reference value; emits a results
  file, a gate-result file, and refined figures.
- **figures**: self-drawn schematics (plotting library, copyright-safe, palette
  matched to the resolved figure-style pack). Do not download web images unless
  truly necessary.

### 1.4 Own the deterministic core

Write the sim spec yourself: exact parameters, PASS/FAIL gates, and a figure-style
block that references the resolved pack. After it runs, verify the numbers against
the literature yourself against a known reference value. Do not accept a simulation
you cannot independently sanity-check.

---

## 2. Verification stack (this is the value — do all of it)

The contract is: **every numeric claim is checked by two independent reviewers.**
Concretely:

1. **Sim review ×2.** Two independent adversarial reviewers, "find defects".
   Independence means separate reasoning paths (or one reviewer plus executable
   recomputation), not two calls in the same context. Apply real findings (e.g. a
   figure's edges must match the prose; a fit window must exclude a saturated
   regime).
2. **AI-tell hunt.** A reviewer scans the drafts and flags mechanical parallelism,
   stacked hedging, misplaced first person, and parenthetical-English gloss, each
   with a quoted phrase and a rewrite. Apply the fixes without changing facts.
3. **Framing council.** A strong critic at high effort, adversarial lens: is the
   topic still recognizably *this subject*? What is the biggest scientific or
   framing risk? Fix the spine if it drifts. **Run steps 1–3 on the content BEFORE
   the first assembly** — they change text and numbers, so doing them post-assembly
   forces a re-assembly.
4. **Visual QA.** A contact sheet of all pages plus a high-resolution zoom of every
   equation and figure page. Inspect each figure image at full resolution (not a
   thumbnail): confirm there are no missing-glyph boxes ("tofu") anywhere text was
   rendered into a figure, and that minus signs render as a proper minus rather
   than a missing glyph (a common failure when a CJK font is combined with a
   plotting library's default numeric formatting — set the library's
   unicode-minus option to off before rendering with a CJK font).
5. **Deterministic content gate BEFORE assembly (hard, exit-coded).** A content
   verifier must exit 0. It recompute-checks rather than trusts: no web citation,
   no prohibited endings, every figure reference resolves to a real file, the
   summary deliverable is within its byte budget, and (if a PDF exists) no
   equation-markup leak. Advisory WARN items (gloss, bare numeric reference labels,
   in-text vs bibliography mismatch) are surfaced but do not block. This automates
   several things a human previously had to catch by eye.
6. **Final adversarial review** (a fresh strong model at high effort, examiner
   lens, on the *finished PDF*): text vs figure consistency, over-claims, style,
   citation format, curriculum fit, plus the three stop-line fields (SENSITIVE
   FRAMING / LOAD-BEARING DISPUTE / UNSUPPORTED NOVELTY — any one vetoes to a human).
   **Blocking → fix → re-assemble → re-verify.** Only then is the report
   submit-ready.

> **Enforcement note.** These checks are currently orchestrator-run, so they remain
> skippable by an orchestrator that routes around them. The fail-closed design (an
> acceptance-side release verifier, a single build entrypoint, a claim-token
> lifecycle, hash-bound manifests) is specced in `plans/v0.7-hardening.md`. The
> content verifier and the backend precheck are its first delivered checkers.

### Subagent rules

- The prompt starts with "do not delegate to sub-agents" — no re-delegation.
- Return a compact structured result (JSON or a short verdict), never COM logs or
  raw dumps into the orchestrator context.
- Long work runs in the background and notifies on completion.

---

## 3. Assembly (HWP via COM) — the concrete recipe

- The content must be in the build grammar: top-level section headings, bold
  paragraphs for sub-headings, figure/equation/table directives with explicit file
  names, widths, captions, and inline vs display equations. Figures live in the
  bundle's figure directory. A normalizer converts authored content to ops.
- **Filling a real form:** section anchors must match the form's anchor text
  EXACTLY.
- **From scratch (no form):** the COM backend opens a base document (it does not
  create a blank), so: (a) create a blank base document and save it; (b) build a
  **seed** document — the section headings only, with the title and section shapes
  applied — via the backend; (c) the build step emits ops that goto-text each
  heading and apply them to the seed; (d) run the backend edit with the ops,
  save-as the output, and export the PDF; (e) convert to the final document format.
- **Equation gotchas:** a `\!\left(` renders the literal word "left" — drop the
  `\!`; split very wide equations into two lines. Plain `\left(...\right)` and
  `\frac` render fine. Always brace sub/superscripts. Verify by grepping the PDF
  text for `left(`, `frac`, and `[[` — each must be zero. (See T13/T14 in
  `trouble-table.md` for the underlying scope rules.)
- COM is single-instance → assemble reports **serially**. Prefix every command with
  `PYTHONIOENCODING=utf-8`.

---

## 4. Figure quality (does not look machine-generated)

The figure look comes from the resolved figure-style preference pack. The shipped
default is an engineering/boxed-axes preset (white background, four-spine box, a
light grid, ticks out, a fixed color cycle, a whitelisted colormap, small frameless
legends placed out of the data, high export DPI). Schematics are clean geometric
shapes with plain labels, no clip-art or emoji, and each figure is self-reviewed
for collisions and for style-rule violations in titles and captions.

**Never let the model's default editorial aesthetic through.** A muted "designer"
palette with soft pastels is a recognizable generation tell; the deliberate,
enforced preset is what makes a figure read as hand-made. Pick one preset via the
pack and enforce it — do not let each figure drift to whatever the model would draw
by default.

**Real diagrams.** For structural or conceptual figures (a process diagram, a
circuit, an anatomical drawing), prefer a real published diagram over a
self-drawn box-and-arrow schematic — a hand-built schematic reads as
machine-generated far more often than a genuine sourced figure does. Sourcing
procedure: search for a public-domain or Creative-Commons figure, and verify
the credit and license ON THE SPECIFIC IMAGE, not just on the page or site it
came from (a site-wide public-domain notice does not guarantee every embedded
image is unencumbered). National-agency and government archives are generally
reliable sources for this. If no cleanly licensed figure can be found, omit
the figure and describe the structure in prose instead — never fabricate a
diagram and never use an unlicensed one. Collect the credits for every figure
sourced this way into an endnote, not into the caption itself. Separately,
for function plots and small data figures, an interactive math tool (e.g. a
graphing calculator or geometry tool) produces an authentic, non-generated
curve — export it via the tool's own screenshot or export capability at high
resolution rather than re-drawing the curve by hand.

---

## 5. Subject routing (generalize)

Anchor each subject to its curriculum unit plus a consistent persona (mathematical
modelling + implementation + error analysis). A general lens — deterministic rule →
unpredictability/pattern → direct reproduction → model-limit — fits most
quantitative subjects; life-science topics take the same shape as
principle → engineering implementation → error, provided the domain hook is kept.
Keep every model epistemically honest: a toy model shows a *principle*; its numbers
do not transfer to the real system's values — say so in the limitations section.

(The concrete per-subject routing table is an operator persona artifact and lives
in the private profile, not here.)

---

## 6. Tooling facts

These are provider CLI details verified in real runs; they are safe to state
publicly and change slowly.

- **Text-only reviewer CLIs have no vision.** A text-only model CLI cannot see an
  image; visual and figure judgment (palette, collisions, tofu/glyph checks,
  layout) must be routed to a vision-capable agent instead. Never let a
  text-only reviewer fill a visual-QA rubric — its "verdict" there is not
  grounded in anything it actually looked at.
- **External reviewer CLI (codex family):** a given reviewer model can require a
  minimum CLI version (an older CLI reports "requires a newer version"). Invoke via
  `codex exec -m <model> -c model_reasoning_effort=high --skip-git-repo-check - < prompt.txt`.
  A Cloudflare-MCP 401 on stderr is harmless. Wrap the call in a `timeout`.
- **External reviewer CLI (grok):** `timeout 150 grok -p "<short>" --output-format json --always-approve`.
  The `-p` payload is argv (roughly a 32 KB cap, no stdin) → for long input, `cd`
  into the directory and tell it to read files by name.
- **Hung reviewer processes:** repeated stop-gate failures can leave orphaned CLI
  processes — kill the process tree early rather than letting them accumulate. Kill
  ONLY the owned process tree; never blanket-kill the host word-processor process
  (an interactive user session may have it open).

---

## 7. Deliverables checklist (per report)

- [ ] Assembled document + PDF, submit-named.
- [ ] All figures present and legible, captions with their figure, equations
      rendered (no `left`/`frac` leak).
- [ ] Tables with one-line rows; no orphan headings or mid-page voids.
- [ ] Citations papers/books, one consistent format, no web.
- [ ] Style rules clean; final adversarial review returns submit-ready.
- [ ] Short summary deliverable within its byte budget (special characters spelled
      out, no numeric over-claim).
- [ ] Non-destructive; trial-and-error logged; memory updated.

---

## 8. Integration with the pipeline (stage/gate mapping)

AUTO mode does NOT bypass the controller — it fills each stage with the
orchestration above and keeps recording state (human gates are recorded as
autonomous acknowledgements, never forged approvals).

| AUTO phase | pipeline stage / gate | note |
|---|---|---|
| ORIENT / DECIDE | setup + design (human `design`) | topic council replaces the solo call; recorded auto-approved |
| FAN-OUT research | research (multi-way fanout) | real papers/books; no web cites |
| FAN-OUT sim + **SIM-REVIEW** | sim (script gate) | two independent reviewers; **freeze numbers here** |
| DESIGN / cast-off | layout (script gate) | optional for from-scratch (no fixed page budget) |
| WRITE | write-to-budget (human `draft`) | main writer, target style; recorded auto-approved |
| **CONTENT-REVIEW** (AI-tell + council) | **Stage 4.5 content_audit** (script gate) | new gate; runs before assembly — see the reorder below |
| ASSEMBLE | assemble + proof | AUTO adds the from-scratch/no-form path (§3) |
| VISUAL QA | contact-sheet (vision judge) | orchestrator + a vision-judge on the sheet |
| understand | understanding gate (human) | recorded auto-approved |
| FINAL ADVERSARIAL | eval panel (scorecard) | fresh strong model at high effort, examiner lens, on the finished PDF |
| DELIVER + kb | return + wiki | archive, memory, run log, trouble-table |

**The one real reorder vs. the master document:** the pipeline historically ran its
eval/review panel after assembly. AUTO mode splits review in two — **content-level
review (AI-tell + framing council + sim-number freeze) runs on the content BEFORE
assembly, as the new Stage 4.5 content_audit gate**, and only **visual + final
adversarial** review runs post-assembly. The reason is cost: COM re-assembly is the
expensive step, so catching text/number/framing issues pre-assembly turns roughly
four assemblies into one plus one.

---

## 9. Anti-patterns (do NOT repeat)

1. **Assemble, then review, then re-assemble** (repeatedly). Freeze content first
   (§1 ordering rule).
2. **Delegate COM before proving the base-doc primitive** → a 15-minute silent
   stall. Prove it inline first.
3. **Rely on a model without a precheck** → a dead reviewer model silently killed a
   council seat plus two review agents. Trivial-call every backend in ORIENT; mind
   CLI version minimums.
4. **Decide topic or approach solo** → the operator had to intervene. Council on
   judgment from the start.
5. **Change sim methodology after writing** → prose and table rework. Freeze the
   sim in SIM-REVIEW.
6. **Skip style rules on figure titles** → a gloss slipped through to the final
   review. The style gate must cover titles and captions, not just body prose.
7. **Let hung reviewer processes accumulate** (a stop-gate loop) → wasted turns.
   Kill the owned process tree early.
