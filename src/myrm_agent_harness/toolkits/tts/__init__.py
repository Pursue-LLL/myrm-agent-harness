"""TTS (Text-to-Speech) Toolkit.

[OUTPUT]
- TTSConfig: Configuration model
- TTSTool: LangChain tool
- AsyncTTSEngine: Core generation engine

[POS]
Provides text-to-speech capabilities for agents, supporting
OpenAI and ElevenLabs with gateway routing.
"""

from .generator import AsyncTTSEngine
from .models import TTSConfig, TTSGenerationError, TTSResult
from .tts_tool import TTSTool

__all__ = [
    "AsyncTTSEngine",
    "TTSConfig",
    "TTSGenerationError",
    "TTSResult",
    "TTSTool",
]
