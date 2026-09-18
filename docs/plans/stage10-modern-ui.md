# Stage 10 — Modern UI: one primitive kit under every surface

Status: ACTIVE 2026-09-19. Owner: Fable. Trigger: the user pointed at the NN/g UI-elements glossary and the
shadcn/ui component catalogue and asked for a more modern UI. References read 2026-09-19:
https://www.nngroup.com/articles/ui-elements-glossary/ and https://ui.shadcn.com/docs/components.

## Diagnosis (inventory of desktop/src, 2026-09-19 01:40)
The tokens (Pretendard, warm paper palette, teal accent, radius, spacing scale) and the information architecture
from Stage 9 are right. What is missing is the layer shadcn/ui and every polished desktop app share: a small kit
of accessible primitives that every surface is built from. Today:

| pattern | count | what a modern app uses instead (NN/g name) |
|---|---|---|
| native `title=""` hovers | 56 | Tooltip: styled, delayed, keyboard-reachable, one design |
| raw `<details><summary>` | 34 | Accordion / Collapsible with a rotating chevron and motion |
| hand-rolled menus (overflow, 열기 ▾, 배율) | 3 | Dropdown Menu with roving focus, typeahead, shortcuts column |
| hand-rolled popovers (자세히, 비교) | 2 | Popover with focus trap, Esc, outside click, arrow |
| hand-rolled dialogs (설정, 영수증) | 2 | Sheet (side) / Dialog (modal) with focus trap and scroll lock |
| radio boxes for 테마 / 제공자 | 2 | Segmented control (Toggle Group) / Radio Group with proper roles |
| tab strips in ContextPanel and Settings | 2 | Tabs primitive with arrow-key navigation |
| custom toast | 1 | Toast/Snackbar: stacked, timed, action slot |
| Tag chip | 1 | Badge variants (default / secondary / outline / destructive) |
| no Kbd, Separator, Switch, Scroll Area, Alert, Progress, Table | 0 | present in shadcn/ui; needed by settings, status, results |

No new dependencies is the constraint (Tauri app, offline). shadcn's approach fits exactly: the primitives are
copied source, not a package. We build them ourselves on React 18 + CSS variables, following shadcn's anatomy and
ARIA (Radix semantics) but with our tokens.

## Principles
- One kit, everywhere: a surface may not render a menu, tooltip, dialog or accordion any other way.
- Anatomy and ARIA follow shadcn/Radix: roles, `aria-expanded`, `aria-controls`, roving tabindex, Esc closes,
  focus returns to the trigger, outside click closes non-modal layers, modal layers trap focus and lock scroll.
- Density from the tokens: 32 px rows, 30 px controls, 36 px menu items, 6 px radius on controls, 10 px on
  cards and sheets, 1 px hairline borders, no drop shadows heavier than the popover level.
- Motion 150 ms with `--ease`; reduced-motion respected; content-visibility for long lists.
- Dark mode by token only (already the rule).

## Slices
- [x] M1 Kit (grok-xhigh, 17 min, 255k in / 82k out; tests 249 → 277; gallery reviewed light+dark): `desktop/src/ui/` with Tooltip, Popover, DropdownMenu (items, separators, shortcuts, submenu-free),
      Dialog, Sheet, Collapsible/Accordion, Tabs, ToggleGroup (segmented), RadioGroup, Switch, Badge (variants),
      Kbd, Separator, ScrollArea, Progress, Alert, Table, Button (variants: primary / secondary / ghost /
      destructive / link; sizes sm / md), Input, Textarea, Select (native-backed with styled trigger), Command
      (adopt the existing palette), Toast (adopt), Skeleton (adopt), EmptyState (adopt). Each with a headless
      test for role/keyboard behaviour. A `docs/demo/desktop/kit.html` gallery route in the dev mock (`?kit=1`)
      showing every primitive in light and dark.
- [x] M2 (with M3, one grok-xhigh lane, 51 min; gates 0/0/0; tests 277) Adopt in the chrome and inspector: toolbar buttons and menus, status bar popover, inspector tabs,
      tree collapsibles, hunk 기술 정보, receipt sections, history compare popover, settings (sheet + tabs +
      segmented theme + switches), toasts, tooltips replacing every `title=`.
- [x] M3 Adopt in the remaining surfaces: Home (button variants, recents as Items), agent tab (message
      bubbles as Items, plan card as Card), pipeline strip and result cards (Progress, Alert, Table), Findings.
