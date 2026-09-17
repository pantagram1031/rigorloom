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
# Prompt-mode inspect/propose turns on this Cursor bridge run ~30–90s.
# The 60s default stays the tools-array probe budget.
PROMPT_MODE_TIMEOUT = 180.0
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
    "maxTokens", "toolsInBody",
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
        if self.source == "os_store":
            # Desktop reads the OS credential manager and injects an env var
            # on the child. Python never talks to the keychain.
            raise AgentHostError(
                "provider_config",
                "credential source os_store is supplied by the desktop: it "
                "reads the OS credential manager and injects an environment "
                "reference on the Agent Host child. The Python host does not "
                "access the OS keychain. Use source env, or none for a "
                "keyless endpoint",
                source=self.source, key=self.key)
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
        raise AgentHostError(
            "provider_config",
            "credential source os_store is supplied by the desktop: it "
            "reads the OS credential manager and injects an environment "
            "reference on the Agent Host child. The Python host does not "
            "access the OS keychain. Use source env, or none for a "
            "keyless endpoint",
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
        raw_max = config.get("maxTokens")
        if raw_max is None:
            self.max_tokens = None
        else:
            self.max_tokens = int(raw_max)
            if self.max_tokens < 1:
                raise AgentHostError("config_invalid", "maxTokens must be positive",
                                     offered=self.max_tokens)
        tools_in_body = config.get("toolsInBody", True)
        if tools_in_body not in (True, False):
            raise AgentHostError("config_invalid",
                                 "toolsInBody must be a boolean",
                                 offered=tools_in_body)
        self.tools_in_body = bool(tools_in_body)
        # Explicit `toolsInBody: false` starts in prompt-mode. Unset/true still
        # sends a `tools` array, then falls back for the rest of the session if
        # this gateway rejects it (the Cursor bridge 500s/`cursor_cli_error`).
        self._tools_in_body_explicit = "toolsInBody" in config
        self._prompt_mode_fallback: dict | None = None
        self._fallback_pending = False
        self.extra_headers = dict(config.get("extraHeaders") or {})
        _reject_secret_shaped(self.extra_headers, "extraHeaders")
        self.notes = dict(config.get("notes") or {})
        self._environ = environ if environ is not None else os.environ
        self._opener = opener or urllib.request.urlopen
        # Cursor-named models 500/hang on a `tools` array (G6a: ~300s then
        # cursor_cli_error). Probing that hang occupies the single worker, so
        # the prompt-mode retry times out behind it. Skip the probe unless
        # the operator set toolsInBody explicitly.
        self._maybe_preempt_cursor_tools()

    # -- contract -----------------------------------------------------------
    def credential_state(self) -> dict:
        """Configured, missing, or not required — decided WITHOUT reading a value."""
        reference = self.credential.public()
        if self.credential.source == "none":
            return {"state": "not_required", **reference}
        if self.credential.source == "env":
            present = bool((self._environ.get(self.credential.key) or "").strip())
            return {"state": "configured" if present else "missing", **reference}
        return {"state": "unsupported",
                "reason": "os_store is supplied by the desktop, not Python",
                **reference}

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
                   "credentialRef": self.credential.public(),
                   "credential": self.credential_state(),
                   "toolsInBody": self.tools_in_body,
                   "toolsInBodyConfigured": self._tools_in_body_explicit,
                   **self.notes},
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
            {"role": "user",
             "content": json.dumps({"instruction": request.instruction,
                                    "context": request.context},
                                   ensure_ascii=False, sort_keys=True)},
        ]
        if request.tools and not self.tools_in_body:
            # Names + argument keys only. Full inputSchema is too large for
            # this Cursor bridge (G6a: a 16.9k prompt was truncated to 14.4k).
            # Without the keys, plan_propose.declares and inspect include
            # values are invisible to the model.
            catalogue = []
            for tool in request.tools:
                item = {"name": tool["name"],
                        "description": tool["description"]}
                schema = tool.get("inputSchema") or {}
                props = schema.get("properties")
                if isinstance(props, dict) and props:
                    item["arguments"] = sorted(props)
                catalogue.append(item)
            messages[0]["content"] += (
                " Tools: reply with one JSON object "
                '{"name": "<tool>", "arguments": {..}} as the entire message. '
                "Catalogue: " + json.dumps(catalogue, ensure_ascii=False)
            )
        for entry in request.history:
            # OpenAI-compatible gateways require the assistant tool_calls
            # message that the tool result answers, plus tool_call_id. The
            # host already keeps both; dropping them made a second turn look
            # like an orphan tool message and a keyless Cursor bridge (and
            # most real routers) refuse it.
            # Prompt-mode (toolsInBody false) cannot send those wire shapes:
            # this Cursor bridge 500s on a `tools` array after ~300s.
            call_id = str(entry.get("callId") or f"call-{entry.get('tool')}")
            arguments = entry.get("arguments") or {}
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False,
                                       sort_keys=True)
            if self.tools_in_body:
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {"name": entry.get("tool"),
                                     "arguments": arguments},
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": entry.get("tool"),
                    "content": json.dumps(
                        {"ok": entry.get("ok"),
                         "result": entry.get("result"),
                         "error": entry.get("error")},
                        ensure_ascii=False, sort_keys=True),
                })
            else:
                parsed_args = arguments
                if isinstance(arguments, str):
                    try:
                        parsed_args = loads_strict(arguments)
                    except StrictJsonError:
                        parsed_args = arguments
                messages.append({
                    "role": "assistant",
                    "content": json.dumps(
                        {"name": entry.get("tool"), "arguments": parsed_args},
                        ensure_ascii=False, sort_keys=True),
                })
                messages.append({
                    "role": "user",
                    "content": json.dumps(
                        {"ok": entry.get("ok"),
                         "result": self._prompt_result(entry),
                         "error": entry.get("error")},
                        ensure_ascii=False, sort_keys=True),
                })
        body = {"model": self.model, "messages": messages}
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if request.tools and self.tools_in_body:
            body["tools"] = [{"type": "function",
                              "function": {"name": tool["name"],
                                           "description": tool["description"],
                                           "parameters": tool["inputSchema"]}}
                             for tool in request.tools]
            # Deliberately not sending tool_choice. The keyless Cursor bridge
            # hangs when tool_choice=auto is set.
        if stream:
            body["stream"] = True
        return body

    def _prompt_result(self, entry: dict):
        """What prompt-mode history may carry: enough to continue, not a dump.

        The keyless Cursor bridge has crashed (HTTP 500, process exit -1) when
        the second turn resent a full ``document/inspect`` payload plus the
        tool catalogue. Anchors and hashes are what the next propose needs.
        """
        result = entry.get("result")
        tool = entry.get("tool")
        if tool == "document_inspect" and isinstance(result, dict):
            slim = {}
            if "documentHash" in result:
                slim["documentHash"] = result["documentHash"]
            summary = result.get("summary")
            if isinstance(summary, dict):
                keep = ("anchors", "fillTargetCount", "documentHash",
                        "pageMetrics")
                slim["summary"] = {key: summary[key] for key in keep
                                   if key in summary}
            regions = result.get("regions")
            if isinstance(regions, dict):
                slim["regionCount"] = len(regions.get("regions") or [])
            forbidden = result.get("forbidden")
            if isinstance(forbidden, dict):
                # Keepable label texts are what plan_propose.declares.keep
                # names. Dropping them (G6a slim) made a bound-form keep
                # list impossible to compose from inspect.
                slim["forbidden"] = {
                    "counts": forbidden.get("counts"),
                    "residue": forbidden.get("residue"),
                    "anchors": self._forbidden_texts(forbidden.get("anchors")),
                    "placeholders": self._forbidden_texts(
                        forbidden.get("placeholders")),
                    "removalTargets": self._forbidden_texts(
                        forbidden.get("removalTargets")),
                }
            return slim
        blob = json.dumps(result, ensure_ascii=False, default=str)
        if len(blob) > 6000:
            from ah_host import summarize
            return {"truncated": True,
                    "summary": summarize(tool or "", result
                                         if isinstance(result, dict) else {})}
        return result

    @staticmethod
    def _forbidden_texts(rows) -> list:
        """Compact keepable/guide rows: text + keepable flag only."""
        out = []
        for entry in rows or []:
            if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                out.append({"text": entry["text"],
                            "keepable": bool(entry.get("keepable"))})
        return out

    def _recover_tool_calls(self, text, tools) -> tuple:
        """Turn a JSON object in assistant text into tool_calls, or nothing.

        Some gateways advertise tools then emit
        ``{"name": "...", "arguments": {...}}`` as content with finish_reason
        stop. That is still a tool request; treating it as closing text ends
        the host loop with no plan. Recovery is identity-checked against the
        offered tool names so ordinary JSON answers stay text.
        """
        if not isinstance(text, str) or not text.strip() or not tools:
            return ()
        blob = text.strip()
        if blob.startswith("```"):
            lines = blob.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            blob = "\n".join(lines).strip()
        try:
            parsed = loads_strict(blob)
        except StrictJsonError:
            return ()
        offered = {tool.get("name") for tool in tools
                   if isinstance(tool, dict) and isinstance(tool.get("name"), str)}
        items = parsed if isinstance(parsed, list) else [parsed]
        calls = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                return ()
            name = item.get("name")
            if name not in offered or "arguments" not in item:
                return ()
            try:
                arguments = self._parse_arguments(item.get("arguments"))
            except ProviderError:
                return ()
            calls.append(ToolCall(call_id=str(item.get("id") or f"recovered-{index}"),
                                  name=name, arguments=arguments))
        return tuple(calls)

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

    def _is_tools_rejection(self, exc: ProviderError) -> bool:
        """True when this HTTP fault is the gateway refusing an OpenAI tools array.

        The keyless Cursor bridge answers HTTP 500 ``cursor_cli_error``. Other
        gateways say so in a 4xx/5xx body that mentions tools. Auth rejections
        stay unauthorized; a 500 that does not mention tools stays a fault.
        """
        if exc.code != "provider_http_error":
            # This Cursor bridge hangs on a `tools` array (then 500s after
            # minutes). A timeout while tools were in the body is the same
            # rejection; prompt-mode must take over rather than fail the run.
            return exc.code == "provider_timeout"
        status = exc.data.get("status")
        body = str(exc.data.get("body") or "")
        lowered = body.lower()
        if status == 500 and "cursor_cli_error" in lowered:
            return True
        if isinstance(status, int) and 400 <= status <= 599:
            return "tools" in lowered
        return False

    def _maybe_preempt_cursor_tools(self) -> None:
        """Skip the hanging tools probe for Cursor-named models."""
        if self._tools_in_body_explicit or not self.tools_in_body:
            return
        if not str(self.model).lower().startswith("cursor-"):
            return
        self._enter_prompt_mode(ProviderError(
            "provider_http_error",
            f"{self.provider_id} Cursor-named models reject an OpenAI tools array",
            provider=self.provider_id, status=500,
            body="cursor_cli_error: tools array omitted; this bridge hangs then 500s",
        ))
        self._prompt_mode_fallback["reason"] = (
            "Cursor-named gateway model; OpenAI tools array omitted "
            "(this bridge 500s/hangs on tools)"
        )
        self.notes["promptModeFallback"]["reason"] = (
            self._prompt_mode_fallback["reason"]
        )

    def _enter_prompt_mode(self, exc: ProviderError) -> None:
        """Stay in prompt-mode for the rest of this adapter's life."""
        fault = exc.as_dict()
        body = str(exc.data.get("body") or "")[:500]
        self.tools_in_body = False
        self.timeout = max(self.timeout, PROMPT_MODE_TIMEOUT)
        self._prompt_mode_fallback = {
            "reason": ("gateway rejected the OpenAI tools array; "
                       "remaining turns use prompt-mode"),
            "status": exc.data.get("status"),
            "body": body,
            "code": exc.code,
            "fault": fault,
        }
        self._fallback_pending = True
        self.notes["promptModeFallback"] = {
            "reason": self._prompt_mode_fallback["reason"],
            "status": self._prompt_mode_fallback["status"],
        }

    def _maybe_fallback_to_prompt(self, exc: ProviderError,
                                  request: ProviderRequest) -> bool:
        if not self.tools_in_body or not request.tools:
            return False
        if not self._is_tools_rejection(exc):
            return False
        self._enter_prompt_mode(exc)
        return True

    def _attach_fallback(self, parsed: ProviderResponse) -> ProviderResponse:
        if not self._fallback_pending or not self._prompt_mode_fallback:
            return parsed
        self._fallback_pending = False
        raw = dict(parsed.raw or {})
        raw["promptModeFallback"] = self._prompt_mode_fallback
        return ProviderResponse(text=parsed.text, tool_calls=parsed.tool_calls,
                                finish_reason=parsed.finish_reason, raw=raw)

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
        if not calls:
            legacy = message.get("function_call")
            if isinstance(legacy, dict) and isinstance(legacy.get("name"), str) \
                    and legacy.get("name"):
                calls.append(ToolCall(
                    call_id=str(legacy.get("id") or "call-0"),
                    name=legacy["name"],
                    arguments=self._parse_arguments(legacy.get("arguments"))))
        raw = {"model": payload.get("model"), "id": payload.get("id")}
        if payload.get("usage") is not None:
            raw["usage"] = payload["usage"]
        text = message.get("content")
        if isinstance(text, list):
            # Some OpenAI-compatible gateways emit content parts instead of a
            # plain string. Join the text parts; ignore the rest.
            text = "".join(part.get("text") or ""
                           for part in text if isinstance(part, dict)) or None
        return ProviderResponse(text=text if text else None,
                                tool_calls=tuple(calls),
                                finish_reason=str(choices[0].get("finish_reason")
                                                  or "stop"),
                                raw=raw)

    # -- calls --------------------------------------------------------------
    def _complete_once(self, request: ProviderRequest) -> ProviderResponse:
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
        parsed = self.parse_completion(payload)
        if not parsed.tool_calls:
            recovered = self._recover_tool_calls(parsed.text, request.tools)
            if recovered:
                return ProviderResponse(text=None, tool_calls=recovered,
                                        finish_reason="tool_calls",
                                        raw=dict(parsed.raw or {}))
        return parsed

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        try:
            parsed = self._complete_once(request)
        except ProviderError as exc:
            if not self._maybe_fallback_to_prompt(exc, request):
                raise
            parsed = self._complete_once(request)
        return self._attach_fallback(parsed)

    def stream(self, request: ProviderRequest) -> Iterator[dict]:
        """Server-sent events, only when the profile actually promises it."""
        self.capabilities().require("streaming")
        try:
            response = self._post("/chat/completions",
                                  self.build_body(request, stream=True), True)
        except ProviderError as exc:
            if not self._maybe_fallback_to_prompt(exc, request):
                raise
            response = self._post("/chat/completions",
                                  self.build_body(request, stream=True), True)
        if self._fallback_pending:
            self._fallback_pending = False
            if self._prompt_mode_fallback:
                yield {"type": "note",
                       "promptModeFallback": self._prompt_mode_fallback}
        total = 0
        finish_reason = "stop"
        usage = None
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
                    done = {"type": "done", "finishReason": finish_reason}
                    if usage is not None:
                        done["usage"] = usage
                    yield done
                    return
                try:
                    chunk = loads_strict(data)
                except StrictJsonError as exc:
                    raise ProviderError(
                        "provider_malformed_response",
                        f"a stream chunk did not parse: {exc.detail}",
                        provider=self.provider_id, strictCode=exc.code) from exc
                if chunk.get("usage") is not None:
                    usage = chunk["usage"]
                choice = (chunk.get("choices") or [{}])[0] or {}
                if choice.get("finish_reason"):
                    finish_reason = str(choice["finish_reason"])
                delta = choice.get("delta") or {}
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
