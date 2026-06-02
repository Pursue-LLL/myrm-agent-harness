"""LLM configuration — framework-agnostic model config.

Provides LLMConfig and CustomModelDef, usable by both agent/ and toolkits/
without any coupling to the agent runtime.
"""

import os
from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class CustomModelDef:
    """Custom model definition for self-hosted endpoints (Ollama/LM Studio/vLLM).

    Provides sensible defaults for model capabilities, enabling zero-config usage.

    Example:
        >>> custom_def = CustomModelDef(
        ...     model_id="ollama/llama3.2",
        ...     context_length=8192,
        ...     max_tokens=4096
        ... )
    """

    model_id: str
    context_length: int = 8192
    max_tokens: int = 4096
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_vision: bool = False
    supports_video: bool = False


class LLMConfig(BaseModel):
    """LLM configuration.

    Primary constructor accepts plain parameters (no env reads).
    Use ``from_env()`` for convenient environment variable initialization.

    Environment variables (MYRM_ prefix):
    - MYRM_MODEL_NAME: Model name (required)
    - MYRM_API_KEY: API key (required)
    - MYRM_BASE_URL: API base URL
    - MYRM_TEMPERATURE: Temperature parameter (default 0.2)
    - MYRM_STREAMING: Enable streaming (default true)
    - MYRM_MAX_CONTEXT_TOKENS: Max context window

    Example:
        >>> config = LLMConfig(model="gpt-4", api_key="sk-...", max_context_tokens=128000)
        >>> config = LLMConfig.from_env()
    """

    model: str = Field(..., description="Model name", min_length=1)
    api_key: str = Field(..., description="API key", min_length=1)
    base_url: str | None = Field(default=None, description="API base URL")
    temperature: float | None = Field(default=None, description="Temperature parameter")
    streaming: bool = Field(default=True, description="Enable streaming")
    model_kwargs: dict[str, object] | None = Field(
        default=None, description="Model-specific parameters"
    )
    max_context_tokens: int | None = Field(
        default=None,
        description="Context window size for dynamic compression and summary thresholds",
    )
    supports_vision: bool = Field(
        default=False, description="Whether the model supports vision/image input"
    )
    supports_video: bool = Field(
        default=False, description="Whether the model supports native video input (e.g. Gemini)"
    )
    custom_model_def: CustomModelDef | None = Field(
        default=None,
        description="Custom model definition for self-hosted endpoints (Ollama/LM Studio/vLLM)",
    )

    model_config = {
        "frozen": True,
    }

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Load config from MYRM_* environment variables.

        Raises:
            ValueError: If MYRM_MODEL_NAME or MYRM_API_KEY is not set
        """
        model = os.getenv("MYRM_MODEL_NAME")
        api_key = os.getenv("MYRM_API_KEY")

        if not model:
            raise ValueError("MYRM_MODEL_NAME environment variable is required")
        if not api_key:
            raise ValueError("MYRM_API_KEY environment variable is required")

        max_ctx_str = os.getenv("MYRM_MAX_CONTEXT_TOKENS")
        temp_str = os.getenv("MYRM_TEMPERATURE")
        return cls(
            model=model,
            api_key=api_key,
            base_url=os.getenv("MYRM_BASE_URL"),
            temperature=float(temp_str) if temp_str is not None else None,
            streaming=os.getenv("MYRM_STREAMING", "true").lower() == "true",
            max_context_tokens=int(max_ctx_str) if max_ctx_str else None,
        )
