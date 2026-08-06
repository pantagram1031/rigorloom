# HWP usage landscape — where the format lives and what each family demands

Status: RESEARCH (Wave 5.1 of `docs/plans/v0.16-unified-core-and-modules.md`).
Feeds 5.2 eval scenarios and the W6 per-family benchmarks (§6.1–6.2).
Method: web survey (Korean-language queries), 2026-08. Prevalence claims are
**estimates from distribution signals** (who publishes forms, in what format),
not from any usage census — no such census exists publicly. Marked accordingly.

## The single biggest environmental fact: the 2026 HWPX mandate

From **2026-05-18**, central and local government 온나라 document systems accept
only **HWPX** attachments — 행정안전부 amended 「행정업무 운영 및 혁신에 관한
규정」 explicitly to make documents machine-readable for AI processing
(https://zdnet.co.kr/view/?no=20260512173412,
https://www.khan.co.kr/article/202605121345001). Consequences for the engine:

- The government-facing world is now **hwpx-first**; legacy `.hwp` remains the
  long tail (published statutory forms, school/corporate archives, older 붙임).
  Every family below is in a *transition state*: blank forms downloaded today
  are often still `.hwp`, but round-trips back into government systems must be
  `.hwpx`. **hwp→hwpx conversion fidelity is therefore a core capability**, not
  a nice-to-have.
- Citizens without Hancom Office are served by the free 공공 한글 editor
  (한컴+행안부, since 2019) for filling public forms
  (https://www.hancom.com/support/downloadCenter/pubHwp,
  https://www.mois.go.kr/frt/bbs/type010/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000008&nttId=72461).
  This confirms the fill-side population is huge and mostly non-expert.

---

## Family ①: 정부/지자체 민원·신고 서식 (civil petition / statutory forms)

- **Prevalence**: highest of all families (estimated). Nearly every statute's
  별지서식 is published as HWP/PDF via 국가법령정보센터
  (https://law.go.kr/LSW/lsBylSc.do) — 법제처 even runs an open API for
  별표/서식 (https://www.data.go.kr/data/3069189/openapi.do). Ministries
  re-distribute them (경찰민원24 https://minwon24.police.go.kr/cvlcpt/cvlcptTmpltGdList.do,
  과기부 전자민원 https://www.emsit.go.kr/cp/ai/LstReqFiles.do). MOIS materials
  reference roughly 8,000 filing/report form types (secondary source:
  https://m.boannews.com/html/detail.html?idx=82352 — treat count as estimated).
- **Format**: `.hwp` still dominant for published blanks; hwpx 병행 growing
  post-mandate.
- **Structure**: one page-filling outer table per form is the norm; dense
  bordered grids, merged cells, small fixed row heights, ㎜-precise layout
  (별지서식 dimensions are literally prescribed by regulation), checkbox
  glyphs (□/☑) as *text*, guide text inside cells (작성방법 notes), signature/
  seal cells (서명 또는 인), processing-flow footer rows (처리절차). Rarely
  multi-section; rarely equations; almost never images.
- **Fill pattern**: **citizen** fills a copy; agency staff fill the 접수/처리
  cells. Fill = text into fixed cells without moving anything.
- **Blank templates**: freely and officially available — the ideal corpus
  backbone. law.go.kr serves per-form HWP downloads.

## Family ②: 공문 / 기안문 (official inter-agency correspondence)

- **Prevalence**: very high in volume but generated **inside** systems
  (온나라, K-에듀파인), not usually hand-assembled from blank files — so it is
  a *produced-document* family more than a *fill-a-template* family.
- **Structure**: 두문/본문/결문 three-part layout fixed by
  「행정업무의 효율적 운영에 관한 규정 시행규칙」
  (https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=119635); header with agency
  name/logo, 결재란 (approval boxes, a table), 관인/직인 seal image placement,
  numbered-item body (1. 가. 1) …), footer with document number/date/contact.
  Headers/footers and a seal image are the distinctive demands; table density
  low except the 결재란.
- **Fill pattern**: staff (공무원·교사) draft; approval chain edits.
- **Blank templates**: format is regulation-defined; unofficial standard blanks
  circulate (e.g. https://gongform.com/공문서-양식-워드-엑셀-hwp-무료-다운로드/).
  For the corpus, prefer the regulation's own 별지 서식 from law.go.kr over
  third-party blanks.

## Family ③: 학교 행정 / 가정통신문 / 학부모 제출 서식

- **Prevalence**: high (estimated). Every school publishes 가정통신문 and
  parent-facing forms as `.hwp` on its site; 교외체험학습 신청서·결과보고서
  and 결석계 are near-universal examples (e.g.
  https://www.maji.es.kr/wah/main/bbs/board/view.htm?menuCode=50&domain.dataNo=15481,
  https://school.use.go.kr/_cmm/fileDownload/hamwol-h/M010302/5aa5f94cb8721999c8b21f4e8da4cce9).
  Internal school administration runs on NEIS/K-에듀파인 (family-② documents),
  with hwp attachments everywhere.
- **Structure**: two sub-shapes. (a) 가정통신문: letterhead header (school
  name/logo), free prose body, tear-off reply slip (절취선) — light tables,
  header/image handling. (b) Parent-submitted forms (체험학습 신청서, 결석계):
  family-①-like single-table forms, but *less* disciplined — school-made, so
  irregular merges, inconsistent cell padding, guide text in colored runs
  (exactly the T18 deletion-protection territory).
- **Fill pattern**: staff author (a); **parents/students** fill (b) — the
  least format-savvy fill population of all families.
- **Blank templates**: abundant on school/교육청 boards; public but scattered.
  Corpus note: school-published files sometimes embed teacher names in
  headers — pick clean blanks, run `privacy_scan`.

## Family ④: 교육·연구 보고서 양식 (current home turf — brief)

- **Prevalence**: moderate; universities, 한국연구재단, 국가연구개발혁신법
  report forms (https://www.nrf.re.kr/biz/notice/view?menu_no=44&nts_no=114828),
  school 탐구보고서/소논문 templates.
- **Structure**: multi-page flowing documents with front-matter tables (과제
  정보 grid), section headings, equations, figures, references — the *opposite*
  demand profile from ①: long flowing text + insertion-heavy, not fixed-grid.
  This is what rigorloom already handles (T16/T17 header-height and column
  drift lessons came from here).
- **Fill pattern**: student/researcher authors substantial prose.
- **Blank templates**: already in-house (`templates/` in the private
  workspace); NRF/university blanks public.

## Family ⑤: 기업 내부 문서 (품의서, 지출결의서, contract paperwork)

- **Prevalence**: medium and **declining toward groupware/전자결재** (estimated;
  distribution signal is mostly third-party form-sharing sites, not official
  sources — e.g. https://blog.storybadaboa-laria.kr/품의서-양식/,
  http://www.freeforms.co.kr/view/7c-form200-012336.html). Companies with
  전자결재 generate these in-system; hwp blanks persist in smaller orgs and
  associations.
- **Structure**: small approval-box table (결재란) top-right, a summary grid,
  amount cells (numeric formatting, 한글 금액 병기), stamp cells. Simpler than
  ① structurally.
- **Fill pattern**: staff.
- **Blank templates**: no authoritative source (that is itself the finding);
  corpus should carry at most one representative third-party blank, flagged as
  non-official.

## Family ⑥: 지원사업/공모 신청서 (government grant & program applications)

- **Prevalence**: high during any 공고 season (estimated). Every K-Startup /
  중기부 / ministry 공고 attaches 신청서+사업계획서 as hwp (e.g.
  http://k-startup.go.kr/common/attachFileView.do?attachSn=211973); 창업진흥원
  maintains a 표준사업계획서. Procurement variants (제안요청서, 입찰참가신청)
  flow through 나라장터 (https://www.pps.go.kr/kor/content.do?key=00302).
- **Structure**: the **hybrid** family — front pages are ①-style fixed grids
  (신청인 정보, 체크박스, 개인정보 동의 + 서명), body is ④-style flowing
  sections with prescribed headings and page budgets ("5쪽 이내"), often
  별첨 재무 tables. Multi-section in one file; page-count constraints matter.
- **Fill pattern**: applicant (citizen/company), high stakes — wrong-year
  template use causes rejection, so *template identity verification* has user
  value here.
- **Blank templates**: public per-공고; URLs rot when 공고 close. Corpus should
  snapshot the 표준사업계획서 rather than a live 공고 attachment.

## Family ⑦: 인사/노무 서식 (근로계약서 and HR forms)

- **Prevalence**: high in small business (estimated). 고용노동부 publishes the
  표준근로계약서 pack — 5+ variants incl. 연소자·단시간·건설일용 — as `.hwp`
  (https://www.moel.go.kr/info/etc/dataroom/view.do?bbs_seq=1358755286341,
  2025 revision https://www.moel.go.kr/policy/policydata/view.do?bbs_seq=20250300356).
- **Structure**: the *simplest* family — numbered clauses as prose, underline
  blanks (____) rather than table cells in the standard contract, two-party
  signature block. Some HR forms (연차신청 등) are small ①-style tables.
- **Fill pattern**: employer staff fills; employee co-signs.
- **Blank templates**: official, stable, small — good easy-tier corpus entries.

---

## Prioritized capability list (prevalence × structural demand)

1. **Fixed-grid table fill without layout drift** — the ①/③b/⑥-front shape:
   write into merged/bordered cells, preserve row heights and page breaks,
   never reflow the grid. Highest prevalence × highest breakage risk.
2. **hwp→hwpx round-trip fidelity** — post-mandate every government-bound
   artifact ends life as hwpx while most blanks are still hwp. Byte-level
   diffable conversion + verification belongs in core.
3. **Guide-text / placeholder detection and safe removal** — colored guide
   runs, 작성예시 rows, checkbox glyphs, 누름틀 fields (Hancom-native form
   fields exist — https://help.hancom.com/hoffice/multi/ko_kr/hwp/insert/madanginfo/madanginfo(press).htm —
   but survey signal says most real forms use plain cells + guide text, not
   누름틀; support reading both, prioritize the plain-cell reality). T18's
   protection rule generalizes here.
4. **Header/footer + seal/stamp handling** — ② and ⑤: 결재란 tables,
   관인/직인 image placement at fixed positions, agency letterheads. Needed
   for anything 공문-shaped; T16's header-height lesson is the known trap.
5. **Multi-section hybrid documents with page budgets** — ⑥ (and ④): fixed
   front grid + flowing body in one file, "N쪽 이내" enforcement, 별첨
   sections. Rigorloom's report machinery is the head start; the general
   version must not assume report semantics.
6. Lower tier: equation/figure insertion (④ only — already strong), tear-off
   reply slips and 절취선 (③a), numeric/금액 cell formatting (⑤).

## Candidate blank-form corpus (official blanks only, no filled documents)

| # | Family | Item | Source URL | Why representative |
|---|--------|------|-----------|--------------------|
| 1 | ① | Any 별지서식 via 법령 서식 search (pick 3–5 across ministries) | https://law.go.kr/LSW/lsBylSc.do | Canonical statutory single-table forms; regulation-prescribed layout |
| 2 | ① | 행정규칙 서식 variant | https://www.law.go.kr/admRulBylSc.do?menuId=9&subMenuId=57&tabMenuId=269 | Same family, different issuing layer — layout discipline varies |
| 3 | ② | 기안문/시행문 서식 (별지, 행정업무 운영·혁신 규정 시행규칙) | https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=119635 | The 공문 layout ground truth: 두문/결문, 결재란, 관인 위치 |
| 4 | ③ | 교외체험학습 신청서·결과보고서·결석계 (school-published set) | https://www.maji.es.kr/wah/main/bbs/board/view.htm?menuCode=50&domain.dataNo=15481 | Parent-filled, school-made irregular tables — the messy real world |
| 5 | ③ | 가정통신문 양식 (교육청/학교 배포) | https://school.use.go.kr/_cmm/fileDownload/hamwol-h/M010302/5aa5f94cb8721999c8b21f4e8da4cce9 | Letterhead + prose + reply-slip shape |
| 6 | ④ | NRF/국가연구개발 보고서 양식 | https://www.nrf.re.kr/biz/notice/view?menu_no=44&nts_no=114828 | Flowing report family, external anchor beyond in-house school templates |
| 7 | ⑥ | 창업사업화 표준사업계획서 (창업진흥원) | via https://k-startup.go.kr 공고 attachments (snapshot needed — 공고 URLs rot) | Hybrid grid+prose with page budget; highest-stakes fill |
| 8 | ⑥ | 조달청 서식자료 (입찰/계약 서식) | https://www.pps.go.kr/kor/content.do?key=00302 | Procurement variant of ⑥, stable official source |
| 9 | ⑦ | 표준근로계약서 5종 (고용노동부) | https://www.moel.go.kr/info/etc/dataroom/view.do?bbs_seq=1358755286341 | Simplest family; official, versioned (2025 개정), small files |
| 10 | ⑤ | 품의서/지출결의서 (third-party, flagged non-official) | https://blog.storybadaboa-laria.kr/품의서-양식/ | Only family without an official source — carry one, labeled |

Corpus hygiene: download blanks only; verify no author metadata / embedded
personal data (`privacy_scan` before the corpus lands anywhere); record
hwp-vs-hwpx of each file as found, since the mix itself is a measurement.

## What W6 must measure per family

- **①**: anchor/cell recall on dense merged grids; fill fidelity (target cell,
  no reflow); checkbox-glyph handling; idempotence under repeat fill.
- **②**: header/footer + 결재란 preservation; seal-image position stability
  after body edits.
- **③**: guide-text detection precision on undisciplined school tables
  (colored runs, 예시 rows) without T18-style structural collapse.
- **④**: existing report benches (already covered by v0.15 suite) — reuse,
  don't duplicate.
- **⑤/⑦**: baseline sanity — simple-table and prose-blank fill should be
  near-100%; any failure here is a red flag, not a boundary.
- **⑥**: multi-section navigation (fill front grid + write body section in one
  run); page-budget check accuracy.
- **Cross-family**: hwp→hwpx conversion diff cleanliness on every corpus file;
  non-destructive guarantee (untouched-region byte identity) per family.

## Honest uncertainty

- No public census of HWP form volume exists; every "prevalence" here is
  inferred from who distributes what. The 8,000-forms figure is a press
  paraphrase, not a verified count.
- Family ⑤ may be smaller than folk wisdom suggests — 전자결재 adoption data
  was not found; the third-party-only distribution signal is consistent with
  a shrinking family.
- 누름틀 (form-field) penetration in real government blanks is unverified from
  the survey alone; W6 should measure it directly on the corpus (count fields
  per file) rather than trust either assumption.
- School-form URLs (#4, #5) are board posts and may rot; snapshot early.
