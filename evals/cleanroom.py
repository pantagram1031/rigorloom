#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cleanroom.py — third-party validation harness (v0.17 item A).

A *clean-room run* installs rigorloom the way a buyer would — from the
distribution zips built by ``scripts/package_module.py`` and nothing else —
into a throwaway root, then proves the install stands on its own. The whole
point is negative: **nothing inside the sandbox may resolve back to this
source checkout.** If it does, the harness fails loudly instead of shipping a
green run that only works on the author's machine.

Subcommands
-----------

``prepare``   install bundles into a sandbox root, enable modules through the
              shipped registry CLI, install the skill surface (when the
              bundles carry one), run the self-check (bundle ``--verify`` +
              capability probe + CLI smoke), assert containment, and write
              ``<root>/install_report.json``.
``verify-containment``
              re-run only the containment assertions over an already prepared
              root (used by the tests that plant a source-checkout reference,
              and by an operator who wants to re-check a sandbox after an
              agent has run in it).
``task``      materialize one task definition into ``<root>/work/<task_id>``:
              copy its corpus inputs (referenced by path — the eval tree never
              embeds corpus binaries), render ``PROMPT.txt``, write
              ``task.json``.
``check``     run a task's ``machine_checks`` against the prepared sandbox
              after an agent has finished, write ``checks.json``.
``list-tasks`` JSON inventory of the task definitions.

The model-invocation layer is deliberately absent: ``prepare`` + ``task``
produce a sandbox and a prompt, ``check`` consumes whatever the agent left
behind. How an agent is launched (Task tool, a CLI, a human at a keyboard) is
the operator's business — see ``evals/README.md`` §"The model-invocation
seam".

Exit codes follow the repo's checker convention: 0 ok, 2 usage/config
refusal, 3 hard finding (containment breach, failed verify, failed check).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable
from xml.etree import ElementTree

HARNESS_ROOT = Path(__file__).resolve().parent
SOURCE_CHECKOUT = HARNESS_ROOT.parent
TASKS_DIR = HARNESS_ROOT / "tasks"
DEFAULT_CORPUS_ROOT = SOURCE_CHECKOUT / "tests" / "corpus" / "forms"

INSTALL_REPORT_SCHEMA = "rigorloom-cleanroom-install/v1"
CHECKS_SCHEMA = "rigorloom-eval-checks/v1"
TASK_SCHEMA = "rigorloom-eval-task/v1"

# Text files worth scanning for an embedded source-checkout path. Binaries are
# covered by the bundle manifest hashes, not by a string search.
_TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".yaml", ".yml", ".txt", ".cfg", ".toml", ".ini",
    ".html", ".js", ".css", ".sh", ".ps1", ".bat", ".xml", ".csv",
}
# Environment variables that would let the sandbox reach back into the source
# checkout (or a previous run's config) no matter how clean the tree is.
_SCRUBBED_ENV = (
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
    "RIGORLOOM_BACKENDS", "RIGORLOOM_PROFILE_ROOT",
)
# Repinned rather than dropped: the engine's layout override must point at the
# SANDBOX install, so a stale operator value can never redirect a probe back to
# the checkout. Containment asserts the pinned value stays inside the sandbox.
_PINNED_ENV = ("RIGORLOOM_ROOT",)

_ALLOWED_GAPS = {
    "skill_surface_not_bundled",
    "no_module_bundles",
}


class CleanroomError(Exception):
    """Loud harness refusal; ``exit_code`` follows the checker convention."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# --------------------------------------------------------------------------- #
# YAML (task definitions)
# --------------------------------------------------------------------------- #
def _strip_comment(line: str) -> str:
    """Drop a trailing ``#`` comment, respecting quoted spans."""
    out: list[str] = []
    quote: str | None = None
    previous = ""
    for char in line:
        if quote:
            out.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
            out.append(char)
        elif char == "#" and previous in ("", " ", "\t"):
            break
        else:
            out.append(char)
        previous = char
    return "".join(out)


def _split_unquoted(text: str, separator: str) -> tuple[str, str] | None:
    """Partition on the first ``separator`` that is not inside quotes."""
    quote: str | None = None
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == separator:
            return text[:index], text[index + 1:]
    return None


def _scalar(token: str) -> Any:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        if token[0] == '"':
            # JSON escapes are honoured inside double quotes; this is also how
            # folded block scalars survive the line-based pass above.
            try:
                return json.loads(token)
            except json.JSONDecodeError:
                pass
        return token[1:-1]
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if not inner:
            return []
        parts, buffer, quote = [], [], None
        for char in inner:
            if quote:
                buffer.append(char)
                if char == quote:
                    quote = None
            elif char in ("'", '"'):
                quote = char
                buffer.append(char)
            elif char == ",":
                parts.append("".join(buffer))
                buffer = []
            else:
                buffer.append(char)
        if "".join(buffer).strip():
            parts.append("".join(buffer))
        return [_scalar(part) for part in parts]
    if token in ("true", "false"):
        return token == "true"
    if token == "null":
        return None
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    return token


def parse_yaml(text: str) -> Any:
    """Stdlib YAML subset for task definitions.

    Supports block mappings, block sequences, sequences of mappings, flow
    lists, ``|``/``>`` block scalars, quoted scalars, and ``#`` comments.
    Deliberately NOT a general YAML parser — but, unlike the installer's
    parser, it splits ``key: value`` and sequence items on *unquoted* colons
    only, so a rubric line like ``- "[machine] exit: 0"`` stays a string.
    """
    lines: list[tuple[int, str]] = []
    raw_lines = text.splitlines()
    index = 0
    while index < len(raw_lines):
        raw = raw_lines[index]
        content = _strip_comment(raw)
        if not content.strip():
            index += 1
            continue
        indent = len(content) - len(content.lstrip(" "))
        stripped = content.strip()
        # block scalar: fold the following more-indented lines into one token
        head = _split_unquoted(stripped, ":")
        if head and head[1].strip() in ("|", ">", "|-", ">-"):
            style = head[1].strip()
            body, index = [], index + 1
            while index < len(raw_lines):
                nxt = raw_lines[index]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip(" "))) <= indent:
                    break
                body.append(nxt.strip())
                index += 1
            joined = ("\n" if style.startswith("|") else " ").join(body).strip()
            lines.append((indent, f"{head[0].strip()}: {json.dumps(joined, ensure_ascii=False)}"))
            continue
        lines.append((indent, stripped))
        index += 1
    if not lines:
        return {}
    value, consumed = _parse_block(lines, 0, lines[0][0])
    if consumed != len(lines):
        raise CleanroomError(f"YAML parse error near: {lines[consumed][1]!r}")
    return value


