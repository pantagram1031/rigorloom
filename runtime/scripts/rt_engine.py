#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded child adapters onto the EXISTING engine and pipeline entrypoints.

The Runtime adapts; it does not reimplement. Every document operation here
terminates in a script this repository already ships:

  * ``engine/scripts/form_inspect.py``   — profile / graph / regions (:1530)
  * ``engine/scripts/preedit.py``        — the offline typed edits (:2417)
  * ``pipeline/scripts/check_residue.py``— the offline residue gate (:770)

SUBPROCESS, NOT IMPORT — recorded choice, with reasons:

  1. crash isolation, which is the whole point of boundary B3 in
     docs/desktop-architecture.md;
  2. the engine scripts are not import-clean for a host process: they mutate
     ``sys.path`` at module scope and import each other by bare basename
     (``form_inspect`` does ``from preedit import ...`` at
     engine/scripts/form_inspect.py:92), so importing one would put
     ``engine/scripts`` permanently on the Runtime's path;
  3. their contract is already a process contract — one JSON object on stdout
     and an exit code in {0, 2, 3} (pipeline/scripts/checker_base.py:13-16).

HONEST LIMITATION, stated rather than hidden: this slice bounds a child's wall
clock and its captured output, and kills the direct child on timeout. It does
NOT establish descendant containment — there is no process group or Windows
Job here. ``pipeline/scripts/diagnostic_candidate_core.py:1128`` does that
properly and records the residual gap as
``DESCENDANT_CONTAINMENT = "not_established"``
(pipeline/scripts/renderer_runtime_v2.py:56). Wiring the Runtime onto that
primitive is Phase 2 work; claiming containment we did not implement would be
worse than the gap.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_codes import (  # noqa: E402
    CHILD_PYTHON_ENV,
    CHILD_TIMEOUT_SECONDS,
    MAX_CHILD_OUTPUT_BYTES,
    RpcError,
)

#: Hancom edit is slower than a form scan; same order as convert, not the
#: generic child bound.
COM_EDIT_TIMEOUT_SECONDS = 300.0

#: Engine ops JSON keys, first wave only. Runtime param names already match.
_COM_PARAM_KEYS: dict[str, tuple[str, ...]] = {
    "replace_all": ("find", "replace", "regex"),
    "goto_text": ("text", "after", "line_end", "cell_below", "next_para"),
    "insert_text": ("text", "pt", "segments", "break_after", "align"),
    "set_cell": ("addr", "text", "table", "expect_empty", "expect"),
    "insert_equation": ("latex", "hwpeqn", "display", "boxed",
                        "base_pt", "font", "box_height_mm"),
    "insert_picture": ("path", "width_mm", "height_mm",
                       "treat_as_char", "own_paragraph"),
    "insert_hyperlink": ("url", "text", "pt"),
}

_EQUATION_SOURCE_KEYS = frozenset({"latex", "hwpeqn", "script"})

#: Repo root = runtime/scripts/../..
DEFAULT_ENGINE_ROOT = Path(__file__).resolve().parents[2]

