# desktop/ — Rigorloom Desktop, Phase 4 verified editing

Tauri 2 + React/TS shell over the real Runtime as a packaged Python sidecar.

**A person can now change a document here, and prove what changed.** Click a
채움 자리, type, and the value joins one OperationPlan; the Runtime says what is
wrong with it before anything is written; a human resolves an approval bound to
that exact plan hash; the plan applies to the session COPY and produces a
candidate with its own sha256 beside an unmoved source hash; the receipt binds
both. Nothing on that path is optimistic — every refusal the protocol declares
has a drawn state, and the two things the application cannot do (re-run the
checkers on demand, prove a render) still say so in as many words.

Phase 3's read-only foundation and the design slice are still here and still
true; what follows marks what Phase 4 changed.

Shell decision, the measurements behind it, and the obligations it imposes:
`docs/desktop-shell-spike.md` (branch `claude/desktop-shell-spike`), `## Decision`.
Protocol: `docs/runtime-protocol-v0.md`. Product shape: `docs/product-direction.md` §4.

---

## Layout

| Path | Owns |
| --- | --- |
| `src-tauri/src/main.rs` | window, commands, the panic hook, prefs wiring |
| `src-tauri/src/sidecar.rs` | **all** protocol I/O — spawn, JSONL, request correlation, batching |
| `src-tauri/src/jobkill.rs` | kill-on-close job object, ported from the spike |
| `src-tauri/src/prefs.rs` | the three things the shell remembers between launches |
| `sidecar/rigorloomd.py` | frozen entry: serves the protocol, and stands in for the interpreter |
| `sidecar/deps.py` | derives the frozen build's hidden imports from the engine's own sources |
| `sidecar/build.ps1` | PyInstaller one-dir against a pinned CPython 3.12.10 |
| `src-tauri/src/digest.rs` | vendored SHA-256, so an export can be hashed without a dependency |
| `src/store.ts` | **the one Workspace** both views project |
| `src/actions.ts` | every operation, as plain functions, so the smoke drives the real path |
| `src/runtime.ts` | thin invoke wrappers and event subscriptions |
| `src/views/` | `DocumentView`, `AgentView` — layouts, no state |
| `src/components/` | tree, text view, panels, verification bar, findings, timeline, composer, logo, splash, **review queue, receipt panel** |
| `src/assets/` | `logo.svg` (drawing of record) and the bundled Pretendard + `OFL.txt` |
| `src/devMock.ts` + `src/fixtures/` | browser-mode replay of a recorded real session; `import.meta.env.DEV` only, absent from production bundles |
| `src/smoke.ts` | the scripted checks, run inside the built app |
| `scripts/` | build, smoke, screenshots, window capture, fixture recorder |

### Keyboard

`Ctrl+O` open · `Ctrl+1` / `Ctrl+2` views · `Ctrl+=` / `Ctrl+-` / `Ctrl+0` app
zoom (50–200 %, persisted, announced as a toast) · `Ctrl+C` copies the selected
cell or paragraph when there is no text selection to copy instead. Dropping a
`.hwpx` on the window opens it; anything else is refused out loud.

Inside a fill seat: `Enter` commits, `Esc` cancels. Every app-level shortcut
returns early when the event target is a text field — a shortcut that reached
past a field the user is typing in would eat a `Ctrl+C` and, worse, could throw
away a composing syllable.

## Running it

```powershell
# from clean: npm install -> sidecar -> vite -> tauri build, exit codes recorded
powershell -ExecutionPolicy Bypass -File desktop/scripts/build-clean.ps1
powershell -ExecutionPolicy Bypass -File desktop/scripts/build-clean.ps1 -Fresh

# evidence
powershell -ExecutionPolicy Bypass -File desktop/scripts/smoke.ps1
powershell -ExecutionPolicy Bypass -File desktop/scripts/smoke.ps1 -Only edit
powershell -ExecutionPolicy Bypass -File desktop/scripts/screenshots.ps1
# NOT headless: SendInput goes to the foreground window. Run it with the
# console in front and do not touch the mouse while it types.
powershell -ExecutionPolicy Bypass -File desktop/scripts/ime.ps1

# development (runs the interpreter directly; no freeze needed)
cd desktop && npm run tauri dev
```

`npm run tauri build`, not `cargo build --release`. `tauri-build` emits
`cargo:rustc-cfg=dev` for a bare cargo invocation, so the binary points at the
Vite dev server and shows `ERR_CONNECTION_REFUSED` when launched standalone.

Dev mode spawns `python runtime/scripts/serve.py`; set `RIGORLOOM_PYTHON` to
choose the interpreter. The UI reports which mode is live (`패키지` / `개발`) in
the verification bar, because "works on my machine" is usually this.

---

## The sidecar is the real Runtime, and freezing it took one trick

`runtime/scripts/rt_engine.py:192` spawns its engine children as

```py
[sys.executable, "<engine-root>/engine/scripts/form_inspect.py", ...]
```

Under PyInstaller `sys.executable` is the frozen executable. Left alone,
`document/inspect` would recursively launch a second protocol server and hang
forever.

`sidecar/rigorloomd.py` therefore has two jobs, chosen by whether `argv[1]` ends
in `.py`. With a `.py` first argument it behaves exactly like `python script.py
…` — puts the script's directory on `sys.path` (what CPython does for a script
invocation, and what `from cli_io import utf8_stdio` depends on) and runs it as
`__main__`. Otherwise it serves the protocol. This works because the three
scripts the Runtime spawns import only the standard library plus their repo
siblings.

