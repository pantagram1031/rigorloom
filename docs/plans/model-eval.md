# Model evaluation ledger — which Cursor models are good enough for which step

Purpose: the user pays for Cursor capacity and wants routing grounded in this
repo's real tasks. Every row is the SAME spec given to several models; Fable
runs the acceptance/review itself. Usage comes from `--output-format json`
(`usage.inputTokens/outputTokens/cacheReadTokens`); prices are not known to the
CLI, so cost is reported as tokens + wall-clock.

## Tasks

| id | kind | spec | acceptance |
|---|---|---|---|
| W1 | Korean technical writing (expand 이론적 배경 with derivation + worked numbers + a table) | `scratchpad/eval-W1-theory-section.md` | 8 EQ tags byte-identical; numbers consistent with results.json (29.2 / 34.1 dB, A 39.1 m², T60 0.59 s); `check_style` 0 HARD; Fable rubric: correctness of derivation, Korean naturalness, level fit, no invented facts |
| C1 | bounded code change with tests (to be chosen from the Stage 2/3 backlog) | tbd | pytest acceptance in an isolated worktree |
| A1 | analysis / root-cause from logs (H1-like) | tbd | matches the verified root cause |

## Results

### W1 (2026-09-16)

Deterministic checks (Fable, 2026-09-16 21:05). All seven drafts: 8 EQ tags byte-identical, 0 `습니다`, 0 URLs, `check_style` 0 HARD / 0 WARN, 4 bold sub-heads (limit 4), 1–2 TABLE tags. Original section: 2,859 chars.

| model | chars | median para | worked numbers (τ, Σ, TL 29.24/34.10) | notes from the worked-example paragraphs |
|---|---|---|---|---|
| claude-opus-5-medium-fast | 6742 | 186 | correct | adds window share 84.1 % / wall 1.9 % as explanation; longest |
| claude-sonnet-5-thinking-high | 5755 | 182 | correct | clean, explains "창 Sτ만 1/5로" |
| gpt-5.6-sol-high-fast | 5944 | 194 | correct | adds the "dB cannot be area-averaged" caution |
| gpt-5.3-codex-high-fast | 5613 | 184 | correct | register slip: cites "결과 파일의 29.2398 dB" in body |
| cursor-grok-4.6-xhigh-fast | 5794 | 155 | correct | shortest paragraphs |
| cursor-grok-4.6-low-fast | 5555 | 207 | correct | one worked paragraph only, but right |
| composer-2.5-fast | 5597 | 180 | **rounding errors** (Σ 9.344e-3 vs 9.334e-3; τ 3.893e-4 vs 3.889e-4; 2.860e-2 vs 2.859e-2) | otherwise fluent |
| gemini-3.7-flash-high | — | — | — | run failed twice on a Cursor config-file race when launched in parallel; rerun serially pending |

Judge pass (gpt-5.6-sol-high-fast in agent mode reading all seven drafts, rubric a–e ×5, 7.9 min, 257k cache-read + 12 fresh input tokens, 4.6k output): grok-4.6-xhigh 25 > opus-5-medium 24 = sonnet-5 24 > sol 23 (flagged its own register slip "결과 파일의") > grok-4.6-low 21 > composer 20 (arithmetic) > codex-5.3-high 16 (working-notation leaks: A_baseline, dTL). Judge's recommendation: grok-4.6-xhigh — clearest energy-conservation derivation and worked numbers, one table caveat (a 합 row that could read as summing TL). Fable spot-check of the top draft follows in the ledger row below.

Usage per W1 run (CLI JSON `usage`; 8 sessions ran concurrently so wall-clock is inflated by throttling; `outputTokens` appears to count only the final chat message for some models, file writes are not always included — treat as indicative):

| model | wall | input | output | cache read |
|---|---|---|---|---|
| gpt-5.6-sol-high-fast | 11.6 min | 119 | 153 | 299k |
| gpt-5.3-codex-high-fast | 13.1 min | 56.8k | 1.2k | 550k |
| composer-2.5-fast | 15.8 min | 70.9k | 14.3k | 887k |
| cursor-grok-4.6-low-fast | 24.9 min | 237k | 18.5k | 1.40M |
| claude-sonnet-5-thinking-high | 36.8 min | 6 | 719 | 481k |
| claude-opus-5-medium-fast | 41.9 min | 66 | 47.6k | 3.83M |
| cursor-grok-4.6-xhigh-fast | 44.2 min | 254k | 46.4k | 2.72M |
| gemini-3.7-flash-high | failed ×3 | — | — | connection lost to agent endpoint every time (also once EPERM config race) |

