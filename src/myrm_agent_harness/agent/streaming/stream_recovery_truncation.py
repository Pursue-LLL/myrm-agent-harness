"""Streaming length truncation recovery mixin.

[INPUT]
- toolkits.llms.ephemeral_output_tokens (POS: ephemeral max-output-tokens ContextVar)
- agent.streaming.types::AgentEventType (POS: streaming event type constants)
- agent.errors.diagnostics::LLMErrorDiagnostic (POS: LLM truncation diagnostic builder)
- toolkits.llms.token_economics.tracker::get_token_tracker (POS: token finish-reason tracker)

[OUTPUT]
- StreamTruncationRecoveryMixin: handles length/max-token continuation, truncated tool-call retry, and truncation warnings.
- ephemeral_max_output_tokens: ContextVar for per-request output token override.
- get_ephemeral_max_output_tokens / set_ephemeral_max_output_tokens / reset_ephemeral_max_output_tokens: accessors.

[POS]
Streaming truncation recovery layer. Detects length-truncated responses, injects safe
continuation prompts with progressive output budget boosting, auto-retries truncated
tool calls, and emits structured truncation warnings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.toolkits.llms.ephemeral_output_tokens import (
    MAX_EPHEMERAL_OUTPUT_TOKENS,
    ephemeral_max_output_tokens,
    get_ephemeral_max_output_tokens,
    reset_ephemeral_max_output_tokens,
    set_ephemeral_max_output_tokens,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.messages import AnyMessage, BaseMessage

    from myrm_agent_harness.agent.streaming.stream_compactor import StreamCompactor
    from myrm_agent_harness.agent.streaming.stream_executor import StreamContext

logger = get_agent_logger(__name__)

_MAX_EPHEMERAL_OUTPUT_TOKENS = MAX_EPHEMERAL_OUTPUT_TOKENS


class StreamTruncationRecoveryMixin:

    _ctx: StreamContext
    _compactor: StreamCompactor
    streaming_final_answer: bool
    _tool_truncation_retries: int
    _MAX_LENGTH_CONTINUE_RETRIES = 3
    _MAX_TOOL_TRUNCATION_RETRIES = 1

    async def _handle_length_truncation(
        self,
        collected_messages: list[BaseMessage],
        retries: int = 0,
    ) -> bool:
        """Detect length truncation and either auto-continue or emit warnings."""
        from langchain_core.messages import AIMessage

        from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

        tracker = get_token_tracker()
        if not tracker or tracker.last_finish_reason not in ("length", "max_tokens"):
            return False

        last_ai_msg: AIMessage | None = None
        for msg in reversed(collected_messages):
            if isinstance(msg, AIMessage):
                last_ai_msg = msg
                break

        if last_ai_msg is None:
            return False

        has_tool_calls = bool(last_ai_msg.tool_calls)
        has_content = self._has_non_reasoning_content(last_ai_msg)
        has_reasoning = self._has_reasoning_content(last_ai_msg)

        ctx = self._ctx
        locale = ctx.merged_context.get("locale", "en") if ctx.merged_context else "en"

        if has_content and not has_tool_calls:
            return await self._try_text_continuation(
                collected_messages,
                retries,
                locale,
            )

        if has_tool_calls:
            return await self._try_tool_call_retry(
                collected_messages,
                locale,
            )

        if has_reasoning and not has_content:
            truncation_type = "thinking_budget_exhausted"
        else:
            return False

        await self._emit_truncation_warning(truncation_type, locale)
        return False

    async def _try_text_continuation(
        self,
        collected_messages: list[BaseMessage],
        retries: int,
        locale: str,
    ) -> bool:
        """Inject a continuation prompt and signal the outer loop to retry astream."""
        ctx = self._ctx

        if retries >= self._MAX_LENGTH_CONTINUE_RETRIES:
            logger.warning(
                " Text continuation exhausted after %d retries",
                retries,
            )
            reset_ephemeral_max_output_tokens()
            await self._emit_truncation_warning("text_continuation_exhausted", locale)
            return False

        if isinstance(ctx.agent_input, Command):
            logger.warning(" Resume mode — text continuation not supported")
            return False

        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))
        messages.clear()
        messages.extend(collected_messages)

        continuation_prompt = (
            "[System: Your previous response was truncated by the output length limit. "
            "Continue exactly where you left off. Do not restart or repeat prior text. "
            "Finish the answer directly.]"
        )
        messages.append(HumanMessage(content=continuation_prompt))
        messages_dict["messages"] = cast("list[AnyMessage]", messages)
        self.streaming_final_answer = False

        self._boost_output_tokens(retries)

        logger.warning(
            "↻ Text continuation (%d/%d)...",
            retries + 1,
            self._MAX_LENGTH_CONTINUE_RETRIES,
        )

        await self._emit_truncation_warning("text_continuation", locale)
        return True

    async def _try_tool_call_retry(
        self,
        collected_messages: list[BaseMessage],
        locale: str,
    ) -> bool:
        """Discard the truncated AI message, boost output budget, and signal retry.

        Only retries once to avoid infinite loops.
        """
        from langchain_core.messages import AIMessage

        ctx = self._ctx
        if isinstance(ctx.agent_input, Command):
            logger.warning(" Resume mode — tool-call truncation retry not supported")
            await self._emit_truncation_warning("tool_call_truncated", locale)
            return False

        tool_truncation_retries = self._tool_truncation_retries
        if tool_truncation_retries >= self._MAX_TOOL_TRUNCATION_RETRIES:
            logger.warning(
                " Tool-call truncation retry exhausted (%d/%d)",
                tool_truncation_retries,
                self._MAX_TOOL_TRUNCATION_RETRIES,
            )
            reset_ephemeral_max_output_tokens()
            await self._emit_truncation_warning("tool_call_truncated", locale)
            return False

        self._tool_truncation_retries = tool_truncation_retries + 1

        # Drop the truncated AI message so LangGraph won't try to execute
        # incomplete tool_calls (which would fail JSON parsing).
        cleaned: list[BaseMessage] = []
        for msg in collected_messages:
            if isinstance(msg, AIMessage) and msg is collected_messages[-1]:
                continue
            cleaned.append(msg)

        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))
        messages.clear()
        messages.extend(cleaned)

        retry_hint = HumanMessage(
            content=(
                "[System: Your previous tool call was truncated by the output length "
                "limit. Please retry the operation. If the output is very large, "
                "consider splitting it into smaller parts.]"
            )
        )
        messages.append(retry_hint)
        messages_dict["messages"] = cast("list[AnyMessage]", messages)
        self.streaming_final_answer = False

        self._boost_output_tokens(0)

        logger.warning(
            "↻ Tool-call truncation retry (%d/%d)...",
            tool_truncation_retries + 1,
            self._MAX_TOOL_TRUNCATION_RETRIES,
        )
        await self._emit_truncation_warning("tool_call_retry", locale)
        return True

    def _boost_output_tokens(self, retries: int) -> None:
        """Set ephemeral output token override with progressive scaling.

        retries=0 → 2x base, retries=1 → 3x base, retries>=2 → 4x base.
        Capped at MAX_EPHEMERAL_OUTPUT_TOKENS (32768).
        """
        base = self._get_configured_max_tokens()
        if base is None:
            return

        multiplier = min(retries + 2, 4)
        boosted = base * multiplier
        set_ephemeral_max_output_tokens(boosted)
        logger.info(
            " Output token boost: %d → %d (×%d, cap %d)",
            base,
            min(boosted, MAX_EPHEMERAL_OUTPUT_TOKENS),
            multiplier,
            MAX_EPHEMERAL_OUTPUT_TOKENS,
        )

    def _get_configured_max_tokens(self) -> int | None:
        """Read the configured max_tokens from the LLM instance."""
        ctx = self._ctx
        llm = ctx.llm
        if llm is None:
            return None
        max_tokens: int | None = getattr(llm, "max_tokens", None)
        return max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else None

    async def _emit_truncation_warning(self, truncation_type: str, locale: str) -> None:
        """Emit a STATUS event with optional i18n diagnostic for truncation."""
        try:
            from myrm_agent_harness.agent.errors.diagnostics import LLMErrorDiagnostic

            diagnostic = LLMErrorDiagnostic.diagnose_truncation(truncation_type, locale)
            diagnostic_dict: dict[str, object] | None = {
                "error_type": diagnostic.error_type,
                "user_message": diagnostic.user_message,
                "resolution_steps": diagnostic.resolution_steps,
                "locale": diagnostic.locale,
            }
        except Exception as diag_err:
            logger.error("Truncation diagnostic failed: %s", diag_err)
            diagnostic_dict = None

        logger.warning(" Length truncation detected: %s", truncation_type)

        event: dict[str, object] = {
            "type": AgentEventType.STATUS.value,
            "step_key": truncation_type,
            "tool_name": None,
            "messageId": self._ctx.message_id,
        }
        if diagnostic_dict:
            event["diagnostic_result"] = diagnostic_dict

        await self._compactor.put(event)

    @staticmethod
    def _has_non_reasoning_content(msg: object) -> bool:
        """Check if an AIMessage has actual user-visible content."""
        content = getattr(msg, "content", None)
        if not content:
            return False
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") not in ("thinking", "redacted_thinking"):
                        return True
                elif isinstance(block, str) and block.strip():
                    return True
            return False
        return bool(content)

    @staticmethod
    def _has_reasoning_content(msg: object) -> bool:
        """Check if an AIMessage contains reasoning/thinking content."""
        kwargs: dict[str, object] = getattr(msg, "additional_kwargs", {}) or {}
        if kwargs.get("reasoning_content"):
            return True

        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    return True

        return False


__all__ = [
    "MAX_EPHEMERAL_OUTPUT_TOKENS",
    "_MAX_EPHEMERAL_OUTPUT_TOKENS",
    "StreamTruncationRecoveryMixin",
    "ephemeral_max_output_tokens",
    "get_ephemeral_max_output_tokens",
    "reset_ephemeral_max_output_tokens",
    "set_ephemeral_max_output_tokens",
]