Two consequences worth knowing before touching the build:

- **The engine scripts ship as data, so PyInstaller cannot see their imports.**
  The first build froze cleanly, answered `initialize`, and died on
  `document/inspect` with `ModuleNotFoundError: No module named 'xml'`.
  `sidecar/deps.py` walks the repo-local dependency closure of the three
  entrypoints with the AST and prints the external top-level imports;
  `build.ps1` passes each as `--hidden-import`. A new engine import cannot
  silently break the packaged build.
- **`build.ps1` exercises both roles before it declares success** — a real
  `initialize` handshake over stdio, and `form_inspect.py --help` as a child.

`--onedir`, per spike finding 3: ready in 264 ms against 1394 ms for one-file,
which self-extracts on every launch. `--noconsole`, so no `conhost.exe` joins
the process tree — which is precisely the configuration that orphans on a hard
kill, and precisely why `jobkill.rs` is not optional.

Interpreter pinned to CPython **3.12.10** at
`%LOCALAPPDATA%\Programs\Python\Python312`. `C:\Python313` is a partial install
that cannot create a venv, and the PATH default is a Microsoft Store build
PyInstaller cannot freeze from. Override with `RIGORLOOM_SIDECAR_PYTHON`.

## What the shell owes the spike

| Obligation | Where |
| --- | --- |
| Job-object-confine every child | `jobkill.rs`, called in `Sidecar::spawn` before anything else can fail; the outcome is reported in the verification bar, never assumed |
| One-dir under `bundle.resources` | `sidecar/build.ps1`, `tauri.conf.json` |
| Batch before crossing IPC | `sidecar.rs` — notifications and stderr go into `pending_out` and leave on a 100 ms timer as arrays |
| `--noconsole`, no conhost | `build.ps1`, plus `CREATE_NO_WINDOW` on the spawn |
| A designed loading state | `App.tsx` `<Boot>`; ~1.5 s to first usable paint is measured, so it has words in it |
| Answer M17 | `panic = "abort"` dropped from `Cargo.toml`; a panic hook writes `crash.log` and emits `runtime://panic`. `ErrorBoundary` is the same obligation on the webview side |
| Native dialogs, no localhost | `@tauri-apps/plugin-dialog`; the capability set is `core:default` + `dialog:default` and nothing else |

---

## Information architecture

One `Workspace` object, two projections. `store.ts` holds `view` as one field
beside `selection`, `expanded`, `page`, `zoom`, `sessions`, `inspects`,
`candidates` and `activity`; `setView` writes only `view`. The views and their
components hold **no state at all**, so a view switch has nothing to lose —
the property is structural, not a discipline. `sharedStateSignature()` states it
once, in the store, and the smoke asserts the signature is byte-identical across
a round trip.

**Document view** — structure tree · page surface · selection context ·
verification bar.

**Agent view** — open documents · timeline and composer · document context ·
the same verification bar component with the same props, because proof state has
one home and must read identically wherever the user is standing.

Every row in the structure tree has a producer in the `document/inspect`
response. Nothing is inferred:

| Row | Source |
| --- | --- |
| 구역 / 문단 | `graph.paragraphs[]` — `section`, `at_para`, `text` |
| 표 / 칸 | `graph.tables[].cells[]` — `addr`, `classification`, `textPreview` |
| 채움 자리 | `regions.regions[]` with their T30/T127 preflight |
| 안내문 | cells classified `guide` |
| 이 빌드가 보지 못하는 것 | `capabilities.backends` + `capabilities.unavailable` |

That last group is the honest answer to "unsupported structures". The Runtime
does not enumerate what it failed to parse, so the panel reports what this build
cannot **reach** and says so in as many words, rather than implying the document
has no such structures.

### Honesty rules the UI keeps

- **No fabricated page.** There is a renderer now, and the rule did not
  change — it just has more branches. When a raster exists it is the real one,
  labelled with the digest and dpi it came from. When one does not, the centre
  quotes the runtime's own `unavailable.reason` and `detail` verbatim, switches
  on the closed reason set rather than matching on prose, and draws
  `summary.pageMetrics` — real numbers, to scale, captioned `PAGE GEOMETRY` so
  it cannot be mistaken for a render of the content. A `renderPrepare` refusal
  gets the same treatment: the runtime's message first, what a person can do
  about it second, the converter's exit code and stderr tail behind a
  disclosure, and no page drawn either way.
- **Proof state appears in exactly one place**, the verification bar, and reads
  `증명 없음` / `실행 안 함` rather than a neutral dash that could be read as
  fine.
- **Colour never carries meaning alone.** Every semantic tone ships with its
  word.
- **Absence is not failure**, and neither is undecidable: a region whose
  `colorAnomaly` key is omitted renders `판단 불가`, not `없음`.
- **The composer is present and disabled**, with a sentence saying there is
  nowhere to send anything yet. A composer that accepted text and dropped it
  would be worse than none. Phase 4 deliberately did NOT enable it: the mock
  agent proposes through its own door and its plan lands in the review queue,
  but there is still no conversational agent to send an instruction to, and
  wiring the box to the mock would be staging a product that does not exist.
- **The agent's proposal is marked as the agent's**, in the queue, per op.
  A user's edit and an agent's proposal pass the same gate, which is the
  claim — and a reviewer must be able to see which is which without asking,
  or the claim is unverifiable by the person doing the approving. Editing an
  agent's op re-proposes the plan as the shell's own and says so, because the
  agent's approval record binds a hash that no longer exists.

---

