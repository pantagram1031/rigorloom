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
- [x] F0 Copy audit note (grok-xhigh, 19 min): 1090 strings; KEEP 873 / SHORTEN 141 / RENAME 31 / MOVE-TO-DETAILS 26 / DROP 16 / tooltip 3; glossary + register rules (commit 94dd9dc). (read-only): every user-visible string with location, class and a proposed rewrite in
      short 합니다체; prose walls cut to one line or moved to tooltips or first-run. Fable edits the proposals
      before they are applied.
- [x] F1 Chrome (grok-high, 24 min; tests 225 → 229; captures reviewed): one toolbar row (열기 · 검사 · 승인 primary right; view toggle segmented; zoom in a menu); pipeline
      strip merged into a slim line; status bar = document · state pill · engine; duplicate zoom controls removed.
- [x] F2 Structure tree as an outline: 입력 칸 collapsed with count; human addresses (표 1 · 5행 2열); charPr and tag
      spam to hover or details; empty groups hidden; forbidden only in a details layer.
- [x] F3 Review card and receipt as a human story: before → after, proposer, one 승인/거부 pair; hashes and ids under
      기술 정보; approval-waiting card compact; receipt summary line first, technical block copyable below.
- [x] F4 Agent tab: tool chatter collapsed into one expandable step row, compact plan card, composer with a
      placeholder only, no protocol notes in the visible thread.
- [x] F5 Feel (grok-xhigh, 30 min; tests 234 → 240; captures reviewed, incl. palette): transitions, skeleton on open, top-right toasts without hashes, window and rail state persisted,
      Ctrl+K palette, focus management; first-run three-step hint, dismissible.
- [x] F6 Startup and latency in the built app: measure cold start → Home, Home → 소논문 open, click → hunk queued;
      targets 2.0 s / 1.5 s / 100 ms / 1.0 s sidecar. Cause: Home waited on sidecar+task packs+splash timer;
      open waited on duplicate `form_inspect` (`forbidden` + `readRegion`) before tree/paper; hunk DOM waited
      on `plan/propose` (React 18 batch) and IPC timing. After: Home 4334→2445 ms (still 0.45 s over; remainder
      is WebView2 process+first paint, not the sidecar), open 2877→679 ms, hunk 139→19 ms, sidecar 654→563 ms.
      `npm test` 240 pass; default smoke 570 passed, 0 failed.
- [x] F7 Fable walk-through (2026-09-18 22:05, dev mock at 1280×800, every tab plus settings) of the built app (ten minutes, screenshots); defects → F8 fit and finish.

## Ledger
| When | What | Result |
|---|---|---|
| 2026-09-18 06:40 | Audit from fresh captures | eight findings above; F0 and F1 launched |
| 2026-09-18 19:10 | F0 and F1 landed | F2–F4 launched as one lane on grok-xhigh using the audit as the copy source |
| 2026-09-18 19:45 | F2–F4 landed in one grok-xhigh lane (33 min, 650k in / 87k out; tests 229 → 234); Fable reviewed four captures: accepted | defects for F5 part A: 표 numbering tree (1-based) vs document (0-based), 'none' in 선택 header, 채움 자리 wording, strip labels, 쓰기 전 확인 chip, doubled 기록 heading |
| 2026-09-18 20:20 | F5 landed | remaining nits for F8: first-run hint 닫기 too faint; Home status bar shows only a dot |
| 2026-09-18 21:35 | F6 measured and fixed in the built exe | before/after medians (3 runs): Home 4334→2445 ms (target 2000; remainder WebView2), open 2877→679 ms (target 1500), hunk 139→19 ms (target 100; 소논문 has 0 fill seats so hunk used kstartup corpus), sidecar first JSONL 654→563 ms / RSS 26.7 MiB (target 1000). Tests 240. Smoke 570/0. |
| 2026-09-18 22:05 | F7 walk-through | flow: one edit needs 승인 요청 → 모두 승인 → 승인된 계획 적용 and shows two 승인 buttons at once → F8 makes it 승인하고 적용 (one primary, 승인만 as the split); seat pane still jargon (분류 채움 / 쓰기 전 확인 / 색 이상); recents truncate the file name; Home scrolls at 800 px; 기록 compare block raw; Settings is only the provider page; hint 닫기 faint; Home status bar dot without text. Note: the browser tool's synthetic Korean typing never fires compositionend, so Enter is held by the IME guard (correct behaviour, not a defect) |
