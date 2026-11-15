# WP10a — Rigorloom UI Redesign Specification

- **Target repository (read-only reference):** this repository at `main` `9940f90`
- **Deliverable scope:** Design specification and annotated wireframes (`Open`, `Review`, `Fill`, `History`, `Settings`) for WP10b implementation; zero runtime security changes and zero new backend RPCs.
- **Audience priority:** (1) Document approver, (2) Manual form filler, (3) Agent operator / debugger (`자세히` disclosure only).
- **Review outcome:** accepted with amendments. Field names in sections 2, 7, 8 and 9 were corrected against `desktop/src/types.ts` and the runtime (page metrics in HWPUNIT, `createdUtc` and `approval.resolvedUtc`, the nested receipt, `MAX_SOURCE_BYTES`, the `/api/agent-host/*` routes). Where this document and the amendments below disagree, the amendments win: one guard, in Python, with no TypeScript copy; no guard verdict on invalid plans; no guard pill on a fill into an empty blank; Review change rows at most 52px and every other row 32-36px; a required acknowledgement and full hashes in the approval dialog; a persistent "preview, may differ from print" label on the page; single-key shortcuts blocked in every editable target and during IME composition; 4.5:1 contrast for all informational text; separate approval and apply times in History; undo that inverts one revision's edits, not a whole-version restore. The vocabulary source is Astra's review, committed as `docs/ui/vocabulary.md`.

---

## 1. Principles and reference traits

### Five design principles

Show the form as the printed page the approver already recognises, never as an XML tree, table index, or unstyled HTML grid. Put every proposed edit in one document-ordered review list beside the page, pairing its before-and-after text with the paragraph fact-guard verdict beneath a single primary approve action. Speak plain office Korean or plain English—one language at a time, never two on the same label—and tuck internal coordinates, run identifiers, and error codes behind `자세히`. Build visual order from spacing, hairline dividers, two weights of Pretendard, and three semantic colours instead of nested cards, box borders, or ten-chip status strips. Keep every review and form-filling action reachable from the keyboard with clear focus rings and purposeful 150 to 200 millisecond motion that respects reduced-motion settings.

### Traits adopted from the six references

| Reference | Trait taken | Why Rigorloom needs it |
| :--- | :--- | :--- |
| **Linear** | Neutral grey surface hierarchy, `32px`–`36px` row density, `1px` dividers instead of box borders, and single-key list navigation (`j` / `k`, `Enter`). | Card borders and padded dashboard tiles halve visible rows and scatter visual attention. |
| **GitHub pull request ("Files changed" & review)** | One document-ordered change stream paired with a single primary review decision (`승인` / `Approve`) and one secondary return action (`돌려보내기` / `Return`). | Today's UI splits "what changes", "whether facts survived", and "approve" across three panes and two modes; unifying them turns approval into one linear pass. |
| **VS Code diff** | Side-by-side spatial anchoring with thin `3px` left-edge change bars, numbered inline markers, and word-level before/after callouts synced by scroll. | Approvers must verify both *where* on the form an edit lands and *exact character changes* inside legal dates, amounts, and clauses without losing page context. |
| **Raycast** | Instant `Cmd/Ctrl+K` command palette exposing every navigation, review, export, and operator action in one searchable list with shortcut hints. | Keeps the top bar quiet (one primary CTA, one secondary CTA, five screen tabs) while giving power users and operators one-keystroke reach to secondary tools. |
| **Figma right-hand inspector** | Contextual property sheet that displays controls *only* for the currently selected blank or change row, disappearing when nothing is selected. | Eliminates persistent empty form controls, permanent coordinate readouts, and disabled button clusters in `Fill` and `Review`. |
| **Apple Pages / Google Docs** | Physical paper sheet centered on a muted desk canvas at true page aspect ratio and print margins (`pageMetrics`), rendered in the bundled Korean face. | An approver trusts a Korean `.hwpx` form when its proportions, margins, cell borders, and Hangul typography match the printed sheet from 한글. |

---

## 2. The five screens

All screens share a single `48px` top bar with `1px` bottom divider (`--border-subtle`), strictly one active UI language (`한국어` shown in wireframes below; `English` switches every chrome label without exception), and zero persistent status bars exposing PIDs or XML paths.

Companion SVG wireframes sit next to this document:
- [open-1440.svg](wireframes/open-1440.svg)
- [review-1440.svg](wireframes/review-1440.svg)
- [review-390.svg](wireframes/review-390.svg)
- [fill-1440.svg](wireframes/fill-1440.svg)
- [history-1440.svg](wireframes/history-1440.svg)
- [settings-1440.svg](wireframes/settings-1440.svg)

---

### 2.1 Open (`열기` / `Open`)

Purpose: Open a `.hwpx` document (by drag-and-drop, native file picker, or bundled standard form) or resume a recent document session without seeing file hashes, byte counts, or XML section trees.

#### Annotated wireframe — `1440px` desktop

```text
+--------------------------------------------------------------------------------------------------+
| Rigorloom    [열기]   검토 4   채우기   기록                                  [명령 Ctrl+K]  설정 | 48px top bar
+--------------------------------------------------------------------------------------------------+
|                                                                                                  |
|                    문서 열기                                                                     | 720px centered
|                    원본 파일은 그대로 두고 안전한 작업 사본을 만들어 엽니다.                     | column (x=360..1080)
|                                                                                                  |
|                    + - - - - - - - - - - - - - - - - - - - - - - - - - - - - +                   |
|                    |          한글 문서(.hwpx)를 여기에 놓으세요             | <-- [A] Drop zone |
|                    |   또는 컴퓨터에 있는 양식이나 기본 양식에서 고릅니다    |     176px tall    |
|                    |                                                         |                   |
|                    |        [ 파일에서 고르기 ]   [ 기본 양식에서 열기 ]     | <-- [B] OS picker |
|                    + - - - - - - - - - - - - - - - - - - - - - - - - - - - - +     & corpus list |
|                                                                                                  |
|                    최근 연 문서                  항목을 누르면 이어서 엽니다                     |
|                    -----------------------------------------------------------                   |
|                    표준근로계약서_2026_신규입사.hwpx     방금 전   [변경 4건 대기] <-- [C] 36px  |
|                    -----------------------------------------------------------     plain rows    |
|                    정보공개청구서_총무팀.hwpx           오늘 11:20 [변경 2건 대기]               |
|                    -----------------------------------------------------------                   |
|                    물품구매표준계약서_조달청.hwpx       어제 17:45      [적용됨]                 |
|                    -----------------------------------------------------------                   |
|                    개인정보수집이용동의서.hwpx          2026-11-12     변경 없음                 |
|                    -----------------------------------------------------------                   |
|                                                                                                  |
|                    기본 제공 양식 (기본 양식에서 열기 선택 시 펼침)                              |
|                    -----------------------------------------------------------                   |
|                    고용노동부 표준근로계약서                                열기 <-- [D] Bundled |
|                    -----------------------------------------------------------     forms         |
|                    행정안전부 정보공개 청구서                               열기                 |
|                    -----------------------------------------------------------                   |
+--------------------------------------------------------------------------------------------------+
```

#### Behaviour & annotations (`Open`)
- **[A] Safe-copy reassurance & `.hwp` guidance:** Opening never mutates the user's source file; the subtitle states this plainly before the first click. If a user drops a binary `.hwp` file when `capabilities.convert` is available (Windows with 한글), Rigorloom converts and opens it automatically; when conversion is unavailable, an inline notice above the drop zone reads `"구형 .hwp 파일은 한글 프로그램에서 표준 문서(.hwpx)로 다시 저장한 뒤 열어 주세요"`.
- **[B] Direct OS file picker:** `파일에서 고르기` (`Choose file`) triggers `<input type="file" accept=".hwpx,.hwp">` -> `POST /api/open-upload` in web mode and native dialog -> `workspace/openPath` in Tauri mode. The old raw server-path modal (`BrowserOpenDialog`) is removed from the primary button and kept only as an operator command (`경로로 문서 열기`) in `Cmd/Ctrl+K`.
- **[C] Recent sessions (`36px` rows):** Each row displays three things only: document filename (disambiguated by parent folder name in muted text if two sessions share a filename), relative/local timestamp (`방금 전`, `오늘 11:20`, `2026-11-12`), and pending status (`변경 N건 대기`, `적용됨`, `변경 없음`). Deterministic landing rule: clicking a row with pending changes opens `Review`; clicking a row with zero pending changes and unfilled blanks opens `Fill`; clicking a completed form opens `Review` showing the applied page.
- **[D] Bundled forms:** `기본 양식에서 열기` toggles an inline `36px`-row list fed by `GET /api/corpus-files`, displaying clean document titles rather than repository fixture paths. If zero recent sessions exist on first launch, the empty table chrome collapses to one calm line (`아직 열어 본 문서가 없습니다`) and expands `기본 제공 양식` by default.
- **`390px` responsive layout:** Single full-width column (`16px` horizontal padding). Drop zone compacts to `144px` height with stacked full-width buttons (`파일에서 고르기`, `기본 양식에서 열기`). Recent rows become two-line `52px` rows (line 1: truncated filename; line 2: timestamp on left, pending badge on right).

---

### 2.2 Review (`검토` / `Review` — main screen)

Purpose: Let the approver inspect every proposed change marked in place on the form page (left `60%`), verify the before/after text and paragraph fact-guard verdict in document order (right `40%`), and commit a cryptographically bound approval with one primary button (`승인`).

#### Annotated wireframe — `1440px` desktop (`864px` left page / `576px` right PR review list)

```text
+--------------------------------------------------------------------------------------------------+
| 열기 | 표준근로계약서_2026.hwpx [검토 중]   [검토 4] 채우기 기록      [돌려보내기] [ 승인 ] 설정 | 48px top bar
+-----------------------------------------------------------+--------------------------------------+
| 1 / 1쪽   배율 100% · 폭 맞춤     양식 쪽 · 인쇄 화면 전환| 변경 4건 · 에이전트 제안 [바뀐 사실 1]| 36px sub-bar
+-----------------------------------------------------------+--------------------------------------+
|      +---------------------------------------------+      | [1] 빈칸 채움 · 성명 (근로자) [유지됨]|
|      |              표 준 근 로 계 약 서           |      |     (빈칸) -> 홍길동                 |
|      |                                             |      +--------------------------------------+
|      | (주)리걸룸과 홍길동은 다음과 같이 체결한다. |      |>|2| 빈칸 채움 · 근무 장소     [유지됨]| <-- Selected
|      | +------------+----------------------------+ |      | |   (빈칸) -> 서울 종로구 세종대로... |     row (j/k)
|      | |성명(근로자)||[1] 홍길동                 | |      | |   직접 고치기 · 이 항목 빼기 · 접기 |
|      | +------------+----------------------------+ |      | |   +------------------------------+ |
|      | |근무 장소   ||[2] 서울 종로구 세종대로...| |<---->| |   | op-2 fill_cell tbl 0 r1 c1   | | <-- 자세히
|      | +------------+----------------------------+ | sync | |   | para 6 pass:true +num:110,4  | |     (mono)
|      | |근로계약기간||[3] 2026년 4월 1일부터...  | |      | |   +------------------------------+ |
|      | |            || [이전: 2026년 3월 1일 ->] | |      +--------------------------------------+
|      | +------------+----------------------------+ |      |!|3| 칸 문구 바꿈 · 근로계약기간      | <-- 3px red
|      | |소정근로시간| 09시 00분부터 18시 00분까지| |      |!|                         [바뀐 사실]|     rail
|      | +------------+----------------------------+ |      |!|   ~2026년 3월 1일~ -> 2026년 4월 1일|
|      |                                             |      |!|   바뀐 날짜: 3월 1일 -> 4월 1일    |
|      | |[4] ~작성 요령: 파란색 안내 문구는...~   | |      |!|                             자세히 |
|      |                                             |      +--------------------------------------+
|      +---------------------------------------------+      | [4] 안내문 지움 · 작성 요령   [유지됨]|
|                                                           |     ~작성 요령: 파란색 안내 문구...~ |
|                                                           +--------------------------------------+
|                                                           |                                      |
|                                                           +--------------------------------------+
|                                                           | [추가로 시킬 일 입력...  Ctrl+Enter] | Quiet prompt
+-----------------------------------------------------------+--------------------------------------+
```

#### Approval dialog & return popover (anchored over `Review`)

```text
       +----------------------------------------------------------+
       | 변경 4건을 문서 사본에 적용할까요?                       |
       | 원본은 건드리지 않고 새 수정본을 만듭니다.               |
       |                                                          |
       | ! 확인: 3번 항목에서 날짜(2026년 3월 1일 -> 4월 1일)가   | <-- Shown whenever any row has
       |   바뀌었습니다. [x] 바뀐 사실을 확인했습니다             |     바뀐 사실 (changed fact)
       |                                                          |
       | 계획 해시  7404d02874ab...9f12                           | <-- Small mono bound hashes
       | 문서 해시  52232388ac76...3c08                           |     (planHash + boundSha256)
       |                                                          |
       |                                      [ 취소 ]  [ 승인 ]  |
       +----------------------------------------------------------+
```

