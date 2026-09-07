# desktop/ — Rigorloom Desktop, Phase 5 agent-native

Tauri 2 + React/TS shell over the real Runtime as a packaged Python sidecar.

**The page is an editor now, and that is measured rather than claimed.** The
overlay slice shipped a component that could click a seat and had no seat to
click: `document/pageGeometry` placed zero on all ten corpus forms. The runtime
stack this build merged rebuilds the drawn grid out of Hancom's own stroked
segments and places 73, and this shell finds all 37 on the exercised page
editable — click one, type into the same `<input>` the tree view mounts, and the
op lands in the same review queue at the same address, all the way to the plan.
The same merge gave 작업 팩 a 실행 button with `module/check` behind it, and the
toolbar a 글꼴 that reads 돋움체 instead of `charPr 11`. What that button mostly
reports is that twelve of eighteen checkers were skipped, and it says skipped.

**A person can now tell the agent what to do, and the agent still cannot do
it.** Type an instruction; the shell spawns an Agent Host process on an
AGENT-authority connection to the same workspace; it inspects, proposes and
asks; its plan lands in the SAME review queue a typed cell value lands in, per
op, marked as the agent's; and it stops, because `approval/resolve` and
`plan/apply` are not in its registry at all. A human approves. That is the whole
product claim, and Phase 5 is the slice where it stopped being a demo button and
became a text box.

**And the window stopped looking like a web page.** There is an editor band
above the paper now — the seat's 글자 모양, the body size, the view switch, one
document zoom, the document's state — a ruler over 페이지 보기 drawn from the
page's real margins, a page footer, and a status bar that carries 쪽 and 위치 and
says outright that it has no 삽입/수정 state because it has no character cursor
to be in one.

**Phase 4's claim is unchanged and still holds.** A person can change a document
here and prove what changed: one OperationPlan, a pre-write verdict, an approval
bound to an exact plan hash, a candidate with its own sha256 beside an unmoved
source hash, and a receipt binding both. Nothing on that path is optimistic —
every refusal the protocol declares has a drawn state, and the things the
application cannot do (re-run the checkers on demand, prove a render, stream a
provider's text) still say so in as many words.

Phase 3's read-only foundation, the design slice and Phase 4's editing loop are
all still here and still true; what follows marks what Phase 5 changed.

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
| `src-tauri/src/prefs.rs` | the things the shell remembers between launches, now including where the window was |
| `src-tauri/src/agenthost.rs` | spawning the Agent Host, tailing its event log live, composing its config |
| `src-tauri/src/credstore.rs` | Windows Credential Manager. **The only place a secret rests** |
| `src-tauri/src/taskpacks.rs` | 작업 팩: the module registry's own answer, via a child process |
| `sidecar/rigorloomd.py` | frozen entry: serves the protocol, and stands in for the interpreter |
| `sidecar/deps.py` | derives the frozen build's hidden imports from the engine's own sources |
| `sidecar/build.ps1` | PyInstaller one-dir against a pinned CPython 3.12.10 |
| `src-tauri/src/digest.rs` | vendored SHA-256, so an export can be hashed without a dependency |
| `src/store.ts` | **the one Workspace** both views project |
| `src/actions.ts` | every operation, as plain functions, so the smoke drives the real path |
| `src/runtime.ts` | thin invoke wrappers and event subscriptions |
| `src/views/` | `DocumentView`, `AgentView` — layouts, no state |
| `src/components/` | tree, text view, panels, verification bar, findings, timeline, composer, logo, splash, review queue, receipt panel, conversation, settings, editor toolbar, task packs, page overlay, **`SeatEditor` — the one inline `<input>`, mounted by BOTH the tree and the page** |
| `src/assets/` | `logo.svg` (drawing of record) and the bundled Pretendard + `OFL.txt` |
| `src/devMock.ts` + `src/fixtures/` | browser-mode replay of a recorded real session; `import.meta.env.DEV` only, absent from production bundles |
| `src/smoke.ts` | the scripted checks, run inside the built app |
| `scripts/` | build, smoke, screenshots, window capture, fixture recorder, **`agent_roundtrip.py`** |

### Keyboard

`Ctrl+O` open · `Ctrl+1` / `Ctrl+2` views · `Ctrl+=` / `Ctrl+-` / `Ctrl+0` app
zoom (50–200 %, persisted, announced as a toast) · `Ctrl+C` copies the selected
cell or paragraph when there is no text selection to copy instead · `F11`
fullscreen · `Esc` closes the topmost overlay. Dropping a `.hwpx` on the window
opens it; anything else is refused out loud.

Inside a fill seat: `Enter` commits, `Esc` cancels. In the composer:
`Ctrl+Enter` sends, bare `Enter` is a newline. Every app-level shortcut returns
early when the event target is a text field — a shortcut that reached past a
field the user is typing in would eat a `Ctrl+C` and, worse, could throw away a
composing syllable.

`F11` and `Esc` are the two deliberate exceptions to that rule, because every
editor's are. `Esc` still yields to a composing syllable (`isComposing`), where
it belongs to the IME, and it is handled in exactly ONE place — `actions.ts`
`closeTopmostOverlay`, innermost first: inline edit → receipt → settings → task
pack → findings. Two components each deciding what `Esc` meant is how a second
press closes something the user was not looking at.

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
`candidates`, `activity`, conversation state, and the unsent composer draft;
`setView` writes only `view`. Components may hold ephemeral presentation state,
but navigation and user work that must survive a view switch live in the
Workspace. `sharedStateSignature()` states that contract once in the store, and
the smoke asserts the signature is byte-identical across a round trip.

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

## The composer, live

**One process per turn, and the reason is not performance.**
`agenthost/scripts/host.py` is a one-shot CLI: parse argv, open a door, run one
`AgentHost.run(instruction)`, print one JSON document, exit. It has no stdin
command loop and no resume — `resumableThread` is `no` everywhere and the host
resends the whole history each turn *inside* one run. Keeping it alive between
messages would mean inventing a shell↔host protocol that does not exist, in a
tree this slice does not own. So: one process per turn, exactly as
`run_mock_agent` already did. The cost is a cold Python start per message; the
benefit is that a hung provider cannot wedge the shell, and that the agent's
authority boundary is a *process* boundary, which is the property everything
else rests on.

**The event log is tailed, not waited for.** The run payload arrives only at
exit, and a live provider turn can take tens of seconds. `--events FILE` mirrors
the ordered log to JSONL as it happens — `EventLog.append` opens, writes and
closes per line, so a reader never sees half a line — and a Rust thread polls
that file, batches whole lines on a 120 ms timer, and emits arrays on
`agenthost://events`. Same rule the sidecar's own channels follow, for the same
measured reason. A trailing fragment is held until its newline arrives.

**One queue, and it is the same object.** `adoptAgentPlan` re-reads the plan over
THIS shell's host connection, validates it here, and writes the one `draft` a
typed cell value writes — every op marked `origin: "agent"` with the plan's
`proposer`. The mock button now calls the same function; two code paths claiming
to end in the same queue would eventually stop.

**The agent cannot approve, and the card quotes rather than claims.**
`neverCompiled` comes from the host's own payload — the host-only methods its
compile gate will never emit — and is printed verbatim. Underneath it, the
Runtime agrees for its own reasons: `desktop/scripts/agent_roundtrip.py` calls
`approval/resolve` and `plan/apply` on a real agent connection and requires
`unknown_method` from both. The claim is measured on both sides of the door.

### Streaming, and what is actually true

`provider.stream.chunk` is a declared event kind, the mock adapter declares
`streaming: yes`, the Anthropic adapter implements SSE — and **no assistant text
streams into this UI**, because `AgentHost.run` only ever calls
`provider.complete()`. No adapter's `stream()` is reachable through `host.py` at
all. So:

- the card streams the host's **progress** — its events arrive live, and the
  newest one is the line under the spinner;
- the assistant **text** appears in one piece when the turn ends;
- the card and the settings pane both say so, in as many words, next to the
  capability row that says `streaming: 예`.

Drawing a typing animation over a batched response would have been the exact
dishonesty the rest of this application is built to avoid. Recorded as agenthost
gap 1 below.

## Provider settings, and the one place a secret rests

The Agent Host takes a credential **reference** — the name of an environment
variable or an OS store key — and refuses a config carrying a value by member
NAME, whatever the value looks like. That contract is only worth something if
the desktop has somewhere real to put the secret, and until Phase 5 it did not:
the honest options were "set an environment variable in a terminal", which is
not a product, or "write it to a JSON file", which is the thing the contract
exists to prevent.

`src-tauri/src/credstore.rs` is Windows Credential Manager through four calls —
`CredWriteW` / `CredReadW` / `CredDeleteW` / `CredFree` — on a dependency this
crate already had. `windows-sys` gains one feature and no new crate. The
`keyring` crate would have pulled a tree to wrap those four calls; this is the
same reasoning that kept `sha2` out in Phase 4.

**The handoff, and why it is an env reference and not a store reference.** The
Agent Host declares an `os_store` credential source and *refuses* it —
`credential_source_unsupported`, "not implemented in this slice". So the shell
reads the secret from the store and sets it on **one child `Command`'s
environment**, and the config names that variable
(`RIGORLOOM_PROVIDER_CREDENTIAL`). The variable exists only inside that child.
That is the same guarantee reached through the door that IS implemented, and it
is recorded as agenthost gap 2 rather than worked around silently.

What the rules add up to, stated as obligations rather than intentions:

| Obligation | Where it is kept |
| --- | --- |
| A secret crosses IPC once, inbound only | `credential_set`; there is no read-back command |
| The UI never redisplays it | no reveal control — a field that can display a key is a field that can be screenshotted |
| `status` answers present/absent and a byte count | enough to tell a whole key from half of one, not enough to be a leak |
| No secret-shaped member reaches a config | refused by NAME in `compose_config`, one layer earlier than the Agent Host's own refusal |
| The config is inspectable | the settings pane prints the file it wrote, verbatim |
| Nothing on disk carries it | `smoke.ps1` greps every byte the app wrote for a sentinel |

**The header is part of the reference, not a default to leave off.** This is the
defect `agent_roundtrip.py` caught: `CredentialRef` falls back to
`Authorization: Bearer <value>`, which is right for an OpenAI-compatible router
and **wrong** for the Messages API, which wants a bare `x-api-key`. A config
omitting `header`/`scheme` looked correct and would have authenticated against
nothing. `compose_config` now writes them per provider and a `cargo test` pins
both.

**연결 확인 is a local describe.** `--capabilities` needs no key, no document and
no network; it works before anything is configured, which is why its answer
about what the adapter does *not* know is trustworthy. The three states reach
the screen unrounded — `unknown` renders as 모름 — because `supports()` treating
an unverified maybe as permission to try is the bug the third state exists to
prevent. A live provider call happens only when a key is stored AND the user
sends a message.

The credential vocabulary rendered in the pane is the adapter's own, not a
translation: `not_required` / `configured` / `missing` / `unsupported`
(`ah_anthropic.credential_state`). The pane shows it beside the OS store's
own present/absent, because the two can disagree — a key saved under one name
while the config points at another — and one line each is how a person sees
that.

## The editor band, the ruler, the status bar

Until Phase 5 the centre had a two-button mode switch and a caveat line, and the
window read as a web page with a document in it. A Hangul editor has a dense
functional band between the chrome and the paper, and that band is most of why
the genre feels like an editor. So there is one: sunken relative to the panel so
the paper stays the raised thing, keyboard-first, no icon cloning, no Hancom
anything, and the hanji palette and single teal accent unchanged. The point
colour is spent nowhere in it.

What it carries, all read-only and all real: the selected seat's 글꼴 (the face
the document declares for its charPr — see 글꼴, in the toolbar below), its
`charPr` id (marked when it differs from the document's own body shape — T30,
surfaced where a person is looking rather than only in the queue), the body size
from `summary.baselineCharPr`, the relocated 본문/페이지 switch, one document
zoom, and the document's state (대기 n / 승인 대기 / 후보본 있음 / 검사).

**The 글꼴 name arrived, and it is still not a dropdown.** Until §14 there was
no typeface name on the wire anywhere and the strip showed `charPr 11`, because
a font control reading 맑은 고딕 because that is what toolbars usually say would
be a fabrication in the one place this application must not fabricate. Gap 16 is
closed and the name is real now — but it is still a READ. Setting a face means
creating a charPr the document does not have, which is a `preedit` question, not
a protocol one, so there is nothing to open a dropdown onto.

**One zoom number, meaning the same thing in both modes.** The toolbar's zoom
writes `zoom`, which 페이지 보기 already used; 본문 보기 now applies it as CSS
`zoom` on the paper column, which scales layout so glyphs re-rasterise rather
than being resampled. App zoom stays separate and is labelled 화면.

