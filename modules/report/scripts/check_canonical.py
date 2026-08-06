# -*- coding: utf-8 -*-
"""Canonical/FINAL pointer validation (shared-miss #3 + #4).

Every audited variant rotted here differently: B wrote the literal string
"null" as its canonical output, D never named its ship artifact, E marked
nothing. This checker reads the workspace's declared canonical pointer —
``canonical_output`` in the PIPELINE.md v0.4 YAML header, falling back to a
``canonical_output`` key in ``.pipeline/handoff.json`` — and HARD-fails when:

- the pointer is missing / null / the literal string "null" while a delivery
  stage (id >= ``--done-after``, default 5) claims status ``done``, or the
  handoff records the workflow as complete; or
- the pointer is set but resolves to a nonexistent path (a pinned target that
  is not there is a HARD error, never a silent pass).

Exit 0 = pass, 2 = usage/input error, 3 = HARD finding.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Module-script import mechanism (see modules/README.md): sibling scripts via
# the module scripts dir, core helpers via the core pipeline/scripts dir.
SCRIPTS_DIR = Path(__file__).resolve().parent
_CORE_SCRIPTS_DIR = SCRIPTS_DIR.parents[2] / "pipeline" / "scripts"
for _dir in (_CORE_SCRIPTS_DIR, SCRIPTS_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
from checker_base import (  # noqa: E402
    _utf8_stdio,
    cli_main,
    exit_code,
    usage_error,
    verdict_skeleton,
)
import pipeline_ctl  # noqa: E402


CHECKER = "check_canonical"
DEFAULT_DONE_AFTER = 5.0

# Values that mean "no pointer declared" — including the literal string
# "null" that variant B managed to write into a live header.
NULL_TOKENS = frozenset({"", "null", "none", "~"})


def is_null_pointer(value) -> bool:
    return value is None or str(value).strip().lower() in NULL_TOKENS


def _stage_number(stage_id: str) -> float | None:
    try:
        return float(stage_id)
    except (TypeError, ValueError):
        return None


def read_declarations(ws: Path) -> dict:
    """Collect pointer + done-claim evidence from header and handoff.

    Returns a dict with keys: ``header`` (parsed header dict or None),
    ``handoff`` (dict or None), ``pointer`` (raw declared value or None) and
    ``pointer_source`` (which file declared it).
    """
    header = None
    loaded = pipeline_ctl.load_header(ws)
    if loaded is not None:
        header = loaded[3]

    handoff = None
    handoff_path = ws / ".pipeline" / "handoff.json"
    try:
        payload = json.loads(handoff_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            handoff = payload
    except (OSError, UnicodeError, json.JSONDecodeError):
        handoff = None

    pointer = None
    pointer_source = None
    if header is not None:
        pointer = header.get("canonical_output")
        pointer_source = "PIPELINE.md"
    if is_null_pointer(pointer) and handoff is not None \
            and not is_null_pointer(handoff.get("canonical_output")):
        pointer = handoff.get("canonical_output")
        pointer_source = ".pipeline/handoff.json"

    return {
        "header": header,
        "handoff": handoff,
        "pointer": pointer,
        "pointer_source": pointer_source,
    }


def done_claims(header: dict | None, handoff: dict | None,
                done_after: float = DEFAULT_DONE_AFTER) -> list[str]:
    """Return the delivery-stage done claims recorded in header/handoff."""
    claims: list[str] = []
    stages = (header or {}).get("stages") or {}
    for stage_id, state in stages.items():
        number = _stage_number(stage_id)
        if number is None or number < done_after:
            continue
        if isinstance(state, dict) and state.get("status") == "done":
            claims.append(f"PIPELINE.md stage {stage_id} done")
    if isinstance(handoff, dict):
        completed = handoff.get("completed_stage")
        completed_number = _stage_number(completed) if completed is not None else None
        if completed_number is not None and completed_number >= done_after:
            claims.append(f"handoff completed_stage {completed}")
        if handoff.get("next_stage") is None and completed is not None:
            claims.append("handoff workflow complete (next_stage null)")
    return claims


def resolve_canonical_target(ws: Path, pointer: str) -> Path:
    target = Path(str(pointer))
    return target if target.is_absolute() else ws / target


def check(ws: str | Path, *,
          done_after: float = DEFAULT_DONE_AFTER) -> tuple[dict, int]:
    ws = Path(ws)
    if not ws.is_dir():
        return usage_error(str(ws), CHECKER, f"workspace does not exist: {ws}")

    decls = read_declarations(ws)
    if decls["header"] is None and decls["handoff"] is None:
        return usage_error(
            str(ws), CHECKER,
            "neither a PIPELINE.md v0.4 header nor .pipeline/handoff.json "
            "was found — no canonical pointer declaration to validate",
        )

    claims = done_claims(decls["header"], decls["handoff"], done_after)
    pointer = decls["pointer"]
    pointer_is_null = is_null_pointer(pointer)

    hard: list[dict] = []
    warn: list[dict] = []
    target_rel = None
    if pointer_is_null and claims:
        hard.append({
            "code": "canonical_null_after_done",
            "msg": (
                "canonical pointer is missing/null while delivery stages "
                "claim done: " + "; ".join(claims)
            ),
            "at": decls["pointer_source"] or "PIPELINE.md",
        })
    if not pointer_is_null:
        target = resolve_canonical_target(ws, pointer)
        target_rel = str(pointer)
        if not target.exists():
            hard.append({
                "code": "canonical_target_missing",
                "msg": "canonical pointer names a nonexistent path — a "
                       "missing pinned target is a HARD error, never a "
                       "silent pass",
                "at": str(target),
            })

    verdict = verdict_skeleton(
        str(ws), CHECKER,
        hard=hard, warn=warn,
        extra={
            "canonical_output": None if pointer_is_null else str(pointer),
            "pointer_source": decls["pointer_source"],
            "target": target_rel,
            "done_claims": claims,
            "done_after": done_after,
        },
        counts={
            "hard": len(hard), "warn": len(warn),
            "done_claims": len(claims),
        },
    )
    return verdict, exit_code(hard=hard)


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="validate the workspace's canonical/FINAL output pointer"
    )
    parser.add_argument(
        "workspace", help="report workspace dir (.../workspaces/report-<slug>)"
    )
    parser.add_argument(
        "--done-after", type=float, default=DEFAULT_DONE_AFTER,
        help="stage id threshold from which a done claim requires the "
             f"canonical pointer (default {DEFAULT_DONE_AFTER})",
    )
    return cli_main(
        parser,
        lambda args: check(args.workspace, done_after=args.done_after),
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
