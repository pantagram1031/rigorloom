"""Acceptance floor for the read-only coordination shadow index."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import coordination_index as indexer  # noqa: E402


def snapshot(**overrides: object) -> dict:
    value = {
        "schema": indexer.LEDGER_SCHEMA,
        "state_root": "C:/private/operational-state",
        "revision": 7,
        "workers": {
            "worker-1": {
                "worker_id": "worker-1",
                "provider": "fake",
                "capabilities": ["coding"],
                "quota_snapshot_id": "quota-1",
            }
        },
        "tasks": {
            "done": {"task_id": "done", "status": "completed", "dependencies": [], "recovery_required": False, "result_id": "result-done"},
            "ready": {"task_id": "ready", "status": "queued", "dependencies": ["done"], "recovery_required": False},
        },
        "leases": {},
        "quota_snapshots": {"quota-1": {"snapshot_id": "quota-1", "value": 80, "direction": "remaining"}},
        "checkpoints": {},
        "results": {"done": {"task_id": "done", "result_id": "result-done"}},
        "requests": {},
        "operations": {},
        "inbox": {},
        "outbox": {},
        "handoffs": {},
    }
    value.update(overrides)
    return value


def write_snapshot(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def rows(path: Path, table: str) -> list[tuple]:
    with sqlite3.connect(path) as connection:
        return connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def test_deterministic_nodes_edges_and_ready_order(tmp_path: Path) -> None:
    source = write_snapshot(tmp_path, snapshot())
    first = tmp_path / "first.sqlite"
    second = tmp_path / "second.sqlite"
    result_a = indexer.build_index(source, first, ledger_id="test", built_at=123)
    result_b = indexer.build_index(source, second, ledger_id="test", built_at=123)

    assert result_a["generation_id"] == result_b["generation_id"]
    assert rows(first, "nodes") == rows(second, "nodes")
    assert rows(first, "edges") == rows(second, "edges")
    assert rows(first, "readiness") == rows(second, "readiness")
    assert indexer.ready_tasks(first)["tasks"] == [
        {"task_id": "ready", "ready": True, "reasons": [], "dependencies": ["done"]}
    ]


def test_readiness_explains_every_refusal_and_cycle(tmp_path: Path) -> None:
    tasks = {
        "done": {"status": "completed", "dependencies": [], "recovery_required": False, "result_id": "result-done"},
        "no-result": {"status": "completed", "dependencies": [], "recovery_required": False},
        "good": {"status": "queued", "dependencies": ["done"], "recovery_required": False},
        "requires-result": {"status": "queued", "dependencies": ["no-result"], "recovery_required": False},
        "missing": {"status": "queued", "dependencies": ["absent"], "recovery_required": False},
        "blocked": {"status": "blocked", "dependencies": [], "blocked_reason": "manual", "recovery_required": False},
        "recover": {"status": "queued", "dependencies": [], "recovery_required": True},
        "leased": {"status": "queued", "dependencies": [], "recovery_required": False},
        "operating": {"status": "queued", "dependencies": [], "recovery_required": False},
        "committed-op": {"status": "queued", "dependencies": [], "recovery_required": False},
        "coordinator-name": {"status": "queued", "dependencies": [], "recovery_required": False},
        "cycle-a": {"status": "queued", "dependencies": ["cycle-b"], "recovery_required": False},
        "cycle-b": {"status": "queued", "dependencies": ["cycle-a"], "recovery_required": False},
    }
    value = snapshot(
        tasks=tasks,
        leases={
            "task:leased": {"kind": "task", "resource_id": "leased", "state": "active", "holder": "worker-1", "fencing_token": "must-not-leak"},
            "coordinator:coordinator-name": {"kind": "coordinator", "resource_id": "coordinator-name", "state": "active", "holder": "coordinator"},
        },
        operations={
            "op-1": {"operation_id": "op-1", "task_id": "operating", "status": "unknown"},
            "op-2": {"operation_id": "op-2", "task_id": "committed-op", "status": "committed"},
        },
    )
    source = write_snapshot(tmp_path, value)
    database = tmp_path / "index.sqlite"
    indexer.build_index(source, database)
    all_tasks = {item["task_id"]: item for item in indexer.ready_tasks(database, include_blocked=True)["tasks"]}

    assert all_tasks["good"]["ready"] is True
    assert "dependency-result-missing:no-result" in all_tasks["requires-result"]["reasons"]
    assert "missing-dependency:absent" in all_tasks["missing"]["reasons"]
    assert {"status:blocked", "explicit-blocker"}.issubset(all_tasks["blocked"]["reasons"])
    assert "recovery-required" in all_tasks["recover"]["reasons"]
    assert "active-lease" in all_tasks["leased"]["reasons"]
    assert "unresolved-operation" in all_tasks["operating"]["reasons"]
    assert all_tasks["committed-op"]["ready"] is True
    assert all_tasks["coordinator-name"]["ready"] is True
    assert "dependency-cycle" in all_tasks["cycle-a"]["reasons"]
    assert "dependency-cycle" in all_tasks["cycle-b"]["reasons"]


def test_artifact_verification_drift_missing_and_deduplication(tmp_path: Path) -> None:
    artifacts = tmp_path / "receipts"
    artifacts.mkdir()
    good = artifacts / "good.md"
    good.write_text("same bytes", encoding="utf-8")
    moved = artifacts / "moved.md"
    moved.write_text("same bytes", encoding="utf-8")
    drifted = artifacts / "drifted.md"
    drifted.write_text("changed", encoding="utf-8")
    expected = indexer._sha_bytes(good.read_bytes())
    value = snapshot(results={
        "done": {
            "task_id": "done",
            "holder": "worker-1",
            "receipt": {"path": str(good), "sha256": expected},
            "copies": [
                {"path": str(moved), "sha256": expected},
                {"path": str(drifted), "sha256": expected},
                {"path": str(artifacts / "missing.md"), "sha256": expected},
            ],
        }
    })
    source = write_snapshot(tmp_path, value)
    database = tmp_path / "index.sqlite"
    indexer.build_index(source, database, allow_roots=[artifacts])

    statuses = {row[5] for row in rows(database, "locators")}
    assert statuses == {"verified", "drifted", "missing"}
    with sqlite3.connect(database) as connection:
        artifact_count = connection.execute("SELECT COUNT(*) FROM nodes WHERE node_type='Artifact'").fetchone()[0]
    assert artifact_count == 2  # one expected artifact plus one observed drifted artifact
    reported = indexer.drifted_artifacts(database)["artifacts"]
    assert [item["status"] for item in reported] == ["drifted", "missing"]


def test_artifacts_are_not_read_without_an_allow_root(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.md"
    receipt.write_text("private", encoding="utf-8")
    value = snapshot(results={"done": {"task_id": "done", "receipt": {"path": str(receipt), "sha256": indexer._sha_bytes(receipt.read_bytes())}}})
    database = tmp_path / "index.sqlite"
    indexer.build_index(write_snapshot(tmp_path, value), database)
    artifact = indexer.drifted_artifacts(database)["artifacts"][0]
    assert artifact["status"] == "excluded"
    assert artifact["observed_sha256"] is None
    assert str(receipt) not in artifact["path"]
    assert artifact["path"].startswith("excluded:sha256:")


def test_fencing_and_credential_values_are_redacted(tmp_path: Path) -> None:
    value = snapshot(
        tasks={"ready": {"status": "queued", "dependencies": [], "recovery_required": False, "accepted_token": "accepted-secret", "github_token": "github-secret", "private_key": "private-secret"}},
        leases={"task:ready": {"state": "active", "holder": "worker-1", "resource_id": "ready", "fencing_token": "lease-secret", "api_key": "key-secret"}},
    )
    database = tmp_path / "index.sqlite"
    indexer.build_index(write_snapshot(tmp_path, value), database)
    database_text = "\n".join(row[0] for row in sqlite3.connect(database).execute("SELECT payload_json FROM nodes"))
    assert "lease-secret" not in database_text
    assert "accepted-secret" not in database_text
    assert "key-secret" not in database_text
    assert "github-secret" not in database_text
    assert "private-secret" not in database_text
    assert "[redacted]" in database_text


def test_failed_rebuild_preserves_previous_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_snapshot(tmp_path, snapshot())
    database = tmp_path / "index.sqlite"
    indexer.build_index(source, database, built_at=1)
    before = database.read_bytes()

    def fail(*_args: object, **_kwargs: object) -> dict[str, int]:
        raise RuntimeError("injected build failure")

    monkeypatch.setattr(indexer, "_populate", fail)
    with pytest.raises(RuntimeError, match="injected build failure"):
        indexer.build_index(source, database, built_at=2)
    assert database.read_bytes() == before
    assert not list(tmp_path.glob(".index.sqlite.*.tmp"))


def test_build_leaves_snapshot_bytes_unchanged(tmp_path: Path) -> None:
    source = write_snapshot(tmp_path, snapshot())
    before = source.read_bytes()
    indexer.build_index(source, tmp_path / "index.sqlite")
    assert source.read_bytes() == before


def test_invalid_schema_and_same_output_path_fail_closed(tmp_path: Path) -> None:
    source = write_snapshot(tmp_path, {**snapshot(), "schema": "wrong"})
    with pytest.raises(indexer.InvalidSnapshot):
        indexer.build_index(source, tmp_path / "index.sqlite")
    valid = write_snapshot(tmp_path, snapshot())
    with pytest.raises(indexer.UnsafePath):
        indexer.build_index(valid, valid)


def test_cli_build_ready_and_explain(tmp_path: Path) -> None:
    source = write_snapshot(tmp_path, snapshot())
    database = tmp_path / "index.sqlite"
    script = Path(indexer.__file__).resolve()
    built = subprocess.run(
        [sys.executable, str(script), "build", "--snapshot", str(source), "--index", str(database), "--ledger-id", "test"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    ready = subprocess.run(
        [sys.executable, str(script), "ready", "--index", str(database)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    explained = subprocess.run(
        [sys.executable, str(script), "explain", "ready", "--index", str(database)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert json.loads(built.stdout)["authority"] == "derived-advisory-only"
    assert json.loads(ready.stdout)["tasks"][0]["task_id"] == "ready"
    assert json.loads(explained.stdout)["readiness"]["ready"] is True
