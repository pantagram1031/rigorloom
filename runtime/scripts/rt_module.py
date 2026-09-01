#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution-module checkers, run against a session. Runtime GAP 17.

Six distribution modules declare checkers on disk and the Runtime knew nothing
about them: no method named one, so the Desktop's 작업 팩 panel was a
declaration viewer with a 준비 중 label and the whole report-pipeline product
sat behind one missing wire (desktop/README.md gap 17). This module is that
wire. It runs a module's declared checkers against the document a session
holds, and returns a VerificationReport-shaped answer.

AGENT-SAFE, and the reasons are worth writing down because the alternative was
defensible.

  * The checker contract is a *verdict producer*, not a mutator: one JSON
    object on stdout and an exit in {0, 2, 3}
    (pipeline/scripts/checker_base.py:13-16). Measured across all eighteen
    checkers the six shipped modules declare, not assumed: the only write path
    any of them has is ``--out``, which this caller never passes.
  * The subject is a COPY. Every call materialises the document into a scratch
    directory, runs the child with that directory as its cwd, and deletes the
    directory afterwards. The session copy, the published candidate and the
    operator's original are out of reach by construction rather than by trust,
    which is what makes "read-only" a property instead of a hope.
  * It publishes nothing and decides nothing: no candidate, no plan state, no
    approval. It appends one ``module.checked`` event, exactly as
    ``plan/propose`` — also agent-safe — appends ``plan.proposed``.
  * Spawning a repo script on an agent call is already the norm here:
    ``document/inspect`` runs ``form_inspect``. What is new is that the script
    is module payload, and the authority for THAT is enablement — an
    install-time operator act recorded in ``modules/enabled.yaml``, which no
    wire call can change. A module nobody enabled cannot be run by anybody.

RESIDUAL, stated rather than glossed: a child is bounded (wall clock, output,
environment allowlist) and killed on timeout, but it is not CONTAINED — no
process group, no Windows Job, same gap ``rt_engine`` records and
``capabilities.unavailable.descendantContainment`` reports. A checker that
writes to an absolute path outside its cwd is therefore not stopped by
anything here; it is only kept away from the session's own bytes.

WHAT MAY BE RUN, AND WHY IT IS A DECLARATION. A session holds a document; half
the shipped checkers take a report *workspace* directory instead. Telling them
apart is not core's to guess: a name list in core violates the first module
rule, and handing an ``.hwpx`` path to a workspace checker produces a verdict
about an empty directory that reads exactly like a finding about the user's
document. So ``provides.checkers[].subject`` (modules/README.md) says which,
and a checker that has not declared one is reported ``skipped`` with reason
``subject_undeclared`` — never run on a guess, never counted as a pass.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import CHILD_TIMEOUT_SECONDS, RpcError  # noqa: E402
from rt_engine import child_python, run_child  # noqa: E402

#: Where the distribution modules live, and which of them are enabled. Both
#: default to the checkout; the overrides exist because a packaged host installs
#: modules beside the application rather than inside the repo, and because a
#: test needs an enablement that is not the operator's own. Precedent for the
#: first: ``pipeline/scripts/personalization_ctl.py:128``.
MODULES_ROOT_ENV = "RIGORLOOM_MODULES_ROOT"
MODULES_ENABLED_ENV = "RIGORLOOM_MODULES_ENABLED"

#: What a checker's positional argument is. Mirrors the closed vocabulary in
#: ``pipeline/scripts/module_registry.py``; a value outside it never reaches
#: here because the registry refuses the manifest.
CHECK_SUBJECTS = ("document", "workspace")

#: Decided BEFORE anything is spawned. A skipped checker is not a pass and is
#: not a failure — it is a checker that was never asked.
SKIP_REASONS = (
    "subject_undeclared",   # the declaration does not say what its input is
    "needs_workspace",      # it takes a report workspace; a session is a document
)

