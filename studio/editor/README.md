# Studio Web Editor — Phase-1 PoC

This directory is an isolated design spike. It does not import into or change
the existing `studio/main.py` dashboard.

The PoC exposes a localhost-only FastAPI page that lists HWPX paragraphs,
allows one plain text payload to be edited, applies the operation through a
byte-local HWPX backend, verifies all other ZIP members byte-for-byte, renders
the revised file with rigorloom's discovered `soffice` command, and rasterizes
the first PDF page with PyMuPDF. A separate sanitized equation fixture proves
that equation-bearing paragraphs are flagged and locked.

## Run

From the repository root:

```powershell
python -m pip install -r studio/requirements.txt
python -m studio.editor.app --port 8010
```

Open `http://127.0.0.1:8010`. Runtime revisions and operation logs go to the
system temporary directory unless `--data-root` is supplied. The process makes
no model or network calls and binds only to `127.0.0.1`.

Run the deterministic tests:

```powershell
python -m pytest studio/editor/tests -q
```

Measure the server-side edit/render/raster cycle:

```powershell
python -m studio.editor.benchmark --iterations 5 --warmup 1 `
  --out studio/editor/results/preview-latency-2026-07-19.json
```

The benchmark records its command, environment, renderer probe, document hash,
per-run fidelity result, and edit/render/raster timings in the JSON output.
