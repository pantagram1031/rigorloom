# -*- coding: utf-8 -*-
"""Declared-values gate runner (variant-audit "Gate architecture" row).

Mechanisms live in the registry (check_residue / check_density /
check_canonical); *values* are declared per workspace in
``<workspace>/gates.yaml``. Ported from the audit winner (reportkit.gates:
YAML gate list, kinds json_equals/json_lt/json_gt/file_exists/text_absent,
dotted-path resolution, missing input = FAIL not crash, gate_result.json
output) with the audit-mandated hardening:

1. **Canonical binding** — every file-referencing gate resolves against the
   workspace; declared paths must be workspace-relative and must not escape
   it. A missing pinned target is a HARD loud failure (exit 3, finding
   ``target_missing``), never a silent pass, and gate_result.json records
   the miss (the failing-before case: windpath's gate_result recorded
   ``file_exists=true`` for a file that had vanished).
2. **Result staleness** — gate_result.json records, per gate, each target
   file's mtime + sha256 at check time so a later reader can detect rot.
3. **Holdout enforcement** — gates.yaml requires a header block
   ``{workspace_slug, form_hash?}``. The runner refuses to run (exit 2)
   when ``workspace_slug`` differs from the actual workspace directory
   name: declared gate values are holdout-scoped to ONE workspace
   (variant-audit / calibration-no-overfit: never copy values wholesale to
   the next report). A declared ``form_hash`` is checked against the form
   profile that a ``residue`` gate loads — mismatch fails that gate
   (``form_hash_mismatch``).
4. **Mechanism delegation** — kinds ``residue`` / ``density`` /
   ``canonical`` delegate to the registry checkers with declared
   parameters: one runner, registry mechanisms, declared values. A
   delegate that usage-errors NEVER passes the gate.

gates.yaml shape (constrained YAML subset, stdlib-parsed — no pyyaml)::

    workspace_slug: report-<slug>     # required, must equal the dir name
    form_hash: <hex>                  # optional
    gates:
      - id: assembled_exists
        kind: file_exists
        file: output/v5/out.hwpx
      - id: rmse_bounded
        kind: json_lt
        file: sim/metrics.json
        path: rmse.value              # dotted path; list int indexes ok
        expect: 0.5
      - id: forbidden_absent
        kind: text_absent
        file: output/v5/pdf_text.txt
        expect:
          - "김선덕"
          - "chatgpt"
      - id: residue_clean
        kind: residue                 # delegates to check_residue
        form_profile: refs/form_profile.json
        artifact: output/v5/out.hwpx
      - id: subhead_density
        kind: density                 # delegates to check_density
        content: bundle/content.md    # optional (this is the default)
      - id: final_pointer
        kind: canonical               # delegates to check_canonical

Output: ``<workspace>/gate_result.json``::

    {"checker": "declared_gates", "workspace": ..., "workspace_slug": ...,
     "form_hash": ..., "checked_at": ...,
     "gates": [{"id", "kind", "pass", "got", "expect", "findings",
                "targets": [{"path", "exists", "mtime", "sha256"}],
                "verdict": {...delegated only...}}],
     "all_pass": bool, "counts": {"gates": N, "failed": K}}

Exit codes (checker_base convention): 0 = all gates pass, 2 = usage/config
refusal (missing/malformed gates.yaml, slug mismatch, invalid declaration —
gate_result.json is NOT written, so a refusal can never masquerade as a
run), 3 = one or more gates failed (gate_result.json IS written: failures
must be recorded). An empty gate list is never a pass (reportkit semantic
kept, exit 3).

CLI: ``python pipeline/scripts/declared_gates.py <workspace_dir>`` (or
``python -m declared_gates <workspace_dir>`` with pipeline/scripts on the
path).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from checker_base import (  # noqa: E402
    EXIT_HARD,
    EXIT_PASS,
    EXIT_USAGE,
    _utf8_stdio,
    dump_json,
)
import check_canonical  # noqa: E402
import check_density  # noqa: E402
import check_residue  # noqa: E402


CHECKER = "declared_gates"
RESULT_NAME = "gate_result.json"
GATES_NAME = "gates.yaml"

_MISSING = object()

BUILTIN_KINDS = ("json_equals", "json_lt", "json_gt", "file_exists",
                 "text_absent")
DELEGATED_KINDS = ("residue", "density", "canonical")
KNOWN_KINDS = BUILTIN_KINDS + DELEGATED_KINDS

# Allowed declaration keys per kind (strict: a typo'd key is a config
# error, not a silently ignored one).
_ALLOWED_KEYS = {
    "json_equals": {"id", "kind", "file", "path", "expect"},
    "json_lt": {"id", "kind", "file", "path", "expect"},
    "json_gt": {"id", "kind", "file", "path", "expect"},
    "file_exists": {"id", "kind", "file", "path"},
    "text_absent": {"id", "kind", "file", "expect"},
    "residue": {"id", "kind", "form_profile", "artifact", "keep_pattern",
                "keep"},
    "density": {"id", "kind", "content", "warn_per_10k", "hard_per_10k",
                "labels"},
    "canonical": {"id", "kind", "done_after"},
}

_ALLOWED_TOP_KEYS = {"workspace_slug", "form_hash", "gates"}

HOLDOUT_RULE = (
    "declared gate values are holdout-scoped to one workspace — do not "
    "copy a gates.yaml wholesale into another report "
    "(variant-audit 'Gate architecture' row / calibration-no-overfit)"
)


class GatesConfigError(ValueError):
    """gates.yaml is missing, malformed, or violates the declaration
    contract. Always a usage refusal (exit 2), never a gate verdict."""


# ── constrained YAML subset parser (stdlib only, per repo rule) ─────


def _strip_comment(line: str) -> str:
    """Remove an unquoted, whitespace-preceded trailing ``# comment``."""
    quote = None
    for index, ch in enumerate(line):
        if quote is not None:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            continue
        if ch == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index]
    return line


