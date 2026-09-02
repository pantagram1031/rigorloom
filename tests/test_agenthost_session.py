# -*- coding: utf-8 -*-
"""A conversation that outlives the process that had it.

Three things are proven here, and the middle one is the reason the file exists:

  * the turn log is durable and append-atomic — including under concurrent
    writers on Windows, where ``open("ab")`` is not atomic and this repository
    measured 167 of 200 lines surviving without it;
  * a host process can be KILLED mid-conversation and a new one on the same
    session picks the history up and continues;
  * the history window is bounded, and what it drops is recorded in the turn
    record rather than quietly forgotten.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading

import pytest

from _agenthost_support import HOST_CLI, agenthost_scripts_on_path
from _runtime_client import CORPUS_FORM, run_cli

agenthost_scripts_on_path()

import ah_mock  # noqa: E402
import mock_agent  # noqa: E402
from ah_codes import SERVE_METHODS, SERVE_PROTOCOL_VERSION, AgentHostError  # noqa: E402
from ah_host import AgentHost  # noqa: E402
from ah_session import DEFAULT_TRUNCATION_POLICY, HostSession, read_records  # noqa: E402

SPAWN_TIMEOUT = 300.0


@pytest.fixture()
def opened(tmp_path):
    root = tmp_path / "root"
    source = tmp_path / "form.hwpx"
    shutil.copyfile(CORPUS_FORM, source)
    session = run_cli(root, "open", "--path", str(source)).result["sessionId"]
    return root, session


# --- the log itself ---------------------------------------------------------

def test_a_fresh_session_has_nothing_and_says_so(tmp_path):
    session = HostSession(tmp_path, "abc").load()
    assert session.attached is False
    assert session.turn_count == 0
    assert session.conversation() == ((), None)
    assert session.current_grant().is_empty()


def test_a_turn_is_readable_by_the_next_process(tmp_path):
    first = HostSession(tmp_path, "abc").load()
    first.append_turn({"turn": 1, "instruction": "do it", "reply": "done"})
    second = HostSession(tmp_path, "abc").load()
    assert second.attached is True
    assert second.turn_count == 1
    assert second.conversation()[0] == ({"instruction": "do it",
                                         "reply": "done"},)
    assert second.next_turn_number() == 2


def test_each_turn_carries_its_schema_and_a_timestamp(tmp_path):
    session = HostSession(tmp_path, "abc").load()
    stored = session.append_turn({"turn": 1, "instruction": "x", "reply": None})
    assert stored["schema"] == "rigorloom/agenthost-turn/v0"
    assert stored["sessionId"] == "abc"
    assert stored["at"].endswith("Z")


def test_concurrent_writers_lose_no_turns(tmp_path):
    """The Windows append trap, exercised on the Agent Host's own log.

    Four threads, fifty records each. Without ``rt_session.append_line``'s
    lock this loses lines silently — that is the measured behaviour recorded
    for the Runtime's event log, and this log uses the same primitive so it
    inherits the same guarantee rather than a similar-looking one.
    """
    session = HostSession(tmp_path, "abc").load()
    writers, per_writer = 4, 50

    def writer(tag):
        for index in range(per_writer):
            session.append_turn({"turn": index, "instruction": f"{tag}-{index}",
                                 "reply": None})

    threads = [threading.Thread(target=writer, args=(tag,))
               for tag in ("a", "b", "c", "d")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    records, skipped = read_records(session.turns_path)
    assert skipped == 0, "a line was torn"
    assert len(records) == writers * per_writer
    assert len({row["instruction"] for row in records}) == writers * per_writer


def test_a_torn_trailing_line_is_skipped_and_counted(tmp_path):
    session = HostSession(tmp_path, "abc").load()
    session.append_turn({"turn": 1, "instruction": "good", "reply": None})
    with session.turns_path.open("ab") as handle:
        handle.write(b'{"turn": 2, "instruction": "half')
    reloaded = HostSession(tmp_path, "abc").load()
    assert reloaded.turn_count == 1
    assert reloaded.turns_skipped == 1
    assert reloaded.public()["unreadableTurnLines"] == 1


def test_a_write_after_a_torn_line_does_not_glue_onto_the_wreck(tmp_path):
    session = HostSession(tmp_path, "abc").load()
    session.ensure_dir()
    with session.turns_path.open("ab") as handle:
        handle.write(b'{"turn": 1, "instruction": "half')
    session.append_turn({"turn": 2, "instruction": "whole", "reply": None})
    records, skipped = read_records(session.turns_path)
    assert skipped == 1
    assert [row["instruction"] for row in records] == ["whole"]


# --- the bounded window -----------------------------------------------------

def test_the_history_window_is_bounded_and_reports_what_it_dropped(tmp_path):
    session = HostSession(tmp_path, "abc", history_window=3).load()
    for index in range(7):
        session.append_turn({"turn": index + 1, "instruction": f"turn {index}",
                             "reply": f"reply {index}"})
    exchanges, truncation = session.conversation()
    assert [row["instruction"] for row in exchanges] == \
        ["turn 4", "turn 5", "turn 6"]
    assert truncation.public() == {"policy": DEFAULT_TRUNCATION_POLICY,
                                   "kept": 3, "dropped": 4}


def test_the_truncation_lands_in_the_turn_record_and_an_event(opened, tmp_path):
    root, session_id = opened
    seed = HostSession(root, session_id).load()
    for index in range(3):
        seed.append_turn({"turn": index + 1, "instruction": f"old {index}",
                          "reply": "ok"})
    # a NEW session object: attaching is what a fresh process does
    store = HostSession(root, session_id, history_window=1).load()
    assert store.attached is True
    door = mock_agent.open_door("protocol", root, None)
    try:
        payload = AgentHost(door, ah_mock.MockProvider(),
                            session=store).run("fill it", session_id)
    finally:
        door.close()
    assert payload["conversation"]["truncation"] == {
        "policy": DEFAULT_TRUNCATION_POLICY, "kept": 1, "dropped": 2}
    kinds = [event["kind"] for event in payload["events"]["events"]]
    assert "session.truncated" in kinds
    assert "session.attached" in kinds
    persisted = read_records(store.turns_path)[0][-1]
    assert persisted["truncation"]["dropped"] == 2


def test_a_zero_window_is_refused_rather_than_meaning_forget_everything(tmp_path):
    with pytest.raises(AgentHostError) as excinfo:
        HostSession(tmp_path, "abc", history_window=0)
    assert excinfo.value.code == "config_invalid"


# --- many turns, one process ------------------------------------------------

def test_a_second_turn_carries_the_first_one_back_to_the_provider(opened):
    root, session_id = opened
    store = HostSession(root, session_id).load()
    seen = []

    class Watcher(ah_mock.MockProvider):
        def complete(self, request):
            seen.append(tuple(request.conversation))
            return super().complete(request)

    door = mock_agent.open_door("protocol", root, None)
    try:
        host = AgentHost(door, Watcher(), session=store, stream_mode="off")
        host.run("first instruction", session_id)
        AgentHost(door, Watcher(), session=store,
                  stream_mode="off").run("second instruction", session_id)
    finally:
        door.close()
    # the first turn saw nothing before it; the second saw the first
    assert seen[0] == ()
    last = seen[-1]
    assert last[0]["instruction"] == "first instruction"
    assert last[0]["reply"] == ah_mock.CLOSING_TEXT["propose-one"]
    assert store.turn_count == 2


def test_the_turn_log_records_the_transport_and_no_document_text(opened):
    root, session_id = opened
    store = HostSession(root, session_id).load()
    door = mock_agent.open_door("protocol", root, None)
    try:
        AgentHost(door, ah_mock.MockProvider(),
                  session=store).run("fill it", session_id)
    finally:
        door.close()
    record = read_records(store.turns_path)[0][0]
    assert record["transports"] == ["stream"] * record["providerTurns"]
    assert record["opsHash"] and record["validationOk"] is True
    assert record["contextDisclosed"] is None
    # a turn record holds identities, never payloads
    assert "result" not in json.dumps(record)
    assert "regions" not in json.dumps(record)


# --- the long-lived host ----------------------------------------------------

class ServeClient:
    """A JSONL client for ``host.py --serve``. The Runtime's framing, reused."""

    def __init__(self, root, *extra):
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        argv = [sys.executable, str(HOST_CLI), "--root", str(root), "--serve",
                "--provider", "mock", *[str(item) for item in extra]]
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=env)
        self.events = []
        self._id = 0

    def read_frame(self):
        line = self.proc.stdout.readline()
        if not line:
            raise AssertionError("the host closed stdout: "
                                 + self.proc.stderr.read().decode("utf-8",
                                                                  "replace"))
        return json.loads(line.decode("utf-8"))

    def call(self, method, params=None):
        self._id += 1
        frame = {"kind": "request", "id": self._id, "method": method}
        if params is not None:
            frame["params"] = params
        self.proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        while True:
            got = self.read_frame()
            if got.get("kind") == "event":
                self.events.append(got["event"])
                continue
            if got.get("kind") == "notification":
                continue
            assert got.get("id") == self._id, got
            return got

    def ok(self, method, params=None):
        frame = self.call(method, params)
        assert frame["kind"] == "response", frame
        return frame["result"]

    def close(self, kill=False):
        try:
            if kill:
                self.proc.kill()
            else:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=SPAWN_TIMEOUT)
        except subprocess.TimeoutExpired:  # pragma: no cover - a hung host
            self.proc.kill()
            self.proc.wait(timeout=SPAWN_TIMEOUT)