## Design language

Tokens live at the top of `src/styles.css`. The identity is **paper, not web**.

**Brand.** The mark is a plain weave: two warps and two wefts crossing four
times, one strand broken at each crossing so the eye reads over-and-under rather
than a grid, with a leg falling from the bottom-right knot to lean it toward R.
R-adjacency is in the silhouette, not in drawing a letter. `src/assets/logo.svg`
is the drawing of record and carries the geometry rationale — why terminals sit
at 4 and 28 on a 32 grid (round caps add half the stroke), why the crossing gaps
are 5.5 (the narrowest that still reads as an interlace at 16 px).
`src/components/Logo.tsx` mirrors it inline so it can inherit `currentColor` and
be animated. The Tauri icon set is generated from it. The wordmark is **Latin
"Rigorloom"**, and the window title matches; there is no 리고룸 in the chrome.

**Typography — Pretendard Variable, bundled.** `src/assets/fonts/`, with
`OFL.txt` beside it. This closes the spike's open question 8: Pretendard is SIL
OFL 1.1, which permits redistribution provided the licence travels with the
font, and it does — into the repository and into the installer. Bundling is what
makes the product look the same on every machine. The fallbacks below it only
matter if it fails to load, and the first of them, 맑은 고딕, ships
Semilight/Regular/Bold and cannot express a hierarchy — the reason a
`system-ui` Korean app reads flat.

Body 13–14 px at `line-height: 1.6`, document body 1.75, headings 1.3, because
Hangul glyphs fill their em box and Latin-tuned 1.4–1.5 crowds them. Weight
carries hierarchy (400 / 500 / 600), never 700+ for Korean UI text. **Hangul is
never letter-spaced**; the one tracked class, `.latin-caps`, is Latin-only by
construction. Evidence — hashes, addresses, exit codes — is `Consolas` with
tabular figures. No second webfont for numbers.

**Colour — warm hanji neutrals.** Surfaces `#F1EEE8` app / `#FAF8F4` panel /
`#FEFDFB` paper; ink `#1C1E21`; hairlines `#E4E0D8`. **No pure `#FFF`
anywhere.** A dark ink strip across the top carries the mark and the wordmark,
and that one element does most of the work of making this stop looking like a
page.

Two signal colours, and the discipline is the point:

- **`#0F766E` deep teal** is the *working* accent — interactive affordance,
  selection, focus, fill seats. Nothing decorative.
- **`#C2410C` 단청 vermilion** is the *reserved* point colour, spent only on
  attention that demands a response: a downed runtime, a recorded shell crash,
  and — as of Phase 4 — approval-pending. Scarcity is the whole mechanism. It
  appears nowhere else, and adding it to a chip would end its meaning.

  Phase 4 was the test of that rule, because the editing loop is full of
  moments that *want* to be loud. None of them got the colour: a queued edit is
  teal, a validation refusal is `--bad`, an apply failure is `--bad`, a stale
  plan is `--bad`, and the agent's proposal arriving is teal. Only
  `.approval-gate` and the `.action.point` inside it are vermilion, and the
  gate's dot breathes on a 2.4 s cycle rather than blinking — it is waiting,
  not alarming. One deliberate omission is worth naming: the timeline's
  `approval.requested` card is NOT vermilion, because a record of something
  that happened is not a gate demanding a response, and spending the colour
  there would make the log compete with the thing the user actually has to act
  on.

Evidence tones (positive / warning / negative / muted) stay separate from both
and always ship with their word: colour is never the only signal, because the
target user reviews documents for hours and may be colour-vision-deficient.

**Space.** 4 px base: 4 / 8 / 12 / 16 / 24 / 32 / 48. `--row-h` is shared by the
structure tree, the session list and the timeline, so rows in different panels
line up and the eye keeps trusting that they refer to the same thing.

**Motion.** One curve, `cubic-bezier(0.2, 0, 0, 1)`, and nothing overshoots — a
document tool that bounces reads as a toy.

| Moment | Behaviour |
| --- | --- |
| Entrance | 700 ms once per launch: the mark weaves itself (warps, then wefts, then the leg — the order a loom is dressed), then the three panes rise in a 60 ms stagger. Click to skip. Never replays. |
| View switch | Shared-axis slide + fade, 200 ms. Document sits left of Agent on one axis, so the direction means something and the two views read as two rooms of one place. |
| Selection | 120 ms. A located node gets a 900 ms teal flash — long enough to find, short enough not to nag. |
| Timeline cards | 8 px rise on enter. |
| Status badges | Cross-fade rather than snap, keyed on the value. |

`prefers-reduced-motion` disables all of it, and nothing but the motion changes:
every animation is decoration over a layout that is already correct.

**Surfaces.** No card grid. Lists, and one primary surface. The paper column is
the brightest thing on screen and the only element with a shadow; everything
else is separated by 1 px hairlines. Density is a feature.

**Copy** is written as Korean product language, not translated developer
strings: `채움 자리`, `쓰기 전 확인`, `이 빌드가 보지 못하는 것`,
`사이드카가 종료되었습니다. 문서 상태는 남아 있습니다.`

### Where I departed from the direction

- **Dark mode was kept.** The direction specifies the light paper palette
  exactly and says nothing about dark. Deleting the existing dark theme would
  have been a regression, so it survives as a *derived* theme: same roles, warm
  ink rather than a blue night mode, both signal colours re-tuned rather than
  reused. Light is the designed one and the one the screenshots show.
