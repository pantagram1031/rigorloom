# agenthost/ — the provider boundary

The Agent Host is the only network-capable component in the program, and
deliberately the one that cannot touch a document. It talks to a model
provider, compiles the model's tool requests into **agent-safe** Runtime calls,
and executes what survives against an agent-authority connection.

```sh
# a host opens the document first — neither this host nor its provider can
python runtime/scripts/cli.py --root $R open --path /abs/form.hwpx

python agenthost/scripts/host.py --root $R --provider mock
python agenthost/scripts/host.py --root $R --provider mock --scenario escalate
python agenthost/scripts/host.py --root $R --provider router --config router.json
python agenthost/scripts/host.py --capabilities --provider mock   # no root needed

# a conversation, instead of N cold starts
python agenthost/scripts/host.py --root $R --serve --provider mock   # JSONL stdio
python agenthost/scripts/host.py --root $R --provider mock --memory  # one shot, durable

# read-scoped document context, granted by an OPERATOR and never by the agent
python agenthost/scripts/host.py --root $R --provider mock \
    --grant-summary --grant-region 0:0,14 --read-scope granted
```

## The shape of it

```
  provider (network)          agenthost (this tree)         runtime (offline)
  ─────────────────           ─────────────────────         ─────────────────
  mock | custom router  <-->  ah_host turn loop
                             ah_compile gate  ────────────>  serve.py --entry agent
                             ah_events log                   (nine agent methods)
```

Document processing stays network-free: the Runtime and the engine never learn
that a provider exists. Nothing here has host authority — no approve, no apply,
no export, no proof mutation.

| File | Owns |
| --- | --- |
| `scripts/ah_codes.py` | the closed vocabularies, kept apart from the Runtime's |
| `scripts/ah_provider.py` | the adapter contract and `CapabilityProfile` |
| `scripts/ah_compile.py` | **the gate**: provider tool request → Runtime call, or refuse |
| `scripts/ah_events.py` | the ordered event log a UI renders |
| `scripts/ah_stream.py` | chunks → one whole response; refuses a truncated stream |
| `scripts/ah_session.py` | the persistent turn log, the window, reattach |
| `scripts/ah_grant.py` | operator-granted read-scoped document context |
| `scripts/ah_mock.py` | the deterministic provider |
| `scripts/ah_router.py` | the configurable OpenAI-compatible endpoint |
| `scripts/ah_anthropic.py` | the official Messages API adapter |
| `scripts/ah_host.py` | the turn loop |
| `scripts/ah_serve.py` | the long-lived host: JSONL frames on stdio |
| `scripts/host.py` | CLI entrypoint |

Stdlib only. Tests live in `tests/` (`tests/test_agenthost_*.py`, helper
`tests/_agenthost_support.py`), because `pyproject.toml`'s `testpaths` is the
collected set and this work does not own `pyproject.toml`.

## Capabilities are declared, never assumed

A consumer asks `profile.supports("streaming")` and gets a truthful answer,
because every capability has **three** states — `yes`, `no`, `unknown` — and
`supports()` is true only for `yes`. An unverified maybe is not permission to
try and hang. Every value records whether it came from the adapter, from
config, or from a probe.

```
modelDiscovery · text · structuredToolUse · structuredOutput · streaming ·
resumableThread        + authOwnership (none | env_reference |
                          os_store_reference | provider_managed)
```

A profile that omits a capability is refused at construction: an adapter must
say `unknown` on purpose rather than be read as declining by accident.

## The compile gate

Every tool request passes through `ah_compile.compile_tool_call` before any
door is touched. The allowed set is **derived** from `rt_core.AGENT_METHODS` —
the same tuple the MCP adapter derives from — so a host action cannot become
reachable by editing this tree. `approval/resolve`, `plan/apply` and
`workspace/openPath` are refused with `tool_forbidden` in either spelling,
before the Runtime is asked. The Runtime would refuse them too; a boundary that
relies on the far side catching everything is not a boundary.

## Two failure worlds

`AgentHostError` is not `rt_codes.RpcError`, and the two code sets are
disjoint. A dead endpoint, a timeout, a malformed completion or a missing
credential is a **provider fault**: the run stops, the fault is named, and the
plan state is untouched. No fallback reply is invented, and no provider outage
is ever reported as a document verdict.

## Providers

**`mock`** — deterministic, no network, no clock. Decides purely from the tool
results it has already seen; two runs against byte-identical documents produce
identical tool requests. Target selection is imported from
`runtime/scripts/mock_agent.py` so the model side and the runtime fixture can
never disagree about what the obvious edit is. Scenarios: `propose-one`,
`propose-invalid`, `propose-then-wait`, `escalate` — the last asks to apply on
purpose, so a UI can watch the gate refuse it.

**`router`** — a configurable OpenAI-compatible endpoint.

