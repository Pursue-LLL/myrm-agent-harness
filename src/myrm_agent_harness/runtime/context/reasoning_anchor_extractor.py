"""Extractor for condensing raw reasoning streams into structured logic anchors.

Extracts core hypotheses, critical counter-arguments, and finalized decisions
from lengthy thoughts to preserve intelligence across long conversations.
"""

import re

from myrm_agent_harness.runtime.context.reasoning_compactor_types import (
    ReasoningChainAnchor,
)


class ReasoningAnchorExtractor:
    """Condenses lengthy thinking blocks into structured, high-density reasoning anchors."""

    def extract_anchor(
        self, turn_index: int, raw_reasoning: str
    ) -> ReasoningChainAnchor:
        """Analyze thinking text and extract a compact ReasoningChainAnchor."""
        clean_text = self._strip_tags(raw_reasoning).strip()
        orig_tokens = max(1, len(clean_text) // 4)

        hypothesis = self._extract_hypothesis(clean_text)
        counter = self._extract_counter_arguments(clean_text)
        deduction = self._extract_final_deduction(clean_text)

        # Fallback if specific markers not found
        if not hypothesis and not counter and not deduction:
            lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
            if lines:
                hypothesis = lines[0][:150]
                deduction = lines[-1][:150] if len(lines) > 1 else lines[0][:150]

        condensed_prompt = self.render_condensed_anchor_block(
            ReasoningChainAnchor(
                turn_index=turn_index,
                core_hypothesis=hypothesis,
                key_counter_arguments=counter,
                finalized_deduction=deduction,
                original_tokens_est=orig_tokens,
                condensed_tokens_est=0,
            )
        )
        condensed_tokens = max(1, len(condensed_prompt) // 4)

        return ReasoningChainAnchor(
            turn_index=turn_index,
            core_hypothesis=hypothesis,
            key_counter_arguments=counter,
            finalized_deduction=deduction,
            original_tokens_est=orig_tokens,
            condensed_tokens_est=condensed_tokens,
        )

    def render_condensed_anchor_block(
        self, anchor: ReasoningChainAnchor
    ) -> str:
        """Render a concise XML/markdown prompt block representing the anchor."""
        lines = [
            f'<reasoning_anchor turn="{anchor.turn_index}">',
            f"  <hypothesis>{anchor.core_hypothesis}</hypothesis>",
        ]
        if anchor.key_counter_arguments:
            lines.append(
                f"  <counter_argument>{anchor.key_counter_arguments}</counter_argument>"
            )
        if anchor.finalized_deduction:
            lines.append(
                f"  <deduction>{anchor.finalized_deduction}</deduction>"
            )
        lines.append("</reasoning_anchor>")
        return "\n".join(lines)

    def _strip_tags(self, text: str) -> str:
        """Remove XML thinking tags if present."""
        text = re.sub(
            r"<\/?(?:thinking|thought|reasoning)>", "", text, flags=re.IGNORECASE
        )
        return text

    def _extract_hypothesis(self, text: str) -> str:
        """Extract first planning or hypothesis statement."""
        patterns = [
            r"(?:hypothesis|we suspect|let\'s assume|first plan|goal is)[,\s:\-]*\s*(.*?)(?:\.|\n|$)",
            r"(?:we need to|let\'s first|i will investigate)[,\s:\-]*\s*(.*?)(?:\.|\n|$)",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:180]
        # Fallback to first non-empty line
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[0][:180] if lines else "Initial hypothesis"

    def _extract_counter_arguments(self, text: str) -> str:
        """Extract reflection, edge case, or counter-argument statements."""
        patterns = [
            r"(?:however|wait|this fails because|on second thought|edge case|risk is)[,\s:\-]*\s*(.*?)(?:\.|\n|$)",
            r"(?:but note that|warning|constraint is)[,\s:\-]*\s*(.*?)(?:\.|\n|$)",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:180]
        return ""

    def _extract_final_deduction(self, text: str) -> str:
        """Extract final deduction or chosen execution path."""
        patterns = [
            r"(?:therefore|in conclusion|so we should|final decision|we must)[,\s:\-]*\s*(.*?)(?:\.|\n|$)",
            r"(?:thus|we decide to)[,\s:\-]*\s*(.*?)(?:\.|\n|$)",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:180]
        # Fallback to last line
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1][:180] if len(lines) > 1 else ""
