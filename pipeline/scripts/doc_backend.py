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
    hwpx    bundled engine (engine/scripts XML engine, any OS). Resolved to
            <repo>/engine/scripts by default and dispatched to
            fill_report.py --engine xml. HWP_MASTER_SCRIPTS is honored as an
            optional override for operators with an external engine checkout
            (deprecated: the engine ships in-repo since Wave 2 / v0.16).
    hwp     COM adapter (Windows + Hancom, bundled at engine/scripts). Not
            dispatched here — prints the assembly-loop instruction and exits 4.

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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))          # pipeline/scripts
_PIPELINE_DIR = os.path.dirname(_HERE)                        # pipeline
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_ENGINE_SCRIPTS = os.path.join(os.path.dirname(_PIPELINE_DIR), "engine", "scripts")
if _ENGINE_SCRIPTS not in sys.path:
    sys.path.insert(0, _ENGINE_SCRIPTS)

from adapters_impl import read_build_yaml_key  # noqa: E402
from checker_base import _utf8_stdio  # noqa: E402
import rhwp_proof  # noqa: E402
import render_cert  # noqa: E402
import document_evidence  # noqa: E402
import render_quality  # noqa: E402
import hwp_equation_diagnostic  # noqa: E402

_HWP_POINTER = (
    "hwp backend is the COM assembly loop (Windows + Hancom), bundled at\n"
    "engine/scripts. It is not dispatched by this command. Run:\n"
    "  python <repo>/engine/scripts/fill_report.py --loop \\\n"
    "    --form <WS>/output/form_copy.hwpx \\\n"
    "    --content <WS>/bundle/content.md --out-dir <WS>/output \\\n"
    "    --build-yaml <WS>/build.yaml --baseline <WS>/form_baseline.json \\\n"
    "    --form-profile <WS>/form_profile.json --proof --max-proof-iters 3\n"
    "See adapters/hwp/README.md."
)

_HWPX_POINTER = (
    "hwpx backend (XML engine; no Hancom/COM) could not be resolved.\n"
    "The engine ships bundled at <repo>/engine/scripts and should always be\n"
    "found there; this error means either a corrupted install (engine/scripts\n"
    "is missing fill_report.py, eqn.py, or xml_backend.py) or an invalid\n"
    "HWP_MASTER_SCRIPTS override pointing at a directory without those files.\n"
    "(The marker check is a misconfiguration guard, not a security check;\n"
    "HWP_MASTER_SCRIPTS is operator-trusted config.)\n"
    "The dispatcher will invoke:\n"
    "  python <engine-scripts>/fill_report.py --engine xml \\\n"
    "    --form <WS>/output/form_copy.hwpx \\\n"
    "    --content <WS>/bundle/content.md --out-dir <WS>/output"
)

# HWP_MASTER_SCRIPTS is operator-trusted config, not attacker input. This
# marker check just catches misconfiguration (e.g. the env var pointing at
# the wrong directory) — it is not a security boundary.
_HWP_MASTER_MARKERS = ("fill_report.py", "eqn.py", "xml_backend.py")
_CONTENT_EQ_RE = re.compile(r"\[\[\s*EQ\b", re.IGNORECASE)
_MAX_ADAPTER_STDOUT_CHARS = 1_000_000
# A valid advisory child payload is not sufficient for submission proof until
# the independent visual-quality decision is released.  Keep this safety hold
# explicit so the parser can be tested without silently promoting tofu/broken
# PDFs; a later release may flip this only with that evidence.


def _reject_json_constant(value):
    raise ValueError(f"non-standard JSON constant: {value}")


_ADAPTER_JSON_DECODER = json.JSONDecoder(parse_constant=_reject_json_constant)


