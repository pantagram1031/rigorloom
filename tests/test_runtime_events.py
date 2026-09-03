# -*- coding: utf-8 -*-
"""The session event log, event/poll, and event/subscribe.

Three properties, and the third is the one a timeline actually needs: ordered,
gap-free, and replayable from a cursor — including while somebody else is
appending.
"""
from __future__ import annotations

import json
import shutil
import threading
import time

import pytest

from _runtime_client import CORPUS_FORM, RuntimeClient, run_cli, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_codes  # noqa: E402
import rt_session  # noqa: E402
from rt_core import RuntimeCore  # noqa: E402

CLEAN_OP = {"kind": "fill_cell", "table": 0, "row": 5, "col": 1, "text": "값"}


def _source(tmp_path, name="form.hwpx"):
    target = tmp_path / name
    shutil.copyfile(CORPUS_FORM, target)
    return target


@pytest.fixture()
def core(tmp_path):
    return RuntimeCore(tmp_path / "root")


@pytest.fixture()
def session(core, tmp_path):
    return core.open_path(str(_source(tmp_path)))["sessionId"]


def _drive(core, session_id):
    """Produce one event of every mutation kind except the applied pair."""
    plan = core.plan_propose(session_id, "preedit", [CLEAN_OP], "test")["plan"]
    core.plan_validate(plan["planId"])
    approval = core.approval_request(plan["planId"], "test")["approval"]
    core.approval_resolve(approval["approvalId"], plan["planId"],
                          plan["planHash"], "approved", "operator")
    return plan, approval


# --- the log ----------------------------------------------------------------

def test_opening_a_document_is_the_first_event(core, session):
    events, next_seq = rt_session.read_events(core.store.get(session))
    assert [event["kind"] for event in events] == ["session.opened"]
    assert events[0]["seq"] == 0 and next_seq == 1
    assert events[0]["detail"]["documentKind"] == "hwpx"


def test_every_mutation_appends_exactly_one_event(core, session):
    _drive(core, session)
    events, _ = rt_session.read_events(core.store.get(session))
    assert [event["kind"] for event in events] == [
        "session.opened", "plan.proposed", "plan.validated",
        "approval.requested", "approval.resolved"]
    assert [event["seq"] for event in events] == [0, 1, 2, 3, 4]
    for event in events:
        assert set(event) <= {"seq", "at", "kind", "sessionId", "detail"}
        assert event["sessionId"] == session


def test_applying_records_the_plan_and_the_candidate(core, session):
    plan, approval = _drive(core, session)
    result = core.plan_apply(plan["planId"], approval["approvalId"])
    events, _ = rt_session.read_events(core.store.get(session))
    kinds = [event["kind"] for event in events]
    assert kinds[-2:] == ["plan.applied", "candidate.published"]
    published = events[-1]["detail"]
    assert published["runId"] == result["candidate"]["runId"]
    assert published["sha256"] == result["candidate"]["candidate"]["sha256"]
    assert published["ranAll"] is True


def test_the_reader_assigns_the_sequence_so_the_file_holds_none(core, session):
    lines = core.store.get(session).events_path.read_text(
        encoding="utf-8").strip().splitlines()
    for line in lines:
        assert "seq" not in json.loads(line)


def test_an_undeclared_event_kind_is_refused(core, session):
    with pytest.raises(ValueError):
        rt_session.append_event(core.store.get(session), "something.invented")


def test_a_torn_trailing_line_is_skipped_without_shifting_anybody(core, session):
    handle = core.store.get(session)
    with handle.events_path.open("ab") as stream:
        stream.write(b'{"kind": "plan.pro')  # a half-written line
    events, next_seq = rt_session.read_events(handle)
    assert [event["kind"] for event in events] == ["session.opened"]
    assert events[0]["seq"] == 0
    rt_session.append_event(handle, "plan.proposed", planId="p")
    events, _ = rt_session.read_events(handle)
    # the torn line still occupies index 1, so the new event is 2 — indexes are
    # never reused, which is what makes a cursor safe
    assert [event["seq"] for event in events] == [0, 2]


