# runtime/ — Runtime Protocol v0

Three front ends over one domain layer. Design: `docs/runtime-protocol-v0.md`
(protocol) and `docs/desktop-architecture.md` (processes and trust boundaries).

```sh
# JSONL over stdio — the protocol server
python runtime/scripts/serve.py --entry host  --root <dir>
python runtime/scripts/serve.py --entry agent --root <dir>

# the same operations, driven by arguments
python runtime/scripts/cli.py --root <dir> <command> [options]

# the agent-safe subset, as MCP tools
python runtime/scripts/mcp_server.py --root <dir>
```

All three share `--root`: sessions, plans, approvals and candidates live under
it, which is how a host can open a document that an agent connection then
inspects and proposes against.

## What this build does

The offline `preedit` backend only. A plan declares its backend; `xml` and
`com` plans — and op kinds those backends own — are refused with
`unsupported_backend` naming which backend would serve them. No COM, no
Hancom, no renderer, no network, no localhost server.

One vertical path, end to end: open a document → inspect it → propose a plan →
validate it → request approval → (host) resolve it → apply it → publish a
candidate with a hash-bound receipt and an offline verification report.

## Layout

| File | Owns |
| --- | --- |
| `scripts/rt_codes.py` | the closed error vocabulary, limits, versions |
| `scripts/rt_jsonl.py` | framing, strict JSON, canonical bytes |
| `scripts/rt_engine.py` | bounded child adapters onto `engine/` and `pipeline/` |
| `scripts/rt_session.py` | ingress, the session/plan/approval store, document views |
| `scripts/rt_plan.py` | OperationPlan, validation, approvals |
| `scripts/rt_apply.py` | execution, candidate publication, receipts |
| `scripts/rt_module.py` | distribution-module checkers, run against a session |
| `scripts/rt_core.py` | **the domain layer** — every operation, once |
| `scripts/rt_server.py` | JSONL transport and the two method registries |
| `scripts/cli.py` | argument parsing and exit codes |
| `scripts/mcp_server.py` | JSON-RPC 2.0 / MCP tool envelope |
| `scripts/serve.py` | server CLI entrypoint |

Stdlib only. Scripts are invoked by path and import their siblings through
`sys.path`, the same idiom as `engine/scripts` and `pipeline/scripts`.

Tests live in `tests/` (`tests/test_runtime_*.py`, helper
`tests/_runtime_client.py`), not here: `pyproject.toml`'s `testpaths` does not
include `runtime/tests`, and this work does not own `pyproject.toml`.

## Three rules worth restating

**Authority is the registry.** The agent entrypoint does not build the
host-only methods. `plan/apply` on an agent connection is `unknown_method`
because it is absent, not because a check refused it. The MCP tool surface is
*derived* from the agent registry, so it inherits that property rather than
re-implementing it.

**The source is never touched.** `workspace/openPath` validates, copies into
the session, and records the SHA-256. Every op reads one file and writes
another. `tests/test_runtime_session.py` pins byte identity of the original
across a full apply.

**A receipt path is not filesystem authority.** `bodySha256` detects drift but
is not authentication: a local writer can recompute it. Every candidate reader
therefore accepts only the canonical leaf the Runtime itself publishes —
`artifact<source suffix>` under that run directory — and refuses any absolute,
traversal, alternate-leaf, or malformed candidate path as pathless
`path_escape`. Receipt read, candidate chaining/comparison/verification,
rendering, and module checks share that resolver.

**One domain layer.** `rt_core` holds every operation; the front ends own only
framing, arguments and envelopes. `tests/test_runtime_parity.py` measures that
against a real corpus document: the same document and the same op proposed
through the server, the CLI and MCP give the same `opsHash`, the same
validation verdict, and — once a host approves — the same candidate SHA-256.

## Two hashes, two jobs

- `planHash` covers the whole plan object, identity and timestamp included. An
  approval binds to it, so two proposals of the same edit must differ.
- `opsHash` covers `{backend, boundSha256, ops}` — this document, these
  operations. It is identical across front ends and across time. This is the
  parity invariant.

## CLI

One JSON document per invocation on stdout, diagnostics on stderr.

