# guard example

`before.hwpx` is the blank 표준근로계약서 (Ministry of Employment and Labor,
2013) from `tests/corpus/forms/converted/`. Its provenance and licence note are
in `tests/corpus/forms/manifest.json`. `after.hwpx` is the same file with three
edits:

| paragraph | edit | verdict |
|---|---|---|
| 2 | 체결한다 → 맺는다 | kept: nothing protected changed |
| 4 | 1. 근로계약기간 → 2. 근로계약기간 | revert: a number changed |
| 5 | 정하지 않는 → 정한 | revert: a negation was dropped |

```sh
cd examples/guard
rigorloom guard before.hwpx after.hwpx > verdict.json   # exit 3
```

`verdict.json` is committed. `tests/test_guard.py` runs the same command and
checks that the output is byte-for-byte the committed file, so this example
can't drift from the code.
