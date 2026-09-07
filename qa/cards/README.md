# QA completion cards on this tip

This directory is the **green tip-stack** (`cursor/tip-stack-green-344-346-348-349-916f`)
runbook for product-completion cards. It does not pull rematch, own_render,
convergence, IoU, or LayoutSnapshot branches.

| Card | On this tip | Run entry |
| --- | --- | --- |
| 1 export safety | Matrix + Windows force-quit Run-Card (#346 / #348) | `python qa/export_safety_card1_matrix.py` |
| 2 draft-fence | Product tests present | `python -m pytest tests/test_desktop_draft_fence.py tests/test_desktop_revision_coherence.py -q` |
| 3 run-scoped edit | Product tests present (#349) | `python -m pytest tests/test_desktop_run_scoped_edit.py -q` |
| 4 Korean mixed E2E | **Not in this tree** (lives on #341 / #347) | Device evidence; still NOT_RUN here |
| 5 install hash | This harness | `python qa/install_candidate_hash.py` |

## Inventory (do not merge those branches into this tip)

- **#337** `qa/run_cards.py` harness — `cursor/qa-harness-d143` (not this tree).
- **#341** card 4 fixture probe / manifest — `claude/qa-card4-korean-e2e-prep` (not this tree).
- **#347** `mock_approved` approval wire — `cursor/qa-approval-resolve-3dda` (not this tree; stacked on #341).
- **#346 / #348** card 1 matrix + native force-quit — **in this tree**.
- Card 5 never claims GUI / IME / install PASS. A Linux checkout run is NOT_RUN.

Card 5 details: [`card5-install-hash.md`](card5-install-hash.md).