```json
{
  "providerId": "my-router",
  "baseUrl": "https://gateway.example.invalid/v1",
  "model": "some-model",
  "credential": { "source": "env", "key": "MY_ROUTER_TOKEN" },
  "capabilities": { "streaming": "no", "structuredToolUse": "yes" },
  "timeoutSeconds": 60
}
```

The config holds a credential **reference** — the name of an environment
variable or an OS store key — never a value. A config carrying a
secret-shaped member (`apiKey`, `token`, `secret`, `authorization`, …) is
refused at load, by member name, whatever the value looks like. The secret is
read at call time, lives in one local variable, and never reaches an event, a
log line, an error payload or a returned object; secret-shaped headers are
redacted before anything is recorded. OS credential-store lookup is **not
implemented** in this slice and says so (`credential_source_unsupported`).

Tested only against a local fake server the test starts and stops
(`tests/_agenthost_support.py`). **No live-provider test exists and none is
claimed.**

**`anthropic`** — the official Messages API, over the same contract.

```sh
python agenthost/scripts/host.py --capabilities --provider anthropic   # keyless
python agenthost/scripts/host.py --provider anthropic --live-smoke     # needs a key
python agenthost/scripts/host.py --root $R --provider anthropic
```

Config is **optional**: the defaults are the documented endpoint, the
recommended model (`claude-opus-5`) and a reference to `ANTHROPIC_API_KEY`, so
`--capabilities` works with nothing set and reports the missing credential
rather than refusing to describe itself. Override any of it the same way the
router does; a secret-shaped config member is refused by name, as there.

Declared capabilities: `streaming` **yes** (SSE), `structuredToolUse` **yes**,
`text` **yes**, `modelDiscovery` **yes** (`GET /v1/models`), `resumableThread`
**no** (the Messages API is stateless — the host resends the whole history each
turn, as with the router), `structuredOutput` **unknown** (the API offers
`output_config.format`; this adapter does not send it, so nothing is promised),
and `vision` **unknown** — the API accepts image blocks, this adapter sends
none, and document images are a later slice. That is *not yet*, not *no*, which
is exactly why `unknown` exists.

Retry policy, minimal and principled: `429` honours `retry-after` when it is
short enough to be a wait rather than a hang (longer than 30 s is honoured by
**refusing**, with the advertised delay reported); `5xx` — including `529
overloaded_error` — and timeouts get **one** fixed backoff; **no other 4xx is
ever retried**, because sending a bad request again just sends it again. A
fault still ends the run cleanly as a provider failure. There is no fallback
provider.

#### Wire shapes: verified vs assumed

Read offline from the bundled `claude-api` skill — `curl/examples.md`,
`shared/error-codes.md`, `shared/tool-use-concepts.md`, `shared/models.md`,
`typescript/claude-api/streaming.md`. **Verified (v):** `POST /v1/messages`;
`x-api-key` + `anthropic-version: 2023-06-01`; required `max_tokens`; `system`
as content blocks; `tools[].input_schema`; response `content[]` / `stop_reason`
/ `usage`; the `tool_use` block shape; `tool_result` continuation in a **user**
message with every result for one assistant turn in **one** message;
`tool_choice` auto/any/tool/none; SSE `message_start` … `message_stop` with
`text_delta` and `input_json_delta`; the error envelope and the status→type
map; `retry-after` on 429; `GET /v1/models/{id}` fields.

**Assumed (a), because those files did not pin them** — marked in
`ah_anthropic.py` at each use rather than guessed silently:

| Assumption | Why it is a guess |
| --- | --- |
| `GET /v1/models` list envelope is `{"data": [...]}` | the docs show *retrieve*, not *list*; the adapter also tolerates a bare array |
| streamed tool input arrives as `delta.partial_json` | only the delta *type name* `input_json_delta` was pinned, not its field |
| `content_block_start` for a tool block is `{"type":"tool_use","id","name","input":{}}` | the doc's SSE sample only shows a text block |
| SSE `ping` and `error` event names | not in the bundled sample |

Deliberately **not sent**: `temperature`, `top_p`, `top_k` (removed on current
models — a 400) and assistant prefill (removed). The adapter cannot inherit
that class of failure because it never emits them.

**The live leg is not run.** Every test talks to a local fake. `--live-smoke`
is implemented and its keyless refusal is tested; one real request against the
API is owed, and the capability payload says so under `notes.liveSmoke` until
somebody reports a green one.

## The event log

Ordered, closed-kind, and clock-free: events carry a monotonic `seq` and
nothing that varies between two identical runs. A UI stamps arrival times
itself, which is the honest place for them. `--events FILE` mirrors the log to
JSONL as it happens; `--redact` blanks ids for a golden document, using the
Runtime's own redaction rule so an Agent Host golden and a mock-agent golden
redact identically.

