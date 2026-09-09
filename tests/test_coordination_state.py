"""Deterministic acceptance floor for the coordination state layer.

The tests use only temporary state roots, fake workers and a fake clock.  They
never contact a provider or deliberately consume a real subscription quota.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from coordination_state import (  # noqa: E402
    CoordinationState,
    FencedError,
    LeaseConflict,
    RecoveryRequired,
    ScopeRefused,
    StateRootError,
)


class FakeClock:
    def __init__(self, value: float = 1_000.0):
        self.value = float(value)

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


def make_state(tmp_path: Path) -> tuple[CoordinationState, FakeClock]:
    clock = FakeClock()
    return CoordinationState(tmp_path / "coordination", clock=clock), clock


def worker(state: CoordinationState, worker_id: str, *, mode: str = "available",
           alive: bool | None = False, budget: int = 0, capability: str = "coding",
           snapshot_id: str | None = None) -> dict:
    return state.register_worker(
        worker_id,
        "fake",
        model="fake-model",
        account_alias=f"acct-{worker_id}",
        capabilities=[capability],
        mode=mode,
        process_alive=alive,
        question_budget=budget,
        quota_snapshot_id=snapshot_id,
    )


def quota(state: CoordinationState, worker_id: str, *, window: str = "w1",
          value: float = 100, exhausted: bool = False, stale: bool = False,
          reset_at: float | None = None) -> dict:
    return state.capture_quota(
        "fake", f"acct-{worker_id}", window, direction="remaining", value=value,
        exhausted=exhausted, stale=stale, reset_at=reset_at, worker_id=worker_id,
    )


def task(state: CoordinationState, task_id: str = "task-1", *, capability: str = "coding",
         allowed_paths: list[str] | None = None) -> dict:
    return state.register_task(task_id, capability=[capability], allowed_paths=allowed_paths or ["src/**"])


def test_state_root_is_explicit_and_files_are_operational(tmp_path: Path) -> None:
    with pytest.raises(StateRootError):
        CoordinationState(None)
    state, _ = make_state(tmp_path)
    state.initialize()
    assert (state.root / "workers.json").exists()
    assert (state.root / "tasks.json").exists()
    assert (state.root / "leases.json").exists()
    assert (state.root / "events.jsonl").exists()
    assert (state.root / "inbox.json").exists()
    assert (state.root / "outbox.json").exists()
    assert (state.root / "handoffs.json").exists()


def test_peer_messages_are_immutable_and_redacted(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    task(state)
    message = state.send_message("task-1", "worker", "deputy", "checkpoint", payload={"api_key": "secret"})
    assert state.message(message["message_id"])["payload"]["api_key"] == "[redacted]"
    acknowledged = state.acknowledge_message(message["message_id"], "deputy")
    assert acknowledged["state"] == "acknowledged"
    assert state.recover()["inbox"][message["message_id"]]["state"] == "acknowledged"


def test_two_coordinators_race_and_only_one_wins_current_fence(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "a")
    worker(state, "b")
    quota(state, "a")
    quota(state, "b")
    task(state)
    results: list[tuple[str, object]] = []
    barrier = threading.Barrier(2)

    def claim(worker_id: str) -> None:
        contender = CoordinationState(state.root, clock=state.clock, lock_timeout=5)
        barrier.wait()
        try:
            results.append((worker_id, contender.acquire_task_lease("task-1", worker_id, expected_task_revision=0)))
        except Exception as exc:  # deliberately capture the losing error
            results.append((worker_id, exc))

    threads = [threading.Thread(target=claim, args=(worker_id,)) for worker_id in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert sum(isinstance(value, dict) for _, value in results) == 1
    assert sum(isinstance(value, LeaseConflict) for _, value in results) == 1
    lease = state.lease("task", "task-1")
    assert lease and lease["epoch"] == 1


def test_draining_checkpoint_and_replacement_resume_once(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "original", alive=False)
    worker(state, "replacement", alive=False)
    quota(state, "original")
    quota(state, "replacement")
    task(state)
    original = state.acquire_task_lease("task-1", "original")
    checkpoint = state.checkpoint_task(
        "task-1", "original", original["epoch"], original["fencing_token"],
        state={"step": 2}, dirty_paths=["src/a.py"], next_safe_action="run tests",
    )
    assert checkpoint["status"] == "checkpointed"
    replacement = state.claim_replacement("task-1", "replacement", checkpoint["checkpoint"]["checkpoint_id"], expected_task_revision=checkpoint["replacement_input_revision"])
    with pytest.raises(LeaseConflict):
        state.claim_replacement("task-1", "replacement", checkpoint["checkpoint"]["checkpoint_id"])
    published = state.publish_result(
        "task-1", "replacement", replacement["epoch"], replacement["fencing_token"],
        replacement["task_revision"], {"ok": True}, result_id="replacement-result",
    )
    assert published["integrated"] is True
    assert state.integration_count("task-1") == 1
    assert state.recover()["tasks"]["task-1"]["integrated_count"] == 1


def test_late_original_output_is_fenced_after_replacement(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "original", alive=False)
    worker(state, "replacement", alive=False)
    quota(state, "original")
    quota(state, "replacement")
    task(state)
    original = state.acquire_task_lease("task-1", "original")
    handoff = state.checkpoint_task("task-1", "original", original["epoch"], original["fencing_token"])
    replacement = state.claim_replacement("task-1", "replacement", handoff["checkpoint"]["checkpoint_id"])
    with pytest.raises(FencedError):
        state.publish_result("task-1", "original", original["epoch"], original["fencing_token"], 1, {"late": True}, result_id="late")
    state.publish_result("task-1", "replacement", replacement["epoch"], replacement["fencing_token"], replacement["task_revision"], {"ok": True}, result_id="good")
    assert state.integration_count("task-1") == 1


def test_live_process_observation_timeout_does_not_duplicate(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "original", alive=True)
    worker(state, "replacement", alive=False)
    quota(state, "original")
    quota(state, "replacement")
    task(state)
    lease = state.acquire_task_lease("task-1", "original")
    result = state.checkpoint_task("task-1", "original", lease["epoch"], lease["fencing_token"], observe_timeout=True)
    assert result["status"] == "observation-pending"
    assert result["duplicate_prevented"] is True
    assert state.lease("task", "task-1")["state"] == "active"
    with pytest.raises(FencedError):
        state.claim_replacement("task-1", "replacement", "not-a-checkpoint")


def test_expired_lease_with_live_process_stays_fenced(tmp_path: Path) -> None:
    state, clock = make_state(tmp_path)
    worker(state, "original", alive=True)
    worker(state, "replacement", alive=False)
    quota(state, "original")
    quota(state, "replacement")
    task(state)
    lease = state.acquire_task_lease("task-1", "original", ttl=1)
    clock.advance(2)
    with pytest.raises(LeaseConflict):
        state.acquire_task_lease("task-1", "replacement")


def test_unknown_com_completion_requires_recovery_and_blocks_replay(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "com-owner", alive=False)
    worker(state, "replacement", alive=False)
    quota(state, "com-owner")
    quota(state, "replacement")
    task(state)
    lease = state.acquire_task_lease("task-1", "com-owner")
    operation = state.begin_operation("task-1", "com-owner", lease["epoch"], lease["fencing_token"], operation_kind="com")
    state.finish_operation(operation["operation_id"], status="unknown")
    with pytest.raises(RecoveryRequired):
        state.replay_operation("task-1", operation["operation_id"])
    with pytest.raises(RecoveryRequired):
        state.acquire_task_lease("task-1", "replacement")
    assert state.task("task-1")["recovery_required"] is True
    state.resolve_recovery("task-1", resolution="operator-readback", receipt={"saved": False})
    assert state.task("task-1")["recovery_required"] is False


def test_stale_or_different_window_quota_cannot_switch_provider(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "stale")
    worker(state, "wrong-window")
    quota(state, "stale", stale=True)
    quota(state, "wrong-window", window="w2")
    task(state)
    blocked = state.route_task("task-1", service="fake", window="w1")
    assert blocked["status"] == "blocked"
    assert {item["reason"] for item in blocked["rejected"]} == {"quota-stale", "quota-window-mismatch"}
    assert state.task("task-1")["status"] == "blocked"


def test_reset_time_does_not_clear_fresh_exhausted_quota(tmp_path: Path) -> None:
    state, clock = make_state(tmp_path)
    worker(state, "exhausted")
    snapshot = quota(state, "exhausted", exhausted=True, reset_at=1_001)
    clock.advance(10)
    assert snapshot["reset_time"] == 1_001
    assert state.worker_available("exhausted", service="fake", window="w1") is False
    assert state.worker("exhausted")["mode"] == "quota-blocked"


def test_recovered_original_waits_while_replacement_has_safe_boundary(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "original", alive=False)
    worker(state, "replacement", alive=False)
    quota(state, "original")
    quota(state, "replacement")
    task(state)
    original = state.acquire_task_lease("task-1", "original")
    handoff = state.checkpoint_task("task-1", "original", original["epoch"], original["fencing_token"])
    replacement = state.claim_replacement("task-1", "replacement", handoff["checkpoint"]["checkpoint_id"])
    state.update_worker("original", mode="available", availability=True, process_alive=True)
    with pytest.raises(LeaseConflict):
        state.acquire_task_lease("task-1", "original")
    state.publish_result("task-1", "replacement", replacement["epoch"], replacement["fencing_token"], replacement["task_revision"], {"done": True}, result_id="done")
    assert state.task("task-1")["status"] == "completed"


def test_reserve_specialist_answers_bounded_question_and_exhausted_routes_deputy(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "specialist", mode="reserve", budget=1)
    worker(state, "deputy", mode="available")
    quota(state, "specialist")
    quota(state, "deputy")
    answer = state.route_question("bounded question", capabilities=["coding"], preferred_worker="specialist", deputy_worker="deputy", service="fake", window="w1")
    assert answer["worker_id"] == "specialist"
    assert answer["bounded"] is True
    state.update_worker("specialist", mode="quota-blocked", availability=False)
    fallback = state.route_question("second question", capabilities=["coding"], preferred_worker="specialist", deputy_worker="deputy", service="fake", window="w1")
    assert fallback["worker_id"] == "deputy"
    assert any(item["reason"] == "mode-quota-blocked" for item in fallback["rejected"])


def test_all_unavailable_persists_and_yields_without_busy_loop(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "blocked", mode="quota-blocked")
    task(state)
    before = len(state.read_events()["events"])
    result = state.route_task("task-1", capabilities=["coding"], service="fake", window="w1")
    after = state.read_events()["events"]
    assert result["yield"] is True and result["busy_loop"] is False
    assert state.task("task-1")["status"] == "blocked"
    assert len(after) == before + 1
    assert after[-1]["kind"] == "routing.blocked"


def test_scope_credentials_and_unrestricted_spawn_are_refused_and_recorded(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    task(state, allowed_paths=["src/**"])
    refused = state.evaluate_request("task-1", "peer", "spawn workers", paths=["secrets/key.txt"], requires_credentials=True, unrestricted_spawn=True, metadata={"api_key": "do-not-log"})
    assert refused["status"] == "refused"
    assert set(refused["request"]["reasons"]) == {"outside-scope", "credential-access", "unrestricted-spawn"}
    events = state.read_events()["events"]
    refusal = events[-1]
    assert refusal["kind"] == "request.refused"
    assert "do-not-log" not in json.dumps(refusal)


def test_restart_recovers_without_duplicate_integration(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    quota(state, "worker")
    task(state)
    lease = state.acquire_task_lease("task-1", "worker")
    state.publish_result("task-1", "worker", lease["epoch"], lease["fencing_token"], lease["task_revision"], {"ok": True}, result_id="once")
    restarted = CoordinationState(state.root, clock=state.clock)
    assert restarted.recover()["tasks"]["task-1"]["integrated_count"] == 1
    duplicate = restarted.publish_result("task-1", "worker", lease["epoch"], lease["fencing_token"], lease["task_revision"], {"ok": True}, result_id="once")
    assert duplicate["status"] == "duplicate"
    assert restarted.integration_count("task-1") == 1


def test_cli_requires_explicit_state_root_and_can_initialize(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "coordination_state.py"
    missing = subprocess.run([sys.executable, str(script), "init"], capture_output=True, text=True)
    assert missing.returncode != 0
    root = tmp_path / "cli-state"
    created = subprocess.run([sys.executable, str(script), "--state-root", str(root), "init"], capture_output=True, text=True)
    assert created.returncode == 0
    assert json.loads(created.stdout)["schema"] == "rigorloom/coordination-state-v1"
