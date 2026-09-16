# Stage 4 GUI research: proven review and preview patterns for Rigorloom

**Scope.** Read-only survey of how mature editors handle preview, agent or reviewer edits, dual views, history, and CJK input, then a small Stage 4 UI slice list. The product constraint is Rigorloom’s existing Runtime CLI: sessions, typed `OperationPlan`s, human `approve`/`reject` bound to a plan hash, `apply` that publishes a candidate plus a last-write receipt, and gates that must not be bypassed by a prettier screen. Renderer and rematch work remain frozen (`docs/plans/cli-first-product-vision.md` §§4, 7; `docs/plans/rigorloom-master-execution-plan.md` §3). The Desktop shell already sketched in `docs/desktop-architecture.md` and `docs/desktop-code-map.md` must consume the same operations as `runtime/scripts/cli.py`, not invent a second document engine.

**How to read this note.** Each tool is scored on five axes: (a) document preview and live rendering, (b) review of proposed changes, (c) source versus rendered pairing, (d) history, undo, and versioning, (e) Korean or CJK IME where vendors documented it. Then: pattern, why it works, evidence, and what Rigorloom should actually borrow given receipts and gates.

---

## Rigorloom constraints that filter every borrow

The CLI already encodes the product’s trust model. `open` copies a source into a session. `inspect` / `read-region` expose addresses. `propose` builds a plan; `validate` and `plan` inspect it; `request-approval` opens a gate; `approve` and `reject` bind `--plan-hash`. `apply` publishes `candidates/<run>/` and writes `receipt` last. `compare` proves reversal or equality at named addresses. `verify` re-runs offline checkers fail-closed. `render` and `geometry` may honestly report `available: false`. `render-prepare` is a host-only Hancom convert. `events` is the session log. `module-check` reports findings; `--require-checks` is the caller who wants the gate in the exit code.

Vision §4 forbids a frontend that silently bypasses those gates or maintains divergent document semantics. Vision §7 puts a faithful frontend at M5, after a stable CLI contract, and states that renderer unfreeze needs a narrow, evidenced owner decision. Desktop architecture already says the shell owns consent, the Runtime owns receipts and containment, and COM is serialized machine-wide. Desktop code map already names the right surfaces: `ReviewQueue`, `ReceiptPanel`, `History`, `PagePreview` versus `TextView`, and composition refs that must survive layout switches.

Therefore: **do not borrow live incremental native rendering.** Do borrow **pending-until-hash-bound-approval**, **hunk-or-op granularity that still applies as one plan**, **honest unavailable preview**, **candidate timeline rather than in-file redlines as the source of truth**, and **IME composition that never races an agent apply**.

---

## 1. LibreOffice Writer

**Pattern.** Recorded redlines (`Edit → Track Changes → Record`) mark inserts, deletions, and usual formatting with author, date, and optional comments; Manage Changes accepts or rejects each recorded change. When reviewers forgot to record, **compare documents** opens the newer file, diffs against the older original, and *synthesizes* insertions and deletions, then the same accept/reject UI applies (`File → Compare Document` in 26.2+; previously under Track Changes). File → Versions stores named snapshots in the same file (open read-only, compare, delete). AutoRecovery and `.BAK` backups are crash/save insurance, not a review graph. Collabora Online later added a **side-by-side compare view** with hover highlighting of the same change on both tiles.

**Why it works.** Proofreading happens in the same visual language as the document. Compare-after-the-fact recovers provenance when tracking was never on. Versions keep the original bytes nearby without Git literacy.