**페이지 보기 gained a ruler and a footer.** The ruler is `summary.pageMetrics`
at the same scale the page figure uses: real width, real margins as the shaded
ends, 1 cm ticks with a longer mark every 5. Centimetres because the corpus form
is A4 with 20 mm margins and the whole 기안문 tradition is metric. The footer is
the Hangul shape — the action on the left, `n쪽 / 전체 n` with ◀ ▶ in the middle,
zoom on the right.

**The status bar learned three Hangul-editor conventions and refused a fourth.**
쪽 is the renderer's own page number, and reads — in 본문 보기 because the
runtime maps no text to any page. 위치 is the selection's address, spelled the
way the runtime addresses it (`표0 (0,14)`, `문단 12`) — never a line and column,
because this build has no character cursor and inventing one would be a lie
about where the user is standing. And the insert/overwrite indicator every
Hangul editor carries reads **삽입/수정 없음**, for the same reason: there is no
caret to be in a mode.

**The window remembers where it was.** Physical pixels plus the scale factor
they were measured at, saved on move and resize behind a 700 ms throttle (a drag
emits one event per frame) and once at startup, because a launch that is never
resized must still leave something behind — "the window remembers" cannot be a
property that only holds for a user who happened to drag it. A restored size
below the editor minimum is clamped, and a position no attached monitor covers
re-centres rather than putting the window somewhere it cannot be dragged back
from.

## 한글 오버레이 — editing on the page

The product's stated wedge is an editor that works *on* the rendered page rather
than beside it. `document/pageGeometry` (§12) is what makes that possible: per
page, every line of text as a normalized rect, mapped to an editable address, a
list of candidates, or nothing — plus rects for empty fill seats, each tagged
with how it was derived.

**The overlay is the renderer's layout, never ours.** Every rectangle drawn on
the page is a `[x0,y0,x1,y1]` fraction the runtime read out of a PDF Hancom laid
out. Nothing is derived from `summary.pageMetrics`, nothing is nudged, and when
the runtime returns no geometry the overlay component is not mounted. That is
not caution for its own sake: a rectangle in the wrong place puts a text cursor
where the text is not, and does it with the authority of a measurement.

**One mutation path, and one editor element.** An editable target's click calls
`beginEdit(table, row, col)` — the same function `TextView`'s cell click calls —
and mounts `SeatEditor`, the same COMPONENT `TextView` mounts, inside the
rectangle the runtime placed. Same `<input>`, same IME behaviour, same
`fill_cell` op, same review queue, same plan hash, same approval, same receipt.
A value typed on the page and a value typed in the tree are indistinguishable by
the time they reach `plan/propose`, which is what makes a second editing surface
a new *surface* rather than a new *risk*.

That is now proven end to end rather than asserted, and proving it cost a
defect: `SeatEditor` used to live inside `TextView`, so the first click on a
real seat opened an edit state with **no field on screen** — 페이지 보기 does
not mount `TextView`. See "the seat slice" below.

**Ambiguity is drawn, never resolved.** A line whose normalized text matches
several addresses arrives with `address: null` and every candidate listed. It is
the only overlay class that is permanently visible, in the warning vocabulary
with its candidate count, and clicking it opens a chooser with no default row,
no preselection and no "most likely" affordance — because a default *is* a pick.
The chooser also says out loud that nothing has been queued, so dismissing it
cannot be mistaken for cancelling an edit that was never made. T41
(`engine/scripts/preedit.py:221`) is the reason: one unscoped key overwrote five
sibling contracts in a six-contract pack and every offline gate passed, because
the label survived as a prefix.

**Zoom costs nothing.** The rects are fractions, so the raster and the overlay
share one sized box and every child re-lays out from numbers already held. The
runtime is asked nothing. Geometry is cached per `(session, page)`; the store
counts real method calls in `geometryFetches` so the harness can assert that
rather than take it on faith.

### What it looks like on real forms today

**Clickable, at last, and lumpy.** `cell_borders` (§12.4) rebuilt the drawn grid
from Hancom's own stroked segments and placed **73 seats across the corpus** —
55 of them on `kstartup-jiwon-sincheongseo-saeopgyehoekseo`, 0 on the two forms
ruled with underlines rather than boxes. On the page the smoke exercises, the
runtime places 37 seats and this build finds **all 37 editable**: every one is
an address `document/inspect` offers as a fill seat, so every one opens the
editor. Ambiguity is still the bulk of the page — 71 ambiguous spans against 10
unique on that same page — and gap 19 stands.

Still true, and still the interesting number: **0 unique SPANS map to an
editable cell.** Matching is by text and an empty seat has no text, so the text
half of the mapping reaches labels and only labels, and every *seat* on a page
came from the border scan. 400 of 473 corpus fill regions still get no seat and
§12.6 lists the causes one by one.

What that number stopped meaning is "the text half of the mapping is wasted".
It reaches **365 paragraph addresses across the corpus**, and 314 of those are
now caret targets — see 지면 커서 below. The seats are where a form is *blank*;
the paragraph lines are where it already says something, and both are places a
person types.

The legend under the raster prints the runtime's own counts (확정 / 후보 / 대응
없음 / 자리) and, where there is nothing to click, still says so and points at
본문 보기 — because the alternative to an empty page here is a *guessed* box,
which is the one thing this feature may never produce.

### The seat, at rest

An empty seat is drawn before the pointer touches it: a faint fill tint in the
accent vocabulary the tree view already uses for a value slot, a baseline rule
under it, and `cursor: text`. It used to appear only on hover, and that was the
right call when the runtime placed zero seats and the alternative was a page
speckled with boxes over nothing. With 37 real seats on a page it is the wrong
call: an invisible invitation makes the product's marquee interaction
undiscoverable unless you already know it is there. The smoke reads the
**computed** style rather than the class list, because a class no rule matches
would satisfy a class-name assertion and draw nothing.

Ambiguity keeps its own vocabulary — the warning palette, permanently visible,
because it is a question and not an invitation — and mapped-but-inert text still
gets no affordance at all.

### 지면 선택, in the status bar

The bar gains one fact, and only in 페이지 보기, because that is the only mode
where a click has a rectangle to have landed in: the address a page click
resolved to, or `후보 N개 — 직접 선택` when it resolved to a question instead of
an answer. A target the runtime mapped but the editor will not open says so
rather than opening an editor that would refuse.

A seat pick also carries **how the rectangle was found** — `표10 (2,1) · 그려진
선으로 잡음` — because §12.4's three derivations are not equally trustworthy and
a seat is the one overlay class a person types into. Leaving that in a tooltip
means it is never read. `data-derivation` on the same element carries the raw
`cell_borders` / `matched_text` / `interpolated` for the harness.

### 지면 커서 — typing in a line, not only in a seat

A seat is an empty cell. A form is mostly not empty cells, so for the life of
the overlay the marquee interaction reached **73 places across the whole
corpus** and every one of them was blank. The other half of "editing on the
page" is the body text: click a uniquely-mapped paragraph line and a real caret
stands in it, in a field mounted in that line's own rect, at the size the render
drew it, at the character the pointer landed on.

**The offset is measured or it is absent.** `document/pageGeometry` now carries
`spans[].charX` — one normalized x per character of the line's text, read out of
the same PDF every rect comes from (§12.2). The click's x, as a fraction of the
page, is compared against those boundaries and the nearest one wins, which is
why clicking the right half of a character puts the caret after it. Nothing is
interpolated from a line's width and its character count: a proportional face
makes that wrong by a character or more mid-line, and a cursor standing where
the glyph is not is the same fabrication as a rectangle in the wrong place.
Where a line carries no boxes the caret goes to the front and **the app says
so** — `caret: null` rather than `caret: 0`, 줄 앞 rather than 0번째 글자 앞 in
the status bar, and a dotted rather than solid hover rule on the line itself, so
the limitation is visible before the click rather than after it.

**One mutation path, two op kinds, no new route.** Typing goes through the same
`commitEdit` → `setQueue` → `plan/propose` → `plan/validate` → review queue →
approval → apply → receipt a seat fill goes through. What differs is the
operation kind, and it is one the Runtime already had: `set_run` at
`(atPara, run)`, which preserves the run's `charPrIDRef`
(`engine/scripts/preedit.py:2464`). No `replace_paragraph_text` was invented on
either side of the wire. The queue holds both kinds, the tree draws both as
`before → after`, and an edit typed on the page shows up in 본문 보기 exactly
as one typed in the tree does.

**The check the shell has to make itself, and the refusals it produces.** A line
is not a run. The two coincide only where the paragraph holds exactly one run
whose text IS the line, and `beginParagraphEdit` asks `document/readRegion`
rather than assuming it from the fact that the text matched. The refusals are a
closed set with a sentence each — `multi_run`, `run_text_differs`,
`no_inventory`, `no_address` — because a person who clicks visibly mapped text
and gets silence concludes the feature is broken, when the honest answer is that
this paragraph has no single run to address.

**What that is worth, measured on the corpus** (ten forms, 51 real
Hancom-rendered pages, before any of it was written):

| | |
| --- | ---: |
| uniquely-mapped spans | 376 |
| …that are paragraph addresses | 365 |
| …that are cell addresses | 11 |
| paragraph lines holding exactly one run — a caret target | **314** |
| paragraph lines holding several runs — refused by name | 51 |
| paragraph lines whose run text disagreed with the line | 0 |
| empty seats the border scan places (unchanged) | 73 |
| **places on a page a person can type, before → after** | **73 → 387** |

And the offsets themselves: **2,591 of 2,591 lines** resolve one box per
character, in order, none degenerate. 2,508 also carry a single `sizePt`; the 83
that do not are set in two sizes at once, so they carry none — reporting one of
them would be a pick.

**Vocabulary, kept apart on purpose.** A seat is an empty box inviting a value
and keeps its faint fill tint with a baseline rule. A caret target already *has*
its text, so tinting it would repaint the body of the form: it gets the
text-selection vocabulary instead — an I-beam and a hairline under the line on
hover. Ambiguity keeps the warning palette and still refuses to resolve itself.
Inert mapped text still gets nothing at all.

**The 입력 indicator finally has something true to say.** It read 삽입/수정 없음
for the life of this product and that was honest — there was no character-level
caret, editing happened per seat, and an indicator claiming 삽입 would have been
inventing one. There is a caret now, so it reads 삽입 while one is open. It never
reads 수정: nothing in this build overwrites, and offering a mode that does not
exist is the same fabrication as a font name nobody declared.

### 글꼴 over a caret, and whose size it is

The toolbar names the face the **run** is set in, from
`document/readRegion` → `runs[].charpr_face` (§14's fourth field, added with
this slice). A run's charPr appears in neither publisher `faceIndex` read
before — the document-level shapes and the fill seats — so above a caret the
strip could print the integer and nothing else.

크기 is the one control where two different facts meet, and they are never
merged. `summary.baselineCharPr.height_pt` is what the document's **header**
declares for the body shape. `spans[].sizePt` is what the **renderer** drew the
caret's line at. §14.1 is explicit that a run's charPr carries no point size of
its own, so with a caret open the honest number is the render's — and it is
labelled 지면에서 잰 값, with `data-source="render"` for the harness, because a
measured size presented as a declared one is a fabrication in the one control
this application must not fabricate in.

Changing either is a later slice and a `preedit` question, not a protocol one:
setting a face means a charPr the document does not have (§14.1).

## 작업 팩 — the panel that stopped being 준비 중

Six distribution modules are declared on disk, each contributing named checkers
and CLI commands, and `report` really does depend on `style` and really is
refused without it. Agent view's left rail lists them — the module registry's
own answer, obtained by running `pipeline/scripts/module_registry.py list` as a
child through the same dual-role entry the Runtime's children use, rather than
writing a second `module.yaml` reader in Rust that would be the wrong one the
first time a manifest used a shape it did not anticipate.

**There is a 실행 button now**, and there was not before, because before there
was no method behind one. `module/check` (§13) is that method: it materialises
the document into `<session>/checks/<callId>/subject/`, runs the module's
checkers with that directory as cwd, deletes it in a `finally`, and returns a
VerificationReport-shaped answer. The session copy, the published candidate and
the operator's original are unreachable **by construction**, which is what makes
"read-only" a property rather than a hope. Nothing is decided: no candidate, no
plan, no approval, and the smoke asserts the review queue is untouched by a run.

### The four rules the report is drawn to

