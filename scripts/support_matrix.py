#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the capability support matrix, and refuse a claim without evidence (T124).

The standing goal requires every capability classified as supported, partially
supported, unsupported, or unknown **with reproducible evidence**, and forbids
claiming parity by inference. ``docs/capability-matrix.md`` does not answer that:
it classifies alias -> OS ceiling (``any``/``tiered``/``windows``), which is a
different axis. The classification existed only as prose.

Prose cannot be checked, so this is a mechanism rather than a document:

* every claim declares at least one EVIDENCE POINTER, and every pointer must
  resolve against the tree — a test function that exists, an eval task that
  exists, a doc heading that exists, a probe key the prober actually emits;
* a ``supported`` claim with no resolving pointer is refused. That is the whole
  point: the table cannot outrun its evidence;
* anything not ``supported`` must carry a reason, so a downgrade explains itself
  instead of going quiet;
* the row set is checked for coverage against things that are DERIVED (the
  installed distribution modules, the shipped eval tasks), so a new module
  cannot be silently absent — the hardcoded-count defect this repo has already
  had four times.

Pointer kinds, and what "resolves" means for each:

    test:<path>::<function>   the file parses and defines that function. Checked
                              by AST, not by running pytest: a generator must not
                              need the suite, and the suite runs this generator.
    eval:<task-id>            evals/tasks/<task-id>.yaml exists.
    doc:<path>#<heading>      the file contains that Markdown heading text.
    probe:<key>               render_probe emits that capability key. Read from
                              the `capabilities` dict literal by AST, so the
                              contract is checked without depending on what this
                              particular host answers.

A pointer proves an assertion EXISTS and is runnable by a third party. It does
not prove the assertion is strong. That distinction is stated in the generated
document rather than glossed.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAIMS = REPO_ROOT / "pipeline" / "references" / "support-claims.yaml"
MATRIX_DOC = REPO_ROOT / "docs" / "support-matrix.md"
PROBE = REPO_ROOT / "pipeline" / "scripts" / "render_probe.py"
TASKS_DIR = REPO_ROOT / "evals" / "tasks"
MODULES_DIR = REPO_ROOT / "modules"

STATUSES = ("supported", "partially", "unsupported", "unknown")
POINTER_KINDS = ("test", "eval", "doc", "probe")
REASON_REQUIRED = tuple(s for s in STATUSES if s != "supported")

_STATUS_LABEL = {
    "supported": "supported",
    "partially": "partially supported",
    "unsupported": "unsupported",
    "unknown": "unknown",
}


class SupportMatrixError(Exception):
    """A claim, a pointer, or the coverage contract is wrong."""


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_claims(path: Path | None = None) -> list[dict]:
    import yaml

    path = Path(path or CLAIMS)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "claims" not in payload:
        raise SupportMatrixError(f"{path.name}: expected a mapping with 'claims'")
    claims = payload["claims"]
    if not isinstance(claims, list) or not claims:
        raise SupportMatrixError(f"{path.name}: 'claims' must be a non-empty list")
    return claims


def installed_modules(root: Path | None = None) -> list[str]:
    """Distribution modules present in this checkout, derived not listed."""
    root = Path(root or MODULES_DIR)
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and (p / "scripts").is_dir())


def shipped_tasks(root: Path | None = None) -> list[str]:
    root = Path(root or TASKS_DIR)
    return sorted(p.stem for p in root.glob("*.yaml"))


