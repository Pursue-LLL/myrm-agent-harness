"""Extract pipeline command spans from shell strings for approval UI.

[INPUT]
- tree_sitter + tree_sitter_bash (optional, via pyproject `[shell-ast]` extra)

[OUTPUT]
- extract_command_spans: Pipeline/logical segment spans (128KB cap, tree-sitter + quote-aware fallback).
- classify_span_risk_levels: Per-segment safe/unknown levels via risk_classifier.
- build_shell_approval_fields: Spans + risks from redacted display args.
- extract_shell_command_text: Read command/code from tool args.
- is_shell_approval_tool: Whether a tool name participates in shell span UX.

[POS]
Shell command span extractor for HITL approval UI. Does not affect security decisions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_execution.security.command_explainer.types import (
    CommandSpan,
    SpanRiskLevel,
)

if TYPE_CHECKING:
    from tree_sitter import Node as TreeSitterNode

logger = logging.getLogger(__name__)

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

    ast_spans = _extract_spans_with_tree_sitter(stripped)
    if ast_spans:
        return ast_spans

    return _extract_spans_quote_aware(stripped)


def classify_span_risk_levels(command: str, spans: list[CommandSpan]) -> list[SpanRiskLevel]:
    """Classify each span segment using the existing shell risk classifier."""
    from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
        CommandRiskLevel,
        classify_command_risk,
    )

    levels: list[SpanRiskLevel] = []
    for span in spans:
        segment = command[span["startIndex"] : span["endIndex"]].strip()
        if not segment:
            levels.append("unknown")
            continue
        level = classify_command_risk(segment)
        levels.append("safe" if level == CommandRiskLevel.SAFE else "unknown")
    return levels


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

    return {
        "command_spans": spans,
        "command_span_risks": classify_span_risk_levels(shell_text, spans),
    }


def _extract_spans_with_tree_sitter(command: str) -> list[CommandSpan]:
    try:
        import tree_sitter_bash as tsb
        from tree_sitter import Language, Parser
    except ImportError:
        return []

    try:
        parser = Parser(Language(tsb.language()))
        source = command.encode("utf-8")
        tree = parser.parse(source)
        root = tree.root_node
        if root.has_error:
            return []

        spans: list[CommandSpan] = []
        _collect_command_spans(root, spans)
        return _dedupe_spans(_byte_spans_to_char_spans(command, spans))
    except Exception:
        logger.warning("command_explainer: tree-sitter parse failed", exc_info=True)
        return []


def _collect_command_spans(node: TreeSitterNode, spans: list[CommandSpan]) -> None:
    if node.type == "pipeline":
        for child in node.named_children:
            if child.type == "command":
                spans.append({"startIndex": child.start_byte, "endIndex": child.end_byte})
        return

    if node.type == "command" and node.parent is not None and node.parent.type != "pipeline":
        spans.append({"startIndex": node.start_byte, "endIndex": node.end_byte})
        return

    for child in node.named_children:
        _collect_command_spans(child, spans)


def _extract_spans_quote_aware(command: str) -> list[CommandSpan]:
    """Fallback: split on |, &&, || outside quotes and return segment spans."""
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


def _dedupe_spans(spans: list[CommandSpan]) -> list[CommandSpan]:
    seen: set[tuple[int, int]] = set()
    unique: list[CommandSpan] = []
    for span in sorted(spans, key=lambda s: s["startIndex"]):
        key = (span["startIndex"], span["endIndex"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(span)
    return unique


def _byte_spans_to_char_spans(source: str, spans: list[CommandSpan]) -> list[CommandSpan]:
    encoded = source.encode("utf-8")
    converted: list[CommandSpan] = []
    for span in spans:
        start_byte = span["startIndex"]
        end_byte = span["endIndex"]
        start_char = len(encoded[:start_byte].decode("utf-8"))
        end_char = len(encoded[:end_byte].decode("utf-8"))
        if end_char > start_char:
            converted.append({"startIndex": start_char, "endIndex": end_char})
    return converted
