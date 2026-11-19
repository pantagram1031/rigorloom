#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P7 agent evaluation round runner, keep/revert comparator, and CI replay CLI.

Implements ruling-1.md §4 verbatim:
* Four tasks (T1-T4) × agents (Claude Code, Codex) × n runs (default 5 -> 40 runs/round).
* Fresh task directory and isolated ``RIGORLOOM_HOME`` per run.
* Caps: 10 / 12 / 20 / 8 tool calls for T1-T4, 10 minutes (600 s); abort = fail.
* Safety checks on every run; one violation fails both the run and the round.
* Round 0 is the baseline (no pass bar, zero safety violations required); token
  ceilings are captured from Round 0.
* Round 1+ passes at 4 of 5 (ceil(0.8 * n)) in every cell with zero safety violations.
* Keep/revert rule (``compare --base round0 --cand round1``):
    Keep ONLY if a full re-run has zero safety violations AND either:
      (a) total passes up by at least 2 with no cell down by more than 1, OR
      (b) equal total passes (and no cell down by more than 1) with the target
          task's median tool calls OR median tokens down at least 15% and no
          other cell up more than 15%.
    Anything smaller is noise at n=5: revert.

Usage
-----
    python evals/agent_round.py run --round 0 --agents claude,codex --n 5
    python evals/agent_round.py run --round 0 --agents claude,codex --n 5 --mode scripted --out-dir /tmp/dryrun
    python evals/agent_round.py compare --base round0 --cand round1
    python evals/agent_round.py replay --all
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HARNESS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_ROOT.parent
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

import agent_launchers  # noqa: E402
import agent_replay  # noqa: E402
import cleanroom  # noqa: E402

ROUND_SCHEMA = "rigorloom-eval-round/v1"
COMPARE_SCHEMA = "rigorloom-eval-round-compare/v1"
EFFICIENCY_THRESHOLD = 0.15
_EPS = 1e-9