```sh
R=./work
python runtime/scripts/cli.py --root $R open --path /abs/form.hwpx
python runtime/scripts/cli.py --root $R inspect --session $SID
python runtime/scripts/cli.py --root $R propose --session $SID \
    --op '{"kind":"fill_cell","table":0,"row":5,"col":1,"text":"value"}'
python runtime/scripts/cli.py --root $R validate --plan $PID
python runtime/scripts/cli.py --root $R request-approval --plan $PID
python runtime/scripts/cli.py --root $R approve --approval $AID \
    --plan $PID --plan-hash $PHASH
python runtime/scripts/cli.py --root $R apply --plan $PID --approval $AID
python runtime/scripts/cli.py --root $R verify --session $SID --run $RUN
```

Exit codes: `0` succeeded · `2` usage error · `3` refusal · `4` internal error.
The fourth is a deliberate extension of the repository's 0/2/3 contract: an
automation must be able to tell "the Runtime refused" from "the Runtime broke".

**A successful exit does not mean verification ran.** `apply` exits 0 when the
plan was applied and a candidate published; whether the offline checkers ran is
a separate fact carried in `result.candidate.checks.ranAll` and `.acceptance`.
`--require-checks` turns "a required check did not run" into exit 3 while still
reporting the candidate that exists. `verify` is fail-closed by construction.

## MCP

Newline-delimited JSON-RPC 2.0 over stdio, which is what the MCP stdio
transport specifies — messages are newline-delimited and must not contain
embedded newlines. (`Content-Length` header framing is the Language Server
Protocol's, not MCP's.) `initialize`, `notifications/initialized`, `ping`,
`tools/list` and `tools/call` are implemented; nothing else is claimed.

Sixteen tools, derived from the agent registry: `capabilities_list`,
`session_list`, `document_inspect`, `document_readRegion`, `plan_propose`,
`plan_validate`, `plan_get`, `approval_request`, `approval_get`,
`candidate_list`, `receipt_read`, `document_render`, `document_pageGeometry`,
`event_poll`, `module_list`, `module_check`.

There is no `workspace_openPath`, no `approval_resolve` and no `plan_apply`,
and there cannot be: the tool list is computed from `rt_core.AGENT_METHODS`,
and a schema for a host-only method fails at import. An MCP client inspects,
proposes, validates and asks for approval; a human on the host CLI does the
rest.

`python runtime/scripts/mcp_server.py --root <dir> --list-tools` prints the
surface, including what is deliberately not exposed.

### Claude Code

`.mcp.json` in the project, or `~/.claude.json` for a user-level server:

```json
{
  "mcpServers": {
    "rigorloom-runtime": {
      "command": "python",
      "args": [
        "/abs/path/to/rigorloom/runtime/scripts/mcp_server.py",
        "--root", "/abs/path/to/your/runtime-root"
      ],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

### Codex CLI

`~/.codex/config.toml`:

```toml
[mcp_servers.rigorloom-runtime]
command = "python"
args = [
  "/abs/path/to/rigorloom/runtime/scripts/mcp_server.py",
  "--root", "/abs/path/to/your/runtime-root",
]

