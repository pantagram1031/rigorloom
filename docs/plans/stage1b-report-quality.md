# Stage 1b — bring the AURALAB report up to the WindPath/Hawkes bar

Status: ACTIVE 2026-09-16. Trigger: user judged the first result "a lot of mess"
compared with the WindPath, Hawkes and chem reports. Measured differences:

| | Hawkes | WindPath | AURALAB v1 |
|---|---|---|---|
| pages | 18 | 18 | 14 |
| body chars | 28.8k | 22.8k | 14.7k |
| figures / widths (mm) | 13 / 79–95 | 11 / 99–110 | 12 / 90–120 |
| tables | 5 | 11 | 5 |
| display equations | 12 | 14 | 8 |
| bold sub-heads | 10 | 6 | 16 |
| paragraphs / median chars | 121 / 195 | 77 / 182 | 62 / 173 |

What reads as "mess": too little prose per figure (figures at 100–120 mm stacked
on pages 7–12 with 20–30 % voids), sub-heads every few lines, thin theory (no
derivation, no worked numbers), thin results discussion (one paragraph per
subsection), few tables, and page count below the form's expectation.

## Targets (exit)

- [ ] Q1 body ≥ 24k chars, 16–18 pages, ≤ 10 bold sub-heads, median paragraph ≥ 190 chars.
- [ ] Q2 figures ≤ 95 mm (maps 85 mm side by side as ONE figure), 12–14 figures, every
      figure referenced and discussed in ≥ 3 sentences.
- [ ] Q3 tables 8–10: add per-component τ/Sτ table (500 Hz worked example), absorption
      share table, field statistics per band (mean/min/max/p05/p95), sweep table,
      gate summary table.
- [ ] Q4 theory section derives eq 3 from eq 2 with the 500 Hz worked numbers, explains
      why 20 dB = 100× energy, introduces image sources with a small sketch figure.
- [ ] Q5 results: one paragraph per band group + one on the dominance reversal + one on
      why ΔLp is uniform (reflection term algebra), with numbers.
- [ ] Q6 fill loop converges without `--spacing-skip-pages` beyond equation pages, bottom
      void ≤ 25 %, rubric true ×4, all gates green again (post-freeze rule applied).

## Who writes

Per the user's model-benchmark request, section expansions are written by
Cursor models against one spec (`docs/plans/model-eval.md`), Fable reviews,
merges the best, and runs `check_style` / `content_audit`.

## Ledger

| When | What | Result |
|---|---|---|
| 2026-09-16 | W1/W2/W3 section expansions written by Cursor models (see model-eval.md), judged, merged: II ← grok-4.6-xhigh, IV ← gpt-5.6-sol, III+V ← opus-5-medium. Tables renumbered by appearance (9), figure widths capped 85–95 mm, `page_numbers: true`, target_pages 16–20, layout plan rebudgeted (check_layout pass), content_audit pass (0 HARD). Body 26.3k chars, 98 paragraphs, median 191, 13 bold heads | Q1/Q3/Q4/Q5 met on paper; Q2 partly (maps not combined); Q6 pending assembly run 11 |
| 2026-09-16 | Judge found two rounding slips in the original 표 5 (36.3→36.2, −5.12→−5.11); fixed in body, claims.yaml, evidence.md | numbers now match results.json |
