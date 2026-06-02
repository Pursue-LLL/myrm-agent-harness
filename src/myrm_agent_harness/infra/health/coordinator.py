"""Health check coordinator.

[INPUT]
- health_checker::HealthChecker (POS: 健康检查抽象基类)
- health_checker::HealthCheckResult (POS: 健康检查结果)
- health_checker::RecoveryResult (POS: 恢复操作结果)

[OUTPUT]
- run_health_checks: Run all registered health checkers sequentially

[POS]
健康检查协调器。串行执行所有注册的checker，如果检查失败则尝试恢复。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.infra.health.health_checker import HealthStatus, RecoveryStatus

if TYPE_CHECKING:
    from myrm_agent_harness.infra.health.health_checker import (
        HealthChecker,
        HealthCheckResult,
        RecoveryResult,
    )

logger = logging.getLogger(__name__)


async def run_health_checks(
    checkers: list[HealthChecker],
    auto_recover: bool = True,
    max_retries: int = 1,
) -> tuple[bool, list[tuple[str, HealthCheckResult, RecoveryResult | None]]]:
    """Run all registered health checkers sequentially.

    Args:
        checkers: List of health checkers to run
        auto_recover: Whether to automatically attempt recovery on failure
        max_retries: Maximum number of recovery retries (default: 1)

    Returns:
        Tuple of (all_healthy: bool, results: list of (name, check_result, recovery_result))

    Raises:
        None - all exceptions are caught and logged
    """
    if not checkers:
        logger.info("[Health] No health checkers registered, skipping checks")
        return True, []

    logger.info(f"[Health] Running {len(checkers)} health checker(s)...")
    results: list[tuple[str, HealthCheckResult, RecoveryResult | None]] = []
    all_healthy = True

    for checker in checkers:
        name = checker.get_name()
        check_result: HealthCheckResult | None = None
        recovery_result: RecoveryResult | None = None

        try:
            # Run health check
            check_result = await checker.check()

            if check_result.is_healthy():
                logger.info(f" {name}: {check_result.message}")
            elif check_result.status == HealthStatus.DEGRADED:
                logger.warning(f" {name}: {check_result.message}")
                all_healthy = False
            else:
                logger.warning(f" {name}: {check_result.message}")
                all_healthy = False

                # Attempt recovery if enabled
                if auto_recover:
                    logger.info(f" → Attempting recovery for {name}...")

                    for attempt in range(max_retries + 1):
                        try:
                            recovery_result = await checker.recover()

                            if recovery_result.is_success():
                                logger.info(
                                    f" {name}: Recovery successful - {recovery_result.message}"
                                )
                                if recovery_result.actions_taken:
                                    for action in recovery_result.actions_taken:
                                        logger.info(f" • {action}")

                                # Re-check after recovery
                                check_result = await checker.check()
                                if check_result.is_healthy():
                                    logger.info(f" {name}: Re-check passed")
                                    all_healthy = True
                                else:
                                    logger.warning(
                                        f" {name}: Re-check failed - {check_result.message}"
                                    )
                                break
                            elif recovery_result.status == RecoveryStatus.PARTIAL:
                                logger.warning(
                                    f" {name}: Partial recovery - {recovery_result.message}"
                                )
                                if attempt < max_retries:
                                    logger.info(
                                        f" → Retrying recovery (attempt {attempt + 2}/{max_retries + 1})..."
                                    )
                                break
                            else:
                                logger.error(
                                    f" {name}: Recovery failed - {recovery_result.message}"
                                )
                                if attempt < max_retries:
                                    logger.info(
                                        f" → Retrying recovery (attempt {attempt + 2}/{max_retries + 1})..."
                                    )
                                else:
                                    break

                        except Exception as recovery_err:
                            logger.error(
                                f" {name}: Recovery error - {recovery_err}",
                                exc_info=True,
                            )
                            if attempt >= max_retries:
                                break

        except Exception as err:
            logger.error(f" {name}: Check failed with exception - {err}", exc_info=True)
            all_healthy = False

        results.append((name, check_result, recovery_result))

    if all_healthy:
        logger.info(" All components healthy, service startup can proceed")
    else:
        logger.warning(
            " Some components unhealthy, check logs above for recovery actions"
        )

    return all_healthy, results
