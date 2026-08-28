"""LLM Core — LiteLLM wrapper

agent/context_management/PROMPT_CACHE_PRACTICE.md §6.1-6.2 whenever this file changes.

[INPUT]
- adapters.chat_model::ChatLiteLLM, clean_model_kwargs (POS: LangChain adapter)
- providers (POS: custom provider module; import triggers side-effect registration)
- litellm::supports_web_search (POS: model native search capability detection)

[OUTPUT]
- create_litellm_model(): factory function to create LiteLLM model instances
- ChatLiteLLM: LangChain-compatible LiteLLM chat model (re-exported from adapter)

[POS]
LLM core. LiteLLM wrapper providing a unified multi-model invocation interface
(OpenAI, Anthropic, Gemini, etc.). Provides a factory function to create LiteLLM instances,
automatically merging model_kwargs into extra_body. Integrates reasoning_timeout floor,
thinking model max_tokens headroom (auto-raise floor to prevent thinking-phase truncation),
local endpoint stall-detection relaxation (auto-detect localhost/RFC1918 → relax first_event/
inter_chunk/request timeouts), OpenRouter reasoning_effort → reasoning.effort rewrite,
and native model capability passthrough (web_search_options) via tri-state native_tools config
(None=auto-detect / set=explicit / empty set=disabled).
Core layer used by LLMManager and business layer as the unified entry point for multi-model calls.
"""

import ipaddress
import logging
from typing import Any
from urllib.parse import urlparse

from myrm_agent_harness.core.config.wire import DEFAULT_WIRE_PROTOCOL, WireProtocol
from myrm_agent_harness.infra.tls_compat import build_httpx_verify, tls_strict_disabled

# Side-effect import: registers custom providers into litellm.custom_provider_map
from myrm_agent_harness.toolkits.llms import providers  # noqa: F401
from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM, clean_model_kwargs
from myrm_agent_harness.toolkits.llms.core.openrouter_verbosity import apply_openrouter_reasoning_effort
from myrm_agent_harness.toolkits.llms.core.reasoning_timeout import get_reasoning_timeout_floor
from myrm_agent_harness.toolkits.llms.core.thinking_headroom import ensure_thinking_headroom

logger = logging.getLogger(__name__)

# Explicit cache (Claude/Qwen): controlled by Pipeline ExplicitCacheProcessor
# via dynamic cache_control injection in message additional_kwargs.
# OpenAI/DeepSeek/Gemini: rely on API auto-prefix cache, no explicit processing needed.

_LOCAL_FIRST_EVENT_TIMEOUT = 300.0
_LOCAL_INTER_CHUNK_TIMEOUT = 600.0
_LOCAL_REQUEST_TIMEOUT = 1800.0


def _is_local_endpoint(url: str | None) -> bool:
    """Detect whether a URL points to a local/private-network LLM service.

    Local models (Ollama, LM Studio, vLLM) have zero network latency but
    potentially long compute latency (prefill). Stall detection thresholds
    designed for cloud APIs will cause false kills on local endpoints.
    """
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "0.0.0.0"):  # noqa: S104  # hostname compare, not a bind
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback
    except ValueError:
        return False


def _merge_model_kwargs_to_extra_body(llm_kwargs: dict[str, Any], model_kwargs: dict[str, Any] | None) -> None:
    """Merge all model_kwargs into extra_body for cross-provider compatibility.

    LiteLLM may drop non-standard parameters for some providers (e.g. OpenAI-compatible
    endpoints). Duplicating model_kwargs into extra_body ensures they reach the provider.

    Args:
        llm_kwargs: LLM parameter dict (mutated in place).
        model_kwargs: Model-specific custom parameters.
    """
    if not model_kwargs:
        return

    extra_body = llm_kwargs.setdefault("extra_body", {})
    if not isinstance(extra_body, dict):
        extra_body = {}
        llm_kwargs["extra_body"] = extra_body

    # Copy model_kwargs into extra_body without overwriting existing keys
    for key, value in model_kwargs.items():
        if key not in extra_body:
            extra_body[key] = value


