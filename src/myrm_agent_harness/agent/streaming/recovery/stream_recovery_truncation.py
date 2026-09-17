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

import re
from typing import TYPE_CHECKING, cast

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.core.events import THINKING_TAG_NAMES
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
        # Tag-wrapped reasoning must be classified before the plain-content probe:
        # providers that inline ``<think>`` into ``content`` (MiniMax) otherwise
        # look like they produced user-visible text.
        has_tagged_reasoning = self._has_inline_reasoning(last_ai_msg)
        has_content = (
            False if has_tagged_reasoning else self._has_non_reasoning_content(last_ai_msg)
        )
        has_reasoning = has_tagged_reasoning or self._has_reasoning_content(last_ai_msg)

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
            return await self._try_thinking_budget_recovery(
                collected_messages,
                last_ai_msg,
                retries,
                locale,
            )

        return False

    async def _try_thinking_budget_recovery(
        self,
        collected_messages: list[BaseMessage],
        draft: BaseMessage,
        retries: int,
        locale: str,
    ) -> bool:
        """Recover a reasoning-only truncation by raising the budget and retrying.

        The thinking phase consumed the whole output budget, so the model never
        reached user-visible text. Re-running without more headroom would simply
        truncate again — the budget boost is what makes the retry productive.

        A resumed turn cannot be retried this way: its ``agent_input`` is a
        ``Command`` that LangGraph has already consumed, and replaying one advances no
        work (it emits zero stream chunks). Rather than spin, such a turn reports the
        condition and ends. It deliberately does *not* raise the output budget: this
        method returns ``False``, so the caller breaks out of the streaming loop and
        the executor's ``finally`` clears the ephemeral override — a raise here could
        never outlive the turn and would only produce a misleading "budget raised" log.
        Prevention lives upstream: ``thinking_headroom`` floors a thinking model's
        ``max_tokens`` at creation time.
        """
        ctx = self._ctx

        if isinstance(ctx.agent_input, Command):
            logger.warning(
                " Reasoning-only truncation in resume mode — a consumed Command "
                "cannot be retried; reporting instead of spinning"
            )
            await self._emit_truncation_warning("thinking_budget_exhausted", locale)
            return False

        if retries >= self._MAX_LENGTH_CONTINUE_RETRIES:
            logger.warning(
                " Thinking-budget recovery exhausted after %d retries",
                retries,
            )
            reset_ephemeral_max_output_tokens()
            await self._emit_truncation_warning("thinking_budget_exhausted", locale)
            return False

        # Drop the reasoning-only draft so the retry starts from clean context; the
        # user never saw it (the scrubber routed it to REASONING), so it must not
        # become conversation history.
        messages_dict = ctx.agent_input
        messages = cast(list["BaseMessage"], messages_dict.get("messages", []))
        messages.clear()
        messages.extend(msg for msg in collected_messages if msg is not draft)
        messages.append(
            HumanMessage(
                content=(
                    "[System: Your previous response spent its entire output budget on "
                    "internal reasoning and produced no user-visible answer. Respond "
                    "directly now, with minimal reasoning.]"
                )
            )
        )
        messages_dict["messages"] = cast("list[AnyMessage]", messages)

        self._boost_output_tokens(retries)
        self.streaming_final_answer = False

        logger.warning(
            "↻ Thinking-budget recovery (%d/%d)...",
            retries + 1,
            self._MAX_LENGTH_CONTINUE_RETRIES,
        )
        await self._emit_truncation_warning("thinking_budget_exhausted", locale)
        return True

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
        await self._emit_truncation_warning("tool_call_retry", locale, restart=True)
        return True

    def _boost_output_tokens(self, retries: int) -> None:
        """Set ephemeral output token override with progressive scaling.

        retries=0 → 2x base, retries=1 → 3x base, retries>=2 → 4x base.
        Capped at MAX_EPHEMERAL_OUTPUT_TOKENS (65536).

        When no output budget is configured, the provider default applies and its size
        is unknown. For a known thinking model the headroom floor is a safe base (it is
        the same value applied at creation time), so the retry gets real room. For
        anything else the ceiling is unknown — raising it could exceed the model's
        limit and turn a truncated answer into a hard error — so the boost stays a
        no-op rather than guessing.
        """
        base = self._get_configured_max_tokens()
        if base is None:
            base = self._default_output_tokens()
        if base is None:
            logger.warning(
                " Output token boost skipped: no configured max_tokens and model "
                "ceiling unknown"
            )
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

    def _default_output_tokens(self) -> int | None:
        """Resolve a safe base output budget when none is configured.

        Only thinking models qualify: their headroom floor is a value already known
        to be accepted by the provider, so scaling it cannot overshoot the ceiling.
        Returns None for unknown models, keeping the boost a safe no-op.
        """
        from myrm_agent_harness.toolkits.llms.core.thinking_headroom import (
            thinking_output_floor,
        )

        llm = self._ctx.llm
        model = getattr(llm, "model_name", None) or getattr(llm, "model", None)
        if not isinstance(model, str) or not model:
            return None
        llm_kwargs = getattr(llm, "model_kwargs", None)
        return thinking_output_floor(
            model, llm_kwargs if isinstance(llm_kwargs, dict) else None
        )

    def _get_configured_max_tokens(self) -> int | None:
        """Read the configured max_tokens from the LLM instance.

        Checks ``llm.max_tokens`` first (direct Pydantic field), then falls
        back to ``llm.model_kwargs["max_tokens"]`` which is where the value
        lands when users set it via the frontend ModelKwargsEditor.
        """
        ctx = self._ctx
        llm = ctx.llm
        if llm is None:
            return None
        max_tokens: int | None = getattr(llm, "max_tokens", None)
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            model_kwargs = getattr(llm, "model_kwargs", None) or {}
            raw = model_kwargs.get("max_tokens")
            max_tokens = raw if isinstance(raw, int) and raw > 0 else None
        return max_tokens

    async def _emit_truncation_warning(
        self,
        truncation_type: str,
        locale: str,
        restart: bool = False,
    ) -> None:
        """Emit a STATUS event with optional i18n diagnostic for truncation.

        ``restart=True`` marks recovery paths that discard the truncated output and
        re-run the turn from scratch (tool-call truncation retry), so the consumer
        drops any draft streamed before the truncation. Continuation and warning-only
        paths leave it False.
        """
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
        if restart:
            event["restart"] = True
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

    @staticmethod
    def _has_inline_reasoning(msg: object) -> bool:
        """Check if an AIMessage's text is nothing but tag-wrapped reasoning.

        Some providers return the thinking phase inside ``content`` wrapped in tags
        (MiniMax emits ``<think>…</think>``) instead of a separate reasoning field.
        The stream layer strips those tags before display, so such a message reaches
        the user as empty even though ``content`` is non-empty.

        Returns True only when tags are present, the text has no thinking left over,
        and the residual carries no user-visible answer — otherwise the message is a
        genuine (truncated) answer that belongs on the continuation path.
        """
        content = getattr(msg, "content", None)
        if not isinstance(content, str) or not content:
            return False

        stripped = content
        tagged = False
        for name in THINKING_TAG_NAMES:
            open_tag = f"<{name}>"
            close_tag = f"</{name}>"
            if open_tag not in stripped and close_tag not in stripped:
                continue
            tagged = True
            # Remove complete blocks, then any unclosed trailing block: an opening
            # tag with no close marks a response cut off mid-reasoning, so the
            # remainder is reasoning too and must not count as visible content.
            stripped = re.sub(
                rf"{re.escape(open_tag)}.*?{re.escape(close_tag)}",
                "",
                stripped,
                flags=re.DOTALL,
            )
            if open_tag in stripped:
                stripped = stripped.split(open_tag, 1)[0]
            stripped = stripped.replace(close_tag, "")

        return tagged and not stripped.strip()


__all__ = [
    "MAX_EPHEMERAL_OUTPUT_TOKENS",
    "_MAX_EPHEMERAL_OUTPUT_TOKENS",
    "StreamTruncationRecoveryMixin",
    "ephemeral_max_output_tokens",
    "get_ephemeral_max_output_tokens",
    "reset_ephemeral_max_output_tokens",
    "set_ephemeral_max_output_tokens",
]
