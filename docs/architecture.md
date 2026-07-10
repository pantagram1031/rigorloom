# Architecture

The project separates orchestration from document production.

1. **Kernel** — `pipeline_ctl.py`, `stages.yaml`, gates, events, and handoffs.
2. **Agent adapters** — optional provider commands mapped to capability roles.
3. **Document adapters** — HWP is supported through the separate `hwp-master`
   repository; other formats can implement the same inspect/assemble/measure/
   proof interface.
4. **Services** — Studio, scheduling, notifications, and external knowledge
   systems are optional. The kernel runs without them.

Workspace state lives in `PIPELINE.md`; machine handoff state lives in
`.pipeline/handoff.json`. The former is authoritative for stage and gate state.
The latter is regenerated after changes and is safe to discard and rebuild.
