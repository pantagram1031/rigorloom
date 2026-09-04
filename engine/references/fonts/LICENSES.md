# Bundled font licences

Fonts under `engine/references/fonts/family-map/` are the deterministic
fallback faces `own_render.BundledFontMap` maps Hancom/HWP body-text face
names to (see `_FAMILY_MAP_TABLE` in `engine/scripts/own_render.py`) when a
document's declared face is not installed on the rendering machine. All three
families are the Naver/NHN "Nanum" set, distributed by Google Fonts, licensed
under the **SIL Open Font License, Version 1.1**. The full licence text —
identical for all three families — is at
`engine/references/fonts/family-map/OFL.txt`, copied verbatim from upstream.

Verification: fetched `OFL.txt` from each family's own upstream directory
(not assumed from one family and applied to the others) and confirmed each
one's own copy states "This Font Software is licensed under the SIL Open
Font License, Version 1.1" over the same copyright block before bundling.

The SIL OFL permits embedding/bundling with software (including selling the
software) and redistribution, provided the font itself is not sold on its
own and the Reserved Font Names are respected — both satisfied here: the
fonts ship as unmodified files under their original names, alongside this
renderer, not sold separately.

## Nanum Myeongjo

- Upstream: https://github.com/google/fonts/tree/main/ofl/nanummyeongjo
- Copyright: (c) 2010, NHN Corporation (http://www.nhncorp.com), with
  Reserved Font Names Nanum, Naver Nanum, NanumGothic, Naver NanumGothic,
  NanumMyeongjo, Naver NanumMyeongjo, NanumBrush, Naver NanumBrush, NanumPen,
  Naver NanumPen.
- Licence: SIL Open Font License 1.1 (confirmed from this family's own
  upstream `OFL.txt`).
- Files bundled: `NanumMyeongjo-Regular.ttf`, `NanumMyeongjo-Bold.ttf`.
- Family name (OpenType `name` table): `NanumMyeongjo` / `나눔명조`.
- Maps: 바탕, 함초롬바탕, 휴먼명조, 신명조, 한양신명조, 궁서.
- sha256: `7ed9e8653a8ed04285d51dc343ffea6eb3d9c73afc27383ea8929ee4ffd03205`
  (Regular), `bc9ed8e60d93fe6db054b8fb988481b625f2eef8cb2317ad0e9834681b8fe3f3`
  (Bold).
- Size: Regular 2,986 KB, Bold 3,003 KB.

## Nanum Gothic

- Upstream: https://github.com/google/fonts/tree/main/ofl/nanumgothic
- Copyright: same NHN Corporation block as above.
- Licence: SIL Open Font License 1.1 (confirmed from this family's own
  upstream `OFL.txt`).
- Files bundled: `NanumGothic-Regular.ttf`, `NanumGothic-Bold.ttf`.
- Family name (OpenType `name` table): `NanumGothic` / `나눔고딕`.
- Maps: 돋움, 굴림, 함초롬돋움, 맑은 고딕, 한양중고딕, HY견고딕.
- sha256: `76f45ef4a6bcff344c837c95a7dcc26e017e38b5846d5ae0cdcb5b86be2e2d31`
  (Regular), `f96298f9fb18e364d2370f4c3ce948ac67a2b61af992d7234bc15c42b033c674`
  (Bold).
- Size: Regular 2,007 KB, Bold 2,025 KB.
- Note: this is a plain OFL sans, not Pretendard. `_FONT_SEARCH` already
  names a repo-vendored `engine/references/fonts/Pretendard-Regular.ttf` as
  its own (separate, whole-document) fallback tier, but no such file is
  present in this checkout — that slot, and whatever ships or does not ship
  it, is unrelated to `BundledFontMap` and out of scope for this slice.

## Nanum Gothic Coding

- Upstream: https://github.com/google/fonts/tree/main/ofl/nanumgothiccoding
- Copyright: same NHN Corporation block as above.
- Licence: SIL Open Font License 1.1 (confirmed from this family's own
  upstream `OFL.txt`).
- Files bundled: `NanumGothicCoding-Regular.ttf`,
  `NanumGothicCoding-Bold.ttf`.
- Family name (OpenType `name` table): `NanumGothicCoding` / `나눔고딕코딩`.
- Maps: 돋움체, 굴림체 (HWP's monospace 돋움/굴림 cuts).
- sha256: `787effd7efed2abca88ade231faa8191f4e9fcf85b1805a13ee1dc3724b72089`
  (Regular), `77a6de97c176b76ef9a683b565a1e6f4ce40b499c72a2972c4b5bdf7c6b8e7a0`
  (Bold).
- Size: Regular 2,262 KB, Bold 2,194 KB.

## Total

6 files, ~14.1 MB (`Regular` + `Bold` per family only — no italic/extra-bold
cuts bundled; a synthetic italic/bold is out of scope, and every mapped
family carries a real bold cut so `_synthetic_bold` never fires for a
bundled hit). Under the ~15 MB budget for this slice.

## Not bundled

**KoPub Batang** was considered for the serif slot per the original brief
("KoPub Batang if OFL-confirmed") and was NOT bundled: KoPub fonts are
distributed under the Korea Copyright Commission's own font licence, not
SIL OFL, so it fails the "if a family cannot be license-confirmed, do not
bundle it" rule here. Nanum Myeongjo (OFL-confirmed) covers the serif slot
instead.

**Pretendard** was named in the task brief as "already bundled" at
`desktop/src/assets/fonts`, but this checkout has no `desktop/` directory at
all — that claim does not hold for this repo state. Pretendard-as-fallback
was not substituted in here: Nanum Gothic (OFL-confirmed, already needed for
the plain-sans slot) covers it instead, and the `desktop/` discrepancy is
reported, not silently worked around.
