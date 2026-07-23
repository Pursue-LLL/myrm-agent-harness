"""HITL tool registry SSOT for subagent blocking and server mount hints.

[INPUT]
- None

[OUTPUT]
- HitlToolPolicy: frozen registry of interactive human-in-the-loop meta tools.

[POS]
Single source for which tools require a live user thread. Subagent delegation reads
subagent_blocked; server mount gates apply channel/mode filters separately.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HitlToolPolicy:
    """Registry of HITL meta tools that must not run on leaf subagents."""

    registered_tools: frozenset[str]
    subagent_blocked: frozenset[str]

    @classmethod
    def default(cls) -> HitlToolPolicy:
        registered = frozenset({"ask_question_tool"})
        return cls(registered_tools=registered, subagent_blocked=registered)


HITL_TOOL_POLICY = HitlToolPolicy.default()
