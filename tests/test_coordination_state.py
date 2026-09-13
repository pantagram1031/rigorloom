"""Deterministic acceptance floor for the coordination state layer.

The tests use only temporary state roots, fake workers and a fake clock.  They
never contact a provider or deliberately consume a real subscription quota.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from coordination_state import (  # noqa: E402
    CrashInjected,
    CoordinationState,
    FencedError,
    InvalidRequest,
    LeaseConflict,
    RecoveryRequired,
    ScopeRefused,
    StateRootError,
    StateBusy,
    _lock_owner_alive,
    _process_start_identity,
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


def task(state: CoordinationState, task_id: str = "task-1", *,
         capability: str = "coding", allowed_paths: list[str] | None = None,
         dependencies: list[str] | None = None) -> dict:
    return state.register_task(
        task_id,
        capability=[capability],
        allowed_paths=allowed_paths or ["src/**"],
        dependencies=dependencies,
    )


def publish(
    state: CoordinationState,
    task_id: str,
    worker_id: str,
    result_id: str,
) -> dict:
    lease = state.acquire_task_lease(task_id, worker_id)
    return state.publish_result(
        task_id,
        worker_id,
        lease["epoch"],
        lease["fencing_token"],
        lease["task_revision"],
        {"verdict": "PASS"},
        result_id=result_id,
    )


def crash_after(stage: str, index: int):
    """Inject a deterministic process-crash equivalent at one WAL boundary."""
    def hook(actual_stage: str, actual_index: int, _name: str) -> None:
        if actual_stage == stage and actual_index == index:
            raise CrashInjected(f"crash at {stage}[{index}]")
    return hook


def event_ids(state: CoordinationState) -> list[str]:
    return [str(event["event_id"]) for event in state.read_events()["events"]]


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


def test_wal_crash_publish_result_recovers_coherent_projection_once(tmp_path: Path) -> None:
    state, clock = make_state(tmp_path)
    worker(state, "worker")
    quota(state, "worker")
    task(state)
    lease = state.acquire_task_lease("task-1", "worker")
    state._txn_hook = crash_after("json", 1)
    with pytest.raises(CrashInjected):
        state.publish_result("task-1", "worker", lease["epoch"], lease["fencing_token"], lease["task_revision"], {"ok": True}, result_id="wal-result")

    restarted = CoordinationState(state.root, clock=clock)
    recovered = restarted.recover()
    assert recovered["tasks"]["task-1"]["status"] == "completed"
    assert recovered["tasks"]["task-1"]["integrated_count"] == 1
    assert recovered["results"]["task-1"]["result_id"] == "wal-result"
    assert recovered["leases"]["task:task-1"]["state"] == "released"
    assert not list((state.root / ".transactions").glob("tx-*.json"))
    ids = event_ids(restarted)
    assert len(ids) == len(set(ids))
    duplicate = restarted.publish_result("task-1", "worker", lease["epoch"], lease["fencing_token"], lease["task_revision"], {"ok": True}, result_id="wal-result")
    assert duplicate["status"] == "duplicate"
    assert restarted.integration_count("task-1") == 1


def test_subprocess_exit_reclaims_dead_lock_and_replays_publish_wal(tmp_path: Path) -> None:
    state, clock = make_state(tmp_path)
    worker(state, "worker")
    quota(state, "worker")
    task(state)
    child_code = r'''
import os
import sys

sys.path.insert(0, sys.argv[2])
from coordination_state import CoordinationState

root = sys.argv[1]
state = CoordinationState(root)
lease = state.acquire_task_lease("task-1", "worker")

def crash(stage, index, _name):
    if stage == "json" and index == 1:
        os._exit(17)

state._txn_hook = crash
state.publish_result("task-1", "worker", lease["epoch"], lease["fencing_token"], lease["task_revision"], {"ok": True}, result_id="subprocess-result")
'''
    script_dir = str(Path(__file__).resolve().parents[1] / "scripts")
    child = subprocess.run(
        [sys.executable, "-c", child_code, str(state.root), script_dir],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert child.returncode == 17, child.stderr
    lock_path = state.root / ".coordination.lock"
    wal_paths = list((state.root / ".transactions").glob("tx-*.json"))
    assert lock_path.exists() and wal_paths
    owner = json.loads(lock_path.read_text(encoding="utf-8"))
    assert owner["pid"] != os.getpid() and isinstance(owner.get("process_start"), str) and owner["process_start"]

    restarted = CoordinationState(state.root, clock=clock, lock_timeout=5)
    recovered = restarted.recover()
    assert recovered["tasks"]["task-1"]["status"] == "completed"
    assert recovered["tasks"]["task-1"]["integrated_count"] == 1
    assert recovered["results"]["task-1"]["result_id"] == "subprocess-result"
    assert recovered["leases"]["task:task-1"]["state"] == "released"
    assert not lock_path.exists()
    assert not list((state.root / ".transactions").glob("tx-*.json"))
    ids = event_ids(restarted)
    assert len(ids) == len(set(ids))


def test_getters_wait_for_inflight_publish_and_return_coherent_projection(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    quota(state, "worker")
    task(state)
    lease = state.acquire_task_lease("task-1", "worker")
    replacement_started = threading.Event()
    release_transaction = threading.Event()
    publish_error: list[BaseException] = []

    def pause_between_json_replacements(stage: str, index: int, _name: str) -> None:
        if stage == "json" and index == 1:
            replacement_started.set()
            assert release_transaction.wait(5)

    state._txn_hook = pause_between_json_replacements

    def publish() -> None:
        try:
            state.publish_result("task-1", "worker", lease["epoch"], lease["fencing_token"], lease["task_revision"], {"ok": True}, result_id="reader-result")
        except BaseException as exc:  # pragma: no cover - diagnostic if thread fails
            publish_error.append(exc)

    writer = threading.Thread(target=publish)
    writer.start()
    assert replacement_started.wait(5)

    reader_done = threading.Event()
    projection: dict[str, dict] = {}
    reader_state = CoordinationState(state.root, clock=state.clock, lock_timeout=5)

    def read_projection() -> None:
        projection["task"] = reader_state.task("task-1")
        projection["lease"] = reader_state.lease("task", "task-1") or {}
        reader_done.set()

    reader = threading.Thread(target=read_projection)
    reader.start()
    assert not reader_done.wait(0.1), "getter returned while WAL transaction held the lock"
    release_transaction.set()
    writer.join(timeout=5)
    reader.join(timeout=5)
    assert not publish_error
    assert reader_done.is_set()
    assert projection["task"]["status"] == "completed"
    assert projection["task"]["integrated_count"] == 1
    assert projection["lease"]["state"] == "released"


def test_route_and_replay_wait_for_publish_wal_then_use_coherent_state(tmp_path: Path) -> None:
    state, clock = make_state(tmp_path)
    worker(state, "worker")
    quota(state, "worker")
    task(state)
    lease = state.acquire_task_lease("task-1", "worker")
    operation = state.begin_operation("task-1", "worker", lease["epoch"], lease["fencing_token"], operation_kind="unit")
    state.finish_operation(operation["operation_id"], status="failed")

    replacement_started = threading.Event()
    release_transaction = threading.Event()
    publish_error: list[BaseException] = []

    def pause_between_json_replacements(stage: str, index: int, _name: str) -> None:
        if stage == "json" and index == 1:
            replacement_started.set()
            assert release_transaction.wait(5)

    state._txn_hook = pause_between_json_replacements

    def publish() -> None:
        try:
            state.publish_result("task-1", "worker", lease["epoch"], lease["fencing_token"], lease["task_revision"], {"ok": True}, result_id="route-reader-result")
        except BaseException as exc:  # pragma: no cover - diagnostic if thread fails
            publish_error.append(exc)

    writer = threading.Thread(target=publish)
    writer.start()
    assert replacement_started.wait(5)

    route_state = CoordinationState(state.root, clock=clock, lock_timeout=5)
    replay_state = CoordinationState(state.root, clock=clock, lock_timeout=5)
    route_done = threading.Event()
    replay_done = threading.Event()
    route_result: dict[str, object] = {}
    replay_error: list[BaseException] = []

    def route() -> None:
        route_result.update(route_state.route_task("task-1", service="fake", window="w1"))
        route_done.set()

    def replay() -> None:
        try:
            replay_state.replay_operation("task-1", operation["operation_id"])
        except BaseException as exc:
            replay_error.append(exc)
        finally:
            replay_done.set()

    route_thread = threading.Thread(target=route)
    replay_thread = threading.Thread(target=replay)
    route_thread.start()
    replay_thread.start()
    assert not route_done.wait(0.1), "route returned while publish WAL held the lock"
    assert not replay_done.wait(0.1), "replay returned while publish WAL held the lock"
    release_transaction.set()
    writer.join(timeout=5)
    route_thread.join(timeout=5)
    replay_thread.join(timeout=5)
    assert not publish_error
    assert route_result["status"] == "completed"
    assert replay_error and isinstance(replay_error[0], RecoveryRequired)
    coherent = route_state.recover()
    assert coherent["tasks"]["task-1"]["status"] == "completed"
    assert coherent["tasks"]["task-1"]["integrated_count"] == 1
    assert coherent["leases"]["task:task-1"]["state"] == "released"


def test_wal_crash_checkpoint_handoff_recovers_then_replacement_integrates_once(tmp_path: Path) -> None:
    state, clock = make_state(tmp_path)
    worker(state, "original", alive=False)
    worker(state, "replacement", alive=False)
    quota(state, "original")
    quota(state, "replacement")
    task(state)
    original = state.acquire_task_lease("task-1", "original")
    state._txn_hook = crash_after("json", 1)
    with pytest.raises(CrashInjected):
        state.checkpoint_task("task-1", "original", original["epoch"], original["fencing_token"], state={"step": 2})

    restarted = CoordinationState(state.root, clock=clock)
    recovered = restarted.recover()
    recovered_task = recovered["tasks"]["task-1"]
    checkpoint_id = recovered_task["checkpoint_id"]
    assert recovered_task["status"] == "checkpointed"
    assert checkpoint_id in recovered["checkpoints"]
    assert checkpoint_id in recovered["handoffs"]
    assert recovered["leases"]["task:task-1"]["state"] == "released"
    assert recovered["workers"]["original"]["mode"] == "draining"

    replacement = restarted.claim_replacement("task-1", "replacement", checkpoint_id, expected_task_revision=recovered_task["revision"])
    restarted.publish_result("task-1", "replacement", replacement["epoch"], replacement["fencing_token"], replacement["task_revision"], {"done": True}, result_id="replacement-result")
    final = restarted.recover()
    assert final["tasks"]["task-1"]["status"] == "completed"
    assert final["tasks"]["task-1"]["integrated_count"] == 1
    assert final["leases"]["task:task-1"]["state"] == "released"
    assert len(event_ids(restarted)) == len(set(event_ids(restarted)))


def test_wal_crash_send_message_recovers_matching_inbox_outbox_once(tmp_path: Path) -> None:
    state, clock = make_state(tmp_path)
    state._txn_hook = crash_after("json", 1)
    with pytest.raises(CrashInjected):
        state.send_message("task-1", "sender", "recipient", "handoff", message_id="msg-wal", payload={"step": 3})

    restarted = CoordinationState(state.root, clock=clock)
    recovered = restarted.recover()
    assert recovered["inbox"]["msg-wal"] == recovered["outbox"]["msg-wal"]
    assert recovered["inbox"]["msg-wal"]["payload"] == {"step": 3}
    assert [event["kind"] for event in restarted.read_events()["events"]].count("message.sent") == 1
    assert len(event_ids(restarted)) == len(set(event_ids(restarted)))
    retried = restarted.send_message("task-1", "sender", "recipient", "handoff", message_id="msg-wal", payload={"step": 3})
    assert retried["message_id"] == "msg-wal"
    assert [event["kind"] for event in restarted.read_events()["events"]].count("message.sent") == 1


def test_wal_crash_after_event_append_replays_stable_event_id_once(tmp_path: Path) -> None:
    state, clock = make_state(tmp_path)
    # outbox, inbox, meta are the three JSON replacements, so event[4] is
    # reached after the first (and only) event has been appended.
    state._txn_hook = crash_after("event", 4)
    with pytest.raises(CrashInjected):
        state.send_message("task-1", "sender", "recipient", "handoff", message_id="msg-event", payload={"step": 4})

    restarted = CoordinationState(state.root, clock=clock)
    restarted.recover()
    events = restarted.read_events()["events"]
    assert [event["kind"] for event in events].count("message.sent") == 1
    assert len([event["event_id"] for event in events]) == len({event["event_id"] for event in events})


def test_torn_trailing_event_is_discarded_before_stable_wal_event_append(tmp_path: Path) -> None:
    state, _ = make_state(tmp_path)
    state.initialize()
    with (state.root / "events.jsonl").open("ab") as stream:
        stream.write(b'{"event_id":"prior","kind":"prior"}\n')
    # The malformed final record is a crash tail, not a valid event.
    with (state.root / "events.jsonl").open("ab") as stream:
        stream.write(b'{"event_id":"partial"')
    state.recover()
    state.append_event("stable.after.torn", {"ok": True})
    lines = (state.root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines if line.strip()]
    assert [item["kind"] for item in parsed] == ["prior", "stable.after.torn"]
    assert parsed[-1]["kind"] == "stable.after.torn"
    assert all(isinstance(item.get("event_id"), str) for item in parsed)


def test_lock_reclaims_exactly_dead_identity_but_live_and_unknown_stay_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state, _ = make_state(tmp_path)
    state.initialize()
    lock_path = state.root / ".coordination.lock"
    dead_pid = os.getpid() + 10_000_000
    lock_path.write_text(json.dumps({"pid": dead_pid, "process_start": "dead-start", "token": "dead-token"}), encoding="utf-8")
    state.register_worker("dead-reclaimed", "fake")
    assert not lock_path.exists()

    live_pid = os.getpid()
    live_identity = _process_start_identity(live_pid)
    assert isinstance(live_identity, str) and live_identity
    lock_path.write_text(json.dumps({"pid": live_pid, "process_start": live_identity, "token": "live-token"}), encoding="utf-8")
    busy = CoordinationState(state.root, clock=state.clock, lock_timeout=0.02)
    with pytest.raises(StateBusy):
        busy.register_worker("live-busy", "fake")
    lock_path.unlink()

    lock_path.write_text(json.dumps({"pid": live_pid, "process_start": live_identity, "token": "unknown-token"}), encoding="utf-8")
    monkeypatch.setattr("coordination_state._process_start_identity", lambda _pid=None: None)
    unknown = CoordinationState(state.root, clock=state.clock, lock_timeout=0.02)
    with pytest.raises(StateBusy):
        unknown.register_worker("unknown-busy", "fake")
    assert _lock_owner_alive({"pid": live_pid, "process_start": live_identity}) is None
    lock_path.unlink()


def test_lock_claim_fault_never_exposes_empty_or_unidentified_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state, _ = make_state(tmp_path)
    state.initialize()
    lock_path = state.root / ".coordination.lock"

    def crash_before_claim(*_args: object, **_kwargs: object) -> None:
        raise CrashInjected("crash during no-clobber lock claim")

    monkeypatch.setattr("coordination_state.os.link", crash_before_claim)
    with pytest.raises(CrashInjected):
        state.register_worker("claim-fault", "fake")
    assert not lock_path.exists()
    assert not list(state.root.glob(".coordination.lock.*.tmp"))

    monkeypatch.undo()
    monkeypatch.setattr("coordination_state._process_start_identity", lambda _pid=None: None)
    with pytest.raises(StateBusy):
        state.register_worker("identity-unknown", "fake")
    assert not lock_path.exists()


def test_cli_requires_explicit_state_root_and_can_initialize(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "coordination_state.py"
    missing = subprocess.run([sys.executable, str(script), "init"], capture_output=True, text=True)
    assert missing.returncode != 0
    root = tmp_path / "cli-state"
    created = subprocess.run([sys.executable, str(script), "--state-root", str(root), "init"], capture_output=True, text=True)
    assert created.returncode == 0
    assert json.loads(created.stdout)["schema"] == "rigorloom/coordination-state-v1"


def test_task_registration_refuses_self_and_closed_cycles_but_allows_forward_refs(
    tmp_path: Path,
) -> None:
    state, _ = make_state(tmp_path)

    forward = task(state, "forward", dependencies=["future"])
    assert forward["dependencies"] == ["future"]
    with pytest.raises(InvalidRequest, match="depend on itself"):
        task(state, "self", dependencies=["self"])
    with pytest.raises(InvalidRequest, match="dependency cycle"):
        task(state, "future", dependencies=["forward"])

    snapshot = state.recover()
    assert "forward" in snapshot["tasks"]
    assert "self" not in snapshot["tasks"]
    assert "future" not in snapshot["tasks"]


@pytest.mark.parametrize(
    ("condition", "expected_reason"),
    [
        ("missing", "dependency-missing"),
        ("incomplete", "dependency-not-completed"),
        ("undecided", "dependency-undecided"),
        ("rejected", "dependency-rejected"),
        ("superseded", "dependency-superseded"),
    ],
)
def test_direct_and_routed_leases_require_accepted_dependencies(
    tmp_path: Path, condition: str, expected_reason: str
) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    quota(state, "worker")
    if condition != "missing":
        task(state, "dependency")
    if condition in {"undecided", "rejected", "superseded"}:
        publish(state, "dependency", "worker", "dependency-result")
    if condition == "superseded":
        task(state, "replacement")
        publish(state, "replacement", "worker", "replacement-result")
    if condition in {"rejected", "superseded"}:
        coordinator = state.acquire_coordinator_lease("coordinator")
        state.decide_result(
            "dependency",
            "dependency-result",
            condition,
            "coordinator",
            coordinator["epoch"],
            coordinator["fencing_token"],
            superseding_task_id=(
                "replacement" if condition == "superseded" else None
            ),
            superseding_result_id=(
                "replacement-result" if condition == "superseded" else None
            ),
        )
    task(state, "direct", dependencies=["dependency"])
    task(state, "routed", dependencies=["dependency"])

    with pytest.raises(LeaseConflict, match=expected_reason):
        state.acquire_task_lease("direct", "worker")
    routed = state.route_task("routed", service="fake", window="w1")

    assert routed["status"] == "blocked"
    assert routed["reason"] == "dependencies-not-accepted"
    assert routed["dependencies"] == [
        {"task_id": "dependency", "reason": expected_reason}
    ]
    assert state.task("routed")["status"] == "queued"


def test_accepted_dependencies_allow_direct_and_routed_leases(
    tmp_path: Path,
) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    quota(state, "worker")
    task(state, "dependency")
    publish(state, "dependency", "worker", "dependency-result")
    coordinator = state.acquire_coordinator_lease("coordinator")
    state.decide_result(
        "dependency",
        "dependency-result",
        "accepted",
        "coordinator",
        coordinator["epoch"],
        coordinator["fencing_token"],
    )
    task(state, "direct", dependencies=["dependency"])
    task(state, "routed", dependencies=["dependency"])

    direct = state.acquire_task_lease("direct", "worker")
    state.release(direct)
    routed = state.route_task("routed", service="fake", window="w1")

    assert direct["holder"] == "worker"
    assert routed["status"] == "routed"
    assert routed["worker_id"] == "worker"


def test_checkpoint_replacement_remains_exempt_from_dependency_recheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "original", alive=False)
    worker(state, "replacement", alive=False)
    task(state, "dependency")
    publish(state, "dependency", "original", "dependency-result")
    coordinator = state.acquire_coordinator_lease("coordinator")
    state.decide_result(
        "dependency",
        "dependency-result",
        "accepted",
        "coordinator",
        coordinator["epoch"],
        coordinator["fencing_token"],
    )
    task(state, "resumable", dependencies=["dependency"])
    lease = state.acquire_task_lease("resumable", "original")
    checkpoint = state.checkpoint_task(
        "resumable",
        "original",
        lease["epoch"],
        lease["fencing_token"],
    )

    def unexpected_recheck(_task: dict) -> tuple[bool, list[dict[str, str]]]:
        raise AssertionError("checkpoint replacement rechecked dependencies")

    monkeypatch.setattr(state, "_dependencies_ready_locked", unexpected_recheck)
    replacement = state.claim_replacement(
        "resumable",
        "replacement",
        checkpoint["checkpoint"]["checkpoint_id"],
    )
    assert replacement["holder"] == "replacement"


def test_decide_result_is_coordinator_fenced_bound_structured_and_immutable(
    tmp_path: Path,
) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    task(state, "candidate")
    publish(state, "candidate", "worker", "candidate-result")
    coordinator = state.acquire_coordinator_lease("coordinator")
    args = (
        "candidate",
        "candidate-result",
        "accepted",
        "coordinator",
        coordinator["epoch"],
        coordinator["fencing_token"],
    )

    with pytest.raises(FencedError):
        state.decide_result(*args[:3], "foreign", *args[4:])
    with pytest.raises(FencedError):
        state.decide_result(*args[:4], coordinator["epoch"] + 1, args[5])
    with pytest.raises(FencedError):
        state.decide_result(*args[:5], "stale-token")
    with pytest.raises(InvalidRequest, match="not canonical"):
        state.decide_result(
            "candidate",
            "wrong-result",
            "accepted",
            "coordinator",
            coordinator["epoch"],
            coordinator["fencing_token"],
        )

    authority = {"card_sha256": "abc123"}
    receipt = {"path": "receipt.md", "verdict": "PASS"}
    facets = {
        "focused-tests": {
            "passed": 3,
            "failed": 0,
            "unrun": ["broad-tests"],
        }
    }
    decided = state.decide_result(
        *args,
        decider="sol-coordinator",
        authority=authority,
        receipt=receipt,
        evidence_facets=facets,
    )
    event_count = [
        event["kind"] for event in state.read_events()["events"]
    ].count("result.decided")
    duplicate = state.decide_result(
        *args,
        decider="sol-coordinator",
        authority=authority,
        receipt=receipt,
        evidence_facets=facets,
    )

    assert decided["status"] == "decided"
    assert decided["decision"]["disposition"] == "accepted"
    assert decided["decision"]["decider"] == "sol-coordinator"
    assert decided["decision"]["authority"] == authority
    assert decided["decision"]["receipt"] == receipt
    assert decided["decision"]["evidence_facets"] == facets
    assert "coordinator_accepted" not in decided["decision"]
    assert duplicate["status"] == "duplicate"
    assert duplicate["decision"] == decided["decision"]
    assert [
        event["kind"] for event in state.read_events()["events"]
    ].count("result.decided") == event_count == 1
    assert state.task("candidate")["decision"] == decided["decision"]
    assert state.recover()["results"]["candidate"]["decision"] == decided["decision"]
    with pytest.raises(FencedError, match="immutable"):
        state.decide_result(
            *args,
            decider="sol-coordinator",
            authority=authority,
            receipt=receipt,
            evidence_facets={"focused-tests": {"passed": 4}},
        )
    state.clock.advance(61)
    with pytest.raises(FencedError, match="no longer current"):
        state.decide_result(
            *args,
            decider="sol-coordinator",
            authority=authority,
            receipt=receipt,
            evidence_facets=facets,
        )


def test_decision_dispositions_enforce_targets_and_terminal_statuses(
    tmp_path: Path,
) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    for task_id in ("accepted", "rejected", "superseded", "replacement"):
        task(state, task_id)
        publish(state, task_id, "worker", f"{task_id}-result")
    coordinator = state.acquire_coordinator_lease("coordinator")

    accepted = state.decide_result(
        "accepted",
        "accepted-result",
        "accepted",
        "coordinator",
        coordinator["epoch"],
        coordinator["fencing_token"],
    )
    rejected = state.decide_result(
        "rejected",
        "rejected-result",
        "rejected",
        "coordinator",
        coordinator["epoch"],
        coordinator["fencing_token"],
        terminal=True,
    )
    with pytest.raises(InvalidRequest, match="requires superseding"):
        state.decide_result(
            "superseded",
            "superseded-result",
            "superseded",
            "coordinator",
            coordinator["epoch"],
            coordinator["fencing_token"],
        )
    with pytest.raises(InvalidRequest, match="not canonical"):
        state.decide_result(
            "superseded",
            "superseded-result",
            "superseded",
            "coordinator",
            coordinator["epoch"],
            coordinator["fencing_token"],
            superseding_task_id="replacement",
            superseding_result_id="wrong-result",
        )
    superseded = state.decide_result(
        "superseded",
        "superseded-result",
        "superseded",
        "coordinator",
        coordinator["epoch"],
        coordinator["fencing_token"],
        superseding_task_id="replacement",
        superseding_result_id="replacement-result",
    )

    assert accepted["task"]["status"] == "completed"
    assert rejected["task"]["status"] == "failed"
    assert superseded["task"]["status"] == "completed"
    assert superseded["decision"]["superseding_task_id"] == "replacement"
    assert superseded["decision"]["superseding_result_id"] == "replacement-result"


def test_one_holder_cannot_hold_two_active_task_leases_including_race(
    tmp_path: Path,
) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    task(state, "first")
    task(state, "second")
    state.acquire_task_lease("first", "worker")
    with pytest.raises(LeaseConflict, match="already has active task lease"):
        state.acquire_task_lease("second", "worker")

    race_state, _ = make_state(tmp_path / "race")
    worker(race_state, "worker")
    task(race_state, "left")
    task(race_state, "right")
    barrier = threading.Barrier(2)
    results: list[object] = []

    def acquire(task_id: str) -> None:
        contender = CoordinationState(
            race_state.root, clock=race_state.clock, lock_timeout=5
        )
        barrier.wait()
        try:
            results.append(contender.acquire_task_lease(task_id, "worker"))
        except Exception as exc:
            results.append(exc)

    threads = [
        threading.Thread(target=acquire, args=(task_id,))
        for task_id in ("left", "right")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert sum(isinstance(value, dict) for value in results) == 1
    assert sum(isinstance(value, LeaseConflict) for value in results) == 1
    active = [
        lease
        for lease in race_state.recover()["leases"].values()
        if lease["state"] == "active" and lease["kind"] == "task"
    ]
    assert len(active) == 1
    assert active[0]["holder"] == "worker"


def _all_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        return [
            key
            for name, item in value.items()
            for key in [str(name), *_all_keys(item)]
        ]
    if isinstance(value, list):
        return [key for item in value for key in _all_keys(item)]
    return []


def test_export_snapshot_is_one_lock_coherent_atomic_and_token_stripped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    task(state, "published")
    publish(state, "published", "worker", "published-result")
    state.send_message(
        "published",
        "worker",
        "coordinator",
        "evidence",
        payload={
            "api_key": "raw-api-secret",
            "nested": {"token": "raw-fencing-secret", "lease_id": "kept-id"},
        },
    )
    coordinator = state.acquire_coordinator_lease("coordinator")
    canonical_paths = {
        **{
            filename: state.root / filename
            for filename in state.FILES.values()
        },
        "events.jsonl": state.root / "events.jsonl",
    }
    before = {
        name: path.read_bytes() for name, path in canonical_paths.items()
    }
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    snapshot_path = export_dir / "snapshot.json"
    manifest_path = export_dir / "manifest.json"
    snapshot_path.write_bytes(b"old snapshot")
    manifest_path.write_bytes(b"old manifest")
    lock_calls = 0
    replace_calls: list[tuple[Path, Path]] = []
    original_lock = state._lock
    original_replace = os.replace

    def counted_lock():
        nonlocal lock_calls
        lock_calls += 1
        return original_lock()

    def recorded_replace(source, target) -> None:
        replace_calls.append((Path(source), Path(target)))
        original_replace(source, target)

    monkeypatch.setattr(state, "_lock", counted_lock)
    monkeypatch.setattr("coordination_state.os.replace", recorded_replace)
    exported = state.export_snapshot(
        snapshot_path,
        manifest_path,
        "coordinator",
        coordinator["epoch"],
        coordinator["fencing_token"],
    )

    snapshot_bytes = snapshot_path.read_bytes()
    snapshot = json.loads(snapshot_bytes)
    manifest = json.loads(manifest_path.read_bytes())
    after = {
        name: path.read_bytes() for name, path in canonical_paths.items()
    }
    assert lock_calls == 1
    assert [target for _, target in replace_calls] == [
        snapshot_path.resolve(),
        manifest_path.resolve(),
    ]
    assert not list(export_dir.glob("*.tmp"))
    assert before == after
    assert exported["snapshot_sha256"] == hashlib.sha256(snapshot_bytes).hexdigest()
    assert manifest["snapshot_sha256"] == exported["snapshot_sha256"]
    assert manifest["ledger_revision"] == snapshot["ledger_revision"]
    assert manifest["event_count"] == len(snapshot["events"])
    assert manifest["last_event_seq"] == snapshot["events"][-1]["seq"]
    assert manifest["redaction_policy_version"] == "1"
    assert manifest["export_implementation_version"] == "1"
    assert manifest["source_sha256"] == {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in before.items()
    }
    forbidden = {
        "fencing_token",
        "accepted_token",
        "token",
        "api_key",
        "password",
        "credential",
        "secret",
    }
    assert forbidden.isdisjoint(set(_all_keys(snapshot)))
    assert b"raw-api-secret" not in snapshot_bytes
    assert b"raw-fencing-secret" not in snapshot_bytes
    leases = snapshot["documents"]["leases"]["leases"].values()
    assert any(lease.get("lease_id") for lease in leases)
    assert any(
        lease.get("release_proof") == "canonical-result" for lease in leases
    )


def test_export_snapshot_recovers_prepared_wal_and_refuses_leftover_wal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = make_state(tmp_path)
    coordinator = state.acquire_coordinator_lease("coordinator")
    state._txn_hook = crash_after("prepared", 0)
    with pytest.raises(CrashInjected):
        state.append_event("recover.before.export", {"ok": True})
    state._txn_hook = None
    assert list((state.root / ".transactions").glob("tx-*.json"))

    snapshot_path = tmp_path / "recovered-snapshot.json"
    manifest_path = tmp_path / "recovered-manifest.json"
    state.export_snapshot(
        snapshot_path,
        manifest_path,
        "coordinator",
        coordinator["epoch"],
        coordinator["fencing_token"],
    )

    assert not list((state.root / ".transactions").glob("tx-*.json"))
    snapshot = json.loads(snapshot_path.read_bytes())
    assert snapshot["events"][-1]["kind"] == "recover.before.export"

    stuck = state.root / ".transactions" / "tx-stuck.json"
    stuck.write_text("{}", encoding="utf-8")
    refused_snapshot = tmp_path / "refused-snapshot.json"
    refused_manifest = tmp_path / "refused-manifest.json"
    monkeypatch.setattr(state, "_recover_locked", lambda: None)
    with pytest.raises(RecoveryRequired, match="pending transactions"):
        state.export_snapshot(
            refused_snapshot,
            refused_manifest,
            "coordinator",
            coordinator["epoch"],
            coordinator["fencing_token"],
        )
    assert not refused_snapshot.exists()
    assert not refused_manifest.exists()


def test_export_snapshot_refuses_unsafe_or_ambiguous_targets(
    tmp_path: Path,
) -> None:
    state, _ = make_state(tmp_path)
    coordinator = state.acquire_coordinator_lease("coordinator")
    fence = (
        "coordinator",
        coordinator["epoch"],
        coordinator["fencing_token"],
    )
    safe_manifest = tmp_path / "safe-manifest.json"

    fenced_snapshot = tmp_path / "fenced-snapshot.json"
    fenced_manifest = tmp_path / "fenced-manifest.json"
    with pytest.raises(FencedError, match="no longer current"):
        state.export_snapshot(
            fenced_snapshot,
            fenced_manifest,
            "coordinator",
            coordinator["epoch"],
            "stale-token",
        )
    assert not fenced_snapshot.exists()
    assert not fenced_manifest.exists()

    with pytest.raises(ScopeRefused, match="state root"):
        state.export_snapshot(
            state.root / "snapshot.json",
            safe_manifest,
            *fence,
        )

    checkout = tmp_path / "other-checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text(
        "[project]\nname = \"rigorloom\"\nversion = \"9.9\"\n",
        encoding="utf-8",
    )
    with pytest.raises(ScopeRefused, match="Rigorloom checkout"):
        state.export_snapshot(
            checkout / "snapshot.json",
            checkout / "manifest.json",
            *fence,
        )

    with pytest.raises(InvalidRequest, match="root"):
        state.export_snapshot(
            Path(tmp_path.anchor),
            safe_manifest,
            *fence,
        )

    ambiguous_snapshot = tmp_path / "ambiguous-snapshot.json"
    ambiguous_snapshot.write_text("old", encoding="utf-8")
    with pytest.raises(InvalidRequest, match="both exist or both be absent"):
        state.export_snapshot(
            ambiguous_snapshot,
            tmp_path / "missing-manifest.json",
            *fence,
        )

    directory_target = tmp_path / "directory-target"
    directory_target.mkdir()
    with pytest.raises(InvalidRequest, match="ambiguous export target"):
        state.export_snapshot(
            directory_target,
            tmp_path / "directory-manifest.json",
            *fence,
        )


def test_cli_decide_result_and_export_snapshot_commands(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "coordination_state.py"
    state = CoordinationState(tmp_path / "cli-ledger")
    worker(state, "worker")
    task(state, "candidate")
    publish(state, "candidate", "worker", "candidate-result")
    coordinator = state.acquire_coordinator_lease("coordinator")
    common = [sys.executable, str(script), "--state-root", str(state.root)]

    decided = subprocess.run(
        [
            *common,
            "decide-result",
            "candidate",
            "candidate-result",
            "accepted",
            "coordinator",
            str(coordinator["epoch"]),
            coordinator["fencing_token"],
            "--authority",
            '{"source":"coordinator"}',
            "--evidence-facets",
            '{"focused-tests":{"passed":1}}',
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    snapshot_path = tmp_path / "cli-snapshot.json"
    manifest_path = tmp_path / "cli-manifest.json"
    exported = subprocess.run(
        [
            *common,
            "export-snapshot",
            "coordinator",
            str(coordinator["epoch"]),
            coordinator["fencing_token"],
            str(snapshot_path),
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert decided.returncode == 0, decided.stderr
    assert json.loads(decided.stdout)["decision"]["disposition"] == "accepted"
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout)["status"] == "exported"
    assert snapshot_path.is_file()
    assert manifest_path.is_file()


def test_legacy_published_result_without_decision_stays_dependency_undecided(
    tmp_path: Path,
) -> None:
    state, _ = make_state(tmp_path)
    worker(state, "worker")
    task(state, "legacy")
    publish(state, "legacy", "worker", "legacy-result")
    task(state, "dependent", dependencies=["legacy"])

    assert "decision" not in state.task("legacy")
    assert "decision" not in state.recover()["results"]["legacy"]
    with pytest.raises(LeaseConflict, match="dependency-undecided"):
        state.acquire_task_lease("dependent", "worker")