- **`검사 실행` runs a real verify against a candidate, and still cannot re-run
  one on demand.** The direction asks for a button that "runs the runtime's
  verify". Phase 3 could not: `verify/*` was not on the wire and
  `candidate_verify` needs an applied candidate, which a read-only phase never
  produced. Phase 4 produces candidates, so half the ask is now met honestly —
  `check_residue` really runs inside `plan/apply`, and `receipt/read` re-hashes
  the artifact against its binding before returning that verdict, which makes
  reading the receipt itself a proof step. The other half is still missing and
  is still labelled as missing: `verify/*` remains GAP, so there is no way to
  ask "check it again, now". The badge therefore reads **적용 시 검사**, not
  검사됨. Relabelling the apply-time verdict as a fresh verification would be
  precisely the dishonesty the bar exists to prevent. Gap 3 below is the method
  that would close it.
- **App zoom uses the webview's own zoom**, not root font-size scaling, so
  vector chrome and the paper column scale with the text and glyphs are
  re-rasterised rather than resampled.

### 본문 보기, and the gap under it

The centre renders the document's own text and table structure in reading
order. It is not a page render and the header strip says so.

The form's table *is* the document — for the corpus 기안문 별지, table 0's 32
cells hold everything and the 26 paragraphs are the runs inside those cells — so
the tables render as the body and only paragraphs whose text appears in no cell
run are shown separately. On the corpus form that second list is correctly
empty.

Two reconstructions were needed, both derived from data the runtime already
gives rather than guessed:

1. **Column spans.** The runtime reports `row,col` and says nothing about
   merges. Laid out naively that is nonsense on a real form: one row of fifteen
   cells and several rows of one cell, and an HTML table aligns columns across
   rows, so the single-cell rows collapse into the first column and the document
   crams into a strip a third of the page wide. The union of every distinct
   `col` in the table is the column axis, and a cell spans from its own `col` to
   the next occupied one in its row. That is a colspan *implied by the
   addressing*, not a guess at geometry.
2. **Paragraph/cell coverage** is exact string matching, which is sound because
   `form_inspect` derives both from the same runs.

The second is a workaround for gap 9: the Runtime exposes `at_para` and
`row,col#run` as two addressings of the same content with no mapping between
them.

Fill seats were already discrete, addressed, `data-node-id`-carrying elements
with their own empty slot, so inline editing replaced a slot's contents with an
input and nothing else here changed. That prediction held exactly.

---

## The editing loop

One sentence per stage, and the reason each one is shaped the way it is.

**Typing.** Clicking a 채움 자리 mounts a real `<input>` in the cell. Real,
because Hangul composition belongs to the IME and only a real text field gets
it: a 두벌식 sequence composes in place, the preedit syllable is visible while
it builds, and Backspace decomposes rather than deletes. `onKeyDown` ignores
Enter while `isComposing` — pressing Enter to confirm a composing syllable is
ordinary Korean typing, and committing the edit there would end it mid-word.
The app-level `Ctrl+` shortcuts return early when the event target is a text
field, so `Ctrl+C` in the editor is a copy and not "copy the selected cell".

**One plan, rebuilt.** Every queued edit lives in ONE `OperationPlan`, rebuilt
by `plan/propose` + `plan/validate` on every change. Not patched: a plan binds
`boundSha256` and hashes its whole op list, so "append to the existing plan" is
not an operation the protocol has, and inventing one would misdescribe what was
approved. Proposing is cheap. Any change also drops a pending approval, because
the new plan has a different hash and `resolve_approval` would refuse the old
binding anyway — the UI agrees with the runtime rather than offering a button
that cannot work.

**The queue shows the verdict, not a summary of it.** Per op: address,
`before → after`, and the validator's own findings with their codes and their
payloads. `fill_charpr_script_anomaly` (T30) carries `charPrSuggested`, and the
fix button writes that value and nothing else — the engine's number, not a
shell guess. `preflight.deferred` is on screen, because a clean validation is
**not** a promise that apply cannot refuse and a green queue that later refused
would otherwise read as a bug in the approval rather than the documented
boundary it is.

**Approval is the one vermilion moment.** `approval/request` then
`approval/resolve`, host authority. The decision binds an exact `planId` AND
`planHash`, so a person cannot approve one plan and have another applied. This
is the only place `--point` is spent in the entire application; it is not in a
chip, not in an error, not in a diff.

**Apply, and the property that matters.** `plan/apply` runs the plan against
the session copy and publishes a candidate. The smoke asserts the candidate's
sha256 exists AND that the source sha256 did not move, and the bar shows both
digests side by side so the user reads that off the screen rather than being
told it.

**Verification, split into two honest halves.** `check_residue` really runs,
inside `plan/apply`, and `receipt/read` re-hashes the artifact against its
binding before returning anything — so 검사 실행 reports a real offline verdict
for a candidate, with `acceptance` true only when every required check RAN and
was clean. What is still absent is a fresh RE-RUN on demand: `verify/*` is GAP
on the wire and `RuntimeCore.candidate_verify` is domain-only, reachable from
the CLI and not from here. The badge therefore says **적용 시 검사**, not
검사됨, and 렌더 증명 did not move at all — `document/render` can produce a
raster now, and `rt_render` still stamps every result `structural_only` /
`proofGrade: none`, because seeing what bytes draw is not knowing they are the
right bytes.