def _split_top_commas(s: str) -> list[str]:
    """Split on commas that sit outside single/double quotes."""
    parts: list[str] = []
    buf: list[str] = []
    quote = None
    for ch in s:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _parse_scalar(token: str):
    """Parse one scalar: quoted string, bool, null, int, float, or string.

    Quoting matters: ``"10101"`` stays a string (windpath's forbidden
    student-id) while ``10101`` becomes an int."""
    t = token.strip()
    if t == "" or t in ("null", "~"):
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        inner = t[1:-1]
        if t[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    if t == "true":
        return True
    if t == "false":
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def _parse_value(token: str):
    """Parse a scalar or an inline ``[a, b]`` list."""
    t = token.strip()
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in _split_top_commas(inner)]
    return _parse_scalar(t)


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_gates_yaml(text: str) -> dict:
    """Parse the constrained gates.yaml subset into
    ``{workspace_slug, form_hash, gates: [dict, ...]}``.

    Raises GatesConfigError on anything outside the contract — silence is
    how gates rot."""
    top: dict = {}
    gates: list[dict] | None = None
    mode = "top"
    gate_indent: int | None = None
    current_gate: dict | None = None
    pending_list_key: str | None = None

    def close_pending() -> None:
        nonlocal pending_list_key
        pending_list_key = None

    def parse_field(rest: str, line_no: int, target: dict) -> None:
        nonlocal pending_list_key
        if ":" not in rest:
            raise GatesConfigError(
                f"line {line_no}: expected 'key: value', got {rest!r}")
        key, _, raw_value = rest.partition(":")
        key = key.strip()
        if not key:
            raise GatesConfigError(f"line {line_no}: empty key")
        if key in target:
            raise GatesConfigError(
                f"line {line_no}: duplicate key {key!r} in gate entry")
        value = raw_value.strip()
        if value == "":
            target[key] = []
            pending_list_key = key
        else:
            close_pending()
            target[key] = _parse_value(value)

    for line_no, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: _indent_of(raw.replace("\t", " "))] or \
                raw.lstrip(" ").startswith("\t"):
            raise GatesConfigError(
                f"line {line_no}: tab indentation is not supported")
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = _indent_of(line)
        content = line.strip()

        if mode == "gates":
            is_item = content == "-" or content.startswith("- ")
            if is_item:
                rest = content[1:].strip()
                if gate_indent is None:
                    gate_indent = indent
                if indent == gate_indent:
                    close_pending()
                    current_gate = {}
                    assert gates is not None
                    gates.append(current_gate)
                    if rest:
                        parse_field(rest, line_no, current_gate)
                    continue
                if (pending_list_key is not None
                        and indent > gate_indent
                        and current_gate is not None):
                    current_gate[pending_list_key].append(
                        _parse_value(rest))
                    continue
                raise GatesConfigError(
                    f"line {line_no}: unexpected list item indentation")
            if gate_indent is not None and indent > gate_indent:
                if current_gate is None:
                    raise GatesConfigError(
                        f"line {line_no}: field outside a gate entry")
                parse_field(content, line_no, current_gate)
                continue
            # dedent back to the top level
            mode = "top"
            close_pending()
            current_gate = None

        # top-level line
        if content == "-" or content.startswith("- "):
            raise GatesConfigError(
                "top-level bare gate list (legacy reportkit format) is not "
                "accepted: gates.yaml requires a header block "
                "{workspace_slug, form_hash?} followed by 'gates:' — "
                + HOLDOUT_RULE)
        if ":" not in content:
            raise GatesConfigError(
                f"line {line_no}: expected 'key: value', got {content!r}")
        key, _, raw_value = content.partition(":")
        key = key.strip()
        value = raw_value.strip()
        if key not in _ALLOWED_TOP_KEYS:
            raise GatesConfigError(
                f"line {line_no}: unknown top-level key {key!r} "
                f"(allowed: {sorted(_ALLOWED_TOP_KEYS)})")
        if key in top or (key == "gates" and gates is not None):
            raise GatesConfigError(
                f"line {line_no}: duplicate top-level key {key!r}")
        if key == "gates":
            if value == "":
                gates = []
                mode = "gates"
                gate_indent = None
            elif value == "[]":
                gates = []
            else:
                raise GatesConfigError(
                    f"line {line_no}: 'gates' must open a block list or "
                    f"be [] — got {value!r}")
            continue
        top[key] = _parse_scalar(value)

    if gates is None:
        raise GatesConfigError(
            "gates.yaml has no 'gates:' list — nothing declared to check")
    top["gates"] = gates
    top.setdefault("form_hash", None)
    return top


