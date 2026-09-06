# Independent review — completion cards 2–3 safety on product tip

Date: 2026-09-06  
Reviewer mode: read-mostly, no product-code edits  
Reviewed tip: `5d955a3836` (#336) stacked on `e900c2a34f` (#333)

## Scope and constraints checked

- Reviewed #333 (`cursor/run-scoped-edit-5851`) and #336 (`cursor/export-safety-6bbd`) on the current stacked tip.
- Cross-referenced #332/#334 contract/review notes (read-only).
- Did **not** touch desktop product code, own-render work, installer flow, or rematch branches.

## 1) UTF-16 / run-span / unmodified-runs risks and missing tests

### Findings

1. **Range-coherence gap when editing the same run twice (FAIL)**  
   In `commitEdit`, replacement is applied to `queuedRun?.text ?? edit.before` (`desktop/src/actions.ts:550-559`), but the selected `rangeStart/rangeEnd` came from `prepareParagraphEdit` on the currently displayed revision text (`desktop/src/revision.ts:217-236`).  
   If one queued `set_run` already changed earlier characters in that run, a second edit can splice at stale offsets.

2. **Run mapping is still text-search based, not geometry run-span based (known risk, still open)**  
   `locateSpanInRuns` resolves by `indexOf`/fallback matching (`desktop/src/run_map.ts:97-155`), which is conservative but can refuse valid cases (`multi_run` / `run_text_differs`) where line-box identity would disambiguate.

3. **Engine-level unmodified-run safety exists; desktop-level coverage is thinner**  
   Good: `preedit.set_runs` has explicit tests that only addressed runs change and neighbors stay untouched (`engine/tests/test_preedit.py:1648-1660`).  
   Gap: desktop run-scoped tests do not cover multi-edit same-run offset drift, control-in-run cases (`hp:lineBreak`/`hp:tab`), or Hangul-heavy strings.

### Missing tests

- Two sequential edits on the **same** wrapped run where first edit changes length before second range.
- Repeated span text in one run + two-run same-substring ambiguity with line-box click disambiguation.
- Caret placement after supplementary-plane characters in real geometry response.
- Run containing inline controls (`lineBreak`/`tab`) to prove preserve-or-refuse behavior.
- Hangul/NFD/compat-jamo strings in the run-map path (not just Latin+emoji).

## 2) Draft-fence gaps card 2 still needs to close

> Documenting only; no attempt to modify card-2 in-flight branch.

1. **No async request fence around queue repropose pipeline (FAIL)**  
   `setQueue` performs async `proposePlan -> validatePlan -> setState` (`desktop/src/actions.ts:712-799`) with no request token/generation guard.  
   Queue edits can be triggered rapidly via input `onChange` (`desktop/src/components/ReviewQueue.tsx:124-131` -> `editOpValue` -> `setQueue`).  
   A slower old response can overwrite newer draft state.

2. **Related race surfaces**  
   - `setHead` can call `setQueue(..., { baseRunId })` while other queue updates are in-flight (`desktop/src/actions.ts:1055-1069`).
   - Same stale-overwrite class unless guarded by last-write-wins fence in client state.

### Card-2 follow-up (concrete)

- Add a draft request generation/id in `setQueue`; ignore stale `propose/validate` completions.
- Add harness coverage for reverse-order completion of queue repropose (similar spirit to click lease race tests, but for draft pipeline).
- Assert invariant: latest `draft.ops` snapshot owns the accepted `planId/opsHash`.

## 3) Real HWPX apply/reopen path status and follow-ups

### Current state

- There **is** a real flow in smoke code: `edit -> approve -> apply -> export -> reopen` (`desktop/src/smoke.ts:456-470`, `786-805`), and `reopenExported()` uses normal `workspace/openPath` (`desktop/src/actions.ts:1359-1376`).
- #336 export safety is strongly covered at Rust matrix level (16 pass in this review run), but those tests use synthetic artifact bytes for many cases (`tests/desktop_export_safety_harness.rs`), not full real-HWPX reopen proof.

### Still missing for closure

1. **Install-candidate execution evidence (NOT_RUN here)**  
   Run the smoke edit phase on hashed install candidate and publish report artifact proving apply/export/reopen on real corpus file.

2. **Focused integration test outside UI harness**  
   Runtime/desktop integration test: apply candidate, export via `export_candidate`, reopen exported file, re-`inspect`, and assert document hash + key region values.

3. **Negative reopen cases**  
   Add explicit failure-path checks for corrupt/partial export pair reopen attempts to ensure refusal is surfaced clearly.

## Evidence run in this review

- PASS: `rustc --test --edition 2021 -o /tmp/export_safety tests/desktop_export_safety_harness.rs && /tmp/export_safety --test-threads=1`  
  Result: 16 passed, 0 failed.

## FAIL / NOT_RUN checklist still required

- [FAIL] Draft async fence: stale `setQueue` completion can clobber latest draft (`actions.ts:712-799`).
- [FAIL] Same-run second-edit range coherence over queued text not guaranteed (`actions.ts:550-559` + `revision.ts:217-236`).
- [NOT_RUN] `pytest` safety suites in this environment (`python3 -m pytest ...` failed: `No module named pytest`).
- [NOT_RUN] JS run-scoped harness execution (desktop TypeScript dependency absent: `desktop/node_modules/typescript` missing).
- [NOT_RUN] Real install-candidate apply/export/reopen evidence capture for card closure.