#: Environment allowlist, not inheritance. Same posture as
#: ``renderer_runtime_v2.ENV_POLICY = "minimal_allowlist_v1"``
#: (pipeline/scripts/renderer_runtime_v2.py:47). PYTHONPATH is deliberately
#: absent: a child must resolve its siblings the way it does on the CLI.
_ENV_KEYS_COMMON = ("PATH", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
_ENV_KEYS_WINDOWS = ("SYSTEMROOT", "SystemRoot", "COMSPEC", "PATHEXT",
                     "SYSTEMDRIVE", "WINDIR", "USERPROFILE", "APPDATA",
                     "LOCALAPPDATA", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
                     # Hancom's COM server resolves its shared configuration under
                     # %ProgramData%; without it CoCreateInstance(HWPFrame.HwpObject)
                     # fails inside the child even though the same script works from
                     # a full shell (measured 2026-09-16: ProgramData alone fixes it).
                     "ProgramData", "PROGRAMDATA")
_ENV_KEYS_POSIX = ("HOME",)


def child_python(environ: dict | None = None) -> str:
    """The interpreter engine children run under.

    ``sys.executable`` is wrong for a packaged host: in a frozen executable it
    IS the host, so every engine child re-launches the application. The desktop
    sidecar worked around that with an argv convention; this override removes
    the need for one. Set ``RIGORLOOM_CHILD_PYTHON`` to a real interpreter and
    children use it, with no other change anywhere.
    """
    environ = os.environ if environ is None else environ
    override = (environ.get(CHILD_PYTHON_ENV) or "").strip()
    return override or sys.executable


def child_python_facts(environ: dict | None = None) -> dict:
    """What interpreter children will use, and where that came from."""
    environ = os.environ if environ is None else environ
    override = (environ.get(CHILD_PYTHON_ENV) or "").strip()
    return {
        "path": override or sys.executable,
        "source": "override" if override else "sys.executable",
        "env": CHILD_PYTHON_ENV,
        "overrideSet": bool(override),
    }


def validate_child_python(environ: dict | None = None) -> dict:
    """Refuse a broken override up front, not on the first document call.

    An unset override is fine — that is the default path. A SET override that
    does not resolve to a file is a misconfiguration the operator must see at
    initialize, not as a mystifying ``capability_unavailable`` twenty seconds
    into the first inspect.
    """
    facts = child_python_facts(environ)
    if not facts["overrideSet"]:
        return facts
    candidate = Path(facts["path"]).expanduser()
    try:
        resolved = candidate if candidate.is_absolute() else candidate.resolve()
        ok = resolved.is_file()
    except OSError as exc:
        raise RpcError("child_python_invalid",
                       f"{CHILD_PYTHON_ENV} could not be checked: {exc}",
                       env=CHILD_PYTHON_ENV, path=facts["path"]) from exc
    if not ok:
        raise RpcError(
            "child_python_invalid",
            f"{CHILD_PYTHON_ENV} is set but names no file; engine children "
            "would fail on the first call",
            env=CHILD_PYTHON_ENV, path=facts["path"])
    facts["path"] = str(resolved)
    return facts


def child_env() -> dict[str, str]:
    keys = _ENV_KEYS_COMMON + (_ENV_KEYS_WINDOWS if os.name == "nt" else _ENV_KEYS_POSIX)
    env = {key: os.environ[key] for key in keys if key in os.environ}
    # The cp949 lesson (engine/scripts/cli_io.py:3): a Korean-locale console
    # kills --help and any non-ASCII JSON unless UTF-8 is forced.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


class ChildResult:
    __slots__ = ("argv", "returncode", "stdout", "stderr", "truncated", "timed_out")

    def __init__(self, argv, returncode, stdout, stderr, truncated, timed_out):
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.truncated = truncated
        self.timed_out = timed_out

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")


def run_child(argv: list[str], *, cwd: Path | None = None,
              timeout: float = CHILD_TIMEOUT_SECONDS,
              max_output: int = MAX_CHILD_OUTPUT_BYTES) -> ChildResult:
    """One bounded child. stdin is closed; stdout and stderr are drained apart."""
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
            env=child_env(),
        )
    except (OSError, ValueError) as exc:
        raise RpcError("capability_unavailable",
                       f"could not start {Path(argv[1]).name if len(argv) > 1 else argv[0]}",
                       detail=str(exc)) from exc

    sinks: dict[str, list[bytes]] = {"out": [], "err": []}
    over = {"out": False, "err": False}

    def drain(pipe, key):
        total = 0
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total <= max_output:
                    sinks[key].append(chunk)
                else:
                    over[key] = True
        except (OSError, ValueError):
            over[key] = True
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    threads = [threading.Thread(target=drain, args=(proc.stdout, "out"), daemon=True),
               threading.Thread(target=drain, args=(proc.stderr, "err"), daemon=True)]
    for thread in threads:
        thread.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    for thread in threads:
        thread.join(timeout=10)

    return ChildResult(
        list(argv),
        proc.returncode if proc.returncode is not None else -1,
        b"".join(sinks["out"]), b"".join(sinks["err"]),
        over["out"] or over["err"], timed_out,
    )


