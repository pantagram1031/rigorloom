#!/usr/bin/env python3
"""E3.2 Hancom acceptance harness — black-box, Automation-only, never promotes.

Proves (or, honestly, fails to prove) that a Rigorloom-written HWPX survives
what a legitimately licensed Hancom install actually does to it: open, save
to a new path, close, reopen, and come back with the edited text intact and
everything the edit did not touch structurally unchanged. Every check is
driven through official Automation (pyhwpx/COM) only — there is no XML
inspection standing in for "Hancom accepted this file".

Not proven anywhere in this module, and not claimable from a green run of it:
that the live COM leg has actually been exercised on this bench. See
``engine/references/owpml-writer-notes.md`` sec. 8 — E3.2 needs COM, and
whether THIS run had it is exactly what ``closed_reason`` in the emitted
verdict says.

Contract, stated because callers must not have to read the source to trust it:

* Always exits 3. This harness promotes nothing, ever — a verdict of all
  ``"pass"`` is still exit 3, because deciding what a passing verdict is
  *for* belongs to whoever calls this, not to the harness that measured it.
* Never modifies ``--source``. Its sha256 is taken before anything else runs
  and re-taken at the very end; a mismatch is reported, not silently trusted.
* Never launches Automation while an ``Hwp.exe`` process already exists
  (exact image-name match via ``tasklist``, not a substring scan) and never
  offers a way to kill one — attaching to, or clearing, a user's live
  document session is not this harness's call to make. When the check
  itself cannot run (no ``tasklist``, e.g. off Windows), that is treated the
  same as "cannot prove it is safe" and everything is skipped.
* When Hancom/COM is unavailable or busy, every check is ``"skipped"`` with
  a reason. Never a fabricated ``"pass"``.

CLI
---
    python hwpx_accept.py --source WRITTEN.hwpx --out OUT_DIR \\
        [--edit-marker "text the edit introduced"]

Writes ``OUT_DIR/accept.json`` and also prints it to stdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from cli_io import utf8_stdio  # noqa: E402
import hwpx_write  # noqa: E402
from com_backend import document_shape_reason  # noqa: E402

# ---------------------------------------------------------------------------
# verdict shape
# ---------------------------------------------------------------------------

#: Order matters: it is also the order checks run in, and a failed step
#: skips every name after it rather than attempting them.
CHECK_NAMES = (
    "open_no_repair",
    "save_new_path",
    "close",
    "reopen",
    "edit_preserved",
    "structures_preserved",
    "bindings_valid",
)


def _skip(reason, **extra):
    row = {"status": "skipped", "reason": reason}
    row.update(extra)
    return row


def _fail(reason, **extra):
    row = {"status": "fail", "reason": reason}
    row.update(extra)
    return row


def _pass(**extra):
    row = {"status": "pass"}
    row.update(extra)
    return row


def _new_verdict(source_path):
    return {
        # This harness never promotes; the field exists so a caller does not
        # have to infer "should I trust this" from exit code alone.
        "ok": False,
        "exit_code": 3,
        "source": str(source_path),
        "candidate": None,
        "source_sha256": None,
        "candidate_sha256": None,
        "edit_marker": None,
        "closed_reason": None,
        "checks": {name: _skip("not_run") for name in CHECK_NAMES},
        "notes": [],
    }


def _skip_all(verdict, reason, note=None):
    verdict["closed_reason"] = reason
    for name in CHECK_NAMES:
        verdict["checks"][name] = _skip(reason)
    if note:
        verdict["notes"].append(note)


def _skip_remaining(verdict, from_name, reason):
    started = False
    for name in CHECK_NAMES:
        if name == from_name:
            started = True
            continue
        if started:
            verdict["checks"][name] = _skip(reason)


def _candidate_path_for(source_path, out_dir):
    """Where the Hancom save-as target lands.

    A separate function so the "never overwrite the source" guard in
    :func:`run` is unit-testable directly (by construction, the naming here
    can never fold back onto ``source_path`` — appending
    ``.accept-candidate`` before the extension is not idempotent — but the
    guard stays as cheap insurance against a future change to this scheme).
    """
    return out_dir / (source_path.stem + ".accept-candidate.hwpx")


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# gate 1: never run against a live user session
# ---------------------------------------------------------------------------

#: Product code, not the test suite ``tests/test_subprocess_bounds.py`` polices
#: — that guard only scans ``test_*.py`` under ``testpaths``. Bounded anyway,
#: because a hung ``tasklist`` must not hang this harness.
TASKLIST_TIMEOUT_SECONDS = 20.0


def hwp_process_busy():
    """(True/False/None, detail). None means the check itself could not run.

    Exact image-name filter (``IMAGENAME eq Hwp.exe``), not a substring
    search over the process list — a process merely named similarly must not
    trip this. ``tasklist`` prints a localized "no tasks match" line to
    stdout (not CSV) when nothing matches, so presence is decided by the
    quoted CSV field actually containing ``"Hwp.exe"``, not by whether
    stdout is non-empty.

    Whatever the caller does with ``None``, it must not treat it as "not
    busy" — see the module docstring: this harness refuses to launch
    Automation whenever it cannot make the exact-name precheck confidently.
    """
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Hwp.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=TASKLIST_TIMEOUT_SECONDS,
            check=False)
    except Exception as exc:  # tasklist missing, PATH problem, non-Windows...
        return None, "tasklist_unavailable: %r" % (exc,)
    output = result.stdout or ""
    return ('"Hwp.exe"' in output), output.strip()


# ---------------------------------------------------------------------------
# COM session helpers — reuses the automation patterns com_backend.py already
# established (SetMessageBoxMode to prevent a modal dialog from hanging the
# call; ``hwp.Title`` as the one window-text probe pyhwpx exposes).
# ---------------------------------------------------------------------------

#: Best-effort net on top of the authoritative signal (``open()``'s own
#: boolean return). UNVERIFIED against a live Hancom install — this harness
#: has never run its COM leg (see module docstring / owpml-writer-notes.md
#: sec. 8). Extend or correct this once a live run has actually observed
#: what a silently-recovered document's title bar says; until then this is a
#: defensive addition, not the primary check.
_REPAIR_TITLE_MARKERS = ("복구",)


def _looks_like_repair(title):
    if not title:
        return False
    return any(marker in title for marker in _REPAIR_TITLE_MARKERS)


def _safe_title(hwp):
    try:
        return hwp.Title
    except Exception:
        return None


def _open_session(path):
    """A fresh ``Hwp()`` with a document opened. Raises on constructor/open error."""
    from pyhwpx import Hwp
    hwp = Hwp(visible=False)
    try:
        hwp.SetMessageBoxMode(0x00020000)  # auto-select the default button; never hang on a dialog
    except Exception:
        pass
    opened = hwp.open(str(Path(path).resolve()))
    return hwp, bool(opened)


def _quit_quietly(hwp):
    if hwp is None:
        return
    try:
        hwp.quit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# structural comparison — the repo's own lexical reader, not byte identity
# ---------------------------------------------------------------------------

def _qname_counts(package):
    counts = Counter()
    for part in package.xml_parts():
        for node in part.tree().iter():
            counts[node.qname] += 1
    return counts


def _section_local_count(package, local):
    total = 0
    for name in package.section_names():
        for _node in package.part(name).tree().iter_local(local):
            total += 1
    return total


def compare_structures(source_path, candidate_path):
    """Compare the reopened candidate's OWPML inventory to the source's.

    Uses ``hwpx_write.HwpxPackage`` / the lexical ``XmlNode`` model — the same
    reader E3.1 measured byte fidelity with — rather than a byte comparison:
    Hancom is free to touch bytes on a save it round-trips (deflate encoding,
    preview regeneration — see owpml-writer-notes.md sec. 5 and 8) so long as
    the document's element inventory and body structure do not drift.

    Policy, stated because it is a choice and not a measurement (no live
    Hancom acceptance run exists yet to calibrate it against): table and
    paragraph counts across ``Contents/section*.xml`` must match exactly
    between source and candidate. The full per-qname count delta is always
    attached to the result, pass or fail, so a human reading a FAIL can tell
    whether the drift is the edit itself or this policy being too strict.
    """
    source_pkg = hwpx_write.HwpxPackage.read(source_path)
    candidate_pkg = hwpx_write.HwpxPackage.read(candidate_path)

    source_counts = _qname_counts(source_pkg)
    candidate_counts = _qname_counts(candidate_pkg)
    all_qnames = set(source_counts) | set(candidate_counts)
    qname_delta = {
        qname: candidate_counts.get(qname, 0) - source_counts.get(qname, 0)
        for qname in all_qnames
        if candidate_counts.get(qname, 0) != source_counts.get(qname, 0)
    }

    source_tables = _section_local_count(source_pkg, "tbl")
    candidate_tables = _section_local_count(candidate_pkg, "tbl")
    source_paras = _section_local_count(source_pkg, "p")
    candidate_paras = _section_local_count(candidate_pkg, "p")

    extra = {
        "source_tables": source_tables, "candidate_tables": candidate_tables,
        "source_paragraphs": source_paras, "candidate_paragraphs": candidate_paras,
        "qname_count_delta": qname_delta,
    }
    if source_tables == candidate_tables and source_paras == candidate_paras:
        return _pass(**extra)
    return _fail("table_or_paragraph_count_drift", **extra)


def _full_text(hwp):
    if hasattr(hwp, "get_text_file"):
        return hwp.get_text_file("TEXT", "")
    return hwp.GetTextFile("TEXT", "")


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def run(source, out_dir, edit_marker=None):
    source_path = Path(source).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    verdict = _new_verdict(source_path)
    verdict["edit_marker"] = edit_marker

    if not source_path.exists():
        _skip_all(verdict, "source_missing")
        return verdict
    source_sha_before = _sha256_file(source_path)
    verdict["source_sha256"] = source_sha_before

    busy, detail = hwp_process_busy()
    if busy is None:
        _skip_all(verdict, "com_busy_check_unavailable", note=detail)
        return verdict
    if busy:
        _skip_all(verdict, "com_busy",
                  note="Hwp.exe already running; refusing to launch Automation "
                       "against a live user session")
        return verdict

    shape_reason = document_shape_reason(str(source_path))
    if shape_reason:
        verdict["checks"]["open_no_repair"] = _fail(
            "source_not_a_document", detail=shape_reason)
        _skip_remaining(verdict, "open_no_repair", "open_failed")
        return verdict

    try:
        import pyhwpx  # noqa: F401
    except ImportError:
        _skip_all(verdict, "com_unavailable", note="pyhwpx not installed")
        return verdict

    candidate_path = _candidate_path_for(source_path, out_dir)
    if candidate_path.resolve() == source_path.resolve():
        _skip_all(verdict, "candidate_path_collides_with_source")
        return verdict
    verdict["candidate"] = str(candidate_path)

    hwp = None
    hwp2 = None
    try:
        # (1) open — no repair/recovery dialog
        try:
            hwp, opened = _open_session(source_path)
        except Exception as exc:
            verdict["checks"]["open_no_repair"] = _fail(
                "open_raised", error=repr(exc))
            _skip_remaining(verdict, "open_no_repair", "open_failed")
            return verdict
        title = _safe_title(hwp)
        if not opened:
            verdict["checks"]["open_no_repair"] = _fail(
                "open_returned_false", title=title)
        elif _looks_like_repair(title):
            verdict["checks"]["open_no_repair"] = _fail(
                "repair_dialog_suspected", title=title)
        else:
            verdict["checks"]["open_no_repair"] = _pass(title=title)
        if verdict["checks"]["open_no_repair"]["status"] != "pass":
            _skip_remaining(verdict, "open_no_repair", "open_failed")
            return verdict

        # (2) save to a new path
        try:
            saved = hwp.save_as(str(candidate_path.resolve()), "HWPX")
        except Exception as exc:
            saved = False
            save_error = repr(exc)
        else:
            save_error = None
        candidate_exists = candidate_path.exists()
        if saved and candidate_exists:
            verdict["candidate_sha256"] = _sha256_file(candidate_path)
            verdict["checks"]["save_new_path"] = _pass(
                candidate_sha256=verdict["candidate_sha256"])
        else:
            verdict["checks"]["save_new_path"] = _fail(
                "save_as_failed", save_as_returned=bool(saved),
                candidate_exists=candidate_exists, error=save_error)
            _skip_remaining(verdict, "save_new_path", "save_failed")
            return verdict

        # (3) close
        try:
            hwp.quit()
            verdict["checks"]["close"] = _pass()
        except Exception as exc:
            verdict["checks"]["close"] = _fail("quit_raised", error=repr(exc))
        finally:
            hwp = None
        if verdict["checks"]["close"]["status"] != "pass":
            _skip_remaining(verdict, "close", "close_failed")
            return verdict

        # (4) reopen the saved file
        try:
            hwp2, reopened = _open_session(candidate_path)
        except Exception as exc:
            verdict["checks"]["reopen"] = _fail("reopen_raised", error=repr(exc))
            _skip_remaining(verdict, "reopen", "reopen_failed")
            return verdict
        title2 = _safe_title(hwp2)
        if not reopened:
            verdict["checks"]["reopen"] = _fail(
                "reopen_returned_false", title=title2)
        elif _looks_like_repair(title2):
            verdict["checks"]["reopen"] = _fail(
                "repair_dialog_suspected", title=title2)
        else:
            verdict["checks"]["reopen"] = _pass(title=title2)
        if verdict["checks"]["reopen"]["status"] != "pass":
            _skip_remaining(verdict, "reopen", "reopen_failed")
            return verdict

        # (5) edited content preserved
        if edit_marker is None:
            verdict["checks"]["edit_preserved"] = _skip("no_edit_description")
        else:
            try:
                full_text = _full_text(hwp2)
            except Exception as exc:
                verdict["checks"]["edit_preserved"] = _fail(
                    "text_read_failed", error=repr(exc))
            else:
                if edit_marker in full_text:
                    verdict["checks"]["edit_preserved"] = _pass()
                else:
                    verdict["checks"]["edit_preserved"] = _fail(
                        "edit_marker_not_found")

        _quit_quietly(hwp2)
        hwp2 = None

        # (6) unaffected structures preserved
        try:
            verdict["checks"]["structures_preserved"] = compare_structures(
                source_path, candidate_path)
        except Exception as exc:
            verdict["checks"]["structures_preserved"] = _fail(
                "inventory_compare_raised", error=repr(exc))

        # (7) source/candidate/receipt bindings valid
        source_sha_after = _sha256_file(source_path)
        verdict["source_sha256"] = source_sha_after
        if source_sha_after != source_sha_before:
            verdict["checks"]["bindings_valid"] = _fail(
                "source_mutated",
                source_sha256_before=source_sha_before,
                source_sha256_after=source_sha_after)
        else:
            verdict["checks"]["bindings_valid"] = _pass(
                source_sha256=source_sha_after,
                candidate_sha256=verdict["candidate_sha256"])
        return verdict
    finally:
        _quit_quietly(hwp)
        _quit_quietly(hwp2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="hwpx_accept.py",
        description=(
            "E3.2 Hancom acceptance harness: black-box, Automation-only proof "
            "that a Rigorloom-written HWPX survives a legitimately licensed "
            "Hancom install. Always exits 3 -- this harness never promotes."))
    parser.add_argument("--source", required=True,
                        help="the written HWPX to test; never modified")
    parser.add_argument("--out", required=True,
                        help="output directory for accept.json and the candidate save")
    parser.add_argument("--edit-marker", default=None,
                        help="substring expected in the reopened document's full "
                             "text; omitted means the edit-preserved check is "
                             "skipped rather than fabricated as a pass")
    return parser


def main(argv=None):
    utf8_stdio()
    args = build_arg_parser().parse_args(argv)
    verdict = run(args.source, args.out, edit_marker=args.edit_marker)
    out_path = Path(args.out) / "accept.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.write(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n")
    # Contract: this harness never promotes. Exit 3 regardless of verdict content.
    return 3


if __name__ == "__main__":
    sys.exit(main())
