# Docs index

## Start here

- [product-direction.md](product-direction.md) — the proposed living product
  direction: Rigorloom as a local-first, verifiable HWP/HWPX desktop
  workbench, with its initial product wedge, trust model, roadmap, and
  non-goals. It does not add or imply current capability.
- [plans/agent-native-desktop-goal.md](plans/agent-native-desktop-goal.md) —
  the durable Claude Goal specification for the agent-native Desktop program:
  Fable 5 orchestration, Opus 5 workstreams, architecture invariants, phases,
  acceptance tasks, security boundaries, verification, and Git policy. This is
  a target and execution contract, not a current-capability claim.
- [support-matrix.md](support-matrix.md) — current per-capability status and
  executable evidence pointers; use this instead of inferring support from a
  roadmap or plan.
- [release-v0.17.0.md](release-v0.17.0.md) — the v0.17.0 validation record:
  bundle inventory, suite matrix, clean-room campaigns, privacy evidence, and
  known limits.
- [release-v0.16.0.md](release-v0.16.0.md) — the preceding unified-core and
  distribution-module release record.
- [architecture.md](architecture.md) — current runtime architecture. The
  proposed Desktop/Application Service boundary is defined separately in
  [product-direction.md](product-direction.md).

## Operate the current product

- [golden-path.md](golden-path.md) — full clone-to-graded-artifact
  walkthrough, stage by stage, using the Hancom-free `hwpx` backend.
- [pipeline-master-v0.6.md](pipeline-master-v0.6.md) — the report stage graph
  and gate contract; read this before operating a report workspace.
- [autonomous-orchestration.md](autonomous-orchestration.md) — running the
  report pipeline unattended.
- [humanization.md](humanization.md) — the Stage 4 humanization contract.
- [report-method.md](report-method.md) — the report-writing method the report
  pipeline drives.
- [style-rules.md](style-rules.md) — prose and figure style rules enforced by
  the content-audit checkers.
- [migration.md](migration.md) — upgrading a workspace across pipeline
  versions.
- [extensions.md](extensions.md) — installing receipt-backed, data-only local
  knowledge packs and understanding their resolution precedence.
- [skills-install.md](skills-install.md) — installing Rigorloom as a
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

[research/](research/) holds point-in-time investigations that feed a plan,
not living documentation:

- [research/variant-audit.md](research/variant-audit.md) — the Phase 0.C
  variant-audit decision matrix: five differential benches over existing
  artifacts, the hybrid gate-architecture verdict, and the shared-miss
  mechanisms that motivated the post-v0.15.0-alpha checkers.
- [research/skill-efficiency-gen5.md](research/skill-efficiency-gen5.md) —
  authoring research for 5-gen models.
- [research/linux-hwp-edit.md](research/linux-hwp-edit.md) — Linux HWP/HWPX
  tooling research behind the v0.15 renderer-certification work.

## `plans/`

[plans/](plans/) holds the design history behind each release wave and durable
program contracts. Historical examples include
[plans/v0.11-Z5.md](plans/v0.11-Z5.md),
[plans/p0-parity-report.md](plans/p0-parity-report.md), and
[plans/v0.16-unified-core-and-modules.md](plans/v0.16-unified-core-and-modules.md).

For current behavior, prefer [support-matrix.md](support-matrix.md), the release
records, and [CHANGELOG.md](../CHANGELOG.md). For the proposed product boundary,
use [product-direction.md](product-direction.md). For the long-running Claude
Goal execution contract, use
[plans/agent-native-desktop-goal.md](plans/agent-native-desktop-goal.md).