def test_the_long_lived_host_announces_itself_then_serves_many_turns(opened):
    root, session_id = opened
    client = ServeClient(root)
    try:
        ready = client.read_frame()
        assert ready["kind"] == "notification"
        assert ready["method"] == "host/ready"
        assert ready["params"]["protocolVersion"] == SERVE_PROTOCOL_VERSION
        assert ready["params"]["sessionId"] == session_id
        assert ready["params"]["methods"] == list(SERVE_METHODS)

        first = client.ok("turn", {"instruction": "fill the first seat"})
        second = client.ok("turn", {"instruction": "and again"})
        state = client.ok("session/state")
        assert first["ok"] is True and second["ok"] is True
        assert state["turnsServedThisProcess"] == 2
        assert state["session"]["turns"] == 2
        # ONE process, two turns: the second remembered the first
        assert second["conversation"]["resent"] == 1
        assert client.ok("shutdown") == {"ok": True,
                                         "turnsServedThisProcess": 2}
    finally:
        client.close()


def test_stream_chunks_are_pushed_before_the_turn_responds(opened):
    root, _session_id = opened
    client = ServeClient(root)
    try:
        client.read_frame()
        client.ok("turn", {"instruction": "fill it"})
        kinds = [event["kind"] for event in client.events]
        assert kinds[0] == "run.started"
        assert "provider.stream.chunk" in kinds
        assert kinds[-1] == "run.finished"
    finally:
        client.close()


