# -*- coding: utf-8 -*-
"""doc_backend.py — pluggable document-backend dispatcher for Stage 5.

Usage:
    python pipeline/scripts/doc_backend.py <WS> [--backend bundle|docx|hwpx|hwp]
                                                [--out-dir <path>]

Backend resolution (first hit wins):
    1. explicit  --backend  flag
    2. build.yaml `doc_backend:` key (minimal line-scan; <WS>/build.yaml)
    3. default   "bundle"

Backends:
    bundle  zero-dependency deliverable (frozen bundle + stdlib HTML preview).
            Always available. Dispatches to pipeline/adapters_impl/bundle_backend.
    docx    optional python-docx render (`pip install python-docx`).
            Dispatches to pipeline/adapters_impl/docx_backend.
    hwpx    EXTERNAL adapter (hwp-master XML engine, any OS). Resolved through
            HWP_MASTER_SCRIPTS and dispatched to fill_report.py --engine xml.
    hwp     EXTERNAL adapter (hwp-master, Windows + Hancom). Not implemented
            here — prints the pointer instruction and exits 4.

Exit codes:
    0  success
    2  usage / bundle floor missing
    3  unknown backend
    4  requested external adapter unavailable — see printed pointer
    5  docx backend requested but python-docx not installed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))          # pipeline/scripts
_PIPELINE_DIR = os.path.dirname(_HERE)                        # pipeline
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from adapters_impl import read_build_yaml_key  # noqa: E402
import rhwp_proof  # noqa: E402

_HWP_POINTER = (
    "hwp backend is an EXTERNAL adapter (Windows + Hancom + hwp-master).\n"
    "It is not implemented in this repo. Run the hwp-master assembly loop:\n"
    "  python <HWP_MASTER_ROOT>/scripts/fill_report.py --loop \\\n"
    "    --form <WS>/output/form_copy.hwpx \\\n"
    "    --content <WS>/bundle/content.md --out-dir <WS>/output \\\n"
    "    --build-yaml <WS>/build.yaml --baseline <WS>/form_baseline.json \\\n"
    "    --form-profile <WS>/form_profile.json --proof --max-proof-iters 3\n"
    "See adapters/hwp/README.md (clone hwp-master beside this repo or set "
    "HWP_MASTER_ROOT)."
)

_HWPX_POINTER = (
    "hwpx backend is an EXTERNAL adapter (hwp-master XML engine; no Hancom/COM).\n"
    "Set HWP_MASTER_SCRIPTS to the hwp-master scripts directory containing\n"
    "fill_report.py, eqn.py, and xml_backend.py, then rerun this command.\n"
    "(All three files must be present — this is a misconfiguration guard, not\n"
    "a security check; HWP_MASTER_SCRIPTS is operator-trusted config.)\n"
    "The dispatcher will invoke:\n"
    "  python <HWP_MASTER_SCRIPTS>/fill_report.py --engine xml \\\n"
    "    --form <WS>/output/form_copy.hwpx \\\n"
    "    --content <WS>/bundle/content.md --out-dir <WS>/output"
)

# HWP_MASTER_SCRIPTS is operator-trusted config, not attacker input. This
# marker check just catches misconfiguration (e.g. the env var pointing at
# the wrong directory) — it is not a security boundary.
_HWP_MASTER_MARKERS = ("fill_report.py", "eqn.py", "xml_backend.py")
_CONTENT_EQ_RE = re.compile(r"\[\[\s*EQ\b", re.IGNORECASE)
_XML_EQ_RE = re.compile(br"<(?:[A-Za-z_][\w.-]*:)?equation\b", re.IGNORECASE)


def _resolve_hwpx_fill_report() -> str | None:
    scripts = os.environ.get("HWP_MASTER_SCRIPTS", "").strip()
    if not scripts:
        return None
    base = os.path.abspath(os.path.expanduser(scripts))
    if not all(os.path.isfile(os.path.join(base, marker))
               for marker in _HWP_MASTER_MARKERS):
        return None
    return os.path.join(base, "fill_report.py")


def _workspace_has_equations(ws: str, target: str, render_probe) -> bool:
    """Detect equation content before or after HWPX assembly."""
    if render_probe.hwpx_has_equations(target):
        return True

    content = os.path.join(ws, "bundle", "content.md")
    with open(content, encoding="utf-8") as stream:
        if _CONTENT_EQ_RE.search(stream.read()):
            return True

    form_copy = os.path.join(ws, "output", "form_copy.hwpx")
    if render_probe.hwpx_has_equations(form_copy):
        return True

    for directory, dirnames, filenames in os.walk(ws, followlinks=False):
        dirnames[:] = [name for name in dirnames
                       if not os.path.islink(os.path.join(directory, name))]
        for filename in filenames:
            if not (filename.lower().startswith("section")
                    and filename.lower().endswith(".xml")):
                continue
            with open(os.path.join(directory, filename), "rb") as stream:
                if _XML_EQ_RE.search(stream.read()):
                    return True
    return False


def _hwpx_renderer_decision(ws: str, out_dir: str | None) -> dict:
    """Choose proof routing for this workspace's assembled HWPX.

    Hancom stays on fill_report's native route (no external ``--pdf-cmd``).
    Soffice is external advisory proof and is unsafe for equation documents.
    """
    target = os.path.join(out_dir or os.path.join(ws, "output"), "out.hwpx")
    try:
        import render_probe
        result = render_probe.probe()
        has_equations = _workspace_has_equations(ws, target, render_probe)
    except Exception:
        return {
            "target": target, "equations": None, "available": [],
            "selected": None, "proof_grade": "none",
            "reason": "renderer_probe_failed", "pdf_cmd_argv": None,
        }

    renderers = result.get("renderers", [])
    available = [renderer.get("name") for renderer in renderers
                 if renderer.get("name")]
    capabilities = result.get("capabilities", {})
    hancom_available = bool(capabilities.get("hancom_com")) or "hancom" in available
    if hancom_available:
        return {
            "target": target, "equations": has_equations,
            "available": available, "selected": "hancom",
            "proof_grade": "hancom", "reason": "hancom_com_available",
            "pdf_cmd_argv": None,
        }

    rhwp_renderer = next(
        (renderer for renderer in renderers
         if renderer.get("name") == "rhwp_svg" and renderer.get("argv")),
        None,
    )
    soffice = next(
        (renderer for renderer in renderers
         if renderer.get("name") in {"soffice_local", "soffice_wsl"}
         and renderer.get("argv")),
        None,
    )
    if rhwp_renderer is not None and (has_equations or soffice is None):
        return {
            "target": target,
            "equations": has_equations,
            "available": available,
            "selected": "rhwp_svg",
            "proof_grade": "experimental-rhwp",
            "reason": "experimental_rhwp_available",
            "pdf_cmd_argv": None,
            "rhwp_renderer": dict(rhwp_renderer),
        }
    if soffice is None:
        return {
            "target": target, "equations": has_equations,
            "available": available, "selected": None,
            "proof_grade": "none", "reason": "renderer_unavailable",
            "pdf_cmd_argv": None,
        }
    if has_equations:
        return {
            "target": target, "equations": True, "available": available,
            "selected": None, "proof_grade": "none",
            "reason": "renderer_cannot_eqn", "pdf_cmd_argv": None,
        }
    return {
        "target": target, "equations": False, "available": available,
        "selected": soffice["name"], "proof_grade": "advisory",
        "reason": "equation_free", "pdf_cmd_argv": list(soffice["argv"]),
    }


def _fill_report_help(fill_report: str) -> str:
    """Return bounded fill_report help output, or an empty string."""
    try:
        proc = subprocess.run(
            [sys.executable, fill_report, "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "") + (proc.stderr or "")


def _public_renderer_decision(decision: dict) -> dict:
    return {key: value for key, value in decision.items()
            if key not in {"pdf_cmd_argv", "rhwp_renderer"}}


def _render_proof_summary(receipt: dict) -> dict:
    return {
        "ok": receipt.get("ok") is True,
        "proof_grade": receipt.get("proof_grade", "none"),
        "submission_grade": False,
        "page_count": receipt.get("page_count", 0),
        "layout_overflow": receipt.get("layout_overflow"),
        "parity_verdict": receipt.get("parity_verdict", "fail"),
        "reason": receipt.get("reason"),
        "comparison": receipt.get("comparison", {}),
    }


def _emit_hwpx_result(completed, decision: dict, proof_receipt: dict | None = None) -> None:
    """Emit one JSON object while preserving a JSON adapter result's fields."""
    raw = completed.stdout or ""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("adapter result is not an object")
    except (json.JSONDecodeError, ValueError):
        payload = {
            "ok": completed.returncode == 0,
            "backend": "hwpx",
            "adapter_stdout": raw,
        }

    payload["renderer_decision"] = _public_renderer_decision(decision)
    if proof_receipt is not None:
        payload["render_proof"] = _render_proof_summary(proof_receipt)
    if completed.returncode == 0:
        payload["proof_grade"] = decision["proof_grade"]
        if (decision["reason"] == "renderer_cannot_eqn"
                or proof_receipt is not None):
            payload["reason"] = decision["reason"]
        else:
            payload.setdefault("reason", decision["reason"])
    print(json.dumps(payload, ensure_ascii=False))