def _parse_adapter_stdout(raw: str | None) -> dict | None:
    """Parse exactly one bounded top-level adapter JSON object.

    ``fill_report`` normally emits one object, but optional PDF/layout
    libraries can append human diagnostics to stdout.  We accept that
    diagnostic suffix/prefix only when there is exactly one unambiguous JSON
    object.  Nested objects belong to their enclosing candidate; a second
    object, malformed/truncated object, or oversized stream fails closed.
    Diagnostics are intentionally discarded rather than copied into a verdict.
    """
    if not isinstance(raw, str) or len(raw) > _MAX_ADAPTER_STDOUT_CHARS:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        whole = _ADAPTER_JSON_DECODER.decode(stripped)
    except (ValueError, json.JSONDecodeError):
        whole = None
    else:
        return whole if isinstance(whole, dict) else None

    candidates: list[tuple[int, int, dict]] = []
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, end = _ADAPTER_JSON_DECODER.raw_decode(raw, index)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            candidates.append((index, end, value))
    maximal = [candidate for candidate in candidates if not any(
        other[0] <= candidate[0] and candidate[1] <= other[1]
        and other != candidate
        and (other[0] < candidate[0] or other[1] > candidate[1])
        for other in candidates
    )]
    if len(maximal) != 1:
        return None
    start, end, payload = maximal[0]
    # A stray brace outside the selected object is either another (possibly
    # truncated) JSON value or an ambiguous diagnostic.  Fail closed rather
    # than selecting the first parseable object.
    outside = raw[:start] + raw[end:]
    if "{" in outside or "}" in outside:
        return None
    return payload


def _resolve_hwpx_fill_report() -> str | None:
    """Resolve the XML engine's fill_report.py.

    Default: the bundled engine at <repo>/engine/scripts (in-repo since the
    Wave 2 absorb, v0.16). HWP_MASTER_SCRIPTS is still honored as an explicit
    override for operators running an external engine checkout — deprecated;
    it will be removed once no external checkouts remain. A set-but-invalid
    override fails loudly (returns None) instead of silently falling back.
    """
    scripts = os.environ.get("HWP_MASTER_SCRIPTS", "").strip()
    base = (os.path.abspath(os.path.expanduser(scripts)) if scripts
            else _ENGINE_SCRIPTS)
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
                if hwp_equation_diagnostic.section_equation_count(stream.read()) > 0:
                    return True
    return False


def _certified_renderer_for_workspace(ws: str, renderers: list[dict]) -> dict | None:
    """Return the configured certified renderer only after explicit build opt-in."""
    build = os.path.join(ws, "build.yaml")
    enabled = read_build_yaml_key(build, "certified_render")
    configured = read_build_yaml_key(build, "render_certificate")
    if str(enabled or "").strip().casefold() != "true" or not configured:
        return None
    configured_path = Path(configured).expanduser()
    if not configured_path.is_absolute():
        configured_path = Path(ws) / configured_path
    try:
        expected = configured_path.resolve()
    except OSError:
        return None
    for renderer in renderers:
        if renderer.get("proof_grade") != "certified" or not renderer.get("argv"):
            continue
        try:
            certificate = Path(str(renderer.get("certificate", ""))).resolve()
        except OSError:
            continue
        if certificate == expected:
            return dict(renderer)
    return None


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
    # ``hancom_com`` is a capability observation only.  This backend is the
    # XML assembly route and never executes Hancom, so availability cannot
    # select a native renderer or establish a Hancom proof grade.

    certified_renderer = _certified_renderer_for_workspace(ws, renderers)

    def with_certified(decision: dict) -> dict:
        if certified_renderer is not None:
            decision["certified_renderer"] = certified_renderer
        return decision

    soffice = next(
        (renderer for renderer in renderers
         if renderer.get("name") in {"soffice_local", "soffice_wsl"}
         and renderer.get("argv")),
        None,
    )
    # T91 keeps the legacy rhwp SVG helper out of automatic routing.  Its
    # historical receipt contains caller paths/process output and lacks the
    # quarantine/process contract required for public evidence.  A future
    # explicit diagnostic lane may execute it; capability alone selects none.
    if has_equations:
        return with_certified({
            "target": target, "equations": True, "available": available,
            "selected": None, "proof_grade": "none",
            "reason": "renderer_cannot_eqn", "pdf_cmd_argv": None,
        })
    if soffice is None:
        return with_certified({
            "target": target, "equations": has_equations,
            "available": available, "selected": None,
            "proof_grade": "none", "reason": "renderer_unavailable",
            "pdf_cmd_argv": None,
        })
    return with_certified({
        "target": target, "equations": False, "available": available,
        "selected": soffice["name"], "proof_grade": "advisory",
        "reason": "equation_free", "pdf_cmd_argv": list(soffice["argv"]),
    })


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
    public = {key: value for key, value in decision.items()
              if key not in {"pdf_cmd_argv", "rhwp_renderer", "certified_renderer",
                             "_quality", "quality_gate_passed", "proof_grade"}}
    if "proof_grade" in decision:
        # This is a route candidate only; terminal proof comes from the
        # artifact-bound receipt and must never be inferred from this field.
        public["candidate_proof_grade"] = decision["proof_grade"]
    return public


