"""Vision fallback processor — convert message media blocks to text before MediaFilter.

When the primary model is text-only but visionFallbackModel is configured, replaces
image blocks in HumanMessage / ToolMessage content with VisionFallbackEngine descriptions
instead of letting MediaFilterProcessor strip them silently.

[INPUT]
- base::BaseProcessor, ProcessorContext
- toolkits.llms.vision.fallback_engine::VisionFallbackEngine
- processors.media_resolver::resolve_image_reference_to_data_url
- utils.image_utils (media detection helpers)

[OUTPUT]
- VisionFallbackProcessor
- apply_vision_fallback_to_messages (shared with stream recovery)

[POS]
Runs immediately before MediaFilterProcessor in the default pipeline chain.
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

from myrm_agent_harness.toolkits.llms.vision.fallback_engine import create_vision_fallback_engine
from myrm_agent_harness.utils.image_utils import (
    content_has_media,
    get_image_url,
    is_base64_data_url,
    is_image_content_item,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..base import BaseProcessor, ProcessorContext
from .media_resolver import FileContentReader, resolve_image_reference_to_data_url

logger = get_agent_logger(__name__)

_VISION_TEXT_PREFIX = "[Image Analysis]:\n"


def _message_text_snippet(content: object) -> str | None:
    if isinstance(content, str) and content.strip():
        return content.strip()
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    if not parts:
        return None
    return "\n".join(parts)


def _find_adjacent_user_prompt(messages: list[BaseMessage], index: int) -> str | None:
    for i in range(index - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, HumanMessage):
            return _message_text_snippet(msg.content)
    return None


def _resolve_vision_prompt(
    messages: list[BaseMessage],
    index: int,
    msg: BaseMessage,
) -> str | None:
    adjacent = _find_adjacent_user_prompt(messages, index)
    if isinstance(msg, ToolMessage) and adjacent:
        return adjacent
    same_message = _message_text_snippet(getattr(msg, "content", None))
    return same_message or adjacent


def _data_url_to_b64_mime(data_url: str) -> tuple[str, str] | None:
    if not is_base64_data_url(data_url):
        return None
    try:
        header, b64_data = data_url.split(";base64,", 1)
        mime_type = header.split(":", 1)[1]
    except (IndexError, ValueError):
        return None
    return b64_data, mime_type


async def _image_item_to_b64_mime(
    item: dict[str, object],
    *,
    file_content_reader: FileContentReader | None = None,
) -> tuple[str, str] | None:
    if not is_image_content_item(item):
        return None

    item_type = item.get("type")
    if item_type == "image_url":
        url = get_image_url(item)
        if not url:
            return None
        if is_base64_data_url(url):
            return _data_url_to_b64_mime(url)
        resolved = await resolve_image_reference_to_data_url(
            url,
            file_content_reader=file_content_reader,
        )
        if resolved is None:
            return None
        return _data_url_to_b64_mime(resolved)

    raw_b64 = item.get("base64")
    if raw_b64 is None:
        raw_b64 = item.get("data")
    if not isinstance(raw_b64, str) or not raw_b64.strip():
        return None

    mime_raw = item.get("mime_type") or item.get("media_type") or "image/png"
    mime_type = str(mime_raw) if mime_raw else "image/png"
    return raw_b64.strip(), mime_type


async def apply_vision_fallback_to_messages(
    messages: list[BaseMessage],
    vision_fallback_model_cfg: object,
    *,
    supports_vision: bool,
    file_content_reader: FileContentReader | None = None,
    vision_fallback_model_cfgs: object | None = None,
) -> int:
    """Convert media blocks to vision-fallback text. Returns number of messages updated."""
    if supports_vision or (
        vision_fallback_model_cfg is None and vision_fallback_model_cfgs is None
    ):
        return 0

    engine = create_vision_fallback_engine(
        vision_fallback_model_cfg,
        vision_fallback_model_cfgs,
    )
    if engine is None:
        return 0
    converted = 0

    for index, msg in enumerate(messages):
        content = getattr(msg, "content", None)
        if not isinstance(content, list) or not content_has_media(content):
            continue

        user_prompt = _resolve_vision_prompt(messages, index, msg)
        new_items: list[str | dict[str, object]] = []
        changed = False

        for item in content:
            if isinstance(item, dict):
                payload = await _image_item_to_b64_mime(
                    item,
                    file_content_reader=file_content_reader,
                )
                if payload is not None:
                    b64_data, mime_type = payload
                    try:
                        description = await engine.describe_image_b64(
                            b64_data,
                            mime_type,
                            prompt=user_prompt,
                        )
                        new_items.append(
                            {
                                "type": "text",
                                "text": f"{_VISION_TEXT_PREFIX}{description}",
                            }
                        )
                        changed = True
                        continue
                    except Exception as exc:
                        logger.warning(
                            "[VisionFallbackProcessor] Failed to describe image block: %s",
                            exc,
                        )
            new_items.append(item)

        if changed:
            msg.content = new_items  # type: ignore[assignment]
            converted += 1

    return converted


class VisionFallbackProcessor(BaseProcessor):
    """Convert surviving media blocks to text via VisionFallbackEngine."""

    def __init__(self, file_content_reader: FileContentReader | None = None) -> None:
        self._file_content_reader = file_content_reader

    @staticmethod
    def _resolve_file_content_reader(context: ProcessorContext) -> FileContentReader | None:
        reader = context.metadata.get("file_content_reader")
        if callable(reader):
            return reader  # type: ignore[return-value]
        merged_reader = context.merged_context.get("file_content_reader")
        if callable(merged_reader):
            return merged_reader  # type: ignore[return-value]
        return None

    @property
    def name(self) -> str:
        return "vision_fallback"

    async def should_process(self, context: ProcessorContext) -> bool:
        if self._should_skip_for_cache_preservation(context):
            return False
        supports_vision = bool(context.metadata.get("supports_vision", True))
        if supports_vision:
            return False
        vision_cfg = context.metadata.get("vision_fallback_model_cfg")
        if vision_cfg is None:
            vision_cfg = context.merged_context.get("vision_fallback_model_cfg")
        vision_cfgs = context.metadata.get("vision_fallback_model_cfgs")
        if vision_cfgs is None:
            vision_cfgs = context.merged_context.get("vision_fallback_model_cfgs")
        return vision_cfg is not None or vision_cfgs is not None

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        vision_cfg = context.metadata.get("vision_fallback_model_cfg")
        if vision_cfg is None:
            vision_cfg = context.merged_context.get("vision_fallback_model_cfg")
        vision_cfgs = context.metadata.get("vision_fallback_model_cfgs")
        if vision_cfgs is None:
            vision_cfgs = context.merged_context.get("vision_fallback_model_cfgs")
        if vision_cfg is None and vision_cfgs is None:
            return context

        supports_vision = bool(context.metadata.get("supports_vision", True))
        file_content_reader = self._file_content_reader or self._resolve_file_content_reader(context)
        converted = await apply_vision_fallback_to_messages(
            context.messages,
            vision_cfg if vision_cfg is not None else vision_cfgs,
            supports_vision=supports_vision,
            file_content_reader=file_content_reader,
            vision_fallback_model_cfgs=vision_cfgs,
        )
        if converted > 0:
            context.operations.append("vision_fallback")
            logger.info(
                "[VisionFallbackProcessor] Converted media in %d message(s) via auxiliary vision model",
                converted,
            )
        return context
