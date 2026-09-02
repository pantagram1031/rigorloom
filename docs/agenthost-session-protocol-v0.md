# Agent Host session protocol v0 — the wire contract

`protocolVersion: 0.1.0` · host `0.2.0` · schemas
`rigorloom/agenthost-{run,events,turn,grant,session}/v0`

Written for the Desktop line, which is not on this branch. **Everything here is
additive**: a consumer built against host 0.1.0 keeps working unchanged — the
one-shot CLI still prints the same document with new members on it, the event
kinds are a superset, and every new host flag defaults to the old behaviour.

What changed, in one line each:

| # | Change | Old behaviour if you ignore it |
| --- | --- | --- |
| 1 | The turn loop **streams** when the provider declares `streaming: yes`, emitting `provider.stream.chunk` | you get the same final `provider.response`; the SSE branch stays dark |
| 2 | `--serve` runs a **long-lived host**: JSONL over stdio, many turns, persistent memory | absent ⇒ the one-shot CLI, unchanged |
| 3 | An **operator** can grant read-scoped document context into the prompt | no grant ⇒ no `documentContext`, exactly as before |

---

## 1. Streaming

### 1.1 When it happens

The host streams a turn **iff** the provider's `CapabilityProfile` reports
`streaming: "yes"`. `"no"` and `"unknown"` both fall back to `complete()` —
`supports()` is true only for a declared yes, because an unverified maybe is
not permission to open an SSE connection and wait. The operator can force the
old path with `--no-stream` (`streamMode: "off"`).

Today: **mock** `yes` (implemented, deterministic, no network) · **anthropic**
`yes` (SSE over `POST /v1/messages`, `stream: true`) · **router** `unknown` by
default. The router's stream **is implemented and tested** against a fake
server; `unknown` is a statement about the *gateway*, not about the code, and
an operator who knows their gateway speaks SSE declares
`"capabilities": {"streaming": "yes"}` in the router config — the profile then
records `declaredBy: "config"`.

### 1.2 What a consumer receives

A new event kind, already declared in 0.1.0 and now actually emitted:

```json
{"seq": 7, "kind": "provider.stream.chunk",
 "detail": {"turn": 1, "index": 3, "chunkType": "text", "text": "…"}}
```

`chunkType` is one of `text` · `tool_call` · `finish` · `done`
(`ah_codes.STREAM_CHUNK_TYPES`, a closed set).

- `text` → `detail.text`, capped at 4096 chars with `detail.truncatedChars`
  when it was longer.
- `tool_call` → `detail.toolCall` = `{callId, name, arguments}`, **whole**.
- `finish` / `done` → `detail.finishReason` when the frame carried one.

