#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime CLI — the same domain layer, driven by arguments instead of frames.

    python runtime/scripts/cli.py --root <dir> <command> [options]

The CLI is a front end over ``rt_core``, not a second implementation. A plan
proposed here and a plan proposed over the JSONL server are the same object,
with the same hash, validated by the same code and applied by the same code;
``tests/test_runtime_parity.py`` proves it against a corpus document rather
than asserting it in a comment. Front-end differences are exactly two: the
``proposer`` string a caller supplies, and the process exit code.

Output is ONE JSON document per invocation on stdout:

    {"ok": true,  "command": "...", "result": {...}}
    {"ok": false, "command": "...", "error": {"code": ..., "message": ...,
                                              "data": {...}}}

Diagnostics go to stderr. Exit codes:

    0  the command succeeded
    2  usage error — bad arguments, or params the domain calls malformed
    3  refusal — the domain said no (a stale plan, an unapproved plan, a
       backend refusal, an unavailable capability under --require-checks)
    4  internal error — a bug here, not a verdict

The three-value 0/2/3 contract is the repository's
(pipeline/scripts/checker_base.py:13-16). The fourth code is a deliberate
extension: a caller automating this must be able to tell "the Runtime refused"
from "the Runtime broke", and collapsing those into 3 hides the second.

A SUCCESSFUL EXIT DOES NOT MEAN VERIFICATION RAN. ``apply`` exits 0 when the
plan was applied and a candidate published; whether the offline checkers ran
is a separate fact, carried in ``result.candidate.checks`` as ``ranAll`` and
``acceptance``. Pass ``--require-checks`` to turn "a required check did not
run" into exit 3 — the candidate is still published and still named in the
payload, because refusing to report a thing that happened would be worse.
``verify`` is fail-closed by construction: it exits 3 when a required check
could not run.

``render`` follows the same rule from the other side: "there is no page image
for this document" is an ANSWER, not a failure, so it exits 0 and the payload
says ``available: false`` with a reason from a closed set. ``--require-render``
turns that into exit 3 for a caller that wants a picture or nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import (  # noqa: E402
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_USAGE,
    IMPL_VERSION,
    PROTOCOL_VERSION,
    SUPPORTED_BACKENDS,
    RpcError,
)
from rt_core import INCLUDE_SECTIONS, RuntimeCore  # noqa: E402
from rt_jsonl import log  # noqa: E402

#: A bug in this process, not a verdict about the document.
EXIT_INTERNAL = 4

#: Refusals that mean "you called it wrong", not "the answer is no".
USAGE_CODES = frozenset({"invalid_params", "unknown_field"})

CLIENT = "cli-client"


class UsageError(Exception):
    """Bad arguments discovered after argparse (exit 2)."""


