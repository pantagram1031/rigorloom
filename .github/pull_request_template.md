## Summary

<!-- What does this PR change, and why? -->

## Checklist

- [ ] Tests added for every fix or new behavior (positive and, for
      gates/checkers, negative cases)
- [ ] Full suite green: `python -m pytest pipeline/tests tests -q`
- [ ] Privacy scan clean: `python pipeline/scripts/privacy_scan.py .` reports
      0 HARD findings
- [ ] Docs updated (`docs/`, `CHANGELOG.md`) if behavior, a gate contract, or
      a CLI flag changed
- [ ] No personal data, credentials, private forms, or generated reports
      included in this PR
