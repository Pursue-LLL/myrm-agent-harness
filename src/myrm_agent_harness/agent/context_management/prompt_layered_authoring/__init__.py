"""Prompt layered authoring and narrative style preset package.

[INPUT]
- layered_types: contracts and data models.
- narrative_style_presets: NarrativeStylePresetRegistry.
- prompt_corruption_detector: PromptCorruptionDetector.
- layered_prompt_assembler: LayeredPromptAssembler.
- prompt_layered_authoring_suite: UserProfilePromptLayeredAuthoringGuideAndNarrativeStylePresetSuite.

[OUTPUT]
- Exposes all core contracts and master facade for layered authoring.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.prompt_layered_authoring
- Module: __init__.py
"""

from myrm_agent_harness.agent.context_management.prompt_layered_authoring.layered_prompt_assembler import (
    LayeredPromptAssembler,
)
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.layered_types import (
    AssembledPromptResult,
    CorruptionSeverity,
    LayeredAuthoringConfig,
    LayeredPromptDraft,
    NarrativeStylePreset,
    PromptCorruptionIssue,
    PromptLayerType,
)
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.narrative_style_presets import (
    NarrativeStylePresetRegistry,
)
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.prompt_corruption_detector import (
    PromptCorruptionDetector,
)
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.prompt_layered_authoring_suite import (
    UserProfilePromptLayeredAuthoringGuideAndNarrativeStylePresetSuite,
)

__all__ = [
    "AssembledPromptResult",
    "CorruptionSeverity",
    "LayeredAuthoringConfig",
    "LayeredPromptAssembler",
    "LayeredPromptDraft",
    "NarrativeStylePreset",
    "NarrativeStylePresetRegistry",
    "PromptCorruptionDetector",
    "PromptCorruptionIssue",
    "PromptLayerType",
    "UserProfilePromptLayeredAuthoringGuideAndNarrativeStylePresetSuite",
]