#: Decided AFTER trying. The child ran, or could not, and produced no verdict
#: this Runtime is willing to read as one.
UNAVAILABLE_REASONS = (
    "spawn_failed",         # the interpreter or the script would not start
    "timed_out",            # exceeded its bound and was killed
    "missing_dependency",   # the child died on an import this machine lacks
    "usage_error",          # exit 2: we called the checker wrongly
    "no_verdict",           # exited, but printed nothing this could parse
)

NOT_RUN_REASONS = SKIP_REASONS + UNAVAILABLE_REASONS

#: Per checker. Default is the engine child bound, which sits above the
#: measured loaded-spawn distribution (tests/test_subprocess_bounds.py: median
#: 9.00s, worst observed 36.46s). The floor is not zero: a bound under a second
#: races the interpreter's own start-up and would report every checker as hung.
DEFAULT_CHECK_TIMEOUT_SECONDS = CHILD_TIMEOUT_SECONDS
MIN_CHECK_TIMEOUT_SECONDS = 1.0
MAX_CHECK_TIMEOUT_SECONDS = 600.0

#: One call may not fan out without limit, and one verdict may not fill a frame.
MAX_CHECKERS_PER_CALL = 64
MAX_FINDINGS_PER_CHECKER = 200
MAX_DETAIL_CHARS = 800
MAX_MESSAGE_CHARS = 600

#: Severity of a normalized finding row. ``skipped`` is a checker's own rule
#: skip, kept as a finding rather than dropped: "this rule did not decide" is
#: the fact a reader needs most and the one a bare pass hides.
FINDING_SEVERITIES = ("hard", "warn", "skipped")

#: Keys a checker uses for the place a finding is about, best first. A rule
#: NAME is deliberately not one of them: it is the code, and echoing it as a
#: location would make every rule-level skip look like it pointed somewhere.
_LOCATION_KEYS = ("at", "where", "location", "seat", "path")


# --- registry access ---------------------------------------------------------

def _module_registry(engine_root: Path):
    """Import ``pipeline/scripts/module_registry.py``, the way rt_geometry does.

    Imported, not spawned. ``rt_engine`` spawns the ENGINE scripts because they
    mutate ``sys.path`` at module scope and import each other by bare basename;
    the registry is stdlib-only, side-effect-free and already the one reader of
    ``module.yaml`` — writing a second one here is exactly the mistake the
    Desktop avoided by shelling out to it.
    """
    scripts = Path(engine_root) / "pipeline" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import module_registry  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        raise RpcError("capability_unavailable",
                       "pipeline/scripts/module_registry.py is not importable, "
                       "so this build cannot see distribution modules",
                       detail=f"{type(exc).__name__}: {exc}"[:MAX_DETAIL_CHARS],
                       expected=str(scripts)) from exc
    return module_registry


def registry_facts(engine_root: Path, environ: dict | None = None) -> dict:
    """Where modules are read from and where enablement is read from."""
    environ = os.environ if environ is None else environ
    root = Path(engine_root)
    override = (environ.get(MODULES_ROOT_ENV) or "").strip()
    modules_root = Path(override) if override else root / "modules"
    enabled_override = (environ.get(MODULES_ENABLED_ENV) or "").strip()
    enabled_file = (Path(enabled_override) if enabled_override
                    else modules_root / "enabled.yaml")
    return {
        "modulesRoot": str(modules_root),
        "modulesRootSource": "override" if override else "engineRoot",
        "enabledFile": str(enabled_file),
        "enabledFileSource": "override" if enabled_override else "modulesRoot",
        "enabledFilePresent": enabled_file.is_file(),
        "env": {"modulesRoot": MODULES_ROOT_ENV, "enabled": MODULES_ENABLED_ENV},
    }