def _rhwp_timeout() -> float:
    raw = os.environ.get("RIGORLOOM_RHWP_TIMEOUT", "").strip()
    if not raw:
        return rhwp_proof.DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return rhwp_proof.DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else rhwp_proof.DEFAULT_TIMEOUT_SECONDS


def _rhwp_comparison() -> dict | None:
    configured = os.environ.get("RIGORLOOM_RHWP_COMPARISON_JSON", "").strip()
    if not configured:
        return None
    try:
        with open(configured, encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _run_experimental_rhwp(
    ws: str,
    out_dir: str | None,
    decision: dict,
) -> dict:
    output = out_dir or os.path.join(ws, "output")
    return rhwp_proof.run_workspace_proof(
        output,
        decision["rhwp_renderer"],
        timeout=_rhwp_timeout(),
        comparison=_rhwp_comparison(),
    )


def _run_hwpx_adapter(ws: str, out_dir: str | None) -> int:
    fill_report = _resolve_hwpx_fill_report()
    if fill_report is None:
        print(_HWPX_POINTER, file=sys.stderr)
        print(json.dumps({"ok": False, "backend": "hwpx", "external": True,
                          "reason": "hwp-master XML adapter unavailable"}))
        return 4

    command = [
        sys.executable, fill_report,
        "--engine", "xml",
        "--form", os.path.join(ws, "output", "form_copy.hwpx"),
        "--content", os.path.join(ws, "bundle", "content.md"),
        "--out-dir", out_dir or os.path.join(ws, "output"),
    ]

    decision = _hwpx_renderer_decision(ws, out_dir)
    help_text = _fill_report_help(fill_report)
    pdf_cmd_argv = decision["pdf_cmd_argv"]
    if pdf_cmd_argv and "--pdf-cmd" in help_text:
        command += ["--pdf-cmd", shlex.join(pdf_cmd_argv)]
    elif pdf_cmd_argv:
        decision.update({
            "selected": None,
            "proof_grade": "none",
            "reason": "fill_report_pdf_cmd_unsupported",
            "pdf_cmd_argv": None,
        })

    if decision["proof_grade"] == "none":
        reason_flag = next(
            (flag for flag in ("--proof-reason", "--no-proof-reason")
             if flag in help_text),
            None,
        )
        if reason_flag:
            command += [reason_flag, decision["reason"]]

    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"failed to launch hwp-master XML adapter: {exc}", file=sys.stderr)
        print(json.dumps({"ok": False, "backend": "hwpx", "external": True,
                          "reason": "failed to launch hwp-master XML adapter"}))
        return 4
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    proof_receipt = None
    if completed.returncode == 0 and decision.get("selected") == "rhwp_svg":
        try:
            proof_receipt = _run_experimental_rhwp(ws, out_dir, decision)
        except Exception as exc:
            proof_receipt = {
                "ok": False,
                "proof_grade": "none",
                "submission_grade": False,
                "page_count": 0,
                "layout_overflow": None,
                "parity_verdict": "fail",
                "reason": "rhwp_proof_failed",
                "error": str(exc),
                "comparison": {},
            }
        if proof_receipt.get("ok") is True:
            decision["proof_grade"] = "experimental-rhwp"
            decision["reason"] = "rhwp_svg_rendered"
        else:
            decision["proof_grade"] = "none"
            decision["reason"] = proof_receipt.get("reason", "rhwp_proof_failed")
            decision["fallback"] = "canonical_hwpx_without_render_proof"
    _emit_hwpx_result(completed, decision, proof_receipt)
    return completed.returncode


