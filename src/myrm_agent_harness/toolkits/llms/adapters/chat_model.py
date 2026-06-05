"""LangChain LiteLLM Adapter


[INPUT]
- langchain_core.language_models.chat_models::BaseChatModel (POS: LangChain chat model base class)
- langchain_core.messages (POS: LangChain message types)
- litellm::litellm (POS: LiteLLM library)
- adapters.converters (POS: message and tool call converters)
- adapters.streaming (POS: streaming response processing)
- adapters.concurrency (POS: concurrency gate for LLM calls)
- adapters.stream_aggregator (POS: stream data aggregation module)
- adapters.tool_recovery (POS: tool call recovery module)
- adapters.safety_termination_detector (POS: Safety termination detector for truncated tool call suppression)
- agent.streaming.stream_recovery_truncation (POS: ephemeral max-output-tokens ContextVar for truncation recovery)
- utils.cost_engine::compute_cost_by_tokens (POS: token-count-based cost calculation for streaming mode)
- utils.token_tracker (POS: Token tracking API — record_token_usage, append_to_ledger, record_finish_reason)

[OUTPUT]
- ChatLiteLLM: LangChain-compatible LiteLLM chat model class (with retry_metrics observability property and provider-aware system-message normalization)
- EmptyChoicesError: empty response exception class (retryable)
- EmptyStreamError: empty stream exception class (retryable)
- clean_model_kwargs(): utility function to clean model parameters

[POS]
LangChain LiteLLM adapter. Provides a LangChain-compatible LiteLLM interface for unified multi-model
invocation. Supports sync/async calls, streaming responses (with TTFT and duration latency tracking),
tool calling, structured output, and model native search (web_search_options).
In streaming mode: manually records token usage + cost calculation + audit log appending + TTFT/duration stats.
**Empty response retry**: covers Sync/Async/Stream, configurable retry count (1-10) and delay (0.1-10.0s);
Stream only supports fully empty stream retry (mid-stream interruptions cannot be retried).
**Metrics observability**: instance-level EmptyRetryMetrics tracks retry count, success rate, total delay;
business layer exports via retry_metrics.to_dict() for monitoring integration.
**Parameter protection**: injects per-call ``allowed_openai_params`` to prevent LiteLLM from
silently dropping framework params (tools, tool_choice) or user-supplied model_kwargs when
a provider's capability declaration is incomplete (e.g. ``xiaomi_mimo``).
Cross-provider compatible via LiteLLM. As the adapter layer, used by core.llm and business layer,
bridging LangChain and LiteLLM.
Provider-aware message normalization keeps providers that reject ``system`` turns
(for example MiniMax) on the compatibility path without leaking that concern to callers.
For OpenAI GPT-5+/Codex/o-series models, promotes ``system`` role to ``developer``
following OpenAI's recommended priority hierarchy (system > developer > user).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from operator import itemgetter
from typing import (
    Any,
    TypeVar,
)

from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import (
    BaseChatModel,
    agenerate_from_stream,
    generate_from_stream,
)
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    BaseMessageChunk,
    FunctionMessageChunk,
    HumanMessage,
    HumanMessageChunk,
    SystemMessage,
    SystemMessageChunk,
    ToolCallChunk,
)
from langchain_core.output_parsers import JsonOutputParser, PydanticOutputParser
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableMap, RunnablePassthrough
from langchain_core.tools import BaseTool
from langchain_core.utils import get_from_dict_or_env
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_core.utils.pydantic import is_basemodel_subclass
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from myrm_agent_harness.toolkits.llms.adapters.concurrency import (
    get_semaphores as _get_semaphores,
)
from myrm_agent_harness.toolkits.llms.adapters.converters import (
    convert_dict_to_message,
    convert_message_to_dict,
    create_usage_metadata,
)
from myrm_agent_harness.toolkits.llms.adapters.metrics import EmptyRetryMetrics
from myrm_agent_harness.toolkits.llms.adapters.model_capability import (
    ModelCapabilityDetector,
)
from myrm_agent_harness.toolkits.llms.adapters.safety_termination_detector import (
    detect_safety_termination,
    suppress_tool_calls_for_safety,
)
from myrm_agent_harness.toolkits.llms.adapters.schema_normalizer import (
    normalize_tool_schema,
)
from myrm_agent_harness.toolkits.llms.adapters.stream_aggregator import (
    StreamAggregator,
    XmlStreamBuffer,
    finalize_stream,
)
from myrm_agent_harness.toolkits.llms.adapters.streaming import (
    build_tool_call_chunks,
    normalize_usage,
)
from myrm_agent_harness.toolkits.llms.adapters.tool_recovery import (
    build_final_tool_call_chunk as _build_final_tool_call_chunk_fn,
)
from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
    clean_model_kwargs as utils_clean_model_kwargs,
)
from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
    should_skip_response_format,
)

_capability_detector = ModelCapabilityDetector()

_BM = TypeVar("_BM", bound=BaseModel)

logger = logging.getLogger(__name__)

_SYSTEM_MESSAGE_DENYLIST_HINTS = ("minimax",)

_DEVELOPER_ROLE_PATTERN = re.compile(r"^(?:gpt-(?:[5-9]|\d{2,})|codex|o[1-9]\d*)")

# Parameters the framework may inject that must never be silently dropped
# by LiteLLM's provider capability whitelist (see `litellm.drop_params`).
_FRAMEWORK_REQUIRED_OPENAI_PARAMS: frozenset[str] = frozenset(
    {
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
        "stream",
        "stream_options",
    }
)


class EmptyChoicesError(Exception):
    """LLM returned empty choices (retryable)."""


class EmptyStreamError(Exception):
    """LLM stream produced no chunks (retryable)."""


class ChatLiteLLM(BaseChatModel):
    """Minimal LangChain ChatModel adapter for litellm.

    Implements the subset of features this project uses: non-streaming/streaming
    chat completions and compatibility with LangChain Runnable API.
    """

    client: Any = None  # type: ignore[assignment]
    model: str = "gpt-3.5-turbo"
    model_name: str | None = None
    openai_api_key: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    organization: str | None = None
    custom_llm_provider: str | None = None
    request_timeout: float | tuple[float, float] | None = 300.0
    temperature: float | None = None
    model_kwargs: dict[str, Any] = Field(default_factory=dict)
    extra_body: dict[str, Any] | None = Field(default=None)
    web_search_options: dict[str, Any] | None = Field(
        default=None,
        description="LiteLLM web_search_options for native search (auto-detected or explicit)",
    )
    top_p: float | None = None
    top_k: int | None = None
    n: int | None = None
    max_tokens: int | None = None
    streaming: bool = False
    max_retries: int = 1
    empty_retry_enabled: bool = Field(
        default=True,
        description="Enable retry on empty response (EmptyChoicesError/EmptyStreamError)",
    )
    empty_retry_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts for empty response (1-10)",
    )
    empty_retry_delay: float = Field(
        default=0.5,
        ge=0.1,
        le=10.0,
        description="Delay between retries in seconds (0.1-10.0)",
    )

    # Private attribute for metrics (Pydantic v2 PrivateAttr)
    _retry_metrics: EmptyRetryMetrics = PrivateAttr(default_factory=EmptyRetryMetrics)

    @property
    def retry_metrics(self) -> EmptyRetryMetrics:
        """Get retry metrics for observability."""
        return self._retry_metrics

    @model_validator(mode="before")
    @classmethod
    def validate_environment(cls, values: dict) -> dict:
        try:
            import litellm  # type: ignore
        except (ImportError, TypeError):
            raise ValueError("Could not import litellm python package. Please install it with uv sync.") from None

        values["openai_api_key"] = get_from_dict_or_env(values, "openai_api_key", "OPENAI_API_KEY", default="")
        values["client"] = litellm
        return values

    @property
    def _default_params(self) -> dict[str, Any]:
        set_model_value = self.model_name or self.model
        params = {
            "model": set_model_value,
            "force_timeout": self.request_timeout,
            "max_tokens": self.max_tokens,
            "stream": self.streaming,
            "n": self.n,
            "temperature": self.temperature,
            "custom_llm_provider": self.custom_llm_provider,
            **self.model_kwargs,
        }
        if self.extra_body:
            params["extra_body"] = self.extra_body
        if self.web_search_options is not None:
            params["web_search_options"] = self.web_search_options
        return params

    @property
    def _client_params(self) -> dict[str, Any]:
        set_model_value = self.model_name or self.model
        self.client.api_base = self.api_base
        self.client.api_key = self.api_key or self.openai_api_key
        self.client.organization = self.organization
        creds: dict[str, Any] = {
            "model": set_model_value,
            "force_timeout": self.request_timeout,
            "api_base": self.api_base,
            "api_key": self.api_key or self.openai_api_key,
        }

        # Inject Authorization header for providers that might need it explicitly (like minimax)
        api_key_val = self.api_key or self.openai_api_key
        logger.debug(f"_client_params api_key_val type: {type(api_key_val)}, val: {str(api_key_val)[:5]}***")
        if api_key_val:
            extra_headers = self.model_kwargs.get("extra_headers", {})
            if "Authorization" not in extra_headers:
                extra_headers["Authorization"] = f"Bearer {api_key_val}"
                creds["extra_headers"] = extra_headers

        return {**self._default_params, **creds}

    @staticmethod
    def _inject_allowed_params(params: dict[str, object]) -> None:
        """Ensure all explicitly-supplied parameters bypass LiteLLM's provider whitelist.

        LiteLLM silently drops parameters not declared in a provider's
        ``supported_params`` when ``litellm.drop_params=True``.  Some providers
        (e.g. ``xiaomi_mimo``) have incomplete capability declarations, causing
        critical params like ``tools`` / ``tool_choice`` — and any user-supplied
        model_kwargs — to be discarded.

        This injects ``allowed_openai_params`` into *params* so that every key
        we explicitly passed is white-listed for the current call, while the
        global ``drop_params`` safety-net remains active for truly unknown params.
        """
        allowed = set(params.keys())
        allowed |= _FRAMEWORK_REQUIRED_OPENAI_PARAMS
        params["allowed_openai_params"] = sorted(allowed)

    @staticmethod
    def _apply_ephemeral_output_override(params: dict[str, object]) -> None:
        """Apply and consume the ephemeral max-output-tokens override if set.

        The truncation recovery layer sets this ContextVar to progressively
        boost the output budget during text continuation or tool-call retry.
        The override is consumed (reset to None) after a single read so that
        subsequent normal calls use the configured default.
        """
        from myrm_agent_harness.agent.streaming.stream_recovery_truncation import (
            get_ephemeral_max_output_tokens,
            reset_ephemeral_max_output_tokens,
        )

        override = get_ephemeral_max_output_tokens()
        if override is not None:
            params["max_tokens"] = override
            reset_ephemeral_max_output_tokens()
            logger.info(" Ephemeral max_tokens override applied: %d", override)

    def _convert_response_to_dict(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "dict"):
            return response.dict()
        raise ValueError(f"Unable to convert LiteLLM response to dict. Type: {type(response)}")

    def _build_empty_choices_error(self, response: Mapping[str, Any]) -> str:
        error_msg = response.get("error", {})
        error_code = response.get("code", "")
        error_type = response.get("type", "")
        original_error = response.get("original_exception", "")

        parts = [
            f"LiteLLM returned empty choices. Model: {self.model_name or self.model}",
            f"Response keys: {list(response.keys())}",
        ]

        if error_msg:
            parts.append(f"Error: {error_msg}")
        if error_code:
            parts.append(f"Error Code: {error_code}")
        if error_type:
            parts.append(f"Error Type: {error_type}")
        if original_error:
            parts.append(f"Original Exception: {original_error}")
        parts.append(f"Full Response: {response}")

        return "\n".join(parts)

    def _extract_tool_context_from_kwargs(
        self,
        kwargs: dict[str, Any],
    ) -> tuple[list[str] | None, dict[str, dict[str, Any]] | None]:
        logger.debug(f"_extract_tool_context_from_kwargs keys: {list(kwargs.keys())}")
        tools = kwargs.get("tools")
        if not tools:
            logger.debug(f"tools is empty or not in kwargs. kwargs keys: {list(kwargs.keys())}")
            return None, None

        tool_names: list[str] = []
        tool_schemas: dict[str, dict[str, Any]] = {}
        for tool in tools:
            if isinstance(tool, dict) and "function" in tool:
                name = tool["function"].get("name")
                if name:
                    tool_names.append(name)
                    tool_schemas[name] = tool

        logger.debug(f"extracted tool_names: {tool_names}")
        return (
            tool_names if tool_names else None,
            tool_schemas if tool_schemas else None,
        )

    def _build_final_tool_call_chunk(
        self,
        raw_tool_calls: Sequence[Mapping[str, Any]],
        tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[ChatGenerationChunk | None, list[dict[str, Any]], list[dict[str, Any]]]:
        return _build_final_tool_call_chunk_fn(raw_tool_calls, tool_schemas)

    @staticmethod
    def _stringify_message_content(content: object) -> str:
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    text = block.strip()
                    if text:
                        parts.append(text)
                elif isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str):
                        text = text.strip()
                        if text:
                            parts.append(text)
                else:
                    text = str(block).strip()
                    if text:
                        parts.append(text)
            return "\n".join(parts)

        return str(content).strip()

    @staticmethod
    def _is_system_role_message(message: object) -> bool:
        """Return True when a message should be treated as a system turn.

        LangChain history can surface system instructions through several
        concrete message shapes. We normalize every system-like role here so
        provider-specific compatibility stays centralized in the adapter.
        """
        if isinstance(message, SystemMessage):
            return True

        if isinstance(message, Mapping):
            role = message.get("role")
        else:
            role = getattr(message, "role", None)
            if role is None:
                role = getattr(message, "type", None)

        return isinstance(role, str) and role.lower() == "system"

    def _create_message_dicts(
        self, messages: list[BaseMessage], stop: list[str] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        params = self._client_params
        if stop is not None:
            if "stop" in params:
                raise ValueError("`stop` found in both the input and default params.")
            params["stop"] = stop
        message_dicts = [convert_message_to_dict(m) for m in self._normalize_messages_for_provider(messages)]
        if self._should_promote_system_to_developer() and message_dicts:
            first = message_dicts[0]
            if isinstance(first, dict) and first.get("role") == "system":
                first["role"] = "developer"
        self._stamp_missing_reasoning_content(message_dicts)
        return message_dicts, params

    def _stamp_missing_reasoning_content(self, message_dicts: list[dict[str, Any]]) -> None:
        """Back-fill empty reasoning_content on assistant messages for thinking-mode models.

        DeepSeek/Kimi/MiMo APIs reject requests where assistant messages lack
        the reasoning_content field when thinking mode is active. This stamps
        an empty string on messages missing the field, enabling model-switch
        and session-restore scenarios without 400 errors.
        Skipped for non-thinking models to avoid prefix-cache churn.
        """
        if not _capability_detector.needs_reasoning_content_echo(
            provider=self.custom_llm_provider or "",
            model=self._get_model_name(),
            base_url=self.api_base or "",
        ):
            return
        for msg in message_dicts:
            if msg.get("role") == "assistant" and "reasoning_content" not in msg:
                msg["reasoning_content"] = ""

    def _normalize_messages_for_provider(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Normalize outbound messages for provider-specific role quirks.

        MiniMax rejects direct system messages in the current chat/completions
        path, so we fold all system instructions into the first human turn.
        This preserves the instruction content while keeping the outbound role
        sequence valid for the provider.
        """
        if not self._should_demote_system_messages():
            return messages

        system_parts: list[str] = []
        for message in messages:
            if self._is_system_role_message(message):
                text = self._stringify_message_content(message.content)
                if text:
                    system_parts.append(text)

        if not system_parts:
            return [message for message in messages if not self._is_system_role_message(message)]

        merged_system = "\n\n".join(system_parts)
        normalized: list[BaseMessage] = []
        human_rewritten = False

        for message in messages:
            if self._is_system_role_message(message):
                continue

            if not human_rewritten and isinstance(message, HumanMessage):
                content = message.content
                if isinstance(content, list):
                    merged_content: str | list[object] = [
                        {"type": "text", "text": merged_system},
                        *content,
                    ]
                else:
                    merged_content = f"{merged_system}\n\n{content}" if content else merged_system

                normalized.append(
                    HumanMessage(
                        content=merged_content,
                        additional_kwargs=dict(getattr(message, "additional_kwargs", {}) or {}),
                        response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
                        name=getattr(message, "name", None),
                        id=getattr(message, "id", None),
                    )
                )
                human_rewritten = True
            else:
                normalized.append(message)

        if human_rewritten:
            return normalized

        return [HumanMessage(content=merged_system), *normalized]

    def _should_demote_system_messages(self) -> bool:
        model_name = self._get_model_name().lower()
        api_base = (self.api_base or "").lower()
        provider = (self.custom_llm_provider or "").lower()
        combined = " ".join((model_name, api_base, provider))
        return any(hint in combined for hint in _SYSTEM_MESSAGE_DENYLIST_HINTS)

    def _should_promote_system_to_developer(self) -> bool:
        """Whether to promote ``system`` role to ``developer`` for the current model.

        OpenAI GPT-5+, Codex, and o-series models give stronger instruction-following
        weight to ``developer`` role.  Some Codex endpoints reject ``system`` outright.
        This is mutually exclusive with ``_should_demote_system_messages`` (MiniMax path).
        """
        if self._should_demote_system_messages():
            return False
        model_name = self._get_model_name().lower()
        bare_model = model_name.rsplit("/", maxsplit=1)[-1]
        return bool(_DEVELOPER_ROLE_PATTERN.match(bare_model))

    def _create_chat_result(
        self,
        response: Mapping[str, Any],
        available_tools: list[str] | None = None,
        tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> ChatResult:
        generations: list[ChatGeneration] = []
        token_usage = response.get("usage", {})
        choices = response.get("choices", [])

        if not choices:
            raise EmptyChoicesError(self._build_empty_choices_error(response))

        for choice in choices:
            finish_reason = choice.get("finish_reason")

            # Safety termination: suppress truncated tool_calls before message
            # conversion to prevent corrupt arguments from being dispatched.
            has_tool_calls = choice.get("message", {}).get("tool_calls")
            if finish_reason and detect_safety_termination(finish_reason) and has_tool_calls:
                suppress_tool_calls_for_safety(choice["message"], finish_reason)

            try:
                message = convert_dict_to_message(choice["message"], available_tools, tool_schemas)
            except Exception as e:
                logger.error(f" Failed to convert message: {type(e).__name__} - {e!s}")
                raise

            if isinstance(message, AIMessage):
                message.response_metadata = {"model_name": self.model_name or self.model}
                message.usage_metadata = create_usage_metadata(token_usage)

            generations.append(
                ChatGeneration(
                    message=message,
                    generation_info=dict(finish_reason=choice.get("finish_reason")),
                )
            )

        set_model_value = self.model_name or self.model
        llm_output = {"token_usage": token_usage, "model": set_model_value}
        return ChatResult(generations=generations, llm_output=llm_output)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        should_stream = kwargs.pop("streaming", self.streaming)
        if should_stream:
            stream_iter = self._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
            return generate_from_stream(stream_iter)

        available_tools, tool_schemas = self._extract_tool_context_from_kwargs(kwargs)
        message_dicts, params = self._create_message_dicts(messages, stop)

        # Filter out internal LangChain parameters that shouldn't be passed to LiteLLM
        filtered_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            not in (
                "ls_structured_output_format",
                "_json_mode_fallback",
                "_in_fallback",
            )
        }

        params = {**params, **filtered_kwargs}
        self._inject_allowed_params(params)
        self._apply_ephemeral_output_override(params)

        import time

        max_attempts = self.empty_retry_max_attempts if self.empty_retry_enabled else 1
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                response = self.client.completion(messages=message_dicts, **params)
                response = self._convert_response_to_dict(response)
                result = self._create_chat_result(response, available_tools, tool_schemas)

                # Update metrics: success after retry
                if attempt > 0:
                    self._retry_metrics.sync_success_after_retry += 1

                return result

            except EmptyChoicesError as e:
                last_error = e
                self._retry_metrics.sync_retry_count += 1

                if attempt < max_attempts - 1:
                    logger.warning(f" Empty choices (attempt {attempt + 1}), retrying...")
                    delay_ms = self.empty_retry_delay * 1000
                    self._retry_metrics.total_retry_delay_ms += delay_ms
                    time.sleep(self.empty_retry_delay)
                else:
                    logger.error(f" Empty choices after {max_attempts} attempts.")
            except Exception as e:
                from myrm_agent_harness.toolkits.llms.errors.classifier import (
                    is_context_overflow,
                    parse_available_output_tokens_from_error,
                )

                if is_context_overflow(e):
                    available = parse_available_output_tokens_from_error(e)
                    if available is not None and available >= 500 and attempt < max_attempts - 1:
                        safe_tokens = max(1, available - 64)
                        logger.warning(
                            f" Context overflow, injecting ephemeral max_tokens={safe_tokens} (attempt {attempt + 1})"
                        )
                        params["max_tokens"] = safe_tokens
                        continue
                    else:
                        logger.warning(
                            f" Context overflow (available={available}), fast-failing to trigger compression."
                        )
                        raise e

                model_name = self.model_name or self.model
                logger.error(f" LiteLLM call failed: {type(e).__name__} - {e!s} (Model: {model_name})")
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Unexpected error in _generate retry loop")

    def _process_chunk(
        self,
        chunk: Any,
        default_chunk_class: type[BaseMessageChunk],
        tool_call_id_map: dict[str, str] | None = None,
        *,
        emit_tool_call_chunks: bool = True,
    ) -> tuple[ChatGenerationChunk | None, type[BaseMessageChunk]]:
        """Process a single streaming response chunk into a ChatGenerationChunk."""
        if not isinstance(chunk, dict):
            try:
                chunk = chunk.model_dump()
            except Exception:
                return None, default_chunk_class

        if not chunk or len(chunk.get("choices", [])) == 0:
            return None, default_chunk_class

        delta = chunk["choices"][0]["delta"]
        role = delta.get("role")
        content = delta.get("content") or ""

        # Some models (e.g. GLM) put the answer in reasoning_content instead of content
        reasoning_content = delta.get("reasoning_content") or ""
        additional_kwargs: dict[str, str] = {}
        if reasoning_content:
            additional_kwargs["reasoning_content"] = reasoning_content

        # Use keyword argument content= since BaseMessageChunk rejects positional args
        msg_chunk: BaseMessageChunk
        if role == "user" or default_chunk_class == HumanMessageChunk:
            msg_chunk = HumanMessageChunk(content=content)
        elif role == "assistant" or default_chunk_class == AIMessageChunk:
            tool_call_chunks: list[ToolCallChunk] = []
            raw_tool_calls = delta.get("tool_calls")
            if emit_tool_call_chunks:
                tool_call_chunks = build_tool_call_chunks(raw_tool_calls, tool_call_id_map)
            msg_chunk = AIMessageChunk(
                content=content,
                tool_call_chunks=tool_call_chunks,
                additional_kwargs=additional_kwargs if additional_kwargs else {},
            )
        elif role == "system" or default_chunk_class == SystemMessageChunk:
            msg_chunk = SystemMessageChunk(content=content)
        elif role == "function" or default_chunk_class == FunctionMessageChunk:
            function_call = delta.get("function_call")
            func_args = function_call.get("arguments", "") if function_call else ""
            func_name = function_call.get("name", "") if function_call else ""
            msg_chunk = FunctionMessageChunk(content=func_args, name=func_name)
        else:
            # Handle different message chunk types that may require additional parameters
            if default_chunk_class == AIMessageChunk:
                msg_chunk = AIMessageChunk(
                    content=content,
                    additional_kwargs=additional_kwargs if additional_kwargs else {},
                )
            elif default_chunk_class == HumanMessageChunk:
                msg_chunk = HumanMessageChunk(content=content)
            elif default_chunk_class == SystemMessageChunk:
                msg_chunk = SystemMessageChunk(content=content)
            elif default_chunk_class == FunctionMessageChunk:
                msg_chunk = FunctionMessageChunk(content=content, name="")
            else:
                # Fallback: assume it's a standard message chunk that only needs content and type
                msg_chunk = default_chunk_class(content=content, type=default_chunk_class.__name__)

        return ChatGenerationChunk(message=msg_chunk), msg_chunk.__class__

    def _record_stream_usage(
        self,
        usage: Any,
        *,
        model_name: str = "",
        duration_ms: float | None = None,
        ttft_ms: float | None = None,
    ) -> None:
        """Record token usage, cost, and latency for streaming responses.

        In streaming mode LiteLLM callbacks are skipped, so we manually record
        usage, compute cost via token counts, and append to the audit ledger.

        Args:
            usage: LiteLLM usage object from the final stream chunk
            model_name: Model identifier for per-model attribution
            duration_ms: Total stream duration (first request to last chunk)
            ttft_ms: Time to first token (first request to first content chunk)
        """
        from myrm_agent_harness.utils.token_economics.cost_engine import (
            compute_cost_by_tokens,
        )
        from myrm_agent_harness.utils.token_economics.tracker import (
            append_to_ledger,
            record_token_usage,
        )

        if not usage:
            return

        usage_dict = normalize_usage(usage)
        resolved_model = model_name or None

        prompt_tokens = int(usage_dict.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage_dict.get("completion_tokens", 0) or 0)
        cost_result = compute_cost_by_tokens(resolved_model, prompt_tokens, completion_tokens)

        record_token_usage(
            usage_dict,
            model_name=resolved_model,
            duration_ms=duration_ms,
            ttft_ms=ttft_ms,
            cost_usd=cost_result.usd,
            cost_status=cost_result.status,
        )
        append_to_ledger(usage_dict, resolved_model, duration_ms, cost_result.usd)

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        import time

        available_tools, tool_schemas = self._extract_tool_context_from_kwargs(kwargs)
        message_dicts, params = self._create_message_dicts(messages, stop)
        params = {
            **params,
            **kwargs,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        self._inject_allowed_params(params)
        self._apply_ephemeral_output_override(params)

        max_attempts = self.empty_retry_max_attempts if self.empty_retry_enabled else 1
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                agg = StreamAggregator(AIMessageChunk)
                xml_content_buffer = XmlStreamBuffer()
                xml_reasoning_buffer = XmlStreamBuffer()

                for chunk in self.client.completion(messages=message_dicts, **params):
                    chunk_dict = agg.ingest_raw_chunk(chunk)
                    if chunk_dict is None:
                        continue
                    agg.aggregate_tool_calls_from_dict(chunk_dict)

                    cg_chunk, new_class = self._process_chunk(
                        chunk_dict,
                        agg.default_chunk_class,
                        agg.tool_call_id_map,
                        emit_tool_call_chunks=False,
                    )
                    if cg_chunk:
                        agg.on_generation_chunk(cg_chunk, new_class)

                        # Filter content and reasoning_content through DSML buffer before yielding
                        raw_content = str(cg_chunk.message.content) if cg_chunk.message.content else ""
                        safe_content = xml_content_buffer.process(raw_content)

                        additional_kwargs = dict(getattr(cg_chunk.message, "additional_kwargs", {}))
                        raw_reasoning = additional_kwargs.get("reasoning_content", "")
                        safe_reasoning = xml_reasoning_buffer.process(str(raw_reasoning)) if raw_reasoning else ""

                        if safe_content or safe_reasoning or getattr(cg_chunk.message, "tool_call_chunks", []):
                            msg_dict = dict(cg_chunk.message)
                            msg_dict.pop("type", None)
                            msg_dict["content"] = safe_content
                            if "additional_kwargs" in msg_dict:
                                ak = dict(msg_dict["additional_kwargs"])
                                if safe_reasoning:
                                    ak["reasoning_content"] = safe_reasoning
                                elif "reasoning_content" in ak:
                                    del ak["reasoning_content"]
                                msg_dict["additional_kwargs"] = ak

                            safe_chunk = cg_chunk.message.__class__(**msg_dict)
                            safe_cg_chunk = ChatGenerationChunk(message=safe_chunk)
                            if run_manager:
                                run_manager.on_llm_new_token(safe_content, chunk=safe_cg_chunk)
                            yield safe_cg_chunk

                if agg.is_empty:
                    raise EmptyStreamError(f"Stream produced no chunks. Model: {self.model_name or self.model}")

                # Flush buffers at the end of the stream
                flushed_content = xml_content_buffer.flush()
                flushed_reasoning = xml_reasoning_buffer.flush()
                if flushed_content or flushed_reasoning:
                    msg_dict = {"content": flushed_content}
                    if flushed_reasoning:
                        msg_dict["additional_kwargs"] = {"reasoning_content": flushed_reasoning}
                    safe_chunk = agg.default_chunk_class(**msg_dict)
                    safe_cg_chunk = ChatGenerationChunk(message=safe_chunk)
                    if run_manager:
                        run_manager.on_llm_new_token(flushed_content, chunk=safe_cg_chunk)
                    yield safe_cg_chunk

                result = finalize_stream(
                    agg,
                    tool_schemas,
                    self.model_name or self.model,
                    is_async=False,
                    record_usage_fn=self._record_stream_usage,
                    available_tools=available_tools,
                )
                if result.final_tool_chunk:
                    if run_manager:
                        run_manager.on_llm_new_token("", chunk=result.final_tool_chunk)
                    yield result.final_tool_chunk

                if attempt > 0:
                    self._retry_metrics.stream_success_after_retry += 1
                break

            except EmptyStreamError as e:
                last_error = e
                self._retry_metrics.stream_retry_count += 1
                if attempt < max_attempts - 1:
                    logger.warning(f" Empty stream (attempt {attempt + 1}), retrying...")
                    self._retry_metrics.total_retry_delay_ms += self.empty_retry_delay * 1000
                    time.sleep(self.empty_retry_delay)
                else:
                    logger.error(f" Empty stream after {max_attempts} attempts.")

        if last_error:
            raise last_error

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        should_stream = kwargs.get("streaming", self.streaming)
        if should_stream:
            return await self._agenerate_inner(messages, stop, run_manager, **kwargs)

        import contextlib

        global_sem, model_sem = await _get_semaphores(self.model_name or self.model)

        # lock both semaphores (global then model)
        async with global_sem or contextlib.nullcontext(), model_sem or contextlib.nullcontext():
            return await self._agenerate_inner(messages, stop, run_manager, **kwargs)

    async def _agenerate_inner(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        should_stream = kwargs.pop("streaming", self.streaming)
        if should_stream:
            try:
                stream_iter = self._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs)
                return await agenerate_from_stream(stream_iter)
            except TypeError as e:
                if "'NoneType' object is not iterable" in str(e):
                    logger.warning(" LangChain agenerate_from_stream bug, falling back to non-streaming")
                    return await self._agenerate(messages, stop, run_manager, stream=False, **kwargs)
                raise
            except Exception:
                logger.error(f" LiteLLM streaming failed (Model: {self.model_name or self.model})")
                raise

        available_tools, tool_schemas = self._extract_tool_context_from_kwargs(kwargs)
        message_dicts, params = self._create_message_dicts(messages, stop)

        # Filter out internal LangChain parameters that shouldn't be passed to LiteLLM
        filtered_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            not in (
                "ls_structured_output_format",
                "_json_mode_fallback",
                "_in_fallback",
            )
        }

        params = {**params, **filtered_kwargs}
        self._inject_allowed_params(params)
        self._apply_ephemeral_output_override(params)

        from myrm_agent_harness.infra.tracing import get_tracer
        from myrm_agent_harness.toolkits.llms.utils.logger import (
            log_llm_request,
            log_llm_response,
        )

        tracer = get_tracer("llm.call")
        model_name = self.model_name or self.model

        max_attempts = self.empty_retry_max_attempts if self.empty_retry_enabled else 1
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                log_llm_request(model_name, message_dicts, params)

                with tracer.start_as_current_span("llm.call") as span:
                    # OpenInference standard attributes
                    span.set_attribute("llm.model_name", model_name)
                    span.set_attribute("llm.request.attempt", attempt + 1)

                    response = await self.client.acreate(messages=message_dicts, **params)
                    response = self._convert_response_to_dict(response)

                    if usage := response.get("usage"):
                        span.set_attribute("llm.token_count.prompt", usage.get("prompt_tokens", 0))
                        span.set_attribute(
                            "llm.token_count.completion",
                            usage.get("completion_tokens", 0),
                        )
                        span.set_attribute("llm.token_count.total", usage.get("total_tokens", 0))

                log_llm_response(response)

                choices = response.get("choices")
                if choices and isinstance(choices, list) and len(choices) > 0:
                    fr = choices[0].get("finish_reason")
                    if isinstance(fr, str) and fr:
                        from myrm_agent_harness.utils.token_economics.tracker import (
                            record_finish_reason,
                        )

                        record_finish_reason(fr)

                result = self._create_chat_result(response, available_tools, tool_schemas)

                # Update metrics: success after retry
                if attempt > 0:
                    self._retry_metrics.async_success_after_retry += 1

                return result

            except EmptyChoicesError as e:
                last_error = e
                self._retry_metrics.async_retry_count += 1

                if attempt < max_attempts - 1:
                    logger.warning(f" Empty choices (attempt {attempt + 1}), retrying...")
                    delay_ms = self.empty_retry_delay * 1000
                    self._retry_metrics.total_retry_delay_ms += delay_ms
                    await asyncio.sleep(self.empty_retry_delay)
                else:
                    logger.error(f" Empty choices after {max_attempts} attempts.")
            except Exception as e:
                from myrm_agent_harness.toolkits.llms.errors.classifier import (
                    is_context_overflow,
                    parse_available_output_tokens_from_error,
                )

                if is_context_overflow(e):
                    available = parse_available_output_tokens_from_error(e)
                    if available is not None and available >= 500 and attempt < max_attempts - 1:
                        safe_tokens = max(1, available - 64)
                        logger.warning(
                            f" Context overflow, injecting ephemeral max_tokens={safe_tokens} (attempt {attempt + 1})"
                        )
                        params["max_tokens"] = safe_tokens
                        continue
                    else:
                        logger.warning(
                            f" Context overflow (available={available}), fast-failing to trigger compression."
                        )
                        raise e

                logger.error(f" LiteLLM acreate failed (Model: {self.model_name or self.model}): {e!s}")
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Unexpected error in _agenerate retry loop")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        import contextlib

        global_sem, model_sem = await _get_semaphores(self.model_name or self.model)

        async with global_sem or contextlib.nullcontext(), model_sem or contextlib.nullcontext():
            async for chunk in self._astream_inner(messages, stop, run_manager, **kwargs):
                yield chunk

    async def _astream_inner(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:

        from myrm_agent_harness.infra.tracing import get_tracer

        tracer = get_tracer("llm.stream")
        model_name = self.model_name or self.model

        available_tools, tool_schemas = self._extract_tool_context_from_kwargs(kwargs)
        message_dicts, params = self._create_message_dicts(messages, stop)

        # Filter out internal LangChain parameters that shouldn't be passed to LiteLLM
        filtered_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            not in (
                "ls_structured_output_format",
                "_json_mode_fallback",
                "_in_fallback",
            )
        }

        params = {
            **params,
            **filtered_kwargs,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        self._inject_allowed_params(params)
        self._apply_ephemeral_output_override(params)

        max_attempts = self.empty_retry_max_attempts if self.empty_retry_enabled else 1
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                with tracer.start_as_current_span("llm.stream_connect") as llm_span:
                    llm_span.set_attribute("llm.model_name", model_name)
                    stream = await self.client.acreate(messages=message_dicts, **params)

                agg = StreamAggregator(AIMessageChunk)
                xml_content_buffer = XmlStreamBuffer()
                xml_reasoning_buffer = XmlStreamBuffer()

                async for chunk in stream:
                    chunk_dict = agg.ingest_raw_chunk(chunk)
                    if chunk_dict is None:
                        continue
                    agg.aggregate_tool_calls_from_dict(chunk_dict)

                    cg_chunk, new_class = self._process_chunk(
                        chunk_dict,
                        agg.default_chunk_class,
                        agg.tool_call_id_map,
                        emit_tool_call_chunks=False,
                    )
                    if cg_chunk:
                        agg.on_generation_chunk(cg_chunk, new_class)

                        # Filter content and reasoning_content through DSML buffer before yielding
                        raw_content = str(cg_chunk.message.content) if cg_chunk.message.content else ""
                        safe_content = xml_content_buffer.process(raw_content)

                        additional_kwargs = dict(getattr(cg_chunk.message, "additional_kwargs", {}))
                        raw_reasoning = additional_kwargs.get("reasoning_content", "")
                        safe_reasoning = xml_reasoning_buffer.process(str(raw_reasoning)) if raw_reasoning else ""

                        if safe_content or safe_reasoning or getattr(cg_chunk.message, "tool_call_chunks", []):
                            msg_dict = dict(cg_chunk.message)
                            msg_dict.pop("type", None)
                            msg_dict["content"] = safe_content
                            if "additional_kwargs" in msg_dict:
                                ak = dict(msg_dict["additional_kwargs"])
                                if safe_reasoning:
                                    ak["reasoning_content"] = safe_reasoning
                                elif "reasoning_content" in ak:
                                    del ak["reasoning_content"]
                                msg_dict["additional_kwargs"] = ak

                            safe_chunk = cg_chunk.message.__class__(**msg_dict)
                            safe_cg_chunk = ChatGenerationChunk(message=safe_chunk)
                            if run_manager:
                                await run_manager.on_llm_new_token(safe_content, chunk=safe_cg_chunk)
                            yield safe_cg_chunk

                logger.debug(f" Stream completed: total {agg.chunk_count} chunks")

                if agg.is_empty:
                    raise EmptyStreamError(f"Stream produced no chunks. Model: {model_name}")

                # Flush buffers at the end of the stream
                flushed_content = xml_content_buffer.flush()
                flushed_reasoning = xml_reasoning_buffer.flush()
                if flushed_content or flushed_reasoning:
                    msg_dict = {"content": flushed_content}
                    if flushed_reasoning:
                        msg_dict["additional_kwargs"] = {"reasoning_content": flushed_reasoning}
                    safe_chunk = agg.default_chunk_class(**msg_dict)
                    safe_cg_chunk = ChatGenerationChunk(message=safe_chunk)
                    if run_manager:
                        await run_manager.on_llm_new_token(flushed_content, chunk=safe_cg_chunk)
                    yield safe_cg_chunk

                result = finalize_stream(
                    agg,
                    tool_schemas,
                    model_name,
                    is_async=True,
                    record_usage_fn=self._record_stream_usage,
                    available_tools=available_tools,
                )
                if result.final_tool_chunk:
                    if run_manager:
                        await run_manager.on_llm_new_token("", chunk=result.final_tool_chunk)
                    yield result.final_tool_chunk

                if attempt > 0:
                    self._retry_metrics.stream_success_after_retry += 1
                break

            except EmptyStreamError as e:
                last_error = e
                self._retry_metrics.stream_retry_count += 1
                if attempt < max_attempts - 1:
                    logger.warning(f" Empty stream (attempt {attempt + 1}), retrying...")
                    self._retry_metrics.total_retry_delay_ms += self.empty_retry_delay * 1000
                    await asyncio.sleep(self.empty_retry_delay)
                else:
                    logger.error(f" Empty stream after {max_attempts} attempts.")
            except Exception as e:
                from myrm_agent_harness.toolkits.llms.errors.classifier import (
                    is_context_overflow,
                    parse_available_output_tokens_from_error,
                )

                if is_context_overflow(e):
                    available = parse_available_output_tokens_from_error(e)
                    if available is not None and available >= 500 and attempt < max_attempts - 1:
                        safe_tokens = max(1, available - 64)
                        logger.warning(
                            f" Context overflow, injecting ephemeral max_tokens={safe_tokens} (attempt {attempt + 1})"
                        )
                        params["max_tokens"] = safe_tokens
                        continue
                    else:
                        logger.warning(
                            f" Context overflow (available={available}), fast-failing to trigger compression."
                        )
                        raise e

                logger.error(f" LiteLLM streaming failed (Model: {model_name}): {e!s}")
                raise

        if last_error:
            raise last_error

    @property
    def _identifying_params(self) -> dict[str, Any]:
        set_model_value = self.model_name or self.model
        return {
            "model": set_model_value,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "n": self.n,
        }

    @property
    def _llm_type(self) -> str:
        return "litellm-chat"

    @staticmethod
    def should_skip_response_format(model: str) -> bool:
        return should_skip_response_format(model)

    @staticmethod
    def clean_model_kwargs(kwargs: dict, model: str, additional_remove_keys: list[str] | None = None) -> dict:
        return utils_clean_model_kwargs(kwargs, model, additional_remove_keys)

    def _get_model_name(self) -> str:
        return getattr(self, "model", "") or getattr(self, "model_name", "") or ""

    async def ainvoke(self, input, config=None, **kwargs):
        logger.debug(f"ainvoke kwargs keys: {list(kwargs.keys())}")
        if "tools" in kwargs:
            logger.debug(f"ainvoke tools count: {len(kwargs.get('tools', []))}")  # type: ignore[override]
        if kwargs.get("_in_fallback", False):
            return await super().ainvoke(input, config, **self.clean_model_kwargs(kwargs, self._get_model_name()))

        result = await super().ainvoke(input, config, **kwargs)
        if not kwargs.get("_json_mode_fallback", False):
            return result

        if result.content and (isinstance(result.content, str) and result.content.strip()):
            return result

        reasoning_content = getattr(result, "additional_kwargs", {}).get("reasoning_content")
        if (
            reasoning_content
            and isinstance(reasoning_content, str)
            and reasoning_content.strip()
            and ("{" in reasoning_content or "[" in reasoning_content)
        ):
            return AIMessage(
                content=reasoning_content.strip(),
                additional_kwargs=getattr(result, "additional_kwargs", {}),
            )

        fallback_kwargs = self.clean_model_kwargs(kwargs, self._get_model_name())
        fallback_kwargs["_in_fallback"] = True
        return await super().ainvoke(input, config, **fallback_kwargs)

    def with_structured_output(
        self,
        schema: dict[str, Any] | type[_BM] | type | None = None,
        *,
        include_raw: bool = False,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, dict | _BM]:
        if kwargs:
            raise ValueError(f"Received unsupported arguments {kwargs}")

        is_pydantic_schema = isinstance(schema, type) and is_basemodel_subclass(schema)

        bind_kwargs: dict[str, Any] = {
            "_json_mode_fallback": True,
            "stream": False,
            "ls_structured_output_format": {"kwargs": {}, "schema": schema},
        }
        if not self.should_skip_response_format(self._get_model_name()):
            bind_kwargs["response_format"] = {"type": "json_object"}

        llm = self.bind(**bind_kwargs)

        if is_pydantic_schema:
            # schema is guaranteed to be Type[BaseModel] when is_pydantic_schema is True
            output_parser: PydanticOutputParser | JsonOutputParser = PydanticOutputParser(
                pydantic_object=schema  # type: ignore
            )
        else:
            output_parser = JsonOutputParser()

        if include_raw:
            parser_assign = RunnablePassthrough.assign(
                parsed=itemgetter("raw") | output_parser, parsing_error=lambda _: None
            )
            parser_none = RunnablePassthrough.assign(parsed=lambda _: None)
            parser_with_fallback = parser_assign.with_fallbacks([parser_none], exception_key="parsing_error")
            return RunnableMap(raw=llm) | parser_with_fallback

        return llm | output_parser

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | BaseTool | Any],
        *,
        tool_choice: str | None = None,
        parallel_tool_calls: bool | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        logger.debug(f"bind_tools called with {len(tools) if tools else 0} tools")
        openai_tools: list[dict[str, Any]] = []
        for t in tools:
            if isinstance(t, dict) and "function" in t:
                openai_tools.append(normalize_tool_schema(t))
            else:
                try:
                    openai_tools.append(normalize_tool_schema(convert_to_openai_tool(t)))
                except Exception as e:
                    logger.error(f"DEBUG: Failed to convert tool {getattr(t, 'name', t)}: {e}")
                    continue

        tool_choice_param: str | dict[str, Any] | None = None
        if tool_choice in ("auto", "any"):
            tool_choice_param = "auto"
        elif tool_choice == "none":
            tool_choice_param = "none"
        elif tool_choice == "required":
            tool_choice_param = "required"
        elif isinstance(tool_choice, str):
            # Specific tool name requested
            tool_choice_param = {"type": "function", "function": {"name": tool_choice}}

        bind_kwargs: dict[str, Any] = {"tools": openai_tools}
        if not openai_tools:
            logger.warning(f"DEBUG: openai_tools is empty! original tools count: {len(tools)}")
        if tool_choice_param:
            bind_kwargs["tool_choice"] = tool_choice_param
        if parallel_tool_calls is not None:
            bind_kwargs["parallel_tool_calls"] = parallel_tool_calls
        if kwargs:
            bind_kwargs.update(kwargs)

        return self.bind(**bind_kwargs)


def clean_model_kwargs(kwargs: dict, model: str, additional_remove_keys: list[str] | None = None) -> dict:
    return ChatLiteLLM.clean_model_kwargs(kwargs, model, additional_remove_keys)