def test_a_killed_host_loses_the_process_and_not_the_conversation(opened):
    root, session_id = opened
    first = ServeClient(root)
    try:
        first.read_frame()
        first.ok("turn", {"instruction": "the turn before the crash"})
    finally:
        first.close(kill=True)
    assert first.proc.returncode != 0 or first.proc.returncode is None

    second = ServeClient(root)
    try:
        ready = second.read_frame()
        assert ready["params"]["session"]["attached"] is True
        assert ready["params"]["session"]["turns"] == 1
        result = second.ok("turn", {"instruction": "the turn after it"})
        assert result["conversation"]["resent"] == 1
        assert [event["kind"] for event in second.events].count(
            "session.attached") == 1
        state = second.ok("session/state")
        assert state["session"]["turns"] == 2
    finally:
        second.close()

    records, skipped = read_records(
        HostSession(root, session_id).turns_path)
    assert skipped == 0
    assert [row["instruction"] for row in records] == [
        "the turn before the crash", "the turn after it"]


def test_the_control_channel_grants_and_revokes_context(opened):
    """The operator's other channel. Same records, same durability."""
    root, session_id = opened
    client = ServeClient(root)
    try:
        client.read_frame()
        granted = client.ok("context/grant",
                            {"items": ["summary", "0:0,14"],
                             "readScope": "granted"})
        assert granted["grant"]["grantedBy"] == "operator:control-channel"
        assert [item["kind"] for item in granted["grant"]["items"]] == \
            ["summary", "region"]
        assert granted["recordedAt"].endswith("Z")

        turn = client.ok("turn", {"instruction": "read what I allowed"})
        assert turn["contextDisclosed"]["count"] == 2
        assert turn["grant"]["readScope"] == "granted"

        revoked = client.ok("context/revoke")
        assert revoked["grant"]["items"] == []
        after = client.ok("turn", {"instruction": "and now nothing"})
        assert after["contextDisclosed"] is None
    finally:
        client.close()

    records, skipped = read_records(
        HostSession(root, session_id).grants_path)
    assert skipped == 0
    assert [row["action"] for row in records] == ["grant", "revoke"]
    # the grant record names addresses; no document text is in the log
    assert records[0]["items"][1]["spec"] == "0:0,14"


