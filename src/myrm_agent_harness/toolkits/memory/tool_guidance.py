"""Domain facade for tool memory guidance.

Exposes contracts and synthesis functions from the `tool_guidance` subpackage.

[INPUT]
- myrm_agent_harness.toolkits.memory.tool_guidance (POS: Subpackage facade)

[OUTPUT]
- Forwarding exports for all ToolGuidance types and synthesis functions.

[POS]
Domain facade module.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.tool_guidance import (
    MAX_CHARS_PER_GUIDELINE,
    MAX_GUIDELINES_PER_TOOL,
    MAX_TOTAL_TOOL_GUIDELINES,
    ToolGuidanceItem,
    ToolGuidanceSummary,
    filter_guidance_items,
    is_exploratory_probe,
    synthesize_tool_guidance,
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
