"""Orchestration signal name registry — not Action Tools.

[OUTPUT]
- DEEP_RESEARCH_SIGNAL_NAMES / VERIFIER_SIGNAL_NAMES / ORCHESTRATION_SIGNAL_NAMES

[POS]
SSOT for control-plane JSON schemas bound via ``llm.bind_tools()`` and intercepted
by Python orchestrators. Never registered in ``_TOOL_LAYERS`` or ``ToolRegistry``
for default GeneralAgent sessions.
"""

from __future__ import annotations

DISPATCH_RESEARCH_SIGNAL = "dispatch_research"
THINK_SIGNAL = "think"
FINALIZE_REPORT_SIGNAL = "finalize_report"
SUBMIT_VERDICT_SIGNAL = "submit_verdict"

DEEP_RESEARCH_SIGNAL_NAMES: frozenset[str] = frozenset(
    {
        DISPATCH_RESEARCH_SIGNAL,
        THINK_SIGNAL,
        FINALIZE_REPORT_SIGNAL,
    }
)

VERIFIER_SIGNAL_NAMES: frozenset[str] = frozenset({SUBMIT_VERDICT_SIGNAL})

ORCHESTRATION_SIGNAL_NAMES: frozenset[str] = frozenset(
    DEEP_RESEARCH_SIGNAL_NAMES | VERIFIER_SIGNAL_NAMES
)
