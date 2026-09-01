#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The official Anthropic Messages API, over the same provider contract.

WHY RAW HTTP AND NOT THE SDK. The bundled ``claude-api`` skill's rule is that
the official SDK is the default and raw HTTP is correct only where the project
cannot take the dependency. ``agenthost/`` is stdlib-only by construction — the
whole program keeps a core install dependency-free — so this adapter is
``urllib`` against the documented wire shapes, exactly like ``ah_router``.

WIRE SHAPES ARE VERIFIED, NOT REMEMBERED. Everything marked (v) below was read
offline from the bundled skill at
``claude-api/curl/examples.md``, ``claude-api/shared/error-codes.md``,
``claude-api/shared/tool-use-concepts.md``, ``claude-api/shared/models.md`` and
``claude-api/typescript/claude-api/streaming.md``. Anything this adapter needed
that those files did NOT pin is marked (a) for assumption, here and in
``agenthost/README.md``, rather than being guessed silently:

  (v) POST /v1/messages; headers x-api-key, anthropic-version: 2023-06-01
  (v) required max_tokens; system as content blocks; messages; tools[].input_schema
  (v) response .content[] blocks, .stop_reason, .usage, .model
  (v) tool_use block {type,id,name,input}; tool_result continuation in a USER
      message carrying {type:"tool_result", tool_use_id, content}
  (v) every tool_result for one assistant turn goes in ONE user message
  (v) tool_choice: auto | any | tool+name | none, + disable_parallel_tool_use
  (v) SSE events message_start, content_block_start, content_block_delta,
      content_block_stop, message_delta, message_stop; delta types text_delta
      and input_json_delta
  (v) error envelope {"type":"error","error":{"type","message"},"request_id"}
      and the status -> type map; retry-after on 429
  (v) GET /v1/models/{id} -> id, display_name, max_input_tokens, max_tokens,
      capabilities
  (a) the LIST envelope of GET /v1/models (assumed ``{"data":[...]}``, tolerated
      as a bare list too)
  (a) the field carrying streamed tool input on an input_json_delta (assumed
      ``partial_json``)
  (a) the content_block_start payload for a tool_use block (assumed
      ``{"type":"tool_use","id","name","input":{}}``)
  (a) SSE ``ping`` and ``error`` event names

NOT SENT, DELIBERATELY. ``temperature``/``top_p``/``top_k`` are removed on
current models and return 400 (v); assistant prefill is removed (v). This
adapter sends none of them, so it cannot inherit that class of failure.