def _dispatch_render_quality(
    assembled: Path,
    rendered_pdf: Path,
    adapter_payload: dict,
) -> dict:
    """Run the shared Hangul checker and the child layout contract."""
    quality = render_quality.inspect(assembled, rendered_pdf)
    checks = adapter_payload.get("checks")
    style_anomalies = adapter_payload.get("style_anomalies")
    quality = render_quality.apply_layout_gate(
        quality,
        converged=adapter_payload.get("converged") is True,
        hard_checks=isinstance(checks, dict) and not bool(checks),
        style_clean=isinstance(style_anomalies, list) and not style_anomalies,
        advisory_hold=(
            adapter_payload.get("proof_grade") == "advisory"
            and not document_evidence.ADVISORY_PROOF_RELEASE_ENABLED
        ),
    )
    return quality


def _render_proof_summary(receipt: dict) -> dict:
    return {
        "ok": receipt.get("ok") is True,
        "proof_grade": receipt.get("proof_grade", "none"),
        "submission_grade": receipt.get("submission_grade", False),
        "page_count": receipt.get("page_count", 0),
        "layout_overflow": receipt.get("layout_overflow"),
        "parity_verdict": receipt.get("parity_verdict", "fail"),
        "reason": receipt.get("reason"),
        "comparison": receipt.get("comparison", {}),
    }


def _emit_hwpx_result(completed, decision: dict, proof_receipt: dict | None = None) -> None:
    """Emit one JSON object while preserving a JSON adapter result's fields."""
    payload = _parse_adapter_stdout(completed.stdout or "")
    if payload is None:
        payload = {
            "ok": completed.returncode == 0,
            "backend": "hwpx",
            "reason": "adapter_output_invalid",
        }

    payload["renderer_decision"] = _public_renderer_decision(decision)
    quality = decision.get("_quality")
    if isinstance(quality, dict):
        payload["render_quality"] = dict(quality)
    if proof_receipt is not None:
        payload["render_proof"] = _render_proof_summary(proof_receipt)
    if completed.returncode != 0:
        # A failed adapter process cannot carry forward a grade from a stale
        # child JSON payload.  The active failed receipt below is authoritative
        # and derives `none`.
        payload["proof_grade"] = "none"
        payload["proof_unavailable"] = True
        if decision.get("terminal_failed"):
            payload["reason"] = decision.get("reason", "renderer_failed")
    if completed.returncode == 0:
        # The child owns terminal execution truth.  A route decision is only a
        # plan; in particular, Hancom capability must never overwrite an XML
        # child's ``proof_grade:none``.  Post-render receipts are authoritative
        # only when their runtime actually succeeded.
        if proof_receipt is not None:
            payload["proof_grade"] = (
                decision["proof_grade"] if proof_receipt.get("ok") is True else "none")
            payload["proof_unavailable"] = proof_receipt.get("ok") is not True
            payload["reason"] = decision["reason"]
        else:
            selected = decision.get("selected")
            # Only a successful named LibreOffice child can carry an advisory
            # grade without a dispatcher-side proof fragment.  XML-only,
            # unavailable, and stale/unknown child claims all fail closed.
            if (decision.get("terminal_failed")
                    or decision.get("quality_gate_passed") is not True) \
                    or selected not in {"soffice_local", "soffice_wsl"} \
                    or payload.get("proof_grade") != "advisory":
                payload["proof_grade"] = "none"
                payload["proof_unavailable"] = True
            else:
                payload["proof_unavailable"] = False
            if decision.get("quality_gate_passed") is not True and isinstance(quality, dict):
                payload["reason"] = quality.get("reason_code", "quality_unknown")
            elif decision.get("terminal_failed"):
                payload["reason"] = decision.get("reason", "renderer_failed")
            elif decision["reason"] == "renderer_cannot_eqn":
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


def _certified_timeout() -> float:
    raw = os.environ.get("RIGORLOOM_CERTIFIED_RENDER_TIMEOUT", "").strip()
    if not raw:
        return render_cert.DEFAULT_RENDER_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return render_cert.DEFAULT_RENDER_TIMEOUT
    return value if value > 0 else render_cert.DEFAULT_RENDER_TIMEOUT


