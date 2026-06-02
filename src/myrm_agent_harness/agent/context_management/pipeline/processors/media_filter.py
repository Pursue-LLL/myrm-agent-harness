"""Proactive media filter processor.

Strips image / video / audio content from messages before sending to the LLM
when the target model does not support multimodal input, preventing 400 errors
and wasted API calls.

Decision logic (two sources, OR-combined):
1. Static config: ``supports_vision`` flag from LLMConfig (metadata)
2. Runtime learning: ``ModelCapabilityLearner`` records models that have
   previously rejected media at runtime (set by MEDIA_REJECTED recovery).

When media is stripped, an ``agent_status`` event is emitted so the frontend
can inform the user.

[INPUT]
- base::BaseProcessor, ProcessorContext (POS: processor base class)
- utils.image_utils (POS: image content detection & stripping)
- toolkits.llms.capability_learner (POS: runtime model capability cache)

[OUTPUT]
- MediaFilterProcessor: proactive media filter processor

[POS]
Proactive media filter processor. Strips multimodal content for text-only models.
"""

from __future__ import annotations

from myrm_agent_harness.utils.image_utils import (
    content_has_media,
    strip_all_media_from_content,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)

CAPABILITY_REJECTS_MEDIA = "rejects_media"
DEFAULT_RETAIN_MEDIA_BLOCKS = 2

class MediaFilterProcessor(BaseProcessor):
    """Proactively strip media content for models that cannot handle it.

    Positioned early in the pipeline (after ThinkingBlockCleaner) to
    prevent downstream processors from wasting effort on content that
    will be rejected by the LLM.

    The processor is a no-op when the model supports vision and has
    not previously rejected media at runtime.
    """

    @property
    def name(self) -> str:
        return "media_filter"

    async def should_process(self, context: ProcessorContext) -> bool:
        if self._should_skip_for_cache_preservation(context):
            return False

        # We now process EVERY request:
        # - Text-only models: strip ALL media
        # - Vision models: strip HISTORICAL media (save tokens)
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        stripped_count = 0

        supports_vision = context.metadata.get("supports_vision", True)
        rejects_media = False

        model_name = context.metadata.get("model_name")
        if model_name and isinstance(model_name, str):
            from myrm_agent_harness.toolkits.llms.capability_learner import (
                get_capability_learner,
            )

            learner = get_capability_learner()
            if learner.get(model_name, CAPABILITY_REJECTS_MEDIA, False):
                rejects_media = True

        strip_all = not supports_vision or rejects_media

        # Determine the safe tail boundary for historical media stripping.
        # We use a Sliding Visual Evidence Window: keep the last K=2 messages that contain media,
        # regardless of role (Human, Tool, etc.). This ensures Computer Use screenshots aren't stripped.
        safe_tail_start = len(context.messages)
        if not strip_all:
            keep_media_count = DEFAULT_RETAIN_MEDIA_BLOCKS
            for i in range(len(context.messages) - 1, -1, -1):
                content = getattr(context.messages[i], "content", None)
                if isinstance(content, list) and content_has_media(content):
                    keep_media_count -= 1
                    if keep_media_count == 0:
                        safe_tail_start = i
                        break
            if keep_media_count > 0:
                safe_tail_start = 0  # Keep all media if total media messages < K

        for i, msg in enumerate(context.messages):
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue

            if not content_has_media(content):
                continue

            # Strip if the model is text-only, OR if it's historical (before the safe tail boundary)
            if strip_all or i < safe_tail_start:
                new_content = strip_all_media_from_content(content)
                if new_content is not content:
                    msg.content = new_content  # type: ignore[assignment]
                    stripped_count += 1

        if stripped_count > 0:
            context.tokens_saved += (
                stripped_count * 500
            )  # conservative estimate per message

            if strip_all:
                logger.info(
                    "[MediaFilter] Stripped ALL media from %d message(s) for text-only model",
                    stripped_count,
                )
            else:
                logger.info(
                    "[MediaFilter] Stripped HISTORICAL media from %d message(s) to save tokens",
                    stripped_count,
                )

            runnable_config = context.metadata.get("runnable_config")
            try:
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                await dispatch_custom_event(
                    "agent_status",
                    {
                        "step_key": "media_stripped",
                        "stripped_count": stripped_count,
                    },
                    config=runnable_config,  # type: ignore[arg-type]
                )
            except Exception as exc:
                logger.debug("Failed to dispatch media_stripped event: %s", exc)

        return context
