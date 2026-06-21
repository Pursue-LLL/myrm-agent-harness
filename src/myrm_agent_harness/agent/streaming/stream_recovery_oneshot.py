"""One-shot error recovery handlers for specific LLM error types.

Provides targeted recovery strategies that attempt a single fix and retry,
without entering backoff or failover loops.

[INPUT]
- toolkits.llms.errors.classifier (POS: 错误分类)
- toolkits.llms.errors.error_types (POS: 三层错误类型定义)
- agent._internals.agent_recovery (POS: 消息压缩/截断工具)

[OUTPUT]
- OneshotRecoveryMixin: One-shot recovery handlers mixed into StreamRecoveryMixin

[POS]
Targeted one-shot recovery handlers for THINKING_SIGNATURE, IMAGE_TOO_LARGE,
MEDIA_REJECTED, and LONG_CONTEXT_TIER errors. Includes model name resolution
via llm_info for capability learning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from langgraph.types import Command

from myrm_agent_harness.agent._internals.agent_recovery import (
    emergency_compact as _emergency_compact,
)
from myrm_agent_harness.agent._internals.agent_recovery import (
    truncate_oldest_rounds as _truncate_oldest_rounds,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.toolkits.llms.errors.classifier import classify_failover_reason
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.agent.streaming.stream_compactor import StreamCompactor
    from myrm_agent_harness.agent.streaming.stream_executor import StreamContext

logger = get_agent_logger(__name__)

_IMAGE_SHRINK_THRESHOLD = 4 * 1024 * 1024  # 4 MB — safe margin under Anthropic 5 MB
_THINKING_BLOCK_TYPES = frozenset(("thinking", "redacted_thinking"))


class OneshotRecoveryMixin:
    """One-shot recovery handlers for specific error types.

    Provides targeted fix-and-retry strategies that should be attempted
    before generic overflow/failover/transient handlers.

    All methods access StreamExecutor attrs via self:
    _ctx, _compactor, streaming_final_answer
    """

    _ctx: StreamContext
    _compactor: StreamCompactor
    streaming_final_answer: bool

    async def _handle_thinking_signature(self, exc: Exception, attempted: bool) -> bool:
        """Strip all thinking-related content from messages and retry once.

        Anthropic signs thinking blocks against the full turn content.
        Context compression or message truncation invalidates the signature,
        causing HTTP 400.  Recovery: remove all thinking/reasoning content
        (thinking, redacted_thinking blocks in content; reasoning_content
        and thinking_blocks in additional_kwargs) and retry.
        """
        if attempted:
            return False
        reason = classify_failover_reason(exc)
        if reason != FailoverReason.THINKING_SIGNATURE:
            return False

        from langchain_core.messages import AIMessage

        ctx = self._ctx
        if isinstance(ctx.agent_input, Command):
            return False

        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))

        stripped = 0
        for msg in messages:
            if not isinstance(msg, AIMessage):
                continue
            content = msg.content
            if isinstance(content, list):
                new_content = [b for b in content if not (isinstance(b, dict) and b.get("type") in _THINKING_BLOCK_TYPES)]
                if len(new_content) != len(content):
                    msg.content = new_content  # type: ignore[assignment]
                    stripped += 1
            kwargs: dict[str, object] = msg.additional_kwargs or {}
            if "reasoning_content" in kwargs:
                del kwargs["reasoning_content"]
                stripped += 1
            if "thinking_blocks" in kwargs:
                del kwargs["thinking_blocks"]
                stripped += 1

        if stripped == 0:
            return False

        logger.warning(
            " Thinking signature invalid — stripped %d thinking blocks, retrying",
            stripped,
        )
        await self._emit_recovery_event("thinking_signature_recovery")
        self.streaming_final_answer = False
        return True

    async def _handle_image_shrink(self, exc: Exception, attempted: bool) -> bool:
        """Shrink oversized base64 images in-place and retry once.

        Triggered by provider per-image byte/dimension limits
        (e.g. Anthropic 5 MB / 8000px per side, 2000px in multi-image).
        Only processes data: URLs; http URLs are fetched server-side.

        Parses provider-reported max_dimension from the error message so
        pixel-only oversized images (e.g. Retina screenshots tiny in bytes
        but exceeding the dimension cap) are also recovered.
        """
        if attempted:
            return False
        reason = classify_failover_reason(exc)
        if reason != FailoverReason.IMAGE_TOO_LARGE:
            return False

        ctx = self._ctx
        if isinstance(ctx.agent_input, Command):
            return False

        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))

        max_dim = _parse_image_max_dimension(exc)
        shrunk = _shrink_oversized_images(messages, max_dimension=max_dim)
        if shrunk == 0:
            return False

        logger.warning(
            " Image(s) exceeded provider limit — shrank %d image(s) (max_dimension=%s), retrying",
            shrunk,
            max_dim,
        )
        await self._emit_recovery_event("image_shrink_recovery")
        self.streaming_final_answer = False
        return True

    async def _handle_media_rejected(self, exc: Exception, attempted: bool) -> bool:
        """Strip all media from messages and retry once.

        Triggered when the model rejects multimodal input entirely
        (e.g., sending images to a text-only model). Records the
        capability via ModelCapabilityLearner so that subsequent
        requests proactively skip media via MediaFilterProcessor.
        """
        if attempted:
            return False
        reason = classify_failover_reason(exc)
        if reason != FailoverReason.MEDIA_REJECTED:
            return False

        ctx = self._ctx
        if isinstance(ctx.agent_input, Command):
            return False

        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))

        stripped = _strip_all_media_from_messages(messages)
        if stripped == 0:
            return False

        model_name = _resolve_model_name_from_ctx(ctx)
        merged_ctx = getattr(ctx, "merged_context", None)
        supports_vision = bool(merged_ctx.get("supports_vision", True)) if isinstance(merged_ctx, dict) else True
        if supports_vision:
            logger.warning(
                "Model marked supports_vision but rejected multimodal input. "
                "Capability flag may be inaccurate (model=%s).",
                model_name or "unknown",
            )

        if model_name:
            from myrm_agent_harness.toolkits.llms.capability_learner import (
                get_capability_learner,
            )

            learner = get_capability_learner()
            learner.learn(str(model_name), "rejects_media", True)
            logger.info(
                "Learned: model %s rejects media — future requests will proactively strip",
                model_name,
            )

        logger.warning(
            " Model rejected multimodal input — stripped media from %d message(s), retrying",
            stripped,
        )
        await self._emit_recovery_event("media_rejected_recovery", stripped_count=stripped)
        self.streaming_final_answer = False
        return True

    async def _handle_long_context_tier(self, exc: Exception) -> bool:
        """Handle Anthropic subscription tier gate by compressing context.

        HTTP 429 "Extra usage is required for long context requests" is NOT
        a transient rate limit — backoff retries will always fail.  Instead,
        trigger context compression to reduce below the 200k standard tier.
        """
        reason = classify_failover_reason(exc)
        if reason != FailoverReason.LONG_CONTEXT_TIER:
            return False

        ctx = self._ctx
        if isinstance(ctx.agent_input, Command):
            return False

        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))

        saved = await _emergency_compact(messages)
        if saved == 0:
            saved = _truncate_oldest_rounds(messages)

        logger.warning(
            " Long-context tier gate — compressed context (freed %d tokens), retrying",
            saved,
        )
        await self._emit_recovery_event("long_context_tier_recovery")
        self.streaming_final_answer = False
        return True

    async def _emit_recovery_event(self, step_key: str, **extra: object) -> None:
        """Emit a STATUS event for recovery actions."""
        event: dict[str, object] = {
            "type": AgentEventType.STATUS.value,
            "step_key": step_key,
            "tool_name": None,
            "messageId": self._ctx.message_id,
        }
        event.update(extra)
        await self._compactor.put(event)


def _resolve_model_name_from_ctx(ctx: object) -> str | None:
    """Resolve model name from StreamContext (llm_info first, then merged_context)."""
    llm_info = getattr(ctx, "llm_info", None)
    if isinstance(llm_info, dict):
        name = llm_info.get("model_name")
        if name:
            return str(name)

    merged_ctx = getattr(ctx, "merged_context", None)
    if isinstance(merged_ctx, dict):
        name = merged_ctx.get("model_name")
        if name:
            return str(name)

    return None


def _strip_all_media_from_messages(messages: list[BaseMessage]) -> int:
    """Walk messages and replace all media items with text placeholders.

    Returns the number of messages that had media stripped.
    """
    from myrm_agent_harness.utils.image_utils import (
        content_has_media,
        strip_all_media_from_content,
    )

    stripped_count = 0
    for msg in messages:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        if not content_has_media(content):
            continue
        new_content = strip_all_media_from_content(content)
        if new_content is not content:
            msg.content = new_content  # type: ignore[assignment]
            stripped_count += 1
    return stripped_count


import re as _re

_IMAGE_MAX_DIM_RE = _re.compile(
    r"(?:maximum|max).*?(?:allowed\s+)?size.*?(\d{3,5})"
    r"|(\d{3,5})\s*(?:px|pixels?)?\s*(?:per[- ]?side|limit|maximum|cap)",
    _re.IGNORECASE,
)

_DEFAULT_MAX_DIMENSION = 8000


def _parse_image_max_dimension(exc: Exception) -> int:
    """Extract provider-reported dimension ceiling from error message.

    Anthropic reports e.g. "maximum allowed size of 2000" or
    "exceeds the maximum of 8000px per side".  Returns the parsed
    integer or ``_DEFAULT_MAX_DIMENSION`` when not parseable.
    """
    from myrm_agent_harness.toolkits.llms.errors.classifier import (
        normalize_provider_error,
    )

    msg = normalize_provider_error(exc).message
    match = _IMAGE_MAX_DIM_RE.search(msg)
    if match:
        value = int(match.group(1) or match.group(2))
        if 64 <= value <= 32768:
            return value
    return _DEFAULT_MAX_DIMENSION


def _shrink_oversized_images(
    messages: list[BaseMessage],
    *,
    max_dimension: int = _DEFAULT_MAX_DIMENSION,
) -> int:
    """Walk messages and shrink base64 images exceeding byte/dimension limits.

    Checks **both** byte size (against ``_IMAGE_SHRINK_THRESHOLD``) and pixel
    dimensions (against ``max_dimension``).  Uses a ``triggered_by`` mechanism
    to validate the correct constraint after resize — a pixel-correct downscale
    is accepted even if its bytes grew (PNG re-encode can increase bytes).

    Returns the number of images actually replaced.  Returns 0 if any image
    was oversized but could not be shrunk (unshrinkable), because retrying
    would re-send the same rejected payload.
    """
    import base64
    import io

    from myrm_agent_harness.utils.image_utils import (
        estimate_base64_byte_size,
        is_base64_data_url,
    )
    from myrm_agent_harness.utils.media.image_compressor import ImageCompressor

    shrunk_count = 0
    unshrinkable_count = 0
    compressor = ImageCompressor()

    for msg in messages:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for idx, part in enumerate(content):
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if not isinstance(image_url, dict):
                continue
            url = image_url.get("url", "")
            if not isinstance(url, str) or not is_base64_data_url(url):
                continue

            original_size = estimate_base64_byte_size(url)
            over_bytes = original_size > _IMAGE_SHRINK_THRESHOLD

            dims = _decode_image_dimensions(url)
            over_pixels = dims is not None and max(dims) > max_dimension

            if not over_bytes and not over_pixels:
                continue

            triggered_by = "bytes" if over_bytes else "dimension"

            try:
                header, b64_data = url.split(";base64,", 1)
                raw_bytes = base64.b64decode(b64_data)
                compressed = compressor.compress(
                    io.BytesIO(raw_bytes),
                    quality=0.5,
                    max_dimension=max_dimension,
                )
                if compressed is None:
                    unshrinkable_count += 1
                    continue

                if triggered_by == "bytes" and len(compressed) >= original_size:
                    unshrinkable_count += 1
                    continue

                new_dims = _decode_bytes_dimensions(compressed)
                if new_dims is not None and max(new_dims) > max_dimension:
                    unshrinkable_count += 1
                    continue

                new_b64 = base64.b64encode(compressed).decode("ascii")
                new_url = f"{header};base64,{new_b64}"
                image_url["url"] = new_url
                shrunk_count += 1
            except Exception as shrink_err:
                logger.warning("Image shrink failed for part %d: %s", idx, shrink_err)
                unshrinkable_count += 1

    if unshrinkable_count > 0:
        logger.warning(
            "Image shrink: %d part(s) could not be shrunk — not retrying",
            unshrinkable_count,
        )
        return 0

    return shrunk_count


def _decode_image_dimensions(data_url: str) -> tuple[int, int] | None:
    """Decode pixel dimensions (width, height) from a base64 data URL."""
    import base64
    import io

    try:
        from PIL import Image

        _, b64_data = data_url.split(";base64,", 1)
        with Image.open(io.BytesIO(base64.b64decode(b64_data))) as img:
            return img.size
    except Exception:
        return None


def _decode_bytes_dimensions(raw_bytes: bytes) -> tuple[int, int] | None:
    """Decode pixel dimensions (width, height) from raw image bytes."""
    import io

    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw_bytes)) as img:
            return img.size
    except Exception:
        return None
