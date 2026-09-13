"""Build and query a disposable SQLite view of a coordination snapshot.

The JSON coordination state remains authoritative.  This module accepts one
immutable snapshot and never opens, repairs, leases, routes, or writes the live
state root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote


LEDGER_SCHEMA = "rigorloom/coordination-state-v1"
INDEX_SCHEMA = "rigorloom/coordination-index-v1"
EXTRACTOR_VERSION = "1"
POLICY_VERSION = "1"
TERMINAL_OPERATION_STATUSES = {"committed", "completed", "failed", "cancelled", "canceled"}
PATH_KEYS = ("path", "receipt_path", "artifact_path", "output_path")
HASH_KEYS = ("sha256", "receipt_sha256", "artifact_sha256")
HEX_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
SENSITIVE_KEYS = {
    "fencing_token",
    "accepted_token",
    "credential",
    "credentials",
    "password",
    "secret",
    "api_key",
    "access_token",
    "refresh_token",
    "authorization",
    "private_key",
    "secret_key",
    "signing_key",
}


class IndexErrorBase(RuntimeError):
    """Base class for bounded, user-facing index failures."""


class InvalidSnapshot(IndexErrorBase):
    pass


class UnsafePath(IndexErrorBase):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_json(value).encode("utf-8"))


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in SENSITIVE_KEYS or lowered.endswith(
                ("_password", "_secret", "_api_key", "_token", "_private_key", "_signing_key")
            ):
                cleaned[str(key)] = "[redacted]"
            else:
                cleaned[str(key)] = _redact(item)
        return cleaned
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _id_part(value: Any) -> str:
    return quote(str(value), safe="")


def _edge_id(edge_type: str, source: str, target: str, provenance: Mapping[str, Any]) -> str:
    return "edge:sha256:" + _sha_json(
        {"edge_type": edge_type, "source": source, "target": target, "provenance": provenance}
    )


def _within(path: Path, roots: Sequence[Path]) -> bool:
    for root in roots:
        try:
            common = os.path.commonpath((str(path), str(root)))
            if os.path.normcase(common) == os.path.normcase(str(root)):
                return True
        except ValueError:
            continue
    return False


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            length += len(chunk)
    return digest.hexdigest(), length


def _records(snapshot: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = snapshot.get(key, {})
    if not isinstance(value, Mapping):
        raise InvalidSnapshot(f"snapshot field {key!r} must be an object")
    return value


def _walk_artifact_records(value: Any, selector: str = "") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        path_key = next((key for key in PATH_KEYS if isinstance(value.get(key), str)), None)
        hash_key = next((key for key in HASH_KEYS if isinstance(value.get(key), str)), None)
        if path_key is not None:
            candidate = {"path": value[path_key]}
            if hash_key is not None:
                candidate["sha256"] = value[hash_key]
            yield selector or "/", candidate
        for key in sorted(value, key=str):
            child = str(key).replace("~", "~0").replace("/", "~1")
            yield from _walk_artifact_records(value[key], f"{selector}/{child}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_artifact_records(item, f"{selector}/{index}")


def _task_cycles(dependencies: Mapping[str, Sequence[str]]) -> set[str]:
    """Return every task that belongs to a dependency cycle."""
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    cyclic: set[str] = set()

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in dependencies.get(node, []):
            if target not in dependencies:
                continue
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        if len(component) > 1 or node in dependencies.get(node, []):
            cyclic.update(component)

    for task_id in sorted(dependencies):
        if task_id not in indices:
            visit(task_id)
    return cyclic


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE generations (
            generation_id TEXT PRIMARY KEY,
            snapshot_sha256 TEXT NOT NULL,
            ledger_schema TEXT NOT NULL,
            ledger_revision INTEGER NOT NULL,
            extractor_version TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            built_at REAL NOT NULL
        );
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE nodes (
            node_id TEXT PRIMARY KEY,
            node_type TEXT NOT NULL,
            logical_key TEXT NOT NULL,
            record_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX nodes_logical ON nodes(node_type, logical_key);
        CREATE TABLE edges (
            edge_id TEXT PRIMARY KEY,
            edge_type TEXT NOT NULL,
            source_id TEXT NOT NULL REFERENCES nodes(node_id),
            target_id TEXT NOT NULL REFERENCES nodes(node_id),
            provenance_json TEXT NOT NULL
        );
        CREATE INDEX edges_source ON edges(source_id, edge_type);
        CREATE INDEX edges_target ON edges(target_id, edge_type);
        CREATE TABLE locators (
            locator_id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL REFERENCES nodes(node_id),
            path TEXT NOT NULL,
            expected_sha256 TEXT,
            observed_sha256 TEXT,
            status TEXT NOT NULL,
            byte_length INTEGER,
            source_node_id TEXT NOT NULL REFERENCES nodes(node_id),
            selector TEXT NOT NULL
        );
        CREATE INDEX locators_status ON locators(status, path);
        CREATE TABLE readiness (
            task_id TEXT PRIMARY KEY,
            is_ready INTEGER NOT NULL,
            reasons_json TEXT NOT NULL,
            dependencies_json TEXT NOT NULL
        );
        """
    )


