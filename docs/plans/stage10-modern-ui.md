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
- [ ] M1 Kit: `desktop/src/ui/` with Tooltip, Popover, DropdownMenu (items, separators, shortcuts, submenu-free),
      Dialog, Sheet, Collapsible/Accordion, Tabs, ToggleGroup (segmented), RadioGroup, Switch, Badge (variants),
      Kbd, Separator, ScrollArea, Progress, Alert, Table, Button (variants: primary / secondary / ghost /
      destructive / link; sizes sm / md), Input, Textarea, Select (native-backed with styled trigger), Command
      (adopt the existing palette), Toast (adopt), Skeleton (adopt), EmptyState (adopt). Each with a headless
      test for role/keyboard behaviour. A `docs/demo/desktop/kit.html` gallery route in the dev mock (`?kit=1`)
      showing every primitive in light and dark.
- [ ] M2 Adopt in the chrome and inspector: toolbar buttons and menus, status bar popover, inspector tabs,
      tree collapsibles, hunk 기술 정보, receipt sections, history compare popover, settings (sheet + tabs +
      segmented theme + switches), toasts, tooltips replacing every `title=`.
- [ ] M3 Adopt in the remaining surfaces: Home (button variants, recents as Items), agent tab (message
      bubbles as Items, plan card as Card), pipeline strip and result cards (Progress, Alert, Table), Findings.
- [ ] M4 Consistency sweep + captures: zero raw `<details>` and zero `title=` tooltips outside the kit; dark
      mode gallery reviewed; recapture all reference PNGs; native smoke green.

## Verification per slice
`npm run build && npm test` (count never drops) and Fable reviews captures, including the kit gallery in both
themes. The built-app smoke must stay green at the end (driver relocations allowed, assertions not).

## Ledger
| When | What | Result |
|---|---|---|
| 2026-09-19 01:40 | Inventory and plan | M1 launched |
