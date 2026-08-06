# Skill efficiency for Claude 5-generation models

Research pass 2026-08-06. Sources: code.claude.com/docs/en/skills,
platform.claude.com skill-authoring best practices, Anthropic engineering post
"Equipping agents for the real world with Agent Skills", the official
skill-creator plugin (485-line SKILL.md), and the operator's own
`legacy-4x-playbook.md` (empirical: which scaffolding stopped paying off on 5-gen).

Honesty note: official docs carry **no gen-5-specific authoring section**. What
exists is one explicit model note (Opus test = "does the skill avoid
over-explaining?"), the "default assumption: Claude is already very smart" rule,
and the operator's measured experience that 4.x scaffolding (mandatory plan
gates, verification checklists, model routing) is counterproductive on 5-gen.
The gen-5 guidance below is derived from those three, and is marked (D) where
derived rather than quoted.

## 1. The cost model (what actually costs tokens)

| layer | loaded | cost behavior |
|---|---|---|
| metadata (`name`+`description`+`when_to_use`) | always, every session | truncated at **1,536 chars** in the listing; `description` capped at 1,024 |
| SKILL.md body | on trigger | **stays in context across turns** — every line is a *recurring* cost |
| `references/*.md` | on demand | zero until read; >100 lines → needs a TOC (partial reads happen) |
| `scripts/*` | **never** | executed via bash; only stdout costs tokens |

Rules that follow directly:
- Body under 500 lines; the real target for a router-style skill is far lower.
- References exactly **one level deep** from SKILL.md — nested refs get
  `head -100`'d and half-read.
- Anything deterministic goes in a script, because scripts are the only
  zero-context layer. "Solve, don't defer": scripts handle their own errors
  with verbose messages ("Field 'x' not found. Available: a, b, c"), no voodoo
  constants.
- Mutually exclusive contexts in separate files (domain split), so a task loads
  only its own branch.

## 2. What changes for gen-5 (D)

- **Cut explanation, keep constraints.** The docs' conciseness test ("does
  Claude already know this?") bites harder: 5-gen knows the *how*; the skill's
  value is the *contract* — invariants, gotchas, verdict formats, things that
  are true about THIS system and undiscoverable from priors. The trouble-table
  is the model of skill-worthy content; a COM API tutorial is not.
- **Degrees of freedom become the core design decision.** Low freedom (exact
  script, "do not modify the command") only where the ground truth is fragile:
  XML surgery, assembly order, itemCnt recomputation. High freedom everywhere
  judgment works: design, prose, review. 4.x needed low freedom as a crutch in
  judgment zones; 5-gen is actively degraded by it (legacy-playbook evidence).
- **Checklists only where skipping is a real failure mode.** Keep them for
  multi-step fragile workflows (the docs' form-filling pattern); drop the
  ritual ones. A gate the code enforces beats a checklist the model recites.
- **Examples still beat descriptions** for style/format outputs — unchanged by
  generation.

## 3. Claude Code levers worth wiring in

- `disable-model-invocation: true` — operator-triggered heavy flows (assembly,
  night runs) stop auto-firing.
- `user-invocable: false` — background knowledge that shouldn't be a command.
- `paths:` glob gating — skill only activates near matching files
  (e.g. `*.hwpx` → engine skill).
- `context: fork` (+`agent:`) — long deterministic subflows run in a subagent,
  keeping the main context clean.
- `allowed-tools` — pre-approve the skill's own scripts to kill permission
  friction inside the turn.
- **Dynamic context injection** `` !`cmd` `` — the line is replaced by command
  output *before* the model sees the skill. This is the natural home for the
  capability probe: the skill loads with live backend/module/renderer state
  already inlined, and the model never re-derives it.

## 4. Discovery (the undertrigger problem)

Claude currently *under*-triggers skills. Descriptions must be third-person,
front-load the key use case, name concrete triggers ("use when the user
mentions X, Y, .hwpx, 양식…"), and be a little pushy. One skill = one clear
activity (gerund names); no `helper`/`utils`. The 1,536-char listing cap means
trigger vocabulary competes with prose — spend it on nouns users actually type.

## 5. Evaluation discipline

- **Evals before docs.** Baseline the task with no skill; write the minimum
  that closes the observed gap; 3+ scenarios per skill.
- Iterate from *observed navigation*, not assumption: which files get ignored
  (delete or re-signal), which get re-read every run (promote into SKILL.md),
  where the model takes unexpected paths (structure isn't intuitive).
- Test on every model tier that will run it; Opus-tier failure mode is
  over-explanation, Haiku-tier is under-specification.

## 6. Consequences for rigorloom's W5 (skill restructuring)

1. Router SKILL.md per distribution bundle, well under 500 lines; module skill
   fragments merged at install (core-only buyer never sees report vocabulary).
2. All engine operations behind scripts returning JSON verdicts; `inspect`
   returns structure only, never body text — the existing hwp-master rule
   becomes a guarantee.
3. Capability probe output injected via `` !`probe --json` `` at skill load.
4. Trouble-table knowledge ships as *behavior* (guards inside scripts) first,
   *reference file* second, SKILL.md body never.
5. Freedom map documented per operation: fill/assembly/postedit = low freedom
   (exact CLI); form diagnosis/layout judgment = high freedom.
6. Skill evals live in the repo next to the corpus (Wave 6 non-report forms
   double as eval scenarios).
