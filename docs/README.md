# Docs index

## Start here

- [product-direction.md](product-direction.md) — the living product direction:
  Rigorloom as an agent-native, local-first HWP/HWPX desktop editor and
  automation runtime with verifiable operations. Covers the initial product
  wedge, the one-Workspace/two-views product shape, the eight product surfaces
  and the host-vs-agent authority model, the shared `OperationPlan` invariant,
  the trust model, the Phase 0–6 roadmap, and the non-goals. Explanatory, not
  normative; it does not add or imply current capability.
- [plans/agent-native-desktop-program.md](plans/agent-native-desktop-program.md)
  — the living program document: current phase and status, the phase ladder
  with entry/exit criteria, the PR dependency graph, the repository truth audit
  (release, tag, and repository-description mismatches as observed), the open
  Phase 0 decisions, standing constraints, and open risks. Read this to know
  where the program stands.
- [plans/agent-native-desktop-goal.md](plans/agent-native-desktop-goal.md) —
  the durable Claude Goal specification for the agent-native Desktop program:
  Fable 5 orchestration, Opus 5 workstreams, architecture invariants, phases,
  acceptance tasks, security boundaries, verification, and Git policy. This is
  the normative target and execution contract, not a current-capability claim.
  Where it and product-direction.md disagree, this document wins.
- [support-matrix.md](support-matrix.md) — current per-capability status and
  executable evidence pointers; use this instead of inferring support from a
  roadmap or plan.
- [release-v0.17.0.md](release-v0.17.0.md) — the v0.17.0 validation record:
  bundle inventory, suite matrix, clean-room campaigns, privacy evidence, and
  known limits. Note: the `v0.17.0` tag exists but no v0.17.0 GitHub Release
  has been published — see the repository truth audit in
  [plans/agent-native-desktop-program.md](plans/agent-native-desktop-program.md) §5.
- [release-v0.16.0.md](release-v0.16.0.md) — the preceding unified-core and
  distribution-module release record.
- [architecture.md](architecture.md) — the current pipeline/kernel
  architecture. The proposed Desktop/Runtime boundary (formerly called
  "Application Service") is defined separately in
  [product-direction.md](product-direction.md) §5.

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
records, and [CHANGELOG.md](../CHANGELOG.md). For the product boundary, use
[product-direction.md](product-direction.md). For program status, phase gates,
and the PR graph, use
[plans/agent-native-desktop-program.md](plans/agent-native-desktop-program.md).
For the normative long-running Claude Goal execution contract, use
[plans/agent-native-desktop-goal.md](plans/agent-native-desktop-goal.md).