#### Behaviour & annotations (`Review`)
- **Top bar states & single primary CTA:** Next to the filename sits one plain plan-state pill: `제안됨` (`Proposed` — plan loaded, not yet interacted with), `검토 중` (`In review` — reviewer inspecting rows or `approval.state === "pending"`), `승인됨` (`Approved` — approval resolved, apply running), or `적용됨` (`Applied` — candidate written and verified). While `제안됨` or `검토 중`, the right top bar shows secondary `돌려보내기` (`Return`) and primary `승인` (`Approve`). Once `적용됨`, the primary button transitions cleanly to `파일 내보내기` (`Export file`) so the user never wonders how to save their finished `.hwpx`.
- **Left `60%` (`864px`) printed-form canvas:** Renders the white paper sheet centered on neutral desk grey (`#F0F0EE` light / `#111110` dark) using physical proportions and print margins from `inspect.summary.pageMetrics` and bundled `Pretendard Variable`. Proposed edits are marked in place:
  - Filled blanks (`fill_cell`) get a `3px` cobalt left bar, soft tint (`--accent-soft`), numbered badge `[1]`, and the new text set at the cell's print position.
  - Replaced runs or cell replacements (`set_run`, `replace_at_cell`) show the new text in place; hovering, clicking, or focusing via `j`/`k` pins a compact inline callout directly beneath the phrase (`이전: 2026년 3월 1일`) so touch and keyboard users never rely on mouse hover alone.
  - Guide removals (`delete_guides`) show muted strikethrough text with a neutral badge (`안내문 지움`).
  - Any paragraph where the guard detected a changed protected fact (`바뀐 사실`) switches its marker bar and badge to semantic crimson (`--fact-changed`).
- **Right `40%` (`576px`) PR-style change list:** One row per change sorted strictly in top-to-bottom document reading order (`sectionIndex` -> `flowIndex` / `tableIndex` -> `row` -> `col`). Each row shows:
  1. Shared ordinal number (`1..N`) matching the marker on the page.
  2. Plain-language op kind (`빈칸 채움`, `칸 문구 바꿈`, `본문 문구 바꿈`, `안내문 지움`) plus the human field label derived from the adjacent `static` header cell (e.g., `근무 장소`) rather than `R1C1`.
  3. Compact before -> after diff (`(빈칸) -> 홍길동`, or word-diff `~2026년 3월 1일~ -> 2026년 4월 1일`).
  4. Paragraph guard verdict pill on the right: `유지됨` (`Kept`, forest green) when no existing protected token was altered or removed, or `바뀐 사실` (`Changed fact`, crimson) with the exact changed category and value named on a second line (`바뀐 날짜: 2026년 3월 1일 -> 2026년 4월 1일`, `바뀐 숫자: 3,000,000 -> 3,200,000`, `바뀐 부정 표현: 아니한다 -> 한다`).
  5. Row-level surgical actions when selected: `직접 고치기` (edits that single item inline), `이 항목 빼기` (drops that single op and re-proposes the rest), and `자세히` (expands monospace coordinates, `charPr`, and raw guard arrays).
- **Bidirectional scroll sync:** Clicking or `j`/`k`-focusing row `#k` scrolls the left page smoothly (`180ms`) to center marker `#k` and highlights its border; clicking marker `#k` on the left page selects and scrolls row `#k` into view in the right pane.
- **Return (`돌려보내기`) without fear of data loss:** Clicking `돌려보내기` opens a compact popover with an optional note (`돌려보내는 이유 (선택)`). For an agent-proposed plan, submitting calls `approval/resolve(decision: "rejected")` and passes the note to the quiet bottom agent input so the agent can revise; for a hand-filled draft, it returns the items to editable state in `Fill` without erasing what the user typed.
- **Approval dialog:** Keeps `planHash` (`계획 해시`) and `boundSha256` (`문서 해시`) visible in `12px` monospace so cryptographic binding (`approval/resolve` -> `plan/apply`) remains auditable. If any row has `바뀐 사실`, the dialog lists those exact rows and requires ticking `바뀐 사실을 확인했습니다` before `승인` activates.
- **`390px` responsive layout ([review-390.svg](wireframes/review-390.svg)):** Top bar holds `열기`, truncated filename, state pill, `돌려보내기`, and `승인`. Below it, a `36px` two-segment switch toggles between `문서 쪽` (width-fitted paper sheet) and `변경 목록 N` (full-width PR rows). While viewing `문서 쪽`, a `64px` sticky bottom stepper bar (`[이전]  2 / 4 · 빈칸 채움 (근무 장소) · 유지됨  [다음]`) lets the mobile approver step sequentially through every marked change on the page without horizontal scrolling.

---

### 2.3 Fill (`채우기` / `Fill`)

Purpose: Click a blank directly on the form page, type in place, press `Enter`, and watch the change appear in the right-hand list—with zero queue cards, zero `R0C14` cell codes, and plain-language feedback when clicking a non-fillable cell.

#### Annotated wireframe — `1440px` desktop

```text
+--------------------------------------------------------------------------------------------------+
| 열기 | 표준근로계약서_2026.hwpx [제안됨]    검토 2  [채우기]  기록       [ 검토하러 가기 ]  설정 | 48px top bar
+-----------------------------------------------------------+--------------------------------------+
| 1 / 1쪽 · 빈칸 9개 중 2개 채움      Tab 다음 빈칸으로 이동| 선택한 빈칸                          |
+-----------------------------------------------------------+ 근무 장소                            |
|      +---------------------------------------------+      | 본문 글자 크기에 맞춰 자동 입력됩니다| <-- Figma-style
|      |              표 준 근 로 계 약 서           |      | [서울특별시 종로구 세종대로 110    ] |     contextual
|      | +------------+----------------------------+ |      | 여러 줄로 입력하기            자세히 |     inspector
|      | |성명(근로자)||홍길동                     | |      +--------------------------------------+
|      | +------------+----------------------------+ |      | 채운 항목 2건   작성 안내문 지우기 + |
|      | |근무 장소   |[서울 종로구 세종대로 110| ]| |<---->+--------------------------------------+
|      | +------------+----------------------------+ |      | 성명 (근로자)   홍길동          빼기 | 44px flat rows
|      | |업무의 내용 | :여기를 눌러 입력하세요:   | |      +--------------------------------------+
|      | +------------+----------------------------+ |      | 근무 장소       서울 종로구...입력중 |
|      | |소정근로시간| 09시 00분부터 18시 00분까지| |      +--------------------------------------+
|      | +------------+----------------------------+ |      |                                      |
|      |  +----------------------------------------+ |      |                                      |
|      |  | ! 이 칸은 양식이 채우는 자리로 보지    | | <-- Plain-language notice when clicking     |
|      |  |   않습니다. 꼭 고쳐야 하면 [기존 문구  | |     a static header/label cell              |
|      |  |   바꾸기]를 쓰세요.                    | |                                             |
|      |  +----------------------------------------+ |                                             |
|      +---------------------------------------------+                                             |
+-----------------------------------------------------------+--------------------------------------+
```

#### Behaviour & annotations (`Fill`)
- **Direct in-page blank editing:** Cells classified as `fill_target` (`engine/scripts/form_inspect.py:1063`) show a subtle warm dashed boundary (`1px dashed --border-strong`) when empty. Clicking a blank mounts an IME-safe `<input>` (or `<textarea>` when cell height >= 2 lines or `여러 줄로 입력하기` is toggled) styled at the cell's exact position and font size.
- **Korean IME & blur safety:** Pressing `Enter` while `event.nativeEvent.isComposing` is `true` completes Hangul syllable assembly without submitting; pressing `Enter` when not composing commits the value into the session's change list and moves focus to the next unfilled blank (`Tab` / `Shift+Tab` also cycle blanks). Clicking outside or switching tabs (`onBlur`) auto-commits non-empty edits so work is never lost; only `Esc` discards the active edit.
- **Guide-text handling:** If a `fill_target` currently holds blue instructional text (`classification: "guide"` or guide-flagged text), clicking it opens an empty input with the guide text shown above as a quiet caption (`안내 문구는 자동으로 지워지고 입력한 값만 들어갑니다`). A single header action `작성 안내문 지우기 추가` adds `delete_guides` for standalone instructional paragraphs (`inspect.summary.removalTargets`).
- **Non-fillable cells in plain Korean:** Clicking a cell classified as `static` never emits `"cell (7,1) is classified 'static', not a fill target"` or `cell_not_fill_target`. Instead, a quiet inline callout anchored to that cell states: `"이 칸은 양식이 채우는 자리로 보지 않습니다"` (`The form does not treat this cell as a blank to fill`), accompanied by an explicit escape hatch link `기존 문구 바꾸기` (`Replace existing text`) that opens a `replace_at_cell` inline edit when the user genuinely needs to alter pre-printed form text. Decorative `spacer` cells ignore pointer hover so users do not click layout gutters by mistake.
- **Figma-style right inspector (`40%`):** Top section shows properties *only* for the focused blank (inferred field title, multi-line toggle, `자세히` disclosure). Below a `1px` divider sits the flat list of entered items (`채운 항목 N건`) with one-click `빼기` (`Remove`). Top-right primary CTA `검토하러 가기` (`Go to review`) proposes/validates the assembled plan (`plan/propose` -> `plan/validate`) and transitions to `Review`.
- **`390px` responsive layout:** Full-width form sheet; tapping any blank scrolls it above the virtual keyboard and docks a `56px` sticky input bar (`필드명` + `<input>` + `[입력]`) above the keyboard so small table cells remain effortless to type into on mobile.

---

### 2.4 History (`기록` / `History`)

Purpose: Show every applied candidate version as a vertical timeline (what changed, who approved, when), compare any two versions side by side, export any historical version, and restore an earlier state by proposing a reverse plan subject to the same approval gate.

#### Annotated wireframe — `1440px` desktop (`576px` left timeline / `864px` right comparison)

```text
+--------------------------------------------------------------------------------------------------+
| 열기 | 표준근로계약서_2026.hwpx [적용됨]     검토   채우기  [기록]        [ 파일 내보내기 ] 설정 | 48px top bar
+----------------------------------------+---------------------------------------------------------+
| 문서 수정 기록                         | 수정본 1 -> 수정본 2 비교 결과                          |
| 어느 두 시점이든 골라 비교·복원합니다  | 승인 시각: 오늘 14:32 · 승인한 사람: 직접 승인          |
|                                        |                      [이 변경 되돌리기 제안] [버전 저장]|
| [비교 기준: 수정본 1] -> [대상: 수정본2]| ------------------------------------------------------- |
|                                        | 되돌리기 제안을 누르면 이전 값을 복원하는 새 변경안이   |
|  (o) 수정본 2 · 칸 문구 바꿈 1건 [현재]| 만들어지며, 검토 화면에서 승인해야 적용됩니다.          |
|   |  직접 승인 · 오늘 14:32 · 점검 통과|                                                         |
|   |                                    | 달라진 항목 1건                                         |
|  ( ) 수정본 1 · 빈칸 채움 3건   [기준] | ------------------------------------------------------- |
|   |  직접 승인 · 오늘 14:10 · 점검 통과| 근무 장소                                      [유지됨] |
|   |                                    | 수정본 1: 서울특별시 종로구 세종대로 110                |
|  (*) 원본 문서                         | 수정본 2: 서울특별시 종로구 세종대로 110 본사 4층       |
|      처음 연 시각: 오늘 13:58          | ------------------------------------------------------- |
|      원본 파일은 수정되지 않음         |                                                         |
|                                        | 자세히 (영수증 검증 · 파일 해시 · 원본 기록 보기)       |
+----------------------------------------+---------------------------------------------------------+
```

