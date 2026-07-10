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
