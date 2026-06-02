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


def _matches_prefix(model: str, prefixes: tuple[str, ...]) -> bool:
    """Check if model matches any of the given prefixes."""
    lower = (model or "").lower()
    return any(lower.startswith(p) or f"/{p}" in lower for p in prefixes)


def _matches_host(base_url: str, hosts: tuple[str, ...]) -> bool:
    """Check if base_url matches any of the given hosts."""
    if not base_url:
        return False
    lower = base_url.lower()
    return any(h in lower for h in hosts)


class ModelCapabilityDetector:
    """Detects model capabilities for reasoning_content handling.

    This detector identifies models that require special reasoning_content
    handling, such as complete echo-back or placeholder filling.

    Usage:
        detector = ModelCapabilityDetector()
        if detector.needs_reasoning_content_echo(provider, model, base_url):
            # Handle reasoning_content specially
    """

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
        return (
            provider_lower in {"xiaomi", "mimo"}
            or _matches_prefix(model, _MIMO_PREFIXES)
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
        return (
            provider_lower == "deepseek"
            or _matches_prefix(model, _DEEPSEEK_PREFIXES)
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
        return (
            provider_lower in {"kimi-coding", "kimi-coding-cn"}
            or _matches_prefix(model, _KIMI_PREFIXES)
            or _matches_host(base_url, _KIMI_HOSTS)
        )