def probe_capability_keys(path: Path | None = None) -> set[str]:
    """Keys of render_probe's ``capabilities`` dict, read by AST.

    Deliberately static. Running the prober would make the answer depend on this
    host's PATH and WSL, and the claim being checked is about the contract's
    vocabulary, not about what one machine reports.
    """
    tree = ast.parse(Path(path or PROBE).read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        literal = {k.value for k in node.keys
                   if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        # The capabilities dict is the one carrying the probe's own vocabulary.
        if {"hancom_com", "soffice_path"} <= literal:
            keys |= literal
    if not keys:
        raise SupportMatrixError(
            "render_probe.py: no capabilities dict literal found; this resolver "
            "was written against one and must be updated, not skipped")
    return keys


# ---------------------------------------------------------------------------
# evidence resolution
# ---------------------------------------------------------------------------

def _defines_function(path: Path, name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return True
    return False


def resolve_pointer(pointer: str, *, root: Path | None = None,
                    probe_keys: set[str] | None = None) -> str | None:
    """None when the pointer resolves; otherwise why it does not."""
    root = Path(root or REPO_ROOT)
    if ":" not in pointer:
        return "not a <kind>:<target> pointer"
    kind, _, target = pointer.partition(":")
    if kind not in POINTER_KINDS:
        return f"unknown pointer kind {kind!r}; expected one of {POINTER_KINDS}"
    if not target:
        return "empty target"

    if kind == "test":
        if "::" not in target:
            return "expected <path>::<function>"
        rel, _, func = target.partition("::")
        path = root / rel
        if not path.is_file():
            return f"no such file: {rel}"
        try:
            if not _defines_function(path, func):
                return f"{rel} does not define {func}"
        except SyntaxError as exc:
            return f"{rel} does not parse: {exc}"
        return None

    if kind == "eval":
        if not (root / "evals" / "tasks" / f"{target}.yaml").is_file():
            return f"no such eval task: {target}"
        return None

    if kind == "doc":
        rel, _, heading = target.partition("#")
        path = root / rel
        if not path.is_file():
            return f"no such file: {rel}"
        if not heading:
            return "expected <path>#<heading>"
        text = path.read_text(encoding="utf-8", errors="replace")
        if heading not in text:
            return f"{rel} has no heading text {heading!r}"
        return None

    keys = probe_keys if probe_keys is not None else probe_capability_keys()
    if target not in keys:
        return f"render_probe emits no capability {target!r}"
    return None


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def validate(claims: list[dict], *, root: Path | None = None) -> list[str]:
    """Every problem, not just the first — a partial report invites a partial fix."""
    root = Path(root or REPO_ROOT)
    problems: list[str] = []
    probe_keys = probe_capability_keys(root / "pipeline/scripts/render_probe.py")
    seen: set[str] = set()

    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            problems.append(f"claim {index}: not a mapping")
            continue
        cid = claim.get("id")
        where = f"claim {cid!r}" if cid else f"claim {index}"
        if not cid or not isinstance(cid, str):
            problems.append(f"{where}: missing string id")
            continue
        if cid in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(cid)

        unknown_keys = set(claim) - {"id", "capability", "status", "evidence",
                                     "reason", "covers", "platforms"}
        if unknown_keys:
            problems.append(
                f"{where}: key(s) {sorted(unknown_keys)} are not read by the "
                "generator, so they would be silently dead")

        if not claim.get("capability"):
            problems.append(f"{where}: missing capability description")

        status = claim.get("status")
        if status not in STATUSES:
            problems.append(f"{where}: status {status!r} not in {STATUSES}")

        evidence = claim.get("evidence") or []
        if not isinstance(evidence, list):
            problems.append(f"{where}: evidence must be a list")
            evidence = []
        for pointer in evidence:
            if not isinstance(pointer, str):
                problems.append(f"{where}: pointer {pointer!r} is not a string")
                continue
            why = resolve_pointer(pointer, root=root, probe_keys=probe_keys)
            if why:
                problems.append(f"{where}: pointer {pointer!r} does not resolve — {why}")

        if status == "supported" and not evidence:
            problems.append(
                f"{where}: status 'supported' with no evidence pointer. A support "
                "claim without reproducible evidence is the thing this file exists "
                "to prevent")
        if status in REASON_REQUIRED and not claim.get("reason"):
            problems.append(
                f"{where}: status {status!r} must carry a reason so the downgrade "
                "explains itself")

    problems.extend(_coverage_problems(claims, root=root))
    return problems


def _coverage_problems(claims: list[dict], *, root: Path) -> list[str]:
    """A new module or task must not be able to go unclassified in silence."""
    covered: set[str] = set()
    for claim in claims:
        if isinstance(claim, dict):
            for item in claim.get("covers") or []:
                covered.add(str(item))
    problems = []
    for name in installed_modules(root / "modules"):
        if f"module:{name}" not in covered:
            problems.append(
                f"distribution module {name!r} is installed but no claim covers "
                f"'module:{name}'")
    for task in shipped_tasks(root / "evals" / "tasks"):
        if f"eval:{task}" not in covered:
            problems.append(
                f"eval task {task!r} ships but no claim covers 'eval:{task}'")
    return problems


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def render_matrix(claims: list[dict] | None = None) -> str:
    claims = claims if claims is not None else load_claims()
    lines = [
        "# Support matrix",
        "",
        "Generated by `scripts/support_matrix.py --write` from",
        "`pipeline/references/support-claims.yaml`. Do not edit this table by hand.",
        "",
        "Each row carries evidence pointers, and the generator refuses a",
        "`supported` row whose pointers do not resolve, so a claim here cannot",
        "outrun what the tree can show. Read the pointers as *this assertion",
        "exists and you can run it* — not as *this assertion is strong*. Anything",
        "not `supported` states a reason.",
        "",
        "`unknown` is a real answer and is used where evidence lives in the other",
        "lane's harness and has not been reproduced here. A missing result is",
        "never counted as parity.",
        "",
        "| Capability | Status | Platforms | Evidence | Reason |",
        "|---|---|---|---|---|",
    ]
    for claim in claims:
        platforms = ", ".join(claim.get("platforms") or ["any"])
        evidence = "<br>".join(f"`{p}`" for p in (claim.get("evidence") or [])) or "—"
        reason = str(claim.get("reason") or "—").replace("|", "\\|")
        lines.append("| %s | %s | %s | %s | %s |" % (
            str(claim.get("capability", "")).replace("|", "\\|"),
            _STATUS_LABEL.get(claim.get("status"), claim.get("status")),
            platforms, evidence, reason))
    counts = {s: sum(1 for c in claims if c.get("status") == s) for s in STATUSES}
    lines += [
        "",
        "%d claims: %s." % (
            len(claims),
            ", ".join("%d %s" % (counts[s], _STATUS_LABEL[s]) for s in STATUSES)),
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="write docs/support-matrix.md instead of stdout")
    ap.add_argument("--check", action="store_true",
                    help="validate claims only; exit 1 if any problem")
    args = ap.parse_args(argv)

    claims = load_claims()
    problems = validate(claims)
    if args.check:
        print(json.dumps({"ok": not problems, "claims": len(claims),
                          "problems": problems}, ensure_ascii=False, indent=2))
        return 1 if problems else 0
    if problems:
        print(json.dumps({"ok": False, "problems": problems},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    text = render_matrix(claims)
    if args.write:
        MATRIX_DOC.write_text(text, encoding="utf-8", newline="\n")
        print(json.dumps({"ok": True, "wrote": str(MATRIX_DOC),
                          "claims": len(claims)}, ensure_ascii=False))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
