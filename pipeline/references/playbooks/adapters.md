# Backend adapters

The pipeline selects workers by capability, not vendor. The state machine does
not call a model directly; the orchestrator maps each role in `agents.yaml` to
an available local agent, CLI, API, or human.

## Required adapter behavior

Every adapter must:

1. accept a bounded task with explicit inputs and expected outputs;
2. avoid including credentials or private corpus material in prompts;
3. return a concise result or a declared artifact path;
4. report non-zero exits, timeouts, and schema failures through
   `pipeline_ctl.py trouble`;
5. never approve human gates;
6. never edit script-generated verdicts.

## Capability mapping

| Role | Minimum capability | Suggested independence |
|---|---|---|
| writer/designer | high reasoning, long-form writing | one primary |
| researcher | browsing or supplied-source analysis | up to three parallel |
| simulation worker | code execution, deterministic checks | one primary |
| mechanical worker | filesystem and command execution | one primary |
| vision judge | image/PDF inspection | independent from writer |
| logic reviewer | critical reasoning | independent from writer |
| numeric reviewer | quantitative verification | two independent passes |
| prose-pattern reviewer | observable style review | independent from rewriter |
| humanizer rewriter | bounded Korean prose editing | local worker by default |
| fidelity/naturalness reviewer | semantic preservation and over-polish | independent from rewriter |
| human gate | operator authority | human only |

## Provider examples

- Interactive agents such as independent reviewer, interactive agent, alternate agent CLI, or local IDE
  agents may orchestrate directly.
- Headless CLIs or APIs may be used as bounded workers.
- Local models are valid when they satisfy the role and output contract.
- A single interactive agent may perform multiple roles sequentially when
  parallel workers are unavailable, but it must record that reduced
  independence in `events.jsonl` or `TROUBLES.md`.
- For Stage 4, prefer spawned local workers for reviewer, rewriter, and judge.
  Do not let one worker both rewrite and approve its own proposal. Pantadex is
  an optional adapter, not an availability requirement.

Backend availability is environment-specific. Do not commit account status,
tokens, benchmark logs, or personal model preferences to the repository.