[mcp_servers.rigorloom-runtime.env]
PYTHONIOENCODING = "utf-8"
```

Both need absolute paths — the adapter has no ambient working directory and
refuses to start without `--root`. Open documents with the host CLI first;
`session_list` is how the agent finds them.

## Page rendering

```sh
python runtime/scripts/cli.py --root $R render --session $SID [--page 0] [--dpi 96]
python runtime/scripts/cli.py --root $R render --session $SID --require-render
```

`document/render` produces a PNG **when the session already has a PDF** — the
opened document is one, or `--run` names a candidate that is one. An HWPX
cannot become a PDF here: conversion is Hancom COM or LibreOffice and this
build calls neither. In that case the answer is a structured unavailable state
with a reason from a closed set (`needs_conversion`, `no_rasterizable_artifact`,
`rasterizer_missing`, `artifact_missing`) — never an approximate page drawn
from the form scan's margins.

`available: false` is a **result**, not an error, so a UI can draw it. `render`
therefore exits 0; `--require-render` turns "no page" into exit 3 for a caller
that wants a picture or nothing.

The raster always has a session-relative `path`; base64 is inlined only under
512 KiB. A result carries `evidence.class = "structural_only"` and
`proofGrade: "none"` — a page image is a view of bytes, not evidence about them.

PyMuPDF is an **optional** dependency, imported lazily; without it the answer is
`rasterizer_missing`. `capabilities.render.converter` is flatly `no` whatever
the machine has installed. For the machine's actual inventory ask
`capabilities/list {probeRenderers: true}` — opt-in, because it costs ~8s.

### Making the PDF: `document/renderPrepare` (host only)

```sh
python runtime/scripts/cli.py --root $R render-prepare --session $SID
python runtime/scripts/cli.py --root $R render --session $SID   # now a page
```

The step that lights up the Document view on a machine with Hancom: a bounded
child runs `engine/scripts/com_backend.py convert` against the **session copy**
— never the file the operator picked — and the PDF lands at
`<session>/derived/source.pdf`, recorded against the source SHA-256 so it can
never be served for a different document.

**COM is serial and we never make room.** `tasklist` is checked for a live
Hancom process and a hit is `com_busy` — not a queue, and never a kill. There
is no kill path in `rt_convert` and a test asserts that by AST. An unreadable
`tasklist` counts as busy, not free. This is `engine/scripts/guards.py:234-240`
(T21) as a rule rather than a comment: two sessions each running
`taskkill /F /IM Hwp.exe` produced four RPC crashes in a row.

Refusals: `needs_hancom`, `com_busy`, `not_convertible`, `convert_failed`
(including `timedOut`). Preparing twice is a no-op. Success appends a
`pdf.prepared` event.

**The live COM leg has no automated test** — the suite may not start Hancom.
Everything around it is tested with the convert step substituted by a prebuilt
PDF. One live smoke on an operator machine is owed.

## Page geometry

```sh
python runtime/scripts/cli.py --root $R geometry --session $SID [--page 0]
```

`document/pageGeometry` returns where the text **is** on the rendered page, and
which editable address each line corresponds to — the two things an editor that
works *on* the page needs. Positions come from PyMuPDF reading the PDF Hancom
laid out, so the layout is the renderer's, never ours.

Its own method rather than a field on `render`, because a raster is per-zoom
and normalized rects are not, because the render frame already caps an inline
image at 512 KiB, and because geometry is cached on the PDF hash while a raster
is not.

**Rects are normalized** — `[x0, y0, x1, y1]` as fractions of the page, origin
top-left, y down. Multiply by the raster's pixel size and draw. `pageSize`
gives the points back if you want them.

Each span is a **line** (PyMuPDF splits at font runs, which would fragment
every label) and carries one of three outcomes:

- `unique` — one address, set;
- `ambiguous` — `address: null` plus every candidate. **Never a pick.** T41 is
  what happens when one unscoped key matches five sheets and the gate passes;
- `unmapped` — `address: null`, and the line still renders as non-editable.

Matching normalizes with `pipeline/scripts/check_residue.normalize_text`,
**imported**, so page matching and the residue gate cannot disagree about what
"the same string" is.

**Empty seats** carry the derivation used: `matched_text`, `cell_borders` (the
rules drawn on the page enclose a box alignment tied to this seat) or
`interpolated` (from a uniquely matched label immediately to its left). A seat
that cannot be placed is **absent** — the Desktop falls back to tree editing
for it, rather than being handed a box that is probably wrong.

`cell_borders` is the one that reaches an empty cell nowhere near a label, and
it is why on-page editing has a target: text-based derivation placed **0 of
473** fill regions across the corpus, because an empty cell has nothing to
match. Hancom strokes every ruling as a line segment rather than a rectangle,
so the grid is rebuilt from the segments — clustered into rules, then kept
only as the smallest rectangles whose four sides are all actually drawn.

Alignment is earned. An anchor is a span naming exactly one table cell whose
drawn box also carries that cell's text; from it the row is walked outward in
lockstep with the declared cells, and every step must be adjacent **and** must
agree with the text the page shows there. The walk stops at the first
disagreement and places nothing past it, so an empty seat is trusted only
because the labelled cells walked to reach it were confirmed by the render.
Two anchors that disagree about a cell refuse it rather than averaging.

Measured on the 10 real Hancom renders (`tests/corpus/forms/render`, produced
by `com_backend.py` on Hancom Office 13.0.0.2986): **73 of 473 seats, all
`cell_borders`**, every one of them a box the page really drew, empty in the
render, none overlapping. The remaining 400 are honestly absent — 148 sit in
tables with no anchor anywhere, and two forms are ruled with underlines rather
than boxes, so nothing on them closes. `seatAbsences` counts the reason per
page (`no_drawn_grid`, `no_anchor_on_page`, `no_anchor_in_row`, `grid_gap`,
`cell_mismatch`, `alignment_failed`) and `drawnCells` says how many closed
cells the page yielded, which separates "not ruled" from "not aligned".

No PDF means no geometry, with the same closed reasons `render` uses. Geometry
is cached on `(pdf sha256, page)`, bounded at 64 entries; the reconstructed
grid joins that cached extraction, so borders are not re-derived per call.

## The typeface name

`document/inspect` carries the face the document declares, per language:
`summary.baselineCharPr.face`, `summary.blackCharPr.face`,
`regions[].charPrFace` and `regions[].charPrSuggestedFace`. It is the HWPX
header's own join of `charPr/fontRef` onto the `fontface` tables — never
inferred, never defaulted, and a test asserts every name on the wire appears in
the document's own `header.xml`.

`null` means *this document declares no resolvable face for that charPr*.
`summary.typefaces.state` is the separate fact — `read`, or `unavailable` with
a reason when the profile carries no mapping at all. One null cannot carry
both. Design: `docs/runtime-protocol-v0.md` §14.

## Distribution-module checkers

```sh
python runtime/scripts/cli.py --root $R modules
python runtime/scripts/cli.py --root $R module-check --session $SID --module gongmun
python runtime/scripts/cli.py --root $R module-check --session $SID --module gongmun \
    --checker check_gongmun --run $RUN --require-checks
