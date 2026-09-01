# desktop/ — Rigorloom Desktop, Phase 3 foundation

Tauri 2 + React/TS shell over the real Runtime as a packaged Python sidecar.

**This phase is read-only.** A clean user can open a supported document,
understand its structure and support status, move between the two views without
losing anything, and close and reopen the workspace without touching a terminal.
Nothing here changes a document: `plan/apply`, `approval/resolve` and the whole
mutation path exist on the host entry and are deliberately never called.

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
| `src/store.ts` | **the one Workspace** both views project |
| `src/actions.ts` | every operation, as plain functions, so the smoke drives the real path |
| `src/runtime.ts` | thin invoke wrappers and event subscriptions |
| `src/views/` | `DocumentView`, `AgentView` — layouts, no state |
| `src/components/` | tree, text view, panels, verification bar, findings, timeline, composer, logo, splash |
| `src/assets/` | `logo.svg` (drawing of record) and the bundled Pretendard + `OFL.txt` |
| `src/devMock.ts` + `src/fixtures/` | browser-mode replay of a recorded real session; `import.meta.env.DEV` only, absent from production bundles |
| `src/smoke.ts` | the scripted checks, run inside the built app |
| `scripts/` | build, smoke, screenshots, window capture, fixture recorder |

### Keyboard

`Ctrl+O` open · `Ctrl+1` / `Ctrl+2` views · `Ctrl+=` / `Ctrl+-` / `Ctrl+0` app
zoom (50–200 %, persisted, announced as a toast) · `Ctrl+C` copies the selected
cell or paragraph when there is no text selection to copy instead. Dropping a
`.hwpx` on the window opens it; anything else is refused out loud.

## Running it

