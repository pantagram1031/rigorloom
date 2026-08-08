# Model routing — which tier to run the skill on

Measured 2026-08-07 in the clean-room harness (the `evals/` clean-room harness in the source repository). This document is
about **using** the skill, not authoring it. It exists so a buyer can run the
cheap tier by default and escalate only where a measurement says to.

## Method

Two clean-room installs per tier, built from the shipped bundles only
(`cleanroom.py prepare` in that harness, zero allowed gaps, containment verified after every
run). Each agent received the sandbox path, the installed `SKILL.md`, and a
Korean user request — nothing else. Repo access was forbidden and verified
absent afterwards (`outside_sandbox_reads: []`, `contained: true`, 0 findings
in all four runs). No operator help, no hints.

Task: **A1** — inspect the 조달청 협업 승인 신청서 (native `.hwpx`, 1 table,
19×9, 45 cells), report the fillable fields, fill 10+ of them from supplied
values without altering the form's appearance, save `filled.hwpx`, and verify
it. Objective grading = the harness's 9 machine checks + containment; the
agents' own numbers are self-reported (see caveat).

Two rounds, because the first round measured the wrong thing:

- **Round 1** ran against v0.16.0 as released. Both tiers completed, but only
  by working around five product defects — no offline way to fill an empty
  cell, `set_cell` writing to the wrong cell (both tiers destroyed label
  cells), `replace` double-applying per its own documented example, the visual
  rubric absent from the bundle, and the residue keep-list unusable on fills.
