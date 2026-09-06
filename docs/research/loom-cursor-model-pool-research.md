# Loom Cursor Cloud Agent model pool — product-completion cards

Point-in-time research (2026-09-06). **No product code.** This is a
routing note for Loom so it stops snap-picking one model for every
install-candidate card.

This is **not** the buyer-facing skill-tier table. That table lives at
`skill/references/model-routing.md` (pointer:
`docs/research/model-routing.md`) and measures Claude Sonnet vs Opus on
form fill. This file answers a different question: which **Cursor Cloud
Agent launch id** to use for Rigorloom *desktop product-completion*
work.

Operator constraints (Hayul):

- Never launch Composer / `composer-2.5`.
- Use **both** the Cursor Models pool (Grok) and the Other Models pool
  (Claude / GPT / Gemini / …). Grok-only is a failure mode.
- Do not hoard the monthly Other Models allowance (do not default every
  card to Opus; do not refuse Other Models entirely so the allowance
  sits unused).

## 1. What Loom has been doing

On 2026-09-06, every sand-sourced Cloud Agent on this repository
launched as `cursor-grok-4.6-high-fast`, including agents whose *names*
asked for Claude:

| Agent | Stated job | Launch model |
| --- | --- | --- |
| Card1 export safety on #333 | card 1 | `cursor-grok-4.6-high-fast` |
| Card3 run-scoped edit on #330 | card 3 | `cursor-grok-4.6-high-fast` |
| Implement #254 on desktop #221 tip | card 2 fence | `cursor-grok-4.6-high-fast` |
| Claude over-eng audit vs 5 cards | independent review | `cursor-grok-4.6-high-fast` |
| Rigorloom GitHub progress audit | research | `cursor-grok-4.6-high-fast` |
| Rigorloom status audit | research | `cursor-grok-4.6-high-fast` |
| This file | research | `cursor-grok-4.6-high-fast` |

That is the snap-pick. Grok 4.6 is a strong *implementation* model
(§3.2). It is the wrong *only* model: it burns no Other Models quota,
gives no vendor-diverse review, and it is how a “Claude over-eng audit”
ran on Grok.

## 2. Stack the cards actually touch

