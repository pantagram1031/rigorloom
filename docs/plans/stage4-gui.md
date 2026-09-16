# Stage 4 — GUI on the stable CLI contract

Status: ACTIVE 2026-09-16. Owner: Fable. Source: `docs/plans/analyses/stage4-gui-research-grok-low.md`
(survey of LibreOffice Writer, Typst, Overleaf, Zed, VS Code, Obsidian, Cursor, GitHub PR review, Google Docs;
32 links). Renderer/rematch/certificate freeze stays in force: no live rendering claims, previews are
"honest page preview" with an explicit reason when unavailable.

## What we borrow (one line each)

- Zed / VS Code multibuffer + per-hunk keep/reject → the plan review queue shows each op with before/after
  from `read-region`; per-op edits produce a NEW `propose` (hash binding stays honest); accept-all = `approve`
  with the displayed plan hash.
- GitHub PR review (commit-bound approval) + LibreOffice author tooltips → every hunk carries session id,
  plan id, plan hash, proposer, backend, parent run, and whether a receipt exists.
- Overleaf Recompile button + Typst stale label → preview is on demand, labelled with the run id it came from,
  never per keystroke; `render` unavailable is shown as the JSON reason, not an error styled as success.
- Obsidian source/live split → structure tree (`inspect`) beside exact region text (`read-region`), so pretty
  views never hide form anchors the residue checker still sees.
- Cursor checkpoints without lying about Git → history is the candidate DAG + events; "restore" is a reverse
  plan (`propose --reverses-run`) through approve/apply, never in-place mutation of the original.
- VS Code IME composition guard → approve/apply buttons are inert while a Korean composition is open.

## Slices (value per effort, each visualizes commands that already exist)

- [x] G1 Plan review queue — `propose`, `validate`, `plan`, `request-approval`, `approve`, `reject`. Existing
      `ReviewQueue` extended (grok-4.6-xhigh, 13 min, 131k in / 44k out / 3.4M cache): IME-inert gate, per-hunk
      provenance strip, approve decoupled from apply; headless tests 113 → 120, build ok. Follow-up: `smoke.ts`
      still expects approve to apply (scripted smoke needs a separate `applyApproved()`), Composer composition
      does not yet set `isComposing`.
- [ ] G2 Receipt / verify / compare inspector — `receipt`, `verify`, `compare`, `candidates`; `acceptance: false`
      and exit 3 stay visible as refusals.
- [ ] G3 Honest page preview — `render`, `render-prepare` (host-only, explicit button), `geometry` when present.
- [ ] G4 Structure tree + region source — `inspect`, `read-region`.
- [ ] G5 Session history + reverse — `events`, `candidates`, `propose --reverses-run`.

Default screen: reuse the desktop `DocumentView` layout from `docs/desktop-code-map.md`: StructureTree (G4) |
TextView + optional PagePreview (G4, G3) | ReviewQueue + ReceiptPanel + History (G1, G2, G5); VerificationBar
shared. No new document semantics; the GUI and the CLI must produce byte-identical plan JSON.

## Acceptance sketch

Same plan JSON from GUI and CLI; a rejected hash cannot apply; receipt byte drift is an error; render unavailable
is exit 0 unless `--require-render`; Korean composition in region text does not submit approve/apply mid-syllable.

## Ledger

| When | What | Result |
|---|---|---|
| 2026-09-16 | Research note by cursor-grok-4.6-low-fast (2.9 min, 82k in / 7.9k out / 491k cache) after the API-billed tier hit its cap; sol's earlier attempt died on the cap | note kept under docs/plans/analyses |
