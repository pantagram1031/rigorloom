# Security Policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub Security Advisories](https://github.com/pantagram1031/rigorloom/security/advisories/new)
for this repository, rather than opening a public issue. This lets us confirm
and fix the problem before it's publicly disclosed.

Include, where possible: the affected file(s) or script, the version or
commit, a minimal reproduction, and what you expect to happen instead.

## What counts as security-relevant here

Rigorloom's gates (`content_audit`, `submission_preflight`, and their
sub-checkers) are relied on to fail closed. Because of that, a bug that lets
a gate **bypass or fail open** is treated as a security issue in this repo,
not just a correctness bug — even without any traditional exploit chain.
Examples that qualify:

- A checker (`verify_content.py`, `check_style.py`, `check_numbers.py`,
  `check_refs.py`, `check_figdata.py`, `check_sources.py`, `check_units.py`,
  `check_saeteuk.py`) exiting 0 (or otherwise reporting no finding) on input
  it is supposed to catch.
- `content_audit.py` or `submission_preflight.py` failing to propagate a
  sub-checker's HARD verdict into the overall exit code.
- A form-hash, structure-hash, or provenance check that can be satisfied by a
  mutated or fabricated artifact.
- A path where a script gate is silently treated as passed without actually
  invoking its bound checker (the class of bug the v0.7 hardening wave
  closed — see [CHANGELOG.md](CHANGELOG.md)).
- Path traversal, zip-slip, or symlink issues in workspace archival/restore
  code (`ws_snapshot.py` and similar).

Also in scope: leakage of personal data, credentials, or private form
content through logs, generated artifacts, or the Studio.

## What's out of scope

- Fidelity gaps that are already documented as known limitations (for
  example, LibreOffice/H2Orestart equation rendering, or the
  `experimental-rhwp` render path — see the "Project status" section of
  [README.md](README.md) and [docs/plans/p0-parity-report.md](docs/plans/p0-parity-report.md)).
- Issues in the separate [hwp-master](https://github.com/pantagram1031/hwp-master)
  project — report those in that repository.

## Response

This is a small, actively developed open-source project without a dedicated
security team or SLA. We aim to acknowledge reports promptly and will credit
reporters in the fix's changelog entry unless you ask us not to.
