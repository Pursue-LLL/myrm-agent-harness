"""Master facade suite for layered prompt authoring and narrative style presets.

[INPUT]
- layered_types: All contracts, drafts, and configuration models.
- narrative_style_presets: NarrativeStylePresetRegistry.
- prompt_corruption_detector: PromptCorruptionDetector.
- layered_prompt_assembler: LayeredPromptAssembler.

[OUTPUT]
- UserProfilePromptLayeredAuthoringGuideAndNarrativeStylePresetSuite: Master facade
  providing high-level methods for prompt assembly, corruption detection, and style presets.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.prompt_layered_authoring
- Module: prompt_layered_authoring_suite.py
"""

from typing import Optional, Sequence
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.layered_prompt_assembler import (
    LayeredPromptAssembler,
)
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.layered_types import (
    AssembledPromptResult,
    LayeredAuthoringConfig,
    LayeredPromptDraft,
    NarrativeStylePreset,
    PromptCorruptionIssue,
)
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.narrative_style_presets import (
    NarrativeStylePresetRegistry,
)
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.prompt_corruption_detector import (
    PromptCorruptionDetector,
)


class UserProfilePromptLayeredAuthoringGuideAndNarrativeStylePresetSuite:
    """Master facade providing authoring guidance, corruption detection, and style presets."""

    def __init__(self, config: Optional[LayeredAuthoringConfig] = None) -> None:
        self._config = config or LayeredAuthoringConfig()
        self._assembler = LayeredPromptAssembler(self._config)
        self._detector = PromptCorruptionDetector(self._config)

    @property
    def config(self) -> LayeredAuthoringConfig:
        """Returns the active authoring configuration."""
        return self._config

    def assemble_prompt(self, draft: LayeredPromptDraft) -> AssembledPromptResult:
        """Compiles a three-layered prompt draft into an annotated system prompt.

        Args:
            draft: The user authoring draft.

        Returns:
            An AssembledPromptResult with the compiled prompt and diagnostic report.
        """
        return self._assembler.assemble(draft)

    def validate_draft(self, draft: LayeredPromptDraft) -> Sequence[PromptCorruptionIssue]:
        """Analyzes a draft for cross-layer contamination and workflow bloat.

        Args:
            draft: The user authoring draft.

        Returns:
            A sequence of detected PromptCorruptionIssue instances.
        """
        return self._detector.analyze_draft(draft)

    def get_preset_text(self, preset: NarrativeStylePreset) -> str:
        """Retrieves canonical instructions for a given narrative style preset."""
        return NarrativeStylePresetRegistry.get_preset_text(preset)

    def create_quick_draft(
        self,
        hard_rules: str,
        workflow_routing: str = "",
        preset: NarrativeStylePreset = NarrativeStylePreset.NATURAL_PROSE,
        custom_style_notes: str = "",
    ) -> AssembledPromptResult:
        """Convenience method to assemble a prompt from individual components.

        Args:
            hard_rules: Invariant behavioral constraints.
            workflow_routing: Tool and routing rules.
            preset: Standard narrative communication style preset.
            custom_style_notes: Optional user-specific tone additions.

        Returns:
            AssembledPromptResult containing the final system prompt block.
        """
        draft = LayeredPromptDraft(
            hard_rules=hard_rules,
            workflow_routing=workflow_routing,
            selected_preset=preset,
            custom_style_notes=custom_style_notes,
        )
        return self._assembler.assemble(draft)
