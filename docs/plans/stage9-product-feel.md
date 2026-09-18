# Stage 9 — Product feel: from "explains itself" to "just works"

Status: ACTIVE 2026-09-18. Owner: Fable. Trigger: the user wants the GUI and app experience to feel like a paid
product many people already use, not like AI output. Honesty rules unchanged (no render-proof claims, approvals stay
human, receipts stay complete), but honesty moves to the details layer instead of the primary surface.

## Audit (Fable, from fresh captures of every state, 2026-09-18 06:40)
1. Explanatory prose on every surface: panels open with a paragraph about what they are ("원본과 후보본을 시간순으로
   봅니다. 되돌리기는…", "에이전트는 계획만 냅니다…", "이 검사 응답에는 forbidden 구역이…", "승인하면 이 계획 지문에 대한
   결정만…"). The single biggest tell.
2. Engineering vocabulary on primary surfaces: charPr 11 → 23, plan hashes (aaaa15…), `fill_cell exit 0`,
   agenthost-mock, host-operator, 지문, forbidden, MCP include, 런타임 pid, structural_only, plan-demo000.
3. Two toolbar rows and about fourteen controls; the pipeline strip is a third row. Paid apps: one row, three
   primary actions, the rest in menus.
4. The structure tree is a debug list: nine identical 채움 tags, charPr transitions, 금지/안내문 counts of 0.
5. Receipt = raw table of hashes and ids; the human story (what changed, who approved, when, how big) is buried.
6. Approval-waiting card: orange wall of prose with requester ids. Toast shows a hash.
7. Mixed Korean register (넣으십시오 / 합니다 / 해 줍니다), machine-shaped sentences.
8. Not yet measured: startup time to Home and to an opened form in the built app, transitions, focus handling,
   window and rail state persistence, first-run experience.

## Principles
- Show, don't explain. A surface explains itself once (tooltip or first-run hint), then gets out of the way.
- Human words first; technical truth one click away (details rows, copy buttons), never deleted.
- One primary action per surface; secondary actions in menus; irreversible actions confirmed inline.
- Quiet chrome: one toolbar row, one status line, consistent short 합니다체, tabular numbers, no tag spam.
- Feel: 150 ms transitions, skeletons while loading, small top-right toasts, remembered window and rail state,
  Ctrl+K command palette, focus lands where the user is looking.
- Measured: cold start to Home and to an opened form in the built app, with numbers in the ledger.

## Slices (Cursor lanes; Fable reviews captures for each; nothing ships on tests alone)
- [ ] F0 Copy audit note (read-only): every user-visible string with location, class and a proposed rewrite in
      short 합니다체; prose walls cut to one line or moved to tooltips or first-run. Fable edits the proposals
      before they are applied.
- [ ] F1 Chrome: one toolbar row (열기 · 검사 · 승인 primary right; view toggle segmented; zoom in a menu); pipeline
      strip merged into a slim line; status bar = document · state pill · engine; duplicate zoom controls removed.
- [ ] F2 Structure tree as an outline: 입력 칸 collapsed with count; human addresses (표 1 · 5행 2열); charPr and tag
      spam to hover or details; empty groups hidden; forbidden only in a details layer.
- [ ] F3 Review card and receipt as a human story: before → after, proposer, one 승인/거부 pair; hashes and ids under
      기술 정보; approval-waiting card compact; receipt summary line first, technical block copyable below.
- [ ] F4 Agent tab: tool chatter collapsed into one expandable step row, compact plan card, composer with a
      placeholder only, no protocol notes in the visible thread.
- [ ] F5 Feel: transitions, skeleton on open, top-right toasts without hashes, window and rail state persisted,
      Ctrl+K palette, focus management; first-run three-step hint, dismissible.
- [ ] F6 Startup and latency in the built app: measure cold start → Home, Home → 소논문 open, click → hunk queued;
      targets 2.0 s / 1.5 s / 100 ms; fix the largest cause found (sidecar start, inspect payload, bundle size).
- [ ] F7 Fable walk-through of the built app (ten minutes, screenshots); defects → F8 fit and finish.

## Ledger
| When | What | Result |
|---|---|---|
| 2026-09-18 06:40 | Audit from fresh captures | eight findings above; F0 and F1 launched |
