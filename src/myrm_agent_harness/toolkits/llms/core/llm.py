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
automatically merging model_kwargs into extra_body. Supports native model capability passthrough
(web_search_options) via tri-state native_tools config (None=auto-detect / set=explicit /
empty set=disabled) for zero-config out-of-the-box usage.
Core layer used by LLMManager and business layer as the unified entry point for multi-model calls.
"""

import logging
from typing import Any

# 导入即注册自定义 Provider 到 litellm.custom_provider_map（副作用导入）
from myrm_agent_harness.toolkits.llms import providers  # noqa: F401
from myrm_agent_harness.infra.tls_compat import build_httpx_verify, tls_strict_disabled
from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM, clean_model_kwargs
from myrm_agent_harness.toolkits.llms.core.reasoning_timeout import get_reasoning_timeout_floor

logger = logging.getLogger(__name__)

# Note：显式Cache（Claude/Qwen）  cache_control  completely 由 Pipeline   ExplicitCacheProcessor 控制
#  not 再 using  LiteLLM   cache_control_injection_points Configure
# 这样 can implements更智能 多断点Strategy（System + Compress边界 + 对话历史 + 20-block 保护）
# OpenAI/DeepSeek/Gemini  using AutoPrefixCache， no 需显式Process


def _merge_model_kwargs_to_extra_body(llm_kwargs: dict[str, Any], model_kwargs: dict[str, Any] | None) -> None:
    """将 model_kwargs  in  AllParameterMerge to  extra_body  in

    LiteLLM 对某些provides商（如 OpenAI compatibleInterface）会Filter掉非standardParameter。
    将 model_kwargs  in  AllParameter simultaneously 放入 extra_body， ensure compatibleAllprovides商。

    Args:
        llm_kwargs: LLM ParameterDict（会被修改）
        model_kwargs: 模型customParameter
    """
    if not model_kwargs:
        return

    extra_body = llm_kwargs.setdefault("extra_body", {})
    if not isinstance(extra_body, dict):
        extra_body = {}
        llm_kwargs["extra_body"] = extra_body

    # 将 model_kwargs  in  AllParameterCopy to  extra_body（ not 覆盖 already  has  ）
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
    **kwargs: Any,
) -> "ChatLiteLLM":
    """
    统一 LLMCreateFunction，Support各种模型Type

    Note：
    - 显式Cache（Claude/Qwen）由 Pipeline   ExplicitCacheProcessor 控制
    - 隐式Cache（OpenAI/DeepSeek/Gemini） using  API AutoPrefixCache， no 需Process
    这样 can implements更智能 多断点Strategy。

    Args:
        model: 模型名称
        base_url: APIbasicURL
        api_key: APIKey
        temperature: 温度Parameter
        streaming: Whether启用流式output
        native_tools: Model native tools config (None=auto-detect, set=explicit, empty set=disable)
        web_search_options: Explicit LiteLLM web_search_options override
        **kwargs: OtherParameter

    Returns:
        ChatLiteLLM: LLMInstance
    """
    llm_kwargs: dict[str, Any] = {"model": model, **kwargs}
    if temperature is not None:
        llm_kwargs["temperature"] = temperature

    if base_url:
        llm_kwargs["api_base"] = base_url

    if api_key:
        llm_kwargs["api_key"] = api_key

    if streaming:
        llm_kwargs["streaming"] = streaming

    # 显式Cache（Claude/Qwen） completely 由 Pipeline   ExplicitCacheProcessor 控制
    #  in 消息  additional_kwargs  in Dynamic注入 cache_control 标记
    # OpenAI/DeepSeek/Gemini  using  API AutoPrefixCache， no 需Process

    # 将 kwargs  in  customParameter simultaneously 放入 extra_body
    # 解决 LiteLLM 对某些provides商Filter非standardParameter 问题
    _merge_model_kwargs_to_extra_body(llm_kwargs, kwargs)

    resolved_wso = _resolve_web_search_options(model, native_tools, web_search_options)
    if resolved_wso is not None:
        llm_kwargs["web_search_options"] = resolved_wso

    if tls_strict_disabled() and "ssl_verify" not in llm_kwargs:
        verify = build_httpx_verify()
        if verify is not True:
            llm_kwargs["ssl_verify"] = verify

    # Apply reasoning model timeout floor (e.g. o3 needs 600s for thinking phase)
    if "request_timeout" not in llm_kwargs:
        floor = get_reasoning_timeout_floor(model)
        if floor is not None:
            llm_kwargs["request_timeout"] = floor

    llm_kwargs = clean_model_kwargs(llm_kwargs, model)

    return ChatLiteLLM(**llm_kwargs)