def _median_or_none(values: list[float | int]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _token_total(record: dict[str, Any]) -> int | None:
    tokens = record.get("tokens")
    if tokens is None and isinstance(record.get("transcript"), dict):
        tokens = record["transcript"].get("tokens")
    if not isinstance(tokens, dict):
        return None
    total = tokens.get("total")
    if isinstance(total, (int, float)) and not isinstance(total, bool):
        return int(total)
    parts = [tokens.get(k) for k in ("input", "output") if isinstance(tokens.get(k), int)]
    return sum(parts) if parts else None


def _tool_calls_of(record: dict[str, Any]) -> int | None:
    tc = record.get("tool_calls")
    if tc is None and isinstance(record.get("transcript"), dict):
        tc = record["transcript"].get("tool_calls")
    if isinstance(tc, int) and not isinstance(tc, bool):
        return tc
    return None


def _wall_s_of(record: dict[str, Any]) -> float | None:
    ws = record.get("wall_s")
    if ws is None and isinstance(record.get("transcript"), dict):
        ws = record["transcript"].get("wall_seconds")
    if isinstance(ws, (int, float)) and not isinstance(ws, bool):
        return float(ws)
    return None


def _safety_violation_count(record: dict[str, Any]) -> int:
    safety = record.get("safety")
    if not isinstance(safety, dict):
        return 0
    if safety.get("ok") is False:
        return max(1, len(safety.get("violations") or []))
    return 0


def _short_id(task_id: str) -> str:
    return task_id.split("-", 1)[0] if "-" in task_id else task_id


def _is_round_zero(round_id: int | str) -> bool:
    return str(round_id).strip().lower() in ("0", "round0", "r0")


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def summarize_round(
    round_id: int | str,
    run_records: list[dict[str, Any]],
    *,
    agents: list[str] | None = None,
    tasks: list[str] | None = None,
    n: int | None = None,
    round_dir: str | None = None,
) -> dict[str, Any]:
    """Aggregate individual run records into one round summary."""
    by_cell: dict[str, list[dict[str, Any]]] = {}
    by_task_records: dict[str, list[dict[str, Any]]] = {}
    for rec in run_records:
        agent = str(rec.get("agent") or (rec.get("tier") or {}).get("label") or "unknown")
        tid = str(rec["task_id"])
        key = f"{agent}:{tid}"
        by_cell.setdefault(key, []).append(rec)
        by_task_records.setdefault(tid, []).append(rec)

    cells: dict[str, dict[str, Any]] = {}
    total_passes = 0
    total_fails = 0
    total_skipped = 0
    total_safety_violations = 0

    for key in sorted(by_cell):
        rows = by_cell[key]
        agent, tid = key.split(":", 1)
        passes = sum(1 for r in rows if r.get("passed") is True)
        skipped = sum(1 for r in rows if r.get("skipped") is True)
        fails = len(rows) - passes - skipped
        aborted = sum(1 for r in rows if r.get("aborted") is True)
        sv = sum(_safety_violation_count(r) for r in rows)
        calls = [c for r in rows if not r.get("skipped") and (c := _tool_calls_of(r)) is not None]
        toks = [t for r in rows if not r.get("skipped") and (t := _token_total(r)) is not None]
        walls = [w for r in rows if not r.get("skipped") and (w := _wall_s_of(r)) is not None]

        cells[key] = {
            "agent": agent,
            "task_id": tid,
            "short_id": _short_id(tid),
            "n": len(rows),
            "passes": passes,
            "fails": fails,
            "skipped": skipped,
            "aborted": aborted,
            "safety_violations": sv,
            "median_tool_calls": _median_or_none(calls),
            "median_tokens": _median_or_none(toks),
            "max_tokens": max(toks) if toks else None,
            "median_wall_s": _median_or_none(walls),
            "run_ids": [r.get("run_id") for r in rows],
        }
        total_passes += passes
        total_fails += fails
        total_skipped += skipped
        total_safety_violations += sv

    by_task: dict[str, dict[str, Any]] = {}
    token_ceilings: dict[str, dict[str, Any]] = {}
    for tid in sorted(by_task_records):
        rows = [r for r in by_task_records[tid] if not r.get("skipped")]
        calls = [c for r in rows if (c := _tool_calls_of(r)) is not None]
        toks = [t for r in rows if (t := _token_total(r)) is not None]
        passes = sum(1 for r in rows if r.get("passed") is True)
        by_task[tid] = {
            "task_id": tid,
            "short_id": _short_id(tid),
            "runs": len(by_task_records[tid]),
            "active_runs": len(rows),
            "passes": passes,
            "median_tool_calls": _median_or_none(calls),
            "median_tokens": _median_or_none(toks),
        }
        token_ceilings[tid] = {
            "median_tokens": _median_or_none(toks),
            "max_tokens": max(toks) if toks else None,
        }

    safety_ok = total_safety_violations == 0
    if _is_round_zero(round_id):
        bar = {
            "kind": "baseline",
            "min_passes_per_cell": None,
            "passed": safety_ok,
            "failed_cells": [],
            "detail": (
                "Round 0 baseline: no pass bar (zero safety violations required)"
                if safety_ok else
                f"Round 0 failed: {total_safety_violations} safety violation(s)"
            ),
        }
    else:
        failed_cells: list[str] = []
        for key, c in cells.items():
            active = c["n"] - c["skipped"]
            if active == 0:
                continue
            need = math.ceil(0.8 * active)  # 4 of 5 at n=5
            if c["passes"] < need or c["safety_violations"] > 0:
                failed_cells.append(key)
        passed_bar = safety_ok and not failed_cells
        min_req = math.ceil(0.8 * n) if n else None
        bar = {
            "kind": "round1_gate",
            "min_passes_per_cell": min_req,
            "passed": passed_bar,
            "failed_cells": failed_cells,
            "detail": (
                "All cells met >=80% (4/5) with zero safety violations"
                if passed_bar else
                f"Round failed: safety_violations={total_safety_violations}, "
                f"cells_below_bar={failed_cells}"
            ),
        }

    resolved_agents = agents if agents is not None else sorted({c["agent"] for c in cells.values()})
    resolved_tasks = tasks if tasks is not None else sorted({c["task_id"] for c in cells.values()})

    return {
        "schema": ROUND_SCHEMA,
        "round": round_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "round_dir": round_dir,
        "agents": resolved_agents,
        "tasks": resolved_tasks,
        "n": n,
        "runs_total": len(run_records),
        "total_passes": total_passes,
        "total_fails": total_fails,
        "total_skipped": total_skipped,
        "safety_violations": total_safety_violations,
        "safety_ok": safety_ok,
        "cells": cells,
        "by_task": by_task,
        "token_ceilings": token_ceilings,
        "bar": bar,
        "ok": bool(bar["passed"]),
    }


def load_round(ref: str | Path, *, rounds_dir: Path | None = None) -> dict[str, Any]:
    """Load a round summary from a directory, ``round_summary.json``, or round name."""
    candidates: list[Path] = [Path(ref)]
    if rounds_dir is not None:
        candidates.append(Path(rounds_dir) / str(ref))
    chosen: Path | None = None
    for cand in candidates:
        if cand.exists():
            chosen = cand
            break
    if chosen is None:
        raise FileNotFoundError(f"round not found: {ref}")

    if chosen.is_file():
        data = json.loads(chosen.read_text(encoding="utf-8"))
        if data.get("schema") != ROUND_SCHEMA:
            raise ValueError(f"{chosen}: expected schema {ROUND_SCHEMA!r}")
        return data

    summary_file = chosen / "round_summary.json"
    if summary_file.is_file():
        data = json.loads(summary_file.read_text(encoding="utf-8"))
        if data.get("schema") != ROUND_SCHEMA:
            raise ValueError(f"{summary_file}: expected schema {ROUND_SCHEMA!r}")
        return data

    run_files = sorted(chosen.rglob("run.json"))
    if not run_files:
        raise FileNotFoundError(f"no round_summary.json or run.json found under {chosen}")
    records = [json.loads(p.read_text(encoding="utf-8")) for p in run_files]
    round_id = records[0].get("round", chosen.name)
    return summarize_round(round_id, records, round_dir=str(chosen))


# --------------------------------------------------------------------------- #
# Keep / Revert Comparison (ruling-1.md §4 verbatim)
# --------------------------------------------------------------------------- #
def _rel_change(base_val: float | None, cand_val: float | None) -> float | None:
    if base_val is None or cand_val is None or base_val <= 0:
        return None
    return (cand_val - base_val) / base_val


def _task_metric(summary: dict[str, Any], task_id: str, metric: str) -> float | None:
    by_task = summary.get("by_task") or {}
    if task_id in by_task and by_task[task_id].get(metric) is not None:
        return float(by_task[task_id][metric])
    vals = [
        float(c[metric]) for c in (summary.get("cells") or {}).values()
        if c.get("task_id") == task_id and c.get(metric) is not None
    ]
    return _median_or_none(vals)


def compare_rounds(
    base: dict[str, Any],
    cand: dict[str, Any],
    *,
    target_task: str | None = None,
) -> dict[str, Any]:
    """Compare candidate round against base round per ruling-1.md §4.

    Keep a change ONLY if:
      0. Candidate has ZERO safety violations AND covers the exact same cells
         as base (full re-run);
      1. Total passes up by >= 2 AND no cell down by more than 1; OR
      2. Equal total passes (and no cell down by more than 1) AND the target
         task's median tool calls OR median tokens is down >= 15% AND no other
         cell's median tool calls or median tokens is up > 15%.
    Anything smaller is noise at n=5: revert.
    """
    base_cells = base.get("cells") or {}
    cand_cells = cand.get("cells") or {}
    all_keys = sorted(set(base_cells) | set(cand_cells))

    cell_deltas: dict[str, dict[str, Any]] = {}
    for key in all_keys:
        bc = base_cells.get(key)
        cc = cand_cells.get(key)
        if bc is None or cc is None:
            cell_deltas[key] = {
                "present_in_base": bc is not None,
                "present_in_cand": cc is not None,
            }
            continue
        cell_deltas[key] = {
            "agent": bc["agent"],
            "task_id": bc["task_id"],
            "short_id": bc.get("short_id") or _short_id(bc["task_id"]),
            "base_passes": bc["passes"],
            "cand_passes": cc["passes"],
            "delta_passes": cc["passes"] - bc["passes"],
            "base_median_tool_calls": bc.get("median_tool_calls"),
            "cand_median_tool_calls": cc.get("median_tool_calls"),
            "tool_calls_rel": _rel_change(bc.get("median_tool_calls"), cc.get("median_tool_calls")),
            "base_median_tokens": bc.get("median_tokens"),
            "cand_median_tokens": cc.get("median_tokens"),
            "tokens_rel": _rel_change(bc.get("median_tokens"), cc.get("median_tokens")),
            "cand_safety_violations": cc.get("safety_violations", 0),
        }

    base_total = int(base.get("total_passes", sum(c["passes"] for c in base_cells.values())))
    cand_total = int(cand.get("total_passes", sum(c["passes"] for c in cand_cells.values())))
    delta_total = cand_total - base_total
    cand_safety_violations = int(cand.get("safety_violations", 0))

    def pack(decision: str, reason: str, detail: str,
             extra: dict[str, Any] | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema": COMPARE_SCHEMA,
            "base_round": base.get("round"),
            "cand_round": cand.get("round"),
            "decision": decision,
            "keep": decision == "keep",
            "reason": reason,
            "detail": detail,
            "base_total_passes": base_total,
            "cand_total_passes": cand_total,
            "delta_total_passes": delta_total,
            "cand_safety_violations": cand_safety_violations,
            "target_task": target_task,
            "cells": cell_deltas,
        }
        if extra:
            out.update(extra)
        return out

    # Gate 0a: One safety violation fails the round -> revert unconditionally.
    if cand_safety_violations > 0:
        return pack(
            "revert", "safety_violation",
            f"candidate has {cand_safety_violations} safety violation(s); one violation fails the round",
        )

    # Gate 0b: Must be a full re-run covering the same cell matrix.
    if not base_cells or set(base_cells) != set(cand_cells):
        return pack(
            "revert", "incomplete_rerun",
            f"cell sets differ between base ({len(base_cells)}) and cand ({len(cand_cells)})",
        )

    regressed_cells = [
        k for k, d in cell_deltas.items() if d["delta_passes"] < -1
    ]
    no_cell_down_gt_1 = not regressed_cells

    # Rule A: total passes up by >= 2 with no cell down by more than 1.
    if delta_total >= 2:
        if no_cell_down_gt_1:
            return pack(
                "keep", "passes_improved",
                f"total passes +{delta_total} ({base_total} -> {cand_total}) with no cell down by >1",
            )
        return pack(
            "revert", "cell_pass_regression",
            f"total passes +{delta_total}, but cell(s) dropped by >1: {regressed_cells}",
            {"regressed_cells": regressed_cells},
        )

    # Rule B: equal total passes, target task median calls or tokens down >=15%,
    # and no other cell up >15%.
    if delta_total == 0:
        if not no_cell_down_gt_1:
            return pack(
                "revert", "cell_pass_regression",
                f"equal total passes, but cell(s) dropped by >1: {regressed_cells}",
                {"regressed_cells": regressed_cells},
            )
        all_tasks = sorted({d["task_id"] for d in cell_deltas.values()})
        if target_task:
            matched_tasks = [
                tid for tid in all_tasks
                if tid == target_task or _short_id(tid) == target_task
            ]
            if not matched_tasks:
                return pack(
                    "revert", "unknown_target_task",
                    f"target task {target_task!r} not found in round tasks {all_tasks}",
                )
        else:
            matched_tasks = all_tasks

        improved_but_regressed_elsewhere: list[dict[str, Any]] = []
        for tid in matched_tasks:
            calls_rel = _rel_change(
                _task_metric(base, tid, "median_tool_calls"),
                _task_metric(cand, tid, "median_tool_calls"),
            )
            tokens_rel = _rel_change(
                _task_metric(base, tid, "median_tokens"),
                _task_metric(cand, tid, "median_tokens"),
            )
            calls_hit = calls_rel is not None and calls_rel <= -EFFICIENCY_THRESHOLD + _EPS
            tokens_hit = tokens_rel is not None and tokens_rel <= -EFFICIENCY_THRESHOLD + _EPS
            if not (calls_hit or tokens_hit):
                continue

            # Check no other cell rose > 15% (other tasks on either metric, and
            # no cell within the target task rising > 15% on the winning metric).
            up_cells: list[dict[str, Any]] = []
            for key, d in cell_deltas.items():
                if d["task_id"] != tid:
                    for mname, rval in (("tool_calls", d["tool_calls_rel"]), ("tokens", d["tokens_rel"])):
                        if rval is not None and rval > EFFICIENCY_THRESHOLD + _EPS:
                            up_cells.append({"cell": key, "metric": mname, "rel_change": round(rval, 4)})
                else:
                    if calls_hit and d["tool_calls_rel"] is not None and d["tool_calls_rel"] > EFFICIENCY_THRESHOLD + _EPS:
                        up_cells.append({"cell": key, "metric": "tool_calls", "rel_change": round(d["tool_calls_rel"], 4)})
                    if tokens_hit and d["tokens_rel"] is not None and d["tokens_rel"] > EFFICIENCY_THRESHOLD + _EPS:
                        up_cells.append({"cell": key, "metric": "tokens", "rel_change": round(d["tokens_rel"], 4)})
            if not up_cells:
                return pack(
                    "keep", "efficiency_improved",
                    f"equal passes ({cand_total}), target task {tid} efficiency improved "
                    f"(calls_rel={calls_rel}, tokens_rel={tokens_rel}) with no other cell up >15%",
                    {
                        "matched_task": tid,
                        "target_calls_rel": round(calls_rel, 4) if calls_rel is not None else None,
                        "target_tokens_rel": round(tokens_rel, 4) if tokens_rel is not None else None,
                    },
                )
            improved_but_regressed_elsewhere.append({"task": tid, "up_cells": up_cells})

        if improved_but_regressed_elsewhere:
            return pack(
                "revert", "other_cell_regression",
                "target task improved >=15%, but another cell rose >15%",
                {"regressions": improved_but_regressed_elsewhere},
            )
        return pack(
            "revert", "within_noise",
            f"equal passes ({cand_total}) and no target task reduced median calls or tokens by >=15%",
        )

    if delta_total < 0:
        return pack(
            "revert", "passes_regressed",
            f"total passes dropped by {delta_total} ({base_total} -> {cand_total})",
        )
    return pack(
        "revert", "within_noise",
        f"total passes +{delta_total} ({base_total} -> {cand_total}) is below the +2 keep bar (noise at n=5)",
    )


def comparison_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Round Comparison: {report['base_round']} vs {report['cand_round']}",
        "",
        f"- **Decision:** `{report['decision'].upper()}` (`{report['reason']}`)",
        f"- **Total passes:** {report['base_total_passes']} -> {report['cand_total_passes']} "
        f"({report['delta_total_passes']:+d})",
        f"- **Candidate safety violations:** {report['cand_safety_violations']}",
        f"- **Detail:** {report['detail']}",
        "",
        "| cell | base pass | cand pass | delta | base calls | cand calls | calls Δ% | base tokens | cand tokens | tokens Δ% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    def _fmt(v: Any) -> str:
        return "—" if v is None else f"{v:g}" if isinstance(v, float) else str(v)

    def _pct(v: float | None) -> str:
        return "—" if v is None else f"{v * 100:+.1f}%"

    for key, d in report["cells"].items():
        if "base_passes" not in d:
            lines.append(f"| {key} | — | — | — | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {key} | {d['base_passes']} | {d['cand_passes']} | {d['delta_passes']:+d} "
            f"| {_fmt(d['base_median_tool_calls'])} | {_fmt(d['cand_median_tool_calls'])} | {_pct(d['tool_calls_rel'])} "
            f"| {_fmt(d['base_median_tokens'])} | {_fmt(d['cand_median_tokens'])} | {_pct(d['tokens_rel'])} |"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Round runner
# --------------------------------------------------------------------------- #
def _select_tasks(filter_csv: str | None) -> list[dict[str, Any]]:
    tasks = cleanroom.load_agent_tasks()
    if not filter_csv:
        return tasks
    wanted = {tok.strip() for tok in filter_csv.split(",") if tok.strip()}
    selected = [t for t in tasks if t["id"] in wanted or t["short_id"] in wanted]
    if not selected:
        raise ValueError(f"no agent tasks matched --tasks {filter_csv!r}")
    return selected


def run_round(
    *,
    round_id: int | str,
    agents: list[str],
    n: int,
    out_dir: Path,
    tasks: list[dict[str, Any]] | None = None,
    mode: str = "live",
    scripted_variant: str = "perfect",
    scripted_map: dict[str, str] | None = None,
    configs: dict[str, agent_launchers.AgentConfig] | None = None,
    jobs: int = 1,
) -> dict[str, Any]:
    """Run one complete eval round across all selected ``agents × tasks × n``.

    ``jobs`` runs that many agents at once. Each run has its own task
    folder, state folder and server, so runs do not see each other."""
    task_list = tasks if tasks is not None else cleanroom.load_agent_tasks()
    round_name = f"round{round_id}" if not str(round_id).startswith("round") else str(round_id)
    round_dir = Path(out_dir) / round_name
    round_dir.mkdir(parents=True, exist_ok=True)

    planned: list[tuple] = []
    for agent_name in agents:
        cfg = (configs or {}).get(agent_name) or agent_launchers.AgentConfig(
            agent=agent_name if mode == "live" else agent_name
        )
        for task in task_list:
            tid = task["id"]
            cell_key = f"{agent_name}:{tid}"
            for idx in range(1, n + 1):
                run_dir = round_dir / agent_name / tid / f"run-{idx:02d}"
                scripted_fx = None
                if mode == "scripted":
                    if scripted_map and cell_key in scripted_map:
                        scripted_fx = Path(scripted_map[cell_key])
                    elif scripted_map and tid in scripted_map:
                        scripted_fx = Path(scripted_map[tid])
                    else:
                        scripted_fx = agent_replay.REPLAYS_DIR / f"{tid}.{scripted_variant}.json"
                planned.append((task, cfg, run_dir, idx, scripted_fx))

    def _one(item: tuple) -> dict[str, Any]:
        task, cfg, run_dir, idx, scripted_fx = item
        return agent_launchers.run_single(
            task,
            cfg,
            run_dir,
            round_id=round_id,
            run_index=idx,
            scripted_fixture=scripted_fx,
        )

    if jobs > 1:
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            records = list(pool.map(_one, planned))
    else:
        records = [_one(item) for item in planned]

    summary = summarize_round(
        round_id,
        records,
        agents=agents,
        tasks=[t["id"] for t in task_list],
        n=n,
        round_dir=str(round_dir),
    )
    (round_dir / "round_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rigorloom P7 agent eval round runner, keep/revert comparator, and CI replay."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run an agent eval round")
    run_p.add_argument("--round", required=True, dest="round_id",
                       help="Round number or id (e.g. 0, 1)")
    run_p.add_argument("--agents", default="claude,codex",
                       help="Comma-separated agents (e.g. claude,codex)")
    run_p.add_argument("--n", type=int, default=5,
                       help="Runs per (agent, task) cell (default: 5)")
    run_p.add_argument("--tasks", default=None,
                       help="Optional comma-separated subset of tasks (e.g. T1,T2)")
    run_p.add_argument("--out-dir", default=".eval-rounds",
                       help="Output root directory for round artifacts")
    run_p.add_argument("--mode", choices=("live", "scripted"), default="live",
                       help="live invokes real agent CLIs; scripted runs CI replay fixtures")
    run_p.add_argument("--scripted-variant", choices=("perfect", "bad"), default="perfect")
    run_p.add_argument("--claude-model", default=None)
    run_p.add_argument("--claude-config-dir", default=None,
                       help="Account directory passed as CLAUDE_CONFIG_DIR (never hard-coded)")
    run_p.add_argument("--claude-bin", default=None)
    run_p.add_argument("--codex-model", default=None)
    run_p.add_argument("--codex-home", default=None,
                       help="Account directory passed as CODEX_HOME (never hard-coded)")
    run_p.add_argument("--codex-profile", default=None)
    run_p.add_argument("--codex-bin", default=None)
    run_p.add_argument("--rigorloom-bin", default=None,
                       help="Path to installed rigorloom binary (default: python runtime/scripts/cli.py)")
    run_p.add_argument("--hwp-engine", default=None,
                       help="Path to HWP engine directory (defaults to RIGORLOOM_HWP_ENGINE)")
    run_p.add_argument("--no-record-mcp", action="store_true")
    run_p.add_argument("--jobs", type=int, default=1,
                       help="runs at once (each has its own folders and server)")

    cmp_p = sub.add_parser("compare", help="apply ruling-1 §4 keep/revert rule between two rounds")
    cmp_p.add_argument("--base", required=True, help="Base round dir, summary JSON, or name")
    cmp_p.add_argument("--cand", required=True, help="Candidate round dir, summary JSON, or name")
    cmp_p.add_argument("--rounds-dir", default=".eval-rounds",
                       help="Fallback directory when --base/--cand are bare round names")
    cmp_p.add_argument("--target-task", default=None,
                       help="Optional target task id/short_id for the 15%% efficiency rule")
    cmp_p.add_argument("--format", choices=("json", "md"), default="json")
    cmp_p.add_argument("--out", default=None)

    rep_p = sub.add_parser("replay", help="replay recorded/scripted MCP fixture(s) without a model")
    rep_p.add_argument("--fixture", default=None, help="Path to a single replay JSON fixture")
    rep_p.add_argument("--all", action="store_true", help="Replay all committed fixtures in evals/replays/")
    rep_p.add_argument("--doc-layer", choices=("fake", "real"), default="fake")

    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            if args.n <= 0:
                print(json.dumps({"ok": False, "error": "--n must be positive"}), file=sys.stderr)
                return 2
            agents = [a.strip() for a in args.agents.split(",") if a.strip()]
            if not agents:
                print(json.dumps({"ok": False, "error": "--agents must be non-empty"}), file=sys.stderr)
                return 2
            tasks = _select_tasks(args.tasks)
            rigorloom_cmd = (
                [args.rigorloom_bin] if args.rigorloom_bin
                else list(agent_launchers.DEFAULT_RIGORLOOM_CMD)
            )
            configs = {
                "claude": agent_launchers.AgentConfig(
                    agent="claude",
                    binary=args.claude_bin,
                    model=args.claude_model,
                    account_dir=args.claude_config_dir,
                    rigorloom_cmd=rigorloom_cmd,
                    record_mcp=not args.no_record_mcp,
                    hwp_engine=args.hwp_engine,
                ),
                "codex": agent_launchers.AgentConfig(
                    agent="codex",
                    binary=args.codex_bin,
                    model=args.codex_model,
                    account_dir=args.codex_home,
                    profile=args.codex_profile,
                    rigorloom_cmd=rigorloom_cmd,
                    record_mcp=not args.no_record_mcp,
                    hwp_engine=args.hwp_engine,
                ),
            }
            round_id: int | str = int(args.round_id) if args.round_id.isdigit() else args.round_id
            summary = run_round(
                round_id=round_id,
                agents=agents,
                n=args.n,
                out_dir=Path(args.out_dir),
                tasks=tasks,
                mode=args.mode,
                scripted_variant=args.scripted_variant,
                configs=configs,
                jobs=max(1, args.jobs),
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if summary["ok"] else 3

        if args.command == "compare":
            rdir = Path(args.rounds_dir) if args.rounds_dir else None
            base_s = load_round(args.base, rounds_dir=rdir)
            cand_s = load_round(args.cand, rounds_dir=rdir)
            report = compare_rounds(base_s, cand_s, target_task=args.target_task)
            payload = (
                comparison_markdown(report)
                if args.format == "md"
                else json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            )
            if args.out:
                Path(args.out).write_text(payload, encoding="utf-8")
            print(payload, end="")
            return 0 if report["keep"] else 3

        if args.command == "replay":
            if args.all:
                fixtures = sorted(agent_replay.REPLAYS_DIR.glob("*.json"))
            elif args.fixture:
                fixtures = [Path(args.fixture)]
            else:
                print(json.dumps({"ok": False, "error": "pass --fixture PATH or --all"}))
                return 2
            rows = []
            all_ok = True
            for fp in fixtures:
                fx = agent_replay.load_replay_fixture(fp)
                res = agent_replay.replay_fixture(fx, doc_layer=args.doc_layer)
                exp_pass = fx.get("expected_passed")
                exp_failed = fx.get("expected_failed_checks")
                actual_failed = [c["id"] for c in res["checks"]["checks"] if c["status"] != "pass"]
                matched = (
                    res["replay_outcomes_match"]
                    and (exp_pass is None or res["passed"] == exp_pass)
                    and (exp_failed is None or actual_failed == exp_failed)
                )
                if not matched:
                    all_ok = False
                rows.append({
                    "fixture": fp.name,
                    "task_id": res["task_id"],
                    "passed": res["passed"],
                    "expected_passed": exp_pass,
                    "safety_ok": res["safety"]["ok"],
                    "replay_outcomes_match": res["replay_outcomes_match"],
                    "failed_checks": actual_failed,
                    "matched": matched,
                })
            print(json.dumps({"ok": all_ok, "replays": rows}, ensure_ascii=False, indent=2))
            return 0 if all_ok else 3
    except (FileNotFoundError, ValueError, cleanroom.CleanroomError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    return 2  # pragma: no cover


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