def _add_node(
    connection: sqlite3.Connection,
    *,
    node_type: str,
    ledger_id: str,
    logical_key: str,
    payload: Any,
) -> str:
    record_hash = _sha_json(payload)
    node_id = ":".join(
        (node_type.lower(), _id_part(ledger_id), _id_part(logical_key), record_hash)
    )
    connection.execute(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?)",
        (node_id, node_type, logical_key, record_hash, _json(_redact(payload))),
    )
    return node_id


def _add_edge(
    connection: sqlite3.Connection,
    edge_type: str,
    source: str,
    target: str,
    provenance: Mapping[str, Any],
) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO edges VALUES (?, ?, ?, ?, ?)",
        (_edge_id(edge_type, source, target, provenance), edge_type, source, target, _json(provenance)),
    )


def _observe_artifact(path_text: str, expected: str | None, roots: Sequence[Path]) -> dict[str, Any]:
    expected = expected.lower() if expected and HEX_SHA256.fullmatch(expected) else None
    raw_path = Path(path_text)
    if not raw_path.is_absolute():
        return {"path": "relative:sha256:" + _sha_bytes(path_text.encode("utf-8")), "expected": expected, "observed": None, "status": "relative-unresolved", "length": None}
    resolved = raw_path.resolve(strict=False)
    if not roots or not _within(resolved, roots):
        return {"path": "excluded:sha256:" + _sha_bytes(path_text.encode("utf-8")), "expected": expected, "observed": None, "status": "excluded", "length": None}
    if not resolved.exists():
        return {"path": path_text, "expected": expected, "observed": None, "status": "missing", "length": None}
    if not resolved.is_file():
        return {"path": path_text, "expected": expected, "observed": None, "status": "not-file", "length": None}
    observed, length = _hash_file(resolved)
    status = "verified" if expected is None or expected == observed else "drifted"
    return {"path": path_text, "expected": expected, "observed": observed, "status": status, "length": length}


