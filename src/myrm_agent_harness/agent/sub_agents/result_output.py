"""Subagent result payload

[INPUT]
- (none)

[OUTPUT]
- SubAgentOutput: Subagent result payload (answer text, or a dict carrying isolation merge metadata)
- answer_text: The answer text of a result payload, whichever form it takes

[POS]
A subagent running in an isolated workspace reports a dict (``text`` plus the metadata that merges its workspace
back) instead of a plain string. Every consumer that needs the answer as text reads it through ``answer_text`` so
that form is handled in one place; code that only passes the payload along keeps it unchanged.
"""

from __future__ import annotations

type SubAgentOutput = str | dict[str, object]


def answer_text(output: SubAgentOutput) -> str:
    """The answer text of ``output``; a dict payload carries it under ``text``."""
    if isinstance(output, dict):
        text = output.get("text")
        return text if isinstance(text, str) else ""
    return output
