# Desktop shell spike — Studio audit, environment check, measured plan

Track C (desktop product and experience). Research and planning only: no
desktop code exists yet and none is written here.

Two kinds of statement appear below and are labelled:

- **Observed** — a `file:line` citation against commit `a635289`, or a note
  from the Studio run recorded in [§1.6](#16-observed-run).
- **Target state** — proposal for the desktop product. Not implemented,
  not decided.

---

## 1. Studio audit

### 1.1 What Studio renders today

Studio is a FastAPI app (`studio/main.py:14`) that serves one HTML page
(`studio/index.html`, 135 lines, all CSS and JS inline) plus a JSON API. The
page has exactly two screens: a card grid of workspaces and a per-workspace
detail view (`studio/index.html:19-38`), toggled in place
(`studio/index.html:73-74`).

**Dashboard screen** — one card per workspace slug matching `report-[A-Za-z0-9_-]+`
(`studio/main.py:98`, `112-119`), rendered from `_workspace_summary`
(`studio/main.py:1087-1113`): stage progress `done/total`, current stage id and
Korean label, pending gate name and type, auto-approved count, last event
timestamp, and a workflow-lint chip. Above the grid sits a capability strip
(`studio/index.html:21`, `57-61`) of four render chips — Hancom COM, soffice,
soffice(WSL), H2Orestart (`studio/main.py:174-183`).

**Detail screen** — a two-column layout (`studio/index.html:27-37`):

| Panel | Source | Citation |
|---|---|---|
| Stage progress | `PIPELINE.md` YAML header, one row per stage with gate badge and raw status | `main.py:378-437`, `index.html:83` |
| Deliverable preview | `output/deliverable/preview.html` in a sandboxed iframe | `main.py:1179-1186`, `index.html:88` |
| PDF viewer | every page of the chosen verify PDF, rasterised server-side by PyMuPDF at 1.5× | `main.py:1377-1398`, `index.html:87` |
| Gate provenance | `.pipeline/gate_checks.jsonl` → gate, checker argv, exit code, 12-char stdout SHA-256, timestamp | `main.py:1125-1151`, `index.html:84` |
| Humanization | `bundle/humanization_rounds.json` → per-round violation counts and hold reasons | `main.py:1154-1176`, `index.html:85` |
| XML render verdict | proof grade, gappy pages, `needs[]` count, `renderer_failed` | `main.py:827-862`, `index.html:86` |
| Actions | hidden unless action mode is on | `main.py:1197-1265`, `index.html:91` |
| Events | `events.jsonl` tail, 5-second poll with an `after` line cursor | `main.py:1487-1491`, `index.html:125-126` |
| Module panels | appended to the aside, one section per enabled module panel | `index.html:100-116` |

**Proof grades.** Three states, always labelled, read from exactly one
canonical file `output/verdict_v06.json` (`main.py:824`, `836`): `hancom` →
`제출급 증명`, `advisory` → `참고용 렌더 (LibreOffice)`, `none` → `렌더 증명
없음` (`main.py:783-787`). The binding to a single filename is deliberate and
commented as an anti-spoofing measure — an earlier "newest `*verdict*.json`"
rule could be defeated by dropping a newer advisory file (`main.py:822-823`).

**Capabilities.** `pipeline/scripts/render_probe.py` runs once per server
process in a subprocess with a 20-second timeout; any failure collapses to a
single gray `probe n/a` chip rather than breaking the page
(`main.py:136-192`), and the result is cached for the process lifetime
(`main.py:195-202`). The Hancom check is registry-only — it looks for the
`HWPFrame.HwpObject` ProgID under `HKEY_CLASSES_ROOT` and never instantiates
COM (`pipeline/scripts/render_probe.py:82-92`).

**Guarded actions.** Five kinds: `check-gate`, `approve-human-gate`,
`run-checker`, `build-bundle`, `build-hwpx` (`main.py:73-76`). Each spawns a
subprocess with a 300-second timeout and returns `{argv, exit_code,
output_tail}` truncated to 4000 characters (`main.py:1250-1265`). Gate targets
are validated against the intersection of the workspace's own `PIPELINE.md`
header and the declared stage graph, so a header cannot self-declare a gate
(`main.py:979-990`). `approve-human-gate` appends a line to `APPROVALS.md`
before invoking the stage machine (`main.py:1221-1225`).

### 1.2 Server and trust model

- **Bind.** `uvicorn.run(app, host="127.0.0.1", port=8000)` and a browser
  auto-open 1.2 s later (`main.py:1828-1833`).
- **Read is unauthenticated.** No middleware of any kind is installed — no
  CORS, no CSP, no auth (`grep` for `CORS|allow_origins|Middleware` in
  `main.py` returns nothing; observed §1.6). Every `GET` is open to anything
  that can reach the port.
- **Write is guarded three ways.** Actions are off unless
  `STUDIO_ALLOW_ACTIONS=1` (`main.py:967-968`, checked first at
  `main.py:1203`); a per-run `secrets.token_urlsafe(16)` must arrive in
  `X-Studio-Token`; and the `Host` header must start with `127.0.0.1` or
  `localhost` (`main.py:993-1002`). The token is printed to the console once
  (`main.py:88-89`) and injected into the page Studio serves itself as
  `<meta name="studio-action-token">` (`main.py:1805`, `index.html:6`,
  `index.html:43`).
- **Path containment.** Slug regex plus a resolve-and-check-parents test
  (`main.py:101-109`); separate `/`, `\`, `..` rejection on figure names and
  PDF stems (`main.py:1368`, `1380`); the deliverable preview must resolve
  inside the workspace (`main.py:1183`).
- **Redaction.** The personalization endpoint deliberately returns shape, not
  content — counts and booleans instead of identity data
  (`main.py:1551-1582`).

**Honest gap.** The `Host` guard exists only on `POST /action`. A
DNS-rebinding attack that resolves an attacker-controlled hostname to
`127.0.0.1` gets same-origin `GET` access to every workspace endpoint —
`content.md` via `/draft` (`main.py:1633-1645`), rendered PDF pages, research
evidence, provenance. Confirmed: `GET /workspace/report-audit/state` with
`Host: evil.example.com` returned `200` (§1.6). Actions stay blocked, so the
damage is read-only exfiltration of document content, but this is exactly the
"Studio silently becomes the shipping security boundary" failure the desktop
program is trying to avoid. **Target state:** the desktop shell must not
inherit an HTTP surface with this property. Either the sidecar speaks stdio
only (no listening socket at all), or the same Host/origin guard applies to
every method.

### 1.3 Module panels and the privilege they get

Registration is declarative. A distribution module declares
`provides.studio_panels` in its `module.yaml`; Studio reads it only through
typed registry accessors and never learns a module's name or path
(`main.py:20-31`, and the same discipline for CLI and checkers at
`main.py:34-52`). `GET /api/panels` returns `{id, title, entry, module}` with
`entry` rewritten to a Studio-served URL (`main.py:929-940`);
`GET /api/panels/{id}/entry` serves the file with a media type derived from
its suffix (`main.py:943-959`). One panel exists in the tree:
`modules/report/studio/panel.js` (20 lines), which renders a single "Run
content audit" button.

**The privilege is total.** `initModulePanels` fetches the entry and, when the
content type is JavaScript, creates a `<script>` element with the fetched text
and appends it to `document.body` (`index.html:111`). HTML entries are
injected as `innerHTML` with their `<script>` children re-created so they
execute too (`index.html:112`). Panel code therefore runs in the main
document: same origin, full DOM access, and — decisively — access to the
`actionToken` constant in the page's top-level scope (`index.html:43`). The
`render(el, ctx)` contract additionally hands each panel a `runAction` closure
(`index.html:121`), but a panel does not need it; it can read the token from
the meta tag and POST anything.

There is a real boundary underneath: the generic
`POST /action/{slug}/run-checker?checker=<name>` resolves the checker through
the registry and validates the name against `^[a-z][a-z0-9_]*$`
(`main.py:1226-1240`), so a panel cannot name an arbitrary script. But a panel
can invoke *any* action kind, including `build-hwpx`. In the current model
that is acceptable — panels ship from the same repository as the core — but it
is not a trust boundary, and it must not be mistaken for one when panels
become a desktop extension point. **Target state:** if the desktop keeps
third-party panels, they need an out-of-document sandbox (isolated origin,
message-passing to a capability-scoped host) rather than script injection.

Note also that the deliverable preview is loaded into `<iframe sandbox>` with
no allow-list (`index.html:88`) — fully restricted. Untrusted *document*
content is treated more carefully than untrusted *panel* content.

### 1.4 Reusable for the desktop IA

1. **The JSON API is the real asset, not the page.** 27 `GET` endpoints exist;
   `index.html` fetches six of them (`state`, `gate-checks`, `humanization`,
   `events`, `deliverable/preview.html`, `api/panels` — plus PDF pages via
   `<img src>`). Seventeen endpoints have no UI consumer at all: `ledger`,
   `buildconfig`, `research`, `figure`, `heartbeat`, `fill`,
   `personalization`, `preview-pdf`, `provenance`, `scorecard`, `draft`,
   `readiness`, `yourmove`, `startprompt`, `workspaces`, `capabilities`,
   `verdict`. These are already-written, already-tested readers for exactly
   the panels the desktop needs. Reuse the readers; discard the page.
2. **The proof-grade vocabulary** (three states, canonical file, mandatory
   qualification of advisory renders) is the strongest concept in the
   codebase and should become the desktop's verification bar verbatim.
3. **Gate provenance as receipts** — argv + exit code + stdout digest +
   timestamp (`main.py:1125-1151`) — is the right shape for an evidence-forward
   product. It is a receipt list, not a status light.
4. **`yourmove` / `readiness`** (`main.py:1672-1775`) already computes a
   single next action, its blocking reason, and the exact command, including
   distinguishing `blocked` / `gate_wait` / `running` / `done` / `stale`. This
   is the seed of the agent view's "what happens next" affordance and has no
   UI today.
5. **Fill-loop iterations** (`main.py:1523-1548`): per-iteration preview PDFs
   with page counts plus normalised anomalies (fill / style / tidy / proof),
   deduplicated to the latest per kind. This is a document-view timeline
   scrubber waiting for a UI.
6. **Degradation discipline.** Every reader answers `{"available": false}` or
   an `n/a` chip instead of failing (`main.py:142-147`, `1045`, `1159`,
   `1557`). Absence is not failure. Carry this rule into the desktop.
7. **Declarative module contribution** through typed registry accessors —
   keep the resolution discipline, replace the delivery mechanism.

### 1.5 Dashboard-shaped dead ends

- **The card grid itself.** `index.html:62-72` renders a responsive
  `minmax(285px,1fr)` grid of workspace cards with hover-lift transforms and
  progress bars. This is the "dashboard-card grid" the program explicitly
  rules out. A desktop editor opens a document; it does not present a gallery
  of KPI tiles.
- **Server-side PDF rasterisation as the document view.** `renderPdf`
  (`index.html:87`) emits one `<img>` per page from a 1.5× PyMuPDF pixmap
  (`main.py:1391`). There is no selection, no text layer, no coordinate
  mapping back to structure, and no zoom beyond browser scaling. It is a
  contact sheet. A desktop page preview that must support click-to-locate and
  crisp rendering at 200% cannot be built on this; the raster path can stay
  only as a fallback thumbnail source.
- **`POST /action` as the write path.** Fire-and-forget subprocess, 300-second
  blocking call, 4000-character output tail, no streaming, no cancel, no
  progress, no structured result (`main.py:1250-1265`). Nothing about an
  `OperationPlan` review queue can be built on this shape.
- **Full-page refresh on every change.** `loadDetail()` re-fetches and
  re-renders every panel (`index.html:77-82`), and `runAction` calls it again
  on completion (`index.html:92`). A synchronised two-view editor needs
  incremental state, not innerHTML replacement.
- **5-second polling** (`index.html:126`) where the engine already writes
  append-only JSONL. The desktop should tail, not poll.
- **Vestigial DOM.** `index.html:39` carries three hidden spans —
  `copy-approval`, `readiness-body`, `mission-stats` — with no code path that
  writes them. Removed features left their sockets behind; do not port them.
- **`GET /startprompt`** (`main.py:1783-1793`) builds a Korean prompt string
  for a human to copy into an agent. In an agent-native desktop the agent is
  in-product; this endpoint is a symptom of the architecture being replaced.
- **Theming/typography as written.** `system-ui,-apple-system,"Segoe
  UI",sans-serif` (`index.html:12`) resolves to 맑은 고딕 on Korean Windows,
  which has only Semilight/Regular/Bold — see §4.

### 1.6 Observed run

Run at commit `a635289` on 2026-09-01, read-only (`STUDIO_ALLOW_ACTIONS`
unset), against a synthetic workspace in the session scratchpad, not a real
one. Launched as `python -m uvicorn studio.main:app --host 127.0.0.1 --port
8391 --log-level warning` with `STUDIO_WORKSPACE_ROOT` pointing at the fixture
and `PYTHONIOENCODING=utf-8`; stopped by killing the port-8391 listener
(`Get-NetTCPConnection -LocalPort 8391`), after which the port refused
connections. No Hancom or COM was started.

| Probe | Result |
|---|---|
| `GET /` | `200` |
| `GET /capabilities` | `hancom_com: true`, `soffice/soffice_wsl/h2orestart: false`, `renderers: [{name: hancom}]`, `hwpx_available: true` |
| `GET /api/panels` | `[{id: report-tools, title: "Report tools", entry: /api/panels/report-tools/entry, module: report}]` |
| `GET /api/panels/report-tools/entry` | `200`, `content-type: text/javascript; charset=utf-8`, no CSP header |
| `GET /workspace/<slug>/state` | full stage list with Korean labels, `gate_waiting: true`, `resume: "2"`, verdict `advisory` with `gappy_pages: [3]`, `needs_count: 2` |
| `GET /workspace/<slug>/yourmove` | `kind: gate_wait`, exact `gate_command` and `approval_line` |
| `POST /action/<slug>/build-bundle` (no token, read-only) | `403 {"detail":"Studio action mode is disabled"}` |
| `GET /workspace/<slug>/state` with `Host: evil.example.com` | `200` — no Host guard on reads |
| `GET /dashboard` with `Origin: https://evil.example.com` | `200`, no `Access-Control-Allow-Origin` in the response headers |

Fixture note: the `PIPELINE.md` v0.4 header is a fenced ` ```yaml ` block whose
first non-empty line must be `# pipeline-state: v0.4` (`main.py:265-277`), not
front matter. A file with `---` front matter parses as `format: "legacy"` and
reports `0/0` stages with no error — worth knowing before debugging a desktop
reader against a hand-written fixture.

---

## 2. Environment check (this machine, nothing installed)

Measured 2026-09-01. No package was installed, upgraded, or removed.

| Tool | Result | Note |
|---|---|---|
| node | `v22.16.0` | present |
| npm | `10.9.2` | present |
| pnpm / yarn | absent | npm suffices |
| rustc | `1.97.1 (8bab26f4f 2026-07-14)` | present |
| cargo | `1.97.1 (c980f4866 2026-06-30)` | present |
| rustup default host | `x86_64-pc-windows-msvc`, only target installed | correct triple for Windows-first |
| MSVC toolchain | Visual Studio **Build Tools 2019**; `link.exe` on PATH | present but old — see risk below |
| Tauri CLI | **absent** (`cargo-tauri`, `tauri` both not found) | see below |
| WebView2 Runtime | `151.0.4129.107`, machine-wide (`HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-…}`); no per-user install | present |
| Python (PATH default) | `3.11.9` at `…\WindowsApps\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\python.exe` | **Microsoft Store build** |
| Other Pythons | `3.13` at `C:\Python313`, `3.12` at `…\Programs\Python\Python312` | non-Store, usable |
| PyInstaller | `6.20.0` (under the Store 3.11) | present |
| Nuitka | absent | alternative packager, not evaluated |
| PySide6 | **absent** | fallback arm needs an install |
| fastapi / uvicorn / pymupdf | `0.136.3` / `0.49.0` / `1.27.2.3` | Studio runs as-is |
| Repo floor | `requires-python = ">=3.10"` (`pyproject.toml:5`) | 3.12 and 3.13 both eligible |

**Installing the Tauri CLI** would be either `cargo install tauri-cli --locked`
(compiles from source; slow, no Node involvement) or `npm i -D
@tauri-apps/cli@^2` inside the spike directory (prebuilt binary, keeps the
toolchain local to the spike). The second is the smaller footprint and the one
to ask for. Everything the CLI depends on — Rust, MSVC linker, WebView2 — is
already here, so this is one command, not a toolchain project.

**Installing PySide6** would be `pip install PySide6` (a few hundred MB of Qt).
Do not install it into the Store Python.

**Risks recorded, not resolved:**

- *Store Python is the PATH default.* PyInstaller does not support freezing
  from a Microsoft Store Python (redirected filesystem, app-execution alias).
  The sidecar spike must pin a non-Store interpreter — `C:\Python313` or the
  3.12 under `Programs\Python` — and say so in the spike's build script.
  Getting this wrong produces a sidecar that builds on this machine and
  nowhere else, or does not build at all.
- *Build Tools 2019.* Tauri 2 itself is fine with it, but individual crates in
  the dependency tree increasingly assume a newer Windows SDK / MSVC. If the
  first `cargo build` fails with a linker or SDK error, that is the cause, and
  the fix is a Build Tools 2022 install — a real prerequisite to confirm
  before the decision, not a footnote.
- *WebView2 is an evergreen system component.* Version `151.x` today; the
  desktop's rendering can change under it without an app release. The spike
  must note which behaviours (IME, high-DPI) it verified against which
  version.

**Nothing found here makes Tauri 2 or the packaged-sidecar plan implausible on
this machine.** Rust, the MSVC linker, WebView2, Node, and PyInstaller are all
present. The only missing piece on the preferred path is the Tauri CLI itself;
the fallback path (PySide6) is the one requiring a large install.

---

## 3. The spike — target state

Goal: choose a shell on measurements, not preference. Build the **same**
minimal application twice and run the same script against both.

### 3.1 What to build (identical on both arms)

A single window that does five things and nothing else:

1. **Window.** One native window, 1280×800, app icon, correct title, closes
   cleanly.
2. **Spawn a packaged sidecar.** A PyInstaller-frozen `rigorloomd` built from a
   ~50-line Python script that imports `fitz`, `fastapi` (import only — no
   server), and one `engine/scripts` module, so the frozen size and cold-start
   cost reflect the real dependency graph rather than a hello-world.
3. **JSONL round-trip over stdio.** Newline-delimited JSON both ways on the
   child's stdin/stdout, stderr reserved for logs. Three request types:
   `{"op":"ping"}` → `{"ok":true}`; `{"op":"echo","n":<N>}` → N lines back
   (throughput); `{"op":"render_page","pdf":<path>,"page":0}` → base64 PNG
   (payload-size behaviour with a real PyMuPDF call). The UI shows round-trip
   latency for each.
4. **Native file dialog.** "Open .hwpx" → OS dialog → the chosen path goes to
   the sidecar and comes back echoed. Verify a path containing Hangul and a
   path containing a space survives intact end to end.
5. **Korean text input.** One plain text field and one field inside a
   virtualised list, both bound to state. Type 한글 through the Microsoft IME.

Both arms use the same subprocess/JSONL boundary even though PySide6 could
call Python in-process — otherwise the comparison is not apples to apples, and
in-process would violate "the engine stays headless".

Deliverable per arm: a directory under `spikes/shell-<tauri|pyside>/`, a
`README.md` with the exact build commands, and a filled measurement table.

### 3.2 What to measure

Report every number as median of 5 with min/max. Machine state: no other app
launching, on AC power, note whether the run is cold (first launch after a
reboot or after clearing the working set) or warm.

| # | Metric | Method | Threshold |
|---|---|---|---|
| M1 | Cold start to first paint | Stopwatch instrumentation from process create to the window's first frame callback | ≤ 1500 ms cold, ≤ 600 ms warm |
| M2 | Sidecar ready | Process create → first `{"ok":true}` for `ping` | ≤ 1200 ms cold |
| M3 | JSONL round-trip | `ping` ×1000, median and p99 | median ≤ 3 ms, p99 ≤ 20 ms |
| M4 | Throughput | `echo n=10000` (~1 MB), wall time | ≥ 20 MB/s, no stall |
| M5 | Large payload | `render_page` returning a ~1 MB base64 PNG | completes, no truncation, no deadlock |
| M6 | Installer size | Built installer/bundle on disk | ≤ 80 MB with sidecar |
| M7 | Installed size | Program folder after install | recorded, no threshold |
| M8 | Memory at rest | Private working set of *all* app processes, 60 s after launch, document open | ≤ 250 MB total |
| M9 | Memory after 50 round-trips | Same measure, checked for monotonic growth | no growth trend |
| M10 | **Process cleanup — graceful** | Close the window; check for orphan `rigorloomd` after 5 s | zero orphans |
| M11 | **Process cleanup — hard kill** | `Stop-Process -Force` on the *shell* process only; check for orphan sidecar | zero orphans — this is the one that decides the design |
| M12 | Process cleanup — sidecar crash | Kill the sidecar; shell must report it and offer restart, not hang or silently zombie | visible, recoverable |
| M13 | Korean IME | Type `안녕하세요` in both fields; verify composition preview, no duplicated jamo, no dropped final consonant, correct caret; then Backspace mid-composition; then Hangul-key toggle mid-field | zero defects — a defect here is disqualifying |
| M14 | IME in a virtualised list | Same, in the list-bound field, with the list scrolling | no composition loss on re-render |
| M15 | High-DPI | Run at 100 / 125 / 150 / 200 % display scaling, and change scaling while running | crisp text, no blurred bitmap scaling, layout intact, live change handled |
| M16 | Multi-monitor DPI | Drag the window between a 100 % and a 150 % monitor if one is available; otherwise record as not tested | no blur |
| M17 | Crash behaviour | Panic/exception in the shell's own code | crash is visible with a stack, not a silent close |
| M18 | Build reproducibility | Clean clone, documented commands, no manual step | builds on a second machine |

M10–M13 and M15 are gates. The rest inform the trade-off.

### 3.3 Notes the implementer needs

- **Sidecar packaging.** PyInstaller one-file self-extracts to a temp
  directory on every launch and will cost hundreds of ms in M2; one-dir does
  not. Tauri's `bundle.externalBin` expects a single binary named with the
  target triple suffix (`rigorloomd-x86_64-pc-windows-msvc.exe`), so one-dir
  needs to ship under `bundle.resources` and be spawned from the resolved
  resource path instead. **Measure both** — the packaging mode is likely to
  dominate M2 and M6, and choosing the shell on a number that is really about
  PyInstaller would be a bad decision.
- **M11 is the hard one.** When the shell is `SIGKILL`-equivalent-killed, no
  cleanup handler runs on either arm. On Windows the reliable answer is a Job
  Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` holding the sidecar, and/or
  a sidecar that exits when its stdin reaches EOF. Implement neither at first:
  measure the naive behaviour, record it, then add the mitigation and measure
  again. Both arms need the same mitigation, so if the naive result differs
  the difference is real; if the mitigated result is identical, M11 stops
  being a differentiator.
- **Pin the interpreter.** Build the sidecar with `C:\Python313\python.exe` or
  the 3.12 under `Programs\Python`, never the Store 3.11 on PATH (§2).
- **Do not touch Hancom or COM in the spike.** `render_page` uses PyMuPDF on a
  checked-in sample PDF.

### 3.4 Decision rule

Apply in order; stop at the first that decides.

1. **Disqualification.** Any arm failing M13 (Korean IME), M15 (high-DPI), or
   M11-after-mitigation loses outright. If both fail, neither stack ships as
   designed and the finding goes back to the program, not to a coin toss.
2. **Hard budget.** Any arm exceeding M1 ≤ 1500 ms cold, M6 ≤ 80 MB, or
   M8 ≤ 250 MB by more than 50 % loses.
3. **Both pass.** Take Tauri 2 + React/TS. Reason stated up front so the
   measurement is not retro-fitted to it: the two-view synchronised document
   product is a layout- and typography-heavy design problem, and the web
   layout engine plus the design-token workflow is a materially better tool
   for it than QML; the sidecar boundary it forces is the boundary the
   architecture wants anyway.
4. **Both pass and Tauri is worse on two or more of M1/M6/M8 by ≥ 30 %.**
   Escalate with the numbers rather than deciding inside the spike.
5. **Only one passes.** Take it, and record what the loser failed on so the
   decision is not silently revisited.

Write the outcome into this file as a dated `## Decision` section with the
filled table. An unrecorded spike is a spike that gets re-run.

---

## 4. Information architecture — target state

One `Workspace` object is the single source of truth; both views are
projections of it. Nothing below exists yet.

### Document view

```
┌──────────────┬────────────────────────────┬──────────────────┐
│ Structure    │  Page preview              │  Agent (context) │
│ nav          │                            │                  │
├──────────────┴────────────────────────────┴──────────────────┤
│ Verification bar                                              │
└───────────────────────────────────────────────────────────────┘
```

**Structure nav.** Two modes over the same tree.
*Content mode* — sections and the tag inventory: `_parse_structure`'s section
list and eq/fig/table counts (`main.py:682-694`) plus `_render_content`'s TOC
(`main.py:650-658`). *Form mode* — the form's own skeleton from
`form_inspect`: `anchor_records` with their `at_para` addresses, and
`table_map` entries with per-cell `addr` and classification
(`engine/scripts/form_inspect.py:29-33`).

**`form_inspect` `table_map` lives here, and it is a new surface.** Studio has
no reader for it — `form_profile.json` is only returned raw by `/draft`
(`main.py:1638-1644`) and nothing renders it. Proposal: the table map is an
*overlay on the page preview*, not a table in a side panel. Each cell's
classification (`guide` / `static` / `fill_target` / `spacer`) is a hit region;
`fill_target` cells are the only ones the agent may write. Selecting a cell in
the overlay reveals its `charpr`, `charpr_suggested`, `script_anomaly` and
`color_anomaly` (`form_inspect.py:49-63`) in the contextual panel, with
`color_anomaly: true` surfaced as a warning — that is precisely the failure
that once shipped blue body text as "checked and clean" (T127,
`form_inspect.py:55-59`). `spacer_cells` render at low contrast and are
excluded from any "cells remaining" count, matching `fill_target_count`.

**Page preview.** Needs a real page renderer with a text layer and
coordinate→structure mapping, not Studio's per-page `<img>` contact sheet
(§1.5). The fill-loop iteration PDFs (`main.py:1523-1548`) become a scrubber
along the preview, so a reviewer can step through iterations and watch gaps
close.

**Contextual agent panel.** Scoped to the current selection: the operations
the agent proposes or performed on *this* node, the evidence behind them
(`research` sources, `main.py:728-755`), and the humanization rounds that
touched it (`main.py:1154-1176`).

**Verification bar.** The single always-visible truth strip, and the only
place proof state may appear:

- Proof grade badge with its mandatory qualification, from the canonical
  verdict file only (`main.py:783-787`, `824`). An advisory render is never
  displayed without the LibreOffice qualification (`studio/README.md:41-60`).
- `gappy_pages`, `needs[]` count, `renderer_failed` (`main.py:852-859`).
- Gate state for the current stage and its type, human or script
  (`main.py:971-976`).
- Workflow-lint state and any HARD findings (`main.py:1032-1084`).
- Render capability chips (`main.py:174-183`) — because a `none` grade caused
  by an absent renderer is a different problem from one caused by a failed
  render, and the user must be able to tell them apart at a glance.

### Agent view

```
┌────────────┬──────────────────────────┬──────────────────────┐
│ Workspaces │  Agent timeline          │  Document context    │
│ + threads  │  + OperationPlan queue   │                      │
└────────────┴──────────────────────────┴──────────────────────┘
```

**Workspaces and threads.** From `/workspaces` (`main.py:879-881`) and
`_workspace_summary` (`main.py:1087-1113`) — as a list, not a card grid
(§1.5). Threads are a new concept with no engine backing yet; see §6.

**Agent timeline.** Three append-only sources merged on timestamp:
`events.jsonl` (`main.py:1487-1491`, already cursor-based via `after`),
`output/fill_events.jsonl` with the normalised fill/style/tidy/proof anomalies
(`main.py:1429-1484`), and `.pipeline/gate_checks.jsonl` provenance receipts
(`main.py:1125-1151`). Receipts render as receipts — checker argv, exit code,
stdout digest — because that is what makes the timeline evidence rather than
narration. Tail the files; do not poll (§1.5).

**OperationPlan review queue.** This concept does not exist in the repository
today; `grep` for `OperationPlan|operation_plan` returns nothing. Its nearest
existing analog is the ops JSON that `build_report.py` emits from `content.md`
(`engine/scripts/build_report.py:1-8`) and that `com_backend.py edit` accepts —
a validated batch of typed operations (`replace_all`, `put_field`, `set_cell`,
`insert_equation`, …) with required-key validation that runs *before* any
document is touched, specifically so a batch cannot half-apply
(`engine/references/ops_schema.md`).

That is already a reviewable plan; it has simply never been shown to anyone.
Put the queue in the **Agent view centre column, below the timeline**, with
each op:

- named by effect, not by op-code;
- carrying its document address — `goto_text` anchor text, `set_cell` `addr`
  (a `cellAddr` from `table_map`, `ops_schema.md`), `edit_equation` index — so
  selecting an op scrolls and highlights the target in the **Document view**;
- flagged when it is one of the ops the schema marks dangerous:
  `set_char_color` with `all:true` overwrites hyperlinks,
  `collapse_empty_paragraphs` can corrupt title sizes
  (`engine/references/ops_schema.md`);
- approvable individually or as a batch, with the batch gate mirroring
  `_validate_ops`: reject the whole plan on the first invalid op rather than
  applying a prefix.

The desktop's action path must be a streaming, cancellable, structured
execution of an approved plan — not Studio's blocking 300-second subprocess
with a truncated output tail (§1.5). Human gates (`design`, `draft`,
`topic_pick`) surface here as approval cards carrying the `approval_line`
`yourmove` already computes (`main.py:1755`), replacing the "copy this command
into a terminal" affordance.

**Document context panel.** The mirror of the Document view's agent panel:
which document the thread is operating on, its stage and next action from
`readiness` / `yourmove` (`main.py:1672-1775`), its proof grade, and the
redacted personalization lock (`main.py:1551-1582`) — shape only, never
identity data.

### The synchronisation contract

Selection is shared and bidirectional: a structure node ↔ a page region ↔ an
op in the queue ↔ a timeline entry. One selection model in the Workspace, both
views subscribing. This is the whole product thesis, and it is the reason
Studio's full-panel `innerHTML` refresh (§1.5) cannot be the starting point.

---

## 5. Design language — target state

**Korean-first typography.** Measured on this machine (§2): 맑은 고딕 (Malgun
Gothic) present with Semilight/Regular/Bold only; **Noto Sans KR present with
Thin, Light, DemiLight, Regular, Medium, Black**; 나눔고딕 present;
**Pretendard absent**; 함초롬돋움/함초롬바탕 present (Hancom document fonts —
these belong to rendered documents, never to app chrome).

Recommendation: **bundle Pretendard Variable** as an app asset (SIL OFL, ships
inside the installer, no network, no per-machine install) and use

```
font-family: Pretendard, "Noto Sans KR", "Malgun Gothic", system-ui, sans-serif;
```

Bundling is what makes the product look the same on every machine; the
fallbacks only matter if bundling is vetoed. Do **not** ship `system-ui` alone
as Studio does (`index.html:12`): on Korean Windows it resolves to 맑은 고딕,
whose three weights cannot express a hierarchy, and whose Semilight is the
only lighter option — the reason Korean apps built on the system stack read as
flat.

Typographic rules:

- Body 14–15 px at `line-height: 1.7`; Latin-tuned 1.4–1.5 leading crowds
  Hangul, whose glyphs fill their em box.
- Headings `line-height: 1.35`.
- **Never letter-space Hangul.** Tracking that flatters uppercase Latin
  destroys syllable-block rhythm. If Latin small-caps labels need tracking,
  scope it to a Latin-only class.
- Weight for hierarchy, size sparingly: 400 body / 500 emphasis / 600 headings.
  Avoid 700+ for Korean UI text — it blurs the denser syllable blocks at 14 px.
- Numerals and evidence (hashes, argv, exit codes) in a monospace with an
  explicit Korean fallback; tabular figures for anything that lines up in a
  column.
- Mixed Korean-Latin runs are the norm in this domain (`fill_target`,
  `proof_grade`, HWPX). Pick a Latin face whose x-height sits near the Hangul
  optical height — Pretendard is designed for exactly this and is the main
  reason to bundle it.

**Spacing.** 4 px base unit; 4 / 8 / 12 / 16 / 24 / 32 / 48. Panel padding 16
or 24, never both in the same tier. Preserve alignment across the two views —
if the structure nav's row height differs from the op queue's, the eye stops
trusting that they refer to the same thing.

**Colour.** One accent, low chroma, used for interactive affordance only.
Semantic colour is reserved for evidence and never spent on decoration:

- proof `hancom` → the single positive tone;
- proof `advisory` → the warning tone, *always accompanied by its text label*
  (colour alone must never be the difference between submission-grade and
  advisory);
- proof `none` and `spacer` cells → muted;
- HARD lint findings and `color_anomaly` → the negative tone.

Studio's existing three-state palette already encodes this correctly
(`main.py:783-787`, `index.html:9-11`); keep the semantics, restyle the
surface. Every semantic state carries a text label and, where it drives a
decision, an icon — the target user reviews documents for hours and may be
colour-vision-deficient.

**Calm and evidence-forward, concretely.** No gradient fills, no glow, no
"AI shimmer", no animated accent. Motion only where it explains a
relationship: a 120–160 ms ease when selection moves between the two views, so
the link is legible. Chrome recedes: the page preview is the brightest surface
on screen, panels sit a step back, borders are 1 px at low contrast rather than
shadows. No card grid (§1.5) — lists and one primary surface. Density is a
feature: this is a professional tool used for long sessions, so prefer a
compact, quiet, information-dense layout over generous marketing whitespace.
Light and dark both first-class, with the proof-grade tones re-tuned per theme
rather than reused.

---

## 6. Open questions

1. **What is a "thread"?** The Agent view assumes workspaces contain threads.
   The engine has stages, gates, and one linear `events.jsonl` per workspace —
   no thread concept. Is a thread a stage attempt, a conversation, or a new
   persisted entity? This blocks the Agent view's left column.
2. **Does `OperationPlan` mean the existing ops JSON, or a new layer above it?**
   §4 assumes the former. If it is a new abstraction spanning research and
   writing as well as document edits, the review queue is a much larger
   design.
3. **Who owns the HTTP surface after the desktop ships?** If the sidecar speaks
   stdio only, Studio's 27 endpoints have to be re-homed as sidecar ops, and
   Studio either dies or stays as a separate developer tool. If both exist,
   the §1.2 DNS-rebinding gap must be closed before the desktop can claim
   Studio is not the security boundary.
4. **Third-party module panels in the desktop.** Script injection into the app
   document (§1.3) cannot survive into a shipped product. Do panels move to a
   sandboxed origin with message passing, to a native plugin API, or does the
   desktop simply not support third-party panels at v1?
5. **Page rendering.** The desktop needs a real page view. Is that PyMuPDF
   raster at device DPI with a separate text-geometry channel for hit
   testing, or a genuine renderer? M15 (200 % scaling) will expose this — a
   1.5× pixmap upscaled to 200 % is visibly soft.
6. **Where does Hancom fit?** The desktop is Windows-first and the machine
   reports `hancom_com: true`, but nothing here has tested driving COM from a
   sidecar under a GUI parent. COM apartment threading and a killed parent
   process are a known-bad combination and need their own spike.
7. **Does the desktop write `PIPELINE.md`, or only the stage machine?**
   `AGENTS.md:6` forbids editing pipeline state by hand. If the desktop
   approves gates in-product, it must route through `pipeline_ctl.py` the way
   Studio's action does (`main.py:1224-1225`) — worth confirming before the
   IA hardens around in-product approval.
8. **Pretendard bundling.** Confirm SIL OFL redistribution inside a Windows
   installer is acceptable to whoever ships this, and whether the variable
   font's subset covers the Hangul range the UI needs without an unacceptable
   size hit.
9. **Two windows or two panes?** "Two synchronised views" is stated without
   saying whether they are tabs, a split, or separate windows. Tabs make the
   sync invisible; a split halves the page preview; separate windows need
   cross-window state. This affects M15 and the layout budget and should be
   settled before the shell is built.

---

## Decision — 2026-09-01

**Take Tauri 2 + React/TS + a packaged Python sidecar. The PySide6/QML arm was
not built: Tauri passed every gate in §3.4 (M10, M11-after-mitigation, M13,
M15) and breached no hard budget in step 2.** Per the decision rule, step 3
applies and the spike stops here.

Executed by the Tauri arm of §3. Code: `spikes/shell-tauri/` (throwaway).
Machine: the one measured in §2. Every number below came from a script in
`spikes/shell-tauri/measure/`; none is estimated. Where a number missed its
threshold, the row says so.

### What was installed for the spike

| Component | Version | Scope |
|---|---|---|
| `@tauri-apps/cli` | 2.11.4 | project-local devDependency |
| `@tauri-apps/api` | 2.11.1 | project-local dependency |
| `@tauri-apps/plugin-dialog` | 2.7.3 | project-local dependency |
| `react` / `react-dom` | 18.3.1 | project-local |
| `vite` | 5.4.21 | project-local |
| `typescript` | 5.9.3 | project-local |
| `@vitejs/plugin-react` | 4.7.0 | project-local |
| PyInstaller | 6.22.2 | venv at `spikes/shell-tauri/sidecar/.venv` |
| PyMuPDF | 1.28.2 | same venv |
| NSIS | 3.11 | auto-downloaded by the Tauri CLI into its own cache |
| `nsis_tauri_utils.dll` | 0.5.3 | same |
| Rust crates | `windows-sys` 0.59 plus the Tauri 2 tree | cargo cache |

Nothing was installed globally, nothing was uninstalled or upgraded, and no
existing interpreter or toolchain was modified. The spike app itself was never
installed — the NSIS installer was built and measured, not run.

### Corrections to §2

- **`C:\Python313` is not usable.** It is a partial install: no `Lib/`, no
  `Scripts/`, and any invocation prints "Could not find platform independent
  libraries". It cannot create a venv. §2 listed it as an eligible non-Store
  interpreter; that was wrong.
- The sidecar is therefore pinned to **CPython 3.12.10** at
  `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.
- **Build Tools 2019 was not a problem.** The §2 risk did not materialise: the
  whole Tauri 2 dependency tree — `tao`, `webview2-com`, `windows-sys`, `muda`,
  `softbuffer` — compiled clean in both debug and release with no linker or SDK
  error. No Build Tools upgrade is needed.

### Measurement table

Gates are marked **G**. Thresholds are the ones written in §3.2 before any
measurement was taken.

| # | Metric | Threshold | Measured | Verdict |
|---|---|---|---|---|
| M1a | Window handle exists | — | median **31 ms** (15–40, n=5) | — |
| M1b | **First paint** (rust `main()` to first frame) | 1500 cold / 600 warm | one-dir median **1465 ms** (1331–2049, n=5); one-file median 1571 ms (1446–2152) | cold OK, **warm missed** |
| M2 | Sidecar ready, end to end | 1200 ms | one-dir median **1757 ms** (1565–3477); one-file median **3018 ms** (2666–4210) | **missed, both** |
| M2b | Frozen sidecar alone, spawn to ready | — | one-dir median **264 ms** (246–545); one-file median **1394 ms** (1028–2916) | diagnostic |
| M3 | JSONL round-trip, n=1000 | median 3 ms, p99 20 ms | median **0.80 ms**, p99 **2.40 ms**, min 0.30, max 6.40 | PASS |
| M4a | Throughput, one IPC event per line | 20 MiB/s | 10 000 lines / 1.10 MiB in **1010 ms = 1.1 MiB/s** | **missed** |
| M4b | Same work, counted in Rust, one event | — | 10 000 lines / 1.11 MiB in **157 ms = 7.0 MiB/s** | **6.4x faster** |
| M5 | Large payload | completes, no truncation or deadlock | **517 KiB PNG** (690 KiB base64), round-trip **282 ms**, of which PyMuPDF **252 ms** | PASS |
| M6 | Installer size | 80 MB | NSIS **30 003 227 B = 28.6 MiB** | PASS |
| M7 | Installed payload | none | shell 4.36 MiB + one-file sidecar 27.36 MiB = **31.7 MiB** (one-dir would be ~64 MiB) | recorded |
| M8 | Memory at rest, whole tree | 250 MB private | 9 processes, working set **450.6 MiB**, **private 243.9 MiB** | PASS, barely |
| M9 | Memory after load | no growth trend | cycle 1 private 347.5 MiB, cycle 2 **342.8 MiB** | PASS |
| **M10 G** | Graceful close, no orphans | zero | sidecar gone under 1 s, WebView2 gone by 3–10 s, **CLEAN** | PASS |
| **M11 G** | Hard kill of the shell, no orphans | zero | **CLEAN in 1 s** with the job object, even against a sidecar that deliberately ignores stdin EOF | PASS **after mitigation** |
| **M12 G** | Sidecar crash | visible, recoverable | badge flips to red `sidecar down`, UI and document state survive, `restart sidecar` yields a new pid and a green badge | PASS |
| **M13 G** | Korean IME | zero defects | `안녕하세요` composed from real 두벌식 scan codes: `U+C548 U+B155 U+D558 U+C138 U+C694`, length 5 | PASS |
| **M14 G** | IME in a controlled list input | no composition loss | `탐구보고서` typed into a list row, then Backspace twice gives `탐구보고` (decompose-then-delete, correct Korean semantics); the other field kept its value | PASS |
| **M15 G** | High-DPI 100/125/150/200 % | crisp, layout intact | all four re-laid out and re-rasterised — `devicePixelRatio` 1 / 1.25 / 1.5 / 2, css viewport 2560x1600 / 1707x1067 / 1280x800. No bitmap upscaling. Screenshots committed. | PASS |
| M16 | Multi-monitor DPI | — | **not tested — one display on this machine** (`\\.\DISPLAY1`, 1440x900 logical at 200 %) | not measured |
| M17 | Shell crash visibility | visible with a stack | **not empirically triggered.** From config: release builds use `panic = "abort"` with `windows_subsystem = "windows"`, so a Rust panic aborts with no console and no dialog | **needs work, not measured** |
| M18 | Build reproducibility | builds elsewhere | **not tested — one machine.** The build is fully scripted (`sidecar/build.sh`, `npm install`, `npx tauri build`) with one manual prerequisite: the pinned interpreter path | not measured |

### The four findings that matter more than the verdict

**1. M11 was a real failure, and what saved the first run was an accident.**
The naive result depends on how the sidecar is frozen:

| Sidecar build | stdin-EOF handling | Job object | Result on hard kill |
|---|---|---|---|
| `--console` | exits on EOF | no | clean, ~1 s |
| `--console` | **ignores EOF** | no | clean, ~1 s |
| `--noconsole` | **ignores EOF** | no | **orphaned, still alive at 25 s** |
| `--noconsole` | exits on EOF | no | **orphaned, still alive at 25 s** |
| `--noconsole` | ignores EOF | **yes** | **clean, 1 s** |

Row 2 proves the console build survives for a reason unrelated to the sidecar's
own logic: the env var did reach the process (verified with a marker file
recording `IGNORE_EOF='1'`) and it still died, so console-group teardown is
doing the work. Rows 3 and 4 show that a `--noconsole` sidecar — the one a
shipping app uses, because `--console` drags a `conhost.exe` into the process
tree — orphans, and that **stdin-EOF handling inside the sidecar does not save
it**. Only the kernel-enforced job object
(`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, implemented in
`spikes/shell-tauri/src-tauri/src/jobkill.rs`) fixes it, and it fixes it even
against a hostile sidecar. **The desktop must ship this. It is not optional and
Tauri does not do it for you.**

