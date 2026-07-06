"""Verifier orchestration signal — session-scoped structured verdict handoff.

[OUTPUT]
- SUBMIT_VERDICT_SIGNAL: signal name constant
- create_submit_verdict_tool(): factory returning session-scoped LangChain tool

[POS]
Verifier sub-agents bind ``submit_verdict`` to emit a structured ``VerificationVerdict``.
This is an orchestration signal (not an Action Tool): excluded from ``_TOOL_LAYERS``
and default GeneralAgent Turn1 bind.
"""

from __future__ import annotations

from langchain_core.tools import tool

from .catalog import SUBMIT_VERDICT_SIGNAL

SUBMIT_VERDICT_SIGNAL_NAME = SUBMIT_VERDICT_SIGNAL


def create_submit_verdict_tool(context: dict[str, object]) -> object:
    """Create a session-scoped submit_verdict tool writing into *context*."""
    from myrm_agent_harness.agent.sub_agents._verification_parsing import VerificationVerdict

    @tool(SUBMIT_VERDICT_SIGNAL)
    def submit_verdict(
        passed: bool,
        summary: str,
        findings: list[dict[str, str]],
        confidence: str = "HIGH",
    ) -> str:
        """Submit the final verification verdict. You MUST call this tool to complete your task."""
        context["_verifier_verdict"] = VerificationVerdict(
            passed=passed,
            summary=summary,
            confidence=confidence,
            findings=findings,
            raw="[Submitted via Tool Call]",
        )
        return "Verdict submitted successfully. Please complete your response."

    return submit_verdict
