#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The composer's round trip, at the protocol layer, without the app.

WHY THIS EXISTS ALONGSIDE `smoke.ps1`. The scripted smoke drives the BUILT
application and is the evidence that matters; this drives the same three
processes the application drives — the Runtime on a host connection, the Agent
Host on an agent connection, and the module registry — and asserts the same
properties without needing a release build. It is what to run when the app
cannot be built (a machine with no Rust toolchain, or, as on the machine this
was written on, no disk), and it is what to run first when the smoke's composer
phase fails, because it says whether the failure is in the shell or underneath
it.

What it asserts, in the order the application does it:

  1. a host opens a document. Neither the Agent Host nor its provider can.
  2. the Agent Host proposes over an AGENT connection, and stops.
  3. the plan it left is readable over a HOST connection — which is what the
     desktop's review queue shows, and what an approval will bind to.
  4. `approval/resolve` and `plan/apply` are absent from the agent's registry.
     Asserted twice: from the host's own `neverCompiled`, and by CALLING them
     on an agent connection and requiring `unknown_method`.
  5. a human resolves the approval and applies. The candidate has its own
     sha256 and the source's has not moved.
  6. the receipt records the agent as requester and the human as approver.
  7. a credential REFERENCE resolves from the child's environment, the
     capability payload says `present`, and the value appears in neither the
     config file nor the payload.
  8. a config carrying a secret-shaped member is refused by NAME.

    python desktop/scripts/agent_roundtrip.py
    python desktop/scripts/agent_roundtrip.py --keep

Exit codes: 0 every assertion held · 3 one did not · 2 could not run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "runtime" / "scripts" / "cli.py"
HOST = REPO / "agenthost" / "scripts" / "host.py"
REGISTRY = REPO / "pipeline" / "scripts" / "module_registry.py"
CORPUS = REPO / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"

#: Obviously not a credential. The point of the check is that a value put where
#: a credential goes never reaches a file or a payload, and proving that needs a
#: value distinctive enough to find. Same string as `smoke.ts`.
SENTINEL = "NOT-A-REAL-KEY-SENTINEL-4f3a9c7e21"
CHILD_ENV = "RIGORLOOM_PROVIDER_CREDENTIAL"

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: object = "") -> bool:
    checks.append((name, bool(ok), str(detail)))
    return bool(ok)


def run(argv: list[str], env: dict | None = None) -> tuple[int, str, str]:
    environ = dict(os.environ)
    environ.setdefault("PYTHONIOENCODING", "utf-8")
    environ.setdefault("PYTHONUTF8", "1")
    if env:
        environ.update(env)
    proc = subprocess.run([sys.executable, *argv], capture_output=True,
                          text=True, encoding="utf-8", env=environ)
    return proc.returncode, proc.stdout, proc.stderr


