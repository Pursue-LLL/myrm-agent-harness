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
- get_global_browser_pool: get global browser pool singleton

[POS]
Global browser resource pool. Manages Browser/Context/Page three-layer resources, implementing zero-copy page reuse,
smart load scheduling, type-based isolation (CRAWL/AGENT/STEALTH), proxy rotation and sticky sessions.
"""

from ..exceptions import BrowserNetworkError, BrowserPoolError, BrowserTimeoutError
from .browser_launcher import BrowserInstance, BrowserLauncher, BrowserLaunchError
from .browser_pool import (
    ContextType,
    GlobalBrowserPool,
)
from .circuit_breaker import CircuitBreaker, CircuitBreakerCallback, CircuitBreakerOpenError, LoggingCallback
from .config import (
    BrowserConfig,
    BrowserMode,
    BrowserPoolConfig,
    CircuitBreakerConfig,
    LaunchMode,
    MemoryGuardConfig,
    RateLimiterConfig,
    ResourceBlockConfig,
    RobustnessPolicy,
    ThrottleMode,
)
from .context_factory import ContextFactory
from .emulation import EmulationConfig
from .page_pool import PagePool
from .proxy import ProxyConfig, ProxyPool, RoundRobinProxyPool
from .singleton import get_global_browser_pool

__all__ = [
    "BrowserConfig",
    "BrowserInstance",
    "BrowserLaunchError",
    "BrowserLauncher",
    "BrowserMode",
    "BrowserNetworkError",
    "BrowserPoolConfig",
    "BrowserPoolError",
    "BrowserTimeoutError",
    "CircuitBreaker",
    "CircuitBreakerCallback",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "ContextFactory",
    "ContextType",
    "EmulationConfig",
    "GlobalBrowserPool",
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
    "get_global_browser_pool",
]
