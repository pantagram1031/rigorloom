# Docs index

- [golden-path.md](golden-path.md) — full clone-to-graded-artifact
  walkthrough, stage by stage, using the Hancom-free `hwpx` backend.
- [pipeline-master-v0.6.md](pipeline-master-v0.6.md) — the stage graph and
  gate contract; read this before operating a workspace.
- [architecture.md](architecture.md) — system architecture.
- [autonomous-orchestration.md](autonomous-orchestration.md) — running the
  pipeline unattended.
- [humanization.md](humanization.md) — the Stage 4 humanization contract.
- [report-method.md](report-method.md) — the report-writing method the
  pipeline drives.
- [style-rules.md](style-rules.md) — prose and figure style rules enforced
  by the content-audit checkers.
- [migration.md](migration.md) — upgrading a workspace across pipeline
  versions.
- [skills-install.md](skills-install.md) — installing this pipeline as a
  Claude-style skill directory via `sync_local`.
- [archive-policy.md](archive-policy.md) — what gets archived vs. kept
  canonical, and when.
- [lessons-learned.md](lessons-learned.md),
  [design-decisions.md](design-decisions.md), and
  [troubleshooting.md](troubleshooting.md) — operational knowledge distilled
  from previous runs; generalized patterns only, no personal reports or
  private templates.
- [trouble-table.md](trouble-table.md) — indexed troubleshooting entries.

## `plans/`

[plans/](plans/) holds the design history behind each release wave — one doc
per hardening or feature wave (for example
[plans/v0.11-Z5.md](plans/v0.11-Z5.md),
[plans/p0-parity-report.md](plans/p0-parity-report.md)). These are point-in-time
design and status records, not living documentation; for current behavior,
prefer the docs listed above and [CHANGELOG.md](../CHANGELOG.md).
