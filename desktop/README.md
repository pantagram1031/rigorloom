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
| `src/components/` | tree, preview, panels, verification bar, timeline, composer |
| `src/smoke.ts` | the scripted checks, run inside the built app |
| `scripts/` | build, smoke, screenshots, window capture |

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

Tokens live at the top of `src/styles.css`.

**Typography.** `Pretendard, "Pretendard Variable", "Noto Sans KR", "Malgun
Gothic", system-ui, sans-serif`. Never `system-ui` alone: on Korean Windows it
resolves to 맑은 고딕, which ships Semilight/Regular/Bold and cannot express a
hierarchy — the reason Studio reads flat. Body 13–14 px at `line-height: 1.7`,
because Hangul glyphs fill their em box and Latin-tuned 1.4–1.5 crowds them;
headings 1.35. Weight carries hierarchy (400/500/600), never 700+ for Korean UI
text. **Hangul is never letter-spaced**; the one tracked class, `.latin-caps`, is
Latin-only by construction. Evidence — hashes, addresses, exit codes — is
monospace with tabular figures.

**Space.** 4 px base: 4 / 8 / 12 / 16 / 24 / 32 / 48. `--row-h` is shared by the
structure tree, the session list and the timeline, so rows in different panels
line up and the eye keeps trusting that they refer to the same thing.

**Colour.** One accent (`#3a6082` light, `#7eacd6` dark), low chroma, interactive
affordance only. Semantic tones are reserved for evidence: positive, warning,
negative, muted — retuned per theme rather than reused. No gradient, no glow, no
animated accent. Motion only where it explains a relationship: 120–140 ms.

**Surfaces.** No card grid. Lists and one primary surface. The centre is the
brightest thing on screen, panels sit a step back, borders are 1 px at low
contrast rather than shadows. Density is a feature — this is a tool for long
sessions.

**Copy** is written as Korean product language, not translated developer
strings: `채움 자리`, `쓰기 전 확인`, `이 빌드가 보지 못하는 것`,
`사이드카가 종료되었습니다. 문서 상태는 남아 있습니다.`

**Pretendard is not bundled.** The stack names it first and it is absent on the
build machine, so the app currently renders in Noto Sans KR. Bundling is the
spike's recommendation and its open question 8 — SIL OFL redistribution inside a
Windows installer needs a decision from whoever ships this, and the Hangul subset
has a size cost. Named here rather than done quietly.

---

## Evidence

Reproduce with the two scripts above. Recorded from the run on this branch:

**Build** (`scripts/_run/build-exit-codes.txt`)

| Step | Exit | Seconds |
| --- | --- | --- |
| `npm install` | 0 | 8 |
| sidecar build (PyInstaller one-dir) | 0 | 93 |
| `npm run build` (tsc + vite) | 0 | 15 |
| `npx tauri build` | 0 | 401 |

Shell exe 6.08 MiB · NSIS installer 8.89 MiB · sidecar payload 23.2 MiB.

**Smoke** — 36 checks, 0 failures, exit 0. Phase `open` (29) opens the corpus
form, verifies the tree against the runtime's own counts (26 of 26 paragraphs,
32 of 32 cells, 9 fill seats), confirms the honest preview state, and asserts the
shared-state signature is identical across `document → agent → document`. Phase
`reattach` (7) is a second process that finds the session the first left on disk
and re-reads it to the same source hash. Between them, an orphan check: the
sidecar is gone after the shell exits.

**Screenshots** — `screenshots/{document,agent}-view-{100,150}pct.png`, real
Korean document loaded, `devicePixelRatio` 1 (2880×1759 css) and 1.5 (1920×1173
css).

**Runtime tests** — `PYTHONIOENCODING=utf-8 python -m pytest tests/test_runtime_*.py -q`
passes unchanged; nothing outside `desktop/` was modified.

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
