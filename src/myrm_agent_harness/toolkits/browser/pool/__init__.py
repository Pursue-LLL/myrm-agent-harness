"""Global browser resource pool — zero-copy page reuse, intelligent scheduling, proxy rotation.

[INPUT]
- patchright.async_api::Browser (POS: Patchright browser instance)
- patchright.async_api::BrowserContext (POS: Patchright browser context)
- patchright.async_api::Page (POS: Patchright page instance)

[OUTPUT]
- GlobalBrowserPool: global browser pool with zero-copy page reuse
- PagePool: per-context page object pool
- ContextType: context purpose classification (CRAWL/AGENT/STEALTH)
- BrowserMode: browser runtime mode enum
- EmulationConfig: type-safe browser environment emulation config
- ProxyConfig: proxy server config
- ProxyPool: proxy pool protocol (supports rotation and sticky sessions)
- RoundRobinProxyPool: default round-robin proxy pool implementation
- ExtensionBridge: Protocol for browser extension CDP proxy integration
- ExtensionTab: data class for tabs exposed by extension
- ExtensionStatus: real-time extension connection status
- ExtensionBridgeNotAvailableError: exception when extension is not connected
- get_global_browser_pool: get global browser pool singleton
- reset_global_browser_pool_for_tests: shut down and clear pool singleton (test teardown)

[POS]
Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing zero-copy page reuse,
smart load scheduling, type-based isolation (CRAWL/AGENT/STEALTH), proxy rotation and sticky sessions.
"""

from ..exceptions import BrowserPoolError
from .browser_launcher import BrowserInstance, BrowserLauncher, BrowserLaunchError
from .browser_pool import (
    ContextType,
    GlobalBrowserPool,
)
from .circuit_breaker import CircuitBreaker, CircuitBreakerCallback, CircuitBreakerOpenError, LoggingCallback
from .chrome_prompt_guard import (
    ChromePromptGuard,
    approve_chrome_remote_debugging_prompt,
    is_accessibility_trusted,
    watch_chrome_remote_debugging_prompt,
)
from .config import (
    BrowserConfig,
    BrowserMode,
    BrowserPoolConfig,
    CircuitBreakerConfig,
    HumanizeConfig,
    HumanizeMode,
    LaunchMode,
    MemoryGuardConfig,
    RateLimiterConfig,
    ResourceBlockConfig,
    RobustnessPolicy,
    ThrottleMode,
)
from .context_factory import ContextFactory
from .emulation import EmulationConfig
from .extension_bridge import (
    ExtensionBridge,
    ExtensionBridgeNotAvailable,
    ExtensionBridgeNotAvailableError,
    ExtensionStatus,
    ExtensionTab,
)
from .page_pool import PagePool
from .proxy import ProxyConfig, ProxyPool, RoundRobinProxyPool
from .singleton import get_global_browser_pool, reset_global_browser_pool_for_tests

__all__ = [
    "BrowserConfig",
    "BrowserInstance",
    "BrowserLaunchError",
    "BrowserLauncher",
    "BrowserMode",
    "BrowserPoolConfig",
    "BrowserPoolError",
    "ChromePromptGuard",
    "CircuitBreaker",
    "CircuitBreakerCallback",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "ContextFactory",
    "ContextType",
    "ChromePromptGuard",
    "EmulationConfig",
    "ExtensionBridge",
    "ExtensionBridgeNotAvailable",
    "ExtensionBridgeNotAvailableError",
    "ExtensionStatus",
    "ExtensionTab",
    "GlobalBrowserPool",
    "HumanizeConfig",
    "HumanizeMode",
    "LaunchMode",
    "LoggingCallback",
    "MemoryGuardConfig",
    "PagePool",
    "ProxyConfig",
    "ProxyPool",
    "RateLimiterConfig",
    "ResourceBlockConfig",
    "RobustnessPolicy",
    "RoundRobinProxyPool",
    "ThrottleMode",
    "ChromePromptGuard",
    "approve_chrome_remote_debugging_prompt",
    "get_global_browser_pool",
    "is_accessibility_trusted",
    "reset_global_browser_pool_for_tests",
    "watch_chrome_remote_debugging_prompt",
]