**1. `skipped` is never a pass.** Twelve of the declared checkers take a report
*workspace* directory and a session holds a document, so on any document session
they come back `skipped: needs_workspace` — and that is the normal case, not an
edge one. They are drawn as 건너뜀 in the neutral vocabulary with a Korean line
keyed on the reason CODE, and the runtime's own `detail` is printed beside it
rather than replaced. Twelve green ticks there would be the single most
misleading thing this panel could print.

**2. A rule the checker could not decide is a finding, not a silence.** §13.4
keeps `severity: "skipped"` findings precisely because "this rule did not
decide" is the fact a reader needs most and the one a bare pass hides. They are
listed with their code at the same weight as a warning, labelled 판정 안 함.

**3. `ok: true` is not acceptance.** Every document checker in the corpus
declares `wants: [baseline]`, and a session with no candidate has no baseline to
give — so the checker runs, reports clean, and the report's `acceptance` is
still false. Both facts are on screen: the row shows its own `pass` verdict AND
입력 부족 with the unmet input named, and the header shows 통과 아님 with the
runtime's own reason. Neither is allowed to hide the other.

**4. A finding's address is a place, and only when the runtime made one.**
`address` is the checker's location translated into `{table,row,col}` /
`{atPara}` where a translation exists and `null` where it does not — never a
half address. An addressed finding gets a link that selects the cell in
본문 보기; an unaddressed one gets the checker's own location as plain text and
no link at all. On this machine's evidence run: **1 of 11 findings carried an
address** (`grant`'s `budget_total_mismatch`, 표11 (5,5)).

### Enablement has two readers, and the panel prints both

Whether a pack can be run is enablement, an install-time operator act recorded
in `enabled.yaml` that no wire call can change. Two things read that file: this
list (through `module_registry.py`) and the Runtime (`rt_module`), and the
Runtime's reading is the one `module/check` obeys — so the 실행 button follows
the Runtime, and the panel says so out loud when the two disagree rather than
picking one. Both now honour `RIGORLOOM_MODULES_ROOT` and
`RIGORLOOM_MODULES_ENABLED` (a new `--enabled-file` flag on the registry CLI,
forwarded by `taskpacks.rs`), and both report which file they read — because
"we disagree" and "we read different files" are different defects.

A fresh checkout has no `enabled.yaml` at all: it is gitignored, correctly, and
a shipped bundle enables nothing until an operator does. That is the panel's
honest empty state and the smoke asserts it in the `chrome` phase — the 실행
control is present and disabled, with the reason — while the `packs` phase
writes an enablement outside the checkout and asserts the run path. Both are
under test in the same run, and the driver checks afterwards that the run left
nothing in the repository's own `modules/`.

The Korean display names live in `taskpacks.rs` rather than in the manifests,
because the manifests are the program's contract with its modules and carry no
UI copy; adding a `displayName` to them would be editing a tree this slice does
not own. A module with no entry shows its declared name verbatim and is flagged
`named: false`, so the absence is visible rather than papered over.

## 글꼴, in the toolbar

The strip showed `charPr 11` where a 글꼴 control belongs, because no typeface
name was on the wire anywhere (gap 16). §14 puts the declared face there —
joined out of the header's own `fontface` tables by `form_inspect`, never
inferred — so the toolbar now reads **돋움체**, and the T30 mismatch beside it
reads **본문은 한양중고딕** instead of a second integer.

Three rules, because a font control is the easiest place in this application to
fabricate:

- **Nothing is defaulted.** A dropdown reading 맑은 고딕 because that is what a
  toolbar usually says would be a fabrication. Where the document declares no
  resolvable face the id stands alone and the strip says which absence it is.
- **Two absences stay apart.** `face: null` means THIS document names no face
  for that charPr; `summary.typefaces.state === "unavailable"` means nothing
  looked. The strip prints 문서가 이름을 안 밝힘 for the first and 읽지 못함 for
  the second, and the smoke asserts the right one for the state the runtime
  reported.
- **한글 first, every language in the tooltip.** §14 carries a face per language
  because Hangul's own font dialog does. The strip has room for one and shows
  the 한글 face; the tooltip carries every language the header resolved,
  unmerged. Collapsing them would be a guess about which of two declared truths
  the reader meant.

The shell builds its charPr→face index from what `document/inspect` already
publishes — the two document-level shapes plus every region's `charPrFace` and
`charPrSuggestedFace` — so every pair on screen is one the runtime stated. A
graph cell whose charPr appears in neither publisher gets no name, which is
correct: nothing on the wire said what it is.


---

## 되돌리기 — two tiers, one of them provable

E1.4 asked for undo whose inverse is *proven*, never a client-side shadow of
the document that can drift from the runtime. The first thing that turned up
on the way there was that the thing the plan assumed already existed did not.

### The defect underneath: two applies made two siblings

`plan/apply` chained every operation from `session.source`. So the second
apply in a session did not produce the next version of the document — it
produced a second first version. Open a form, fill a cell, approve, apply; fill
another cell, approve, apply; export. The exported candidate carries the second
edit and not the first, silently, with a valid receipt binding valid bytes.

Nothing in the receipt chain ordered plans, because nothing recorded a parent.
There was, therefore, no chain for an undo to be the inverse *of*.

The fix is one field with consequences: `plan/propose` takes a `baseRunId`, the
plan binds that candidate's digest, `plan/apply` chains onto that candidate's
bytes, and the receipt records `base`. Everything else follows — validation
profiles the base (the second edit of a paragraph addresses runs the first edit
produced), and a candidate-based plan can never be `plan_stale` because a
published candidate is immutable. Protocol §15 has the whole shape.

### Tier one: an edit in the queue

An op in the review queue is not in any candidate, so **removing it IS the
undo**. No runtime call, no document, nothing to reconcile. The only thing this
tier owes anyone is its label: the control says **대기열에서 제거**, and the
toast says 문서는 처음부터 바뀐 적이 없습니다. Calling it 문서 되돌리기 would
tell someone their file changed back when the file never changed.

다시 넣기 re-enqueues the op OBJECT that was removed, not a reconstruction of
it from a remembered address and a remembered string. That is what makes the
redo exact rather than merely similar — the smoke asserts the target, the
value, the `before`, and that the re-proposed plan has the identical `opsHash`.

The stack is cleared on apply and on a document switch, and gap 31 says why.

### Tier two: an applied candidate

An applied candidate is immutable and receipted, so undoing one cannot mean
changing it and must not mean deleting it. It means proposing the **inverse**
as a new plan, which travels the same review → approve → apply path as
anything else and produces one MORE candidate with one more receipt.

Three rules, each of them a way a shortcut would lie:

1. **The previous value is READ, never remembered.** It comes from
   `document/readRegion` against the candidate the edit was made ON — the
   parent named in the receipt, or the source at the root of the chain. Every
   `readRegion` answer now states its `subject`, so a caller that asked for a
   candidate and silently got the source cannot mistake one for the other. An
   address the runtime did not return is a refusal (`previous_value_unreadable`),
   never an empty string: an inverse that guessed blank would WRITE a blank
   over something unknown.
2. **What cannot be inverted is refused by name.** `fill_cell` and `set_run`
   are invertible. `delete_guides` is not, and a candidate containing one gets
   `not_invertible` with the kinds listed — not a button that would produce a
   partial undo (gap 29).
3. **It is a PROPOSAL.** It lands in the queue labelled 되돌리기 제안, chained
   onto the HEAD rather than onto the candidate being reversed — undoing an
   older edit must not throw away the newer ones on top of it — and a person
   approves it exactly as they approved the edit.

### The proof

`candidate/compare` is a new agent-safe read (§15.4). Given the reversal and
the document it claims to have restored, it re-reads BOTH from bytes their
receipts re-verified and reports, per address, whether the text is equal.

It is in the runtime and not in the shell for one reason: a client comparing
two strings it had already fetched would be comparing its own memory and
calling it proof.

Two equalities, printed apart because they are different facts:

| | what it means | measured on the corpus form |
| --- | --- | --- |
| `regionsEqual` | the addresses hold identical text | **true** — this is the undo |
| `artifactEqual` | the two files are the same bytes | **false**, and expected |

`artifactEqual: false` is not a failed undo and the panel says so out loud:
`preedit` rewrites XML and rezips the package, so member order and zip metadata
move even when every character is restored. A UI that drew that as a defect
would be inventing one.

### 기록

The right column's second panel, under the queue. Lineage order (parents before
children, forks visible as forks), each row showing the candidate it was built
on, which rows are reversals of which, and which one is the head.

The head is a **choice**, and it is marked. The runtime keeps none (§15.7) —
a chain can fork and it will publish both branches — so pretending otherwise
would be the shell deciding what the file IS without saying so. Selecting a row
opens it read-only; it does not move the head, does not re-render the page as
that candidate, and does not change what an export writes. Export names its run
on the row itself.

---

## 후보본과 다름 — the layout echo, honestly (E1.2)

After an apply the page view is still showing a raster of the SOURCE. E1.2 asks
for the candidate. On this machine the candidate cannot be drawn: `renderPrepare`
answers `needs_hancom` from the frozen sidecar (P1), and would answer `com_busy`
on a machine with pyhwpx while the operator's own Hancom is open.

So the page does the honest thing rather than the impressive one:

- the source raster stays, under a banner reading **후보본과 다름 — 이 그림은
  원본 기준**, naming the candidate it is not showing;
- the addresses the receipts say changed are marked on the overlay — dashed, in
  the warning palette, deliberately not filled, because there is no content to
  show, only a statement that what is drawn underneath is out of date;
- **다시 그리기** calls `renderPrepare` on the candidate (`runId` is new, §15.6)
  and prints whatever the runtime answers — a candidate PDF, or the refusal.

What it will not do is paint the edited text onto the raster. The overlay's
rule is that every rectangle on the page came out of the renderer's own layout
(§12.2); a glyph placed at a guessed position breaks that rule in the most
convincing way available — a page that looks right and is not.

Gap 32 records exactly what a real echo needs: close P1 and the existing
`renderPrepare --runId` path produces one with no desktop change, or land
E2.1's own line breaker and draw it at `own-uncertified` grade with the grade
visible. Those are the two real echoes. There is no third.

---

## 자체 렌더 — the page a fresh install actually gets

The honest states above were all correct and, taken together, they added up to
a product that showed nothing. Trace what a first-time user meets: they open an
HWPX, press 페이지 보기, and get a refusal card. Not because anything is broken
— because the packaged sidecar carries no `pyhwpx`, so `renderPrepare` answers
`needs_hancom` on every machine that has not installed the office suite. The
marquee surface of this application was unreachable by default.

`engine/scripts/own_render.py` draws OWPML without Hancom, and §11.1c wires it
in as a third tier. What that changes here is not "there is now a picture" — it
is that there are now **three kinds of picture** and the user has to be able to
tell them apart at a glance, because they look identical.

**The badge is the feature.** Above the paper, before the ruler, in the reading
order a person needs: 한컴 렌더 · PDF 렌더 · 자체 렌더 · 미인증. It switches on
the runtime's own closed grade set, never on prose. 미인증 is inside the badge
TEXT rather than in a tooltip, because uncertified is the whole claim and a
badge reading only 자체 렌더 would read as a brand name.

**무엇을 못 그렸나** sits one click under the page and prints the sidecar's
`elements_skipped` verbatim — element, reason, count — rather than a summary. A
count on its own tells nobody anything they can check against their document;
`hh:bottomBorder@type=DASH ×3 · non-solid border stroked as solid` does. On the
corpus form the phase uses, that list has one entry (`hp:tbl@pos`, an anchored
table placed at its declared offset with no wrap computation), and the smoke
compares it row by row against what the runtime sent, not by counting rows.

**Tiers are never mixed on one page.** The overlay is drawn only when the
geometry and the raster came from the same renderer. Rects read out of a PDF,
laid over pixels our own renderer drew, would be the most convincing lie this
product could tell — every rectangle would look measured, and every one would
be in the wrong place. A mismatch is a stated state, not a silent omission.

**What an own-rendered page honestly cannot do.** The sidecar's `line_boxes`
record where each line was DRAWN, not what it said, so geometry comes back with
real rects and `mapping.state: "unavailable"`: no address, no seat, no caret
offset. Nothing is reconstructed by reopening the document and guessing which
line is which. A click therefore cannot open an edit — but it now says so,
naming the line, where before it returned in silence. On a PDF page a silent
unmapped click was a rare miss; on an own-rendered page every line is unmapped,
and silence would read as a dead page rather than as a stated limit.

That is the honest shape of the tier: **the page is usable to LOOK at and not
to edit on**, and the UI says which. Editing still goes through 본문 보기, which
never needed a render.

### The band, and the five things people do