**Export.** `artifact/exportTo` is GAP, so the copy is the shell's own work:
a native save dialog, a Rust command that composes the source path from the
runtime root plus the session and run ids (never from the webview), and the
candidate and its receipt leaving together — always. The copy is hashed on the
way out and a mismatch is a refusal, not a log line. Then a reopen flow opens
the exported file through `workspace/openPath` like any other document, which
is the only export proof worth having: not that a copy succeeded, but that what
left the application still loads.

**Designed failures.** A queue bound to another document refuses and offers to
re-propose. A sidecar death mid-apply records what was in flight and offers to
look, because `rt_apply` removes the run directory on failure but the shell
cannot know which side of the receipt write the tear happened on — so it reads
`candidate/list` rather than guessing either way. Cancel sends the protocol's
cancel FRAME, cooperative between ops.

### Two things the Rust side needed

**Cancel needs its own handle.** `runtime_call` holds the sidecar mutex for the
whole round trip, so a `runtime_cancel` taking the same mutex could only have
run *after* the call it meant to stop had already finished. `CancelHandle`
clones the stdin and tag maps, which are behind their own short-lived locks.
That is the entire trick, and without it cancellation is decorative.

**`sha2` was not added as a dependency.** `src-tauri/src/digest.rs` is a
vendored SHA-256 with the FIPS 180-4 vectors as `cargo test` cases. Exporting
bytes without hashing them is not an option, and a crate for sixty lines is not
one either.

---

## Evidence

### Phase 3 (commit `2f27d3e`), reproduced from a clean build

| Step | Exit | Seconds |
| --- | --- | --- |
| `npm install` | 0 | 8 |
| sidecar build (PyInstaller one-dir) | 0 | 93 |
| `npm run build` (tsc + vite) | 0 | 15 |
| `npx tauri build` | 0 | 401 |

Shell exe 6.08 MiB · NSIS installer 8.89 MiB · sidecar payload 23.2 MiB.
Smoke: 36 checks, 0 failures, exit 0, across two processes with an orphan check
between them. `pytest tests/test_runtime_*.py` 162 passed.

### The design slice

| Step | Exit | Time |
| --- | --- | --- |
| `npx tsc --noEmit` | 0 | — |
| `npm run tauri build` (release) | 0 | 4m 30s |
| `scripts/smoke.ps1` | 0 | **64 checks, 0 failures** |
| `scripts/screenshots.ps1` | 0 | 6 images |
| `pytest tests/test_runtime_*.py` | 0 | 162 passed, 517s |

Shell exe 8.22 MiB · NSIS installer 10.90 MiB · sidecar payload 23.26 MiB. The
shell grew 6.08 → 8.22 MiB and the installer 8.89 → 10.90 MiB, which is almost
exactly the 1.96 MiB of bundled Pretendard.

Smoke: phase `open` 54, phase `reattach` 10, plus the orphan check between them.
Beyond Phase 3's coverage it now asserts that 본문 보기 is the default centre,
that **every** text run the runtime reported is present in the rendered paper
column, that cells render as real table cells with the runtime's own cell count,
that 페이지 보기 is offered and disabled, that selection syncs tree→centre and
centre→tree, that the located node flashes, that 검사 실행 produces addressed
findings while the bar still refuses to claim a render proof, and that app zoom
and 최근 문서 survive a real process boundary.

Screenshots — `screenshots/`: `entrance`, `welcome`, and
`{document,agent}-view-{100,150}pct`, all with the real corpus 기안문 loaded.

`lto = "thin"` replaced `lto = true` for an independent reason: fat LTO with
`codegen-units = 1` died with `rustc-LLVM ERROR: out of memory` on a 16 GB
machine with a browser open. A build that only completes on an idle machine is
not a build.

### Phase 4 — verified editing

| Step | Exit | Time |
| --- | --- | --- |
| `npx tsc --noEmit` | 0 | — |
| `cargo test digest` | 0 | 2 passed (FIPS vectors) |
| `sidecar/build.ps1` | 0 | 23.4 MiB payload |
| `npm run tauri build` (release) | 0 | 3m 20s |
| `scripts/smoke.ps1` | 0 | **184 checks, 0 failures** |
| `scripts/screenshots.ps1` | 0 | 13 images |
| `scripts/ime.ps1` | 0 | 3 checks, real scan codes |
| `pytest tests/test_runtime_*.py` | 0 | 267 passed, 279s |

Shell exe 8.31 MiB · NSIS installer 11.01 MiB · sidecar payload 23.4 MiB. The
shell grew 8.22 → 8.31 MiB across the whole editing loop, the receipt panel,
the review queue and a vendored SHA-256, which is about what a few hundred
lines of TSX and sixty lines of Rust should cost. `pytest` moved 162 → 267 with
the merge, not with anything here; it is run to prove the merge broke nothing,
and it did not.

Smoke, by phase: `open` 54 · `reattach` 10 · `edit` 83 · `agent` 21 · `page`
16, plus the orphan check between the first two and an out-of-process hash
comparison of the exported file against the digest its receipt binds.

The `edit` phase is the whole loop against the real corpus 기안문: inline edit
→ queue → T30 refusal and its resolution → staleness refusal → approval →
apply → candidate sha256 with the source sha256 unmoved → the candidate's real
`check_residue` verdict → receipt → export → reopen. `agent` is acceptance
task C in the UI. `page` is 페이지 보기 against what this machine can actually
do.

Screenshots — `screenshots/`: the four from the design slice, plus
`inline-edit`, `review-queue`, `approval`, `candidate-verified`, `receipt`,
`page-view`, `agent-proposal`. None are staged: each is reached by running the
real loop to that point, so the approval in `approval.png` is a record the
Runtime issued and the hash on the bar in `candidate-verified.png` belongs to a
candidate on disk.

