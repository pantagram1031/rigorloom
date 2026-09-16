# Stage 4b — Desktop revamp: from debug console to product

Status: ACTIVE 2026-09-17. Owner: Fable. Trigger: the user looked at the Stage 4 desktop and said it
"looks vibe coded"; asked for a revamp inspired by open-source apps. Input: research note
`docs/plans/analyses/stage4b-design-research.md` (R0, grok-low). Renderer/rematch/certificate freeze stays
in force: nothing here may add a rendering claim, weaken a gate, or bypass approve → apply.

## Diagnosis (from screenshots of the vite dev-mock, 2026-09-17)

The tokens are fine (Pretendard, warm paper, teal accent). What reads as "vibe coded":

1. Everything at once. Three panes plus a toolbar plus a status bar are all populated on first open; the
   right pane stacks 선택 항목 / 검토 대기열 / 기록 / 연결 as four sections of prose with no hierarchy.
2. The status bar is a debug readout: twelve chips (쪽, 위치, 입력, 원본 hash, 후보본, 렌더 증명, 제출 검사,
   채움 자리, 서식 검사, 검사 실행, 런타임 pid, 자식 정리, 확인 안 됨). A user needs at most: what document,
   is it checked, is anything waiting for approval.
3. Internal jargon as labels (렌더 증명, 제출 검사, 자식 정리, 런타임 pid, structural_only) with no
   tooltips. The honesty is right; the vocabulary is the engineer's.
4. The 작업 (Agent) tab is a separate washed-out screen with a raw `[object Object]` in its sidebar
   (`TaskPacks`/`SessionList`), no empty state, and the composer sits in a dimmed centre.
5. Empty states are sentences in grey ("아직 만들어진 후보본이 없습니다…") rather than designed states with a
   single next action.
6. No home. The app opens straight into a fixture document; there is no welcome/recents screen.

## Principles (borrowed, one line each; details in the R0 note)

- Document is the hero (Typst / Overleaf / AFFiNE): the page or text occupies the centre with paper
  metaphor; every other surface collapses.
- One inspector, tabbed (Obsidian right sidebar / Yaak): 선택 · 검토 · 기록 · 에이전트 as tabs of one right
  panel, badge counts on 검토 (queued ops) and 기록 (new receipts).
- Review is a diff (GitButler / Zed multibuffer / GitHub PR): each queued op is a hunk card with
  before/after, provenance in a details row, keyboard j/k + a/r; accept-all = approve the displayed hash.
- Status bar says three things (Zed / VS Code): document · verification state (one pill, popover for the
  twelve details) · runtime connection. Everything else moves into the popover or the inspector.
- Home with recents (Zed / GitButler welcome): open, recents, drop zone, one link to the CLI docs.
- Honest labels, human words: keep the promise, change the vocabulary; every renamed label gets a tooltip
  that says exactly what is and is not proven (glossary from R0).
- Empty states are designed (Linear-style): icon, one sentence, one action; never raw JSON or objects.
- No new document semantics; GUI and CLI still produce byte-identical plan JSON; IME gate stays.

## Slices (each: Cursor grok-high implements under a spec; Fable verifies headless tests + screenshots)

- [x] R0 Research note (cursor-grok-4.6-low-fast, 2.1 min, 87k in / 5.9k out / 511k cache): 18 patterns from GitButler,
      Yaak, AFFiNE, Zed, Obsidian, Typst, Pretendard/KLReq/Toss; IA proposal, glossary, top-ten fixes. Commit 37d707b.
- [x] R1 Stop the bleeding (cursor-grok-4.6-high-fast, 11 min, 318k in / 43k out / 4.1M cache; tests 149 → 157):
      `[object Object]` was `reason: String(e)` on a `{code, message}` throw in `loadTaskPacks` (fixed via
      `label.ts` + `asRuntimeError`); the dimmed Agent centre was `.action:disabled{opacity:.42}` plus a faint
      paragraph, now a full-contrast `EmptyState` ("에이전트가 연결되어 있지 않습니다" + 설정 열기) with the composer
      visibly disabled; `EmptyState.tsx` used by ReviewQueue/History/Conversation/SessionList; tree headings 표 /
      입력 칸; Hangul tracking off, tabular nums. Verified in dev-mock screenshots. Follow-up for R2: the
      browser-mode Tauri drag-drop unsubscribe error still logs once per mount (cosmetic in dev only).
