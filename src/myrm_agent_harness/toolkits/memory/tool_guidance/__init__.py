"""Tool guidance evolution subpackage.

Provides structured procedural types and cache-stable, pure-functional
synthesis for active tool guidelines.

[INPUT]
- myrm_agent_harness.toolkits.memory.tool_guidance.types::ToolGuidanceItem, ToolGuidanceSummary
- myrm_agent_harness.toolkits.memory.tool_guidance.synthesizer::*

[OUTPUT]
- Unified public exports for tool guidance models and synthesizer algorithms.

[POS]
Tool memory procedural contract & synthesis domain layer.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.tool_guidance.synthesizer import (
    MAX_CHARS_PER_GUIDELINE,
    MAX_GUIDELINES_PER_TOOL,
    MAX_TOTAL_TOOL_GUIDELINES,
    filter_guidance_items,
    is_exploratory_probe,
    synthesize_tool_guidance,
)
from myrm_agent_harness.toolkits.memory.tool_guidance.types import (
    ToolGuidanceItem,
    ToolGuidanceSummary,
)

__all__ = [
    "MAX_CHARS_PER_GUIDELINE",
    "MAX_GUIDELINES_PER_TOOL",
    "MAX_TOTAL_TOOL_GUIDELINES",
    "ToolGuidanceItem",
    "ToolGuidanceSummary",
    "filter_guidance_items",
    "is_exploratory_probe",
    "synthesize_tool_guidance",
]
