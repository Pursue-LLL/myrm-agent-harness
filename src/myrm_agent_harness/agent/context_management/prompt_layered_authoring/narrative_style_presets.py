"""Standard narrative style presets and communication tone generator.

[INPUT]
- layered_types: NarrativeStylePreset.

[OUTPUT]
- NarrativeStylePresetRegistry: Supplies standard narrative presets and
  synthesizes cohesive tone guidance with custom user authoring notes.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.prompt_layered_authoring
- Module: narrative_style_presets.py
"""

from typing import Dict, Optional
from myrm_agent_harness.agent.context_management.prompt_layered_authoring.layered_types import (
    NarrativeStylePreset,
)


class NarrativeStylePresetRegistry:
    """Registry providing vetted narrative style templates grounded in AGENTS.md communications."""

    _PRESETS: Dict[NarrativeStylePreset, str] = {
        NarrativeStylePreset.NATURAL_PROSE: (
            "- Default to natural, cohesive prose rather than bullet-heavy status dumps.\n"
            "- Lead directly with conclusions and key takeaways, followed by essential rationale.\n"
            "- Reserve bullet points strictly for genuinely enumerable entities or checklist steps.\n"
            "- Show personality where fitting: highlight interesting root causes, elegant simplifications, and tradeoffs.\n"
            "- Strictly eliminate canned enthusiasm, robotic chatter, and sycophantic praise."
        ),
        NarrativeStylePreset.CONCISE_EXECUTIVE: (
            "- Provide high-density, concise executive briefings.\n"
            "- Lead with bottom-line impacts, operational decisions, and risk assessments.\n"
            "- Minimize technical implementation minutiae unless explicitly requested.\n"
            "- Keep paragraphs short, sharp, and outcome-oriented with zero polite filler."
        ),
        NarrativeStylePreset.ENGINEERING_RIGOROUS: (
            "- Adopt the posture of a world-class principal architect and systems engineer.\n"
            "- Ground all technical assertions in verifiable evidence ([file:line] citations or benchmarks).\n"
            "- Be brutally honest about complexity, technical debt, and concurrency hazards.\n"
            "- Explain 'why' instead of merely 'what'; celebrate minimal, high-leverage code changes."
        ),
        NarrativeStylePreset.WARM_CHARISMATIC: (
            "- Communicate with genuine warmth, wit, and conversational charisma.\n"
            "- Foster an engaging, collaborative atmosphere with thoughtful humor and empathetic encouragement.\n"
            "- Balance high-velocity productivity with human relatability and visual elegance.\n"
            "- Remain sharp and constructive while avoiding dry corporate monotone."
        ),
        NarrativeStylePreset.CUSTOM: (
            "- Follow custom user-specified communication style directives strictly."
        ),
    }

    @classmethod
    def get_preset_text(cls, preset: NarrativeStylePreset) -> str:
        """Returns the canonical instruction block for a style preset."""
        return cls._PRESETS.get(preset, cls._PRESETS[NarrativeStylePreset.NATURAL_PROSE])

    @classmethod
    def synthesize_style_layer(
        cls,
        preset: NarrativeStylePreset,
        custom_notes: str = "",
        explicit_style_text: str = "",
    ) -> str:
        """Synthesizes the complete narrative style layer combining presets and custom input.

        Args:
            preset: Selected standard style preset.
            custom_notes: Optional supplementary notes.
            explicit_style_text: Optional explicit user style text overriding the preset.

        Returns:
            A clean formatted narrative style instruction block.
        """
        lines = ["[STYLE_PRESET_DIRECTIVES]"]
        if explicit_style_text.strip():
            lines.append(explicit_style_text.strip())
        else:
            lines.append(cls.get_preset_text(preset))

        if custom_notes.strip():
            lines.append("\n[USER_CUSTOM_STYLE_ADDITIONS]")
            lines.append(custom_notes.strip())

        lines.append("[/STYLE_PRESET_DIRECTIVES]")
        return "\n".join(lines)
