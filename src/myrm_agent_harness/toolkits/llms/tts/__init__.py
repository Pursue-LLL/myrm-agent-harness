"""TTS (Text-to-Speech) generation module under llms media stack.

[OUTPUT]
- TTSConfig, TTSResult, TTSGenerationError, MediaMeta, MediaCallback
- AsyncTTSEngine: Core generation engine
- TTSTool, create_tts_tool: LangChain adapter

[POS]
Audio generation capability — symmetric with llms/image and llms/video.
Supports OpenAI and ElevenLabs with gateway routing and BYOK fallback.
"""

from .generator import AsyncTTSEngine
from .models import MediaCallback, MediaMeta, TTSConfig, TTSGenerationError, TTSResult
from .tts_langchain_tool import TTSTool, create_tts_tool

__all__ = [
    "AsyncTTSEngine",
    "MediaCallback",
    "MediaMeta",
    "TTSConfig",
    "TTSGenerationError",
    "TTSResult",
    "TTSTool",
    "create_tts_tool",
]
