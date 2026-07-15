#!/usr/bin/env python3
"""Experimental rhwp SVG proof runner for HWPX render surrogates."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from hwpx_render_surrogate import create_render_surrogate


EXPERIMENTAL_GRADE = "experimental-rhwp"
PROOF_GRADE_RANK = {
    "none": 0,
    EXPERIMENTAL_GRADE: 1,
    "advisory": 2,
    "hancom": 3,
}
DEFAULT_TIMEOUT_SECONDS = 45.0
_OUTPUT_LIMIT = 16_000


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _bounded(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value)
    return text[-_OUTPUT_LIMIT:]


def _comparison_record(comparison: dict | None) -> dict:
    source = comparison if isinstance(comparison, dict) else {}
    render_diff = source.get("render_diff")
    ir_diff = source.get("ir_diff")
    render_diff = render_diff if isinstance(render_diff, dict) else {
        "status": "not_run",
        "reason": "no_reference_render",
    }
    ir_diff = ir_diff if isinstance(ir_diff, dict) else {
        "status": "not_run",
        "reason": "no_reference_ir",
    }
    mismatch_pages = render_diff.get("structural_mismatch_pages", 0)
    difference_count = ir_diff.get("difference_count", 0)
    try:
        mismatch_pages = int(mismatch_pages)
    except (TypeError, ValueError):
        mismatch_pages = 0
    try:
        difference_count = int(difference_count)
    except (TypeError, ValueError):
        difference_count = 0
    complete = (
        render_diff.get("status") != "not_run"
        and ir_diff.get("status") != "not_run"
    )
    record = {
        "render_diff": render_diff,
        "ir_diff": ir_diff,
        "structure_mismatch": mismatch_pages > 0 or difference_count > 0,
        "complete": complete,
    }
    if isinstance(comparison, dict):
        record.update({"provenance": "external", "reproducible": False})
    return record


def _verify_renderer_binary(renderer: dict) -> dict:
    argv = renderer.get("argv")
    candidate = renderer.get("binary_path")
    if not candidate and isinstance(argv, list) and argv:
        if renderer.get("wsl"):
            candidate = argv[2] if argv[:2] == ["wsl", "--"] and len(argv) > 2 else None
        else:
            candidate = argv[0]
    if not candidate:
        return {
            "ok": False, "path": None, "sha256": None,
            "reason": "rhwp_unpinned",
        }
    from render_probe import verify_rhwp_binary
    return verify_rhwp_binary(candidate)


def _command(
    renderer: dict,
    surrogate: Path,
    svg_dir: Path,
    verified_binary: str,
) -> list[str]:
    argv = renderer.get("argv")
    if not isinstance(argv, list) or not argv:
        raise ValueError("rhwp renderer has no argv template")
    input_value = str(surrogate)
    output_value = str(svg_dir)
    if renderer.get("wsl"):
        from render_probe import to_wsl_path
        input_value = to_wsl_path(input_value)
        output_value = to_wsl_path(output_value)
    command = [
        str(item).replace("{in}", input_value).replace("{outdir}", output_value)
        for item in argv
    ]
    if renderer.get("wsl"):
        if command[:2] != ["wsl", "--"] or len(command) < 3:
            raise ValueError("unsupported rhwp WSL command template")
        command[2] = to_wsl_path(verified_binary)
    else:
        command[0] = verified_binary
    return command


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=f".{path.name}.",
        suffix=".tmp", dir=path.parent, delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def run_svg_proof(
    canonical: str | os.PathLike[str],
    proof_dir: str | os.PathLike[str],
    renderer: dict,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    comparison: dict | None = None,
) -> dict:
    """Create a surrogate, run rhwp export-svg, and persist a fail-closed receipt."""
    canonical_path = Path(canonical).resolve()
    proof_path = Path(proof_dir).resolve()
    proof_path.mkdir(parents=True, exist_ok=True)
    surrogate = proof_path / "render-surrogate.hwpx"
    svg_dir = proof_path / "svg"
    svg_dir.mkdir(parents=True, exist_ok=True)
    for stale_svg in svg_dir.glob("*.svg"):
        stale_svg.unlink()

    receipt: dict = {
        "ok": False,
        "renderer": renderer.get("name", "rhwp_svg"),
        "renderer_version": renderer.get("version"),
        "proof_grade": "none",
        "submission_grade": False,
        "page_count": 0,
        "layout_overflow": None,
        "parity_verdict": "fail",
        "comparison": _comparison_record(comparison),
        "fallback": None,
    }
    verification = _verify_renderer_binary(renderer)
    receipt["renderer_binary"] = {
        "path": verification.get("path"),
        "sha256": verification.get("sha256"),
    }
    if verification.get("ok") is not True:
        receipt["reason"] = verification.get("reason", "rhwp_unpinned")
        receipt["fallback"] = "canonical_hwpx_without_render_proof"
        _write_json(proof_path / "receipt.json", receipt)
        return receipt
    try:
        surrogate_receipt = create_render_surrogate(canonical_path, surrogate)
        receipt["surrogate"] = surrogate_receipt
        command = _command(renderer, surrogate, svg_dir, verification["path"])
        receipt["command"] = command
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        receipt["exit_code"] = completed.returncode
        receipt["stdout"] = _bounded(completed.stdout)
        receipt["stderr"] = _bounded(completed.stderr)
        diagnostic = (receipt["stdout"] + "\n" + receipt["stderr"]).upper()
        overflow_seen = "LAYOUT_OVERFLOW" in diagnostic
        receipt["layout_overflow"] = (
            True if overflow_seen else
            (False if completed.returncode == 0 else None)
        )
        receipt["page_count"] = len(list(svg_dir.glob("*.svg")))
        if completed.returncode != 0:
            receipt["reason"] = "rhwp_failed"
            receipt["fallback"] = "canonical_hwpx_without_render_proof"
        elif receipt["page_count"] <= 0:
            receipt["reason"] = "rhwp_no_svg_pages"
            receipt["fallback"] = "canonical_hwpx_without_render_proof"
        else:
            receipt["ok"] = True
            receipt["proof_grade"] = EXPERIMENTAL_GRADE
            receipt["reason"] = "rhwp_svg_rendered"
            if (receipt["layout_overflow"]
                    or receipt["comparison"]["structure_mismatch"]):
                receipt["parity_verdict"] = "fail"
            elif not receipt["comparison"]["complete"]:
                receipt["parity_verdict"] = "unverified"
            else:
                receipt["parity_verdict"] = "partial"
    except subprocess.TimeoutExpired as exc:
        receipt.update({
            "reason": "rhwp_timeout",
            "timeout_seconds": timeout,
            "stdout": _bounded(exc.stdout),
            "stderr": _bounded(exc.stderr),
            "fallback": "canonical_hwpx_without_render_proof",
        })
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile,
            ElementTree.ParseError) as exc:
        receipt.update({
            "reason": "rhwp_unavailable_or_surrogate_failed",
            "error": str(exc),
            "fallback": "canonical_hwpx_without_render_proof",
        })
    _write_json(proof_path / "receipt.json", receipt)
    return receipt


def merge_assembly_verdict(
    verdict_path: str | os.PathLike[str],
    receipt: dict,
) -> dict | None:
    """Attach machine-produced experimental proof without claiming submission proof."""
    path = Path(verdict_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    summary = {
        "ok": receipt.get("ok") is True,
        "renderer": receipt.get("renderer"),
        "proof_grade": receipt.get("proof_grade", "none"),
        "submission_grade": False,
        "page_count": receipt.get("page_count", 0),
        "layout_overflow": receipt.get("layout_overflow"),
        "parity_verdict": receipt.get("parity_verdict", "fail"),
        "reason": receipt.get("reason"),
        "comparison": receipt.get("comparison", {}),
    }
    payload["rhwp_proof"] = summary
    rhwp_grade = (
        str(receipt.get("proof_grade", "none")).strip().lower()
        if receipt.get("ok") is True else "none"
    )
    if rhwp_grade not in PROOF_GRADE_RANK:
        rhwp_grade = "none"
    existing_grade = payload.get("proof_grade")
    existing_rank = PROOF_GRADE_RANK.get(
        str(existing_grade).strip().lower(), -1
    )
    if existing_grade is None or PROOF_GRADE_RANK[rhwp_grade] > existing_rank:
        payload["proof_grade"] = rhwp_grade
    _write_json(path, payload)
    return payload


def run_workspace_proof(
    output_dir: str | os.PathLike[str],
    renderer: dict,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    comparison: dict | None = None,
) -> dict:
    output = Path(output_dir)
    receipt = run_svg_proof(
        output / "out.hwpx",
        output / "proof" / "rhwp",
        renderer,
        timeout=timeout,
        comparison=comparison,
    )
    merge_assembly_verdict(output / "verdict_v06.json", receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="run experimental rhwp SVG proof")
    parser.add_argument("canonical")
    parser.add_argument("proof_dir")
    parser.add_argument("--rhwp", default=None)
    parser.add_argument("--wsl", action="store_true")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--comparison-json")
    args = parser.parse_args(argv)
    comparison = None
    if args.comparison_json:
        comparison = json.loads(Path(args.comparison_json).read_text(encoding="utf-8"))
    rhwp_binary = args.rhwp or os.environ.get("RHWP_BIN", "").strip() or "rhwp"
    local_binary = rhwp_binary
    if args.wsl:
        from render_probe import to_wsl_path
        rhwp_binary = to_wsl_path(rhwp_binary)
    renderer = {
        "name": "rhwp_svg",
        "wsl": args.wsl,
        "binary_path": local_binary,
        "argv": (
            ["wsl", "--", rhwp_binary, "export-svg", "{in}", "-o", "{outdir}"]
            if args.wsl else
            [rhwp_binary, "export-svg", "{in}", "-o", "{outdir}"]
        ),
    }
    receipt = run_svg_proof(
        args.canonical,
        args.proof_dir,
        renderer,
        timeout=args.timeout,
        comparison=comparison,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["ok"] else 3


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
