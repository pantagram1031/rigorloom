# -*- coding: utf-8 -*-
"""Transport class: framing, strict JSON, lifecycle, stable codes.

Every assertion here is about the wire, not about documents — the cheap tests
that must stay fast enough that nobody skips them.
"""
from __future__ import annotations

import json

import pytest

from _runtime_client import RuntimeClient, runtime_scripts_on_path

runtime_scripts_on_path()

import rt_codes  # noqa: E402
import rt_jsonl  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    with RuntimeClient(tmp_path / "root") as handle:
        yield handle


# --- the closed vocabulary --------------------------------------------------

def test_error_codes_are_one_closed_set_with_no_overlap():
    assert rt_codes.TRANSPORT_CODES & rt_codes.DOMAIN_CODES == frozenset()
    assert rt_codes.ERROR_CODES == (rt_codes.TRANSPORT_CODES
                                    | rt_codes.DOMAIN_CODES)


def test_an_undeclared_code_cannot_be_constructed():
    with pytest.raises(AssertionError):
        rt_codes.RpcError("totally_made_up", "nope")


def test_the_receipt_codes_are_not_reused_for_frames():
    """docs/runtime-protocol-v0.md §5.1 said they would be; they must not be."""
    assert "receipt_duplicate_key" not in rt_codes.ERROR_CODES
    assert "receipt_nonfinite_value" not in rt_codes.ERROR_CODES
    assert "duplicate_key" in rt_codes.TRANSPORT_CODES
    assert "nonfinite_number" in rt_codes.TRANSPORT_CODES


# --- strict JSON ------------------------------------------------------------

def test_duplicate_keys_are_refused_recursively():
    with pytest.raises(rt_jsonl.StrictJsonError) as excinfo:
        rt_jsonl.loads_strict('{"a": {"b": 1, "b": 2}}')
    assert excinfo.value.code == "duplicate_key"


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_constants_are_refused(literal):
    with pytest.raises(rt_jsonl.StrictJsonError) as excinfo:
        rt_jsonl.loads_strict('{"v": %s}' % literal)
    assert excinfo.value.code == "nonfinite_number"


def test_an_overflowing_float_literal_is_refused_too():
    with pytest.raises(rt_jsonl.StrictJsonError) as excinfo:
        rt_jsonl.loads_strict('{"v": 1e400}')
    assert excinfo.value.code == "nonfinite_number"


def test_canonical_bytes_are_order_independent_and_omit_the_self_hash():
    left = rt_jsonl.canonical_bytes({"b": 1, "a": 2, "h": "x"}, omit=("h",))
    right = rt_jsonl.canonical_bytes({"a": 2, "h": "y", "b": 1}, omit=("h",))
    assert left == right == b'{"a":2,"b":1}'


# --- lifecycle --------------------------------------------------------------

def test_an_ordinary_call_before_initialize_is_refused(client):
    error = client.err("session/list", {})
    assert error["code"] == "not_initialized"
    # and the connection survives
    assert client.initialize()["kind"] == "response"


def test_version_negotiation_is_exact_match(client):
    frame = client.initialize(version="1")
    assert frame["kind"] == "error"
    assert frame["error"]["code"] == "protocol_version_unsupported"
    assert frame["error"]["data"]["supported"] == ["0"]
    # a refused handshake does not initialize the connection
    assert client.err("session/list", {})["code"] == "not_initialized"
    assert client.initialize(version="0")["kind"] == "response"


def test_initialize_twice_is_refused(client):
    client.initialize()
    assert client.err("initialize", {"protocolVersion": "0"})["code"] == \
        "already_initialized"


def test_eof_shuts_down_cleanly(client):
    client.initialize()
    client.close_stdin()
    assert client.wait() == 0


# --- framing ----------------------------------------------------------------

def test_malformed_json_is_refused_and_the_connection_survives(client):
    client.initialize()
    client.write_raw(b"{not json at all\n")
    frame = client.recv()
    assert frame["kind"] == "error" and frame["error"]["code"] == "frame_malformed"
    assert client.ok("session/list", {}) == {"sessions": []}


def test_a_frame_that_is_not_an_object_is_refused(client):
    client.initialize()
    client.write_raw(b"[1,2,3]\n")
    assert client.recv()["error"]["code"] == "frame_malformed"


def test_duplicate_keys_in_a_frame_are_refused_on_the_wire(client):
    client.initialize()
    client.write_raw(b'{"kind":"request","id":"d1","method":"session/list",'
                     b'"method":"initialize"}\n')
    assert client.recv()["error"]["code"] == "duplicate_key"


def test_nonfinite_numbers_in_a_frame_are_refused_on_the_wire(client):
    client.initialize()
    client.write_raw(b'{"kind":"request","id":"n1","method":"session/list",'
                     b'"params":{"x":NaN}}\n')
    assert client.recv()["error"]["code"] == "nonfinite_number"


