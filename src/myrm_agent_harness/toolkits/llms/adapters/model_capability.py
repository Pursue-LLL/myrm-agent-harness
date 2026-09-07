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

# Loopback / local / constrained inference hosts
_LOCAL_GRAMMAR_HOSTS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "llama-server",
    "ollama",
    "vllm",
    "sglang",
)
_LOCAL_GRAMMAR_PROVIDERS = (
    "ollama",
    "llama_cpp",
    "llamacpp",
    "vllm",
    "local",
    "sglang",
)
_LOCAL_WEAK_HOSTS = (
    "127.0.0.1",
    "localhost",
    "0.0.0.0",
    "::1",
    "llama-server",
    "ollama",
    "vllm",
    "sglang",
)
_LOCAL_WEAK_PREFIXES = (
    "ollama/",
    "vllm/",
    "local/",
    "llama/",
    "lmstudio/",
)

# Local / Edge endpoint hosts and providers
_LOCAL_HOST_SUBSTRINGS = (
    "127.0.0.1",
    "localhost",
    "0.0.0.0",
    ":8000",
    ":8080",
    ":11434",  # Ollama default port
    ":8088",
    ":5000",
)
_LOCAL_PROVIDERS = ("ollama", "local", "vllm", "llama-server", "llamacpp", "sglang")
_LOCAL_MODEL_PREFIXES = ("ollama/", "ollama_chat/", "local/")


def _matches_prefix(model: str, prefixes: tuple[str, ...]) -> bool:
    """Check if model matches any of the given prefixes."""
    lower = (model or "").lower()
    return any(lower.startswith(p) or f"/{p}" in lower or f"/{p.rstrip('/')}" in lower for p in prefixes)


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
        """Return True when the provider, model prefix or base_url points to a local or loopback inference engine.

        Detects llama-server, Ollama, vLLM, LM Studio, Exo, and other local loopback hosts.
        """
        provider_lower = (provider or "").lower()
        model_lower = (model or "").lower()
        local_keywords = (
            "ollama",
            "local",
            "llama",
            "llama-cpp",
            "llama_cpp",
            "vllm",
            "lmstudio",
            "exo",
            "sglang",
        )
        if provider_lower in local_keywords:
            return True
        if any(
            model_lower.startswith(f"{kw}/") or model_lower.startswith(f"{kw}:")
            for kw in local_keywords
        ):
            return True
        if not base_url:
            return False
        base_lower = base_url.lower()
        local_hosts = (
            "127.0.0.1",
            "localhost",
            "0.0.0.0",
            "::1",
            ":8000",
            ":8080",
            ":11434",
            ":1234",
            ":52415",
            ":9333",
            "llama-server",
            "host.docker.internal",
        )
        return any(h in base_lower for h in local_hosts)

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
        JSON/Grammar constraints on tool calling to prevent malformed syntax.
        """
        return self.is_local_endpoint(provider, model, base_url)

    def supports_json_schema_constrained_tool_calls(
        self,
        provider: str = "",
        model: str = "",
        base_url: str = "",
    ) -> bool:
        """Return True when the model/endpoint benefits from JSON Schema grammar constraint transport."""
        return self.is_local_endpoint(provider, model, base_url)
