"""
[INPUT]
- Voice transcript string
- VoiceScreenshotContext with raw/base64 screenshot
- VisualIntentDecision result

[OUTPUT]
- InjectedVoiceVisualTurn containing image payload and system grounding guidance

[POS]
Multimodal prompt injector and token cost estimator for voice visual context (Item 303).
Calculates tile-based token budgeting and formats standardized context payloads for LLM invocation.
"""

import math

from .voice_visual_types import (
    InjectedVoiceVisualTurn,
    VisualIntentCategory,
    VisualIntentDecision,
    VoiceScreenshotContext,
    VoiceVisualConfig,
)


class VoiceVisualContextInjector:
    """Formats and injects captured screen context into multimodal LLM requests."""

    _CATEGORY_PROMPTS: dict[VisualIntentCategory, str] = {
        VisualIntentCategory.ERROR_DIAGNOSIS: (
            "[Visual Context: Attached is the user's active screen/window at the time of speaking. "
            "Focus diagnosis on visible error messages, stack traces, console outputs, or warning dialogs.]"
        ),
        VisualIntentCategory.UI_ELEMENT_QUERY: (
            "[Visual Context: Attached is the user's active screen/window at the time of speaking. "
            "Identify the specific UI controls, buttons, forms, or visual layout components the user is pointing to.]"
        ),
        VisualIntentCategory.CODE_INSPECTION: (
            "[Visual Context: Attached is the user's active screen/window at the time of speaking. "
            "Inspect the code editor, terminal buffer, or diff view visible in the screenshot.]"
        ),
        VisualIntentCategory.GENERAL_SCREEN: (
            "[Visual Context: Attached is the user's active screen/window at the time of speaking. "
            "Ground your response in the visible screen state.]"
        ),
        VisualIntentCategory.NO_VISUAL_INTENT: "",
    }

    def __init__(self, config: VoiceVisualConfig | None = None) -> None:
        self._config = config or VoiceVisualConfig()

    def estimate_token_cost(self, width: int, height: int) -> int:
        """Estimate multimodal image token consumption using standard grid tiling."""
        if width <= 0 or height <= 0:
            return self._config.base_image_tokens

        tile_size = self._config.default_tile_size
        tiles_x = max(1, math.ceil(width / tile_size))
        tiles_y = max(1, math.ceil(height / tile_size))
        total_tiles = tiles_x * tiles_y

        return self._config.base_image_tokens + (total_tiles * self._config.tokens_per_tile)

    def inject(
        self,
        transcript: str,
        decision: VisualIntentDecision,
        screenshot: VoiceScreenshotContext | None = None,
    ) -> InjectedVoiceVisualTurn:
        """Construct multimodal turn envelope with screenshot attachment and guidance."""
        if not decision.has_visual_intent or screenshot is None or not screenshot.image_base64:
            return InjectedVoiceVisualTurn(
                user_transcript=transcript,
                has_image=False,
                category=decision.category,
                image_base64=None,
                mime_type="image/png",
                prompt_guidance="",
                estimated_tokens=0,
            )

        token_cost = (
            screenshot.estimated_token_cost
            if screenshot.estimated_token_cost > 0
            else self.estimate_token_cost(screenshot.width, screenshot.height)
        )

        guidance = self._CATEGORY_PROMPTS.get(
            decision.category,
            self._CATEGORY_PROMPTS[VisualIntentCategory.GENERAL_SCREEN],
        )

        if screenshot.window_title:
            guidance += f" [Active Window: {screenshot.window_title}]"

        return InjectedVoiceVisualTurn(
            user_transcript=transcript,
            has_image=True,
            category=decision.category,
            image_base64=screenshot.image_base64,
            mime_type=screenshot.mime_type,
            prompt_guidance=guidance,
            estimated_tokens=token_cost,
        )
