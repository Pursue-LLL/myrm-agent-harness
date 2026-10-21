"""HITL tool registry SSOT for subagent blocking and server mount hints.

[INPUT]
- None

[OUTPUT]
- HitlToolPolicy: frozen registry of interactive human-in-the-loop meta tools.
- HITL_TOOL_POLICY: default policy singleton.

[POS]
Subagent-side import-safe SSOT for HITL policy. Placed outside meta_tools package
to avoid package-level circular imports when subagent types are imported early.
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
