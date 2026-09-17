# Stage 6 — Real agent loop (desktop 에이전트 tab + Agent Host + a real provider)

Status: ACTIVE 2026-09-17. Owner: Fable. Input: docs/plans/analyses/stage6-agenthost-providers.md (A2).
Rule: keys never in files. The Agent Host never approves, applies or opens documents.

## Provider choice
The Agent Host has `mock`, `router` (OpenAI-compatible) and `anthropic` providers. On this PC the keyless
loopback bridge to Cursor models (cursor-api-proxy) is the credential-free option: it reuses the Cursor CLI login,
so the `router` provider needs only `baseUrl` + `model`. The persistent instance on 127.0.0.1:8765 is broken since
the 2026-09-15 cursor-agent update (Node 22 refuses to spawn a `.cmd` shim; the new shim delegates to PowerShell).
A temporary instance on 127.0.0.1:8766 started with `CURSOR_AGENT_NODE` / `CURSOR_AGENT_SCRIPT` pointing at
`versions/2026.09.15-d2fe57e/node.exe` + `index.js` works (models listed; see ledger). The user decides whether to
fix the autostart script the same way. Anthropic direct stays possible once the user enters a key in Settings.

## Slices
- [ ] G6a CLI session: `agenthost` with `--provider router` against 127.0.0.1:8766 on the 소논문 form: instruction →
      plan → request-approval → approve (human, CLI) → apply → receipt; transcript kept under the run dir.
- [ ] G6b Desktop session: Settings → 제공자 router (주소 + 모델, no credential) → Composer instruction → plan-arrival
      card → 검토 hunks → 승인 → 적용 → 영수증, on the 소논문 form; screenshot pass.
- [ ] G6c Same on the AURALAB report with a bound form profile; one honest refusal recorded if the provider
      proposes an op outside the first wave.
- [ ] G6d Protocol gaps fixed at the cause (from A2: `stream()` unused, `os_store` unimplemented, README stale).

## Ledger
| When | What | Result |
|---|---|---|
