# Stage 4b — desktop design research (R0)

Read-only note. Tokens in `desktop/src/styles.css` stay. Problem is IA, hierarchy, and polish. Maps: `docs/desktop-code-map.md`, `docs/plans/stage4-gui.md`. Current shell: `DocumentView` (StructureTree | TextView/PagePreview | ContextPanel stacked) plus a separate `AgentView`; `VerificationBar` is a chip strip of process facts.

## 1. Pattern catalog

**P1. Document is the only hero (AFFiNE, Obsidian, Typst web).** Shell is left nav + centre canvas + one right inspector. Secondary work never replaces the document. Screens: [affine.pro](https://affine.pro/), [Typst export/preview](https://typst.app/docs/web-app/export-and-preview/).  
*Use:* Drop the Document/Agent view swap in `App.tsx`. Keep the HWPX surface in `DocumentView` centre.

**P2. Right inspector is tabs, not a stack (AFFiNE `ViewSidebarTab`, Obsidian sidebar).** One tab visible: properties, outline, comments, or AI chat. Collapse the whole rail; do not stack chat under properties. [AFFiNE detail page](https://deepwiki.com/toeverything/affine/2.3.2-document-editor-and-detail-pages), [Obsidian sidebar](https://obsidian.md/help/sidebar).  
*Use:* `ContextPanel` becomes tabs 선택 / 검토 / 기록 / 에이전트.

**P3. Left rail collapses to icons and persists width (Yaak, AFFiNE).** CSS Grid + `SplitLayout`; width and hidden flags live in settings. [Yaak workspace layout](https://deepwiki.com/mountain-loop/yaak/2.1-workspace-layout-and-navigation), [AFFiNE root sidebar](https://deepwiki.com/toeverything/AFFiNE/2.3.1-root-application-sidebar).  
*Use:* Collapse `StructureTree` so the paper can go full width; persist via existing prefs IPC.

**P4. Empty body is a hotkey primer, not a paragraph (Yaak).** No selection → `HotkeyList` (open, send, shortcuts). Changelog: [hotkey hints on empty states](https://yaak.app/changelog/2024.1.0).  
*Use:* Replace `.empty` copy in `ContextPanel`, `ReviewQueue`, `History`, tree with one action + one shortcut.

**P5. Recents belong on the home surface (Yaak, GitButler).** Home is a designed first screen; workspaces/recents are first-class, not an afterthought under a live document. [GitButler setup](https://docs.gitbutler.com/guide).  
*Use:* Promote `Welcome.tsx` to a real home when `inspect` is null: drop zone, recents cards (name, time — hide sha in the row), Ctrl+O.

**P6. Hunk review is click-to-include, not a wall of facts (GitButler).** Unassigned changes vs branch lanes; files/hunks/lines assigned with one click; preview can go fullscreen. [Desktop overview](https://docs.gitbutler.com/overview), [0.15 layout](https://blog.gitbutler.com/gitbutler-15-quirky-quinceanera).  
*Use:* `ReviewQueue` hunks: before/after + 승인/거절. Provenance (plan hash, parent run, proposer) behind a disclosure, not the first line.

**P7. Review stays in the document (Zed Project Diff / agent diff).** Diff is a centre multibuffer: keep/reject per hunk, stage-and-next, split or unified. Chrome stays the editor. [Zed Git](https://zed.dev/docs/git.md), [zed.dev/git](https://zed.dev/git).  
*Use:* Selecting a queue op should scroll/highlight the seat in `TextView`/`PagePreview`. Do not send the human to `AgentView` to approve.

**P8. Command palette is the overflow (Zed).** Cmd/Ctrl-Shift-P holds Git and agent actions so the toolbar stays short. [Zed features](https://zed.dev/features).  
*Use:* Park 런타임 재시작, 검사 실행, 비교, 내보내기, 스모크 behind a palette; `EditorToolbar` keeps 열기 / 본문·페이지 / 승인 요청.

**P9. Preview is on demand and labelled by source (Typst, Overleaf — already in stage4-gui).** Official Typst app live-previews, but View can hide editor or preview, pop out, and Quick export sits on the preview chrome. rigorloom already forbids per-keystroke render.  
*Use:* Keep G3: button + run/source label + stale banner. Hide preview until asked; never look like live type-and-see.

**P10. Status bar shows four human facts; details click open (Obsidian).** Status bar is bottom-right, context-sensitive (mode, counts). Extra metrics open on click. [Obsidian workspace](https://obsidianmd-obsidian-help.mintlify.app/ui/workspace), [word-count click → modal](https://github.com/banisterious/obsidian-custom-selected-word-count). Tabular numerals so the bar does not jitter ([forum](https://forum.obsidian.md/t/word-count-adds-distracting-motion-to-status-bar/18253)).  
*Use:* `VerificationBar` visible: 위치, 원본/후보본 (short hash), 검사, 연결. Click → popover for pid, 자식 정리, 렌더 증명 없음, 지면 출처.

**P11. AI lives in the inspector, document stays (AFFiNE chat tab).** Chat is a sidebar tab; document does not unmount. Toggle tooltips Open/Close sidebar. [chat.tsx](https://github.com/toeverything/AFFiNE/blob/9c55edeb/packages/frontend/core/src/desktop/pages/workspace/detail-page/tabs/chat.tsx).  
*Use:* Merge `AgentView` conversation + `Composer` into inspector tab 에이전트. `SessionList`/`TaskPacks` as overflow, not a second layout.

**P12. Korean UI verbs name the next action (Toss TDS).** Buttons: 확인/취소 defaults, but consumer guide prefers 닫기 over 취소 when work is not discarded; CTA must say the outcome. [useDialog](https://tossmini-docs.toss.im/tds-mobile/hooks/OverlayExtension/use-dialog/), [Apps in Toss UX](https://developers-apps-in-toss.toss.im/design/consumer-ux-guide).  
*Use:* 승인하고 적용, 이 자리만 거절, 문서 열기 — not 확인 for apply.

**P13. Hangul density: zero tracking, 4–8–12 rhythm (Pretendard, W3C klreq, Naver-like spacing).** Pretendard is built so you do not add letter-spacing. [Pretendard README](https://github.com/orioncactus/pretendard/blob/main/packages/pretendard/docs/en/README.md). Hangul default inter-character space is zero ([klreq](https://w3c.github.io/klreq/new.html)). Compact Korean products cluster 4/8/12/16px ([Naver tokens survey](https://oh-my-design.kr/design-systems/naver)).  
*Use:* Drop `letter-spacing: 0.07em` / `0.06em` on UI labels in `styles.css`. Keep line-height ≥1.5 on Korean body; chips get padding, not tracking.

**P14. Tauri: one webview, custom chrome, persist split (GitButler, Yaak).** UI is web; disk/process in Rust. Split libraries (`react-resizable-panels` analog) + settings atoms.  
*Use:* Do not add a second window for Agent. Persist rail widths in prefs already used for recents.

**P15. Designed empty + loading, never raw prose (Yaak, GitButler blank workspace).** Loading is a short progress line; empty is illustration + primary button.  
*Use:* Tree loading already has a sentence — replace with a skeleton matching StructureTree rows. Queue empty: “칸을 눌러 값을 넣으면 검토 목록이 생깁니다” + pointer to the centre.

**P16. One primary action per hunk (Zed stage-and-next, GitButler commit).** Keyboard: accept this, jump next.  
*Use:* `ReviewQueue` 이 항목 승인 (IME-inert, already G1) as the only filled button; 모두 승인 secondary.

## 2. Proposed information architecture

**Home** (`Welcome`): mark, one lede, 문서 열기, recents. No verify bar chips, no empty tree, no empty inspector.

**Workspace (one layout):**

```
[ 구조 레일 ] [ 문서 (본문 | 페이지) ] [ 검사기 탭 ]
                 EditorToolbar
footer: 위치 · 원본/후보본 · 검사 · 연결   [⋯ 자세히]
```

- **Left — 구조:** collapsible `StructureTree`. Counts stay in the head. Forbidden rows stay read-only (G4).
- **Centre — 문서:** hero. Toolbar: 열기, 본문/페이지, 미리보기 만들기, 승인 요청. Caveat stays one quiet line (not a banner competing with the paper).
- **Right — 검사기 tabs:**
  - **선택** — current cell/para, region source, 값 넣기.
  - **검토** — `ReviewQueue` only. Default when `draft.ops.length > 0`.
  - **기록** — `History` + receipt entry points. Keep 영수증 wording.
  - **에이전트** — `Conversation` + `Composer`. Approvals still only in 검토 (agent host still cannot `approval/resolve`).
- **Status:** at most four facts. Popover: hashes, pid, job confine, render proof-grade none, geometry source, overlay pick.
- **Modals unchanged in role:** `Findings`, `ReceiptPanel`, `Settings`.

`setView('agent')` goes away as a layout. Store fields for conversation remain; only the mount point changes.

## 3. Glossary (chrome only; CLI/JSON keys unchanged)

| Current | User label | Tooltip |
| --- | --- | --- |
| 렌더 증명 | 그림 증명 | 페이지 그림은 보여줄 수 있어도 증거가 아닙니다. 런타임은 모든 렌더에 증명 없음(structural_only)을 붙입니다. |
| 제출 검사 | 적용 시 검사 | 후보본을 만들 때 돌린 검사입니다. 지금 다시 돌리는 버튼은 없습니다. |
| 채움 자리 | 입력 칸 | 값을 넣도록 열린 칸입니다. 승인 전에는 파일이 바뀌지 않습니다. |
| 서식 검사 | 서식 점검 | 색·글꼴 등 서식 이상을 읽습니다. 제출용 검사가 아닙니다. |
| 런타임 pid | 엔진 | 문서 엔진 연결 상태입니다. 프로세스 번호는 자세히에서 봅니다. |
| 자식 정리 | 종료 시 정리 | 창이 강제 종료돼도 엔진 자식 프로세스를 함께 끝낼 수 있는지입니다. |
| 후보본 | 후보본 | 승인·적용 후 생긴 사본입니다. 원본 파일은 그대로입니다. |
| 원본 | 원본 | 연 파일의 해시입니다. 이 앱은 원본을 고치지 않습니다. |

Keep **영수증**. Do not relabel it as 렌더 증명. Keep **원본/후보본** in the bar; they are the product promise.

Other chrome: 대기 → 검토 대기; 지면 출처 → 자세히; 삽입/수정 없음 → hide unless a caret is open.

## 4. Top ten fixes (impact / effort)

1. **Fix `[object Object]`** — likely a React child that is a nested object (status/error/classification) rather than a string. Hunt in `ContextPanel.tsx` header count, `PageOverlay.tsx` classification, `Timeline.tsx` `event.kind`, toolbar summaries. One-line `String()`/`label` map. **Tiny / huge trust.**
2. **Tab the right column** — `ContextPanel.tsx` (+ `ReviewQueue.tsx`, `History.tsx`, mount `Composer.tsx`/`Conversation.tsx`). Stops the “everything visible” wall. **Medium / high.**
3. **Cut `VerificationBar.tsx` to four items + popover.** Move pid, 자식 정리, 렌더 증명, 채움 자리 count, 지면 출처. `font-variant-numeric: tabular-nums`. **Medium / high.**
4. **Retire `AgentView.tsx` as a full-screen layout** — `App.tsx` view switch. Agent tab in inspector. **Medium / high (tests that click `view-agent` need new testids).**
5. **Queue empty + hunk chrome** — `ReviewQueue.tsx`: designed empty; provenance in `<details>`. **Small / high.**
6. **Welcome as home** — `Welcome.tsx` + `DocumentView.tsx`: hide empty tree/inspector until a file is open; recents without leading hash. **Small / medium.**
7. **Collapse left rail** — `DocumentView.tsx` / `StructureTree.tsx` + prefs. **Medium / medium.**
8. **Korean type polish** — `styles.css`: kill wide letter-spacing on Hangul UI; empty states not `p.empty` walls. **Small / medium.**
9. **Glossary pass** — labels in `VerificationBar.tsx`, `EditorToolbar.tsx`, `DocumentContext.tsx`, tree “채움 자리” heading. Tooltips keep the honest contract. **Small / medium.**
10. **Command palette / overflow** — new small component; move rare actions out of the bar. `EditorToolbar.tsx`. **Larger / medium (do after 3–4).**

Out of scope here: renderer claims, new Runtime verbs, color retokenizing.

## Sources (primary)

- GitButler: https://docs.gitbutler.com/overview · https://blog.gitbutler.com/gitbutler-15-quirky-quinceanera · https://github.com/gitbutlerapp/gitbutler  
- Yaak: https://deepwiki.com/mountain-loop/yaak/2.1-workspace-layout-and-navigation · https://yaak.app/changelog/2024.1.0  
- AFFiNE: https://affine.pro/ · https://deepwiki.com/toeverything/affine/2.3.2-document-editor-and-detail-pages  
- Zed: https://zed.dev/docs/git.md · https://zed.dev/features  
- Obsidian: https://obsidian.md/help/sidebar · https://obsidianmd-obsidian-help.mintlify.app/ui/workspace  
- Typst: https://typst.app/docs/web-app/export-and-preview/  
- Korean type/UX: https://github.com/orioncactus/pretendard · https://w3c.github.io/klreq/new.html · https://tossmini-docs.toss.im/tds-mobile/hooks/OverlayExtension/use-dialog/ · https://developers-apps-in-toss.toss.im/design/consumer-ux-guide  