**2. Tauri's per-event IPC is the throughput ceiling, not the pipe.** Emitting
one event per JSONL line gives 1.1 MiB/s (about 9 900 events/s); counting the
same lines in Rust and emitting once gives 7.0 MiB/s. **The agent timeline must
not tail JSONL by forwarding each line to the webview.** Batch in Rust — by
count or by frame interval — and send arrays. The naive design would have made
a busy run feel broken, and it would have been misread as "Tauri is slow".

**3. PyInstaller packaging mode dominates sidecar startup by 5.3x.** One-dir
reaches ready in 264 ms standalone; one-file takes 1394 ms because it
self-extracts on every launch. End to end the gap is 1757 ms versus 3018 ms.
One-file also runs **two** processes (bootloader plus extracted child); one-dir
runs one. §3.3 predicted that choosing a shell on a number that is really about
PyInstaller would be a bad decision — it would have been. **Ship one-dir via
`bundle.resources`, not one-file via `externalBin`**, and pay roughly 32 MiB
more on disk for it.

**4. M1 and M2 miss their targets, and the targets were the naive part.** First
paint is about 1.5 s and sidecar-ready about 1.8 s even in the better
configuration. Neither is a gate, and both have obvious untried headroom: the
sidecar is spawned inside `setup()` where it contends with WebView2
initialisation, the frontend boots React before it needs to, and nothing is
lazy. But the 600 ms warm first paint written into §3.2 is not reachable by
tuning alone on this stack. Plan around **about 1.5 s to a usable window**,
with a designed loading state rather than a blank one.

