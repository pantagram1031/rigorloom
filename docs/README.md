# Docs index

## Operating the pipeline

- [golden-path.md](golden-path.md) — full clone-to-graded-artifact
  walkthrough using the Hancom-free `hwpx` backend.
- [pipeline-master-v0.6.md](pipeline-master-v0.6.md) — the stage graph and
  gate contract; read this before operating a workspace.
- [autonomous-orchestration.md](autonomous-orchestration.md) — running the
  pipeline unattended.
- [migration.md](migration.md) — upgrading a workspace across pipeline
  versions.
- [troubleshooting.md](troubleshooting.md) and
  [trouble-table.md](trouble-table.md) — indexed troubleshooting entries.

## Architecture and design

- [architecture.md](architecture.md) — system architecture.
- [support-matrix.md](support-matrix.md) — per-capability status with
  evidence pointers (generated; do not edit by hand).
- [capability-matrix.md](capability-matrix.md) — module-chain aliases
  and OS ceilings (generated).
- [design-decisions.md](design-decisions.md) — rationale for key
  architectural choices.
- [gate-calibration.md](gate-calibration.md) — gate threshold reasoning.

## Authoring and style

- [report-method.md](report-method.md) — the report-writing method the
  pipeline drives.
- [humanization.md](humanization.md) — the Stage 4 humanization contract.
- [style-rules.md](style-rules.md) — prose and figure style rules enforced
  by the content-audit checkers.

## Extension and installation

- [extensions.md](extensions.md) — receipt-backed, data-only local
  knowledge packs and their resolution precedence.
- [skills-install.md](skills-install.md) — installing this pipeline as a
  Claude-style skill directory via `sync_local`.
- [archive-policy.md](archive-policy.md) — what gets archived vs. kept
  canonical, and when.

## Releases

- [release-v0.17.0.md](release-v0.17.0.md) — v0.17.0 evidence record:
  bundle hashes, validation ledger, honest limits.
- [release-v0.16.0.md](release-v0.16.0.md) — v0.16.0 release record:
  bundle inventory, suite matrix, capability boundaries.
- [lessons-learned.md](lessons-learned.md) — operational knowledge
  distilled from previous runs.

## Research

[research/](research/) holds point-in-time investigations that feed
plans, not living documentation:

- [research/variant-audit.md](research/variant-audit.md) — the Phase 0.C
  variant-audit decision matrix and hybrid gate-architecture verdict.
- [research/skill-efficiency-gen5.md](research/skill-efficiency-gen5.md) —
  authoring research for 5-gen models.
- [research/linux-hwp-edit.md](research/linux-hwp-edit.md) — Linux
  HWP/HWPX tooling research behind the v0.15 renderer-certification work.
- [research/xc1-conversion-bench.md](research/xc1-conversion-bench.md) —
  HWP→HWPX conversion bench (10/10 on official corpus).

## Plans

[plans/](plans/) holds the design history behind each release wave — one
doc per hardening or feature wave. These are point-in-time design records,
not living documentation; for current behavior, prefer the operating docs
above and [CHANGELOG.md](../CHANGELOG.md).
