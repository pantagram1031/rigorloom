#!/usr/bin/env python3
"""Receipt-only dual-converter bounded content/object agreement oracle (T88).

The oracle compares one quarantined T86 ``rhwp`` candidate with one T87 Java
candidate.  It never promotes either candidate to ingress, Stage 0, rendering,
submission, or a canonical output.  The bounded content/object comparison is intentionally
implemented here rather than through ``content_extract.semantic_fingerprint``:
the paired result must bind section/spine order, text and whitespace, story and
table topology, equations, explicit controls, and referenced picture payloads
under one closed grammar.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import sys
import tempfile
import unicodedata
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

try:
    import diagnostic_candidate_core as _core
    import hwp_diagnostic_candidate as _rhwp
    import hwp_java_diagnostic_candidate as _java
    import hwp_ingress as _ingress
    import story_graph as _story_graph
except ImportError:  # pragma: no cover - package import fallback
    from pipeline.scripts import diagnostic_candidate_core as _core
    from pipeline.scripts import hwp_diagnostic_candidate as _rhwp
    from pipeline.scripts import hwp_java_diagnostic_candidate as _java
    from pipeline.scripts import hwp_ingress as _ingress
    from pipeline.scripts import story_graph as _story_graph


SCHEMA = "rigorloom/hwp-semantic-oracle/v1"
ADAPTER = "paired_converter"
ROOT_LEAF = "hwp-semantic-oracle"
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3
RUN_ID_RE = re.compile(r"(?:[0-9a-f]{16}|[0-9a-f]{32})\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
APPROVED_RHWP_SHA256 = (
    "e38215daddf63b284cbe05322541b44f65efd727ce7f50b9b4ffd94930e7ab72"
)
COMPARISON_METHOD = "paired_converter_bounded_content_object_v1"
COVERAGE = {
    "compared": [
        "text", "story_table_topology", "equations",
        "referenced_pictures", "explicit_controls",
    ],
    "not_compared": [
        "style_definitions", "paragraph_numbering",
        "layout_pagination", "metadata",
    ],
}
ALLOWLIST_PATH = Path(__file__).parents[1] / "references" / "hwp_semantic_oracle" / "rhwp-allowlist.json"
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_HWPX_BYTES = getattr(_ingress, "MAX_HWPX_ARCHIVE_BYTES", 64 * 1024 * 1024)
MAX_MEMBER_BYTES = getattr(_ingress, "MAX_HWPX_MEMBER_BYTES", 16 * 1024 * 1024)
MAX_TOTAL_BYTES = getattr(_ingress, "MAX_HWPX_TOTAL_UNCOMPRESSED", 64 * 1024 * 1024)
MAX_MEMBERS = getattr(_ingress, "MAX_HWPX_MEMBERS", 2048)
MAX_RATIO = getattr(_ingress, "MAX_HWPX_COMPRESSION_RATIO", 200)


class OracleError(Exception):
    """Expected refusal with a closed machine reason."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _empty_source() -> dict[str, Any]:
    return {
        "format": "hwp", "version": None, "bytes": None,
        "sha256": None, "compressed": None, "security_flags": [],
    }


def _base(*, status: str, reason: str,
          source: dict[str, Any] | None = None,
          execution: dict[str, str] | None = None,
          comparison: dict[str, Any] | None = None,
          inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": status,
        "reason": reason,
        "adapter": ADAPTER,
        "source": source or _empty_source(),
        "execution": execution or {"rhwp": "not_run", "java": "not_run"},
        "inputs": inputs or {"rhwp": None, "java": None, "pair": None},
        "comparison": comparison or {
            "state": "unknown", "method": "none",
            "reason": "independent_source_oracle_not_run",
        },
        "render": {"state": "not_run"},
        "proof_grade": "none",
        "submission_grade": False,
        "ceiling": "diagnostic_only",
        "output": {"state": "none"},
    }


def _duplicates_closed(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OracleError("receipt_duplicate_key")
        result[key] = value
    return result


def _read_receipt(path: Path, *, allow_hardlink: bool = False) -> tuple[dict[str, Any], bytes]:
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or (not allow_hardlink and getattr(info, "st_nlink", 1) != 1)):
            raise OracleError("receipt_invalid")
        raw = _core.read_regular_once(path, MAX_RECEIPT_BYTES, "receipt_invalid")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicates_closed)
    except OracleError:
        raise
    except _core.CoreError as exc:
        raise OracleError(exc.reason)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise OracleError("receipt_invalid")
    if not isinstance(payload, dict):
        raise OracleError("receipt_invalid")
    return payload, raw


def _validate_run_id(value: str) -> str:
    if not isinstance(value, str) or RUN_ID_RE.fullmatch(value) is None:
        raise OracleError("run_id_invalid")
    return value


def _closed_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _validate_source(source: Any) -> dict[str, Any]:
    if (not isinstance(source, dict) or set(source) != {
            "format", "version", "bytes", "sha256", "compressed", "security_flags"}
            or source.get("format") != "hwp"
            or not isinstance(source.get("version"), str)
            or re.fullmatch(r"5\.[01]\.\d+\.\d+", source["version"]) is None
            or isinstance(source.get("bytes"), bool)
            or not isinstance(source.get("bytes"), int) or source["bytes"] <= 0
            or not _closed_sha(source.get("sha256"))
            or not isinstance(source.get("compressed"), bool)
            or source.get("security_flags") != []):
        raise OracleError("source_descriptor_invalid")
    return source