```powershell
# from clean: npm install -> sidecar -> vite -> tauri build, exit codes recorded
powershell -ExecutionPolicy Bypass -File desktop/scripts/build-clean.ps1
powershell -ExecutionPolicy Bypass -File desktop/scripts/build-clean.ps1 -Fresh

# evidence
powershell -ExecutionPolicy Bypass -File desktop/scripts/smoke.ps1
powershell -ExecutionPolicy Bypass -File desktop/scripts/screenshots.ps1

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

- **No fabricated page.** There is no renderer anywhere in this build. The
  centre surface says so and quotes the runtime's own
  `capabilities.unavailable.renderProbe` string verbatim. What is drawn is
  `summary.pageMetrics` — real numbers, to scale, captioned `PAGE GEOMETRY` so it
  cannot be mistaken for a render of the content.
- **Proof state appears in exactly one place**, the verification bar, and reads
  `증명 없음` / `실행 안 함` rather than a neutral dash that could be read as
  fine.
- **Colour never carries meaning alone.** Every semantic tone ships with its
  word.
- **Absence is not failure**, and neither is undecidable: a region whose
  `colorAnomaly` key is omitted renders `판단 불가`, not `없음`.
- **The composer is present and disabled**, with a sentence saying there is
  nowhere to send anything yet. A composer that accepted text and dropped it
  would be worse than none.

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
  and — when Phase 4 brings it — approval-pending. Scarcity is the whole
  mechanism. It appears nowhere else, and adding it to a chip would end its
  meaning.

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
- **`검사 실행` cannot run `verify`, and does not claim to.** The direction asks
  for a button that "runs the runtime's verify". `verify/*` is not on the wire
  and `RuntimeCore.candidate_verify` needs an applied candidate, which a
  read-only phase never produces. Wiring the button to nothing, or relabelling
  a different check as verification, would be precisely the dishonesty the
  verification bar exists to prevent. So it re-reads the document and reports
  the engine's own preflight facts — `color_anomaly` (T127), `scriptAnomaly`
  (T30), per-run colour drift — each carrying an address, and the two proof
  badges keep saying 증명 없음 / 실행 안 함 throughout. Gap 3 below is the
  method that would let it do more.
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

Fill seats are already discrete, addressed, `data-node-id`-carrying elements
with their own empty slot. Phase 4's inline editing replaces a slot's contents
with an input and drafts an OperationPlan; nothing else here has to change.

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

### The design slice: NOT built, NOT smoked, screenshots NOT regenerated

Stated plainly because the alternative is a README that implies evidence which
does not exist.

**The build machine ran out of disk part-way through this slice** — `C:` reached
0 bytes free of 463 GB. `cargo clean --profile dev` reclaimed 1 GB of my own
unused debug artifacts; the release link then failed again at 0.05 GB free. The
remaining large reclaimable item in this worktree is ~4.4 GB of untracked,
gitignored build residue under `spikes/` left behind by an earlier branch
checkout, which is not mine to delete unasked.

Before that, thin LTO replaced fat LTO for an unrelated and independently
correct reason: fat LTO with `codegen-units = 1` died with
`rustc-LLVM ERROR: out of memory` on a 16 GB machine with a browser open. A
build that only completes on an idle machine is not a build.

What **is** verified on this slice:

| | |
| --- | --- |
| `npx tsc --noEmit` | exit 0 |
| `npm run build` (tsc + vite) | exit 0 — `dist/` produced, Pretendard bundled into it |
| Runtime fixture | recorded from a real Runtime v0 session (`scripts/record-fixture.py`) |
| Rendered and inspected in a browser against that fixture | see below |

The browser check ran the real components against the real recorded runtime
output and confirmed, programmatically: `Pretendard Variable` loaded
(`document.fonts.check` true); app `rgb(241,238,232)`, paper `rgb(254,253,251)`,
titlebar `rgb(28,30,33)`; paper column 720 px; 34 document cells and 9 fill
seats rendered, 8 with empty slots; **2 colour-anomaly runs rendered in the
document's actual `rgb(0,0,255)`** with the anomaly marking — the T127 failure
made visible rather than normalised away; every table row's colspans summing to
the table's 15-column axis; 페이지 보기 present and disabled; the centre caveat
reading 본문 보기 — 실제 페이지 배치는 렌더 증명 후 표시됩니다.

What that check cannot cover: the packaged sidecar, the job object, the
entrance and view-switch motion in a real window, DPI behaviour, drag-and-drop,
the native dialog, zoom persistence across a process boundary, and every smoke
assertion that needs two launches. `scripts/smoke.ps1` and
`scripts/screenshots.ps1` were extended for all of it and are unrun; the four
screenshots in `screenshots/` are **from Phase 3 and are stale** — they predate
the entire visual identity.

Everything above is one `powershell -File desktop/scripts/build-clean.ps1`
away once there is disk.

### What the evidence does not cover

- **The native file dialog is not exercised.** The smoke opens by path through
  `actions.openPath`, the same function the dialog calls with its result, but no
  OS-level input is synthesized and the dialog itself is untested.
- **No IME testing here.** The spike covered M13/M14 with real 두벌식 scan codes;
  this build has no text input to type into yet.
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

## Runtime gaps this phase hit

Recorded, not patched: `runtime/**` belongs to another branch.

1. **No event stream.** `event/subscribe` is GAP, so the Agent timeline cannot
   show the workspace's `events.jsonl`. It shows this shell's own protocol
   traffic and says so on screen. *Suggested shape:* `event/subscribe
   {sessionId?, after?} → notification event {seq, at, kind, payload}` with a
   monotonic `seq`, so a reconnecting subscriber can resume — protocol open
   question 8.
2. **No page rendering.** No `document/render`, and `capabilities.unavailable
   .renderProbe` says no renderer capability is reported or claimed. The centre
   of Document view — the product's main surface — is therefore permanently the
   unavailable state. *Suggested shape:* `document/render {sessionId, page, dpi}
   → {png: base64, widthPx, heightPx}` plus a text-geometry channel for hit
   testing; protocol open question 5 already frames the choice.
3. **No verification methods.** `verify/*` is GAP, so the verification bar can
   only report "not run". Residue checking exists in the domain layer
   (`RuntimeCore.candidate_verify`, reachable from the CLI's `verify`) but is
   deliberately not on the wire. *Suggested shape:* promote it to
   `verify/residue {sessionId, runId}` returning the verdict object unflattened.
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
11. **No page render, and now a UI waiting for one.** Unchanged from gap 2, but
    the cost is concrete: 페이지 보기 exists, is wired, and is disabled. The
    shell polls `capabilities.methods` for anything under `document/render` and
    will enable the mode the moment one appears, so the runtime side can land
    without a desktop change.

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
- **`runtime_call` serialises on one mutex.** Fine for a read-only phase with one
  call in flight; a plan-apply phase with concurrent progress will need the lock
  scoped to the write rather than the whole call.
- **Two sessions of the same file are indistinguishable in the list** except by
  timestamp. Opening the same form twice is legal and produces two rows.
