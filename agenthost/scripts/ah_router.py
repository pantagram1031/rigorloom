#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A configurable OpenAI-compatible endpoint adapter — the "custom router" path.

WHAT THE CONFIG MAY HOLD: a base URL, a model name, capability overrides, and a
credential REFERENCE — the name of an environment variable or an OS
credential-store key. What it may not hold is a credential. A config carrying
anything secret-shaped is refused at load with ``config_invalid``, because the
first time a token lands in a JSON file somebody commits that file.

The value itself is read at call time, lives in a local variable for the length
of one request, and never reaches an event, a log line, an error payload or a
returned object. ``ah_events.redact_headers`` is applied to every header dict
before it is recorded.

FAILURE IS ISOLATED. Every fault on this boundary raises ``ProviderError`` with
a code from ``ah_codes.PROVIDER_CODES``: unreachable, timeout, HTTP status,
unauthorized, malformed body, oversized body. None of them is a document
verdict, and none of them is ever replaced by a guess at what the model would
have said. A router that returns garbage produces a refusal, not an answer.

Tested only against a deterministic local fake (``tests/test_agenthost_router.py``
starts a stdlib server on 127.0.0.1 and stops it). There is no live-provider
test and none is claimed.
"""
from __future__ import annotations

import json
import socket
import sys
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

RUNTIME_SCRIPTS = Path(__file__).resolve().parents[2] / "runtime" / "scripts"
if str(RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SCRIPTS))

from rt_jsonl import StrictJsonError, loads_strict  # noqa: E402

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
CREDENTIAL_SOURCES = ("none", "env", "os_store")

#: Config members that would mean somebody pasted a secret in. Refused by NAME,
#: whatever the value looks like — a guard that inspects values is a guard that
#: can be talked out of it.
SECRET_SHAPED_KEYS = frozenset({
    "apikey", "api_key", "token", "accesstoken", "access_token", "secret",
    "password", "authorization", "bearer", "credentialvalue", "credential_value",
})

CONFIG_KEYS = frozenset({
    "providerId", "baseUrl", "model", "credential", "capabilities",
    "timeoutSeconds", "maxResponseBytes", "extraHeaders", "notes",
})
CREDENTIAL_KEYS = frozenset({"source", "key", "scheme", "header"})


def _reject_secret_shaped(config: dict, where: str = "config") -> None:
    for name in config:
        if str(name).replace("-", "").replace("_", "").lower() in {
                key.replace("_", "") for key in SECRET_SHAPED_KEYS}:
            raise AgentHostError(
                "config_invalid",
                f"{where} member {name!r} looks like a credential; this adapter "
                "takes a reference (an env var or store key), never a value",
                member=name)


class CredentialRef:
    """A NAME, and how to look it up. Never a value."""

    def __init__(self, spec: dict | None):
        spec = dict(spec or {"source": "none"})
        _reject_secret_shaped(spec, "credential")
        unknown = sorted(set(spec) - CREDENTIAL_KEYS)
        if unknown:
            raise AgentHostError("config_invalid",
                                 "credential reference carries unknown members",
                                 unknown=unknown, allowed=sorted(CREDENTIAL_KEYS))
        self.source = spec.get("source", "none")
        if self.source not in CREDENTIAL_SOURCES:
            raise AgentHostError("config_invalid",
                                 f"credential source must be one of "
                                 f"{list(CREDENTIAL_SOURCES)}",
                                 offered=self.source)
        self.key = spec.get("key")
        if self.source != "none" and not self.key:
            raise AgentHostError("config_invalid",
                                 "a credential reference needs the name of the "
                                 "variable or store key to read",
                                 source=self.source)
        self.scheme = spec.get("scheme", "bearer")
        self.header = spec.get("header", "Authorization")

    @property
    def auth_ownership(self) -> str:
        return {"none": "provider_managed", "env": "env_reference",
                "os_store": "os_store_reference"}[self.source]

    def resolve(self, environ: dict) -> str | None:
        """Return the secret for ONE request. Callers must not retain it."""
        if self.source == "none":
            return None
        if self.source == "env":
            value = environ.get(self.key)
            if not value:
                raise ProviderError(
                    "credential_unavailable",
                    f"environment variable {self.key} is not set; the adapter "
                    "will not proceed without the credential it was told to use",
                    credentialRef=self.key, source="env")
            return value
        raise ProviderError(
            "credential_source_unsupported",
            "OS credential-store lookup is not implemented in this slice; use "
            "an environment reference or a provider-managed endpoint",
            credentialRef=self.key, source=self.source)

    def public(self) -> dict:
        """What a UI or an event may see: the reference, never the secret."""
        return {"source": self.source, "key": self.key, "scheme": self.scheme}


class RouterAdapter(ProviderAdapter):
    """One configurable chat-completions endpoint."""

    def __init__(self, config: dict, environ: dict | None = None,
                 opener=None):
        import os

        if not isinstance(config, dict):
            raise AgentHostError("config_invalid", "router config must be an object")
        # Secret-shaped FIRST. A pasted token is also an unknown member, and
        # "unknown member" is the less useful of the two things to be told.
        _reject_secret_shaped(config)
        unknown = sorted(set(config) - CONFIG_KEYS)
        if unknown:
            raise AgentHostError("config_invalid",
                                 "router config carries unknown members",
                                 unknown=unknown, allowed=sorted(CONFIG_KEYS))
        self.provider_id = config.get("providerId") or "custom-router"
        base = config.get("baseUrl")
        if not isinstance(base, str) or not base.startswith(("http://", "https://")):
            raise AgentHostError("config_invalid",
                                 "baseUrl must be an http or https URL",
                                 offered=base)
        self.base_url = base.rstrip("/")
        self.model = config.get("model")
        if not isinstance(self.model, str) or not self.model:
            raise AgentHostError("config_invalid", "model must be a non-empty string")
        self.credential = CredentialRef(config.get("credential"))
        self.overrides = config.get("capabilities") or {}
        self.timeout = float(config.get("timeoutSeconds") or DEFAULT_TIMEOUT)
        self.max_bytes = int(config.get("maxResponseBytes")
                             or DEFAULT_MAX_RESPONSE_BYTES)
        self.extra_headers = dict(config.get("extraHeaders") or {})
        _reject_secret_shaped(self.extra_headers, "extraHeaders")
        self.notes = dict(config.get("notes") or {})
        self._environ = environ if environ is not None else os.environ
        self._opener = opener or urllib.request.urlopen

    # -- contract -----------------------------------------------------------
    def capabilities(self) -> CapabilityProfile:
        base = CapabilityProfile(
            provider_id=self.provider_id,
            model=self.model,
            auth_ownership=self.credential.auth_ownership,
            capabilities={
                # An OpenAI-compatible gateway USUALLY does these. "Usually" is
                # not a capability claim, so anything unverified is unknown and
                # the operator declares it in config.
                "modelDiscovery": cap("unknown",
                                      "not probed; /models may or may not exist"),
                "text": cap("yes", "chat completions is the adapter's only call"),
                "structuredToolUse": cap(
                    "unknown", "depends on the gateway; declare it in config"),
                "structuredOutput": cap(
                    "unknown", "response_format support is gateway-specific"),
                "streaming": cap(
                    "unknown", "SSE support is gateway-specific; declare it"),
                "resumableThread": cap(
                    "no", "chat completions is stateless; the host resends"),
                "vision": cap(
                    "unknown", "image input is gateway-specific and this "
                               "adapter sends none; declare it in config"),
            },
            notes={"baseUrl": self.base_url,
                   "credentialRef": self.credential.public(), **self.notes},
        )
        return base.with_overrides(self.overrides)

    # -- http ---------------------------------------------------------------
    def _headers(self, streaming: bool) -> tuple[dict, dict]:
        """(headers to send, headers safe to record)."""
        headers = {"Content-Type": "application/json",
                   "Accept": "text/event-stream" if streaming else "application/json"}
        headers.update(self.extra_headers)
        secret = self.credential.resolve(self._environ)
        if secret:
            prefix = "Bearer " if self.credential.scheme == "bearer" else ""
            headers[self.credential.header] = f"{prefix}{secret}"
        return headers, redact_headers(headers)

    def _post(self, path: str, body: dict, streaming: bool):
        headers, _safe = self._headers(streaming)
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = urllib.request.Request(f"{self.base_url}{path}", data=data,
                                         headers=headers, method="POST")
        try:
            return self._opener(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            status = exc.code
            detail = ""
            try:
                detail = exc.read(2048).decode("utf-8", errors="replace")
            except OSError:
                pass
            if status in (401, 403):
                raise ProviderError("provider_unauthorized",
                                    f"{self.provider_id} rejected the credential "
                                    f"(HTTP {status})",
                                    provider=self.provider_id, status=status,
                                    credentialRef=self.credential.public()) from exc
            raise ProviderError("provider_http_error",
                                f"{self.provider_id} returned HTTP {status}",
                                provider=self.provider_id, status=status,
                                body=detail[:2048]) from exc
        except socket.timeout as exc:
            raise ProviderError("provider_timeout",
                                f"{self.provider_id} did not answer within "
                                f"{self.timeout}s",
                                provider=self.provider_id,
                                timeoutSeconds=self.timeout) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                raise ProviderError("provider_timeout",
                                    f"{self.provider_id} did not answer within "
                                    f"{self.timeout}s",
                                    provider=self.provider_id,
                                    timeoutSeconds=self.timeout) from exc
            raise ProviderError("provider_unreachable",
                                f"{self.provider_id} could not be reached",
                                provider=self.provider_id,
                                reason=str(exc.reason)) from exc
        except OSError as exc:
            raise ProviderError("provider_unreachable",
                                f"{self.provider_id} could not be reached",
                                provider=self.provider_id, reason=str(exc)) from exc

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

    # -- payloads -----------------------------------------------------------
    def build_body(self, request: ProviderRequest, *, stream: bool) -> dict:
        messages = [
            {"role": "system",
             "content": ("You may inspect a document and propose an edit plan. "
                         "You cannot approve or apply anything.")},
        ]
        # Earlier exchanges in this host session, oldest first. Plain
        # user/assistant turns, so a gateway that supports nothing beyond chat
        # completions still carries the memory correctly.
        for exchange in request.conversation:
            messages.append({"role": "user",
                             "content": str(exchange.get("instruction") or "")})
            reply = exchange.get("reply")
            if reply:
                messages.append({"role": "assistant", "content": str(reply)})
        messages.append(
            {"role": "user",
             "content": json.dumps({"instruction": request.instruction,
                                    "context": request.context},
                                   ensure_ascii=False, sort_keys=True)})
        for entry in request.history:
            messages.append({
                "role": "tool",
                "name": entry.get("tool"),
                "content": json.dumps(
                    {"ok": entry.get("ok"),
                     "result": entry.get("result"), "error": entry.get("error")},
                    ensure_ascii=False, sort_keys=True),
            })
        body = {"model": self.model, "messages": messages}
        if request.tools:
            body["tools"] = [{"type": "function",
                              "function": {"name": tool["name"],
                                           "description": tool["description"],
                                           "parameters": tool["inputSchema"]}}
                             for tool in request.tools]
        if stream:
            body["stream"] = True
        return body

    def _parse_arguments(self, raw) -> dict:
        if isinstance(raw, dict):
            return raw
        if raw in (None, ""):
            return {}
        if not isinstance(raw, str):
            raise ProviderError("provider_malformed_response",
                                "tool call arguments were neither an object nor "
                                "a JSON string", provider=self.provider_id)
        try:
            parsed = loads_strict(raw)
        except StrictJsonError as exc:
            raise ProviderError("provider_malformed_response",
                                f"tool call arguments did not parse: {exc.detail}",
                                provider=self.provider_id,
                                strictCode=exc.code) from exc
        if not isinstance(parsed, dict):
            raise ProviderError("provider_malformed_response",
                                "tool call arguments must decode to an object",
                                provider=self.provider_id)
        return parsed

    def parse_completion(self, payload) -> ProviderResponse:
        if not isinstance(payload, dict):
            raise ProviderError("provider_malformed_response",
                                "completion body was not an object",
                                provider=self.provider_id)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("provider_empty_response",
                                f"{self.provider_id} returned no choices",
                                provider=self.provider_id)
        message = (choices[0] or {}).get("message") or {}
        calls = []
        for index, raw in enumerate(message.get("tool_calls") or []):
            function = (raw or {}).get("function") or {}
            name = function.get("name")
            if not isinstance(name, str) or not name:
                raise ProviderError("provider_malformed_response",
                                    "a tool call arrived with no function name",
                                    provider=self.provider_id, index=index)
            calls.append(ToolCall(call_id=str(raw.get("id") or f"call-{index}"),
                                  name=name,
                                  arguments=self._parse_arguments(
                                      function.get("arguments"))))
        return ProviderResponse(text=message.get("content"),
                                tool_calls=tuple(calls),
                                finish_reason=str(choices[0].get("finish_reason")
                                                  or "stop"),
                                raw={"model": payload.get("model")})

    # -- calls --------------------------------------------------------------
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        response = self._post("/chat/completions",
                              self.build_body(request, stream=False), False)
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
        return self.parse_completion(payload)

    def stream(self, request: ProviderRequest) -> Iterator[dict]:
        """Server-sent events, only when the profile actually promises it."""
        self.capabilities().require("streaming")
        response = self._post("/chat/completions",
                              self.build_body(request, stream=True), True)
        total = 0
        try:
            for raw_line in response:
                total += len(raw_line)
                if total > self.max_bytes:
                    raise ProviderError("provider_response_too_large",
                                        f"{self.provider_id} streamed more than "
                                        f"{self.max_bytes} bytes",
                                        provider=self.provider_id,
                                        limit=self.max_bytes)
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    yield {"type": "done", "finishReason": "stop"}
                    return
                try:
                    chunk = loads_strict(data)
                except StrictJsonError as exc:
                    raise ProviderError(
                        "provider_malformed_response",
                        f"a stream chunk did not parse: {exc.detail}",
                        provider=self.provider_id, strictCode=exc.code) from exc
                delta = ((chunk.get("choices") or [{}])[0] or {}).get("delta") or {}
                if delta.get("content"):
                    yield {"type": "text", "text": delta["content"]}
                for index, raw in enumerate(delta.get("tool_calls") or []):
                    function = (raw or {}).get("function") or {}
                    yield {"type": "tool_call",
                           "toolCall": ToolCall(
                               call_id=str(raw.get("id") or f"call-{index}"),
                               name=str(function.get("name") or ""),
                               arguments=self._parse_arguments(
                                   function.get("arguments"))).public()}
        finally:
            try:
                response.close()
            except OSError:
                pass


def load_router_config(path: Path | str) -> dict:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AgentHostError("config_invalid",
                             f"router config is unreadable: {exc}") from exc
    try:
        config = loads_strict(raw)
    except StrictJsonError as exc:
        raise AgentHostError("config_invalid",
                             f"router config is not strict JSON: {exc.detail}",
                             strictCode=exc.code) from exc
    if not isinstance(config, dict):
        raise AgentHostError("config_invalid", "router config must be an object")
    return config