- [x] R2 Shell IA (cursor-grok-4.6-high-fast, 16.6 min, 363k in / 58k out / 9.8M cache; tests 157 → 164): single
      workspace, header switch removed, right inspector tabs 선택 / 검토 / 기록 / 에이전트 with badges and a default-tab
      rule, left rail collapses to a 40px icon rail (Ctrl+B, prefs_save), status bar = name+backend · verification
      pill · 엔진 연결됨/끊김 · ⋯ 자세히 popover with the former chips and glossary tooltips; `setView('agent')` is now
      a tab switch; smoke checks relocated. Screenshot pass done (default, 검토, popover, collapsed rail, 에이전트).
      Follow-ups: popover is dense (R6); 기록 still mounts Timeline (R5).
- [x] R3 Home screen (cursor-grok-4.6-high-fast, 12.5 min, 499k in / 48k out / 4.7M cache; tests 164 → 171): Home
      replaces the three columns when no session is in front (mark, lede, 문서 열기, drop zone, recents from prefs
      with relative time and 찾을 수 없음 for missing files, first-run line, CLI 문서 / 설정), header 홈 button and
      Ctrl+Shift+H keep the session alive, splash ≤ 400 ms, status bar shows only the engine state on Home.
      Verified in dev-mock (page text + screenshots; recent row opens the workspace). Not done: CLI 문서 has no
      hosted URL yet, so it is an in-app hint.
- [x] R4 Review as diff (cursor-grok-4.6-high-fast, 14.3 min, 752k in / 56k out / 3.3M cache; tests 171 → 181):
      `HunkCard.tsx` per queued op (Korean kind label, address, state tag, before/after with an LCS diff from
      `diff.ts`, 승인/거부, folded 출처 row), j/k/a/r/Enter/Shift+A, 모두 승인 · N · hash in the tab header bound to
      the displayed plan hash, refusal card verbatim, byte-identical plan JSON test. Verified in dev-mock via DOM
      (queued 행정안전부 on 표 0 R0C14 → card + 모두 승인 · 1); the browser pane was too narrow for a screenshot of
      the inspector at that moment. Not done: per-hunk include/exclude (approval stays commit-bound by design).
- [x] R5 Agent chat + checkpoint timeline (cursor-grok-4.6-high-fast, 10.6 min, 380k in / 47k out / 3.8M cache;
      tests 181 → 187): bubbles + tool system rows, plan-arrival card that switches to 검토 and bumps its badge,
      sticky composer with 입력 중 … indicator and inert send while composing/disconnected, 문서 정보 as collapsed
      details; 기록 = 원본 → candidates timeline with head marker, 자세히 / 여기로 되돌리기 (reverse plan, never apply) /
      비교, protocol events under a collapsed 이벤트 (N). DOM-verified in dev-mock.
- [x] R6 Polish pass (cursor-grok-4.6-high-fast, 17 min, 226k in / 57k out / 9.0M cache; tests 187 → 190): 19-glyph
      inline `Icon.tsx` wired through header, toolbar, tabs, tree, timeline, hunk cards, empty states; focus-visible
      rings, hover/pressed tokens, Korean type rules, dark-mode coverage with contrast fixes, reduced-motion; 24
      reference PNGs (home / workspace / review / history / agent / popover × 1280×800, 1920×1080 × light, dark)
      captured from the dev-mock via CDP into `docs/demo/desktop/` with `capture.mjs` + README. Fable reviewed the
      captures: accepted. Defects seen → R7: rail footer overlap with the 문서/작업 팩 disclosure, 기록 header count
      spacing, 서식 control clipping at 1280 px, popover density.
- [ ] R7 Fit and finish: the four defects above; recapture the six 1280×800 light PNGs.

## Verification per slice

`npm run build` and `npm test` from `desktop/` (count never drops), then Fable opens
http://localhost:5184 (`npx vite` from `desktop/`) and screenshots the states the slice touched. A slice is
done only when the screenshot matches the intent; "tests pass" alone is not acceptance for a revamp.

## Ledger

| When | What | Result |
|---|---|---|
| 2026-09-17 | Diagnosis from dev-mock screenshots (document tab, 작업 tab) | six findings above; R0 launched on cursor-grok-4.6-low-fast |
| 2026-09-17 | R0 note (grok-low) and R1 fixes (grok-high) landed; 작업 tab screenshot before/after | see slices; commit below |
| 2026-09-17 | R2 shell IA landed; five dev-mock screenshots checked | commit below |
| 2026-09-17 | R3 home screen landed | commit below |
| 2026-09-17 | R4 hunk review landed; T9 runtime README (composer) committed 233270e | commit below |
| 2026-09-17 | R5 landed; gemini-3.8-flash C1 row recorded | commit below |
| 2026-09-17 | R6 landed with 24 reference captures; Fable review found four small defects → R7 | commit below |