def redact_paths(text: str, *paths) -> str:
    """Replace absolute path forms with their basename. Longest first."""
    variants: list[tuple[str, str]] = []
    for path in paths:
        if path is None:
            continue
        candidate = Path(path)
        name = candidate.name or str(candidate)
        forms = [str(candidate), str(candidate).replace("/", "\\"),
                 str(candidate).replace("\\", "/")]
        try:
            resolved = candidate.resolve()
            forms.extend([str(resolved), str(resolved).replace("\\", "/"),
                          str(resolved).replace("/", "\\")])
        except OSError:
            pass
        for form in forms:
            if form:
                variants.append((form, name))
    variants.sort(key=lambda item: len(item[0]), reverse=True)
    out = text
    seen: set[str] = set()
    for form, name in variants:
        if form in seen:
            continue
        seen.add(form)
        out = out.replace(form, name)
    return out


def one_json_object(text: str) -> dict | None:
    """Exactly one JSON object, optionally preceded by non-JSON noise."""
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, end = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        return None
    if text[end:].strip():
        return None
    return obj if isinstance(obj, dict) else None


def strip_equation_source(value):
    """Drop latex/hwpeqn/script so a receipt cannot carry equation input."""
    if isinstance(value, dict):
        return {key: strip_equation_source(item)
                for key, item in value.items()
                if key not in _EQUATION_SOURCE_KEYS}
    if isinstance(value, list):
        return [strip_equation_source(item) for item in value]
    return value


def com_edit_argv(script, file, ops_path, save_as, export_pdf=None) -> list[str]:
    """The one argv shape: edit --file --ops --save-as [--export-pdf]. Never kill-stale."""
    argv = [child_python(), str(script), "edit",
            "--file", str(file),
            "--ops", str(ops_path),
            "--save-as", str(save_as)]
    if export_pdf is not None:
        argv += ["--export-pdf", str(export_pdf)]
    return argv


def stage_com_ops(ops: list, work_dir: Path) -> list[dict]:
    """Runtime plan ops → engine ops JSON list. Pictures land under work/assets/."""
    from rt_plan import COM_FIRST_WAVE, COM_FIRST_WAVE_SET  # noqa: PLC0415

    staged: list[dict] = []
    assets = Path(work_dir) / "assets"
    for op in ops:
        kind = op.get("kind") or op.get("op")
        if kind not in COM_FIRST_WAVE_SET:
            raise RpcError(
                "unknown_op_kind",
                f"op kind {kind!r} is deferred on the com backend in this wave",
                kind=kind, servedBy="com",
                knownKinds=list(COM_FIRST_WAVE))
        params = dict(op.get("params") or {})
        if kind == "insert_picture":
            src = Path(params.get("path") or "")
            if not src.is_file():
                raise RpcError(
                    "invalid_params",
                    "insert_picture path is not a file",
                    kind=kind, path=src.name or None)
            assets.mkdir(parents=True, exist_ok=True)
            dest = assets / src.name
            if dest.exists() and dest.resolve() != src.resolve():
                dest = assets / f"{dest.stem}-{uuid.uuid4().hex[:8]}{dest.suffix}"
            shutil.copyfile(src, dest)
            params["path"] = str(dest)
        row = {"op": kind}
        for key in _COM_PARAM_KEYS[kind]:
            if key in params:
                row[key] = params[key]
        staged.append(row)
    return staged