# ── declaration validation ──────────────────────────────────────────


def _require_str(gate: dict, key: str, gid: str) -> str:
    value = gate.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GatesConfigError(
            f"gate {gid!r}: required key {key!r} missing or not a "
            f"non-empty string")
    return value


def validate_declaration(config: dict, ws: Path) -> None:
    """Strict pre-run validation: holdout header + per-gate contracts."""
    slug = config.get("workspace_slug")
    if not isinstance(slug, str) or not slug.strip():
        raise GatesConfigError(
            "gates.yaml is missing the required 'workspace_slug' header — "
            + HOLDOUT_RULE)
    actual = ws.resolve().name
    if slug != actual:
        raise GatesConfigError(
            f"gates.yaml declares workspace_slug {slug!r} but the "
            f"workspace directory is {actual!r} — refusing to run: "
            + HOLDOUT_RULE)
    form_hash = config.get("form_hash")
    if form_hash is not None and not isinstance(form_hash, str):
        raise GatesConfigError("'form_hash' must be a string when declared")

    seen_ids: set[str] = set()
    for index, gate in enumerate(config["gates"]):
        if not isinstance(gate, dict):
            raise GatesConfigError(f"gate #{index} is not a mapping")
        gid = gate.get("id")
        if not isinstance(gid, str) or not gid.strip():
            raise GatesConfigError(
                f"gate #{index}: 'id' missing or not a non-empty string")
        if gid in seen_ids:
            raise GatesConfigError(f"duplicate gate id {gid!r}")
        seen_ids.add(gid)
        kind = gate.get("kind")
        if kind not in KNOWN_KINDS:
            raise GatesConfigError(
                f"gate {gid!r}: unknown kind {kind!r} "
                f"(known: {list(KNOWN_KINDS)})")
        extra = set(gate) - _ALLOWED_KEYS[kind]
        if extra:
            raise GatesConfigError(
                f"gate {gid!r} (kind {kind}): unexpected keys "
                f"{sorted(extra)} (allowed: {sorted(_ALLOWED_KEYS[kind])})")
        if kind in ("json_equals", "json_lt", "json_gt", "text_absent"):
            _require_str(gate, "file", gid)
        if kind == "text_absent":
            expect = gate.get("expect")
            if isinstance(expect, str):
                expect = [expect]
            if (not isinstance(expect, list) or not expect
                    or not all(isinstance(s, str) and s for s in expect)):
                raise GatesConfigError(
                    f"gate {gid!r}: text_absent requires a non-empty "
                    f"'expect' list of non-empty strings")
        if kind == "file_exists":
            target = gate.get("path") or gate.get("file")
            if not isinstance(target, str) or not target.strip():
                raise GatesConfigError(
                    f"gate {gid!r}: file_exists requires 'path' or 'file'")
        if kind == "residue":
            _require_str(gate, "form_profile", gid)
            _require_str(gate, "artifact", gid)
        for num_key in ("warn_per_10k", "hard_per_10k", "done_after"):
            if num_key in gate and not isinstance(
                    gate[num_key], (int, float)):
                raise GatesConfigError(
                    f"gate {gid!r}: {num_key!r} must be a number, got "
                    f"{gate[num_key]!r}")
        for list_key in ("keep", "labels"):
            if list_key in gate:
                value = gate[list_key]
                if (not isinstance(value, list)
                        or not all(isinstance(s, str) for s in value)):
                    raise GatesConfigError(
                        f"gate {gid!r}: {list_key!r} must be a list of "
                        f"strings")
        if "keep_pattern" in gate and not isinstance(
                gate["keep_pattern"], str):
            raise GatesConfigError(
                f"gate {gid!r}: 'keep_pattern' must be a string")
        # canonical binding: every declared file path must stay inside ws
        for path_key in _file_keys(gate):
            _bind(ws, str(gate[path_key]), gid, path_key)