def utf8_stdio() -> None:
    """Before parse_args, for the cp949 reason at engine/scripts/cli_io.py:3."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def emit(payload: dict, code: int) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2,
                                sort_keys=True, allow_nan=False) + "\n")
    sys.stdout.flush()
    return code


def _load_ops(args) -> list:
    ops: list = []
    if args.ops_file:
        try:
            payload = json.loads(Path(args.ops_file).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise UsageError(f"--ops-file is not readable JSON: {exc}") from exc
        if isinstance(payload, dict) and "ops" in payload:
            payload = payload["ops"]
        if not isinstance(payload, list):
            raise UsageError('--ops-file must hold an array, or an object with '
                             'an "ops" array')
        ops.extend(payload)
    for index, text in enumerate(args.op or ()):
        try:
            ops.append(json.loads(text))
        except ValueError as exc:
            raise UsageError(f"--op[{index}] is not valid JSON: {exc}") from exc
    if not ops:
        raise UsageError("propose needs --ops-file or at least one --op")
    return ops


def _parse_region(spec: str) -> dict:
    """``T:R,C`` / ``R,C`` / ``para:N`` -> a readRegion address."""
    text = spec.strip()
    lowered = text.lower()
    if lowered.startswith("para:"):
        try:
            return {"atPara": int(text.split(":", 1)[1])}
        except ValueError as exc:
            raise UsageError(f"--region {spec!r}: para:N needs an integer") from exc
    table = 0
    if ":" in text:
        head, _, text = text.partition(":")
        try:
            table = int(head)
        except ValueError as exc:
            raise UsageError(f"--region {spec!r}: table index must be an integer"
                             ) from exc
    row, comma, col = text.partition(",")
    if not comma:
        raise UsageError(f"--region {spec!r}: expected T:R,C, R,C or para:N")
    try:
        return {"table": table, "row": int(row), "col": int(col)}
    except ValueError as exc:
        raise UsageError(f"--region {spec!r}: row and col must be integers") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runtime/scripts/cli.py",
        description="Drive the Runtime domain layer from the command line. "
                    "One JSON document per invocation on stdout.")
    parser.add_argument("--root", required=True,
                        help="directory the Runtime may write under (sessions, "
                             "plans, approvals, candidates). No default, ever.")
    parser.add_argument("--engine-root", default=None,
                        help="repo root holding engine/scripts and "
                             "pipeline/scripts (default: this checkout)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("capabilities", help="what this build can do")
    sub.add_parser("sessions", help="list sessions under the root")

    p = sub.add_parser("open", help="validate and copy a document into a session")
    p.add_argument("--path", required=True, help="absolute path to the source")

    p = sub.add_parser("open-workspace",
                       help="validate and copy a report workspace DIRECTORY "
                            "into a session (host action; it reaches a tree)")
    p.add_argument("--path", required=True,
                   help="absolute path to the workspace directory")

    p = sub.add_parser("workspace",
                       help="which declared parts a workspace session has")
    p.add_argument("--session", required=True)
    p.add_argument("--require-parts", action="store_true",
                   help="exit 3 when a declared-required part is absent "
                        "(default: exit 0 and report per part, which is an "
                        "answer)")

    p = sub.add_parser("inspect", help="summary, graph and editable regions")
    p.add_argument("--session", required=True)
    p.add_argument("--include", default=None,
                   help=f"comma-separated subset of {','.join(INCLUDE_SECTIONS)}")

    p = sub.add_parser("read-region", help="exact text and runs for named regions")
    p.add_argument("--session", required=True)
    p.add_argument("--region", action="append", required=True,
                   metavar="T:R,C|R,C|para:N",
                   help="region address (repeatable)")

    p = sub.add_parser("render", help="a page image, or why there cannot be one")
    p.add_argument("--session", required=True)
    p.add_argument("--page", type=int, default=0, help="0-based page index")
    p.add_argument("--dpi", type=int, default=None)
    p.add_argument("--run", default=None,
                   help="render a published candidate instead of the source")
    p.add_argument("--no-inline", action="store_true",
                   help="never inline the PNG; report only its path")
    p.add_argument("--require-render", action="store_true",
                   help="exit 3 when no page image is possible (default: exit 0 "
                        "and report the unavailable state, which is an answer)")

    p = sub.add_parser("geometry",
                       help="text positions on a page, mapped to addresses")
    p.add_argument("--session", required=True)
    p.add_argument("--page", type=int, default=0)
    p.add_argument("--run", default=None)
    p.add_argument("--require-geometry", action="store_true",
                   help="exit 3 when no geometry is possible (default: exit 0 "
                        "and report the unavailable state, which is an answer)")

    p = sub.add_parser("render-prepare",
                       help="convert the session copy to a PDF so render can "
                            "raster it (host action; needs Hancom)")
    p.add_argument("--session", required=True)
    p.add_argument("--timeout", type=float, default=None,
                   help="seconds to allow the converter")

    p = sub.add_parser("events", help="read the session event log")
    p.add_argument("--session", required=True)
    p.add_argument("--after", type=int, default=-1,
                   help="return events with seq > after; -1 replays all")
    p.add_argument("--limit", type=int, default=None)

    sub.add_parser("modules",
                   help="distribution modules on disk and what they contribute")

    p = sub.add_parser("module-check",
                       help="run a distribution module's checkers against a "
                            "session's document")
    p.add_argument("--session", required=True)
    p.add_argument("--module", required=True,
                   help="distribution module name (see the modules command)")
    p.add_argument("--checker", action="append", default=None, metavar="NAME",
                   help="run only this checker (repeatable; default: all the "
                        "module declares)")
    p.add_argument("--run", default=None,
                   help="check a published candidate instead of the session "
                        "source; the source is then supplied as its baseline")
    p.add_argument("--timeout", type=float, default=None,
                   help="seconds to allow EACH checker")
    p.add_argument("--require-checks", action="store_true",
                   help="exit 3 unless every selected checker ran, was clean "
                        "and had every input it declares it needs")

    p = sub.add_parser("propose", help="build an OperationPlan")
    p.add_argument("--session", required=True)
    p.add_argument("--backend", default=SUPPORTED_BACKENDS[0])
    p.add_argument("--op", action="append", metavar="JSON",
                   help="one op object as JSON (repeatable)")
    p.add_argument("--ops-file", default=None,
                   help='JSON array of ops, or an object with an "ops" array')
    p.add_argument("--proposer", default=CLIENT)

    p = sub.add_parser("validate", help="validate a plan without executing it")
    p.add_argument("--plan", required=True)

    p = sub.add_parser("plan", help="read a plan back")
    p.add_argument("--plan", required=True)

    p = sub.add_parser("request-approval", help="open an approval for a plan")
    p.add_argument("--plan", required=True)
    p.add_argument("--requested-by", default=CLIENT)

    p = sub.add_parser("approval", help="read an approval back")
    p.add_argument("--approval", required=True)

    for name, decision in (("approve", "approved"), ("reject", "rejected")):
        p = sub.add_parser(name, help=f"resolve an approval as {decision}")
        p.add_argument("--approval", required=True)
        p.add_argument("--plan", required=True)
        p.add_argument("--plan-hash", required=True,
                       help="the plan hash this decision binds; a mismatch is "
                            "refused")
        p.add_argument("--approver", default="cli-operator")
        p.set_defaults(decision=decision)

    p = sub.add_parser("apply", help="execute an approved plan, publish a candidate")
    p.add_argument("--plan", required=True)
    p.add_argument("--approval", required=True)
    p.add_argument("--require-checks", action="store_true",
                   help="exit 3 when a required offline check did not run "
                        "(the candidate is still published and still reported)")

    p = sub.add_parser("candidates", help="published candidates for a session")
    p.add_argument("--session", required=True)

    p = sub.add_parser("receipt", help="read a receipt; refuses on byte drift")
    p.add_argument("--session", required=True)
    p.add_argument("--run", required=True)

    p = sub.add_parser("verify", help="re-run the offline checks; fail closed")
    p.add_argument("--session", required=True)
    p.add_argument("--run", required=True)

    return parser


def dispatch(core: RuntimeCore, args) -> tuple[dict, int]:
    command = args.command
    if command == "capabilities":
        from rt_core import METHODS
        return {"protocolVersion": PROTOCOL_VERSION, "implVersion": IMPL_VERSION,
                **core.capability_snapshot(methods=list(METHODS))}, EXIT_OK
    if command == "open":
        return core.open_path(args.path), EXIT_OK
    if command == "open-workspace":
        return core.open_workspace(args.path), EXIT_OK
    if command == "workspace":
        result = core.workspace_inspect(args.session)
        # An absent part is an ANSWER — a workspace at stage 2 has no
        # output/out.pdf and saying so is the point — so it exits 0 by default.
        if args.require_parts and result["layout"]["counts"]["absentRequired"]:
            return result, EXIT_REFUSED
        return result, EXIT_OK
    if command == "sessions":
        return core.session_list(), EXIT_OK
    if command == "inspect":
        include = ([item.strip() for item in args.include.split(",") if item.strip()]
                   if args.include else None)
        return core.document_inspect(args.session, include), EXIT_OK
    if command == "read-region":
        regions = [_parse_region(spec) for spec in args.region]
        return core.document_read_region(args.session, regions), EXIT_OK
    if command == "render":
        result = core.document_render(args.session, page=args.page,
                                      dpi=args.dpi, run_id=args.run,
                                      inline=not args.no_inline)
        if args.require_render and not result["available"]:
            return result, EXIT_REFUSED
        return result, EXIT_OK
    if command == "geometry":
        result = core.document_page_geometry(args.session, page=args.page,
                                             run_id=args.run)
        if args.require_geometry and not result["available"]:
            return result, EXIT_REFUSED
        return result, EXIT_OK
    if command == "render-prepare":
        return core.document_render_prepare(args.session,
                                            timeout=args.timeout), EXIT_OK
    if command == "events":
        return core.event_poll(args.session, after=args.after,
                               limit=args.limit), EXIT_OK
    if command == "modules":
        return core.module_list(), EXIT_OK
    if command == "module-check":
        result = core.module_check(args.session, args.module,
                                   checkers=args.checker, run_id=args.run,
                                   timeout=args.timeout)
        # A findings report is an ANSWER, so it exits 0 by default: the caller
        # asked what the checkers say, and they said it. --require-checks is
        # for the caller who wants the acceptance to be the exit code.
        if args.require_checks and not result["acceptance"]:
            return result, EXIT_REFUSED
        return result, EXIT_OK
    if command == "propose":
        return core.plan_propose(args.session, args.backend, _load_ops(args),
                                 args.proposer), EXIT_OK
    if command == "validate":
        return core.plan_validate(args.plan), EXIT_OK
    if command == "plan":
        return core.plan_get(args.plan), EXIT_OK
    if command == "request-approval":
        return core.approval_request(args.plan, args.requested_by), EXIT_OK
    if command == "approval":
        return core.approval_get(args.approval), EXIT_OK
    if command in ("approve", "reject"):
        return core.approval_resolve(args.approval, args.plan, args.plan_hash,
                                     args.decision, args.approver), EXIT_OK
    if command == "apply":
        result = core.plan_apply(args.plan, args.approval)
        checks = result["candidate"]["checks"]
        if args.require_checks and not checks["ranAll"]:
            # Exit 3, and still report the candidate: it exists, and hiding
            # that would be a worse lie than the one --require-checks guards.
            return result, EXIT_REFUSED
        return result, EXIT_OK
    if command == "candidates":
        return core.candidate_list(args.session), EXIT_OK
    if command == "receipt":
        return core.receipt_read(args.session, args.run), EXIT_OK
    if command == "verify":
        result = core.candidate_verify(args.session, args.run)
        # Fail closed: a check that could not run is never a pass
        # (pipeline/scripts/privacy_scan.py:16-25).
        return result, EXIT_OK if result["checks"]["ranAll"] else EXIT_REFUSED
    raise UsageError(f"unknown command {command!r}")


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command
    root = Path(args.root).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return emit({"ok": False, "command": command,
                     "error": {"code": "invalid_params",
                               "message": f"--root is not usable: {exc}"}},
                    EXIT_USAGE)
    try:
        core = RuntimeCore(root, args.engine_root)
        result, code = dispatch(core, args)
    except UsageError as exc:
        return emit({"ok": False, "command": command,
                     "error": {"code": "invalid_params", "message": str(exc)}},
                    EXIT_USAGE)
    except RpcError as exc:
        return emit({"ok": False, "command": command,
                     "error": exc.to_frame_error()},
                    EXIT_USAGE if exc.code in USAGE_CODES else EXIT_REFUSED)
    except Exception as exc:  # noqa: BLE001 - a bug must not look like a verdict
        import traceback
        log("runtime cli internal error:\n" + traceback.format_exc())
        return emit({"ok": False, "command": command,
                     "error": {"code": "internal_error",
                               "message": f"{type(exc).__name__}: see stderr"}},
                    EXIT_INTERNAL)
    return emit({"ok": code == EXIT_OK, "command": command, "result": result}, code)


if __name__ == "__main__":
    raise SystemExit(main())
