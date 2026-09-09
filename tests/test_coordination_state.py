"""Deterministic acceptance floor for the coordination state layer.

The tests use only temporary state roots, fake workers and a fake clock.  They
never contact a provider or deliberately consume a real subscription quota.
"""
from __future__ import annotations

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


def task(state: CoordinationState, task_id: str = "task-1", *, capability: str = "coding",
         allowed_paths: list[str] | None = None) -> dict:
    return state.register_task(task_id, capability=[capability], allowed_paths=allowed_paths or ["src/**"])


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
