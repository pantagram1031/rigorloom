# Lessons learned

This document preserves reusable engineering lessons from real pipeline runs.
It deliberately excludes personal reports, identities, private templates, and
provider account details.

## Enforce invariants in code

A written instruction is not a gate. Earlier workflows described human approval,
non-destructive editing, and deterministic simulation verdicts correctly, but an
agent could still narrate compliance and continue. The durable rule is:

- persist every gate with state, source, and time;
- reject stage advancement when its gate is unmet;
- treat script output as immutable evidence;
- change a gate's inputs and rerun it instead of rewriting a failed result;
- distinguish human approval from autonomous acknowledgement.

The same rule applies to file safety. A statement such as “always use a copy” is
not sufficient; writers must reject identical input/output paths and verify the
source hash after assembly.

## Avoid tautological verification

A check is invalid when its measured value is derived directly from the expected
value. For simulations, perturb inputs and recompute the dependent quantity
through the real pipeline. For document production, inspect the saved artifact,
not the operation list that was intended to create it.

## Typeset from a budget

Repairing layout after assembly by accumulating font, spacing, and margin knobs
made outputs fragile. The stable sequence is:

1. inspect the form and freeze its owned structure;
2. allocate section line budgets, tables, figures, and equations;
3. write to that budget;
4. assemble from a pristine form copy;
5. repair overflow or voids with small content deltas;
6. rerun assembly and proof from the pristine copy.

This is why Stage 2.5 exists. Text is the final layout control; global formatting
changes are not.

## Keep one source of truth

Multiple hand-edited outputs and sibling backup files made resume behavior
ambiguous. The current design keeps one canonical output, immutable receipts,
and generated indexes. Scratch and completed stage work are archived, while
canonical inputs and outputs stay in place.

## Calibrate automation against real artifacts

Visual and structural checks need explicit exemptions for intentional form
features such as cover whitespace, heading boundaries, and page-bottom gaps.
An exemption must be declared and tested; it must not be added after seeing a
failure merely to turn the result green.

## Use independent review for numeric claims

A second reviewer is useful only when it is genuinely independent. Numeric
claims should be checked by at least two distinct reasoning paths or by one
reviewer plus executable recomputation. Provider names are configuration, not
part of the kernel contract.

## Bound delegation

Nested delegation produced duplicated work and lost ownership. Give a worker a
bounded artifact, forbid recursive delegation when appropriate, and require a
small structured return. Raw logs and large binary artifacts belong in the
workspace, not in the orchestrator context.

## Treat downloads as hostile inputs

HTTP success is not proof of valid data. Validate size, content type or header,
schema, and expected columns before a downloaded dataset becomes evidence.

## Preserve failures as tests

Every expensive HWP or pipeline repair should end as a synthetic fixture,
deterministic test, troubleshooting signature, or explicit design decision.
Otherwise the same probe cycle will recur during the next refactor.