Reading: for a 6k-char Korean section with worked numbers, sol/codex/composer/grok-low were 3–4× cheaper in cache tokens than opus/grok-xhigh, and codex/sol/grok-low all produced correct arithmetic; the quality gap showed up in register (codex, sol) and depth (grok-low), not in numbers. Composer alone made an arithmetic error. Launch note: starting 8 sessions within seconds hit `EPERM rename cli-config.json` for one of them — stagger launches by ≥ 3 s and keep concurrency ≤ 4 for usable wall-clock.

### C1 — port `page_numbers` / `header_text` (2026-09-16, 7 isolated worktrees, one spec)

| model | wall | acceptance (tests / compile / dry-run op idx 17) | diff size | implementation notes |
|---|---|---|---|---|
| cursor-grok-4.6-xhigh-fast | ~25 min | 203 passed / ok / ok | +400 −6 | pyhwpx `PageNumPos` wrapper when present, raw `HPageNumPos` action fallback; header via HeaderFooter; **adopted** |
| claude-opus-5-medium-fast | ~30 min | 208 passed / ok / ok | +395 −4 | wrapper + `PageNumberPos` variant; most tests |
| composer-2.5-fast | ~15 min | 199 passed / ok / ok | +303 −1 | wrapper only |
| gpt-5.3-codex-high-fast | ~14 min | 199 passed / ok / ok | +282 −0 | wrapper only; position map; `pt` metadata-only |
| gpt-5.6-sol-high-fast | ~12 min | 193 passed / ok / ok | +175 −6 | wrapper only, smallest diff; header inserts a hidden white run (odd) |
| claude-sonnet-5-thinking-high | > 60 min | still running at adoption time | +468 | — |
| gemini-3.7-flash-high | failed | connection lost to the Cursor agent endpoint | — | not usable from this CLI today |

Reading: every model that finished produced a passing, spec-shaped implementation; the differences were robustness (raw-action fallback) and diff economy. For spec-driven, test-gated engine work the cheap tier (composer, codex-high, sol-high) is sufficient; pick grok-xhigh/opus when the COM surface is uncertain. Live Hancom proof of the adopted op is pending the next assembly.

### W2 (results section) and W3 (methods + discussion), 2026-09-16, three models each

Deterministic checks: all six drafts kept every FIG/TABLE block and anchor (FIG width attributes differed only because Fable capped widths after launch; normalized at merge), 0 polite endings. Sizes: W2 opus 9.9k / sonnet 7.1k / sol 7.0k chars; W3 opus 5.9k+4.6k / sonnet 4.8k+3.1k / sol 6.1k+4.5k.

Judge (gpt-5.6-sol-high-fast, agent mode, reads results.json / gates.py to verify):
- W2: sol 22 > sonnet 19 > opus 13. The judge caught two rounding errors in the ORIGINAL 표 5 that every draft copied (36.25 → 36.2 not 36.3; −5.115 → −5.11 not −5.12) — a real find, fixed in body/claims/evidence. Opus contradicted itself on the 125 Hz vs 1000 Hz crossover and leaked gate names. **sol adopted**.
- W3: opus 20 > sol 19 > sonnet 17. All three over-stated the height argument (defaults are 1.2 m, so wording was softened rather than removed) and one claimed hash-based tamper detection more strongly than the pipeline does (softened). Opus's V is the best reflection; its "renovation order is robust" claim was hedged with the gap/flanking caveat. **opus adopted**.

Reading: a cheap judge (sol, ~8 min, ~260k cache tokens) reliably finds arithmetic/rounding slips and register leaks, including in the human-written baseline; its rankings agreed with Fable's spot checks. Writing quality ordering differed by task (grok-xhigh best on theory, sol on results, opus on reflection), so no single cheap model wins across kinds; sol-high-fast is the best value per token for prose so far.

