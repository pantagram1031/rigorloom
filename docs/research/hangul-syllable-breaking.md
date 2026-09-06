# `breakNonLatinWord` and the 13 lines a syllable rule loses

[#313](https://github.com/pantagram1031/rigorloom/pull/313) found the cache
cutting **inside Hangul words in paragraphs that declare
`hh:breakSetting@breakNonLatinWord="KEEP_WORD"`** — `moel-2013` ¶261 between
`예금통장`/`에`, `saeopja` ¶189 between `제61조제3`/`항` — and measured what
happens when a syllable break is allowed everywhere: the break score goes
**48/113 → 89/113** on the installed-face half and **21/47 → 10/47** on the
rest. Forty-three paragraphs start being reproduced; **thirteen stop**.

This page answers whether a rule narrower than "syllable" holds those
thirteen while keeping the gains.

**It does not. Nothing shipped.** `own_render.py` is untouched on this
branch; the matrix and the thirteen diagnoses below are the deliverable.

> **Superseded as a statement about the tree.** The above is #316's own
> result and stands as written. What changed underneath it is the *cost*:
> [#320](https://github.com/pantagram1031/rigorloom/pull/320)'s measured
> stand-in advance table closed eleven of the thirteen, leaving one —
> `kstartup` ¶719 — and the syllable unit then SHIPPED on
> `claude/engine-e2-syllable-switch`. `breakNonLatinWord` is now read,
> reported and not obeyed; see `own_render.KOREAN_BREAK_UNIT`. The break
> score went 48/113 · 21/47 to **89/113 · 32/47**, 53 gains against that one
> declared regression. Everything below — §1's reading of the public
> document, §2's cut-class matrix, §3's thirteen — is the basis that shipped
> it, and §4's narrowing table is still the reason the rule is `syllable`
> and not one of the class-based narrowings.

## What was measured

| | |
|---|---|
| Corpus | the ten public forms under `tests/corpus/forms/converted` |
| Path A | the cached `hp:lineseg` read straight — the census and the cut-class matrix |
| Path B | the same originals re-laid out by our own flow pass, scored against the cache by `advance_probe.break_scoreboard` at 144 dpi |
| Path C | an edited candidate against licensed Hancom output — **NOT RUN**, here or anywhere in this repo |
| Instrument | `engine/scripts/syllable_break_probe.py --corpus --census --candidates --regressions` |

Every own render on this branch stays `own-uncertified`. The IoU figures
quoted from `render_scoreboard.py` are an image-overlap measure and are not a
compatibility percentage.

## 1. What the public documents say

Hancom's own public format document — 『한/글 문서 파일 구조 5.0』,
*Hwp Document File Formats 5.0*, **revision 1.3:20181108**, §4.2.10 문단 모양
(`Tag ID : HWPTAG_PARA_SHAPE`), in the 속성 1 bit table that follows 표 43 —
defines the two switches as **one bit and two bits**, verbatim:

```
bit 5～6   줄 나눔 기준 영어 단위     0  단어
                                     1  하이픈
                                     2  글자
bit 7      줄 나눔 기준 한글 단위     0  어절
                                     1  글자
```

The OWPML serialisation of those same two fields carries the names this
renderer reads. The independent Java implementation `neolord0/hwpxlib`, which
tracks the OWPML document, enumerates them with the Korean gloss attached:
`LineBreakForNonLatin` is exactly `KEEP_WORD` (`어절`) and `BREAK_WORD`
(`글자`); `LineBreakForLatin` is `KEEP_WORD` (`단어`), `HYPHENATION`
(`하이픈`) and `BREAK_WORD` (`글자`).

**There is no third state and no exception clause.** The Korean switch is one
bit. `어절` means the line breaks at word boundaries; `글자` means it breaks
between any two syllables. Nothing in the public document qualifies either
with a script, a character class or a punctuation rule.

### Is there any other declaration that could carry it?

No — not in the format, and not in this corpus. Every attribute the ten forms
actually declare on the elements that could plausibly hold such a switch:

| element | attributes present in the corpus |
|---|---|
| `hh:breakSetting` | `breakLatinWord`, `breakNonLatinWord`, `lineWrap`, `widowOrphan`, `keepWithNext`, `keepLines`, `pageBreakBefore` |
| `hp:paraPr` | `condense`, `snapToGrid`, `fontLineHeight`, `checked`, `suppressLineNumbers`, `tabPrIDRef`, `textDir` |
| `hh:autoSpacing` | `eAsianEng`, `eAsianNum` — both `0` on all 774 definitions |
| `hh:charPr` | `height`, `textColor`, `shadeColor`, `symMark`, `useFontSpace`, `useKerning`, `borderFillIDRef` |

`hh:charPr`'s per-script children (`ratio`, `spacing`, `relSz`, `offset`) are
**metric** slots — they say how wide a Hangul cell is, never whether it may be
broken after. There is no per-run language or script class that participates
in breaking at all. The nearest thing to a per-script switch,
`hh:autoSpacing@eAsianEng`/`@eAsianNum`, governs automatic spacing between
East-Asian and Latin/numeral text and is `0` everywhere here.

The one document-level record that *could* qualify a break rule,
`HWPTAG_FORBIDDEN_CHAR` (금칙처리 문자, `HWPTAG_BEGIN+78`, 가변 length), is
listed in the public document **without its contents**. That is why this
renderer's `LINE_START_PROHIBITED` / `LINE_END_PROHIBITED` tables are declared
in the sidecar as this renderer's own tables and not as the standard's — the
standard names the record and does not publish the set.

## 2. What the corpus declares, and where the cache actually cut

2995 paragraphs carry an `hp:lineseg`; 160 of them are multi-line and
scorable, giving **218 cached line ends**.

| declaration | values |
|---|---|
| `breakNonLatinWord` | KEEP_WORD 2226, BREAK_WORD 769 |
| `breakLatinWord` | KEEP_WORD 2750, BREAK_WORD 242, HYPHENATION 3 |
| `lineWrap` | BREAK 2995 (the only value present) |
| alignment | JUSTIFY 1268, CENTER 1202, LEFT 278, RIGHT 243, DISTRIBUTE 4 |
| `condense` | 0 → 2709, 25 → 282, 20 → 4 |
| `widowOrphan` | 0 → 2995 |

### The cut-class matrix

Every cached line end, classified by the pair of characters it fell between:

| `breakNonLatinWord` | space | inside-cjk-word | inside-latin-word | inside-digit-group | script-change | punctuation |
|---|---|---|---|---|---|---|
| **KEEP_WORD** | 108 | **70** | 0 | 0 | 2 | 24 |
| **BREAK_WORD** | 12 | 1 | 0 | 0 | 0 | 1 |

Three readings come straight off that table.

**(a) `KEEP_WORD` is not honoured as written.** Seventy of the 204 cached cuts
in `KEEP_WORD` paragraphs — **34 %** — fall between two Hangul syllables of one
어절. This is not a handful of edge cases; it is the ordinary behaviour.

**(b) It is not an emergency break either.** The obvious rescue for (a) is
that the engine honours `어절` and only breaks a word that cannot fit a line
of its own. Measured: **all 70** of those in-word cuts sit in words occupying
**0.033 to 0.393** of their own column — `또는` at 4 % of a 49 435 HWPUNIT
column, `지방자치단체가` at 14 %, the widest anywhere
(`「결과보고서원문파일」,「제출완료」로`) at 39 %. Not one of the 70 is a word
that could not have moved to the next line whole. **The emergency-break
reading is refuted.**

**(c) The cache never cuts inside a Latin word or a digit group.** Zero of 218,
under either declared value. It does cut at a **script change** inside one
어절 — `moel-2013` ¶215 `[ ]4조|3교대`, `saeopja` ¶189 `제61조제3|항`, both
Hangul-against-digit — but never between two Latin letters and never between
two digits. So a narrowing along the Latin/digit seam is consistent with the
cache; it simply is not what the thirteen need.

## 3. The thirteen, one by one

Every quantity below is the one `_line_fits` actually compares: `avail` is the
line box **minus the hanging indent** — every one of the thirteen paragraphs
declares a hanging `intent`, so quoting `@horzsize` would overstate the room by
2 300–3 300 HWPUNIT — and the excess counts the trailing 자간 gap. The
right-edge budget is `RIGHT_EDGE_TOLERANCE_HWP` = 96 HWPUNIT.

| form | ¶ | installed-only | align | `bNL` | cached cut | our cut | classes | avail | cached line excess | our line excess |
|---|---:|---|---|---|---:|---:|---|---:|---:|---:|
| kstartup | 719 | **yes** | JUSTIFY | KEEP_WORD | 93 `업 \|관` | 94 `관\|련` | space\|hangul → hangul\|hangul | 44 744 | −1 633.2 | **+58.8** |
| moel-2013 | 20 | no | JUSTIFY | KEEP_WORD | 41 `의 \|교` | 42 `교\|부` | space\|hangul → hangul\|hangul | 45 128 | −2 374.0 | −488.8 |
| moel-2013 | 55 | no | JUSTIFY | KEEP_WORD | 41 `의 \|교` | 42 `교\|부` | space\|hangul → hangul\|hangul | 45 128 | −2 728.4 | −911.4 |
| moel-2013 | 57 | no | JUSTIFY | KEEP_WORD | 46 `을 \|교` | 47 `교\|부` | space\|hangul → hangul\|hangul | 45 128 | −2 156.4 | −327.7 |
| moel-2013 | 118 | no | JUSTIFY | KEEP_WORD | 45 `의 \|교` | 46 `교\|부` | space\|hangul → hangul\|hangul | 45 128 | −2 001.8 | −135.4 |
| moel-2013 | 146 | no | JUSTIFY | KEEP_WORD | 45 `의 \|교` | 46 `교\|부` | space\|hangul → hangul\|hangul | 45 128 | −2 001.8 | −135.4 |
| moel-2025 | 25 | no | JUSTIFY | KEEP_WORD | 45 `게 \|이` | 46 `이\|행` | space\|hangul → hangul\|hangul | 48 190 | −2 360.5 | −475.2 |
| moel-2025 | 56 | no | JUSTIFY | KEEP_WORD | 45 `게 \|이` | 46 `이\|행` | space\|hangul → hangul\|hangul | 48 190 | −2 360.5 | −475.2 |
| moel-2025 | 91 | no | JUSTIFY | KEEP_WORD | 45 `게 \|이` | 46 `이\|행` | space\|hangul → hangul\|hangul | 48 190 | −2 360.5 | −475.2 |
| moel-2025 | 93 | no | JUSTIFY | KEEP_WORD | 52 `야 \|하` | 53 `하\|며` | space\|hangul → hangul\|hangul | 48 190 | −2 502.1 | −843.1 |
| moel-2025 | 152 | no | JUSTIFY | KEEP_WORD | 45 `게 \|이` | 46 `이\|행` | space\|hangul → hangul\|hangul | 48 190 | −2 360.5 | −475.2 |
| moel-2025 | 227 | no | JUSTIFY | KEEP_WORD | 45 `게 \|이` | 46 `이\|행` | space\|hangul → hangul\|hangul | 48 190 | −2 360.5 | −475.2 |
| nrf | 32 | no | JUSTIFY | KEEP_WORD | 52 `비 \|신` | 54 `청\|을` | space\|hangul → hangul\|hangul | 45 453 | −2 451.1 | **+83.7** |

Faces and 자간 per paragraph:

| ¶ | faces on the paragraph | 자간 values | hanging `intent` |
|---|---|---|---|
| kstartup 719 | installed only (맑은 고딕 / `malgun.ttf`) | −6, −3, 0 | −2 872 |
| moel-2013 20 / 55 / 57 / 118 / 146 | bundled + installed + system | 0 · −5…0 · −8,−3 · −5…0 · −5…0 | −2 440 … −2 604 |
| moel-2025 25 / 56 / 91 / 152 / 227 | bundled + installed | −3, 0, 3 | −2 490 |
| moel-2025 93 | bundled + installed + system | −19 … −3 | −2 339 |
| nrf 32 | bundled + system | −6, −4, 0 | −3 318 |

### They are one shape, not thirteen

Every one of the thirteen is the same event: **JUSTIFY, `KEEP_WORD`,
`condense=0` (no slack at all), a hanging indent, the cache cutting at a
space, and our breaker taking one more syllable** (two, in `nrf` ¶32). There
is no punctuation at either cut, no Latin, no digit, no full-width form. The
thirteen are only seven distinct sentences: the six `moel-2025` rows are two
sentences (five of them `성실하게 |이행하여야`), the five `moel-2013` rows are
three, and `kstartup` ¶719 and `nrf` ¶32 are one each.

The spec's four candidate explanations resolve like this:

* **a hanging-punctuation rule** — inapplicable. No cut in the thirteen has
  punctuation on either side.
* **a Latin-word rule** — inapplicable. No Latin at any of the 26 cuts.
* **a digit-group rule** — inapplicable. No digit at any of the 26 cuts.
* **a width error** — **eleven of thirteen.** Our line overshoots the cache's
  decision by **135.4 to 911.4 HWPUNIT**: less than one 12 pt Hangul cell
  (1 200 HWPUNIT) in every case, and under 2 % of a 45 000-unit line. All
  eleven carry at least one stand-in face (`bundled` and/or `system`), so
  their width is a substituted-face estimate and not a measurement of the
  declared face. This is the fallback slice's population.
* **something else** — **two of thirteen: the right-edge budget.**
  `kstartup` ¶719 (+58.8) and `nrf` ¶32 (+83.7) are already **over** their
  box by our own arithmetic and are admitted only by the 96 HWPUNIT error
  budget. `kstartup` ¶719 is the single regression on a paragraph whose every
  face is the declared, installed one, so it is the only one of the thirteen
  a width correction on this machine could not be blamed for.

So there are two groups, **11 width and 2 budget**, and neither group is
separable from the 43 gains by anything a break-opportunity rule can see.

## 4. Every narrowing, priced

`own_render.break_opportunities` allows a break wherever **either** side is a
CJK cell, so #313's `syllable` is broader than its name: it also opens
Hangul-against-Latin, Hangul-against-digit and Hangul-against-punctuation. The
narrowings cut it back along exactly the seams §1 and §2(c) name.

| candidate | installed | other | regressions | gains | `lineseg` break-seq exact | jumin ¶139 / ¶160 |
|---|---|---|---|---|---|---|
| **shipped** | 48 / 113 | 21 / 47 | — | — | 69 / 161 | wrong / exact |
| `syllable` | 89 / 113 | 10 / 47 | **13** | 43 | 99 / 161 | exact / exact |
| `cjk-cjk` (both sides CJK) | 87 / 113 | 9 / 47 | **13** | 40 | 96 / 161 | exact / exact |
| `cjk-cjk+alnum` (+ script change) | 89 / 113 | 9 / 47 | **13** | 42 | — | — |
| `cjk-cjk+digit` (+ digit only) | 89 / 113 | 9 / 47 | **13** | 42 | — | — |

**Every class-based narrowing costs the same thirteen and buys fewer gains.**
That is the expected result once §3 is read: the cut our breaker takes in all
thirteen is `hangul|hangul`, which is precisely the class the 43 gains need.
No partition of the characters separates them.

Because §3 says the residue is width, the fit budget was swept as well —
outside the break-opportunity rule, but it is the term two of the thirteen
turn on:

| candidate | installed | other | regressions | gains |
|---|---|---|---|---|
| `syllable`, budget 96 (shipped) | 89 / 113 | 10 / 47 | 13 | 43 |
| `syllable`, budget 0 | **90 / 113** | 10 / 47 | **12** | 43 |
| `syllable`, budget −150 | 77 / 113 | 13 / 47 | 11 | 32 |
| `syllable`, budget −500 | 40 / 113 | 23 / 47 | 21 | 15 |
| `syllable`, budget −960 | 22 / 113 | 28 / 47 | 31 | 12 |
| `syllable`, budget −1250 | 15 / 113 | 27 / 47 | 41 | 14 |

Dropping the budget to 0 recovers `kstartup` ¶719 — the one installed-face
regression — and costs nothing, but the other twelve need a *negative* budget
of at least 911 HWPUNIT, and at −500 the score has already collapsed below
`shipped`. **No setting reaches zero regressions.**

## What ships

**Nothing.** `engine/scripts/own_render.py` is byte-identical to
`claude/engine-e2-cell-rebreak`. The break-opportunity path is unchanged, the
fit budget is unchanged, and `break_scoreboard` stays at 48/113 and 21/47.

New on this branch: `engine/scripts/syllable_break_probe.py` (the instrument
that produces every table above) and `engine/tests/test_syllable_break_probe.py`
(the cut partition, the narrowing seam, and the two cached cuts the argument
turns on, pinned so a corpus reading can be falsified).

## Not proven

- **Path C was not run.** No candidate on this branch was rendered against
  licensed Hancom output. Every number here is either the cache read straight
  (path A) or our own flow pass scored against the cache (path B), and the
  two are never mixed into one figure.
- **The width diagnosis is a bound, not a measurement.** Saying eleven
  regressions are "a width error" means our arithmetic puts the extra
  syllable inside the box by 135–911 HWPUNIT while the cache did not take it.
  It does not say *which* term is wrong. Eleven of the eleven carry a
  stand-in face, which makes the substituted metric the obvious suspect, but
  no face on this machine measures the declared one and nothing here
  separates a face error from a residual the installed half shares.
- **`kstartup` ¶719 is one paragraph.** It is the only installed-face
  regression in the corpus and the only evidence that the budget, and not the
  stand-in faces, is a term here. One paragraph is not a measurement of the
  budget, and the budget was not moved on it.
- **`condense=0` on all thirteen is not a finding.** 2709 of 2995 corpus
  paragraphs declare `condense=0`; the thirteen having it says nothing that
  the corpus does not already say about every paragraph.
- **The 금칙 table is this renderer's.** The public document names
  `HWPTAG_FORBIDDEN_CHAR` and does not publish its contents, so the 24
  punctuation cuts in the matrix are classified against a conventional
  Korean prohibition list, not against the engine's own.
- **Ten forms.** The whole matrix is 218 cached line ends. Zero
  `inside-latin-word` and zero `inside-digit-group` cuts is an absence in a
  small sample and not a proof that the engine never makes one.
