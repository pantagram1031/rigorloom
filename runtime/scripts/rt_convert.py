#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""document/renderPrepare: make the PDF that document/render then rasterises.

This is the one place in the Runtime that can reach Hancom, and it is HOST-ONLY
for that reason. The whole chain is: a human clicks in the Desktop →
``renderPrepare`` converts the SESSION COPY to a PDF → ``document/render``
rasterises pages from it. No agent connection can start it.

FOUR HARD RULES, and the reasons they exist are in this repository's history:

1. **The user's original is never the input.** The conversion runs against
   ``<session>/source/…``, the copy ``workspace/openPath`` made. Hancom opens
   and re-saves documents; pointing it at the file the operator picked would
   put the one irreplaceable artifact under an automated editor.
2. **COM is serial, and we never make room.** ``tasklist`` is checked for an
   existing Hancom process and a live one is a refusal — ``com_busy`` — not a
   queue and certainly not a kill. ``engine/scripts/guards.py:234-240`` records
   what ``--kill-stale`` did the last time two sessions shared a machine: each
   one's ``taskkill /F /IM Hwp.exe`` killed the other's in-progress instance,
   four RPC crashes in a row. ``visual_verify`` states the same rule for the
   same reason (pipeline/scripts/visual_verify.py:57-63): "killing a live
   Hancom belongs to an operator, not to a verification loop". No flag here
   kills anything.
3. **The child is bounded like every other child.** Same ``run_child``, same
   environment allowlist, same timeout, same refusal-on-timeout. A conversion
   that hangs is a structured refusal, never a hung request.
4. **Absence is reported, not worked around.** No Hancom means
   ``needs_hancom`` with the reason, and ``capabilities.render.prepare`` says
   so before anyone clicks.

THE LIVE COM LEG IS NOT TESTED IN THIS SUITE. The repository forbids running
Hancom from tests, so the tests cover the probe, the busy refusal, the
absent-Hancom refusal, the non-convertible refusal, and the plumbing with the
convert step substituted by a prebuilt PDF. One live smoke on an operator
machine remains owed and is stated as owed.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import CHILD_TIMEOUT_SECONDS, RpcError  # noqa: E402
from rt_engine import child_python, run_child  # noqa: E402
from rt_session import atomic_write_bytes, now_utc, sha256_file  # noqa: E402

#: The same ProgIDs ``pipeline/scripts/render_probe.py:85`` looks for. One
#: predicate for "is Hancom here", not two that can disagree.
HWP_PROGIDS = ("HWPFrame.HwpObject", "HWPFrame.HwpObject.1",
               "HWPFrame.HwpObject.2")

#: Image names that mean a Hancom instance is already up. ``Hwp.exe`` is the
#: process ``--kill-stale`` used to kill (engine/scripts/guards.py:234), which
#: is exactly the thing we refuse to do.
HANCOM_IMAGE_NAMES = ("hwp.exe",)

#: Formats a conversion can start from.
CONVERTIBLE_SUFFIXES = (".hwpx", ".hwp")

#: Where a prepared PDF lands inside the session, and how it is recorded.
DERIVED_DIRNAME = "derived"
DERIVED_PDF_NAME = "source.pdf"
#: Hancom is slower than a form scan; give it its own bound rather than
#: borrowing the generic child timeout.
CONVERT_TIMEOUT_SECONDS = 300.0
MIN_CONVERT_TIMEOUT = 30.0
MAX_CONVERT_TIMEOUT = 900.0

TASKLIST_TIMEOUT_SECONDS = 30.0


def hancom_facts() -> dict:
    """Is Hancom reachable from this interpreter? winreg only, no subprocess.

    Three things must all hold, and the answer names which one failed:
    Windows, ``pyhwpx`` importable (``com_backend`` needs it), and one of the
    HWP ProgIDs registered.
    """
    if sys.platform != "win32":
        return {"state": "no", "reason": "not Windows; Hancom COM is win32 only",
                "progid": None, "pyhwpx": False}
    has_pyhwpx = importlib.util.find_spec("pyhwpx") is not None
    progid = None
    try:
        import winreg

        for candidate in HWP_PROGIDS:
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, candidate):
                    progid = candidate
                    break
            except OSError:
                continue
    except ImportError:  # pragma: no cover - winreg exists on win32
        progid = None
    if not has_pyhwpx:
        return {"state": "no",
                "reason": "pyhwpx is not importable; the COM backend needs it",
                "progid": progid, "pyhwpx": False}
    if progid is None:
        return {"state": "no",
                "reason": "no HWP COM ProgID is registered; Hancom does not "
                          "appear to be installed",
                "progid": None, "pyhwpx": True}
    return {"state": "yes", "reason": None, "progid": progid, "pyhwpx": True}


