# runtime/ — Runtime Protocol v0 (Phase 1 slice)

JSONL-over-stdio server that adapts the existing engine and pipeline
entrypoints. Design: `docs/runtime-protocol-v0.md` (protocol) and
`docs/desktop-architecture.md` (processes and trust boundaries).

```sh
python runtime/scripts/serve.py --entry host  --root <dir>
python runtime/scripts/serve.py --entry agent --root <dir>
```

## What this slice does

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
| `scripts/rt_server.py` | the two method registries and the dispatch loop |
| `scripts/serve.py` | CLI entrypoint |

Stdlib only. Scripts are invoked by path and import their siblings through
`sys.path`, the same idiom as `engine/scripts` and `pipeline/scripts`.

Tests live in `tests/` (`tests/test_runtime_*.py`, helper
`tests/_runtime_client.py`), not here: `pyproject.toml`'s `testpaths` does not
include `runtime/tests`, and this slice does not own `pyproject.toml`.

## Two rules worth restating

**Authority is the registry.** The agent entrypoint does not build the
host-only methods. `plan/apply` on an agent connection is `unknown_method`
because it is absent, not because a check refused it. No field in any frame
can change that.

**The source is never touched.** `workspace/openPath` validates, copies into
the session, and records the SHA-256. Every op reads one file and writes
another. `tests/test_runtime_session.py` pins byte identity of the original
across a full apply.

## Known gaps

- Child processes are bounded (time, output, environment allowlist) but not
  contained: no process group, no Windows Job. `pipeline/scripts/diagnostic_candidate_core.py:1128`
  does that properly; wiring onto it is Phase 2.
- `scripts/py_compile_sweep.py` does not cover `runtime/scripts/*.py` — its
  `PATTERNS` needs one line, and that file is not owned by this slice.
  `tests/test_runtime_transport.py` byte-compiles the tree in the meantime.
- Records under `--root` are last-writer-wins across processes; nothing
  serialises two hosts driving one root.