def load_registry(engine_root: Path, environ: dict | None = None):
    """``(ModuleRegistry, facts)``. A broken declaration is loud, never a skip."""
    module_registry = _module_registry(engine_root)
    facts = registry_facts(engine_root, environ)
    registry = module_registry.ModuleRegistry(
        facts["modulesRoot"],
        enabled_file=facts["enabledFile"],
        pyproject=Path(engine_root) / "pyproject.toml")
    return registry, facts


def _module_error(module_registry):
    return module_registry.ModuleError


# --- capability ---------------------------------------------------------------

def module_capability(engine_root: Path, environ: dict | None = None) -> dict:
    """What ``module/check`` can do here, computed without running anything.

    Defensive on purpose: this is folded into every ``capabilities/list`` and
    every ``initialize``, and a single malformed ``module.yaml`` in someone's
    install must not make the connection unopenable. The registry's loudness is
    preserved as a reported reason instead of an exception.
    """
    base = {
        "state": "unavailable",
        "reason": None,
        "methods": ["module/list", "module/check"],
        "subjects": list(CHECK_SUBJECTS),
        "skipReasons": list(SKIP_REASONS),
        "unavailableReasons": list(UNAVAILABLE_REASONS),
        "findingSeverities": list(FINDING_SEVERITIES),
        "authority": (
            "agent-safe: the checker contract is read-only, the subject handed "
            "to it is a scratch copy, and a module can only be reached at all "
            "if the operator enabled it in enabled.yaml"),
        "containment": "not_established",
        "limits": {
            "defaultTimeoutSeconds": DEFAULT_CHECK_TIMEOUT_SECONDS,
            "minTimeoutSeconds": MIN_CHECK_TIMEOUT_SECONDS,
            "maxTimeoutSeconds": MAX_CHECK_TIMEOUT_SECONDS,
            "maxCheckersPerCall": MAX_CHECKERS_PER_CALL,
            "maxFindingsPerChecker": MAX_FINDINGS_PER_CHECKER,
        },
    }
    try:
        registry, facts = load_registry(engine_root, environ)
        base.update(facts)
        discovered = sorted(registry.discover())
        enabled = [spec.name for spec in registry.enabled_modules()]
    except RpcError as exc:
        base["reason"] = exc.message
        return base
    except Exception as exc:  # noqa: BLE001 - a bad manifest is reported, not raised
        base["reason"] = f"{type(exc).__name__}: {exc}"[:MAX_DETAIL_CHARS]
        return base
    base["discovered"] = discovered
    base["enabled"] = enabled
    if not discovered:
        base["reason"] = "no distribution module is present under the modules root"
    elif not enabled:
        base["state"] = "ready"
        base["reason"] = ("no distribution module is enabled; module/check has "
                          "nothing to run until enabled.yaml lists one")
    else:
        base["state"] = "ready"
    return base


# --- module/list ----------------------------------------------------------------

def _relative(path: str, root: str) -> str:
    """Module-relative, so a wire answer never carries the operator's tree."""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).name


