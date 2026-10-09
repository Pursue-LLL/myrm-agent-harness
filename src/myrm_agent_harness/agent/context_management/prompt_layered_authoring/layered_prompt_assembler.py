"""Deterministic layered prompt assembler with semantic isolation tags.

[INPUT]
- layered_types: LayeredPromptDraft, AssembledPromptResult, LayeredAuthoringConfig,
  PromptCorruptionIssue, CorruptionSeverity.
- narrative_style_presets: NarrativeStylePresetRegistry.
- prompt_corruption_detector: PromptCorruptionDetector.

[OUTPUT]
- LayeredPromptAssembler: Compiles layered drafts into authoritative system prompt blocks
  annotated with structural boundaries and diagnostic metadata.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.prompt_layered_authoring
- Module: layered_prompt_assembler.py
"""

from typing import Dict, List
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.layered_types import (
    AssembledPromptResult,
    CorruptionSeverity,
    LayeredAuthoringConfig,
    LayeredPromptDraft,
)
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.narrative_style_presets import (
    NarrativeStylePresetRegistry,
)
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.prompt_corruption_detector import (
    PromptCorruptionDetector,
)


class LayeredPromptAssembler:
    """Assembles three-layer authoring components into an authoritative system prompt."""

    def __init__(self, config: LayeredAuthoringConfig) -> None:
        self._config = config
        self._detector = PromptCorruptionDetector(config)

    def assemble(self, draft: LayeredPromptDraft) -> AssembledPromptResult:
        """Assembles the provided layered draft into a production-grade system prompt block.

        Args:
            draft: The draft partitioned across hard rules, workflow routing, and narrative style.

        Returns:
            An AssembledPromptResult containing the compiled prompt and diagnostic reports.
        """
        # 1. Run corruption and boundary diagnostics
        issues = self._detector.analyze_draft(draft)
        has_critical = any(issue.severity == CorruptionSeverity.CRITICAL for issue in issues)
        is_valid = not (has_critical and self._config.enforce_strict_separation)

        # 2. Synthesize narrative style layer
        style_block = NarrativeStylePresetRegistry.synthesize_style_layer(
            preset=draft.selected_preset,
            custom_notes=draft.custom_style_notes,
            explicit_style_text=draft.narrative_style,
        )

        sections: List[str] = []
        counts: Dict[str, int] = {}

        # 3. Layer 1: Hard Invariant Rules
        if draft.hard_rules.strip():
            clean_rules = draft.hard_rules.strip()
            sections.append(
                f"[LAYER_1_HARD_INVARIANT_RULES]\n"
                f"{clean_rules}\n"
                f"[/LAYER_1_HARD_INVARIANT_RULES]"
            )
            counts["hard_rules"] = len(clean_rules)
        else:
            counts["hard_rules"] = 0

        # 4. Layer 2: Workflow & Tool Routing Guidance
        if draft.workflow_routing.strip():
            clean_workflow = draft.workflow_routing.strip()
            sections.append(
                f"[LAYER_2_WORKFLOW_ROUTING_GUIDANCE]\n"
                f"{clean_workflow}\n"
                f"[/LAYER_2_WORKFLOW_ROUTING_GUIDANCE]"
            )
            counts["workflow_routing"] = len(clean_workflow)
        else:
            counts["workflow_routing"] = 0

        # 5. Layer 3: Narrative & Style Presets
        sections.append(
            f"[LAYER_3_NARRATIVE_COMMUNICATION_STYLE]\n"
            f"{style_block}\n"
            f"[/LAYER_3_NARRATIVE_COMMUNICATION_STYLE]"
        )
        counts["narrative_style"] = len(style_block)

        compiled_prompt = "\n\n".join(sections)
        total_chars = len(compiled_prompt)

        return AssembledPromptResult(
            assembled_system_prompt=compiled_prompt,
            detected_issues=issues,
            is_valid=is_valid,
            total_characters=total_chars,
            layer_character_counts=counts,
        )
