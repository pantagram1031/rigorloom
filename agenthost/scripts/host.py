#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent Host CLI — run one provider turn-loop against an agent Runtime door.

    python agenthost/scripts/host.py --root <dir> --provider mock
    python agenthost/scripts/host.py --root <dir> --provider router \\
        --config router.json
    python agenthost/scripts/host.py --capabilities --provider mock

One JSON document on stdout, diagnostics on stderr. Exit codes match the
Runtime CLI's: 0 the run completed, 2 usage, 3 refusal or provider fault,
4 internal.

A provider fault exits 3 and says ``providerFault``; it never reports a
document verdict, and the run payload's ``plan``/``validation`` stay exactly
as far as the run actually got.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import (  # noqa: E402
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_USAGE,
    HOST_VERSION,
    AgentHostError,
)
from ah_events import EventLog  # noqa: E402
from ah_host import DEFAULT_MAX_TURNS, HOST_NAME, AgentHost, redact_run  # noqa: E402
from ah_mock import SCENARIOS, MockProvider  # noqa: E402
from ah_router import RouterAdapter, load_router_config  # noqa: E402

RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

from mock_agent import DOORS, open_door  # noqa: E402

PROVIDERS = ("mock", "router")

DEFAULT_INSTRUCTION = ("Fill the first editable seat in this form with the "
                       "agent-host marker, then ask a human to approve it.")

#: What each mock scenario is supposed to end up looking like. A fixture that
#: cannot say whether it did what it claimed is not a fixture.
MOCK_EXPECTATIONS = {
    "propose-one": "a validated plan and a pending approval",
    "propose-invalid": "validation refuses the target and no approval is opened",
    "propose-then-wait": "a validated plan and a pending approval",
    "escalate": "the compile layer refuses the apply request",
}


def check_expectation(scenario: str, payload: dict) -> bool:
    validation = payload.get("validation") or {}
    approval = payload.get("approval") or {}
    forbidden = [row for row in payload.get("refusals") or []
                 if row.get("code") == "tool_forbidden"]
    if scenario in ("propose-one", "propose-then-wait"):
        return (validation.get("ok") is True
                and approval.get("state") == "pending"
                and not forbidden)
    if scenario == "propose-invalid":
        return validation.get("ok") is False and not approval
    if scenario == "escalate":
        return (validation.get("ok") is True
                and approval.get("state") == "pending"
                and len(forbidden) == 1)
    return True


def utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def emit(payload: dict, code: int, *, do_redact: bool) -> int:
    document = redact_run(payload) if do_redact else payload
    sys.stdout.write(json.dumps(document, ensure_ascii=False, indent=2,
                                sort_keys=True, allow_nan=False) + "\n")
    sys.stdout.flush()
    return code


def build_provider(args):
    if args.provider == "mock":
        return MockProvider(scenario=args.scenario)
    config = load_router_config(args.config) if args.config else None
    if config is None:
        raise AgentHostError("config_invalid",
                             "--provider router needs --config naming a router "
                             "config file")
    return RouterAdapter(config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenthost/scripts/host.py",
        description="Run a provider turn-loop against an agent-authority "
                    "Runtime door. The host can propose and ask for approval; "
                    "it can never approve or apply.")
    parser.add_argument("--root", default=None,
                        help="the Runtime session-store root a host opened into")
    parser.add_argument("--session", default=None,
                        help="session id (default: first of the sorted list)")
    parser.add_argument("--provider", default=PROVIDERS[0], choices=list(PROVIDERS))
    parser.add_argument("--scenario", default=SCENARIOS[0], choices=list(SCENARIOS),
                        help="mock provider only")
    parser.add_argument("--config", default=None,
                        help="router config JSON (credential REFERENCE only)")
    parser.add_argument("--door", default=DOORS[0], choices=list(DOORS))
    parser.add_argument("--engine-root", default=None)
    parser.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--events", default=None,
                        help="also mirror the event log to this JSONL file")
    parser.add_argument("--capabilities", action="store_true",
                        help="print the provider's CapabilityProfile and exit; "
                             "no document, no root needed")
    parser.add_argument("--redact", action="store_true",
                        help="blank ids and timestamps for a golden document")
    parser.add_argument("--stderr-log", default=None,
                        help="write the child runtime's stderr here")
    return parser


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        provider = build_provider(args)
    except AgentHostError as exc:
        return emit({"ok": False, "host": HOST_NAME, "error": exc.as_dict()},
                    EXIT_USAGE, do_redact=args.redact)

    if args.capabilities:
        return emit({"ok": True, "host": HOST_NAME, "hostVersion": HOST_VERSION,
                     "provider": provider.capabilities().public()},
                    EXIT_OK, do_redact=args.redact)

    if not args.root:
        return emit({"ok": False, "host": HOST_NAME,
                     "error": {"code": "config_invalid",
                               "message": "--root is required unless "
                                          "--capabilities is given"}},
                    EXIT_USAGE, do_redact=args.redact)
    root = Path(args.root).expanduser()
    if not root.is_dir():
        return emit({"ok": False, "host": HOST_NAME,
                     "error": {"code": "config_invalid",
                               "message": f"--root does not exist: {root}"}},
                    EXIT_USAGE, do_redact=args.redact)

    door = None
    try:
        door = open_door(args.door, root, args.engine_root,
                         Path(args.stderr_log) if args.stderr_log else None)
        events = EventLog(args.events)
        host = AgentHost(door, provider, events, max_turns=args.max_turns)
        payload = host.run(args.instruction, args.session)
    except AgentHostError as exc:
        return emit({"ok": False, "host": HOST_NAME, "error": exc.as_dict()},
                    EXIT_REFUSED, do_redact=args.redact)
    except Exception as exc:  # noqa: BLE001 - a bug must not look like a verdict
        print("agent host internal error:\n" + traceback.format_exc(),
              file=sys.stderr, flush=True)
        return emit({"ok": False, "host": HOST_NAME,
                     "error": {"code": "host_internal_error",
                               "message": f"{type(exc).__name__}: see stderr"}},
                    EXIT_INTERNAL, do_redact=args.redact)
    finally:
        if door is not None:
            door.close()

    if args.provider == "mock":
        met = check_expectation(args.scenario, payload)
        payload["scenario"] = args.scenario
        payload["expectation"] = MOCK_EXPECTATIONS[args.scenario]
        payload["expectationMet"] = met
        payload["ok"] = payload["ok"] and met
    code = EXIT_OK if payload["ok"] else EXIT_REFUSED
    return emit(payload, code, do_redact=args.redact)


if __name__ == "__main__":
    raise SystemExit(main())
