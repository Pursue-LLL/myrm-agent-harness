"""Vertical Persona Presets and Sub-Bot Sandbox Tester package.

[INPUT]
- Subagent role definitions, test requests, A2A interaction flow steps.

[OUTPUT]
- VerticalRolePreset catalog, sandbox test runner, A2A flow inspector with loop detection.

[POS]
- Harness orchestration layer for enterprise-ready specialist agent personas.
"""

from myrm_agent_harness.agent.sub_agents.vertical_presets.presets_catalog import (
    BUILTIN_PRESETS,
    PresetsCatalog,
)
from myrm_agent_harness.agent.sub_agents.vertical_presets.sandbox_tester import (
    A2AFlowInspector,
    SubBotSandboxTester,
)
from myrm_agent_harness.agent.sub_agents.vertical_presets.types import (
    A2AFlowStep,
    A2AFlowTrace,
    ReasoningEffort,
    SubBotTestRequest,
    SubBotTestResult,
    VerticalRoleCategory,
    VerticalRolePreset,
)

__all__ = [
    "A2AFlowInspector",
    "A2AFlowStep",
    "A2AFlowTrace",
    "BUILTIN_PRESETS",
    "PresetsCatalog",
    "ReasoningEffort",
    "SubBotSandboxTester",
    "SubBotTestRequest",
    "SubBotTestResult",
    "VerticalRoleCategory",
    "VerticalRolePreset",
]