### Three defects the Phase 4 evidence found

1. **A selector returning a fresh object took the whole root down — again.**
   `draftStaleness` built a new object on every call. `useSyncExternalStore`
   compares snapshots with `Object.is`, so React concluded the store was
   changing forever, error #185 fired, and the boundary unmounted `App` — which
   ran its effect cleanup and *silently dropped the event subscriptions with
   it*. The symptom was every store assertion passing, every DOM assertion
   failing, and zero events delivered. This is the exact failure the comment
   above `NO_CANDIDATES` was written for, walked into anyway, which is worth
   recording: the warning was not enough, so `checkAlive` now names a dead tree
   directly and `domState()` quotes the boundary in the detail of any failing
   DOM check instead of leaving fifteen of them to misreport it.
2. **The packaged sidecar was the pre-merge runtime.** The frozen one-dir
   predated the Phase 3 branch, so the shipped build advertised no `event/*`,
   no `document/render` and no `document/renderPrepare`, and `event/subscribe`
   answered `unknown_method`. Nothing in the source was wrong — which is
   precisely why only a harness against the built app could see it. Rebuilding
   the sidecar is now part of any run that touches runtime capability.
3. **A prefix selector counted the counter.** `[data-testid^="event-"]` matched
   the header's `event-count` element as a twentieth card. Renamed to
   `events-total` and the assertion is scoped to the card list. Same family as
   the design slice's vacuous tree/centre check, three months of lessons later.

A fourth, in the harness rather than the app: **`ime.ps1` would not parse**,
because it was written as UTF-8 with no BOM and PowerShell 5.1 on this
cp949-locale machine read the Korean in it as ANSI, mangling the file into a
syntax error two lines into the param block. Every other `.ps1` here carries
`EF BB BF`; that is not decoration and a new script must have one.

Two assertions were **inverted rather than deleted**, because reality moved
under them and deleting them would have quietly reduced coverage: 페이지 보기
was asserted DISABLED in Phase 3 and is now asserted to track
`capabilities.methods` *in either direction*, and the agent phase asserts the
host can RESOLVE the agent's request rather than make a second one — which is
the authority split the scenario exists to demonstrate.

### What this machine actually answers for `renderPrepare`

`needs_hancom` — *"this machine cannot produce a PDF: pyhwpx is not importable;
the COM backend needs it"*. Recorded because it is the honest state and not a
failure, and because it is **not** the refusal that was predicted: the brief
expected `convert_failed` from a broken `CoCreateInstance`. Both are true of
this machine; the frozen sidecar simply refuses one gate earlier, at the
`pyhwpx` import, because the PyInstaller interpreter does not carry it. Running
against a dev checkout with `pyhwpx` installed would reach the COM call and get
`convert_failed` instead. Both are designed states, both render with the
runtime's own `detail` verbatim plus what a person can do about it, and neither
fabricates a page — the smoke asserts whichever branch it saw.

### Four defects the design-slice evidence run found

Getting to green took four fixes, none of them cosmetic, and all four were in
code or harness that had previously been reported as working.

1. **The smoke never had the isolated profile it claimed.** `smoke.ps1` set
   `$env:LOCALAPPDATA` to redirect the app's data directory, but Tauri resolves
   `app_local_data_dir()` through `SHGetKnownFolderPath`, which reads the user
   profile from the OS and ignores that variable. Every "clean user" run had in
   fact been reading and writing the developer's real prefs — proven by the
   mtime on `%LOCALAPPDATA%\dev.rigorloom.desktop\desktop-prefs.json` moving
   during a run. So `boot()` found the previous run's `lastSessionId`, opened a
   document, and the welcome screen never mounted. `app_data_dir()` now honours
   an explicit `RIGORLOOM_APPDATA`, and both scripts set it. A dead `$SmokeRoot`
   that was created and deleted but never handed to the app is gone.
2. **`locate-flash` was applied imperatively and silently wiped.** `className`
   on those cells is React-controlled, so the next render dropped the class.
   User-visible, not just a test artefact. It is React state now. The first
   attempt at that fix scheduled it behind `requestAnimationFrame`, which
   WebView2 withholds from windows that are not in the foreground — a flash that
   worked only when the window had focus. It is set synchronously.
3. **A passing check was passing vacuously.** The tree and the centre both mark
   nodes with `data-node-id`, and the tree comes first in the document, so the
   unscoped `document.querySelector` in "selecting in the tree marks the same
   node in the centre" was reading the tree and agreeing with itself. Both sync
   checks are scoped to `[data-testid="text-view"]`. The failing flash check is
   what exposed it; had it passed, the vacuous one would still be there.
4. **The screenshots captured other applications.** `shot.ps1` used
   `CopyFromScreen`, which copies whatever pixels sit inside the window's
   rectangle, and `SetForegroundWindow` cannot be relied on to clear them
   because Windows refuses focus changes from a process that is not already in
   the foreground. One run produced "screenshots" of the app with an unrelated
   chat window composited over the middle, private content included. Capture is
   `PrintWindow` with `PW_RENDERFULLCONTENT` now, and it throws rather than
   falling back to a screen grab.

The runtime was not implicated in any of them; `reattach` passed 10/10
throughout.

### What the evidence does not cover

- **Neither native dialog is exercised.** The smoke opens by path through
  `actions.openPath` and exports by path through `actions.exportApplied`, which
  are the same functions the open and save dialogs call with their results —
  but no OS-level input is synthesized and the dialogs themselves are untested.
