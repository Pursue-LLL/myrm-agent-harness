"""Model capability detection for reasoning_content handling.

Detects models that require special reasoning_content handling:
- MiMo: requires complete reasoning_content echo-back
- DeepSeek: requires reasoning_content on tool-call messages
- Kimi/Moonshot: requires reasoning_content on tool-call messages

[INPUT]
- (none)

[OUTPUT]
- ModelCapabilityDetector: class — Model capability detection

[POS]
Provides ModelCapabilityDetector for reasoning_content handling.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

# Model prefixes for detection
_MIMO_PREFIXES = ("xiaomi_mimo/", "mimo")
_DEEPSEEK_PREFIXES = ("deepseek/",)
_KIMI_PREFIXES = ("moonshot/", "kimi/")

# Base URL hosts for detection
_DEEPSEEK_HOSTS = ("api.deepseek.com",)
_KIMI_HOSTS = ("api.kimi.com", "moonshot.ai", "moonshot.cn")
_MIMO_HOSTS = ("api.xiaomimimo.com",)

# Local inference engines. Loopback/private hosts are intentionally absent: a gateway that
# merely listens on loopback (LiteLLM proxy, one-api, OmniRoute) is not a local engine and
# must keep native tool calling instead of grammar-constrained transport.
_ENGINE_PROVIDERS = (
    "ollama",
    "llama_cpp",
    "llamacpp",
    "llama-cpp",
    "llama-server",
    "vllm",
    "lmstudio",
    "lm-studio",
    "sglang",
    "exo",
    "local",
)
_ENGINE_MODEL_PREFIXES = (
    "ollama/",
    "ollama_chat/",
    "llama/",
    "llama-cpp/",
    "vllm/",
    "lmstudio/",
    "sglang/",
    "exo/",
    "local/",
)
_ENGINE_HOST_KEYWORDS = (
    "llama-server",
    "llama.cpp",
    "llamacpp",
    "ollama",
    "vllm",
    "sglang",
    "lmstudio",
    "lm-studio",
    "exo",
)
# Default serve ports: Ollama, LM Studio, vLLM, llama-server, Exo, SGLang
_ENGINE_PORTS = (11434, 1234, 8000, 8080, 52415, 30000)
# Cloud providers with native tool calling; never downgrade them to grammar transport
# even when the caller points them at a loopback gateway.
_CLOUD_PROVIDERS = (
    "openai",
    "anthropic",
    "google",
    "gemini",
    "vertex",
    "azure",
    "bedrock",
    "mistral",
    "xai",
    "groq",
    "openrouter",
    "deepseek",
    "moonshot",
    "kimi",
    "cohere",
    "together",
    "fireworks",
    "perplexity",
    "zhipu",
    "dashscope",
    "minimax",
)


def _matches_prefix(model: str, prefixes: tuple[str, ...]) -> bool:
    """Check if model matches any of the given prefixes."""
    lower = (model or "").lower()
    return any(lower.startswith(p) or f"/{p}" in lower or f"/{p.rstrip('/')}" in lower for p in prefixes)


def _matches_port(base_url: str, ports: tuple[int, ...]) -> bool:
    """Check whether the URL's *own* port matches one of the given ports.

    The port must be parsed, never substring-matched: a substring test would treat
    any URL merely containing ``:8080`` as a local engine — including ``:80800`` and
    ports hidden in a query string — and downgrade a remote gateway to constrained
    tool-call transport.
    """
    if not base_url:
        return False
    candidate = base_url.strip()
    if "://" not in candidate:
        candidate = f"//{candidate}"
    try:
        port = urlsplit(candidate).port
    except ValueError:
        return False
    return port is not None and port in ports


def _matches_host(base_url: str, hosts: tuple[str, ...]) -> bool:
    """Check if base_url matches any of the given hosts."""
    if not base_url:
        return False
    lower = base_url.lower()
    return any(h in lower for h in hosts)


class ModelCapabilityDetector:
    """Detects model capabilities for reasoning_content handling and local transport."""

    def needs_reasoning_content_echo(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
    ) -> bool:
        """Return True when the model enforces reasoning_content echo-back.

        MiMo, DeepSeek v4 thinking, and Kimi / Moonshot thinking all reject
        replays of assistant tool-call messages that omit reasoning_content.

        Args:
            provider: Provider name (e.g., "deepseek", "kimi-coding")
            model: Model name (e.g., "deepseek-v4-flash", "kimi-k2.5")
            base_url: Base URL for API calls

        Returns:
            True if the model requires reasoning_content echo-back
        """
        return (
            self.is_mimo_model(provider, model, base_url)
            or self.is_deepseek_model(provider, model, base_url)
            or self.is_kimi_model(provider, model, base_url)
        )

    def is_mimo_model(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
    ) -> bool:
        """Return True when the current provider is MiMo.

        MiMo requires reasoning_content on every assistant tool-call message;
        omitting it causes HTTP 400 when the message is replayed.

        Args:
            provider: Provider name
            model: Model name
            base_url: Base URL for API calls

        Returns:
            True if the model is MiMo
        """
        provider_lower = (provider or "").lower()
        model_lower = (model or "").lower()
        return (
            provider_lower in {"xiaomi", "mimo"}
            or _matches_prefix(model, _MIMO_PREFIXES)
            or model_lower.startswith("mimo")
            or _matches_host(base_url, _MIMO_HOSTS)
        )

    def is_deepseek_model(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
    ) -> bool:
        """Return True when the current provider is DeepSeek thinking mode.

        DeepSeek V4 thinking mode requires reasoning_content on every
        assistant tool-call turn; omitting it causes HTTP 400 when the
        message is replayed in a subsequent API request.

        Args:
            provider: Provider name
            model: Model name
            base_url: Base URL for API calls

        Returns:
            True if the model is DeepSeek
        """
        provider_lower = (provider or "").lower()
        model_lower = (model or "").lower()
        return (
            provider_lower == "deepseek"
            or _matches_prefix(model, _DEEPSEEK_PREFIXES)
            or model_lower.startswith("deepseek")
            or _matches_host(base_url, _DEEPSEEK_HOSTS)
        )

    def is_kimi_model(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
    ) -> bool:
        """Return True when the current provider is Kimi / Moonshot thinking mode.

        Kimi /coding and Moonshot thinking mode both require reasoning_content
        on every assistant tool-call message; omitting it causes the next
        replay to fail with HTTP 400.

        Args:
            provider: Provider name
            model: Model name
            base_url: Base URL for API calls

        Returns:
            True if the model is Kimi/Moonshot
        """
        provider_lower = (provider or "").lower()
        model_lower = (model or "").lower()
        return (
            provider_lower in {"kimi-coding", "kimi-coding-cn"}
            or _matches_prefix(model, _KIMI_PREFIXES)
            or model_lower.startswith(("kimi", "moonshot"))
            or _matches_host(base_url, _KIMI_HOSTS)
        )

    def is_local_endpoint(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
    ) -> bool:
        """Return True when provider/model/base_url identifies a local inference engine.

        Engine evidence is required — a loopback or private host alone is NOT enough,
        because OpenAI-compatible gateways (LiteLLM proxy, one-api, OmniRoute) commonly
        listen on loopback while forwarding to remote providers that support native tool
        calling. Detected engines: llama-server, Ollama, vLLM, LM Studio, Exo, SGLang.

        Port evidence is parsed, not substring-matched, so a remote gateway is never
        downgraded merely because its URL happens to contain a local serve port.
        """
        provider_lower = (provider or "").lower()
        if provider_lower in _CLOUD_PROVIDERS:
            return False
        if provider_lower in _ENGINE_PROVIDERS:
            return True
        if _matches_prefix(model, _ENGINE_MODEL_PREFIXES):
            return True
        if not base_url:
            return False
        base_lower = base_url.lower()
        if any(keyword in base_lower for keyword in _ENGINE_HOST_KEYWORDS):
            return True
        return _matches_port(base_url, _ENGINE_PORTS)

    def is_local_weak_endpoint(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
    ) -> bool:
        """Alias for is_local_endpoint for semantic clarity."""
        return self.is_local_endpoint(provider, model, base_url)

    def supports_grammar_constrained_tool_calls(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
    ) -> bool:
        """Return True when model is a weak local model running on a local inference server.

        Local inference servers (llama-server, Ollama, vLLM) benefit from structured
        JSON/Grammar constraints on tool calling to prevent malformed syntax. Proxies on
        loopback are excluded so their native tool calling is preserved.
        """
        return self.is_local_endpoint(provider, model, base_url)

    def supports_json_schema_constrained_tool_calls(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
    ) -> bool:
        """Return True when the model/endpoint benefits from JSON Schema constraint transport.

        Restricted to genuine local inference engines: injecting the transport schema into
        a loopback gateway that fronts remote providers fails strict gateways with HTTP 400
        ("An object with no properties is not allowed") and loses native tool calling.
        """
        return self.is_local_endpoint(provider, model, base_url)
