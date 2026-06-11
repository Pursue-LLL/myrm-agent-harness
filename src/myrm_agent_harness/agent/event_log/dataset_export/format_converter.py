"""Format converter — transform ExecutionTrace into standard fine-tuning formats.

Supports three industry-standard output formats:
- ShareGPT: multi-turn conversation with ``from`` / ``value`` pairs
- Alpaca: instruction / input / output triplet
- OpenAI: chat completions format with role-based messages

Also provides content deduplication via SHA-256 hashing and PII redaction
by delegating to the existing ``redact_pii`` infrastructure.

[INPUT]
- event_log.trace_types::ExecutionTrace (POS: Read-side aggregation types)
- security.detection.pii_redactor::redact_pii (POS: PII redactor)
- dataset_export.protocols::ExportFormat (POS: Pure type definitions)

[OUTPUT]
- convert_trace: convert a single trace to the specified format
- deduplicate: remove duplicate samples by content hash
- redact_trace_pii: apply PII redaction to trace text fields

[POS]
Stateless format conversion. Each function is a pure transform
(trace → dict) with no I/O or side effects.
"""

from __future__ import annotations

import hashlib
import json

from ..trace_types import ExecutionTrace
from .protocols import ExportFormat


def convert_trace(trace: ExecutionTrace, fmt: ExportFormat) -> dict[str, object]:
    """Convert an ExecutionTrace to the specified dataset format.

    Args:
        trace: source execution trace
        fmt: target format

    Returns:
        A dict ready for JSONL serialization.
    """
    if fmt == ExportFormat.SHAREGPT:
        return _to_sharegpt(trace)
    if fmt == ExportFormat.ALPACA:
        return _to_alpaca(trace)
    return _to_openai(trace)


def content_hash(sample: dict[str, object]) -> str:
    """Compute SHA-256 hash of a sample's textual content for deduplication."""
    raw = json.dumps(sample, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def deduplicate(samples: list[dict[str, object]]) -> list[dict[str, object]]:
    """Remove duplicate samples by content hash (preserves first occurrence)."""
    seen: set[str] = set()
    unique: list[dict[str, object]] = []
    for sample in samples:
        h = content_hash(sample)
        if h not in seen:
            seen.add(h)
            unique.append(sample)
    return unique


def redact_trace_pii(trace: ExecutionTrace) -> tuple[ExecutionTrace, int]:
    """Apply PII redaction to the text fields of an ExecutionTrace.

    Returns a new trace with redacted fields and the total redaction count.
    Since ExecutionTrace is mutable (slots=True, not frozen), we modify
    the fields in-place and return the same object.
    """
    from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii

    total_redactions = 0

    if trace.task_input:
        redacted, count = redact_pii(trace.task_input)
        trace.task_input = redacted
        total_redactions += count

    if trace.output:
        redacted, count = redact_pii(trace.output)
        trace.output = redacted
        total_redactions += count

    return trace, total_redactions


# ---------------------------------------------------------------------------
# Private format builders
# ---------------------------------------------------------------------------


def _to_sharegpt(trace: ExecutionTrace) -> dict[str, object]:
    """Convert to ShareGPT multi-turn conversation format.

    Structure:
        {
            "conversations": [
                {"from": "human", "value": "..."},
                {"from": "gpt", "value": "..."},
                {"from": "tool", "value": "..."},  // optional
                ...
            ],
            "metadata": { session_id, outcome, duration_ms }
        }
    """
    conversations: list[dict[str, str]] = []

    if trace.task_input:
        conversations.append({"from": "human", "value": trace.task_input})

    for tc in trace.tool_calls:
        tool_desc = f"[Tool Call: {tc.tool_name}]"
        if tc.input_data:
            args_preview = ", ".join(f"{k}={v!r}" for k, v in list(tc.input_data.items())[:5])
            tool_desc += f"\nArgs: {args_preview}"
        if tc.output_summary:
            tool_desc += f"\nResult: {tc.output_summary}"
        elif tc.error:
            tool_desc += f"\nError: {tc.error}"
        conversations.append({"from": "tool", "value": tool_desc})

    if trace.output:
        conversations.append({"from": "gpt", "value": trace.output})

    return {
        "conversations": conversations,
        "metadata": _trace_metadata(trace),
    }


def _to_alpaca(trace: ExecutionTrace) -> dict[str, object]:
    """Convert to Alpaca instruction-following format.

    Structure:
        {
            "instruction": "task input",
            "input": "tool call context (optional)",
            "output": "agent response",
            "metadata": { ... }
        }
    """
    tool_context_parts: list[str] = []
    for tc in trace.tool_calls:
        part = f"[{tc.tool_name}]"
        if tc.output_summary:
            part += f": {tc.output_summary}"
        tool_context_parts.append(part)

    return {
        "instruction": trace.task_input or "",
        "input": "\n".join(tool_context_parts) if tool_context_parts else "",
        "output": trace.output or "",
        "metadata": _trace_metadata(trace),
    }


def _to_openai(trace: ExecutionTrace) -> dict[str, object]:
    """Convert to OpenAI chat completions format.

    Structure:
        {
            "messages": [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "...", "tool_calls": [...]},
                ...
            ],
            "metadata": { ... }
        }
    """
    messages: list[dict[str, object]] = []

    messages.append({"role": "system", "content": "You are a helpful AI assistant."})

    if trace.task_input:
        messages.append({"role": "user", "content": trace.task_input})

    for tc in trace.tool_calls:
        tool_call_msg: dict[str, object] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": json.dumps(tc.input_data, ensure_ascii=False) if tc.input_data else "{}",
                    },
                }
            ],
        }
        messages.append(tool_call_msg)

        tool_result = tc.output_summary or tc.error or ""
        messages.append({"role": "tool", "name": tc.tool_name, "content": tool_result})

    if trace.output:
        messages.append({"role": "assistant", "content": trace.output})

    return {
        "messages": messages,
        "metadata": _trace_metadata(trace),
    }


def _trace_metadata(trace: ExecutionTrace) -> dict[str, object]:
    """Extract common metadata fields for all formats."""
    return {
        "session_id": trace.session_id,
        "outcome": trace.outcome.value,
        "duration_ms": round(trace.duration_ms, 1),
        "total_tokens": trace.total_tokens,
        "tool_call_count": len(trace.tool_calls),
        "llm_call_count": len(trace.llm_calls),
    }