def _populate(
    connection: sqlite3.Connection,
    snapshot: Mapping[str, Any],
    *,
    ledger_id: str,
    allow_roots: Sequence[Path],
) -> dict[str, int]:
    section_types = {
        "workers": "Actor",
        "tasks": "Task",
        "leases": "Lease",
        "quota_snapshots": "Quota",
        "checkpoints": "Checkpoint",
        "results": "Result",
        "requests": "Request",
        "operations": "Operation",
        "inbox": "Message",
        "outbox": "Message",
        "handoffs": "Handoff",
    }
    lookup: dict[tuple[str, str], str] = {}
    for section, node_type in section_types.items():
        for key, payload in sorted(_records(snapshot, section).items(), key=lambda item: str(item[0])):
            if not isinstance(payload, Mapping):
                raise InvalidSnapshot(f"{section}[{key!r}] must be an object")
            logical = f"{section}:{key}" if section in {"inbox", "outbox"} else str(key)
            lookup[(section, str(key))] = _add_node(
                connection, node_type=node_type, ledger_id=ledger_id, logical_key=logical, payload=payload
            )

    tasks = _records(snapshot, "tasks")
    for task_id, payload in sorted(tasks.items(), key=lambda item: str(item[0])):
        source = lookup[("tasks", str(task_id))]
        dependencies = payload.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise InvalidSnapshot(f"task {task_id!r} dependencies must be a list")
        for dependency in sorted(str(item) for item in dependencies):
            target = lookup.get(("tasks", dependency))
            if target is not None:
                _add_edge(connection, "depends_on", source, target, {"section": "tasks", "field": "dependencies", "explicit": True})

    workers = _records(snapshot, "workers")
    results = _records(snapshot, "results")
    for result_key, payload in sorted(results.items(), key=lambda item: str(item[0])):
        source = lookup[("results", str(result_key))]
        task_id = str(payload.get("task_id", result_key))
        target = lookup.get(("tasks", task_id))
        if target is not None:
            _add_edge(connection, "produced_for", source, target, {"section": "results", "field": "task_id", "explicit": True})
        holder = payload.get("holder")
        if isinstance(holder, str):
            actor = lookup.get(("workers", holder))
            if actor is not None:
                _add_edge(connection, "produced_by", source, actor, {"section": "results", "field": "holder", "explicit": True})
        for selector, record in _walk_artifact_records(payload):
            observation = _observe_artifact(str(record["path"]), record.get("sha256"), allow_roots)
            identity = observation["observed"] or observation["expected"]
            logical = f"sha256:{identity}" if identity else "unresolved:" + _sha_json({"path": observation["path"], "source": source, "selector": selector})
            artifact_id = _add_node(
                connection,
                node_type="Artifact",
                ledger_id="artifact",
                logical_key=logical,
                payload={"classification": "pointer-only"},
            ) if connection.execute("SELECT 1 FROM nodes WHERE node_type='Artifact' AND logical_key=?", (logical,)).fetchone() is None else connection.execute("SELECT node_id FROM nodes WHERE node_type='Artifact' AND logical_key=?", (logical,)).fetchone()[0]
            provenance = {"source_section": "results", "source_key": str(result_key), "selector": selector, "explicit": True}
            _add_edge(connection, "has_receipt", source, artifact_id, provenance)
            locator_id = "locator:sha256:" + _sha_json({"artifact": artifact_id, "path": observation["path"], "source": source, "selector": selector})
            connection.execute(
                "INSERT OR IGNORE INTO locators VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (locator_id, artifact_id, observation["path"], observation["expected"], observation["observed"], observation["status"], observation["length"], source, selector),
            )

    for checkpoint_key, payload in sorted(_records(snapshot, "checkpoints").items(), key=lambda item: str(item[0])):
        task_id = payload.get("task_id")
        if isinstance(task_id, str) and ("tasks", task_id) in lookup:
            _add_edge(connection, "checkpointed_as", lookup[("tasks", task_id)], lookup[("checkpoints", str(checkpoint_key))], {"section": "checkpoints", "field": "task_id", "explicit": True})

    for lease_key, payload in sorted(_records(snapshot, "leases").items(), key=lambda item: str(item[0])):
        lease = lookup[("leases", str(lease_key))]
        holder = payload.get("holder")
        if isinstance(holder, str) and ("workers", holder) in lookup:
            _add_edge(connection, "held_by", lease, lookup[("workers", holder)], {"section": "leases", "field": "holder", "explicit": True})
        resource = payload.get("resource_id")
        if not isinstance(resource, str) and str(lease_key).startswith("task:"):
            resource = str(lease_key).split(":", 1)[1]
        kind = payload.get("kind")
        inferred_task_kind = kind is None and str(lease_key).startswith("task:")
        if isinstance(resource, str) and (kind == "task" or inferred_task_kind) and ("tasks", resource) in lookup:
            _add_edge(connection, "covers", lease, lookup[("tasks", resource)], {"section": "leases", "field": "resource_id", "explicit": isinstance(payload.get("resource_id"), str)})

    for worker_id, payload in sorted(workers.items(), key=lambda item: str(item[0])):
        quota_id = payload.get("quota_snapshot_id")
        if isinstance(quota_id, str) and ("quota_snapshots", quota_id) in lookup:
            _add_edge(connection, "measured_for", lookup[("quota_snapshots", quota_id)], lookup[("workers", str(worker_id))], {"section": "workers", "field": "quota_snapshot_id", "explicit": True})

    dependencies = {str(task_id): [str(item) for item in payload.get("dependencies", [])] for task_id, payload in tasks.items()}
    cyclic = _task_cycles(dependencies)
    active_leases: set[str] = set()
    for lease_key, payload in _records(snapshot, "leases").items():
        if payload.get("state") != "active":
            continue
        kind = payload.get("kind")
        if kind != "task" and not (kind is None and str(lease_key).startswith("task:")):
            continue
        resource = payload.get("resource_id")
        if not isinstance(resource, str) and str(lease_key).startswith("task:"):
            resource = str(lease_key).split(":", 1)[1]
        if isinstance(resource, str):
            active_leases.add(resource)
    unresolved_operations: set[str] = set()
    for payload in _records(snapshot, "operations").values():
        task_id = payload.get("task_id")
        status = str(payload.get("status", "unknown"))
        if isinstance(task_id, str) and status not in TERMINAL_OPERATION_STATUSES:
            unresolved_operations.add(task_id)

    for task_id, payload in sorted(tasks.items(), key=lambda item: str(item[0])):
        task_id = str(task_id)
        reasons: list[str] = []
        status = str(payload.get("status", "unknown"))
        if status != "queued":
            reasons.append(f"status:{status}")
        if payload.get("recovery_required"):
            reasons.append("recovery-required")
        if payload.get("blocked_reason"):
            reasons.append("explicit-blocker")
        if task_id in cyclic:
            reasons.append("dependency-cycle")
        for dependency in dependencies[task_id]:
            dependency_record = tasks.get(dependency)
            if dependency_record is None:
                reasons.append(f"missing-dependency:{dependency}")
            elif dependency_record.get("status") != "completed":
                reasons.append(f"dependency-not-completed:{dependency}:{dependency_record.get('status', 'unknown')}")
            elif not dependency_record.get("result_id") or dependency not in results:
                reasons.append(f"dependency-result-missing:{dependency}")
        if task_id in active_leases:
            reasons.append("active-lease")
        if task_id in unresolved_operations:
            reasons.append("unresolved-operation")
        connection.execute(
            "INSERT INTO readiness VALUES (?, ?, ?, ?)",
            (task_id, int(not reasons), _json(sorted(set(reasons))), _json(dependencies[task_id])),
        )

    return {
        "nodes": connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        "edges": connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        "locators": connection.execute("SELECT COUNT(*) FROM locators").fetchone()[0],
        "ready": connection.execute("SELECT COUNT(*) FROM readiness WHERE is_ready=1").fetchone()[0],
    }