`main` still has no `desktop/` (`a635289`, #149). The product tip is
unmerged. Skimmed from #221 / #330 (`0211c1888ad5` / `9f59b31`) and the
card audit in #329 — not from renderer-research tips.

| Layer | What it is | Why the card cares |
| --- | --- | --- |
| Desktop shell | Tauri 2 + React 18 + TypeScript 5.9 + Vite (`desktop/src`, `desktop/src-tauri`) | Cards 1–4 are FE + packaged-app work. `actions.ts` is the public click/save path; `revision.ts` holds the edit lease. |
| Runtime sidecar | Packaged Python Runtime (`runtime.ts` → `document/pageGeometry`, `set_run`, inspect/plan/apply) | Card 2 binds `runId` + document SHA. Card 3 splices one run and queues `set_run`. |
| HWPX engine | `engine/scripts` (preedit / `set_run` / form inspect) + writer stack `#177–#224` (`hwpx_write.py` exists on desktop tips, not on `main`) | Card 1 is export/save + crash around those bytes. Card 3 must not flatten neighbour runs (`charPrIDRef` stays). |
| Own renderer | `own_render.py` line boxes (`text`, `char_x`, `address`) | Card 3 wants one additive `run_spans` field when the renderer line unfreezes. **Do not rematch desktop onto renderer research to close a card.** |
| Studio | localhost Python dashboard (`studio/`) | Not the product editor. Do not send card work here. |
| Packaging | `scripts/package_module.py --verify` (zip SHA / `MANIFEST.json`) | Card 5 is a *Windows install* hash outside the checkout, not this zip helper alone. |

Card PASS definition (from #329; do not redefine):

| Card | PASS requires |
| --- | --- |
| 1 export / save safety | Existing bytes preserved; fail / crash / force-quit / receipt regressions |
| 2 draft-fence FE | Stale async plan must not overwrite newer input |
| 3 run-scoped edit | One plain-text run (wrapped lines included); selected run only; source-map = revision + run + UTF-16 |
| 4 Korean mixed E2E | Real install; mixed formatting, long paragraphs, tables; edit → undo/redo → AI review → save → reopen |
| 5 install hash | Exact source / EXE / sidecar / installer hashes verified **outside** the checkout |
| 6 short audits | Over-engineering / doc-only contract review. No product code. |

#330 already implemented the card-2 lease on the #221 tip (Grok). #333
implemented first-scope card 3 on top of #330 (also Grok). Those are
existence proofs that Grok *can* ship a narrow desktop slice. They are
not a reason to keep launching every follow-up on Grok.

## 3. Evidence used (and what it is not)

### 3.1 Two Cursor usage pools

Cursor’s own docs, not folklore:

- [Models & Pricing](https://cursor.com/docs/models-and-pricing): two
  monthly pools. **Cursor Models** = Grok 4.6, Grok 4.5, Composer 2.5
  (generous included usage). **Other Models** = every third-party id,
  billed at API list price.
- [Usage and limits](https://cursor.com/help/models-and-usage/usage-limits):
  Pro / Pro+ / Ultra include both pools. Unused Other Models usage does
  **not** roll over. Composer is in the Cursor Models pool; Claude / GPT
  / Gemini / Kimi are not.

List prices used below (per million tokens, Cursor pricing page,
2026-09-06):

| Launch id | Pool | Input | Output | Notes |
| --- | --- | --- | --- | --- |
| `grok-4.6` | Cursor Models | $2 (Fast $4) | $6 (Fast $12) | Jointly trained by Cursor and SpaceXAI |
| `composer-2.5` | Cursor Models | $0.50 | $2.50 | **Banned for Loom. Do not launch.** |
| `claude-sonnet-4-6` | Other Models | $3 | $15 | 1M context; no long-context surcharge |
| `claude-opus-4-6` | Other Models | $5 | $25 | Same; Cursor now recommends Opus 5 at the same price |
| `claude-opus-4-5` | Other Models | $5 | $25 | Older Opus. Do not pick over 4.6 |
| `gpt-5.6-sol` | Other Models | $4 | $20 | 2× input above 272k; Fast is 2× |
| `gpt-5.5` | Other Models | $5 | $30 | Costlier than Sol, weaker on CursorBench |
| `gpt-5.4` | Other Models | $2.50 | $15 | Mid OpenAI; not a card primary |
| `gpt-5.3-codex` | Other Models | $1.75 | $14 | Cursor: ~⅓ Opus price, Terminal-Bench lead |
| `gemini-3.1-pro` | Other Models | $2 | $12 | 1M context; long-context surcharge above 200k |
| `gemini-3.8-flash` | Other Models | $0.75 | $3.50 | 1M max; cheap cached reads |
| `kimi-k2.7-code` | Other Models | $0.95 | $4 | Hidden by default |

“Do not over-hoard monthly Cursor quota” in this file means: **spend
Other Models where a documented strength earns it; keep long crash/E2E
loops on Grok so one card cannot empty the Other Models pool; never
default to Opus.** Hoarding the Other Models pool by launching
Grok-only is the current bug. Emptying it on Opus is the opposite bug.

### 3.2 CursorBench 3.2 (vendor, editor-agent tasks)

Source: [cursor.com/cursorbench](https://cursor.com/cursorbench),
changelog through 2026-09-02 (Gemini 3.8 Flash added). CursorBench is
Cursor’s own multi-file agent harness (instruction following + tool
use). It is **not** a Hangul / HWPX / Tauri bench. Treat ±1–2 points as
noise.

Selected rows (score / cost per task / tokens / steps):

| Model | Score | $/task | Tokens | Steps |
| --- | ---: | ---: | ---: | ---: |
| Grok 4.6 Extra High | 70.8% | 2.81 | 41k | 46 |
| Grok 4.6 High | 69.9% | 2.34 | 32k | 39 |
| Gemini 3.8 Flash High | 69.2% | 2.38 | 82k | **161** |
| GPT-5.6 Sol Max | 67.2% | 5.69 | 28k | 48 |
| Grok 4.6 Medium | 67.1% | 1.28 | 18k | 29 |
| GPT-5.6 Sol High | 63.5% | 2.79 | 14k | 32 |
| Claude Opus 4.8 Max | 62.3% | 5.77 | 71k | 44 |
| Claude Sonnet 5 Max | 61.5% | 4.30 | 93k | 86 |
| GPT-5.5 High | 58.4% | 2.05 | 12k | 28 |
| Composer 2.5 | 56.1% | 0.44 | 14k | 33 |
| Kimi K2.7 Code | 49.7% | 1.43 | 31k | 58 |

Loom’s listed Claude ids are **4.6 / 4.5**, which do not appear on this
3.2 board (4.8 / 5 / Fable do). Do not pretend Sonnet 4.6 scored 61.5%
— that row is Sonnet 5. Directionally, current Sonnet/Opus-class models
are *behind* Grok 4.6 High on this harness and *much* more expensive
per task.

Caveats, marked:

- **Home-field (uncertain).** Grok 4.6 is jointly trained by Cursor and
  SpaceXAI. A third-party writeup of CursorBench 3.2 notes Cursor
  flagged that Grok 4.5 *may* have seen a Cursor codebase snapshot in
  training ([Petralian](https://petralian.com/posts/cursorbench-3-2-fable-5-composer-2-5-cost-vs-score)).
  Exact impact on 4.6 is unpublished. Do not treat the 69.9% as an
  independent SWE-bench.
- **Gemini Flash High is a trap for fence work.** 69.2% looks close to
  Grok High, but 161 steps / 82k tokens is agent churn. A one-line
  lease bug is exactly the kind of task churn misses.
- **Composer is cheap and banned**, and 13 points behind Grok High.
  That is two independent reasons not to launch it.
- **Kimi K2.7 Code is not a card model.** 49.7% and 58 steps. Moonshot
  vendor benches (SWE-bench Pro, etc.) are a different harness; they do
  not rescue this Cursor agent row.

### 3.3 Cursor model-page claims (vendor)

Quoted strengths, used only where they match a card:

- [Grok 4.6](https://cursor.com/docs/models/grok-4-6): long-running
  tool loops (“checking results, and adjusting”); documents /
  spreadsheets / PDFs; better instruction following than 4.5. Effort
  High is the default; Extra High is the 0.9-point CursorBench bump.
- [GPT-5.3 Codex](https://cursor.com/docs/models/gpt-5-3-codex): “leads
  Terminal-Bench by a wide margin”; “on par with Opus 4.6 on our
  internal benchmarks, at roughly one-third the price”; “grinds through
  … deep debugging.” Style “less polished than Opus on
  architecture-heavy tasks.”
- [GPT-5.6 Sol](https://cursor.com/docs/models/gpt-5-6-sol): persistent
  multi-hour agents; “less comment and final-message slop than many
  Claude models.” Limitations: over-uses subagents; instruction
  following can lag Claude on some agent-behavior evals; 2× input
  above 272k tokens.
- [Claude Opus 4.6](https://cursor.com/docs/models/claude-opus-4-6):
  plans before it acts; code review and production-critical changes;
  intent tracking. Limitations: **most expensive**; **can
  over-elaborate or drift**; overconfident with thin context. Cursor
  now points operators at Opus 5 at the same price — Loom’s id is
  still 4.6.
- [Claude Sonnet 4.6](https://cursor.com/docs/models/claude-4-6-sonnet):
  everyday coding + thinking without Opus pricing; 1M context, no
  long-context surcharge. Cursor now recommends Sonnet 5.
- [Gemini 3.1 Pro](https://cursor.com/docs/models/gemini-3-1-pro):
  images + code; “UI/UX … frontend … visual code understanding”; 1M
  context. Long-context surcharge above 200k.
- [Gemini 3.8 Flash](https://cursor.com/docs/models/gemini-3-8-flash):
  cheap high-throughput coding; 1M max; 90% cache-read discount.

### 3.4 In-repo measurements (different product surface)

`skill/references/model-routing.md` (measured 2026-08-07/08, Claude
agents, form-fill A1, clean-room):

- Inspect / fill / verify: **Sonnet**. Same machine checks as Opus
  after surface fixes. Round 3: Sonnet 182k tokens, Opus 159k, identical
  verdicts.
- Diagnosis (“why is this wrong?”): **Opus**. Causal explanations
  Sonnet did not produce (charPr trap, cp949 `--help` crash).
- Governing rule: if the cheap tier needs judgment because the CLI is
  vague, **fix the surface**, do not escalate the tier.
- One non-Claude data point: a Codex harness (sol / terra / luna) could
  drive the shipped fill surface; luna needed more retries. Not
  comparable token accounting.

That table is about *running the skill*, not about editing
`desktop/src/actions.ts`. Keep the rule: exact CLI / hash / receipt
work does not need Opus. Use it when the job is *understanding* a
failure the tests cannot attribute.

`docs/research/skill-efficiency-gen5.md` (2026-08-06): 5-gen models are
degraded by 4.x scaffolding (mandatory plan gates, ritual checklists).
Card prompts should state the contract and the refuse tokens, not a
second architecture.

`AGENTS.md` role names: `high-reasoning`, `research`, `vision`,
`mechanical`, `independent-review`. Assign those, then pick a launch
id. Do not assign by vendor slogan.

### 3.5 Korean text — honest gap

Card 4 is Korean mixed-format (long paragraphs + tables + undo/redo +
AI review). Public 2025 Hangul benches (GEM linguistic competence;
Korean Pharmacist Licensing Exam) predate Grok 4.6 / Gemini 3.1 Pro /
Claude 4.6 and are **not** cited as a ranking. This repo’s own renderer
line (PR #322) treats the Korean break unit as the syllable — that is
engine research, parked for cards.

**Uncertainty:** no public 2026 Hangul+HWPX+IME bench for the Loom id
set. Card 4 therefore uses Grok for the long install loop (quota +
documented document/tool persistence) and Gemini 3.1 Pro when the
failure is visual / table / page, not “the agent got tired.”

## 4. Pool policy for Loom

Launch ids only from the operator subset. Preferred **variants**:

- `grok-4.6` at **High** (not Extra High unless a card is stuck; +0.9
  CursorBench / +20% $). Fast is acceptable on the Cursor Models pool.
- Other Models: standard (non-Fast) unless the operator asks. Fast is
  2× on Sol and Grok.
- Never `composer-2.5`, never Auto/Router (Router can land on
  Composer).
- Never `kimi-k2.7-code` for cards 1–5.
- Never `claude-opus-4-5` when `claude-opus-4-6` exists.
- Never `gpt-5.5` as a primary (CursorBench 58.4% High, $5/$30 — worse
  and costlier than `gpt-5.6-sol`).

Spend pattern per week of card work:

| Pool | What it is for |
| --- | --- |
| Cursor Models (`grok-4.6`) | Long loops: crash/force-quit matrix, real-install E2E, mechanical hash scripts once the contract is known |
| Other Models (Sonnet / Codex / Gemini) | Fence + encoding contracts, independent review, visual/Korean page failures, short packaging notes |
| Other Models (Opus 4.6) | Escalate only: unattributed crash, reverse-order click still leaking, UTF-16 vs grapheme dispute, Korean layout diagnosis |

That uses **both** pools without parking the monthly Other Models
allowance and without letting one Opus session eat it.

## 5. Use X for Y because Z

### Card 1 — export / save safety + crash / force-quit

**Use `grok-4.6` (primary)** because the job is a long tool loop:
install or sidecar, save, kill, reopen, compare bytes/receipts. Cursor
documents exactly that strength; CursorBench High is 69.9% at $2.34
with 39 steps (low churn); the spend stays on the generous Cursor
Models pool so a 20-case crash matrix does not empty Other Models.

**Use `gpt-5.3-codex` (backup)** because Cursor claims Terminal-Bench
leadership and “deep debugging” at ~⅓ Opus price. A hung sidecar / COM
/ force-quit harness is Codex-shaped (process, exit codes, flaky
repro). Other Models spend is justified if Grok’s first matrix is
green-but-wrong (tests that never actually kill the app).

**Avoid `gemini-3.8-flash`** because 161 CursorBench steps is churn;
churn writes extra tests that do not kill the process. **Avoid
`claude-opus-4-6` as primary** because Cursor’s own limitation is
over-elaboration — the writer stack (#177–#224) is exactly where this
repo already over-built. **Avoid `kimi-k2.7-code`** (49.7%).

**Escalate to `claude-opus-4-6`** when a crash is not attributable
after one Grok matrix and one Codex harness pass (in-repo rule:
diagnosis is Opus work). Do not escalate because “export feels
important.”

### Card 2 — draft-fence / stale async plan (frontend)

**Use `claude-sonnet-4-6` (primary)** because the defect is a public
effect / lease, not a new renderer. #254 showed a helper refusal
converted into an old `clickOverlaySpan` write; #330’s fix is
“superseded work is a silent no-op.” Claude’s documented habit
(“plans before it acts,” intent across turns) matches “do not convert
a stale refusal into a selection.” Sonnet, not Opus: in-repo fill
work was Sonnet-complete once the contract was explicit, and Cursor
prices Sonnet at $3/$15 with no long-context surcharge. This is the
Other Models spend that stops Grok-only.

**Use `grok-4.6` (backup)** because #330 already landed on Grok. If
Sonnet bikesheds `revision.ts`, Grok can implement a written lease
without a second architecture.

**Avoid `gemini-3.8-flash`** (step churn on a one-line freshness
guard). **Avoid `gpt-5.6-sol` as primary** — Cursor says Sol can wait
for an explicit “do it” and over-spawn subagents; a fence PR that
grows a new snapshot type is a regression (#253 LayoutSnapshot stays
parked). **Avoid Opus as primary** — Cursor: over-elaborate; Hayul’s
audit card exists because Claude research already over-built.

**Escalate to `claude-opus-4-6`** only if reverse-order clicks still
write after Sonnet + Grok, or if Runtime profile routing and the
public handler disagree (the #254 ablation that needed *both* layers).

### Card 3 — run-scoped edit (UTF-16 / source-map / one run)

**Use `gpt-5.3-codex` (primary)** because the remaining work is
offset arithmetic and a refusal table (`cross_run`, `utf16_split`,
revision mismatch), not a redesign. Cursor: Codex ≈ Opus 4.6 on
internal coding benches at ~⅓ price; Terminal-Bench lead matches
“write a Node harness that proves supplementary-plane offsets.”
`offsetUnit: "utf-16"` is JavaScript / HWPX code units — a model that
grinds tests is the point. This is Other Models, not Grok-only.

**Use `grok-4.6` (backup)** because #333 already shipped first-scope
card 3 on Grok (wrapped line, multi-run, `cross_run`, supplementary
plane, stale lease). Follow-ups that are “make the existing harness
stricter” can stay on Grok.

**Avoid `gemini-3.8-flash`** — 82k tokens / 161 steps to maybe get
UTF-16 wrong (code points vs code units is a one-character bug).
**Avoid `kimi-k2.7-code`.** **Avoid flattening the paragraph** as a
“simplification” — any model that proposes that fails the card.

**Escalate to `claude-opus-4-6`** when reviewers disagree on
UTF-16 vs Unicode code point vs grapheme, or when a span wants to
join neighbour runs and someone argues for flatten. That is contract
diagnosis, not more splice code.

### Card 4 — Korean mixed-format E2E on a real install

**Use `grok-4.6` (primary)** because PASS is a *long* loop on a hashed
Windows install (edit → undo/redo → AI review → save → reopen), not a
renderer IoU. Grok’s documented document + multi-step tool loop, plus
Cursor Models pool economics, is why this card must not start on
Gemini 3.1 Pro 1M (long-context surcharge above 200k) or Opus ($5/$25
and over-elaboration). #184 (undo two tiers) is already on the
desktop line; the agent’s job is to *drive the install*, not invent
undo.

**Use `gemini-3.1-pro` (backup)** because Cursor documents image+code
and frontend/visual understanding. If the Grok loop fails on a table
cell, wrapped Hangul, or “reopen does not show what we saved,” switch
to Gemini for a **screenshot-grounded** pass — not to start a new
renderer tip.

**Avoid `gemini-3.8-flash` as the E2E driver** (churn × long loop =
quota burn on Other Models). **Avoid Opus as primary. Avoid
`gpt-5.6-sol` as primary** — 2× input above 272k makes a “read the
whole desktop + engine” session the hoarding failure mode.

**Escalate to `claude-opus-4-6`** for Korean *layout diagnosis* (why
this table cell / syllable / 자간 is wrong) after Grok and Gemini
disagree. Escalate to `gemini-3.1-pro` mid-run if the log is clean
and the page is wrong — that is vision, not more reasoning.

Hangul quality ranking across Grok / Gemini 3.1 / Claude 4.6 is
**unmeasured**. Do not claim a winner.

### Card 5 — install-candidate hash verification / packaging notes

**Use `gemini-3.8-flash` (primary)** because the job is short,
high-throughput, and contract-shaped: read `package_module.py`
`--verify`, `MANIFEST.json`, sidecar/EXE hashing notes; write the
outside-checkout procedure. Flash is $0.75/$3.50 with cheap cache
reads — this is how Other Models quota gets used *without* being
hoarded for Opus. CursorBench 69.2% is enough for notes; the 161-step
failure mode is bounded if the prompt forbids new packaging
architecture.

**Use `grok-4.6` (backup)** because this is mechanical/exact-CLI work
in the in-repo sense (Sonnet-tier). If Flash starts redesigning
`ZIP_EPOCH`, move to Grok with “verify only, no new hasher.”

**Avoid Opus and Sol** (price, slop, subagents). **Avoid treating
`scripts/package_module.py --verify` as card 5 PASS** — #329 requires
hashes of a real Windows install *outside* the checkout.

**Escalate to `claude-sonnet-4-6`** if the MANIFEST schema and the
installer sidecar disagree (contract review, still not Opus).

### Card 6 — short audits / over-engineering / doc-only contracts

**Use `claude-sonnet-4-6` (primary)** because this is the
`independent-review` role. In-repo, Opus earned its keep on *causal*
diagnosis; Sonnet was enough for verify-the-contract. Cursor: same
provider style as Opus at $3/$15. The previous “Claude over-eng
audit” (#329) was launched on Grok — do not repeat that. Prompt:
read-only, no product code, no new probe framework.

**Use `gemini-3.8-flash` (backup)** as a cheap second reader on a
finished markdown file (1M window, $0.75 input). Not as the first
auditor of a 200-PR conveyor.

**Avoid `grok-4.6` as the auditor of Grok implementation PRs**
(cards 1/3). Vendor-diverse review is the point of the Other Models
pool. **Avoid Opus as the default auditor** — Cursor lists
over-elaboration; this repo’s last two weeks of Claude motion
(#301–#328, +46k lines, zero card PASS) is the exhibit.

**Escalate to `claude-opus-4-6`** only when the audit question is
“why is this wrong?” and Sonnet’s answer is a symptom list (the
measured Sonnet/Opus split).

## 6. Global avoid list

| Id | Why |
| --- | --- |
| `composer-2.5` | Operator ban. Also CursorBench 56.1% vs Grok High 69.9%. Auto/Router can select it — do not use Auto. |
| `kimi-k2.7-code` | CursorBench 49.7%, 58 steps. Vendor SWE numbers are a different harness. |
| `claude-opus-4-6` as default | Other Models hoard; Cursor: over-elaborate; this repo already has a Claude over-build conveyor. Escalate-only. |
| `claude-opus-4-5` | Older than 4.6 at the same price class. |
| `gpt-5.5` | 58.4% CursorBench High; $5/$30 vs Sol $4/$20. |
| `gpt-5.4` | No reason over Codex (tests) or Sol (long agent) or Grok (pool). |
| `gemini-3.8-flash` on fences / UTF-16 / E2E driver | Score looks fine; 161 steps do not. |
| Grok-only | Current Loom bug. Violates the both-pools constraint. |
| Renderer rematch / new IoU / LayoutSnapshot | #329: park. No model should reopen that conveyor to “help” a card. |

## 7. Loom launch table

Launch the **primary**. If the first PR comes back as a new
architecture, a rematch, or a probe framework, stop and launch the
**backup** on the same tip SHA. Escalate only on the trigger in the
last column.

| Task | Primary | Backup | Escalate when |
| --- | --- | --- | --- |
| 1. Export / save safety + crash / force-quit | `grok-4.6` | `gpt-5.3-codex` | `claude-opus-4-6` — crash still unattributed after one matrix + one harness |
| 2. Draft-fence / stale async plan (FE) | `claude-sonnet-4-6` | `grok-4.6` | `claude-opus-4-6` — reverse-order click still writes, or Runtime vs public handler disagree |
| 3. Run-scoped edit (UTF-16 / source-map) | `gpt-5.3-codex` | `grok-4.6` | `claude-opus-4-6` — UTF-16 vs code-point vs grapheme, or flatten-the-run argument |
| 4. Korean mixed E2E on real install | `grok-4.6` | `gemini-3.1-pro` | `gemini-3.1-pro` if the page is wrong and the log is clean; `claude-opus-4-6` if Grok and Gemini disagree on *why* |
| 5. Install hash / packaging notes | `gemini-3.8-flash` | `grok-4.6` | `claude-sonnet-4-6` — MANIFEST vs installer sidecar contract conflict |
| 6. Short audits / over-eng / doc contracts | `claude-sonnet-4-6` | `gemini-3.8-flash` | `claude-opus-4-6` — audit needs a cause, not a symptom list |

Pool mix of **primaries**: Grok (Cursor Models) on cards 1 and 4;
Other Models on cards 2, 3, 5, 6. Every card has a cross-pool backup.

## 8. What would change this table

Revisit if any of these become true:

1. Loom gains `claude-sonnet-5` / `claude-opus-5` / `claude-opus-4-8`.
   Cursor already recommends those over 4.6 at the same price class.
   Swap Sonnet 4.6 → Sonnet 5 and Opus 4.6 → Opus 5 **ids only**; the
   escalate-not-default rule stays.
2. A Hangul+IME+HWPX bench exists for this id set. Then card 4’s
   backup/escalate between Gemini and Opus can stop being a guess.
3. CursorBench publishes Sonnet 4.6 / Opus 4.6 / GPT-5.3 Codex /
   Gemini 3.1 Pro rows on 3.2. Several Loom ids are missing today.
4. Other Models allowance is actually exhausted mid-month. Then
   temporarily move card 5 and card 3 backup onto `grok-4.6`; do not
   move card 6 (review) onto Grok.

## 9. Sources

- Cursor: [Models & Pricing](https://cursor.com/docs/models-and-pricing),
  [Usage and limits](https://cursor.com/help/models-and-usage/usage-limits),
  [CursorBench 3.2](https://cursor.com/cursorbench),
  [Grok 4.6](https://cursor.com/docs/models/grok-4-6),
  [GPT-5.3 Codex](https://cursor.com/docs/models/gpt-5-3-codex),
  [GPT-5.6 Sol](https://cursor.com/docs/models/gpt-5-6-sol),
  [Claude Opus 4.6](https://cursor.com/docs/models/claude-opus-4-6),
  [Claude Sonnet 4.6](https://cursor.com/docs/models/claude-4-6-sonnet),
  [Gemini 3.1 Pro](https://cursor.com/docs/models/gemini-3-1-pro),
  [Gemini 3.8 Flash](https://cursor.com/docs/models/gemini-3-8-flash).
- Third-party CursorBench writeup (home-field caveat):
  [Petralian, CursorBench 3.2](https://petralian.com/posts/cursorbench-3-2-fable-5-composer-2-5-cost-vs-score).
- In-repo: `skill/references/model-routing.md`,
  `docs/research/skill-efficiency-gen5.md`, `AGENTS.md`,
  `scripts/package_module.py`, `studio/README.md`.
- Product cards / tips (unmerged): #221, #254, #329, #330, #332, #333;
  desktop tree on `cursor/revision-coherence-221-7f8c`.
- Cloud Agent launch ids: Cursor Cloud `list-cloud-agents` for this
  environment, 2026-09-06.
