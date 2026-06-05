"""Wait strategy implementations — internal module.


[INPUT]
- _wait_types::WaitStrategy, WaitMetrics, ReasonType, _HybridTaskResult (POS: type definitions)
- _dom_stable_js::generate_dom_stable_js (POS: JS generator)
- patchright.async_api::Page (POS: Patchright page instance)

[OUTPUT]
- wait_networkidle_only: network idle detection only
- wait_dom_stable_only: DOM stability detection only
- wait_smart: adaptive detection
- wait_hybrid: hybrid detection

[POS]
Concrete wait strategy implementations. Each strategy function receives a Page instance and parameters, returns WaitMetrics.
Dispatched by wait_for_page_ready in wait_strategies.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

from ._dom_stable_js import generate_dom_stable_js
from ._wait_types import ReasonType, WaitMetrics, WaitStrategy, _HybridTaskResult

if TYPE_CHECKING:
    from patchright.async_api import Page

    from myrm_agent_harness.toolkits.web_fetch.router.domain_metrics import (
        DomainMetricsManager,
    )

logger = logging.getLogger(__name__)


def _elapsed_ms_since(start_time: float) -> int:
    """Compute from start_time to 现 in  毫秒数."""
    return int((time.perf_counter() - start_time) * 1000)


async def wait_networkidle_only(page: Page, max_ms: int, start_time: float) -> WaitMetrics:
    """Only网络Empty闲检测."""
    try:
        await page.wait_for_load_state("networkidle", timeout=max_ms)
        elapsed_ms = _elapsed_ms_since(start_time)
        logger.debug(f"Wait: networkidle after {elapsed_ms}ms")
        return WaitMetrics(
            strategy=WaitStrategy.NETWORKIDLE,
            reason="network_only",
            elapsed_ms=elapsed_ms,
            network_idle_ms=elapsed_ms,
        )
    except (TimeoutError, RuntimeError, OSError):
        elapsed_ms = _elapsed_ms_since(start_time)
        logger.debug(f"Wait: networkidle timeout or error after {elapsed_ms}ms")
        return WaitMetrics(
            strategy=WaitStrategy.NETWORKIDLE,
            reason="capped",
            elapsed_ms=elapsed_ms,
        )


async def wait_dom_stable_only(page: Page, max_ms: int, quiet_ms: int, start_time: float) -> WaitMetrics:
    """OnlyDOMstable性检测."""
    result = await page.evaluate(generate_dom_stable_js(max_ms, quiet_ms))

    elapsed_ms = _elapsed_ms_since(start_time)

    if isinstance(result, dict):
        reason_map: dict[str, ReasonType] = {
            "quiet": "quiet",
            "capped": "capped",
            "nobody": "capped",
        }
        reason = reason_map.get(result.get("reason", "capped"), "capped")

        return WaitMetrics(
            strategy=WaitStrategy.DOM_STABLE,
            reason=reason,
            elapsed_ms=elapsed_ms,
            dom_stable_ms=result.get("elapsed_ms", elapsed_ms),
            dom_mutation_count=result.get("mutation_count", 0),
            dom_reset_count=result.get("reset_count", 0),
            shadow_dom_count=result.get("shadow_count", 0),
        )
    else:
        return WaitMetrics(
            strategy=WaitStrategy.DOM_STABLE,
            reason="capped",
            elapsed_ms=elapsed_ms,
        )


async def wait_spa_stable(page: Page, max_ms: int, start_time: float) -> WaitMetrics:
    """SPA 稳态检测."""
    js_wait = """() => new Promise((resolve) => {
        if (!window.__myrm_spa_state) {
            // Not a supported environment or script not injected yet
            resolve({ reason: "unsupported", elapsed_ms: 0 });
            return;
        }
        if (window.__myrm_spa_state.stable) {
            resolve({ reason: "spa_stable", elapsed_ms: 0 });
            return;
        }
        window.__myrm_spa_stable_resolve = () => resolve({ reason: "spa_stable", elapsed_ms: 0 });
    })"""

    try:
        await page.evaluate(js_wait, timeout=max_ms)
        elapsed_ms = _elapsed_ms_since(start_time)
        logger.debug(f"Wait: SPA stable after {elapsed_ms}ms")
        return WaitMetrics(
            strategy=WaitStrategy.SPA_STABLE,
            reason="both",
            elapsed_ms=elapsed_ms,
            dom_stable_ms=elapsed_ms,
            network_idle_ms=elapsed_ms,
        )
    except (TimeoutError, RuntimeError, OSError):
        elapsed_ms = _elapsed_ms_since(start_time)
        logger.debug(f"Wait: SPA stable timeout or error after {elapsed_ms}ms")
        return WaitMetrics(
            strategy=WaitStrategy.SPA_STABLE,
            reason="capped",
            elapsed_ms=elapsed_ms,
        )


async def wait_smart(
    page: Page,
    max_ms: int,
    quiet_ms: int,
    grace_period_ms: int,
    start_time: float,
    domain: str | None = None,
    domain_metrics_manager: DomainMetricsManager | None = None,
) -> WaitMetrics:
    """自适应检测（fast优先，准确性保障）.

    Strategy:
    1. fast尝试：networkidle 检测（DynamicTimeout）
    2. Success → 立i.e.Return
    3. Timeout →  using  hybrid（剩余时间）

    fastPathTimeout调整：
    -  has 历史Data： using  P95 延迟 × 1.2（上限 max_ms）
    - networkidle Success率 < 50%：SkipfastPath
    -  no 历史Data：max_ms × 0.3（上限 500ms）
    """
    fast_timeout_ms = min(int(max_ms * 0.3), 500)
    skip_fast_path = False

    if domain and domain_metrics_manager:
        try:
            metrics_data = domain_metrics_manager.get(domain)
            if metrics_data:
                learned_timeout = metrics_data.get_smart_fast_timeout()
                if learned_timeout is None:
                    skip_fast_path = True
                    logger.debug(
                        f"Wait: SMART strategy - skipping networkidle fast path for {domain} (low success rate)"
                    )
                elif learned_timeout > 0:
                    fast_timeout_ms = min(learned_timeout, max_ms)
                    logger.debug(f"Wait: SMART strategy - using learned fast_timeout={fast_timeout_ms}ms for {domain}")
        except Exception as e:
            logger.warning(f"Failed to get learned timeout for {domain}: {e}")

    if skip_fast_path:
        logger.debug(f"Wait: SMART strategy - directly using hybrid for {domain}")
        hybrid_metrics = await wait_hybrid(page, max_ms, quiet_ms, grace_period_ms, start_time)
        return WaitMetrics(
            strategy=WaitStrategy.SMART,
            reason=hybrid_metrics.reason,
            elapsed_ms=hybrid_metrics.elapsed_ms,
            network_idle_ms=hybrid_metrics.network_idle_ms,
            dom_stable_ms=hybrid_metrics.dom_stable_ms,
            dom_mutation_count=hybrid_metrics.dom_mutation_count,
            dom_reset_count=hybrid_metrics.dom_reset_count,
            shadow_dom_count=hybrid_metrics.shadow_dom_count,
        )

    try:
        # SPA_STABLE is now the primary fast path in SMART mode
        hybrid_metrics = await wait_spa_stable(page, fast_timeout_ms, start_time)
        if hybrid_metrics.reason != "capped":
            elapsed_ms = _elapsed_ms_since(start_time)
            logger.debug(f"Wait: SMART strategy - SPA stable succeeded in {elapsed_ms}ms")
            return WaitMetrics(
                strategy=WaitStrategy.SMART,
                reason="both",
                elapsed_ms=elapsed_ms,
                network_idle_ms=elapsed_ms,
                dom_stable_ms=elapsed_ms,
            )

        await page.wait_for_load_state("networkidle", timeout=fast_timeout_ms)
        elapsed_ms = _elapsed_ms_since(start_time)
        logger.debug(f"Wait: SMART strategy - networkidle succeeded in {elapsed_ms}ms")

        return WaitMetrics(
            strategy=WaitStrategy.SMART,
            reason="network_only",
            elapsed_ms=elapsed_ms,
            network_idle_ms=elapsed_ms,
        )

    except TimeoutError:
        elapsed_fast = _elapsed_ms_since(start_time)
        remaining_ms = max(0, max_ms - elapsed_fast)

        if remaining_ms < 100:
            return WaitMetrics(
                strategy=WaitStrategy.SMART,
                reason="capped",
                elapsed_ms=elapsed_fast,
            )

        logger.debug(
            f"Wait: SMART strategy - networkidle timeout after {elapsed_fast}ms, "
            f"switching to hybrid (remaining={remaining_ms}ms)"
        )

        hybrid_metrics = await wait_hybrid(page, remaining_ms, quiet_ms, grace_period_ms, start_time)
        return WaitMetrics(
            strategy=WaitStrategy.SMART,
            reason=hybrid_metrics.reason,
            elapsed_ms=hybrid_metrics.elapsed_ms,
            network_idle_ms=hybrid_metrics.network_idle_ms,
            dom_stable_ms=hybrid_metrics.dom_stable_ms,
            dom_mutation_count=hybrid_metrics.dom_mutation_count,
            dom_reset_count=hybrid_metrics.dom_reset_count,
            shadow_dom_count=hybrid_metrics.shadow_dom_count,
        )


def _handle_first_completed(
    dom_task: asyncio.Task[object],
    network_task: asyncio.Task[None],
    done: set[asyncio.Task[object]],
    first_elapsed_ms: int,
) -> _HybridTaskResult:
    """Process第一个Complete 任务."""
    result = _HybridTaskResult()

    if dom_task in done:
        try:
            task_result = dom_task.result()
            if isinstance(task_result, dict):
                result.dom_result = task_result
                result.dom_elapsed_ms = first_elapsed_ms
        except (TimeoutError, RuntimeError) as e:
            logger.warning(f"Wait: DOM detection failed: {e}")

    if network_task in done:
        try:
            network_task.result()
            result.network_elapsed_ms = first_elapsed_ms
        except (TimeoutError, RuntimeError) as e:
            logger.warning(f"Wait: Network idle detection failed: {e}")

    return result


async def _apply_grace_period(
    result: _HybridTaskResult,
    dom_task: asyncio.Task[object],
    network_task: asyncio.Task[None],
    pending: set[asyncio.Task[object]],
    grace_ms: int,
    start_time: float,
) -> _HybridTaskResult:
    """应用grace periodWait第二个任务."""
    if not pending:
        result.reason = "both"
        return result

    remaining_task = pending.pop()

    if grace_ms <= 0:
        remaining_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await remaining_task
        return result

    try:
        await asyncio.wait_for(remaining_task, timeout=grace_ms / 1000)

        second_elapsed_ms = _elapsed_ms_since(start_time)

        if remaining_task is dom_task:
            task_result = dom_task.result()
            if isinstance(task_result, dict):
                result.dom_result = task_result
                result.dom_elapsed_ms = second_elapsed_ms
        else:
            network_task.result()
            result.network_elapsed_ms = second_elapsed_ms

        result.reason = "both"

    except TimeoutError:
        remaining_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await remaining_task
    except (RuntimeError, OSError) as e:
        logger.warning(f"Wait: Second task failed during grace period: {e}")
        remaining_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await remaining_task

    return result


async def _cleanup_hybrid_tasks(
    dom_task: asyncio.Task[object],
    network_task: asyncio.Task[None],
) -> None:
    """Clean up混合检测任务."""
    dom_task.cancel()
    network_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.gather(dom_task, network_task, return_exceptions=True)


def _build_hybrid_metrics(
    result: _HybridTaskResult,
    start_time: float,
) -> WaitMetrics:
    """Build混合检测metrics."""
    elapsed_ms = _elapsed_ms_since(start_time)

    mutation_count = 0
    reset_count = 0
    shadow_count = 0
    if result.dom_result:
        mutation_count = int(result.dom_result.get("mutation_count", 0))
        reset_count = int(result.dom_result.get("reset_count", 0))
        shadow_count = int(result.dom_result.get("shadow_count", 0))

    return WaitMetrics(
        strategy=WaitStrategy.HYBRID,
        reason=result.reason,
        elapsed_ms=elapsed_ms,
        network_idle_ms=result.network_elapsed_ms,
        dom_stable_ms=result.dom_elapsed_ms,
        dom_mutation_count=mutation_count,
        dom_reset_count=reset_count,
        shadow_dom_count=shadow_count,
    )


async def wait_hybrid(page: Page, max_ms: int, quiet_ms: int, grace_period_ms: int, start_time: float) -> WaitMetrics:
    """混合检测（先 to 先得+grace periodValidate）.

    Strategy:
    1. parallelExecuteDOM检测 and 网络检测
    2. Wait任一Complete（FIRST_COMPLETED）
    3. 给第二个任务grace period
    4. Grace period内Complete → reason="both"
    5. Otherwise立i.e.Return → reason="first_completed"
    """
    dom_task = asyncio.create_task(page.evaluate(generate_dom_stable_js(max_ms, quiet_ms)))
    network_task = asyncio.create_task(page.wait_for_load_state("networkidle", timeout=max_ms))

    try:
        done, pending = await asyncio.wait([dom_task, network_task], return_when=asyncio.FIRST_COMPLETED)

        first_elapsed_ms = _elapsed_ms_since(start_time)
        result = _handle_first_completed(dom_task, network_task, done, first_elapsed_ms)

        remaining_ms = max(0, max_ms - first_elapsed_ms)
        grace_ms = min(grace_period_ms, remaining_ms)

        result = await _apply_grace_period(result, dom_task, network_task, pending, grace_ms, start_time)

    except TimeoutError:
        await _cleanup_hybrid_tasks(dom_task, network_task)
        result = _HybridTaskResult(reason="capped")
    except (RuntimeError, OSError) as e:
        logger.warning(f"Wait: hybrid detection error: {e}")
        await _cleanup_hybrid_tasks(dom_task, network_task)
        result = _HybridTaskResult(reason="capped")

    return _build_hybrid_metrics(result, start_time)