def _run_certified_renderer(
    ws: str,
    out_dir: str | None,
    renderer: dict,
) -> dict:
    """Post-assembly certified render; replace the fallback PDF only on success."""
    output = Path(out_dir or os.path.join(ws, "output")).resolve()
    target = output / "out.hwpx"
    certificate = Path(str(renderer.get("certificate", ""))).expanduser()
    proof_dir = output / "proof" / "certified"
    proof_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "ok": False,
        "renderer": renderer.get("name"),
        "proof_grade": "none",
        "submission_grade": False,
        "page_count": 0,
        "layout_overflow": None,
        "parity_verdict": "fail",
        "reason": "certified_check_failed",
        "certificate": str(certificate),
        "comparison": {},
    }
    try:
        eligibility = render_cert.check_document(target, certificate)
    except Exception as exc:
        receipt["error"] = str(exc)
        render_cert.write_json(proof_dir / "receipt.json", receipt)
        return receipt
    receipt["eligibility"] = eligibility
    if eligibility.get("eligible") is not True:
        receipt["reason"] = eligibility.get("reason_code", "certified_check_failed")
        render_cert.write_json(proof_dir / "receipt.json", receipt)
        return receipt

    argv = renderer.get("argv")
    if not isinstance(argv, list) or not argv:
        receipt["reason"] = "certificate_runtime_command_invalid"
        render_cert.write_json(proof_dir / "receipt.json", receipt)
        return receipt
    try:
        with tempfile.TemporaryDirectory(prefix="candidate-", dir=proof_dir) as tmp:
            candidate_dir = Path(tmp)
            explicit_candidate = candidate_dir / "candidate.pdf"
            input_value = str(target)
            output_value = str(explicit_candidate)
            outdir_value = str(candidate_dir)
            if renderer.get("wsl"):
                import render_probe
                input_value = render_probe.to_wsl_path(input_value)
                output_value = render_probe.to_wsl_path(output_value)
                outdir_value = render_probe.to_wsl_path(outdir_value)
            command = [
                str(item).replace("{in}", input_value)
                .replace("{out}", output_value)
                .replace("{outdir}", outdir_value)
                for item in argv
            ]
            receipt["command"] = command
            completed = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=_certified_timeout(),
            )
            receipt["exit_code"] = completed.returncode
            receipt["stdout"] = (completed.stdout or "")[-16000:]
            receipt["stderr"] = (completed.stderr or "")[-16000:]
            candidates = [explicit_candidate, candidate_dir / "out.pdf"]
            produced = next(
                (path for path in candidates if path.is_file() and path.stat().st_size > 0),
                None,
            )
            if completed.returncode != 0:
                receipt["reason"] = "certified_renderer_nonzero"
            elif produced is None:
                receipt["reason"] = "certified_renderer_output_missing"
            else:
                receipt["page_count"] = render_cert.pdf_page_count(produced)
                staged = output / ".out.certified.tmp"
                try:
                    shutil.copyfile(produced, staged)
                    os.replace(staged, output / "out.pdf")
                finally:
                    staged.unlink(missing_ok=True)
                receipt.update({
                    "ok": True,
                    "proof_grade": "certified",
                    "submission_grade": True,
                    "parity_verdict": "pass",
                    "reason": "certified_rendered",
                    "certificate_sha256": eligibility.get("certificate_sha256"),
                })
    except subprocess.TimeoutExpired:
        receipt["reason"] = "certified_renderer_timeout"
    except (OSError, RuntimeError, ValueError) as exc:
        receipt["reason"] = "certified_renderer_failed"
        receipt["error"] = str(exc)

    render_cert.write_json(proof_dir / "receipt.json", receipt)
    if receipt["ok"]:
        verdict_path = output / "verdict_v06.json"
        try:
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            verdict = None
        if isinstance(verdict, dict):
            verdict["certified_proof"] = _render_proof_summary(receipt)
            # The current terminal receipt supersedes any stale grade in an
            # older verdict.  Never preserve a higher historical grade with a
            # max(old, new) merge.
            verdict["proof_grade"] = "certified"
            render_cert.write_json(verdict_path, verdict)
    return receipt