#### Behaviour & annotations (`History`)
- **Vertical candidate timeline (`40%` left):** Anchors `원본 문서` (`Original document`) at the base and stacks each applied candidate chronologically upward (`수정본 1`, `수정본 2`). Every node states three human facts: *what changed* (summarised from receipt ops, e.g., `빈칸 채움 3건`), *who approved* (`직접 승인` for human `approved`, `자동 승인 규칙` for `auto_approved`), and *when*, as two labelled times (`승인 시각` from `receipt.approval.resolvedUtc`, `적용 시각` from `receipt.createdUtc` / the `candidate/list` row's `createdUtc`), plus the submission check outcome (`제출 전 점검 통과` or `남은 안내문 확인 필요`).
- **Compare any two:** Two clean selectors (`비교 기준` and `비교 대상`) allow comparing any pair (`원본 문서` vs `수정본 2`, or `수정본 1` vs `수정본 2`) via `candidate/compare` and `POST /api/guard/diff` (`{ sessionId, runId, againstRunId }`).
- **Restore = propose reverse with same approval:** Clicking `이 변경 되돌리기 제안` (`Propose undo of this change`) builds the inverse operation list (`reverses: { runId }`, `desktop/src/actions.ts:1125-1268`), submits `plan/propose`, and navigates straight to `Review` where the user sees the reversed values on the page and approves them through the standard `승인` dialog. If a candidate contains non-invertible operations (`delete_guides`), the button swaps cleanly to `이전 버전 파일 저장` (`Save earlier version`) with a plain explanation (`지운 안내문은 자동 복원안을 만들 수 없어 이전 버전 사본을 바로 저장합니다`).
- **`390px` responsive layout:** Vertical timeline fills the top viewport; tapping a timeline card opens the comparison and `이 변경 되돌리기 제안` / `이 버전 저장` actions in a full-width sheet below.

---

### 2.5 Settings (`설정` / `Settings`)

Purpose: Configure **only** Language, Theme, and Runtime root—nothing else.

#### Annotated wireframe — `1440px` desktop

```text
+--------------------------------------------------------------------------------------------------+
| Rigorloom    열기   검토 4   채우기   기록                                                 [설정]| 48px top bar
+--------------------------------------------------------------------------------------------------+
|                                                                                                  |
|                          설정                                                                    | 560px centered
|                          --------------------------------------------------------                | sheet (x=440..1000)
|                          언어                                  [한국어 | English]                |
|                          화면의 모든 안내와 단추를 고른 한 가지 언어로만 표시합니다.             |
|                          --------------------------------------------------------                |
|                          화면 테마                     [밝게 | 어둡게 | 시스템 설정]             |
|                          밝은 종이 화면이나 어두운 작업 화면을 고릅니다.                         |
|                          --------------------------------------------------------                |
|                          작업 폴더                                                               |
|                          열어 둔 문서의 작업 사본과 수정 기록이 보관되는 위치입니다.             |
|                          [/Users/minsu/Library/Application Support/Rigorloom] [바꾸기]           |
|                          --------------------------------------------------------                |
|                                                                                                  |
+--------------------------------------------------------------------------------------------------+
```

#### Behaviour & annotations (`Settings`)
- **Single-language guarantee:** Selecting `한국어` renders every label, tab, button, state badge, empty state, and error message in plain Korean; selecting `English` renders every one of them in plain English. Only the Language segmented control itself keeps native autonyms (`한국어` / `English`) so someone who switches by mistake can immediately switch back.
- **Theme token swap:** `밝게` (`Light`), `어둡게` (`Dark`), and `시스템 설정` (`System`) toggle `document.documentElement.dataset.theme` and persist via `POST /api/prefs` with zero layout shift.
- **Runtime root (`작업 폴더` / `Workspace folder`):** Displays the active root directory and a `폴더 바꾸기` (`Change folder`) control. Changing it warns gently if another folder is currently open (`현재 입력해 둔 초안은 지금 폴더에 안전하게 보관됩니다`) before calling `POST /api/prefs` and `POST /api/runtime/start`.
- **Strict scope ("Nothing else"):** AI provider endpoints, model names, API credential inputs, and sidecar diagnostics are removed from `Settings` and relocated into the operator-only `에이전트 연결 설정 (자세히)` modal reachable via `Cmd/Ctrl+K`.
- **`390px` responsive layout:** Full-width `16px`-padded vertical stack; segmented controls sit below each label at `100%` width (`36px` tall).

---

## 3. Component inventory

Every file currently inside `desktop/src` (50 files total: 32 `.tsx` views/components, 13 `.ts` modules, 1 `.css` stylesheet, and 4 bundled assets/fixtures) is mapped below with `keep`, `change`, or `remove`, followed by the new files to create for WP10b.

### 3.1 Existing UI entry, views, and components (`desktop/src/**/*.tsx`, `styles.css`)

| File path | Action | Specific changes or removal reason |
| :--- | :--- | :--- |
| `desktop/src/main.tsx` | **keep** | Mounts React root, `ErrorBoundary`, and smoke hook unchanged. |
| `desktop/src/App.tsx` | **change** | Replace the 2-mode (`문서` / `에이전트`) + 3-pane developer layout and bottom PID status bar with the 5-screen shell (`Open`, `Review`, `Fill`, `History`, `Settings`), unified `48px` top bar, global keyboard listener (`j`/`k`, `Enter`, `a`, `r`, `Cmd/Ctrl+K`), and single-language `i18n` context. |
| `desktop/src/styles.css` | **change** | Replace warm-teal/terracotta card borders, vertical stacked button styles, and 7-step font scale with the Section 5 token sheet (neutral greys, `#1A56DB` / `#4C8BF5` cobalt accent, 3 semantic guard colours, 4 type sizes, 2 weights, `1px` dividers, `150–200ms` reduced-motion-safe transitions). |
| `desktop/src/views/DocumentView.tsx` | **remove** | Replaced by dedicated `ReviewView.tsx`, `FillView.tsx`, and `HistoryView.tsx`; its old 3-column structure-tree + verification-chip-bar + card-queue split caused the developer-console clutter. |
| `desktop/src/views/AgentView.tsx` | **remove** | Standalone multi-pane chat/timeline mode is retired; agent prompt input lives as a quiet collapsible bar at the bottom of `Review` and operator transcript/tool logs move under `자세히` (`OperatorDrawer.tsx`). |
| `desktop/src/components/ApprovalDialog.tsx` | **change** | Remove bilingual labels and internal state jargon; add plain copy (`원본은 건드리지 않고 새 수정본을 만듭니다`), explicit `바뀐 사실` acknowledgement checkbox when guard warnings exist, and compact `12px` mono `planHash` + `boundSha256` rows. |
| `desktop/src/components/BrowserOpenDialog.tsx` | **change** | Remove from primary `Open` flow (replaced by direct OS file picker + drag-drop); retain only as an operator modal triggered from Command Palette (`경로로 문서 열기`) with single-language copy. |
| `desktop/src/components/Composer.tsx` | **change** | Simplify into the single-line expandable instruction bar docked at the bottom of `Review` (`추가로 시킬 일이 있으면 여기에 적으세요`), hiding host-blocker error codes in favour of plain sentences. |
| `desktop/src/components/ContextPanel.tsx` | **remove** | Exposed raw `sessionId`, `sourceSha256`, section counts, and XML inspection metadata on the main screen; absorbed into `DetailDisclosure.tsx` (`자세히`). |
| `desktop/src/components/Conversation.tsx` | **change** | Strip out of primary navigation; mount only inside the operator `자세히` drawer when inspecting full agent turn history. |
| `desktop/src/components/DocumentContext.tsx` | **remove** | Redundant header strip showing raw file paths and internal document badges in `AgentView`; superseded by the unified `48px` top bar. |
| `desktop/src/components/EditorToolbar.tsx` | **remove** | Contained the vertical letter-stacked mode buttons (`본문 보기`, `페이지 보기`) and raw `+ 작업 추가` op-kind buttons; replaced by quiet `32px` page sub-bar (`PageSheet.tsx`) and top-bar screen tabs. |
| `desktop/src/components/ErrorBoundary.tsx` | **change** | Localise crash fallback screen into single-language plain Korean / English and place stack trace inside a collapsed `자세히` disclosure. |
| `desktop/src/components/Findings.tsx` | **change** | Translate raw `check_residue` codes (`form_residue`, `pinned_target_missing`) via `i18n/vocabulary.ts` into plain sentences; move raw region coordinates under `자세히`. |
| `desktop/src/components/GuardDiffPanel.tsx` | **change** | Refactor into the per-paragraph guard verdict engine feeding each `ChangeRow.tsx` (`유지됨` vs `바뀐 사실: <항목>`) and `HistoryView.tsx` comparisons instead of a separate tab disconnected from the page. |
| `desktop/src/components/History.tsx` | **change** | Promote from cramped sidebar drawer into the full `HistoryView.tsx` vertical timeline with two-version selector, human approval attribution, export, and `이 변경 되돌리기 제안`. |
| `desktop/src/components/Logo.tsx` | **keep** | Clean geometric mark used in the `Open` and `Settings` top bar. |
| `desktop/src/components/PageOverlay.tsx` | **change** | Replace raw `(row, col)` tags with numbered change markers (`1..N`), `3px` semantic left bars, inline hover/selected before-after callouts, and bidirectional scroll-sync anchors. |
| `desktop/src/components/PagePreview.tsx` | **change** | Integrate as the optional raster print-check mode (`인쇄 화면 전환`) inside `PageSheet.tsx`, hiding tier strings (`own-uncertified`, `no_rasterizable_artifact`) behind `자세히`. |
| `desktop/src/components/ReceiptPanel.tsx` | **change** | Remove from main right sidebar; render strictly inside `HistoryView.tsx` under collapsed `자세히` for cryptographic receipt inspection. |
| `desktop/src/components/ReviewQueue.tsx` | **remove** | Card-per-op queue displaying `fill_cell`, `replace_at_cell`, `R0C14`, and nested card borders; replaced by `ChangeList.tsx` + `ChangeRow.tsx`. |
| `desktop/src/components/SeatEditor.tsx` | **change** | Keep the proven Korean IME `isComposing` guard (`keyCode === 229` / `compositionend`); add `onBlur` auto-commit, `Tab`/`Shift+Tab` blank cycling, multi-line `<textarea>` switch, and human field labels. |
| `desktop/src/components/SessionList.tsx` | **change** | Remove sidebar session switcher clutter; convert into the flat `36px`-row `RecentSessionsList` inside `OpenView.tsx` showing only filename, timestamp, and pending change count. |
| `desktop/src/components/Settings.tsx` | **change** | Strip all Agent Host provider/credential fields out of `Settings` (moving them to `OperatorAgentModal.tsx` under `Cmd/Ctrl+K`); render **only** Language (`한국어` / `English`), Theme (`밝게` / `어둡게` / `시스템 설정`), and Runtime root (`작업 폴더`). |
| `desktop/src/components/Splash.tsx` | **change** | Replace bilingual startup text with single-language Pretendard loading label (`문서 작업 공간을 준비하고 있습니다` / `Preparing workspace`). |
| `desktop/src/components/StructureTree.tsx` | **remove** | Left-rail tree exposing `"표 0 R0C14 charPr 11 -> 23"` and XML region indices; removed from user-facing UI (raw region addresses appear only inside a row's `자세히`). |
| `desktop/src/components/Tag.tsx` | **change** | Restrict to 4 semantic variants (`neutral`, `accent`, `kept`, `changed-fact`) at `12px` weight `600`, `4px` radius, zero border. |
| `desktop/src/components/TaskPacks.tsx` | **remove** | Canned prompt-card grid from `AgentView`; removed to avoid card-grid clutter (starter prompts become optional autocomplete suggestions in the quiet `Review` prompt input). |
| `desktop/src/components/TextView.tsx` | **change** | Rework from unstyled fluid HTML tables into the physical-proportion form renderer inside `PageSheet.tsx` driven by `inspect.summary.pageMetrics`, print borders, inferred blank seats, and inline markers. |
| `desktop/src/components/Timeline.tsx` | **change** | Move low-level RPC/agent event stream (`plan.proposed`, `tool.call`) out of main screens into `OperatorDrawer.tsx` (`자세히`). |
| `desktop/src/components/Toast.tsx` | **change** | Enforce single-language vocabulary lookup for every toast and route raw error codes into a collapsible `자세히` toggle inside error toasts. |
| `desktop/src/components/VerificationBar.tsx` | **remove** | The 10-chip cryptic status strip (`후보본 없음`, `렌더 증명 증명 없음`, `제출 검사 실행 안 함`); completely removed and replaced by the single top-bar plan state pill and per-row guard verdicts. |
| `desktop/src/components/Welcome.tsx` | **remove** | Replaced by `OpenView.tsx` (single-column drop zone, OS picker, recent sessions, and bundled forms). |

### 3.2 Existing state, transport, domain modules, and assets

| File path | Action | Specific changes or removal reason |
| :--- | :--- | :--- |
| `desktop/src/store.ts` | **change** | Replace `mode: "document" \| "agent"` with `screen: "open" \| "review" \| "fill" \| "history" \| "settings"`, add `language: "ko" \| "en"` (default `"ko"`), `selectedChangeId`, and `commandPaletteOpen`. |
| `desktop/src/actions.ts` | **change** | Keep all runtime orchestration (`propose`, `validate`, `approveAndApply`, `proposeReverseFromCandidate`, `exportDocument`, `refreshGuardDiff`); add single-op removal/edit re-propose helpers, per-op `{ beforeText, afterText }` guard fallback when a draft has validation warnings, and vocabulary-mapped error strings. |
| `desktop/src/runtime.ts` | **change** | Keep JSON-RPC/HTTP bridge untouched on web mode; add local pure-TS `guardDiff` token parity fallback when running in standalone Tauri without `rt_ui.py` HTTP `/api/guard/diff`. |
| `desktop/src/types.ts` | **change** | Add `ScreenId`, `UiLanguage`, `DocumentOrderedChange`, and `ParagraphGuardSummary` types; keep all protocol wire types intact. |
| `desktop/src/revision.ts` | **keep** | UTF-16 code-unit diff and single-run `set_run` derivation (`CaretRefusal` codes mapped to plain labels in `vocabulary.ts`). |
| `desktop/src/run_map.ts` | **keep** | DOM selection <-> run inventory offset mapping for inline paragraph editing. |
| `desktop/src/documentEvents.ts` | **keep** | Runtime SSE/poll invalidation listener (`plan.proposed`, `plan.applied`, `approval.requested`). |
| `desktop/src/runtimeSubscriptions.ts` | **keep** | Manages `event/subscribe` lifecycle across sessions. |
| `desktop/src/agent/planProjection.ts` | **change** | Enrich projected ops with adjacent `static` header cell labels (`fieldLabel`) and strict document reading-order sort keys. |
| `desktop/src/workspace/reviewSummary.ts` | **change** | Simplify output to drive the 4 plan states (`제안됨`, `검토 중`, `승인됨`, `적용됨`) and `바뀐 사실` count instead of the 10-chip `VerificationBar`. |
| `desktop/src/workspace/composerDraft.ts` | **keep** | Preserves unsent prompt text per session. |
| `desktop/src/smoke.ts` | **change** | Update selectors for the 5 screens (`Open`, `Review`, `Fill`, `History`, `Settings`). |
| `desktop/src/devMock.ts` | **keep** | Offline fixture harness using `corpus.json` for deterministic UI verification. |
| `desktop/src/assets/fonts/PretendardVariable.woff2` | **keep** | Sole bundled UI and form typeface (SIL OFL 1.1). |
| `desktop/src/assets/fonts/OFL.txt` | **keep** | Bundled font licence. |
| `desktop/src/assets/logo.svg` | **keep** | Application mark asset. |
| `desktop/src/fixtures/corpus.json` | **keep** | Recorded Runtime v0 fixture session. |

### 3.3 New views, components, and modules to add (`desktop/src/...`)

| New file path | Responsibility |
| :--- | :--- |
| `desktop/src/views/OpenView.tsx` | Implements Screen 1 (`Open`): `.hwpx` drop zone, OS file upload/open trigger, `36px` recent sessions list with pending change counts, and expandable bundled forms list. |
| `desktop/src/views/ReviewView.tsx` | Implements Screen 2 (`Review`): `60% / 40%` split layout, bidirectional scroll sync between `PageSheet` markers and `ChangeList` rows, return popover (`돌려보내기`), and quiet bottom prompt input. |
| `desktop/src/views/FillView.tsx` | Implements Screen 3 (`Fill`): `60%` interactive `PageSheet` with click-to-type blanks and plain-language static-cell popover (`이 칸은 양식이 채우는 자리로 보지 않습니다`), plus `40%` Figma-style selected-blank inspector and entered-items list. |
| `desktop/src/views/HistoryView.tsx` | Implements Screen 4 (`History`): `40%` vertical candidate timeline (`원본 문서`, `수정본 1..N`), arbitrary two-version comparison header, `이 변경 되돌리기 제안`, per-version export, and collapsed receipt `자세히`. |
| `desktop/src/views/SettingsView.tsx` | Implements Screen 5 (`Settings`): centered `560px` sheet with Language (`한국어` / `English`), Theme (`밝게` / `어둡게` / `시스템 설정`), and Runtime root (`작업 폴더`) only. |
| `desktop/src/components/TopBar.tsx` | Shared `48px` header: `열기` back-link or brand, active document title, plan-state pill, screen tabs (`검토`, `채우기`, `기록`), contextual primary/secondary CTAs (`승인` + `돌려보내기`, `검토하러 가기`, or `파일 내보내기`), and `설정`. |
| `desktop/src/components/PageSheet.tsx` | Paper-accurate page container sizing sheets from `inspect.summary.pageMetrics` (width, height, print margins), switching cleanly between HTML form projection (`TextView`) and raster print check (`PagePreview` + `PageOverlay`). |
| `desktop/src/components/ChangeList.tsx` | Right-hand `40%` PR-style list header (total changes, origin, `바뀐 사실` count) and keyboard-navigable (`j`/`k`) list container. |
| `desktop/src/components/ChangeRow.tsx` | Single document-ordered change row: ordinal badge, plain-language op kind, inferred field name, word-level before/after diff, paragraph guard verdict (`유지됨` / `바뀐 사실: ...`), inline edit/remove actions, and `자세히` disclosure. |
| `desktop/src/components/CommandPalette.tsx` | Raycast-style `Cmd/Ctrl+K` modal with fuzzy filter in active language, keyboard shortcut hints, and operator commands. |
| `desktop/src/components/DetailDisclosure.tsx` | Reusable `자세히` / `Details` accordion rendering strictly monospace internal metadata (Section 7). |
| `desktop/src/components/OperatorAgentModal.tsx` | Houses Agent Host provider/credential configuration (`/api/agent-host/*`, `/api/credentials/*`) and raw event diagnostics outside `Settings`, opened only via `Cmd/Ctrl+K`. |
| `desktop/src/i18n/vocabulary.ts` | Authoritative single-language lookup tables (`ko` and `en`) implementing Section 4 for every op kind, status string, guard category, and error code. |
| `desktop/src/workspace/fieldLabels.ts` | Pure helper scanning `inspect.graph.tables` to pair each `fill_target` `(row, col)` with its nearest left/top `static` label cell (falling back to `"빈칸 N"` / `"Blank N"`, never `R0C14`). |

---

## 4. Vocabulary table

Rule: **Strictly one language per label.** When `language === "ko"`, only the Korean column renders; when `language === "en"`, only the English column renders. Internal identifiers appear on screen **only** inside `자세히`.

### 4.1 Every operation kind known to the runtime (`27` op kinds across `preedit`, `xml`, and `com`)

| Internal op kind | Source `path:line` | Korean label (`한국어`) | English label (`English`) |
| :--- | :--- | :--- | :--- |
| `fill_cell` | `runtime/scripts/rt_plan.py:59`, `runtime/scripts/rt_apply.py:66`, `desktop/src/types.ts:289` | 빈칸 채움 | Fill blank |
| `replace_at_cell` (`mode: "replace"`) | `runtime/scripts/rt_plan.py:60`, `runtime/scripts/rt_plan.py:648`, `desktop/src/types.ts:297` | 칸 문구 바꿈 | Replace cell text |
| `replace_at_cell` (`mode: "append"`) | `runtime/scripts/rt_plan.py:60`, `runtime/scripts/rt_plan.py:648`, `desktop/src/types.ts:302` | 칸 문구 덧붙임 | Append to cell |
| `set_run` | `runtime/scripts/rt_plan.py:61`, `runtime/scripts/rt_apply.py:99`, `desktop/src/types.ts:307` | 본문 문구 바꿈 | Edit body phrase |
| `delete_guides` | `runtime/scripts/rt_plan.py:62`, `runtime/scripts/rt_apply.py:104`, `desktop/src/types.ts:313` | 안내문 지움 | Remove guide text |
| `normalize_clones` | `runtime/scripts/rt_plan.py:68`, `engine/scripts/preedit.py:2526` | 복제 글자 모양 정리 | Clean up cloned text styles |
| `goto_text` | `runtime/scripts/rt_plan.py:72`, `engine/scripts/xml_backend.py:28`, `engine/scripts/com_backend.py:1609` | 문구 위치로 이동 | Jump to text |
| `insert_text` | `runtime/scripts/rt_plan.py:72`, `engine/scripts/xml_backend.py:28`, `engine/scripts/com_backend.py:1612` | 문구 넣기 | Insert text |
| `insert_equation` | `runtime/scripts/rt_plan.py:72`, `engine/scripts/xml_backend.py:28`, `engine/scripts/com_backend.py:1613` | 수식 넣기 | Insert equation |
| `insert_table` | `runtime/scripts/rt_plan.py:73`, `engine/scripts/xml_backend.py:29`, `engine/scripts/com_backend.py:1615` | 표 넣기 | Insert table |
| `page_binding` | `runtime/scripts/rt_plan.py:73`, `engine/scripts/xml_backend.py:29`, `engine/scripts/com_backend.py:1626` | 쪽 제본 여백 맞춤 | Set binding margin |
| `replace_all` | `runtime/scripts/rt_plan.py:73`, `engine/scripts/xml_backend.py:29`, `engine/scripts/com_backend.py:1607` | 문구 일괄 바꿈 | Replace all occurrences |
| `insert_blank_before` | `runtime/scripts/rt_plan.py:74`, `engine/scripts/xml_backend.py:30`, `engine/scripts/com_backend.py:1624` | 앞에 빈 줄 넣기 | Insert blank line above |
| `insert_picture` | `runtime/scripts/rt_plan.py:74`, `engine/scripts/xml_backend.py:30`, `engine/scripts/com_backend.py:1616` | 그림 넣기 | Insert image |
| `set_line_spacing` | `runtime/scripts/rt_plan.py:74`, `engine/scripts/xml_backend.py:30`, `engine/scripts/com_backend.py:1627` | 줄 간격 조정 | Adjust line spacing |
| `put_field` | `runtime/scripts/rt_plan.py:78`, `engine/scripts/com_backend.py:1608` | 누름틀 값 채움 | Fill form field |
| `find_delete` | `runtime/scripts/rt_plan.py:78`, `engine/scripts/com_backend.py:1610` | 문구 찾아 지움 | Find and remove text |
| `move` | `runtime/scripts/rt_plan.py:78`, `engine/scripts/com_backend.py:1611` | 커서 위치 이동 | Move cursor position |
| `edit_equation` | `runtime/scripts/rt_plan.py:79`, `engine/scripts/com_backend.py:1614` | 수식 고침 | Edit equation |
| `set_cell` | `runtime/scripts/rt_plan.py:80`, `engine/scripts/com_backend.py:1617` | 표 칸 값 입력 | Set table cell value |
| `set_char_color` | `runtime/scripts/rt_plan.py:80`, `engine/scripts/com_backend.py:1618` | 글자 색 바꿈 | Change text colour |
| `delete_ctrls` | `runtime/scripts/rt_plan.py:80`, `engine/scripts/com_backend.py:1619` | 개체 표시 지움 | Remove control objects |
| `collapse_empty_paragraphs` | `runtime/scripts/rt_plan.py:81`, `engine/scripts/com_backend.py:1620` | 연속 빈 줄 합침 | Collapse blank lines |
| `delete_blank_after` | `runtime/scripts/rt_plan.py:81`, `engine/scripts/com_backend.py:1621` | 뒤 빈 줄 지움 | Remove blank line below |
| `delete_blank_before` | `runtime/scripts/rt_plan.py:81`, `engine/scripts/com_backend.py:1622` | 앞 빈 줄 지움 | Remove blank line above |
| `set_para_align` | `runtime/scripts/rt_plan.py:82`, `engine/scripts/com_backend.py:1623` | 문단 정렬 바꿈 | Change paragraph alignment |
| `insert_hyperlink` | `runtime/scripts/rt_plan.py:82`, `engine/scripts/com_backend.py:1625` | 웹 링크 넣기 | Insert web link |
| `page_break_before` | `runtime/scripts/rt_plan.py:83`, `engine/scripts/com_backend.py:1628` | 앞에서 쪽 나눔 | Insert page break above |

### 4.2 Plan, approval, guard, cell, check, and render statuses

| Internal status / token | Source `path:line` | Korean label (`한국어`) | English label (`English`) |
| :--- | :--- | :--- | :--- |
| `proposed` | `runtime/scripts/rt_plan.py:460` | 제안됨 | Proposed |
| `validated` (reviewing) | `runtime/scripts/rt_core.py:469`, `desktop/src/types.ts:317` | 검토 중 | In review |
| `invalid` | `runtime/scripts/rt_core.py:469`, `desktop/src/types.ts:317` | 확인 필요 | Needs fixes |
| `approved` | `runtime/scripts/rt_core.py:515`, `runtime/scripts/rt_codes.py:165` | 승인됨 | Approved |
| `auto_approved` | `runtime/scripts/rt_plan.py:747`, `runtime/scripts/rt_codes.py:165` | 자동 승인 규칙 | Auto-approved rule |
| `pending` | `runtime/scripts/rt_codes.py:165` | 승인 대기 | Awaiting approval |
| `rejected` | `runtime/scripts/rt_core.py:515`, `runtime/scripts/rt_codes.py:165` | 돌려보냄 | Returned |
| `applied` | `runtime/scripts/rt_core.py:544`, `desktop/src/types.ts:317` | 적용됨 | Applied |
| `guard.pass: true` / `kept` | `runtime/scripts/rt_ui.py:473`, `runtime/scripts/rt_guard.py:150` | 유지됨 | Kept |
| `guard.pass: false` / `protected_change` | `runtime/scripts/rt_ui.py:481`, `runtime/scripts/rt_guard.py:150` | 바뀐 사실 | Changed fact |
| `paragraph_count_changed` | `runtime/scripts/rt_guard.py:140`, `runtime/scripts/rt_ui.py:1737` | 문단 수 바뀜 | Paragraph count changed |
| `numbers` (guard category) | `runtime/scripts/rt_fidelity.py:15`, `runtime/scripts/rt_guard.py:161` | 바뀐 숫자 | Changed number |
| `dates` (guard category) | `runtime/scripts/rt_fidelity.py:18`, `runtime/scripts/rt_guard.py:161` | 바뀐 날짜 | Changed date |
| `direct_quotes` (guard category) | `runtime/scripts/rt_fidelity.py:34`, `runtime/scripts/rt_guard.py:163` | 바뀐 인용문 | Changed quotation |
| `qualifiers` (guard category) | `runtime/scripts/rt_fidelity.py:44`, `runtime/scripts/rt_guard.py:164` | 바뀐 부정·한정 표현 | Changed negation or qualifier |
| `quantifiers` (guard category) | `runtime/scripts/rt_fidelity.py:48`, `runtime/scripts/rt_guard.py:164` | 바뀐 수량 표현 | Changed quantifier |
| `causal_markers` (guard category) | `runtime/scripts/rt_fidelity.py:52`, `runtime/scripts/rt_guard.py:165` | 바뀐 인과 표현 | Changed causal phrasing |
| `direction_words` (guard category) | `runtime/scripts/rt_fidelity.py:56`, `runtime/scripts/rt_guard.py:165` | 바뀐 증감·방향 표현 | Changed direction word |
| `urls` / `markdown_links` | `runtime/scripts/rt_fidelity.py:37-40`, `runtime/scripts/rt_guard.py:163` | 바뀐 웹 주소 | Changed web address |
| `citations` / `source_ids` | `runtime/scripts/rt_fidelity.py:24-27`, `runtime/scripts/rt_guard.py:162` | 바뀐 출처 표기 | Changed citation |
| `inline_math` | `runtime/scripts/rt_fidelity.py:31`, `runtime/scripts/rt_guard.py:162` | 바뀐 수식 | Changed formula |
| `headings` / `tags` / `protected_spans` | `runtime/scripts/rt_fidelity.py:29,42,60` | 바뀐 제목·보호 구절 | Changed heading or protected span |
| `fill_target` (cell class) | `engine/scripts/form_inspect.py:1063`, `desktop/src/types.ts:132` | 입력 빈칸 | Blank to fill |
| `static` (cell class) | `engine/scripts/form_inspect.py:1128`, `desktop/src/types.ts:132` | 이 칸은 양식이 채우는 자리로 보지 않습니다 | The form does not treat this cell as a blank to fill |
| `guide` (cell class) | `engine/scripts/form_inspect.py:1126`, `desktop/src/types.ts:132` | 작성 안내 문구 | Form guide text |
| `spacer` (cell class) | `engine/scripts/form_inspect.py:1130`, `desktop/src/types.ts:132` | 여백 칸 | Layout spacer |
| `clean` / `pass` (check state) | `runtime/scripts/rt_codes.py:158`, `desktop/src/workspace/reviewSummary.ts:27` | 제출 전 점검 통과 | Pre-submission check passed |
| `warn` / `partial` (check state) | `runtime/scripts/rt_codes.py:158`, `desktop/src/workspace/reviewSummary.ts:27` | 한 번 더 확인 | Worth a look |
| `hard` / `fail` (check state) | `runtime/scripts/rt_codes.py:158`, `desktop/src/workspace/reviewSummary.ts:27` | 고쳐야 적용 가능 | Must fix before applying |
| `skipped` / `not_run` / `unavailable` | `runtime/scripts/rt_codes.py:158,163` | 아직 점검 전 | Not checked yet |
| `hancom` (render grade) | `runtime/scripts/rt_own.py:68` | 한글 인쇄 화면 | Hancom print view |
| `pdf` (render grade) | `runtime/scripts/rt_own.py:68` | PDF 인쇄 화면 | PDF print view |
| `own-uncertified` (render grade) | `runtime/scripts/rt_own.py:68` | 미리보기 화면 (인쇄본 대조 전) | Preview layout (not print-certified) |

### 4.3 Validation findings, runtime error codes, and UI refusal codes visible today

| Internal code | Source `path:line` | Korean label (`한국어`) | English label (`English`) |
| :--- | :--- | :--- | :--- |
| `cell_not_fill_target` | `runtime/scripts/rt_plan.py:591`, `engine/scripts/preedit.py:216` | 이 칸은 양식이 채우는 자리로 보지 않습니다 | The form does not treat this cell as a blank to fill |
| `cell_address_unknown` | `runtime/scripts/rt_plan.py:586` | 양식에서 해당 표 칸을 찾을 수 없습니다 | Could not find that table cell in the form |
| `fill_charpr_color_anomaly` / `color_anomaly` | `runtime/scripts/rt_plan.py:598`, `desktop/src/actions.ts:2852` | 빈칸 기본 글자 색이 본문과 달라 확인이 필요합니다 | Blank default text colour differs from body text |
| `fill_charpr_script_anomaly` / `script_anomaly_target` | `runtime/scripts/rt_plan.py:595`, `desktop/src/actions.ts:2878` | 위첨자·아래첨자 서식이 걸린 칸이어서 글자 크기를 확인해 주세요 | Blank uses superscript or subscript formatting |
| `run_color_anomaly` | `desktop/src/actions.ts:2865` | 바꾸려는 문구에 강조 색상이 포함되어 있습니다 | Phrase contains highlighted text colour |
| `at_cell_expect_mismatch` | `runtime/scripts/rt_plan.py:89`, `engine/scripts/preedit.py:252` | 칸의 현재 문구가 처음 읽었을 때와 달라졌습니다 | Cell text changed since this plan was created |
| `replace_key_ambiguous` / `at_cell_run_ambiguous` | `runtime/scripts/rt_plan.py:89,656` | 같은 문구가 한 칸 안에 여러 번 나와 위치를 특정할 수 없습니다 | That phrase appears more than once in the same cell |
| `ambiguous_fill_keys` | `runtime/scripts/rt_codes.py:153` | 같은 이름의 빈칸이 여러 개여서 구분이 필요합니다 | Multiple blanks share the same label |
| `run_inventory_unavailable` / `run_address_unknown` | `runtime/scripts/rt_plan.py:678,688` | 이 문단은 글자 서식 구조상 직접 고치기를 지원하지 않습니다 | This paragraph's formatting structure cannot be edited inline |
| `op_field_invalid` / `invalid_params` | `runtime/scripts/rt_plan.py:604`, `runtime/scripts/rt_codes.py:97` | 입력한 변경 항목 형식이 올바르지 않습니다 | Change entry is incomplete or invalid |
| `xml_wellformedness` / `artifact_malformed` | `runtime/scripts/rt_plan.py:91`, `pipeline/scripts/check_residue.py:724` | 문서 내부 구조가 손상되어 저장을 중단했습니다 | Stopped because the document file structure is damaged |
| `form_residue` | `pipeline/scripts/check_residue.py:610` | 지우지 않은 작성 안내 문구가 남아 있습니다 | Form guide text is still left in the document |
| `pinned_target_missing` / `expected_text_missing` | `pipeline/scripts/check_residue.py:646,687` | 들어가야 할 필수 문구가 문서에서 빠졌습니다 | Required text is missing from the document |
| `plan_stale` | `runtime/scripts/rt_codes.py:128`, `runtime/scripts/rt_plan.py:546` | 문서가 중간에 바뀌어 변경안을 새 기준으로 다시 맞춰야 합니다 | Document changed; refresh this plan against the latest version |
| `plan_invalid` | `runtime/scripts/rt_codes.py:132` | 먼저 확인해야 할 항목이 있어 아직 적용할 수 없습니다 | Resolve flagged items before applying this plan |
| `plan_not_approved` | `runtime/scripts/rt_codes.py:129` | 승인 절차를 거친 뒤에 적용할 수 있습니다 | Plan must be approved before it can be applied |
| `approval_binding_mismatch` | `runtime/scripts/rt_codes.py:133` | 승인 시점의 문서나 변경안이 달라져 다시 승인해야 합니다 | Document or plan changed since approval; please approve again |
| `approval_already_resolved` | `runtime/scripts/rt_codes.py:134` | 이미 처리된 승인 요청입니다 | This approval request was already completed |
| `apply_in_progress` | `runtime/scripts/rt_codes.py:130` | 지금 변경안을 문서에 적용하고 있습니다 | Changes are currently being applied |
| `apply_outcome_unknown` | `runtime/scripts/rt_codes.py:131` | 적용 완료 여부를 확인하는 중입니다. 기록 화면을 확인해 주세요 | Checking whether apply finished; please verify in History |
| `source_rejected` / `not_convertible` | `runtime/scripts/rt_codes.py:136,152` | 지원하지 않는 파일 형식입니다. 한글 문서(.hwpx)를 넣어 주세요 | Unsupported file type; please choose a .hwpx document |
| `needs_hancom` / `convert_failed` | `runtime/scripts/rt_codes.py:150,151` | 구형 .hwp 파일은 한글에서 .hwpx로 저장한 뒤 열어 주세요 | Save legacy .hwp files as .hwpx in Hancom Office before opening |
| `com_busy` | `runtime/scripts/rt_codes.py:149` | 한글 프로그램이 다른 작업 중입니다. 잠시 후 다시 시도해 주세요 | Hancom Office is busy; please try again shortly |
| `region_too_large` / `frame_too_large` / `response_too_large` | `runtime/scripts/rt_codes.py:91,99,135` | 문서나 선택 영역이 너무 커서 한 번에 불러올 수 없습니다 | Document or section is too large to load at once |
| `artifact_missing` / `source_not_found` / `candidate_not_found` | `runtime/scripts/rt_codes.py:138`, `runtime/scripts/rt_ui.py:1585-1595` | 작업 사본 파일을 찾을 수 없습니다. 문서를 다시 열어 주세요 | Working copy could not be found; please reopen the document |
| `candidate_hash_mismatch` / `receipt_body_mismatch` / `recovery_receipt_mismatch` | `runtime/scripts/rt_codes.py:139,140`, `desktop/src/actions.ts:1988` | 저장된 사본의 무결성 검증이 일치하지 않습니다 | Saved copy did not match its integrity record |
| `export_hash_mismatch` / `export_download_failed` | `desktop/src/actions.ts:2178,2193` | 파일 내보내기에 실패했습니다. 다시 시도해 주세요 | Could not export file; please try again |
| `not_invertible` / `previous_value_unreadable` | `desktop/src/actions.ts:1141,1190` | 이 변경은 자동 되돌리기 변경안을 만들 수 없습니다 | Cannot build an automatic undo plan for this change |
| `cross_run` / `multi_run` / `utf16_split` (`CaretRefusal`) | `desktop/src/revision.ts:26-33` | 글자 서식이 바뀌는 경계가 섞여 있으니 한 문구씩 고쳐 주세요 | Selection crosses formatting boundaries; edit one phrase at a time |
| `no_host` / `no_credential` / `no_credential_name` / `no_base_url` | `desktop/src/store.ts:1086-1095` | 에이전트 연결이 아직 설정되지 않았습니다 (명령창에서 설정) | Agent connection is not configured yet (open Command Palette) |
| `guard_unavailable` | `runtime/scripts/rt_ui.py:503` | 사실 유지 점검기를 지금 실행할 수 없습니다 | Fact guard check is currently unavailable |
| `unknown_session` / `session_not_found` | `runtime/scripts/rt_codes.py:123`, `runtime/scripts/rt_ui.py:1581` | 열려 있던 문서 세션이 닫혔습니다. 다시 열어 주세요 | Document session closed; please reopen the file |
| `unknown_plan` / `plan_not_found` / `unknown_approval` | `runtime/scripts/rt_codes.py:124,125`, `runtime/scripts/rt_ui.py:1670` | 찾으려는 변경안이 더 이상 유효하지 않습니다 | That change plan is no longer active |
| `unsupported_backend` / `unknown_op_kind` / `capability_unavailable` / `backend_refused` | `runtime/scripts/rt_codes.py:126,127,141,143` | 현재 환경에서 지원하지 않는 편집 작업입니다 | This edit action is not supported in the current environment |
| `render_failed` / `page_out_of_range` | `runtime/scripts/rt_codes.py:145,146` | 인쇄 미리보기 이미지를 만들지 못했습니다. 양식 쪽 화면을 사용합니다 | Could not build print preview image; showing form page layout |
| `path_escape` | `runtime/scripts/rt_codes.py:137` | 허용된 작업 폴더 밖의 경로에는 접근할 수 없습니다 | Cannot access files outside the allowed workspace folder |
| `publication_failed` / `internal_error` / `child_python_invalid` | `runtime/scripts/rt_codes.py:101,142,144` | 작업 처리 중 내부 오류가 발생했습니다 | An internal error occurred while processing the task |
| `protocol_version_unsupported` / `not_initialized` / `already_initialized` / `frame_malformed` / `duplicate_key` / `nonfinite_number` / `unknown_field` / `unknown_method` / `duplicate_request_id` / `unknown_subscription` / `subscription_limit` / `cancelled` | `runtime/scripts/rt_codes.py:88-100,147-148` | 작업 공간 연결을 다시 시작해 주세요 | Please reconnect the workspace runtime |
| `draft_superseded` | `desktop/src/actions.ts:3046` | 새 변경안이 도착해 이전 초안을 대체했습니다 | A newer plan replaced the previous draft |
| `agent_output_unreadable` / `agent_plan_before_unreadable` / `agent_plan_projection_unsupported` | `desktop/src/actions.ts:3020,3069`, `desktop/src/agent/planProjection.ts:47` | 에이전트 제안을 화면에 표시할 수 없어 다시 요청해야 합니다 | Could not display the agent proposal; please request it again |

---

## 5. Token sheet

Dark mode is a pure token swap (`[data-theme="dark"]` or `@media (prefers-color-scheme: dark)` when `theme === "auto"`), never a second stylesheet. `Pretendard Variable` (`desktop/src/assets/fonts/PretendardVariable.woff2`, SIL OFL 1.1) is the sole bundled font; monospace (`--font-mono`) is forbidden outside `.detail-disclosure` (`자세히`) and `.approval-hash` (the small bound hashes inside the approval dialog).

```css
@font-face {
  font-family: "Pretendard Variable";
  src: url("/assets/fonts/PretendardVariable.woff2") format("woff2-variations");
  font-weight: 400 600;
  font-style: normal;
  font-display: block;
}

:root {
  /* ── Typography: 1 bundled Korean face, 3 text sizes + 1 display size, 2 weights ── */
  --font-sans: "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Malgun Gothic", system-ui, sans-serif;
  --font-mono: ui-monospace, "SFMono-Regular", Menlo, Consolas, "Cascadia Mono", monospace;

  --text-sm: 12px;       /* badges, timestamps, keyboard hints, 자세히 mono, bound hashes */
  --text-base: 13px;     /* primary UI body, change rows, table labels, buttons */
  --text-lg: 15px;       /* top-bar document title, section headings, dialog titles */
  --text-display: 20px;  /* Open / Settings screen title, printed form main title */

  --weight-regular: 400;
  --weight-semibold: 600;

  --leading-ui: 1.45;
  --leading-doc: 1.7;    /* Hangul document line-height inside the paper sheet */

  /* ── 8 px spacing scale ── */
  --space-1: 8px;
  --space-2: 16px;
  --space-3: 24px;
  --space-4: 32px;
  --space-5: 40px;
  --space-6: 48px;
  --space-8: 64px;

  /* ── Work-tool density & structure ── */
  --topbar-h: 48px;
  --row-compact-h: 32px; /* controls, compact list items, sub-bar */
  --row-h: 36px;         /* standard recent-session and command-palette rows */
  --divider: 1px;

  /* ── Radii ── */
  --radius-sm: 4px;      /* status pills, inline markers, 자세히 box */
  --radius-md: 6px;      /* buttons, inputs, segmented controls */
  --radius-lg: 8px;      /* approval dialog, command palette, drop zone */

  /* ── Purposeful motion (150–200 ms, no bounce) ── */
  --ease-standard: cubic-bezier(0.2, 0, 0, 1);
  --duration-fast: 150ms;   /* row expand/collapse, dialog fade */
  --duration-scroll: 180ms; /* page-to-marker scroll sync & focus pulse */
  --duration-panel: 200ms;  /* mobile sheet & drawer transitions */
}

/* ── Light theme (default) ── */
:root,
:root[data-theme="light"] {
  /* Neutral greys */
  --bg-app: #F7F7F5;          /* Open / Settings calm backdrop */
  --bg-canvas: #F0F0EE;       /* Left 60% desk behind the white form sheet */
  --bg-surface: #FFFFFF;      /* Top bar, right 40% pane, dialogs */
  --bg-subtle: #F7F7F5;       /* Table static header cells, quiet prompt input */
  --bg-control: #F0F0EE;      /* Secondary buttons, segmented track */
  --bg-paper: #FFFFFF;        /* Printed form sheet */
  --bg-seat-empty: #FAF9F5;   /* Unfilled form blank subtle tint */
  --bg-hover: rgba(24, 24, 23, 0.04);
  --bg-selected: #F7F9FE;

  --fg-primary: #181817;
  --fg-secondary: #575653;
  --fg-muted: #8A8984;
  --fg-on-accent: #FFFFFF;

  --border-subtle: #E4E4E0;   /* 1 px hairline dividers */
  --border-strong: #C8C7C1;   /* Paper edge, dashed blank seat, dialog frame */
  --border-print: #181817;    /* Printed HWPX form table gridlines */

  /* One non-purple accent (Cobalt Blue) */
  --accent: #1A56DB;
  --accent-hover: #1545B5;
  --accent-soft: #EBF1FD;
  --accent-marker-bg: #F2F6FE;
  --focus-ring: #1A56DB;

  /* Semantic 1: Kept (유지됨) */
  --kept-fg: #166534;
  --kept-bg: #E8F5ED;
  --kept-rail: #16A34A;

  /* Semantic 2: Needs a look (한 번 더 확인 / non-fill cell notice) */
  --needs-look-fg: #B45309;
  --needs-look-bg: #FEF3C7;
  --needs-look-rail: #D97706;

  /* Semantic 3: Changed fact (바뀐 사실) */
  --changed-fact-fg: #B91C1C;
  --changed-fact-bg: #FDF2F2;
  --changed-fact-rail: #DC2626;
  --changed-fact-border: #F3C5C5;
}

/* ── Dark theme (pure token swap) ── */
:root[data-theme="dark"] {
  --bg-app: #141413;
  --bg-canvas: #111110;
  --bg-surface: #1C1C1A;
  --bg-subtle: #232320;
  --bg-control: #2A2A27;
  --bg-paper: #1E1E1C;
  --bg-seat-empty: #252521;
  --bg-hover: rgba(238, 238, 235, 0.05);
  --bg-selected: #1B2436;

  --fg-primary: #EEEEEB;
  --fg-secondary: #A3A29D;
  --fg-muted: #6E6D68;
  --fg-on-accent: #0D1526;

  --border-subtle: #2C2C29;
  --border-strong: #42423D;
  --border-print: #6E6D68;

  /* Cobalt Blue adjusted for dark-surface contrast */
  --accent: #4C8BF5;
  --accent-hover: #6BA1F8;
  --accent-soft: #1B2A47;
  --accent-marker-bg: #182338;
  --focus-ring: #4C8BF5;

  /* Semantic 1: Kept */
  --kept-fg: #4ADE80;
  --kept-bg: #132A1C;
  --kept-rail: #22C55E;

  /* Semantic 2: Needs a look */
  --needs-look-fg: #FBBF24;
  --needs-look-bg: #2D210B;
  --needs-look-rail: #F59E0B;

  /* Semantic 3: Changed fact */
  --changed-fact-fg: #F87171;
  --changed-fact-bg: #2E1517;
  --changed-fact-rail: #EF4444;
  --changed-fact-border: #5C2327;
}

/* ── Hard font scoping rule ── */
body {
  font-family: var(--font-sans);
  font-size: var(--text-base);
  font-weight: var(--weight-regular);
  line-height: var(--leading-ui);
  color: var(--fg-primary);
  background: var(--bg-app);
}

.detail-disclosure,
.approval-hash {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

/* ── Visible keyboard focus ── */
:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  :root {
    --duration-fast: 0ms;
    --duration-scroll: 0ms;
    --duration-panel: 0ms;
  }
  * {
    scroll-behavior: auto !important;
    transition-duration: 0ms !important;
    animation-duration: 0ms !important;
  }
}
```

---

## 6. Keyboard map and command palette

### 6.1 Korean IME & shortcut dispatch rules

1. **Active Hangul composition protection:** Inside `<input>` and `<textarea>` (`SeatEditor`, `Composer`, `CommandPalette`), any `keydown` where `event.nativeEvent.isComposing === true` or `event.keyCode === 229` is ignored by shortcut handlers so the final Hangul jamo syllable (`홍길동` + `Enter`) is never swallowed or prematurely submitted.
2. **IME-independent single-key navigation:** When focus is outside text inputs (for example, navigating `Review` rows), single-letter shortcuts match `event.code` (`KeyJ`, `KeyK`, `KeyA`, `KeyR`, `KeyD`, `KeyE`) without modifiers. Thus pressing the physical `J`, `K`, `A`, or `R` key works identically even when the user's OS input mode is set to Korean 2-beolsik (`ㅓ`, `ㅏ`, `ㅁ`, `ㄱ`).

### 6.2 Global and screen keyboard map

| Shortcut | Scope | Action |
| :--- | :--- | :--- |
| `Cmd/Ctrl + K` | Everywhere | Open or close the Command Palette (`명령창`). |
| `Cmd/Ctrl + O` | Everywhere | Switch to `Open` (`열기`) and trigger file picker. |
| `Cmd/Ctrl + 1` | Document open | Switch to `Review` (`검토`). |
| `Cmd/Ctrl + 2` | Document open | Switch to `Fill` (`채우기`). |
| `Cmd/Ctrl + 3` | Document open | Switch to `History` (`기록`). |
| `Cmd/Ctrl + ,` | Everywhere | Switch to `Settings` (`설정`). |
| `j` / `ArrowDown` | `Review`, `Open`, `History` | Select next change row (scrolls page marker into view), next recent document, or older candidate. |
| `k` / `ArrowUp` | `Review`, `Open`, `History` | Select previous change row (scrolls page marker into view), previous recent document, or newer candidate. |
| `Enter` | `Review` / `Open` | In `Review`: expand/collapse selected change row & pin inline before/after callout. In `Open`: open selected session. |
| `Enter` | `Fill` (blank focused, not composing) | Commit current blank value to the session list and focus the next blank (`Ctrl/Cmd + Enter` when in multi-line mode). |
| `Shift + Enter` | `Fill` (single-line blank) | Switch the active blank to multi-line `<textarea>` mode and insert a line break. |
| `Tab` / `Shift + Tab` | `Fill` | Commit current blank (if modified) and move to next / previous fillable blank on the page in reading order. |
| `a` | `Review` (plan active) | Open the `승인` (`Approve`) confirmation dialog (`Enter` inside dialog confirms when enabled). |
| `r` | `Review` (plan active) | Open the `돌려보내기` (`Return`) note popover. |
| `e` | `Review` (row selected) | Edit the selected change inline on the page (`직접 고치기`). |
| `Backspace` / `Delete` | `Review` or `Fill` (list row focused) | Remove the selected item from the draft plan (`이 항목 빼기`, undoable via `Cmd/Ctrl + Z`). |
| `d` | `Review` or `History` | Toggle `자세히` (`Details`) on the currently selected row or candidate. |
| `[` / `]` | `Review` or `Fill` (multi-page doc) | Previous page / next page on the form canvas. |
| `Cmd/Ctrl + Z` | `Fill` or `Review` (draft) | Undo last manual change (`undoDraft` in `actions.ts`). |
| `Cmd/Ctrl + Shift + Z` | `Fill` or `Review` (draft) | Redo last undone manual change (`redoDraft` in `actions.ts`). |
| `Esc` | Anywhere | Close open dialog/palette, cancel active inline blank edit (restoring prior value), or clear selection. |

### 6.3 Command palette (`Cmd/Ctrl + K`) command list

Commands render strictly in the active single language (`한국어` or `English`), filtered by fuzzy substring on title and keywords, hiding commands that do not apply when no document is open.

| Korean command (`한국어`) | English command (`English`) | Shortcut | Availability | Underlying action |
| :--- | :--- | :--- | :--- | :--- |
| 변경안 승인하기 | Approve changes | `A` | Active plan in `Review` | Opens `ApprovalDialog` -> `approveAndApply` |
| 변경안 돌려보내기 | Return changes with note | `R` | Active plan in `Review` | Opens return popover -> `rejectActivePlan` / return to `Fill` |
| 파일 내보내기 (.hwpx) | Export document (.hwpx) | `Cmd/Ctrl+E` | Document open | `exportDocument` (`POST /api/export` + download) |
| 문서 열기 (파일 선택) | Open document (choose file) | `Cmd/Ctrl+O` | Always | Switches to `Open` & triggers OS file picker |
| 기본 제공 양식에서 열기 | Open bundled standard form | — | Always | Switches to `Open` & expands `기본 제공 양식` |
| 검토 화면으로 이동 | Go to Review | `Cmd/Ctrl+1` | Document open | `setScreen("review")` |
| 채우기 화면으로 이동 | Go to Fill | `Cmd/Ctrl+2` | Document open | `setScreen("fill")` |
| 수정 기록 화면으로 이동 | Go to History | `Cmd/Ctrl+3` | Document open | `setScreen("history")` |
| 바뀐 사실이 있는 항목으로 이동 | Jump to next changed fact | — | Plan has `바뀐 사실` row | Selects next row where `guard.pass === false` |
| 다음 빈칸으로 이동 | Jump to next empty blank | — | Document has unfilled `fill_target` | Switches to `Fill` & focuses first empty blank |
| 작성 안내 문구 모두 지우기 추가 | Add step to remove form guide text | — | `removalTargets.count > 0` | Appends `delete_guides` op to current draft |
| 양식 쪽 화면 / 인쇄 화면 전환 | Toggle form layout and print preview | — | Document open | Toggles `PageSheet` between HTML form and `document/render` |
| 최신 수정본 되돌리기 제안 | Propose undo of latest version | — | >= 1 applied candidate | `proposeReverseFromCandidate(headRunId)` -> `Review` |
| 언어 바꾸기 (한국어 / English) | Switch language (Korean / English) | — | Always | Toggles `language` & persists via `POST /api/prefs` |
| 화면 테마 바꾸기 (밝게 / 어둡게) | Toggle light and dark theme | — | Always | Cycles `theme` & persists via `POST /api/prefs` |
| 설정 열기 | Open Settings | `Cmd/Ctrl+,` | Always | `setScreen("settings")` |
| 경로로 문서 열기 (자세히) | Open document by file path (Details) | — | Always (Operator) | Opens `BrowserOpenDialog` (`workspace/openPath`) |
| 에이전트 연결 및 작업 기록 보기 (자세히) | Agent host setup and event log (Details) | — | Always (Operator) | Opens `OperatorAgentModal` (`/api/agent-host/*`, raw `Timeline`) |

---

## 7. What stays under `자세히`

Nothing is deleted from the operator's debugging capability, but every machine-facing identifier below is strictly hidden from primary surfaces and rendered in `12px` `--font-mono` only when the user explicitly opens `자세히` (`Details`) or triggers an operator command from `Cmd/Ctrl+K`:

1. **Per-change row `자세히` (`Review` and `Fill`):**
   - Internal operation ID and wire `kind` (`op-2`, `fill_cell`, `replace_at_cell`, `set_run`, `delete_guides`, `mode: "replace" | "append"`).
   - Structural region and cell coordinates (`sectionIndex`, `tableIndex`, `row`, `col`, `regionId`, `paragraphIndex`, `runIndex`, UTF-16 `start`/`end` offsets).
   - HWPX typography and style IDs (`charPrIdRef`, `styleIdRef`, `charPr 11 -> 23`, script/colour anomaly target IDs).
   - Raw paragraph guard diff payload (`paragraphIndex`, `pass`, `kept`, `added`, `removed` arrays across the 15 `rt_fidelity.py` categories).
   - Raw validation/refusal codes and server strings (`cell_not_fill_target`, `at_cell_expect_mismatch`, `fill_charpr_color_anomaly`) when a finding is attached to that row.
2. **Document & page header `자세히` (`PageSheet` sub-bar):**
   - `sessionId`, `sourceSha256` (`workspace/openPath` / `session/list`), the head candidate's `sha256` (from its `candidate/list` row), byte size, format string, and section/table/region counts from `document/inspect`.
   - Render tier grade (`hancom`, `pdf`, `own-uncertified`), renderer unavailable reason (`rasterizer_missing`, `no_rasterizable_artifact`, `needs_conversion`), `dpi`, `contentBoxPx`, and `skippedXml` tag counts from `document/render` (`rt_own.py:68-87`).
   - Geometry derivation method (`matched_text`, `cell_borders`, `interpolated`, `own_cell`), `confidence` (`unique`, `ambiguous`, `unmapped`), `absenceReason`, and cross-check pixel deltas from `document/pageGeometry` (`rt_geometry.py:66-110`).
3. **Candidate & audit `자세히` (`History`):**
   - Full `receipt.json` payload as typed in `desktop/src/types.ts` `Receipt` (`runId`, `planId`, `planHash`, `backend`, `createdUtc`, nested `source {name, sha256, bytes}`, nested `candidate {role, path, sha256, bytes}`, `base`, `reverses`, nested `approval {approvalId, planHash, requestedUtc, resolvedUtc, approver, decision}`, `steps[]`, `checks`).
   - Raw `checks` object (`residue`, `guard`, `wellformedness`, rule states `hard`/`warn`/`skipped`/`clean`, check states `ran`/`unavailable`/`skipped`, raw `Finding` JSON).
   - Candidate artifact disk path under the runtime workspace.
4. **Operator modal via `Cmd/Ctrl+K` (`에이전트 연결 및 작업 기록 보기 (자세히)`):**
   - Runtime sidecar `pid`, protocol version, containment verification state (`런타임 pid · 자식 프로세스 정리 상태`), and backend capability matrix (`preedit`, `xml`, `com`).
   - Agent Host configuration (`provider`, `model`, `baseUrl`, credential slot names via `/api/agent-host/*` and `/api/credentials/*`).
   - Live raw JSON-RPC / SSE event log (`plan.proposed`, `approval.requested`, `plan.applied`, agent tool calls and raw turn payloads).

*(Exception required by the brief: `planHash` and `boundSha256` remain directly visible—not hidden inside a collapsed toggle—in `12px` monospace inside `ApprovalDialog` so the human approver sees the exact cryptographic hashes their approval binds to.)*

---

## 8. Data check

Target: **Zero new runtime JSON-RPC methods, zero new `rt_ui.py` HTTP endpoints, and zero changes to `rt_ui.py` security.**

### 8.1 Screen-to-endpoint / RPC mapping

| Screen | UI feature / data need | Existing bridge endpoint or JSON-RPC method | Source citation (`path:line`) |
| :--- | :--- | :--- | :--- |
| **Open** | Load/save recent session metadata, UI language, theme, and draft counts | `GET /api/prefs`, `POST /api/prefs` | `runtime/scripts/rt_ui.py:968-1006, 2141, 2214` |
| **Open** | List bundled standard `.hwpx` forms | `GET /api/corpus-files` | `runtime/scripts/rt_ui.py:1009-1028, 2145` |
| **Open** | Drag-and-drop or OS file picker upload (web mode) | `POST /api/open-upload` -> `workspace/openPath` | `runtime/scripts/rt_ui.py:1031-1083, 2215` |
| **Open** | Open local or bundled `.hwpx` / `.hwp` path | `workspace/openPath` | `runtime/scripts/rt_server.py:379`, `runtime/scripts/rt_core.py:253` |
| **Open** | Enumerate active runtime sessions (`sessionId`, `path`, `headRunId`) | `session/list` | `runtime/scripts/rt_server.py:385`, `runtime/scripts/rt_core.py:261`, `runtime/scripts/rt_session.py:481` |
| **Open** | Detect plans proposed externally via CLI/MCP for pending badge counts | `GET /events` (SSE) / `event/poll` + `plan/get` | `runtime/scripts/rt_ui.py:2100`, `runtime/scripts/rt_server.py:445, 524` |
| **Review** | Page metrics, table graph, cell classifications, removal targets | `document/inspect` | `runtime/scripts/rt_server.py:390`, `runtime/scripts/rt_core.py:265`, `runtime/scripts/rt_session.py:617` |
| **Review** | Read paragraph text, run inventory, and cell contents for page & diff | `document/readRegion` | `runtime/scripts/rt_server.py:410`, `runtime/scripts/rt_core.py:305` |
| **Review** | Propose, re-propose (single-op edit/delete), validate, and read plan | `plan/propose`, `plan/validate`, `plan/get` | `runtime/scripts/rt_server.py:419-449`, `runtime/scripts/rt_core.py:381-482` |
| **Review** | Paragraph fact-guard verdict (`유지됨` / `바뀐 사실` + named tokens) | `POST /api/guard/diff` (`{ sessionId, planId }` calling `RuntimeCore.plan_preview`, or `{ beforeText, afterText }`) | `runtime/scripts/rt_ui.py:1632-1773, 2226`, `runtime/scripts/rt_core.py:572-659`, `runtime/scripts/rt_guard.py:124` |
| **Review** | Request approval, read bound `planHash` + `boundSha256`, approve or return | `approval/request`, `approval/get`, `approval/resolve` (host), `plan/apply` (host) | `runtime/scripts/rt_server.py:450-481`, `runtime/scripts/rt_core.py:484-570` |
| **Review** | Quiet bottom prompt input to request or revise an agent plan | `POST /api/agent-host/run`, `POST /api/agent-host/stop` (status via `GET /api/agent-host/status`) | `runtime/scripts/rt_ui.py:2149, 2221-2222` |
| **Review** | Optional print-screen raster check & marker bounding boxes | `document/renderPrepare` (host), `document/render`, `document/pageGeometry` | `runtime/scripts/rt_server.py:512, 659, 668`, `runtime/scripts/rt_render.py:274`, `runtime/scripts/rt_geometry.py:689` |
| **Review & History** | Export current head or specific historical `runId` as `.hwpx` | `POST /api/export` + `GET /api/export-download` | `runtime/scripts/rt_ui.py:1086-1195, 2114, 2216` |
| **Fill** | Identify fillable blanks (`fill_target`), static headers (`static`), guides (`guide`), spacers (`spacer`) | `document/inspect` (`regions.regions`, `graph.tables`), `document/readRegion` | `runtime/scripts/rt_session.py:649-688`, `engine/scripts/form_inspect.py:1063-1132` |
| **Fill** | Stage blank fills, inline run edits, and guide removals into a validated plan | `plan/propose`, `plan/validate` | `runtime/scripts/rt_server.py:419, 439` |
| **History** | Vertical timeline of applied candidates | `candidate/list` | `runtime/scripts/rt_server.py:483`, `runtime/scripts/rt_apply.py:391` |
| **History** | Approval attribution (`approved` vs `auto_approved`), timestamp, ops summary, check states | `receipt/read` (per `runId`, cached client-side in session store) | `runtime/scripts/rt_server.py:505`, `runtime/scripts/rt_apply.py:442` |
| **History** | Compare any two versions (`원본 문서` or `runId` A vs `runId` B) | `candidate/compare` + `POST /api/guard/diff` (`{ sessionId, runId, againstRunId }`) | `runtime/scripts/rt_server.py:489`, `runtime/scripts/rt_core.py:793`, `runtime/scripts/rt_ui.py:1679-1700` |
| **History** | Restore = propose reverse plan through standard approval gate | `document/readRegion` + `plan/propose` (`reverses: { runId }`) | `runtime/scripts/rt_plan.py:432`, `desktop/src/actions.ts:1125-1268` |
| **Settings** | Read/write Language, Theme, and Runtime root; restart sidecar on root change | `GET /api/prefs`, `POST /api/prefs`, `GET /api/default-root`, `POST /api/runtime/start` | `runtime/scripts/rt_ui.py:958-1006, 2141, 2144, 2211, 2214` |

### 8.2 Risk register & security verification

- **New runtime methods or bridge endpoints (`RISK: NONE`):** Every screen is 100% fed by existing Runtime v0 JSON-RPC methods and `rt_ui.py` HTTP routes. Four nuances are handled purely in TypeScript without touching Python:
  1. *Pending count on `Open` recent rows:* `session/list` (`rt_session.py:481`) returns `sessionId`, `path`, and `headRunId` without a `planCount` field. Client-created drafts already persist in `ui-prefs.json` (`GET /api/prefs`), and externally proposed CLI/MCP plans emit `plan.proposed` on `event/poll` (`rt_server.py:524`) with `planId` resolvable via `plan/get` (`rt_server.py:445`). No `plan/list` RPC is needed.
  2. *Guard diff when a draft has a validation error:* `POST /api/guard/diff` with `{ sessionId, planId }` calls `RuntimeCore.plan_preview` (`rt_core.py:593`), which raises `plan_invalid` if validation is hard-blocked. Because `POST /api/guard/diff` *already* accepts direct `{ beforeText, afterText }` (`rt_ui.py:1637-1645`), the client falls back to sending `{ beforeText, afterText }` projected from `readRegion` + `planProjection.ts` whenever `plan.state === "invalid"`, keeping guard badges live at all times.
  3. *Timeline attribution on `History`:* `candidate/list` rows carry `runId`, `sha256`, `bytes`, `createdUtc`, `planId`, `base`, `reverses`, `acceptance` and `opKinds` (`rt_apply.py:420-430`); the approval time is only in the receipt (`approval.resolvedUtc`), so `HistoryView` fetches `receipt/read` lazily for visible nodes and caches the immutable receipts in memory by `runId`.
  4. *Standalone Tauri parity:* In web mode (`rigorloom ui`), `POST /api/guard/diff` runs directly in `rt_ui.py`. For standalone Tauri builds (`isTauri() === true` where `rt_ui.py` HTTP routes are absent, `desktop/src/runtime.ts:488`), `desktop/src/runtime.ts` mirrors the 15 deterministic regex extractors from `rt_fidelity.py:14-61` in pure TypeScript over `before`/`after` strings—requiring zero new Tauri Rust commands or Python RPCs.
- **`rt_ui.py` security (`UNCHANGED`):** Loopback-only `127.0.0.1` binding, per-launch `X-Rigorloom-Token` header check (plus query-token scoping strictly to `GET /events` and `GET /api/export-download`), `Origin` / `Host` loopback verification (`rt_ui.py:2038-2065`), `_require_bare_component` path traversal guards, `MAX_SOURCE_BYTES` / `MAX_JSON_BODY_BYTES` caps, and `host`-vs-`agent` RPC method separation (`rt_server.py:159-176`, keeping `approval/resolve` and `plan/apply` strictly host-only) remain completely untouched.

---

## 9. Page rendering

Rigorloom has two existing ways to show a `.hwpx` page. An honest design uses each for what it actually guarantees and tells the truth about what does not match 한글 print output.

### 9.1 Path A (Default in `Review` and `Fill`): Scaled HTML Form Sheet (`PageSheet` + `TextView`)

- **How it works with existing data:** `document/inspect` (`rt_session.py:617-695`) supplies `pageMetrics` (`width`, `height`, `margin.{left,right,top,bottom,header,footer,gutter}`, `usable_width`, `usable_height`, `desktop/src/types.ts:115`) in HWPUNIT (1/7200 inch, `engine/scripts/form_inspect.py:779-834`); the UI converts with mm = value x 25.4 / 7200 (A4 59528 x 84188 = 210 x 297 mm) and `graph.tables` (row counts, column counts, cell spans, `classification`). `document/readRegion` supplies full paragraph runs and cell text. `PageSheet.tsx` sizes a white sheet (`aspect-ratio: width / height` from `pageMetrics`, e.g., `210 / 297` for A4) with proportional print margins inside the `60%` desk canvas (`#F0F0EE`), sets all Korean text in bundled `Pretendard Variable`, draws `1px` crisp print borders (`--border-print`) on form tables, tints `static` label cells subtly, and renders inline change markers (`Review`) or click-to-type `SeatEditor` inputs (`Fill`) directly inside the DOM cells.
- **Why it must be the default:** It renders instantaneously on Linux, macOS, and Windows with zero external binaries; text stays crisp at any zoom; screen readers and keyboard `Tab` order work natively; and every proposed edit (`fill_cell`, `replace_at_cell`, `set_run`, `delete_guides`) previews live *before* `plan/apply` writes a candidate `.hwpx`.
- **What will NOT match 한글 print output in Path A (honest limits):**
  1. **Pagination & automatic page breaks:** Multi-page flow is approximated by section breaks and estimated content height rather than 한글's proprietary HWPX line-and-table splitter; a long table that spills onto page 2 in 한글 may appear as one continuous sheet frame until rasterized.
  2. **Original HWPX fonts & glyph metrics:** Forms authored in `함초롬바탕` (`HCR Batang`), `휴먼명조`, or `돋움` render in bundled `Pretendard Variable` (`sans-serif`), so character widths, kerning, and line-wrap points differ from Hancom print.
  3. **Exact column widths & border styles when unrasterized:** Where `inspect.graph.tables` carries row/col spans without millimeter column widths or double/dotted border styles, HTML table layout distributes column widths proportionally rather than matching exact HWPUnit rule geometry.
  4. **Floating objects, equations, stamps, and headers/footers:** Floating pictures, 직인 (seal images), HWP equation scripts, and running headers/footers outside body/table regions are omitted or shown only as quiet placeholders.

### 9.2 Path B (One-click `인쇄 화면 전환` in `Review`): Raster Render + `pageGeometry` Overlay (`PagePreview` + `PageOverlay`)

- **How it works with existing data:** Calls `document/renderPrepare` (`rt_server.py:659`) and `document/render` (`rt_render.py:274`, `rt_own.py:68`) to display a `150 DPI` PNG of the page alongside `document/pageGeometry` (`rt_geometry.py:689`) bounding boxes for change markers.
  - **Tier 1 (`grade: "hancom"`):** Windows machine with 한글 installed—true print-certified rendering.
  - **Tier 2 (`grade: "pdf"`):** Bundled/companion PDF rasterized via `pdftoppm` (`poppler`)—exact print layout for the source or exported PDF.
  - **Tier 3 (`grade: "own-uncertified"`):** Built-in `render_hwpx.py` renderer (`rt_own.py`)—renders HWPUnit table column widths, cell borders, cell shading, and pagination without 한글, but uses system fallback fonts and skips unsupported XML tags (`skippedXml`).
- **What will NOT match or is constrained in Path B (honest limits):**
  1. **Unapplied plans cannot be raster-rendered by 한글 until applied:** `document/render` rasterizes an on-disk artifact (`source` or an applied `candidate` `runId`). For an *unapplied* plan, Path B must overlay HTML before/after markers (`PageOverlay`) atop the base document's PNG using `pageGeometry` coordinates; if an edit wraps onto an extra line, the base PNG underneath does not reflow until `승인` creates the candidate.
  2. **Environment availability:** On Linux/macOS without `pdftoppm` (`rasterizer_missing`) or when `render_hwpx.py` skips complex drawing controls, Tier 1/2 are unavailable and Tier 3 explicitly labels itself `미리보기 화면 (인쇄본 대조 전)` (`Preview layout — not print-certified`) instead of claiming print fidelity.
  3. **Geometry mapping gaps:** Cells without drawn borders (`no_drawn_grid`) or dense pages (`page_too_dense` at `rt_geometry.py:93`) can yield `unmapped` or `ambiguous` boxes (`CONFIDENCES` at `rt_geometry.py:74`); in those cases, clicking the row in the right-hand `ChangeList` still highlights the change text and shows the page, without drawing a misleading box at `(0, 0)`.

---

## 10. GPT Sol attack

## GPT Sol attack (unedited)

### Open

1. “Will opening overwrite my 한글 file?” — **yes**: the subtitle explains the working copy.
2. “Why will my familiar .hwp not open?” — **partly**: conversion/refusal is specified; show supported formats and conversion availability before selection.
3. “Which button opens my own form?” — **yes**: file selection and bundled forms have separate labels.
4. “Are these bundled forms current official forms?” — **no**: show provenance and revision date, or explicitly say these are examples.
5. “Does ‘변경 4건 대기’ mean four missing answers?” — **no**: label these proposed edits awaiting review, separately from unfilled blanks.
6. “Which of two identically named files is mine?” — **partly**: parent-folder disambiguation helps; expose the full filename and location on focus, including mobile truncation.
7. “Does a recent entry reopen yesterday’s copy or today’s changed original?” — **no**: explain saved session versus reopening the source and handle changed/missing sources.
8. “What should I do on my first launch?” — **yes**: empty recents collapse and bundled forms expand.
9. “Why did one recent entry open Fill and another Review?” — **partly**: the routing rule exists only in the specification; give each row an explicit destination/action.
10. “Did my drop work, and can I retry without duplicating it?” — **no**: specify upload/conversion progress, failure recovery, and duplicate-open behavior.

### Review

1. “Is the paper showing the original or the proposed result?” — **partly**: before/after markers help; label the whole page’s version and preview mode persistently.
2. “Where on the form is this change?” — **yes**: row selection and page markers synchronize in both directions.
3. “Does green ‘유지됨’ mean this answer is factually correct?” — **no**: say it only means the checker detected no protected-token loss/change; it does not verify truth.
4. “Why is a changed date allowed?” — **partly**: the acknowledgement explains the exact date; distinguish intentional changes from hard failures that acknowledgement cannot override.
5. “Does 승인 sign, submit, save, or just approve?” — **partly**: the dialog says a new revision is created; state that export is still required and no external submission occurs.
6. “Am I approving one selected row or all four?” — **yes**: the dialog explicitly names the total change count.
7. “Can I correct one wrong answer without rejecting everything?” — **yes**: the selected row offers direct editing and removal.
8. “Who receives 돌려보내기, and will somebody actually revise it?” — **partly**: agent/manual behavior is defined; show the recipient, send result, and next step, including agent-unavailable cases.
9. “Can I trust the page breaks, seal, and printed appearance?” — **partly**: section 9 admits limitations; put the HTML approximation warning on the actual screen, including omitted objects.
10. “Did approval succeed after a timeout, or should I click again?” — **no**: design the applying, unknown-outcome, retry-disabled, and completed states with a link to the resulting revision.

### Fill

1. “Where may I type?” — **yes**: empty blanks have boundaries and a direct input prompt.
2. “Why can’t I type into this apparent blank?” — **partly**: static-cell refusal has an escape hatch; specify behavior for unrecognized blanks and duplicate field names.
3. “Will Enter cut off my last Korean syllable?” — **yes**: composition-aware dispatch and the key-code fallback are specified.
4. “How do I put a second line in an address?” — **partly**: multiline controls and shortcuts exist; reconcile ordinary Enter behavior between section 2.3 and the keyboard table and show the active hint.
5. “Did clicking elsewhere save this answer?” — **partly**: blur commits nonempty text; show saved-to-draft status and clarify that it is not yet applied to a revision.
6. “How do I erase an answer I already committed?” — **no**: define empty-value commit, clearing versus removing a proposal, and what happens on blur after deleting all text.
7. “Does 빼기 erase the form’s original contents?” — **no**: label it ‘remove this proposed edit’ and show the value that returns, with visible undo.
8. “Will blue instructions become my submitted answer?” — **yes**: instructions become a caption and the replacement behavior is explained.
9. “Does ‘9 blanks’ mean nine mandatory answers?” — **no**: distinguish detected blanks from required fields; do not imply completeness validation.
10. “Will a long answer fit when I open the exported form in 한글?” — **no**: show overflow/layout uncertainty and offer print verification; automatic font-size reassurance does not establish fit.

### History

1. “Which revision is actually current?” — **yes**: the timeline marks the current revision.
2. “Which way does this comparison run?” — **yes**: baseline/target selectors and labeled values establish direction.
3. “Who approved this document?” — **partly**: ‘직접 승인’ describes a method, not a person; show recorded approver or explicitly say identity was not recorded.
4. “Is this the approval time or the time changes were applied?” — **no**: label the two timestamps accurately and separately.
5. “Does restoring revision 1 discard revisions 2 and 3?” — **no**: explain that undoing a selected change acts on the current head and can preserve later edits; distinguish this from whole-version restoration.
6. “Will clicking 되돌리기 change my file immediately?” — **yes**: the explanatory text says it creates a proposal requiring approval.
7. “Can I restore deleted instructions?” — **partly**: the fallback is specified; identify the exact earlier version offered and explain that saving it does not change the current working version.
8. “Do 파일 내보내기 and 이 버전 저장 save the same thing?” — **no**: name the revision on each action and specify its filename/destination.
9. “Does 점검 통과 mean it is ready for official submission?” — **no**: explain which checks ran and expose missing/unavailable checks in plain language before export.
10. “Why is an unapplied or rejected edit missing from history?” — **no**: label this as applied-revision history and provide a clear route back to pending proposals.

### Settings

1. “Will changing language translate the document?” — **partly**: copy refers to screen labels; explicitly say document contents stay in their original language.
2. “Can I undo an accidental language switch?” — **yes**: language choices retain their native names.
3. “What does 시스템 설정 follow?” — **partly**: the choice exists; explain that it follows the operating system and show the currently effective theme.
4. “Will dark mode change my printed document?” — **no**: explain screen appearance versus exported/printed formatting.
5. “Is 작업 폴더 my final output folder?” — **partly**: storage copy helps; explicitly distinguish internal working storage from export destinations.
6. “Will changing folders move all my documents and history?” — **no**: state whether this switches workspaces or migrates data, and provide a route back.
7. “What happens to the answer I am typing if I change folders?” — **partly**: preservation is promised; specify a successful save checkpoint before restarting and a save-failure path.
8. “Where is Save, and did my setting stick?” — **no**: specify immediate-save feedback, failure feedback, and rollback behavior.
9. “Which computer’s folder am I choosing in browser mode?” — **no**: identify the runtime machine and provide a selection mechanism appropriate to web versus desktop.
10. “What if the folder is unwritable or a restart fails?” — **no**: show the error beside the control and retain/recover the previous working folder.

### Other defects

Code citations below are relative to the repository root.

- **Invented geometry fields:** section 9.1 names `pageMetrics.widthMm` and `heightMm`; the current UI contract has `summary.pageMetrics.width`, `height`, `margin`, and `assumptions` (`desktop/src/types.ts:115`). Specify the actual units and conversion before claiming physical print margins.
- **Invented timestamps:** sections 2.4/8 claim candidate `createdAt` and receipt `appliedAt`; published receipts and candidate rows use `createdUtc` (`runtime/scripts/rt_apply.py:285`, `runtime/scripts/rt_apply.py:425`). Approval time is separately `approval.resolvedUtc` (`desktop/src/types.ts:301`). The History mockup conflates approval and application.
- **Invented receipt shape:** section 7 lists flat `approvalId`, `sourceSha256`, and `outputSha256` as receipt fields; the contract nests approval, source, and candidate (`desktop/src/types.ts:336`). Map to actual fields rather than specifying a fictitious raw payload.
- **Invented upload constant:** security section 8.2 names `MAX_UPLOAD_BYTES`; upload enforcement uses `MAX_SOURCE_BYTES` (`runtime/scripts/rt_ui.py:1042`); JSON body cap is `MAX_JSON_BODY_BYTES` (`runtime/scripts/rt_ui.py:62`).
- **Restoration overclaim:** ‘any two’ comparison is not arbitrary whole-version restoration. `proposeUndoOf` reads a selected operation’s parent values and stages inverses on the current head (`desktop/src/actions.ts:1153`, `desktop/src/actions.ts:1251`). Define overlapping later edits and exclude unsupported operations before offering restore.
- **Guard fallback overclaim:** `planProjection.ts` translates operations to a queue; it is not a document preview engine, and rejects unsupported operations (`desktop/src/agent/planProjection.ts:1`). Section 8.2’s promise of live guard badges ‘at all times’ for invalid plans needs a complete, faithful projection or an unavailable state.
- **Unsupported certainty in green examples:** Review’s expanded details explicitly show added numbers `110, 4`, while the main row says ‘유지됨’; History likewise changes `110` to `110 … 4층` with a green badge. Explain the actual guard policy and distinguish permitted additions from unchanged facts.
- **Approval mockup contradicts required gate:** `review-1440.svg` shows the changed-date warning and an active approval button without the acknowledgement checkbox required by section 2.2. It also truncates both hashes despite the requirement to show the exact binding; provide full selectable values.
- **IME/editable coverage gap:** section 6.1 protects only input/textarea and handles physical `KeyA`/`KeyR` outside them. Any contenteditable page editor would turn Korean `ㅁ`/`ㄱ` into approval/return actions. Exclude every editable target and active composition globally, including Enter-to-confirm in dialogs. Input/textarea composition is explicitly covered, so these shortcuts are not inherently conflicting there.
- **Keyboard trap:** Fill reserves Tab/Shift+Tab for cycling blanks but gives no keyboard escape to the review button or inspector. Define a way to leave blank navigation.
- **Low-contrast essential text:** muted `#8A8984` on white is approximately 3.5:1; dark muted `#6E6D68` on `#1C1C1A` is approximately 3.3:1. These are used at 12px for timestamps and guidance. Raise contrast for readable text.
- **Density contradicts brief:** Fill specifies 44px list rows; Review SVG uses 72/76/104px unexpanded rows, versus the requested 32–36px rows. Define compact rows with expansion for full diff details.
- **Unsubstantiated number:** ‘Office reviewers scan 10 to 40 form entries at once’ in section 1 has no evidence; remove the claim. Example counts and chosen dimensions should be explicitly marked as mock data/design values.
- **Runtime-root reassurance is incomplete:** changing roots stops the running sidecar (`runtime/scripts/rt_ui.py:613–623`). The design needs an explicit save/agent-work checkpoint before restart; an existing endpoint does not make this transition lossless.
- **Security boundary:** no `rt_ui.py` security change is requested by the design. Keep that constraint; do not implement browser folder selection by relaxing path, token, Host, or Origin checks.
- **Surface audit:** the displayed op/cell identifiers in Review are inside an explicitly expanded ‘자세히’ region; the approval hashes are the brief’s explicit exception. No other definite internal-ID leak or doubled translated label was found. Separate native language options are not a doubled label.
