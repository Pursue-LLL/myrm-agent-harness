# [INPUT]: ResponseVerbosityLevel
# [OUTPUT]: PromptDisciplineInjector
# [POS]: agent/context_management/response_verbosity/prompt_discipline_injector.py

"""Prompt discipline injector enforcing strict information density and conciseness rules.

[INPUT]
- ResponseVerbosityLevel: Active verbosity tier (LOW, MEDIUM, HIGH).

[OUTPUT]
- PromptDisciplineInjector: Synthesizes high-leverage system prompt instructions tailored to the verbosity level.

[POS]
Discipline injection layer in response verbosity subsystem counteracting LLM verbosity biases.
"""

from __future__ import annotations

from .verbosity_types import ResponseVerbosityLevel


class PromptDisciplineInjector:
    """Generates precise prompt discipline directives corresponding to verbosity tiers."""

    LOW_VERBOSITY_DIRECTIVE: str = (
        "### [Response Density: Ultra-Concise (Low)]\n"
        "- Strict Rule: Directly output core answers, exact code changes, or executable CLI commands.\n"
        "- Zero Fluff: Absolutely no conversational greetings, preamble, summary repetitions, or polite filler.\n"
        "- Length Constraint: Limit the entire response strictly to 3-5 lines or minimal code blocks unless impossible."
    )

    MEDIUM_VERBOSITY_DIRECTIVE: str = (
        "### [Response Density: Balanced (Medium)]\n"
        "- Standard Rule: Deliver focused, high-density explanations covering key rationale and essential steps.\n"
        "- Concise Framing: Avoid unnecessary chit-chat while maintaining clarity, completeness, and structured formatting."
    )

    HIGH_VERBOSITY_DIRECTIVE: str = (
        "### [Response Density: Comprehensive (High)]\n"
        "- In-Depth Rule: Thoroughly elaborate architectural rationale, alternative trade-offs, and multi-faceted trade-offs.\n"
        "- Rich Elaboration: Include thorough code comments, edge-case analysis, and end-to-end conceptual walkthroughs."
    )

    def generate_discipline_instruction(self, level: ResponseVerbosityLevel) -> str:
        """Produce the appropriate prompt discipline text for the given tier."""
        if level == ResponseVerbosityLevel.LOW:
            return self.LOW_VERBOSITY_DIRECTIVE
        if level == ResponseVerbosityLevel.HIGH:
            return self.HIGH_VERBOSITY_DIRECTIVE
        return self.MEDIUM_VERBOSITY_DIRECTIVE
