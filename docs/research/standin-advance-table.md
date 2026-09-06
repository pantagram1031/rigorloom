# The eleven are one face, and the reference PDFs draw it

[#316](https://github.com/pantagram1031/rigorloom/pull/316) found thirteen
paragraphs the `syllable` break candidate loses and split them two ways:
**eleven a width error**, on lines whose runs resolve to a stand-in face, and
**two the right-edge budget**, already over their box by our own arithmetic.
It could not say which term of the width was wrong, only that all eleven carry
a substituted face.

This page names the face, measures it, and closes the eleven.

**One face does all of it: 휴먼명조.** It is declared `TTF`, this machine does
not have it, our resolver substitutes the bundled `NanumMyeongjo`, and the
substitute advances a Hangul syllable at **0.950 em** where the reference PDFs
draw the declared face at **0.996**. Under-measuring every syllable by 5 % is
the whole of the eleven.

**What ships:** a `standin_faces` section in
`engine/references/fonts/hft-widths.measured.json`, measured from drawn glyph
origins, and the advance-path lookup that reads it. **The breaker is not
switched**; `syllable` stays out of the tree, and its number is reported here
so the two changes can be reviewed apart.

## What was measured

| | |
|---|---|
| Corpus | the ten public forms under `tests/corpus/forms/converted` |
| Path A | the cached `hp:lineseg` read straight, and `lineseg_vs_pdf --corpus` as the control |
| Path B | the same originals re-laid out by our own flow pass, scored against the cache by `advance_probe.break_scoreboard` at 144 dpi |
| Path C | an edited candidate against licensed Hancom output — **NOT RUN**, here or anywhere in this repo |
| Instruments | `hft_width_table.py --build`, `syllable_break_probe.py --corpus --regressions`, `pdf_face_probe.py`, `lineseg_vs_pdf.py` |

Every own render on this branch stays `own-uncertified`. The IoU figures
quoted from `render_scoreboard.py` are an image-overlap measure and are not a
compatibility percentage.

## 1. The eleven, line by line

`avail` is the line box less the hanging indent, which is what `_line_fits`
actually compares; the excess counts the trailing 자간 gap. "our advance" and
"PDF advance" are summed over the characters of the span our breaker took —
`[line start, our cut)` — that the pairing matched glyph for glyph. The PDF
side is the pen distance between consecutive glyph origins inside one
text-showing run; a run's last glyph has no successor and is excluded from the
per-face figures in §2.

| form | ¶ | declared face per run (`hh:font` name / `@type`) → resolved | chars paired | our advance | PDF advance | our − PDF | excess before | excess after |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| moel-2013 | 20 | 휴먼명조 `TTF` → bundled ×30<br>HCI Poppy `HFT` → installed ×12 | 40/42 | 43339.2 | 45755.3 | **−2416.1** | −488.8 | **+1372.8** |
| moel-2013 | 55 | 휴먼명조 `TTF` → bundled ×30<br>HCI Poppy `HFT` → installed ×12 | 39/42 | 42273.1 | 45683.1 | **−3410.0** | −911.4 | **+931.7** |
| moel-2013 | 57 | 휴먼명조 `TTF` → bundled ×31<br>HCI Poppy `HFT` → installed ×12<br>HCI Poppy `HFT` → system ×4 | 44/47 | 42908.8 | 45222.4 | **−2313.6** | −327.7 | **+1475.2** |
| moel-2013 | 118 | 휴먼명조 `TTF` → bundled ×30<br>HCI Poppy `HFT` → installed ×12<br>한양신명조 `HFT` → installed ×4 | 43/46 | 43075.1 | 45361.0 | **−2285.9** | −135.4 | **+1635.5** |
| moel-2013 | 146 | 휴먼명조 `TTF` → bundled ×30<br>HCI Poppy `HFT` → installed ×12<br>한양신명조 `HFT` → installed ×4 | 43/46 | 43075.1 | 45361.0 | **−2285.9** | −135.4 | **+1635.5** |
| moel-2025 | 25 | 휴먼명조 `TTF` → bundled ×32<br>HCI Poppy `HFT` → installed ×14 | 43/46 | 45725.8 | 48118.0 | **−2392.2** | −475.2 | **+1537.2** |
| moel-2025 | 56 | 휴먼명조 `TTF` → bundled ×32<br>HCI Poppy `HFT` → installed ×14 | 43/46 | 45725.8 | 48118.0 | **−2392.2** | −475.2 | **+1537.2** |
| moel-2025 | 91 | 휴먼명조 `TTF` → bundled ×32<br>HCI Poppy `HFT` → installed ×14 | 43/46 | 45725.8 | 48118.0 | **−2392.2** | −475.2 | **+1537.2** |
| moel-2025 | 93 | 휴먼명조 `TTF` → bundled ×36<br>HCI Poppy `HFT` → installed ×13<br>HCI Poppy `HFT` → system ×4 | 49/53 | 44928.9 | 48280.6 | **−3351.7** | −843.1 | **+1075.7** |
| moel-2025 | 152 | 휴먼명조 `TTF` → bundled ×32<br>HCI Poppy `HFT` → installed ×14 | 43/46 | 45725.8 | 48118.0 | **−2392.2** | −475.2 | **+1537.2** |
| moel-2025 | 227 | 휴먼명조 `TTF` → bundled ×32<br>HCI Poppy `HFT` → installed ×14 | 43/46 | 45725.8 | 48118.0 | **−2392.2** | −475.2 | **+1537.2** |

Read the last three columns together. Our span was **narrower than the ink
Hancom actually laid down** by 2286 to 3410 HWPUNIT, which put it inside the
box by 135 to 911 — so our breaker took one syllable more than Hancom did.
Correcting the width puts the same span 932 to 1636 HWPUNIT **over** the box,
far outside the 96 HWPUNIT budget, and the break falls back where the cache
put it. All eleven.

#316's two budget rows, for completeness:

| form | ¶ | declared face per run → resolved | excess before | excess after |
|---|---:|---|---:|---:|
| kstartup | 719 | 맑은 고딕 `TTF` → installed ×45 | +58.8 | +58.8 |
| nrf | 32 | 휴먼명조 `TTF` → bundled ×37<br>HCI Poppy `HFT` → system ×16<br>한컴바탕 `TTF` → system ×1 | +83.7 | span no longer offered |

`kstartup` ¶719 does not move and cannot: every face on it is the declared,
installed one, so no stand-in correction can reach it. It remains the single
regression under `syllable`, exactly as #316 predicted. `nrf` ¶32 is carried
along by the correction — its line ends earlier now, so the over-budget span is
never offered to the fit test — which is why the count is 13 → 1 and not
13 → 2.

Neither of those two paragraphs pairs to the PDF at all (0 of 45 and 0 of 54
characters): both sit where `lineseg_vs_pdf.skip_reason` declines the pairing,
so their rows carry the fit arithmetic only and no measured advance.

## 2. Which faces, and what the PDFs carry

Per (declared face, `@type`, what the resolver did, what the PDF drew with),
over the eleven lines, run-final glyphs excluded:

| declared face | `@type` | resolved | PDF font | n | ours | Hancom | ours − Hancom | per char | ratio |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| 휴먼명조 | TTF | bundled | 휴먼명조 | 324 | 386918.6 | 408381.5 | −21462.9 | −66.24 | 0.94744 |
| HCI Poppy | HFT | installed | 휴먼명조 | 62 | 38974.0 | 41602.7 | −2628.7 | −42.40 | 0.93681 |
| HCI Poppy | HFT | system | T2 | 4 | 2291.8 | 2302.8 | −11.0 | −2.75 | 0.99523 |

Corpus-wide, 휴먼명조 is the **only** declared face our resolver answers from
the bundled family map — 3529 characters, every one of them drawn in the
reference by a font whose name reads back as 휴먼명조:

| declared face | n | resolver | PDF font | Hangul n | median em |
|---|---:|---|---|---:|---:|
| 휴먼명조 | 3529 | bundled 3529 | 휴먼명조 | 3528 | 0.99638 |
| 맑은 고딕 | 1431 | installed 1431 | MalgunGothic(Bold) | 607 | 0.96430 |
| 한양신명조 | 1196 | installed 1196 | 휴먼명조 1169, T2 27 | 0 | — |
| 바탕 | 1041 | installed 1041 | Batang | 630 | 1.00000 |
| 한양중고딕 | 652 | installed 652 | T6/T19/T3 | 590 | 0.97039 |
| HCI Poppy | 123 | system 123 | T2/T5/T8 | 0 | — |
| HY울릉도M | 36 | system 36 | HYwulM | 28 | 1.00231 |
| 고딕 | 24 | system 24 | T5 | 24 | 0.97443 |

### The answer to #316's question is a third thing

#316 asked whether these are faces the measured HFT table (#292) **could carry
but does not**, as #313 found for 한양신명조 digits, or faces **absent from
every reference PDF**. Neither.

**휴먼명조 is in four of the ten reference PDFs, and it is not an HFT face.**
Every HFT face reaches the export as an anonymous **Type 3** font — that is
the whole reason #292's table exists, because a Type 3 font has no font
program and no `hmtx` anywhere on any machine, so its `/Widths` array is the
only metric that exists. 휴먼명조 reaches the export as
`INPILL+ÈÞ¸Õ¸íÁ¶` — the CP949 bytes of 휴먼명조 — a **`Type0` /
`CIDFontType2`, `Identity-H`, subset-embedded TrueType**:

```
moel-pyojun-geunrogyeyakseo-2013.pdf
  xref  12  Type0   ext=ttf   base='INPILL+ÈÞ¸Õ¸íÁ¶'  name='F1'  Identity-H
  xref  13  Type3   ext=n/a   base='T2'
  ...
```

So the HFT table cannot carry it, twice over: `hft_width_table.measure()`
skips any font whose `subtype` is not `Type3`, and the renderer's
`_declared_hft_face` only answers for a run whose `hh:font@type` is `HFT`.
Adding 휴먼명조 to `faces` would be adding a TrueType face to a table whose
declaration says, correctly, that it is about faces that have no TrueType
metric.

It also cannot be read the same way. `/W` on an embedded CIDFont describes a
font program that is present in the file, and this repo does not open Hancom
font data. **So it was measured a different way: from the drawn glyph origins
alone** — the pen distance between two consecutive glyphs of one
text-showing run, divided by the run's declared cell. That is ink positions on
a public page, the same black-box reading `verify_against_anchors` already uses
as the HFT table's own check, and it never opens the font object.

### There is nothing per-code-point to find

Measured that way, 휴먼명조 has 145 code points over 2330 observations, and
they are all the same number:

```
휴먼명조 hangul   n=2330   median 0.99638   min 0.99638   max 1.00565   4 distinct values
```

A spread of 0.00927 em over 2330 observations, in four values, is the PDF
coordinate grid and not the face. **휴먼명조's Hangul cell is one em**, like
바탕's (1.00000), 맑은 고딕's and 한양중고딕's. The per-code-point table is
recorded anyway, with its observation count and source form per entry, because
that is the shape the file already has and a reader should be able to falsify
any single row — but the number that closes the eleven is one per face.

## 3. What that is worth

`syllable_break_probe.py --corpus`, at 144 dpi, path B:

| breaker | table | installed | other | regressions | gains |
|---|---|---|---|---:|---:|
| shipped | before | 48 / 113 | 21 / 47 | — | — |
| shipped | **after** | **48 / 113** | **21 / 47** | **0** | **0** |
| `syllable` | before | 89 / 113 | 10 / 47 | 13 | 43 |
| `syllable` | **after** | **89 / 113** | **32 / 47** | **1** | **53** |

Two readings.

**Under the shipped breaker the table changes no break decision at all.** That
is the honest statement of what this branch ships today: 0 regressions and 0
gains on the break scoreboard, which is what makes it safe to land ahead of
the breaker question.

**Under `syllable` it closes twelve of the thirteen.** The one left is
`kstartup` ¶719, the installed-face budget row. The non-installed half, which
`syllable` had driven *down* from 21/47 to 10/47, comes back to 32/47 — above
where the shipped breaker leaves it. **The breaker is not switched here.**

`jumin` ¶139 and ¶160, measured on this tree rather than carried over from
#316:

| | shipped | `syllable` |
|---|---|---|
| ¶139 before | wrong | exact |
| ¶139 after | wrong | exact |
| ¶160 before / after | not scorable | not scorable |

¶139 is unmoved by the table under either breaker — it is `syllable`'s gain
and not this slice's. ¶160 is not in `break_scoreboard`'s scorable set on this
tree, which is reported as measured rather than as #316 phrased it. `jumin`'s
only non-installed face is 한컴 윤체 B, which falls through to `system` and
did not qualify for the table, so the stand-in rule cannot reach this form.

### The one thing it costs

`own_render.lineseg_agreement` over the corpus moves on exactly two columns:

```
paragraphs_line_count_exact            2132 -> 2131
multiline paragraphs_line_count_exact   145 -> 144
paragraphs_break_sequence_exact        2056 -> 2056   (unmoved)
break_positions_matched                  92 ->   92   (unmoved)
```

One paragraph: **`nrf` ¶30**. Widening its 휴먼명조 syllables means its second
line no longer fits, so we lay it out in three lines where the cache uses two.
¶30 was **already** a break-sequence disagreement before this — cache
`[0, 50]`, ours `[0, 45]`, its first line breaking five characters early for a
reason this slice does not touch — so no paragraph that agreed on breaks
stopped agreeing. The width correction only propagated an existing error from
the break column into the line-count column.

`layout_divergence.py --corpus` moves with it: paragraph classes
**1801 / 94 / 131 / 28 → 1799 / 94 / 133 / 29**. `nrf` ¶31 and ¶32 go
agree → B (a 35.2 px own vertical drift, downstream of ¶30 taking a third
line), and `kstartup` ¶740 goes A → C — the same line, same `dy` 159.08, same
pages 21/20 before and after, reclassified because its text now matches and
only the page still differs. Full root list unchanged: the dominant first-drift
predecessor is `none/empty=0/PERCENT` on every form that has one, and the seat
carriers stay `page_top` (kstartup), `d_prev_advance_hwp` (moel-2025) and
`page_move` (nrf).

### The rasters

`render_scoreboard.py --corpus --dpi 144`, ssim / ssim_inked / text-line IoU,
means over the ten forms:

| policy | before | after |
|---|---|---|
| `cache` | 0.861944 / 0.393719 / 0.736589 | **0.868907 / 0.418264 / 0.743523** |
| `computed` | 0.848325 / 0.364894 / 0.692148 | **0.853950 / 0.383682 / 0.698067** |

53 pages and **10/10 exact page counts** on both policies, before and after.
No form moves down on any of the three channels; the six forms that declare no
휴먼명조 are unchanged to six decimal places.

Controls:

* `lineseg_vs_pdf.py --corpus` — **411/411** paragraphs, **8566/8566**
  characters, unchanged. It reads the cache against the PDF and touches none of
  our advances, which is exactly why it is the control.
* `right_edge_probe.py --corpus --breaks` — the shipped tolerance row is
  unchanged at 48/113 and 21/47. The zero-tolerance candidates
  (`strict`/`space`/`punct`/`condense`/`pen`) go 21/47 → 20/47, and `tol12` and
  `gap` each gain `moel-2025` ¶160; those are candidate rows, not the shipped
  path.
* `render_check.py` on `render-check-01` is byte-identical at both dpi — 96 dpi
  6 match / 37 close / 6 differs / 2 unsupported, 144 dpi 14 / 31 / 4 / 2.
  It has **no `--layout-policy` flag**, so it is one reading and not two.
  The document is set in 바탕, which is installed here, so the stand-in rule
  never fires on it.

## What ships

* `engine/references/fonts/hft-widths.measured.json` — a new `standin_faces`
  section and its own `standin_declaration`. The existing `declaration`,
  `hangul_em` and `faces` sections are **byte-identical**; the HFT table is
  untouched at 5 faces, 226 code points, 2301 observations.
* `engine/scripts/hft_width_table.py` — `measure_standin_faces` and
  `build_standin_section`, run by `--build`, plus the coverage lines.
* `engine/scripts/own_render.py` — `HftWidthTable` reads the section;
  `_standin_declared_face` and `_standin_advance_hwp` are the lookup, consulted
  by `_advance_hwp` after the HFT table. Only the advance path is touched.
* `engine/tests/test_standin_width_table.py` — the section's declaration and
  provenance, the reader, the resolver gate, and **`moel-2013` ¶118 pinned both
  ways**: under `syllable` its computed breaks equal the cache's with the table
  and do not without it.

Three faces qualified on this machine: 휴먼명조 (145 code points, 2330
observations, 4 forms), HY울릉도M (17, 36, 1 form) and HCI Poppy's `system`
fallback (9, 102, 3 forms). Only the first has any weight.

The gate is the **resolver**, not the declaration: `_standin_declared_face`
answers `None` for a run whose face was found installed. A machine that has
휴먼명조 meters those runs off the real face's own outlines and is not touched
by any of this, which is the behaviour you want — the table is a correction to
a substitution, and where there is no substitution there is nothing to
correct.

## Not proven

- **Path C was not run.** No candidate on this branch was rendered against
  licensed Hancom output. Every number here is either the cache read straight
  (path A) or our own flow pass scored against the cache (path B), and the two
  are never mixed into one figure. Every own render stays `own-uncertified`.
- **The table is machine-dependent by construction.** `standin_faces` records
  what *this* box substituted. On a machine with Hancom Office installed the
  section would be empty and the whole rule inert — and the eleven would
  presumably never have been wrong. The file says so in its own declaration,
  but it means the shipped JSON is a measurement of one machine's font
  situation and not a property of the corpus.
- **One em is a reading of four numbers.** 휴먼명조's Hangul advance is
  0.99638 with a 0.00927 spread across four distinct values, and it is recorded
  as measured rather than rounded to 1.0. Whether the true value is exactly the
  declared cell — as 바탕 and 맑은 고딕 read — or 0.9964, this corpus cannot
  separate: the difference is 4.7 HWPUNIT on a 13 pt cell, inside the PDF's own
  coordinate rounding.
- **`nrf` ¶30 is a real cost and it is one paragraph.** The line-count column
  went down. The argument that it is worth it rests on ¶30 already being a
  break-sequence disagreement, which is a fact about ¶30 and not a general
  guarantee that widening a stand-in never breaks a paragraph that agreed.
- **The eleven are seven distinct sentences.** #316 measured that; five of the
  six `moel-2025` rows are the same sentence. Eleven line-level closures are
  not eleven independent confirmations.
- **`kstartup` ¶719 is untouched and unexplained.** It is the only
  installed-face regression in the corpus, the budget is the only term left on
  it, and this slice did not move the budget.
- **The `syllable` numbers are not a proposal.** 89/113, 32/47 and one
  regression are reported so the breaker question can be decided on measured
  ground. Switching the breaker is a separate change and is deliberately not
  made here.
- **HCI Poppy's two seats disagree.** The same declared HFT face reads
  0.93681 against the export where it resolved `installed` and 0.99523 where it
  fell through to `system`, on the eleven lines. 62 characters against 4 is not
  enough to say what that is, and the HFT table already answers this face
  wherever it carries the code point.