THE LIVE LEG IS NOT RUN. Every test here talks to a local fake. ``--live-smoke``
is implemented and its keyless refusal is tested; one real request against
``api.anthropic.com`` remains owed and is stated as owed in the capability
payload and the README.
"""
from __future__ import annotations

import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import AgentHostError, ProviderError  # noqa: E402
from ah_events import redact_headers  # noqa: E402
from ah_provider import (  # noqa: E402
    CapabilityProfile,
    ProviderAdapter,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
    cap,
)
from ah_router import CredentialRef, _reject_secret_shaped  # noqa: E402

RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

from rt_jsonl import StrictJsonError, loads_strict  # noqa: E402

PROVIDER_ID = "anthropic"
DEFAULT_BASE_URL = "https://api.anthropic.com"
#: (v) claude-api skill: use this unless the operator names another model.
DEFAULT_MODEL = "claude-opus-5"
#: (v) The long-standing API version header value.
ANTHROPIC_VERSION = "2023-06-01"
#: (v) skill guidance: ~16000 non-streaming keeps responses under HTTP
#: timeouts; ~64000 for streaming, where timeouts are not the concern.
DEFAULT_MAX_TOKENS = 16000
DEFAULT_STREAM_MAX_TOKENS = 64000
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
#: A tiny probe for --live-smoke. Small enough to cost nothing worth counting.
SMOKE_MAX_TOKENS = 16

#: (v) error-codes.md. 429 and every 5xx (500 api_error, 529 overloaded_error)
#: are retryable; no other 4xx ever is.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504, 529})
#: One retry. A second is a queue, and a queue in a turn loop is a hang.
MAX_ATTEMPTS = 2
DEFAULT_BACKOFF_SECONDS = 1.0
#: A Retry-After longer than this is honoured by REFUSING, not by sleeping: a
#: turn loop that naps for five minutes looks identical to a hang.
MAX_RETRY_AFTER_SECONDS = 30.0

CONFIG_KEYS = frozenset({
    "providerId", "baseUrl", "model", "credential", "capabilities",
    "maxTokens", "timeoutSeconds", "maxResponseBytes", "anthropicVersion",
    "extraHeaders", "notes",
})

#: (v) status -> error type, from error-codes.md. Used to name a fault
#: precisely instead of reporting every non-2xx as "http error".
STATUS_ERROR_TYPES = {
    400: "invalid_request_error", 401: "authentication_error",
    403: "permission_error", 404: "not_found_error",
    413: "request_too_large", 429: "rate_limit_error",
    500: "api_error", 529: "overloaded_error",
}


# --- SSE ---------------------------------------------------------------------

class SseDecoder:
    """Incremental server-sent-event decoder. Chunk boundaries are not events.

    An HTTP body arrives in whatever pieces the socket felt like producing, and
    a naive ``for line in response`` reader is fine until one lands mid-frame.
    This buffers and only yields complete events, so a stream split at an
    arbitrary byte behaves exactly like one that is not.
    """

    def __init__(self):
        self._buffer = ""

    def feed(self, chunk: bytes | str) -> list[tuple[str | None, str]]:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8", errors="replace")
        self._buffer += chunk
        events: list[tuple[str | None, str]] = []
        while True:
            # (v) SSE frames are separated by a blank line.
            for separator in ("\r\n\r\n", "\n\n"):
                index = self._buffer.find(separator)
                if index != -1:
                    frame, self._buffer = (self._buffer[:index],
                                           self._buffer[index + len(separator):])
                    break
            else:
                return events
            parsed = self._parse_frame(frame)
            if parsed is not None:
                events.append(parsed)

    @staticmethod
    def _parse_frame(frame: str) -> tuple[str | None, str] | None:
        name = None
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith(":"):  # a comment/keepalive
                continue
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines and name is None:
            return None
        return name, "\n".join(data_lines)

    def pending(self) -> str:
        return self._buffer


# --- the adapter -------------------------------------------------------------

class AnthropicAdapter(ProviderAdapter):
    """Anthropic Messages API. Credential by reference, faults isolated."""

    def __init__(self, config: dict | None = None, environ: dict | None = None,
                 opener=None):
        import os

        config = dict(config or {})
        # Secret-shaped FIRST, as in ah_router: "you pasted a key here" is the
        # more useful of the two things to be told.
        _reject_secret_shaped(config)
        unknown = sorted(set(config) - CONFIG_KEYS)
        if unknown:
            raise AgentHostError("config_invalid",
                                 "anthropic config carries unknown members",
                                 unknown=unknown, allowed=sorted(CONFIG_KEYS))
        self.provider_id = config.get("providerId") or PROVIDER_ID
        base = config.get("baseUrl") or DEFAULT_BASE_URL
        if not isinstance(base, str) or not base.startswith(("http://", "https://")):
            raise AgentHostError("config_invalid",
                                 "baseUrl must be an http or https URL",
                                 offered=base)
        self.base_url = base.rstrip("/")
        self.model = config.get("model") or DEFAULT_MODEL
        if not isinstance(self.model, str) or not self.model:
            raise AgentHostError("config_invalid", "model must be a non-empty string")
        # Default credential: the environment variable the SDKs read. Still a
        # REFERENCE — the name, never the value.
        self.credential = CredentialRef(config.get("credential") or {
            "source": "env", "key": "ANTHROPIC_API_KEY",
            "header": "x-api-key", "scheme": "raw"})
        self.overrides = config.get("capabilities") or {}
        self.max_tokens = int(config.get("maxTokens") or DEFAULT_MAX_TOKENS)
        if self.max_tokens < 1:
            raise AgentHostError("config_invalid", "maxTokens must be positive",
                                 offered=self.max_tokens)
        self.timeout = float(config.get("timeoutSeconds") or DEFAULT_TIMEOUT)
        self.max_bytes = int(config.get("maxResponseBytes")
                             or DEFAULT_MAX_RESPONSE_BYTES)
        self.anthropic_version = config.get("anthropicVersion") or ANTHROPIC_VERSION
        self.extra_headers = dict(config.get("extraHeaders") or {})
        _reject_secret_shaped(self.extra_headers, "extraHeaders")
        self.notes = dict(config.get("notes") or {})
        self._environ = environ if environ is not None else os.environ
        self._opener = opener or urllib.request.urlopen
        self._sleep = time.sleep

    # -- contract ------------------------------------------------------------
    def credential_state(self) -> dict:
        """Configured or missing — decided WITHOUT reading the value."""
        reference = self.credential.public()
        if self.credential.source == "none":
            return {"state": "not_required", **reference}
        if self.credential.source == "env":
            present = bool((self._environ.get(self.credential.key) or "").strip())
            return {"state": "configured" if present else "missing", **reference}
        return {"state": "unsupported",
                "reason": "OS credential-store lookup is not implemented",
                **reference}

    def capabilities(self) -> CapabilityProfile:
        base = CapabilityProfile(
            provider_id=self.provider_id,
            model=self.model,
            auth_ownership=self.credential.auth_ownership,
            capabilities={
                "modelDiscovery": cap(
                    "yes", "GET /v1/models; needs a configured credential to "
                           "actually answer"),
                "text": cap("yes", "POST /v1/messages"),
                "structuredToolUse": cap(
                    "yes", "tools[].input_schema + tool_use / tool_result blocks"),
                "structuredOutput": cap(
                    "unknown",
                    "the API offers output_config.format; this adapter does not "
                    "send it, so nothing is promised"),
                "streaming": cap("yes", "SSE over POST /v1/messages stream:true"),
                "resumableThread": cap(
                    "no", "the Messages API is stateless; the host resends the "
                          "whole history each turn, as with the router"),
                "vision": cap(
                    "unknown",
                    "the API accepts image blocks; this adapter sends none. "
                    "Document images are a later slice, so this is not-yet, "
                    "not no"),
            },
            notes={
                "baseUrl": self.base_url,
                "anthropicVersion": self.anthropic_version,
                "credentialRef": self.credential.public(),
                "credential": self.credential_state(),
                "maxTokens": self.max_tokens,
                "liveSmoke": ("implemented behind --live-smoke; never run in "
                              "the test suite, which talks only to a local fake"),
                "notSent": ["temperature", "top_p", "top_k", "assistant prefill"],
                **self.notes,
            },
        )
        return base.with_overrides(self.overrides)

    # -- payloads ------------------------------------------------------------
    def build_body(self, request: ProviderRequest, *, stream: bool) -> dict:
        """Provider-neutral request -> the Messages API shape. (v)"""
        content: list[dict] = [{
            "type": "text",
            "text": json.dumps({"instruction": request.instruction,
                                "context": request.context},
                               ensure_ascii=False, sort_keys=True),
        }]
        messages: list[dict] = [{"role": "user", "content": content}]
        for entry in request.history:
            call_id = entry.get("callId") or f"toolu_{entry.get('tool')}"
            # (v) The assistant's tool_use turn is echoed back, then the results
            # come in a USER message. Every result for one assistant turn goes
            # in ONE user message; splitting them teaches the model to stop
            # asking for parallel calls.
            messages.append({"role": "assistant", "content": [{
                "type": "tool_use", "id": call_id,
                "name": entry.get("tool"),
                "input": entry.get("arguments") or {},
            }]})
            messages.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": json.dumps(
                    entry.get("result") if entry.get("ok")
                    else entry.get("error"),
                    ensure_ascii=False, sort_keys=True),
                # (v) a failed tool comes back as a result with is_error, never
                # as a dropped block
                **({} if entry.get("ok") else {"is_error": True}),
            }]})

        body: dict = {
            "model": self.model,
            # (v) required on every request
            "max_tokens": (DEFAULT_STREAM_MAX_TOKENS if stream
                           else self.max_tokens),
            # (v) system as content blocks
            "system": [{"type": "text", "text":
                        "You may inspect a document and propose an edit plan. "
                        "You cannot approve or apply anything; a host does that."}],
            "messages": messages,
        }
        if request.tools:
            body["tools"] = [{"name": tool["name"],
                              "description": tool["description"],
                              "input_schema": tool["inputSchema"]}
                             for tool in request.tools]
            body["tool_choice"] = {"type": "auto"}  # (v)
        if stream:
            body["stream"] = True
        return body

    def parse_message(self, payload) -> ProviderResponse:
        """A Messages response -> the provider-neutral shape. (v)"""
        if not isinstance(payload, dict):
            raise ProviderError("provider_malformed_response",
                                "the completion body was not an object",
                                provider=self.provider_id)
        if payload.get("type") == "error":
            raise self._error_from_body(payload, status=None)
        blocks = payload.get("content")
        if not isinstance(blocks, list):
            raise ProviderError("provider_malformed_response",
                                "the message carried no content array",
                                provider=self.provider_id)
        texts: list[str] = []
        calls: list[ToolCall] = []
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
            elif kind == "tool_use":
                name = block.get("name")
                if not isinstance(name, str) or not name:
                    raise ProviderError("provider_malformed_response",
                                        "a tool_use block carried no name",
                                        provider=self.provider_id, index=index)
                arguments = block.get("input")
                if arguments is None:
                    arguments = {}
                if not isinstance(arguments, dict):
                    raise ProviderError("provider_malformed_response",
                                        "tool_use input must be an object",
                                        provider=self.provider_id, index=index)
                calls.append(ToolCall(call_id=str(block.get("id")
                                                  or f"toolu_{index}"),
                                      name=name, arguments=arguments))
        if not blocks and not texts:
            raise ProviderError("provider_empty_response",
                                f"{self.provider_id} returned an empty message",
                                provider=self.provider_id)
        return ProviderResponse(
            text="".join(texts) or None,
            tool_calls=tuple(calls),
            # (v) stop_reason: end_turn | tool_use | max_tokens | stop_sequence
            finish_reason=str(payload.get("stop_reason") or "end_turn"),
            raw={"model": payload.get("model"), "id": payload.get("id"),
                 "usage": payload.get("usage")},
        )

    # -- http ----------------------------------------------------------------
    def _headers(self, *, stream: bool) -> tuple[dict, dict]:
        headers = {
            "content-type": "application/json",
            "accept": "text/event-stream" if stream else "application/json",
            # (v) required
            "anthropic-version": self.anthropic_version,
        }
        headers.update(self.extra_headers)
        secret = self.credential.resolve(self._environ)
        if secret:
            prefix = "Bearer " if self.credential.scheme == "bearer" else ""
            headers[self.credential.header] = f"{prefix}{secret}"
        return headers, redact_headers(headers)

    def _error_from_body(self, payload: dict, *, status: int | None,
                         retry_after=None) -> ProviderError:
        """(v) {"type":"error","error":{"type","message"},"request_id"}"""
        detail = payload.get("error") if isinstance(payload, dict) else None
        api_type = (detail or {}).get("type") or STATUS_ERROR_TYPES.get(status or 0)
        message = (detail or {}).get("message") or "the provider reported an error"
        data = {"provider": self.provider_id, "apiErrorType": api_type,
                "requestId": payload.get("request_id") if isinstance(payload, dict)
                else None}
        if status is not None:
            data["status"] = status
        if retry_after is not None:
            data["retryAfterSeconds"] = retry_after
        if status in (401, 403) or api_type in ("authentication_error",
                                                "permission_error"):
            return ProviderError("provider_unauthorized",
                                 f"{self.provider_id} rejected the credential: "
                                 f"{message}",
                                 credentialRef=self.credential.public(), **data)
        if status == 429 or api_type == "rate_limit_error":
            return ProviderError("provider_http_error",
                                 f"{self.provider_id} rate limited the request: "
                                 f"{message}", **data)
        return ProviderError("provider_http_error",
                             f"{self.provider_id} returned an error: {message}",
                             **data)

    @staticmethod
    def _retry_after(headers) -> float | None:
        """(v) 429 carries retry-after in seconds."""
        if headers is None:
            return None
        raw = None
        try:
            raw = headers.get("retry-after") or headers.get("Retry-After")
        except AttributeError:
            return None
        if raw is None:
            return None
        try:
            return max(0.0, float(str(raw).strip()))
        except (TypeError, ValueError):
            # An HTTP-date form is legal but this adapter does not parse it;
            # it falls back to the fixed backoff rather than guessing a clock.
            return None

    def _open(self, path: str, body: dict | None, *, stream: bool,
              method: str = "POST"):
        headers, _safe = self._headers(stream=stream)
        data = (json.dumps(body, ensure_ascii=False, allow_nan=False)
                .encode("utf-8")) if body is not None else None
        request = urllib.request.Request(f"{self.base_url}{path}", data=data,
                                         headers=headers, method=method)
        return self._opener(request, timeout=self.timeout)

    def _request(self, path: str, body: dict | None, *, stream: bool,
                 method: str = "POST"):
        """One bounded call with at most one principled retry.

        429 honours ``retry-after`` when it is short enough to be a wait rather
        than a hang; 5xx and timeouts get one fixed backoff; no other 4xx is
        ever retried, because retrying a bad request just sends it again.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._open(path, body, stream=stream, method=method)
            except urllib.error.HTTPError as exc:
                status = exc.code
                payload: dict = {}
                try:
                    raw = exc.read(self.max_bytes)
                    payload = json.loads(raw.decode("utf-8")) or {}
                except (OSError, ValueError, UnicodeError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                retry_after = self._retry_after(getattr(exc, "headers", None))
                error = self._error_from_body(payload, status=status,
                                              retry_after=retry_after)
                if status not in RETRYABLE_STATUSES or attempt >= MAX_ATTEMPTS:
                    raise error from exc
                delay = DEFAULT_BACKOFF_SECONDS
                if status == 429 and retry_after is not None:
                    if retry_after > MAX_RETRY_AFTER_SECONDS:
                        # Honour it by refusing. Sleeping this long inside a
                        # turn is indistinguishable from a hang.
                        raise ProviderError(
                            "provider_http_error",
                            f"{self.provider_id} asked for a "
                            f"{retry_after:.0f}s wait, longer than this host "
                            f"will hold a turn open ({MAX_RETRY_AFTER_SECONDS:.0f}s)",
                            provider=self.provider_id, status=status,
                            retryAfterSeconds=retry_after,
                            limitSeconds=MAX_RETRY_AFTER_SECONDS) from exc
                    delay = retry_after
                self._sleep(delay)
            except socket.timeout as exc:
                if attempt >= MAX_ATTEMPTS:
                    raise ProviderError(
                        "provider_timeout",
                        f"{self.provider_id} did not answer within "
                        f"{self.timeout}s", provider=self.provider_id,
                        timeoutSeconds=self.timeout, attempts=attempt) from exc
                self._sleep(DEFAULT_BACKOFF_SECONDS)
            except urllib.error.URLError as exc:
                timed_out = isinstance(exc.reason, socket.timeout)
                if attempt >= MAX_ATTEMPTS:
                    if timed_out:
                        raise ProviderError(
                            "provider_timeout",
                            f"{self.provider_id} did not answer within "
                            f"{self.timeout}s", provider=self.provider_id,
                            timeoutSeconds=self.timeout,
                            attempts=attempt) from exc
                    raise ProviderError(
                        "provider_unreachable",
                        f"{self.provider_id} could not be reached",
                        provider=self.provider_id, reason=str(exc.reason),
                        attempts=attempt) from exc
                self._sleep(DEFAULT_BACKOFF_SECONDS)
            except OSError as exc:
                if attempt >= MAX_ATTEMPTS:
                    raise ProviderError("provider_unreachable",
                                        f"{self.provider_id} could not be reached",
                                        provider=self.provider_id,
                                        reason=str(exc)) from exc
                self._sleep(DEFAULT_BACKOFF_SECONDS)

    def _read_bounded(self, response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            try:
                chunk = response.read(65536)
            except socket.timeout as exc:
                raise ProviderError("provider_timeout",
                                    f"{self.provider_id} stalled mid-body",
                                    provider=self.provider_id) from exc
            if not chunk:
                break
            total += len(chunk)
            if total > self.max_bytes:
                raise ProviderError("provider_response_too_large",
                                    f"{self.provider_id} sent more than "
                                    f"{self.max_bytes} bytes",
                                    provider=self.provider_id,
                                    limit=self.max_bytes)
            chunks.append(chunk)
        return b"".join(chunks)

    # -- calls ---------------------------------------------------------------
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        response = self._request("/v1/messages",
                                 self.build_body(request, stream=False),
                                 stream=False)
        try:
            body = self._read_bounded(response)
        finally:
            try:
                response.close()
            except OSError:
                pass
        try:
            payload = loads_strict(body.decode("utf-8"))
        except (UnicodeError, StrictJsonError) as exc:
            raise ProviderError("provider_malformed_response",
                                f"{self.provider_id} did not return valid JSON",
                                provider=self.provider_id,
                                detail=str(exc)[:400]) from exc
        return self.parse_message(payload)

    def stream(self, request: ProviderRequest) -> Iterator[dict]:
        """SSE, reassembled across chunk boundaries. (v) event names"""
        self.capabilities().require("streaming")
        response = self._request("/v1/messages",
                                 self.build_body(request, stream=True),
                                 stream=True)
        decoder = SseDecoder()
        total = 0
        #: index -> partial tool_use being assembled from input_json_delta (a)
        partial: dict[int, dict] = {}
        try:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_bytes:
                    raise ProviderError("provider_response_too_large",
                                        f"{self.provider_id} streamed more than "
                                        f"{self.max_bytes} bytes",
                                        provider=self.provider_id,
                                        limit=self.max_bytes)
                for name, data in decoder.feed(chunk):
                    for item in self._stream_event(name, data, partial):
                        yield item
        finally:
            try:
                response.close()
            except OSError:
                pass

    def _stream_event(self, name, data, partial) -> list[dict]:
        if not data:
            return []
        try:
            payload = loads_strict(data)
        except StrictJsonError as exc:
            raise ProviderError("provider_malformed_response",
                                f"a stream frame did not parse: {exc.detail}",
                                provider=self.provider_id,
                                strictCode=exc.code) from exc
        if not isinstance(payload, dict):
            return []
        kind = payload.get("type") or name
        if kind == "error":  # (a) event name
            raise self._error_from_body(payload, status=None)
        if kind == "ping":  # (a) event name
            return []
        index = payload.get("index")
        if kind == "content_block_start":
            block = payload.get("content_block") or {}
            if block.get("type") == "tool_use":  # (a) payload shape
                partial[index] = {"id": block.get("id"),
                                  "name": block.get("name"), "json": ""}
            return []
        if kind == "content_block_delta":
            delta = payload.get("delta") or {}
            if delta.get("type") == "text_delta":  # (v)
                text = delta.get("text")
                return [{"type": "text", "text": text}] if text else []
            if delta.get("type") == "input_json_delta":  # (v) name, (a) field
                if index in partial:
                    partial[index]["json"] += delta.get("partial_json") or ""
            return []
        if kind == "content_block_stop":
            pending = partial.pop(index, None)
            if pending is None:
                return []
            raw = pending["json"].strip()
            arguments: dict = {}
            if raw:
                try:
                    parsed = loads_strict(raw)
                except StrictJsonError as exc:
                    raise ProviderError(
                        "provider_malformed_response",
                        f"streamed tool input did not parse: {exc.detail}",
                        provider=self.provider_id, strictCode=exc.code) from exc
                if not isinstance(parsed, dict):
                    raise ProviderError("provider_malformed_response",
                                        "streamed tool input was not an object",
                                        provider=self.provider_id)
                arguments = parsed
            return [{"type": "tool_call",
                     "toolCall": ToolCall(call_id=str(pending["id"] or "toolu_0"),
                                          name=str(pending["name"] or ""),
                                          arguments=arguments).public()}]
        if kind == "message_delta":  # (v) carries stop_reason
            reason = (payload.get("delta") or {}).get("stop_reason")
            return [{"type": "finish", "finishReason": reason}] if reason else []
        if kind == "message_stop":  # (v)
            return [{"type": "done", "finishReason": "stop"}]
        return []

    # -- models ---------------------------------------------------------------
    def list_models(self) -> list:
        """(v) GET /v1/models/{id} fields; (a) the list envelope."""
        self.capabilities().require("modelDiscovery")
        response = self._request("/v1/models", None, stream=False, method="GET")
        try:
            body = self._read_bounded(response)
        finally:
            try:
                response.close()
            except OSError:
                pass
        try:
            payload = loads_strict(body.decode("utf-8"))
        except (UnicodeError, StrictJsonError) as exc:
            raise ProviderError("provider_malformed_response",
                                f"{self.provider_id} did not return valid JSON",
                                provider=self.provider_id,
                                detail=str(exc)[:400]) from exc
        rows = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ProviderError("provider_malformed_response",
                                "the model list was not an array",
                                provider=self.provider_id)
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append({"id": row.get("id"),
                        "displayName": row.get("display_name"),
                        "maxInputTokens": row.get("max_input_tokens"),
                        "maxTokens": row.get("max_tokens"),
                        "provider": self.provider_id})
        return out

    # -- live smoke ------------------------------------------------------------
    def live_smoke(self) -> dict:
        """One tiny real request. Refuses cleanly when there is no credential.

        Never called by the test suite. The keyless refusal IS tested; the leg
        that actually reaches api.anthropic.com is owed.
        """
        state = self.credential_state()
        if state["state"] != "configured" and self.credential.source != "none":
            raise ProviderError(
                "credential_unavailable",
                f"no credential for {self.provider_id}: "
                f"{state['key']} is not set, so there is nothing to smoke-test",
                credentialRef=state, provider=self.provider_id)
        body = {"model": self.model, "max_tokens": SMOKE_MAX_TOKENS,
                "messages": [{"role": "user", "content": "ping"}]}
        response = self._request("/v1/messages", body, stream=False)
        try:
            raw = self._read_bounded(response)
        finally:
            try:
                response.close()
            except OSError:
                pass
        try:
            payload = loads_strict(raw.decode("utf-8"))
        except (UnicodeError, StrictJsonError) as exc:
            raise ProviderError("provider_malformed_response",
                                f"{self.provider_id} did not return valid JSON",
                                provider=self.provider_id) from exc
        parsed = self.parse_message(payload)
        return {"ok": True, "provider": self.provider_id, "model": self.model,
                "stopReason": parsed.finish_reason,
                "usage": (parsed.raw or {}).get("usage"),
                "note": "a live request actually reached the provider"}


def load_anthropic_config(path: Path | str) -> dict:
    from ah_router import load_router_config

    return load_router_config(path)
