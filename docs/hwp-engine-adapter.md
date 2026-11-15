# The optional HWP engine

Rigorloom edits `.hwpx` forms on its own. A separate HWP engine, installed on
its own and not part of this repository, can do more: read and convert `.hwp`
binaries, build documents from a blank form, lay out pages the way Hancom does,
and write PDFs with a text layer. Rigorloom can call it when it is there and
works the same as before when it is not.

This is the first step. Today the adapter can find the engine, call it and
report what it said. Routing runtime plans through the engine is a later piece
of work.

## Turning it on

Point `RIGORLOOM_HWP_ENGINE` at the directory that holds the engine's
`kit_api.py`, then check:

```sh
export RIGORLOOM_HWP_ENGINE=/path/to/engine
rigorloom engine          # exit 0 when the engine answers, 3 when it is absent
```

Rigorloom never imports the engine. Each call runs `kit_api.py` as a separate
process in your working directory, so relative paths mean what you meant, and
a crash in the engine comes back as a refusal.

## What you cannot do without it

When the engine is absent, every adapter call returns
`{"ok": false, "error": {"code": "capability_unavailable", "reason": ...}}`.
The reasons say what the built-in path cannot do:

| Engine function | Reason without the engine | What that means |
|---|---|---|
| `to_hwpx` | `hwp_binary_unsupported` | `.hwp` files cannot be converted, read or edited on Linux |
| `build` | `structural_build_unsupported` | no new paragraphs, tables or sections from a blank form |
| `edit` | `structural_edit_unsupported` | no inserting or restyling paragraphs, tables, equations, pictures |
| `pages` | `page_layout_unavailable` | Hancom-equivalent line and page breaks cannot be predicted |
| `pdf` | `text_pdf_unavailable` | no PDF with a text layer; the built-in renderer gives uncertified PNGs |
| `fill` | `engine_fill_unavailable` | filling stays within the built-in preedit operations |
| `analyze`, `features_used` | `engine_analysis_unavailable`, `feature_scan_unavailable` | the built-in form profile is used |
| `check_form`, `save`, `features` | `engine_form_check_unavailable`, `engine_save_unavailable`, `engine_features_unavailable` | the built-in rules and writer are used |

Other reasons come from a present engine: `engine_path_missing`,
`engine_timeout`, `engine_not_runnable`, `engine_contract_violation`,
`engine_result_too_large`, and `engine_refused`. For a refusal from the engine
only its error code is kept (`error.engine.code`). Engine messages and stderr
can quote file paths or document text, so they are printed to your terminal's
stderr and never put into a result that might be stored or shared.

## What never goes into this repository

The engine's source, its fonts, and any documents used to test it. The adapter
is the only part that lives here: `runtime/scripts/rt_kit.py` and
`tests/test_kit_adapter.py`.