```

`module/check` runs a distribution module's declared checkers against the
document a session holds and returns their findings — severity, code, message,
and the finding's address translated into the Runtime's own addressing where
the checker gives one. Design and the full argument: `docs/runtime-protocol-v0.md`
§13.

**Agent-safe.** The checker contract is a verdict producer (JSON on stdout,
exit 0/2/3), and it is not trusted to be: the document is copied into
`<session>/checks/<callId>/`, the child runs with that as its cwd, and the
directory is deleted afterwards, so the session copy, the candidate and the
operator's original are unreachable by construction. A module is reachable at
all only if the operator enabled it in `enabled.yaml` — an install-time act no
wire call can perform.

**A checker that did not run is never a pass.** Rows are `ran` / `skipped` /
`unavailable`, each with a reason from a closed set: `subject_undeclared`,
`needs_workspace`, `spawn_failed`, `timed_out`, `missing_dependency`,
`usage_error`, `no_verdict`. `acceptance` is true only when every selected
checker ran, was clean, and had every input its declaration says it needs; a
checker that ran without one is `partial`, not clean.

**Which checkers are runnable** comes from `provides.checkers[].subject`
(`modules/README.md`): `document` runs, `workspace` is skipped
(`needs_workspace` — a session is one document, not a report workspace),
absent is skipped (`subject_undeclared`). Core never learns a module's name.

Each checker is bounded by `timeoutSeconds` (default 120s, clamped to
[1, 600]); a hung one is killed and the rest of the pack still runs. The kill
reaches the direct child only — descendants are not contained, same as
everywhere else here.

`RIGORLOOM_MODULES_ROOT` and `RIGORLOOM_MODULES_ENABLED` override where modules
and enablement are read from; both default to this checkout, and
`capabilities.modules` reports which was used.

## Events

Every session keeps `<session>/events.jsonl`, appended on each mutation:
`session.opened`, `plan.proposed`, `plan.validated`, `approval.requested`,
`approval.resolved`, `plan.applied`, `candidate.published`, `module.checked`.

```sh
python runtime/scripts/cli.py --root $R events --session $SID [--after N]
```

On the wire there are two surfaces because there are two transports:

- `event/subscribe {sessionId, after?, intervalMs?}` → notifications on the
  same stdio stream, seq-ordered and gap-free, replayed from `after+1`. Plus
  `event/unsubscribe`. **Protocol-only** — a push has nowhere to live in an MCP
  tool call.
- `event/poll {sessionId, after?, limit?}` — the same events, request/response,
  and an MCP tool, so a pull-only client is not left out.

The sequence is the **line index**, not a stored field: monotonic, gap-free and
duplicate-free by construction, so a cursor survives a reconnect. Appends take
a real file lock — `open("ab")` plus one `write` is *not* an atomic append on
Windows (CPython emulates `O_APPEND` with seek-then-write; four threads × fifty
lines produced 167 of 200 on this bench, silently).

## Packaging: `RIGORLOOM_CHILD_PYTHON`

Engine children spawn under this interpreter when it is set, and under
`sys.executable` otherwise. A frozen host needs it: there `sys.executable` is
the host, so every child re-launches the application. A set-but-broken value is
refused at `initialize` with `child_python_invalid` rather than surfacing as a
mystery twenty seconds into the first document call.
`capabilities.childPython` reports the path and where it came from.

## Mock agent

`runtime/scripts/mock_agent.py` is a deterministic driver of the agent surface,
for repeatable Desktop, state and approval tests.

```sh
# a host opens the document first — the agent surface cannot
python runtime/scripts/cli.py --root $R open --path /abs/form.hwpx