def _write_dispatch_receipt(
    ws: str,
    *,
    backend: str,
    evidence_class: str,
    terminal_state: str,
    input_path: Path,
    output_path: Path | None,
    input_role: str = "assembled_hwpx",
    reason_code: str | None = None,
    exit_code: int | None = None,
    renderer_id: str | None = None,
    quality: dict | None = None,
) -> dict | None:
    """Persist a generic receipt for a post-assembly dispatcher runtime."""
    if output_path is None:
        output_role = "rendered_pdf"
    else:
        suffix = output_path.suffix.casefold()
        output_role = {
            ".pdf": "rendered_pdf",
            ".svg": "diagnostic_svg",
            ".hwpx": "assembled_hwpx",
        }.get(suffix, "rendered_pdf")
    try:
        receipt = document_evidence.build_receipt(
            ws,
            backend=backend,
            evidence_class=evidence_class,
            terminal_state=terminal_state,
            input_path=input_path,
            output_path=output_path,
            input_role=input_role,
            output_role=output_role,
            reason_code=reason_code,
            exit_code=exit_code,
            renderer_id=renderer_id,
            quality=quality,
        )
        document_evidence.write_receipt(ws, receipt)
        return receipt
    except document_evidence.EvidenceError:
        return None


def _run_hwpx_adapter(ws: str, out_dir: str | None) -> int:
    fill_report = _resolve_hwpx_fill_report()
    if fill_report is None:
        print(_HWPX_POINTER, file=sys.stderr)
        print(json.dumps({"ok": False, "backend": "hwpx", "external": True,
                          "reason": "XML engine unavailable"}))
        return 4

    command = [
        sys.executable, fill_report,
        "--engine", "xml",
        "--assemble",
        "--form", os.path.join(ws, "output", "form_copy.hwpx"),
        "--content", os.path.join(ws, "bundle", "content.md"),
        "--out-dir", out_dir or os.path.join(ws, "output"),
        "--out", os.path.join(ws, "output", "verdict_v06.json"),
    ]

    decision = _hwpx_renderer_decision(ws, out_dir)
    help_text = _fill_report_help(fill_report)
    pdf_cmd_argv = decision["pdf_cmd_argv"]
    if pdf_cmd_argv and "--pdf-cmd" in help_text:
        command += ["--pdf-cmd", shlex.join(pdf_cmd_argv)]
        if decision.get("selected") and "--renderer-id" in help_text:
            command += ["--renderer-id", str(decision["selected"])]
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
        print(f"failed to launch XML engine adapter: {exc}", file=sys.stderr)
        print(json.dumps({"ok": False, "backend": "hwpx", "external": True,
                          "reason": "failed to launch XML engine adapter"}))
        return 4
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if (completed.returncode != 0
            and decision.get("selected") in {"soffice_local", "soffice_wsl"}):
        # ``equation_free`` is only a routing plan.  Once the selected
        # renderer process fails, expose terminal execution truth instead of
        # carrying that pre-route reason into the verdict.
        decision["terminal_failed"] = True
        decision["reason"] = "renderer_failed"
    adapter_payload = _parse_adapter_stdout(completed.stdout or "")
    if adapter_payload is None:
        adapter_payload = {}
    proof_receipt = None
    if completed.returncode == 0 and decision.get("certified_renderer"):
        try:
            certified_receipt = _run_certified_renderer(
                ws, out_dir, decision["certified_renderer"]
            )
        except Exception as exc:
            certified_receipt = {
                "ok": False, "proof_grade": "none", "submission_grade": False,
                "reason": "certified_renderer_failed", "error": str(exc),
                "comparison": {},
            }
        if certified_receipt.get("ok") is True:
            proof_receipt = certified_receipt
            decision["selected"] = decision["certified_renderer"].get("name")
            decision["proof_grade"] = "certified"
            decision["reason"] = "certified_rendered"

    if (completed.returncode == 0 and proof_receipt is None
            and decision.get("selected") == "rhwp_svg"):
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
    output = Path(out_dir or os.path.join(ws, "output"))
    assembled = output / "out.hwpx"
    if completed.returncode != 0:
        selected = decision.get("selected")
        if selected in {"soffice_local", "soffice_wsl"}:
            _write_dispatch_receipt(
                ws,
                backend="oss_preview_libreoffice",
                evidence_class="advisory_render",
                terminal_state="failed",
                input_path=assembled,
                output_path=None,
                reason_code="renderer_failed",
                exit_code=completed.returncode,
                renderer_id=str(selected),
            )
        elif selected == "rhwp_svg":
            _write_dispatch_receipt(
                ws,
                backend="oss_preview_rhwp",
                evidence_class="diagnostic_render",
                terminal_state="failed",
                input_path=assembled,
                output_path=None,
                reason_code="renderer_failed",
                exit_code=completed.returncode,
                renderer_id="rhwp_svg",
            )
        else:
            _write_dispatch_receipt(
                ws,
                backend="xml_only",
                evidence_class="structural_only",
                terminal_state="failed",
                input_path=assembled,
                output_path=None,
                reason_code="xml_assembly_failed",
                exit_code=completed.returncode,
            )
    if proof_receipt is not None:
        if decision.get("selected") == "rhwp_svg":
            svg_candidates = sorted((output / "proof" / "rhwp" / "svg").glob("*.svg"))
            diagnostic = svg_candidates[0] if svg_candidates else None
            _write_dispatch_receipt(
                ws,
                backend="oss_preview_rhwp",
                evidence_class="diagnostic_render",
                terminal_state=("succeeded" if proof_receipt.get("ok") is True else "failed"),
                input_path=assembled,
                output_path=diagnostic,
                reason_code=("rhwp_render_succeeded"
                             if proof_receipt.get("ok") is True
                             else "rhwp_render_failed"),
                exit_code=(0 if proof_receipt.get("ok") is True
                           else proof_receipt.get("exit_code")),
                renderer_id="rhwp_svg",
            )
        elif decision.get("selected"):
            _write_dispatch_receipt(
                ws,
                backend="certified_renderer",
                evidence_class="certified_render",
                terminal_state=("succeeded" if proof_receipt.get("ok") is True else "failed"),
                input_path=assembled,
                output_path=output / "out.pdf",
                reason_code=("certified_render_succeeded"
                             if proof_receipt.get("ok") is True
                             else "certified_render_failed"),
                exit_code=(0 if proof_receipt.get("ok") is True
                           else proof_receipt.get("exit_code")),
                renderer_id=str(decision.get("selected")),
            )
    elif completed.returncode == 0:
        selected = str(decision.get("selected") or "")
        if selected in {"soffice_local", "soffice_wsl"}:
            rendered_pdf = output / "out.pdf"
            child_grade = str(adapter_payload.get("proof_grade", "none")).lower()
            renderer_failed = bool(adapter_payload.get("renderer_attempted"))
            if rendered_pdf.is_file() and not renderer_failed:
                quality = _dispatch_render_quality(
                    assembled, rendered_pdf, adapter_payload)
                # The process and PDF succeeded even when quality rejects the
                # proof.  Keep that execution fact distinct from a renderer
                # nonzero/missing-output failure.
                decision["terminal_failed"] = False
                decision["_quality"] = quality
                decision["quality_gate_passed"] = (
                    quality.get("state") == "passed"
                    and child_grade == "advisory")
                if quality.get("state") == "passed":
                    reason_code = "render_succeeded"
                else:
                    reason_code = quality.get("reason_code", "quality_unknown")
                _write_dispatch_receipt(
                    ws,
                    backend="oss_preview_libreoffice",
                    evidence_class="advisory_render",
                    terminal_state="succeeded",
                    input_path=assembled,
                    output_path=rendered_pdf,
                    reason_code=reason_code,
                    exit_code=0,
                    renderer_id=selected,
                    quality=quality,
                )
            else:
                # A zero adapter exit with no current PDF is not a renderer
                # success.  Keep the failure reason truthful and replace any
                # stale advisory receipt with an active failed terminal row.
                decision["terminal_failed"] = True
                decision["reason"] = (
                    "renderer_failed" if rendered_pdf.is_file()
                    else "renderer_output_missing"
                )
                _write_dispatch_receipt(
                    ws,
                    backend="oss_preview_libreoffice",
                    evidence_class="advisory_render",
                    terminal_state="failed",
                    input_path=assembled,
                    output_path=None,
                    reason_code=decision["reason"],
                    exit_code=0,
                    renderer_id=selected,
                )
        else:
            _write_dispatch_receipt(
                ws,
                backend="xml_only",
                evidence_class="structural_only",
                terminal_state="succeeded",
                input_path=Path(ws) / "output" / "form_copy.hwpx",
                output_path=assembled,
                input_role="source_form",
                exit_code=0,
                reason_code=decision.get("reason", "xml_verified_no_proof"),
            )
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
    # cp949-safe --help: reconfigure BEFORE parse_args (see cli_io.py).
    _utf8_stdio()
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
                          "reason": "hwp is the COM assembly loop (engine/scripts); run it directly"}))
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
