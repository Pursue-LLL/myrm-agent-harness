"""Orchestration signal schemas — control plane, not Action Tools."""

from .catalog import (
    DEEP_RESEARCH_SIGNAL_NAMES,
    DISPATCH_RESEARCH_SIGNAL,
    FINALIZE_REPORT_SIGNAL,
    ORCHESTRATION_SIGNAL_NAMES,
    SUBMIT_VERDICT_SIGNAL,
    THINK_SIGNAL,
    VERIFIER_SIGNAL_NAMES,
)
from .deep_research import (
    DISPATCH_TOOL_NAME,
    FINALIZE_TOOL_NAME,
    THINK_TOOL_NAME,
    build_orchestrator_tools,
)
from .verifier import SUBMIT_VERDICT_SIGNAL_NAME, create_submit_verdict_tool

__all__ = [
    "DEEP_RESEARCH_SIGNAL_NAMES",
    "DISPATCH_RESEARCH_SIGNAL",
    "DISPATCH_TOOL_NAME",
    "FINALIZE_REPORT_SIGNAL",
    "FINALIZE_TOOL_NAME",
    "ORCHESTRATION_SIGNAL_NAMES",
    "SUBMIT_VERDICT_SIGNAL",
    "SUBMIT_VERDICT_SIGNAL_NAME",
    "THINK_SIGNAL",
    "THINK_TOOL_NAME",
    "VERIFIER_SIGNAL_NAMES",
    "build_orchestrator_tools",
    "create_submit_verdict_tool",
]