python runtime/scripts/mock_agent.py --root $R                      # propose-one
python runtime/scripts/mock_agent.py --root $R --scenario propose-invalid
python runtime/scripts/mock_agent.py --root $R --scenario propose-then-wait
python runtime/scripts/mock_agent.py --root $R --redact              # golden output
python runtime/scripts/mock_agent.py --root $R --probe-authority     # show the boundary
python runtime/scripts/mock_agent.py --root $R --door mcp            # same run, via MCP
```

It inspects the document, picks one target, proposes a typed plan carrying a
fixed marker, validates, requests approval, and reads plan/approval/candidate
status back. It stops there: it does not approve and it does not apply, because
those methods are absent from an agent connection. `--probe-authority` attempts
them anyway and records the `unknown_method` refusals so a test can show the
boundary instead of trusting it.

**Which door.** The default is `protocol` — the mock spawns
`serve.py --entry agent` and speaks JSONL over its stdio, because that is the
transport `docs/desktop-architecture.md` §1 puts a Desktop Agent Host on.
`--door mcp` runs the same scenarios through the MCP adapter; a test asserts
both doors reach the same `opsHash`.

**Determinism.** No randomness and no clock in the decision path. The target is
the first editable region in document order whose charPr preflight needs no
declaration — a seat carrying a `scriptAnomaly` or `colorAnomaly` is skipped,
never filled with a guessed charPr, because those are exactly the seats that
print smaller or in the guide colour. If no clean seat exists the mock refuses
with `no_clean_seat`. The value written is `--marker`, a fixed string.

`--redact` blanks only identity and timestamps (`planId`, `approvalId`,
`createdUtc`, …) and deliberately keeps the content hashes, so the output is a
golden document you can diff and `opsHash` is still in it. Two runs against
byte-identical sources produce identical redacted output.

Exit codes follow the CLI's: `0` the scenario held, `2` usage, `3` the
scenario's own expectation failed or the surface refused, `4` internal.
`propose-invalid` exits **0** — it succeeded at provoking the refusal it exists
to provoke, and `expectationMet` says so.

## Known gaps

- Children are bounded (time, output, environment allowlist) but not
  contained: no process group, no Windows Job.
  `pipeline/scripts/diagnostic_candidate_core.py:1128` does that properly.
- Records under `--root` are last-writer-wins; nothing serialises two hosts
  driving one root.
- The MCP adapter implements the five methods above and no resources, prompts,
  sampling, completion or logging capabilities.