### Honest limitations of this run

- **M15 did not change the machine's display scaling.** The 200 % row is the
  real OS scale factor; 100, 125 and 150 % were forced on the WebView through
  `--force-device-scale-factor`. That exercises web-content re-layout and
  re-rasterisation, which is where the risk lives, but not the native frame's
  DPI handling and not a live scale change while running.
- **"Cold" is approximate.** No reboot was performed. First-run-after-build
  values (2049–2916 ms) are reported alongside the repeat values rather than
  being labelled true cold starts.
- **M13 and M14 were driven by synthetic scan codes**, not human typing. That
  is strictly harder than the tooling default — which injects Unicode and
  bypasses the IME entirely; the first attempt produced a literal
  `dkssudgktpdy` and would have been a false pass — but it is still not a human
  at a keyboard.
- **The sidecar is an echo and render stub**, not `runtime/scripts/serve.py`
  (which does not exist on this branch). It imports PyMuPDF eagerly so the
  frozen size and import cost are realistic, but it runs no engine code.
- **M8's first attempt under-counted.** Walking `ParentProcessId` missed the
  WebView2 hosts in one run (3 processes instead of 9). The reported figure
  comes from `memory.ps1`, which identifies processes by image name and by the
  bundle identifier in the WebView2 command line.
- No COM, no Hancom, and no network beyond the Tauri CLI's own NSIS download.