def resolve_backend(ws: str, flag: str | None) -> str:
    if flag:
        return flag
    yaml_val = read_build_yaml_key(os.path.join(ws, "build.yaml"), "doc_backend")
    if yaml_val:
        return yaml_val
    return "bundle"


def main(argv=None):
    ap = argparse.ArgumentParser(description="pluggable document-backend dispatcher")
    ap.add_argument("workspace", help="report workspace dir (…/workspaces/report-<slug>)")
    ap.add_argument("--backend", choices=["bundle", "docx", "hwpx", "hwp"], default=None,
                    help="override build.yaml doc_backend (default: bundle)")
    ap.add_argument("--out-dir", default=None,
                    help="output dir (default: <WS>/output/deliverable for bundle, "
                         "<WS>/output for docx/hwpx)")
    a = ap.parse_args(argv)

    ws = a.workspace
    if not os.path.isdir(ws):
        print(json.dumps({"ok": False, "error": f"workspace not found: {ws}"}), file=sys.stderr)
        return 2

    backend = resolve_backend(ws, a.backend)

    # --out-dir containment: deliverables only ever land inside the workspace's
    # output/ tree (the bundle backend deletes-and-recreates figure dirs at the
    # target, so an arbitrary path here would be destructive).
    if a.out_dir is not None:
        out_real = os.path.realpath(a.out_dir)
        allowed = os.path.realpath(os.path.join(ws, "output"))
        try:
            contained = os.path.commonpath([allowed, out_real]) == allowed
        except ValueError:  # different drives
            contained = False
        if not contained:
            print(json.dumps({"ok": False,
                              "error": f"--out-dir must stay under <WS>/output: {a.out_dir}"}),
                  file=sys.stderr)
            return 2

    if backend == "hwp":
        print(_HWP_POINTER, file=sys.stderr)
        print(json.dumps({"ok": False, "backend": "hwp", "external": True,
                          "reason": "hwp is an external adapter (hwp-master)"}))
        return 4

    if backend == "hwpx":
        return _run_hwpx_adapter(ws, a.out_dir)

    if backend == "bundle":
        from adapters_impl import bundle_backend
        result, code = bundle_backend.build(ws, a.out_dir)
    elif backend == "docx":
        from adapters_impl import docx_backend
        result, code = docx_backend.build(ws, a.out_dir)
    else:
        print(json.dumps({"ok": False, "error": f"unknown backend: {backend}"}), file=sys.stderr)
        return 3

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
