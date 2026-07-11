# Optional Pantadex humanization adapter

Pantadex may fill the `humanizer-rewriter` role or act as an independent
comparison judge when its MCP is already configured. Local workers remain the
default. The repository contains no endpoint, credential, private style corpus,
or server implementation.

Map available Pantadex operations to the portable contract:

1. health/scorer check, if exposed;
2. AI-tell scoring as advisory evidence, never a paragraph selector;
3. PASS returns the original unchanged; REWORK inspects all prose paragraphs;
4. light paragraph-level humanization with actual changes returned as v2 JSON;
5. optional style polish, fidelity audit, and naturalness review as independent
   evidence;
6. mandatory local `humanization_ctl.py apply`, regardless of service result.

Older deployments may expose `score_ai_tells`, `humanize_full`,
`humanize_scorer_health`, `polish_report_style`, or `fidelity_audit` directly;
some also expose `naturalness_review` or `strict_humanize`. These operations are
independent: a full rewrite does not imply that fidelity or naturalness review
already ran. The Rigorloom orchestrator remains responsible for role separation
and local apply. Newer deployments may expose the tools through a shell or job
tool. Discovery must happen at runtime. Never hard-code a private server address.

For formal reports, use the lightest correction mode. Register-related scores
are especially prone to false positives and remain advisory. Do not rewrite
normal formal nominalization or ending consistency solely to reduce a score.
Local profile rules and the deterministic fidelity gate always win.

The preferred path invokes a local high-reasoning rewriter using the same prompts
and JSON schema. Pantadex availability never changes pipeline state or artifact
contracts.
