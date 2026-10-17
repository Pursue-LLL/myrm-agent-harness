"""Extract pipeline command spans from shell strings for approval UI.

[INPUT]
- core.security.shell_command_lexer: where each command of the line starts and ends (same reading as the risk classifier)

[OUTPUT]
- extract_command_spans: One span per command, indexed into the command as given (128KB cap).
- classify_span_risk_levels: Per-segment safe/unknown levels via risk_classifier.
- classify_span_risk_reasons: Per-segment stable i18n reason codes via risk_classifier.
- build_shell_approval_fields: Spans, risks, reasons, plain_explanation, and execution_intent from redacted display args.
- extract_shell_command_text: Read command/code from tool args.
- is_shell_approval_tool: Whether a tool name participates in shell span UX.

[POS]
Shell command span extractor for HITL approval UI. Does not affect security decisions.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.shell_command_lexer import split_command_spans
from myrm_agent_harness.toolkits.code_execution.security.command_explainer.types import (
    CommandSpan,
    SpanRiskLevel,
    SpanRiskReason,
)

MAX_COMMAND_SPAN_SOURCE_CHARS = 128 * 1024

_SHELL_TOOL_NAMES = frozenset({"bash_code_execute_tool", "execute_code"})


def is_shell_approval_tool(tool_name: str) -> bool:
    return tool_name in _SHELL_TOOL_NAMES


def extract_shell_command_text(tool_input: dict[str, object]) -> str:
    for key in ("command", "code", "script", "cmd"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def extract_command_spans(command: str) -> list[CommandSpan]:
    """Return one highlight span per command in *command*, indexed into the text as given.

    The approval card highlights the untrimmed command, so indices must not shift with surrounding blanks.
    Spans are never empty: the card drops zero-width spans, which would misalign its parallel risk lists.
    """
    if not command.strip():
        return []

    if len(command) > MAX_COMMAND_SPAN_SOURCE_CHARS:
        return [{"startIndex": 0, "endIndex": len(command)}]

    spans: list[CommandSpan] = [
        {"startIndex": start, "endIndex": end} for start, end in split_command_spans(command) if end > start
    ]
    return spans or [{"startIndex": 0, "endIndex": len(command)}]


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

    from myrm_agent_harness.toolkits.code_execution.security.command_explainer.humanize import (
        humanize_command,
    )

    result: dict[str, object] = {
        "command_spans": spans,
        "command_span_risks": levels,
        "command_span_reasons": reasons,
    }
    explanation = humanize_command(shell_text, spans, levels)
    if explanation:
        result["plain_explanation"] = explanation
    intent_raw = redacted_args.get("reason")
    if isinstance(intent_raw, str):
        intent = intent_raw.strip()
        if intent:
            result["execution_intent"] = intent

    from myrm_agent_harness.toolkits.code_execution.security.ast_parser import BashASTParser

    ast_actions = BashASTParser.parse(shell_text)
    escalations = BashASTParser.summarize_escalations(ast_actions)
    if escalations:
        result["escalations"] = escalations
    result["atomic_actions"] = [
        {
            "command": a.command_text,
            "base_cmd": a.base_cmd,
            "capability_level": str(a.capability_level),
            "escalation_reason": a.escalation_reason,
        }
        for a in ast_actions
    ]

    return result