def test_a_grant_on_the_serve_command_line_is_recorded_at_attach(opened):
    root, session_id = opened
    client = ServeClient(root, "--grant-region", "0:0,14",
                         "--read-scope", "granted")
    try:
        ready = client.read_frame()
        assert ready["params"]["grant"]["grantedBy"] == "operator:cli"
        assert ready["params"]["grant"]["readScope"] == "granted"
        turn = client.ok("turn", {"instruction": "read the granted seat"})
        assert turn["contextDisclosed"]["count"] == 1
    finally:
        client.close()
    records, _skipped = read_records(HostSession(root, session_id).grants_path)
    assert [row["grantedBy"] for row in records] == ["operator:cli"]


def test_a_grant_from_a_previous_process_is_still_in_force(opened):
    root, _session_id = opened
    first = ServeClient(root)
    try:
        first.read_frame()
        first.ok("context/grant", {"items": ["0:0,14"], "readScope": "granted"})
    finally:
        first.close(kill=True)

    second = ServeClient(root)
    try:
        ready = second.read_frame()
        assert ready["params"]["grant"]["readScope"] == "granted"
        assert ready["params"]["grant"]["items"][0]["spec"] == "0:0,14"
        assert ready["params"]["grant"]["grantedBy"] == "operator:control-channel"
    finally:
        second.close()


def test_the_serve_channel_refuses_what_it_does_not_offer(opened):
    root, _session_id = opened
    client = ServeClient(root)
    try:
        client.read_frame()
        unknown = client.call("plan/apply", {})
        assert unknown["kind"] == "error"
        assert unknown["error"]["code"] == "tool_unknown"

        empty = client.call("turn", {"instruction": "   "})
        assert empty["error"]["code"] == "config_invalid"

        client.proc.stdin.write(b'{"kind":"request","id":9,"method":"turn",'
                                b'"extra":1}\n')
        client.proc.stdin.flush()
        bad = client.read_frame()
        assert bad["error"]["code"] == "config_invalid"
        assert bad["error"]["data"]["unknown"] == ["extra"]
    finally:
        client.close()


def test_a_replayed_request_id_is_refused(opened):
    root, _session_id = opened
    client = ServeClient(root)
    try:
        client.read_frame()
        for _ in range(2):
            client.proc.stdin.write(
                b'{"kind":"request","id":1,"method":"session/state"}\n')
        client.proc.stdin.flush()
        first = client.read_frame()
        second = client.read_frame()
        assert first["kind"] == "response"
        assert second["kind"] == "error"
        assert second["error"]["code"] == "config_invalid"
    finally:
        client.close()


def test_one_shot_memory_mode_writes_the_same_log(opened):
    """``--memory`` without ``--serve``: still one conversation, still durable."""
    root, session_id = opened
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    for instruction in ("first", "second"):
        done = subprocess.run(
            [sys.executable, str(HOST_CLI), "--root", str(root),
             "--provider", "mock", "--memory", "--instruction", instruction],
            capture_output=True, env=env, timeout=SPAWN_TIMEOUT)
        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
        payload = json.loads(done.stdout.decode("utf-8"))
    assert payload["session"]["turns"] == 2
    assert payload["conversation"]["resent"] == 1
    records, _skipped = read_records(HostSession(root, session_id).turns_path)
    assert [row["instruction"] for row in records] == ["first", "second"]


def test_without_memory_nothing_is_written(opened):
    root, session_id = opened
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run(
        [sys.executable, str(HOST_CLI), "--root", str(root),
         "--provider", "mock"],
        capture_output=True, env=env, timeout=SPAWN_TIMEOUT)
    assert done.returncode == 0
    payload = json.loads(done.stdout.decode("utf-8"))
    assert "session" not in payload
    assert not HostSession(root, session_id).dir.exists()