def _file_keys(gate: dict) -> list[str]:
    """Declaration keys of this gate that name files on disk."""
    kind = gate.get("kind")
    if kind in ("json_equals", "json_lt", "json_gt", "text_absent"):
        return ["file"]
    if kind == "file_exists":
        return ["path"] if gate.get("path") else ["file"]
    if kind == "residue":
        return ["form_profile", "artifact"]
    if kind == "density":
        return ["content"] if gate.get("content") else []
    return []


def _bind(ws: Path, declared: str, gid: str, key: str) -> Path:
    """Resolve a declared path against the workspace — and only inside it."""
    candidate = Path(declared)
    if candidate.is_absolute():
        raise GatesConfigError(
            f"gate {gid!r}: {key!r} must be workspace-relative, got "
            f"absolute path {declared!r} (canonical binding)")
    resolved = (ws / candidate).resolve()
    ws_resolved = ws.resolve()
    if resolved != ws_resolved and ws_resolved not in resolved.parents:
        raise GatesConfigError(
            f"gate {gid!r}: {key!r} escapes the workspace: {declared!r} "
            f"(canonical binding)")
    return resolved


# ── target metadata (staleness records) ─────────────────────────────


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def target_meta(ws: Path, declared: str) -> dict:
    """mtime + sha256 of one target at check time, so a later reader of
    gate_result.json can detect that the pinned file has since changed or
    vanished (result-staleness contract)."""
    path = ws / declared
    if path.is_file():
        stat = path.stat()
        return {"path": declared, "exists": True, "mtime": stat.st_mtime,
                "sha256": _sha256(path)}
    if path.exists():  # directory or other non-file: present, not hashable
        return {"path": declared, "exists": True,
                "mtime": path.stat().st_mtime, "sha256": None}
    return {"path": declared, "exists": False, "mtime": None,
            "sha256": None}


# ── dotted-path resolution (reportkit semantics, kept) ──────────────