def build_index(
    snapshot_path: Path,
    index_path: Path,
    *,
    ledger_id: str = "default",
    allow_roots: Sequence[Path] = (),
    built_at: float | None = None,
) -> dict[str, Any]:
    snapshot_path = snapshot_path.resolve(strict=True)
    index_path = index_path.resolve(strict=False)
    if snapshot_path == index_path:
        raise UnsafePath("snapshot and index paths must differ")
    raw = snapshot_path.read_bytes()
    try:
        snapshot = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidSnapshot(f"snapshot is not valid UTF-8 JSON: {snapshot_path}") from exc
    if not isinstance(snapshot, Mapping) or snapshot.get("schema") != LEDGER_SCHEMA:
        raise InvalidSnapshot(f"snapshot schema must be {LEDGER_SCHEMA!r}")
    revision = snapshot.get("revision")
    if not isinstance(revision, int) or revision < 0:
        raise InvalidSnapshot("snapshot revision must be a non-negative integer")
    resolved_roots = tuple(root.resolve(strict=True) for root in allow_roots)
    if any(not root.is_dir() for root in resolved_roots):
        raise UnsafePath("every allow-root must be an existing directory")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{index_path.name}.", suffix=".tmp", dir=index_path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    snapshot_sha = _sha_bytes(raw)
    generation_id = _sha_json({"snapshot_sha256": snapshot_sha, "extractor": EXTRACTOR_VERSION, "policy": POLICY_VERSION, "ledger_id": ledger_id})
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            _schema(connection)
            stats = _populate(connection, snapshot, ledger_id=ledger_id, allow_roots=resolved_roots)
            timestamp = time.time() if built_at is None else float(built_at)
            connection.execute(
                "INSERT INTO generations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (generation_id, snapshot_sha, LEDGER_SCHEMA, revision, EXTRACTOR_VERSION, POLICY_VERSION, timestamp),
            )
            metadata = {
                "schema": INDEX_SCHEMA,
                "generation_id": generation_id,
                "snapshot_sha256": snapshot_sha,
                "ledger_schema": LEDGER_SCHEMA,
                "ledger_revision": str(revision),
                "authority": "derived-advisory-only",
            }
            connection.executemany("INSERT INTO metadata VALUES (?, ?)", sorted(metadata.items()))
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise IndexErrorBase("SQLite integrity check failed")
        finally:
            connection.close()
        for attempt in range(4):
            try:
                os.replace(temporary, index_path)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.05 * (2 ** attempt))
        return {"status": "built", "authority": "derived-advisory-only", "index": str(index_path), "generation_id": generation_id, "snapshot_sha256": snapshot_sha, "ledger_revision": revision, **stats}
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _open_read_only(index_path: Path) -> sqlite3.Connection:
    resolved = index_path.resolve(strict=True)
    uri = "file:" + quote(resolved.as_posix(), safe="/:" ) + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    schema = connection.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
    if schema is None or schema[0] != INDEX_SCHEMA:
        connection.close()
        raise IndexErrorBase(f"unsupported index schema: {index_path}")
    return connection


