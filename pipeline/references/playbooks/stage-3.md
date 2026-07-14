# Stage 3 — Data / Sim (deterministic gate, HARD)
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: Execute the Stage 2 verification criteria in code. The gate code
emits `sim/gate_result.json` (immutable, authoritative). No post-hoc edits.

ENTRY: `pipeline_ctl resume` → stage 3. Stage 2 done (gate design ok).

EXACT actions:
```
# write + run sim in <WS>/sim/
#   verification criteria from 01_design.md executed by code
#   sim spec fixes one numeric RNG seed before execution (no implicit entropy)
#   code records that seed in sim/results.json or sim/provenance.json
#   gate code emits sim/gate_result.json  (immutable, authoritative)
# figures → <WS>/bundle/figures/*.png  with:
#   matplotlib.rcParams['font.family']='Malgun Gothic'
#   matplotlib.rcParams['axes.unicode_minus']=False
#   write one checksum record for every referenced PNG (format below)
```
- Every figure-generation step MUST write checksum metadata from the final PNG
  bytes so Stage 4.5 can detect a hand-edited or stale image. Prefer a UTF-8
  sibling sidecar named `bundle/figures/x.png.sha256` whose first token is the
  64-hex SHA-256, conventionally `<sha256>  x.png`. A single
  `bundle/figures/figures_manifest.json` is also valid; use either a direct
  `{"x.png": "<sha256>"}` mapping (paths are relative to the figures
  directory) or `{"figures": [{"file": "x.png", "sha256": "<sha256>"}]}`.
  If both sources exist, both must match the PNG. Regenerate the checksum after
  every legitimate figure regeneration; never update it to bless an unexplained
  manual image edit.
- Verification FAIL → fix the MODEL, rerun. NEVER edit numbers or the JSON
  post-hoc (§7). scope narrowing (e.g. AFGKM만) = declared input, re-run.
- Every fresh simulation fixes a numeric RNG `seed` in its spec and echoes the
  same seed into `sim/results.json` or `sim/provenance.json`. An empty/string
  seed is invalid. Before the sane gate, run
  `python pipeline/scripts/check_numbers.py --require-seed <WS>`; a populated
  results file without the seed is HARD. A missing/empty legacy results file is
  only advisory until the simulation is rerun.
- `sim/VERIFY.md`: show RAW + ADJUSTED verdict side by side. Never write
  only "all passed".

ROLE BINDINGS (§R): sim-executor = agent.worker/medium (medium, run+QA).
reviewer-logic = agent.worker/high (sim-code review, high) — **but never sole
numeric reviewer; pair with a second independent high-reasoning pass for numbers** (§R). designer
= high-capability worker (model judgment).

EXIT + gate: `sim/gate_result.json` emitted + `sim/VERIFY.md` (raw+adjusted).
This is the **script gate `sane`** — the code's verdict is truth, not a
human gate. The `check` subcommand RUNS the bound checker (`{WS}/sim/gates.py`)
and records its exit code + provenance; it never accepts a hand-supplied
verdict. `sim/gates.py` must exit 0 on pass, nonzero on fail. Run `check`,
THEN advance → stage 4:
```
# cd <REPO_ROOT>/ (all paths below are relative to this, repository-root CWD)
python pipeline/scripts/pipeline_ctl.py check <WS> sane
python pipeline/scripts/pipeline_ctl.py advance <WS> 3 --status done
```

FAILURE table:
| Symptom | Cause | Action |
|---|---|---|
| gate verdict FAIL | model wrong | fix model, rerun; never edit JSON |
| tempted to edit gate_result.json | — | contract violation (§7); forbidden |
| figure 한글 깨짐 | font not set | set Malgun Gothic + unicode_minus=False, rerun |
| `figure_data_drift` at content audit | PNG differs from its recorded checksum | regenerate the figure from simulation and rewrite its checksum; do not hand-edit the verdict |
| `figure_unverified` WARN | legacy PNG has no checksum metadata | regenerate or hash the final PNG and add the sidecar/manifest entry |
| one reviewer alone cleared numbers | single-reviewer risk | add an independent second pass |
| check_numbers exit 3: missing/invalid seed | fresh sim omitted RNG provenance | fix the sim spec/code, rerun, and record the numeric seed |
