# -*- coding: utf-8 -*-
"""probe.py — one-shot capability probe for the rigorloom-hwp skill surface.

Merges three existing sources into ONE compact JSON document (W5.3; plan
§5.3 "one entry point built on render_probe + backend_precheck"):

  render          render_probe.probe() — Hancom COM / soffice / WSL /
                  H2Orestart / rhwp / certified renderer (machine state)
  modules         module_registry.ModuleRegistry().summary() — discovered +
                  enabled distribution modules, their CLI commands and run
                  modes (compacted: names only, no absolute script paths)
  backends        backend_precheck PATH/version checks — only when a real
                  backends config is present (RIGORLOOM_BACKENDS env or
                  --backends); the shipped example config is placeholders,
                  so absent config reports "unconfigured", never a fake ping

Designed for dynamic context injection: the skill's SKILL.md carries a
``!`python engine/scripts/probe.py --json` `` line, so the model sees live
capability state at skill load without re-deriving it. Output is therefore
COMPACT (single-line JSON) — every byte recurs in context each session.

Never raises: each source is individually guarded and degrades to an
``{"error": ...}`` stub. Exit 0 always (informational).

Layout resolution: works from the repo checkout (engine/scripts/ beside
pipeline/scripts/) and from a flattened skill install (all scripts in one
directory). RIGORLOOM_ROOT overrides the repo-root guess.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _candidate_script_dirs() -> list[Path]:
    """Places pipeline-core scripts may live, in preference order."""
    roots: list[Path] = []
    env_root = os.environ.get("RIGORLOOM_ROOT", "").strip()
    if env_root:
        roots.append(Path(env_root) / "pipeline" / "scripts")
    roots.append(_HERE.parents[1] / "pipeline" / "scripts")  # repo checkout
    roots.append(_HERE)                                      # flattened install
    return [r for r in roots if r.is_dir()]


for _dir in _candidate_script_dirs():
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))


def _render_summary() -> dict:
    try:
        import render_probe
        result = render_probe.probe()
        caps = result.get("capabilities", {})
        summary = {
            "hancom_com": caps.get("hancom_com"),
            "soffice": bool(caps.get("soffice_path")) or bool(caps.get("soffice_wsl")),
            "soffice_wsl": caps.get("soffice_wsl"),
            "h2orestart": caps.get("h2orestart"),
            "renderers": [r.get("name") for r in result.get("renderers", [])],
            "pdf_capable": render_probe.best_pdf_cmd(result) is not None,
        }
        if "render_certificate" in caps:
            summary["render_certificate_reason"] = caps.get(
                "render_certificate_reason")
        return summary
    except Exception as exc:  # degraded, never fatal
        return {"error": f"render_probe unavailable: {exc}"}


def _modules_summary() -> dict:
    try:
        from module_registry import ModuleError, ModuleRegistry
    except Exception as exc:
        return {"error": f"module_registry unavailable: {exc}"}
    # A flattened core-only install may have no modules/ dir at all — that is
    # the legitimate "nothing enabled" state, not an error.
    try:
        registry = ModuleRegistry()
        if not registry.modules_root.is_dir():
            return {"discovered": [], "enabled": [], "cli": [], "run_modes": []}
        full = registry.summary()
        return {
            "discovered": full["discovered"],
            "enabled": full["enabled"],
            "cli": sorted(entry["command"] for entry in full["cli"]),
            "run_modes": sorted(entry["name"] for entry in full["run_modes"]),
            "checkers": sorted(entry["name"] for entry in full["checkers"]),
        }
    except ModuleError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"module summary failed: {exc}"}


def _backends_summary(config: str | None) -> dict | str:
    path = config or os.environ.get("RIGORLOOM_BACKENDS", "").strip()
    if not path:
        return "unconfigured"
    try:
        import backend_precheck
        backends = backend_precheck.validate_backends(
            backend_precheck.load_backends(path))
        results = [backend_precheck.check_backend(be, live=False)
                   for be in backends]
        return {
            "config": path,
            "backends": [
                {"backend": r.get("backend"), "on_path": r.get("on_path"),
                 "live": r.get("live"), **({"note": r["note"]} if r.get("note") else {})}
                for r in results
            ],
        }
    except Exception as exc:
        return {"error": f"backend precheck failed: {exc}", "config": path}


def probe(backends_config: str | None = None) -> dict:
    return {
        "schema": "rigorloom-capability-probe/v1",
        "platform": sys.platform,
        "render": _render_summary(),
        "modules": _modules_summary(),
        "backends": _backends_summary(backends_config),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="rigorloom-hwp capability probe (render + modules + backends)")
    ap.add_argument("--json", action="store_true",
                    help="compact single-line JSON (default output is the same; "
                         "flag kept for the SKILL.md injection contract)")
    ap.add_argument("--pretty", action="store_true", help="indented JSON")
    ap.add_argument("--backends", default=None,
                    help="backends YAML/JSON config for backend_precheck "
                         "(default: RIGORLOOM_BACKENDS env; absent = 'unconfigured')")
    a = ap.parse_args(argv)
    result = probe(a.backends)
    if a.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