def cli(root: Path, *args: str) -> dict:
    """One host-authority CLI call, parsed. The CLI wraps in {ok, result}."""
    code, out, err = run([str(CLI), "--root", str(root), "--engine-root", str(REPO), *args])
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return {"ok": False, "exit": code, "stderr": err[-800:], "raw": out[-400:]}
    payload["exit"] = code
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="leave the scratch root behind")
    args = parser.parse_args(argv)

    for path in (CLI, HOST, REGISTRY, CORPUS):
        if not path.is_file():
            print(f"cannot run: missing {path}", file=sys.stderr)
            return 2

    root = Path(tempfile.mkdtemp(prefix="rigorloom-agent-roundtrip-"))
    try:
        return drive(root)
    finally:
        if args.keep:
            print(f"\nscratch root kept at {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


def drive(root: Path) -> int:
    # 1. A host opens the document.
    opened = cli(root, "open", "--path", str(CORPUS))
    check("a host opened the corpus form", opened.get("ok") is True, opened.get("exit"))
    # `workspace/openPath` returns the session fields at the top of `result`;
    # some earlier readers expected a `session` wrapper, so accept either
    # rather than depending on which one this build speaks.
    result = opened.get("result") or {}
    session = result.get("session") or result
    session_id = session.get("sessionId")
    source_sha = (session.get("source") or {}).get("sha256", "")
    if not check("the session has a source sha256", len(source_sha) == 64, source_sha):
        return report()

    # 2. The Agent Host runs on an AGENT connection and stops.
    events = root / "agenthost-events.jsonl"
    code, out, err = run([
        str(HOST), "--root", str(root), "--session", session_id,
        "--provider", "mock", "--scenario", "propose-one", "--door", "protocol",
        "--engine-root", str(REPO), "--events", str(events),
        "--instruction", "Fill the first editable seat and ask a human to approve it.",
    ])
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        check("the agent host emitted one JSON document", False, err[-600:])
        return report()
    check("the agent host exited 0", code == 0, code)
    check("the agent host reported ok", payload.get("ok") is True,
          json.dumps(payload.get("error") or payload.get("providerFault")))

    # The live event mirror the desktop tails.
    lines = [json.loads(line) for line in
             events.read_text(encoding="utf-8").splitlines() if line.strip()]
    check("the event mirror was written as the run happened", len(lines) > 0, len(lines))
    check("its seq is the line index, gap-free",
          all(row["seq"] == index for index, row in enumerate(lines)),
          [row["seq"] for row in lines][:12])
    check("it opens and closes with the run",
          bool(lines) and lines[0]["kind"] == "run.started"
          and lines[-1]["kind"] == "run.finished",
          f"{lines[0]['kind'] if lines else '-'} … {lines[-1]['kind'] if lines else '-'}")

    plan_id = ((payload.get("plan") or {}).get("planId"))
    approval = payload.get("approval") or {}
    check("the agent host proposed a plan", bool(plan_id), plan_id)
    check("and left its approval PENDING", approval.get("state") == "pending",
          json.dumps(approval))
    check("the approval names the agent as requester",
          approval.get("requestedBy") == "agenthost-mock", approval.get("requestedBy"))
    check("the host names the methods its gate will never compile",
          "approval/resolve" in (payload.get("neverCompiled") or [])
          and "plan/apply" in (payload.get("neverCompiled") or []),
          payload.get("neverCompiled"))
    if not plan_id:
        return report()

    # 3. The plan is readable over a HOST connection — the review queue's copy.
    got = cli(root, "plan", "--plan", plan_id)
    plan = (got.get("result") or {}).get("plan") or {}
    check("the plan reads back over a host connection", got.get("ok") is True, got.get("exit"))
    check("bound to the bytes the session holds", plan.get("boundSha256") == source_sha,
          plan.get("boundSha256"))
    check("proposed by the agent host, and it says so",
          plan.get("proposer") == "agenthost-mock", plan.get("proposer"))
    validated = cli(root, "validate", "--plan", plan_id)
    validation = (validated.get("result") or {}).get("validation") or {}
    check("it validates over the host connection", validation.get("ok") is True,
          json.dumps(validation.get("hard")))

    # 4. The authority split, measured on the agent connection itself.
    #    `neverCompiled` is the host's claim; this is the Runtime's answer.
    refused = agent_call_refused(root, session_id, plan_id)
    check("approval/resolve is unknown on an agent connection",
          refused.get("approval/resolve") == "unknown_method",
          refused.get("approval/resolve"))
    check("plan/apply is unknown on an agent connection",
          refused.get("plan/apply") == "unknown_method", refused.get("plan/apply"))

    # 5. A human resolves and applies.
    plan_hash = plan.get("planHash")
    approved = cli(root, "approve", "--approval", approval["approvalId"],
                   "--plan", plan_id, "--plan-hash", plan_hash,
                   "--approver", "roundtrip-operator")
    record = (approved.get("result") or {}).get("approval") or {}
    check("a human resolved the agent's approval", record.get("state") == "approved",
          json.dumps(record))
    applied = cli(root, "apply", "--plan", plan_id, "--approval", approval["approvalId"])
    candidate = (applied.get("result") or {}).get("candidate") or {}
    run_id = candidate.get("runId")
    candidate_sha = (candidate.get("candidate") or {}).get("sha256", "")
    check("the plan applied and published a candidate", applied.get("ok") is True,
          json.dumps(applied.get("error") or {}))
    check("the candidate has its own sha256", len(candidate_sha) == 64, candidate_sha)
    check("and it is not the source's", candidate_sha != source_sha, candidate_sha[:16])

    listed = cli(root, "sessions")
    rows = (listed.get("result") or {}).get("sessions") or []
    current = next((row for row in rows if row["sessionId"] == session_id), {})
    check("the source sha256 did not move",
          (current.get("source") or {}).get("sha256") == source_sha, source_sha[:16])

    # 6. The receipt binds who asked and who decided.
    receipt = cli(root, "receipt", "--session", session_id, "--run", run_id)
    body = (receipt.get("result") or {}).get("receipt") or {}
    check("the receipt reads back and re-hashes clean", receipt.get("ok") is True,
          json.dumps(receipt.get("error") or {}))
    check("it records the agent host as requester",
          (body.get("approval") or {}).get("requestedBy") == "agenthost-mock",
          json.dumps(body.get("approval")))
    check("and the human as approver",
          (body.get("approval") or {}).get("approver") == "roundtrip-operator",
          json.dumps(body.get("approval")))

    credential_checks(root)
    task_pack_checks()
    return report()


def agent_call_refused(root: Path, session_id: str, plan_id: str) -> dict:
    """Call the two host-only methods on an AGENT connection and record the code.

    Through `mock_agent.open_door`, which is the same door the Agent Host uses,
    so this is the registry the agent really has rather than a second one built
    for the test.
    """
    sys.path.insert(0, str(REPO / "runtime" / "scripts"))
    from mock_agent import DoorRefusal, open_door  # noqa: E402

    door = open_door("protocol", root, REPO, None)
    out: dict[str, str] = {}
    try:
        for method, params in (
            ("approval/resolve", {"approvalId": "x", "planId": plan_id,
                                  "planHash": "x", "decision": "approved",
                                  "approver": "nobody"}),
            ("plan/apply", {"planId": plan_id, "approvalId": "x"}),
        ):
            try:
                door.call(method, params)
                out[method] = "ANSWERED — the boundary is gone"
            except DoorRefusal as exc:
                out[method] = exc.as_dict().get("code", "?")
    finally:
        door.close()
    _ = session_id
    return out


def credential_checks(root: Path) -> None:
    """The desktop's credential handoff, minus the OS store.

    The desktop reads the secret out of Windows Credential Manager and sets it
    on ONE child `Command`'s environment; the config names that variable. This
    exercises the second half — the half the Agent Host can see — and asserts
    the value reaches neither the config file nor the payload.
    """
    config_path = root / "anthropic.json"
    # header/scheme are part of the reference, not defaults to leave off:
    # CredentialRef falls back to `Authorization: Bearer`, which is right for
    # an OpenAI-compatible router and wrong for the Messages API. This mirrors
    # what `agenthost::compose_config` writes.
    config = {"model": "claude-opus-5",
              "credential": {"source": "env", "key": CHILD_ENV,
                             "header": "x-api-key", "scheme": "raw"}}
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    code, out, err = run([str(HOST), "--capabilities", "--provider", "anthropic",
                          "--config", str(config_path)],
                         env={CHILD_ENV: SENTINEL})
    check("--capabilities answers with a credential reference", code == 0, err[-400:])
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        check("the capability payload parses", False, out[-400:])
        return
    notes = ((payload.get("provider") or {}).get("notes") or {})
    # The adapter's own vocabulary, not one invented here:
    # not_required | configured | missing | unsupported
    # (`ah_anthropic.credential_state`). "configured" is decided by looking at
    # whether the variable is set, WITHOUT reading it.
    check("the adapter resolved the reference and says configured",
          (notes.get("credential") or {}).get("state") == "configured",
          json.dumps(notes.get("credential")))
    check("the reference names the header the Messages API actually wants",
          (notes.get("credential") or {}).get("scheme") == "raw"
          and (notes.get("credentialRef") or {}).get("key") == CHILD_ENV,
          json.dumps(notes.get("credentialRef")))
    check("the payload does not contain the value", SENTINEL not in out, "stdout")
    check("stderr does not contain the value", SENTINEL not in err, "stderr")
    check("the config file does not contain the value",
          SENTINEL not in config_path.read_text(encoding="utf-8"), str(config_path))

    # Three states, unrounded — what the settings pane renders.
    caps = (payload.get("provider") or {}).get("capabilities") or {}
    check("the profile names every capability", len(caps) == 7, sorted(caps))
    check("an unverified capability is unknown, not no",
          (caps.get("structuredOutput") or {}).get("state") == "unknown",
          json.dumps(caps.get("structuredOutput")))

    # And a config carrying a value is refused by NAME.
    bad = root / "bad.json"
    bad.write_text(json.dumps({"apiKey": "anything"}), encoding="utf-8")
    code, out, _ = run([str(HOST), "--capabilities", "--provider", "anthropic",
                        "--config", str(bad)])
    check("a secret-shaped config member is refused before anything runs",
          code != 0 and "apiKey" in out, f"exit {code}")


def task_pack_checks() -> None:
    """The 작업 팩 list is the module registry's own answer, not a second parser."""
    code, out, err = run([str(REGISTRY), "--modules-root", str(REPO / "modules"),
                          "--pyproject", str(REPO / "pyproject.toml"), "list"])
    check("the module registry lists the installed packs", code == 0, err[-300:])
    try:
        summary = json.loads(out)
    except json.JSONDecodeError:
        check("the registry emitted JSON", False, out[-300:])
        return
    check("six distribution modules are declared",
          len(summary.get("discovered") or []) >= 6, summary.get("discovered"))
    check("report declares its dependency on style",
          "style" in ((summary.get("requires_modules") or {}).get("report") or []),
          (summary.get("requires_modules") or {}).get("report"))
    names = {row.get("name") for row in summary.get("checkers") or []}
    check("the packs carry the checkers their manifests declare",
          "check_style" in names and "check_refs" in names, sorted(names)[:8])


def report() -> int:
    failed = [row for row in checks if not row[1]]
    for name, ok, detail in checks:
        mark = "PASS" if ok else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f"  — {detail}"
        print(line)
    print(f"\n  {len(checks) - len(failed)} passed, {len(failed)} failed")
    return 0 if not failed else 3


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
    raise SystemExit(main())
