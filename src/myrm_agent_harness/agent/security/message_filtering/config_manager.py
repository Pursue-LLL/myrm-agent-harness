"""ConfigManager for hot-reloading message filter configurations.

Design principle:
- Framework layer (this file): Protocol + Memory implementation
- Business layer: Database-backed implementation

[INPUT]
- (none)

[OUTPUT]
- ConfigManager: Protocol for configuration managers.
- MemoryConfigManager: In-memory configuration manager with observer pattern.

[POS]
ConfigManager for hot-reloading message filter configurations.
"""

import logging
from collections.abc import Callable
from typing import Protocol

from .base import FilterConfig

logger = logging.getLogger(__name__)

ConfigObserver = Callable[[FilterConfig], None]


class ConfigManager(Protocol):
    """Protocol for configuration managers.

    Implementations can load configs from various sources (memory, DB, file).
    """

    def get_config(self) -> FilterConfig:
        """Get current configuration."""
        ...

    def reload(self) -> None:
        """Reload configuration from source."""
        ...

    def subscribe(self, observer: ConfigObserver) -> None:
        """Subscribe to configuration changes."""
        ...


class MemoryConfigManager:
    """In-memory configuration manager with observer pattern.

    Usage:
        >>> manager = MemoryConfigManager(FilterConfig(enabled=True))
        >>> manager.subscribe(lambda cfg: print(f"Config updated: {cfg}"))
        >>> manager.update_config(FilterConfig(enabled=False))  # Triggers observer
    """

    def __init__(self, initial_config: FilterConfig):
        self._config = initial_config
        self._observers: list[ConfigObserver] = []

    def get_config(self) -> FilterConfig:
        """Get current configuration."""
        return self._config

    def reload(self) -> None:
        """No-op for memory manager (config is already in memory)."""
        pass

    def subscribe(self, observer: ConfigObserver) -> None:
        """Subscribe to configuration changes.

        Args:
            observer: Callback function invoked when config changes
        """
        self._observers.append(observer)

    def update_config(self, new_config: FilterConfig) -> None:
        """Update configuration and notify observers.

        Args:
            new_config: New configuration to apply
        """
        old_config = self._config
        self._config = new_config
        logger.info(f"Config updated: {old_config} -> {new_config}")
        self._notify_observers()

    def _notify_observers(self) -> None:
        """Notify all observers of configuration change."""
        for observer in self._observers:
            try:
                observer(self._config)
            except Exception as e:
                logger.error(f"Observer callback failed: {e}", exc_info=True)