def _resolve_path(obj, dotted_path):
    """Dict keys and list int indexes (negative ok) via dot notation."""
    if dotted_path in (None, ""):
        return obj
    cur = obj
    for part in str(dotted_path).split("."):
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
            else:
                return _MISSING
        elif isinstance(cur, list):
            try:
                idx = int(part)
            except ValueError:
                return _MISSING
            if -len(cur) <= idx < len(cur):
                cur = cur[idx]
            else:
                return _MISSING
        else:
            return _MISSING
    return cur


# ── gate evaluation ─────────────────────────────────────────────────


def _row(gate: dict, *, ok: bool, got=None, expect=None,
         findings=(), targets=(), verdict=None) -> dict:
    row = {
        "id": gate.get("id"),
        "kind": gate.get("kind"),
        "pass": bool(ok),
        "got": got,
        "expect": expect,
        "findings": list(findings),
        "targets": list(targets),
    }
    if verdict is not None:
        row["verdict"] = verdict
    return row


def _missing_target_row(gate: dict, expect, targets: list[dict]) -> dict:
    """Shared-miss #4: a pinned target that is not there is a loud HARD
    failure recorded in the result — never a silent pass, never a stale
    ``true``."""
    missing = [t["path"] for t in targets if not t["exists"]]
    return _row(
        gate, ok=False,
        got={"missing": missing},
        expect=expect,
        findings=["target_missing"],
        targets=targets,
    )


def _eval_builtin(ws: Path, gate: dict, targets: list[dict]) -> dict:
    kind = gate["kind"]
    expect = gate.get("expect")

    if kind == "file_exists":
        # the miss is already recorded by the caller when absent
        return _row(gate, ok=True, got=True, expect=True, targets=targets)

    file_path = ws / gate["file"]
    if kind == "text_absent":
        forbidden = expect if isinstance(expect, list) else [expect]
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return _row(gate, ok=False, got=f"unreadable: {exc}",
                        expect=expect, findings=["target_unreadable"],
                        targets=targets)
        found = [s for s in forbidden if s and s in text]
        return _row(gate, ok=not found, got=found, expect=expect,
                    findings=["forbidden_text_present"] if found else [],
                    targets=targets)

    # json_equals / json_lt / json_gt
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _row(gate, ok=False, got=f"unreadable: {exc}", expect=expect,
                    findings=["target_unreadable"], targets=targets)
    got = _resolve_path(data, gate.get("path"))
    if got is _MISSING:
        return _row(gate, ok=False, got=None, expect=expect,
                    findings=["json_path_missing"], targets=targets)
    if kind == "json_equals":
        ok = got == expect
    elif kind == "json_lt":
        try:
            ok = got < expect
        except TypeError:
            ok = False
    else:  # json_gt
        try:
            ok = got > expect
        except TypeError:
            ok = False
    return _row(gate, ok=bool(ok), got=got, expect=expect,
                findings=[] if ok else ["comparison_failed"],
                targets=targets)


def _eval_delegated(ws: Path, gate: dict, targets: list[dict],
                    declared_form_hash) -> dict:
    """One runner, registry mechanisms, declared values."""
    kind = gate["kind"]
    if kind == "residue":
        verdict, code = check_residue.check(
            ws / gate["form_profile"],
            ws / gate["artifact"],
            keep_pattern=gate.get("keep_pattern",
                                  check_residue.DEFAULT_KEEP_PATTERN),
            keep=tuple(gate.get("keep") or ()),
        )
    elif kind == "density":
        content = gate.get("content")
        verdict, code = check_density.check(
            ws,
            content=(ws / content) if content else None,
            warn_per_10k=float(gate.get(
                "warn_per_10k", check_density.DEFAULT_WARN_PER_10K)),
            hard_per_10k=float(gate.get(
                "hard_per_10k", check_density.DEFAULT_HARD_PER_10K)),
            guide_labels=check_density.DEFAULT_GUIDE_LABELS
            + tuple(gate.get("labels") or ()),
        )
    else:  # canonical
        verdict, code = check_canonical.check(
            ws,
            done_after=float(gate.get(
                "done_after", check_canonical.DEFAULT_DONE_AFTER)),
        )
        pointer = verdict.get("target")
        if pointer and not Path(str(pointer)).is_absolute():
            targets = targets + [target_meta(ws, str(pointer))]

    findings = [item.get("code") for item in verdict.get("hard") or []]
    if code == EXIT_USAGE:
        # a delegate that cannot even run its check must never pass the
        # gate — a broken pin is a failure, not a skip
        findings.append("delegate_usage_error")
    ok = code == EXIT_PASS

    # holdout form binding: values declared for one form family must not
    # silently run against another form's profile
    profile_hash = verdict.get("form_hash")
    if (kind == "residue" and declared_form_hash and profile_hash
            and profile_hash != declared_form_hash):
        findings.append("form_hash_mismatch")
        ok = False

    return _row(gate, ok=ok,
                got=verdict.get("verdict"), expect="pass",
                findings=findings, targets=targets, verdict=verdict)