- **The IME harness is not headless**, though it did run. `scripts/ime.ps1` +
  `scripts/ime_type.py`, adapted from the spike's `measure/ime_keys.py`, typed
  `안녕하세요 서울특별시` into the shipped inline editor as 26 real 두벌식 scan
  code events (`dkssudgktpdy tjdnfxmrquftl`), pressed Enter, and the app
  reported the committed value back byte-identical — into the field, and into
  the plan queue. It also asserts a `compositionend` actually fired, because a
  value comparison alone cannot distinguish composed Hangul from injected
  characters and would pass on a run that proved nothing. What it does NOT
  cover: one IME (Microsoft, 두벌식), one machine, and `SendInput` needs the
  window in the foreground, so it cannot join the headless smoke.
- **Cancel-mid-apply is implemented and not proven.** The cancel FRAME path,
  the `CancelHandle`, and the recovery state all exist and are wired to
  buttons, but the smoke never cancels an apply: the corpus form applies in
  well under a second, so there is no reliable window to cancel inside. Forcing
  one would mean instrumenting the runtime, which is out of scope here.
- **The recovery state is likewise unproven.** Killing the sidecar at the exact
  moment between the artifact move and the receipt write is not something this
  harness can arrange from outside.
- **100% and 150% are forced on the WebView** with
  `--force-device-scale-factor`, as in the spike. That exercises web-content
  re-layout and re-rasterisation but not the native frame's DPI handling, and no
  live scale change was performed. The machine's real scale is 200%.
- **One machine.** The build is fully scripted with one prerequisite — the pinned
  interpreter path — but has not been reproduced elsewhere.
- **No installed-app run.** The NSIS installer is built and measured, not run,
  so the resource path is verified against `target/release/resources/`, not
  against an installed `Program Files` layout.

---

## Runtime gaps

Recorded, not patched: `runtime/**` belongs to another branch. Gaps 1, 2 and 11
CLOSED in Phase 3 and are consumed by this build; the rest stand.

### Closed since Phase 3

1. ~~**No event stream.**~~ CLOSED. `event/subscribe` is on the wire,
   seq-ordered and replayable, and the Agent timeline is now the session's own
   `events.jsonl` rather than this shell's protocol chatter. The suggested
   shape recorded here was adopted almost exactly, including the monotonic
   `seq` for resume — with the better decision that `seq` IS the line index
   rather than a stored field.
2. ~~**No page rendering.**~~ CLOSED. `document/render` plus the host-only
   `document/renderPrepare`. 페이지 보기 enables itself off
   `capabilities.methods` with no desktop change, exactly as gap 11 predicted.
11. ~~**No page render, and now a UI waiting for one.**~~ CLOSED with gap 2.
   Worth noting that the prediction held: the shell polled the capability list,
   the runtime landed the method, and the mode lit up without a line of desktop
   code changing. The tab's smoke assertion had to be inverted, which is the
   only cost.

### Still open

3. **No verification methods.** `verify/*` is still GAP, and Phase 4 makes the
   cost concrete rather than theoretical. A real offline verdict now EXISTS —
   `check_residue` runs inside `plan/apply` and the receipt carries it — so the
   bar can report a candidate's verdict honestly. What it cannot do is re-run
   the checkers on demand, which is what a user pressing 검사 실행 on an
   already-applied candidate actually wants. So the badge has to distinguish
   적용 시 검사 from 검사됨, and that distinction is a workaround for this gap
   rather than a product decision. *Suggested shape, unchanged:* promote
   `RuntimeCore.candidate_verify` to `verify/residue {sessionId, runId}`
   returning the verdict object unflattened. It is domain code that already
   exists and is already exposed on the CLI; only the wire is missing.
3b. **`artifact/exportTo` is GAP, so the shell writes outside the workspace.**
   The Desktop's whole safety story is that the Runtime is the only thing that
   touches documents — and export breaks it, because getting a candidate to a
   person means writing a file the Runtime will not write. The shell's
   `export_candidate` command is as narrow as it can be made (source path
   composed from the root plus ids, never from the webview; `candidatePath`
   forced to a bare name; receipt always travels; the copy is hashed), but it
   is still the one place the shell has a file-writing power the capability set
   otherwise denies it. *Suggested shape:* `artifact/exportTo {sessionId,
   runId, destination}` host-only, copying artifact AND receipt, returning the
   digest of what it wrote — which is exactly what the shell now does, and
   belongs one layer down.
3c. **`plan_stale` is structurally unreachable, so its refusal is untestable.**
   `validate_plan` compares `boundSha256` against `session.current_source_sha256()`,
   but `workspace/openPath` copies the bytes into the session and nothing ever
   writes to that copy again — so the current hash cannot move under a live
   plan. The refusal is correct, the UI handles it, and no test in this repo
   can provoke it. The reachable staleness is shell-side (a queue bound to a
   session that is no longer active), which is what the Desktop refuses and
   what the smoke exercises. *Suggested shape:* nothing to build; worth a line
   in the protocol doc saying the condition is currently unreachable, so the
   next reader does not spend an afternoon trying to trigger it.
4. **`document/graph` is not a method.** `docs/runtime-protocol-v0.md` §6 lists
   it; §9 supersedes that — `document/inspect` returns `summary`, `graph` and
   `regions` together. Harmless, but the §6 table will mislead the next client
   author.
