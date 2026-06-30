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
- toolkits.llms.ephemeral_output_tokens (POS: ephemeral max-output-tokens ContextVar for truncation recovery)
- core.context_vars::prompt_routing_key_var (POS: Session-scoped routing key for OpenAI prompt cache affinity)
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
from collections.abc import Sequence
from operator import itemgetter
from typing import (
    Any,
    TypeVar,
)

from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.output_parsers import JsonOutputParser, PydanticOutputParser
from langchain_core.runnables import Runnable, RunnableMap, RunnablePassthrough
from langchain_core.tools import BaseTool
from langchain_core.utils import get_from_dict_or_env
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_core.utils.pydantic import is_basemodel_subclass
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from myrm_agent_harness.toolkits.llms.adapters.metrics import EmptyRetryMetrics
from myrm_agent_harness.toolkits.llms.adapters.schema_normalizer import (
    normalize_tool_schema,
)
from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
    clean_model_kwargs as utils_clean_model_kwargs,
)
from myrm_agent_harness.toolkits.llms.utils.litellm_utils import (
    should_skip_response_format,
)

_BM = TypeVar("_BM", bound=BaseModel)

logger = logging.getLogger(__name__)


from myrm_agent_harness.toolkits.llms.adapters.chat_model_async_mixin import ChatLiteLLMAsyncMixin
from myrm_agent_harness.toolkits.llms.adapters.chat_model_exceptions import (
    EmptyChoicesError,
    EmptyStreamError,
    _DEVELOPER_ROLE_PATTERN,
    _FRAMEWORK_REQUIRED_OPENAI_PARAMS,
)
from myrm_agent_harness.toolkits.llms.adapters.chat_model_message_mixin import ChatLiteLLMMessageMixin
from myrm_agent_harness.toolkits.llms.adapters.chat_model_sync_mixin import ChatLiteLLMSyncMixin

__all__ = [
    "ChatLiteLLM",
    "EmptyChoicesError",
    "EmptyStreamError",
    "_DEVELOPER_ROLE_PATTERN",
    "clean_model_kwargs",
]

class ChatLiteLLM(ChatLiteLLMMessageMixin, ChatLiteLLMSyncMixin, ChatLiteLLMAsyncMixin, BaseChatModel):
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
        from myrm_agent_harness.toolkits.llms.ephemeral_output_tokens import (
            get_ephemeral_max_output_tokens,
            reset_ephemeral_max_output_tokens,
        )

        override = get_ephemeral_max_output_tokens()
        if override is not None:
            params["max_tokens"] = override
            reset_ephemeral_max_output_tokens()
            logger.info(" Ephemeral max_tokens override applied: %d", override)

    def _inject_prompt_routing_key(self, params: dict[str, object]) -> None:
        """Inject OpenAI prompt_cache_key for KV cache routing affinity.

        Only activates for native OpenAI endpoints (api.openai.com).
        Uses the session-scoped routing key from ContextVar to ensure requests
        within a conversation route to the same inference node, maximizing
        prefix cache hit rate.
        """
        from myrm_agent_harness.core.context_vars import prompt_routing_key_var

        routing_key = prompt_routing_key_var.get()
        if not routing_key:
            return

        if not self._is_openai_native_endpoint():
            return

        params["prompt_cache_key"] = routing_key

    def _is_openai_native_endpoint(self) -> bool:
        """Detect whether this instance targets a native OpenAI API endpoint."""
        api_base = (self.api_base or "").lower()
        provider = (self.custom_llm_provider or "").lower()

        if provider and provider != "openai":
            return False

        if not api_base or "api.openai.com" in api_base:
            return True

        return False

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
        model_id = self.model_name or self.model
        openai_tools: list[dict[str, Any]] = []
        for t in tools:
            if isinstance(t, dict) and "function" in t:
                openai_tools.append(normalize_tool_schema(t, model_name=model_id))
            else:
                try:
                    openai_tools.append(normalize_tool_schema(convert_to_openai_tool(t), model_name=model_id))
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
