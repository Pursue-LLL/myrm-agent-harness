"""LLM call aggregation for trace reconstruction.

Pairs each ``llm_request`` with its ``token_usage`` completion (queued FIFO;
orphaned usage is still recorded with the event's own metadata) and builds the
``LLMCallRecord`` timeline with start/end times and prompt preview.

[POS]
Internal read-side helper of trace_builder.  Not part of the public API.
"""

from __future__ import annotations

from ._common import _int_or_zero, _str_or_none
from .trace_types import ExecutionTrace, LLMCallRecord
from .types import StructuredEvent


class _PendingLLMRequest:
    """Tracks an llm_request waiting for its token_usage completion."""

    __slots__ = ("message_count", "model_name", "prompt_preview", "sequence", "start_time")

    def __init__(
        self,
        sequence: int,
        start_time: float,
        model_name: str | None,
        prompt_preview: str | None,
        message_count: int,
    ) -> None:
        self.sequence = sequence
        self.start_time = start_time
        self.model_name = model_name
        self.prompt_preview = prompt_preview
        self.message_count = message_count


def _handle_llm_request(
    event: StructuredEvent, pending_llm: list[_PendingLLMRequest]
) -> None:
    """Queue an llm_request waiting for its token_usage completion."""
    pending_llm.append(
        _PendingLLMRequest(
            sequence=event.sequence,
            start_time=event.timestamp,
            model_name=_str_or_none(event.data.get("model_name")),
            prompt_preview=_str_or_none(event.data.get("prompt_preview")),
            message_count=_int_or_zero(event.data.get("message_count")),
        )
    )


def _handle_token_usage(
    event: StructuredEvent,
    trace: ExecutionTrace,
    pending_llm: list[_PendingLLMRequest],
) -> None:
    """Merge a token_usage event into the trace as an LLMCallRecord."""
    payload_data = (
        event.data.get("data") if isinstance(event.data.get("data"), dict) else event.data
    )
    usage = payload_data.get("usage", {})
    if not isinstance(usage, dict):
        return

    duration_ms_raw = payload_data.get("duration_ms")
    duration_ms = float(duration_ms_raw) if isinstance(duration_ms_raw, (int, float)) else None
    pending_req = pending_llm.pop(0) if pending_llm else None
    end_time = event.timestamp
    if pending_req:
        start_time = pending_req.start_time
        sequence = pending_req.sequence
        model_name = pending_req.model_name or _str_or_none(payload_data.get("model_name"))
        prompt_preview = pending_req.prompt_preview
        message_count = pending_req.message_count
    else:
        sequence = event.sequence
        model_name = _str_or_none(payload_data.get("model_name"))
        prompt_preview = None
        message_count = 0
        if duration_ms is not None:
            start_time = end_time - duration_ms / 1000.0
        else:
            start_time = end_time

    cached_tokens = 0
    if details := usage.get("prompt_tokens_details"):
        if isinstance(details, dict):
            cached_tokens = int(details.get("cached_tokens", 0))
    elif "cache_read_input_tokens" in usage:
        cached_tokens = int(usage.get("cache_read_input_tokens", 0))

    trace.llm_calls.append(
        LLMCallRecord(
            sequence=sequence,
            start_time=start_time,
            end_time=end_time,
            model_name=model_name,
            prompt_preview=prompt_preview,
            message_count=message_count,
            duration_ms=duration_ms,
            ttft_ms=(
                float(payload_data.get("ttft_ms"))
                if payload_data.get("ttft_ms") is not None
                else None
            ),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            cache_read_tokens=cached_tokens,
        )
    )