### T8 — catalog maintenance (composer-2.5-fast, 2026-09-16)

Add two catalog entries + refresh ~35 implementation line references + bump two test constants. composer-2.5-fast: 6.7 min, 36k input / 7.4k output / 239k cache tokens, `tests/test_hancom_operation_catalog.py` 8 passed on first try, entries reviewed (ids, coverage state) and committed c862943. Reading: for mechanical, well-specified maintenance the cheapest tier is enough. Launch gotcha: a prompt containing ` - ` (space-hyphen-space) makes the cursor-agent.ps1 launcher fail with a PSArgumentException before any model runs; write prompts without bare hyphens.

### A1 — analysis note for Stage 3 COM wiring (2026-09-16)

Two cheap models asked for the same design note (read-only). Usage: gpt-5.6-sol-high-fast 6.1 min, 15.7k output, 1.85M cache; cursor-grok-4.6-low-fast 4.4 min, 9.4k output, 632k cache. Quality assessment: pending Fable review of the two notes.

### Stage 3 production tasks (grok-4.6-xhigh-fast, 2026-09-16)

| task | wall | in / out / cache tokens | outcome |
|---|---|---|---|
| S1 capability + plan contract | 17 min | 285k / 50k / 6.4M | 59 + 55 tests green first run; committed |
| S2+S3 adapter + apply + receipt | 18 min | 172k / 54k / 4.6M | 35 + 112 tests green first run; live smoke then exposed a child-env gap (`ProgramData`) that no unit test could see — fixed by Fable after bisecting |

Reading: grok-xhigh delivers spec-shaped runtime code with green suites in one pass; the residual risk is host integration, which only a live run reveals. A1's two cheap notes (sol, grok-low) were accurate enough to plan S1–S3 without Fable reading the runtime code itself.

### Allocation exhausted (2026-09-16 ~22:15)

The primary Cursor account (`pantagram1031`) returned `ActionRequiredError: You've hit your usage limit … resets 9/23/2026` while launching the Stage 4 research task R1 on gpt-5.6-sol-high-fast. Today's spend on this account: W1 ×8, judge ×3, W2 ×3, W3 ×3, C1 ×7, T1–T8, H1, S1, S2+S3, A1 ×2 (≈ 30 agent sessions). Probe right after: `cursor-grok-4.6-xhigh-fast`, `cursor-grok-4.6-low-fast`, `composer-2.5-fast`, `auto` still answer; `claude-opus-5`, `claude-sonnet-5`, `gpt-5.3-codex`, `gemini-3.7-flash` (and `gpt-5.6-sol`) return `usage limit`. So the cap is on the API-billed tier only; Cursor's own models keep running. Gemini's earlier "connection lost" failures were probably the same cap surfacing differently. The second account (`pantagram1301`) has the same allocation; switching requires the user to sign in (Fable never handles credentials). Routing until 9/23: production code → grok-4.6-xhigh; mechanical/maintenance → composer-2.5-fast; analysis/research → grok-4.6-low; judging → grok-4.6-xhigh (sol unavailable).

### Antigravity pool (added 2026-09-16 night at the user's request)

`agy --print … --model M --effort high --mode accept-edits --dangerously-skip-permissions --output-format json --print-timeout 45m`; JSON returns `status`, `duration_seconds`, `usage{input,output,thinking,cache_read}`. Models: gemini-3.8/3.7/3.6-flash (low/med/high), gemini-3.1-pro (low/high), claude-sonnet-4-6 (thinking), claude-opus-4-6-thinking, gpt-oss-120b-medium. Smoke PONG: 18.6 s, 17k input. First real task: S7 (xml backend routing) on claude-sonnet-4-6 — result below when done. Cursor default per user: `cursor-grok-4.6-high-fast` from now on.

## Verdicts so far (Stage 1 experience, all cursor-grok-4.6-xhigh-fast)

- T1–T7, H1: 9/9 bounded engine tasks accepted after my review; typical
  wall-clock 6–15 min; every acceptance suite passed on first run; one design
  miss (T4 whole-paragraph rule) that was a spec gap, not a model error.
  Grok 4.6 xhigh-fast is sufficient for spec-driven code with tests.