Kinds: `run.started`, `provider.selected`, `provider.request`,
`provider.response`, `provider.failed`, `provider.stream.chunk`,
`tool.requested`, `tool.refused`, `tool.compiled`, `runtime.result`,
`runtime.refused`, `session.attached`, `session.turn`, `session.truncated`,
`context.granted`, `context.revoked`, `context.included`, `context.refused`,
`host.note`, `run.finished`.

## Streaming reaches the turn loop

The loop calls `provider.stream()` **iff** the profile declares
`streaming: "yes"`. `"no"` and `"unknown"` both fall back to `complete()`, and
the run's `turnLog` records which path each turn actually took plus the reason
it was not the other one — a measurement, never inferred from the promise.
`--no-stream` forces the old path.

Mock **yes** (deterministic, no network) · anthropic **yes** (SSE) · router
**unknown**, which is a statement about the *gateway*: the router's SSE path is
implemented and tested against a fake server, and an operator who knows their
gateway declares `"capabilities": {"streaming": "yes"}` in the config.

**A partial tool call is never dispatched**, structurally: the chunk
vocabulary has no shape for one. An adapter assembles fragmentary tool input
itself and yields nothing until it parses, so a stream cut mid-argument yields
no tool-call chunk at all — and a stream that never reaches its terminal chunk
is `provider_stream_incomplete`, a named provider fault, not a short answer.
Proven by cutting an SSE body mid-`input_json_delta` and showing the Runtime is
never asked.

## A conversation with memory

`--serve` keeps one process alive and speaks JSONL frames on stdio, reusing the
Runtime's own framing (`rt_jsonl`): `initialize`, `turn`, `context/grant`,
`context/revoke`, `session/state`, `shutdown`, with every event pushed as it
happens so a streamed answer is visible mid-turn. `--memory` gives the one-shot
CLI the same durability.

State lives at `<root>/agenthost/<sessionId>/` — beside the Runtime's session
store, never inside it — as `turns.jsonl` and `grants.jsonl`, appended through
`rt_session.append_line`, the Runtime's primitive rather than a second copy of
it (`open("ab")` is not an atomic append on Windows; this repo measured 167 of
200 lines surviving four writers without the lock). A new host on the same
session reloads both and continues, after a clean exit or a kill.

Memory is bounded and the bound is declared: the newest `--history-window`
exchanges (default 12) are resent, nothing is summarised, and anything dropped
appears in the run payload, in a `session.truncated` event and in the turn
record. A turn record holds identities — instruction, reply, transports, plan
id, refusal codes — and never a tool result or a line of document text.

Full wire contract for consumers: **`docs/agenthost-session-protocol-v0.md`**.

## Read-scoped document context, by operator grant

`--grant-summary` / `--grant-region T:R,C` on the CLI, or a `context/grant`
frame on the long-lived host's own stdin. Those are the only two ways one
exists. The model cannot ask: `context/grant` and its siblings are
`HOST_CONTROL_METHODS`, refused by name with `tool_forbidden` in either
spelling — the same treatment `plan/apply` gets.

`--read-scope` bounds what the AGENT may reach: `open` (default — the Phase-2
surface, unchanged), `granted` (a `document_readRegion` outside the grant is
`grant_scope_exceeded` at the compile gate, before the Runtime is asked; a
mixed batch is refused whole), or `none`.

Be precise about what this is. Under `open` a model can still read any region
by asking for it as a tool, so a grant is not by itself a confidentiality
boundary over the document — it bounds what the host **volunteers**. `granted`
makes it a boundary in both directions, and it is off by default because
tightening the shipped surface silently would be a behaviour change wearing a
feature's clothes.

Privacy: the grant record and every event name **addresses, byte counts and
SHA-256s — never text**. The granted text exists in one request body and in no
log, event or turn record, which is also why reattach re-fetches it from the
Runtime instead of replaying it.

## Exit codes

`0` the run completed · `2` usage · `3` refusal or provider fault · `4`
internal. Same table as the Runtime CLI.

## Known gaps

- The official first-party provider path is a later slice: it needs credential
  UI, which does not exist yet.
- OS credential-store resolution is declared and refused, not implemented.
- `resumableThread` is `no` everywhere; the host resends history each turn.
  Memory is now the HOST's (`ah_session`), which is why that stays `no`: no
  endpoint is trusted to have kept anything.
- No retry, no backoff, no fallback provider. A fault ends the run.
- **No live provider call, streaming included.** The SSE parser has never met a
  real endpoint; every test talks to a local fake. E4.5 is still owed.
- The long-lived host serves **one turn at a time**. There is no cancel frame:
  a turn runs to its own bound (`maxTurns`), and a client that wants out closes
  stdin.
- `--read-scope granted` bounds `document/readRegion` only. Every other agent
  method is untouched by a grant, and `document/inspect` still returns the
  document's structure to any agent connection.
