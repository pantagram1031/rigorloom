# Stage 6 A2 — real-provider Agent Host loop

Read-only survey of this worktree. No code or git changes. Word budget: under 1500.

## 1. Providers, selection, credentials, compile gate

**Roster.** CLI `PROVIDERS = ("mock", "router", "anthropic")` (`agenthost/scripts/host.py:47`). Factory `build_provider` (`host.py:96–110`): `mock` → `MockProvider`; `anthropic` → `AnthropicAdapter(config or {})` (config optional); `router` → `RouterAdapter` and **requires** `--config`. No other adapters exist (`agenthost/scripts/ah_mock.py`, `ah_router.py`, `ah_anthropic.py`). Desktop Settings offers the same three (`desktop/src/components/Settings.tsx:36–51`).

**Selection.** Host CLI: `--provider` default `mock` (`host.py:123`). Desktop: `ProviderSettings.provider` in prefs (`desktop/src/store.ts:677–682`, default `mock`); `sendInstruction` passes that id into Tauri `agent_host_run` (`desktop/src/actions.ts:3481–3487`; `desktop/src-tauri/src/main.rs:478–512`; spawn args `--provider` at `desktop/src-tauri/src/agenthost.rs:445–452`). Env is **not** used to pick the provider. `RIGORLOOM_AGENT_HOST` / `RIGORLOOM_PYTHON` only locate `host.py` (`agenthost.rs:81–156`).

**Credentials (Python).** Config holds a **reference**, never a value. Secret-shaped member names are refused (`ah_router.py:61–81`, `73–81`). `CredentialRef.source` is `none` | `env` | `os_store` (`ah_router.py:56, 115–132`). `env` reads `environ[key]` at call time. `os_store` always raises `credential_source_unsupported` (`ah_router.py:128–132`). Anthropic default: `{source: env, key: ANTHROPIC_API_KEY, header: x-api-key, scheme: raw}` (`ah_anthropic.py:201–205`). Router default timeout 60 s (`ah_router.py:54`); Anthropic 120 s, `maxTokens` 16000, model `claude-opus-5`, base `https://api.anthropic.com` (`ah_anthropic.py:81–90`).

**Credentials (desktop Settings).** Pane “설정 — 에이전트 제공자” (`Settings.tsx:152`). Save path:

1. UI prefs: `savePrefs({ provider })` — which provider, router `baseUrl`/`model`/`storeKey`, anthropic `model`/`storeKey`. Defaults: store keys `RIGORLOOM_ROUTER` / `RIGORLOOM_ANTHROPIC` (`store.ts:677–706`; `actions.ts:3261–3271`).
2. Host config file: `{app_local_data_dir}/agenthost/{provider}.json` unless `RIGORLOOM_APPDATA` (`main.rs:67–74`; `agenthost.rs:282–306`). Rust **composes** `credential`; the webview cannot send it (`agenthost.rs:222–272`). If a secret is stored: `{source: env, key: RIGORLOOM_PROVIDER_CREDENTIAL, header/scheme}` — Anthropic `x-api-key`/`raw`, router `Authorization`/`bearer` (`agenthost.rs:180–185, 251–272`). If Anthropic has no stored secret, the `credential` member is omitted so the adapter default `ANTHROPIC_API_KEY` remains (`agenthost.rs:273–278`).
3. Secret: Windows Credential Manager target `rigorloom-desktop:{storeKey}` (`desktop/src-tauri/src/credstore.rs:35–38, 78–124`). IPC `credential_set` is one-way; `credential_status` returns present/absent + **byte count**, never the value (`credstore.rs:198–216`; `main.rs:520–544`). At run, `credstore::get` is set **only** on the child `Command` as `RIGORLOOM_PROVIDER_CREDENTIAL` (`agenthost.rs:347–356, 467–477`). Events/logs redact `authorization` / `x-api-key` (`agenthost/scripts/ah_events.py:25–28`). Non-Windows store returns `credential_store_unavailable` (`credstore.rs:183–196`).

**Compile gate.** Allowed tools = `mcp_server.tool_name(m)` for every `rt_core.AGENT_METHODS` except `initialize` (`ah_compile.py:40–43`; roster `runtime/scripts/rt_core.py:91–110`): `capabilities/list`, `session/list`, `document/inspect`, `document/readRegion`, `plan/propose`, `plan/validate`, `plan/get`, `approval/request`, `approval/get`, `candidate/list`, `candidate/compare`, `receipt/read`, `document/render`, `document/pageGeometry`, `event/poll`, `module/list`, `module/check`. Forbidden by identity: `HOST_ONLY_METHODS` (`rt_core.py:123–128`) — `workspace/openPath`, `approval/resolve`, `plan/apply`, `document/renderPrepare` — both slash and underscore spellings (`ah_compile.py:48–51, 87–94`). Run payload lists `neverCompiled` (`ah_host.py:190`). Host loop calls `complete()`, not `stream()` (`ah_host.py:109–119`; Settings copy `Settings.tsx:435–438`).

## 2. Composer → Host → Runtime → 검토 queue