**Evidence.** [Comparing versions](https://help.libreoffice.org/latest/en-US/text/shared/guide/redlining_doccompare.html); [Recording changes](https://help.libreoffice.org/latest/en-US/text/shared/guide/redlining_enter.html); [File → Versions](https://help.libreoffice.org/latest/en-US/text/shared/01/01190000.html); Writer Guide ch. 3; [Collabora compare view](https://vmiklos.hu/blog/cool-doc-compare.html). LibreOffice documents that **not all formatting changes are recorded** (example: tab-stop alignment).

**CJK.** Writer is a native CJK word processor; IME is the OS plus Hancom-like layout, not a documented web composition protocol. Borrow the *product* expectation (Hangul occupies space between neighbors during composition), not a Writer API.

**Borrow for Rigorloom.** Treat agent `propose` like an unrecorded reviewer: **compare session source (or parent candidate) to the would-be apply**, then accept/reject at **operation** granularity, not character redlines inside HWPX. Do not store versions inside the user’s original file (`open` already copies). Use `compare --region` the way Writer uses Manage Changes. Never pretend COM track-changes coverage exists until the Hancom catalog says so (vision §5 “Review tools”). Side-by-side from Collabora is the right *visual* for frozen-renderer Stage 4: left = `read-region` text, right = last `render` PNG **if** `available`, else an explicit unavailable card, not a fake live Writer.

---

## 2. Typst (typst.app and `typst watch`)

**Pattern.** Source on the left, compiled PDF/HTML preview on the right. The compiler is incremental (`comemo`); the app advertises millisecond compiles “as you type.” CLI `typst watch` recompiles on save. Diagnostics are first-class. Comments exist in the proprietary web app. Errors can **halt** preview; users report the illusion of live Docs-like editing breaking when the document is temporarily invalid.

**Why it works.** Preview is cheap, local, and the same artifact you will export. Incrementality is a language design constraint, not a UI trick.

**Evidence.** [typst.app](https://typst.app/); [GitHub README / watch](https://github.com/typst/typst); [open-source vs app](https://typst.app/open-source/); forum threads on preview pausing on errors.

**CJK.** Public compiler docs emphasize fonts and CJK via user-selected fonts; there is no special IME chapter comparable to VS Code. Hangul in Typst is ordinary Unicode in source.

**Borrow for Rigorloom.** Borrow **split source/preview layout** and **stale-preview honesty** (show compile time, hash, backend). Do **not** borrow keystroke-live COM. Map Typst’s compile button to `render-prepare` (host, serialized) plus `render --page`. If convert is frozen or busy, keep the last receipt-bound PNG and label it stale against current plan hash—the Typst “preview stopped” lesson, stated as a feature. Diagnostics map to `module-check` findings, not compiler logs invented in the shell.

---

## 3. Overleaf

**Pattern.** Code Editor versus Visual (rich text) Editor share one project; a PDF pane sits beside either. Recompile is explicit (with auto-compile as a setting). SyncTeX maps source ↔ PDF. Track Changes and comments work in both editors for entitled projects; **Reviewing mode** forces tracked edits and comments for Reviewer roles who cannot switch to Editing. Comments attach to selected source spans; resolve archives threads.

**Why it works.** Dual editors serve different literacies without forking the project. Reviewing mode is a **permission**, not a stylesheet. SyncTeX makes the PDF an index into source, not a screenshot gallery.

**Evidence.** [How do I use Overleaf](https://docs.overleaf.com/getting-started/how-do-i-use-overleaf.md); [layout](https://docs.overleaf.com/navigating-in-the-editor/working-with-the-pdf-viewer/editor-and-pdf-layout-and-sizing); [SyncTeX](https://docs.overleaf.com/navigating-in-the-editor/working-with-the-pdf-viewer/moving-between-the-editor-and-pdf.md); [Reviewing](https://www.overleaf.com/learn/how-to/Reviewing_and_reviewers_on_Overleaf); [comments](https://docs.overleaf.com/collaborating/commenting); [track changes](https://docs.overleaf.com/collaborating/track-changes); [rich text + review](https://www.overleaf.com/blog/the-updated-rich-text-editor-simplifies-team-collaboration).

**CJK.** XeLaTeX/LuaLaTeX + CJK packages; IME is the browser textarea. SyncTeX can fail on generated content (bibliographies)—a useful warning for HWP fields and captions.

**Borrow for Rigorloom.** Map Code Editor → `inspect` graph + region text; Visual Editor → later native/COM editing, not Stage 4. Map Reviewing mode → **agent-authority cannot `approve` or `plan/apply`** (already in runtime protocol / desktop map). Map SyncTeX → `geometry` addresses when available; until then, tree selection drives both panes. Map Recompile → host `render-prepare`. Do not ship a rich-text HWP editor that writes XML behind the Runtime.

---

## 4. Zed

**Pattern.** Agent edits surface as a **multibuffer**: every changed file’s hunks in one editable tab, keep/reject per hunk or globally. Optional `agent.single_file_review` inlines the same controls, temporarily overriding git diff. Split diffs (v0.224+) show base left / working copy right, aligned with spacer blocks, still one multibuffer. Provenance depends on the agent protocol: external ACP agents that bypass Zed’s filesystem APIs can produce **empty review UI** even though files changed.

**Why it works.** Review is a first-class buffer, not a chat attachment. Split diff scales because alignment is an editor primitive (block map). It fails when edit provenance is missing—the same failure Rigorloom would have if the GUI applied bytes the Runtime did not plan.

**Evidence.** [Agent Panel — reviewing changes](https://zed.dev/docs/ai/agent-panel.html); [Split diffs](https://zed.dev/blog/split-diffs); [empty ACP review](https://github.com/zed-industries/zed/issues/50142).

**CJK.** Not a documented differentiator; GPUI text layout plus OS IME.

**Borrow for Rigorloom.** One **Review multibuffer of plan operations** (not files): each op is a hunk (`set_cell`, `replace_all`, `insert_text`, …) with before/after from `read-region` / parent run. Keep/reject per op **rebuilds the plan and invalidates the previous plan-hash** (Zed keep is local; Rigorloom must `propose` again or subset then `request-approval`). Refuse to show a review surface unless the plan id, hash, and session match—Zed’s ACP empty-diff bug as a product rule. Split view: left = before text at address, right = proposed text; rendered PNG is a third pane, not a fake hunk.

---

## 5. Visual Studio Code

**Pattern.** Inline Chat (`Ctrl+I`) shows a scoped diff with Keep/Undo. Agent sessions mark edits **pending** after save; explorer dots; overlay Keep/Undo; hover for **per-hunk** accept/reject; multi-file diff with Inline / Side by Side / Automatic. Staging in SCM can auto-accept pending edits. Optional auto-accept delay. Checkpoints restore workspace *and* (in some flows) conversation. Hunk widgets refuse accept if the model `versionId` drifted—stale-target detection.

**Why it works.** Pending is a first-class file state. Granularity matches how humans actually review. Auto-accept is opt-in and documented as a security hazard.

**Evidence.** [Inline chat](https://code.visualstudio.com/docs/chat/inline-chat); [Review agent changes](https://code.visualstudio.com/docs/copilot/review-code-edits) / [agents path](https://code.visualstudio.com/docs/agents/run/review-code-edits); [reviewing foundations](https://code.visualstudio.com/learn/foundations/reviewing-and-controlling-agent-changes); hunk `versionId` guard in `chatEditingCodeEditorIntegration.ts`.

**CJK.** VS Code invested early in Korean IME: composition letters occupy space between neighbors (Word-like, not overlay-like Japanese Notepad); zero-size textarea breaks Korean IME; `compositionstart/update/end` must not clear the textarea in ways that drop `compositionend`. IME smoke tests are part of editor changes ([PR #5615](https://github.com/microsoft/vscode/pull/5615); wiki IME Test). Desktop map already stores composition refs outside remounts—this is the same rule.

**Borrow for Rigorloom.** Pending = approval state `pending`, not “bytes already in the original.” Per-hunk Keep maps to **dropping ops from a draft plan**, then a new hash. The `versionId` check maps to **stale targets / plan-hash mismatch** on `approve`. Auto-accept maps to existing `auto_approved` **only** where policy already allows it—never a GUI timer that skips `request-approval`. IME: freeze ReviewQueue apply and agent `propose` while composition is active (`docs/plans/rigorloom-release-product-brand-plan.md` IME list).

---

## 6. Obsidian

**Pattern.** Three states: Reading (`mode: preview`), Live Preview (`mode: source`, `source: false`), Source (`mode: source`, `source: true`). Live Preview hides markup except at the caret. Ctrl/Cmd-click the view switcher opens **Editing and Reading side by side**. Rendering is the same Markdown pipeline, cheap enough to be live.

**Why it works.** Modes are explicit, API-visible, and cheap. Side-by-side is an opt-in, not the default tax.

**Evidence.** [Views and editing](https://obsidian.md/help/edit-and-read); [Live Preview announcement](https://obsidian.md/blog/live-preview-update/); forum `getState`/`setState` notes.

**CJK.** Markdown Unicode; IME is CodeMirror’s. Live Preview can hide syntax that CJK authors still need (ruby, raw HTML)—a warning against hiding HWP control characters.

**Borrow for Rigorloom.** Three honest modes: **structure/source text**, **WYSIWYG-ish region editor (later)**, **page image**. Default Stage 4: source text + optional page image, like Obsidian’s Ctrl-click split—not Live Preview of HWP XML. Do not hide `forbidden` form anchors in a “pretty” view; `inspect --include forbidden` is a gate input.

---

## 7. Extra: Cursor (agent Keep/Undo, checkpoints)

**Pattern.** Editor Window: inline red/green diffs, per-file and per-hunk Keep/Undo, Keep All / Undo All, Review banner. Agents Window: file-level review, weaker hunk UI; Inline Diffs off implies **auto-keep to disk**. Checkpoints snapshot files before significant agent edits; restore reverts files, not chat. Separate **Agent Review** (`/agent-review`) is a *second model* judging the diff, not the Keep/Undo widget.

**Why it works when it works.** Review sits on the artifact the user already has open. Checkpoints beat Git for “undo the last agent turn.” It fails when the product ships two windows with two review semantics.

**Evidence.** [Agent overview / checkpoints](https://cursor.com/docs/agent/overview); [Agent Review](https://cursor.com/docs/agent/agent-review); forum threads on Inline Diffs vs Agents Window (e.g. [165428](https://forum.cursor.com/t/inline-review-feature-with-keep-revert-missing-since-recent-updates/165428)).

**Borrow for Rigorloom.** One review surface (desktop map: ReviewQueue in both Document and Agent layouts). Never auto-keep to the user original. Checkpoints = **candidate chain** (`--base-run`, `--reverses-run`) plus `events`, not a silent file snapshot outside receipts. Do not confuse “second model review” with the human gate.

---

## 8. Extra: GitHub pull request review (and Google Docs Suggesting, briefly)

**GitHub pattern.** Files changed: unified or split diff, line and range comments, `suggestion` fences the author can **Commit suggestion** or batch. Review submits Comment / Approve / Request changes as a single decision over the whole PR. Suggestions only on **open** PRs; merged/closed freeze the apply button. Comments bind `commit_id` + path + line.

**Why it works.** Discussion is attached to a frozen SHA. Approve is not the same as merge. Suggestions are typed patches, not vibes.

**Evidence.** [Commenting on a PR](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/commenting-on-a-pull-request); [Incorporating feedback](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-feedback-in-your-pull-request); [Reviewing proposed changes](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/reviewing-proposed-changes-in-a-pull-request).

**Google Docs Suggesting (second extra, compressed).** Editing / Suggesting / Viewing modes. Suggestions are margin cards with Accept/Reject; Tools → Review suggested edits can preview accept-all / reject-all. API `SuggestionsViewMode` can fetch document **as if** all accepted or all rejected. Comments ≠ suggestions.

**Evidence.** [Suggest edits](https://support.google.com/docs/answer/6033474); [Docs API suggestions](https://developers.google.com/workspace/docs/api/how-tos/suggestions).

**Borrow for Rigorloom.** GitHub: `approve` binds plan hash like a review on a commit; `apply` is merge. Comments can live on region addresses without mutating HWP. Frozen/merged PR = already-applied candidate: edit by new plan, not by mutating the receipt. Docs: Viewing mode = preview candidate as if applied (`read-region --run`) versus source; Accept all = one `approve` of the whole plan, not a loop that applies ops without a receipt. Preview-without-suggestions = `--require-equal` compare after reject.

---

## Cross-cutting synthesis

| Axis | What actually transfers | What does not |
| --- | --- | --- |
| Preview | Overleaf Recompile + Typst stale-hash label + honest unavailable | Typst/Obsidian keystroke-live native HWP |
| Review | Zed/VS Code hunk keep; GitHub hash-bound approve; LO compare-after-fact | In-document redlines as source of truth; Cursor auto-keep |
| Dual view | Overleaf split + SyncTeX-like `geometry`; Obsidian opt-in split | Rich-text Visual Editor of HWP in Stage 4 |
| History | Candidate DAG + events + reverse plans; LO Versions as *named* receipts | Embedding versions in the user’s original |
| IME | VS Code composition occupancy + freeze concurrent apply | Assuming browser textarea is “good enough” without tests |

**Provenance.** Every reviewed hunk should display: session id, plan id, plan hash, proposer, backend, parent `run`, addresses, and whether a receipt already exists. That is GitHub `commit_id` plus LibreOffice author tooltip plus Rigorloom `receipt`.

**Gates.** UI buttons are aliases: Approve → `approve --plan --plan-hash`; Apply → `apply`; Check → `module-check` / `verify`; Compare → `compare`. Exit code 3 and `acceptance: false` must remain visible as refused, not restyled as success.

---

## Stage 4 UI slice list (at most five, value per effort)

Ordered for a frozen renderer, existing Tauri layouts, and CLI parity. Each slice is a visualization of commands that already exist.

### 1. Plan review queue (highest value / effort)

**Visualizes:** `propose`, `validate`, `plan`, `request-approval`, `approval`, `approve`, `reject`.

Show the pending plan as a multibuffer of operations with before/after from `read-region` (and `--run` of `--base-run` when chained). Per-op Keep/Reject **edits a draft and requires a new `propose`** so hash binding stays honest; Accept-all / Reject-all call `approve` / `reject` with the displayed hash. Agent layout’s button is the same host action (`docs/desktop-code-map.md`). Skip COM. This is the product: agents propose, humans bind a hash.

### 2. Receipt, verify, and compare inspector

**Visualizes:** `receipt`, `verify`, `compare`, `candidates`.

After apply, a panel that re-reads the receipt (refuse on byte drift), lists candidate hashes, and runs address compares against source or another run. Surface residue/`acceptance: false` as a finding, not a green check. Maps GitHub “files changed + SHA” and LO Compare onto the receipt-last rule. Low extra backend cost.

### 3. Honest page preview (no renderer unfreeze)

**Visualizes:** `render`, `render-prepare`, `geometry` (optional).

PagePreview already in the code map: request a PNG; if `available: false`, show the JSON reason and last good image with its run id. Host-only `render-prepare` behind an explicit button, never on each keystroke. Sync selection via inspect tree until geometry exists. Typst/Overleaf layout without Typst latency claims.

### 4. Structure tree and region source

**Visualizes:** `inspect`, `read-region`.

Left pane: graph, editable versus `forbidden` regions. Centre: exact text/runs for the selection. This is Obsidian Source + Overleaf Code Editor, cheap and unfrozen. It makes slice 1’s hunks navigable and prevents “pretty” views from hiding form anchors the residue checker still sees.

### 5. Session history and reverse

**Visualizes:** `events`, `candidates`, `propose --reverses-run`, `compare`.

Timeline of protocol events and published runs; restore is **propose a reverse plan**, approve, apply—not in-place undo of the original. Cursor checkpoints without lying about Git. Completes recovery UX the master plan lists for M5, using only existing CLI.

**Deferred (on purpose).** Live COM preview, rich-text HWP IME editor, Overleaf-style comments stored in the document, LibreOffice-in-process track changes, second-model Agent Review. Those wait on unfreeze, catalog coverage, and IME evidence.

---

## Recommended default Stage 4 screen

Reuse DocumentView: StructureTree (slice 4) | TextView + optional PagePreview (slices 4 and 3) | ReviewQueue + ReceiptPanel + History (slices 1, 2, 5). VerificationBar stays shared. Settings stay outside the switch. No new document semantics.

**Acceptance sketch (not a freeze lift).** Same plan JSON from GUI and CLI; rejected hash cannot apply; receipt drift is an error; render unavailable is exit 0 unless `--require-render`; Korean composition in region text does not submit approve/apply mid-syllable. That is enough GUI to make the receipt-and-gate model visible without inventing a renderer.
