# Golden path: clone to a graded artifact, without Hancom

This walks one report workspace from a fresh clone through the whole stage
graph to a Stage 6 `submission_preflight` verdict, using the Hancom-free
`hwpx` document backend. Every command below is a real script in this repo,
verified against its own `--help` output and source while writing this doc.
Paths use `<WS>` for the absolute workspace path and `<REPO_ROOT>` for this
checkout's root; run everything with `<REPO_ROOT>` as the working directory.

Two things this doc is honest about up front:

- **Content generation is out of scope here.** Stages 1–4 (research, design,
  sim, write) produce the evidence and prose that later gates check. This doc
  shows the mechanical stage-machine commands to move through them, not how
  to write a report — that is what the stage playbooks under
  `pipeline/references/playbooks/` and the `report-pipeline` skill are for.
- **Only `hwpx` and `hwp` backends can reach a graded verdict.** The `bundle`
  and `docx` backends never produce `output/out.hwpx`, so they cannot pass
  the Stage 5.3 `format_check` gate or reach Stage 6 (see the backend table
  in [README.md](../README.md)). If you just want to see the pipeline run
  anywhere with zero dependencies, stop after step 4A below.

## 0. Prerequisites

- Python 3.10+, standard library only, for everything except the `hwpx`/`hwp`
  backends.