**Instruction.** Composer `sendInstruction` (`actions.ts:3458–3511`) → invoke `agent_host_run` (`runtime.ts:420–442`) → spawn `host.py --root --session --provider --door protocol --instruction --events {appdata}/agenthost/runs/{turnId}.jsonl` (`agenthost.rs:436–460`). One process per turn; no stdin loop (`agenthost.rs:5–13`). Host `AgentHost.run(instruction)` (`ah_host.py:88–196`) opens an **agent** Runtime door (`host.py:196–200`); document I/O never sees the provider (`ah_host.py:6–10`).

**Events back.** Host `--events FILE` JSONL, kinds in `ah_events.py:31–45`. Rust tails complete lines, batches every 120 ms, emits Tauri `agenthost://events` (`agenthost.rs:59–62, 593–635`). Webview `onAgentEvents` (`runtime.ts:556–562`). On exit, stdout JSON is authoritative (`actions.ts:3490–3497`). Shell run timeout 20 min (`agenthost.rs:64–67`).

**Plan arrival.** Host keeps latest successful `plan_propose` / `plan_validate` / `approval_request` (`ah_host.py:167–185`; `summarize` exposes `planId` + `opsHash`, `ah_host.py:63–66`). Desktop `payload.plan.planId` → `adoptAgentPlan` re-reads **this** sidecar: `getPlan` + `validatePlan`, projects ops into `draft` (`actions.ts:3372–3437, 3500–3508`). That is the 검토 queue. A provider fault leaves the queue untouched (`actions.ts:3454–3456`; `ah_host.py:13–16`).

**What the host cannot do.** Propose and `approval/request` only. It cannot `approval/resolve` or `plan/apply` (compile + agent registry). It cannot open a document (`ah_host.py:207–211`). Stop kills the child; host holds no document lock (`agenthost.rs:559–562`).

## 3. One recorded real session on this PC

**Least new code: Anthropic.** Adapter already POSTs `/v1/messages` (`ah_anthropic.py:276–327`). Path: Settings → Anthropic → paste key into OS store (store key default `RIGORLOOM_ANTHROPIC`) **or** set process env `ANTHROPIC_API_KEY` for CLI `--provider anthropic` without desktop config. Optional `--live-smoke` (`host.py:137–140, 162–179`; `ah_anthropic.py:697–730`). Router needs a `baseUrl` + model and is extra config; **no Codex Router / LiteLLM URL is recorded in this repo.** `~/.claude.json` appears only as MCP client config in `runtime/README.md:178`, not as a provider endpoint — treat the local OpenAI-compatible address as **unknown**.

**Model id.** Anthropic: config/`--config` `model`, else `claude-opus-5` (`ah_anthropic.py:83, 198`). Desktop field empty means adapter default (`store.ts:670–675, 703–705`). Router: required non-empty `model` (`ah_router.py:163–165`). Mock: `mock-deterministic-1` (`ah_mock.py:46`).

**Timeouts.** Anthropic HTTP 120 s, one retry (`ah_anthropic.py:90, 98–103`); router 60 s; host `max_turns` default 8 (`ah_host.py:46`); desktop kill 20 min.

**Transcript / receipt of the agent turn.** (a) JSONL `…/agenthost/runs/{turnId}.jsonl` (`agenthost.rs:436–439`; returned `eventsPath` `agenthost.rs:549–556`). (b) Host stdout run payload: `events`, `plan`, `validation`, `approval`, `providerFault` (`ah_host.py:172–191`). (c) Desktop `Turn.payload` / `events` in store (`actions.ts:3466–3497`). Runtime **document** receipts (`receipt/read`) are separate; the host does not write them.

## 4. Gaps (blockers)

| Gap | One-line fix | Effort |
| --- | --- | --- |
| No live `api.anthropic.com` run; tests use a local fake; `--live-smoke` live leg owed (`ah_anthropic.py:45–48, 697–701`; `tests/test_agenthost_anthropic.py:6`) | Record one `--live-smoke` then one Composer turn with stored key; keep tests fake | S |
| Python `os_store` unimplemented (`ah_router.py:128–132`); desktop already env-injects | Leave the workaround, or implement OS lookup in the adapter | S / M |
| Host never calls `stream()` despite Anthropic `streaming: yes` | Wire `stream` into `AgentHost.run` or keep batched turns and stop promising live tokens | M |
| CLI default `--provider mock`; a real session must opt in | Explicit `--provider anthropic` / Settings radio; not a missing field | S |
| Router `baseUrl` empty blocks Composer (`store.ts:1236–1238`); no documented local gateway | Fill Settings 주소 or skip router | S |
| README “credential UI does not exist yet” (`agenthost/README.md:202–204`) is stale vs Settings | Correct README; not a run blocker | S |
| Non-Windows: credstore unavailable (`credstore.rs:183–186`) | CLI `ANTHROPIC_API_KEY` on this Windows PC | S |
| Host cannot open a document | Operator/desktop must `open` first | S |
| No live-router test (`ah_router.py:22–24`) | Irrelevant if using Anthropic first | S |

**Not a blocker:** compile gate is complete; Settings writes redacted configs; mock is hard-coded only as the **default**, not the only path.