def _generation(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM generations").fetchone()
    return dict(row) if row is not None else {}


def ready_tasks(index_path: Path, *, include_blocked: bool = False) -> dict[str, Any]:
    with _open_read_only(index_path) as connection:
        where = "" if include_blocked else "WHERE is_ready=1"
        rows = connection.execute(f"SELECT * FROM readiness {where} ORDER BY task_id").fetchall()
        items = [
            {"task_id": row["task_id"], "ready": bool(row["is_ready"]), "reasons": json.loads(row["reasons_json"]), "dependencies": json.loads(row["dependencies_json"])}
            for row in rows
        ]
        return {"authority": "advisory-only", "generation": _generation(connection), "tasks": items, "canonical_revalidation_required": True}


def explain_task(index_path: Path, task_id: str) -> dict[str, Any]:
    with _open_read_only(index_path) as connection:
        node = connection.execute("SELECT * FROM nodes WHERE node_type='Task' AND logical_key=?", (task_id,)).fetchone()
        if node is None:
            raise IndexErrorBase(f"unknown task: {task_id}")
        ready = connection.execute("SELECT * FROM readiness WHERE task_id=?", (task_id,)).fetchone()
        edges = connection.execute(
            "SELECT edge_type, source_id, target_id, provenance_json FROM edges WHERE source_id=? OR target_id=? ORDER BY edge_type, source_id, target_id",
            (node["node_id"], node["node_id"]),
        ).fetchall()
        return {
            "authority": "advisory-only",
            "generation": _generation(connection),
            "task": {"node_id": node["node_id"], "record_hash": node["record_hash"], "record": json.loads(node["payload_json"])},
            "readiness": {"ready": bool(ready["is_ready"]), "reasons": json.loads(ready["reasons_json"]), "dependencies": json.loads(ready["dependencies_json"])},
            "edges": [{"type": row["edge_type"], "source": row["source_id"], "target": row["target_id"], "provenance": json.loads(row["provenance_json"])} for row in edges],
            "canonical_revalidation_required": True,
        }


def drifted_artifacts(index_path: Path) -> dict[str, Any]:
    with _open_read_only(index_path) as connection:
        rows = connection.execute(
            "SELECT * FROM locators WHERE status != 'verified' ORDER BY status, path, locator_id"
        ).fetchall()
        return {
            "authority": "advisory-only",
            "generation": _generation(connection),
            "artifacts": [dict(row) for row in rows],
            "canonical_revalidation_required": True,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--snapshot", required=True, type=Path)
    build.add_argument("--index", required=True, type=Path)
    build.add_argument("--ledger-id", default="default")
    build.add_argument("--allow-root", action="append", default=[], type=Path)
    ready = sub.add_parser("ready")
    ready.add_argument("--index", required=True, type=Path)
    ready.add_argument("--include-blocked", action="store_true")
    explain = sub.add_parser("explain")
    explain.add_argument("task_id")
    explain.add_argument("--index", required=True, type=Path)
    artifacts = sub.add_parser("artifacts")
    artifacts.add_argument("--index", required=True, type=Path)
    artifacts.add_argument("--missing-or-drifted", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_index(args.snapshot, args.index, ledger_id=args.ledger_id, allow_roots=args.allow_root)
        elif args.command == "ready":
            result = ready_tasks(args.index, include_blocked=args.include_blocked)
        elif args.command == "explain":
            result = explain_task(args.index, args.task_id)
        elif args.command == "artifacts":
            if not args.missing_or_drifted:
                raise IndexErrorBase("artifacts currently requires --missing-or-drifted")
            result = drifted_artifacts(args.index)
        else:  # pragma: no cover
            raise IndexErrorBase(f"unknown command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (IndexErrorBase, OSError, sqlite3.Error) as exc:
        print(json.dumps({"status": "error", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