def running_hancom_processes() -> dict:
    """Exact ``tasklist`` image-name check. Never kills, never guesses.

    An unreadable answer counts as BUSY, not as free: the failure mode of
    guessing wrong here is starting a second Hancom beside somebody's live
    one, and this repository has already paid for that once.
    """
    if sys.platform != "win32":
        return {"state": "no", "processes": [], "reason": "not Windows"}
    result = run_child(["tasklist", "/FO", "CSV", "/NH"],
                       timeout=TASKLIST_TIMEOUT_SECONDS)
    if result.timed_out or result.returncode != 0:
        return {"state": "unknown", "processes": [],
                "reason": f"tasklist exited {result.returncode}"
                          + (" after timing out" if result.timed_out else "")}
    found = []
    text = result.stdout.decode("utf-8", errors="replace")
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        image = (row[0] or "").strip()
        if image.lower() in HANCOM_IMAGE_NAMES:
            pid = row[1].strip() if len(row) > 1 else None
            found.append({"image": image, "pid": pid})
    return {"state": "yes" if found else "no", "processes": found,
            "reason": None}


def prepare_capability() -> dict:
    """``capabilities.render.prepare`` — can this machine make a PDF at all?"""
    hancom = hancom_facts()
    return {
        "state": hancom["state"],
        "reason": hancom["reason"],
        "method": "document/renderPrepare",
        "authority": "host",
        "backend": "engine/scripts/com_backend.py convert",
        "progid": hancom["progid"],
        "convertibleFrom": list(CONVERTIBLE_SUFFIXES),
        "serial": ("one Hancom at a time; a live instance is refused with "
                   "com_busy and never terminated"),
        "liveSmoke": "not run in the test suite; COM is forbidden there",
    }


def run_convert(tools, source: Path, target: Path, *,
                timeout: float = CONVERT_TIMEOUT_SECONDS) -> dict:
    """One bounded ``com_backend convert`` child. The only COM call there is.

    Substituted wholesale in tests — the suite may not start Hancom — which is
    why it is a module-level function with no cleverness in it: everything
    around it is exercised for real.
    """
    backend = tools.root / "engine" / "scripts" / "com_backend.py"
    if not backend.is_file():
        raise RpcError("capability_unavailable",
                       "engine/scripts/com_backend.py is not in this install",
                       tool="com_backend")
    argv = [child_python(), str(backend), "convert",
            "--file", str(source), "--to", str(target)]
    result = run_child(argv, timeout=timeout)
    return {
        "argv": ["com_backend.py", "convert"],
        "exitCode": result.returncode,
        "timedOut": result.timed_out,
        "stdout": result.text[:4000],
        "stderr": result.stderr.decode("utf-8", errors="replace")[:4000],
    }


