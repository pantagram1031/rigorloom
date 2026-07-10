# HWP document adapter

HWP/HWPX assembly is intentionally maintained in the separate public
[hwp-master](https://github.com/pantagram1031/hwp-master) repository.

Clone it beside this repository or set `HWP_MASTER_ROOT`:

```sh
git clone https://github.com/pantagram1031/hwp-master.git ../hwp-master
export HWP_MASTER_ROOT="$(cd ../hwp-master && pwd)"
```

Stage playbooks use `<HWP_MASTER_ROOT>/scripts/...` placeholders. Any other
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
