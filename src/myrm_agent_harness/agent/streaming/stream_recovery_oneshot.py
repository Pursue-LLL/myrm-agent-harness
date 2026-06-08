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

        Triggered by provider per-image size limits (e.g. Anthropic 5 MB).
        Only processes data: URLs; http URLs are fetched server-side and
        are not subject to this limit.
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

        shrunk = _shrink_oversized_images(messages)
        if shrunk == 0:
            return False

        logger.warning(
            " Image(s) exceeded provider size limit — shrank %d image(s), retrying",
            shrunk,
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


def _shrink_oversized_images(messages: list[BaseMessage]) -> int:
    """Walk messages and shrink base64 images exceeding threshold.

    Returns the number of images actually replaced.
    """
    from myrm_agent_harness.utils.image_utils import (
        estimate_base64_byte_size,
        is_base64_data_url,
    )
    from myrm_agent_harness.utils.media.image_compressor import ImageCompressor

    shrunk_count = 0

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
            if original_size <= _IMAGE_SHRINK_THRESHOLD:
                continue

            try:
                import base64

                header, b64_data = url.split(";base64,", 1)
                raw_bytes = base64.b64decode(b64_data)
                compressor = ImageCompressor()
                compressed = compressor.compress(raw_bytes, max_bytes=_IMAGE_SHRINK_THRESHOLD)

                if len(compressed) >= original_size:
                    continue

                new_b64 = base64.b64encode(compressed).decode("ascii")
                new_url = f"{header};base64,{new_b64}"
                image_url["url"] = new_url
                shrunk_count += 1
            except Exception as shrink_err:
                logger.warning("Image shrink failed for part %d: %s", idx, shrink_err)

    return shrunk_count
