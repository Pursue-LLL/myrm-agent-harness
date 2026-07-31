"""Advisor (reference) prompts for agent-loop MoA overlay.

Reference models in the agent loop are lightweight advisors — not the acting
agent. They must not hallucinate tool execution or claim side effects occurred.

[OUTPUT]
- ADVISOR_SYSTEM: fixed system instruction for reference model calls
- build_advisor_injection_block(): format successful refs for HumanMessage tail
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.llms.consensus.types import ReferenceResponse

ADVISOR_SYSTEM = (
    "You are an advisory reference model in a multi-model agent loop. "
    "You are NOT the acting agent and you do NOT have access to tools. "
    "Provide concise, high-quality advice, critique, or alternative approaches "
    "based on the conversation so far. "
    "NEVER claim you executed a command, ran code, called a tool, or changed any state. "
    "If the acting agent should take an action, describe what it should do — do not "
    "pretend you already did it."
)

_INJECTION_HEADER = (
    "[Multi-model advisor perspectives — reference only; the acting agent decides and executes.]"
)


def build_advisor_injection_block(successful: list[ReferenceResponse]) -> str:
    """Format reference responses for transient HumanMessage tail injection."""
    if not successful:
        return ""
    numbered = "\n".join(
        f"{idx + 1}. [{ref.model}]: {ref.content.strip()}"
        for idx, ref in enumerate(successful)
        if ref.content.strip()
    )
    if not numbered:
        return ""
    return f"{_INJECTION_HEADER}\n{numbered}"


__all__ = ["ADVISOR_SYSTEM", "build_advisor_injection_block"]
