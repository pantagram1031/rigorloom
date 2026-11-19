#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture and normalise golden fixtures for the legacy ``rigorloom`` CLI.

This script runs a fixed, deterministic-ready sequence of legacy invocations
against ``runtime/scripts/cli.py`` and writes one JSON golden per case under
``tests/legacy_cli/goldens/<case>.json`` with the schema::

    {
      "argv": [...],
      "exit": <int>,
      "stdout_normalized": "<str>",
      "stderr_is_empty": <bool>
    }

Execution environment
---------------------
* ``stdin=subprocess.DEVNULL``
* ``cwd=REPO_ROOT`` so relative fixture paths resolve identically on Linux and
  Windows.
* ``PYTHONIOENCODING=utf-8``, ``RIGORLOOM_DETERMINISTIC=1``, ``COLUMNS=80``,
  ``PYTHONDONTWRITEBYTECODE=1``.
* Ambient overrides ``RIGORLOOM_HWP_ENGINE``, ``RIGORLOOM_CHILD_PYTHON``,
  ``RIGORLOOM_MODULES_ROOT``, ``RIGORLOOM_MODULES_ENABLED``,
  ``RIGORLOOM_WHEEL_PYTHON``, and ``PYTHONPATH`` are stripped so local/CI
  environment variables cannot alter output.

Normalisation rules (explicit and minimal)
------------------------------------------
1. **Line endings**: convert ``\\r\\n`` and ``\\r`` to ``\\n`` so Windows CRLF
   matches Linux LF.
2. **Temporary paths**: replace exact occurrences of the temp ``--root`` path
   (and its resolved/POSIX/JSON-escaped forms) with ``<ROOT>``, and the temp
   scratch directory path (where the absolute input copy for ``open --path``
   lives) with ``<TMP>``. Backslashes inside ``<ROOT>...`` and ``<TMP>...``
   placeholders are normalised to ``/``; backslashes elsewhere are untouched.
3. **ISO-8601 UTC timestamps**: replace timestamps matching
   ``YYYY-MM-DDTHH:MM:SS(.fff)?(Z|+HH:MM)`` with ``<TS>``. (Note:
   ``RIGORLOOM_DETERMINISTIC=1`` is honoured by ``demo gongmun``, not by
   ``open``/``propose``/``request-approval``/``events``.)
4. **Session / plan / approval / run IDs and UUIDs**: replace the chained
   ``sessionId``, ``planId``, ``approvalId`` (and any ``runId``) tracked during
   the run, hyphenated UUIDs, and 32-hex ID values on ID keys (``sessionId``,
   ``planId``, ``approvalId``, ``runId``, ``boundPlanId``, ``offeredPlanId``)
   with ``<ID>``.
5. **Derived SHA-256 digests only**: replace 64-hex digests with ``<SHA256>``
   ONLY where they derive from random IDs or timestamps — specifically
   ``planHash`` (and ``boundPlanHash``/``offeredPlanHash``). Content hashes of
   committed fixture files (``source.sha256``, ``documentHash``, ``boundSha256``,
   ``currentSha256``, ``opsHash``, ``sourceSha256``) are kept exact.

Cases intentionally omitted from byte-for-byte goldens
------------------------------------------------------
* ``doctor`` (no engine root): embeds host Python ``sys.version_info[:3]``,
  ``sys.executable``, symlink-resolved executable path, and host
  ``setuptools``/``wheel`` availability and versions.
* ``--root R capabilities``: embeds host ``sys.executable``, checkout
  ``REPO_ROOT`` paths, ``modules/enabled.yaml`` state (toggled between
  ``core-only`` and ``all-modules`` in CI), OS-specific ``render.prepare``
  reasons (Linux vs Windows), and interpreter-optional ``PIL``/``pymupdf``
  availability (differs in a clean wheel venv). Both ``doctor`` and
  ``capabilities`` are checked structurally in ``tests/test_legacy_cli_goldens.py``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_SCRIPT = REPO_ROOT / "runtime" / "scripts" / "cli.py"
GOLDENS_DIR = Path(__file__).resolve().parent / "goldens"
CORPUS_FORM = (
    REPO_ROOT / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"
)

