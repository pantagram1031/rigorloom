# Hancom acceptance — first live run (E3.2)

2026-09-04, Hancom Office closed at the start; `Hwp.exe` process-busy checked
clear before each of the three legs below (single COM session at a time, one
leg at a time). All three ran to completion via `engine/scripts/hwpx_accept.py`
(official pyhwpx Automation only). Each source was a real `hwpx_write`
round-trip of a corpus form (or `hwpx_write.blank_package()`) with a small
unique text marker inserted into the first `<hp:t>` of section 0 before the
harness ran — the harness itself never edits, it only verifies open/save/
close/reopen and checks the marker survived.

The harness always exits 3 (it never promotes); the verdict content below is
what decides pass/fail, not the exit code.

## Verdicts

| Source | open_no_repair | save_new_path | close | reopen | edit_preserved | structures_preserved | bindings_valid |
|---|---|---|---|---|---|---|---|
| `accept-gianmun-byeolji-1ho.json` (gianmun-byeolji-1ho.hwpx round-trip) | pass | pass | pass | pass | pass | pass (3 tbl, 67 p, unchanged) | pass |
| `accept-blank-package.json` (hwpx_write.blank_package()) | pass | pass | pass | pass | pass | pass (0 tbl, 1 p, unchanged) | pass |
| `accept-kstartup-jiwon.json` (kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwpx round-trip, largest form) | pass | pass | pass | pass | pass | pass (42 tbl, 798 p, unchanged) | pass |

All 21 checks (7 per run × 3 runs) passed. No repair/recovery dialog was
suspected on any open or reopen (window title never contained "복구"; the
form runs' title read "빈 문서 1 - 한글" — a generic Hancom automation title,
not a repair marker — the blank-package run's title showed the actual
filename instead, which is the one open-title discrepancy worth flagging for
a future run, not a failure by this harness's own criteria).

One structural note: the blank-package run's `qname_count_delta` shows Hancom
adding ~30 header/metadata elements on save (font tables, `opf:meta`,
`hh:typeInfo`, etc.) that the minimal writer omits — expected, since
`blank_package()` deliberately builds the smallest valid package, not a full
Hancom-equivalent header. Table/paragraph counts (the harness's pass/fail
policy) were unaffected.

## Not done here

- The writer was not modified. No failure occurred to record a finding for.
- `accept.json` `source`/`candidate` absolute paths were redacted to
  `<scratchpad>` before commit (`pipeline/scripts/privacy_scan.py` did not
  flag the original JSON-escaped `C:\\Users\\<name>\\...` paths — its
  `RE_USER_PATH` regex expects a single backslash and the JSON escaping
  doubles it, so the scan silently passed personal-path content; redacted by
  hand as a precaution, not because the scan caught it).
