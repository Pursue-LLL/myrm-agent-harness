"""
[INPUT]
- Spoken voice transcript
- VoiceScreenshotContext optional screenshot payload
- VoiceVisualConfig configuration

[OUTPUT]
- VisualIntentDecision intent detection result
- InjectedVoiceVisualTurn complete multimodal context payload

[POS]
Main entry facade for VoiceScreenshotContextAwarenessSuite (Item 303).
Coordinates sub-millisecond visual intent detection, screenshot attachment,
and LLM multimodal grounding injection.
"""

from .voice_visual_detector import VoiceVisualIntentDetector
from .voice_visual_injector import VoiceVisualContextInjector
from .voice_visual_types import (
    InjectedVoiceVisualTurn,
    VisualIntentCategory,
    VisualIntentDecision,
    VoiceScreenshotContext,
    VoiceVisualConfig,
)


class VoiceScreenshotContextAwarenessSuite:
    """Unified facade coordinating voice utterance visual intent awareness and screenshot injection."""

    def __init__(self, config: VoiceVisualConfig | None = None) -> None:
        self._config = config or VoiceVisualConfig()
        self._detector = VoiceVisualIntentDetector(self._config)
        self._injector = VoiceVisualContextInjector(self._config)

    @property
    def config(self) -> VoiceVisualConfig:
        return self._config

    def detect_intent(self, transcript: str) -> VisualIntentDecision:
        """Heuristically detect if spoken utterance references visible screen context."""
        return self._detector.detect(transcript)

    def estimate_image_token_cost(self, width: int, height: int) -> int:
        """Estimate token cost for a screenshot of given dimensions."""
        return self._injector.estimate_token_cost(width, height)

    def format_visual_turn(
        self,
        transcript: str,
        decision: VisualIntentDecision,
        screenshot: VoiceScreenshotContext | None = None,
    ) -> InjectedVoiceVisualTurn:
        """Format utterance and screenshot into a standardized multimodal turn."""
        return self._injector.inject(transcript, decision, screenshot)

    def process_voice_turn(
        self,
        transcript: str,
        screenshot: VoiceScreenshotContext | None = None,
    ) -> InjectedVoiceVisualTurn:
        """End-to-end evaluation: detect visual intent and inject screenshot if needed."""
        decision = self.detect_intent(transcript)
        return self.format_visual_turn(transcript, decision, screenshot)