def prepare_pdf(session, tools, *, timeout: float | None = None,
                candidate: dict | None = None) -> dict:
    """Convert the session copy — or one published candidate — to a PDF.

    Rule 1 of this module is unchanged and is why ``candidate`` is a resolved
    record rather than a path: the subject is either ``<session>/source/…`` or
    an artifact under ``<session>/candidates/<runId>/`` that ``read_receipt``
    already re-verified. Nothing a client sent is ever opened.

    Each subject gets its OWN prepared PDF, bound to that subject's digest, so
    a candidate's page can never be served for the source or the other way
    round — the same binding ``existing_pdf`` has always enforced, keyed per
    run instead of once per session.
    """
    if timeout is None:
        timeout = CONVERT_TIMEOUT_SECONDS
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise RpcError("invalid_params", "timeoutSeconds must be a number")
    if not MIN_CONVERT_TIMEOUT <= float(timeout) <= MAX_CONVERT_TIMEOUT:
        raise RpcError("invalid_params",
                       f"timeoutSeconds must be between {MIN_CONVERT_TIMEOUT} "
                       f"and {MAX_CONVERT_TIMEOUT}", timeoutSeconds=timeout,
                       min=MIN_CONVERT_TIMEOUT, max=MAX_CONVERT_TIMEOUT)

    if candidate is None:
        source = session.source
        subject_sha = session.meta["sourceSha256"]
        run_id = None
    else:
        source = candidate["path"]
        subject_sha = candidate["sha256"]
        run_id = candidate["runId"]

    if source.suffix.lower() not in CONVERTIBLE_SUFFIXES:
        raise RpcError("not_convertible",
                       f"a {source.suffix or 'extensionless'} source is not "
                       "something the converter takes",
                       suffix=source.suffix, runId=run_id,
                       convertibleFrom=list(CONVERTIBLE_SUFFIXES))

    existing = existing_pdf(session, run_id=run_id)
    if existing is not None:
        return {"sessionId": session.id, "prepared": False, "runId": run_id,
                "reason": "already prepared for these bytes",
                "pdf": existing}

    hancom = hancom_facts()
    if hancom["state"] != "yes":
        raise RpcError("needs_hancom",
                       "this machine cannot produce a PDF: " + hancom["reason"],
                       hancom=hancom, runId=run_id,
                       capability=prepare_capability())

    busy = running_hancom_processes()
    if busy["state"] != "no":
        # Refuse. Do not queue, do not kill. See rule 2 in the module docstring.
        raise RpcError("com_busy",
                       "a Hancom instance is already running on this machine; "
                       "close it and try again — the Runtime will not "
                       "terminate somebody else's session",
                       processes=busy["processes"], state=busy["state"],
                       runId=run_id, reason=busy["reason"])

    derived = session.dir / DERIVED_DIRNAME
    derived.mkdir(parents=True, exist_ok=True)
    name = DERIVED_PDF_NAME if run_id is None else f"candidate-{run_id}.pdf"
    target = derived / name
    outcome = run_convert(tools, source, target, timeout=float(timeout))

    if outcome["timedOut"]:
        raise RpcError("convert_failed",
                       f"the conversion did not finish within {timeout}s",
                       timedOut=True, timeoutSeconds=timeout, runId=run_id,
                       **_tail(outcome))
    if outcome["exitCode"] != 0 or not target.is_file():
        raise RpcError("convert_failed",
                       f"the converter exited {outcome['exitCode']} and left no "
                       "usable PDF", timedOut=False, runId=run_id,
                       **_tail(outcome))

    digest, size = sha256_file(target)
    record = {
        "path": f"{DERIVED_DIRNAME}/{name}",
        "sha256": digest,
        "bytes": size,
        "producedBy": "engine/scripts/com_backend.py convert",
        "producedUtc": now_utc(),
        # Bound to the bytes it came from, so a derived PDF can never be served
        # for a document it does not describe — source or candidate.
        "sourceSha256": subject_sha,
        "runId": run_id,
    }
    _write_meta(session, record, run_id=run_id)
    return {"sessionId": session.id, "prepared": True, "pdf": record,
            "runId": run_id, "convert": {"exitCode": outcome["exitCode"]}}


def _tail(outcome: dict) -> dict:
    return {"exitCode": outcome["exitCode"],
            "stdout": outcome["stdout"][-1200:],
            "stderr": outcome["stderr"][-1200:]}


def _write_meta(session, record: dict, *, run_id: str | None = None) -> None:
    import json

    if run_id is None:
        session.meta["derivedPdf"] = record
    else:
        # A separate map, so a candidate's PDF can never be picked up as the
        # source's. `derivedPdf` keeps meaning exactly what it always meant.
        by_run = session.meta.get("derivedPdfByRun")
        if not isinstance(by_run, dict):
            by_run = {}
        by_run[run_id] = record
        session.meta["derivedPdfByRun"] = by_run
    atomic_write_bytes(
        session.meta_path,
        json.dumps(session.meta, ensure_ascii=False, indent=2,
                   sort_keys=True, allow_nan=False).encode("utf-8"))


def existing_pdf(session, *, run_id: str | None = None,
                 expect_sha256: str | None = None) -> dict | None:
    """A prepared PDF for THESE bytes, or nothing.

    The binding check is not ceremony: a session's source cannot change under
    the Runtime, but a root is a directory on a disk that other things can
    touch, and serving a PDF of some other document as this document's pages
    would be the worst possible failure of a viewer. A candidate's PDF is bound
    the same way, to the candidate's digest.
    """
    if run_id is None:
        record = (session.meta or {}).get("derivedPdf")
        expected = expect_sha256 or session.meta.get("sourceSha256")
    else:
        by_run = (session.meta or {}).get("derivedPdfByRun")
        record = by_run.get(run_id) if isinstance(by_run, dict) else None
        expected = expect_sha256
    if not isinstance(record, dict):
        return None
    if expected is not None and record.get("sourceSha256") != expected:
        return None
    path = session.dir / str(record.get("path") or "")
    if not path.is_file():
        return None
    try:
        digest, size = sha256_file(path)
    except OSError:
        return None
    if digest != record.get("sha256") or size != record.get("bytes"):
        return None
    return dict(record)
