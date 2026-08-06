# Reopen/amend transition — design (W1, shared-miss #2)

Status: DESIGN. Implementation follows as separate slices. Matrix evidence:
`docs/research/variant-audit.md` Bench 4 — **every variant's worst state lie
lived in post-"done" work**: hawkes ran 18.5 h of rework (v2→v17, retitles,
forks) after the machine recorded complete; sambal/enso shipped artifacts past
a stalled/failing recorded state; nothing anywhere can reopen a finished stage
or record an off-graph edit.

## Design principles

1. **Append-only honesty.** Reopening never rewrites history — `done_at`
   stays; an amendment is a new record, not an edit.
2. **Cheap to invoke.** D's rework went off the books precisely because there
   was no lightweight way to record it. One command, one reason string.
3. **Mode-agnostic.** Works with the stage machine (night mode) and with the
   stateless lean mode, where it attaches to the FINAL pointer instead of a
   stage.
4. **A backstop that needs no cooperation.** Even if nobody calls reopen, the
   next gate run must detect unrecorded edits by hash.

## Mechanism

### Amendment records

`PIPELINE.md` YAML header gains:

```yaml
amendments:
  - {id: A1, opened_at: ..., reason: "operator: subhead density rework",
     scope: ["5"], status: open|closed, closed_at: null,
     artifact_before: <sha256>, artifact_after: null, gates_rerun: []}
```

### Commands (pipeline_ctl)

- `reopen <stage> --reason <text>` — allowed only on `done` stages. Creates an
  open amendment, sets the stage to a new status `amending` (distinct from
  pending/done; prior completion preserved), and **invalidates the canonical
  pointer** — it must be re-designated at close.
- `amend-close <id>` — refuses unless: the reopened stages' gates re-ran green,
  `check_canonical` passes on the re-designated pointer, and the verdict file
  passes `verdict_schema`. Writes `artifact_after` hash and a closure receipt.

Both transitions are receipt-signed like normal stage transitions
(`receipt_sign`), so amendments cannot be forged or postdated silently.

### The backstop: `unrecorded_edit`

`submission_preflight` (and stage-6 composition) compares the canonical
artifact's current sha256 against the last recorded hash (stage receipt or
closed amendment). **Mismatch with no open amendment = HARD
`unrecorded_edit`.** This fires regardless of whether anyone used reopen —
it is the mechanism that would have caught hawkes' silent v2→v17 line and
sambal's post-stall 사람화 artifact.

### Stateless (supervised-lean) mode

No stages to reopen. The FINAL pointer record (check_canonical) carries the
hash; `declared_gates` already records per-gate target mtime+sha256 at check
time. Amendment = re-running the declared gates after an edit; `unrecorded_edit`
fires when the FINAL hash differs from the newest gate_result with no
re-run after the edit. Same honesty, no ceremony.

## Still-catches (calibration rule)

- hawkes: retitled ship artifact + 15 rework versions after "done" →
  `unrecorded_edit` at any later preflight.
- sambal: `Sambal_E_소논문_최신_사람화.hwpx` created 40 min after the last
  recorded event, stages still pending → hash absent from any receipt →
  `unrecorded_edit`.
- windpath: v7 final while gate_result pins v5 → staleness data + FINAL
  pointer rule flags it.

## Implementation slices (in order)

1. Schema + `reopen`/`amend-close` in pipeline_ctl, with receipts and tests.
2. `unrecorded_edit` in submission_preflight (+ stage-6 composition), tests
   against synthetic hawkes/sambal-shaped fixtures.
3. Stateless-mode wiring: FINAL pointer hash ↔ declared_gates staleness data.

Out of scope here: retroactive repair of the five audited workspaces — they
stay as exhibits; the mechanism is for every run after it lands.