5. **No workspace concept on the wire.** `workspace/list` is unimplemented;
   `session/list` is the only enumeration. Agent view's left column is therefore
   headed 문서, not 워크스페이스, so the UI does not claim a concept the runtime
   lacks. *Suggested shape:* decide whether a desktop Workspace is a runtime
   object or a shell-side grouping of sessions before the IA hardens.
6. **No section or heading structure.** `graph.paragraphs[].section` is the XML
   member name (`Contents/section0.xml`), not a document section. There is no TOC
   and no heading level, so the tree groups by file. Studio's `_parse_structure`
   has a TOC reader that the Runtime does not expose.
7. **Last-writer-wins under `--root`.** Already recorded in `runtime/README.md`
   as the slice's largest risk, and the desktop makes it reachable: two windows
   on one root will clobber each other's session records. The shell does not
   guard against this and cannot from outside.
8. **`sys.executable` child spawning is hostile to packaging.** Worked around in
   `sidecar/rigorloomd.py` with no runtime change, and the workaround holds. But
   an explicit `RIGORLOOM_CHILD_PYTHON` override in `rt_engine.EngineTools` would
   let a packaged host point children at a real interpreter without an argv
   convention, and would remove the closure-computation step in `deps.py`.
9. **No mapping between the two addressings.** `at_para` (paragraphs) and
   `row,col#run` (cells) name the same underlying runs, and the Runtime exposes
   both without saying which paragraph lives in which cell. The centre column
   needs that to render a document once rather than twice, so it matches run
   text against paragraph text — sound here, because `form_inspect` derives both
   from the same runs, but a mapping is not something a client should have to
   reconstruct. *Suggested shape:* `graph.paragraphs[]` gains an optional
   `cell: {table, row, col, run}` when the paragraph sits inside one, populated
   from the enumeration `_run_record` already walks.
10. **No merge geometry.** `table_map` reports each cell's `addr` but no
    `colSpan`/`rowSpan`, so a form's real ruling cannot be reproduced. The
    centre reconstructs horizontal spans from the gaps between occupied `col`
    values, which is right often enough to read but is inference, not data.
    *Suggested shape:* carry the `colSpan`/`rowSpan` HWPX already stores on
    each cell straight through into `table_map`.
### New in Phase 4

12. **`unsupported_backend` is invisible until the user has already typed.**
    A plan declares its backend, and this build serves `preedit` only — but
    nothing in `capabilities` says which OP KINDS a given seat can accept, so
    the shell cannot grey out an edit it knows will be refused. Today every
    fill seat happens to be servable by `fill_cell`, so the gap is latent. It
    stops being latent the moment the UI offers anything the `xml` or `com`
    registries own (an equation, a picture, a hyperlink), because the refusal
    would arrive after the person had composed the content. *Suggested shape:*
    `regions[]` gains `servableOpKinds: string[]`, derived from the same
    registry membership `build_plan` already checks.
13. **A cancelled apply has no distinct outcome the client can read.** The
    cancel frame works and `rt_server._checkpoint` acts on it between ops, but
    what comes back is the generic `cancelled` error — with no statement of how
    many ops ran before the stop, and no distinction between "cancelled before
    anything was written" and "cancelled after op 3 of 5, and the run directory
    was removed". `rt_apply` does remove the run directory, so the answer is
    always "nothing was published", but the client has to know that from
    reading the source rather than from the response. *Suggested shape:* the
    `cancelled` error for `plan/apply` carries `{opsCompleted, published:
    false}`.
14. **`event/subscribe` has no way to say "and also the next session".** A
    subscription is per session, so switching documents means unsubscribing and
    re-subscribing, which resets the client's whole event list and re-replays
    from zero. That is correct and cheap at this scale, and it will not be when
    a workspace has fifty sessions. Not urgent; recorded before it is.
15. **The apply lock is the whole call, not the write.** Already flagged as a
    risk in Phase 3 and now load-bearing: `runtime_call` holds one mutex for
    the entire round trip, so a `plan/apply` blocks every other request from
    the UI while it runs. Cancellation had to route around it entirely (see
    `CancelHandle`). This is a *shell* defect rather than a runtime one, and it
    is recorded here because the fix — scoping the lock to the write — is the
    next thing anyone touching `sidecar.rs` should do.

## Assumptions

- Windows-first. `jobkill.rs` and the liveness probe are Windows-only by
  construction and return an error elsewhere; nothing else is OS-specific.
- The Runtime is the only thing that touches documents. The capability set
  grants no `fs`, no `shell`, no `http`.
- One shell process, one sidecar, one root. Multi-window is not designed for.
- `--entry host` is correct for the desktop: it opens arbitrary paths, which is
  host-only authority (protocol §4).

## Known risks

- **The evergreen WebView2** can change rendering under a released build. This
  one was exercised against 151.0.4129.107.
- **`CALL_TIMEOUT` is 180 s**, matching `tests/_runtime_client.py`, because the
  Runtime spawns repo-script children and
  `tests/test_subprocess_bounds.py` measured a loaded cold spawn at a 9.00 s
  median with a 36.46 s worst case. A user waiting three minutes on a hung call
  sees a designed timeout, but three minutes is a long time.
- **`runtime_call` serialises on one mutex, and Phase 4 made that bite.** The
  lock is held for the whole round trip, so an apply blocks every other request
  from the UI while it runs, and cancellation had to route around it entirely
  through a separate `CancelHandle` — see gap 15. Scoping the lock to the write
  rather than the wait is the next thing anyone touching `sidecar.rs` should
  do.
- **Two sessions of the same file are indistinguishable in the list** except by
  timestamp. Opening the same form twice is legal and produces two rows.
