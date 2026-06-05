"""Page wait strategies — hybrid detection for optimal page ready detection.


[INPUT]
- _wait_types (POS: type definitions and statistics)
- _wait_impl (POS: strategy implementations)
- patchright.async_api::Page (POS: Patchright page instance)
- time::perf_counter (POS: high-precision timer)
- logging::getLogger (POS: Python logging)

[OUTPUT]
- WaitStrategy: wait strategy enum (4 types: smart/hybrid/dom_stable/networkidle)
- WaitMetrics: wait metrics (full observability)
- WaitStrategyStats: runtime statistics class (thread-safe)
- wait_for_page_ready: page readiness detection entry point (default SMART strategy, auto-records stats)
- get_wait_strategy_stats: retrieve global statistics
- reset_wait_strategy_stats: reset statistics (for testing)

[POS]
Page wait strategy module. Provides 4 wait strategies:
1. SMART adaptive: tries networkidle first (fast), falls back to hybrid (accurate) on timeout
2. HYBRID: DOM stability + network idle dual detection (first-to-complete + grace period)
3. DOM_STABLE: MutationObserver monitors DOM changes (including Shadow DOM)
4. NETWORKIDLE: Playwright native network idle detection

Features:
- Smart filtering: excludes animation attributes (style/class/aria-*) to reduce false positives
- Shadow DOM support: recursively observes all shadowRoots
- JavaScript caching: @lru_cache avoids redundant generation
- Full metrics: elapsed_ms, dom_stable_ms, network_idle_ms, shadow_dom_count
- Runtime statistics: global stats class records strategy usage and hit rates (thread-safe)
- Parameter validation: max_ms/quiet_ms/grace_period_ms legality checks
- Resource cleanup: complete cleanup after Task cancellation to avoid ResourceWarning

Module structure:
- _wait_types.py: type definitions (WaitStrategy/WaitMetrics/WaitStrategyStats) and runtime stats
- _wait_impl.py: 4 strategy implementations (networkidle/dom_stable/smart/hybrid)
- _dom_stable_js.py: DOM stability detection JavaScript generator
- wait_strategies.py: public interface (this file)
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from ._wait_impl import (
    wait_dom_stable_only,
    wait_hybrid,
    wait_networkidle_only,
    wait_smart,
    wait_spa_stable,
)
from ._wait_types import (
    WaitMetrics,
    WaitStrategy,
    WaitStrategyStats,
    _global_stats,
    get_wait_strategy_stats,
    reset_wait_strategy_stats,
)

if TYPE_CHECKING:
    from patchright.async_api import Page

    from myrm_agent_harness.toolkits.web_fetch.router.domain_metrics import (
        DomainMetricsManager,
    )

logger = logging.getLogger(__name__)


def _record_to_domain_metrics(metrics: WaitMetrics, domain: str, domain_metrics_manager: DomainMetricsManager) -> None:
    """RecordWaitMetrics to  DomainMetrics."""

    try:
        domain_metrics = domain_metrics_manager.get_or_create(domain)

        if metrics.strategy == WaitStrategy.NETWORKIDLE or metrics.reason == "network_only":
            domain_metrics.record_wait_strategy("networkidle", metrics.elapsed_ms)
            domain_metrics.record_networkidle_result(success=metrics.reason == "network_only")

        elif metrics.strategy in (WaitStrategy.HYBRID, WaitStrategy.SMART):
            if metrics.network_idle_ms is not None:
                domain_metrics.record_networkidle_result(success=True)
            elif metrics.reason != "network_only":
                domain_metrics.record_networkidle_result(success=False)

            if metrics.dom_stable_ms is not None:
                domain_metrics.record_wait_strategy("dom_stable", metrics.dom_stable_ms)

        elif metrics.strategy in (WaitStrategy.DOM_STABLE, WaitStrategy.SPA_STABLE):
            domain_metrics.record_wait_strategy("dom_stable", metrics.elapsed_ms)

    except Exception as e:
        logger.warning(f"Failed to record wait metrics for {domain}: {e}")


async def wait_for_page_ready(
    page: Page,
    *,
    strategy: WaitStrategy = WaitStrategy.SMART,
    max_ms: int = 5000,
    quiet_ms: int = 500,
    grace_period_ms: int = 200,
    domain: str | None = None,
    domain_metrics_manager: DomainMetricsManager | None = None,
) -> WaitMetrics:
    """WaitPage准备就绪.

    Args:
        page: Patchright PageInstance
        strategy: WaitStrategy（DefaultSMART最优，自适应fast+准确）
        max_ms: MaximumWait时长（硬Timeout， must >0）
        quiet_ms: 静默期时长（ no 变化时视 is stable， must >=0）
        grace_period_ms: 混合Strategy in ，第一个任务Complete后给第二个任务 额外Wait时间（ must >=0）
        domain: Domain（ for Domain级学习，SMART Strategyoptimized）
        domain_metrics_manager: DomainMetricsManager Instance（ for 读取历史Data）

    Returns:
        WaitMetrics: completeWaitMetrics

    Raises:
        ValueError: Parameter not 合法（负数、零Value etc.）

    Examples:
        # 自适应检测（最优性能+准确性平衡）
        metrics = await wait_for_page_ready(page, strategy=WaitStrategy.SMART)
        logger.info(f"Page ready: {metrics.reason}, elapsed={metrics.elapsed_ms}ms")

        # Domain级optimized（基于历史Data）
        metrics = await wait_for_page_ready(
            page,
            strategy=WaitStrategy.SMART,
            domain="example.com",
            domain_metrics_manager=manager
        )

        # 混合检测（准确性优先）
        metrics = await wait_for_page_ready(page, strategy=WaitStrategy.HYBRID)

        # OnlyDOM检测（fastMode）
        metrics = await wait_for_page_ready(
            page,
            strategy=WaitStrategy.DOM_STABLE,
            max_ms=3000
        )
    """
    if max_ms <= 0:
        raise ValueError(f"max_ms must be positive, got {max_ms}")
    if quiet_ms < 0:
        raise ValueError(f"quiet_ms must be non-negative, got {quiet_ms}")
    if grace_period_ms < 0:
        raise ValueError(f"grace_period_ms must be non-negative, got {grace_period_ms}")

    if quiet_ms > max_ms:
        logger.warning(f"quiet_ms ({quiet_ms}ms) exceeds max_ms ({max_ms}ms), adjusting to {max_ms}ms")
        quiet_ms = max_ms

    start_time = time.perf_counter()

    if strategy == WaitStrategy.NETWORKIDLE:
        metrics = await wait_networkidle_only(page, max_ms, start_time)
    elif strategy == WaitStrategy.DOM_STABLE:
        metrics = await wait_dom_stable_only(page, max_ms, quiet_ms, start_time)
    elif strategy == WaitStrategy.SPA_STABLE:
        metrics = await wait_spa_stable(page, max_ms, start_time)
    elif strategy == WaitStrategy.SMART:
        metrics = await wait_smart(
            page,
            max_ms,
            quiet_ms,
            grace_period_ms,
            start_time,
            domain,
            domain_metrics_manager,
        )
    else:  # HYBRID
        metrics = await wait_hybrid(page, max_ms, quiet_ms, grace_period_ms, start_time)

    _global_stats.record_call(metrics.strategy, metrics.reason, metrics.elapsed_ms)

    if domain and domain_metrics_manager:
        _record_to_domain_metrics(metrics, domain, domain_metrics_manager)

    return metrics


__all__ = [
    "WaitMetrics",
    "WaitStrategy",
    "WaitStrategyStats",
    "get_wait_strategy_stats",
    "reset_wait_strategy_stats",
    "wait_for_page_ready",
]
