"""Global provider registry with lazy initialization of built-in providers.

[INPUT]
- (none)

[OUTPUT]
- get_registry: Return the global provider registry, creating it lazily o...

[POS]
Global provider registry with lazy initialization of built-in providers.
"""

from __future__ import annotations

import logging

from .base import ProviderRegistry

logger = logging.getLogger(__name__)

_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """Return the global provider registry, creating it lazily on first access.

    Built-in providers are registered here. Import errors (missing optional
    dependencies) are logged as warnings, not raised.
    """
    global _registry
    if _registry is not None:
        return _registry

    _registry = ProviderRegistry()

    _register_builtin(_registry, "openai_provider", "OpenAISoraProvider")
    _register_builtin(_registry, "google_provider", "GoogleVeoProvider")
    _register_builtin(_registry, "qwen_provider", "QwenVideoProvider")
    _register_builtin(_registry, "minimax_provider", "MiniMaxVideoProvider")

    logger.info("Video provider registry initialized with %d providers", len(_registry))
    return _registry


def _register_builtin(registry: ProviderRegistry, module_name: str, class_name: str) -> None:
    """Import and register a single built-in provider, tolerating import failures."""
    try:
        import importlib

        mod = importlib.import_module(f".{module_name}", package=__package__)
        cls = getattr(mod, class_name)
        registry.register(cls())
    except Exception:
        logger.warning("Failed to register built-in video provider '%s'", class_name, exc_info=True)