- For the Hancom-free `hwpx` path: a checkout of the separate
  [hwp-master](https://github.com/pantagram1031/hwp-master) project, which
  supplies `fill_report.py`, `eqn.py`, `xml_backend.py`, and `form_inspect.py`.
  None of these require Hancom or Windows for the XML engine path.
- For the full `hwp` path (native Hancom proof): Windows + a licensed Hancom
  Office HWP install, plus hwp-master's optional `[windows]`/`[proof]` extras.
  This doc calls out each place that path diverges.

## 1. Clone and bootstrap

```sh
git clone https://github.com/pantagram1031/rigorloom.git
cd rigorloom
python3 scripts/bootstrap.py
```

`scripts/bootstrap.py` verifies the interpreter, creates a private
personalization profile under the Git-ignored `.local/`, registers the
default preference packs, and runs an end-to-end smoke test (`new_report` →
`resume` → a passing script gate) against a synthetic form fixture. It is
idempotent. This step alone proves the kernel is wired correctly; it does not
produce a real document.

Optionally, for the Hancom-free path, clone hwp-master beside this repo and
point at its `scripts/` directory:

```sh
git clone https://github.com/pantagram1031/hwp-master.git ../hwp-master
export HWP_MASTER_SCRIPTS="$(cd ../hwp-master/scripts && pwd)"
export HWP_MASTER_ROOT="$(cd ../hwp-master && pwd)"
```

`HWP_MASTER_SCRIPTS` is what `doc_backend.py --backend hwpx` reads; the
dispatcher checks that `fill_report.py`, `eqn.py`, and `xml_backend.py` all
exist under it before invoking anything (`pipeline/scripts/doc_backend.py`).

## 2. Create an example workspace

```sh
python scripts/new_report.py --slug demo --subject math \
  --topic "A testable question" --form /absolute/path/to/form.hwpx \
  --mode night
```

`--form` must point at an existing file (`new_report.py` checks `is_file()`
only at creation time; later stages validate its actual HWPX structure). If
you don't have a real submission form handy, you can create a placeholder to
exercise the CLI wiring the same way `bootstrap.py`'s smoke test does — but
note this will not pass the content/format gates below, which expect a real
form and real content:

```sh
python3 -c "open('/tmp/placeholder-form.hwpx','wb').write(b'placeholder')"
```

`--mode night` lets `pipeline_ctl.py gate` auto-approve human gates for this
walkthrough; script gates are never auto-approved — they always run their
bound checker. This prints the workspace path and the next command:

```sh
python pipeline/scripts/pipeline_ctl.py resume ./workspaces/report-demo
```

## 3. Walk the stage graph

`pipeline_ctl.py resume <WS>` always tells you the next stage. The gate kinds
are declared in `pipeline/references/stages.yaml`:

| Stage | Name | Gate kind | Resolve with |
|---|---|---|---|
| 0 | form_intake | none | `pipeline_ctl.py advance <WS> 0 --status done` (after `form_inspect.py`, hwp-master) |
| 1 | research | none | `pipeline_ctl.py advance <WS> 1 --status done` |
| 2 | design | human | `pipeline_ctl.py gate <WS> design --mode night` |
| 2.5 | layout_plan | script (external checker) | registered per-workspace; see `playbooks/stage-2.5.md` |
| 3 | sim | script (`{WS}/sim/gates.py`) | `pipeline_ctl.py check <WS> sane` |
| 4 | write | human | `pipeline_ctl.py gate <WS> draft --mode night` |
| 4.5 | content_audit | script | `pipeline_ctl.py check <WS> content_audit` |
| 5 | assemble | none (backend-conditional) | `pipeline/scripts/doc_backend.py <WS> --backend hwpx` |
| 5.3 | format_check | script | `pipeline_ctl.py check <WS> format_check` |
| 5.5 | understand | script | `pipeline_ctl.py check <WS> understand` |
| 5.7 | final_panel | script | `pipeline_ctl.py check <WS> final_panel` |
| 6 | return | script | `pipeline_ctl.py check <WS> submission_preflight` |

Human gates (`gate` subcommand) auto-approve in `night`/`autonomous` mode;
script gates (`check` subcommand) always run their bound checker and never
auto-approve, regardless of mode — this is the fail-closed fix from the
v0.7 hardening wave. After each resolved gate, advance the stage:

```sh
python pipeline/scripts/pipeline_ctl.py advance <WS> <stage> --status done
```

Stage 4.5's `content_audit.py` runs seven sub-checkers against
`bundle/content.md` and the figures directory (see README.md's "Content audit
and submission gates" section for the full list); write real, gate-passing
content there before continuing — this is the one step in the walkthrough
that cannot be faked with a placeholder.

## 4A. Assemble without Hancom (bundle — any machine, advisory only)

To prove the pipeline runs anywhere with zero dependencies:

```sh
python pipeline/scripts/doc_backend.py <WS> --backend bundle
```

This always succeeds if `bundle/content.md` exists, and writes
`output/deliverable/` (content, figures, `preview.html`, `manifest.json`).
It never writes `output/out.hwpx`, so Stage 5.3 `format_check` will fail HARD
with `output_missing` if you try to advance past it on a bundle-only build.
Stop here if you only wanted to see the pipeline run end to end.

## 4B. Assemble without Hancom (hwpx — reaches a graded artifact)

Set `doc_backend: hwpx` in `<WS>/build.yaml`, or pass `--backend hwpx`
explicitly:

```sh
python pipeline/scripts/ws_snapshot.py snapshot <WS>
python pipeline/scripts/doc_backend.py <WS> --backend hwpx
```

(`ws_snapshot.py snapshot` is the pre-assembly restore point the stage-5
playbook recommends before any assembly attempt.) The dispatcher invokes
hwp-master's `fill_report.py --engine xml` against `<WS>/output/form_copy.hwpx`
and `<WS>/bundle/content.md`, filling `output/out.hwpx` without Hancom or COM
on any OS. If `HWP_MASTER_SCRIPTS` is unset or incomplete, the dispatcher
exits 4 and prints the exact fix instead of guessing.

**Where the proof grade comes from:** `doc_backend.py` probes this machine's
render capabilities (`render_probe.py`: Hancom COM, `soffice` local/WSL,
H2Orestart) and picks a renderer:

- Hancom COM available → `proof_grade: hancom` (always outranks other grades).
- No Hancom, but a probe-verified document-scoped certificate is configured
  and `build.yaml` explicitly sets `certified_render: true` plus
  `render_certificate: <path>` → eligible documents may receive
  `proof_grade: certified`. This grade sits above advisory and below Hancom.
- No Hancom, `soffice`+H2Orestart available, and the document has **no**
  equations → `proof_grade: advisory` (a LibreOffice-rendered PDF, not
  print-grade proof).
- No Hancom and the document **has** equations → `proof_grade: none`.
  H2Orestart's equation fidelity is unverified, so the dispatcher refuses to
  call it proof at all rather than risk a false pass.
- No usable renderer at all → `proof_grade: none`.

This decision is echoed in the dispatcher's own JSON output and is expected
to land in `<WS>/output/verdict_v06.json` (written by the hwp-master assembly
loop itself) as the `proof_grade` field — that is exactly what Stage 6
`submission_preflight.py` reads later.

### Equation documents on Linux (experimental)

When there's no Hancom and the document has equations (or no `soffice`
renderer is installed at all), `doc_backend.py` can route to `rhwp_svg`
instead of leaving `proof_grade: none`. To enable it: install `rhwp`, point
`RHWP_BIN` at it (or leave it on `PATH`), and set `RHWP_SHA256` to the
SHA-256 of that exact executable file — the pin is mandatory; an unpinned or
mismatched binary is never treated as available
(`render_probe.verify_rhwp_binary`). The probe then runs `rhwp export-svg`
against a canonical-immutable render surrogate and writes a fail-closed
receipt to `output/proof/rhwp/receipt.json`, reporting an SVG page count and
an overflow/pagination check (`layout_overflow`, `parity_verdict`).

What you do **not** get: submission grade. `proof_grade: experimental-rhwp`
is hard-blocked by `submission_preflight.py` (`P5`: "diagnostic render
evidence, not a submission proof grade") and, unlike `advisory`, cannot be
waived with `--allow-advisory`. Pixel-level parity with Hancom rendering has
not been achieved — see
[`docs/plans/p0-parity-report.md`](plans/p0-parity-report.md) for the honest
status.

## 5. Post-assembly gates

```sh
python pipeline/scripts/pipeline_ctl.py advance <WS> 5 --status done
python pipeline/scripts/pipeline_ctl.py check <WS> format_check
python pipeline/scripts/pipeline_ctl.py advance <WS> 5.3 --status done

python pipeline/scripts/pipeline_ctl.py check <WS> understand
python pipeline/scripts/pipeline_ctl.py advance <WS> 5.5 --status done

python pipeline/scripts/pipeline_ctl.py check <WS> final_panel
python pipeline/scripts/pipeline_ctl.py advance <WS> 5.7 --status done

python pipeline/scripts/pipeline_ctl.py check <WS> submission_preflight
```

- `format_check` (`verify_format.py <WS> --require-output`) hard-enforces
  body font size, line spacing, margins, and PDF page bounds, and fails HARD
  if `output/out.hwpx` is missing.
- `understand` (`check_understanding.py`) requires five questions and, in
  supervised mode, five non-empty answers in `QUESTIONS.md`.
- `final_panel` (`check_scorecard.py`) fails HARD if any stop-line field in
  `output/scorecard*.json` is true, or the scorecard is missing/malformed.
- `submission_preflight` composes `check_saeteuk.py`, checks the canonical
  artifact's identity fields against `request.yaml`, recomputes and compares
  the assembled HWPX's form-structure hash against `form_baseline.json`, and
  requires `proof_grade` to be `hancom`, `certified`, or `advisory`.
  `certified` additionally requires the build opt-in, a passing live
  `render_cert check`, and a certificate whose self-hash, corpus manifest,
  renderer binary, and pinned versions re-verify. Hancom/advisory grades are
  cross-checked against this machine's actual render capabilities, so a recorded `hancom` grade
  that can't be reproduced here (no Hancom on this delivery machine) is
  rejected rather than trusted blindly.

## 6. Where you land

- Exit 0 on `submission_preflight` = a graded verdict: `proof_grade` is
  `hancom`, `certified`, or `advisory`, the form structure is unmutated, and identity
  fields are filled. This is printed as JSON and can be written with `--out`.
- An `advisory`-grade equation document, or any `proof_grade: none` run, is
  rejected by default. To record an explicit draft exception (never a silent
  pass), use `--allow-advisory --reason "<why>"` or `--allow-unproven` —
  both are logged in the verdict JSON, not hidden.

## Windows + Hancom alternative

Everything from step 4B onward has a Hancom/COM equivalent: set
`doc_backend: hwp`, ensure hwp-master's `.[windows]`/`.[proof]` extras and a
licensed Hancom install are present, and run
`<HWP_MASTER_ROOT>/scripts/fill_report.py --loop --proof ...` per
`pipeline/references/playbooks/stage-5.md`'s §HWP section instead of
`doc_backend.py --backend hwpx`. That path reaches `proof_grade: hancom`
directly and includes hwp-master's own render-measured fill/tidy/typeset
loop, which the XML engine only gained (optionally, when a renderer is
configured) in the v0.10 wave.
