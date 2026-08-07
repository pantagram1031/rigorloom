# Docs index

- [release-v0.16.0.md](release-v0.16.0.md) — the v0.16.0 release record:
  bundle inventory, suite matrix, privacy evidence, capability boundaries,
  operator-run leftovers.
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
- [extensions.md](extensions.md) — installing receipt-backed, data-only local
  knowledge packs and understanding their resolution precedence.
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

## `research/`

[research/](research/) holds point-in-time investigations that feed a
plan, not living documentation:

- [research/variant-audit.md](research/variant-audit.md) — the Phase 0.C
  variant-audit decision matrix: five differential benches over existing
  artifacts, the hybrid gate-architecture verdict, and the shared-miss
  mechanisms that motivated the new post-v0.15.0-alpha checkers (see
  `CHANGELOG.md`).
- [research/skill-efficiency-gen5.md](research/skill-efficiency-gen5.md) —
  authoring research for 5-gen models.
- [research/linux-hwp-edit.md](research/linux-hwp-edit.md) — Linux HWP/HWPX
  tooling research behind the v0.15 renderer-certification work.

## `plans/`

[plans/](plans/) holds the design history behind each release wave — one doc
per hardening or feature wave (for example
[plans/v0.11-Z5.md](plans/v0.11-Z5.md),
[plans/p0-parity-report.md](plans/p0-parity-report.md)). These are point-in-time
design and status records, not living documentation; for current behavior,
prefer the docs listed above and [CHANGELOG.md](../CHANGELOG.md).

The current wave is v0.16 — start with
[plans/v0.16-unified-core-and-modules.md](plans/v0.16-unified-core-and-modules.md)
(the master plan: engine absorption, personalization/style as separate
distribution modules) and its Phase 0 companion
[plans/v0.16-prep-variant-audit.md](plans/v0.16-prep-variant-audit.md).
