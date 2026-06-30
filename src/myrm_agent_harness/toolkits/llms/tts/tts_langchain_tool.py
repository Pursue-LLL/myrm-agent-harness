"""LangChain BaseTool wrapper for AsyncTTSEngine.

[INPUT]
- langchain_core.tools::BaseTool (POS: LangChain tool base class)
- pydantic::BaseModel, Field (POS: Tool input schema)
- .generator::AsyncTTSEngine (POS: TTS engine)
- .models::TTSConfig (POS: Config)

[OUTPUT]
- TTSTool: LangChain tool for text-to-speech generation
- create_tts_tool: factory returning a configured TTSTool

[POS]
Bridges AsyncTTSEngine to SkillAgent registry which requires BaseTool.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from myrm_agent_harness.core.artifacts.constants import ArtifactType

from .generator import AsyncTTSEngine
from .models import TTSConfig

logger = logging.getLogger(__name__)

ArtifactPushFn = Callable[[str, str, ArtifactType, str], None]


class TTSInput(BaseModel):
    """Input schema for TTS tool."""

    text: str = Field(..., description="The text to convert to speech. Should be plain text.")


class TTSTool(BaseTool):
    """Tool for generating speech from text."""

    name: str = "tts_generate"
    description: str = (
        "Generate speech (audio) from text. Use this when the user asks you to read something out loud "
        "or generate a voice message."
    )
    args_schema: type[BaseModel] = TTSInput

    config: TTSConfig = Field(exclude=True)
    _engine: AsyncTTSEngine = PrivateAttr()
    _on_artifact_created: ArtifactPushFn | None = PrivateAttr(default=None)

    def __init__(
        self,
        config: TTSConfig,
        *,
        on_artifact_created: ArtifactPushFn | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(config=config, **kwargs)
        self._engine = AsyncTTSEngine(config)
        self._on_artifact_created = on_artifact_created

    def _run(
        self,
        text: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        """Synchronous run is not supported."""
        raise NotImplementedError("TTSTool only supports async execution.")

    async def _arun(
        self,
        text: str,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        """Asynchronously generate speech."""
        try:
            result = await self._engine.generate(text)

            out: dict[str, object] = {
                "status": "success",
                "provider": result.provider,
                "model": result.model,
                "latency_ms": round(result.latency_ms),
            }
            if result.persisted_url:
                out["audio_url"] = result.persisted_url
                out["message"] = f"Successfully generated audio. URL: {result.persisted_url}"
                self._push_artifact(result)
            else:
                out["message"] = "Successfully generated audio, but failed to persist to URL."

            return json.dumps(out, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    def _push_artifact(self, result: Any) -> None:
        """Notify caller about the generated artifact via callback."""
        if not self._on_artifact_created:
            return
        url = result.persisted_url
        if not url:
            return
        from myrm_agent_harness.utils.mime_types import extension_for_mime

        ext = extension_for_mime(result.mime_type)
        try:
            self._on_artifact_created(
                f"generated_{result.model}.{ext}",
                url,
                ArtifactType.AUDIO,
                result.mime_type,
            )
        except Exception as exc:
            logger.debug("Artifact push callback failed: %s", exc)


def create_tts_tool(
    config: TTSConfig,
    *,
    on_artifact_created: ArtifactPushFn | None = None,
) -> TTSTool:
    """Wrap an AsyncTTSEngine config as a LangChain tool named ``tts_generate``."""
    return TTSTool(config, on_artifact_created=on_artifact_created)
