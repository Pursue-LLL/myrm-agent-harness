"""
[INPUT]
- Audio transcript text from voice recognition
- Optional raw screenshot payload (base64 or bytes)

[OUTPUT]
- VisualIntentDecision (category, confidence, matched triggers)
- VoiceScreenshotContext (image dimensions, mime type, token cost estimation)
- InjectedVoiceVisualTurn (multimodal payload formatted for LLM consumption)

[POS]
Type definitions and data models for VoiceScreenshotContextAwarenessSuite (Item 303).
Governs visual trigger categorization, heuristic confidence scoring, and multimodal prompt contracts.
"""

from dataclasses import dataclass, field
from enum import Enum


class VisualIntentCategory(str, Enum):
    """Categorization of user's visual reference intention in spoken commands."""

    ERROR_DIAGNOSIS = "error_diagnosis"      # e.g., "这个报错怎么解决", "why this stacktrace"
    UI_ELEMENT_QUERY = "ui_element_query"    # e.g., "这个按钮点了没反应", "what is this icon"
    CODE_INSPECTION = "code_inspection"      # e.g., "看下这段代码有什么问题", "review this function"
    GENERAL_SCREEN = "general_screen"        # e.g., "当前屏幕上有什么", "look at my screen", "这里怎么弄"
    NO_VISUAL_INTENT = "no_visual_intent"    # Pure speech command without screen context


@dataclass(frozen=True)
class VisualIntentDecision:
    """Heuristic visual intent classification result."""

    has_visual_intent: bool
    category: VisualIntentCategory
    confidence: float
    matched_triggers: list[str]
    clean_text: str


@dataclass(frozen=True)
class VoiceScreenshotContext:
    """Standardized representation of a captured screenshot associated with voice query."""

    image_base64: str
    mime_type: str = "image/png"
    width: int = 1920
    height: int = 1080
    timestamp: float = 0.0
    window_title: str | None = None
    estimated_token_cost: int = 0


@dataclass(frozen=True)
class InjectedVoiceVisualTurn:
    """Multimodal turn structure injected into LLM context."""

    user_transcript: str
    has_image: bool
    category: VisualIntentCategory
    image_base64: str | None = None
    mime_type: str = "image/png"
    prompt_guidance: str = ""
    estimated_tokens: int = 0


@dataclass(frozen=True)
class VoiceVisualConfig:
    """Configuration options for voice screenshot context awareness."""

    enabled: bool = True
    min_confidence_threshold: float = 0.5
    default_tile_size: int = 512
    base_image_tokens: int = 85
    tokens_per_tile: int = 170
    custom_triggers: list[str] = field(default_factory=list)
