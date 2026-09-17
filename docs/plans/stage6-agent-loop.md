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
- [x] G6a CLI session (2026-09-17 23:53, cursor-grok-4.6-high-fast lane, 121 min incl. eleven host runs; see ledger row): `agenthost` with `--provider router` against 127.0.0.1:8766 on the 소논문 form: instruction →
      plan → request-approval → approve (human, CLI) → apply → receipt; transcript kept under the run dir.
- [ ] G6b Desktop session: Settings → 제공자 router (주소 + 모델, no credential) → Composer instruction → plan-arrival
      card → 검토 hunks → 승인 → 적용 → 영수증, on the 소논문 form; screenshot pass.
- [ ] G6c Same on the AURALAB report with a bound form profile; one honest refusal recorded if the provider
      proposes an op outside the first wave.
- [ ] G6d Protocol gaps fixed at the cause (from A2: `stream()` unused, `os_store` unimplemented, README stale).

## Ledger
| When | What | Result |
|---|---|---|
| 2026-09-17 | G6a CLI `--provider router` `cursor-grok-4.6-high-fast` @ `http://127.0.0.1:8766/v1` (keyless, `credential.source=none`, `toolsInBody: false`) | wall **215.61s**; bridge usage **11387** total (11052 prompt / 335 completion, 6 turns). Plan `341cebc4d8e04f28bfd53137b7897460` hash `a913328f08fe2c886d6dc68814b49500f2ba5dd5c2654eb6cd34b453240f9ea8` opsHash `95a87559e8f136a41ed263155839d92b6d28c2b482c3a0c14735b3bff28965f5` backend **xml** ops: `replace_all` 논문제목→Agent 스모크, `goto_text` `I.  서론`, `insert_text` 이 문장은 에이전트가 제안했다. Validation **pass**. Host `approval/request` `aecbd7e9e1e84ab4a8f5d2875ef7d6b9` pending → CLI approve (plan hash) → apply rc 0 → receipt run **`651284489c8e4bcd8d95272b0ed9e113`** `backend: xml` `evidence.class: structural_only` (wellFormed). Candidate `artifact.hwpx` 48865 B sha256 `546661e66ee9ba00fb94c82ef45a2c2a261885f05a153457f5de9771a7f90b81`; unzip `Contents/section0.xml` has `Agent 스모크`×2 and `이 문장은 에이전트가 제안했다.`×1 (`논문제목` 0). Residue checker honestly `acceptance: false` (partial form fill). Transcript `C:\Users\user\AppData\Local\Temp\g6a-host\events-run11.jsonl` (stdout `stdout-run11.json`). First-wave-wrong propose recorded on run10 (`operations`/`replace`/`insert`, unknown_field). Adapter fixes: keyless `credential` `not_required`; OpenAI history `tool_call_id`; recover JSON-as-text tool calls; omit `tools` array (this bridge 500s/`cursor_cli_error` with tools); stream done carries usage; prompt-mode slims inspect history. |
| 2026-09-17 | Bridge limits learned in G6a | the Cursor bridge passes prompts on the Windows command line (a 16.9k-char prompt was truncated to 14.4k), returns HTTP 500 on an OpenAI `tools` array, and hangs on `tool_choice`; the router adapter therefore gained a prompt-mode (`toolsInBody: false`) with JSON-as-text tool-call recovery, `credential.source: none` → `not_required`, and usage on `provider.response`. Anthropic direct has none of these limits; recorded for the desktop session (G6b) |