The five actions of the ordinary loop were spread across four places — 열기 in
the title bar, 검사 in the band, 저장/내보내기 in the verification bar, 되돌리기
behind a tab in the other view, 승인 in the right-hand panel. Each placement was
locally defensible and the sum was a product you had to be taught. They are one
row now, first in the band, and each one says why it is unavailable instead of
being greyed in silence. The panels that own the detail still own it; these are
doors.

What moved out is everything a person LOOKS UP rather than watches: 글꼴, 글자
모양, 크기 into a 서식 menu, and the app zoom into a 화면 menu that names its own
shortcuts. `<details>` rather than popups, so nothing leaves the DOM for a
screen reader or for the evidence harness, and there is no z-index or
outside-click handler to keep in step.

**Two zooms, and they stopped being confusable.** 화면 (Ctrl+= / Ctrl+− /
Ctrl+0, persisted, webview-level) and the document's own scale used to sit side
by side in the strip as two percentages. The document one now lives in the page
footer with 폭 맞춤 and 쪽 맞춤 beside it, measured off the scroller's own box
through a `ResizeObserver` so a resized window keeps fitting. Neither refetches
anything: the raster is CSS-scaled and the overlay rects are page fractions
(§12.1), and the smoke proves it by comparing `geometryFetches` across a zoom
sweep — the one property no DOM assertion can see.

**Chrome.** Type scale up one step across the board (nothing under 12px
survives; the text people work in is 14px), 30px minimum on every button, 40px
band. The wide soft shadows are cut to thin elevation — they read as glow, and a
document tool that glows looks like a marketing page.

---

## Evidence

### 자체 렌더 — the tier-3 slice

| Step | Result |
| --- | --- |
| `tsc --noEmit` | 0 |
| sidecar build (all role checks) | 0 |
| `npm run tauri build` | 0 |
| `smoke.ps1` | **499 passed, 0 failed** across 14 phases |
| new phases | `own` 40 · `own-reattach` 3 |
| runtime suites + `tests/test_agenthost_compile.py` | 457 passed |
| `py_compile` sweep | 0 |
| privacy gate (`git archive HEAD` → `privacy_scan.py`) | HARD=0, WARN=45 (all pre-existing test fixtures) |

Screenshots: `page-own-render.png` (the badge, the open 무엇을 못 그렸나 list),
`page-own-render-150pct.png`, `page-own-render-seat-edit.png` (gap 34's answer:
a seat open in the inline editor on a page no Hancom drew — 지면 출처 자체 렌더 ·
미검증 in the status bar, `own_cell` as the derivation, and the legend's
렌더러 대조 — 확인 5 · 불일치 0 · 미확인 4), `toolbar.png`.

