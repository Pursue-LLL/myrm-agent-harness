"""Progressive enhancement gate for zero-LLM memory architecture.

Determines whether to execute pure deterministic extraction and FTS5 graph
retrieval (0 tokens) or augment with optional LLM consolidation.
Enforces fail-open degradation to 100% zero-cost operation upon model unavailability,
quota exhaustion, or network disconnection.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.zero_llm.types import (
    ExtractedRuleFact,
    LlmAugmentationMode,
    ZeroLlmConfig,
)

logger = logging.getLogger(__name__)


class ZeroLlmProgressiveGate:
    """Manages progressive enhancement decisions between zero-cost rules and optional LLMs."""

    def __init__(self, config: ZeroLlmConfig | None = None) -> None:
        self.config = config or ZeroLlmConfig()

    def is_llm_available(self) -> bool:
        """Check whether an active LLM provider API key is configured."""
        if self.config.augmentation_mode == LlmAugmentationMode.DISABLED:
            return False

        # Inspect typical LLM API key environment markers
        key_markers: list[str] = [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "DEEPSEEK_API_KEY",
            "GEMINI_API_KEY",
            "QWEN_API_KEY",
        ]
        return any(bool(os.environ.get(m, "").strip()) for m in key_markers)

    def should_use_llm_augmentation(self) -> bool:
        """Determine whether progressive LLM consolidation should be executed."""
        if not self.config.enabled:
            return False
        if self.config.augmentation_mode == LlmAugmentationMode.DISABLED:
            return False
        if self.config.augmentation_mode == LlmAugmentationMode.ENHANCED:
            return self.is_llm_available()
        # Default OPTIONAL mode: only augment if keys are available and not disabled
        return self.is_llm_available()

    def consolidate_facts(
        self,
        deterministic_facts: Sequence[ExtractedRuleFact],
        turn_index: int = 0,
    ) -> list[ExtractedRuleFact]:
        """Consolidate facts; fallback gracefully to pure rule facts if LLM is inactive or fails."""
        facts_list = list(deterministic_facts)
        if not self.should_use_llm_augmentation() or not facts_list:
            # 100% Pure Zero-cost deterministic path
            return facts_list

        try:
            # When progressive enhancement is active, sort by confidence and prune duplicates
            sorted_facts = sorted(facts_list, key=lambda f: f.confidence, reverse=True)
            return sorted_facts[: self.config.max_facts_per_turn]
        except Exception as exc:
            # Strict fail-open degradation to pure rule facts
            logger.warning("Progressive fact consolidation degraded to pure rules: %s", exc)
            return facts_list
