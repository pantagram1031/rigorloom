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
- [ ] R2 Shell IA: single workspace (`DocumentView` absorbs `AgentView`): left outline rail (collapsible to
      icons), centre document, right inspector with tabs 선택 / 검토 / 기록 / 에이전트 and badge counts;
      status bar reduced to document · verification pill (popover holds the former chips) · runtime.
      View-state tests updated, `setView` kept as a tab switch for compatibility.
- [ ] R3 Home screen: `Welcome.tsx` becomes a real home (recents from prefs IPC, open, drop zone, CLI link);
      splash shortened; first-run copy.
- [ ] R4 Review as diff: hunk cards with before/after from `read-region`, provenance details row, j/k a/r
      keys, "모두 승인" = approve displayed hash, rejected hash cannot apply (existing tests preserved).
- [ ] R5 Agent in the inspector: Conversation + Composer inside the 에이전트 tab; plan arrival badges 검토;
      composition guard unchanged.
- [ ] R6 Polish pass: density, focus rings, icon set (inline SVG, no new deps), Korean line-height/letter
      spacing per R0 §glossary, dark mode check, 1280×800 and 1920×1080 screenshots into docs/demo/desktop/.

## Verification per slice

`npm run build` and `npm test` from `desktop/` (count never drops), then Fable opens
http://localhost:5184 (`npx vite` from `desktop/`) and screenshots the states the slice touched. A slice is
done only when the screenshot matches the intent; "tests pass" alone is not acceptance for a revamp.

## Ledger

| When | What | Result |
|---|---|---|
| 2026-09-17 | Diagnosis from dev-mock screenshots (document tab, 작업 tab) | six findings above; R0 launched on cursor-grok-4.6-low-fast |
| 2026-09-17 | R0 note (grok-low) and R1 fixes (grok-high) landed; 작업 tab screenshot before/after | see slices; commit below |