def _receipt_run_id(path: Path, payload: dict[str, Any]) -> str:
    run_id = path.parent.name
    _validate_run_id(run_id)
    output = payload.get("output")
    if (not isinstance(output, dict) or set(output) != {
            "state", "path", "sha256", "bytes", "counts"}
            or output.get("state") != "quarantined"
            or output.get("path") != f"{run_id}/candidate.hwpx"
            or Path(output["path"]).is_absolute()
            or not _closed_sha(output.get("sha256"))
            or isinstance(output.get("bytes"), bool)
            or not isinstance(output.get("bytes"), int) or output["bytes"] <= 0):
        raise OracleError("receipt_output_invalid")
    counts = output.get("counts")
    if (not isinstance(counts, dict) or set(counts) != {"tables", "pictures", "equations"}
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 0
                   for v in counts.values())):
        raise OracleError("receipt_output_invalid")
    return run_id


def _validate_common_receipt(payload: dict[str, Any], *, schema: str,
                             adapter: str, path: Path) -> tuple[str, dict[str, Any]]:
    if set(payload) != {
            "schema", "status", "reason", "adapter", "source", "execution",
            "comparison", "render", "proof_grade", "submission_grade", "output"}:
        raise OracleError("receipt_schema_invalid")
    if (payload.get("schema") != schema or payload.get("status") != "candidate"
            or payload.get("reason") != "candidate_created"
            or payload.get("adapter") != adapter
            or payload.get("comparison") not in ({
                "state": "unknown", "method": "none",
                "reason": "independent_oracle_not_run",
            }, {
                "state": "unknown", "method": "none",
                "reason": "independent_source_oracle_not_run",
            })
            or payload.get("render") != {"state": "not_run"}
            or payload.get("proof_grade") != "none"
            or payload.get("submission_grade") is not False):
        raise OracleError("receipt_state_invalid")
    run_id = _receipt_run_id(path, payload)
    return run_id, _validate_source(payload.get("source"))


def _approved_rhwp_sha256() -> str:
    """Load the release-owned T86 executable allowlist, fail closed."""
    try:
        raw = _core.read_regular_once(ALLOWLIST_PATH, 16 * 1024,
                                      "rhwp_allowlist_unavailable")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicates_closed)
    except OracleError:
        raise
    except (_core.CoreError, OSError, UnicodeError, json.JSONDecodeError,
            TypeError, ValueError):
        raise OracleError("rhwp_allowlist_unavailable")
    if (not isinstance(payload, dict)
            or set(payload) != {"schema", "adapter", "version", "sha256"}
            or payload.get("schema") != "rigorloom/hwp-semantic-oracle-allowlist/v1"
            or payload.get("adapter") != "rhwp"
            or payload.get("version") != "0.8.2"
            or payload.get("sha256") != APPROVED_RHWP_SHA256):
        raise OracleError("rhwp_allowlist_invalid")
    return payload["sha256"]


