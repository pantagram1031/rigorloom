# HWP document adapter

HWP is now one of **three** Stage 5 document backends, selected in `build.yaml`
(`doc_backend:`) and dispatched by `pipeline/scripts/doc_backend.py`: `bundle`
(zero-dependency floor, always available), `docx` (optional `python-docx`), and
`hwp` (this adapter — Windows + Hancom, the only one needing an external repo).
The pipeline runs end-to-end WITHOUT this adapter via the `bundle` backend; use
`hwp` only when a native HWP deliverable is required.

HWP/HWPX assembly is handled by the engine bundled at `engine/` in this
repository (absorbed from the former external hwp-master project in Wave 2 /
v0.16; its history is preserved in this repo). No external checkout or
environment variable is needed — stage playbooks reference
`engine/scripts/...` directly. Any other
document backend may be substituted if it implements inspect, assemble, tidy,
measure, and proof-render operations described by the v0.6 contract.

## Minimum verification for one-off edits

Even when a document is edited outside a full pipeline workspace, do not stop
after a successful COM save:

1. apply offline HWPX typeset defaults so body paragraphs use widow/orphan
   protection and declared headings/captions use keep-with-next;
2. export PDF and run numeric layout QA for bottom voids and abnormal gaps;
3. render every page and inspect heading/caption continuity;
4. inspect pages containing new inline equations at high resolution, because a
   malformed superscript can be invisible in a contact-sheet thumbnail.

Intentional cover whitespace and display-equation spacing may be exempted only
after visual confirmation. Prefer text-anchor exemptions over page numbers,
which become stale after reflow.