def module_list(engine_root: Path, environ: dict | None = None) -> dict:
    """Every declared module, what it contributes, and what is runnable here.

    Paths are module-relative. An absolute script path is the operator's
    directory layout, and there is no reason for it to cross a wire that an
    agent reads.
    """
    module_registry = _module_registry(engine_root)
    registry, facts = load_registry(engine_root, environ)
    try:
        discovered = registry.discover()
        enabled_names = [spec.name for spec in registry.enabled_modules()]
    except _module_error(module_registry) as exc:
        raise RpcError("capability_unavailable",
                       "the distribution-module declarations on disk do not "
                       "validate; nothing is listed rather than half of it",
                       detail=str(exc)[:MAX_DETAIL_CHARS], **facts) from exc

    root = facts["modulesRoot"]
    modules = []
    for name in sorted(discovered):
        spec = discovered[name]
        provides = spec.provides
        checkers = []
        for entry in provides.get("checkers", []):
            subject = entry.get("subject")
            checkers.append({
                "name": entry["name"],
                "script": _relative(str(spec.payload_path(entry["script"])), root),
                "subject": subject,
                "wants": list(entry.get("wants") or []),
                "runnableAgainstDocument": subject == "document",
                "reason": None if subject == "document" else (
                    "needs_workspace" if subject == "workspace"
                    else "subject_undeclared"),
            })
        modules.append({
            "name": name,
            "enabled": name in enabled_names,
            "requires": spec.requires,
            "requiresModules": list(spec.requires_modules),
            "checkers": checkers,
            "cli": [entry["command"] for entry in provides.get("cli", [])],
            "packTypes": list(provides.get("pack_types", [])),
            "runModes": [entry["name"] for entry in provides.get("run_modes", [])],
            "gateKinds": [entry["kind"] for entry in provides.get("gate_kinds", [])],
            "studioPanels": [entry["id"] for entry in provides.get("studio_panels", [])],
            "playbooks": len(provides.get("playbooks", [])),
            "hasSkillFragment": bool(provides.get("skill")),
        })
    return {
        "version": registry.version,
        **facts,
        "discovered": sorted(discovered),
        "enabled": enabled_names,
        "modules": modules,
        "note": ("a module that is present but not enabled contributes nothing "
                 "and cannot be checked against; enablement is an operator act "
                 "recorded in enabled.yaml, never a wire call"),
    }


# --- module/check ------------------------------------------------------------------

