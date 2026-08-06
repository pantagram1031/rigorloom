# Sanitized PoC samples

These files are non-personal fixtures derived from the repository operator's
generic science-report form, then populated with synthetic Studio text through
the existing `hwp-master` XML engine. `sample_factory.py sanitize` replaces the
creator, last-save user, dates, title, and preview text before checking that the
source metadata values are absent from every text-bearing archive member.

- `sanitized-editable.hwpx` is equation-free so the repo-discovered WSL
  LibreOffice/H2Orestart renderer can exercise the edit-to-preview loop.
- `sanitized-equation-hazard.hwpx` adds one HwpEqn control. The editor inspects
  and locks that paragraph. It is deliberately not sent through LibreOffice,
  because the current filter returns `Unspecified Application Error` for this
  fixture.

The fixtures contain no report workspace, student submission, or personal
style-profile content.