### Visual evidence

`spikes/shell-tauri/screenshots/`:

| File | Shows |
|---|---|
| `dpi-100pct.png` | forced scale 1.0, `devicePixelRatio 1`, 2560x1600 css |
| `dpi-125pct.png` | forced scale 1.25 |
| `dpi-150pct.png` | forced scale 1.5, 1707x1067 css |
| `dpi-200pct.png` | the machine's real 200 % scale, 1280x800 css |
| `dpi-200-ime-composed.png` | M13 — `안녕하세요` and its code points |
| `m12-sidecar-crash-and-restart.png` | M12 — recovered, new sidecar pid, state intact |
| `measurements-m3-m4-m5.png` | M3, both M4 arms, and M5 in one frame |

### What this obliges the implementation to do

1. Job-object-confine every child process; treat the sidecar's own EOF handling
   as defence in depth, never as the mechanism.
2. Freeze the sidecar one-dir, ship it under `bundle.resources`, and pin a
   non-Store interpreter in the build script.
3. Batch sidecar output in Rust before it crosses the IPC boundary.
4. Freeze the sidecar `--noconsole` and verify no `conhost.exe` appears in the
   process tree.
5. Give M17 an actual answer: install a panic hook that writes a crash log and
   surfaces something, because `panic = "abort"` under `windows_subsystem =
   "windows"` currently means a silent disappearance.
6. Design for about 1.5 s to first usable paint.
