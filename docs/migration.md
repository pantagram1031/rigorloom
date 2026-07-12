# Public repository migration

This repository was created as a clean, standalone distribution rather than by
publishing an existing personal working tree and its history.

Included:

- the v0.6 state machine and tests;
- current contracts and stage playbooks;
- the read-only Studio;
- generic style/layout examples;
- automatic handoff and archive behavior;
- legacy public contracts under `archive/`.

Excluded:

- report workspaces and generated documents;
- student or operator identity data;
- private templates and reference submissions;
- screenshots, run logs, scratch probes, and local launch configuration;
- credentials, account health, provider quotas, and personal model preferences;
- private writing corpora and voice profiles.

The original working directories remain untouched. This public repository is
safe to clone independently and depends on `hwp-master` only when HWP/HWPX
document assembly is required.

## Second wave (v0.7 convergence)

A later convergence made this public repository the single source of truth for the
kernel and the engineering knowledge, while all personal material stays in a private
overlay.

Came upstream (generalized):

- kernel gate integrity — the lean-core enforcement (a `check` subcommand that runs
  the registered checker itself, retirement of the caller-supplied gate exit,
  script gates that block in every run mode, and the new Stage 4.5 content_audit);
- deterministic checkers — the content verifier, the backend precheck, and the
  pack-driven style/format checkers;
- preference packs — the schema, the resolution engine, and neutral defaults, so
  operator taste becomes versioned data rather than hardcoded rules;
- knowledge docs — the generalized autonomous-orchestration playbook, the T1–T14
  trouble table, the night-run lessons, and the redacted v0.7 hardening plan.

Stayed private (a local overlay, never in the repo):

- resolved preference-pack instances (prose, figure, structure, and summary taste);
- school forms, templates, report workspaces, and reference submissions;
- the direction/persona context and curriculum material;
- author and operator identity, run logs, wiki, and provider account details.

The sync model is one-way: kernel, engine, and schema changes happen in this
repository first and are then exported to the local skills copy by a scripted,
allowlisted, hash-verified sync. The skills copy is generated, never the editing
surface; the sync refuses to run when it detects local edits, which forces every
change upstream. Taste changes edit the private packs (and mirror the human-readable
rule document); new trial-and-error knowledge is captured locally and promoted to
the public trouble table once it generalizes.
