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

Eleven tools, derived from the agent registry: `capabilities_list`,
`session_list`, `document_inspect`, `document_readRegion`, `plan_propose`,
`plan_validate`, `plan_get`, `approval_request`, `approval_get`,
`candidate_list`, `receipt_read`.

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

## Known gaps

- Children are bounded (time, output, environment allowlist) but not
  contained: no process group, no Windows Job.
  `pipeline/scripts/diagnostic_candidate_core.py:1128` does that properly.
- Records under `--root` are last-writer-wins; nothing serialises two hosts
  driving one root.
- The MCP adapter implements the five methods above and no resources, prompts,
  sampling, completion or logging capabilities.
