# Edit Stage 4.5 — submission preflight

Run the registered submission preflight after acceptance and before delivery.
Its HWPX form-skeleton comparison is the final authority: a recorded baseline
must match the edited output's charPr, paraPr, secPr, table/cell, and control
structure. Resolve any form_mutated finding by rebuilding from the pristine
form copy; never replace the baseline with the edited output's hash.

Resolve only through:

    python pipeline/scripts/pipeline_ctl.py check <WS> submission_preflight
