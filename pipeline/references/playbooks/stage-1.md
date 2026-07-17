# Stage 1 — Research (evidence pack)
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: Web/RAG evidence with tracked sources. No body fact without a
source id (or explicit student inference).

ENTRY: `pipeline_ctl resume` → stage 1. Stage 0 done.

EXACT commands / actions:
```
# 3 parallel researcher subagents (lenses), then 1 cross-exam round.
#   R1 concepts/theory · R2 datasets + CC images (license+source) ·
#   R3 books(ISBN) + curriculum tie-in → research/curriculum.md
# Tooling per subagent: WebSearch / firecrawl / deep-research skill.
# Output:
#   research/evidence.md   numbered claims, each tagged with source id(s)
#   research/sources.json  [{id,title,url,accessed,kind:web|dataset|paper|book,claim_ids}]
#   claims.yaml            per-claim evidence ledger at workspace root
```
At research time, record every verified DOI or ISBN through the write-through
cache, for example `python pipeline/scripts/source_fetch.py record --doi
10.x/y --title "..." --retrieved-from <URL> --content-sha256 <SHA256>`.
Do this when the source is verified, not later at gate time; the command writes only under
`<PROFILE_ROOT>/cache/sources/`.

For the `backfill` alias, run `python pipeline/scripts/claims_ledger.py
claim_extract <WS>` first, then use retro-research to fill every skeleton entry
with source id, locator, and short quote while building the evidence pack. The
skeleton intentionally fails `check_claims` until evidenced; retro-research is
complete only when `python pipeline/scripts/check_claims.py <WS>` exits 0.
- Any body-fact claim needs ≥1 source id; uncited → flag, body only as
  student inference.
- Datasets: record REAL url + size/header assertion (block the
  `hyg_v41.csv`=14B "404: Not Found" incident).
- Cross-exam: cross-examiner challenges top claims, ONE round, no open
  debate. Unresolved → flagged, cannot become body fact.

ROLE BINDINGS (registry §R): researcher×3 = agent.worker/medium parallel
(medium). cross-examiner = agent.worker/high (high). Subagents return
verdict/summary only — no raw search dumps to main context.

EXIT + gate: evidence.md + sources.json + claims.yaml + curriculum.md written;
cross-exam done. No human gate. Advance → stage 2:
```
python pipeline/scripts/pipeline_ctl.py advance <WS> 1 --status done
```

FAILURE table:
| Symptom | Cause | Action |
|---|---|---|
| dataset url 404/stub | stale link | reject; find replacement with size/header assertion; never swallow stub |
| claim uncited after research | no source found | mark student-inference or drop; never fabricate id |
| researcher returns raw dumps | template not followed | re-invoke with subagent-templates.md return schema |
| night: token budget hit | fan-out too wide | degrade 3→2 researchers, record assumption |