def _resolve_web_search_options(
    model: str,
    native_tools: set[str] | None,
    web_search_options: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve web_search_options based on native_tools configuration.

    Three-state logic:
    - native_tools is None (default): auto-detect via litellm.supports_web_search()
    - native_tools contains "web_search": explicitly enable
    - native_tools is empty set: explicitly disable all native tools

    Args:
        model: Model identifier for auto-detection
        native_tools: User-configured native tools (None = auto-detect)
        web_search_options: Explicit web_search_options override

    Returns:
        web_search_options dict if native search should be enabled, None otherwise
    """
    if web_search_options is not None:
        return web_search_options

    if native_tools is not None:
        if "web_search" in native_tools:
            return {}
        return None

    try:
        import litellm

        if litellm.supports_web_search(model=model):
            logger.info("Model '%s' supports native web search (auto-detected)", model)
            return {}
    except (ImportError, AttributeError):
        logger.debug("litellm.supports_web_search() unavailable, skipping auto-detection")

    return None


def create_litellm_model(
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float | None = None,
    streaming: bool = False,
    native_tools: set[str] | None = None,
    web_search_options: dict[str, Any] | None = None,
    wire_protocol: WireProtocol = DEFAULT_WIRE_PROTOCOL,
    **kwargs: Any,
) -> "ChatLiteLLM":
    """Unified factory for creating ChatLiteLLM instances across all providers.

    Explicit cache (Claude/Qwen) is controlled by ExplicitCacheProcessor.
    Implicit cache (OpenAI/DeepSeek/Gemini) relies on API auto-prefix cache.

    Args:
        model: Model identifier (e.g. "gpt-4o", "claude-3-opus").
        base_url: Custom API base URL.
        api_key: API key for authentication.
        temperature: Sampling temperature.
        streaming: Enable streaming output.
        native_tools: Model native tools config (None=auto-detect, set=explicit, empty set=disable).
        web_search_options: Explicit LiteLLM web_search_options override.
        **kwargs: Additional model-specific parameters (e.g. model_kwargs, max_tokens).

    Returns:
        Configured ChatLiteLLM instance.
    """
    llm_kwargs: dict[str, Any] = {"model": model, "wire_protocol": wire_protocol, **kwargs}
    if temperature is not None:
        llm_kwargs["temperature"] = temperature

    if base_url:
        llm_kwargs["api_base"] = base_url

    if api_key:
        llm_kwargs["api_key"] = api_key

    if streaming:
        llm_kwargs["streaming"] = streaming

    # Merge kwargs into extra_body for cross-provider compatibility
    _merge_model_kwargs_to_extra_body(llm_kwargs, kwargs)

    # OpenRouter: rewrite reasoning_effort → extra_body.reasoning.effort
    apply_openrouter_reasoning_effort(model, llm_kwargs)

    # Thinking models: raise max_tokens floor to prevent thinking-phase truncation
    ensure_thinking_headroom(model, llm_kwargs)

    resolved_wso = _resolve_web_search_options(model, native_tools, web_search_options)
    if resolved_wso is not None:
        llm_kwargs["web_search_options"] = resolved_wso

    if tls_strict_disabled() and "ssl_verify" not in llm_kwargs:
        verify = build_httpx_verify()
        if verify is not True:
            llm_kwargs["ssl_verify"] = verify

    # Apply reasoning model timeout floor (e.g. o3 needs 600s for thinking phase)
    reasoning_floor = get_reasoning_timeout_floor(model)

    if "request_timeout" not in llm_kwargs and reasoning_floor is not None:
        llm_kwargs["request_timeout"] = reasoning_floor

    if "first_event_timeout" not in llm_kwargs and reasoning_floor is not None:
        llm_kwargs["first_event_timeout"] = min(reasoning_floor / 2, 300.0)

    # Local endpoints: relax stall detection to avoid killing long prefills and ensure 64k agentic context window
    if _is_local_endpoint(base_url):
        logger.info("Local endpoint detected (%s), relaxing stall timeouts and configuring num_ctx", base_url)
        if "first_event_timeout" not in llm_kwargs:
            llm_kwargs["first_event_timeout"] = _LOCAL_FIRST_EVENT_TIMEOUT
        if "inter_chunk_timeout" not in llm_kwargs:
            llm_kwargs["inter_chunk_timeout"] = _LOCAL_INTER_CHUNK_TIMEOUT
        if "request_timeout" not in llm_kwargs:
            llm_kwargs["request_timeout"] = _LOCAL_REQUEST_TIMEOUT

        # For Ollama / local endpoints, ensure num_ctx=64000 is passed in options
        extra_body = llm_kwargs.setdefault("extra_body", {})
        if isinstance(extra_body, dict):
            options = extra_body.setdefault("options", {})
            if isinstance(options, dict) and "num_ctx" not in options:
                options["num_ctx"] = 64000

    llm_kwargs = clean_model_kwargs(llm_kwargs, model)

    return ChatLiteLLM(**llm_kwargs)