def write_com_ops_file(rows: list, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def _ops_kinds_from_file(ops_path: Path) -> list[str]:
    raw = json.loads(Path(ops_path).read_text(encoding="utf-8"))
    rows = raw.get("ops") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise RpcError("invalid_params", "COM ops file must be a list or {ops: [...]}",
                       path=Path(ops_path).name)
    kinds = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RpcError("invalid_params", f"ops[{index}] is not an object")
        kinds.append(row.get("op") or row.get("kind"))
    return kinds


#: Run in a bounded child with the engine root's ``pipeline/scripts`` on the
#: path. Derives the keep list with the ONE implementation that owns the
#: formula, then runs the gate with it, and reports both. Nothing here decides
#: residue on its own: every verdict field comes from ``check_residue.check``.
_DECLARATION_BRIDGE = r"""
import json, sys
request = json.loads(open(sys.argv[1], encoding="utf-8").read())
sys.path.insert(0, request["scripts"])
try:
    import check_residue, visual_verify
except Exception as exc:
    print(json.dumps({"ok": False, "code": "capability_unavailable",
                      "detail": "%s: %s" % (type(exc).__name__, exc)}))
    raise SystemExit(0)

profile = json.loads(open(request["profile"], encoding="utf-8").read())
raw_map = request.get("fillMap") or {}
flat, error = check_residue.normalize_fill_map(raw_map)
if error:
    print(json.dumps({"ok": False, "code": "invalid_params", "detail": error}))
    raise SystemExit(0)
scopes = check_residue.fill_map_scopes(raw_map)
haystack = check_residue.artifact_text(request["artifact"])

derived, consumed, unfilled = [], [], []
if flat:
    try:
        derived, consumed, unfilled = visual_verify.derive_form_keep(
            profile, flat, haystack, scopes)
    except visual_verify.AmbiguousFillKeyError as exc:
        print(json.dumps({"ok": False, "code": "ambiguous_fill_keys",
                          "detail": str(exc), "keys": exc.keys},
                         ensure_ascii=False))
        raise SystemExit(0)

keep = list(dict.fromkeys(list(derived) + list(request.get("keep") or [])))
pattern = request.get("keepPattern") or check_residue.DEFAULT_KEEP_PATTERN
try:
    forbidden, kept = check_residue.derive_forbidden(profile, pattern, keep)
except Exception as exc:
    print(json.dumps({"ok": False, "code": "invalid_params",
                      "detail": "%s: %s" % (type(exc).__name__, exc)}))
    raise SystemExit(0)
if not forbidden:
    print(json.dumps({"ok": False, "code": "exemption_too_broad",
                      "detail": "the declaration keeps every inventory entry, "
                                "so the residue gate would have nothing left to "
                                "judge and its pass would mean nothing",
                      "kept": len(kept)}, ensure_ascii=False))
    raise SystemExit(0)

verdict, code = check_residue.check(
    request["profile"], request["artifact"],
    keep_pattern=pattern, keep=tuple(keep), fill_map=flat or None)
print(json.dumps({"ok": True, "verdict": verdict, "exitCode": code,
                  "derivedKeep": list(derived), "rawKeep":
                  list(request.get("keep") or []),
                  "consumed": list(consumed), "unfilled": list(unfilled),
                  "forbiddenAfter": len(forbidden), "keptAfter": len(kept)},
                 ensure_ascii=False))
"""


def _com_missing_fact(hancom: dict, script_present: bool) -> str | None:
    """Which availability fact failed, or None when COM may be proposed."""
    if hancom.get("state") == "yes" and script_present:
        return None
    if hancom.get("state") != "yes":
        reason = hancom.get("reason") or ""
        if "not Windows" in reason:
            return "platform"
        if not hancom.get("pyhwpx"):
            return "pyhwpx"
        if not hancom.get("progid"):
            return "progid"
        return "hancom"
    return "script"


class EngineTools:
    """Resolved paths to the shipped entrypoints, with honest availability."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or DEFAULT_ENGINE_ROOT).resolve()
        self.form_inspect = self.root / "engine" / "scripts" / "form_inspect.py"
        self.preedit = self.root / "engine" / "scripts" / "preedit.py"
        self.check_residue = self.root / "pipeline" / "scripts" / "check_residue.py"
        self.com_backend = self.root / "engine" / "scripts" / "com_backend.py"

    def availability(self) -> dict[str, dict]:
        rows = {}
        for name, path in (("form_inspect", self.form_inspect),
                           ("preedit", self.preedit),
                           ("check_residue", self.check_residue),
                           ("com_backend", self.com_backend)):
            present = path.is_file()
            rows[name] = {
                "state": "available" if present else "unavailable",
                "reason": None if present else "script not found under the engine root",
                "path": path.relative_to(self.root).as_posix() if present else None,
            }
        return rows

    def com_capability(self) -> dict:
        """``capabilities.backends.com`` — produced, never a constant.

        ``available`` only when ``hancom_facts()["state"] == "yes"`` AND
        ``engine/scripts/com_backend.py`` resolves under this engine root.
        Does not start Hancom, does not import pyhwpx, does not spawn a child.
        """
        from rt_convert import hancom_facts  # noqa: PLC0415
        from rt_plan import COM_DEFERRED_OP_KINDS, COM_FIRST_WAVE  # noqa: PLC0415

        hancom = hancom_facts()
        script_present = self.com_backend.is_file()
        facts = {
            "platform": sys.platform,
            "pyhwpx": hancom["pyhwpx"],
            "progid": hancom["progid"],
        }
        missing = _com_missing_fact(hancom, script_present)
        available = missing is None
        if available:
            reason = None
        elif hancom["state"] != "yes":
            reason = hancom["reason"]
        else:
            reason = "engine/scripts/com_backend.py is not in this install"
        payload = {
            "state": "available" if available else "unavailable",
            "reason": reason,
            "opKinds": list(COM_FIRST_WAVE),
            "deferredOpKinds": sorted(COM_DEFERRED_OP_KINDS),
            "facts": facts,
        }
        if missing is not None:
            payload["missing"] = missing
        return payload

    def _residue_declared(self, profile: Path, artifact: Path,
                          declaration: dict) -> dict:
        """The declared path: derive, gate, and report what was exempted."""
        scripts = self.root / "pipeline" / "scripts"
        if not (scripts / "visual_verify.py").is_file():
            return {"checker": "check_residue", "state": "unavailable",
                    "reason": "pipeline/scripts/visual_verify.py is not in this "
                              "install, so the keep derivation this declaration "
                              "needs cannot run",
                    "verdict": None, "ok": None}
        request = {
            "scripts": str(scripts),
            "profile": str(profile),
            "artifact": str(artifact),
            "fillMap": declaration.get("fillMap") or {},
            "keep": declaration.get("keep") or [],
            "keepPattern": declaration.get("keepPattern"),
        }
        # Beside the profile, which already lives under the Runtime root: the
        # child reads one file and the sandbox gains nothing outside it.
        request_path = Path(profile).with_name(f"{Path(profile).stem}-declares.json")
        try:
            request_path.write_text(
                json.dumps(request, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            return {"checker": "check_residue", "state": "unavailable",
                    "reason": f"could not stage the declaration: {exc}",
                    "verdict": None, "ok": None}

        result = run_child([child_python(), "-c", _DECLARATION_BRIDGE,
                            str(request_path)])
        if result.timed_out:
            return {"checker": "check_residue", "state": "unavailable",
                    "reason": "the keep derivation exceeded its time bound",
                    "verdict": None, "ok": None}
        text = result.text.strip()
        try:
            payload = json.loads(text[text.index("{"):]) if "{" in text else None
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            return {"checker": "check_residue", "state": "unavailable",
                    "reason": f"the keep derivation produced no verdict object "
                              f"(exit {result.returncode})",
                    "verdict": None, "ok": None}

        if not payload.get("ok"):
            code = payload.get("code") or "invalid_params"
            if code == "ambiguous_fill_keys":
                # Structured, not a message a client has to parse: ``keys``
                # carries each offending key with every inventory string it
                # claimed and how often that string is present, which is the
                # whole repair. Declared in ``rt_codes.DOMAIN_CODES`` and mapped
                # to exit 2 by ``cli.USAGE_CODES`` — the document was never
                # judged, so this is not a gate refusal.
                raise RpcError(
                    "ambiguous_fill_keys",
                    "a declared fill key claims more than one form string, so "
                    "the keep derivation cannot tell which one this plan "
                    "actually filled; name a key that matches exactly one, or "
                    'declare {"text": VALUE, "other_occurrences": '
                    '"form_text"|"seats"} to say what the others are',
                    keys=payload.get("keys") or [], detail=payload.get("detail"))
            if code == "exemption_too_broad":
                raise RpcError("invalid_params", payload.get("detail") or code,
                               kept=payload.get("kept"))
            if code == "capability_unavailable":
                return {"checker": "check_residue", "state": "unavailable",
                        "reason": "the keep derivation is not importable in this "
                                  f"install: {payload.get('detail')}",
                        "verdict": None, "ok": None}
            raise RpcError("invalid_params",
                           payload.get("detail") or "the declaration was refused",
                           code=code)

        verdict = payload["verdict"] or {}
        return {
            "checker": "check_residue",
            "state": "ran",
            "exitCode": payload.get("exitCode"),
            "verdict": verdict.get("verdict"),
            "ok": verdict.get("ok"),
            "counts": verdict.get("counts"),
            "hard": (verdict.get("hard") or [])[:50],
            "warn": (verdict.get("warn") or [])[:50],
            # THE AUDIT TRAIL. A verdict that was reached with exemptions must
            # say which ones, or "clean" is unreviewable: derivedKeep is what
            # the form legitimately prints, consumed is what this plan filled,
            # unfilled is what it claimed to fill and did not, and rawKeep is
            # the operator's own additions. forbiddenAfter is what the gate was
            # still holding the document to.
            "exemptions": {
                "source": "plan.declares",
                "derivation": "visual_verify.derive_form_keep",
                "derivedKeep": payload.get("derivedKeep") or [],
                "rawKeep": payload.get("rawKeep") or [],
                "consumed": payload.get("consumed") or [],
                "unfilled": payload.get("unfilled") or [],
                "forbiddenAfter": payload.get("forbiddenAfter"),
                "keptAfter": payload.get("keptAfter"),
                "note": ("an exempted entry is removed from the forbidden list "
                         "or attributed to a declared value's span; attribution "
                         "stays per occurrence, so a second unfilled occurrence "
                         "of the same string is still residue"),
            },
        }

    def _require(self, name: str, path: Path) -> None:
        if not path.is_file():
            raise RpcError("capability_unavailable",
                           f"{name} is not available in this install",
                           tool=name)

    # -- form_inspect -------------------------------------------------------
    def profile(self, source: Path, out_path: Path,
                full_text: list[str] | None = None) -> dict:
        """Write a form profile to ``out_path``; return the child result meta."""
        self._require("form_inspect", self.form_inspect)
        argv = [child_python(), str(self.form_inspect), str(source),
                "--out", str(out_path)]
        for spec in (full_text or ()):
            argv += ["--full-text", spec]
        result = run_child(argv)
        if result.returncode != 0 or not out_path.is_file():
            raise RpcError(
                "backend_refused",
                "form_inspect refused this document",
                tool="form_inspect", exitCode=result.returncode,
                timedOut=result.timed_out,
                stdout=result.text[:4000],
                stderr=result.stderr.decode("utf-8", errors="replace")[:4000],
            )
        return {"exitCode": result.returncode, "profile": str(out_path)}

    # -- preedit ------------------------------------------------------------
    def preedit_run(self, argv_tail: list[str]) -> tuple[int, dict | None, str]:
        """Run one preedit subcommand. Returns (exit, parsed JSON or None, raw)."""
        self._require("preedit", self.preedit)
        result = run_child([child_python(), str(self.preedit)] + argv_tail)
        raw = result.text
        parsed = None
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    import json as _json
                    parsed = _json.loads(line)
                except ValueError:
                    parsed = None
                break
        if result.timed_out:
            raise RpcError("backend_refused", "preedit exceeded its time bound",
                           tool="preedit", timedOut=True)
        return result.returncode, parsed, raw

    # -- com_backend edit ---------------------------------------------------
    def com_edit_run(self, file, ops_path, save_as, export_pdf=None,
                     timeout: float = COM_EDIT_TIMEOUT_SECONDS) -> dict:
        """One bounded ``com_backend.py edit`` child. Never ``--kill-stale``.

        Refuses before spawn when Hancom is missing, when an Hwp.exe is already
        running, when file and save-as resolve to the same path, or when the
        ops file names a kind outside the first wave. Parses exactly one JSON
        object from stdout.
        """
        from rt_convert import hancom_facts, hancom_is_busy, running_hancom_processes  # noqa: PLC0415
        from rt_plan import COM_FIRST_WAVE, COM_FIRST_WAVE_SET  # noqa: PLC0415

        self._require("com_backend", self.com_backend)
        src = Path(file)
        ops = Path(ops_path)
        dest = Path(save_as)
        pdf = Path(export_pdf) if export_pdf is not None else None

        hancom = hancom_facts()
        if hancom.get("state") != "yes":
            raise RpcError(
                "needs_hancom",
                "this machine cannot run a COM edit: "
                + (hancom.get("reason") or "Hancom is not available"),
                hancom=hancom)

        busy = running_hancom_processes()
        if hancom_is_busy(busy):
            raise RpcError(
                "com_busy",
                "a Hancom instance is already running on this machine; "
                "close it and try again — the Runtime will not "
                "terminate somebody else's session",
                processes=busy.get("processes") or [],
                state=busy.get("state"),
                reason=busy.get("reason"))

        try:
            same = src.resolve() == dest.resolve()
        except OSError:
            same = str(src) == str(dest)
        if same:
            raise RpcError(
                "invalid_params",
                "COM edit save-as must be a different path from the input file",
                file=src.name, saveAs=dest.name)

        try:
            kinds = _ops_kinds_from_file(ops)
        except (OSError, UnicodeError, ValueError) as exc:
            raise RpcError(
                "invalid_params",
                "COM ops file is unreadable",
                path=ops.name, detail=str(exc)) from exc
        for kind in kinds:
            if kind not in COM_FIRST_WAVE_SET:
                raise RpcError(
                    "unknown_op_kind",
                    f"op kind {kind!r} is deferred on the com backend in this wave",
                    kind=kind, servedBy="com",
                    knownKinds=list(COM_FIRST_WAVE))

        argv = com_edit_argv(self.com_backend, src, ops, dest, pdf)
        paths = (src, ops, dest, pdf, self.com_backend)
        result = run_child(argv, timeout=timeout)
        raw = result.text
        parsed = one_json_object(raw)
        redacted_out = redact_paths(raw[:4000], *paths)
        redacted_err = redact_paths(
            result.stderr.decode("utf-8", errors="replace")[:4000], *paths)
        if result.timed_out:
            raise RpcError(
                "backend_refused", "com_backend edit exceeded its time bound",
                tool="com_backend", timedOut=True,
                stdout=redacted_out, stderr=redacted_err)
        if result.returncode != 0 or parsed is None or not parsed.get("ok"):
            message = None
            if isinstance(parsed, dict):
                message = parsed.get("error") or parsed.get("reason")
            if message:
                message = redact_paths(str(message), *paths)
            raise RpcError(
                "backend_refused",
                message or f"com_backend edit refused this batch (exit {result.returncode})",
                tool="com_backend", exitCode=result.returncode,
                timedOut=False,
                stdout=redacted_out, stderr=redacted_err)
        if not dest.is_file():
            raise RpcError(
                "backend_refused",
                "com_backend edit left no save-as file",
                tool="com_backend", exitCode=result.returncode,
                stdout=redacted_out, stderr=redacted_err)
        return {
            "exitCode": result.returncode,
            "payload": parsed,
            "argv": list(argv),
        }

    # -- render_probe -------------------------------------------------------
    def render_probe(self) -> dict:
        """This MACHINE's renderer inventory. Opt-in: it costs seconds.

        ``pipeline/scripts/render_probe.py`` shells out to ``soffice`` and, on
        Windows, to ``wsl``; measured at ~8s on the bench. That is fine for a
        button and ruinous for ``initialize``, so nothing calls this unless a
        caller asks for it, and the answer is cached for the process.

        What it reports is what the machine HAS, not what this build USES: the
        Runtime calls no converter, and ``capabilities.render.converter`` says
        so regardless of what turns up here.
        """
        probe = self.root / "pipeline" / "scripts" / "render_probe.py"
        if not probe.is_file():
            return {"state": "unavailable",
                    "reason": "pipeline/scripts/render_probe.py not found",
                    "capabilities": None, "renderers": []}
        result = run_child([child_python(), str(probe), "--json"])
        if result.timed_out or result.returncode != 0:
            return {"state": "unavailable",
                    "reason": (f"render_probe exited {result.returncode}"
                               + (" after timing out" if result.timed_out else "")),
                    "capabilities": None, "renderers": []}
        try:
            import json as _json
            payload = _json.loads(result.text)
        except ValueError:
            return {"state": "unavailable",
                    "reason": "render_probe produced no JSON object",
                    "capabilities": None, "renderers": []}
        return {"state": "probed", "reason": None,
                "capabilities": payload.get("capabilities"),
                "renderers": payload.get("renderers", []),
                "note": ("machine inventory only; this build calls none of "
                         "these, see capabilities.render.converter")}

    # -- check_residue ------------------------------------------------------
    def residue(self, profile: Path, artifact: Path,
                declaration: dict | None = None) -> dict:
        """Run the residue gate. NEVER raises for a finding — a finding is data.

        Without a ``declaration`` this is byte-for-byte the call it always was:
        no keep list, no keep pattern, no fill map, which grades the artifact as
        a REPORT FINAL. That default is right for a report and wrong for a form
        fill, and it is what produced DIST-PAYLOAD-02's 25 ``form_residue``
        findings on a document whose only sin was being a form. Keeping it as
        the default means nothing grades more leniently by accident: a plan that
        declares nothing is judged exactly as before.

        With a declaration the gate is given the three policy inputs it has
        always accepted, and the keep list is DERIVED by
        ``visual_verify.derive_form_keep`` — the one implementation of
        ``(anchors ∪ placeholders) − consumed``, its ambiguity refusal, and its
        rule that guide text is never keepable. The Runtime does not restate
        that formula; it spawns it, for the reason ``rt_module`` gives for
        spawning engine scripts rather than importing them (``visual_verify``
        imports ``preedit`` at module scope and rewrites ``sys.path`` on the way
        in — that belongs in a child, not in the Runtime process).

        The child returns the derivation AND the verdict together, so the two
        cannot disagree about which keep list produced which finding.
        """
        if not self.check_residue.is_file():
            return {"checker": "check_residue", "state": "unavailable",
                    "reason": "pipeline/scripts/check_residue.py not found under "
                              "the engine root",
                    "verdict": None, "ok": None}
        if declaration:
            return self._residue_declared(profile, artifact, declaration)
        result = run_child([child_python(), str(self.check_residue),
                            "--form-profile", str(profile),
                            "--artifact", str(artifact)])
        if result.timed_out:
            return {"checker": "check_residue", "state": "unavailable",
                    "reason": "checker exceeded its time bound",
                    "verdict": None, "ok": None}
        parsed = None
        text = result.text.strip()
        if text.startswith("{"):
            try:
                import json as _json
                parsed = _json.loads(text)
            except ValueError:
                parsed = None
        if parsed is None:
            return {"checker": "check_residue", "state": "unavailable",
                    "reason": f"checker produced no verdict object (exit "
                              f"{result.returncode})",
                    "verdict": None, "ok": None}
        return {
            "checker": "check_residue",
            "state": "ran",
            "exitCode": result.returncode,
            "verdict": parsed.get("verdict"),
            "ok": parsed.get("ok"),
            "counts": parsed.get("counts"),
            "hard": parsed.get("hard", [])[:50],
            "warn": parsed.get("warn", [])[:50],
        }