def run_gate(ws: Path, gate: dict, declared_form_hash=None) -> dict:
    """Evaluate one declared gate. Targets are stat'd + hashed first; a
    missing pinned target short-circuits to a loud recorded failure."""
    targets = [target_meta(ws, str(gate[key])) for key in _file_keys(gate)]
    if gate["kind"] == "density" and not gate.get("content"):
        targets = [target_meta(ws, "bundle/content.md")]
    expect = (True if gate["kind"] == "file_exists"
              else "pass" if gate["kind"] in DELEGATED_KINDS
              else gate.get("expect"))

    if any(not t["exists"] for t in targets):
        return _missing_target_row(gate, expect, targets)
    if gate["kind"] in DELEGATED_KINDS:
        return _eval_delegated(ws, gate, targets, declared_form_hash)
    return _eval_builtin(ws, gate, targets)


# ── runner ──────────────────────────────────────────────────────────


def run_all(ws: str | Path) -> tuple[dict, int]:
    """Load + validate <ws>/gates.yaml, run every gate, return
    (result payload, exit code). Raises GatesConfigError for refusals."""
    ws = Path(ws)
    if not ws.is_dir():
        raise GatesConfigError(f"workspace does not exist: {ws}")
    gates_path = ws / GATES_NAME
    try:
        text = gates_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise GatesConfigError(f"gates.yaml not found: {gates_path}")
    except (OSError, UnicodeError) as exc:
        raise GatesConfigError(f"gates.yaml unreadable: {exc}")

    config = parse_gates_yaml(text)
    validate_declaration(config, ws)

    declared_form_hash = config.get("form_hash")
    rows = [run_gate(ws, gate, declared_form_hash)
            for gate in config["gates"]]
    failed = [row for row in rows if not row["pass"]]
    # empty gate list is never a pass: nothing declared = nothing verified
    all_pass = bool(rows) and not failed

    result = {
        "checker": CHECKER,
        "workspace": str(ws),
        "workspace_slug": config["workspace_slug"],
        "form_hash": declared_form_hash,
        "checked_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "gates": rows,
        "all_pass": all_pass,
        "counts": {"gates": len(rows), "failed": len(failed)},
    }
    return result, (EXIT_PASS if all_pass else EXIT_HARD)


def main(argv=None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="declared-values gate runner: registry mechanisms, "
                    "per-workspace values from <workspace>/gates.yaml")
    parser.add_argument(
        "workspace", help="report workspace dir (contains gates.yaml)")
    args = parser.parse_args(argv)

    try:
        result, code = run_all(args.workspace)
    except GatesConfigError as exc:
        # refusal: no gate_result.json — a refusal must never look like a run
        payload = {"ok": False, "checker": CHECKER,
                   "workspace": str(args.workspace),
                   "error": str(exc), "verdict": "usage_error"}
        print(dump_json(payload))
        return EXIT_USAGE

    for row in result["gates"]:
        if row["pass"]:
            print(f"PASS {row['id']}")
        else:
            print(f"FAIL {row['id']} findings={row['findings']} "
                  f"got={row['got']!r} expect={row['expect']!r}")
    out_path = Path(args.workspace) / RESULT_NAME
    out_path.write_text(dump_json(result) + "\n", encoding="utf-8")
    print(dump_json(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