- **Round 2** ran after those were fixed (PRs #59–#62). This is the round that
  measures tiers rather than defect-workaround cost.

## Measurements

| round | tier | outcome | machine checks | session tokens | self-reported steps / tools / retries |
|---|---|---|---|---|---|
| 1 (alpha) | Sonnet | completed | 8 pass / 0 fail / 1 skip | 288k | 30 / 78 / 2 |
| 1 (alpha) | Opus | completed | 8 pass / 0 fail / 1 skip | 184k | 24 / 64 / 4 |
| 2 (fixed) | Sonnet | completed | 8 pass / 0 fail / 1 skip | **132k** | 9 / 22 / 2 |
| 2 (fixed) | Opus | completed | 8 pass / 0 fail / 1 skip | 124k | 12 / 39 / 1 |
| 3 (full product) | Sonnet | completed | 9 pass / 0 fail / 1 skip of 10 | **182k** | 10 / 78 / 3 |
| 3 (full product) | Opus | completed | 9 pass / 0 fail / 1 skip of 10 | **159k** | 16 / 43 / 1 |

The fixes cut Sonnet's session cost by 54% and Opus's by 33%. In round 2 the
two tiers land within 6% of each other on tokens — and Sonnet's list price is
roughly a fifth of Opus's, so on the measured task Sonnet is the cheaper tier
by a wide margin for an identical machine-verified result.

**Round 3** ran the same task against the full product: all nine round-1/2
defects fixed, the charPr pre-flight in place, and all six modules enabled
(so the verification path is longer — a work-type checker now runs too, and
the machine-check count went 9 → 10 because A1 gained a module-gated check).
Both tiers completed with identical verdicts. Costs rose from round 2 because
the work grew, not because the tiers regressed: Sonnet 132k → 182k, Opus
124k → 159k, with Sonnet again ~1/5 the price per token.

**The round-3 result that changes the routing table**: in round 2 the only
quality difference between tiers was the superscript-charPr trap — Opus
root-caused it by reading `header.xml`; Sonnet did not and shipped a 6.35pt
raised fill. In round 3 `form_inspect`'s pre-flight named the anomalous cell
and the suggested charPr id, and **both tiers avoided the trap on the first
attempt without knowing the trap existed**. That is the surface-fix rule
paying off: the escalation point disappeared because the surface stopped
requiring judgement, not because the cheap tier got smarter.

**Caveat on self-reported numbers.** They are inconsistent: the Sonnet round-2
agent's narrative said 51 tool calls while its own `run.json` said 22. Treat
steps/tools/retries as directional only. Session tokens are platform-measured
and outcome/machine-checks are harness-measured; those are the numbers to
trust.

## Routing table

| task class | tier | basis |
|---|---|---|
| **inspect** (profile a form, report fillable fields) | Sonnet | measured, round 2 — both tiers identical output; anchors/tables/cells matched the pinned floors exactly |
| **fill** (values into cells, prefix-preserving edits) | Sonnet | measured, rounds 2 **and 3** — with `fill-cells`, `--addr` guards and the charPr pre-flight this is exact-CLI work. Round 3 is the stronger evidence: the one trap that previously separated the tiers is now caught by the tool, so both tiers fill correctly unaided |
| **verify / judge** (render → rubric → verdict) | Sonnet | measured, round 2 — Sonnet drove the render→judge loop to `acceptance: true` unaided |
| **diagnosis** (why is this output wrong, what is this document doing) | **Opus** | measured, both rounds — Opus produced causal explanations Sonnet did not: it root-caused the superscript-charPr trap to a specific charPr id, identified the missing pre-flight as a design gap, and found a shipped `--help` crash on cp949 consoles. Sonnet hit the same defects but reported them as friction |
| assemble (multi-section build, page budgets) | **not measured** | the measured task is single-page form fill; no claim |
| prose / humanize | **not measured** | the style module was installed but the task exercised no prose path; no claim |

Escalate to Opus when the job is *understanding* rather than *executing*:
an unexplained render defect, an unfamiliar form family whose fill targets
carry unknown formatting, or a failure the deterministic checks cannot
attribute. Everything on the documented CLI path is Sonnet work.

## Surface fixes, not tier escalation

The governing rule was: if the cheap tier struggles because a step leans on
model judgment where an exact CLI would do, fix the surface and re-measure.
That is what rounds 1→2 are. Every round-1 workaround became a shipped
mechanism — `preedit fill-cells` for empty runs, `set_cell --addr` with
`--expect-empty`, single-pass `replace`, the rubric inside the bundle,
`--fill-map` keep derivation. No task was declared Opus-only.

One round-2 friction remains and is being fixed the same way rather than
routed around: the keep-list treats a prefix-preserving fill
(`" http://"` → `" http://domain.kr"`) as unconsumed residue, which cost both
tiers a retry.

## Limits of this measurement

1. **One task, one form family.** A1 is a single-page grant/procurement form.
   Nothing here generalizes to multi-section documents or to the families with
   no corpus (school, corporate).
2. **One machine.** Hancom COM present, Korean-locale Windows. The cp949
   `--help` crash exists precisely because that platform was never exercised
   from a clean install before.
3. **Two tiers only.** Haiku was not measured; the gen-5 skill research warns
   the failure mode there is under-specification, which is exactly what the
   round-1 defects looked like. Worth measuring before claiming a floor.
4. **Authors' harness.** The tasks, rubric, and machine checks are ours. An
   independent party writing their own task would be a stronger proof and has
   not happened.
5. **Round-2 numbers included one known defect** (the keep-list derivation);
   round 3 ran after it landed. Round 3 in turn surfaced one gap that cost
   both tiers work: nothing shipped yielded the exact text of a printed
   non-anchor seat, so both agents ended up reading the artifact's own XML —
   Opus to build two replace keys, Sonnet because `text_preview` truncated at
   30 characters with no flag and hid a `(     개월)` blank. **Closed after
   the round** (T34): `replace --at-cell ROW,COL=값` addresses the seat run so
   no exact string is needed, `text_preview` now carries `truncated`, and
   `form_inspect --full-text ROW,COL` is the per-cell escape hatch. The
   numbers in this table are the pre-fix measurement; expect both tiers to
   drop on the next round.
6. **Every run so far is a Claude agent.** A different agent harness has not
   been measured, and the skill leans on at least one Claude-Code-specific
   mechanism (the capability probe is injected by an inline-command syntax).
   Whether the shipped surface works outside one vendor's harness is a
   separate axis of this table and is currently blank.