def test_a_note_that_cannot_be_written_never_undoes_the_deed(core, session,
                                                             monkeypatch):
    handle = core.store.get(session)

    def explode(*args, **kwargs):
        raise OSError("disk went away")

    monkeypatch.setattr(type(handle.events_path), "open", explode, raising=False)
    rt_session.append_event(handle, "plan.proposed", planId="p")  # must not raise


# --- event/poll -------------------------------------------------------------

def test_poll_replays_from_a_cursor(core, session):
    _drive(core, session)
    first = core.event_poll(session, after=-1)
    assert [event["kind"] for event in first["events"]][0] == "session.opened"
    assert first["nextSeq"] == 5 and first["more"] is False
    later = core.event_poll(session, after=2)
    assert [event["seq"] for event in later["events"]] == [3, 4]


def test_poll_is_bounded_and_says_when_there_is_more(core, session):
    _drive(core, session)
    page = core.event_poll(session, after=-1, limit=2)
    assert [event["seq"] for event in page["events"]] == [0, 1]
    assert page["more"] is True and page["nextSeq"] == 2
    rest = core.event_poll(session, after=page["nextSeq"] - 1, limit=2)
    assert [event["seq"] for event in rest["events"]] == [2, 3]


def test_poll_rejects_a_silly_limit(core, session):
    for bad in (0, -1, 10_000):
        with pytest.raises(rt_codes.RpcError) as excinfo:
            core.event_poll(session, limit=bad)
        assert excinfo.value.code == "invalid_params"


def test_poll_is_reachable_over_the_wire_and_as_an_mcp_tool(tmp_path):
    import mcp_server

    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    with RuntimeClient(root) as client:
        client.initialize()
        result = client.ok("event/poll", {"sessionId": session})
    assert [event["kind"] for event in result["events"]] == ["session.opened"]
    assert "event_poll" in mcp_server.TOOL_TO_METHOD


# --- event/subscribe --------------------------------------------------------

def _collect(client, wanted: int, timeout: float = 90.0) -> list[dict]:
    """Read event notifications until ``wanted`` have arrived.

    Drains whatever the client already buffered while it was waiting on a
    response first — a subscription pushes frames between requests, which is
    the whole point.
    """
    events: list[dict] = []
    buffered, client.notifications = client.notifications, []
    for frame in buffered:
        if frame.get("method") == "event":
            events.append(frame["params"]["event"])
    deadline = time.monotonic() + timeout
    while len(events) < wanted and time.monotonic() < deadline:
        frame = client.recv(timeout=max(1.0, deadline - time.monotonic()))
        if frame.get("kind") == "notification" and frame.get("method") == "event":
            events.append(frame["params"]["event"])
    return events


