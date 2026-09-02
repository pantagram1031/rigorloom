---
name: Bug report
about: Report a problem with the pipeline, a gate, the Runtime, the Desktop app, or the Studio
title: "[Bug] "
labels: bug
---

## Describe the bug

A clear, concise description of what's wrong.

## Steps to reproduce

1.
2.
3.

## Expected behavior

What you expected to happen instead.

## Environment

- OS:
- Python version:
- Rigorloom version / commit:
- Surface (`pipeline` / `runtime` / `desktop` / `studio`):
- Document backend in use (`bundle` / `docx` / `hwpx` / `hwp`), if relevant:

## Evidence

This repository settles arguments with artifacts rather than with
descriptions, and a bug report is no exception: the payloads below say what
your build could actually do, and without them a maintainer is guessing at the
same question you are. Attach whatever applies. Every command here prints JSON
to stdout and none of them modify a document.

**What this build says it can do** — always useful, and usually the thing that
explains "it works on my machine":

```sh
python runtime/scripts/cli.py --root <your runtime root> capabilities
```

The `capabilities` payload names the backends, the rasterizer state, the
render converter, the child interpreter and the module registry state. If the
Desktop app is what misbehaved, its verification bar names the runtime root it
is using, and this is the same payload the app itself reads.

**If a document was edited, applied or exported** — the receipt:

- From the Desktop app: **영수증 보기** in the verification bar shows the
  receipt and the JSON behind it, and an export writes
  `<artifact>.receipt.json` beside the exported candidate.
- From the command line:
  `python runtime/scripts/cli.py --root <root> receipt --session <sessionId> --run <runId>`

A receipt binds a digest to the bytes it accounts for, so paste it whole; a
trimmed receipt cannot be checked against anything.

**If a page did not render, or rendered wrong** — what render backends this
host actually has (it reports capability state, not filesystem paths):

```sh
python pipeline/scripts/render_probe.py --json
```

For a pipeline run, `output/verdict_v06.json` carries the proof grade the
submission gates read; attach it alongside.

**If a gate fired, or refused to** — the gate's own verdict, not a summary of
it. Paste the command and its full output including the summary line (for
example `summary: HARD=0 WARN=43 TOTAL=43`).

## Logs / output

```
paste relevant command output, JSON verdicts, or traceback here
```

## Additional context

Anything else that would help (workspace layout, a minimal `build.yaml`,
etc.). Please do not attach real report content, private forms, or
personally identifying data — see [AGENTS.md](../../AGENTS.md). Receipts,
capability payloads and verdicts are built to be shareable; a source document
is not.