#: Generous bound compatible with tests/test_subprocess_bounds.py (> 20s).
SUBPROCESS_TIMEOUT = 120

_STRIPPED_ENV_KEYS = (
    "RIGORLOOM_HWP_ENGINE",
    "RIGORLOOM_CHILD_PYTHON",
    "RIGORLOOM_MODULES_ROOT",
    "RIGORLOOM_MODULES_ENABLED",
    "RIGORLOOM_WHEEL_PYTHON",
    "PYTHONPATH",
)

_ISO_TS_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})\b"
)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_JSON_ID_FIELD_RE = re.compile(
    r'("(?:sessionId|planId|approvalId|runId|boundPlanId|offeredPlanId)"\s*:\s*")[0-9a-f]{32}(")'
)
_JSON_DERIVED_HASH_RE = re.compile(
    r'("(?:planHash|boundPlanHash|offeredPlanHash)"\s*:\s*")[0-9a-f]{64}(")'
)
_PLACEHOLDER_PATH_RE = re.compile(r"(<(?:ROOT|TMP)>(?:[^\"'\s]*))")


@dataclass(frozen=True)
class CaseSpec:
    """Definition of one legacy CLI golden case."""

    name: str
    argv: tuple[str, ...]


CASES: tuple[CaseSpec, ...] = (
    # Captured on main as `--help`. Since T179 the bare `--help` shows the
    # document verbs; the legacy help is unchanged behind `protocol --help`
    # (and after a global --root).
    CaseSpec("help_top", ("protocol", "--help")),
    CaseSpec("help_guard", ("guard", "--help")),
    CaseSpec("help_style_check", ("style", "check", "--help")),
    CaseSpec("help_demo_gongmun", ("demo", "gongmun", "--help")),
    CaseSpec(
        "guard_pass_json",
        ("guard", "examples/guard/before.hwpx", "examples/guard/before.hwpx"),
    ),
    CaseSpec(
        "guard_pass_text",
        (
            "guard",
            "examples/guard/before.hwpx",
            "examples/guard/before.hwpx",
            "--format",
            "text",
        ),
    ),
    CaseSpec(
        "guard_fail_json",
        ("guard", "examples/guard/before.hwpx", "examples/guard/after.hwpx"),
    ),
    CaseSpec(
        "guard_fail_text",
        (
            "guard",
            "examples/guard/before.hwpx",
            "examples/guard/after.hwpx",
            "--format",
            "text",
        ),
    ),
    CaseSpec(
        "guard_fail_block_diff",
        (
            "guard",
            "examples/guard/before.hwpx",
            "examples/guard/after.hwpx",
            "--mode",
            "block-diff",
        ),
    ),
    CaseSpec(
        "style_check_pass_json",
        ("style", "check", "examples/gongmun/expected/filled.hwpx"),
    ),
    CaseSpec(
        "style_check_json",
        ("style", "check", "tests/fixtures/style_packs/with_findings.txt"),
    ),
    CaseSpec(
        "style_check_text",
        (
            "style",
            "check",
            "tests/fixtures/style_packs/with_findings.txt",
            "--format",
            "text",
        ),
    ),
    CaseSpec(
        "style_check_gongmun_json",
        (
            "style",
            "check",
            "tests/fixtures/style_packs/with_findings.gongmun.txt",
            "--pack",
            "gongmun",
        ),
    ),
    CaseSpec(
        "style_check_gongmun_text",
        (
            "style",
            "check",
            "tests/fixtures/style_packs/with_findings.gongmun.txt",
            "--pack",
            "gongmun",
            "--format",
            "text",
        ),
    ),
    CaseSpec("engine_absent", ("engine",)),
    CaseSpec("sessions_empty", ("--root", "<ROOT>", "sessions")),
    CaseSpec(
        "open",
        ("--root", "<ROOT>", "open", "--path", "<TMP>/gianmun-byeolji-1ho.hwpx"),
    ),
    CaseSpec("inspect", ("--root", "<ROOT>", "inspect", "--session", "<SESSION_ID>")),
    CaseSpec(
        "read_region",
        (
            "--root",
            "<ROOT>",
            "read-region",
            "--session",
            "<SESSION_ID>",
            "--region",
            "0:5,1",
        ),
    ),
    CaseSpec(
        "propose",
        (
            "--root",
            "<ROOT>",
            "propose",
            "--session",
            "<SESSION_ID>",
            "--op",
            '{"kind":"fill_cell","table":0,"row":5,"col":1,"text":"한빛"}',
        ),
    ),
    CaseSpec("validate", ("--root", "<ROOT>", "validate", "--plan", "<PLAN_ID>")),
    CaseSpec(
        "request_approval",
        ("--root", "<ROOT>", "request-approval", "--plan", "<PLAN_ID>"),
    ),
    CaseSpec(
        "approval",
        ("--root", "<ROOT>", "approval", "--approval", "<APPROVAL_ID>"),
    ),
    CaseSpec("plan", ("--root", "<ROOT>", "plan", "--plan", "<PLAN_ID>")),
    CaseSpec("events", ("--root", "<ROOT>", "events", "--session", "<SESSION_ID>")),
    CaseSpec(
        "candidates_empty",
        ("--root", "<ROOT>", "candidates", "--session", "<SESSION_ID>"),
    ),
    CaseSpec("usage_unknown_command", ("nonexistent-cmd",)),
    CaseSpec("usage_missing_root", ("sessions",)),
    CaseSpec(
        "usage_bad_region",
        (
            "--root",
            "<ROOT>",
            "read-region",
            "--session",
            "<SESSION_ID>",
            "--region",
            "nope",
        ),
    ),
)