def test_subscribe_replays_everything_after_the_response(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    core = RuntimeCore(root)
    _drive(core, session)

    with RuntimeClient(root) as client:
        client.initialize()
        result = client.ok("event/subscribe", {"sessionId": session,
                                               "intervalMs": 50})
        assert result["subscriptionId"]
        events = _collect(client, 5)
    assert [event["seq"] for event in events] == [0, 1, 2, 3, 4]
    assert [event["kind"] for event in events][:2] == ["session.opened",
                                                       "plan.proposed"]


def test_the_response_arrives_before_any_event_on_it(tmp_path):
    """A client must know its subscription id before the first event."""
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    with RuntimeClient(root) as client:
        client.initialize()
        client.send_frame({"kind": "request", "id": "sub", "method": "event/subscribe",
                           "params": {"sessionId": session, "intervalMs": 50}})
        first = client.recv()
        assert first["kind"] == "response" and first["id"] == "sub"
        events = _collect(client, 1)
    assert events[0]["seq"] == 0


def test_a_cursor_skips_what_the_client_already_has(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    _drive(RuntimeCore(root), session)
    with RuntimeClient(root) as client:
        client.initialize()
        client.ok("event/subscribe", {"sessionId": session, "after": 2,
                                      "intervalMs": 50})
        events = _collect(client, 2)
    assert [event["seq"] for event in events] == [3, 4]


def test_events_appended_after_subscribe_arrive_ordered_and_gap_free(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    core = RuntimeCore(root)
    with RuntimeClient(root) as client:
        client.initialize()
        client.ok("event/subscribe", {"sessionId": session, "intervalMs": 50})
        _collect(client, 1)  # the replay of session.opened
        _drive(core, session)
        events = _collect(client, 4)
    assert [event["seq"] for event in events] == [1, 2, 3, 4]
    assert [event["kind"] for event in events] == [
        "plan.proposed", "plan.validated", "approval.requested",
        "approval.resolved"]


def test_concurrent_appends_are_delivered_once_each_in_order(tmp_path):
    """Two writers, one subscriber: every index exactly once, ascending."""
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    core = RuntimeCore(root)
    handle = core.store.get(session)
    total = 60

    def writer(tag):
        for index in range(total // 2):
            rt_session.append_event(handle, "plan.proposed",
                                    planId=f"{tag}-{index}")

    with RuntimeClient(root) as client:
        client.initialize()
        client.ok("event/subscribe", {"sessionId": session, "intervalMs": 50})
        threads = [threading.Thread(target=writer, args=(tag,))
                   for tag in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        events = _collect(client, total + 1)

    seqs = [event["seq"] for event in events]
    assert seqs == sorted(seqs), "events arrived out of order"
    assert len(seqs) == len(set(seqs)), "an event was delivered twice"
    assert seqs == list(range(len(seqs))), "there is a gap in the sequence"
    assert len(seqs) == total + 1
    planned = [event for event in events if event["kind"] == "plan.proposed"]
    assert len({event["detail"]["planId"] for event in planned}) == total


def test_unsubscribe_stops_the_stream_and_reports_the_cursor(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    with RuntimeClient(root) as client:
        client.initialize()
        subscription = client.ok("event/subscribe",
                                 {"sessionId": session, "intervalMs": 50})
        _collect(client, 1)
        stopped = client.ok("event/unsubscribe",
                            {"subscriptionId": subscription["subscriptionId"]})
        assert stopped["stopped"] is True
        assert stopped["deliveredThrough"] == 0
        error = client.err("event/unsubscribe",
                           {"subscriptionId": subscription["subscriptionId"]})
    assert error["code"] == "unknown_subscription"


def test_a_busy_loop_is_not_a_subscription(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    with RuntimeClient(root) as client:
        client.initialize()
        for bad in (0, 5, 60_000):
            error = client.err("event/subscribe",
                               {"sessionId": session, "intervalMs": bad})
            assert error["code"] == "invalid_params"
            assert error["data"]["min"] == rt_codes.MIN_EVENT_POLL_MS


def test_subscriptions_are_capped(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    with RuntimeClient(root) as client:
        client.initialize()
        for _ in range(rt_codes.MAX_SUBSCRIPTIONS):
            client.ok("event/subscribe", {"sessionId": session,
                                          "intervalMs": 5000})
        error = client.err("event/subscribe", {"sessionId": session,
                                               "intervalMs": 5000})
    assert error["code"] == "subscription_limit"


def test_subscribe_is_on_both_entries_and_absent_from_mcp(tmp_path):
    import mcp_server
    import rt_core

    for entry in ("host", "agent"):
        with RuntimeClient(tmp_path / f"root-{entry}", entry=entry) as client:
            methods = client.initialize()["result"]["capabilities"]["methods"]
            assert "event/subscribe" in methods
            assert "event/unsubscribe" in methods
    for name in rt_core.PROTOCOL_ONLY_METHODS:
        assert mcp_server.tool_name(name) not in mcp_server.TOOL_TO_METHOD


def test_an_unknown_session_cannot_be_subscribed_to(tmp_path):
    with RuntimeClient(tmp_path / "root") as client:
        client.initialize()
        error = client.err("event/subscribe", {"sessionId": "nope"})
    assert error["code"] == "unknown_session"


def test_eof_stops_the_poller(tmp_path):
    root = tmp_path / "root"
    session = run_cli(root, "open", "--path", str(_source(tmp_path))).result["sessionId"]
    client = RuntimeClient(root)
    client.initialize()
    client.ok("event/subscribe", {"sessionId": session, "intervalMs": 50})
    _collect(client, 1)
    client.close_stdin()
    assert client.wait() == 0
    client.close()