**Renderer at #215.** The sidecar in this build carries
`claude/engine-e2-converge` merged to its tip (#215) — table/box registration,
the bundled OFL faces (now actually shipped as PyInstaller data; see the new
`admrul` role check in `build.ps1` above), and the inline-table page-break
rule. The only third-party fidelity read on that tree is the private holdout,
tracker 02 (`docs/research/holdout-scoreboard-02.md`, aggregate numbers only,
document withheld): 18/18 pages exact, `ssim_inked_mean` 0.1295 → 0.1731,
`text_line_iou_mean` 0.5389 → 0.5847, `ssim_inked_min` crossing zero
(−0.0405 → +0.0273 — no page's ink is anti-correlated with Hancom's any
more). That is better and still not close to fidelity in absolute terms, and
it says nothing about the fonts this slice bundled: the holdout's own faces
were all installed on the machine that scored it (`bundled_character_share`
0.0), so `BundledFontMap` was never consulted and no fidelity number exists
yet for a document that actually falls through to it. None of this reaches
the UI — the badge still reads 자체 렌더 · 미인증, and `own-uncertified`
stays the only grade a fresh install can earn.

**Three defects the evidence found, all in the packaging and all invisible to
the checks that existed before it.**

1. **`--hidden-import PIL` does not collect Pillow's submodules.** The bundle
   had `_internal/PIL` on disk and `import PIL` worked; `from PIL import
   ImageDraw` raised, and the renderer answered *Pillow is not installed* — the
   exact shape of a tier that is present, advertised and dead. Fixed with
   `--collect-submodules PIL`. This is why the new role check renders a real
   corpus page rather than asking for `--version`: a smoke test of the import
   surface would have passed.
2. **`render_capability` built the tier-3 row without the engine root it was
   given.** It fell back to a path derived from `rt_engine.__file__`, which is
   correct in a checkout and outside the bundle in a frozen build, so a shipped
   install would have advertised `own.state: "no"` while carrying the renderer.
   Threaded from `RuntimeCore`; the regression test points a core at an empty
   root and requires it to say so, because no test that only runs from a
   checkout can see this.
3. **The `unmapped → draw nothing` overlay rule erased the whole overlay.** It
   was written when an unmapped line was a rare miss on a PDF page; on an
   own-rendered page every line is unmapped by construction, so the rule
   deleted all 30 line boxes and left a page that looked like one nothing had
   been measured on. Own-rendered lines are now drawn silently — no fill, no
   seat vocabulary, a hit target that states its own limit.

Two build-script fixes came out of the same run: the own-render probe goes
through `Start-Process`, because `$ErrorActionPreference = 'Stop'` turns the
renderer's ElementTree `DeprecationWarning` into a terminating error and failed
a build where the page had in fact been drawn; and the serve-role reap now
kills the one-dir bootloader's CHILD as well as the bootloader — the orphan the
existing comment in that file warned about, still holding build trees open
twenty minutes at a time.

**What this evidence does not cover.** The `toolbar.png` capture asks the 서식
menu to open and it does not survive to the captured frame, so the shot shows
the band closed. No tier-1 page was produced on this machine: `renderPrepare`
answers `needs_hancom` (the packaged sidecar carries no `pyhwpx`), so the
`hancom` grade is exercised only by the prepare suite with a substituted
converter, never live. The staged overlay session grades `pdf` rather than
`hancom` — correct, because a PDF a script staged is not one this machine's
Hancom produced — which means the 한컴 렌더 badge text has never been
photographed.

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

### Phase 5 — agent-native

Reproducing this needs one thing Phase 4 did not: `desktop/scripts/smoke.ps1`
points the RELEASE build at the repo's `agenthost/scripts/host.py` and
`modules/` through `RIGORLOOM_AGENT_HOST` and `RIGORLOOM_MODULES_ROOT`, the same
way it already pointed it at `mock_agent.py`. The bundled sidecar carries its
own copy of both since this slice, so the overrides pin the run to the branch's
source rather than to whatever was last frozen — which is the lesson from the
Phase 4 defect where the shipped sidecar predated its own branch.

```powershell
npx tsc --noEmit
cargo test --release                       # in desktop/src-tauri
python desktop/scripts/agent_roundtrip.py  # the protocol layer, no app needed
powershell -File desktop/sidecar/build.ps1
cd desktop; npm run tauri build
powershell -File desktop/scripts/smoke.ps1
powershell -File desktop/scripts/screenshots.ps1
python -m pytest tests/test_runtime_*.py tests/test_agenthost_*.py -q
```

| Step | Exit | Time |
| --- | --- | --- |
| `npx tsc --noEmit` | 0 | — |
| `cargo test --release` | 0 | **10 passed** (FIPS vectors, a real credential-store round trip, four config-composition rules) |
| `scripts/agent_roundtrip.py` | 0 | **38 checks, 0 failures** |
| `sidecar/build.ps1` | 0 | 25.9 MiB payload, four role checks |
| `npm run tauri build` (release) | 0 | 2m 33s |
| `scripts/smoke.ps1` | 0 | **274 checks, 0 failures** |
| `scripts/screenshots.ps1` | 0 | 18 images |
| `pytest tests/test_runtime_*.py` | 0 | 267 passed, 317 s |
| `pytest tests/test_agenthost_*.py` | 0 | 164 passed, 88 s |

Shell exe 8.48 MiB · NSIS installer 11.52 MiB · sidecar payload 25.9 MiB. The
shell grew 8.31 → 8.48 MiB across the credential store, the host spawn and tail,
the module registry reader and the window prefs; the sidecar grew 23.4 → 25.9
MiB, which is the `agenthost/scripts` tree plus 2.0 MiB of module declarations.

Smoke, by phase: `open` 55 · `reattach` 10 · `edit` 83 · `agent` 21 · `page` 16
· **`composer` 31 · `settings` 28 · `chrome` 26 · `chrome-reattach` 5**, plus
three checks the driver makes from outside the app: the orphan check, the
export hash comparison, and two new ones —

- **the credential sentinel appears in none of the 212 files the app wrote.**
  `smoke.ts` puts `NOT-A-REAL-KEY-SENTINEL-…` into the real Windows Credential
  Manager and drives the settings pane through it; `smoke.ps1` then reads every
  byte under the harness's app-data and run directories, as UTF-8 *and* as
  UTF-16, and requires the string in none of them. An in-app assertion can only
  see what the app chose to hand it; this sees the disk.
- **the window came back to 2880×1759 at (0,0) across a process boundary.**
  Compared between two launches' own reports rather than by asking the second
  launch about its own prefs — which would be self-fulfilling, because the
  startup save writes whatever was restored, so a restore losing a frame's
  pixels each launch would agree with itself forever.

The `composer` phase is the whole of Objective A against the real corpus form:
the composer is live and `composerBlocker` says why when it is not; a typed
instruction spawns a real Agent Host process; its 25-event log arrives
seq-ordered and gap-free from `run.started` to `run.finished`; its plan lands in
the SAME `draft`, validated over the shell's own connection, every op
`origin: "agent"`; the payload names `workspace/openPath, approval/resolve,
plan/apply, document/renderPrepare` as methods it can never compile; the
approval is `pending` and `requestedBy: "agenthost-mock"` when the run ends; no
candidate exists until a human resolves it; and the receipt then records
`requestedBy: agenthost-mock` / `approver: smoke-operator`. The conversation
survives a view switch byte-identically.

**`agent_roundtrip.py` is new, and it is not a duplicate of the smoke.** It
drives the same three processes the application drives — the Runtime on a host
connection, the Agent Host on an agent connection, the module registry — and
asserts the same properties without a release build. It is what to run when the
app cannot be built, and what to run FIRST when the smoke's composer phase
fails, because it says whether the failure is in the shell or underneath it. It
is also what caught the `Authorization: Bearer` defect above, by reading the
credential reference back out of the adapter instead of trusting the write.

Screenshots — `screenshots/`: the thirteen from Phase 4, plus `composer`,
`provider-settings`, `toolbar-text`, `toolbar-page`, `task-packs`. None are
staged. `composer.png` photographs a plan a real Agent Host process proposed
seconds earlier; `provider-settings.png` photographs a real `--capabilities`
answer with **no credential stored**, which is the state a new user meets, and
its capability table shows 예 / 아니오 / 모름 as the adapter actually declared
them.

### The seat slice — a clicked seat, a run button, and a font name

Three features the runtime stack unblocked in one merge: `cell_borders` seats,
`module/check`, and the declared typeface name.

```powershell
npx tsc --noEmit
cargo test --release                       # in desktop/src-tauri
powershell -File desktop/sidecar/build.ps1 # MUST precede the app build
cd desktop; npm run tauri build
powershell -File desktop/scripts/smoke.ps1
powershell -File desktop/scripts/screenshots.ps1
```

| Step | Exit | Result |
| --- | --- | --- |
| `npx tsc --noEmit` | 0 | — |
| `cargo test --release` | 0 | 11 passed |
| `sidecar/build.ps1` | 0 | 63.5 MiB payload, **ten** role checks |
| `npm run tauri build` (release) | 0 | 2m 29s warm |
| `scripts/smoke.ps1` | 0 | **360 checks, 0 failures** |
| `scripts/screenshots.ps1` | 0 | 22 images |
| `pytest tests/test_runtime_{geometry,module_check,typeface}.py pipeline/tests/test_module_registry.py` | 0 | 191 passed, 101s |

Smoke, by phase: `open` 55 · `reattach` 10 · `edit` 83 · `agent` 21 · `page` 16
· **`overlay` 44** · **`packs` 34** · `composer` 31 · `settings` 28 ·
`chrome` 33 · `chrome-reattach` 5, plus four the driver makes from outside.

**The sidecar's role checks went from six to ten**, and the four new ones are
the pre-merge-sidecar defect class applied to this merge rather than the last
one: `rt_module.py` present by name, `module/list` and `module/check`
advertised, `cell_borders` in the frozen runtime's own `derivationMethods`, and
the bundled module declarations readable through the runtime's registry with a
non-empty `discovered`. The third is the one that matters most:
`document/pageGeometry` was advertised by the *previous* bundle too and placed
zero seats on every form, so "the method exists" stopped being proof that the
marquee interaction can reach anything.

#### The `overlay` phase's seat numbers

Staged-real against `kstartup-jiwon-sincheongseo-saeopgyehoekseo`, whose own
Hancom render the corpus carries. The harness does **not** hardcode a page: it
asks the runtime page by page and settles on the one with the most seats, so
the phase exercises whatever the derivation actually placed. It found
`1:2 2:0 3:0 4:0 5:0 6:37 7:7 8:0` and chose page 6.

- **37 seats returned, 37 drawn, 37 editable, 37 clickable** — against 125
  editable fill regions in the form, 10 unique spans and 71 ambiguous.
- A `cell_borders` seat clicked → the inline editor opened **on the address the
  seat carries** (10-2-1, not a neighbour) → 지면 선택 read
  `표10 (2,1) · 그려진 선으로 잡음` with `data-derivation="cell_borders"` →
  the value committed → **one** `fill_cell` op at 10-2-1 in the review queue →
  the plan the runtime returned names that same cell. The approve/apply depth
  is `phaseEdit`'s and is not duplicated here; this proves the entry point
  reaches the same queue.
- The seat's resting background is `color(srgb … / 0.07)` with a border, read
  off `getComputedStyle` before any hover, and its cursor is `text`.
- **9 → 9 geometry fetches across the four-level zoom sweep.** The number is
  larger than the overlay slice's 2 because the page scan asked for eight pages
  before settling; the property is the same one and it still holds — zoom
  multiplies fractions the client already has and asks the runtime nothing.

#### The `packs` phase's numbers

`grant` and `report` against the same form, with an enablement written to the
run directory and pointed at by `RIGORLOOM_MODULES_ENABLED`.

- Both readers agree: registry `[grant,report,style]`, runtime
  `[grant,report,style]`, same `enabledFile` path.
- `grant` → **1 selected, 1 ran, 11 findings, all `severity: skipped`,
  `ok: true`, `partial: true`, `wantsUnsatisfied: [baseline]`, acceptance
  false.** The panel shows `pass` and 입력 부족 together and the header shows
  통과 아님, with the runtime's reason ("a checker ran without an input it
  declares it needs").
- **1 of 11 findings carried a Runtime address**; exactly 1 link was drawn, and
  clicking it selected 표11 (5,5) in 본문 보기.
- `report` → **12 selected, 0 ran, 12 skipped, every one `needs_workspace`**,
  `ranAll: false`, `acceptance: false`. Twelve 건너뜀 rows, each with the
  Korean reason line and the runtime's own English detail beside it. No row
  reads `pass`.
- The disabled `gongmun` pack's 실행 is disabled, and opening another pack
  drops the previous pack's verdict rather than leaving it under a new heading.
- From outside: the run left no `enabled.yaml` in the checkout.

#### The typeface, in the `chrome` phase

On `gianmun-byeolji-1ho`, `summary.typefaces.state` is `read`, the first fill
seat's charPr 11 resolves to **돋움체** in all seven languages, and the toolbar
shows that name — asserted to be a name the runtime declared for THAT charPr,
not merely a name. The T30 mismatch renders **본문은 한양중고딕** (charPr 23),
which is the §14 example verbatim.

#### Screenshots

Two new, both real: `page-seat-edit` (page 6 of the staged-real session, a
`cell_borders` seat open in the inline editor with a value part-typed, the
surrounding empty seats showing their resting tint, 지면 선택 reading
`표10 (2,1) · 그려진 선으로 잡음`) and `task-pack-check` (a genuine `grant`
report: 통과 아님, the runtime's counts, `check_grant pass 입력 부족`, and the
판정 안 함 findings with their codes). `toolbar-text` and `toolbar-page` are
re-taken because they were photographing whichever session the previous shot
had left selected — the same defect the `page-overlay-unavailable` capture had —
and now open their intended document unconditionally, which is why the toolbar
in them reads 돋움체 / 본문은 한양중고딕.

#### Five defects this slice's evidence found

1. **A seat click opened an edit with nowhere to type.** The overlay's editable
   branch had never fired — zero seats on every form — and the first click on a
   real one set `inlineEdit`, put `표10 (2,1)` in the status bar, and mounted no
   input: `SeatEditor` lived inside `TextView`, which 페이지 보기 does not
   mount. Fixed by extracting `SeatEditor` into its own module and mounting the
   SAME component in the seat's rect. Copying it would have been the defect;
   the whole claim of this feature is that there is one editor.
2. **`data-testid="pack-report"` named two different things.** The report
   container and the list row for the pack *called* `report`. Three assertions
   about the report's contents were silently reading the list row's blurb —
   they failed, which is the good outcome, but a looser assertion would have
   passed against the wrong element forever. The report's testids are now
   `module-check-*`.
3. **A capture saved a 314x50 title-bar sliver and reported success.**
   `shot.ps1` only checked `width > 0`, and the app's window rect is 314x50
   until `MoveWindow` fits it to the work area — even while the WebView inside
   already reports a 2880x1759 CSS viewport. A move that had not landed yet
   therefore produced a 1 KiB PNG filed under `task-packs.png`. A fragment filed
   as evidence of a panel is worse than a failed capture, because the failure is
   visible and the fragment is not. It now polls after the move and refuses
   anything below the editor's own 1024x640 minimum.

   The first attempt at that fix is worth recording because it was wrong in an
   instructive way: it enforced the minimum at SELECTION time, which rejects the
   real window — 314x50 before the move is the editor, not a helper — and
   captured nothing at all. Two runs and a window enumeration established that.
   Window selection separately stopped depending on `MainWindowHandle`: the
   process owns four top-level windows and the largest visible one now wins,
   with `MainWindowHandle` as the fallback. `screenshots.ps1` retries a failed
   shot once and gained `-Only` for re-taking one.
4. **`smoke.ts` contained a literal NUL byte**, in
   `.includes(detail ?? "\0")` as an impossible sentinel. git therefore
   classified the entire harness as BINARY: no eol normalisation despite
   `* text=auto eol=lf`, the file committed with CRLF while every sibling is
   LF, and every diff of it unreviewable — `grep` reports it as
   "Binary file … matches" to this day. Replaced with a visible sentinel
   string, which is also more honest about what the assertion means. The test
   commit carries the one-time normalisation the gitattributes always intended,
   which is why that file's diff is whole-file.
5. **The 준비 중 assertion outlived what it stood for.** The `chrome` phase
   asserted the pack panel says 준비 중; it no longer does, because it no
   longer is. Repointed rather than deleted, to the property the label stood
   for: the panel says what it can do and what it still cannot, and on a
   checkout with nothing enabled the 실행 control is present AND refused with
   its reason.

#### What this slice did NOT prove on this machine

- **No live conversion.** Every rect on every page in this evidence came from a
  PDF the corpus carries, staged the way `renderPrepare` would have staged it.
  The packaged sidecar has no `pyhwpx` (packaging gap P1) and a Hancom instance
  is open, so a live prepare answers `needs_hancom` or `com_busy` — which the
  overlay phase's LIVE leg photographs and asserts, rather than skipping.
- **The finding-to-cell navigation rests on one finding.** 1 of 11 was
  addressable. The link is drawn for exactly the addressed ones and not drawn
  for the other ten, which is the property that matters, but "exactly one" is a
  thin sample and gap 21 is why.
- **`module/check` was never given a `runId`.** The shell always calls it
  against the session source, so every document checker in this evidence ran
  `partial` with `wantsUnsatisfied: [baseline]`. A candidate would supply the
  baseline by construction (§13.3) and produce a complete verdict; the shell has
  no control that asks for one yet.
- **No workspace checker ran, anywhere.** Twelve of eighteen cannot, by
  construction. What is proven is that they are drawn as skipped.
- **IME composition on the page surface is not separately measured.**
  `scripts/ime.ps1` types real scan codes into the tree's field. The page mounts
  the same `SeatEditor` component, so the behaviour is shared by construction
  rather than by test — the harness has no page-surface leg.
- **One renderer, one machine.** Hancom Office 13.0.0.2986, a single
  200 %-scaled display. Seat placement tolerances against other Hancom versions
  are untested, and §12.6 already records that.

### The caret slice — typing in a line, and what the evidence found

Reproduced from a clean build on the operator machine (Windows 11, one Hancom
Office 13.0.0.2986 install, open throughout — the runtime never touched it).

| step | result |
| --- | --- |
| `npx tsc --noEmit` | exit 0 |
| `sidecar/build.ps1` (PyInstaller one-dir) | exit 0, 60 s |
| `npm run build` (tsc + vite) | exit 0, 15 s |
| `npx tauri build` (cargo release + NSIS) | exit 0, 421 s |
| `scripts/smoke.ps1`, 11 phases | **396 checks, 0 failures** (was 360 at Phase 6) |
| `scripts/ime.ps1 -Surface both` | **IME PASS**, 2 surfaces, real 두벌식 scan codes |
| `scripts/screenshots.ps1 -Only page-caret-edit` | `page-caret-edit.png`, 2880×1704 |
| `tests/test_runtime_geometry.py` | 86 passed |
| `tests/test_runtime_typeface.py` | 14 passed |
| every other `tests/test_runtime_*.py` | 257 passed, 0 failed |
| `tests/test_agenthost_compile.py` | 34 passed |
| `scripts/py_compile_sweep.py` | 125 files, 0 failures |
| `privacy_scan.py` over `git archive HEAD` | **HARD=0**, WARN=43 (all pre-existing corpus fixtures) |

**The sidecar's role check gained a leg.** `serve role: sub-line offsets on
spans[].charX, unit normalized` — the frozen runtime is asked whether it
extracts per-character boxes before the bundle is allowed to ship, because a
bundle that does not would answer every click by snapping to the front of the
line and would do it *silently*: the field opens, the caret sits at offset 0,
and nothing on screen is wrong except the position.

**What the smoke measured on the page it exercises** (page 6 of the seated
corpus form, the page the runtime seats most heavily):

- 86 lines, all 86 resolving per-character offsets, 634 characters.
- 37 seats, all 37 editable — unchanged.
- 10 uniquely-mapped paragraph lines, all 10 carrying offsets, all 10 drawn as
  caret targets with `cursor: text` and none of them dressed as a fill seat.
- A caret placed on the first one tried: `문단 182`, offset **5** into a
  7-character line, with the browser's own `selectionStart` at 5.
- A real `MouseEvent` at a second position in the same line: offset **6**, the
  number `charX` names for that x. Two positions, two offsets — the check that
  the overlay's `clientX` → page-fraction arithmetic is right and not
  accidentally always zero.
- A refusal, provoked on purpose: `문단 338` holds two runs, so **no caret was
  placed**, `multi_run` reached the status bar, and the queue did not move.
- The typed sentence became one `set_run` op at `(atPara 182, run 0)`, in the
  same queue as a seat fill, and the plan the *runtime* returned named that
  same paragraph and run.
- 글꼴 read 맑은 고딕 for charPr 21, from the document's own header. 크기 read
  `14.04pt` with `data-source="render"` — the size the PDF was drawn at, not a
  declaration the header does not make.

**IME, on the page surface, by test rather than by construction.** Phase 6
recorded the page field as "shared by construction, not by test", and
construction is not evidence when the field is mounted in an absolutely-
positioned overlay over a raster with its selection set programmatically.
`ime.ps1 -Surface page` stages a rendered session, walks pages and lines until
the runtime places a caret, and drives 두벌식 **scan codes** — not injected
Unicode, which would bypass the IME and prove nothing — into it:

    editor open at p:2
    caret at character 12, page 1
    [PASS] the IME composed into the shipped editor
    [PASS] Enter committed the composed value into the plan queue
    [PASS] the field saw real composition events, not injected characters
    [PASS] the composed value queued a set_run op

#### Six defects this evidence found

1. **The caret worked; everything around it did not.** The first full run was
   377/15. Every one of the 15 failures was in the code around the caret, and
   the caret itself was right on its first real page.
2. **A renamed testid broke a Phase 4 check.** `queued-0-1-2` became
   `queued-c:0:1:2` when the queued-value component learned a second op kind,
   and "the document itself shows the pending value in place" failed while the
   value was on screen the whole time. The cell spelling is restored.
3. **The harness was impatient, and it read as the feature being wrong.** The
   check driving a real `MouseEvent` waited 300 ms; behind that click is
   `document/readRegion`, which runs `form_inspect` as a child process. It
   reported `caret none`, which looks exactly like the component computing the
   wrong offset. Twelve downstream checks were failing on the empty caret that
   left behind rather than on themselves.
4. **`runOp!.opId` threw and killed the phase**, so eight checks never ran and
   the harness reported a TypeError where it should have reported eight results
   naming the cause.
5. **`ime.ps1` lost its UTF-8 BOM when it was rewritten**, and PowerShell 5.1
   read its Korean strings as ANSI and failed to parse the file at
   `[ValidateSet(...)]` — an error pointing 180 lines away from the cause.
   Every other script in `scripts/` carries a BOM; this one now does again.
6. **A PowerShell function emits everything it does not consume.** `$failed +=
   Invoke-Surface $which` collected stray objects and then tried to add an
   array to an integer — *after* the seat surface had already printed three
   `[PASS]` lines. `build-clean.ps1` carries a note about the same trap. The
   counter is script-scoped now.

And one found by reading rather than by running, which is worth saying because
the harness could not have caught it: an ambiguous span's candidate list very
often holds one anchor and one cell (§12.4), and choosing the anchor half
answered 값을 넣는 자리가 아닙니다 — correct until a paragraph line became
somewhere a person types. The smoke's ambiguous click asserts that nothing is
queued and then dismisses, so it never chose a candidate at all.

#### What this evidence does not cover

- **One page of one form.** The caret checks run on whichever page the runtime
  seats most heavily, which is page 6 of one corpus form. The corpus-wide
  numbers (314 of 365) come from the runtime tests and an offline measurement,
  not from the app.
- **A wrapped paragraph.** Every corpus body paragraph is a single rendered
  line, so `run_text_differs` was never provoked by a real wrap — only
  `multi_run` was. Gap 25.
- **A filled document.** Every corpus render is a blank form (§12.6), so
  whether a caret lands correctly on a page whose paragraphs already carry
  user-entered text is untested here.
- **A machine that can render.** This one cannot: `renderPrepare` answers
  `needs_hancom` because the frozen sidecar carries no pyhwpx (packaging gap
  P1), so every page in this evidence is the corpus's own staged Hancom render.

### 한글 오버레이 — the overlay slice

```powershell
npx tsc --noEmit
cargo test --release                       # in desktop/src-tauri
powershell -File desktop/sidecar/build.ps1 # MUST precede the app build
cd desktop; npm run tauri build
powershell -File desktop/scripts/smoke.ps1
powershell -File desktop/scripts/screenshots.ps1
```

The sidecar rebuild is not optional for this slice and the build script now
enforces why: it refuses unless the frozen runtime carries `rt_geometry.py`,
advertises `document/pageGeometry`, and reports its rasterizer present. Those
three are the Phase 4 defect ("the packaged sidecar was the pre-merge runtime")
turned into build failures.

The smoke's `overlay` phase needs one thing the others do not: a session on disk
that already has a rendered PDF. `scripts/stage-rendered-session.py` puts one
there, and the header of that file is the argument for why it is evidence
rather than staging — short version, the PDF is `com_backend.py convert` output
against the very HWPX the session is opened from, under Hancom 13.0.0.2986,
recorded in `docs/research/xc1-conversion-bench.md` §4. What is substituted is
*when* Hancom ran, not what it produced, and every rect, address and count the
app then shows is read by the Runtime out of that file.

| Step | Exit | Result |
| --- | --- | --- |
| `npx tsc --noEmit` | 0 | — |
| `cargo test --release` | 0 | 10 passed |
| `sidecar/build.ps1` | 0 | 63.2 MiB payload, **six** role checks |
| `npm run tauri build` (release) | 0 | 5m 52s cold, 2m 38s warm |
| `scripts/smoke.ps1` | 0 | **310 checks, 0 failures** |
| `scripts/screenshots.ps1` | 0 | 20 images |

Shell exe 8.49 MiB · NSIS installer 25.26 MiB · sidecar payload 63.2 MiB. The
sidecar grew 25.9 → 63.2 MiB and the installer 11.52 → 25.26 MiB, all of it
PyMuPDF. That is a large price for one wheel and it buys the only thing that
makes 페이지 보기 a feature rather than a claim; it is recorded here rather than
buried so that a future slice can argue with it.

Smoke, by phase: `open` 55 · `reattach` 10 · `edit` 83 · `agent` 21 · `page` 16
· **`overlay` 34** · `composer` 31 · `settings` 28 · `chrome` 27 ·
`chrome-reattach` 5, plus the three the driver makes from outside the app.

The `overlay` phase's own numbers, which are the interesting part:

- LIVE — geometry `available: false`, reason `needs_conversion`, **0 overlay
  elements in the DOM, 0 spans, 0 seats**, and the existing unavailable state
  carrying the runtime's own detail. Nothing was drawn where nothing was known.
- STAGED-REAL — source `prepared_pdf`, mapping `ran` through
  `check_residue.normalize_text`, **3 unique · 13 ambiguous · 10 unmapped of 26
  lines · 0 seats**. Drawn: 3 unique overlays, 13 ambiguous overlays, 0 seats —
  each count equal to the runtime's own, and 10 unmapped lines drawn as nothing.
- **2 → 2 geometry fetches across a four-level zoom sweep** (1.4 / 2.0 / 0.8 /
  1.0), overlay still drawn, rects still expressed as percentages
  (`7.0953%` wide in a stage of `794.182px`).
- An ambiguous click resolved to 2 candidates with a **null address**, listed
  both with no preselected row, left the queue at 0 ops and the plan at none,
  and put `후보 2개 — 직접 선택` in the status bar. Dismissing changed nothing.
- **9 editable fill regions in the form · 0 seats placed · 0 clickable on the
  page.** Runtime gap 18.

Screenshots — `screenshots/`: the eighteen from Phase 5, plus `page-overlay`
(the staged-real page with the runtime's own rects on it and the candidate
chooser open over a genuine two-way ambiguity) and
`page-overlay-unavailable` (the same document with nothing substituted, which
is a refusal). Both are in the directory on purpose. A screenshot set that
showed only the working case would advertise a capability this machine does not
have.

*Superseded in part by the seat slice:* the staged session is now the form the
runtime actually seats, so `page-overlay` and `page-overlay-unavailable` are two
different documents rather than one — the first is the seated form's page 1, the
second is still this machine refusing `com_busy` on the form the harness opens
live. Both claims each capture makes are unchanged; only the pairing is.

### Three defects the overlay evidence found

1. **The frozen sidecar could not have drawn a page at all.** No PyMuPDF in the
   bundle, so every packaged install answered `rasterizer_missing` to every PDF.
   Fixed in the build; three new build-time role checks make the class of
   failure unrepeatable. See the commit for why this is the same defect as
   Phase 4's pre-merge sidecar wearing different clothes.
2. **`needs_hancom` guidance asserted something the runtime never said.** It
   read "이 기계에는 변환에 쓸 한컴오피스가 없습니다" — printed directly beneath
   the runtime's own words saying the real problem was a missing `pyhwpx`, on a
   machine with Hancom 2024 installed and running. The reason line is the fact;
   the guidance now says what to do about it and claims nothing about the
   machine.
3. **The first `page-overlay-unavailable` capture photographed a working page.**
   The shot phase only opened the corpus when nothing was already active, and by
   then `lastSessionId` was the staged session the previous shot had selected.
   A capture named for a refusal that shows the success case is the one kind of
   evidence that actively misleads, so the live shot now opens the HWPX
   unconditionally.

Plus a layout defect the first capture exposed rather than a logic one: the
legend under the page inherited `.raster-note`'s single-line flex row and
squeezed its counts into a four-character column. It wraps now, and the counts
never break.

### 되돌리기 — the undo slice (E1.4 + E1.2)

Reproduced on the operator machine (Windows 11, one Hancom Office install open
throughout — the runtime never touched it). The runtime changed in this slice,
so the sidecar rebuild is not optional and the privacy gate runs over a real
`git archive` of HEAD rather than over the working tree.

```powershell
npx tsc --noEmit
powershell -File desktop/sidecar/build.ps1     # runtime changed: MUST precede
cd desktop; npx tauri build
powershell -File desktop/scripts/smoke.ps1
powershell -File desktop/scripts/screenshots.ps1
python -m pytest tests/test_runtime_*.py tests/test_agenthost_compile.py -q
python scripts/py_compile_sweep.py
git archive HEAD | tar -x -C <scratch>; python pipeline/scripts/privacy_scan.py <scratch>
```

| step | result |
| --- | --- |
| `npx tsc --noEmit` | 0 |
| `sidecar/build.ps1` | 0 · 69.2 MiB payload · `candidate/compare` advertised |
| `npx tauri build` (release) | 0 · 3m 34s |
| `scripts/smoke.ps1` | 0 · **455 checks, 0 failures** |
| `scripts/screenshots.ps1` | 0 · 25 images |
| `pytest tests/test_runtime_*.py` | 0 · **413 passed**, 382 s |
| `pytest tests/test_agenthost_compile.py` | 0 · 35 passed |
| `scripts/py_compile_sweep.py` | 0 · 125 files, 0 failures |
| `privacy_scan.py` over `git archive HEAD` | 0 · **HARD=0**, WARN=43 |

Shell exe 8.51 MiB · NSIS installer 26.55 MiB.

Smoke, by phase: `open` 55 · `reattach` 10 · `edit` 83 · `agent` 21 · `page` 16
· `overlay` 80 · **`undo` 59** · `packs` 34 · `composer` 31 · `settings` 28 ·
`chrome` 33 · `chrome-reattach` 5, plus the checks the driver makes from
outside the app.

#### How the inverse is proven, in the run

Nothing below is the shell comparing two strings it was already holding.

- The pre-edit value is **read**, not remembered: `document/readRegion` against
  the parent named in the receipt, and the answer states its own `subject`
  (`{"kind":"candidate","runId":"fc769a9ebc69…"}` in the run).
- The chain is real. A second edit binds the FIRST candidate's bytes
  (`f5fb2fa4d56d` vs `f5fb2fa4d56d`) and the chained candidate still carries
  the first edit — the two-siblings defect, asserted in the UI.
- The reversal is a proposal: it lands in the queue as 되돌리기 제안 declaring
  `reverses.runId`, chained onto the HEAD, and applies as one MORE candidate.
  All three candidates stay listed.
- The proof comes from the runtime. `candidate/compare` reported
  `regions: [{"address":"0:0,14","equal":true}]` — **`regionsEqual: true`** —
  and `artifactEqual: false`, printed apart, because `preedit` rezips the
  package and an undo restores the value, never the bytes.
- Two independent re-reads agree: `readRegion` on the reversal returns the
  pre-edit value, and the newer edit ON TOP of the reversed one survived.
- The receipt records both `reverses` and `base`, so the claim outlives the
  session.
- 기록 draws the whole lineage (3 rows, head marked 현재, parents named), and
  selecting an older candidate opens it read-only without moving the head.

The E1.2 half runs against the staged rendered session: after an apply the page
keeps the SOURCE raster under 후보본과 다름 — 이 그림은 원본 기준, names the
candidate it is not showing, marks the changed address on the overlay
(**1 rect for `c:10:2:1`**, page 6, 37 seated of 99 clean), refuses to paint the
new text onto the raster, and 다시 그리기 lands on this machine's real answer:
`needs_hancom — pyhwpx is not importable`.

Screenshots — `screenshots/`: the twenty-three from the seat slice, plus
`history-reversal` (기록 with a three-row chain, the middle row marked 되돌려짐
and the head marked 되돌리기, over the runtime's own 되돌리기 확인됨 verdict and
its 파일 전체 해시 일치: false line) and `page-candidate-differs` (the stale page
naming candidate `a03fd55fbebd` and its four changed addresses). Neither is
staged.

### Three defects the undo evidence found

1. **A render loop took the whole root down on every apply.** `layoutEcho` is
   read through `useSyncExternalStore`, so its result has to be
   reference-stable while nothing changes — and `s.changedByRun[head.runId] ??
   []` allocated a fresh array every call. The identity check below it never
   matched, every snapshot read produced a new object, and React gave up with
   #185. The window where that default is taken is exactly the moment after an
   apply, which is the moment the echo exists for. One shared `NO_CHANGES`
   closes it; the comment above the function had already named the hazard.
   It cost the `undo` phase seven checks and hung `open` outright.
2. **The echo check was a coin flip.** With the loop gone it failed honestly:
   the banner named one changed address and the overlay marked zero rectangles,
   and the overlay was right — the form's first clean cell sits outside the
   drawn page, so there was no rectangle to mark. The seat now comes from the
   intersection of clean-per-`form_inspect` and seated-on-the-page-being-drawn,
   and an empty intersection is reported rather than passed over.
3. **The 기록 capture photographed a refusal and would have been captioned as a
   reversal.** All captures share one runtime root, so by the time the history
   shot ran, the session already held a candidate an earlier capture had
   applied; re-writing the same two cells was refused (`backend_refused` — the
   shell sets `overwrite` only on an inverse), `applied` stayed null, and the
   reversal block never ran. The capture takes seats no earlier capture touches
   now. The collision itself is still open for every capture after the first
   apply: `screenshots.ps1` clears its app-data once per RUN, not once per
   capture, while the captures are written as though they were independent. The
   real fix is a root per capture, which is a harness change with a staging
   step to move, not a product one.

### Four defects the Phase 5 evidence found

1. **The credential reference would have authenticated against nothing.**
   `CredentialRef` defaults to `Authorization: Bearer <value>`; the Messages API
   wants a bare `x-api-key`. The config `compose_config` wrote omitted `header`
   and `scheme`, so it *looked* right and the desktop would have sent the wrong
   header to the right endpoint — a failure that only shows up on a live call,
   which is precisely the call this run could not make. Caught by
   `agent_roundtrip.py` reading the reference back out of the adapter instead of
   trusting the write, which is the whole reason that harness reads rather than
   asserts on its own inputs. Fixed per provider and pinned by a `cargo test`.
2. **The UI had guessed a credential vocabulary.** It looked for
   `present`/`absent`; the adapter answers `not_required` / `configured` /
   `missing` / `unsupported`. Same harness, same round. The settings pane now
   renders the adapter's closed set verbatim, beside the OS store's own
   present/absent, because the two can disagree.
3. **`build.ps1` left its own probe running and hung anything waiting on it.**
   The serve-role probe is `--noconsole` and this script does not job-confine it
   (that is `jobkill.rs`'s job, inside the app). `Start-Process -Wait` returned,
   the survivor kept the script's process tree open, and a background shell
   waiting on the tree saw a build that printed `exit 0` and then sat for
   fifteen minutes. Observed, not theorised. The probe is reaped explicitly now.
4. **The ruler was measuring nothing.** Placed at the top of the scroller, it
   sat above the refusal card explaining why there was no page — a ruler not
   touching the page it measures is decoration. It renders directly above
   whichever page-like thing is drawn now, raster or geometry figure.

And three assertions were **inverted or repointed rather than deleted**, for the
reason Phase 4 established: reality moved under them and deleting them would
have quietly reduced coverage. `composer present and disabled` became `present
and live, and it explains itself rather than sitting grey`; the two timeline
checks switch to the 문서 기록 tab first, because the property is unchanged and
only where a person stands to see it moved.

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

- **No live provider call was made.** This is the big one, and it is exactly
  the gap this slice was supposed to make closable rather than close. The
  Anthropic adapter is tested only against a local fake it starts and stops;
  `--live-smoke` is implemented and its keyless refusal is tested; and the
  credential UI the agenthost README named as the missing prerequisite now
  exists. What did NOT happen is one real request to `api.anthropic.com`,
  because that needs a key this run had no business having. Everything the
  desktop asserts about the Anthropic provider is therefore about its
  *description of itself* (`--capabilities`, which is a local describe) and
  about a credential REFERENCE resolving — never about a completion coming
  back. The composer's round trip is proven end to end with the MOCK provider
  and with nothing else.
- **The credential store is exercised with a sentinel, never a real key.**
  `credstore.rs`'s test writes `not-a-real-key-…` to the real Windows
  Credential Manager, reads it back, asserts the status payload does not
  contain it, and deletes it. The smoke does the same through the UI with
  `NOT-A-REAL-KEY-SENTINEL-…` and `smoke.ps1` then greps every byte the app
  wrote for that string. What this proves is that a value put where a
  credential goes does not leak; what it does not prove is anything about a
  real key's lifetime in a real session.
- **Streaming is unproven because it is unreachable.** No test asserts that a
  streamed chunk reaches the UI, because `AgentHost.run` never calls
  `provider.stream()` — see agenthost gap 1. The `provider.stream.chunk` branch
  in `Conversation.tsx` is written and dead.
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
CLOSED in Phase 3; gaps 16 and 17 CLOSED by the runtime stack this build merged,
and 18 is now a number rather than a zero. All of them are consumed here; the
rest stand.

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


### New in Phase 5

16. ~~**No typeface name anywhere on the wire.**~~ **CLOSED** by §14. The
    suggested shape was adopted almost exactly and improved on: `form_inspect`
    publishes `charpr_faces` (charPr id → {lang: face}) and `rt_session` reads
    it into `summary.baselineCharPr.face`, `summary.blackCharPr.face`,
    `regions[].charPrFace` and `regions[].charPrSuggestedFace`. Two things the
    suggestion did not anticipate and the wire got right: the face is **per
    language**, because Hangul's font dialog is and the corpus 기안문 declares
    different 한글 and 영문 faces; and `summary.typefaces.state` is a separate
    field, so "this document names no face for this charPr" and "nothing looked"
    cannot be confused. The toolbar consumes both. What is still absent is a
    seat's own point size (§14.1) and any way to *set* a face, which is a
    `preedit` question rather than a protocol one.

17. ~~**No way to run a module's checker against a session.**~~ **CLOSED** by
    §13, `module/list` + `module/check`. The suggested shape was right about
    the wire and wrong about one thing worth recording: both methods are
    **agent-safe**, not host-only. The argument that changed it is in §13.1 —
    the checker contract is a verdict producer, the subject is a scratch copy
    by construction, it decides nothing, and the authority to run a module at
    all is enablement, an install-time operator act no wire call can reach.
    Host-only would have put the only quality signal an agent could use on the
    far side of the gate it exists to inform. The 작업 팩 panel has a 실행
    button now; what it still cannot do is run the twelve workspace checkers,
    which is gap 20 below rather than a leftover of this one.

### New with the overlay

18. **`document/pageGeometry` seats 73 of 473 fill regions, and the rest are
    structural.** Recorded here as measured twice, because the two measurements
    are the interesting part.

    *Before `cell_borders`:* **10 forms, 51 pages, 473 editable fill regions, 0
    seats, 0 unique spans whose address is an editable cell.** Not "few". None.
    Matching is by text and an empty fill seat has no text, so the only cells
    that ever matched were the static labels around it, and interpolation only
    reached a seat immediately after a uniquely mapped label in the same row —
    which real Hancom layout does not provide.

    *After:* **73 seats, all `cell_borders`**, from rebuilding the drawn grid
    out of Hancom's own stroked segments rather than looking for a text
    neighbour. The suggested fix ("find the drawn grid, not a neighbour") is
    what landed. The distribution is lumpy and honestly so: 55 on
    `kstartup-jiwon-sincheongseo-saeopgyehoekseo`, 0 on the two forms ruled with
    underlines rather than boxes. On the page this build's smoke exercises, all
    37 seats are addresses the editor opens — the marquee interaction is real
    and proven end to end.

    **What remains open is the other 400**, and §12.6 attributes them: 148 sit
    in tables with no anchor anywhere, truncated 30-character previews cannot
    establish a correspondence (only refute one), unruled forms correctly place
    nothing, the walk stops at a gap or a merged cell, and alignment is per
    page. Also still true: **0 unique SPANS map to an editable cell**, so every
    clickable target on a page today came from the border scan and none from
    text matching. *Suggested shape for the largest block:* an anchor does not
    have to come from a span. A table whose declared cell text is unique within
    the page could anchor on its own geometry — same `cell_agrees` check, no
    span required — which is where the 148 live.

19. **Ambiguity is the normal case, not the exception.** Across the same
    corpus, `ambiguous` outnumbers `unique` roughly six to one (saeopja: 586
    ambiguous against 34 unique; moel-2025: 162 against 2). A form is full of
    repeated boilerplate — `서명`, `직위(직급)`, `(   )` — and matching by
    normalized text alone cannot separate them. This is not a defect in the
    T41 discipline; refusing to pick is right. It does mean that a UI which
    treats ambiguity as a rare interruption would be wrong about this domain,
    which is why the overlay draws it as a first-class permanently-visible
    state rather than a warning. *Suggested shape:* nothing on the wire yet —
    but if a span carried its page-order position relative to its candidates,
    a chooser could at least order them by proximity without picking one.

### New with the seat slice

20. **Twelve of the eighteen checkers have no session to run against.** The
    Runtime has no *workspace* concept at all, so every `subject: workspace`
    checker — all twelve of `modules/report`, plus `style`'s one — answers
    `skipped: needs_workspace` on any document session, by construction and
    correctly. Measured on this machine rather than read off the manifests:
    running `module/check` on `report` selects 12, runs 0, skips 12, and
    reports `acceptance: false`. That is the honest answer and the panel draws
    it as such, but it also means the report-pipeline half of 작업 팩 is a
    panel that can only explain why it did nothing. §13.7 names the fix and
    this build agrees with it: *a workspace session kind*, not a directory
    guessed from a document — guessing would hand an `.hwpx` path to a
    workspace checker and produce a verdict about an empty directory that reads
    exactly like a finding about the user's file.

21. **A checker's location is usually not an address.** `module/check`
    translates a finding's place into the Runtime's own addressing where a
    translation exists and returns `null` where it does not, which is right.
    On this machine's run that is **1 of 11 findings** — the other ten carried
    no `at` the translator could read, so the panel shows the checker's own
    location as text and offers no link. The gap is not in the translator; it
    is that most checker rules report a *rule* outcome rather than a place.
    *Suggested shape:* nothing on the wire — this is a `checker_base` contract
    question about what a `Finding` is obliged to carry, and it belongs to the
    modules, not to the protocol.

22. **`--pack`, `--vocabulary` and `--mode` are unreachable.** Every checker
    runs on its own defaults because a pack instance is operator state
    (`personalization_ctl`) and `policy/set` is still GAP, so `module/check`
    passes none of them. The panel says so in 아직 없는 것. Recorded as §13.7
    already does; repeated here because it is the second thing a person asks
    after pressing 실행 once.

### New with the caret

23. **`set_run` replaces a whole run, so an offset positions the cursor and
    nothing else.** The caret lands on a measured character, and then the
    operation that carries the edit rewrites the entire run
    (`engine/scripts/preedit.py:2464`). For the 314 corpus lines where the run
    IS the line that is exactly right and invisible to the user. It stops being
    invisible the moment a paragraph is long enough that a person expects to
    edit a clause without the whole paragraph appearing in the review queue's
    `before → after`. The queue is honest about it — it shows the whole run
    changing, because the whole run does change — but it reads as a heavier
    edit than the person made. *Suggested shape:* not a new operation. A
    `set_run` whose `text` differs from `expect` only in a substring could
    carry the substring bounds for the reviewer's benefit, the way
    `--at-cell-expect` already carries an exact-byte precondition; the write
    stays run-wide and only the presentation gets finer.

24. **51 of 365 mapped paragraph lines refuse a caret, and the refusal costs a
    round trip.** A line's run count is only knowable from
    `document/readRegion`, so the overlay draws every uniquely-mapped paragraph
    line as a caret target and finds out on click whether it is one. That is
    the honest ordering — the alternative is asking for every paragraph's run
    inventory on page load, which is 119 addresses on one corpus form — but it
    means a person can click something that looks clickable and be told no.
    The refusal names itself, which is the mitigation, not the fix.
    *Suggested shape:* `document/pageGeometry` could carry `runCount` on a
    span whose address is a paragraph, from the profile it already holds — the
    span mapping knows the `at_para`, and `full_text` is the only thing missing.
    Then the overlay draws the 51 as inert from the start.

25. **A caret cannot cross a line.** Geometry is per line and `set_run` is per
    run, so a paragraph that wraps onto several rendered lines maps each line
    to the same run and the mapping refuses all of them
    (`run_text_differs` — the line's text is a fragment of the run's). On the
    corpus this is 0 lines, because these are forms and their body paragraphs
    are single-line; it will not be 0 on a report. *Suggested shape:* this is
    the E2 line-breaker's question, not the caret's. Until Rigorloom can break
    lines itself it cannot know that three rendered lines are one paragraph
    except by string containment, which is the guess §12.3 refuses.

26. **The size over a caret is the renderer's, because the header has no
    other.** §14.1 says a run's charPr carries an id and a name but no point
    size. So 크기 above a caret shows `spans[].sizePt` — what the PDF was drawn
    at — labelled 지면에서 잰 값 to keep it apart from the header's declared
    baseline. It is a real measurement and it is not the document's own
    declaration, and on a document with no render there is no size for a run at
    all. *Suggested shape:* `charpr_faces` is a join the profile already does;
    the same join could carry the charPr's `height` where the header declares
    one, which would make the control's two sources agree about what they are.

### New with undo (E1.4)

27. **The runtime has no head, so the shell decides what the document IS.**
    `plan/propose` records a `base` and the receipt keeps it, but nothing in
    the runtime says which candidate a session is *on* — and a chain can fork,
    because two plans may legally name the same base and the runtime will
    publish both. So `head` is shell state. It is made visible rather than
    hidden: 기록 marks the head row 현재, moving it is a click, and an export
    always names the run it is writing. The cost is that two windows on one
    root can hold two different heads and neither is wrong.
    *Suggested shape:* not a `head` field — that would be the runtime deciding
    a product question. A `candidate/list` that reported `children` per row
    would let a client detect a fork and say so, which is the part a client
    cannot derive cheaply today (it walks every `base` itself).

28. **`reverses` is a recorded claim, not a checked one.** `plan/propose`
    takes it and the receipt keeps it; nothing verifies at propose time that
    the ops actually undo anything. Proving it there would mean executing
    them, which is exactly what `plan/validate` may not do (§3.7). So the
    proof is after the fact, from `candidate/compare`, and the UI is careful:
    the queue says 되돌리기 제안 (a claim) and only the 기록 panel says
    되돌리기 확인됨, and only after the runtime answered. A candidate whose
    `reverses` is a lie is therefore possible and would be caught by its own
    proof failing. *Suggested shape:* nothing to build. Worth a line in §15
    saying the claim and the proof are separate on purpose.

29. **Only `fill_cell` and `set_run` can be inverted.** The inverse of an
    operation is "write the previous value", and the previous value is
    readable only where the operation targets an address `readRegion` can
    name. `delete_guides` deletes paragraphs chosen by colour or charPr id and
    there is no address to read back, so a candidate containing one is refused
    a 되돌리기 제안 by name (`not_invertible`) rather than being offered a
    button that would produce a partial undo. *Suggested shape:* an inverse
    for `delete_guides` needs the deleted paragraphs' content in the receipt,
    which is a receipt-size question before it is an undo question.

30. **A reversal's proof is byte-exact, so whitespace is a difference.**
    `candidate/compare` reports `normalizer: "exact"`. There is no
    `check_residue.normalize_text` on that path, so an inverse that restored
    "가 나" as "가  나" would be reported as NOT equal. That is the right
    direction to err for an undo, and it is stated in the UI rather than
    quietly normalised away.

31. **The redo stack is per queue and does not survive an apply.** Tier-one
    redo re-enqueues the exact op object that was removed, which is what makes
    it exact — and the moment the queue becomes a candidate that op is inside
    a published document, so offering to re-enqueue it would put the same edit
    in twice. The stack is therefore cleared on apply and on a document
    switch. There is no cross-apply redo and there should not be one: redoing
    an applied edit is proposing it again, which is what the editor already
    does.

### New with the layout echo (E1.2)

32. **After an apply the page is the SOURCE's raster, and no honest redraw is
    available on this machine.** `document/render` with a `runId` on an HWPX
    candidate answers `needs_conversion`, and the conversion is
    `renderPrepare`, which this build's frozen sidecar refuses `needs_hancom`
    (P1) — and which would refuse `com_busy` on a machine that had pyhwpx
    while the operator's own Hancom was open. So 페이지 보기 shows the source
    raster with a 후보본과 다름 — 이 그림은 원본 기준 banner, marks the
    addresses the receipts say changed, and offers 다시 그리기, which asks and
    prints whatever comes back.

    **What a real echo needs, precisely, so this is not left as a wish:**
    either (a) a Hancom render of the candidate — which means closing P1, and
    then the existing `renderPrepare --runId` path produces one and the echo
    state disappears on its own with no desktop change; or (b) **E2.1's own
    line breaker**, which is the only route that works on a machine with no
    Hancom at all: Rigorloom lays the candidate out itself and draws it at
    `own-uncertified` grade with the grade visible. Both are real echoes.
    Neither of them is "draw the new text onto the old raster", which is the
    one thing this build will not do — the overlay's rule (§12.2) is that
    every rectangle on the page came out of the renderer's own layout, and a
    glyph placed at a guessed position breaks it in the most convincing way
    available.

33. **The changed-region marking needs a plan read per candidate in the
    chain.** The addresses come from the receipts' own plans, walked up the
    `base` links, which is one `plan/get` per ancestor. Cheap for a chain of
    three and not free for a chain of fifty; and until those reads land the
    banner says the list is not read yet rather than marking nothing and
    looking clean. *Suggested shape:* a receipt already carries `steps[]` with
    each op's `kind` and `opId`; carrying the op's ADDRESS there too would make
    this a zero-call derivation from data the receipt is already keeping.

34. **본문 보기 has the same staleness the page has, and only the page says so.**
    `document/inspect` and `document/readRegion` without a `runId` answer from
    the SOURCE, and the tree, the paper column and a seat's `before` are all
    drawn from that. So after an apply the centre column shows the document as
    it was, exactly as the raster does — but the raster now carries a
    후보본과 다름 banner and the text view carries nothing. On the corpus this
    is invisible because a second edit goes into a different, still-empty seat;
    it stops being invisible the moment somebody edits the same cell twice and
    the queue's `before` quotes the pre-first-edit value.
    *Suggested shape:* the runtime side already exists — `readRegion` takes a
    `runId` (§15.3) and `document/inspect` could take one the same way, since
    `load_profile` now accepts a subject. Then the centre re-reads against the
    head and the whole class of staleness closes at once, page and text
    together, instead of the page being honest alone.

### New with the own renderer (tier 3)

34. ~~**An own-rendered page carries no addresses, so it cannot be edited
    on.**~~ **CLOSED**, and along the shape this entry predicted: the renderer
    laid the glyphs out, so it knows the text and the per-character x, and it
    drew every line out of the tree, so it knows the paragraph or cell it came
    from. `line_boxes` carries `text`, `char_x`, `size_pt` and `address` now,
    and `cell_boxes` carries every drawn cell rectangle with its own
    `hp:cellAddr`. `document/pageGeometry` reshapes those into the shape
    `base_span` / `map_spans` already speak and runs the SAME form scan a
    PDF-read page runs — same normalizer, same unique/ambiguous/unmapped
    verdicts — so no new concept reached the wire and the Desktop consumed it
    without a new consumer.

    What did NOT happen is the renderer being believed. Its own address is a
    cross-check that can only confirm or demote (`mapping.crossCheck`):
    agreement makes a span `unique`; a contradiction makes it `ambiguous`
    carrying both; a line the scan matched nothing for keeps `address: null`
    with the renderer's answer recorded beside it and NOT applied. Across the
    ten corpus forms, 2,271 spans: **393 agree, 0 disagree**, 1,205 where the
    renderer named one of an already-ambiguous line's candidates (marked in the
    chooser, never taken — T41 does not lapse for a second witness), 3 where it
    named one the scan's list lacked, 670 recorded and not claimed. Seats come
    from the boxes the renderer drew, under their own derivation `own_cell`:
    **473 across the corpus**, on the same fill cells tier 1 places.

    Getting to 0 disagreements took one correction worth recording. The scan
    calls a paragraph inside a table cell an `anchor` at paragraph N; the
    renderer calls it that cell AND paragraph N. Comparing the full address key
    read 256 of 393 scan-unique lines as contradictions — a numbering bug that
    did not exist. `addresses_agree` treats an identical `atPara` as agreement
    across kinds, and the disagreement count went to zero.

35. **Tier 3 is not certified against anything, and cannot be from here.**
    `render_cert` scores a renderer against a Hancom reference render, and the
    own renderer emits raster PDFs with no text layer, so only the page-count
    and raster channels can score it at all. Every page it draws is therefore
    `own-uncertified` and will stay that way until a vector text backend
    exists. The Desktop's job is the label, and the label is the whole of what
    this build can honestly offer.

36. **The page a user sees can be a different tier from the one they had a
    moment ago, with no transition.** Running `renderPrepare` successfully on a
    machine that does have Hancom silently promotes the page from tier 3 to
    tier 1: the badge changes, the skipped list empties, the overlay gains
    addresses. That is correct, and it is also a jump with no explanation
    attached. *Suggested shape:* a one-line note under the badge when the tier
    changed during this session, naming both.

## Packaging gaps

Not runtime gaps and not agent-host gaps: things true of the **artifact this
build produces**, which is a category the earlier phases did not need.

P1. **The frozen sidecar has no `pyhwpx`, so a packaged install can never
    convert.** Found by the overlay evidence, and it is the same shape as the
    rasterizer defect this slice fixed. `document/renderPrepare` in the
    PACKAGED runtime answers `needs_hancom` with "pyhwpx is not importable; the
    COM backend needs it" — on a machine where Hancom Office 2024 is installed,
    registered as `HWPFrame.HwpObject`, and running. Three runtimes, three
    different answers for the same click: the packaged one says
    `needs_hancom`/no-pyhwpx, a dev interpreter on this machine says `com_busy`
    (an instance is open and the Runtime will not terminate it), and the README
    recorded `convert_failed` from an earlier machine state. All three are
    honest; only the first is a property of what we ship. Until pyhwpx is in
    the bundle, 페이지 그림 만들기 in a shipped install is a button that can
    only refuse — which also means the overlay can only ever see a page for a
    document that was *already* a PDF.

    Not fixed here. PyMuPDF is a pure read-side wheel and bundling it was a
    contained decision; pyhwpx drags in COM automation against an installed
    Hancom, and whether that belongs in the shipped payload is a product call,
    not a build-script one.

P2. **The smoke had an undeclared dependency on an untracked file.** Three
    `chrome` checks asserted `report requires style` and the `check_style`
    checker by name. Both are only true of an *enabled* registry, and
    enablement lives in `modules/enabled.yaml`, which `.gitignore` excludes — so
    they passed on the machine that wrote them and fail on every fresh
    checkout, including this worktree, where the registry honestly reports six
    modules discovered and none enabled. The app was correct throughout; the
    evidence was not reproducible. Repointed rather than deleted, per the
    standing rule: they now assert that the shell repeats the registry's answer
    exactly and adds nothing, in both directions, and one of them records which
    of the two registry states the run exercised so the report says so out loud.

## Agent Host gaps

Recorded, not patched: `agenthost/**` belongs to another branch. All four were
found by building against it, and all four are cheap to close on that side.

1. **The turn loop never streams.** `AgentHost.run` calls `provider.complete()`
   and nothing else. `provider.stream.chunk` is a declared event kind that
   nothing emits, `ProviderAdapter.stream()` exists and is implemented by two
   adapters, and neither is reachable through `host.py`. So a provider whose
   profile truthfully says `streaming: yes` still delivers its text in one
   piece, and this UI has to say so beside the capability row that says yes —
   which is a strange thing to have to write. *Suggested shape:* `AgentHost.run`
   takes `stream: bool`, and when `profile.supports("streaming")` it iterates
   `provider.stream(request)`, appending `provider.stream.chunk` per delta and
   assembling the same `ProviderResponse` at the end. The event kind and the
   adapter method are both already there; only the loop chooses not to use them.
2. **`os_store` is declared and refused.** `CredentialRef` accepts
   `source: "os_store"` and `resolve()` raises `credential_source_unsupported`.
   The desktop now HAS an OS credential store, so the honest handoff is an
   environment reference set on the child process — which works, and is one
   indirection more than the contract already describes. *Suggested shape:* let
   the host resolve `os_store` on Windows through the same `CredRead` this
   shell's `credstore.rs` uses, or drop the source from `CREDENTIAL_SOURCES`
   so it stops advertising something no build can do.
3. **`host.py` is one-shot, so a conversation is N processes.** There is no
   stdin command loop and no resume; `resumableThread` is `no` everywhere and
   history is resent inside a single run. That is correct and cheap at this
   scale — a cold Python start per message — and it will stop being cheap on a
   provider with a real context to rebuild. Recorded before it is urgent.
   *Suggested shape:* an `--serve` mode framing the same run payloads over
   stdio, which is the shape `runtime/scripts/serve.py` already establishes.
4. **No live-provider test exists, and the desktop cannot supply one.** Every
   agenthost test talks to a local fake; `--live-smoke` is implemented and its
   keyless refusal is tested. This slice adds the credential UI the README named
   as the missing piece, so a live leg is now RUNNABLE by a person with a key —
   and was not run here. See below.

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
- **A provider turn is a cold Python start, per message.** Measured at roughly
  two seconds here for the mock, which does no network at all; a real provider
  adds its own latency on top. Acceptable at this scale and stated so it is not
  discovered as a surprise — agenthost gap 3 is the fix, and it lives on the
  other side of the boundary.
- **The credential store is per-machine and per-user, and nothing says so on
  screen yet.** `CRED_PERSIST_LOCAL_MACHINE` under the running user's profile.
  A person who moves the app to another machine finds the key gone and the
  composer explaining that it is missing, which is the right behaviour and not
  the same as being told in advance.