def _parse_block(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[Any, int]:
    if lines[i][1].startswith("- "):
        return _parse_seq(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_seq(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[list, int]:
    items: list[Any] = []
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent or not content.startswith("- "):
            break
        if ind > indent:
            raise CleanroomError(f"YAML bad indentation near: {content!r}")
        rest = content[2:].strip()
        key_col = indent + 2
        head = _split_unquoted(rest, ":")
        if head is not None and not rest.startswith("["):
            sub: list[tuple[int, str]] = [(key_col, rest)]
            j = i + 1
            while j < len(lines) and lines[j][0] >= key_col:
                sub.append(lines[j])
                j += 1
            value, consumed = _parse_map(sub, 0, key_col)
            if consumed != len(sub):
                raise CleanroomError(f"YAML bad list item near: {rest!r}")
            items.append(value)
            i = j
        else:
            items.append(_scalar(rest))
            i += 1
    return items, i


def _parse_map(lines: list[tuple[int, str]], i: int, indent: int) -> tuple[dict, int]:
    result: dict[str, Any] = {}
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent or content.startswith("- "):
            break
        if ind > indent:
            raise CleanroomError(f"YAML bad indentation near: {content!r}")
        head = _split_unquoted(content, ":")
        if head is None:
            raise CleanroomError(f"YAML expected 'key: value' near: {content!r}")
        key, value = head[0].strip(), head[1].strip()
        if value == "":
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                child, i = _parse_block(lines, i + 1, lines[i + 1][0])
                result[key] = child
            else:
                result[key] = {}
                i += 1
        else:
            result[key] = _scalar(value)
            i += 1
    return result, i


def load_task(path: Path | str) -> dict[str, Any]:
    """Parse and validate one task definition YAML."""
    path = Path(path)
    if not path.is_file():
        raise CleanroomError(f"task definition not found: {path}")
    try:
        raw = parse_yaml(path.read_text(encoding="utf-8"))
    except CleanroomError as exc:
        raise CleanroomError(f"{path.name}: unparseable task YAML: {exc}")
    if not isinstance(raw, dict):
        raise CleanroomError(f"{path.name}: task root must be a mapping")
    validate_task(raw, source=path.name)
    raw["_source"] = str(path)
    return raw


_CHECK_KINDS = {"python", "shell", "file", "geometry", "idempotence",
                "residue", "text_present", "text_absent", "unmodified"}
_FILE_MODES = {"exists", "absent", "nonempty"}
# ``requires_module: NAME`` gates one machine_check on a distribution module
# being enabled in the sandbox. Same name grammar as module_registry's _NAME_RE.
_MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def validate_task(task: dict[str, Any], source: str = "<task>") -> None:
    """Schema validation for a task definition. Every violation is loud."""

    def fail(message: str) -> None:
        raise CleanroomError(f"{source}: {message}")

    if task.get("schema") != TASK_SCHEMA:
        fail(f"schema must be {TASK_SCHEMA!r} (got {task.get('schema')!r})")
    for field in ("id", "family", "prompt"):
        if not isinstance(task.get(field), str) or not task[field].strip():
            fail(f"{field} is required and must be a non-empty string")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task["id"]):
        fail(f"id {task['id']!r} must be a filesystem-safe token")

    inputs = task.get("input_files")
    if not isinstance(inputs, list) or not inputs:
        fail("input_files must be a non-empty list of repo-relative paths")
    for entry in inputs:
        if not isinstance(entry, str) or not entry.strip():
            fail("input_files entries must be non-empty strings")
        # Absoluteness is checked in BOTH path flavours: on Windows
        # ``Path('/etc/passwd').is_absolute()`` is False (no drive), which
        # would let a posix-absolute path through.
        if (PurePosixPath(entry).is_absolute()
                or PureWindowsPath(entry).is_absolute()
                or entry.startswith("..")):
            fail(f"input_files entry must be repo-relative: {entry!r}")

    # ``baseline`` (optional): the blank form the produced artifact came from,
    # named by input basename. Consumed by checkers declaring wants: [baseline]
    # (v0.17 G3) and exposed to task authors as ``${BASELINE}``.
    if "baseline" in task:
        declared = task["baseline"]
        if not isinstance(declared, str) or not declared.strip():
            fail("baseline must be the basename of one of input_files")
        basenames = {PurePosixPath(entry).name for entry in inputs
                     if isinstance(entry, str)}
        if declared not in basenames:
            fail(f"baseline {declared!r} is not one of this task's inputs "
                 f"({sorted(basenames)}) — the blank form must be a task input")

    behaviors = task.get("expected_behavior")
    if not isinstance(behaviors, list) or not behaviors:
        fail("expected_behavior must be a non-empty list of rubric strings")
    for entry in behaviors:
        if not isinstance(entry, str) or not entry.strip():
            fail("expected_behavior entries must be non-empty strings")

    checks = task.get("machine_checks")
    if not isinstance(checks, list) or not checks:
        fail("machine_checks must be a non-empty list")
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            fail("machine_checks entries must be mappings")
        cid = check.get("id")
        if not isinstance(cid, str) or not cid.strip():
            fail("every machine_check needs an id")
        if cid in seen:
            fail(f"duplicate machine_check id {cid!r}")
        seen.add(cid)
        kind = check.get("kind")
        if kind not in _CHECK_KINDS:
            fail(f"machine_check {cid!r}: kind must be one of "
                 f"{sorted(_CHECK_KINDS)} (got {kind!r})")
        if "requires_module" in check:
            required = check["requires_module"]
            if not isinstance(required, str) or not _MODULE_NAME_RE.fullmatch(
                    required):
                fail(f"machine_check {cid!r}: requires_module must be a "
                     f"kebab-case distribution-module name (got {required!r})")
        if kind == "python":
            argv = check.get("argv")
            if not isinstance(argv, list) or not argv:
                fail(f"machine_check {cid!r}: python kind needs argv[]")
        elif kind == "shell":
            if not isinstance(check.get("command"), str):
                fail(f"machine_check {cid!r}: shell kind needs command")
        elif kind == "file":
            if not isinstance(check.get("path"), str):
                fail(f"machine_check {cid!r}: file kind needs path")
            if check.get("mode", "exists") not in _FILE_MODES:
                fail(f"machine_check {cid!r}: file mode must be one of "
                     f"{sorted(_FILE_MODES)}")
        elif kind in ("geometry", "idempotence"):
            for field in ("before", "after"):
                if not isinstance(check.get(field), str):
                    fail(f"machine_check {cid!r}: {kind} kind needs "
                         f"{field} (a path)")
        elif kind == "residue":
            for field in ("profile", "artifact"):
                if not isinstance(check.get(field), str):
                    fail(f"machine_check {cid!r}: residue kind needs {field}")
        elif kind == "unmodified":
            if not isinstance(check.get("input"), str):
                fail(f"machine_check {cid!r}: unmodified kind needs input "
                     "(a task input_files basename)")
        elif kind in ("text_present", "text_absent"):
            if not isinstance(check.get("artifact"), str):
                fail(f"machine_check {cid!r}: {kind} kind needs artifact")
            strings = check.get("strings")
            if not isinstance(strings, list) or not strings:
                fail(f"machine_check {cid!r}: {kind} kind needs a non-empty "
                     "strings[] list")
        for expr in check.get("assert_json") or []:
            if not isinstance(expr, str):
                fail(f"machine_check {cid!r}: assert_json entries are strings")
            _parse_assertion(expr, source=f"{source}:{cid}")


def load_tasks(tasks_dir: Path | str = TASKS_DIR) -> list[dict[str, Any]]:
    tasks_dir = Path(tasks_dir)
    if not tasks_dir.is_dir():
        raise CleanroomError(f"tasks directory not found: {tasks_dir}")
    tasks = [load_task(path) for path in sorted(tasks_dir.glob("*.yaml"))]
    ids = [task["id"] for task in tasks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise CleanroomError(f"duplicate task ids across files: {sorted(duplicates)}")
    return tasks


# --------------------------------------------------------------------------- #
# Assertion mini-language: "len(anchors) >= 29", "table_map[0].rowCnt == 19"
# --------------------------------------------------------------------------- #
_ASSERT_RE = re.compile(
    r"^\s*(?P<path>len\([^)]+\)|[A-Za-z_][\w.\[\]]*)\s*"
    r"(?P<op>==|!=|>=|<=|>|<)\s*(?P<value>.+?)\s*$")
_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def _parse_assertion(expr: str, source: str = "<assert>") -> tuple[str, str, Any]:
    match = _ASSERT_RE.match(expr)
    if not match:
        raise CleanroomError(
            f"{source}: unparseable assertion {expr!r} — expected "
            "'<json.path> <op> <value>', e.g. 'len(anchors) >= 29'")
    raw_value = match.group("value")
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value.strip("'\"")
    return match.group("path"), match.group("op"), value


def _resolve_json_path(document: Any, path: str) -> Any:
    """Resolve ``a.b[0].c`` (and the ``len(...)`` wrapper) against a document."""
    wrap_len = False
    if path.startswith("len(") and path.endswith(")"):
        wrap_len = True
        path = path[4:-1].strip()
    current = document
    for token in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if token.startswith("["):
            index = int(token[1:-1])
            if not isinstance(current, list) or index >= len(current):
                raise KeyError(f"index {token} not available at {path!r}")
            current = current[index]
        else:
            if not isinstance(current, dict) or token not in current:
                raise KeyError(f"key {token!r} not available at {path!r}")
            current = current[token]
    return len(current) if wrap_len else current


def evaluate_assertions(document: Any, expressions: Iterable[str]) -> list[dict]:
    results = []
    for expr in expressions:
        path, op, expected = _parse_assertion(expr)
        try:
            actual = _resolve_json_path(document, path)
            ok = bool(_OPS[op](actual, expected))
            detail = None
        except (KeyError, TypeError) as exc:
            actual, ok, detail = None, False, str(exc)
        results.append({"expr": expr, "ok": ok, "actual": actual,
                        "detail": detail})
    return results


# --------------------------------------------------------------------------- #
# Sandbox plumbing
# --------------------------------------------------------------------------- #
def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm(path: Path | str) -> str:
    text = str(Path(path)).replace("\\", "/")
    return text.lower() if os.name == "nt" else text


def _is_within(child: Path | str, parent: Path | str) -> bool:
    child_n, parent_n = _norm(child), _norm(parent).rstrip("/")
    return child_n == parent_n or child_n.startswith(parent_n + "/")


def forbidden_roots(extra: Iterable[str | Path] = ()) -> list[Path]:
    """Roots the sandbox must never reference: this checkout plus extras."""
    roots = [SOURCE_CHECKOUT.resolve()]
    for entry in extra:
        resolved = Path(entry).resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def child_env(sandbox: Path, install_root: Path,
              forbidden: Iterable[Path]) -> tuple[dict[str, str], list[dict]]:
    """Environment for every sandbox subprocess, plus the scrub receipt.

    Two axes are scrubbed: variables that let Python import from outside the
    sandbox (``PYTHONPATH`` & friends), and *any* variable whose value points
    into a forbidden root — including ``PATH`` entries, which are pruned
    element-wise rather than dropped wholesale.
    """
    forbidden = [Path(root) for root in forbidden]
    env = dict(os.environ)
    scrubbed: list[dict] = []

    for name in (*_SCRUBBED_ENV, *_PINNED_ENV):
        if name in env:
            scrubbed.append({"var": name, "reason": "sandbox-isolation"})
            env.pop(name)

    path_entries = env.get("PATH", "").split(os.pathsep)
    kept = [entry for entry in path_entries
            if entry and not any(_is_within(entry, root) for root in forbidden)]
    if len(kept) != len([e for e in path_entries if e]):
        scrubbed.append({"var": "PATH", "reason": "entries under a forbidden root"})
    env["PATH"] = os.pathsep.join(kept)

    for name, value in list(env.items()):
        if name in ("PATH", "TEMP", "TMP", "TMPDIR"):
            continue
        if any(_is_within(value, root) for root in forbidden):
            scrubbed.append({"var": name, "reason": "value under a forbidden root"})
            env.pop(name)

    tmp = sandbox / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env["TEMP"] = env["TMP"] = env["TMPDIR"] = str(tmp)
    # The engine's own layout override: point it at the SANDBOX install so a
    # stale operator value can never redirect a probe back to the checkout.
    env["RIGORLOOM_ROOT"] = str(install_root)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env, scrubbed


class Sandbox:
    """A prepared clean-room root and the subprocess discipline around it."""

    def __init__(self, root: Path | str, extra_forbidden: Iterable[str | Path] = ()):
        self.root = Path(root).resolve()
        self.forbidden = forbidden_roots(extra_forbidden)
        for forbidden_root in self.forbidden:
            if _is_within(self.root, forbidden_root):
                raise CleanroomError(
                    f"sandbox root {self.root} is INSIDE forbidden root "
                    f"{forbidden_root} — a clean-room root must live outside "
                    "the source checkout", exit_code=2)
        self.install = self.root / "install"
        self.skills = self.root / "skills"
        self.work = self.root / "work"
        self.bundles = self.root / "bundles"
        self.commands: list[dict] = []
        self._env, self.env_scrubbed = child_env(
            self.root, self.install, self.forbidden)

    # -- subprocess ---------------------------------------------------------
    def run(self, argv: list[str], *, cwd: Path | None = None,
            shell: bool = False, timeout: int = 600) -> subprocess.CompletedProcess:
        cwd = cwd or self.root
        proc = subprocess.run(
            argv if not shell else argv[0],
            cwd=str(cwd), env=self._env, shell=shell, timeout=timeout,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.commands.append({
            "argv": argv if not shell else [argv[0]],
            "shell": shell,
            "cwd": str(cwd),
            "returncode": proc.returncode,
        })
        return proc

    def run_python(self, script: Path | str, args: list[str], **kwargs):
        script = Path(script)
        if not _is_within(script, self.install) and not _is_within(script, self.root):
            raise CleanroomError(
                f"refusing to run {script}: outside the sandbox root "
                f"{self.root}", exit_code=3)
        return self.run([sys.executable, str(script), *args], **kwargs)

    @property
    def env(self) -> dict[str, str]:
        return dict(self._env)


# --------------------------------------------------------------------------- #
# Bundle installation
# --------------------------------------------------------------------------- #
def _safe_extract(bundle: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise CleanroomError(
                    f"{bundle.name}: refusing traversal entry {name!r}",
                    exit_code=3)
        archive.extractall(target)


def _bundle_manifest(bundle: Path) -> dict:
    try:
        with zipfile.ZipFile(bundle) as archive:
            raw = archive.read("MANIFEST.json")
    except KeyError:
        raise CleanroomError(f"{bundle.name}: no MANIFEST.json — not a "
                             "rigorloom bundle", exit_code=2)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CleanroomError(f"{bundle.name}: unreadable zip: {exc}", exit_code=2)
    return json.loads(raw.decode("utf-8"))


def install_bundles(sandbox: Sandbox, bundles: list[Path]) -> dict[str, Any]:
    """Install core + module bundles the way a buyer would. Bundles only.

    Each zip is first COPIED into ``<root>/bundles/`` and everything after
    that works from the copy. Two reasons: a buyer has downloaded zips, not a
    build tree; and the run record must never carry the absolute path of a
    ``dist/`` directory that usually sits inside the source checkout.
    """
    sandbox.install.mkdir(parents=True, exist_ok=True)
    sandbox.bundles.mkdir(parents=True, exist_ok=True)

    manifests = {}
    for original in bundles:
        manifest = _bundle_manifest(original)
        name = manifest.get("name")
        if not name:
            raise CleanroomError(f"{original.name}: MANIFEST.json has no name",
                                 exit_code=2)
        if name in manifests:
            raise CleanroomError(f"two bundles both named {name!r}", exit_code=2)
        local = sandbox.bundles / original.name
        shutil.copy2(original, local)
        manifests[name] = (local, manifest)

    if "core" not in manifests:
        raise CleanroomError(
            "no core bundle among the inputs — a clean-room install starts "
            "from rigorloom-core-<version>.zip", exit_code=2)

    installed = []

    core_bundle, core_manifest = manifests["core"]
    _safe_extract(core_bundle, sandbox.install)
    # The bundle's own manifest/install note belong beside the tree, not in it:
    # a module bundle would otherwise overwrite core's copies.
    for control in ("MANIFEST.json", "INSTALL.md"):
        source = sandbox.install / control
        if source.exists():
            shutil.move(str(source), str(sandbox.bundles / f"core.{control}"))
    installed.append({
        "name": "core", "version": core_manifest.get("version"),
        "zip": bundle_reference(core_bundle), "sha256": _sha256_file(core_bundle),
        "files": len(core_manifest.get("files", [])),
    })

    staging = sandbox.root / ".staging"
    for name, (bundle, manifest) in sorted(manifests.items()):
        if name == "core":
            continue
        area = staging / name
        if area.exists():
            shutil.rmtree(area)
        _safe_extract(bundle, area)
        payload = area / "modules" / name
        if not payload.is_dir():
            raise CleanroomError(
                f"{bundle.name}: module bundle has no modules/{name}/ payload",
                exit_code=3)
        destination = sandbox.install / "modules" / name
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(payload), str(destination))
        for control in ("MANIFEST.json", "INSTALL.md"):
            source = area / control
            if source.exists():
                shutil.move(str(source), str(sandbox.bundles / f"{name}.{control}"))
        installed.append({
            "name": name, "version": manifest.get("version"),
            "zip": bundle_reference(bundle), "sha256": _sha256_file(bundle),
            "files": len(manifest.get("files", [])),
        })
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    return {"installed": installed,
            "module_bundles": sorted(n for n in manifests if n != "core"),
            "local_bundles": [str(local) for local, _ in manifests.values()]}


def bundle_reference(bundle: Path) -> str:
    """Bundle identity for the report: filename only.

    The zip's directory is the operator's build output (typically inside the
    checkout); recording its absolute path would put a source-checkout string
    into the report and make containment self-defeating.
    """
    return Path(bundle).name


def verify_bundles(sandbox: Sandbox, bundles: list[Path]) -> list[dict]:
    """Run the SHIPPED verifier (``install/scripts/package_module.py``) over
    every input zip. Uses the buyer's copy on purpose: this also proves the
    packaged verifier itself survived packaging."""
    verifier = sandbox.install / "scripts" / "package_module.py"
    if not verifier.is_file():
        raise CleanroomError(
            "core bundle does not ship scripts/package_module.py — cannot "
            "self-verify", exit_code=3)
    results = []
    for bundle in bundles:
        proc = sandbox.run_python(verifier, ["--verify", str(bundle)])
        try:
            report = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            report = {"ok": False, "stdout": (proc.stdout or "")[:400]}
        results.append({
            "bundle": bundle_reference(bundle),
            "exit_code": proc.returncode,
            "ok": proc.returncode == 0 and bool(report.get("ok")),
            "files": report.get("files"),
            "problems": report.get("problems") or [],
        })
    return results


def enable_modules(sandbox: Sandbox, names: list[str] | None,
                   all_modules: bool) -> dict[str, Any]:
    """Enable distribution modules through the shipped registry CLI."""
    registry = sandbox.install / "pipeline" / "scripts" / "module_registry.py"
    if not registry.is_file():
        raise CleanroomError(
            "core bundle does not ship pipeline/scripts/module_registry.py",
            exit_code=3)
    base = ["--modules-root", str(sandbox.install / "modules"),
            "--pyproject", str(sandbox.install / "pyproject.toml")]
    selector = ["--all"] if all_modules else (
        ["--names", *names] if names else ["--none"])
    proc = sandbox.run_python(registry, [*base, "write-enabled", *selector])
    if proc.returncode != 0:
        raise CleanroomError(
            f"module_registry write-enabled failed (exit {proc.returncode}): "
            f"{(proc.stdout or proc.stderr or '')[:400]}", exit_code=3)
    summary = json.loads(proc.stdout)
    return summary


def capability_probe(sandbox: Sandbox) -> dict[str, Any]:
    probe = sandbox.install / "engine" / "scripts" / "probe.py"
    if not probe.is_file():
        raise CleanroomError(
            "core bundle does not ship engine/scripts/probe.py", exit_code=3)
    proc = sandbox.run_python(probe, ["--json"])
    if proc.returncode != 0:
        raise CleanroomError(
            f"capability probe failed (exit {proc.returncode}): "
            f"{(proc.stderr or '')[:400]}", exit_code=3)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CleanroomError(f"capability probe emitted non-JSON: {exc}",
                             exit_code=3)


_SMOKE_SCRIPTS = (
    "engine/scripts/form_inspect.py",
    "engine/scripts/preedit.py",
    "engine/scripts/style_diff.py",
    "pipeline/scripts/check_residue.py",
    "pipeline/scripts/privacy_scan.py",
)


def cli_smoke(sandbox: Sandbox, registry_summary: dict) -> list[dict]:
    """``--help`` every CLI a buyer is told to run: the core surface plus every
    command the enabled modules registered. A traceback or a non-zero exit is
    a failed install, not a warning."""
    targets = [(rel, sandbox.install / rel) for rel in _SMOKE_SCRIPTS]
    for entry in registry_summary.get("cli", []):
        script = Path(entry["script"])
        try:
            rel = script.relative_to(sandbox.install).as_posix()
        except ValueError:
            rel = str(script)
        targets.append((f"module:{entry['module']}:{entry['command']}", script))

    results = []
    for label, script in targets:
        if not Path(script).is_file():
            results.append({"target": label, "ok": False,
                            "detail": "script missing from the install"})
            continue
        proc = sandbox.run_python(script, ["--help"], timeout=120)
        traceback = "Traceback (most recent call last)" in (proc.stderr or "")
        results.append({
            "target": label,
            "ok": proc.returncode == 0 and not traceback,
            "exit_code": proc.returncode,
            "detail": ((proc.stderr or "").strip()[-300:] or None)
            if (proc.returncode != 0 or traceback) else None,
        })
    return results


# --------------------------------------------------------------------------- #
# Skill install (bundle-provided only)
# --------------------------------------------------------------------------- #
SKILL_MANIFEST_TEMPLATE = """\
# generated by evals/cleanroom.py — clean-room skill install
install_root: "{install_root}"

source_map:
  - from: "{skill_md}"
    to: "SKILL.md"
{extra_map}
exclude:
  - "__pycache__"
  - "*.pyc"
  - ".sync*"
"""


def locate_skill_surface(install_root: Path) -> dict[str, Any]:
    """Where (if anywhere) the installed tree carries the router skill."""
    candidates = [
        (install_root / "SKILL.md", "SKILL.md", "references", "."),
        (install_root / "skill" / "SKILL.md", "skill/SKILL.md",
         "skill/references", "skill"),
    ]
    for skill_md, rel, refs_rel, _base in candidates:
        if skill_md.is_file():
            return {"present": True, "skill_md": rel,
                    "references": refs_rel
                    if (install_root / refs_rel).is_dir() else None}
    return {"present": False, "skill_md": None, "references": None}


def install_skill(sandbox: Sandbox, *, skills_root: Path | None = None,
                  merge_fragments: bool = True) -> dict[str, Any]:
    """Install the router skill from the SANDBOX tree with the SANDBOX copy of
    ``sync_local.py``. Both must have arrived in a bundle; nothing is read from
    the source checkout."""
    skills_root = Path(skills_root or sandbox.skills)
    installer = sandbox.install / "scripts" / "sync_local.py"
    surface = locate_skill_surface(sandbox.install)
    missing = []
    if not installer.is_file():
        missing.append("scripts/sync_local.py")
    if not surface["present"]:
        missing.append("SKILL.md")
    if missing:
        return {
            "ok": False, "gap": "skill_surface_not_bundled", "missing": missing,
            "detail": "the installed bundles carry no router skill and/or no "
                      "installer; a buyer therefore cannot install the skill "
                      "surface from dist zips alone",
        }

    install_root = skills_root / "rigorloom-hwp"
    install_root.parent.mkdir(parents=True, exist_ok=True)
    extra = ""
    if surface["references"]:
        extra = (f'  - from: "{surface["references"]}"\n'
                 f'    to: "references"\n')
    for component in ("engine/scripts", "pipeline/scripts"):
        if (sandbox.install / component).is_dir():
            extra += f'  - from: "{component}"\n    to: "{component}"\n'
    if merge_fragments:
        extra += "merge_skill_fragments: true\n"
    manifest_path = sandbox.root / "skill-manifest.yaml"
    manifest_path.write_text(
        SKILL_MANIFEST_TEMPLATE.format(
            install_root=str(install_root).replace("\\", "\\\\"),
            skill_md=surface["skill_md"], extra_map=extra),
        encoding="utf-8")

    proc = sandbox.run_python(installer, [
        "--manifest", str(manifest_path),
        "--checkout-root", str(sandbox.install),
    ])
    installed_skill = install_root / "SKILL.md"
    return {
        "ok": proc.returncode == 0 and installed_skill.is_file(),
        "exit_code": proc.returncode,
        "install_root": str(install_root),
        "skill_md_installed": installed_skill.is_file(),
        "detail": (proc.stderr or proc.stdout or "").strip()[-400:]
        if proc.returncode != 0 else None,
    }


# --------------------------------------------------------------------------- #
# Containment — the whole point
# --------------------------------------------------------------------------- #
def _iter_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or ".git" in path.parts:
            continue
        if path.suffix.lower() in _TEXT_SUFFIXES:
            yield path


def scan_for_source_references(root: Path, roots: Iterable[Path],
                               limit: int = 40) -> list[dict]:
    """Find any text file under ``root`` that embeds a forbidden root path.

    Both separator flavours are searched (``C:\\x\\y`` and ``C:/x/y``), case
    insensitively on Windows, because a leaked path can be written either way.
    """
    needles: list[tuple[str, Path]] = []
    for forbidden in roots:
        text = str(forbidden)
        for variant in {text, text.replace("\\", "/"), text.replace("/", "\\")}:
            needles.append(
                (variant.lower() if os.name == "nt" else variant, forbidden))
    findings: list[dict] = []
    for path in _iter_text_files(root):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        haystack = content.lower() if os.name == "nt" else content
        for needle, forbidden in needles:
            index = haystack.find(needle)
            if index < 0:
                continue
            line = haystack.count("\n", 0, index) + 1
            findings.append({
                "rule": "source_path_in_install",
                "file": path.relative_to(root).as_posix(),
                "line": line,
                "forbidden_root": str(forbidden),
                "snippet": content[max(0, index - 20):index + 90].strip(),
            })
            break
        if len(findings) >= limit:
            break
    return findings


def scan_for_escaping_links(root: Path) -> list[dict]:
    findings = []
    for path in root.rglob("*"):
        try:
            if not path.is_symlink():
                continue
            target = path.resolve()
        except OSError:
            continue
        if not _is_within(target, root):
            findings.append({
                "rule": "symlink_escapes_sandbox",
                "file": str(path),
                "target": str(target),
            })
    return findings


def _import_origin_probe(sandbox: Sandbox) -> dict[str, Any]:
    """Prove that a sandbox process importing the core modules resolves them
    inside the sandbox — the runtime axis of containment, which a text scan
    cannot see."""
    scripts = sandbox.install / "pipeline" / "scripts"
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(scripts)!r})\n"
        "import module_registry, privacy_scan\n"
        "print(json.dumps({'module_registry': module_registry.__file__,"
        " 'privacy_scan': privacy_scan.__file__, 'sys_path': sys.path}))\n"
    )
    proc = sandbox.run([sys.executable, "-c", code])
    if proc.returncode != 0:
        return {"ok": False, "detail": (proc.stderr or "")[-400:]}
    return json.loads(proc.stdout)


def containment_report(sandbox: Sandbox, *,
                       reported_paths: Iterable[tuple[str, str]] = (),
                       runtime: bool = True) -> dict[str, Any]:
    """Every containment axis, as one machine-readable verdict."""
    findings: list[dict] = []
    roots = sandbox.forbidden

    findings.extend(scan_for_source_references(sandbox.root, roots))
    findings.extend(scan_for_escaping_links(sandbox.root))

    for label, value in reported_paths:
        if not value:
            continue
        for forbidden in roots:
            if _is_within(value, forbidden):
                findings.append({
                    "rule": "reported_path_outside_sandbox",
                    "label": label, "path": value,
                    "forbidden_root": str(forbidden),
                })
                break
        else:
            if not _is_within(value, sandbox.root):
                findings.append({
                    "rule": "reported_path_outside_sandbox",
                    "label": label, "path": value,
                    "forbidden_root": None,
                })

    import_probe: dict[str, Any] = {"skipped": True}
    if runtime:
        import_probe = _import_origin_probe(sandbox)
        if import_probe.get("ok") is False:
            findings.append({"rule": "import_probe_failed",
                             "detail": import_probe.get("detail")})
        else:
            for key in ("module_registry", "privacy_scan"):
                origin = import_probe.get(key)
                if origin and not _is_within(origin, sandbox.install):
                    findings.append({
                        "rule": "import_resolved_outside_sandbox",
                        "module": key, "origin": origin})
            for entry in import_probe.get("sys_path", []):
                for forbidden in roots:
                    if entry and _is_within(entry, forbidden):
                        findings.append({
                            "rule": "sys_path_entry_in_forbidden_root",
                            "entry": entry, "forbidden_root": str(forbidden)})

    for name in _SCRUBBED_ENV:
        if name in sandbox.env:
            findings.append({"rule": "env_not_scrubbed", "var": name})
    for name in _PINNED_ENV:
        value = sandbox.env.get(name)
        if value and not _is_within(value, sandbox.root):
            findings.append({"rule": "pinned_env_outside_sandbox",
                             "var": name, "value": value})
    for entry in sandbox.env.get("PATH", "").split(os.pathsep):
        for forbidden in roots:
            if entry and _is_within(entry, forbidden):
                findings.append({"rule": "path_entry_in_forbidden_root",
                                 "entry": entry})

    return {
        "contained": not findings,
        "forbidden_roots": [str(root) for root in roots],
        "sandbox_root": str(sandbox.root),
        "env_scrubbed": sandbox.env_scrubbed,
        "import_probe": {k: v for k, v in import_probe.items()
                         if k != "sys_path"},
        "findings": findings,
    }


# --------------------------------------------------------------------------- #
# prepare
# --------------------------------------------------------------------------- #
def prepare(root: Path | str, bundles: list[Path | str], *,
            enable: str = "all", allow_gaps: Iterable[str] = (),
            extra_forbidden: Iterable[str | Path] = (),
            skip_skill: bool = False) -> tuple[dict[str, Any], int]:
    """Install bundles into a clean root and prove the install stands alone."""
    bundle_paths = []
    for entry in bundles:
        path = Path(entry).resolve()
        if not path.is_file():
            raise CleanroomError(f"bundle not found: {entry}", exit_code=2)
        if path.suffix.lower() != ".zip":
            raise CleanroomError(f"not a bundle zip: {entry}", exit_code=2)
        bundle_paths.append(path)
    if not bundle_paths:
        raise CleanroomError("at least one --bundle is required", exit_code=2)

    unknown = sorted(set(allow_gaps) - _ALLOWED_GAPS)
    if unknown:
        raise CleanroomError(
            f"unknown --allow-gap value(s) {unknown}; known gaps: "
            f"{sorted(_ALLOWED_GAPS)}", exit_code=2)

    root = Path(root).resolve()
    if root.exists() and any(root.iterdir()):
        raise CleanroomError(
            f"sandbox root {root} is not empty — a clean-room run starts from "
            "a fresh directory", exit_code=2)
    root.mkdir(parents=True, exist_ok=True)

    sandbox = Sandbox(root, extra_forbidden)
    report: dict[str, Any] = {
        "schema": INSTALL_REPORT_SCHEMA,
        "sandbox_root": str(sandbox.root),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "bundles": [bundle_reference(b) for b in bundle_paths],
        "gaps": [],
        "gaps_acknowledged": sorted(set(allow_gaps)),
    }

    report["install"] = install_bundles(sandbox, bundle_paths)
    report["verify"] = verify_bundles(
        sandbox, [Path(p) for p in report["install"]["local_bundles"]])
    report["install"].pop("local_bundles")

    if enable == "all":
        summary = enable_modules(sandbox, None, all_modules=True)
    elif enable == "none":
        summary = enable_modules(sandbox, [], all_modules=False)
    else:
        summary = enable_modules(
            sandbox, [n.strip() for n in enable.split(",") if n.strip()],
            all_modules=False)
    report["registry"] = {
        "discovered": summary.get("discovered", []),
        "enabled": summary.get("enabled", []),
        "cli": [entry["command"] for entry in summary.get("cli", [])],
        "checkers": [entry["name"] for entry in summary.get("checkers", [])],
        "run_modes": [entry["name"] for entry in summary.get("run_modes", [])],
    }
    if not report["install"]["module_bundles"]:
        report["gaps"].append({
            "id": "no_module_bundles", "severity": "HARD",
            "detail": "core-only install: no distribution-module bundles were "
                      "supplied, so module tasks cannot run",
        })

    report["probe"] = capability_probe(sandbox)
    probe_enabled = sorted(report["probe"].get("modules", {}).get("enabled", []))
    if probe_enabled != sorted(report["registry"]["enabled"]):
        raise CleanroomError(
            f"capability probe disagrees with the registry about enabled "
            f"modules: probe={probe_enabled} registry="
            f"{sorted(report['registry']['enabled'])}", exit_code=3)

    report["cli_smoke"] = cli_smoke(sandbox, summary)

    if skip_skill:
        report["skill"] = {"ok": None, "skipped": True}
    else:
        report["skill"] = install_skill(sandbox)
        if report["skill"].get("gap"):
            report["gaps"].append({
                "id": report["skill"]["gap"], "severity": "HARD",
                "detail": report["skill"]["detail"],
                "missing": report["skill"]["missing"],
            })
        elif not report["skill"]["ok"]:
            raise CleanroomError(
                f"skill install failed: {report['skill'].get('detail')}",
                exit_code=3)

    reported: list[tuple[str, str]] = [
        ("registry.modules_root", summary.get("modules_root", "")),
    ]
    for entry in summary.get("cli", []):
        reported.append((f"registry.cli.{entry['command']}", entry["script"]))
    for entry in summary.get("checkers", []):
        reported.append((f"registry.checker.{entry['name']}", entry["script"]))
    for entry in summary.get("skill_fragments", []):
        reported.append((f"registry.skill.{entry['module']}", entry["fragment"]))
    report["containment"] = containment_report(sandbox, reported_paths=reported)
    report["commands"] = sandbox.commands

    failures: list[str] = []
    if not report["containment"]["contained"]:
        failures.append(
            f"containment breach ({len(report['containment']['findings'])} "
            "finding(s))")
    bad_verify = [row["bundle"] for row in report["verify"] if not row["ok"]]
    if bad_verify:
        failures.append(f"bundle --verify failed: {bad_verify}")
    bad_smoke = [row["target"] for row in report["cli_smoke"] if not row["ok"]]
    if bad_smoke:
        failures.append(f"CLI smoke failed: {bad_smoke}")
    unacknowledged = [gap["id"] for gap in report["gaps"]
                      if gap["id"] not in set(allow_gaps)]
    if unacknowledged:
        failures.append(
            f"unacknowledged coverage gap(s): {unacknowledged} — pass "
            "--allow-gap to record them as known product gaps")

    report["failures"] = failures
    report["ok"] = not failures
    (sandbox.root / "install_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return report, (0 if report["ok"] else 3)


# --------------------------------------------------------------------------- #
# task materialization
# --------------------------------------------------------------------------- #
def materialize_task(root: Path | str, task: dict[str, Any], *,
                     corpus_root: Path | str = DEFAULT_CORPUS_ROOT,
                     extra_forbidden: Iterable[str | Path] = ()
                     ) -> dict[str, Any]:
    """Copy a task's inputs into ``<root>/work/<id>/inputs`` and render the
    prompt. Corpus files are *referenced by path* in the task YAML and copied
    here — the eval tree never carries binaries of its own."""
    sandbox = Sandbox(root, extra_forbidden)
    if not sandbox.install.is_dir():
        raise CleanroomError(
            f"{sandbox.root} has no install/ — run `prepare` first", exit_code=2)
    corpus_root = Path(corpus_root).resolve()

    work = sandbox.work / task["id"]
    inputs = work / "inputs"
    if work.exists():
        shutil.rmtree(work)
    inputs.mkdir(parents=True)

    copied = []
    for relative in task["input_files"]:
        source = (SOURCE_CHECKOUT / relative).resolve()
        if not source.is_file():
            # allow corpus-root-relative references too
            source = (corpus_root / relative).resolve()
        if not source.is_file():
            raise CleanroomError(
                f"task {task['id']}: input file not found: {relative}",
                exit_code=2)
        destination = inputs / source.name
        shutil.copy2(source, destination)
        copied.append({
            "source": relative,
            "sandbox_path": str(destination),
            "sha256": _sha256_file(destination),
        })

    prompt = task["prompt"].strip()
    listing = "\n".join(f"- {row['sandbox_path']}" for row in copied)
    rendered = (
        f"{prompt}\n\n"
        f"[files]\n{listing}\n\n"
        f"[working directory]\n{work}\n"
    )
    (work / "PROMPT.txt").write_text(rendered, encoding="utf-8")

    baseline = None
    if task.get("baseline"):
        baseline = next(
            (row["sandbox_path"] for row in copied
             if Path(row["sandbox_path"]).name == task["baseline"]), None)
        if baseline is None:  # pragma: no cover — validate_task rules it out
            raise CleanroomError(
                f"task {task['id']}: declared baseline {task['baseline']!r} "
                "was not among the copied inputs", exit_code=2)

    payload = {
        "schema": TASK_SCHEMA,
        "id": task["id"],
        "family": task["family"],
        "source_scenario": task.get("source_scenario"),
        "blocked_on": task.get("blocked_on"),
        "baseline": baseline,
        "prompt": prompt,
        "rendered_prompt": rendered,
        "work_dir": str(work),
        "inputs": copied,
        "expected_behavior": task["expected_behavior"],
        "machine_checks": task["machine_checks"],
        "install_root": str(sandbox.install),
    }
    (work / "task.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- #
# machine checks
# --------------------------------------------------------------------------- #
def _expand(value: str, variables: dict[str, str]) -> str:
    for key, replacement in variables.items():
        value = value.replace("${" + key + "}", replacement)
    return value


def _geometry_signature(profile: dict) -> list[dict]:
    """Table geometry with the text-dependent fields stripped — the comparison
    method pinned by the W5.3 results appendix in form-eval-scenarios.md."""
    signature = []
    for table in profile.get("table_map", []):
        cells = []
        for cell in table.get("cells", []):
            cells.append({key: cell.get(key) for key in
                          ("addr", "width", "height", "borderFillIDRef",
                           "shaded")})
        signature.append({
            "index": table.get("index"), "section": table.get("section"),
            "rowCnt": table.get("rowCnt"), "colCnt": table.get("colCnt"),
            "pageBreak": table.get("pageBreak"),
            "repeatHeader": table.get("repeatHeader"), "cells": cells,
        })
    return signature


_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")


def artifact_text(path: Path) -> str:
    """Normalized searchable text of an hwpx (zip) or a plain-text dump.

    Mirrors ``check_residue.artifact_text``. Reimplemented here rather than
    imported so the harness process never puts a sandbox directory on its own
    ``sys.path`` — the harness must be able to judge an install it does not
    execute inside.
    """
    if zipfile.is_zipfile(path):
        chunks: list[str] = []
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".xml")]
            contents = [n for n in names
                        if n.replace("\\", "/").startswith("Contents/")]
            for name in sorted(contents or names):
                payload = archive.read(name)
                try:
                    root = ElementTree.fromstring(payload)
                    chunks.append(" ".join(root.itertext()))
                except ElementTree.ParseError:
                    chunks.append(_TAG_RE.sub(
                        " ", payload.decode("utf-8", errors="replace")))
        return _WS_RE.sub(" ", " ".join(chunks)).strip()
    return _WS_RE.sub(" ", path.read_text(encoding="utf-8")).strip()


def _profile_inventory_texts(profile: dict) -> list[str]:
    """anchors + guide_text + placeholders, flattened and deduplicated."""
    texts: list[str] = []
    for key in ("anchors", "guide_text", "placeholders"):
        for entry in profile.get(key) or []:
            if isinstance(entry, str):
                texts.append(entry)
            elif isinstance(entry, dict) and isinstance(entry.get("text"), str):
                texts.append(entry["text"])
    return list(dict.fromkeys(texts))


def _zip_member_digest(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {info.filename: hashlib.sha256(archive.read(info)).hexdigest()
                for info in archive.infolist() if not info.is_dir()}


def sandbox_modules(sandbox: Sandbox) -> dict[str, Any]:
    """The sandbox's OWN answer to "which distribution modules are enabled and
    what do they provide", asked of the SHIPPED registry CLI rather than read
    out of ``install_report.json`` — so an enabled set changed after ``prepare``
    (or a module disabled by hand) is still the truth the checks are gated on.

    A root with no registry script is core-only, not an error: absence is not
    failure (``modules/README.md``).
    """
    script = sandbox.install / "pipeline" / "scripts" / "module_registry.py"
    if not script.is_file():
        return {"available": False, "enabled": [], "checkers": []}
    proc = sandbox.run_python(script, [
        "--modules-root", str(sandbox.install / "modules"),
        "--pyproject", str(sandbox.install / "pyproject.toml"), "list"])
    if proc.returncode != 0:
        raise CleanroomError(
            f"the sandbox's distribution-module registry refused to answer "
            f"(exit {proc.returncode}): "
            f"{(proc.stdout or proc.stderr or '')[:400]}", exit_code=3)
    try:
        summary = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise CleanroomError(
            f"the sandbox's registry emitted non-JSON: {exc}", exit_code=3)
    return {"available": True,
            "enabled": list(summary.get("enabled") or []),
            "checkers": list(summary.get("checkers") or [])}


def task_baseline(work: Path, task: dict[str, Any]) -> str | None:
    """The sandbox path of the blank form this task declares, or None.

    Read from the materialized ``task.json`` when present (that is where the
    copied input path lives), falling back to resolving the declared basename
    against ``<work>/inputs`` so a caller can gate checks before/without a
    re-materialization.
    """
    declared = task.get("baseline")
    if not declared:
        return None
    manifest = work / "task.json"
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if payload.get("baseline"):
            return str(payload["baseline"])
        for row in payload.get("inputs") or []:
            if Path(row.get("sandbox_path", "")).name == declared:
                return str(row["sandbox_path"])
    candidate = work / "inputs" / declared
    return str(candidate) if candidate.is_file() else None


def checker_wants(sandbox: Sandbox, script_ref: str,
                  checkers: Iterable[dict[str, Any]]) -> list[str]:
    """``wants`` declared by the enabled checker this argv[0] invokes, or [].

    Resolution is by PATH, never by name or filename convention: the harness
    matches the script the check runs against the scripts the sandbox's own
    registry reports. An unknown script (a core CLI, an unenabled module's
    payload) declares nothing and is left completely alone.
    """
    script = Path(script_ref)
    if not script.is_absolute():
        script = sandbox.install / script_ref
    try:
        script = script.resolve()
    except OSError:  # pragma: no cover — defensive
        return []
    for row in checkers:
        try:
            if Path(row["script"]).resolve() == script:
                return list(row.get("wants") or [])
        except (OSError, KeyError):  # pragma: no cover — defensive
            continue
    return []


def run_machine_check(sandbox: Sandbox, check: dict[str, Any],
                      variables: dict[str, str], *,
                      enabled_modules: Iterable[str] = (),
                      checkers: Iterable[dict[str, Any]] = (),
                      baseline: str | None = None) -> dict[str, Any]:
    cid = check["id"]
    result: dict[str, Any] = {"id": cid, "kind": check["kind"],
                              "description": check.get("description")}
    if check.get("blocked_on"):
        result.update({"status": "skipped", "reason": check["blocked_on"]})
        return result

    # Per-module gate (v0.17 G2). A check that calls into a distribution
    # module's payload cannot run in a sandbox where that module is disabled;
    # before this gate it FAILED there, which is a false finding about the
    # product. Semantics are ``blocked_on``'s, exactly: status "skipped" with a
    # recorded reason, counted in ``counts.skipped``, never in ``counts.pass``
    # — and score.py reads those counts, so a skip can never satisfy the
    # "machine checks ran and all passed" condition either.
    required_module = check.get("requires_module")
    if required_module and required_module not in set(enabled_modules):
        result.update({
            "status": "skipped",
            "reason": f"requires_module: distribution module "
                      f"{required_module!r} is not enabled in this sandbox",
            "requires_module": required_module,
        })
        return result

    kind = check["kind"]
    expect_exit = int(check.get("expect_exit", 0))

    # Baseline provisioning (v0.17 G3). A checker whose module.yaml declares
    # ``wants: [baseline]`` gets the task's blank form handed to it as
    # ``--baseline <path>`` — the caller no longer has to know. Two honest
    # edge cases:
    #   * the baseline path is ALREADY in the argv — either as an explicit
    #     --baseline value or because the check deliberately runs the checker
    #     ON the blank form itself (a document is never its own baseline). The
    #     harness supplies nothing and says so.
    #   * the task declares NO baseline. Running anyway would hand back a
    #     verdict whose baseline-only rules all self-skipped, exit 0 — a
    #     silent pass. So the check is skipped WITH THE REASON instead,
    #     mirroring blocked_on / requires_module.
    argv: list[str] = []
    if kind == "python":
        argv = [_expand(str(entry), variables) for entry in check["argv"]]
        wants = checker_wants(sandbox, argv[0], checkers)
        if "baseline" in wants:
            result["wants"] = wants
            if not baseline:
                result.update({
                    "status": "skipped",
                    "reason": "checker declares wants: [baseline] but the "
                              "task declares no baseline form — its "
                              "baseline-only rules would all self-skip",
                })
                return result
            if baseline in argv:
                result["baseline"] = "already-in-argv"
            else:
                argv += ["--baseline", baseline]
                result["baseline"] = "supplied-by-harness"

    document: Any = None
    try:
        if kind == "python":
            script = Path(argv[0])
            if not script.is_absolute():
                script = sandbox.install / argv[0]
            proc = sandbox.run_python(script, argv[1:],
                                      cwd=Path(variables["WORK"]))
            result["exit_code"] = proc.returncode
            result["ok"] = proc.returncode == expect_exit
            if not result["ok"]:
                result["detail"] = (proc.stderr or proc.stdout or "")[-400:]
            source = check.get("json_file")
            if source:
                target = Path(_expand(source, variables))
                if target.is_file():
                    document = json.loads(target.read_text(encoding="utf-8"))
                else:
                    result["ok"] = False
                    result["detail"] = f"expected JSON not produced: {target}"
            elif check.get("assert_json"):
                document = json.loads(proc.stdout or "null")
        elif kind == "shell":
            command = _expand(check["command"], variables)
            proc = sandbox.run([command], shell=True,
                               cwd=Path(variables["WORK"]))
            result["exit_code"] = proc.returncode
            result["ok"] = proc.returncode == expect_exit
            if not result["ok"]:
                result["detail"] = (proc.stderr or proc.stdout or "")[-400:]
        elif kind == "file":
            target = Path(_expand(check["path"], variables))
            mode = check.get("mode", "exists")
            if mode == "exists":
                result["ok"] = target.exists()
            elif mode == "absent":
                result["ok"] = not target.exists()
            else:
                result["ok"] = target.is_file() and target.stat().st_size > 0
            result["detail"] = None if result["ok"] else f"{mode} failed: {target}"
        elif kind == "geometry":
            before = json.loads(Path(_expand(check["before"], variables))
                                .read_text(encoding="utf-8"))
            after = json.loads(Path(_expand(check["after"], variables))
                               .read_text(encoding="utf-8"))
            result["ok"] = _geometry_signature(before) == _geometry_signature(after)
            result["detail"] = None if result["ok"] else (
                "table geometry changed between the blank and filled profile")
        elif kind == "idempotence":
            before = Path(_expand(check["before"], variables))
            after = Path(_expand(check["after"], variables))
            result["ok"] = _zip_member_digest(before) == _zip_member_digest(after)
            result["detail"] = None if result["ok"] else (
                "zip member contents differ between the two fill runs")
        elif kind == "residue":
            # Form-fill keep derivation (form-eval-scenarios.md, W5.3
            # protocol note 1): on a FILL the form's own labels legitimately
            # survive, so keep = inventory entries still present in the
            # artifact. Non-vacuity is enforced separately: at least
            # ``require_consumed`` inventory entries must have DISAPPEARED,
            # otherwise a do-nothing agent would score a green residue gate.
            profile_path = Path(_expand(check["profile"], variables))
            artifact = Path(_expand(check["artifact"], variables))
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            text = artifact_text(artifact)
            # ``baseline`` (the blank form) makes "consumed" a DIFFERENCE
            # rather than an absolute: some scan strings never appear verbatim
            # in extracted text (run splits, spacing), and counting those as
            # consumed would hand a do-nothing agent a free non-vacuity point.
            baseline = check.get("baseline")
            baseline_text = (artifact_text(Path(_expand(baseline, variables)))
                             if baseline else None)
            keep, consumed = [], []
            for entry in _profile_inventory_texts(profile):
                normalized = _WS_RE.sub(" ", entry).strip()
                if not normalized:
                    continue
                if normalized in text:
                    keep.append(entry)
                elif baseline_text is None or normalized in baseline_text:
                    consumed.append(entry)
            argv: list[str] = ["--form-profile", str(profile_path),
                               "--artifact", str(artifact)]
            for entry in keep:
                argv += ["--keep", entry]
            proc = sandbox.run_python(
                sandbox.install / "pipeline" / "scripts" / "check_residue.py",
                argv, cwd=Path(variables["WORK"]))
            required = int(check.get("require_consumed", 1))
            result["exit_code"] = proc.returncode
            result["kept"] = len(keep)
            result["consumed"] = consumed
            gate_ok = proc.returncode == expect_exit
            vacuous = len(consumed) < required
            result["ok"] = gate_ok and not vacuous
            if not gate_ok:
                result["detail"] = (proc.stdout or proc.stderr or "")[-400:]
            elif vacuous:
                result["detail"] = (
                    f"residue gate is vacuous: only {len(consumed)} inventory "
                    f"entr(y/ies) consumed, {required} required — the fill "
                    "did not remove anything the form asked to be filled")
        elif kind == "unmodified":
            # Non-destructive contract: the sandbox copy of the input must
            # still hash to what `task` recorded when it copied it in.
            manifest = json.loads(
                (Path(variables["WORK"]) / "task.json").read_text(
                    encoding="utf-8"))
            wanted = check["input"]
            rows = [row for row in manifest["inputs"]
                    if Path(row["sandbox_path"]).name == wanted]
            if not rows:
                result["ok"] = False
                result["detail"] = f"no task input named {wanted!r}"
            else:
                target = Path(rows[0]["sandbox_path"])
                actual = _sha256_file(target) if target.is_file() else None
                result["ok"] = actual == rows[0]["sha256"]
                result["detail"] = None if result["ok"] else (
                    f"input {wanted} was modified in place "
                    f"(expected {rows[0]['sha256'][:12]}, got "
                    f"{(actual or 'missing')[:12]})")
        elif kind in ("text_present", "text_absent"):
            artifact = Path(_expand(check["artifact"], variables))
            text = artifact_text(artifact)
            wanted = kind == "text_present"
            offenders = [s for s in check["strings"]
                         if (_WS_RE.sub(" ", s).strip() in text) != wanted]
            result["ok"] = not offenders
            result["detail"] = None if result["ok"] else (
                f"{'missing' if wanted else 'still present'}: {offenders}")
        else:  # pragma: no cover — validate_task rejects unknown kinds
            raise CleanroomError(f"unsupported check kind {kind!r}")
    except CleanroomError:
        raise
    except Exception as exc:
        result["ok"] = False
        result["detail"] = f"{type(exc).__name__}: {exc}"

    if check.get("assert_json"):
        if document is None:
            result["ok"] = False
            result.setdefault("detail", "no JSON document to assert against")
            result["assertions"] = []
        else:
            assertions = evaluate_assertions(document, check["assert_json"])
            result["assertions"] = assertions
            if not all(row["ok"] for row in assertions):
                result["ok"] = False
    result["status"] = "pass" if result.get("ok") else "fail"
    return result


def run_checks(root: Path | str, task: dict[str, Any], *,
               extra_forbidden: Iterable[str | Path] = ()) -> dict[str, Any]:
    sandbox = Sandbox(root, extra_forbidden)
    work = sandbox.work / task["id"]
    if not work.is_dir():
        raise CleanroomError(
            f"task {task['id']} was never materialized in {sandbox.root} — "
            "run `task` first", exit_code=2)
    variables = {
        "SANDBOX": str(sandbox.root),
        "INSTALL": str(sandbox.install),
        "WORK": str(work),
        "INPUTS": str(work / "inputs"),
        "SKILLS": str(sandbox.skills),
    }
    modules = sandbox_modules(sandbox)
    baseline = task_baseline(work, task)
    if baseline:
        variables["BASELINE"] = baseline
    results = [run_machine_check(sandbox, check, variables,
                                 enabled_modules=modules["enabled"],
                                 checkers=modules["checkers"],
                                 baseline=baseline)
               for check in task["machine_checks"]]
    passed = sum(1 for row in results if row["status"] == "pass")
    failed = sum(1 for row in results if row["status"] == "fail")
    skipped = sum(1 for row in results if row["status"] == "skipped")
    payload = {
        "schema": CHECKS_SCHEMA,
        "task_id": task["id"],
        "family": task["family"],
        "sandbox_root": str(sandbox.root),
        "enabled_modules": modules["enabled"],
        "baseline": baseline,
        "counts": {"pass": passed, "fail": failed, "skipped": skipped,
                   "total": len(results)},
        "ok": failed == 0,
        "checks": results,
    }
    (work / "checks.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clean-room validation harness: install rigorloom from "
                    "dist bundles into a throwaway root and prove nothing "
                    "resolves back to the source checkout.")
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", help="install bundles into a fresh root")
    prep.add_argument("--bundle", action="append", required=True, metavar="ZIP")
    prep.add_argument("--root", required=True, help="empty sandbox directory")
    prep.add_argument("--enable", default="all",
                      help="all | none | comma-separated module names")
    prep.add_argument("--allow-gap", action="append", default=[],
                      metavar="ID", help=f"known gaps: {sorted(_ALLOWED_GAPS)}")
    prep.add_argument("--extra-forbidden-root", action="append", default=[],
                      metavar="DIR",
                      help="additional root the sandbox must not reference")
    prep.add_argument("--skip-skill", action="store_true",
                      help="do not attempt the skill install step")

    cont = sub.add_parser("verify-containment",
                          help="re-run containment over a prepared root")
    cont.add_argument("--root", required=True)
    cont.add_argument("--extra-forbidden-root", action="append", default=[])
    cont.add_argument("--no-runtime", action="store_true",
                      help="skip the import-origin subprocess probe")

    mat = sub.add_parser("task", help="materialize a task into the sandbox")
    mat.add_argument("--root", required=True)
    mat.add_argument("--task", required=True, metavar="YAML")
    mat.add_argument("--corpus-root", default=str(DEFAULT_CORPUS_ROOT))
    mat.add_argument("--extra-forbidden-root", action="append", default=[])

    chk = sub.add_parser("check", help="run a task's machine checks")
    chk.add_argument("--root", required=True)
    chk.add_argument("--task", required=True, metavar="YAML")
    chk.add_argument("--extra-forbidden-root", action="append", default=[])

    lst = sub.add_parser("list-tasks", help="JSON inventory of task definitions")
    lst.add_argument("--tasks-dir", default=str(TASKS_DIR))

    args = parser.parse_args(argv)

    try:
        if args.command == "prepare":
            report, code = prepare(
                args.root, args.bundle, enable=args.enable,
                allow_gaps=args.allow_gap,
                extra_forbidden=args.extra_forbidden_root,
                skip_skill=args.skip_skill)
            _emit({"ok": report["ok"], "root": report["sandbox_root"],
                   "enabled": report["registry"]["enabled"],
                   "gaps": [gap["id"] for gap in report["gaps"]],
                   "contained": report["containment"]["contained"],
                   "failures": report["failures"],
                   "report": str(Path(report["sandbox_root"]) /
                                 "install_report.json")})
            return code
        if args.command == "verify-containment":
            sandbox = Sandbox(args.root, args.extra_forbidden_root)
            report = containment_report(sandbox, runtime=not args.no_runtime)
            _emit(report)
            return 0 if report["contained"] else 3
        if args.command == "task":
            task = load_task(args.task)
            payload = materialize_task(
                args.root, task, corpus_root=args.corpus_root,
                extra_forbidden=args.extra_forbidden_root)
            _emit({"ok": True, "task_id": payload["id"],
                   "work_dir": payload["work_dir"],
                   "inputs": [row["sandbox_path"] for row in payload["inputs"]],
                   "prompt_file": str(Path(payload["work_dir"]) / "PROMPT.txt")})
            return 0
        if args.command == "check":
            task = load_task(args.task)
            payload = run_checks(args.root, task,
                                 extra_forbidden=args.extra_forbidden_root)
            _emit(payload)
            return 0 if payload["ok"] else 3
        if args.command == "list-tasks":
            tasks = load_tasks(args.tasks_dir)
            _emit({"ok": True, "count": len(tasks), "tasks": [
                {"id": t["id"], "family": t["family"],
                 "blocked_on": t.get("blocked_on"),
                 "checks": len(t["machine_checks"]),
                 "rubric_lines": len(t["expected_behavior"])}
                for t in tasks]})
            return 0
    except CleanroomError as exc:
        _emit({"ok": False, "error": str(exc)})
        return exc.exit_code
    return 2  # pragma: no cover


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
