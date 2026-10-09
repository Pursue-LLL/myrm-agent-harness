"""Dual-persona warmth and professional demeanor switcher.

[INPUT]
- arbitrage_types: PersonaMode.

[OUTPUT]
- DualPersonaSwitcher: Injects prompt guidance and recommends sampling
  temperatures based on professional vs companion operational demeanor.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.workspace_arbitrage
- Module: dual_persona_switcher.py
"""

from typing import Dict, Optional, Tuple
from myrm_agent_harness.agent.context_management.workspace_arbitrage.arbitrage_types import (
    PersonaMode,
)


class DualPersonaSwitcher:
    """Dynamically tailors system instructions and sampling parameters for dual persona modes."""

    _PROFESSIONAL_DIRECTIVE = (
        "[PERSONA_DIRECTIVE: PROFESSIONAL_MODE]\n"
        "- Tone: Rigorous, concise, analytical, and highly objective.\n"
        "- Objective: Prioritize technical accuracy, concrete deliverables, and zero redundant chatter.\n"
        "- Formatting: Lead with evidence and conclusions; eliminate canned praise and artificial enthusiasm.\n"
        "[/PERSONA_DIRECTIVE]"
    )

    _COMPANION_DIRECTIVE = (
        "[PERSONA_DIRECTIVE: COMPANION_MODE]\n"
        "- Tone: Warm, witty, charismatic, and genuinely conversational.\n"
        "- Objective: Provide supportive, empathetic companionship alongside reliable task delivery.\n"
        "- Formatting: Natural and lively prose; engage with humor and thoughtful encouragement.\n"
        "[/PERSONA_DIRECTIVE]"
    )

    def __init__(self, default_mode: PersonaMode = PersonaMode.PROFESSIONAL) -> None:
        self._current_mode = default_mode

    @property
    def current_mode(self) -> PersonaMode:
        """Returns the currently active persona mode."""
        return self._current_mode

    def set_mode(self, mode: PersonaMode) -> None:
        """Switches the active persona mode."""
        self._current_mode = mode

    def get_directive_for_mode(self, mode: Optional[PersonaMode] = None) -> str:
        """Returns the specific persona instruction block for injection."""
        active_mode = mode or self._current_mode
        if active_mode == PersonaMode.COMPANION:
            return self._COMPANION_DIRECTIVE
        return self._PROFESSIONAL_DIRECTIVE

    def modify_system_prompt(
        self,
        base_prompt: str,
        mode: Optional[PersonaMode] = None,
        warmth_level: float = 0.5,
    ) -> str:
        """Modifies a system prompt by appending persona guidance.

        Args:
            base_prompt: Original base system instructions.
            mode: Desired persona mode (defaults to currently configured mode).
            warmth_level: Normalized warmth scalar between 0.0 and 1.0.

        Returns:
            Enhanced system prompt incorporating the persona directive.
        """
        directive = self.get_directive_for_mode(mode)
        bounded_warmth = max(0.0, min(1.0, warmth_level))
        warmth_annotation = f"\n[WARMTH_LEVEL: {bounded_warmth:.2f}]"

        return f"{base_prompt.strip()}\n\n{directive}{warmth_annotation}"

    def recommend_generation_params(
        self, mode: Optional[PersonaMode] = None
    ) -> Tuple[float, float]:
        """Recommends (temperature, top_p) settings aligned with the persona.

        Returns:
            Tuple of (temperature, top_p) optimal for the selected demeanor.
        """
        active_mode = mode or self._current_mode
        if active_mode == PersonaMode.COMPANION:
            return 0.75, 0.95
        return 0.20, 0.90
