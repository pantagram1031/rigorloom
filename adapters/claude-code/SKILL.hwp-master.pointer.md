---
name: hwp-master-pointer
description: "Pointer note: HWP/HWPX document stages of the report pipeline are handled by the separate hwp-master project, installed as its own skill. This file only records where it lives, what it needs, and which pipeline stages call it."
---

# HWP / HWPX document stages — use the separate hwp-master project

The report pipeline is document-backend-neutral. Native Hancom (HWP/HWPX)
document work is **not** bundled in this repository. It lives in the separate
public project:

- **github.com/pantagram1031/hwp-master**

Install it as its own skill and point the pipeline at it. Clone it beside the
Rigorloom checkout or set an environment variable:

```sh
git clone https://github.com/pantagram1031/hwp-master.git ../hwp-master
export HWP_MASTER_ROOT="$(cd ../hwp-master && pwd)"
```

Stage playbooks reference `<HWP_MASTER_ROOT>/scripts/...`. Any other document
backend may be substituted if it implements the v0.6 contract's inspect,
assemble, tidy, measure, and proof-render operations.

## Requirements (COM assembly path)

- **Windows** with the desktop **Hancom Office HWP** application installed
  locally. The pipeline does not bundle Hancom Office.
- The hwp-master project's `[windows]` and `[proof]` extras (COM automation +
  PDF proof-render).
- Verify the checkout before Stage 0:

  ```powershell
  python <HWP_MASTER_ROOT>/scripts/doctor.py --require-com --require-proof `
    --report-pipeline <CHECKOUT>
  ```

  If this check fails, do not enter the COM assembly path. Use only
  provider-neutral pipeline stages or supported non-COM HWPX/XML operations until
  a Windows HWP host is available.

## Which pipeline stages call it

- **Stage 0 — form intake.** Inspect the original form without modifying it and
  freeze anchors, page metrics, tables, placeholders, guide text, and break
  state:

  ```sh
  python <HWP_MASTER_ROOT>/scripts/form_inspect.py <form> \
    --out <WS>/form_profile.json --baseline <WS>/form_baseline.json
  ```

- **Stage 5 — assemble + proof.** Run the single assembly + proof loop against a
  copy of the form:

  ```sh
  python <HWP_MASTER_ROOT>/scripts/fill_report.py --loop \
    --form <WS>/output/form_copy.hwpx --content <WS>/bundle/content.md \
    --out-dir <WS>/output --build-yaml <WS>/build.yaml \
    --baseline <WS>/form_baseline.json --form-profile <WS>/form_profile.json \
    --proof --max-proof-iters 3
  ```

## Non-destructive form-copy rule

Always assemble into a **new** output file (`form_copy.hwpx`); never write into
the original submitted or template form. On damage, rebuild from the untouched
source and the bundle. Even one-off edits outside a workspace must save to a new
file, apply widow/orphan + keep-with-next defaults, export a PDF, run layout QA,
and inspect every page (new inline equations at high resolution) before delivery.