def test_an_oversized_frame_is_refused_and_the_next_frame_still_parses(client):
    client.initialize()
    blob = "x" * (rt_codes.MAX_FRAME_BYTES + 4096)
    client.write_raw((json.dumps({"kind": "request", "id": "big",
                                  "method": "session/list",
                                  "params": {"pad": blob}}) + "\n").encode("utf-8"))
    frame = client.recv()
    assert frame["error"]["code"] == "frame_too_large"
    assert frame["error"]["data"]["limit"] == rt_codes.MAX_FRAME_BYTES
    # the drain left the stream on a frame boundary
    assert client.ok("session/list", {}) == {"sessions": []}


def test_the_oversize_refusal_never_parses_the_frame(tmp_path):
    """A cap that parses first is not a cap. Proven at the reader, not the server."""
    import io

    payload = b'{"kind":"request","id":"x","method":"boom","pad":"' + b"y" * 4096 + b'"}\n'
    stream = io.BytesIO(payload + b'{"kind":"request","id":"y"}\n')
    kind, raw = rt_jsonl.read_raw_frame(stream, max_bytes=512)
    assert (kind, raw) == (rt_jsonl.READ_OVERSIZE, None)
    kind, raw = rt_jsonl.read_raw_frame(stream, max_bytes=512)
    assert kind == rt_jsonl.READ_LINE
    assert json.loads(raw)["id"] == "y"


# --- request shape ----------------------------------------------------------

def test_unknown_top_level_frame_members_are_refused(client):
    client.initialize()
    client.send_frame({"kind": "request", "id": "u1", "method": "session/list",
                       "authority": "host"})
    frame = client.recv()
    assert frame["error"]["code"] == "unknown_field"
    assert frame["error"]["data"]["unknown"] == ["authority"]


def test_unknown_params_fields_are_refused_under_the_default_policy(client):
    client.initialize()
    error = client.err("session/list", {"nope": 1})
    assert error["code"] == "unknown_field"
    assert error["data"]["unknown"] == ["nope"]


def test_the_ignore_policy_drops_unknown_params_fields(client):
    client.initialize(policy="ignore")
    assert client.ok("session/list", {"nope": 1}) == {"sessions": []}


def test_the_unknown_field_policy_is_itself_validated(client):
    frame = client.call("initialize", {"protocolVersion": "0",
                                       "unknownFieldPolicy": "whatever"})
    assert frame["error"]["code"] == "invalid_params"


def test_unknown_method_names_the_registry_and_the_host_table(client):
    client.initialize()
    error = client.err("does/notExist", {})
    assert error["code"] == "unknown_method"
    assert error["data"]["knownOnHostEntry"] is False
    assert "session/list" in error["data"]["known"]


def test_a_reused_request_id_is_refused(client):
    client.initialize()
    client.ok("session/list", {}, request_id="same")
    error = client.err("session/list", {}, request_id="same")
    assert error["code"] == "duplicate_request_id"


def test_a_non_request_frame_kind_is_refused(client):
    client.initialize()
    client.send_frame({"kind": "response", "id": "z", "method": "session/list"})
    assert client.recv()["error"]["code"] in ("frame_malformed", "unknown_field")


# --- stdout purity ----------------------------------------------------------

def test_stdout_carries_only_frames_while_children_print(client, tmp_path):
    """form_inspect prints a summary line of its own; it must not reach stdout.

    ``engine/scripts/form_inspect.py:1586`` prints ``wrote <path>: anchors=...``
    whenever ``--out`` is given. If the Runtime inherited its child's stdout
    that line would land between two frames and corrupt the stream.
    """
    from _runtime_client import CORPUS_FORM

    client.initialize()
    session = client.ok("workspace/openPath", {"path": str(CORPUS_FORM)})["sessionId"]
    client.ok("document/inspect", {"sessionId": session, "include": ["summary"]})
    result = client.ok("session/list", {})
    assert result["sessions"][0]["sessionId"] == session
    lines = client.stdout_lines()
    assert len(lines) == 4
    for line in lines:
        assert b"wrote " not in line, "a child's stdout leaked into the frame stream"
        parsed = json.loads(line.decode("utf-8"))
        assert parsed["kind"] in ("response", "error", "notification")


def test_every_runtime_script_byte_compiles():
    """``scripts/py_compile_sweep.py`` PATTERNS does not cover ``runtime/``.

    That file belongs to another surface, so the sweep's one-line addition is
    somebody else's commit. Until then the property is pinned here rather than
    left unchecked.
    """
    import py_compile

    from _runtime_client import RUNTIME_SCRIPTS

    targets = sorted(RUNTIME_SCRIPTS.glob("*.py"))
    assert len(targets) >= 6, targets
    for path in targets:
        py_compile.compile(str(path), doraise=True, quiet=1)


def test_diagnostics_go_to_stderr(client):
    client.initialize()
    assert "runtime ready" in client.stderr_text()
    for line in client.stdout_lines():
        assert b"runtime ready" not in line
