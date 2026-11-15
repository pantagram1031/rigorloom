# Rigorloom Architecture

Rigorloom fills in and edits Korean official documents in HWPX on your own machine. An agent or a person proposes an edit, a person approves it, and only then is the document changed. Two checks sit on top of every edit: `rigorloom guard` reports any number, date, quotation, negation or direction word that an edit changed, and `rigorloom style check` points at Korean phrasing worth a second look. This page says which code owns an edit and which paths do not go through it yet.

## Runtime Edit Transaction

`runtime/scripts/rt_core.py` (`RuntimeCore`) is the single authority for interactive document editing transactions. Every interactive edit passes through five stages: `propose` creates a plan bound to the active session source or base candidate hash, `validate` inspects document preflight constraints without modifying files, `request` opens a pending approval record, `resolve` accepts an explicit human approval or rejection decision binding plan ID and plan hash, and `apply` executes the validated engine steps once in isolation, checks protected expressions, writes an immutable candidate under `candidates/<runId>/`, and publishes `receipt.json` only after the candidate artifact is on disk. `RuntimeCore.plan_preview` runs the same execution steps inside a temporary directory without mutating session state, approvals, candidates, or apply attempts.

Report workflow state lives separately in each report workspace's `PIPELINE.md` (authoritative stage and gate state) and `APPROVALS.md` (human-gate ledger managed by `modules/report/scripts/pipeline_ctl.py`). Human gate approvals in `APPROVALS.md` are isolated from `RuntimeCore` approval records and cannot resolve or apply a runtime edit plan.

## Adapters and Authority Boundaries

All user-facing and model-facing front ends act strictly as adapters over `RuntimeCore` (or `pipeline_ctl.py` for report workflow gates) and never import or invoke raw edit workers directly:

- `runtime/scripts/cli.py` exposes host CLI subcommands, including `guard`, `style`, workspace inspection, session management, plan resolution, apply, and UI startup.
- `runtime/scripts/rt_server.py` serves the line-delimited JSONL stdio runtime protocol for host and agent connections.
- `runtime/scripts/mcp_server.py` exposes an agent-only MCP tool surface derived strictly from `AGENT_METHODS` minus `initialize`.
- `agenthost/` hosts model providers over an agent-authority runtime connection, checks every tool call against `ALLOWED_TOOLS` (`tool_forbidden` for every host-only method in slashed or underscored form), and keeps no local plan store.
- `runtime/scripts/rt_ui.py` and `desktop/` provide the local web and desktop UI over the sidecar runtime, delegating preview to `RuntimeCore.plan_preview` and report human-gate serialization in `APPROVALS.md` to `pipeline_ctl.py`.

## External Gaps Outside RuntimeCore

Three document-editing paths still operate outside `RuntimeCore`'s `propose`, `validate`, `request`, `resolve`, and `apply` transaction:

- Report HWPX assembly (`engine/scripts/fill_report.py` and `engine/scripts/build_report.py`) runs standalone report build steps rather than runtime plans.
- Structured story editing (`pipeline/scripts/story_edit.py`) writes standalone output files and story-edit receipts outside the runtime session store, and `rt_apply.read_receipt` refuses story-edit receipts.
- Post-edit cleanup (`engine/scripts/tidy_hwpx.py`) operates directly on HWPX packages as a standalone utility outside `RuntimeCore` candidate publication.
