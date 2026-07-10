# Optional Pantadex humanization adapter

Pantadex may fill the `humanizer-chain` role when its MCP is already configured.
It is optional; the repository contains no endpoint, credential, private style
corpus, or server implementation.

Map available Pantadex operations to the portable contract:

1. health/scorer check, if exposed;
2. AI-tell scoring as advisory evidence;
3. light, targeted humanization of failing paragraphs only;
4. optional style polish;
5. optional service fidelity audit;
6. mandatory local `humanization_ctl.py apply`, regardless of service result.

Older deployments may expose `score_ai_tells`, `humanize_full`,
`humanize_scorer_health`, `polish_report_style`, or `fidelity_audit` directly;
newer deployments may expose them through a shell or job tool. Tool discovery
must happen at runtime. Never hard-code a private server address.

For formal reports, use the lightest correction mode. If the service lacks a
report genre, use its closest formal prose mode but treat register-related scores
as advisory. Local profile rules and the deterministic fidelity gate always win.

When Pantadex is unavailable, invoke any high-reasoning writer using the same
prompts and JSON schema. No pipeline state or artifact contract changes.
