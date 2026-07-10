# Troubleshooting

## Resume returns an unexpected stage

Do not edit `PIPELINE.md` manually. Inspect the stage rows, gate records, and
latest receipt, then use `pipeline_ctl.py gate` or `advance` to make the intended
transition. Narrative progress notes are not state.

## A script failed but a summary says it passed

The script verdict wins. Archive the contradictory summary, correct the gate
inputs, rerun the script, and record the new verdict as a separate event.

## A simulation check always passes

Look for a tautology: the “measured” side may be the injected or expected value
itself. Perturb upstream inputs and recompute the final dependent result through
the production calculation.

## A downloaded dataset is tiny or unparsable

It may be an error page saved as data. Check byte size, header or magic bytes,
schema, and required columns before retrying from an authoritative source.

## An agent cannot determine which file is current

Use `WORKSPACE_INDEX.md`, `.pipeline/artifacts.json`, and the latest stage receipt.
Move unreferenced `.bak`, `.old`, and scratch output through the organizer; do
not create another canonical filename.

## A stage rerun duplicates or corrupts output

Discard the partial derivative and rebuild from the canonical bundle and a
pristine form copy. Do not hand-patch a failed assembly and then continue the
pipeline from that derivative.

## Studio or an adapter accepts an unexpected path

Treat workspace identifiers as untrusted input. Validate the slug, resolve the
path, and assert containment within the configured workspace root before reading
or writing any file.

## HWP stages are unavailable

Run the `hwp-master` doctor. Full COM editing requires Windows, locally installed
desktop Hancom Office HWP, and the optional Python COM packages. Continue only
with provider-neutral or non-COM stages when that host is unavailable.

## A one-off HWP edit looks acceptable but was not run through the pipeline

Keep the original unchanged and save the edit as a new file. Export a PDF, run
layout QA, and inspect all rendered pages for widow/orphan headings, detached
captions, blank bands, and equation damage. A contact sheet is not sufficient
for new inline equations: inspect those pages at high resolution. If any check
fails, rebuild from the pristine source instead of stacking manual formatting
changes on the damaged derivative.
