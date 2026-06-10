"""Extract pipeline command spans from shell strings for approval UI.

[INPUT]
- None (quote-aware string splitter; no optional deps)

[OUTPUT]
- extract_command_spans: Pipeline/logical segment spans (128KB cap, quote-aware split).
- classify_span_risk_levels: Per-segment safe/unknown levels via risk_classifier.
- classify_span_risk_reasons: Per-segment stable i18n reason codes via risk_classifier.
- build_shell_approval_fields: Spans, risks, and reasons from redacted display args.
- extract_shell_command_text: Read command/code from tool args.
- is_shell_approval_tool: Whether a tool name participates in shell span UX.

[POS]
Shell command span extractor for HITL approval UI. Does not affect security decisions.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.security.command_explainer.types import (
    CommandSpan,
    SpanRiskLevel,
    SpanRiskReason,
)

MAX_COMMAND_SPAN_SOURCE_CHARS = 128 * 1024

_SHELL_TOOL_NAMES = frozenset({"bash_code_execute_tool", "bash_tool", "execute_code"})


def is_shell_approval_tool(tool_name: str) -> bool:
    return tool_name in _SHELL_TOOL_NAMES


def extract_shell_command_text(tool_input: dict[str, object]) -> str:
    for key in ("command", "code", "script", "cmd"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def extract_command_spans(command: str) -> list[CommandSpan]:
    """Return highlight spans for each pipeline/logical segment in *command*."""
    stripped = command.strip()
    if not stripped:
        return []

    if len(stripped) > MAX_COMMAND_SPAN_SOURCE_CHARS:
        return [{"startIndex": 0, "endIndex": len(stripped)}]

    return _extract_spans_quote_aware(stripped)


def _classify_span_risk_pairs(
    command: str,
    spans: list[CommandSpan],
) -> tuple[list[SpanRiskLevel], list[SpanRiskReason]]:
    from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
        CommandRiskLevel,
        classify_segment_risk_detail,
    )

    levels: list[SpanRiskLevel] = []
    reasons: list[SpanRiskReason] = []
    for span in spans:
        segment = command[span["startIndex"] : span["endIndex"]]
        level, reason = classify_segment_risk_detail(segment)
        if level == CommandRiskLevel.SAFE:
            levels.append("safe")
            reasons.append("safe")
        else:
            levels.append("unknown")
            reasons.append(reason)
    return levels, reasons


def classify_span_risk_levels(command: str, spans: list[CommandSpan]) -> list[SpanRiskLevel]:
    """Classify each span segment using the existing shell risk classifier."""
    levels, _ = _classify_span_risk_pairs(command, spans)
    return levels


def classify_span_risk_reasons(command: str, spans: list[CommandSpan]) -> list[SpanRiskReason]:
    """Classify each span segment and return stable i18n reason codes."""
    _, reasons = _classify_span_risk_pairs(command, spans)
    return reasons


def build_shell_approval_fields(
    tool_name: str,
    redacted_args: dict[str, object],
) -> dict[str, object]:
    """Build command_spans and command_span_risks from redacted display args."""
    if not is_shell_approval_tool(tool_name):
        return {}

    shell_text = extract_shell_command_text(redacted_args)
    if not shell_text:
        return {}

    spans = extract_command_spans(shell_text)
    if not spans:
        return {}

    levels, reasons = _classify_span_risk_pairs(shell_text, spans)
    return {
        "command_spans": spans,
        "command_span_risks": levels,
        "command_span_reasons": reasons,
    }


def _extract_spans_quote_aware(command: str) -> list[CommandSpan]:
    """Split on |, &&, || outside quotes and return segment spans."""
    segments: list[tuple[int, int]] = []
    cursor = 0
    i = 0
    in_single = False
    in_double = False
    length = len(command)

    def flush_segment(end: int) -> None:
        nonlocal cursor
        segment = command[cursor:end].strip()
        if not segment:
            cursor = end
            return
        start = command.find(segment, cursor, end)
        if start < 0:
            start = cursor
        segments.append((start, start + len(segment)))
        cursor = end

    while i < length:
        ch = command[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if in_single or in_double:
            i += 1
            continue

        if command.startswith("||", i) or command.startswith("&&", i):
            flush_segment(i)
            i += 2
            while i < length and command[i].isspace():
                i += 1
            cursor = i
            continue
        if ch == "|":
            flush_segment(i)
            i += 1
            while i < length and command[i].isspace():
                i += 1
            cursor = i
            continue
        i += 1

    flush_segment(length)

    if not segments:
        return [{"startIndex": 0, "endIndex": len(command)}]

    return [{"startIndex": start, "endIndex": end} for start, end in segments]
