#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drain a provider stream into one honest ``ProviderResponse``.

The turn loop needs a whole answer before it can compile a tool call, and a UI
needs the pieces as they arrive. Those two needs pull in opposite directions
only if you let them: this module iterates the adapter's chunks, hands each one
to a sink (which is where ``provider.stream.chunk`` gets emitted) and returns
the assembled response at the end.

THREE RULES, and the first is the one that matters.

  1. A PARTIAL TOOL CALL IS NEVER DISPATCHED. The chunk vocabulary
     (``ah_codes.STREAM_CHUNK_TYPES``) has no shape for one. An adapter
     assembles fragmentary tool input itself — Anthropic's
     ``input_json_delta``, the OpenAI-shaped ``function.arguments`` — and
     yields a ``tool_call`` chunk only once the arguments parse as an object.
     A stream that dies mid-argument therefore yields NO tool_call chunk at
     all, and rule 2 turns that into a named fault rather than a silent
     half-answer.
  2. A stream must reach a terminal chunk. One that stops earlier ended
     mid-answer, and that is ``provider_stream_incomplete`` — never a short
     reply, because a short reply is the model's decision and a truncated
     stream is a transport's accident.
  3. An undeclared chunk type is refused, not ignored. Dropping an unknown
     chunk is how a consumer silently loses content it was supposed to render.

``finishReason`` follows the same "measured, not assumed" posture: a ``finish``
chunk is authoritative (Anthropic's ``message_delta`` carries the real
``stop_reason``), and ``done`` only fills in when nothing better was said.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ah_codes import (  # noqa: E402
    STREAM_CHUNK_TYPES,
    STREAM_TERMINAL_TYPES,
    ProviderError,
)
from ah_provider import ProviderResponse, ToolCall  # noqa: E402


@dataclass
class StreamOutcome:
    """The assembled answer plus what the assembly itself observed."""

    response: ProviderResponse
    chunks: int = 0
    text_chunks: int = 0
    text_bytes: int = 0
    tool_calls: int = 0
    stats: dict = field(default_factory=dict)

    def public(self) -> dict:
        return {"chunks": self.chunks, "textChunks": self.text_chunks,
                "textBytes": self.text_bytes, "toolCalls": self.tool_calls}


def _tool_call_from(chunk: dict, provider_id: str, index: int) -> ToolCall:
    raw = chunk.get("toolCall")
    if not isinstance(raw, dict):
        raise ProviderError("provider_stream_chunk_invalid",
                            "a tool_call chunk carried no toolCall object",
                            provider=provider_id, chunkIndex=index)
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        # An unnamed call cannot be compiled, and guessing a name is exactly
        # the fabrication this host refuses to do.
        raise ProviderError("provider_stream_chunk_invalid",
                            "a streamed tool call carried no name",
                            provider=provider_id, chunkIndex=index)
    arguments = raw.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ProviderError("provider_stream_chunk_invalid",
                            "streamed tool arguments were not an object",
                            provider=provider_id, chunkIndex=index,
                            offered=type(arguments).__name__)
    call_id = raw.get("callId")
    if not isinstance(call_id, str) or not call_id:
        raise ProviderError("provider_stream_chunk_invalid",
                            "a streamed tool call carried no callId",
                            provider=provider_id, chunkIndex=index, tool=name)
    return ToolCall(call_id=call_id, name=name, arguments=dict(arguments))


def drain(provider, request, on_chunk=None) -> StreamOutcome:
    """Iterate ``provider.stream(request)`` to a whole response.

    ``on_chunk(index, chunk)`` sees every chunk in order, before assembly, and
    is where the event log gets its ``provider.stream.chunk`` entries. It is
    called for the terminal chunk too: a UI wants to know the stream closed.
    """
    provider_id = getattr(provider, "provider_id", "unknown")
    texts: list[str] = []
    calls: list[ToolCall] = []
    finish_reason: str | None = None
    terminal: str | None = None
    outcome = StreamOutcome(response=ProviderResponse())

    for index, chunk in enumerate(provider.stream(request)):
        if not isinstance(chunk, dict):
            raise ProviderError("provider_stream_chunk_invalid",
                                "a stream chunk was not an object",
                                provider=provider_id, chunkIndex=index,
                                offered=type(chunk).__name__)
        kind = chunk.get("type")
        if kind not in STREAM_CHUNK_TYPES:
            raise ProviderError("provider_stream_chunk_invalid",
                                f"undeclared stream chunk type {kind!r}",
                                provider=provider_id, chunkIndex=index,
                                known=list(STREAM_CHUNK_TYPES))
        if terminal is not None:
            # Content after the close is content the adapter said would not
            # come. Refuse rather than quietly append it.
            raise ProviderError("provider_stream_chunk_invalid",
                                "a chunk arrived after the stream closed",
                                provider=provider_id, chunkIndex=index,
                                after=terminal, kind=kind)
        outcome.chunks += 1
        if on_chunk is not None:
            on_chunk(index, chunk)
        if kind == "text":
            text = chunk.get("text")
            if not isinstance(text, str):
                raise ProviderError("provider_stream_chunk_invalid",
                                    "a text chunk carried no text",
                                    provider=provider_id, chunkIndex=index)
            if text:
                texts.append(text)
                outcome.text_chunks += 1
                outcome.text_bytes += len(text.encode("utf-8"))
        elif kind == "tool_call":
            calls.append(_tool_call_from(chunk, provider_id, index))
            outcome.tool_calls += 1
        elif kind == "finish":
            reason = chunk.get("finishReason")
            if isinstance(reason, str) and reason:
                finish_reason = reason
        elif kind in STREAM_TERMINAL_TYPES:
            reason = chunk.get("finishReason")
            if finish_reason is None and isinstance(reason, str) and reason:
                finish_reason = reason
            terminal = kind

    if terminal is None:
        raise ProviderError(
            "provider_stream_incomplete",
            f"{provider_id} closed the stream before a terminal chunk; the "
            "answer is truncated and nothing is invented in its place",
            provider=provider_id, chunks=outcome.chunks,
            textChunks=outcome.text_chunks, toolCalls=outcome.tool_calls,
            expected=list(STREAM_TERMINAL_TYPES))

    outcome.response = ProviderResponse(
        text="".join(texts) if texts else None,
        tool_calls=tuple(calls),
        finish_reason=finish_reason or ("tool_calls" if calls else "stop"),
        raw={"transport": "stream"})
    return outcome