def _validate_rhwp_receipt(path: Path, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    run_id, source = _validate_common_receipt(
        payload, schema="rigorloom/hwp-diagnostic-candidate/v1",
        adapter="rhwp", path=path)
    execution = payload.get("execution")
    if (not isinstance(execution, dict) or set(execution) != {
            "state", "binary_sha256", "exit_code"}
            or execution.get("state") != "succeeded"
            or execution.get("exit_code") != 0
            or execution.get("binary_sha256") != _approved_rhwp_sha256()):
        raise OracleError("rhwp_not_approved")
    return run_id, source


def _validate_java_receipt(path: Path, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    run_id, source = _validate_common_receipt(
        payload, schema="rigorloom/hwp-java-diagnostic-candidate/v1",
        adapter="hwp2hwpx_java", path=path)
    execution = payload.get("execution")
    required = {
        "state", "exit_code", "java_launcher_sha256", "runtime_binding",
        "toolchain_lock_sha256", "bridge_sha256", "main_class",
        "package_normalization", "missing_aux_rootfiles_pruned", "classpath",
    }
    if (not isinstance(execution, dict) or set(execution) != required
            or execution.get("state") != "succeeded"
            or execution.get("exit_code") != 0
            or execution.get("runtime_binding") != "launcher_rehashed_runtime_unbound"
            or execution.get("main_class") != "Hwp2HwpxBridge"
            or execution.get("package_normalization") != "zip_envelope_canonicalized"
            or not _closed_sha(execution.get("java_launcher_sha256"))
            or not _closed_sha(execution.get("toolchain_lock_sha256"))
            or not _closed_sha(execution.get("bridge_sha256"))
            or isinstance(execution.get("missing_aux_rootfiles_pruned"), bool)
            or not isinstance(execution.get("missing_aux_rootfiles_pruned"), int)
            or execution["missing_aux_rootfiles_pruned"] < 0):
        raise OracleError("java_not_bound")
    classpath = execution.get("classpath")
    if (not isinstance(classpath, list) or len(classpath) != 1
            or not isinstance(classpath[0], dict)
            or set(classpath[0]) != {"role", "sha256"}
            or classpath[0].get("role") != "hwp2hwpx_fat_jar"
            or not _closed_sha(classpath[0].get("sha256"))):
        raise OracleError("java_not_bound")
    # Bind the receipt to the release-owned T87 lock without importing its
    # semantic extractor or trusting arbitrary runtime paths.
    try:
        lock, lock_sha, bridge = _java._load_toolchain()
    except Exception:
        raise OracleError("java_toolchain_unavailable")
    if (execution["toolchain_lock_sha256"] != lock_sha
            or execution["bridge_sha256"] != lock["bridge"]["sha256"]
            or execution["classpath"][0]["sha256"] != lock["tool"]["sha256"]):
        raise OracleError("java_toolchain_mismatch")
    return run_id, source


def _safe_member(name: str) -> str:
    if (not isinstance(name, str) or not name or "\\" in name
            or name.startswith("/") or name.startswith("./")
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise OracleError("hwpx_member_invalid")
    return name


def _norm_text(value: str) -> str:
    # Preserve ordinary spaces/tabs and only canonicalize Unicode plus line
    # endings.  Collapsing all whitespace would erase meaningful text runs.
    return unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


_KNOWN = {
    "sec", "p", "run", "t", "tbl", "tr", "tc", "span", "ctrl", "pic",
    "img", "equation", "script", "header", "footer", "footNote", "endNote",
    "subList", "lineBreak", "colPr", "cellSpan", "rowSpan", "cellAddr",
    "para", "runPr", "charPr", "secPr", "beginNum", "pagePr", "textWrap",
    "drawText", "shape", "caption", "fieldBegin", "fieldEnd", "bookmark",
    "switch", "insert", "delete", "trackChange", "docPr", "offset", "pos",
    "sz", "href", "binData", "container", "rootfiles", "rootfile", "package",
    "metadata", "manifest", "spine", "item", "itemref", "opf", "default",
}
# T79 is the authoritative closed OWPML grammar.  Reuse its declared local
# vocabulary for the internal fingerprint walk rather than maintaining a
# second speculative list; expanded-QName/parent validation still occurs in
# the captured-snapshot story-graph gate below.
_KNOWN.update(
    getattr(_story_graph, "_KNOWN_PARAGRAPH", set())
    | getattr(_story_graph, "_KNOWN_CORE", set())
    | getattr(_story_graph, "_HEADER_LOCALS", set())
    | getattr(_story_graph, "_HEADER_CORE", set())
    | getattr(_story_graph, "_HEADER_PARAGRAPH", set())
)
_STORY = {"header", "footer", "footNote", "endNote"}
_BOUNDARY = {"p", "tbl", "tr", "tc", "span", "ctrl", "lineBreak", *_STORY}
_CONTROL = {"ctrl", "pic", "equation", "drawText", "shape", "caption",
            "fieldBegin", "fieldEnd", "bookmark", "switch", "insert", "delete"}
_STRUCTURAL = {
    "sec", "p", "tbl", "tr", "tc", "span", "ctrl", "pic", "img",
    "equation", "script", "lineBreak", "shape", "rect", "cellSpan", "rowSpan",
    "cellAddr",
    *_STORY,
}
_UNSUPPORTED = {"fieldBegin": "unsupported_field", "fieldEnd": "unsupported_field",
                "hiddenComment": "unsupported_hidden_comment",
                "masterPage": "unsupported_master_page",
                "drawText": "unsupported_draw_text", "caption": "unsupported_caption"}


def _attrs(elem: ET.Element) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for key, value in elem.attrib.items():
        name = _local(key)
        lower = name.casefold()
        # Volatile IDs are not bounded content/object agreement evidence.  Topology and
        # spans remain bound because their attributes do not match this rule.
        if lower == "id" or lower.endswith("idref") or lower.endswith("id"):
            continue
        result.append((name, _norm_text(str(value))))
    return tuple(sorted(result))


def _bin_map(members: dict[str, bytes]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for name, value in members.items():
        if name.casefold().startswith("bindata/"):
            result[Path(name).stem.casefold()] = value
            result[name.casefold()] = value
    return result


def _picture_refs(elem: ET.Element, bins: dict[str, bytes],
                  manifest_bins: dict[str, bytes | None] | None = None
                  ) -> tuple[str, ...]:
    refs: list[str] = []
    for key, raw in elem.attrib.items():
        value = str(raw).replace("\\", "/")
        folded = value.casefold()
        key_local = _local(key).casefold()
        if (folded.startswith("bindata/") or folded.startswith("bin")
                or "binaryitem" in key_local):
            # A binaryItemIDRef is an OPF manifest id, not a filename.  When
            # the validated manifest declares that id, use only its target;
            # do not fall back to a same-stem BinData decoy.  A direct
            # BinData path remains supported for older packages.
            if "binaryitemidref" in key_local:
                # This attribute is an OPF manifest identity by contract;
                # absence (or a non-BinData manifest target) is refusal, never
                # a same-stem filename guess.
                if manifest_bins is None or folded not in manifest_bins:
                    raise OracleError("picture_reference_unavailable")
                data = manifest_bins[folded]
            else:
                data = bins.get(folded)
                if data is None:
                    data = bins.get(Path(folded).stem)
            if data is None:
                raise OracleError("picture_reference_unavailable")
            refs.append(hashlib.sha256(data).hexdigest())
    return tuple(sorted(refs))


def _walk(elem: ET.Element, bins: dict[str, bytes], *, text: list[Any],
          structure: list[Any], equations: list[str], pictures: list[tuple[str, ...]],
          stories: list[str], controls: list[str],
          manifest_bins: dict[str, bytes | None] | None = None) -> None:
    local = _local(elem.tag)
    if local in _UNSUPPORTED:
        raise OracleError(_UNSUPPORTED[local])
    if local not in _KNOWN:
        folded = local.casefold()
        if (folded.endswith("ctrl") or folded.startswith("future")
                or folded.startswith("unknown")):
            raise OracleError("unknown_control")
        raise OracleError("hwpx_grammar_unknown")
    attrs = _attrs(elem)
    if local in _STRUCTURAL:
        structure.append(("start", local, attrs))
    if local in _BOUNDARY:
        text.append(("boundary", local))
    if local in _STORY:
        stories.append(local)
    if local in _CONTROL:
        controls.append(local)
    if local in {"tab", "fwSpace", "lineBreak"}:
        # These are logical text seats/control boundaries, not XML formatting.
        # Keep them distinct from ordinary text so A <tab/> B cannot collapse
        # to the same fingerprint as AB.
        text.append(("text_control", local))
    if local in {"pic", "img"}:
        pictures.append(_picture_refs(elem, bins, manifest_bins))
    if local == "script":
        script = _norm_text(elem.text or "")
        if script:
            equations.append(script)
    # Only text-bearing OWPML seats are logical text.  XML indentation around
    # paragraphs/runs is formatting and must not alter agreement; a `t` seat,
    # in contrast, preserves even an ordinary single space exactly.
    if local == "t" and elem.text is not None:
        text.append(_norm_text(elem.text))
    for child in elem:
        _walk(child, bins, text=text, structure=structure,
               equations=equations, pictures=pictures,
               stories=stories, controls=controls,
               manifest_bins=manifest_bins)
        if child.tail:
            tail = child.tail
            # OWPML text belongs to a `t` seat; tails are XML formatting and
            # never carry logical spaces between text seats.
            if tail.strip():
                text.append(_norm_text(tail))
    if local in _STRUCTURAL:
        structure.append(("end", local))


def _coalesce_text_runs(tokens: list[Any]) -> tuple[Any, ...]:
    """Coalesce adjacent `t` seats while retaining explicit boundaries."""
    result: list[Any] = []
    for token in tokens:
        if (isinstance(token, str) and result
                and isinstance(result[-1], str)):
            result[-1] += token
        else:
            result.append(token)
    return tuple(result)


def _opf_layout(members: dict[str, bytes]) -> tuple[list[str], dict[str, bytes | None]]:
    """Return OPF spine section members and validated BinData id bindings."""
    container = members.get("META-INF/container.xml")
    if container is None:
        raise OracleError("hwpx_container_missing")
    try:
        root = ET.fromstring(container)
    except ET.ParseError:
        raise OracleError("hwpx_container_invalid")
    paths = [node.attrib.get("full-path", "") for node in root.iter()
             if _local(node.tag) == "rootfile"]
    if paths.count("Contents/content.hpf") != 1:
        raise OracleError("hwpx_opf_missing")
    try:
        opf = ET.fromstring(members["Contents/content.hpf"])
    except (KeyError, ET.ParseError):
        raise OracleError("hwpx_opf_invalid")
    manifests = [node for node in opf if _local(node.tag) == "manifest"]
    spines = [node for node in opf if _local(node.tag) == "spine"]
    if len(manifests) != 1 or len(spines) != 1:
        raise OracleError("hwpx_opf_invalid")
    manifest: dict[str, str] = {}
    for item in manifests[0]:
        if _local(item.tag) != "item" or not item.attrib.get("id"):
            raise OracleError("hwpx_manifest_invalid")
        item_id = item.attrib["id"]
        href = item.attrib.get("href", "").replace("\\", "/")
        # Hancom packages use both package-root resources (`settings.xml`)
        # and explicit `Contents/...` hrefs.  Resolve an exact present member
        # first, then the OPF Contents base for the legacy short spelling.
        direct = posixpath.normpath(href)
        if direct in members:
            target = direct
        else:
            target = posixpath.normpath(posixpath.join("Contents", href))
        if target.startswith("../") or target not in members or item_id in manifest:
            raise OracleError("hwpx_manifest_invalid")
        manifest[item_id] = target
    manifest_sections: dict[str, str] = {}
    for item_id, target in manifest.items():
        if not target.lower().endswith(".xml"):
            continue
        try:
            item_root = ET.fromstring(members[target])
        except (KeyError, ET.ParseError):
            continue
        if _local(item_root.tag) == "sec":
            manifest_sections[item_id] = target
    result: list[str] = []
    for ref in spines[0]:
        if _local(ref.tag) != "itemref" or ref.attrib.get("idref") not in manifest:
            raise OracleError("hwpx_spine_invalid")
        item_id = ref.attrib["idref"]
        target = manifest_sections.get(item_id)
        if target is None:
            continue
        if target in result:
            raise OracleError("hwpx_spine_invalid")
        result.append(target)
    physical: list[str] = []
    for name, data in members.items():
        if not name.lower().endswith(".xml"):
            continue
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            continue
        if _local(root.tag) == "sec":
            physical.append(name)
    if not result or sorted(result) != sorted(physical):
        raise OracleError("hwpx_sections_coverage")
    # Bind every manifest id to a payload only when it names BinData.  Keep a
    # None marker for non-BinData ids so an item-ref cannot silently fall back
    # to a guessed stem/path when the manifest owns that identifier.
    manifest_bins: dict[str, bytes | None] = {}
    for item_id, target in manifest.items():
        manifest_bins[item_id.casefold()] = (
            members[target] if target.casefold().startswith("bindata/") else None)
    return result, manifest_bins


def _opf_sections(members: dict[str, bytes]) -> list[str]:
    return _opf_layout(members)[0]


def _fingerprint_bytes(raw: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not 0 < len(infos) <= MAX_MEMBERS:
                raise OracleError("hwpx_invalid")
            if infos[0].filename != "mimetype" or infos[0].header_offset != 0:
                raise OracleError("hwpx_mimetype_invalid")
            members: dict[str, bytes] = {}
            folded: set[str] = set()
            total = 0
            for info in infos:
                name = _safe_member(info.filename)
                if info.is_dir() or name.casefold() in folded:
                    raise OracleError("hwpx_member_invalid")
                folded.add(name.casefold())
                if (info.flag_bits & (0x1 | 0x8 | 0x20)
                        or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                        or info.file_size > MAX_MEMBER_BYTES):
                    raise OracleError("hwpx_member_invalid")
                if info.file_size and (info.compress_size == 0
                                       or info.file_size > info.compress_size * MAX_RATIO):
                    raise OracleError("hwpx_ratio_invalid")
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise OracleError("hwpx_size_invalid")
                members[name] = archive.read(info)
            if archive.testzip() is not None:
                raise OracleError("hwpx_crc_invalid")
            if (infos[0].extra or infos[0].flag_bits
                    or infos[0].compress_type != zipfile.ZIP_STORED
                    or members.get("mimetype") != b"application/hwp+zip"):
                raise OracleError("hwpx_mimetype_invalid")
        sections, manifest_bins = _opf_layout(members)
        bins = _bin_map(members)
        text: list[Any] = []
        structure: list[Any] = []
        equations: list[str] = []
        pictures: list[tuple[str, ...]] = []
        stories: list[str] = []
        controls: list[str] = []
        for ordinal, section in enumerate(sections):  # spine order is authoritative
            try:
                root = ET.fromstring(members[section])
            except (KeyError, ET.ParseError):
                raise OracleError("hwpx_section_invalid")
            # Preserve only the section's OPF spine ordinal.  Package member
            # names are transport details and must not make equal bounded
            # content/object values
            # disagree (e.g. section0.xml versus bodyA.xml).
            structure.append(("section", ordinal))
            _walk(root, bins, text=text, structure=structure,
                  equations=equations, pictures=pictures,
                  stories=stories, controls=controls,
                  manifest_bins=manifest_bins)
        return {
            "text": _coalesce_text_runs(text), "structure": tuple(structure),
            "equations": tuple(equations), "pictures": tuple(pictures),
            "stories": tuple(stories), "controls": tuple(controls),
        }
    except OracleError:
        raise
    except (_core.CoreError, OSError, ValueError, zipfile.BadZipFile,
            zipfile.LargeZipFile, KeyError):
        raise OracleError("hwpx_invalid")


def _fingerprint(path: Path) -> dict[str, Any]:
    try:
        raw = _core.read_regular_once(path, MAX_HWPX_BYTES, "candidate_unavailable")
    except _core.CoreError as exc:
        raise OracleError(exc.reason)
    return _fingerprint_bytes(raw)


def _compare_fingerprints(left: dict[str, Any], right: dict[str, Any]) -> dict[str, bool]:
    return {
        "text": left["text"] == right["text"],
        "story_table_topology": (
            left["structure"] == right["structure"]
            and left["stories"] == right["stories"]),
        "equations": left["equations"] == right["equations"],
        "referenced_pictures": left["pictures"] == right["pictures"],
        "explicit_controls": left["controls"] == right["controls"],
    }


def _binding_digest(role: str, *parts: bytes) -> str:
    digest = hashlib.sha256()
    for value in (SCHEMA.encode("ascii"), role.encode("ascii"), *parts):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def _input_bindings(*, left_raw: bytes, left_candidate_raw: bytes,
                    right_raw: bytes, right_candidate_raw: bytes) -> dict[str, Any]:
    left = _binding_digest("rhwp", left_raw, left_candidate_raw)
    right = _binding_digest("java", right_raw, right_candidate_raw)
    pair = _binding_digest(
        "pair", left_raw, left_candidate_raw, right_raw, right_candidate_raw)
    return {
        "rhwp": {"binding_sha256": left},
        "java": {"binding_sha256": right},
        "pair": {"binding_sha256": pair},
    }


def _candidate_snapshot(path: Path, output: dict[str, Any]) -> tuple[dict[str, Any], tuple[Any, ...]]:
    fingerprint, identity, _raw = _candidate_capture(path, output)
    return fingerprint, identity


def _candidate_capture(path: Path, output: dict[str, Any]) -> tuple[
        dict[str, Any], tuple[Any, ...], bytes]:
    """Read and fingerprint one candidate from one bounded byte snapshot."""
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_nlink", 1) != 1):
            raise OracleError("candidate_invalid")
        raw = _core.read_regular_once(path, MAX_HWPX_BYTES, "candidate_unavailable")
    except OracleError:
        raise
    except _core.CoreError as exc:
        raise OracleError(exc.reason)
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != output["bytes"] or digest != output["sha256"]:
        raise OracleError("candidate_drift")
    return (_fingerprint_bytes(raw),
            (getattr(info, "st_dev", 0), getattr(info, "st_ino", 0),
             len(raw), digest), raw)


def _verify_captured_candidate(*, root_leaf: str, receipt_raw: bytes,
                               candidate_raw: bytes, run_id: str,
                               verifier: Any) -> None:
    """Exercise an existing public candidate verifier over immutable bytes.

    The verifier is deliberately pointed at a private temporary tree containing
    the exact receipt and candidate snapshots already captured by the oracle;
    it cannot reopen a caller-controlled path during this check.
    """
    try:
        with tempfile.TemporaryDirectory(prefix=".oracle-verify-") as temp:
            root = Path(temp) / root_leaf
            run = root / run_id
            run.mkdir(parents=True, exist_ok=False)
            _core.write_bytes(run / "receipt.json", receipt_raw)
            candidate_path = run / "candidate.hwpx"
            _core.write_bytes(candidate_path, candidate_raw)
            story = _story_graph.inspect_story_graph(candidate_path)
            if not isinstance(story, dict) or story.get("status") != "passed":
                raise OracleError("story_graph_refused")
            result = verifier(root, run_id)
    except _core.CoreError as exc:
        raise OracleError(exc.reason)
    except (OSError, TypeError, ValueError, RuntimeError):
        raise OracleError("candidate_verifier_failed")
    if not isinstance(result, dict) or result.get("status") != "candidate":
        raise OracleError("candidate_verifier_refused")


def _load_current_inputs(left_path: Path, right_path: Path) -> dict[str, Any]:
    """Validate and snapshot both converter lanes for compare/verify."""
    if left_path.expanduser().resolve() == right_path.expanduser().resolve():
        raise OracleError("roles_not_distinct")
    left, left_raw = _read_receipt(left_path)
    right, right_raw = _read_receipt(right_path)
    left_id, left_source = _validate_rhwp_receipt(left_path, left)
    right_id, right_source = _validate_java_receipt(right_path, right)
    # Lane run IDs are opaque producer-local labels; the oracle binds the
    # candidate bytes and source descriptor, not an accidental equality (or
    # inequality) between those labels.
    if left_source != right_source:
        raise OracleError("source_descriptor_mismatch")
    left_candidate = left_path.parent / "candidate.hwpx"
    right_candidate = right_path.parent / "candidate.hwpx"
    if left_candidate.resolve() == right_candidate.resolve():
        raise OracleError("roles_not_distinct")
    left_fp, left_identity, left_candidate_raw = _candidate_capture(
        left_candidate, left["output"])
    right_fp, right_identity, right_candidate_raw = _candidate_capture(
        right_candidate, right["output"])
    # Re-run the lane-owned public verifiers against the exact bytes captured
    # above.  This retains T85/story/package checks from each producer without
    # allowing a mutable live path to become agreement evidence.
    _verify_captured_candidate(
        root_leaf="hwp-diagnostic", receipt_raw=left_raw,
        candidate_raw=left_candidate_raw, run_id=left_id,
        verifier=_rhwp.verify_diagnostic)
    _verify_captured_candidate(
        root_leaf="hwp-java-diagnostic", receipt_raw=right_raw,
        candidate_raw=right_candidate_raw, run_id=right_id,
        verifier=_java.verify_diagnostic)
    return {
        "source": left_source,
        "left": left,
        "right": right,
        "left_raw": left_raw,
        "right_raw": right_raw,
        "left_candidate": left_candidate,
        "right_candidate": right_candidate,
        "left_candidate_raw": left_candidate_raw,
        "right_candidate_raw": right_candidate_raw,
        "left_fp": left_fp,
        "right_fp": right_fp,
        "left_identity": left_identity,
        "right_identity": right_identity,
        "inputs": _input_bindings(
            left_raw=left_raw, left_candidate_raw=left_candidate_raw,
            right_raw=right_raw, right_candidate_raw=right_candidate_raw),
        "execution": {"rhwp": "succeeded", "java": "succeeded"},
        "matches": _compare_fingerprints(left_fp, right_fp),
    }


def _same_input_snapshot(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare the opaque role bytes/bindings captured at two instants."""
    return all(left.get(key) == right.get(key) for key in (
        "source", "left_raw", "right_raw", "left_candidate_raw",
        "right_candidate_raw", "inputs", "matches"))


def _paths_overlap(left: Path, right: Path) -> bool:
    try:
        a, b = left.expanduser().resolve(), right.expanduser().resolve()
        return a == b or a in b.parents or b in a.parents
    except (OSError, RuntimeError, TypeError, ValueError):
        return True


def _oracle_run_layout(root: Path, run_id: str) -> tuple[Path, Path, Any]:
    """Validate and snapshot an oracle receipt-only run directory."""
    run_path = root / run_id
    receipt_path = run_path / "receipt.json"
    try:
        run_info = run_path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (not stat.S_ISDIR(run_info.st_mode)
                or stat.S_ISLNK(run_info.st_mode)
                or getattr(run_info, "st_file_attributes", 0) & reparse):
            raise OracleError("receipt_layout_invalid")
        entries = list(run_path.iterdir())
        if len(entries) != 1 or entries[0].name != "receipt.json":
            raise OracleError("receipt_layout_invalid")
        receipt_info = receipt_path.lstat()
        if (not stat.S_ISREG(receipt_info.st_mode)
                or stat.S_ISLNK(receipt_info.st_mode)
                or getattr(receipt_info, "st_file_attributes", 0) & reparse
                or getattr(receipt_info, "st_nlink", 1) != 1):
            raise OracleError("receipt_layout_invalid")
        identity = _core.node_identity(run_path)
    except OracleError:
        raise
    except (_core.CoreError, OSError, TypeError, ValueError):
        raise OracleError("receipt_layout_invalid")
    return run_path, receipt_path, identity


def _recheck_oracle_run_layout(run_path: Path, expected_identity: Any) -> None:
    current_path, _receipt_path, current_identity = _oracle_run_layout(
        run_path.parent, run_path.name)
    if (current_path != run_path
            or not _core.same_file_identity(current_identity, expected_identity)):
        raise OracleError("receipt_layout_invalid")


def _publish_receipt(root: Path, guard: dict[str, Any], run_id: str,
                     payload: dict[str, Any]) -> dict[str, Any]:
    # Keep staging outside the guarded publication root.  Creating a temp
    # directory under the root would legitimately change its mtime before the
    # owner-token publisher's first guard check and look like a root swap.
    # Hard-link publication requires staging on the same filesystem as the
    # guarded root.  A sibling temp dir stays outside the receipt root while
    # avoiding cross-volume EXDEV failures from the process temp volume.
    def publish_from_stage(temp: str) -> dict[str, Any]:
        stage = Path(temp) / "publish" / run_id
        stage.mkdir(parents=True, exist_ok=False)
        staged_receipt = stage / "receipt.json"
        raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
        try:
            _core.write_bytes(staged_receipt, raw)
        except _core.CoreError as exc:
            raise OracleError(exc.reason)
        def check(g, *, refresh=False):
            try:
                _core.check_root_guard(g, refresh=refresh,
                                       node_identity_fn=_core.node_identity)
            except _core.CoreError as exc:
                raise _core.CoreError(exc.reason)
        def write(path: Path, data: bytes):
            _core.write_bytes(path, data)
        def validate(path: Path):
            # The staged receipt remains linked while ownership validation
            # runs; permit that known two-link publication state only here.
            loaded, loaded_raw = _read_receipt(path, allow_hardlink=True)
            if loaded != payload or loaded_raw != raw:
                raise _core.CoreError("receipt_output_mismatch")
        try:
            return _core.publish_owner_token_receipt(
                root / run_id, stage, payload, root_guard=guard,
                check_root_guard_fn=check, write_bytes_fn=write,
                node_identity_fn=_core.node_identity,
                same_identity_fn=_core.same_file_identity,
                remove_owned_fn=_core.remove_owned,
                rollback_fn=_core.rollback_publication,
                validate_receipt_fn=validate,
                token_prefix=".t88-owner-",
            )
        except _core.CoreError as exc:
            raise OracleError(exc.reason)

    # TemporaryDirectory cleanup is outside the receipt commit.  If cleanup
    # itself fails after the owner-token publisher has returned, preserve the
    # committed receipt rather than converting success into a false refusal.
    committed = False
    result: dict[str, Any] | None = None
    try:
        with tempfile.TemporaryDirectory(
                prefix=f".{ROOT_LEAF}-", dir=str(root.parent)) as temp:
            result = publish_from_stage(temp)
            committed = True
    except Exception:
        if not committed:
            raise
    if result is None:  # defensive closed failure for malformed seams
        raise OracleError("diagnostic_publish_failed")
    return result


def compare_diagnostic(*, rhwp_receipt: str | Path,
                       java_receipt: str | Path,
                       diagnostic_root: str | Path,
                       run_id: str) -> dict[str, Any]:
    source: dict[str, Any] | None = None
    execution = {"rhwp": "not_run", "java": "not_run"}
    inputs: dict[str, Any] | None = None
    try:
        run_id = _validate_run_id(run_id)
        root_input = Path(diagnostic_root)
        root = _core.prepare_root(root_input, expected_leaf=ROOT_LEAF)
        guard = _core.capture_root_guard(root_input, root)
        _core.check_root_guard(guard, node_identity_fn=_core.node_identity)
        left_path, right_path = Path(rhwp_receipt), Path(java_receipt)
        if (_paths_overlap(root, left_path.parent)
                or _paths_overlap(root, right_path.parent)):
            raise OracleError("roles_not_distinct")
        current = _load_current_inputs(left_path, right_path)
        source = current["source"]
        execution = current["execution"]
        inputs = current["inputs"]
        left_raw = current["left_raw"]
        right_raw = current["right_raw"]
        left = current["left"]
        right = current["right"]
        left_candidate = current["left_candidate"]
        right_candidate = current["right_candidate"]
        if (_paths_overlap(root, left_candidate)
                or _paths_overlap(root, right_candidate)):
            raise OracleError("roles_not_distinct")
        matches = current["matches"]
        if not all(matches.values()):
            raise OracleError("bounded_content_object_mismatch")
        payload = _base(
            status="diagnostic_agreement", reason="agreement_created",
            source=source, execution=execution,
            inputs=inputs,
            comparison={
                "state": "agreement",
                "method": COMPARISON_METHOD,
                "source_fidelity": "not_established",
                "independence": "converter_code_distinct_java_runtime_unbound",
                "coverage": COVERAGE,
                "matches": matches,
            })
        # Re-capture every role before commit.  This closes a path replacement
        # or same-inode overwrite after the first comparison, including
        # candidate bytes and the opaque pair binding.
        current_again = _load_current_inputs(left_path, right_path)
        if not _same_input_snapshot(current, current_again):
            raise OracleError("input_drift")
        _core.check_root_guard(guard, node_identity_fn=_core.node_identity)
        return _publish_receipt(root, guard, run_id, payload)
    except OracleError as exc:
        return _base(status="refused", reason=exc.reason,
                     source=source, execution=execution, inputs=inputs)
    except (_core.CoreError, OSError, TypeError, ValueError, RuntimeError):
        return _base(status="refused", reason="diagnostic_io_failed",
                     source=source, execution=execution, inputs=inputs)


def _validate_oracle_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != {
            "schema", "status", "reason", "adapter", "source", "execution",
            "inputs", "comparison", "render", "proof_grade", "submission_grade",
            "ceiling", "output"}:
        raise OracleError("receipt_schema_invalid")
    if (payload.get("schema") != SCHEMA
            or payload.get("status") != "diagnostic_agreement"
            or payload.get("reason") != "agreement_created"
            or payload.get("adapter") != ADAPTER
            or payload.get("render") != {"state": "not_run"}
            or payload.get("proof_grade") != "none"
            or payload.get("submission_grade") is not False
            or payload.get("ceiling") != "diagnostic_only"
            or payload.get("output") != {"state": "none"}):
        raise OracleError("receipt_schema_invalid")
    execution = payload.get("execution")
    if execution != {"rhwp": "succeeded", "java": "succeeded"}:
        raise OracleError("receipt_execution_invalid")
    inputs = payload.get("inputs")
    if (not isinstance(inputs, dict) or set(inputs) != {"rhwp", "java", "pair"}
            or any(not isinstance(inputs.get(role), dict)
                   or set(inputs[role]) != {"binding_sha256"}
                   or not _closed_sha(inputs[role].get("binding_sha256"))
                   for role in ("rhwp", "java", "pair"))):
        raise OracleError("receipt_inputs_invalid")
    comparison = payload.get("comparison")
    if (not isinstance(comparison, dict)
            or set(comparison) != {
                "state", "method", "source_fidelity", "independence",
                "coverage", "matches"}
            or comparison.get("state") != "agreement"
            or comparison.get("method") != COMPARISON_METHOD
            or comparison.get("source_fidelity") != "not_established"
            or comparison.get("independence") != "converter_code_distinct_java_runtime_unbound"
            or comparison.get("coverage") != COVERAGE):
        raise OracleError("receipt_comparison_invalid")
    matches = comparison.get("matches")
    if (not isinstance(matches, dict)
            or set(matches) != {
                "text", "story_table_topology", "equations",
                "referenced_pictures", "explicit_controls"}
            or any(type(value) is not bool for value in matches.values())
            or not all(matches.values())):
        raise OracleError("receipt_comparison_invalid")
    return _validate_source(payload.get("source"))


def verify_diagnostic(diagnostic_root: str | Path, run_id: str, *,
                     rhwp_receipt: str | Path | None = None,
                     java_receipt: str | Path | None = None) -> dict[str, Any]:
    """Verify an oracle receipt against both current converter inputs.

    The oracle receipt intentionally contains no converter paths or run IDs.
    Callers therefore have to supply both current lane receipts at verify time;
    their candidate paths, source descriptors, lock bindings, and bytes are
    revalidated before the prior agreement is accepted.
    """
    source: dict[str, Any] | None = None
    execution = {"rhwp": "not_run", "java": "not_run"}
    inputs: dict[str, Any] | None = None
    try:
        run_id = _validate_run_id(run_id)
        if rhwp_receipt is None or java_receipt is None:
            raise OracleError("verification_inputs_required")
        root_input = Path(diagnostic_root)
        root = _core.prepare_root(root_input, expected_leaf=ROOT_LEAF)
        guard = _core.capture_root_guard(root_input, root)
        _core.check_root_guard(guard, node_identity_fn=_core.node_identity)
        left_path, right_path = Path(rhwp_receipt), Path(java_receipt)
        if (_paths_overlap(root, left_path.parent)
                or _paths_overlap(root, right_path.parent)):
            raise OracleError("roles_not_distinct")
        run_path, receipt_path, run_identity = _oracle_run_layout(root, run_id)
        payload, raw = _read_receipt(receipt_path)
        source = _validate_oracle_payload(payload)
        current = _load_current_inputs(left_path, right_path)
        execution = current["execution"]
        inputs = current["inputs"]
        if (current["source"] != source
                or current["matches"] != payload["comparison"]["matches"]
                or current["inputs"] != payload["inputs"]):
            raise OracleError("input_drift")
        # A verify call must bind the receipt and all four converter role
        # snapshots at the final boundary.  Re-capture after the initial load
        # so a same-inode overwrite of the oracle receipt, producer receipt,
        # or candidate cannot return the prior agreement.
        current_again = _load_current_inputs(left_path, right_path)
        oracle_again, oracle_raw_again = _read_receipt(receipt_path)
        if (oracle_again != payload or oracle_raw_again != raw
                or not _same_input_snapshot(current, current_again)):
            raise OracleError("input_drift")
        _recheck_oracle_run_layout(run_path, run_identity)
        _core.check_root_guard(guard, node_identity_fn=_core.node_identity)
        return payload
    except OracleError as exc:
        return _base(status="refused", reason=exc.reason,
                     source=source, execution=execution, inputs=inputs)
    except (OSError, TypeError, ValueError, RuntimeError, _core.CoreError):
        return _base(status="refused", reason="diagnostic_io_failed",
                     source=source, execution=execution, inputs=inputs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="receipt-only paired HWP bounded content/object oracle")
    sub = parser.add_subparsers(dest="command", required=True)
    compare = sub.add_parser("compare", help="compare one T86 and one T87 candidate")
    compare.add_argument("rhwp_receipt")
    compare.add_argument("java_receipt")
    compare.add_argument("--diagnostic-root", required=True)
    compare.add_argument("--run-id", required=True)
    verify = sub.add_parser("verify", help="verify one oracle receipt")
    verify.add_argument("--diagnostic-root", required=True)
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--rhwp-receipt", required=True)
    verify.add_argument("--java-receipt", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "compare":
        result = compare_diagnostic(
            rhwp_receipt=args.rhwp_receipt, java_receipt=args.java_receipt,
            diagnostic_root=args.diagnostic_root, run_id=args.run_id)
    else:
        result = verify_diagnostic(
            args.diagnostic_root, args.run_id,
            rhwp_receipt=args.rhwp_receipt, java_receipt=args.java_receipt)
    try:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    except (BrokenPipeError, OSError, UnicodeError):
        return EXIT_REFUSED
    return EXIT_OK if result.get("status") == "diagnostic_agreement" else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
