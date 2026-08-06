#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Distribution-module registry (Wave 3 contract, plan §3.1).

Terminology guard: the things this registry manages are **distribution
modules** — packaging/capability units declared by ``modules/<name>/module.yaml``
per ``pipeline/references/module.schema.json`` and ``modules/README.md``. They
are unrelated to the v0.12 **stage contracts** in
``pipeline/references/modules.yaml`` (pipeline stage composition, consumed by
``compose.py``), which keep working untouched.

Contract rules enforced here:

- Core never imports a module: core code calls the typed accessors
  (``enabled_checkers()`` …) and never a module's name.
- Absence is not failure: a missing/empty ``modules/`` tree or a missing
  ``modules/enabled.yaml`` yields an empty registry, never an error.
- Presence is integration: enabling a module surfaces its declared
  contributions with no further configuration.
- Invalid declarations are loud: a malformed ``module.yaml`` raises
  ``ModuleError`` naming the module — never a silent skip.
- Version gate: ``requires.rigorloom`` is checked against the project version
  from ``pyproject.toml``; an unsatisfied range is a load refusal.

Stdlib-only by design (a core-only install carries no extra dependencies);
``module.yaml`` is parsed with a strict pure-literal YAML subset documented in
``modules/README.md``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODULES_ROOT = REPO_ROOT / "modules"
DEFAULT_PYPROJECT = REPO_ROOT / "pyproject.toml"
MODULE_MANIFEST = "module.yaml"
ENABLED_FILE = "enabled.yaml"
MODULE_SCHEMA = "rigorloom-module/v1"
ENABLED_SCHEMA = "rigorloom-enabled-modules/v1"

_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_CHECKER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PACK_TYPE_RE = _CHECKER_NAME_RE
_STATE_POLICIES = ("stage_machine", "receipts", "stateless")
_PROVIDES_KEYS = (
    "checkers", "cli", "pack_types", "run_modes",
    "studio_panels", "skill", "playbooks",
)
_COMPARATOR_RE = re.compile(r"^(==|!=|>=|<=|>|<)\s*(\d+(?:\.\d+){0,2})$")


class ModuleError(Exception):
    """Loud failure for anything wrong with a distribution module."""


# ---------------------------------------------------------------------------
# Strict pure-literal YAML subset
# ---------------------------------------------------------------------------

def _strip_comment(line: str) -> str:
    """Drop an inline comment, honouring single/double quotes."""
    quote = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index]
    return line


def _scalar(token: str, where: str) -> Any:
    token = token.strip()
    if not token:
        raise ModuleError(f"{where}: empty scalar")
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        return token[1:-1]
    lowered = token.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    if lowered in ("null", "~", "none"):
        return None
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d+\.\d+", token):
        return float(token)
    return token


def _split_flow(body: str, where: str) -> list[str]:
    """Split flow-collection innards on top-level commas."""
    parts: list[str] = []
    depth = 0
    quote = None
    current = ""
    for char in body:
        if quote:
            current += char
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            current += char
        elif char in "{[":
            depth += 1
            current += char
        elif char in "}]":
            depth -= 1
            if depth < 0:
                raise ModuleError(f"{where}: unbalanced flow collection")
            current += char
        elif char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    if quote or depth:
        raise ModuleError(f"{where}: unbalanced flow collection")
    if current.strip():
        parts.append(current)
    return parts


def _flow_value(token: str, where: str) -> Any:
    token = token.strip()
    if token.startswith("{"):
        if not token.endswith("}"):
            raise ModuleError(f"{where}: unterminated flow mapping")
        payload: dict[str, Any] = {}
        for part in _split_flow(token[1:-1], where):
            if ":" not in part:
                raise ModuleError(
                    f"{where}: flow mapping entry {part.strip()!r} has no ':'")
            key, value = part.split(":", 1)
            key = str(_scalar(key, where))
            if key in payload:
                raise ModuleError(f"{where}: duplicate key {key!r}")
            payload[key] = _flow_value(value, where)
        return payload
    if token.startswith("["):
        if not token.endswith("]"):
            raise ModuleError(f"{where}: unterminated flow list")
        return [_flow_value(part, where) for part in _split_flow(token[1:-1], where)]
    return _scalar(token, where)


