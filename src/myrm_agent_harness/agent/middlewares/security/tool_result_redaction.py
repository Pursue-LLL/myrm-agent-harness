"""Credential redaction for a tool result, which is text or a list of content blocks.

[INPUT]
- agent.security.detection.leak_detector::redact_leaks (POS: Output-side credential leak detector. 40+ credential
  pattern matchers for preventing secret exfiltration.)

[OUTPUT]
- ToolContent: the content type of a tool result (text, or text and image blocks)
- redact_tool_content: redact credentials in a tool result; of a block list only text is scanned, image data passes
  through untouched

[POS]
Content-shape adapter between a ToolMessage and the leak detector, so the guardrail middleware treats a text result and
a text + image result alike.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.detection.leak_detector import redact_leaks

ToolContent = str | list[str | dict[str, object]]


def redact_tool_content(content: ToolContent) -> ToolContent:
    """Redact credentials in a tool result. A result with an image is a block list: only its text is scanned."""
    if isinstance(content, str):
        return redact_leaks(content)
    return [_redact_block(block) for block in content]


def _redact_block(block: str | dict[str, object]) -> str | dict[str, object]:
    if isinstance(block, str):
        return redact_leaks(block)
    text = block.get("text")
    return {**block, "text": redact_leaks(text)} if isinstance(text, str) else block
