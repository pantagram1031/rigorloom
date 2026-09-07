# QA completion cards on this tip

This directory is the **green tip-stack** (`cursor/tip-stack-green-344-346-348-349-916f`)
runbook for product-completion cards. It does not pull rematch, own_render,
convergence, IoU, or LayoutSnapshot branches.

| Card | On this tip | Run entry |
| --- | --- | --- |
| 1 export safety | Matrix + Windows force-quit Run-Card (#346 / #348) | `python qa/export_safety_card1_matrix.py` |
| 2 draft-fence | Product tests present | `python -m pytest tests/test_desktop_draft_fence.py tests/test_desktop_revision_coherence.py -q` |
| 3 run-scoped edit | Product tests present (#349) | `python -m pytest tests/test_desktop_run_scoped_edit.py -q` |
| 4 Korean mixed E2E | Prep harness restacked from #341 / #347; IME still **NOT_RUN** / hold | `python qa/run_cards.py --job qa/job.card4.example.json` |
| 5 install hash | This harness | `python qa/install_candidate_hash.py` |

## Inventory

- **#337** `qa/run_cards.py` harness — restacked onto this tip.
- **#341** card 4 fixture probe / manifest — restacked onto this tip (IME remains NOT_RUN).
- **#347** `mock_approved` approval wire — restacked onto this tip (does not claim human approval or GUI/IME PASS).
- **#346 / #348** card 1 matrix + native force-quit — **in this tree**.
- Rematch / own_render / conveyor / LayoutSnapshot / IoU pins stay frozen off this tip.
- Card 5 never claims GUI / IME / install PASS. A Linux checkout run is NOT_RUN.

Card 5 details: [`card5-install-hash.md`](card5-install-hash.md).