@dataclass
class _Line:
    number: int
    indent: int
    text: str


def _logical_lines(text: str, where: str) -> list[_Line]:
    lines: list[_Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ModuleError(f"{where}:{number}: tabs are not allowed in indentation")
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip():
            continue
        lines.append(_Line(number, len(stripped) - len(stripped.lstrip()), stripped.strip()))
    return lines


def _parse_block(lines: list[_Line], pos: int, indent: int, where: str) -> tuple[Any, int]:
    """Parse the block starting at ``lines[pos]`` (all at ``indent``)."""
    if lines[pos].text.startswith("- "):
        return _parse_list(lines, pos, indent, where)
    return _parse_map(lines, pos, indent, where)


def _parse_map(lines: list[_Line], pos: int, indent: int, where: str) -> tuple[dict, int]:
    payload: dict[str, Any] = {}
    while pos < len(lines) and lines[pos].indent == indent:
        line = lines[pos]
        if line.text.startswith("- "):
            raise ModuleError(
                f"{where}:{line.number}: list item at mapping indentation")
        if ":" not in line.text:
            raise ModuleError(f"{where}:{line.number}: expected 'key: value'")
        key, value = line.text.split(":", 1)
        key = str(_scalar(key, f"{where}:{line.number}"))
        if key in payload:
            raise ModuleError(f"{where}:{line.number}: duplicate key {key!r}")
        value = value.strip()
        if value:
            payload[key] = _flow_value(value, f"{where}:{line.number}")
            pos += 1
        else:
            pos += 1
            if pos < len(lines) and lines[pos].indent > indent:
                payload[key], pos = _parse_block(lines, pos, lines[pos].indent, where)
            else:
                payload[key] = None
        if pos < len(lines) and lines[pos].indent > indent:
            raise ModuleError(
                f"{where}:{lines[pos].number}: unexpected indentation")
    return payload, pos


def _parse_list(lines: list[_Line], pos: int, indent: int, where: str) -> tuple[list, int]:
    items: list[Any] = []
    while pos < len(lines) and lines[pos].indent == indent:
        line = lines[pos]
        if not line.text.startswith("- "):
            raise ModuleError(
                f"{where}:{line.number}: expected '- ' list item")
        body = line.text[2:].strip()
        if not body:
            raise ModuleError(
                f"{where}:{line.number}: empty list items are not supported")
        items.append(_flow_value(body, f"{where}:{line.number}"))
        pos += 1
        if pos < len(lines) and lines[pos].indent > indent:
            raise ModuleError(
                f"{where}:{lines[pos].number}: nested block under a list item "
                "is not supported — use a flow mapping ({key: value, ...})")
    return items, pos


def parse_yaml_subset(text: str, where: str) -> dict:
    """Parse the documented pure-literal YAML subset into a dict."""
    lines = _logical_lines(text, where)
    if not lines:
        return {}
    if lines[0].indent != 0:
        raise ModuleError(f"{where}:{lines[0].number}: top level must not be indented")
    payload, pos = _parse_map(lines, 0, 0, where)
    if pos != len(lines):
        raise ModuleError(f"{where}:{lines[pos].number}: unparsed trailing content")
    return payload


# ---------------------------------------------------------------------------
# Project version + range gate
# ---------------------------------------------------------------------------

def project_version(pyproject: Path = DEFAULT_PYPROJECT) -> str:
    """Read [project].version from pyproject.toml (the single version source)."""
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError as exc:
        raise ModuleError(f"cannot read project version: {pyproject}: {exc}") from exc
    try:
        import tomllib
        version = tomllib.loads(text).get("project", {}).get("version")
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        version = match.group(1) if match else None
    if not version:
        raise ModuleError(f"no [project].version in {pyproject}")
    return str(version)


def _version_tuple(version: str, where: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", version.strip())
    if not match:
        raise ModuleError(f"{where}: unparseable version {version!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def version_satisfies(version: str, range_spec: str, where: str = "requires.rigorloom") -> bool:
    """True when ``version`` satisfies the comma-ANDed comparator range."""
    actual = _version_tuple(version, where)
    for clause in range_spec.split(","):
        clause = clause.strip()
        match = _COMPARATOR_RE.match(clause)
        if not match:
            raise ModuleError(
                f"{where}: invalid range clause {clause!r} "
                "(expected comparator + dotted version, e.g. '>=0.16')")
        op, bound = match.group(1), _version_tuple(match.group(2), where)
        satisfied = {
            "==": actual == bound,
            "!=": actual != bound,
            ">=": actual >= bound,
            "<=": actual <= bound,
            ">": actual > bound,
            "<": actual < bound,
        }[op]
        if not satisfied:
            return False
    return True


# ---------------------------------------------------------------------------
# Declaration validation (mirrors pipeline/references/module.schema.json)
# ---------------------------------------------------------------------------

def _fail(module: str, message: str) -> None:
    raise ModuleError(f"distribution module '{module}': {message}")


def _require_str(module: str, value: Any, where: str, pattern: re.Pattern | None = None) -> str:
    if not isinstance(value, str) or not value:
        _fail(module, f"{where} must be a non-empty string, got {value!r}")
    if pattern and not pattern.fullmatch(value):
        _fail(module, f"{where} {value!r} does not match {pattern.pattern}")
    return value


def _require_entry_list(
    module: str, value: Any, where: str, fields: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _fail(module, f"provides.{where} must be a list, got {type(value).__name__}")
    entries = []
    for index, item in enumerate(value):
        spot = f"provides.{where}[{index}]"
        if not isinstance(item, dict):
            _fail(module, f"{spot} must be a mapping, got {item!r}")
        unknown = sorted(set(item) - set(fields))
        if unknown:
            _fail(module, f"{spot} has unknown keys {unknown}")
        entry = {}
        for name, rule in fields.items():
            if name not in item:
                _fail(module, f"{spot} is missing required key '{name}'")
            if rule == "gates":
                gates = item[name]
                if not isinstance(gates, list) or not all(
                    isinstance(gate, str) and gate for gate in gates
                ):
                    _fail(module, f"{spot}.{name} must be a list of non-empty strings")
                entry[name] = list(gates)
            elif isinstance(rule, tuple):
                choice = item[name]
                if choice not in rule:
                    _fail(module, f"{spot}.{name} must be one of {list(rule)}, got {choice!r}")
                entry[name] = choice
            else:
                entry[name] = _require_str(module, item[name], f"{spot}.{name}", rule)
        entries.append(entry)
    return entries


def validate_declaration(module: str, payload: Any) -> dict[str, Any]:
    """Validate a parsed module.yaml; return it normalized. Loud on any flaw."""
    if not isinstance(payload, dict):
        _fail(module, "module.yaml root must be a mapping")
    unknown = sorted(set(payload) - {"schema", "name", "requires", "provides"})
    if unknown:
        _fail(module, f"unknown top-level keys {unknown}")
    for required in ("schema", "name", "requires", "provides"):
        if required not in payload:
            _fail(module, f"missing required key '{required}'")
    if payload["schema"] != MODULE_SCHEMA:
        _fail(module, f"schema must be '{MODULE_SCHEMA}', got {payload['schema']!r}")
    name = _require_str(module, payload["name"], "name", _NAME_RE)
    if name != module:
        _fail(module, f"name {name!r} must equal its directory name '{module}'")
    requires = payload["requires"]
    if not isinstance(requires, dict) or set(requires) != {"rigorloom"}:
        _fail(module, "requires must be exactly {rigorloom: \"<range>\"}")
    range_spec = _require_str(module, requires["rigorloom"], "requires.rigorloom")
    # Parse eagerly so a bad range is a validation error, not a gate-time one.
    version_satisfies("0.0.0", range_spec, f"module '{module}' requires.rigorloom")

    provides = payload["provides"]
    if provides is None:
        provides = {}
    if not isinstance(provides, dict):
        _fail(module, "provides must be a mapping")
    unknown = sorted(set(provides) - set(_PROVIDES_KEYS))
    if unknown:
        _fail(module, f"provides has unknown keys {unknown} "
                      f"(known: {list(_PROVIDES_KEYS)})")

    normalized: dict[str, Any] = {
        "schema": MODULE_SCHEMA, "name": name,
        "requires": {"rigorloom": range_spec}, "provides": {},
    }
    out = normalized["provides"]
    if "checkers" in provides:
        out["checkers"] = _require_entry_list(
            module, provides["checkers"], "checkers",
            {"name": _CHECKER_NAME_RE, "script": None})
    if "cli" in provides:
        out["cli"] = _require_entry_list(
            module, provides["cli"], "cli",
            {"command": _NAME_RE, "script": None})
    if "pack_types" in provides:
        packs = provides["pack_types"]
        if not isinstance(packs, list):
            _fail(module, "provides.pack_types must be a list of names")
        out["pack_types"] = [
            _require_str(module, item, f"provides.pack_types[{idx}]", _PACK_TYPE_RE)
            for idx, item in enumerate(packs)]
    if "run_modes" in provides:
        out["run_modes"] = _require_entry_list(
            module, provides["run_modes"], "run_modes",
            {"name": _NAME_RE, "state_policy": _STATE_POLICIES, "gates": "gates"})
    if "studio_panels" in provides:
        out["studio_panels"] = _require_entry_list(
            module, provides["studio_panels"], "studio_panels",
            {"id": _NAME_RE, "title": None, "entry": None})
    if "skill" in provides:
        skill = provides["skill"]
        if not isinstance(skill, dict):
            _fail(module, "provides.skill must be a mapping {fragment, references}")
        unknown = sorted(set(skill) - {"fragment", "references"})
        if unknown:
            _fail(module, f"provides.skill has unknown keys {unknown}")
        fragment = _require_str(module, skill.get("fragment"), "provides.skill.fragment")
        references = skill.get("references", [])
        if not isinstance(references, list):
            _fail(module, "provides.skill.references must be a list of paths")
        out["skill"] = {
            "fragment": fragment,
            "references": [
                _require_str(module, item, f"provides.skill.references[{idx}]")
                for idx, item in enumerate(references)],
        }
    if "playbooks" in provides:
        playbooks = provides["playbooks"]
        if not isinstance(playbooks, list):
            _fail(module, "provides.playbooks must be a list of paths")
        out["playbooks"] = [
            _require_str(module, item, f"provides.playbooks[{idx}]")
            for idx, item in enumerate(playbooks)]
    return normalized


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModuleSpec:
    name: str
    root: Path
    requires: str
    provides: dict = field(compare=False)

    def payload_path(self, relative: str) -> Path:
        resolved = (self.root / relative).resolve()
        if self.root.resolve() not in resolved.parents and resolved != self.root.resolve():
            raise ModuleError(
                f"distribution module '{self.name}': payload path {relative!r} "
                "escapes the module directory")
        return resolved


class ModuleRegistry:
    """Discovery + enablement + typed accessors for distribution modules."""

    def __init__(
        self,
        modules_root: Path | str = DEFAULT_MODULES_ROOT,
        *,
        enabled_file: Path | str | None = None,
        version: str | None = None,
        pyproject: Path | str = DEFAULT_PYPROJECT,
    ) -> None:
        self.modules_root = Path(modules_root)
        self.enabled_file = (
            Path(enabled_file) if enabled_file is not None
            else self.modules_root / ENABLED_FILE)
        self._version = version
        self._pyproject = Path(pyproject)
        self._discovered: dict[str, ModuleSpec] | None = None
        self._enabled: list[ModuleSpec] | None = None

    # -- discovery ----------------------------------------------------------

    @property
    def version(self) -> str:
        if self._version is None:
            self._version = project_version(self._pyproject)
        return self._version

    def discover(self) -> dict[str, ModuleSpec]:
        """Validate and return every modules/<name>/module.yaml (enabled or not)."""
        if self._discovered is not None:
            return self._discovered
        found: dict[str, ModuleSpec] = {}
        if self.modules_root.is_dir():
            for manifest in sorted(self.modules_root.glob(f"*/{MODULE_MANIFEST}")):
                module = manifest.parent.name
                try:
                    text = manifest.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as exc:
                    _fail(module, f"module.yaml unreadable: {exc}")
                payload = parse_yaml_subset(text, str(manifest))
                declaration = validate_declaration(module, payload)
                found[module] = ModuleSpec(
                    name=module,
                    root=manifest.parent,
                    requires=declaration["requires"]["rigorloom"],
                    provides=declaration["provides"],
                )
        self._discovered = found
        return found

    # -- enablement ---------------------------------------------------------

    def enabled_names(self) -> list[str]:
        """Names listed in enabled.yaml; missing file = none = core-only."""
        if not self.enabled_file.is_file():
            return []
        payload = parse_yaml_subset(
            self.enabled_file.read_text(encoding="utf-8"), str(self.enabled_file))
        if not payload:
            return []
        if set(payload) - {"schema", "enabled"}:
            raise ModuleError(
                f"{self.enabled_file}: unknown keys "
                f"{sorted(set(payload) - {'schema', 'enabled'})}")
        if payload.get("schema") != ENABLED_SCHEMA:
            raise ModuleError(
                f"{self.enabled_file}: schema must be '{ENABLED_SCHEMA}'")
        names = payload.get("enabled") or []
        if not isinstance(names, list) or not all(
            isinstance(name, str) and name for name in names
        ):
            raise ModuleError(f"{self.enabled_file}: enabled must be a list of names")
        if len(names) != len(set(names)):
            raise ModuleError(f"{self.enabled_file}: enabled list has duplicates")
        return list(names)

    def enabled_modules(self) -> list[ModuleSpec]:
        """Enabled, version-gated, payload-checked, collision-checked specs."""
        if self._enabled is not None:
            return self._enabled
        discovered = self.discover()
        specs: list[ModuleSpec] = []
        for name in self.enabled_names():
            if name not in discovered:
                raise ModuleError(
                    f"enabled.yaml names distribution module '{name}' but "
                    f"{self.modules_root / name / MODULE_MANIFEST} does not exist")
            spec = discovered[name]
            if not version_satisfies(
                self.version, spec.requires,
                f"module '{name}' requires.rigorloom",
            ):
                raise ModuleError(
                    f"refusing to load distribution module '{name}': it requires "
                    f"rigorloom '{spec.requires}' but this project is version "
                    f"{self.version} (from {self._pyproject})")
            self._check_payload_paths(spec)
            specs.append(spec)
        self._check_collisions(specs)
        self._enabled = specs
        return specs

    def _check_payload_paths(self, spec: ModuleSpec) -> None:
        for relative in _declared_paths(spec.provides):
            if not spec.payload_path(relative).is_file():
                _fail(spec.name, f"declared payload file is missing: {relative}")

    @staticmethod
    def _check_collisions(specs: list[ModuleSpec]) -> None:
        for kind, keys in (
            ("checkers", "name"), ("cli", "command"),
            ("run_modes", "name"), ("studio_panels", "id"),
        ):
            seen: dict[str, str] = {}
            for spec in specs:
                for entry in spec.provides.get(kind, []):
                    value = entry[keys]
                    if value in seen:
                        raise ModuleError(
                            f"distribution modules '{seen[value]}' and "
                            f"'{spec.name}' both provide {kind} {keys}={value!r}")
                    seen[value] = spec.name
        seen = {}
        for spec in specs:
            for pack in spec.provides.get("pack_types", []):
                if pack in seen:
                    raise ModuleError(
                        f"distribution modules '{seen[pack]}' and '{spec.name}' "
                        f"both provide pack_type {pack!r}")
                seen[pack] = spec.name

    # -- typed accessors (core consumes these; never module names) -----------

    def _entries(self, kind: str, path_keys: tuple[str, ...]) -> list[dict[str, Any]]:
        rows = []
        for spec in self.enabled_modules():
            for entry in spec.provides.get(kind, []):
                row = dict(entry)
                for key in path_keys:
                    row[key] = str(spec.payload_path(entry[key]))
                row["module"] = spec.name
                rows.append(row)
        return rows

    def enabled_checkers(self) -> list[dict[str, Any]]:
        """[{name, script(abs path), module}] across all enabled modules."""
        return self._entries("checkers", ("script",))

    def enabled_cli(self) -> list[dict[str, Any]]:
        """[{command, script(abs path), module}]."""
        return self._entries("cli", ("script",))

    def enabled_pack_types(self) -> list[str]:
        """Pack-type names contributed by enabled modules."""
        packs: list[str] = []
        for spec in self.enabled_modules():
            packs.extend(spec.provides.get("pack_types", []))
        return packs

    def enabled_run_modes(self) -> list[dict[str, Any]]:
        """[{name, state_policy, gates, module}]."""
        return self._entries("run_modes", ())

    def enabled_studio_panels(self) -> list[dict[str, Any]]:
        """[{id, title, entry(abs path), module}]."""
        return self._entries("studio_panels", ("entry",))

    def enabled_skill_fragments(self) -> list[dict[str, Any]]:
        """[{fragment(abs), references([abs]), module}]."""
        rows = []
        for spec in self.enabled_modules():
            skill = spec.provides.get("skill")
            if skill:
                rows.append({
                    "fragment": str(spec.payload_path(skill["fragment"])),
                    "references": [
                        str(spec.payload_path(ref)) for ref in skill["references"]],
                    "module": spec.name,
                })
        return rows

    def enabled_playbooks(self) -> list[dict[str, Any]]:
        """[{path(abs), module}]."""
        rows = []
        for spec in self.enabled_modules():
            for playbook in spec.provides.get("playbooks", []):
                rows.append({
                    "path": str(spec.payload_path(playbook)),
                    "module": spec.name,
                })
        return rows

    # -- summary --------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        discovered = self.discover()
        enabled = self.enabled_modules()
        return {
            "schema": "rigorloom-module-registry/v1",
            "version": self.version,
            "modules_root": str(self.modules_root),
            "discovered": sorted(discovered),
            "enabled": [spec.name for spec in enabled],
            "checkers": self.enabled_checkers(),
            "cli": self.enabled_cli(),
            "pack_types": self.enabled_pack_types(),
            "run_modes": self.enabled_run_modes(),
            "studio_panels": self.enabled_studio_panels(),
            "skill_fragments": self.enabled_skill_fragments(),
            "playbooks": self.enabled_playbooks(),
        }


def _declared_paths(provides: dict[str, Any]) -> Iterator[str]:
    for entry in provides.get("checkers", []):
        yield entry["script"]
    for entry in provides.get("cli", []):
        yield entry["script"]
    for entry in provides.get("studio_panels", []):
        yield entry["entry"]
    skill = provides.get("skill")
    if skill:
        yield skill["fragment"]
        yield from skill["references"]
    yield from provides.get("playbooks", [])


def write_enabled(
    modules_root: Path | str,
    names: list[str],
    *,
    enabled_file: Path | str | None = None,
) -> Path:
    """Write modules/enabled.yaml naming ``names`` (deduplicated, ordered)."""
    root = Path(modules_root)
    target = Path(enabled_file) if enabled_file is not None else root / ENABLED_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    listed = ", ".join(dict.fromkeys(names))
    target.write_text(
        f"schema: {ENABLED_SCHEMA}\nenabled: [{listed}]\n", encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Distribution-module registry (list / write-enabled). "
                    "Not the v0.12 stage-contract catalog — that is compose.py.")
    parser.add_argument("--modules-root", default=str(DEFAULT_MODULES_ROOT))
    parser.add_argument("--pyproject", default=str(DEFAULT_PYPROJECT))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="JSON summary of discovered/enabled modules")
    enable = sub.add_parser(
        "write-enabled", help="write modules/enabled.yaml")
    group = enable.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", dest="all_modules",
                       help="enable every discovered distribution module")
    group.add_argument("--none", action="store_true", dest="no_modules",
                       help="enable nothing (explicit core-only)")
    group.add_argument("--names", nargs="+", metavar="NAME")
    args = parser.parse_args(argv)

    registry = ModuleRegistry(args.modules_root, pyproject=args.pyproject)
    try:
        if args.command == "write-enabled":
            if args.all_modules:
                names = sorted(registry.discover())
            elif args.no_modules:
                names = []
            else:
                names = args.names
            target = write_enabled(args.modules_root, names)
            registry = ModuleRegistry(args.modules_root, pyproject=args.pyproject)
            payload = registry.summary()
            payload["written"] = str(target)
        else:
            payload = registry.summary()
    except ModuleError as exc:
        json.dump({"ok": False, "error": str(exc)}, sys.stdout, ensure_ascii=False)
        print()
        return 3
    payload["ok"] = True
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