CASE_ORDER: tuple[str, ...] = tuple(spec.name for spec in CASES)


def build_env() -> dict[str, str]:
    """Return a clean, deterministic subprocess environment."""
    env = dict(os.environ)
    for key in _STRIPPED_ENV_KEYS:
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["RIGORLOOM_DETERMINISTIC"] = "1"
    env["COLUMNS"] = "80"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def normalize_for_compare(text: str) -> str:
    """Normalise CRLF -> LF and backslashes inside <ROOT>/<TMP> placeholders."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    return _PLACEHOLDER_PATH_RE.sub(
        lambda m: m.group(1).replace("\\\\", "/").replace("\\", "/"),
        unified,
    )


def _path_variants(path: Path) -> list[str]:
    candidates: set[str] = set()
    for base in (path, path.resolve()):
        raw = str(base)
        candidates.add(raw)
        candidates.add(base.as_posix())
        # JSON-escaped form on Windows (backslashes doubled).
        candidates.add(json.dumps(raw)[1:-1])
    return sorted((c for c in candidates if c), key=len, reverse=True)


def normalize_output(
    text: str,
    *,
    root_dir: Path,
    tmp_dir: Path,
    chained_ids: Sequence[str] = (),
    derived_hashes: Sequence[str] = (),
) -> str:
    """Apply the minimal, explicit golden normalisation rules to CLI stdout."""
    out = text.replace("\r\n", "\n").replace("\r", "\n")
    for variant in _path_variants(root_dir):
        out = out.replace(variant, "<ROOT>")
    for variant in _path_variants(tmp_dir):
        out = out.replace(variant, "<TMP>")
    out = normalize_for_compare(out)
    out = _ISO_TS_RE.sub("<TS>", out)
    for item in sorted((x for x in chained_ids if x), key=len, reverse=True):
        out = out.replace(item, "<ID>")
    out = _UUID_RE.sub("<ID>", out)
    out = _JSON_ID_FIELD_RE.sub(r"\g<1><ID>\g<2>", out)
    for digest in sorted((x for x in derived_hashes if x), key=len, reverse=True):
        out = out.replace(digest, "<SHA256>")
    out = _JSON_DERIVED_HASH_RE.sub(r"\g<1><SHA256>\g<2>", out)
    return out


def materialize_argv(
    argv_template: Sequence[str],
    *,
    root_dir: Path,
    tmp_dir: Path,
    state: dict[str, str],
    engine_root: Path | None = None,
) -> list[str]:
    """Expand golden argv placeholders into concrete paths and chained IDs."""
    mapping = {
        "<ROOT>": str(root_dir),
        "<SESSION_ID>": state.get("session_id", ""),
        "<PLAN_ID>": state.get("plan_id", ""),
        "<APPROVAL_ID>": state.get("approval_id", ""),
    }
    concrete: list[str] = []
    for token in argv_template:
        if token in mapping:
            concrete.append(mapping[token])
        elif token.startswith("<TMP>/"):
            rel = token[len("<TMP>/") :]
            concrete.append(str(tmp_dir / rel))
        else:
            concrete.append(token)
    if engine_root is not None and concrete[:1] == ["--root"]:
        # Installed wheel omits engine/ and pipeline/; pass checkout --engine-root
        # after --root <dir> for protocol commands that invoke form_inspect.
        concrete = concrete[:2] + ["--engine-root", str(engine_root)] + concrete[2:]
    return concrete


def run_case_sequence(
    cmd_prefix: Sequence[str],
    case_argvs: Sequence[tuple[str, Sequence[str]]],
    *,
    engine_root: Path | None = None,
) -> dict[str, dict]:
    """Run all legacy cases in order in an isolated temp root/scratch dir."""
    env = build_env()
    results: dict[str, dict] = {}
    state: dict[str, str] = {}
    chained_ids: list[str] = []
    derived_hashes: list[str] = []

    with tempfile.TemporaryDirectory(prefix="rigorloom-legacy-cli-") as raw_base:
        base_dir = Path(raw_base)
        root_dir = base_dir / "root"
        tmp_dir = base_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CORPUS_FORM, tmp_dir / CORPUS_FORM.name)

        for name, argv_template in case_argvs:
            concrete = materialize_argv(
                argv_template,
                root_dir=root_dir,
                tmp_dir=tmp_dir,
                state=state,
                engine_root=engine_root,
            )
            proc = subprocess.run(
                [*cmd_prefix, *concrete],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=str(REPO_ROOT),
                timeout=SUBPROCESS_TIMEOUT,
                check=False,
            )
            if proc.returncode == 0:
                try:
                    payload = json.loads(proc.stdout)
                except ValueError:
                    payload = None
                if isinstance(payload, dict):
                    res = payload.get("result") or {}
                    if name == "open" and isinstance(res.get("sessionId"), str):
                        state["session_id"] = res["sessionId"]
                        chained_ids.append(res["sessionId"])
                    elif name == "propose" and isinstance(res.get("plan"), dict):
                        plan = res["plan"]
                        if isinstance(plan.get("planId"), str):
                            state["plan_id"] = plan["planId"]
                            chained_ids.append(plan["planId"])
                        if isinstance(plan.get("planHash"), str):
                            derived_hashes.append(plan["planHash"])
                    elif name == "request_approval" and isinstance(
                        res.get("approval"), dict
                    ):
                        approval = res["approval"]
                        if isinstance(approval.get("approvalId"), str):
                            state["approval_id"] = approval["approvalId"]
                            chained_ids.append(approval["approvalId"])

            stdout_norm = normalize_output(
                proc.stdout,
                root_dir=root_dir,
                tmp_dir=tmp_dir,
                chained_ids=chained_ids,
                derived_hashes=derived_hashes,
            )
            results[name] = {
                "argv": list(argv_template),
                "exit": proc.returncode,
                "stdout_normalized": stdout_norm,
                "stderr_is_empty": proc.stderr == "",
            }
    return results


def capture_goldens() -> list[Path]:
    """Capture all cases from runtime/scripts/cli.py and write goldens."""
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in GOLDENS_DIR.glob("*.json"):
        stale.unlink()

    captured = run_case_sequence(
        [sys.executable, str(CLI_SCRIPT)],
        [(spec.name, spec.argv) for spec in CASES],
    )
    written: list[Path] = []
    for spec in CASES:
        target = GOLDENS_DIR / f"{spec.name}.json"
        body = (
            json.dumps(
                captured[spec.name], ensure_ascii=False, indent=2, sort_keys=True
            )
            + "\n"
        )
        target.write_text(body, encoding="utf-8", newline="\n")
        written.append(target)
    return written


def main() -> int:
    written = capture_goldens()
    print(f"Captured {len(written)} legacy CLI golden(s) under {GOLDENS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
