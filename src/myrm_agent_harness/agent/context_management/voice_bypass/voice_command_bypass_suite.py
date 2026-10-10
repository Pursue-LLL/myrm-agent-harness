"""Unified suite facade for voice command local bypass and tiered intent routing.

[INPUT]
Raw voice utterance transcription strings, VoiceBypassConfig.

[OUTPUT]
VoiceCommandLocalBypassAndTieredIntentRoutingSuite evaluating Tier-0 vs Tier-1 routing.

[POS]
Top-level facade in context_management/voice_bypass/voice_command_bypass_suite.py.
"""

from __future__ import annotations

import logging

from .voice_bypass_types import (
    VoiceBypassConfig,
    VoiceCommandMatchResult,
    VoiceIntentTier,
)
from .voice_command_matcher import VoiceCommandMatcher

logger = logging.getLogger(__name__)


class VoiceCommandLocalBypassAndTieredIntentRoutingSuite:
    """High-level suite for voice command local bypass and tiered intent dispatch."""

    def __init__(
        self,
        config: VoiceBypassConfig | None = None,
        matcher: VoiceCommandMatcher | None = None,
    ) -> None:
        self._config = config or VoiceBypassConfig()
        self._matcher = matcher or VoiceCommandMatcher(config=self._config)

    @property
    def config(self) -> VoiceBypassConfig:
        """Access operational configuration."""
        return self._config

    def route_utterance(self, raw_utterance: str) -> VoiceCommandMatchResult:
        """Route a single voice utterance to Tier-0 bypass or Tier-1 agent LLM."""
        return self._matcher.match(raw_utterance)

    def batch_route(self, utterances: list[str]) -> list[VoiceCommandMatchResult]:
        """Route a batch of utterances, returning routing decisions for each."""
        return [self._matcher.match(u) for u in utterances]

    def compute_cumulative_token_savings(
        self,
        results: list[VoiceCommandMatchResult],
    ) -> int:
        """Calculate total estimated LLM tokens saved across routed utterances."""
        return sum(r.tokens_saved for r in results if r.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS)
