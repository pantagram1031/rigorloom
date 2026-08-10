#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-module packaging (v0.16 plan §3.5): standalone installable bundles.

``--module <name>`` emits ``rigorloom-<name>-<version>.zip`` containing the
distribution module's directory (payload + module.yaml) plus a generated
``MANIFEST.json`` (name, version = rigorloom project version, requires,
per-file sha256, provides summary) and an ``INSTALL.md`` (drop into
``modules/<name>/``, enable via the module_registry CLI).

``--module core`` emits the core bundle: ``engine/`` + the pipeline core
(``pipeline/scripts``, ``pipeline/adapters_impl``,
 ``pipeline/references``) + ``studio/`` + the router
skill surface (``skill/SKILL.md`` + ``skill/references/``) + the skill
installer (``scripts/sync_local.py`` + ``scripts/sync_manifest.example.yaml``)
+ ``modules/README.md`` (the distribution-module contract; no module
payloads) + ``pyproject.toml``/``LICENSE``.

Validation before anything is written:

- the module's ``module.yaml`` must validate (registry discovery is reused —
  a malformed declaration is a loud refusal, exit 2);
- every declared payload file must exist (dangling path = refusal, exit 2);
- ``privacy_scan`` runs over the staged bundle and any HARD finding refuses
  the build (exit 3) — a bundle is a distribution artifact, repo hygiene
  applies with no exceptions;