**A partial tool call never appears and is never dispatched.** There is no
partial-tool-call chunk shape: the adapter assembles fragmentary tool input
(Anthropic's `input_json_delta`, the OpenAI-shaped `function.arguments`) and
yields nothing until it parses as an object. A stream that dies mid-argument
therefore yields no `tool_call` chunk at all, and the run ends as
`provider_stream_incomplete` — a named provider fault, with the plan state
untouched, never a short answer.

### 1.3 New members on the run payload

```jsonc
{
  "streamMode": "auto",                 // or "off"
  "transports": ["stream"],             // the distinct paths this run used
  "turnLog": [                          // one entry per provider turn
    {"turn": 1, "transport": "stream", "fallbackReason": null,
     "historyLength": 0, "conversationLength": 2,
     "stream": {"chunks": 9, "textChunks": 6, "textBytes": 71,
                "toolCalls": 1},
     "toolCalls": 1, "finishReason": "tool_use"}
  ]
}
```

`fallbackReason` is non-null exactly when `transport` is `"complete"` and the
operator did not ask for it — it names the capability state that caused the
fallback. A turn that ended in a provider fault carries `"fault": "<code>"`
instead of `toolCalls`/`finishReason`.

### 1.4 New provider codes

`provider_stream_incomplete` (the stream closed before a terminal chunk) and
`provider_stream_chunk_invalid` (an undeclared chunk type, a malformed tool
call chunk, or content after the close). Both are `PROVIDER_CODES`: a provider
fault, never a document verdict.

---

## 2. The long-lived host

```sh
python agenthost/scripts/host.py --root $R --serve --provider mock
```

One process, many turns, JSONL frames on stdio. The framing is **the Runtime's,
imported not reimplemented** (`runtime/scripts/rt_jsonl.py`): one JSON object
per line, UTF-8, `\n`-terminated, 1 MiB cap, an oversized inbound line refused
without being parsed, stdout frames only and every diagnostic on stderr. A
consumer that already speaks to `runtime/scripts/serve.py` needs no new
transport code.

### 2.1 Frames

```
->  {"kind":"request","id":1,"method":"turn","params":{"instruction":"…"}}
<-  {"kind":"event","id":1,"event":{"seq":0,"kind":"run.started","detail":{…}}}
<-  … one event frame per event, AS IT HAPPENS (stream chunks included)
<-  {"kind":"response","id":1,"result":{…the run payload…}}
```

Errors are `{"kind":"error","id":1,"error":{"code","message","data"}}` carrying
an `AgentHostError` — the host's vocabulary, never `RpcError`.

At startup, before any request: `{"kind":"notification","method":"host/ready",
"params":{…state…}}`.

### 2.2 Methods (`ah_codes.SERVE_METHODS`)

| Method | Params | Result |
| --- | --- | --- |
| `initialize` | — | the state block (§2.3) |
| `turn` | `{instruction, maxTurns?}` | the full run payload, as the one-shot CLI prints |
| `context/grant` | `{items[], readScope?}` | `{ok, grant, recordedAt, session}` |
| `context/revoke` | `{readScope?}` | `{ok, grant, recordedAt, session}` |
| `session/state` | — | the state block |
| `shutdown` | — | `{ok, turnsServedThisProcess}`, then EOF |

Refusals a consumer must handle: an unknown method → `tool_unknown`; a
non-request frame, an unknown frame member, a bad id, a **reused id**, an empty
instruction, an unparseable or oversized frame → `config_invalid`.

**One turn at a time, single-threaded on purpose.** The Runtime door is a child
process with one stdio pair and the turn log is append-only; interleaving two
turns would produce a conversation whose order nobody can reconstruct. A
request arriving mid-turn waits in the pipe.

### 2.3 The state block

```jsonc
{
  "host": "rigorloom-agenthost", "hostVersion": "0.2.0",
  "protocolVersion": "0.1.0", "methods": [...],
  "sessionId": "…", "provider": {…CapabilityProfile…},
  "streamMode": "auto", "turnsServedThisProcess": 2,
  "session": {"schema": "rigorloom/agenthost-session/v0", "sessionId": "…",
              "dir": "<root>/agenthost/<sessionId>", "turns": 5,
              "attached": true, "historyWindow": 12,
              "truncationPolicy": "recent-exchanges", "exchangesResent": 5,
              "truncation": null, "unreadableTurnLines": 0,
              "unreadableGrantLines": 0, "grant": {…}},
  "grant": {…}
}
```

### 2.4 Memory, persistence and reattach

State lives in **`<root>/agenthost/<sessionId>/`** — beside the Runtime's
session store, never inside it. The Runtime owns `<root>/sessions/`.

- `turns.jsonl` — one record per exchange, append-only.
- `grants.jsonl` — one record per operator decision, append-only. A revoke is
  a record, not a deletion.

Both append through `rt_session.append_line`, the Runtime's own primitive, not
a copy of it: `open(path, "ab")` is **not** an atomic append on Windows (the
CRT emulates `O_APPEND` by seek-then-write), measured in this repository at 167
of 200 lines surviving four concurrent writers. A torn trailing line is
repaired before the next append and skipped on read, counted as
`unreadableTurnLines` rather than silently healed.

**Reattach**: a new host process on the same root and session id reads the logs
and continues — after a clean shutdown, after a kill, after a reboot. It emits
`session.attached` with the turn count. An operator grant recorded by an
earlier process is still in force and is **not** re-derived from CLI flags.

**Bounded memory, declared**: the newest `--history-window` exchanges (default
12) are resent as plain user/assistant turns; nothing is summarised. When the
window drops anything, the run payload carries

```json
"conversation": {"resent": 12,
                 "truncation": {"policy": "recent-exchanges",
                                "kept": 12, "dropped": 4}}
```

a `session.truncated` event fires, and the same object is written into the turn
record. A dropped exchange is never invisible.

`--memory` gives the same durability to the one-shot CLI (one turn appended per
invocation). Without either flag nothing is written and the directory is not
created — 0.1.0 behaviour, exactly.

### 2.5 What a turn record holds

Identities, never payloads: `instruction`, `reply`, `finishReason`, `ok`,
`providerId`, `model`, `transports[]`, `providerTurns`, `refusals[{stage,
code}]`, `planId`, `opsHash`, `validationOk`, `approvalId`, `truncation`,
`grantId`, `contextDisclosed`, `providerFault`. **No tool results and no
document text.**

### 2.6 A new field on `ProviderRequest`

`conversation: tuple` — prior exchanges, oldest first, each
`{"instruction": str, "reply": str | None}`. Separate from `history` (this
turn-loop's tool traffic) because they are separate things. Both shipped
adapters render it: Anthropic as user/assistant message pairs before the
current instruction, the router the same way in OpenAI shape. Default empty, so
an adapter that has not learned it is not silently dropping memory.

---

## 3. Operator-granted document context

### 3.1 The authority

A grant is created **only** from an operator channel: `--grant-summary` /
`--grant-region T:R,C` on the CLI (`grantedBy: "operator:cli"`), or a
`context/grant` frame on the long-lived host's own stdin
(`grantedBy: "operator:control-channel"`). There is deliberately no
`--grant-everything`.

The model cannot ask for one. `context/grant`, `context/revoke`,
`session/state`, `turn` and `shutdown` are `ah_codes.HOST_CONTROL_METHODS`, and
`ah_compile` refuses every spelling of them with `tool_forbidden` — the same
treatment `plan/apply` gets, and for the same reason: a refusal that says which
authority was reached for is auditable, and `tool_unknown` is not.

### 3.2 What reaches the prompt

Granted context rides in the existing `context` member of the provider request,
so no adapter had to learn a new field:

```jsonc
"context": {
  "sessionId": "…", "surface": [...], "readScope": "open",
  "documentContext": {"grantId": "3f2a…", "grantedBy": "operator:cli",
                      "documentSummary": {…}, "regions": […]}
}
```

`documentSummary` is the DocumentSummary of §3.3 of the runtime protocol;
`regions` are `document/readRegion` results for the granted addresses, fetched
**fresh from the Runtime on every turn**. They are not replayed from the turn
log, because the turn log never held them.

### 3.3 Read scope — how far the AGENT may reach

`--read-scope` / `params.readScope`, one of:

| Scope | `document/readRegion` from the model |
| --- | --- |
| `open` *(default)* | anywhere — the Phase-2 agent surface, unchanged |
| `granted` | only the granted addresses; anything else is `grant_scope_exceeded` at the **compile gate**, before the Runtime is asked, and a mixed batch is refused whole |
| `none` | refused outright |

`open` stays the default deliberately: narrowing it silently would be a
behaviour change wearing a feature's clothes, and `open` is what the Desktop
ships today.

**Be precise about what a grant is.** With `open`, a model can still read any
region by *asking for it as a tool*, and the result lands in the history that
goes back to the provider. A grant is therefore not by itself a
confidentiality boundary over the document — it bounds what the host
**volunteers**. `granted` makes it a boundary in the other direction too. The
Desktop UI should say which scope is in force, not merely that "context is
shared".

### 3.4 What is recorded

Run payload: `grant` (schema, grantId, grantedBy, readScope, items — each with
`kind` and, for a region, `address` + canonical `spec`) and `contextDisclosed`
(`{count, bytes, items:[{kind, spec, bytes, sha256}]}`).

Events: `context.granted` (the grant), `context.included` (what actually went
into this prompt — addresses, byte counts, SHA-256s), `context.revoked`,
`context.refused` (the agent reached past the grant).

`grants.jsonl`: the same, plus `at` (UTC) and `action` (`grant`/`revoke`).
The timestamp lives **in the log and not in the event**, because the event log
is deliberately clock-free — two identical runs produce identical bytes — while
an audit record that cannot say *when* is not an audit record.

**No document text anywhere in any of it.** The text exists in one request body
and in no log, event or turn record. A hash proves later exactly what left the
machine; it does not reproduce it.

---

## 4. Event kinds, complete

`run.started` · `run.finished` · `provider.selected` · `provider.request` ·
`provider.response` · `provider.failed` · **`provider.stream.chunk`** ·
`tool.requested` · `tool.refused` · `tool.compiled` · `runtime.result` ·
`runtime.refused` · **`session.attached`** · **`session.turn`** ·
**`session.truncated`** · **`context.granted`** · **`context.revoked`** ·
**`context.included`** · **`context.refused`** · `host.note`

Bold are new in 0.2.0. Still clock-free, still monotonic `seq`, still
`{seq, kind, detail?}` and nothing else. `provider.request` and
`provider.response` gained a `transport` member; `provider.request` also
carries `conversationLength`.

---

## 5. What is NOT proven

- **No live provider call.** Every assertion in
  `tests/test_agenthost_streaming.py`, `_session.py` and `_grant.py` is made
  against the deterministic mock or a local fake server the test starts and
  stops. The owed live leg (E4.5) is still owed, streaming included: the SSE
  parser has never met a real endpoint.
- **The router's `streaming: unknown`** is honest and stays that way until
  somebody measures a specific gateway. The code path is tested; the gateway
  is not.
- **No Desktop consumer exists on this branch.** The contract above is written
  to be adopted, not to describe something already adopted.
