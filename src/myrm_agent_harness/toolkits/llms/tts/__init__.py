"""TTS (Text-to-Speech) generation module under llms media stack.

[OUTPUT]
- TTSConfig, TTSResult, TTSGenerationError, MediaMeta, MediaCallback
- AsyncTTSEngine: Core generation engine

[POS]
Audio generation capability — symmetric with llms/image and llms/video.
Supports OpenAI and ElevenLabs with gateway routing and BYOK fallback.
LangChain adapters live in myrm-agent-server/app/ai_agents/media_tools/.
"""

from .generator import AsyncTTSEngine
from .models import MediaCallback, MediaMeta, TTSConfig, TTSGenerationError, TTSResult

__all__ = [
    "AsyncTTSEngine",
    "MediaCallback",
    "MediaMeta",
    "TTSConfig",
    "TTSGenerationError",
    "TTSResult",
]