- [x] M4 Consistency sweep + captures (part 1 grok lane; part 2 Fable, no lane: C: was full): zero raw `<details>`
      and zero `title=` tooltips outside the kit; dark mode gallery reviewed; all reference PNGs recaptured;
      built-app smoke green (2026-09-19 08:20: 570 passed / 0 failed, 278 unit tests).

## Verification per slice
`npm run build && npm test` (count never drops) and Fable reviews captures, including the kit gallery in both
themes. The built-app smoke must stay green at the end (driver relocations allowed, assertions not).

## Ledger
| When | What | Result |
|---|---|---|
| 2026-09-19 01:40 | Inventory and plan | M1 launched |
| 2026-09-19 02:35 | M1 landed | kit gallery coherent in both themes; nits for M2/M3: tooltip demo row overlaps, toast/skeleton demo oversized. M2+M3 launched as one lane |
| 2026-09-19 03:30 | M2+M3 landed; Fable reviewed captures | adoption complete but the swap broke layout: icon+label Buttons stack and wrap, toolbar taller, Sheet header centred with a giant close, 자세히 popover clipped at the viewport bottom, first-run hint too heavy, hunk header wraps, dark paper too black → M4 fixes at the kit level, then rebuild + smoke |
| 2026-09-19 04:40 | M4 part 1 landed; BLOCKED on disk | C: drive is at 0 bytes free (464 GB used). The lane died with 'database or disk is full' after the kit fixes but before relocating smoke driver targets. Smoke on this build: 641 passed / 55 failed (own 17, overlay 20, chrome 11, edit 4, open 1, page 1, agent-live 1). Nothing in this session accounts for the space (session scratch ~25 MB; cargo target is on F:). Largest user-profile consumers found: AppData\Local 111 GB (wsl 25, Programs 19, Packages 14, Google 8, Android 7), AppData\Roaming 42 GB, Downloads 67 GB (sambalE 9.6 + sambalE-for-box.tar 9.0 + box-pull-sessions 6.5 + shorts-studio 4.4). Next after space is freed: M4 part 2 = relocate the 55 driver targets (assertions untouched), rebuild, smoke green, recapture |
| 2026-09-19 05:55 | M4 part 2 partial; disk workaround | C: hit 0 bytes: Cursor lanes, git and even console output failed. Workaround: worktree on F: (F:
| 2026-09-19 06:10 | M4 part 2 (Fable, direct; F: worktree `F:
igorloom-work\stage1`, branch `claude/stage1-report-demo-f`) | 55 → 2 failures by relocating driver targets to the kit's attributes (`data-state`, `role=menuitem`, `data-tip`) and one real defect fixed at the kit: the Tooltip wrapper span had taken the page-overlay `.ov` geometry (0 of 37 spans drawn); Tooltip now anchors on its child like shadcn's asChild (commit 4455254) |
| 2026-09-19 07:40 | Last 2 failures were a product defect, not a driver one | M4 part 1 had moved the 서식 readout (글꼴 · 글자 모양 · 크기) into the ··· overflow menu. Opening a menu moves focus; the seat editor commits on blur; so the readout could never describe a caret: it always said 본문 기준. Fix (category b): the readout is a read-only font box in the band's right cluster, as in Word/한글, never inside a menu. The band is now a container query (`.center-toolbar`): the box sheds the note, then charPr, then labels, then the face, and hides entirely below 600 px of band; below 560 px action labels and the zoom label go, gaps tighten. Grid side columns are `minmax(max-content, 1fr)` so clusters cannot overlap at 1024 with both rails open (measured: 414/418, 604/608 px edges). chrome.test.mjs updated to assert this mechanism instead of the dead `@media (min-width)` rules. Two DOM reads in the edit phase now wait (bounded, 5 s) for the row to paint before asserting; the assertion is unchanged |
| 2026-09-19 08:20 | Stage 10 DONE | `npm test` 278/0; grep gates 0 `title="`, 0 `<details`; full default smoke 570 passed / 0 failed on the rebuilt app (an earlier run on a loaded machine showed 4 timing failures in edit, which is what the bounded waits address; one run lost `_run/export` mid-way while a unit-test run overlapped it and was not reproducible alone). References recaptured from the F: tree (a stale vite on 5184 from the C: tree had served old code once; killed). Remaining for the user: push, PR from docs/plans/pr-stage1.md, free C: |