def _bounded(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "…"


def _address(location) -> dict | None:
    """The finding's place in the Runtime's own addressing, when it has one.

    A checker writes ``at`` in the engine's shape (``{table, addr: [r, c]}``,
    ``{table, row}``, ``{para}``). The Desktop clicks addresses, so the row
    carries a translated one where a translation exists and ``null`` where it
    does not — never a half-address that would select the wrong cell.
    """
    if not isinstance(location, dict):
        return None
    table = location.get("table")
    row, col = location.get("row"), location.get("col")
    addr = location.get("addr")
    if isinstance(addr, (list, tuple)) and len(addr) == 2:
        row, col = addr[0], addr[1]
    if isinstance(table, int) and isinstance(row, int) and isinstance(col, int):
        return {"table": table, "row": row, "col": col}
    para = location.get("atPara")
    if para is None:
        para = location.get("para")
    if isinstance(para, int) and not isinstance(para, bool):
        return {"atPara": para}
    return None


def _finding(severity: str, row: dict) -> dict:
    assert severity in FINDING_SEVERITIES, severity
    code = row.get("code") or row.get("rule")
    message = row.get("msg") or row.get("message") or row.get("reason")
    location = None
    for key in _LOCATION_KEYS:
        if key in row and row[key] is not None:
            location = row[key]
            break
    return {
        "severity": severity,
        "code": str(code) if code is not None else None,
        "message": _bounded(message, MAX_MESSAGE_CHARS) if message is not None else None,
        "location": location if isinstance(location, (dict, str, int)) else None,
        "address": _address(location),
    }


def _findings(parsed: dict) -> tuple[list, dict]:
    rows: list[dict] = []
    truncated: dict[str, int] = {}
    for severity in FINDING_SEVERITIES:
        items = parsed.get(severity)
        if not isinstance(items, list):
            continue
        kept = [item for item in items if isinstance(item, dict)]
        if len(kept) > MAX_FINDINGS_PER_CHECKER:
            truncated[severity] = len(kept) - MAX_FINDINGS_PER_CHECKER
            kept = kept[:MAX_FINDINGS_PER_CHECKER]
        rows.extend(_finding(severity, item) for item in kept)
    return rows, truncated


def _parse_verdict(text: str):
    stripped = text.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except ValueError:
        start = stripped.find("{")
        if start < 0:
            return None
        try:
            payload = json.loads(stripped[start:])
        except ValueError:
            return None
    return payload if isinstance(payload, dict) else None


def _row(entry: dict, *, state: str, reason: str | None, **extra) -> dict:
    assert state in ("ran", "skipped", "unavailable"), state
    assert reason is None or reason in NOT_RUN_REASONS, reason
    row = {
        "checker": entry["name"],
        "module": entry["module"],
        "subject": entry.get("subject"),
        "wants": list(entry.get("wants") or []),
        "state": state,
        "reason": reason,
        "ok": None,
        "verdict": None,
    }
    row.update(extra)
    return row


def _resolve_subject(session, run_id):
    """The bytes to check, and what they are. A candidate is re-verified first."""
    if run_id is None:
        return session.source, {
            "kind": "session_source",
            "name": session.meta["sourceName"],
            "sha256": session.meta["sourceSha256"],
            "bytes": session.meta["sourceBytes"],
            "runId": None,
        }
    from rt_apply import read_receipt  # noqa: PLC0415

    # read_receipt re-verifies the candidate bytes against their binding, so a
    # checker is never handed an artifact that drifted after publication.
    receipt = read_receipt(session, run_id)
    candidate = receipt["candidate"]
    path = session.candidates_dir / run_id / candidate["path"]
    return path, {
        "kind": "candidate",
        "name": candidate["path"],
        "sha256": candidate["sha256"],
        "bytes": candidate["bytes"],
        "runId": run_id,
    }


def _select(registry, module_registry, module: str, wanted, facts: dict) -> list:
    """The checkers this call will consider, or a refusal naming why not."""
    try:
        declared = registry.discover()
        enabled = {spec.name for spec in registry.enabled_modules()}
        rows = [row for row in registry.enabled_checkers()
                if row["module"] == module]
    except _module_error(module_registry) as exc:
        raise RpcError("capability_unavailable",
                       "the distribution-module declarations on disk do not "
                       "validate",
                       detail=str(exc)[:MAX_DETAIL_CHARS], **facts) from exc

    if module not in declared:
        raise RpcError("capability_unavailable",
                       f"no distribution module named {module!r} is declared "
                       "under this modules root",
                       module=module, declared=sorted(declared), **facts)
    if module not in enabled:
        raise RpcError("capability_unavailable",
                       f"distribution module {module!r} is present but not "
                       "enabled; enabling it is an operator act, not a wire call",
                       module=module, declared=sorted(declared),
                       enabled=sorted(enabled), **facts)

    by_name = {row["name"]: row for row in rows}
    if wanted is None:
        chosen = [by_name[name] for name in sorted(by_name)]
    else:
        if not isinstance(wanted, list) or not wanted:
            raise RpcError("invalid_params",
                           "checkers must be a non-empty array of checker names")
        missing = [name for name in wanted
                   if not isinstance(name, str) or name not in by_name]
        if missing:
            raise RpcError("invalid_params",
                           f"module {module!r} declares no such checker",
                           module=module, unknown=missing,
                           declared=sorted(by_name))
        seen: list = []
        for name in wanted:
            if name not in seen:
                seen.append(name)
        chosen = [by_name[name] for name in seen]
    if len(chosen) > MAX_CHECKERS_PER_CALL:
        raise RpcError("invalid_params",
                       f"a call may run at most {MAX_CHECKERS_PER_CALL} checkers",
                       requested=len(chosen), limit=MAX_CHECKERS_PER_CALL)
    return chosen


def _timeout(value) -> float:
    if value is None:
        return float(DEFAULT_CHECK_TIMEOUT_SECONDS)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RpcError("invalid_params", "timeoutSeconds must be a number",
                       timeoutSeconds=value)
    seconds = float(value)
    if not MIN_CHECK_TIMEOUT_SECONDS <= seconds <= MAX_CHECK_TIMEOUT_SECONDS:
        raise RpcError("invalid_params",
                       f"timeoutSeconds must be between "
                       f"{MIN_CHECK_TIMEOUT_SECONDS} and "
                       f"{MAX_CHECK_TIMEOUT_SECONDS}",
                       timeoutSeconds=value)
    return seconds


def _run_one(entry: dict, *, subject_copy: Path, baseline_copy: Path | None,
             cwd: Path, timeout: float) -> dict:
    argv = [child_python(), entry["script"], str(subject_copy)]
    wants = list(entry.get("wants") or [])
    unsatisfied = []
    if "baseline" in wants:
        if baseline_copy is None:
            unsatisfied.append("baseline")
        else:
            argv += ["--baseline", str(baseline_copy)]
    started = time.monotonic()
    try:
        result = run_child(argv, cwd=cwd, timeout=timeout)
    except RpcError as exc:
        return _row(entry, state="unavailable", reason="spawn_failed",
                    detail=_bounded(exc.message, MAX_DETAIL_CHARS),
                    durationMs=int((time.monotonic() - started) * 1000))
    duration = int((time.monotonic() - started) * 1000)
    stderr = result.stderr.decode("utf-8", errors="replace")
    common = {
        "exitCode": result.returncode,
        "durationMs": duration,
        "timedOut": result.timed_out,
        "outputTruncated": result.truncated,
    }

    if result.timed_out:
        return _row(entry, state="unavailable", reason="timed_out",
                    detail=(f"the checker was killed after {timeout:g}s; the "
                            "direct child is gone, descendants are not "
                            "contained by this build"),
                    **common)
    parsed = _parse_verdict(result.text)
    if result.returncode == 2:
        message = None
        if isinstance(parsed, dict):
            message = parsed.get("error") or parsed.get("verdict")
        return _row(entry, state="unavailable", reason="usage_error",
                    detail=_bounded(message or stderr or "exit 2 with no message",
                                    MAX_DETAIL_CHARS),
                    **common)
    if parsed is None:
        reason = ("missing_dependency"
                  if ("ModuleNotFoundError" in stderr or "ImportError" in stderr)
                  else "no_verdict")
        return _row(entry, state="unavailable", reason=reason,
                    detail=_bounded(stderr or result.text
                                    or "no output at all", MAX_DETAIL_CHARS),
                    **common)

    findings, truncated = _findings(parsed)
    counts = parsed.get("counts")
    row = _row(entry, state="ran", reason=None, **common)
    row["ok"] = bool(parsed.get("ok"))
    row["verdict"] = parsed.get("verdict")
    row["counts"] = counts if isinstance(counts, dict) else {}
    row["findings"] = findings
    if truncated:
        row["findingsTruncated"] = truncated
    if isinstance(parsed.get("rule_states"), dict):
        row["ruleStates"] = parsed["rule_states"]
    row["wantsUnsatisfied"] = unsatisfied
    row["partial"] = bool(unsatisfied)
    return row


def run_module_checks(session, *, engine_root: Path, module: str,
                      checkers=None, run_id=None, timeout=None,
                      environ: dict | None = None) -> dict:
    """Run a distribution module's checkers against this session's document.

    Never a fabricated pass. ``acceptance`` is true only when every selected
    checker RAN, reported clean, and had every input it declares it needs —
    the rule ``visual_verify`` states at pipeline/scripts/visual_verify.py:42-47
    and ``rt_apply.verification_report`` already applies to the offline gate.
    """
    if not isinstance(module, str) or not module:
        raise RpcError("invalid_params", "module must be a non-empty string")
    seconds = _timeout(timeout)
    module_registry = _module_registry(engine_root)
    registry, facts = load_registry(engine_root, environ)
    selected = _select(registry, module_registry, module, checkers, facts)

    subject_path, subject = _resolve_subject(session, run_id)
    if not subject_path.is_file():
        raise RpcError("artifact_missing",
                       "the document this session holds is not on disk",
                       sessionId=session.id, kind=subject["kind"])

    call_id = uuid.uuid4().hex
    scratch = session.dir / "checks" / call_id
    rows: list[dict] = []
    baseline = {"supplied": False, "kind": None,
                "reason": ("checking the session source itself: a document is "
                           "never its own baseline")}
    try:
        try:
            (scratch / "subject").mkdir(parents=True, exist_ok=False)
            subject_copy = scratch / "subject" / subject["name"]
            shutil.copyfile(subject_path, subject_copy)
            baseline_copy = None
            if run_id is not None:
                # The blank form a candidate was produced from IS the session
                # source, by construction: rt_apply reads it and writes the
                # candidate. So the one checker input this Runtime can supply
                # honestly, it supplies.
                (scratch / "baseline").mkdir(parents=True, exist_ok=False)
                baseline_copy = scratch / "baseline" / session.meta["sourceName"]
                shutil.copyfile(session.source, baseline_copy)
                baseline = {"supplied": True, "kind": "session_source",
                            "sha256": session.meta["sourceSha256"],
                            "reason": None}
        except OSError as exc:
            raise RpcError("capability_unavailable",
                           "could not stage a scratch copy of the document; the "
                           "checkers are never pointed at the session's own bytes",
                           detail=str(exc)[:MAX_DETAIL_CHARS]) from exc

        for entry in selected:
            subject_kind = entry.get("subject")
            if subject_kind is None:
                rows.append(_row(
                    entry, state="skipped", reason="subject_undeclared",
                    detail=("this checker's declaration does not say what its "
                            "positional argument is, so nothing here knows "
                            "whether a document may be handed to it")))
                continue
            if subject_kind != "document":
                rows.append(_row(
                    entry, state="skipped", reason="needs_workspace",
                    detail=("this checker takes a report workspace directory; a "
                            "Runtime session holds one document, which is not "
                            "one")))
                continue
            rows.append(_run_one(entry, subject_copy=subject_copy,
                                 baseline_copy=baseline_copy, cwd=scratch,
                                 timeout=seconds))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    ran = [row for row in rows if row["state"] == "ran"]
    skipped = [row for row in rows if row["state"] == "skipped"]
    unavailable = [row for row in rows if row["state"] == "unavailable"]
    partial = [row for row in ran if row.get("partial")]
    unclean = [row for row in ran if row["ok"] is not True]
    ran_all = bool(rows) and len(ran) == len(rows)

    if not rows:
        reason = "this module declares no checker to run"
    elif not ran_all:
        reason = "a selected checker did not run"
    elif partial:
        reason = "a checker ran without an input it declares it needs"
    elif unclean:
        reason = "a checker reported findings"
    else:
        reason = None

    return {
        "sessionId": session.id,
        "module": module,
        "modulesRoot": facts["modulesRoot"],
        "enabledFile": facts["enabledFile"],
        "subject": subject,
        "baseline": baseline,
        "selected": [row["checker"] for row in rows],
        "ranAll": ran_all,
        "acceptance": bool(ran_all and not partial and not unclean),
        "reason": reason,
        "checks": rows,
        "counts": {
            "selected": len(rows),
            "ran": len(ran),
            "skipped": len(skipped),
            "unavailable": len(unavailable),
            "partial": len(partial),
            "hard": sum(len([f for f in row.get("findings", [])
                             if f["severity"] == "hard"]) for row in ran),
            "warn": sum(len([f for f in row.get("findings", [])
                             if f["severity"] == "warn"]) for row in ran),
        },
        "bounds": {
            "perCheckerSeconds": seconds,
            "worstCaseSeconds": round(seconds * max(len(rows), 1), 3),
            "containment": "not_established",
        },
        "evidence": {
            "class": "structural_only",
            "note": ("checker verdicts over a scratch copy of the document; no "
                     "renderer ran and nothing here is a render proof"),
        },
        "note": ("acceptance asserts that every selected checker RAN, reported "
                 "clean, and had every input it declares it needs; a checker "
                 "that could not run is reported with a reason and is never "
                 "counted as a pass"),
    }