- every doc path the shipped skill surface (``SKILL.md`` / ``FRAGMENT.md`` +
  ``references/*.md``) names must resolve INSIDE the staged bundle — a
  dangling reference is exit 3. Derived, not a filename list: the next one is
  caught without anyone updating this file.

``--verify <bundle>`` re-hashes a built bundle (zip or extracted directory)
against its MANIFEST.json: any mismatch, missing, or unlisted file is a
loud failure (exit 3) — tamper detection, not a checksum suggestion.

Builds are **reproducible**: the same tree produces the same bundle bytes,
so a published zip sha256 is evidence a reader can re-derive rather than a
number they must take on trust. See ``ZIP_EPOCH`` below for what is pinned
and why.

Exit codes follow the checker convention: 0 ok, 2 usage/config refusal,
3 hard findings (privacy HARD / verification mismatch).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SCRIPTS = REPO_ROOT / "pipeline" / "scripts"
if str(CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CORE_SCRIPTS))

import module_registry  # noqa: E402
import privacy_scan  # noqa: E402

MANIFEST_NAME = "MANIFEST.json"
INSTALL_NAME = "INSTALL.md"
MANIFEST_SCHEMA = "rigorloom-bundle-manifest/v1"
CORE_NAME = "core"

# Never staged into a bundle: caches and VCS state.
_JUNK_DIRS = {"__pycache__", ".git", ".pytest_cache", "node_modules"}
_JUNK_SUFFIXES = {".pyc", ".pyo"}

# ── reproducible zip writing ─────────────────────────────────────────
#
# A published zip sha256 is only evidence if the reader can re-derive it.
# Before this, `ZipFile.write(path, arcname)` stamped every member with the
# STAGING file's mtime and st_mode, so building `core` twice from an
# unchanged tree gave two different zip hashes (measured during v0.17.0
# preparation: 97092d2e… then 71943ea9…). Everything a zip member records
# other than its NAME and its CONTENT is pinned here.
#
# ── the timestamp: a fixed constant, deliberately NOT the commit date ──
#
# Deriving `date_time` from the source commit (`git log -1 --format=%ct`)
# was considered and rejected. The bundle hash must be a function of the
# TREE, and git history is not part of the tree:
#
#   * a buyer who has the tree but not the history — a source tarball, a
#     `git archive` export, an unzipped bundle, a shallow clone — gets no
#     `%ct` at all and would fall back to the constant, producing a hash
#     that disagrees with the published one for byte-identical content.
#     That reader is exactly who the release record asks to reproduce it,
#     so a commit-derived stamp is non-reproducible where it matters most.
#   * the same content can sit at different commits (rebase, cherry-pick,
#     an unrelated docs commit), which would move the hash of a bundle
#     whose files did not change.
#
# So: one constant, for everyone, always. 1980-01-01 00:00:00 is the
# earliest instant the DOS date field inside a zip can represent, which
# makes it the one value that needs no epoch, timezone, or locale
# reasoning. There is deliberately no SOURCE_DATE_EPOCH override either:
# an environment variable one builder exports and another does not is the
# same reproducibility hole moved somewhere harder to see.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

# Regular file, 0o644. Derived from st_mode otherwise, which is
# umask-dependent on POSIX and 0o666 (or 0o444 read-only) on Windows.
_ZIP_EXTERNAL_ATTR = 0o100644 << 16

# 3 = Unix. `ZipInfo.__init__` picks 0 on Windows and 3 everywhere else, so
# the build host's OS would otherwise leak into the archive bytes.
_ZIP_CREATE_SYSTEM = 3

# Pinned explicitly: the default (`compresslevel=None` -> zlib's own
# default) is not a promise, and a level change would move every hash.
_ZIP_COMPRESS_TYPE = zipfile.ZIP_DEFLATED
_ZIP_COMPRESS_LEVEL = 9

# Core bundle contents (--module core): general document-engine surface
# only — no distribution-module payloads, no test suites.
#
# ``skill/`` + ``scripts/sync_local.py`` + the manifest example are the
# *skill surface*: without all three a buyer installs the engine and has no
# way to install the router skill (the defect the v0.17 clean-room harness
# reported as ``skill_surface_not_bundled``). They are part of the product,
# not of the build tree.
_CORE_COMPONENTS = (
    "engine",
    "pipeline/scripts",
    # doc_backend.py runs from pipeline/scripts and imports this package via
    # the sibling pipeline directory.  Keep it in the core zip; sync_local's
    # flattened install mapping handles the separate target path.
    "pipeline/adapters_impl",
    "pipeline/references",
    "studio",
    "skill",
    "scripts/sync_local.py",
    "scripts/sync_manifest.example.yaml",
    "modules/README.md",
    "pyproject.toml",
    "LICENSE",
)
_CORE_EXCLUDED_DIRS = _JUNK_DIRS | {"tests"}

# Every core bundle must carry these, whatever else changes about the
# component list. Asserted against the staged tree before the manifest is
# written, so a component-list edit can never silently drop the skill
# surface again.
_CORE_REQUIRED_FILES = (
    "skill/SKILL.md",
    "scripts/sync_local.py",
    "scripts/sync_manifest.example.yaml",
    "scripts/package_module.py",
    "pipeline/scripts/module_registry.py",
    "pipeline/scripts/hwp_ingress.py",
    "pipeline/adapters_impl/__init__.py",
    "pipeline/adapters_impl/bundle_backend.py",
    "pipeline/adapters_impl/docx_backend.py",
    "engine/scripts/probe.py",
)
_CORE_REQUIRED_GLOBS = (
    ("skill/references", "*.md"),
)

# ── shipped-surface reference integrity ──────────────────────────────
#
# A skill surface that points at a document the bundle does not carry is the
# same defect class as shipping no skill at all: the reader is told to open a
# file they never received. The v0.17 clean-room run hit it on the visual
# rubric (both agents had to reverse-engineer the class vocabulary from
# source), so the guard below is DERIVED, not a filename list — every doc path
# the shipped surface mentions must resolve inside the staged bundle, so the
# next dangling reference fails the build without anyone remembering to add it.
#
# Matches an .md path inside an inline code span or a markdown link target.
_DOC_REF_RE = re.compile(r"`([^`\s]+\.md)`|\]\(\s*([^)\s#]+\.md)[^)]*\)")


def _referenced_doc_paths(text: str) -> list[str]:
    """Doc paths a markdown document tells its reader to open.

    Only *paths* count: a bare filename with no separator (``PIPELINE.md``,
    ``content.md``) names a workspace artifact the reader creates, not a file
    the bundle owes them. URLs and absolute paths are out of scope too.
    """
    found: list[str] = []
    for match in _DOC_REF_RE.finditer(text):
        ref = (match.group(1) or match.group(2) or "").strip()
        if "/" not in ref or "://" in ref or ref.startswith(("/", "<")):
            continue
        if ref not in found:
            found.append(ref)
    return found


def _surface_docs(staging: Path, skill_root: Path) -> list[Path]:
    """The shipped skill surface: SKILL.md/FRAGMENT.md + references/*.md."""
    root = staging / skill_root
    if not root.is_dir():
        return []
    docs = sorted(p for p in root.glob("*.md") if p.is_file())
    docs += sorted(p for p in (root / "references").glob("*.md")
                   if p.is_file())
    return docs


def _resolves_in_bundle(staging: Path, skill_root: Path, owner: Path,
                        ref: str) -> bool:
    """Can a reader of ``owner`` open ``ref`` from inside this bundle?

    Three legitimate spellings, because the surface is read from two places:
    relative to the installed skill root (``references/forms.md``), relative
    to the referring file, and relative to the bundle root
    (``engine/references/ops_schema.md``).
    """
    bases = (staging / skill_root, owner.parent, staging)
    for base in bases:
        try:
            candidate = (base / ref).resolve()
            candidate.relative_to(staging.resolve())
        except (OSError, ValueError):
            continue
        if candidate.is_file():
            return True
    return False


def _assert_skill_surface_references(staging: Path, skill_root: Path,
                                     label: str) -> None:
    """Every doc path the shipped skill surface names must be IN the bundle."""
    dangling: list[str] = []
    for doc in _surface_docs(staging, skill_root):
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise PackageError(
                f"{label}: unreadable skill-surface document "
                f"{doc.relative_to(staging).as_posix()}: {exc}", exit_code=3)
        for ref in _referenced_doc_paths(text):
            if not _resolves_in_bundle(staging, skill_root, doc, ref):
                dangling.append(
                    f"{doc.relative_to(staging).as_posix()} -> {ref}")
    if dangling:
        listed = "\n".join(f"  {row}" for row in dangling)
        raise PackageError(
            f"{label}: the shipped skill surface references "
            f"{len(dangling)} document(s) the bundle does not carry:\n"
            f"{listed}\nShip the file as part of the skill surface, or stop "
            "naming a path the reader cannot open.", exit_code=3)


# ── shipped-surface table integrity ──────────────────────────────────
#
# In GitHub-flavoured markdown a `|` splits cells even inside a code span; the
# only way to put one in a cell is `\|`. So `com_backend.py inspect|edit` in
# the SKILL.md routing table silently gave that row FOUR cells where every
# other row had three — the last column fell off for readers, and the routing
# table is the first thing a router reads. Cell counts are cheap to check and
# nobody will remember to; so the build checks them.


def markdown_table_cells(line: str) -> list[str]:
    """Cells of one GFM table row, honouring `\\|` and nothing else.

    Deliberately NOT code-span aware: GFM is not either. That is the whole
    point of the check.
    """
    cells: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and index + 1 < len(line):
            current.append(line[index:index + 2])
            index += 2
            continue
        if char == "|":
            cells.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    cells.append("".join(current))
    # Leading/trailing pipes are delimiters, not empty cells.
    if cells and not cells[0].strip():
        cells = cells[1:]
    if cells and not cells[-1].strip():
        cells = cells[:-1]
    return cells


def markdown_table_defects(text: str) -> list[dict]:
    """Rows whose cell count disagrees with their table's header row.

    Returns ``[{table_line, line, cells, expected, row}]`` — one entry per
    offending row, so the message can name the row a reader would lose.
    """
    defects: list[dict] = []
    block: list[tuple[int, str]] = []

    def _flush() -> None:
        if len(block) < 2:
            return
        header_line, header = block[0]
        expected = len(markdown_table_cells(header))
        for number, row in block:
            count = len(markdown_table_cells(row))
            if count != expected:
                defects.append({"table_line": header_line, "line": number,
                                "cells": count, "expected": expected,
                                "row": row.strip()[:120]})

    for number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("|"):
            block.append((number, line.strip()))
            continue
        _flush()
        block = []
    _flush()
    return defects


def _assert_skill_surface_tables(staging: Path, skill_root: Path,
                                 label: str) -> None:
    """Every table in the shipped skill surface must be rectangular."""
    broken: list[str] = []
    for doc in _surface_docs(staging, skill_root):
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue          # the reference guard already reports this
        name = doc.relative_to(staging).as_posix()
        for defect in markdown_table_defects(text):
            broken.append(
                f"{name}:{defect['line']} has {defect['cells']} cells, "
                f"header (line {defect['table_line']}) has "
                f"{defect['expected']}: {defect['row']}")
    if broken:
        listed = "\n".join(f"  {row}" for row in broken)
        raise PackageError(
            f"{label}: the shipped skill surface has "
            f"{len(broken)} ragged table row(s):\n{listed}\n"
            "A raw '|' splits a cell even inside a code span — write it as "
            "'\\|'.", exit_code=3)


class PackageError(Exception):
    """Loud packaging refusal; ``exit_code`` follows the checker convention."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_junk(path: Path) -> bool:
    return (any(part in _JUNK_DIRS for part in path.parts)
            or path.suffix.lower() in _JUNK_SUFFIXES)


def _copy_tree(source: Path, target: Path, excluded_dirs: set[str]) -> None:
    def _ignore(directory: str, names: list[str]) -> set[str]:
        del directory
        return {name for name in names
                if name in excluded_dirs
                or Path(name).suffix.lower() in _JUNK_SUFFIXES}
    shutil.copytree(source, target, ignore=_ignore)


def _provides_summary(provides: dict[str, Any]) -> dict[str, Any]:
    """Compact human/machine summary of a module's contributions."""
    keyed = {
        "checkers": "name", "cli": "command", "run_modes": "name",
        "gate_kinds": "kind", "studio_panels": "id", "preflight": "name",
    }
    summary: dict[str, Any] = {}
    for key, field in keyed.items():
        entries = provides.get(key) or []
        if entries:
            summary[key] = [entry[field] for entry in entries]
    if provides.get("pack_types"):
        summary["pack_types"] = list(provides["pack_types"])
    if provides.get("playbooks"):
        summary["playbooks"] = len(provides["playbooks"])
    if provides.get("skill"):
        summary["skill"] = True
    return summary


def _staged_members(staging: Path) -> list[tuple[str, Path]]:
    """``(posix relative path, absolute path)`` for every non-junk staged file.

    Sorted by the POSIX relative path, not by ``Path``: ``PurePath`` ordering
    is platform-dependent (Windows compares case-folded, POSIX does not), and
    ``rglob`` order is filesystem order. Both the manifest's ``files`` list and
    the zip's member order come from here, so neither can depend on the host.
    """
    members = [
        (path.relative_to(staging).as_posix(), path)
        for path in staging.rglob("*")
        if path.is_file() and not _is_junk(path.relative_to(staging))
    ]
    members.sort(key=lambda member: member[0])
    return members


def _staged_files(staging: Path) -> list[Path]:
    return [path for _, path in _staged_members(staging)
            if path.name != MANIFEST_NAME]


def _write_bundle_zip(staging: Path, bundle: Path) -> None:
    """Write the staged tree to ``bundle`` deterministically.

    Same tree in, same bytes out: fixed member order, fixed timestamp, fixed
    permissions, fixed create_system, fixed compression. Nothing here reads
    the filesystem's metadata, only its content.
    """
    with zipfile.ZipFile(bundle, "w", _ZIP_COMPRESS_TYPE,
                         compresslevel=_ZIP_COMPRESS_LEVEL) as archive:
        for name, path in _staged_members(staging):
            info = zipfile.ZipInfo(filename=name, date_time=ZIP_EPOCH)
            info.compress_type = _ZIP_COMPRESS_TYPE
            info.create_system = _ZIP_CREATE_SYSTEM
            info.external_attr = _ZIP_EXTERNAL_ATTR
            archive.writestr(info, path.read_bytes(),
                             compresslevel=_ZIP_COMPRESS_LEVEL)


def _run_privacy_gate(staging: Path) -> None:
    findings = privacy_scan.scan_tree(staging.resolve(), None)
    hard = [f for f in findings if f["severity"] == "HARD"]
    if hard:
        lines = "\n".join(
            f"  {f['file']}:{f['line'] or '-'} {f['rule']}: {f['snippet']}"
            for f in hard[:20])
        raise PackageError(
            f"privacy_scan found {len(hard)} HARD finding(s) in the staged "
            f"bundle — refusing to package:\n{lines}", exit_code=3)


_SKILL_RESYNC_NOTE = """
This module declares a skill fragment (`provides.skill`). It is merged into
the router skill only when the skill installer runs, so re-run it after
enabling this module — see "Install the skill surface" in the core bundle's
`INSTALL.md`:

```sh
python scripts/sync_local.py --manifest my-skill-manifest.yaml \\
    --checkout-root .
```

The fragment appears in the installed `SKILL.md` under `## Module: {name}`.
"""


def _module_install_md(name: str, version: str, requires: str,
                       has_skill: bool = False) -> str:
    skill_note = _SKILL_RESYNC_NOTE.format(name=name) if has_skill else ""
    return f"""# rigorloom-{name} {version} — distribution module bundle

Standalone installable bundle for the `{name}` distribution module
(requires rigorloom `{requires}`).

## Install

1. Copy `modules/{name}/` from this bundle into your rigorloom install's
   `modules/` directory (the whole directory, `module.yaml` included).
2. Enable it:

   ```sh
   python pipeline/scripts/module_registry.py write-enabled --names {name}
   ```

   (or `--all` to enable every discovered module; `enabled.yaml` is
   per-install state and is never committed.)
3. Verify: `python pipeline/scripts/module_registry.py list` must show the
   module under `enabled` with its contributions surfaced.

Presence is integration: enabling the module surfaces its checkers, CLI,
run modes, gate kinds, and studio panels with no further configuration.
{skill_note}
Verify bundle integrity any time with
`python scripts/package_module.py --verify <this bundle>`.
"""


def _core_install_md(version: str) -> str:
    return f"""# rigorloom-core {version} — core bundle

The core document engine: `engine/`, the pipeline core
(`pipeline/scripts`, `pipeline/adapters_impl`, `pipeline/references`),
`studio/`, the router skill
surface (`skill/SKILL.md` + `skill/references/`), the skill installer
(`scripts/sync_local.py` + `scripts/sync_manifest.example.yaml`), and the
distribution-module contract (`modules/README.md`). No distribution-module
payloads are included — core ships alone and runs green alone (absence is
not failure).

## Install

1. Extract this bundle into an empty directory. That directory is your
   INSTALL ROOT; every command below is run from it.
2. Install runtime dependencies as needed (`studio/requirements.txt` for
   the studio dashboard).
3. Add capability bundles by installing distribution modules
   (`rigorloom-<name>-<version>.zip`) into `modules/` and enabling them via
   `python pipeline/scripts/module_registry.py write-enabled`.

## Install the skill surface

The router skill (`rigorloom-hwp`) is what an agent loads; it is installed
OUT of this tree and INTO your agent's skills directory. Do it after
enabling modules, so their skill fragments are merged in.

1. Copy the bundled manifest example and edit it:

   ```sh
   cp scripts/sync_manifest.example.yaml my-skill-manifest.yaml
   ```

   Keep only the router-skill target. The whole file is:

   ```yaml
   install_root: "<YOUR SKILLS DIR>/rigorloom-hwp"
   merge_skill_fragments: true
   source_map:
     - from: "skill/SKILL.md"
       to: "SKILL.md"
     - from: "skill/references"
       to: "references"
     - from: "engine/scripts"
       to: "engine/scripts"
     - from: "pipeline/scripts"
       to: "pipeline/scripts"
     - from: "pipeline/adapters_impl"
       to: "pipeline/adapters_impl"
   exclude:
     - "__pycache__"
     - "*.pyc"
     - ".sync*"
   ```

   `install_root` must be ABSOLUTE — e.g.
   `~/.claude/skills/rigorloom-hwp`, or on Windows
   `C:\\\\Users\\\\<you>\\\\.claude\\\\skills\\\\rigorloom-hwp`.

2. Run the bundled installer, pointing `--checkout-root` at THIS install
   root (the `from:` paths above are resolved against it):

   ```sh
   python scripts/sync_local.py --manifest my-skill-manifest.yaml \\
       --checkout-root . --dry-run
   python scripts/sync_local.py --manifest my-skill-manifest.yaml \\
       --checkout-root .
   ```

3. Where it lands: `<install_root>/SKILL.md` (the router skill, with each
   enabled module's fragment appended under a `## Module: <name>` heading),
   `<install_root>/references/` (core references plus every enabled
   module's skill references), and the script trees the manifest maps.
   The previous install is archived to `<install_root>.bak-<timestamp>`.

`merge_skill_fragments: true` reads enablement from this install's
`modules/enabled.yaml`, so re-run the installer after enabling or disabling
a module.

Verify bundle integrity any time with
`python scripts/package_module.py --verify <this bundle>`.
"""


def _assert_module_skill_shipped(name: str, spec: Any, staging: Path) -> None:
    """A module that declares ``provides.skill`` must SHIP that fragment and
    its references inside the staged payload.

    The declaration is what the installer merges into the router SKILL.md; a
    bundle that declares a fragment it does not carry produces an install
    whose skill merge fails on a file the buyer never received. Payload
    existence is checked upstream against the checkout — this checks the
    *bundle*, which is the artifact that actually leaves the building.
    """
    skill = spec.provides.get("skill")
    if not skill:
        return
    wanted = [skill["fragment"], *skill.get("references", [])]
    missing = [relative for relative in wanted
               if not (staging / "modules" / name / relative).is_file()]
    if missing:
        raise PackageError(
            f"distribution module '{name}' declares provides.skill but the "
            f"staged bundle does not carry: {missing} — a declared skill "
            "fragment must ship with the module that declares it",
            exit_code=3)


def _assert_core_skill_surface(staging: Path) -> None:
    """The core bundle must carry the whole skill surface.

    Found by the v0.17 clean-room harness: the core bundle shipped the engine
    with no ``SKILL.md``, no references and no installer, so a buyer could not
    install the skill at all. This assertion runs over the *staged tree*, so
    the gap cannot reappear through an edit to ``_CORE_COMPONENTS``.
    """
    missing = [relative for relative in _CORE_REQUIRED_FILES
               if not (staging / relative).is_file()]
    for directory, pattern in _CORE_REQUIRED_GLOBS:
        if not sorted((staging / directory).glob(pattern)):
            missing.append(f"{directory}/{pattern}")
    if missing:
        raise PackageError(
            f"core bundle is missing required file(s): {missing} — the core "
            "bundle must ship the skill surface (SKILL.md, references, and "
            "the sync_local installer) or a buyer gets an engine with no "
            "skill", exit_code=3)


def _stage_module(name: str, staging: Path,
                  registry: "module_registry.ModuleRegistry") -> dict:
    discovered = registry.discover()  # loud on any malformed module.yaml
    if name not in discovered:
        raise PackageError(
            f"no distribution module named {name!r} under "
            f"{registry.modules_root} (discovered: {sorted(discovered)})")
    spec = discovered[name]
    # Reuse the registry's payload contract: every declared payload file
    # must exist — a dangling path is a refusal, not a silent skip.
    for relative in module_registry._declared_paths(spec.provides):
        if not spec.payload_path(relative).is_file():
            raise PackageError(
                f"distribution module '{name}': declared payload file is "
                f"missing: {relative}")
    _copy_tree(spec.root, staging / "modules" / name, _JUNK_DIRS)
    _assert_module_skill_shipped(name, spec, staging)
    declared_skill = spec.provides.get("skill")
    if declared_skill:
        # The fragment's own directory is the module's skill root — derived
        # from the declaration, never assumed to be called "skill/".
        skill_root = (Path("modules") / name
                      / Path(declared_skill["fragment"]).parent)
        _assert_skill_surface_references(
            staging, skill_root, f"distribution module '{name}'")
        _assert_skill_surface_tables(
            staging, skill_root, f"distribution module '{name}'")
    return {
        "requires": {"rigorloom": spec.requires},
        "provides": _provides_summary(spec.provides),
        "install_md": _module_install_md(
            name, registry.version, spec.requires,
            has_skill=bool(spec.provides.get("skill"))),
    }


def _stage_core(staging: Path, repo_root: Path, version: str) -> dict:
    for component in _CORE_COMPONENTS:
        source = repo_root / component
        target = staging / component
        if source.is_dir():
            _copy_tree(source, target, _CORE_EXCLUDED_DIRS)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            raise PackageError(f"core component missing: {component}")
    # The verify tool itself ships with core so a target install can check
    # its own bundles.
    scripts_dir = staging / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).resolve(), scripts_dir / "package_module.py")
    _assert_core_skill_surface(staging)
    _assert_skill_surface_references(staging, Path("skill"), "core bundle")
    _assert_skill_surface_tables(staging, Path("skill"), "core bundle")
    return {
        "requires": None,
        "provides": {"core_components": list(_CORE_COMPONENTS),
                     "skill": True},
        "install_md": _core_install_md(version),
    }


def build_bundle(
    name: str,
    out_dir: Path | str = REPO_ROOT / "dist",
    *,
    modules_root: Path | str | None = None,
    repo_root: Path | str = REPO_ROOT,
    version: str | None = None,
) -> Path:
    """Build one bundle zip; returns its path. Raises PackageError loudly."""
    repo_root = Path(repo_root)
    registry = module_registry.ModuleRegistry(
        Path(modules_root) if modules_root is not None
        else repo_root / "modules",
        version=version,
        pyproject=repo_root / "pyproject.toml",
    )
    bundle_version = registry.version
    out_dir = Path(out_dir)

    with tempfile.TemporaryDirectory(prefix="rigorloom-bundle-") as tmp:
        staging = Path(tmp) / f"rigorloom-{name}"
        staging.mkdir(parents=True)
        if name == CORE_NAME:
            meta = _stage_core(staging, repo_root, bundle_version)
        else:
            meta = _stage_module(name, staging, registry)

        # Privacy gate BEFORE the manifest exists: nothing HARD ships.
        _run_privacy_gate(staging)

        (staging / INSTALL_NAME).write_text(
            meta["install_md"], encoding="utf-8", newline="\n")
        files = [
            {"path": path.relative_to(staging).as_posix(),
             "sha256": _sha256_file(path)}
            for path in _staged_files(staging)
        ]
        # Every value here is derived from tree CONTENT: no build time, no
        # absolute path, no host name, no set/dict iteration order. ``files``
        # is sorted by path (``_staged_members``); ``provides`` mirrors the
        # declaration order of the module's own ``module.yaml`` (or the fixed
        # ``_CORE_COMPONENTS`` tuple), which is content, not iteration order.
        # ``json.dumps`` below is given an explicit indent and newline so the
        # serialisation cannot drift either. A test asserts the absence of
        # timestamps and absolute paths so this stays true.
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "name": name,
            "version": bundle_version,
            "requires": meta["requires"],
            "provides": meta["provides"],
            "files": files,
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")

        out_dir.mkdir(parents=True, exist_ok=True)
        bundle = out_dir / f"rigorloom-{name}-{bundle_version}.zip"
        _write_bundle_zip(staging, bundle)
    return bundle


# ── verification (tamper detection) ─────────────────────────────────


def _bundle_contents(target: Path) -> tuple[dict, dict[str, bytes]]:
    """(manifest, {relative_path: bytes}) from a zip or extracted dir."""
    contents: dict[str, bytes] = {}
    if target.is_file() and target.suffix.lower() == ".zip":
        with zipfile.ZipFile(target) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                contents[info.filename.replace("\\", "/")] = (
                    archive.read(info))
    elif target.is_dir():
        for path in sorted(target.rglob("*")):
            if path.is_file() and not _is_junk(path.relative_to(target)):
                contents[path.relative_to(target).as_posix()] = (
                    path.read_bytes())
    else:
        raise PackageError(f"not a bundle zip or directory: {target}")
    raw = contents.pop(MANIFEST_NAME, None)
    if raw is None:
        raise PackageError(f"bundle has no {MANIFEST_NAME}: {target}")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"unreadable {MANIFEST_NAME}: {exc}")
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise PackageError(
            f"{MANIFEST_NAME} schema must be '{MANIFEST_SCHEMA}'")
    return manifest, contents


def verify_bundle(target: Path | str) -> tuple[dict, int]:
    """Re-hash a bundle against its manifest. Any drift is a hard failure."""
    manifest, contents = _bundle_contents(Path(target))
    listed = {entry["path"]: entry["sha256"]
              for entry in manifest.get("files", [])}
    problems = []
    for path, expected in sorted(listed.items()):
        data = contents.get(path)
        if data is None:
            problems.append({"path": path, "problem": "missing"})
        elif _sha256_bytes(data) != expected:
            problems.append({"path": path, "problem": "hash_mismatch"})
    for path in sorted(set(contents) - set(listed)):
        problems.append({"path": path, "problem": "not_in_manifest"})
    report = {
        "ok": not problems,
        "name": manifest.get("name"),
        "version": manifest.get("version"),
        "files": len(listed),
        "problems": problems,
    }
    return report, (0 if not problems else 3)


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify standalone rigorloom bundles "
                    "(per-distribution-module, or --module core).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--module", metavar="NAME",
                       help="distribution module name, or 'core'")
    group.add_argument("--verify", metavar="BUNDLE",
                       help="verify a built bundle (zip or extracted dir) "
                            "against its MANIFEST.json")
    parser.add_argument("--out", default=str(REPO_ROOT / "dist"),
                        help="output directory for bundle zips "
                             "(default: dist/)")
    parser.add_argument("--modules-root", default=None,
                        help="modules directory to package from "
                             "(default: <repo>/modules)")
    args = parser.parse_args(argv)

    try:
        if args.verify:
            report, code = verify_bundle(Path(args.verify))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return code
        bundle = build_bundle(
            args.module, Path(args.out),
            modules_root=args.modules_root)
    except (PackageError, module_registry.ModuleError) as exc:
        code = getattr(exc, "exit_code", 2)
        print(json.dumps({"ok": False, "error": str(exc)},
                         ensure_ascii=False))
        return code
    report, code = verify_bundle(bundle)
    print(json.dumps({"ok": code == 0, "bundle": str(bundle),
                      "files": report["files"]}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
