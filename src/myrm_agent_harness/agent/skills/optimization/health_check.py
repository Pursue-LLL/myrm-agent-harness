"""Health Check Protocol

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- typing.Protocol (POS: Python协议类型基类)
- typing.Any (POS: 通用类型)

[OUTPUT]
- HealthCheckProtocol: 健康检查抽象接口
- HealthCheckResult: 健康检查结果类型别名
- AggregatedHealthResult: 聚合健康检查结果模型
- aggregate_health_checks: 聚合多个组件健康检查

[POS]
Health check protocol (framework layer). Unified health check interface for all components.

"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

HealthCheckResult = dict[str, bool | str | int | float | None]


class AggregatedHealthResult(BaseModel):
    healthy: bool
    component: str
    total_components: int
    healthy_components: int
    components: dict[str, HealthCheckResult]

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)


class HealthCheckProtocol(Protocol):
    """健康检查抽象接口

    所有可健康检查的组件都应该实现此接口。

    标准返回字段：
    - healthy: bool - 必需，总体健康状态
    - component: str - 必需，组件名称
    - error: str - 可选，错误信息（仅当healthy=False时）

    其他字段根据组件特性自定义，例如：
    - monitoring_active: bool - 监控任务是否运行中
    - queue_size: int - 队列大小
    - connection_pool: int - 连接池大小
    - response_time_ms: float - 响应时间
    """

    async def health_check(self) -> HealthCheckResult:
        """执行健康检查

        Returns:
            健康检查结果字典，必须包含healthy和component字段

        Examples:
            >>> # 健康状态
            >>> {
            ...     "healthy": True,
            ...     "component": "optimization_scheduler",
            ...     "monitoring_active": True,
            ...     "queue_size": 3
            ... }
            >>>
            >>> # 异常状态
            >>> {
            ...     "healthy": False,
            ...     "component": "optimization_scheduler",
            ...     "error": "Queue worker not running"
            ... }
        """
        ...


async def aggregate_health_checks(
    components: dict[str, HealthCheckProtocol], strict: bool = True
) -> AggregatedHealthResult:
    """聚合多个组件的健康检查

    将多个组件的健康检查聚合为整体健康状态。

    Args:
        components: 组件名称到HealthCheckProtocol实现的映射
        strict: 严格模式（True：任一组件不健康则整体不健康；False：容忍部分失败）

    Returns:
        聚合后的健康检查结果

    Examples:
        >>> scheduler = OptimizationScheduler(...)
        >>> storage = InMemoryStorage(...)
        >>>
        >>> result = await aggregate_health_checks({
        ...     "scheduler": scheduler,
        ...     "storage": storage
        ... })
        >>>
        >>> # 结果示例
        >>> {
        ...     "healthy": True,
        ...     "component": "skill_optimization",
        ...     "components": {
        ...         "scheduler": {"healthy": True, "component": "optimization_scheduler"},
        ...         "storage": {"healthy": True, "storage_type": "in_memory"}
        ...     }
        ... }
    """
    results: dict[str, HealthCheckResult] = {}
    all_healthy = True

    for name, component in components.items():
        try:
            result = await component.health_check()
            results[name] = result

            if not result.get("healthy", False):
                all_healthy = False

        except Exception as e:
            results[name] = {
                "healthy": False,
                "component": name,
                "error": f"Health check failed: {e}",
            }
            all_healthy = False

    if strict:
        overall_healthy = all_healthy
    else:
        healthy_count = sum(1 for r in results.values() if r.get("healthy", False))
        overall_healthy = healthy_count > 0

    return AggregatedHealthResult(
        healthy=overall_healthy,
        component="aggregated",
        total_components=len(components),
        healthy_components=sum(1 for r in results.values() if r.get("healthy", False)),
        components=results,
    )


def validate_health_check_result(result: HealthCheckResult) -> bool:
    """验证健康检查结果是否符合规范

    Args:
        result: 健康检查结果

    Returns:
        是否符合规范

    Examples:
        >>> valid_result = {"healthy": True, "component": "scheduler"}
        >>> validate_health_check_result(valid_result)
        True
        >>>
        >>> invalid_result = {"component": "scheduler"}  # 缺少healthy字段
        >>> validate_health_check_result(invalid_result)
        False
    """
    if not isinstance(result, dict):
        return False

    if "healthy" not in result:
        return False

    if not isinstance(result["healthy"], bool):
        return False

    if "component" not in result:
        return False

    if not isinstance(result["component"], str):
        return False

    return not (not result["healthy"] and "error" not in result)
